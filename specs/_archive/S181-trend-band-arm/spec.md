# Spec: S181 — 趋势波段臂（B 臂，替代搁置 ash-mcp）

> 状态：已实现（2026-09-11，骨架 653d83e + TDD b234446 全绿）
> 作者：lzw9560  日期：2026-09-10
> 关联：S172-红利低波指数复制臂（A 臂 floor 范式）；S175-模拟盘自洽闭环（多臂框架+PaperPortfolio）；S173-TradeJournal闭环（journal_recorder _process_* 范式）；expert-round-portfolio-overlay（#2 趋势波段臂设计）；expert-round-opensource-practitioner（动量 A 股无效纠偏）；gap-edge-net-negative-after-cost（gap 唯一 edge 破灭，趋势替代短线方向）
>
> 分级：**large**（碰交易信号 + 趋势因子 + 多臂接入，走完整 SDD + grill + feature 分支）
> 本文件命名为 `spec.md`，放在 `specs/S181-趋势波段臂/` 子目录下。
> 同目录附 `plan.md`（技术方案）/ `tasks.md`（任务拆分）。

## 1. 问题 / 目标

gap 扣成本 net 负（north-star 唯一 edge 破灭），打板选股层 §44 全 falsified，ash-mcp 自复制 B 臂搁置（5 元佣金击穿）。短线方向（gap/打板）扣成本不赚钱后，需要一个**波段趋势**方向作 B 臂替代——题材/政策驱动的板块轮动，非纯价格动量（动量 A 股 §44 已 falsified）。

一句话：建一个 paper_track 的趋势波段信号生成器，接入多臂框架（替代 trend mock 槽），用板块轮动 + 资金流识别 trending sectors，复用 non_limitup_funnel 选股 + path_return 扣诚实成本，§44 未验标探索性。

## 2. 背景

### 2.1 为什么不是纯动量

memory `expert-round-opensource-practitioner` + `grill-reframe-final-verdict`：纯价格动量在 A 股 §44 全 falsified（breakout lift 1.36x <2x，gene_score rho≈0.03 null，turnover lift<1）。趋势波段臂的 edge 假设不在个股动量，而在**板块轮动 timing**——哪个题材/政策正在启动，资金正在流入哪个行业。这是不同的机制（sector rotation vs stock momentum），§44 未测过板块级信号。

### 2.2 现有基建可复用（grep 确认，非臆造）

| 模块 | 函数 | 用途 | 状态 |
|---|---|---|---|
| `strategies/sector_cycle.py` | `aggregate_sectors(date)`, `aggregate_concepts(date)`, `sector_rotation(date)`, `concept_rotation(date)`, `classify_phase(count, avg_3d, has_history)` | 板块/概念周期阶段分类（启动/发酵/高潮/退潮/冷门）+ 轮动检测 | 已实现（S066） |
| `strategies/pattern_scan.py` | `get_sector_stocks(industry_name, industry_map)`, `load_industry_map()`, `scan_patterns(code, bars, sector_bars)` | 板块成分股（baostock 5540 只 84 行业）+ 形态扫描 | 已实现（S066 P2） |
| `strategies/market_scan.py` | `build_non_limitup_candidates(top_sectors, industry_map, cache, per_sector)`, `compute_sector_stock_rank_map(...)` | 热门板块 → 成分股 → 候选 shape {code,name,bars,sector,sector_rank,close} | 已实现（S094 T8） |
| `strategies/non_limitup_funnel.py` | `run_non_limitup_funnel(candidates, weather_state, sector_rank_map)` | 候选 + 形态扫描 + 策略分 → scored candidates | 已实现（S066 P2-3） |
| `strategies/funnel/aggregation.py` | `score_candidates(produced, weather_state, funnel_type)` | 统一打分 + check_quality 闸 | 已实现（S094 T16） |
| `market.py` | `_sectors()` → `data.sources.eastmoney.sector_fund_flow()` | 行业板块资金流（净流入/流出） | 已实现（S085 A5） |
| `engine/accounting.py` | `path_return(trades, bars, stop_pct, take_profit_pct, max_hold_days, apply_cost)`, `_cost_pct(entry, size, entry_date)`, `COMMISSION_MIN_YUAN=5.0` | 可平仓臂 path return + 诚实成本（5 元 min + 印花 + slippage 0.70%） | 已实现（S162 R1） |
| `strategies/journal_recorder.py` | `JournalRecorder.run_daily(target_date, arms)`, `_process_breakout(target_date)`, `settle_pending_breakout()`, `DEFAULT_ARMS=["floor","breakout"]` | orchestrator 顺序管线，breakout 臂 path_return 范式 | 已实现（S173/S175） |
| `recommendation_engine.py` | `ArmHonestLabel`, `MultiArmRecommendation`, `get_multi_arm_recommendations()` | 多臂推荐框架（trend 当前 mock_not_ready 占位） | 已实现（S175 R9） |
| `candidate_funnel/evaluation.py` | `DIM_ARM_MAP`, `lift_for_arm(arm)`, `DIMENSION_LIFT_REGISTRY` | arm→dimension 映射 + lift sizing（trend 当前 None→1.0 cap 不作用） | 已实现（S180 R3） |
| `engine/paper_portfolio.py` | `PaperPortfolio.equity()`, `PaperPortfolio.final_size(arm, arm_size, lift_multiplier)` | 多臂 sizing 读 equity + lift cap | 已实现（S175 R10） |

