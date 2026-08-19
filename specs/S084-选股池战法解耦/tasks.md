# 任务拆分 · S084 选股池战法解耦（reframe）

> 对应：`spec.md`（grill reframe 2026-08-19）+ `plan.md`
> 粒度：原子任务。**已实现部分标注【已实现】**（S084 初版），**reframe 新增标注【新】**。
> 规则：每条完成即跑单测/验收；em_get 防封底线；不臆造；match_strategies card=None 保留 fallback。

---

## 阶段 A · 选股池 R1-only（删 R2/R3）【新】

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| A1 | `_run_funnel_impl` 删 `_filter_r2`/`_filter_r3` 调用，`final_candidates = R1 全涨停 + 自选`（不按活跃度/催化筛） | `backend/candidate_funnel/funnel.py` | funnel 跑通，final_candidates = R1 全量（无 R2/R3 过滤）；映射 AC1 |
| A2 | R2/R3 layer 处理：删或保留为"战法参考"（不再筛，仅展示该层语义） | `backend/candidate_funnel/funnel.py` | layers 不含 R2/R3 筛选逻辑；映射 AC1 |
| A3 | 保留 yesterday_date + zt_pool_map + industry_map + per-code derived（懒加载/读预采集） | `backend/candidate_funnel/funnel.py` | 3 子对象透传不变；映射 AC2 |
| A4 | 单测：R1-only（无 R2/R3 过滤），final_candidates = R1 全涨停 | `backend/candidate_funnel/tests/test_funnel.py` | pytest 全过；映射 AC1 |

## 阶段 B · 战法 R2/R3 下放 + fallback【新】

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| B1 | `match_strategies` 每战法自定 R2（活跃度：turnover/amount/vol_ratio）/R3（催化：auction/公告/板块）阈值，从 card.indicators/gene_score 读 | `backend/limitup_strategy.py` | 每战法读 card + 自定阈值判定；映射 AC3 |
| B2 | weak_turn_strong `card.derived=None` 时战法层调 `get_snapshots_by_code` + `compute_derived_features` 自补（B2 fallback 保留，card=None 走原路径） | `backend/limitup_strategy.py` | derived=None 自补命中一致；card.derived 非空直接读；映射 AC5 |
| B3 | pattern_reversal 从 card.pool_item.zdp/indicators 读 + 自定 R3 阈值 | `backend/limitup_strategy.py` | card 非空从 card 读命中；映射 AC3 |
| B4 | 单测：战法 R2/R3 自定 + derived=None fallback | `backend/tests/test_s084_match_card.py` | pytest 全过；映射 AC3/AC5/AC7 |

## 阶段 C · 16:30 异步预采集【新】

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| C1 | `scheduled_tasks.py` `_executors` 加 16:30 异步预采集任务类型（每日 16:30 触发） | `backend/scheduled_tasks.py` | 任务注册 + cron 16:30 触发；映射 AC4 |
| C2 | 预采集 derived：`compute_derived_features(get_snapshots_by_code(code, yesterday))` 落库（derived 缓存表/字段） | `backend/scheduled_tasks.py` | derived 落库；derived_source 读预采集；映射 AC4 |
| C3 | derived_source 改读预采集（不实时算）；未预采集→None（战法 fallback 补） | `backend/candidate_funnel/sources/derived_source.py` | 读预采集快；None 降级；映射 AC4/AC5 |
| C4 | 单测：异步任务 + derived_source 读预采集 | `backend/tests/test_scheduled_tasks.py` | pytest 全过；映射 AC4 |

## 阶段 D · §44 降级【新】

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| D1 | `CLAUDE.md` §1.2 工程底线：§44（lift bar）从"必过 gate"改"参考性建议" | `CLAUDE.md` | 文档更新；映射 AC6 |
| D2 | §44 注释移设计期（验证设计方案）+ 回溯模块（独立模块，引入 §44 作为回溯方案之一） | `CLAUDE.md` | 注释说明；映射 AC6 |

## 阶段 E · 前端（已实现，验证）【已实现】

| ID | 任务 | 改动文件 | 验收方式 |
|---|---|---|---|
| E1 | 两级 Tab（最顶）+ 选股池 Tab（FunnelLayers + SelectionPipeline 终选全因子） | `frontend/src/pages/Workflow.tsx` | `tsc --noEmit` 过；映射 AC8 |
| E2 | 每层因子（FunnelLayerCard passedFactors）+ 终选全因子（DiagnosisCard 3 子对象 + 10 字段） | `FunnelLayerCard.tsx`/`DiagnosisCard.tsx`/`SelectionPipeline.tsx` | `tsc --noEmit` 过；映射 AC9 |

## 阶段 F · 回归 + 验收

| ID | 任务 | 验收方式 |
|---|---|---|
| F1 | pytest 全过（candidate_funnel + s070/s079/s081/s084 + scheduled_tasks） | `.venv/bin/python -m pytest candidate_funnel/tests/ tests/test_s070*.py tests/test_s079*.py tests/test_s081*.py tests/test_s084*.py tests/test_scheduled_tasks.py -m "not live" --no-cov -q` 全绿 |
| F2 | 前端 tsc | `cd frontend && npx tsc --noEmit` 全过 |
| F3 | AC1-AC11 逐条核对 | AC checklist 全绿 |
| F4 | 验收报告更新（reframe） | `specs/S084-选股池战法解耦/验收报告.md` 更新 |

---

## 依赖图

```
A1（funnel 删 R2/R3）→ A4（单测）
B1（战法自定 R2/R3）→ B2（derived=None fallback）→ B4（单测）
C1（16:30 任务）→ C2（derived 落库）→ C3（derived_source 读预采集）→ C4（单测）
D1（CLAUDE §44 降级）
E1/E2（前端已实现，tsc 验证）
F1-F4（回归 + 验收）
```

- A（选股池 R1-only）是地基，破坏性改（删 R2/R3），先做。
- B（战法 R2/R3）依赖 A（选股池不筛后战法自筛）。
- C（异步预采集）独立，可并行 A/B。
- D（§44 降级）独立文档改。
- E（前端）已实现，仅验证。
- 关键路径：A1→B1→B2→C1→C2→F1→F3。

---

## 执行规则

1. **一次一任务**：按 ID 顺序，完成一条跑其验收再开下一条。
2. **B2 保留 fallback**：match_strategies card=None 时保留既有 S070 自取数路径不删；card.derived=None 时战法层自补。
3. **em_get 防封**：zt_pool_source 走 first_board_filter.fetch_zt_pool（em_get）；sectors 走 market.get_overview（5min 缓存）；industry_map 从 zt pool hybk。
4. **异步不阻塞**：16:30 预采集落库，选股池读预采集（不 per-code 实时算）。
5. **§44 降级**：参考性建议，不强制 gate；§44 移设计期 + 回溯模块。
6. **不臆造**：3 子对象各自 None 降级；pe_ttm/pb/mcap_yi 历史日 None+missing。
7. **commit 引用**：commit message 带 S084 + 任务 ID（如 `S084-A1 funnel 删 R2/R3，选股池 R1-only`）。
