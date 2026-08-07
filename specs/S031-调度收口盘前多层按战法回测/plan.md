# Plan: S031 — 调度收口 + 盘前简报多层 + 交互式战法 + 按战法回测

> 对应 `spec.md`。细化 A/B 两节并行实现的技术方案。
> A = S011 复活切片（R3/R5/R7/R9/R11/R12 + 预计算 seed），B = 盘前简报多层 + 交互式战法 + 按战法回测引擎。
> 砍 R6/R8/R10 推 S011b 第二轮。

---

## A 节：调度收口 + 预计算打通

### A1. SQLite WAL + busy_timeout（R3）

`scheduled_tasks._init_db`（:71）建表后加：

```python
conn = sqlite3.connect(_DB_PATH, timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")
conn.execute("PRAGMA foreign_keys=ON")
```

所有写路径已过 `_manager`（`TaskManager`），加 `_DB_LOCK`（已有 `threading.Lock`）。WAL 对读路径（routers/scheduled_tasks.py list）零影响——WAL 读不阻塞写。

**不引连接池**（YAGNI，单进程 + `check_same_thread=False` + lock 够用）。

### A2. lifespan 最小版（R5）

`app.py` 现状模块级 `start_portfolio_scheduler(1800)` + `start_limitup_scheduler()` + `_st.start_scheduler()`。改为：

```python
from contextlib import asynccontextmanager

_portfolio_stop = threading.Event()

def _start_portfolio_thread(interval: int = 1800):
    def loop():
        while not _portfolio_stop.wait(interval):
            try:
                asyncio.run(_refresh_snapshot())
            except Exception:
                pass  # R8 第二轮改 logging
    threading.Thread(target=loop, daemon=True).start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    _st.start_scheduler()
    _start_portfolio_thread()
    yield
    # shutdown
    _st.get_scheduler().stop()
    _portfolio_stop.set()

app = FastAPI(title="Vibe-Research API", version="0.1.4", lifespan=lifespan)
```

- `CronScheduler.stop`（已有 `scheduled_tasks.py:702`）置 `_running=False`，daemon 线程自然退出。**不 join**（daemon 不阻塞退出，S011 原设计如此）。
- `portfolio` 加模块级 `_portfolio_stop = threading.Event()`，`while True`→`while not _portfolio_stop.wait(interval)`（可被 stop 唤醒，替 `time.sleep`）。
- **except:pass 留第二轮（R8）**——本轮只加停止标志，except 改 logging 推 S011b。

### A3. 三份预计算合并（R7）

现状三份重复：
- `scheduler.py:16-61` `_precompute_limitup_async`（回溯 3 天：screener/STI/auction/daily_review）
- `scheduled_tasks.py:465-511` `_execute_limitup_precompute`（几乎逐行复制 + `back_days` 参数）
- `scheduled_tasks.py:440-457` `_execute_daily_data_refresh` 里又调 `daily_review.precompute_daily`

**合并到 `scheduled_tasks._execute_limitup_precompute` 为单一源**：
- 删 `scheduler.py:_precompute_limitup_async`（随 R12 删整个文件）。
- `_execute_daily_data_refresh` 不再调 `reviewer.precompute_daily`（由 limitup_precompute 统一驱动），只保留 `portfolio.refresh_all`。
- `_execute_limitup_precompute` 保持现有逻辑（screener → STI → auction → daily_review，各独立 try/except 容错），作为唯一预计算入口。

### A4. 统一 BEIJING_TZ（R9）

`scheduled_tasks._tick`（:735）`now = datetime.now()` → `now = datetime.now(BEIJING_TZ)`。`cron_match`（:639）纯函数收 `datetime`，带时区的 `now` 传入即可比较（cron 字段是时分日月周，时区不影响数值）。导入 `from limitup_screener import BEIJING_TZ`（`scheduler.py` 已用此路径，统一）。

### A5. 删死代码（R11）

`pre_market_workflow.py:199-230` `_build_strategy_match` —— rg 确认无调用方，直接删。

### A6. 删 scheduler.py（R12，最后一步）

顺序硬约束：
1. A1-A5 完成 + 单测过
2. seed 默认任务验证（A7）
3. `app.py:40` 删 `from scheduler import start_limitup_scheduler, start_portfolio_scheduler`
4. `app.py:72-73` 删 `start_portfolio_scheduler(1800)` + `start_limitup_scheduler()`
5. `backend/scheduler.py` `git rm`
6. portfolio 启动改 `app.py` lifespan 内 `_start_portfolio_thread()`（A2）

