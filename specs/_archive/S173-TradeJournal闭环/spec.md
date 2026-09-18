# Spec: S173 — Trade Journal 闭环（跨臂胜率全链路）

> 状态：已实现（2026-09-09，fa25be8+84a5c2d，4 模块 trade_journal+journal_recorder+drawdown_breaker+ledger 55 测；grill 8 CRITICAL+9 HIGH 全修）
> 作者：lzw9560  日期：2026-09-08
> 关联：S166-TradeJournal+RiskLedger（journal.py 手动账本，本 spec 不重复造）/ S162-反前视引擎三层（accounting.py + executor + fill_policies）/ S172-红利低波指数复制臂（A 臂 floor）/ S159-§44应用规约v2（lift_to_multiplier 待接线）/ S171-长线价值
> 分级：large —— 跨 4 臂统一闭环 + drawdown 熔断 + 前端归因，feature 分支 + grill + 验收

## 1. 问题 / 目标

north-star 三问（买什么/何时买/何时卖）的 3 缺口之一：**胜率没闭环**。当前 4 臂孤立——A 臂（长线 ETF floor）/ 打板 paper / 趋势 paper / gap drop（已 falsified）——各自出信号，但 signal→entry→exit→net PnL 全链路没人串，导致 kill 规则与 EWMA 进化没有诚实数据可吃。

一句话：跨 4 臂统一胜率闭环，每 signal→entry→exit→net PnL，诚实含成本/滑点/涨停买不到/T+1，给 kill + EWMA 供数据。

> **成本口径分轨**（grill C2 修正）：`backend/engine/accounting.py` 提供两种净收益算式：
> - `path_return(trades, bars, stop, take, max_hold, apply_cost=True)`（:91）——需 bars + stop/take/max_hold 的路径模拟，用于打板/趋势等**可平仓臂**。
> - `gap_net_return(entry_price, exit_price, entry_date, size)`（:184）——纯 2 价事件（买 T 收盘卖 T+1 开盘），无 stop/take/max_hold，用于 gap **隔夜事件臂**。返回 `(net_return_ratio, cost_pct, gross_return_ratio)`。
>
> gap 臂已 falsified（§44 证 gap edge 是成本假象），但 journal 接 accounting 真成本是为了**不再重复 gap 的成本幻觉错误**。两条路径都走 accounting 统一成本模型（`_cost_pct`），杜绝成本口径分裂。

## 2. 背景

### 2.1 现状（grep + codegraph 实测，非凭记忆）

| 模块 | 位置 | 是什么 | 与本 spec 关系 |
|---|---|---|---|
| 手动账本 | `backend/journal.py`（S166）| trades.json + fees.json，CRUD + fills 结算（`_fee_of`/`realized_pnl`/`gross_pnl`/`fees`/`realized_pct`），threading.Lock 防静默丢单 | **用户真实成交**账本。本 spec **不重复造**——闭环账本是模拟/纸面臂的自动录，与手动真实成交是不同关切，分离不合并 |
| 胜率结算层 | `backend/win_rate_tracker.py` | WinRateRecord（entry/exit/return_pct/is_win + 5 列信号归因），22 调用方 | **结算层**——录已完成的交易。本 spec 闭环臂**不经 settlement_recorder**（grill C7），journal_recorder 是唯一写入者，winrate.db legacy 只读 |
| 成本会计 | `backend/engine/accounting.py`（S162）| `path_return`（:91）+ `gap_net_return`（:184）+ `_cost_pct`（:67）+ `ROUND_TRIP_COST_PCT`（0.70%）+ `STAMP_DUTY_PCT`（0.05%，2023-08-28 减半）+ `COMMISSION_MIN_YUAN`（5 元）+ survivorship（unbuyable 过滤）+ T+1 guard | **复用**——可平仓臂 net PnL 走 `path_return(apply_cost=True)`，gap 臂走 `gap_net_return`，floor 臂走 mark-to-market（§5.3），不发明新算式 |
| 反前视引擎 | `backend/engine/executor.py`（:35 `execute`）+ `fill_policies.py`（S162）| FillPolicy 协议 + `fill()` + `execute()`，OHLC 撮合。**executor 只做 entry fill，无 exit fill**（:35-62 只返 entry_price + fill_status） | **复用**——纸面臂的 entry fill 走 executor。exit 不走 executor（H9），走 batch 模式：call path_return → 取 PathReturn(exit_reason/exit_date) → 写 journal |
| Trades dataclass | `backend/engine/decision.py`（:33）| immutable dataclass：code/signal_date/fill_type/direction/size/entry_price/exit_date/exit_price/fill_status/fill_reason。**无 signal_id/arm 字段** | **不改**（C8）——signal_id + arm 由 journal_recorder 录入时赋值（生成 UUID + 已知调用哪臂），trade_journal 表是 source of truth |
| IP 熔断器 | `backend/circuit_breaker.py` | `CircuitBreaker`/`get_breaker("eastmoney")`，防 em_get/sina 封 IP | **与 drawdown 熔断无关**——本 spec 的 drawdown CB 是风控 sizing 熔断，新建不复用 |
| 风控账本 | `backend/risk_rules.py`（:103 `equity_curve`）/`at_risk.py`/`excursion.py`（S166）| 风险宪法 + 在险资金 + gap-down excursion。`equity_curve` 用**绝对 CNY 回撤**（peak-cum，:130-133），非百分比 | drawdown CB 遵循 `equity_curve` 绝对回撤模式（C4），不重发明百分比公式 |
| 胜率 Sharpe | `backend/win_rate_tracker.py`（:192）| per-trade Sharpe = mean/std，**无年化**（不乘 sqrt252） | **不复用**其 Sharpe 算式——本 spec 修正年化方法（H2：先日聚合再 Sharpe） |
| 结算记录器 | `backend/settlement_recorder.py`（:53 `return_pct`）| `return_pct = ((exit-exit)/entry)*100`——**毛收益**（无成本），写 winrate.db | **闭环臂不经此路径**（C7）——settlement_recorder 服务手动成交（journal.py 流转），闭环臂走 journal_recorder + accounting path_return(apply_cost=True) |
| §44 统计 | `backend/s44_verifier/stats.py`（:139 `day_clustered_t_test` / :300 `permutation_p_value` / :324 `bonferroni_bh`）+ `wiring.py`（:57 `compute_dsr` / :156 `compute_haircut`）| day-clustered t-test / permutation null / Bonferroni-BH / DSR+MinTRL / haircut | **复用**——R3 跨臂聚合统计走这些函数（H1），不裸点估计 |
| 前端 Journal | `frontend/src/pages/Journal.tsx` + `components/journal/`（TradeJournalSection/DiagnosticsSection/JournalSettings/RiskReportSection）| S166 复活的 Journal 页 | **扩展**不并行——本 spec 在现有 Journal 页加闭环 ledger 视图 |

