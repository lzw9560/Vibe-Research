# Spec: S084 — 选股池战法解耦（选股池 Tab + 战法 Tab 两级导航 + 因子补全）

> 状态：草案
> 作者：Claude  日期：2026-08-18
> 关联：`CLAUDE.md` §1.1、`specs/S002-打板工作流重构/`（P1 候选池漏斗）、`specs/S070-intraday采集管道/`（R7 派生）、`specs/S079-打板P2战法与仓位闸/`（仓位闸+龙虎榜）、`specs/S081-打板P2战法匹配/`（PRD 2 战法）、`specs/S083-工作流重构选股池分层/`（因子复用部分已 commit ada2b71，漏斗接入部分作废改耦合方向）
>
> **起因**：用户提出"第一步选股池是所有战法的基础，第二步才进入工作流"+"选股池要包含后面战法所需要的所有盘前因子，打造战法坚定基石"+"系统逻辑不要那么复杂，解耦"。当前 `pre_market_workflow.run()` 把选股池筛选+战法匹配+仓位建议串在一个函数里，战法因子散落在 `match_strategies` 各 elif 分支各自取数，与漏斗重复。S083 漏斗接入是耦合方向（漏斗塞进 pre_market_workflow），和用户"解耦"诉求相反，S083 漏斗接入部分作废，保留因子复用部分（ada2b71）。

---

## 1. 问题 / 目标

当前系统的耦合问题：
1. **选股池和战法耦合**：`pre_market_workflow.run()` 把"选股池筛选+战法匹配+仓位建议"串在一个函数里，选股池不独立
2. **战法因子散落**：`match_strategies` 各 elif 分支各自调 astock/kline/S070 取数，选股池没有一站式输出所有战法因子
3. **选股池因子缺口**：战法需要 6 类因子（GeneScore/涨停池原始dict/S070R7派生/前日成交额/K线派生/活跃度），选股池漏斗只采集了部分，战法还要自己补取
4. **前端导航按时间阶段**：Workflow.tsx 按"盘前/盘中/盘后"组织，不是按"选股池/战法"功能组织

**目标**：选股池独立产出 + 战法独立消费 + 前端两级 Tab 导航。选股池 = 漏斗 R1→R2→R3 完整筛选 + 补全所有战法盘前因子（GeneScore/涨停池原始dict/S070R7派生/K线派生/活跃度/资金流），输出 `DiagnosisCard`（含 `gene_score` + `pool_item` + `derived` + `indicators`）。战法从选股池 `DiagnosisCard` 读全部因子，不自己取数。前端 Workflow.tsx 加"选股池"Tab + "战法"Tab 两级导航。

---

## 2. 背景

### 2.1 战法因子缺口分析（grill 核实）

11 个短线战法需要的盘前因子 vs 漏斗已采集字段：

| 因子 | 哪些战法用 | 漏斗是否有 | 缺口来源 |
|---|---|---|---|
| GeneScore（total_score/zt_count_250d/factors/封板率/次日溢价率/涨停频次） | 既有 9 战法全部 | ❌ gene.py 只存 gene_score 数字，丢完整对象 | limitup_screener（漏斗 R1 已调但只存数字） |
| 涨停池原始 dict（lbc/zdp/fbt/zbc） | 弱转强+形态反包 | ❌ 漏斗不含 | astock.em_zt_topic_pool（涨停池） |
| S070 R7 分时派生（broken_duration/max_drop/last_lock） | 弱转强接力 | ❌ 漏斗不含 | compute_derived_features(get_snapshots_by_code) |
| 前日成交额（prev_amount_yi） | 形态反包（放量对比） | ❌ 漏斗只有当日 amount_yi | K线前日 bar（activity.py 已取 bars） |
| K线派生（max_high/shadow/ma_5/prev_turnover） | 形态反包+弱转强 | ✅ S083 已加（ada2b71） | 已补全 |
| 活跃度（turnover/vol_ratio/amount/amplitude） | 所有战法通用 | ✅ 漏斗 R2 已有 | 已有 |
| 资金流（main_net/dragon_tiger/northbound） | 所有战法通用 | ✅ 漏斗 R2 已有 | 已有 |

