# 技术方案 · S084 选股池战法解耦（reframe：R1-only + R2/R3 下放 + 异步预采集 + §44 降级）

> 对应 spec.md（grill reframe 2026-08-19）
> 性质：技术实现方案（spec 已签字，本文件进入文件/函数级设计，受 CLAUDE.md §0 SDD 约束）
>
> grill reframe 决议：
> - 选股池只做 R1（全涨停 + 补因子），不做 R2/R3 过滤（R2/R3 下放战法，每战法自定阈值）
> - 16:30 异步预采集 derived 落库（不阻塞主流程）
> - 战法 fallback（card.derived=None 时战法层自补）
> - §44 从工程底线降级为参考性建议（不强制 gate；设计方案经深度调研）

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力 | 代码事实 |
|---|---|---|
| R1 选股池只全涨停 | candidate_funnel funnel.py R1（涨停基因筛选） | `funnel.py:299-323` R1 宽源；`_filter_r2`/`_filter_r3` 删 |
| R1.2 3 子对象 | gene.py gene_obj + zt_pool_source + derived_source | **已实现**（S084 初版） |
| R1.3 IndicatorSet 10 字段 | activity.py 两路径 + fund_flow sectors | **已实现** |
| R2/R3 下放战法 | match_strategies card 参数 | `limitup_strategy.py:693` 已加 card；每战法自定阈值【新】 |
| R3 16:30 异步预采集 | scheduled_tasks _executors | `scheduled_tasks.py` 加新任务类型【新】 |
| R4 战法 fallback | derived_source + match_strategies S070 fallback | `limitup_strategy.py:816-829` S070 fallback 保留；card.derived=None 战法层自补【新】 |
| R5 §44 降级 | CLAUDE.md §1.2 工程底线 | 改工程底线段【新】 |
| 前端两级 Tab + 全因子展示 | FunnelLayers + SelectionPipeline + DiagnosisCard.tsx + FunnelLayerCard | **已实现**（S084 初版 + review 修复） |

**已实现（S084 初版，保留）**：models 3 子对象 + 10 字段、gene gene_obj、zt_pool_source、derived_source、activity 两路径、fund_flow sectors（industry_map 防封修复）、diagnosis 塞入+透传、funnel yesterday_date/zt_pool/industry_map/derived、match_strategies card 参数、StrategyMatcher card/cards_map、前端两级 Tab + FunnelLayers + SelectionPipeline 终选全因子 + DiagnosisCard 3 子对象 + FunnelLayerCard 每层因子。

**reframe 新增**：funnel 删 R2/R3（R1-only）、match_strategies 每战法自定 R2/R3 阈值 + derived=None fallback、scheduled_tasks 16:30 异步预采集、CLAUDE.md §44 降级。

---

## 1. 目录结构

### 1.1 后端
```
backend/
├── candidate_funnel/
│   ├── funnel.py                # 【改】_run_funnel_impl 删 _filter_r2/_filter_r3，final = R1 全涨停 + 自选
│   ├── models.py                # 【已改】DiagnosisCard 3 子对象 + IndicatorSet 10 字段
│   ├── diagnosis.py             # 【已改】build_diagnosis_card 塞 3 子对象 + build_indicator_set 透传
│   └── sources/                 # 【已改/新增】gene/activity/fund_flow + zt_pool_source/derived_source
├── limitup_strategy.py          # 【改】match_strategies 每战法自定 R2/R3 阈值 + derived=None fallback
├── strategies/strategy_matcher.py  # 【已改】match/match_batch card/cards_map
├── scheduled_tasks.py           # 【改】加 16:30 异步预采集任务类型
├── pre_market_workflow.py       # 【不改】Q3=C 三入口并存
└── CLAUDE.md（项目根）          # 【改】§1.2 §44 降级为参考性建议
```

### 1.2 前端（已实现，验证）
```
frontend/src/
├── pages/Workflow.tsx                      # 【已改】两级 Tab（最顶）+ 选股池 Tab
├── lib/candidates.ts                       # 【已改】DiagnosisCard 3 子对象 + IndicatorSet 10 字段
├── components/candidate/{FunnelLayers,DiagnosisCard}.tsx  # 【已改】
├── components/ui/FunnelLayerCard.tsx       # 【已改】每层因子
└── components/pipeline/SelectionPipeline.tsx  # 【已改】终选全因子
```

---

## 2. 实现步骤

### R1：选股池 R1-only（删 R2/R3）
**文件**：`candidate_funnel/funnel.py`
- `_run_funnel_impl`：删 `_filter_r2`/`_filter_r3` 调用，`final_candidates = R1 全涨停 + 自选`（不按活跃度/催化筛）
- 保留：yesterday_date + zt_pool_map + industry_map + per-code derived（懒加载/读预采集）
- R1 layer.passed 仍展示涨停基因股；R2/R3 layer 删或保留为"战法参考"（不再筛）