### 2.2 为什么现在做

- §44 verdict（S168/S159）：选股层无 validated edge，edge 在盘中未测——但无论 edge 在哪，**胜率闭环是测量基建**，任何线路都需要 signal→PnL 诚实数据。design-agnostic。
- 多策略工具箱（memory `multi-strategy-toolbox-evolution`）：4 臂 + EWMA 进化 + kill 规则需要胜率数据驱动。gap 已 falsified 证明：不看真成本（accounting）的胜率是幻觉。闭环必须接 accounting 真成本。
- portfolio overlay（#3/#4）框架需要 per-arm 胜率/Sharpe/drawdown 数据驱动 sizing 调整 + kill。

### 2.3 gap 教训（不重复）

gap 臂 §44 falsified 的根因：gap edge 是**成本假象**——毛收益 +1.30% 看起来是 edge，但扣 accounting 真成本（round-trip 0.70% + 印花 + 滑点 + T+1 不可卖 + 涨停买不到）后 net < 随机基准。`gap_net_return`（accounting.py:184）已经内含 `_cost_pct` 扣减——gap 闭环走它即可，毛收益（gross_return）与净收益（net_pnl）分列，杜绝成本幻觉重演。

## 3. 需求清单

- [ ] R1 **trade_journal 表**：SQLite 表（queryable 供聚合/drawdown），字段 `signal_id`(UUID) / `arm`(tag) / `stock_code` / `entry_price` / `entry_date` / `exit_price` / `exit_date` / `exit_reason` / `net_pnl` / `pnl_unit`(CNY) / `cost_pct` / `gross_return` / `is_realized`(bool) / `unrealized_pnl` / `fills_json`(成交明细) / `created_at`。迁移幂等（v1 完整 CREATE + `__init__` 接线，见 memory `migration-stubs-fresh-db-fix`）。
  - `pnl_unit` 固定 `CNY`（H3 统一单位）：可平仓臂 net_pnl = path_return.return_pct × position_notional；paper 臂按 `virtual_capital × return_pct` 折算 CNY；floor 臂 net_pnl = ETF NAV 变动 × shares。
  - `unrealized_pnl`（C6）：is_realized=0 的持仓，每日盘后按 close 重算浮盈/浮亏（CNY），equity 曲线含 realized + unrealized。
  - `exit_reason` enum：`'stop'` | `'take'` | `'max_hold'` | `'signal'` | `'manual'` | `'hold'`（C3：floor 不主动平仓标 'hold'）| `'unbuyable'`（涨停买不到）。
- [ ] R2 **每日盘后生命周期**（C1 orchestrator + H9 batch 模式）：journal_recorder 作为 **orchestrator**，显式顺序管线调用（非订阅/事件驱动）：
  1. 调各臂 signal 生成器取候选 → 生成 signal_id (UUID) + 标 arm tag
  2. 构造 Trades → 调 `Executor.execute(trades, bars, T1OpenFill())` 做 entry fill
  3. 涨停买不到走 survivorship 过滤 → 标 entry_price=NULL + exit_reason='unbuyable'
  4. **可平仓臂**：调 `accounting.path_return(trades_filled, bars, stop, take, max_hold, apply_cost=True)` → 取 PathReturn(exit_reason/exit_date/return_pct/cost_pct/gross_return_pct) → net_pnl = return_pct × position_notional → 写 trade_journal
  5. **gap 臂**：调 `accounting.gap_net_return(entry, exit, entry_date, size)` → 取 (net_ratio, cost_pct, gross_ratio) → 写 trade_journal
  6. **floor 臂**：不走 path_return（C3/C6），走 mark-to-market（§5.3）
  - N 由 arm 配置（打板 T+1 / 趋势 5-20d / 长线 floor hold 不平）
  - **executor 只做 entry fill 无 exit fill**（executor.py:35-62 证实），故 exit 走 batch：path_return 一次性返回完整 PathReturn（含 exit_reason/exit_date），journal_recorder 不等 executor exit 事件。
- [ ] R3 **跨臂聚合 + 统计方法论**（H1 + H8）：
  - per-arm 净胜率（Wilson CI）/ 净超额 vs 基准 / 盈亏比 / 总 net_pnl
  - **净超额**走 `s44_verifier.stats.day_clustered_t_test(returns, dates)`（:139）——day-clustered 防同日 picks 膨胀 n，返 t_stat + p_one_sided + n_days
  - **4 臂多重检验**走 `s44_verifier.stats.bonferroni_bh(p_values, n=K, method)`（:324），K cap 8（§44v2）
  - **Sharpe**走 `s44_verifier.wiring.compute_dsr(returns, n_trials=4)`（:57）出 Deflated Sharpe + MinTRL（H2）
  - **每点估计配 CI**：胜率 Wilson interval / Sharpe bootstrap CI / 净超额 day-clustered t-test CI
  - **survivorship coverage**（H8）：R3 报 3 指标并列——`signal_coverage_rate` = buyable / (buyable + unbuyable) + `execution_winrate` = wins / (wins + losses) among buyable + unbuyable 单独可见。kill 吃 execution_winrate，coverage 并列可见不进 kill 分母。
  - 聚合走 SQLite query 不读结果 cache（memory `s088-recompute-paradigm`）
  - **不足 n 标 underpowered 不出 kill**（H1）：n_days < 2 或 n_picks < 30 → 标 "exploratory/underpowered"，只报数不出 kill verdict