### A7. 预计算 seed（R13 / S028 #3）

`scheduled_tasks` 启动时（`start_scheduler` 内）seed 默认任务：

```python
def _ensure_seed_tasks():
    existing = {t.name for t in _manager.list_tasks()}
    if "limitup_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="limitup_precompute",
            task_type="limitup_precompute",
            cron_expr="30 15 * * 1-5",  # 工作日 15:30
            payload={"back_days": 3},
            enabled=True,
        ))
```

交易日判断：`_tick` 命中后，`_execute_limitup_precompute` 内 `datetime.now(BEIJING_TZ).weekday() >= 5` 跳过（cron `1-5` 已限工作日，双保险）。节假日表 `data/trading_calendar.json` **本轮不建**——cron `1-5` 跳周末够用，节假日由 `get_screener_result` 返回空涨停池自然处理（非交易日无涨停数据，screener 返空，不报错）。注释标明"节假日精确判断推 S011b 随 trading_calendar.json 建"。

`_ensure_seed_tasks` 在 `CronScheduler.start`（或 `get_scheduler`）末尾调，幂等（查 name 已存在则跳过）。

---

## B 节：盘前简报多层 + 交互式战法 + 按战法回测

### B1. 涨停基因因子三层化（R14，后端）

`limitup_screener_factor.fetch()` 现输出 1 个 `FunnelLayer`。改为 3 层：

```
L1 打分:  input = len(filtered_out) + candidates + strong  (全涨停)
          output = candidates + strong (qualified)
          filtered_out = report.filtered_out
          conditions = [五维权重, 合格阈值, 高基因阈值]
          config_out: data_status/reason/scanned_count (S028 逻辑移入)
L2 战法:  input = len(L1.output)
          output = [c for c in candidates if c.code in {sm.code for sm in strategy_matches}]
          filtered_out = [L1.output 中未匹配战法的]
          conditions = ["8大战法自动匹配", "取置信度最高"]
          passed 每项 detail 携 best_strategy/confidence（供 R19 交互反筛）
L3 仓位:  input = len(L2.output)
          output = [c for c in matched if c.code in {ps.code for ps in position_suggestions}]
          filtered_out = [L2.output 中未给仓位的]
          conditions = ["仓位建议（PositionAdvisor）"]
```

保留 S028 的 `data_status`/`conditions`/`scanned_count` 逻辑（移入 L1 config_out）。L2/L3 的 passed 用 `report.strategy_matches`/`report.position_suggestions` 的 code 集合做过滤，不臆造。

### B2. 去 [:20] 上限（R15）

`pre_market_workflow.py:147` `for stock in pool.candidates[:20]:` → `for stock in pool.candidates:`。

性能基线：`_strategy_matcher.match(stock)` 内调 `match_strategies(code, gene)`——**纯内存计算**（读 `gene.factors`/`zt_count_250d`，不调 astock，只比对 STRATEGY_REGISTRY 8 项条件）。50/80/100 qualified 三档测：<1s 可接受。`PositionAdvisor.advise_batch` 同理纯内存。无 em_get 调用，无封号风险。

### B3. FunnelLayerCard 公共组件抽取（R16/R17）

从 `FunnelLayers.tsx` 提取 `FunnelLayerCard({layer, onPick})`：

```tsx
// FunnelLayerCard.tsx
export function FunnelLayerCard({ layer, onPick }: { layer: FunnelLayer; onPick?: (code: string) => void }) {
  return (
    <div className="rounded-lg border border-border/40 p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{layer.input_count}</span>
        <ArrowRight className="h-3 w-3" />
        <span className="font-medium text-foreground">{layer.output_count}</span>
      </div>
      <ConditionsChips conditions={layer.conditions} variant="info" />
      <PassedList codes={layer.output_codes} onPick={onPick} />
      <FilteredList items={layer.filtered_out} />
    </div>
  );
}
```

`FunnelLayers`（候选池页）和 `FactorSection`（盘前简报）共用。conditions chips：因子层用 info 色（权重公式），候选池用 neutral（过滤规则），视觉区分语义。

### B4. Sheet 抽屉 + CandidateDetailPanel（R18）

新建 `frontend/src/components/ui/Sheet.tsx`：

