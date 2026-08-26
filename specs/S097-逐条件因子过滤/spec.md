# Spec: S097 — 逐条件因子过滤

> 状态：草案
> 作者：Claude 会话  日期：2026-08-26
> 级别：medium（跨层 backend match() + frontend 渲染；不碰外部数据源 / 不新增 AI 工具 / 不涉财务验算）
> 流程门：spec.md（S094:304 预留"待开独立 spec"）+ issue 层单轮 review；直接 develop（免 feature 分支 / 免完整 grill）
> 依赖：S094 主体已实现（12 战法 impl + dispatch_match + score_candidates 已就位）
> 关联：S094（②⑦分组视图载体）、S066（CandidateProgressiveCard L2 因子区可消费本契约）、S096（p2_fired_rule 类比）

## 1. 问题 / 目标

12 战法 `match()` 统一返回 `list[ConditionMatch]`（3 字段 condition/value/description），**只记命中项**：
- 10 战法"全有或全无"（多子条件合 1 个 ConditionMatch，未命中返 `[]`，不拆子条件、不记未命中）
- 2 战法（weak_turn_strong/pattern_reversal）"部分命中"（≥N 因子输出，只 append 命中因子，未命中丢弃）
- **无"输入数/过滤后数"批次漏斗**（match() 是单只函数，批次聚合要调度层）

**目标**：拆 12 战法条件到因子级 + 三态分立（hit/miss/data_unavailable）+ 并联批次聚合 + 前端每战法子管线渲染「条件→输入数→命中数→命中率」漏斗 + 候选行条件命中标记。让用户看清"每战法每条件过滤了多少只"，且数据缺失（limitup 路径无 market_scan_ctx）不混进逻辑过滤。

## 2. 背景

- **12 战法 impl**：`backend/strategies/impl/{gene_based,indicator_based,db_based,pool_based}.py`，统一协议 `strategy_base.StrategyProtocol.match(ctx) -> list[ConditionMatch]`
- **ConditionMatch**（`strategy_base.py:34`）：`condition/value/description` 3 字段，仅命中项
- **dispatch_match**（`strategy_base.py:219`）：遍历注册表调 `impl.match(ctx)`，`if not matches: continue`，组装 `StrategySignal`
- **compute_confidence**：weak_turn_strong/pattern_reversal 用 `len(matches)`；其他 10 战法固定值
- **score_candidates**（`strategy_funnel_registry.py:490`）：按 funnel_type 分流，透传 `score_breakdown`/`confidence`/`signal_strength`
- **S094:304 预留**：明确"12 战法 match() 重构返回条件级过滤明细（每条件 输入数/过滤后数/条件描述），前端每战法子管线渲染因子条件→过滤数明细漏斗。待开独立 spec（预计 medium，跨层）"
- **S096 p2_fired_rule**：P2 市场情绪"为何此 tier"单字符串——S097 借鉴"给原因"思路，但结构化（每条件 state 而非单字符串）
- **前端载体**：S094 ②⑦分组视图（`StrategySubPipelineView.tsx`）按战法分组渲染候选行——S097 在此渲染漏斗

## 3. 需求清单

### A. 返回契约（match 层）
- [ ] R1 新增 `ConditionEval` model：`condition_id/condition_name/factor/threshold/actual_value/state(hit|miss|data_unavailable)/description`
- [ ] R2 新增 `StrategyMatchResult` model：`strategy_code/strategy_name/conditions(list[ConditionEval])/hit_count/total_count/fired/fire_rule/confidence/data_ok`
- [ ] R3 12 战法 `match()` 改返 `StrategyMatchResult`（替代 `list[ConditionMatch]`），全量条件评估（命中+未命中+数据降级）
- [ ] R4 拆 10 个"全有或全无"战法的多子条件为独立 ConditionEval（见 §5.2 条件表）
- [ ] R5 weak_turn_strong/pattern_reversal 补未命中因子（现只 append 命中）

### B. 三态分立（数据降级 vs 逻辑未命中）
- [ ] R6 `state=data_unavailable`：战法数据前置缺失（dragon_head 无 pattern / reverse_package 炸板池DB缺失 / low_absorption 无 pattern 等）→ `data_ok=False`，conditions 全 data_unavailable，fired=False（诚实降级，不算逻辑未命中）
- [ ] R7 批次聚合 `data_unavailable_count` 单列（前端漏斗"数据缺失 N 只"独立，不算逻辑过滤）