**6 个缺口**：GeneScore 完整对象 / 涨停池原始 dict / S070 R7 分时派生（3 字段）/ 前日成交额。

### 2.2 既有选股池 API（grill 核实，Q4=A 复用）

前端 `frontend/src/lib/candidates.ts` 已有独立选股池 API client：
- `runFunnel(stage, date)` → POST `/workflow/candidates/funnel`
- `getFunnelLayers(runId, date)` → GET `/workflow/funnel/layers`
- `getFunnelConfig()` / `updateFunnelConfig()` / `rerunLayer()` / `rerunLayerDownstream()`

后端 `candidate_funnel/funnel.py` 有 `run_funnel(stage, date, cfg, ctx)` + TTL 缓存（`_FUNNEL_CACHE`，默认 3600s）。

**选股池 API 已独立存在，只是前端 PreMarketBriefing 没用它（用了 `/api/workflow/pre-market` 透传的 `funnel_layers`）**。解耦 = 前端选股池 Tab 直接调既有 API。

### 2.3 与既有 spec 关系

- **S002（P1 已实现）**：漏斗 `run_funnel` 已实现 + 验收。本 spec 扩展其输出（DiagnosisCard 加 3 子对象），不改漏斗 R1→R2→R3 筛选逻辑
- **S070（已合并 develop）**：R7 派生 `compute_derived_features` 供选股池补 derived 子对象
- **S083（因子复用已 commit ada2b71）**：IndicatorSet 加 4 字段（max_high/shadow/ma_5/prev_turnover）+ match_strategies 加 indicators 参数已落地。本 spec 补 DiagnosisCard 3 子对象 + gene.py 存完整 GeneScore + 选股池补涨停池原始dict+S070派生+前日成交额
- **S083（漏斗接入 pre_market_workflow 部分）**：作废。S083 spec §3.1 R1（删 _build_candidate_pool 改调 run_funnel）作废 —— 解耦方向不改 pre_market_workflow 内部，选股池 Tab 独立调 API
- **S079/S081（已合并 develop）**：仓位闸+龙虎榜+战法匹配已落地，本 spec 不改后端战法/仓位/风控逻辑

---

## 3. 需求清单

### 3.1 选股池 DiagnosisCard 补全 3 子对象（Q6=B）

- [ ] R1：`DiagnosisCard` 加 `gene_score: GeneScore | None = None` 字段
  - [ ] R1.1 `candidate_funnel/sources/gene.py` 扩展 `genes[code]` 存完整 GeneScore 对象（不只存 gene_score 数字，存 `gene_obj: GeneScore`）
  - [ ] R1.2 `candidate_funnel/diagnosis.py` `build_diagnosis_card` 从 `genes[code].gene_obj` 取 GeneScore 塞入
- [ ] R2：`DiagnosisCard` 加 `pool_item: dict | None = None` 字段（涨停池原始 dict）
  - [ ] R2.1 漏斗新增 source 或扩展 activity.py，从 `astock.em_zt_topic_pool` 取涨停池原始 dict（lbc/zdp/fbt/zbc/fund/hybk），按 code 匹配
  - [ ] R2.2 `build_diagnosis_card` 塞入 pool_item
- [ ] R3：`DiagnosisCard` 加 `derived: dict | None = None` 字段（S070 R7 分时派生）
  - [ ] R3.1 漏斗新增 source 或扩展，调 `compute_derived_features(get_snapshots_by_code(code, date))` 取 broken_duration_min/max_drop_pct/last_lock_time
  - [ ] R3.2 盘前 snapshots 未采集时 `derived=None` 标"分时数据未就绪"降级，不臆造
- [ ] R4：`IndicatorSet` 加 `prev_amount_yi: Optional[float] = None`（前日成交额）
  - [ ] R4.1 `activity.py` 已取 K线 bars，从前日 bar 算 `prev_amount_yi = prev_bar.amount / 1e8`
  - [ ] R4.2 `diagnosis.py` `build_indicator_set` 透传