**关键发现**：`routers/strategy.py:258` 已有 `/api/strategy/non-limitup-funnel` 端点跑完整 pipeline（sector_rotation → build_non_limitup_candidates → run_non_limitup_funnel → score_candidates）。trend 臂可**复用**这套 pipeline，只在 sector 选择步骤注入 rotation phase + fund flow 复合排序（替代纯 zt_count 排序）。

### 2.3 成本诚实（gap 教训）

memory `gap-edge-cost-never-wired`：gap 三脚本成本不一致（0.40/0.70/0%），accounting 5 元 min 未接线。trend 臂**必须**走 `path_return(apply_cost=True)`——与 breakout 臂同路径，`_cost_pct` 含 ROUND_TRIP_COST_PCT(0.70) + 印花(0.05%) + 佣金(5元×2/notional×100)。不自造成本函数，不绕过 accounting。

### 2.4 不做什么

- **不做 §44 验证**：本 spec 只建 signal generator + paper_track 接入。§44 harness（板块级 day_paired_lift）另 spec。
- **不做实盘**：trend 是 paper_track（action_type="paper_track"），不推荐真金。0% 分配（floor-heavy 设计：ETF 50-60% + trend 0% paper）。
- **不做 fork non_limitup_funnel**：复用现有 pipeline，不 reimplement 形态扫描/打分逻辑（DRY）。

## 3. 需求清单