```tsx
import { createPortal } from "react-dom";

export function Sheet({ open, onClose, children, side = "right" }: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className={cn("absolute top-0 right-0 h-full w-full max-w-md overflow-y-auto bg-background p-4 shadow-xl")}>
        {children}
      </div>
    </div>,
    document.body
  );
}
```

`CandidateDetail.tsx` 重构：
- 抽出 `CandidateDetailPanel({ code }: { code: string })`——纯展示，调 `candidatesApi.diagnosis(code)`，内 `<Skeleton>` loading 态。
- 路由页 thin 包装：`<CandidateDetailPanel code={params.code} />`
- 抽屉：`<Sheet open={!!drawerCode} onClose={() => setDrawerCode(null)}><CandidateDetailPanel code={drawerCode} /></Sheet>`

点候选：`setDrawerCode(code)`，不 `navigate`。`/workflow/candidates/:code` 直链仍可用（路由页）。

### B5. 交互式战法 L2（R19）

L2 层加战法多选 chips（8 大战法，从 `STRATEGY_REGISTRY` 或 L2 passed 的 `best_strategy` 去重取）：

```tsx
function StrategyFilter({ strategies, selected, onChange }) {
  const toggle = (s) => {
    const next = new Set(selected);
    next.has(s) ? next.delete(s) : next.add(s);
    onChange(next);
  };
  return (
    <FilterBar pills={[
      { key: "all", label: "全部", active: selected.size === 0, onClick: () => onChange(new Set()) },
      ...strategies.map(s => ({ key: s, label: s, active: selected.has(s), onClick: () => toggle(s) }))
    ]} />
  );
}
```

反筛纯前端：

```tsx
const visible = selected.size > 0
  ? layer.output.filter(c => selected.has(c.detail?.best_strategy))
  : layer.output;
```

选"全部"清空 `selected`，恢复。**不重新请求后端**。

### B6. 按战法回测引擎（R20，后端新模块）

新建 `backend/strategies/strategy_backtest.py`：

```python
from dataclasses import dataclass
from limitup_screener.data import load_gene_scores, get_db
from limitup_screener.models import GeneScore
from limitup_strategy import STRATEGY_REGISTRY, match_strategies
import astock
from data.mappers import kline_from_mootdx
from datetime import datetime, timedelta

@dataclass
class StrategyBacktestResult:
    strategy_code: str
    strategy_name: str
    win_rate: float          # 0-1
    avg_return: float        # 百分比
    sample_size: int        # 实际回测交易笔数
    available_days: int     # DB 实际可用天数（可能 < lookback_days）

class StrategyBacktester:
    """按战法历史回测——只用 DB 已有历史日，不触发 em_get 回溯。"""

    _CACHE: dict = {}
    _CACHE_TTL = 43200  # 12 小时

    def run(self, lookback_days: int = 60) -> list[StrategyBacktestResult]:
        dates = self._get_available_dates(lookback_days)
        # 逐日：load_gene_scores → match_strategies → 收集 (code, strategy_code, date)
        trades: list[dict] = []
        for d in dates:
            scores = load_gene_scores(d) or []
            for gene in scores:
                if not gene.qualify:
                    continue
                signals = match_strategies(gene.code, gene)
                for sig in signals:
                    trades.append({
                        "code": gene.code, "strategy_code": sig.strategy_code,
                        "strategy_name": sig.strategy_name, "date": d,
                        "max_hold": sig.max_hold_days,
                        "stop_pct": next(s["stop_loss_pct"] for s in STRATEGY_REGISTRY if s["code"] == sig.strategy_code),
                        "profit_pct": next(s["take_profit_pct"] for s in STRATEGY_REGISTRY if s["code"] == sig.strategy_code),
                    })
        # 逐笔 K 线算盈亏
        for t in trades:
            t.update(self._backtest_single(t["code"], t["date"], t["max_hold"], t["stop_pct"], t["profit_pct"]))
        # 按战法聚合
        return self._aggregate(trades, len(dates))

    def _get_available_dates(self, lookback_days: int) -> list[str]:
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT date FROM gene_scores ORDER BY date DESC LIMIT ?",
            (lookback_days,),
        ).fetchall()
        conn.close()
        return [r["date"] for r in rows]

    def _backtest_single(self, code, date, max_hold_days, stop_pct, profit_pct) -> dict:
        """K 线算入场(次日开盘)/出场(max_hold 收盘或 stop/profit 提前平)。"""
        raw = astock.kline(code, category=4, offset=max_hold_days + 5)
        bars = kline_from_mootdx(code, raw).bars
        idx = next((i for i, b in enumerate(bars) if (b.date or "")[:10] == date), None)
        if idx is None or idx + 1 >= len(bars):
            return {"won": False, "return_pct": 0.0, "skipped": True}
        entry = bars[idx + 1].open  # 次日开盘买入
        for j in range(idx + 1, min(idx + 1 + max_hold_days, len(bars))):
            if bars[j].low <= entry * (1 + stop_pct / 100):
                return {"won": False, "return_pct": float(stop_pct), "skipped": False}
            if bars[j].high >= entry * (1 + profit_pct / 100):
                return {"won": True, "return_pct": float(profit_pct), "skipped": False}
        exit_price = bars[min(idx + max_hold_days, len(bars) - 1)].close
        ret = (exit_price - entry) / entry * 100 if entry else 0.0
        return {"won": ret > 0, "return_pct": round(ret, 2), "skipped": False}

    def _aggregate(self, trades, available_days) -> list[StrategyBacktestResult]:
        by_strat: dict[str, list] = {}
        for t in trades:
            if t.get("skipped"):
                continue
            by_strat.setdefault(t["strategy_code"], []).append(t)
        results = []
        for s in STRATEGY_REGISTRY:
            items = by_strat.get(s["code"], [])
            total = len(items)
            wins = sum(1 for t in items if t["won"])
            avg_ret = sum(t["return_pct"] for t in items) / total if total else 0.0
            results.append(StrategyBacktestResult(
                strategy_code=s["code"], strategy_name=s["name"],
                win_rate=round(wins / total, 4) if total else 0.0,
                avg_return=round(avg_ret, 2),
                sample_size=total, available_days=available_days,
            ))
        return results
```