- [ ] R4 **drawdown 熔断接线 + underpowered gate**（C4 + C5 + H4 + H5 + H6）：
  - equity 曲线 = initial_capital + cumulative_net_pnl（realized + unrealized MTM），遵循 `risk_rules.equity_curve()`（:103）**绝对 CNY 回撤**模式：drawdown = peak_cny - current_cny（C4：不用零基百分比 (peak-current)/peak，那会 20x 膨胀）
  - drawdown 阈值相对 initial_capital：DD/initial_capital > 10% → sizing ×0.5；> 15% → 全停（×0）
  - **drawdown topology**（H5）：(a) per-arm DD → 仅该臂 size_multiplier 缩放；(b) portfolio aggregate DD → portfolio-level breaker 统一缩放所有臂；(c) `final_size = arm_size_multiplier × portfolio_size_multiplier × lift_multiplier` 三层乘积
  - **floor 臂豁免 per-arm DD**（C5：ETF 历史 -13.6% > 10% 会误杀；floor 是 buy+hold 长线，per-arm MTM 波动不是策略失效信号）——floor 仅参与 portfolio aggregate DD，不参与 per-arm DD
  - **underpowered gate**（H4）：`drawdown_status` = 'enforced' | 'underpowered' | 'disabled' + `days_tracked`。days_tracked < 60 → multiplier=1.0 status='underpowered'（不生效，参考 §44v2 days_robust<60 逻辑）。Sharpe/胜率/净超额同款 gate（n<30 或 days<60 → exploratory 只报数不 kill）。floor Sharpe 不适用标 N/A_hold，改报 tracking_error + 浮盈。
  - **熊市 regime**（H6）：加熊市检测（CSI300 < 200 日均线 或 市场 DD > 15%）。熊市时 floor 豁免 drawdown enforce（或阈值 >25%），CB 只作用非 floor 臂。或相对回撤（arm_DD - 市场_DD）。
  - 熔断器输出 `size_multiplier`，与 `lift_to_multiplier`（S159 待接线）**复合相乘**（lift 管 signal 信任，drawdown 管组合风控，两者正交）
- [ ] R5 **每臂 entry/exit 接线（orchestrator 模式）**（C1 + C8）：
  - journal_recorder 作为 **orchordinator** 显式调用各臂 signal 生成器（非订阅），顺序管线：signal 生成 → Trades 构造 → Executor.execute → accounting 算 return → 写 trade_journal
  - arm tag schema 前向兼容（当前 concretely 在 code 的臂：`floor`(S172, `index_replication_floor.build_position_batches`) / `breakout`(premarket_selection, `select_premarket_candidates` 或 `select_premarket_with_risk`) / `limitup`(打板 paper) / `trend`(趋势 paper) / `gap`(falsified，保留录数据但标 dead_arm)；未实现的臂用 string tag，不硬编码 enum 强制全部存在）
  - **Trades 不加 signal_id/arm 字段**（C8）：signal_id (UUID) + arm 由 journal_recorder 录入 trade_journal 时赋值（journal_recorder 知道调了哪臂），不灌 Trades dataclass。trade_journal 表是 source of truth。