- [ ] R1 **signal generator**：`select_trend_candidates(date)` → top N 候选（{code, name, sector, sector_rank, pattern, strategy_score}），复用 build_non_limitup_candidates + run_non_limitup_funnel + score_candidates pipeline
- [ ] R2 **trending sector 识别**：`_identify_trending_sectors(date)` → 板块周期阶段（启动/发酵）+ 资金净流入 + zt 动量复合排序 → top sectors（区别于 sector_rotation 纯 zt_count 排序）
- [ ] R3 **journal_recorder 接入**：`_process_trend(target_date)` 方法——select → Trades → Executor.execute(T1OpenFill) → path_return(apply_cost=True) → trade_journal.insert(arm="trend")；DEFAULT_ARMS 加 "trend"
- [ ] R4 **settle_pending**：`settle_pending_trend()`——重算昨日未平 'hold'（仿 settle_pending_breakout，TREND_* params），bars 增长后 INSERT OR REPLACE 同 signal_id
- [ ] R5 **swing trade 参数**：stop=-6%, take=+15%, max_hold=10（2 周 swing，wider than breakout -4%/+8%/3d）——§44 未验 paper params
- [ ] R6 **honest_label**：新增 `ArmHonestLabel.EXPLORATORY`（"探索性·未验证"——signal 已建，§44 未跑，非 mock 非 falsified 非 dead）；recommendation_engine trend 分支从 mock loop 拆出独立建，action_type="paper_track"
- [ ] R7 **lift/sizing 接线**：DIM_ARM_MAP trend → ["trend_swing"]，DIMENSION_LIFT_REGISTRY 加 trend_swing 维度（days_robust=0 → provisional ×0.5 cap，§44 v2 规则）；PaperPortfolio.final_size("trend", ...) 咬合
- [ ] R8 **前端**：MultiArmPanel.tsx verdictCls/verdictText 加 "exploratory" → 黄色 badge "探索性·未验证"；trend 卡显 paper_track（已有渲染分支）
- [ ] R9 不破坏现有功能（现有 pytest -m "not live" 全绿 + npx tsc --noEmit 零错误）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/trend_swing_arm.py` | **新建**。signal generator（select_trend_candidates + _identify_trending_sectors）+ trend_arm_status + trend_arm_report |
| `backend/strategies/journal_recorder.py` | **改**。加 `_process_trend` + `settle_pending_trend`；DEFAULT_ARMS 加 "trend"；加 TREND_STOP_PCT/TREND_TAKE_PCT/TREND_MAX_HOLD 常量 |
| `backend/recommendation_engine.py` | **改**。trend 从 mock loop 拆出独立分支（EXPLORATORY + paper_track + tj.aggregate_by_arm stats）；ArmHonestLabel 加 EXPLORATORY |
| `backend/candidate_funnel/evaluation.py` | **改**。DIM_ARM_MAP trend → ["trend_swing"]；DIMENSION_LIFT_REGISTRY 加 trend_swing 维度 |
| `frontend/src/components/recommendation/MultiArmPanel.tsx` | **改**。verdictCls/verdictText 加 "exploratory" 映射 |
| `backend/strategies/sector_cycle.py` | **不改**（复用 aggregate_sectors/classify_phase/sector_rotation） |
| `backend/strategies/non_limitup_funnel.py` | **不改**（复用 run_non_limitup_funnel） |
| `backend/strategies/market_scan.py` | **不改**（复用 build_non_limitup_candidates） |
| `backend/engine/accounting.py` | **不改**（复用 path_return + _cost_pct） |
| `backend/engine/paper_portfolio.py` | **不改**（复用 equity + final_size） |
| `backend/scheduled_tasks.py` | **可选后续**（cron 接线 deferred，本 spec 只建工具） |

## 5. 设计方案

### 5.1 Trending sector 识别（trend 臂核心，唯一新颖逻辑）

现有 `sector_rotation(date)` 按 zt_count_today 排序——是"今天涨停最多的板块"。trend 臂要的是"正在进入上升趋势的板块"（启动/发酵阶段 + 资金流入），不同：

```
_identify_trending_sectors(date):
  1. sector_cycle.aggregate_sectors(date) → [{industry, zt_count_today, zt_momentum, ...}]
  2. per sector: classify_phase(zt_count_today, avg_3d) → phase + multiplier
     - "启动" → 1.1（加速）
     - "发酵" → 1.0（正常升温）
     - "高潮" → 0.9（可能见顶，不追）
     - "退潮" → 0.5（排除）
     - "冷门"/"无历史" → 排除
  3. market._sectors() → sector_fund_flow → per industry net inflow（亿）
  4. composite_score = phase_multiplier × (1 + fund_flow_sign) × max(zt_momentum, 0.1)
     - fund_flow_sign = 1 if net>0 else 0.5（资金流出降权不排除，趋势可能中继）
  5. filter: phase in ["启动","发酵"] + fund_flow_sign>0 → trending sectors
  6. rank by composite_score desc → top TREND_TOP_SECTORS（默认 5）
