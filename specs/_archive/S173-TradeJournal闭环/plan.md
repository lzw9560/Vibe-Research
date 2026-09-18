# Plan: S173 — Trade Journal 闭环（技术方案）

> spec → plan（SDD §0 不跳）。本文档：怎么做——orchestrator 架构 + MTM 分轨 + 统计方法论层 + drawdown topology + 各模块接口。
> 关联 spec：`./spec.md`。下游：`./tasks.md`（可执行 checklist）。

## 1. 模块拓扑

```
journal_recorder.run_daily()  ← orchestrator（C1 顺序管线，非订阅）
  │
  ├─ floor 臂：import index_replication_floor.build_position_batches() → ETF batches
  │    → 构造 Trades → Executor.execute(T1OpenFill) → entry fill
  │    → MTM 分轨（C3/C6）：exit_reason='hold'，不调 path_return
  │    → trade_journal.insert(is_realized=0, unrealized_pnl=按 close 重算)
  │
  ├─ breakout 臂：import premarket_selection.select_premarket_candidates() → candidates
  │    → 构造 Trades → Executor.execute(T1OpenFill) → entry fill
  │    → 可平仓臂：accounting.path_return(apply_cost=True) → PathReturn
  │    → net_pnl = return_pct/100 × position_notional (CNY)
  │    → trade_journal.insert(is_realized=1)
  │
  ├─ limitup/trend 臂：mock signal generator → 同 breakout 流程
  │
  └─ gap 臂（falsified dead_arm）：accounting.gap_net_return() → (net_ratio, cost_pct, gross_ratio)
       → net_pnl = net_ratio × position_notional (CNY)
       → trade_journal.insert(is_realized=1, is_dead_arm=1)

drawdown_breaker.DrawdownBreaker
  ← 读 trade_journal 聚合 equity 曲线（realized + unrealized MTM）
  ← 绝对 CNY 回撤（C4，遵循 risk_rules.equity_curve 模式）
  ← floor 豁免 per-arm DD（C5），仅参与 portfolio aggregate DD
  ← underpowered gate（H4：days<60 → multiplier=1.0 status='underpowered'）
  ← 熊市 regime（H6：CSI300<200 日线 → floor 豁免）
  → 输出 size_multiplier（与 lift_multiplier 复合相乘，H5 三层乘积）

trade_journal.TradeJournal
  ← SQLite ledger（.vibe-research/trade_journal.db，vr_paths.data_dir()）
  ← CRUD：insert / update_unrealized / query_by_arm
  ← 聚合统计：aggregate_by_arm() → per-arm winrate/Sharpe/净超额/coverage_rate
  ← 统计方法论层：day_clustered_t_test / compute_dsr / bonferroni_bh / CI / underpowered gate
```

## 2. 模块接口设计

### 2.1 trade_journal.py（ledger + 聚合 + 统计方法论）

**职责**：SQLite CRUD + 跨臂聚合 query + 统计方法论封装（复用 s44_verifier，不重发明）。

**关键函数签名**：

```python
class TradeJournal:
    def __init__(self, db_path: Path | None = None): ...
    # db_path 默认 vr_paths.resolve_data_dir() / "trade_journal.db"

    def insert(self, record: JournalRecord) -> str:
        """插入一条闭环交易记录。返 signal_id。幂等（INSERT OR REPLACE）。"""

    def update_unrealized(self, signal_id: str, unrealized_pnl: float, current_price: float): ...

    def query_records(self, arm: str | None = None, is_realized: bool | None = None,
                      is_dead_arm: bool = False, limit: int = 5000) -> list[JournalRecord]: ...

    def aggregate_by_arm(self, arm: str | None = None) -> dict:
        """跨臂聚合统计。SQLite query 不读结果 cache（memory s088 重算范式）。
        返 per-arm: net_winrate (Wilson CI) / Sharpe (日聚合+DSR+MinTRL) /
        净超额 (day_clustered_t_test+CI) / 盈亏比 / 总 net_pnl /
        signal_coverage_rate / execution_winrate。is_dead_arm=1 不混入。
        n<30 或 days<60 → status='underpowered' 不出 kill。"""

    def equity_curve(self, arm: str | None = None) -> list[dict]:
        """equity 曲线 = initial_capital + cumulative_net_pnl (realized + unrealized MTM)。
        遵循 risk_rules.equity_curve 绝对 CNY 回撤模式。"""

@dataclass(frozen=True)
class JournalRecord:
    signal_id: str        # UUID
    arm: str              # 'floor'|'breakout'|'limitup'|'trend'|'gap'
    stock_code: str
    entry_price: float | None
    entry_date: str
    exit_price: float | None
    exit_date: str | None
    exit_reason: str | None   # 'stop'|'take'|'max_hold'|'signal'|'manual'|'hold'|'unbuyable'
    net_pnl: float | None     # CNY (H3)
    pnl_unit: str = "CNY"
    cost_pct: float = 0.0
    gross_return: float | None = None
    is_realized: int = 0
    unrealized_pnl: float | None = None
    is_dead_arm: int = 0
    fills_json: str = ""
    created_at: str = ""
```