- [ ] R6 **诚实标注**：每条 journal 记录标 `is_realized`（已平仓真盈亏）vs `unrealized`（持仓浮动 + 每日 MTM 重算）；gap/dead_arm 记录标 `is_dead_arm` flag 不参与聚合胜率但保留录（可复盘为何 falsified）。
- [ ] R7 **不破坏现有**：journal.py（S166 手动账本）/ win_rate_tracker / accounting / executor / decision.Trades 全不改动接口，只读不复用内部。pytest -m "not live" 全绿。
- [ ] R8 **私有数据隔离**：trade_journal 表存 `.vibe-research/`（`vr_paths.data_dir()`），绝不进 git。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/trade_journal.py` | **新建**。闭环 ledger（SQLite CRUD + 生命周期方法 + 跨臂聚合 query + drawdown equity 曲线）。**不复刻 journal.py 的手动 CRUD**——本模块是自动录（orchestrator 批量调用），journal.py 是手动真实成交，分离不合并 |
| `backend/strategies/journal_recorder.py` | **新建**。**orchestrator**（非订阅器）——显式顺序管线调用各臂 signal 生成器 → 构造 Trades → Executor.execute → accounting 算 return → 写 trade_journal。调用点：`floor` 臂在 `index_replication_floor.build_position_batches`(:65) 之后；`breakout` 臂在 `premarket_selection.select_premarket_candidates`(:119) 或 `select_premarket_with_risk`(:214) 之后。**这些调用点是新增非复用**——现有 signal 生成器不自带 journal 写入，journal_recorder 在其返回后接管。 |
| `backend/engine/drawdown_breaker.py` | **新建**。drawdown 熔断器（equity 曲线追踪 + size_multiplier 输出 + underpowered gate + 熊市 regime）。**不复刻** circuit_breaker.py（那是 IP 封阻断，不同关切）。遵循 `risk_rules.equity_curve()` 绝对 CNY 回撤模式（C4）。|
| `backend/engine/accounting.py` | **不改**（只读 `path_return`/`gap_net_return`/`_cost_pct`，复用算 net PnL）|
| `backend/engine/executor.py` / `fill_policies.py` | **不改**（只读 entry fill，复用撮合。exit 不走 executor——H9 batch 模式走 path_return 一次性取 PathReturn）|
| `backend/engine/decision.py`（Trades）| **不改**（C8：signal_id/arm 不灌 Trades，由 journal_recorder 录入 trade_journal 时赋值）|
| `backend/win_rate_tracker.py` | **不改接口**——C7 决策：闭环臂不经 `settlement_recorder.record_settlement`（:143），**不经** win_rate_tracker.add_record。journal_recorder 是闭环臂唯一写入者，写 trade_journal 表。winrate.db legacy 只读（手动成交经 settlement_recorder 仍写 winrate.db，两个库独立）。**删"如需同步后续 plan 决定"punt**——明确二选一选 a：闭环臂 journal_recorder 唯一写入，winrate.db legacy 只读。|
| `backend/settlement_recorder.py` | **不改**——仍服务 journal.py 手动成交流转（S034），写 winrate.db。闭环臂不经此路径。两库独立：trade_journal（模拟/纸面闭环）+ winrate.db（手动真实成交）。|
| `backend/journal.py`（S166）| **不改**（手动真实成交账本，独立关切）|
| `backend/risk_rules.py` | **不改**（只读 `equity_curve` 绝对回撤模式参考，drawdown_breaker 遵循但不调它）|
| `backend/vr_paths.py` | **不改**（复用 `data_dir()` 指 `.vibe-research/`）|
| `frontend/src/components/journal/JournalLedger.tsx` | **新建**。持仓 + 实时盈亏（unrealized MTM） + 归因视图，**挂在现有 Journal.tsx 页内**（新增 section，不建并行页）|
| `frontend/src/pages/Journal.tsx` | **小改**。挂 JournalLedger section |
| `frontend/src/lib/query/journal.ts` | **小改**。加闭环 ledger query（复用现有 contract 模式）|
| `backend/routers/journal.py` | **小改**。加闭环 ledger 端点（GET /api/journal/closed-loop + /drawdown-status），不覆盖现有 16 端点 |

> **受影响文件说明**：任务原述「新建 trade_journal.py + journal_recorder.py + JournalLedger.tsx」——经核实 journal.py(S166)/Journal.tsx(S166) 已存在，本 spec 改为**新建闭环专用模块 + 扩展现有前端页**，不并行造账本/页。drawdown_breaker 单独建（circuit_breaker.py 是 IP 熔断不可复用）。accounting/executor/decision.Trades/win_rate_tracker 只读不改接口。
>
> **C7 决策**（winrate.db 双写矛盾）：选 **方案 a**——闭环臂不经 settlement_recorder，journal_recorder 唯一写入 trade_journal 表，winrate.db legacy 只读。理由：settlement_recorder（settlement_recorder.py:53 `return_pct` 是毛收益无成本）服务 journal.py 手动成交流转（S034），口径是用户自填价格；闭环臂走 accounting path_return(apply_cost=True) 净口径。两库口径不同混录会污染统计。分离比改 settlement_recorder 调 path_return 更干净（后者改 settlement_recorder 会波及其 22 个调用方契约，爆炸半径大）。

## 5. 设计方案

### 5.1 闭环账本 vs 手动账本（分离不合并）

| | journal.py（S166，已存在）| trade_journal.py（本 spec，新建）|
|---|---|---|
| 数据源 | 用户手动录入真实成交 | journal_recorder orchestrator 批量调各臂 signal 生成器 → executor → accounting |
| 存储 | trades.json（文件，原子写）| SQLite 表（queryable 供聚合）|
| 成本 | `_fee_of`（用户费率配置）| `accounting._cost_pct`（S162 成本模型，统一口径）|
| 净收益口径 | 用户自填价格算 realized_pnl | accounting path_return/gap_net_return(apply_cost=True) 净口径 |
| 用途 | 个人真实持仓/已实现盈亏 | 纸面/模拟臂胜率闭环 + kill/EWMA 反馈 |
| 关系 | 独立，不合并 | 读 accounting + executor，不读 journal.py |

**分离理由**：真实成交（用户实际买入价/费率/滑点）与模拟成交（executor 撮合 + accounting 成本模型）是**不同数据源**——混录会让胜率统计口径污染。分开后真实成交走 journal.py → settlement_recorder → winrate.db，模拟闭环走 trade_journal.py，各自口径干净。

### 5.2 trade_journal 表 schema

```sql
CREATE TABLE IF NOT EXISTS trade_journal (
  signal_id       TEXT PRIMARY KEY,        -- UUID，跨臂唯一（journal_recorder 生成，C8）
  arm             TEXT NOT NULL,           -- 'floor'|'breakout'|'limitup'|'trend'|'gap'
  stock_code      TEXT NOT NULL,
  entry_price     REAL,
  entry_date      TEXT NOT NULL,
  exit_price      REAL,
  exit_date       TEXT,
  exit_reason     TEXT,                    -- 'stop'|'take'|'max_hold'|'signal'|'manual'|'hold'|'unbuyable'
  net_pnl         REAL,                    -- CNY（H3 统一），走 accounting.path_return/gap_net_return(apply_cost=True) 折算
  pnl_unit        TEXT DEFAULT 'CNY',     -- 固定 CNY（H3）：paper 臂 virtual_capital×return_pct 折算
  cost_pct        REAL,                    -- accounting._cost_pct 算出的 round-trip 成本%
  gross_return    REAL,                    -- 毛收益%（不扣成本），与 net_pnl 分列防成本幻觉
  is_realized     INTEGER DEFAULT 0,       -- 0=unrealized持仓 1=已平仓
  unrealized_pnl  REAL,                    -- C6：is_realized=0 时每日盘后按 close 重算浮盈（CNY）
  is_dead_arm     INTEGER DEFAULT 0,       -- gap 等 falsified 臂标 1，不参与聚合胜率但保留
  fills_json      TEXT,                    -- 成交明细 JSON（executor fill 输出）
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tj_arm ON trade_journal(arm);
CREATE INDEX IF NOT EXISTS idx_tj_entry_date ON trade_journal(entry_date);
```

- **H3 单位统一**：`pnl_unit` 固定 `CNY`。可平仓臂 net_pnl = `PathReturn.return_pct / 100 × position_notional`（position_notional = entry_price × size）；paper 臂按 `virtual_capital × return_pct / 100`；floor 臂 net_pnl = ETF NAV 变动 × shares。gross_return 仍存百分比值（用于分列展示），net_pnl 存 CNY（用于聚合/Sharpe）。
- **C3 exit_reason 加 'hold'**：floor 臂不主动平仓，标 'hold'（持仓中，每日 MTM 更新 unrealized_pnl）。
- 迁移幂等：`__init__` 接线 + v1 完整 CREATE（memory `migration-stubs-fresh-db-fix`：新增带表功能须 v1 完整 CREATE + `__init__` 接线，不做桩）。

### 5.3 每日盘后生命周期（orchestrator + batch 模式 + MTM 分轨）

**C1 orchestrator 顺序管线**（非订阅/事件驱动）：

```
T-1 盘后：
  journal_recorder.run_daily():
    1. 调各臂 signal 生成器取候选
       - floor: index_replication_floor.build_position_batches() → 候选 ETF + 买入价
       - breakout: premarket_selection.select_premarket_candidates() → 候选股 + 信号日
       - limitup/trend: 对应 signal 生成器（mock 或实跑）
    2. 每条候选 → 生成 signal_id (UUID) + 标 arm tag
    3. 构造 Trades(code, signal_date, fill_type, direction, size)（C8：不带 signal_id/arm）
    4. 调 Executor.execute(trades, bars, T1OpenFill()) → entry fill
    5. 涨停买不到 → survivorship 过滤 → 标 entry_price=NULL + exit_reason='unbuyable'

T+1 起（batch 模式，H9：不走 executor exit，不订阅事件）：
  可平仓臂（breakout/limitup/trend）：
    6. 调 accounting.path_return(trades_filled, bars, stop, take, max_hold, apply_cost=True)
       → PathReturn(won, return_pct, exit_reason, exit_date, cost_pct, gross_return_pct)
    7. net_pnl = return_pct / 100 × position_notional (CNY)
    8. 写 trade_journal: signal_id/arm/stock_code/entry_price/entry_date/exit_price/
       exit_date/exit_reason/net_pnl/pnl_unit='CNY'/cost_pct/gross_return/is_realized=1
    9. path_return 内含 stop/take/max_hold 逻辑（accounting.py:137-181）——一次性返回完整路径

  gap 臂（falsified，保留录数据）：
    10. 调 accounting.gap_net_return(entry_price, exit_price, entry_date, size)
        → (net_ratio, cost_pct, gross_ratio)
    11. net_pnl = net_ratio × position_notional (CNY)
    12. 写 trade_journal: is_realized=1, is_dead_arm=1

  floor 臂（C3/C6：不走 path_return，走 mark-to-market）：
    13. entry 走 executor（同上）
    14. exit_reason='hold'（不主动平仓）
    15. 每日盘后按 ETF close 重算 unrealized_pnl = (current_close - entry_price) × shares - entry_cost
    16. net_pnl = NULL（未实现），unrealized_pnl 更新
    17. is_realized=0，equity 曲线含 unrealized MTM
```

**C3/C6 floor 分轨理由**：
- floor 臂是 ETF buy+hold 长线策略，path_return 需要 stop/take/max_hold——但 floor 无 stop/take（不主动平仓），max_hold 无限。强行走 path_return 会：①无 'hold' exit_reason（已加，C3）；②ETF 成本结构与个股不同（印花税 0.05% sell-side 仍适用，但 ETF round-trip spread ~0.1-0.3% 远小于个股 0.70%，用个股 _cost_pct 会 overcharge ~7.6x）；③floor 永不实现 net_pnl（buy+hold），equity 曲线看不到（C6）。
- floor 改走 mark-to-market：entry commission only（~0.05% 单边），每日按 ETF NAV 独立喂 equity 曲线（含 unrealized_pnl），不走 path_return。

**H7 gap-aware fill（stop/take 乐观偏差修正）**：
- accounting.path_return（:137-161）当前 stop/take 逻辑：`if low <= entry*(1+stop_pct/100)` → exit at stop level。这是**乐观偏差**——实际如果开盘价已穿透 stop（gap-down 开盘），成交价应是 open 而非 stop。
- 修正（gap-aware fill）：`if bar.open < stop_level → exit at open`；else `if low <= stop_level → exit at stop`。take profit 对称：`if bar.open > take_level → exit at open`；else `if high >= take_level → exit at take`。
- 若继承 engine 限制无法改 accounting.py（不改接口约束），则**文档化 optimism bias + 量级**：标注 path_return stop/take 是保守估计（stop 偏乐观 take 偏悲观），在 trade_journal.fills_json 记录 raw exit_price + optimism_flag。

**H9 batch 模式**（非 event-driven）：
- executor.py:35 `execute()` 只做 entry fill（:35-62 证实），无 exit fill 接口。
- journal_recorder 不等 executor exit events（接口不存在），改 batch 模式：call `path_return` → 一次性取完整 PathReturn（含 exit_reason/exit_date/exit_price）→ 写 journal。path_return 内部遍历 bars 做 stop/take/max_hold 闭环（accounting.py:137-181），返回时 exit 已确定。

- N 由 arm 配置：打板 T+1（次日盘中/开盘卖）/ 趋势 5-20d / 长线 floor hold 不主动平（exit_reason='hold'）
- survivorship 过滤：涨停一字板买不到的 signal，标 entry_price=NULL + exit_reason='unbuyable'，不进胜率分母（但保留录可复盘覆盖率，H8）
- T+1 guard：accounting 已有 T+1 不可卖 guard（idx+2>=len → None，:120），复用不重造

### 5.4 跨臂聚合 + 统计方法论（H1 + H2）

```python
def aggregate_by_arm(arm: str | None = None) -> dict:
    # SQLite query，不读结果 cache（memory s088-recompute-paradigm）
    # per-arm: net_winrate (Wilson CI) / Sharpe (DSR+MinTRL) / 净超额 (day-clustered t-test)
    #          / 盈亏比 / 总 net_pnl / signal_coverage_rate / execution_winrate
    # 基准：floor vs 930955 / breakout+limitup vs 等权随机基线
```

- **H2 Sharpe 年化修正**：per-trade Sharpe × sqrt252 无效（低频臂如 floor 每年交易 <10 次，套 sqrt252 高估 ~16x）。
  - 正确做法：先按 exit_date 日聚合 net_pnl → daily PnL 序列 → 再算 Sharpe = mean(daily_pnl) / std(daily_pnl) × sqrt(252)（日频年化有效）。
  - 或走 `compute_dsr(returns, n_trials=4)`（wiring.py:57）出 Deflated Sharpe + MinTRL，报 raw Sharpe + DSR + MinTRL 三列。
  - 统一 trade_journal 与 win_rate_tracker 同一年化定义（win_rate_tracker.py:192 当前是 per-trade 无年化，本 spec 不改它，但 trade_journal 聚合走日聚合年化）。
- **H1 统计方法论**：
  - 净超额 vs 基准走 `day_clustered_t_test(returns, dates)`（stats.py:139）——防同日 picks 膨胀 n（§44 proven：1000 picks/14 days → effective n ~14）
  - 4 臂多重检验走 `bonferroni_bh(p_values, n=K, method="BH")`（stats.py:324），K cap 8
  - 走 `compute_dsr(returns, n_trials=4, trial_cols=per_arm_returns)`（wiring.py:57）出 DSR + MinTRL
  - 走 `compute_haircut(returns, n_obs, n_tests, method)`（wiring.py:156）出 Sharpe haircut
  - 每点估计配 CI：胜率 Wilson interval / Sharpe bootstrap CI / 净超额 day-clustered t-test CI
  - **不足 n 标 underpowered 不出 kill**：n_days < 2 或 n_picks < 30 → 标 "exploratory/underpowered"，只报数不出 kill verdict
- **H8 coverage rate**：报 3 指标——signal_coverage_rate = buyable/(buyable+unbuyable) + execution_winrate = wins/(wins+losses) among buyable + unbuyable count。kill 吃 execution_winrate，coverage 并列可见不进 kill 分母。
- is_dead_arm=1 的记录不参与胜率/Sharpe 聚合，但保留可查（复盘 falsified 原因）

### 5.5 drawdown 熔断器（C4 + C5 + H4 + H5 + H6）

```python
class DrawdownBreaker:
    # equity 曲线 = initial_capital + cumulative_net_pnl (realized + unrealized MTM)
    #   — 遵循 risk_rules.equity_curve() (:103) 绝对 CNY 回撤模式
    # drawdown = peak_cny - current_cny（绝对 CNY，C4）
    # drawdown_pct = drawdown / initial_capital（相对 initial_capital，非相对 peak）
    # DD_pct > 10% → size_multiplier = 0.5
    # DD_pct > 15% → size_multiplier = 0.0（全停）
    # 输出 size_multiplier，与 lift_to_multiplier（S159）复合相乘
```

- **C4 绝对回撤（非零基百分比）**：原公式 `(peak - current)/peak` 从 peak=0 起算（零基曲线），对 1% 的 1000 元浮盈 → 10 元回撤 = 1%DD，但对 10000 元后续盈利 → 200 元回撤 = 2%DD，同一绝对金额不同百分比 → 20x 膨胀。改用 `risk_rules.equity_curve()` 模式：equity = initial_capital + cumulative_net_pnl，drawdown_cny = peak_cny - current_cny，drawdown_pct = drawdown_cny / initial_capital。
- **C6 equity 含 unrealized MTM**：floor 臂 buy+hold 永不实现 net_pnl（NULL），equity 曲线看不到。修正：equity = initial_capital + cumulative_realized_pnl + sum(unrealized_pnl)。is_realized=0 的持仓每日盘后按 close 重算 unrealized_pnl。floor 走 ETF NAV 独立喂 equity，不走 path_return。
- **C5 floor 豁免 per-arm DD**：ETF 历史 -13.6% > 10% 会误杀 floor。floor 是 buy+hold 长线，per-arm MTM 波动不是策略失效信号。floor 仅参与 portfolio aggregate DD，不参与 per-arm DD（或 arm-specific 高阈值 >15%×0.5 / >20%×0）。
- **H5 drawdown topology**：
  - (a) **per-arm DD** → 仅该臂 size_multiplier 缩放（floor 豁免）
  - (b) **portfolio aggregate DD** → portfolio-level breaker 统一缩放所有臂（floor 含在内，但阈值高或熊市豁免）
  - (c) `final_size = arm_size_multiplier × portfolio_size_multiplier × lift_multiplier` 三层乘积
- **H4 underpowered gate**：`drawdown_status` = 'enforced' | 'underpowered' | 'disabled' + `days_tracked`。
  - days_tracked < 60 → multiplier=1.0 status='underpowered'（不生效，参考 §44v2 days_robust<60）
  - Sharpe/胜率/净超额同款 gate：n<30 或 days<60 → exploratory 只报数不 kill
  - floor Sharpe 不适用标 N/A_hold，改报 tracking_error + 浮盈
- **H6 熊市 regime**：加熊市检测（CSI300 < 200 日均线 或 CSI300 DD > 15%）。熊市时 floor 豁免 drawdown enforce（阈值 >25%），CB 只作用非 floor 臂。或相对回撤（arm_DD - 市场_DD），排除系统性下跌归因到策略。
- 与 `lift_to_multiplier` 正交复合：final_size = lift_multiplier × drawdown_multiplier。lift 管 signal 信任（§44 验证），drawdown 管组合风控，不互相吞。
- 全停（×0）后恢复：需连续 N 日无新 drawdown 扩大 + 用户确认（不自动恢复，防反复割）。

### 5.6 备选方案为何不选

- **扩 journal.py 加 signal_id/arm 字段**：混录真实成交与模拟成交，口径污染（§5.1）。分离更干净。
- **复用 win_rate_tracker 加全链路**：WinRateRecord 是结算层（已完成交易），加生命周期会改其 22 调用方契约，爆炸半径大。上游闭环新建不动结算层。
- **复用 circuit_breaker.py 做 drawdown**：那是 IP 封阻断器（半开/熔断/恢复 timeout），语义不同——drawdown 是 equity 风控 sizing，不是网络重试。新建语义清晰。
- **enum 硬编码 arm**：当前 4 臂只有 2 个 concretely 在 code（floor/breakout），打板/趋势是概念，gap falsified。硬 enum 强制全部存在会卡住。用 string tag + 前向兼容。
- **C7 方案 b（改 settlement_recorder 调 path_return）**：改 settlement_recorder 会波及其 22 个调用方契约（winrate.db 读写路径），爆炸半径大。方案 a（journal_recorder 唯一写入）更干净——两库独立，互不干扰。

## 6. 验收标准

- [ ] A1 4 臂 signal 都能录到 trade_journal（floor/breakout 实跑 + limitup/trend/gap mock signal 录入）
- [ ] A2 net_pnl 算对：`path_return(apply_cost=True)` 跑通，gross_return 与 net_pnl 分列，cost_pct = `_cost_pct` 输出（用 `~/tools/financial_rigor.py` cross_validate 抽验 net vs gross vs cost 关系）。gap 臂走 `gap_net_return` 验 (net_ratio, cost_pct, gross_ratio)。floor 走 MTM 验 unrealized_pnl。
- [ ] A3 跨臂聚合：per-arm Sharpe（日聚合年化 + DSR + MinTRL）+ 净超额（day_clustered_t_test + CI）+ 盈亏比 + signal_coverage_rate + execution_winrate 产出，is_dead_arm=1 不混入聚合。n<30 或 days<60 标 underpowered 不 kill。
- [ ] A4 drawdown 熔断触发：mock equity 曲线 DD/initial_capital > 10% → size_multiplier=0.5 / > 15% → 0.0，与 lift_multiplier 复合相乘。days<60 → status='underpowered' multiplier=1.0。floor 豁免 per-arm DD。
- [ ] A5 survivorship 过滤：涨停一字板 signal 标 entry_price=NULL + exit_reason='unbuyable'，不进 execution_winrate 分母，但 signal_coverage_rate 含 unbuyable count。
- [ ] A6 trade_journal 表存 `.vibe-research/`，`git status` 确认未进 git
- [ ] A7 journal.py(S166) / win_rate_tracker / accounting / executor / decision.Trades 接口未改（grep 确认无 breaking change）。winrate.db 未经 journal_recorder 写入（C7：闭环臂唯一写 trade_journal）。
- [ ] A8 `pytest -m "not live"` 全绿（新建单测 + 不破坏现有）
- [ ] A9 前端 JournalLedger section 挂在现有 Journal.tsx 页内，显持仓 + unrealized MTM + 归因
- [ ] A10 floor 臂 equity 可见：buy+hold 持仓每日 MTM 更新 unrealized_pnl，equity 曲线含 realized + unrealized（C6）
- [ ] A11 熊市 regime 检测：CSI300 < 200 日线时 floor 豁免 drawdown enforce，CB 只作用非 floor 臂（H6）

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：闭环账本是测量基建（录 signal→PnL 数据），非直接给买卖建议。kill/EWMA 是内部进化反馈，不直接出交易指令给用户。属系统能力（CLAUDE.md §1.1）。用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」。
- [x] **判断可复现**：net PnL 走 `accounting.path_return(apply_cost=True)` / `gap_net_return` 可复算，禁臆造/心算。聚合走 SQLite query 不读结果 cache（memory s088）。涉及成本的用 `~/tools/financial_rigor.py` cross_validate 抽验。
- [x] **涨停四池/连板股榜**：不涉及（本 spec 是闭环账本，非涨停/连板榜单呈现）。
- [x] **用户私有数据隔离**：trade_journal 表存 `data_dir()`（`.vibe-research/`，gitignored，绝不进 git）。见 `vr_paths.py` `data_dir()`。
- [x] **新增东财端点走 `em_get`**：本 spec 不新增东财端点（OHLC 走 executor 既有 kline 读路径，accounting 不联网）。无防封新增。
- [x] **§44 诚实标注**：gap/dead_arm 记录标 `is_dead_arm=1` 不混入聚合胜率（防 falsified 臂污染存活臂统计）。net_pnl 强制走 accounting 真成本，杜绝 gap 成本幻觉重演（§2.3 教训）。
- [x] **H1 统计不确定性诚实标注**：每点估计配 CI（胜率 Wilson / Sharpe bootstrap / 净超额 day-clustered t-test CI）。不足 n（n_days<2 或 n_picks<30）标 underpowered/exploratory 不出 kill verdict。不裸点估计。4 臂多重检验走 bonferroni_bh（K cap 8）防 false positive。Sharpe 走 DSR + MinTRL 防 inflated Sharpe。这是"统计严谨"工程底线——让胜率数字为真，不是合规仪式。

**弱合规定位**：私人投研助理，闭环账本是内部测量基建，无合规仪式需求。工程底线（不臆造/私有数据隔离/防封/统计严谨）全部确认通过。

## 8. 测试计划

- **单测（离线）**：
  - `test_trade_journal`：mock executor fill + accounting path_return，验 signal→entry→exit→net_pnl 录入 + is_realized 切换 + is_dead_arm 不混聚合。gap 臂走 gap_net_return 验。floor 臂走 MTM 验 unrealized_pnl 每日更新。
  - `test_drawdown_breaker`：mock equity 曲线，验 DD/initial_capital>10%→0.5 / >15%→0.0 / 与 lift_multiplier 复合相乘。days<60→underpowered multiplier=1.0。floor 豁免 per-arm DD。熊市 regime 豁免 floor。
  - `test_journal_recorder`：mock 各臂 signal 生成器返回 + executor fill，验 4 臂（floor/breakout/limitup/gap）全录到 + survivorship 过滤涨停买不到。验 orchestrator 顺序管线（非订阅）。验 Trades 不带 signal_id/arm（C8）。
  - `test_trade_journal_migration`：fresh DB 建表幂等 + v1 完整 CREATE（memory migration-stubs-fresh-db-fix）
  - `test_aggregate_stats`：验 day_clustered_t_test + bonferroni_bh + compute_dsr + compute_haircut 调用 + CI 产出 + underpowered gate（n<30 标 exploratory）
  - 跑 `pytest -m "not live" backend/tests/ -k "trade_journal or drawdown_breaker or journal_recorder or aggregate_stats"`
- **联网验收**：A1 floor/breakout 实跑一次真 signal→fill→exit（executor 读真 kline）
- **成本验算**：A2 用 `~/tools/financial_rigor.py cross-validate --field net_pnl --values '{"gross":G,"cost":C,"net":N}' --unit CNY` 抽验 net = gross - cost 关系
- **不破坏现有**：A8 全量 `pytest -m "not live"` 绿（含 S166 journal 测试 / S162 engine 测试）

## 9. 风险与回滚

| 风险 | 影响 | 回滚 |
|---|---|---|
| trade_journal 表迁移失败 | 闭环账本不可用 | 迁移幂等 + v1 完整 CREATE；失败标 latent（is_dead_arm 全标，不阻断现有 4 臂运行）|
| accounting path_return/gap_net_return 口径与实际成交偏差 | net_pnl 不准 | 真实成交走 journal.py 独立口径（§5.1），模拟闭环用 accounting 统一模型；偏差用 `financial_rigor.py` cross_validate 抽验 |
| drawdown 熔断误触发（小样本 equity 曲线抖动）| 误降 sizing 误停臂 | H4 underpowered gate：days_tracked<60 → status='underpowered' multiplier=1.0 不生效（参考 §44 v2 days_robust<60 逻辑）；需 ≥60 日 equity 才 enforce |
| floor per-arm DD 误杀（ETF 波动 >10%）| floor 被误停 | C5：floor 豁免 per-arm DD，仅参与 portfolio aggregate DD；或熊市 regime 高阈值（H6）|
| executor 只做 entry fill 无 exit fill | exit 录不到 | H9 batch 模式：path_return 一次性返回完整 PathReturn（含 exit_reason/exit_date），不等 executor exit events |
| path_return stop/take 乐观偏差（gap-through 未建模）| net_pnl 偏乐观 | H7：gap-aware fill（open 穿透 stop → exit at open）；若不改 accounting 则文档化 optimism bias + 量级，fills_json 记 optimism_flag |
| winrate.db 双写口径不一致 | 统计污染 | C7 方案 a：闭环臂不经 settlement_recorder，journal_recorder 唯一写入 trade_journal，winrate.db legacy 只读 |
| Sharpe 年化方法不当（per-trade × sqrt252）| Sharpe 高估 ~16x | H2：先日聚合 daily PnL 再年化，或走 compute_dsr 出 DSR+MinTRL |
| 熊市系统性下跌归因到策略 | 误 kill 非 floor 臂 | H6：熊市 regime 检测（CSI300<200 日线），floor 豁免 drawdown，或相对回撤（arm_DD-市场_DD）|
| net_pnl 单位跨臂不一致（CNY vs %）| 聚合算错 | H3：pnl_unit 固定 CNY，paper 臂 virtual_capital×return_pct 折算 |
| 前端 JournalLedger 挂载冲突现有 Journal 页 | Journal 页渲染坏 | 新 section 独立 query + error boundary；挂载失败只隐藏该 section 不影响现有 |
| arm tag 前向兼容漏（新臂未注册）| 新臂 signal 录不进 | string tag 不硬 enum（§5.6），未知 arm 也能录（标 unknown_arm 不阻断，后续补 tag）|

---

> 本 spec 只写规范，不写实现代码。下一步：plan.md（技术方案）→ tasks.md（任务拆分）→ 实现 → 验收。SDD §0 不跳。
> 实现前 grill：本 spec 涉及胜率统计 + drawdown 风控 sizing，属方法论变更，须起 ≥6 视角 adversarial verify（memory `adversarial-verify-workflow`：S150/S153 solo 漏 CRITICAL，对抗审查抓真 bug）。
> v2 修订：grill 8 CRITICAL（C1-C8）+ 9 HIGH（H1-H9）已 apply，每条改对应 section。关键决策：C7 选方案 a（journal_recorder 唯一写入，winrate.db legacy 只读）；C5 floor 豁免 per-arm DD 仅参与 portfolio aggregate；C1 改订阅为 orchestrator 顺序管线。