### 3.2 战法从 DiagnosisCard 读全部因子（Q3=A + Q6=B）

- [ ] R5：`match_strategies` 改为从 `DiagnosisCard` 读因子（不再各自调 astock/kline/S070）
  - [ ] R5.1 既有 9 战法从 `card.gene_score` 读 GeneScore（total_score/zt_count_250d/factors）
  - [ ] R5.2 PRD 弱转强接力从 `card.pool_item` 读 lbc/hs/zdp + `card.indicators.prev_turnover_pct` 算 vol_ratio_1d + `card.derived` 读 broken_duration/max_drop/last_lock
  - [ ] R5.3 PRD 形态反包从 `card.pool_item.zdp` + `card.indicators.max_high_pct/shadow_length_pct/ma_5_status` + `card.indicators.prev_amount_yi/amount_yi` 算放量对比
  - [ ] R5.4 删 `match_strategies` 各 elif 分支的 astock/kline/S070 调用（全部从 card 读）
- [ ] R6：`StrategyMatcher.match()` 改为接受 `DiagnosisCard`（或 gene+indicators+pool_item+derived 多参数）
  - [ ] R6.1 向后兼容：新参数默认 None，既有调用不传 card 行为不变
  - [ ] R6.2 传 card 时从 card 取全部子对象传给 match_strategies

### 3.3 前端选股池 Tab（Q5=A + Q4=A）

- [ ] R7：`Workflow.tsx` 加两级 Tab 导航（选股池 / 战法）
  - [ ] R7.1 选股池 Tab：调既有 `runFunnel(stage, date)` API 展示漏斗 R1→R2→R3 三层 + final_candidates（DiagnosisCard 列表含全部因子）
  - [ ] R7.2 选股池 Tab 展示候选标的 + 六类指标 + 风险标记（复用 PreMarketBriefing 的 FactorSection/CandidateFunnelEmbed 组件）
  - [ ] R7.3 选股池 Tab 不调 `/api/workflow/pre-market`（解耦，直接调选股池 API）
- [ ] R8：战法 Tab 保留既有战法流入口卡片网格（首板流/弱转强接力/反包流等 7 个卡片）
  - [ ] R8.1 点击战法卡片进入战法特定筛选页面（从选股池缓存读 DiagnosisCard 做战法匹配）
  - [ ] R8.2 战法特定筛选页面调 `match_strategies` 传入 DiagnosisCard（含全部因子）

### 3.4 pre_market_workflow 解耦（Q1=A 选股池独立）

