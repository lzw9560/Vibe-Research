# 任务拆分 · S023 漏斗可用性与因子解耦

> 对应：`spec.md`（需求）、`plan.md`（技术方案）
> 粒度：原子任务（独立可验，1-2h/条）。每条含依赖、改动文件、验收方式、映射 AC。
> 规则：每条完成即跑对应单测；东财走 em_get；不写方向/参考价位（合规）。

---

## 阶段 A · 因子接口与注册表（R1，AC5 扩展性）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | `factors/base.py`：Candidate/FactorResult/SelectionFactor Protocol 定义 | — | `factors/base.py`、`factors/__init__.py` | `python -c "from factors.base import FactorResult"` 不报错 |
| A2 | `factors/registry.py`：注册表 + register/get_all_factors/get_factor | A1 | `factors/registry.py` | 注册一个假因子 → get_factor 返回 |
| A3 | 单测：因子接口与注册表 | A2 | `factors/tests/test_base.py` | pytest 过 |

## 阶段 B · 两套因子适配（R1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | `CandidateFunnelFactor`：调 run_funnel，包成 FactorResult（原生多层，candidates 带 source_layer/hit_rules） | A1 | `factors/candidate_funnel_factor.py` | mock run_funnel → FactorResult.layers 多层 |
| B2 | `LimitupScreenerFactor`：调 PreMarketWorkflow，包成 FactorResult（单层+战法/仓位入 detail） | A1 | `factors/limitup_screener_factor.py` | mock PreMarketWorkflow → 单层 FactorResult |
| B3 | 注册两因子到 registry | B1,B2 | `factors/registry.py` | get_all_factors 返回 2 个 |
| B4 | 单测：两适配层 | B1,B2 | `factors/tests/test_factors.py` | pytest 过 |

## 阶段 C · 真实数据链路（R5，AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | `vr_paths.last_trading_date()`：非交易日→最近 A 股交易日 | — | `vr_paths.py` | 周末调用→返回周五日期 |
| C2 | sources 取数失败标 data_status+reason，不静默空 | — | `candidate_funnel/sources/*.py` | mock 失败 → 返回含 data_status 的标记 |
| C3 | 漏斗层 input_count 区分"采集到0"与"采集失败" | C2 | `candidate_funnel/models.py`、`funnel.py` | 失败层标 data_status |
| C4 | 单测：真实数据链路（last_trading_date + 失败标记） | C1,C2,C3 | `candidate_funnel/tests/test_sources_data.py` | pytest 过 |

## 阶段 D · 盘前简报接因子（R2，AC1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | `/api/workflow/pre-market` 遍历注册表返回多因子 | B3,C1 | `routers/workflow.py` | curl → factors 数组含 2 套 |
| D2 | `trading_workflow.run_pre_market` 改调注册表 | B3 | `trading_workflow.py` | 单测 mock 注册表 |
| D3 | 前端 PreMarketBriefing 按因子分区展示（折叠区+候选可点） | D1 | `frontend/.../PreMarketBriefing.tsx` | tsc 过；两因子分区渲染 |
| D4 | 数据未取得如实显示原因（不静默空白） | C2,D1 | `frontend/.../PreMarketBriefing.tsx` | mock 未取得 → 显示原因文案 |

## 阶段 E · 候选详情页（R3，AC2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | `FunnelLayer` 加 conditions/passed；Candidate 加 source_factor_id/source_layer | A1 | `candidate_funnel/models.py` | 字段存在；旧测试不破 |
| E2 | 诊断接口加来源字段（source_factor_id/source_layer） | E1 | `routers/candidates.py` | curl diagnosis → 含来源 |
| E3 | DiagnosisCard 前端呈现依据链（规则/取值/missing/阈值档位） | E2 | `frontend/.../DiagnosisCard.tsx` | tsc 过；依据链渲染 |
| E4 | CandidateDetail 页面 + 路由 `/workflow/candidates/:code` | E3 | `frontend/.../CandidateDetail.tsx`、`router.tsx` | 路由可达；详情渲染 |
| E5 | 候选列表项可点击跳转详情 | E4 | `frontend/.../FunnelLayers.tsx`、`PreMarketBriefing.tsx` | 点击 → 跳详情页 |

## 阶段 F · 漏斗每层可观测可调参（R4，AC3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| F1 | FunnelLayer.conditions 生成（从 rules_applied 生成可读描述+情绪档位标注） | E1 | `candidate_funnel/funnel.py` | conditions 非空含情绪档位 |
| F2 | FunnelLayers 前端展示筛选条件+通过候选清单 | F1,E5 | `frontend/.../FunnelLayers.tsx` | 每层显示条件+passed 列表 |
| F3 | `PUT /api/workflow/funnel/layers/{id}/rerun` 只重跑该层 | F1 | `routers/candidates.py`、`funnel.py` | 调参后 rerun → 只该层结果变 |
| F4 | `POST .../layers/{id}/rerun-downstream` 往下全跑 | F3 | `routers/candidates.py` | rerun-downstream → 下游层更新 |
| F5 | 前端调参交互：调参→重跑该层→展示结果→"下游全跑"按钮 | F3,F4 | `frontend/.../FunnelLayers.tsx` | 调参→只该层变→按钮出现→点击下游变 |

## 阶段 G · 集成验收

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| G1 | 全量离线测试 | A-F | — | pytest -m "not live" 全绿 |
| G2 | live 冒烟：盘前简报两因子+漏斗每层+详情+调参 | A-F | — | curl + 前端手测 |
| G3 | 合规自查：grep 方向词；连板梯队 code/name 呈现 | — | — | 无方向词；原始池如实呈现 |
