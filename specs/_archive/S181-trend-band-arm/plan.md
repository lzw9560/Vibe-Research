# Plan: S181 — 趋势波段臂（B 臂，替代搁置 ash-mcp）

> spec: spec.md  状态：草案  日期：2026-09-10  分级：large

## 1. 取舍与备选

### 1.1 复用 non_limitup_funnel vs 新写 signal generator

**选：复用** `build_non_limitup_candidates` + `run_non_limitup_funnel` + `score_candidates`，只换 sector 输入。

理由（DRY）：
- non_limitup_funnel 已实现完整 pipeline（板块成分股 → 形态扫描 → 策略分），5540 只 baostock industry_map + kline cache 一次性加载
- trend 臂的新颖性在 sector 选择（rotation phase + fund flow），不在 stock-level 形态扫描
- 复用避免 reimplementation drift（coding-style DRY 原则）

**不选：fork non_limitup_funnel**。fork 后两份 pipeline 维护 drift，因子定义改了一处忘了另一处。trend 只需注入不同 sector list，不碰 funnel 内部。

**不选：从零写 signal generator**。已有 sector_cycle + pattern_scan + market_scan + non_limitup_funnel 四层基建，重写是造轮子（CLAUDE.md 先搜后写）。

### 1.2 honest_label：新增 EXPLORATORY vs 复用 MOCK_NOT_READY

**选：新增 `EXPLORATORY`**。

理由（诚实）：
- `MOCK_NOT_READY` = signal 生成器未建。trend 生成器已建 → 标 mock 不诚实
- `SECTION44_FALSIFIED` = §44 跑了否了。trend §44 没跑 → 不能标 falsified
- `EXTERNALLY_VALIDATED` = 外部三重定论。trend 没有学术/卖方/指数定论 → 不能标 validated
- `EXPLORATORY` = signal 已建，§44 未验，积极跟踪待判。准确反映 trend 当前状态

### 1.3 trade mechanics：path_return vs gap_net_return vs MTM

**选：path_return(apply_cost=True)**。

| 路径 | 适用 | 选不选 |
|---|---|---|
| path_return(stop/take/max_hold, apply_cost=True) | 可平仓臂，有 stop/take/max_hold | ✅ trend 是 swing（有 stop/take/max_hold） |
| gap_net_return(entry, exit) | 隔夜 gap 事件（2 价，无 stop/take） | ❌ trend 不是隔夜事件 |
| MTM (hold, 不平) | floor 长线底仓 | ❌ trend 有主动平仓（stop/take/max_hold） |

trend 走 path_return 同 breakout——有 stop/take/max_hold，扣 `_cost_pct`（5 元 min + 印花 + slippage），成本分轨与 breakout 一致（C2 分轨）。

### 1.4 settle_pending：并行方法 vs 泛化

**默认选：并行 `settle_pending_trend`**（小 blast radius）。

`settle_pending_breakout` 硬编 BREAKOUT_* params + arm="breakout"。并行 `settle_pending_trend` 同结构换 TREND_* params + arm="trend"。

**备选（grill 后定）：泛化** `settle_pending_breakout` → `settle_pending(arm, stop, take, max_hold)` 让 breakout + trend 共用。DRY 但改已有方法签名，blast radius 更大。若 grill 认为重复不可接受则泛化。

## 2. 模块拆分

### 2.1 `backend/strategies/trend_swing_arm.py`（signal generator + 报告，~150 行）

```
trend_swing_arm.py
  ├─ TREND_STOP_PCT = -6.0           # swing stop（wider than breakout -4%）
  ├─ TREND_TAKE_PCT = 15.0           # swing take（wider than breakout +8%）
  ├─ TREND_MAX_HOLD = 10             # 2 weeks（vs breakout 3d）
  ├─ TREND_TOP_N = 5                 # paper 跟踪候选数
  │
  ├─ _identify_trending_sectors(date)  # sector_cycle phase + fund flow → top sectors
  │   ├─ sector_cycle.aggregate_sectors(date) → [{industry, zt_count_today, zt_momentum}]
  │   ├─ sector_cycle.classify_phase(count, avg_3d) → phase + multiplier
  │   ├─ market._sectors() → sector_fund_flow → net inflow 筛选
  │   └─ composite rank → top TREND_TOP_SECTORS 个 trending sectors
  │
  ├─ select_trend_candidates(date)    # signal generator → top N candidates
  │   ├─ _identify_trending_sectors(date) → top sectors
  │   ├─ market_scan.build_non_limitup_candidates(top, industry_map, cache, per_sector)
  │   ├─ non_limitup_funnel.run_non_limitup_funnel(candidates, ...) → pattern scan
  │   ├─ funnel.aggregation.score_candidates(produced, None, "market_scan") → scored
  │   └─ scored[:TREND_TOP_N] → 返回 candidates
  │
  ├─ trend_arm_status(journal)        # open positions 汇总（from trade_journal）
  └─ trend_arm_report(journal)        # report（PnL + coverage + days_tracked）
```