**关键设计决策**（grill 第 3 轮锁定）：
- **不复用 `match_strategies` 输出的 `entry_price`**（`limitup_strategy.py:680` `entry_price=round(gene.total_score,2)` 是假的）。只用 `match_strategies` 的**战法匹配判定**（哪些股命中哪个战法）+ confidence。
- **入场价 = 次日开盘价**（K 线取数），**出场 = max_hold_days 后收盘 或 触发 stop_loss_pct/take_profit_pct 提前平**。
- **只跑 DB 已有历史日**（R21 防封）：`_get_available_dates` 查 `gene_scores` 表的 DISTINCT date，按 lookback_days 截断。当前 8 天（07-28~08-06），随 seed 积累变厚。lookback_days 传 60 但实际只跑 8 天，`available_days` 字段标注实际。
- `match_strategies` 需要 `GeneScore`——`load_gene_scores(date)` 已能从 DB 重构 `GeneScore`（`data.py:99`），复用。
- **缓存**：`_CACHE` 内存 + TTL 12h，重复请求不重算。

端点：`backend/routers/strategy.py` 加：

```python
@router.get("/api/strategy/backtest")
async def strategy_backtest(lookback_days: int = Query(60, ge=1, le=365)) -> Dict[str, Any]:
    bt = StrategyBacktester()
    results = await asyncio.to_thread(bt.run, lookback_days)
    return {"data": [{
        "strategy": r.strategy_name, "strategy_code": r.strategy_code,
        "win_rate": r.win_rate, "avg_return": r.avg_return,
        "sample_size": r.sample_size, "available_days": r.available_days,
    } for r in results]}
```

### B7. WinRatePanel 对比展示（R22）

盘前简报新增 `WinRateComparePanel`——并列两列：

```
| 战法       | 回测胜率(R20) | 合成胜率(标"估算") | 样本量 |
|------------|--------------|-------------------|--------|
| 首板挖掘   | 62.3%        | 0.80              | 12     |
| 连板接力   | ...          | ...               | ...    |
```

- 左列：`GET /api/strategy/backtest`（R20 真实回测）。`useStrategyBacktest(60)` hook 取数。
- 右列：`report.strategy_matches` 里各股的 `best_strategy` + `confidence` → 按 `limitup_strategy.py:685` 公式 `min(confidence*0.8+0.2,0.95)` 重算，按战法取均值展示，**标注"合成估算非回测"**。
- 两列对比，让用户看真实 vs 估算差异。`available_days` 标注实际回测天数。
- 用户录入胜率（`/api/winrate/strategy`）作第三面板靠后（已有，不本 spec 扩）。