**统计方法论层**（复用 s44_verifier，不重发明）：

```python
def _wilson_ci(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """胜率 Wilson score interval（lower, upper）。"""

def _daily_aggregate_sharpe(net_pnls: list[float], exit_dates: list[str]) -> dict:
    """H2 Sharpe 年化修正：先按 exit_date 日聚合 net_pnl → daily PnL 序列 →
    Sharpe = mean/std × sqrt(252)。返 {sharpe, n_days, daily_mean, daily_std}。"""

def _compute_arm_stats(records: list[JournalRecord]) -> dict:
    """单臂统计封装：调 day_clustered_t_test + compute_dsr + bonferroni_bh +
    wilson_ci + daily_aggregate_sharpe + coverage_rate。
    underpowered gate：n_picks<30 或 n_days<60 → status='underpowered'。"""
```

### 2.2 journal_recorder.py（orchestrator）

**职责**：C1 顺序管线 orchestrator——调各臂 signal 生成器 → Trades 构造 → Executor.execute → accounting 算 return → 写 trade_journal。

**关键函数签名**：

```python
class JournalRecorder:
    def __init__(self, journal: TradeJournal | None = None,
                 executor: Executor | None = None): ...

    def run_daily(self, target_date: str | None = None,
                  arms: list[str] | None = None) -> dict:
        """每日盘后闭环管线（orchestrator 顺序调用，非订阅）。
        arms 默认 ['floor','breakout']；limitup/trend/gap mock。
        返 {arm: {n_candidates, n_buyable, n_unbuyable, n_realized}}。"""

    def _process_floor(self, target_date: str) -> dict:
        """floor 臂（C3/C6 MTM 分轨）：
        1. build_position_batches() → ETF batches
        2. 构造 Trades(code=ETF, signal_date, fill_type=t1_open, direction=long, size)
        3. Executor.execute(T1OpenFill) → entry fill
        4. exit_reason='hold'（不主动平仓）
        5. unrealized_pnl = (current_close - entry_price) × shares（每日 MTM 更新）
        6. trade_journal.insert(is_realized=0)"""

    def _process_breakout(self, target_date: str) -> dict:
        """breakout 臂（可平仓臂）：
        1. select_premarket_candidates(target_date) → candidates
        2. 构造 Trades(code, signal_date, fill_type=t1_open, direction=long, size=100)
        3. Executor.execute(T1OpenFill) → entry fill
        4. 涨停买不到 → survivorship 过滤 → exit_reason='unbuyable'
        5. accounting.path_return(trades_filled, bars, stop, take, max_hold, apply_cost=True)
           → PathReturn(return_pct, exit_reason, exit_date, cost_pct, gross_return_pct)
        6. net_pnl = return_pct/100 × position_notional (CNY)
        7. trade_journal.insert(is_realized=1)"""

    def _process_gap(self, target_date: str) -> dict:
        """gap 臂（falsified dead_arm，保留录数据）：
        1. mock signal (entry/exit price + date)
        2. accounting.gap_net_return(entry, exit, entry_date, size) → (net_ratio, cost_pct, gross_ratio)
        3. net_pnl = net_ratio × position_notional (CNY)
        4. trade_journal.insert(is_realized=1, is_dead_arm=1)"""

    def update_floor_mtm(self, target_date: str) -> int:
        """每日盘后更新 floor 臂 unrealized_pnl（C6）。
        按 ETF close 重算 unrealized_pnl = (current_close - entry_price) × shares。"""
```

**C8 Trades 不加字段**：signal_id (UUID) + arm 由 journal_recorder 录入 trade_journal 时赋值。Trades dataclass 不改。

**H9 batch 模式**：executor 只做 entry fill（executor.py:35-62 证实），exit 走 batch：call path_return → 一次性取完整 PathReturn → 写 journal。不等 executor exit events。

### 2.3 drawdown_breaker.py（风控 sizing 熔断）

**职责**：equity 曲线追踪 + size_multiplier 输出 + underpowered gate + 熊市 regime。

**关键函数签名**：

```python
class DrawdownBreaker:
    def __init__(self, journal: TradeJournal | None = None,
                 initial_capital: float = 100000.0): ...

    def compute_drawdown(self, arm: str | None = None) -> DrawdownResult:
        """计算回撤（C4 绝对 CNY，遵循 risk_rules.equity_curve 模式）。
        equity = initial_capital + cumulative_realized_pnl + sum(unrealized_pnl)
        drawdown_cny = peak_cny - current_cny
        drawdown_pct = drawdown_cny / initial_capital"""

    def size_multiplier(self, arm: str | None = None) -> tuple[float, str]:
        """输出 size_multiplier + status。
        - per-arm DD（floor 豁免 C5）：DD_pct>10%→0.5, >15%→0.0
        - portfolio aggregate DD：统一缩放所有臂（floor 含但阈值高/熊市豁免）
        - underpowered gate（H4）：days_tracked<60→multiplier=1.0 status='underpowered'
        - 熊市 regime（H6）：CSI300<200日线→floor 豁免
        返 (multiplier, status)。"""

    def final_size(self, arm: str, arm_size: float,
                   lift_multiplier: float = 1.0) -> float:
        """H5 三层乘积：final_size = arm_size × portfolio_multiplier × lift_multiplier。"""

@dataclass(frozen=True)
class DrawdownResult:
    equity: float
    peak: float
    drawdown_cny: float
    drawdown_pct: float
    size_multiplier: float
    status: str   # 'enforced'|'underpowered'|'disabled'
    days_tracked: int
    is_bear_market: bool
```