### C. 批次聚合（调度层）
- [ ] R8 `dispatch_match` 适配：`result = impl.match(ctx)` → `if not result.fired: continue`（替代 `if not matches`）；**StrategySignal 保持兼容结构不改**（`matches` 字段类型不变 list[ConditionMatch]，避免破坏 limitup_strategy 7+ 消费方：strategy_matcher/pre_market_workflow/strategy_backtest/prediction_ingest/position_advisor_v2/前端）；dispatch_match 从 result 提取：`matches` 字段存命中项 ConditionMatch shape（condition/value/description 从 ConditionEval 映射），加可选 `strategy_match_result` 新字段存完整 result；`logic_description`/`reasoning` 用 result.conditions 的 description
- [ ] R9 `compute_confidence` 在 match() 内算（填 `result.confidence`），dispatch_match 直接用 `result.confidence` 不再调 `impl.compute_confidence(matches, ctx)`（strategy_base.py:238）；`compute_confidence` 方法保留兼容（不删，防外部调用）但 dispatch_match 不再依赖。weak_turn_strong/pattern_reversal 用 `result.hit_count` 算 confidence；其他 10 战法固定值不变
- [ ] R10 `score_candidates` 批次聚合产出 `StrategyFunnelSummary`（每战法每条件 input_count/passed_count/data_unavailable_count/pass_rate + 候选命中标记），透传前端
- [ ] R11 **并联独立**：input_count = 该战法评估候选总数（非顺序串联），passed_count = 命中数——适用全条件命中 + ≥N/M 两类触发规则

### D. 前端契约
- [ ] R12 `StrategySubPipelineView` 渲染漏斗：战法触发率 → 逐条件（input→passed+data_unavailable→pass_rate）→ 候选行条件命中标记
- [ ] R13 `StrategyFunnelSummary` TS 类型 + `ScoredCandidate` 加可选 `strategy_funnel` 字段（存本战法批次漏斗 + 候选命中标记）；briefing 透传

### E. 处置与兼容
- [ ] R14 n_shape_counterattack `condition` 标签去"放量"（`gene_based.py:139` `condition="N字形态+放量"` → `condition="N字区间"`；description 字段已无放量；§5.2 condition_name="N字区间" 已落地）
- [ ] R15 历史快照兼容：旧 scored_candidates 快照无 conditions/strategy_funnel → 前端降级不显漏斗（只显 score）；新快照含
- [ ] R16 12 战法 match() 测试更新（返回结构变）
- [ ] R17 `scored_candidates` 每项加 `strategy_funnel` 字段（`StrategyFunnelSummary`：该战法批次漏斗 input/passed/data_unavailable/pass_rate + 候选命中标记）；`score_candidates` 批次聚合产出

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/strategy_base.py` | 新增 ConditionEval + StrategyMatchResult model；dispatch_match 适配 fired；compute_confidence 签名 |
| `backend/strategies/impl/gene_based.py` | 8 战法 match() 拆条件返 StrategyMatchResult |
| `backend/strategies/impl/indicator_based.py` | 2 战法（weak_turn_strong/pattern_reversal）补未命中 |
| `backend/strategies/impl/db_based.py` | reverse_package match() 拆 |
| `backend/strategies/impl/pool_based.py` | storm_reversal match() 拆 |
| `backend/strategies/strategy_funnel_registry.py` | score_candidates 批次聚合 StrategyFunnelSummary + 透传 |
| `frontend/src/components/pipeline/StrategySubPipelineView.tsx` | 渲染漏斗 + 候选命中标记 |
| `frontend/src/lib/api/types.ts` | StrategyFunnelSummary TS 类型 |
| `backend/tests/test_s094_*.py` | match() 返回结构测试更新 |

## 5. 设计方案

### 5.1 返回契约

```python
class ConditionEval(BaseModel):
    condition_id: str        # "first_plate.c1"（战法内唯一）
    condition_name: str      # "基因得分合格"
    factor: str              # "total_score"
    threshold: str          # ">= 60"
    actual_value: str | None
    state: Literal["hit", "miss", "data_unavailable"]
    description: str

class StrategyMatchResult(BaseModel):
    strategy_code: str
    strategy_name: str
    conditions: list[ConditionEval]   # 全量（命中+未命中+数据降级）
    hit_count: int                    # state=hit 数
    total_count: int
    fired: bool                       # 按触发规则
    fire_rule: str                    # "全条件命中" / "≥4/5 命中"
    confidence: float | None
    data_ok: bool                     # 数据前置可用（False=整战法降级不评估）