- [ ] R9：`pre_market_workflow.run()` 不再内部调选股池筛选 + 战法匹配
  - [ ] R9.1 选股池产出由选股池 API 独立调 `run_funnel`（前端选股池 Tab 触发）
  - [ ] R9.2 战法匹配由战法 API 独立调 `match_strategies`（前端战法 Tab 触发，从选股池缓存读 DiagnosisCard）
  - [ ] R9.3 pre_market_workflow 保留仓位建议 + S079 后处理 + 推送（编排层，调选股池缓存 + 战法缓存产出）
  - [ ] R9.4 或者 pre_market_workflow 完全废弃（选股池 Tab + 战法 Tab 各自独立，不需要编排层）—— 实现阶段核实

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/models.py`（修改） | DiagnosisCard 加 3 字段（gene_score/pool_item/derived）；IndicatorSet 加 prev_amount_yi |
| `backend/candidate_funnel/sources/gene.py`（修改） | 扩展 genes dict 存完整 GeneScore 对象 |
| `backend/candidate_funnel/sources/activity.py`（修改） | 已取 K线 bars，扩展算 prev_amount_yi；或新增涨停池原始 dict 取数 |
| `backend/candidate_funnel/sources/`（新增 source） | 涨停池原始 dict source（从 em_zt_topic_pool 取 lbc/zdp/fbt/zbc）+ S070 R7 派生 source |
| `backend/candidate_funnel/diagnosis.py`（修改） | build_diagnosis_card 塞入 gene_score/pool_item/derived |
| `backend/limitup_strategy.py`（修改） | match_strategies 各 elif 从 DiagnosisCard 读因子，删各自取数代码 |
| `backend/strategies/strategy_matcher.py`（修改） | match() 改为接受 DiagnosisCard（或多参数） |
| `backend/pre_market_workflow.py`（修改） | 解耦：选股池+战法独立，pre_market_workflow 退化为编排层或废弃 |
| `backend/routers/workflow.py`（修改） | 选股池 API 透传 DiagnosisCard 含 3 子对象 |
| `frontend/src/pages/Workflow.tsx`（修改） | 加两级 Tab（选股池/战法），选股池 Tab 调 runFunnel API |
| `frontend/src/lib/candidates.ts`（修改） | DiagnosisCard 类型加 3 子对象字段 |

---

## 5. 设计方案

### 5.1 解耦架构（选股池独立产出 → 战法独立消费）

```
[选股池 Tab]（前端 Workflow.tsx）
  调 runFunnel API → run_funnel() 产出 FunnelResult
  FunnelResult.final_candidates: list[DiagnosisCard]
    DiagnosisCard 含：
      ├── gene_score: GeneScore（既有9战法用，gene.py 扩展存完整对象）
      ├── pool_item: dict（涨停池原始dict，lbc/zdp/fbt/zbc/fund/hybk）
      ├── derived: dict（S070 R7 派生，broken_duration/max_drop/last_lock）
      ├── indicators: IndicatorSet（活跃度+资金流+K线派生+prev_amount_yi）
      ├── activity: ActivityAssessment
      └── risk_flags: list[str]
    ↓ 存 TTL 缓存（_FUNNEL_CACHE）

[战法 Tab]（前端 Workflow.tsx）
  从选股池缓存读 DiagnosisCard
  调 match_strategies(card) → 战法特定硬阈值匹配
    既有9战法：从 card.gene_score 读
    PRD弱转强：从 card.pool_item + card.derived + card.indicators 读
    PRD形态反包：从 card.pool_item + card.indicators 读
  输出 StrategySignal（命中/置信度/触发价）
  ↓
  仓位建议（PositionAdvisor）+ S079 后处理（cap_by_market_phase + DragonTigerSeatFilter）