- 仿 `index_replication_floor.py` 范式（模块级 signal generator + status + report）
- signal generator 委托 market_scan + non_limitup_funnel + score_candidates（不自建形态扫描/打分）
- `_identify_trending_sectors` 是 trend 臂唯一新颖逻辑——sector rotation phase + fund flow composite
- 私有数据不写文件（trend 全 paper，state 在 trade_journal.db，不写 batches.json）

### 2.2 `backend/strategies/journal_recorder.py`（加 _process_trend + settle_pending_trend）

```
journal_recorder.py（diff）
  ├─ TREND_STOP_PCT = -6.0 / TREND_TAKE_PCT = 15.0 / TREND_MAX_HOLD = 10  # 新增常量
  ├─ DEFAULT_ARMS: ["floor", "breakout", "trend"]  # 加 trend
  │
  ├─ _process_trend(target_date)       # 新增——仿 _process_breakout 换 TREND_* params
  │   ├─ select_trend_candidates(target_date) → candidates
  │   ├─ per candidate: Trades → Executor.execute(T1OpenFill) → path_return(TREND_*)
  │   ├─ path_return None → 'hold' unrealized
  │   ├─ path_return not None → realized + net_pnl + cost_pct
  │   └─ trade_journal.insert(arm="trend")
  │
  ├─ settle_pending_trend()            # 新增——仿 settle_pending_breakout 换 TREND_* params
  │   └─ query is_realized=0 arm='trend' exit_reason='hold' → bars 增长后重算 path_return → INSERT OR REPLACE 同 signal_id
  │
  └─ run_daily() dispatch: arm=="trend" → self._process_trend(target_date)
```

- `_process_trend` 结构与 `_process_breakout` 一致（select → Trades → execute → path_return → insert）
- 唯一差异：select_trend_candidates（trend sector rotation）vs select_premarket_candidates（breakout pattern）
- `settle_pending_trend` 同 `settle_pending_breakout` 结构，换 TREND_* params + arm="trend"
- 截断检测同 SH5：max_hold exit 且 bars 不足完整持仓期 → 留 hold

### 2.3 `backend/recommendation_engine.py`（trend mock → real arm）

```python
# 现有（删）：
for arm in ("limitup", "trend"):
    recs.append(MultiArmRecommendation(arm=arm, ...MOCK_NOT_READY...))

# 新增（替换 trend 分支）：
recs.append(MultiArmRecommendation(
    arm="trend", honest_label=ArmHonestLabel.EXPLORATORY,
    action_type="paper_track",
    coverage_rate=tj.aggregate_by_arm().get("trend", {}).get("coverage_rate"),
    days_tracked=tj.aggregate_by_arm().get("trend", {}).get("n_days", 0),
    validated=False,
    note="题材/政策趋势驱动（非纯动量），signal 已建但 §44 未验证；"
         "primary 信号（板块 rotation）未测，secondary 因子（个股动量）§44 falsified；"
         "paper tracking 不推荐真金",
))
# limitup 仍 mock_not_ready（signal 未建）
```

- `ArmHonestLabel` 加 `EXPLORATORY = "exploratory"`（§5.3 定义）
- trend 从 mock loop 拆出，独立建 MultiArmRecommendation（含 tj.aggregate_by_arm 统计）
- limitup 留在 mock loop（signal 生成器确实未建）

### 2.4 `backend/candidate_funnel/evaluation.py`（DIM_ARM_MAP + registry）

```python
DIM_ARM_MAP["trend"] = ["trend_swing"]  # 从 None 改为 dimension

DIMENSION_LIFT_REGISTRY["trend_swing"] = DimensionValidation(
    dimension_id="trend_swing", label="趋势波段(板块rotation)",
    lift=1.0, n=0, days_robust=0,
    validation_status="探索性", weight_multiplier=0.5,  # §44 v2: <60 days → ×0.5
    source_script="(未跑，待 S182 §44 harness)",
    note="板块级 rotation 信号，§44 未测；days_robust=0 → provisional ×0.5 cap",
)
```

- lift_for_arm("trend") → (0.5, "trend_swing 最保守（provisional cap, §44 未测）")
- PaperPortfolio.final_size("trend", ...) → arm_size × 0.5（provisional cap 咬合）
- 当前空转（trend paper_track 不 sizing 真金），前瞻 §44 跑后更新 lift + days_robust

### 2.5 `frontend/src/components/recommendation/MultiArmPanel.tsx`

```typescript
// verdictCls 加：
if (label === "exploratory") return "bg-yellow-500/15 text-yellow-600";
// verdictText 加：
if (label === "exploratory") return "探索性·未验证";
```