### B8. 页内布局重整（R23）

`PreMarketBriefing.tsx` 纵向分区：

1. 市场情绪卡（既有）
2. 涨停基因因子漏斗（三步 L1/L2/L3）—— `FactorSection` 多层 `FunnelLayerCard` + R19 战法筛选 `StrategyFilter`
3. 候选池漏斗（R1-R3）—— `useFunnelLayers` + `FunnelLayers`
4. WinRateComparePanel（R22）
5. 抽屉层（Sheet，点候选触发）

每区 `SectionHeader` 标题 + 一句说明。

### B9. GeneScreener 定位厘清（R24）

盘前简报头部："阈值配置 / 全市场得分表 →" 链 `/limitup/gene`。
GeneScreener 页头：副标题"（盘前简报的配置伴随页）"+ 回链"← 回盘前简报"。

---

## 实现步骤（A/B 并行，按依赖排序）

### A 节步骤

1. **A1** SQLite WAL + busy_timeout（`scheduled_tasks._init_db`）+ 单测 `test_wal_pragma`
2. **A2** lifespan（`app.py` `@asynccontextmanager` + `_portfolio_stop`）+ 单测 `test_lifespan_shutdown`
3. **A4** BEIJING_TZ（`scheduled_tasks._tick`）+ 单测 `test_tick_beijing_tz`
4. **A3** 三份预计算合并（`_execute_daily_data_refresh` 去 daily_review 重复调用）
5. **A7** seed 默认任务（`_ensure_seed_tasks`）+ 单测 `test_seed_idempotent`
6. **A5** 删 `_build_strategy_match` 死代码
7. **A6** 删 `scheduler.py` + `app.py` 去 import（最后一步，A1-A5 + seed 验证后）
8. `pytest -m "not live"` 全过 + :8900 启停冒烟

### B 节步骤

1. **B2** 去 `[:20]`（`pre_market_workflow.py:147`）+ 性能基线测（50/80/100 qualified）
2. **B1** 因子三层（`limitup_screener_factor.fetch()` 拼 3 FunnelLayer）+ 后端单测 `test_limitup_screener_factor_layers`
3. **B3** `FunnelLayerCard` 抽取 + 候选池页回归测
4. **B16/R17** `FactorSection` 多层渲染 + `useFunnelLayers` 嵌入盘前简报
5. **B4** `Sheet` 组件 + `CandidateDetailPanel` 抽出 + 组件单测
6. **B5** 交互式战法 L2（`StrategyFilter` 多选反筛）
7. **B6** `strategy_backtest.py` 回测引擎 + `GET /api/strategy/backtest` 端点 + 后端单测 `test_strategy_backtest`
8. **B7** `WinRateComparePanel` 对比展示 + `useStrategyBacktest` hook
9. **B8** 布局重整（纵向分区 + SectionHeader）
10. **B9** GeneScreener 定位厘清
11. 前端 tsc + vitest 全过 + playwright 冒烟

### A/B 交叉依赖

- **B2（去 [:20]）** 不依赖 A，可最先做。
- **B6（回测引擎）** 不依赖 A（只读 DB 已有 8 天），可独立做。
- **B1（因子三层）** 依赖 B2（去上限后 L2 才有完整 strategy_matches）。
- **A7（seed）** 不阻塞 B——B 验收用 DB 已有 8 天历史日，不强依赖 seed 已跑。
- **A6（删 scheduler）** 必须在 A1-A5 + A7 验证后，最后一步。

---

## 风险点

- **删 scheduler 前 scheduled_tasks 需验证** → 顺序硬约束（A1-A5 + seed 验证后才删）
- **回测引擎 K 线取数慢**：8 天 × ~80 股 = ~640 次 mootdx 调用。mootdx 本地无封号，但慢。缓存 12h（`_CACHE` + TTL），重复请求不重算。
- **去 [:20] 性能**：match_strategies 纯内存（无 astock），最坏 100 × <10ms = <1s。若超预期，加并行 `match_batch`（已有）。
- **FunnelLayerCard 抽取**：候选池页（`/candidates`）与盘前简报共用，改动影响候选池页，需回归测。
- **lifespan 兼容**：`_portfolio_stop.wait(interval)` 替 `time.sleep`，daemon 线程可被 stop 唤醒。`except:pass` 留第二轮。