```

### 5.2 备选方案为何不选

- **S083 漏斗接入 pre_market_workflow（耦合方向）**：把漏斗塞进 pre_market_workflow 内部，选股池和战法仍串在一个函数里，不解耦
- **Q6=A 全部补进 IndicatorSet**：IndicatorSet 膨胀到 23 字段，且 S070 R7 分时派生是盘中数据塞进盘前指标语义不对
- **Q5=B 改侧边栏**：改动面大，分散的 /candidates + /value-funnel + /limitup 合并到统一入口涉及多页面迁移
- **Q5=C 新建路由**：新建 /pools + /strategies 改动面大

### 5.3 工程约束

- **不破坏既有 9 战法**：match_strategies 新参数默认 None，既有调用不传 card 行为不变
- **不破坏 S079 后处理**：cap_by_market_phase + DragonTigerSeatFilter 在战法匹配之后串，不改
- **不破坏 S070 R7 派生**：derived 子对象盘前 snapshots 未采集时标 None 降级
- **em_get 防封底线**：涨停池原始 dict 从 astock.em_zt_topic_pool 取（走 em_get 限流）
- **数据缺失透明**：3 子对象各自管理缺失，gene_score=None/pool_item=None/derived=None 各标原因
- **选股池 API 复用**：前端选股池 Tab 调既有 runFunnel API，不新建端点

---

## 6. 验收标准

- [ ] AC1：DiagnosisCard 含 3 子对象（gene_score/pool_item/derived），选股池一站式输出所有战法盘前因子
- [ ] AC2：gene.py 扩展存完整 GeneScore 对象（不只存 gene_score 数字），DiagnosisCard.gene_score 非 None
- [ ] AC3：pool_item 从 astock.em_zt_topic_pool 取（lbc/zdp/fbt/zbc），走 em_get 限流
- [ ] AC4：derived 从 S070 R7 compute_derived_features 取（broken_duration/max_drop/last_lock），盘前未采集时 None 降级
- [ ] AC5：IndicatorSet 含 prev_amount_yi（前日成交额，activity.py 从 K线前日 bar 算）
- [ ] AC6：match_strategies 各 elif 从 DiagnosisCard 读全部因子，不调 astock/kline/S070（删重复取数代码）
- [ ] AC7：既有 9 战法回归通过（传/不传 card 命中一致）
- [ ] AC8：前端 Workflow.tsx 有两级 Tab（选股池/战法），选股池 Tab 调 runFunnel API 展示漏斗 + 候选
- [ ] AC9：战法 Tab 保留既有战法流入口卡片，点击进入战法特定筛选（从选股池缓存读 DiagnosisCard）
- [ ] AC10：pre_market_workflow 解耦（选股池+战法独立，不再串在一个函数里）
- [ ] AC11：所有研判/买卖时机/仓位参数挂轻量风险提醒（CLAUDE.md §1.1 弱合规）

---

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1）；挂轻量风险提醒
- [ ] 判断可复现：涉及数据的跑 `financial_rigor.py` 验算 —— **实现阶段验证**
- [x] 不接券商不下单（AC7 工程底线）
- [x] em_get 防封：涨停池原始 dict 从 astock.em_zt_topic_pool 取
- [x] 不臆造：3 子对象各自管理缺失，标 None + 原因
- [x] S002 参考价位隔离决议 + AC10 显式豁免（继承 S079 §2.3）

---

## 8. 测试计划

- **单元测试**（`pytest -m "not live"`）：
  - gene.py 扩展存完整 GeneScore：mock screener_result，验证 genes[code] 含 gene_obj
  - DiagnosisCard 3 子对象填充：mock funnel 构建，验证 card.gene_score/pool_item/derived 非 None
  - match_strategies 从 card 读因子：mock DiagnosisCard 含全部子对象，验证战法命中
  - 数据缺失降级：mock derived=None（snapshots 未采集），验证弱转强标"分时数据未就绪"
  - 既有 9 战法回归：传/不传 card 命中一致
- **前端**：选股池 Tab 调 runFunnel 展示漏斗 + 候选；战法 Tab 保留卡片网格
- **手动验收**：前后端跑起来，选股池 Tab 展示 R1→R2→R3 + 候选，战法 Tab 点击进战法特定筛选

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| DiagnosisCard 加 3 子对象破坏序列化 | 前端类型/快照不兼容 | 3 字段默认 None，既有快照无字段降级 |
| match_strategies 改从 card 读破坏既有 9 战法 | 既有战法不命中 | 新参数默认 None 向后兼容；传 card 时从 card 读，不传时走原路径 |
| pre_market_workflow 解耦破坏盘前简报 | 盘前简报空/报错 | 灰度：选股池 Tab 独立先跑通，pre_market_workflow 保留编排层过渡 |
| S070 R7 派生盘前未采集 | derived=None 弱转强不命中 | 诚实标"分时数据未就绪"，盘中采集完后补 |

**回滚**：
1. DiagnosisCard 3 子对象默认 None，不影响既有序列化
2. match_strategies 新参数默认 None，删除即回退
3. 前端两级 Tab 独立于既有 PreMarketBriefing，回滚只删 Tab 不影响盘前简报

---

## 10. 待定项

- T1：pre_market_workflow 解耦后是否完全废弃（R9.4）—— 实阶段核实选股池 Tab + 战法 Tab 是否能完全替代盘前简报
- T2：价值选股池（S005 value_funnel）是否纳入选股池 Tab 作为第二个池子 —— 本 spec 只做短线选股池，价值池后续
- T3：战法-选股池映射（哪些战法用哪个池子）—— 本 spec 短线 11 战法共用短线池，映射=1:1，后续价值战法加入时需映射