```

**OQ1**：composite formula 是默认提案——用户确认或调整权重。备选：加 newsradar 政策/新闻关键词匹配（需新基建，YAGNI 暂不建）。

### 5.2 Stock selection（复用 non_limitup_funnel pipeline）

```
select_trend_candidates(date):
  1. _identify_trending_sectors(date) → top 5 trending sectors
  2. market_scan.build_non_limitup_candidates(top, industry_map, cache, per_sector=20)
     → [{code, name, bars, sector, sector_rank, close}]
  3. non_limitup_funnel.run_non_limitup_funnel(candidates, weather_state=None, sector_rank_map)
     → + pattern scan (relative_strength, ma_bullish, volume_signal, sector_strength)
  4. funnel.aggregation.score_candidates(produced, None, "market_scan")
     → scored candidates
  5. scored[:TREND_TOP_N] → top N（默认 5）候选
```

**复用而非 fork**：trend 臂不 reimplement 形态扫描/打分。唯一差异是 step 1 的 sector 选择（rotation phase + fund flow vs 纯 zt_count）。

**OQ2**：non_limitup_funnel 的 4 因子（relative_strength/ma_bullish/volume_signal/sector_strength）本质是价格动量——memory 说动量 A 股 §44 falsified。但 trend 臂用它们做**二次确认**（primary 信号是板块轮动 timing，stock-level 是 secondary filter），不是 primary edge。是否接受用 §44-falsified 因子做 secondary？备选：trend 臂自建非动量因子（如资金流净流入个股、龙虎榜机构席位），但需新基建。

### 5.3 ArmHonestLabel 新增 EXPLORATORY

现有 enum（recommendation_engine.py:206-211）：
- EXTERNALLY_VALIDATED（floor，外部三重定论）
- SECTION44_FALSIFIED（breakout，§44 证否）
- MOCK_NOT_READY（limitup，signal 未建）
- DEAD_ARM（gap，不推荐）

新增 `EXPLORATORY = "exploratory"`（探索性·未验证）——signal generator 已建，§44 未跑，不能标 falsified（没测过）；不能标 externally_validated（无外部定论）；不标 mock（generator 已建）。准确反映 trend 当前状态。

**OQ3**：是否新增 enum vs 复用 MOCK_NOT_READY 改 note。默认新增（诚实——generator 已建不是 mock）。

### 5.4 Trade mechanics（path_return + 诚实成本）

```
TREND_STOP_PCT = -6.0      # swing 容忍更大回撤（vs breakout -4%）
TREND_TAKE_PCT = 15.0       # swing 目标更大涨幅（vs breakout +8%）
TREND_MAX_HOLD = 10         # 2 周持仓期（vs breakout 3 天）
```

走 `path_return(trades, bars, stop_pct=-6, take_profit_pct=15, max_hold_days=10, apply_cost=True)`——与 breakout 同路径，`_cost_pct` 含 5 元 min 佣金 + 印花 + 0.70% slippage。

**OQ4**：swing 参数（-6%/+15%/10d）是 paper 默认提案——用户确认或调整。§44 未验，仅 paper_track。

### 5.5 journal_recorder _process_trend（仿 _process_breakout）

```
_process_trend(target_date):
  candidates = select_trend_candidates(target_date)
  per candidate:
    bars = bars_provider(candidate.code)
    trades = Trades(code, signal_date=target_date, fill_type=T1OpenFill, size=100)
    filled = executor.execute(trades, bars, T1OpenFill())
    if not filled.is_accepted():
      → JournalRecord(arm="trend", exit_reason="unbuyable", is_realized=1)
    pr = path_return(filled, bars, -6, 15, 10, apply_cost=True)
    if pr is None:
      → JournalRecord(arm="trend", exit_reason="hold", is_realized=0)  # T+1 guard
    else:
      net_pnl = pr.return_pct/100 × (entry_price × 100)
      → JournalRecord(arm="trend", exit_reason=pr.exit_reason, is_realized=1,
                       net_pnl, cost_pct=pr.cost_pct, gross_return=pr.gross_return_pct)