## 3. 关键设计决策

### 3.1 MTM 分轨（C3/C6）

floor 臂不走 path_return（需 stop/take/max_hold，floor 无 stop/take 不主动平）。改走 mark-to-market：
- entry commission only（~0.05% 单边）
- 每日盘后按 ETF close 重算 unrealized_pnl = (current_close - entry_price) × shares - entry_cost
- is_realized=0，equity 曲线含 unrealized MTM

### 3.2 统计方法论层（H1/H2）

| 指标 | 方法 | 函数 |
|---|---|---|
| 净超额 vs 基准 | day-clustered t-test（防同日膨胀 n） | `s44_verifier.stats.day_clustered_t_test(returns, dates)` |
| 4 臂多重检验 | Bonferroni-BH（K cap 8） | `s44_verifier.stats.bonferroni_bh(p_values, n=K)` |
| Sharpe | 日聚合 + DSR + MinTRL | `s44_verifier.wiring.compute_dsr(returns, n_trials=4)` |
| Sharpe haircut | 多重检验 haircut | `s44_verifier.wiring.compute_haircut(returns, n_obs, n_tests)` |
| 胜率 CI | Wilson score interval | `_wilson_ci(wins, total)` |
| underpowered gate | n<30 或 days<60 | status='underpowered' 不出 kill |

### 3.3 drawdown topology（C4/C5/H4/H5/H6）

- (a) per-arm DD → 仅该臂 size_multiplier 缩放（floor 豁免 C5）
- (b) portfolio aggregate DD → portfolio-level breaker 统一缩放所有臂
- (c) final_size = arm_size_multiplier × portfolio_size_multiplier × lift_multiplier（三层乘积 H5）
- 熊市 regime（H6）：CSI300<200 日线 → floor 豁免 drawdown enforce

### 3.4 H3 单位统一

pnl_unit 固定 CNY：
- 可平仓臂：net_pnl = return_pct/100 × position_notional
- paper 臂：net_pnl = virtual_capital × return_pct/100
- floor 臂：net_pnl = ETF NAV 变动 × shares
- gap 臂：net_pnl = net_ratio × position_notional

### 3.5 H7 gap-aware fill

accounting.path_return 当前 stop/take 逻辑有乐观偏差（gap-through 未建模）。不改 accounting.py 接口（只读约束），在 fills_json 记录 optimism_flag + raw exit_price，文档化偏差量级。

### 3.6 C7 winrate.db 隔离

闭环臂不经 settlement_recorder，journal_recorder 唯一写入 trade_journal 表。winrate.db legacy 只读（手动成交经 settlement_recorder 仍写 winrate.db，两库独立）。

## 4. 前端接口

### 4.1 新增后端端点（routers/journal.py 小改）

```
GET /api/journal/closed-loop        → 闭环 ledger 记录 + 聚合统计
GET /api/journal/drawdown-status    → drawdown 熔断状态
```

### 4.2 前端 JournalLedger.tsx（新建）

挂在现有 Journal.tsx 页内（新增 section/tab），显：
- 持仓列表（is_realized=0 的 floor 持仓 + unrealized MTM）
- 实时盈亏（net_pnl + gross_return + cost_pct 分列）
- 归因视图（per-arm winrate/Sharpe/coverage_rate）
- error boundary：挂载失败只隐藏该 section 不影响现有

## 5. 不改的模块（只读）

- accounting.py（path_return/gap_net_return/_cost_pct 只读复用）
- executor.py / fill_policies.py（T1OpenFill 只读复用 entry fill）
- decision.py（Trades 不加 signal_id/arm，C8）
- risk_rules.py（equity_curve 只读参考绝对回撤模式）
- win_rate_tracker.py（接口不改，winrate.db legacy 只读）
- settlement_recorder.py（不改，服务 journal.py 手动成交）
- journal.py（S166 手动账本不改，独立关切）

## 6. 测试策略

- test_trade_journal：mock executor + accounting，验 CRUD + is_dead_arm 不混聚合 + 迁移幂等
- test_drawdown_breaker：mock equity 曲线，验 DD 阈值 + floor 豁免 + underpowered + 熊市
- test_journal_recorder：mock 各臂 signal 生成器，验 4 臂全录到 + survivorship + Trades 不带 signal_id
- test_aggregate_stats：验 day_clustered_t_test + bonferroni_bh + compute_dsr + CI + underpowered gate
- 全量 pytest -m "not live" --deselect 3 flaky（newsradar/s032/s040）