### R2：R2/R3 下放战法（每战法自定阈值）
**文件**：`limitup_strategy.py`
- `match_strategies` 每战法自定 R2（活跃度：turnover/amount/vol_ratio）/R3（催化：auction/公告/板块）阈值：
  - first_plate：定 turnover_cold/amount_yi_min（从 card.indicators 读）
  - consecutive_relay/break_reseal：定封板率/zt_count（从 card.gene_score）
  - weak_turn_strong：定 lbc/broken/max_drop（从 card.derived/pool_item）
  - pattern_reversal：定 zdp/max_high/shadow/ma5（从 card.pool_item/indicators）
- 选股池不替战法筛 R2/R3；战法从 card 读因子 + 自定阈值判定

### R3：16:30 异步预采集
**文件**：`scheduled_tasks.py`
- 加新任务类型：每日 16:30 启动（`_executors` 加方法）
- 预采集 derived：`compute_derived_features(get_snapshots_by_code(code, yesterday))` 落库（derived 缓存表/字段，或 seal_intraday_snapshots 已有则 derived_source 读）
- 不阻塞主流程；选股池 `run_funnel` 读预采集的（不 per-code 实时算）；未预采集则 derived=None

### R4：战法 fallback（card.derived=None 自补）
**文件**：`limitup_strategy.py`
- weak_turn_strong：card.derived=None 时战法层调 `get_snapshots_by_code` + `compute_derived_features` 自补（B2 fallback 保留，card=None 走原路径）
- card.derived 非空（异步预采集落库）→ 直接读，不重算

### R5：§44 降级
**文件**：`CLAUDE.md`
- §1.2 工程底线：§44（lift bar）从"必过 gate"改"参考性建议"
- 注释：§44 移设计期（验证设计方案）+ 回溯模块（独立模块，引入 §44 作为回溯方案之一）

---

## 3. 验收对齐

| spec AC | plan 实现步骤 | 关键验证点 |
|---|---|---|
| AC1 选股池 R1-only | R1（funnel 删 R2/R3） | final_candidates = R1 全涨停，无 R2/R3 过滤 |
| AC2 3 子对象 + 10 字段 | 已实现 | card.gene_score/pool_item/derived 非 None（有数据时） |
| AC3 R2/R3 下放战法 | R2（match_strategies 自定） | 每战法自定活跃度/催化阈值 |
| AC4 16:30 异步预采集 | R3（scheduled_tasks） | 任务 16:30 触发，derived 落库 |
| AC5 战法 fallback | R4（derived=None 自补） | card.derived=None 时战法层自补命中一致 |
| AC6 §44 降级 | R5（CLAUDE.md） | §1.2 改参考性建议 |
| AC7 match_strategies card | 已实现 | 既有 9 + PRD 2 战法回归 |
| AC8 前端两级 Tab | 已实现 | tsc 过 |
| AC9 每层因子 + 终选全因子 | 已实现 | FunnelLayerCard 每层 + SelectionPipeline 终选 |
| AC10 三入口并存 | pre_market_workflow 不改 | 既有测试回归 |
| AC11 轻量风险提醒 | 既有 Disclaimer | 继承 |

---

## 4. 工程约束

- **em_get 防封底线**：zt_pool_source 走 first_board_filter.fetch_zt_pool（em_get + 24h 缓存）；sectors 走 market.get_overview（5min 缓存）；industry_map 从 zt pool hybk（em_get-backed，review HIGH 修复）
- **不臆造**：3 子对象各自 None 降级；pe_ttm/pb/mcap_yi 历史日 None+missing
- **异步不阻塞**：16:30 预采集落库，选股池读预采集（不 per-code 实时算 derived）
- **向后兼容**：match_strategies card 默认 None，既有调用行为不变；pre_market_workflow 不传 card 走 fallback
- **§44 降级**：参考性建议，不强制 gate；§44 移设计期 + 回溯模块

---

## 5. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| R1-only 破坏既有 R2/R3 筛选 | 候选数变多（全涨停） | 回滚恢复 _filter_r2/_filter_r3；R2/R3 下放战法后战法自筛 |
| 16:30 异步任务失败 | derived 未落库 | derived=None 降级，战法 fallback 自补 |
| 战法 R2/R3 阈值拍脑袋 | 阈值不准 | §44 回溯模块跑数据后调；当前用 S081 PRD 阈值 |
| §44 降级过度（不再验证） | 未验证就信 | 保留回溯模块引入 §44；设计期仍验设计方案 |

**回滚**：
1. funnel R2/R3 删除可回滚（恢复 _filter_r2/_filter_r3 调用）
2. scheduled_tasks 新任务可删（derived_source 实时算 fallback）
3. match_strategies 战法 R2/R3 阈值可调（card 默认 None 不破坏既有）
4. CLAUDE.md §44 降级可回滚（改回工程底线）