```

- arm="trend"，与 breakout 同走 path_return 分轨（C2 成本分轨）
- settle_pending_trend() 仿 settle_pending_breakout()，T+2+ bars 增长后重算 'hold'
- DEFAULT_ARMS 从 ["floor","breakout"] 改 ["floor","breakout","trend"]

### 5.6 recommendation_engine trend 分支（拆出 mock loop）

现有（recommendation_engine.py:293-299）trend 在 mock loop 里。改为独立分支：

```python
# trend：EXPLORATORY paper_track（signal 已建，§44 未验）
try:
    trend_stats = tj.aggregate_by_arm().get("trend", {})
    recs.append(MultiArmRecommendation(
        arm="trend", honest_label=ArmHonestLabel.EXPLORATORY,
        action_type="paper_track",
        coverage_rate=trend_stats.get("coverage_rate"),
        days_tracked=trend_stats.get("n_days", 0),
        validated=False,
        note="题材/政策趋势驱动（非纯动量），signal 已建但 §44 未验证；"
             "primary 信号（板块 rotation）未测，secondary 因子（个股动量）§44 falsified；"
             "paper tracking 不推荐真金",
    ))
except Exception as e:
    recs.append(MultiArmRecommendation(
        arm="trend", honest_label=ArmHonestLabel.EXPLORATORY,
        action_type="paper_track", note=f"trend stats 不可得: {e}",
    ))
# limitup 仍留 mock loop（signal 未建）
for arm in ("limitup",):
    recs.append(MultiArmRecommendation(arm=arm, ...MOCK_NOT_READY...))