- 1 行 cls + 1 行 text，最小改动
- trend 卡显黄色 badge（介于 floor 蓝 externally_validated 与 breakout 红 falsified 之间）
- action_type="paper_track" 已有渲染分支（:100-103），trend 卡显"paper tracking · 不推荐真金"

## 3. 依赖序

```
（已存在，复用）
  sector_cycle.py（aggregate_sectors, classify_phase, sector_rotation）
  pattern_scan.py（get_sector_stocks, load_industry_map, scan_patterns）
  market_scan.py（build_non_limitup_candidates, compute_sector_stock_rank_map）
  non_limitup_funnel.py（run_non_limitup_funnel）
  funnel/aggregation.py（score_candidates）
  market.py（_sectors → sector_fund_flow）
  accounting.py（path_return, _cost_pct, COMMISSION_MIN_YUAN）
  engine/*（Executor, T1OpenFill, TradeJournal, PaperPortfolio）
  evaluation.py（DIM_ARM_MAP, lift_for_arm）
    ↑
（新建）
  strategies/trend_swing_arm.py（signal generator，依赖上方全部）
    ↑
（改）
  strategies/journal_recorder.py（_process_trend + settle_pending_trend + DEFAULT_ARMS）
    ↑
（改）
  recommendation_engine.py（trend mock → real EXPLORATORY arm）
  candidate_funnel/evaluation.py（DIM_ARM_MAP + registry trend entry）
    ↑
（改）
  frontend MultiArmPanel.tsx（verdictCls/Text 加 exploratory）
    ↑
（新建测试）
  tests/test_trend_swing_arm.py（signal generator + journal _process_trend）
```

- 不改 sector_cycle / pattern_scan / market_scan / non_limitup_funnel / accounting / engine（只复用）
- 不改 scheduled_tasks（cron 接线后续 plan 决定，本 spec 只建工具）
- 不改 vr_paths（不写私有数据文件，state 全在 trade_journal.db）

## 4. 数据流

```
盘后 T 跑（run_daily target_date=T-1，T1OpenFill 在 T 成交）：

select_trend_candidates(T-1)
  ├─ _identify_trending_sectors(T-1)
  │   ├─ sector_cycle.aggregate_sectors(T-1) → [{industry, zt_count, zt_momentum}]
  │   ├─ classify_phase(count, avg_3d) → 启动/发酵 sectors
  │   └─ market._sectors() → sector_fund_flow → net inflow > 0 筛
  │   → top 5 trending sectors
  ├─ build_non_limitup_candidates(top, industry_map, cache, per_sector=20)
  │   → [{code, name, bars, sector, sector_rank, close}]
  ├─ run_non_limitup_funnel(candidates, ...) → + pattern scan
  ├─ score_candidates(produced, None, "market_scan") → scored
  └→ scored[:5] → 5 candidates

_process_trend(T-1)
  per candidate:
    ├─ Trades(code, signal_date=T-1, fill_type=T1OpenFill, size=100)
    ├─ Executor.execute(T1OpenFill) → entry_price (T open)
    ├─ path_return(filled, bars, stop=-6%, take=+15%, max_hold=10, apply_cost=True)
    │   ├─ None → JournalRecord(arm="trend", exit_reason="hold", is_realized=0)
    │   └→ PathReturn → JournalRecord(arm="trend", exit_reason, is_realized=1, net_pnl, cost_pct)
    └─ trade_journal.insert()

settle_pending_trend()（盘后 T 跑，重算昨日 'hold'）
  query is_realized=0 arm="trend" exit_reason="hold"
  → bars 增长后 path_return 重算
  → INSERT OR REPLACE 同 signal_id 更新 is_realized=1

recommendation_engine get_multi_arm_recommendations()
  trend: EXPLORATORY paper_track + tj.aggregate_by_arm("trend") stats
```

## 5. 测试策略

- **离线单测**（mock sector_cycle + market + kline cache）：
  - `test_trend_swing_arm`：mock aggregate_sectors 返固定 sector list + mock classify_phase → 验 _identify_trending_sectors 筛 启动/发酵 + fund flow 正 → top sectors 正确
  - mock build_non_limitup_candidates + run_non_limitup_funnel + score_candidates → 验 select_trend_candidates 返 top N 带正确 shape
  - `test_journal_recorder_trend`：mock bars_provider（A股 mock bars 延伸到 T+2+max_hold=12）→ _process_trend 产 realized（net_pnl 非 None, cost_pct 非 0）+ hold（bars 不足）+ unbuyable（涨停）
  - settle_pending_trend：hold → bars 增长 → INSERT OR REPLACE 同 signal_id → is_realized=1
  - VR_DATA_DIR 隔离（conftest.py tmp 目录）
- **不破坏现有**：`pytest -m "not live"` 全绿（A7）+ `npx tsc --noEmit` 零错误（A8）
- **联网验收**（手动跑，不进 pytest）：`select_trend_candidates(prev_trading_date)` 返真实 candidates 非空（A4）