```

`match()` 返 `StrategyMatchResult`（替代 `list[ConditionMatch]`）。`data_ok=False` 时 conditions 全 `data_unavailable`、fired=False（诚实降级，不算逻辑未命中）。

### 5.2 12 战法条件表

| 战法 | 条件 | 因子 | 阈值 | 触发规则 | 数据前置 |
|---|---|---|---|---|---|
| first_plate | C1 基因合格 | total_score | ≥60 | 全条件命中 | gene |
| | C2 涨停频次 | 涨停频次 | >20 | | |
| consecutive_relay | C1 连板历史 | zt_count_250d | ≥2 | 全条件命中 | gene |
| | C2 封板能力 | 封板率 | ≥60 | | |
| break_reseal | C1 黄金区频次 | zt_count_250d | [3,5] | 全条件命中 | gene |
| | C2 强封板 | 封板率 | ≥80 | | |
| low_absorption | C1 回调MA5 | ma5_proximity | ≤3 | 全条件命中 | pattern |
| | C2 均线多头 | ma_bullish | True | | |
| n_shape_counterattack | C1 N字区间 | zt_count_250d | [2,10] | 全条件命中 | gene |
| platform_breakout | C1 横盘 | consolidation_days | ≥5 | 全条件命中 | pattern |
| | C2 放量突破 | volume_breakout_ratio | >2 | | |
| end_of_day_sneak | C1 尾盘封板 | 封板率 | ≥40 | 全条件命中 | gene |
| | C2 溢价能力 | 次日溢价率 | >40 | | |
| dragon_head | C1 板块领涨 | sector_rank | ≤3 | 全条件命中 | pattern+msc |
| storm_reversal | C1 早盘封板 | fbt | ≤103000 | 全条件命中 | pool_item |
| reverse_package | C1 前日真炸板 | open_count(池成员) | ≥2 含code | 全条件命中 | 炸板池DB |
| weak_turn_strong | C1 连板天数 | lbc | ≥1 | **≥4/5 命中** | pool_item+derived+indicators |
| | C2 炸板时长 | broken_duration_min | ≥20 | | |
| | C3 回撤幅度 | max_drop_pct | ≥5.0 | | |
| | C4 尾盘封死 | last_lock_time | ≥14:40 | | |
| | C5 换手倍数 | vol_ratio_1d | [1.8,3.0] | | |
| pattern_reversal | C1 上影线 | shadow_length_pct | ≥4 | **≥2/3 命中** | pattern |
| | C2 放量 | volume_breakout_ratio | ≥1.2 | | |
| | C3 5日线向上 | ma5_slope | >0 | | |

**触发规则两类**：全条件命中（10 战法，所有条件 hit 才 fired）/ ≥N/M（weak_turn_strong ≥4/5、pattern_reversal ≥2/3）。

### 5.3 三态分立

- **hit**：条件命中
- **miss**：条件未命中（数据可用，逻辑不满足）
- **data_unavailable**：数据前置缺失（不算逻辑过滤）

`data_ok=False`（数据前置缺失）时整战法 conditions 全 data_unavailable，fired=False。批次聚合 `data_unavailable_count` 单列，前端漏斗"数据缺失 N 只"独立显示，不混进逻辑过滤——避免 limitup 路径（无 market_scan_ctx）的 dragon_head/low_absorption 等误显"过滤掉 X 只"。

### 5.4 并联批次聚合

`input_count` = 该战法评估候选总数（非顺序串联），`passed_count` = 命中数，`data_unavailable_count` 单列。适用全条件命中 + ≥N/M 两类触发规则。瓶颈条件靠 `passed_count` 最低反推。

```typescript
interface StrategyFunnelSummary {
  strategy_code: string; strategy_name: string
  fired_count: number; total_count: number
  conditions: Array<{
    condition_id: string; condition_name: string; factor: string; threshold: string
    input_count: number
    passed_count: number
    data_unavailable_count: number
    pass_rate: number
  }>
  candidates: Array<{
    code: string; name: string; fired: boolean
    conditions: Array<{ condition_id: string; state: "hit"|"miss"|"data_unavailable" }>
  }>
}
```

### 5.5 关键设计决策

- **数据降级 vs 逻辑未命中（三态分立）**：limitup 路径无 market_scan_ctx 的 dragon_head/low_absorption 等算 data_unavailable 不算 miss。
- **区间条件粒度**：`[3,5]`/`[2,10]` 作为一个"区间命中"条件（不拆上下界，区间是战法逻辑）。
- **并联统一**：适用所有触发规则，简单不误导。
- **n_shape description 修**：去"放量"（n_shape 是纯基因频次战法）——实为 `condition` 标签去放量（description 已无放量）。

## 6. 验收标准

- [ ] A1 12 战法 match() 返 StrategyMatchResult，全量条件（hit+miss+data_unavailable）
- [ ] A2 dispatch_match 用 result.fired，compute_confidence 用 hit_count
- [ ] A3 score_candidates 产 StrategyFunnelSummary（每条件 input/passed/data_unavailable/pass_rate）
- [ ] A4 前端 StrategySubPipelineView 渲染漏斗 + 候选命中标记
- [ ] A5 数据缺失（limitup 路径）显 data_unavailable 不混 miss
- [ ] A6 12 战法测试更新全绿；2267+ 回归零破坏
- [ ] A7 历史快照兼容（旧无 conditions 降级显 score）

## 7. 合规与工程底线自查

- [ ] 不臆造：data_unavailable 诚实标注数据缺失，不编 miss；条件阈值沿用 S094 不改
- [ ] 私有数据隔离：match 读已有 gene/pattern/pool_item；reverse_package 炸板池 DB 已有（不新增私有数据）
- [ ] em_get 防封：无新增外部端点
- [ ] 研判/推荐：S097 是 UX 过滤明细，非买卖推荐，挂轻量风险提醒

## 8. 测试计划

- `pytest -m "not live" --ignore=tests/test_newsradar_global_intel.py --ignore=tests/test_s032_workflow_state.py --no-cov`
- 12 战法 match() 单测（每战法 hit/miss/data_unavailable 三态 + fired 判定）
- 批次聚合测试（input/passed/data_unavailable 统计 + 并联语义）
- 前端 vitest（漏斗渲染 + 候选命中标记）
- 历史快照兼容测试（旧无 conditions 降级）

## 9. 风险与回滚 + §43 冲突审查

### 9.1 冲突审查表（AGENTS §43）

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S094 R4 match 下沉 volume_signal | match 返 list[ConditionMatch] | 返 StrategyMatchResult（含 conditions） | 共存 | volume_signal 逻辑不变（dispatch_match :247 调 compute_volume_signal，不在 match 返回）；仅返结构扩 |
| limitup_strategy.StrategySignal.matches | list[ConditionMatch] 类型 | **保持兼容不改类型** | 共存 | dispatch_match 从 result 映射 ConditionMatch shape；7+ 消费方（strategy_matcher/pre_market_workflow/strategy_backtest/prediction_ingest/position_advisor_v2/前端）零迁移 |
| S094 R9 dragon_head 条件化 | sector_rank≤3 命中 | C1 板块领涨（sector_rank≤3） | 共存 | 逻辑不变，拆为 ConditionEval |
| S094 R10 3 战法 PatternScan | low_absorption/platform_breakout/pattern_reversal 读 PatternScan | 同 | 共存 | 条件拆为 ConditionEval，因子读 PatternScan 不变 |
| S096 p2_fired_rule | P2 单字符串"为何此 tier" | S097 结构化 conditions | 借鉴 | 不冲突（P2 市场情绪 tier vs S097 战法条件，不同层） |
| S066 CandidateProgressiveCard L2 | L2 因子区待接入 | 可消费 S097 conditions | 衔接 | S097 不强制；CandidateProgressiveCard 接入是独立项（本 spec 不实现） |

### 9.2 风险

- 12 战法 match() 重构面广 → 逐战法 TDD，先 1 战法（first_plate）跑通契约再铺 12
- compute_confidence 签名变 → 波及 dispatch_match 调用链（S094 已统一，影响可控）
- 前端漏斗渲染复杂度 → 先静态漏斗，交互后补
- **C4 pre-existing bug**（weak_turn_strong）：`last_lock_time >= "2026-01-01T14:40"`（indicator_based.py:65）整串 ISO 比较，日期段压倒时间段，C4 近乎恒命中（触发规则从 ≥4/5 退化为 ≥3/4）。S097 拆 C4 后漏斗会显 C4≈100% pass（误导）。处置：S097 不改逻辑（只拆结构），C4 比较修复另开 issue（或 S097 顺手修 `last_lock_time[11:16] >= "14:40"`，待定）

### 9.3 回滚

match() 返结构变是承重改动 → 回滚 = `git revert` S097 commit。旧 `list[ConditionMatch]` 协议可在过渡期共存（dispatch_match 兼容两种返回），降低回滚成本。