```

### 5.7 lift/sizing 接线

`evaluation.py` DIM_ARM_MAP: `"trend": None` → `"trend": ["trend_swing"]`

DIMENSION_LIFT_REGISTRY 加：
```python
"trend_swing": DimensionValidation(
    dimension_id="trend_swing", label="趋势波段(板块rotation)",
    lift=1.0, n=0, days_robust=0,
    validation_status="探索性", weight_multiplier=0.5,  # §44 v2: <60 days → ×0.5
    source_script="(未跑，待 §44 harness)",
    note="板块级 rotation 信号，§44 未测；days_robust=0 → provisional ×0.5 cap",
)
```

- `lift_for_arm("trend")` → (0.5, "trend_swing provisional cap")
- `PaperPortfolio.final_size("trend", arm_size, 0.5)` → arm_size × 0.5（咬合）
- 当前空转（trend paper_track 不 sizing 真金，0% 分配）；前瞻 §44 跑后更新 lift + days_robust

### 5.8 备选方案为何不选

- **ash-mcp 自复制 smart-beta**：5 元佣金击穿（S172 §2.2 成本对比），搁置。
- **纯价格动量臂**：§44 全 falsified（breakout/gene_score/turnover），不造已证否的轮子。
- **fork non_limitup_funnel**：reimplementation drift，DRY 原则下复用。
- **实盘 trend**：§44 未验，paper_track 先攒 60 天数据再复验。

## 6. 验收标准

- [ ] A1 `select_trend_candidates(prev_trading_date)` 返 ≤5 候选，每个含 {code, name, sector, sector_rank, pattern, strategy_score}（联网验收）
- [ ] A2 `_identify_trending_sectors(date)` 返 top sectors，phase 含"启动"/"发酵"（非纯 zt_count 排序）
- [ ] A3 `JournalRecorder._process_trend(target_date)` 产 trade_journal 记录（arm="trend"，is_realized=1 的有 net_pnl + cost_pct ≠ 0，is_realized=0 的 exit_reason="hold"）
- [ ] A4 `settle_pending_trend()` 重算昨日 'hold' → bars 增长后 INSERT OR REPLACE 同 signal_id 更新 is_realized=1
- [ ] A5 `get_multi_arm_recommendations()` 返 trend=EXPLORATORY paper_track（非 mock_not_ready），含 coverage_rate + days_tracked
- [ ] A6 `lift_for_arm("trend")` 返 (0.5, ...)（provisional cap 咬合，非 1.0）
- [ ] A7 `pytest -m "not live"` 全绿（不破坏现有）+ `npx tsc --noEmit` 零错误
- [ ] A8 trend 仓位 action_type="paper_track"，前端 MultiArmPanel 显黄色 "探索性·未验证" badge
- [ ] A9 成本走 `path_return(apply_cost=True)`，cost_pct 含 5 元 min 佣金（grep 确认无自造成本函数）

## 7. 合规与工程底线自查（逐条确认）

- [x] **研判/推荐/买卖时机**：trend 臂给 paper_track 信号（§44 未验），不推荐真金（action_type="paper_track"）。属系统能力（2026-07-30 新口径）。用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」。
- [x] **判断可复现**：sector_cycle + market 数据均为公开数据（板块涨停数/资金流），可复算。path_return 成本用标准 `_cost_pct` 口径，禁臆造/心算。§44 未验诚实标注 EXPLORATORY，不假装 validated。
- [x] **涨停四池/连板股榜**：trend 臂用 sector_cycle 的 aggregate_sectors（涨停板块聚合，非个股推荐）。板块涨停数是客观市场广度，非个股榜单。
- [x] **用户私有数据隔离**：trend paper 仓位写 trade_journal.db（`.vibe-research/`，gitignored，见 vr_paths.resolve_data_dir()）。不进 git。
- [x] **新增东财端点走 `em_get`**：trend 臂复用 market._sectors() → sector_fund_flow（已走 eastmoney.sector_fund_flow，走 em_get 限流，S085 A5 已接线）。无新增裸调 requests。

**弱合规定位**：私人投研助理，paper_track 不涉真金，工程底线（不臆造/私有数据隔离/防封）全部确认通过。

## 8. 测试计划

- **离线单测**（mock sector_cycle + market + kline cache）：
  - `test_trend_swing_arm`：mock aggregate_sectors 返固定 sector list + mock classify_phase → 验 _identify_trending_sectors 筛 启动/发酵 + fund flow 正 → top sectors 正确
  - mock build_non_limitup_candidates + run_non_limitup_funnel + score_candidates → 验 select_trend_candidates 返 top N 带正确 shape
  - `test_journal_recorder_trend`：mock bars_provider（A股 mock bars 延伸到 T+2+max_hold=12）→ _process_trend 产 realized（net_pnl 非 None, cost_pct 非 0）+ hold（bars 不足）+ unbuyable（涨停）
  - settle_pending_trend：hold → bars 增长 → INSERT OR REPLACE 同 signal_id → is_realized=1
- **不破坏现有**：A7 全量 `pytest -m "not live"` 绿 + `npx tsc --noEmit` 零错误
- **联网验收**（手动跑，不进 pytest）：A1/A2 跑真实 sector_cycle + market 数据

## 9. 风险与回滚

| 风险 | 影响 | 回滚 |
|---|---|---|
| 板块轮动 timing 无 edge（§44 跑后 falsified） | trend 臂成 dead_arm | 标 SECTION44_FALSIFIED + DEAD_ARM，保留录数据不参与聚合（同 gap） |
| non_limitup_funnel 因子（动量）§44 已 falsified，secondary 也无效 | trend 选股无 edge | primary（板块 rotation）仍可能有效；若也无效 → 全 falsified |
| TREND_* params（-6%/+15%/10d）不合理 | paper PnL 失真 | 参数是 paper，§44 跑后校准；回滚 = 改 params 重跑 |
| sector_cycle 依赖涨停池数据（涨停少时 trending sectors 空） | select_trend_candidates 返空 | 降级：扩大 phase 筛选含"高潮"或 fallback 到 sector_rotation zt_count 排序 |
| settle_pending_trend max_hold=10 需 12 天 bars（T+2+10） | bars 不足时长期 hold | 同 settle_pending_breakout 截断检测，留 hold 等更多 bars |
| DEFAULT_ARMS 加 "trend" 后 run_daily 变慢 | 定时任务延迟 | trend 在 breakout 之后跑（顺序），若慢可从 DEFAULT_ARMS 拆出单独 cron |

---

> 本 spec 只写规范，不写实现代码。下一步：plan.md（技术方案）→ tasks.md（任务拆分）→ grill（≥6 视角对抗）→ 实现 → 验收。SDD §0 不跳。
> §44 harness（板块级 rotation 信号验证）另 spec，不在本 spec 范围。