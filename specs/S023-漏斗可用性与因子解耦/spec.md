# Spec: S023 — 漏斗可用性与因子解耦

> 状态：草案
> 作者：Codex（brainstorming 对齐用户）  日期：2026-08-02
> 关联：`../S002-打板工作流重构/spec.md`（P1 漏斗）、`../../ARCHITECTURE.md`、`../../CLAUDE.md` §0/§1
> 设计文档：`../../docs/superpowers/specs/2026-08-02-daban-workflow-p1-polish-design.md`

---

## 1. 问题 / 目标

P1 漏斗已实现但不可用：盘前简报走旧路径未接漏斗产出、候选点不进详情、漏斗看不到每层筛选条件与通过候选、取数失败静默返空。目标：选股因子与工作流解耦，两套选股标准（旧 limitup_screener + 新 candidate_funnel）作为可插拔组件并存，盘前简报调用因子、候选可点进诊断卡详情含完整依据链、漏斗每层可观测可调参、全链路真实数据不静默返空。

## 2. 背景

- 旧 `pre_market_workflow.py`（S002 P1 前）+ 新 `candidate_funnel/`（P1）两套并行未打通。盘前简报 `PreMarketBriefing.tsx` 调 `/api/workflow/pre-market` 走旧路径，不用漏斗产出。
- P1 漏斗后端具备 `rules_applied`/`missing`/`adjustment`（AC5/AC6 已实现），但前端 `FunnelLayers.tsx` 只展示计数+被过滤，无筛选条件/通过候选/调参交互。
- candidate_funnel sources 为真实采集（非 mock），但取数失败静默返空 dict，给人"假数据"观感。
- 非交易时段行情为收盘快照，漏斗需用上一交易日数据正常跑。

## 3. 需求清单

- [ ] R1 选股因子接口：`factors/base.py` 定义 `FactorResult`/`SelectionFactor` Protocol + `factors/registry.py` 注册表；`LimitupScreenerFactor`/`CandidateFunnelFactor` 适配两套标准。
- [ ] R2 盘前简报接因子：`/api/workflow/pre-market` 返回多因子产出并列；前端按因子分区展示，候选可点击。
- [ ] R3 候选详情页：路由 `/workflow/candidates/:code`，DiagnosisCard 含完整依据链（入口层/命中规则/取值/missing/阈值档位）。
- [ ] R4 漏斗每层可观测可调参：每层展示筛选条件+通过候选+调参；调参只重跑该层，结果确认后用户决定是否下游全跑。
- [ ] R5 真实数据链路：`vr_paths.last_trading_date()`；sources 取数失败标"未取得"+原因，不静默返空；非交易时段用上一交易日。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/factors/base.py` | 新建：FactorResult/SelectionFactor Protocol |
| `backend/factors/registry.py` | 新建：因子注册表 |
| `backend/factors/limitup_screener_factor.py` | 新建：旧因子适配层 |
| `backend/factors/candidate_funnel_factor.py` | 新建：漏斗因子适配层 |
| `backend/routers/workflow.py` | 改：pre-market 端点调因子注册表 |
| `backend/routers/candidates.py` | 改：FunnelLayer 加 conditions/passed；诊断接口加来源字段 |
| `backend/trading_workflow.py` | 改：run_pre_market 调因子注册表 |
| `backend/candidate_funnel/models.py` | 改：FunnelLayer 加 conditions/passed；Candidate 加 source_factor_id/source_layer |
| `backend/candidate_funnel/sources/*.py` | 改：取数失败标 data_status+reason |
| `backend/vr_paths.py` | 改：新增 last_trading_date() |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | 改：按因子分区展示 |
| `frontend/src/pages/workflow/CandidateDetail.tsx` | 新建：详情页含依据链 |
| `frontend/src/components/candidate/FunnelLayers.tsx` | 改：筛选条件+通过候选+调参重跑 |
| `frontend/src/components/candidate/DiagnosisCard.tsx` | 改：呈现依据链 |
| `frontend/src/router.tsx` | 改：加详情路由 |

## 5. 设计方案

详见设计文档 §S023。要点：
- 因子接口 `SelectionFactor` Protocol（fetch/describe），`FactorResult` 统一产出格式。旧因子单层包装，漏斗原生多层。
- 注册表按 id 注册，工作流遍历调用。新因子加注册即可。
- 逐层调参交互：调参→只重跑该层→展示新结果→"下游全跑"按钮→用户点才往下。
- 非交易日转上一交易日，data_date 如实标注。
- 备选（不选）：全打包进 S002 改动——会污染已签 P1，故独立 spec。

## 6. 验收标准

- [ ] A1 盘前简报展示两套因子产出并列，数据未取得如实显示原因（不静默空白）
- [ ] A2 候选标的可点击进入诊断卡详情，详情含完整依据链（入口层/规则/取值/missing/阈值档位）
- [ ] A3 漏斗每层展示筛选条件+通过候选+可调参；调参只重跑该层，确认后用户决定是否下游全跑
- [ ] A4 非交易时段漏斗用上一交易日数据正常跑，取不到标原因，不静默返空
- [ ] A5 因子接口可插拔，新因子加注册即可被工作流调用（扩展性）
- [ ] A6 合规：详情/漏斗不输出方向结论词，只出客观分档+依据；连板梯队原始池如实呈现 code/name

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1）；输出挂轻量风险提醒
- [x] 判断可复现：依据链（rules_applied/adjustment/missing）如实呈现，禁臆造
- [x] 涨停四池/连板股榜个股属公开榜单客观事实，可呈现 code/name
- [x] 用户私有数据（持仓/研报/key）未进 git
- [x] 新增东财端点走 `em_get()` 限流（本 spec 不新增端点，复用现有）

## 8. 测试计划

- 离线：`backend/.venv/bin/python -m pytest candidate_funnel/tests/ factors/tests/ -m "not live"`
- live 冒烟：起 uvicorn:8900 → `GET /api/workflow/pre-market` 两因子返回 → `GET /api/workflow/funnel/layers` 每层含 conditions/passed → 点候选进详情
- 前端：`npx tsc --noEmit`；vite 起 → 盘前简报两因子分区 + 漏斗调参交互

## 9. 风险与回滚

- 旧因子适配层不改 limitup_screener 代码，只加包装，回滚=删 factors/ 目录 + 还原 workflow.py。
- FunnelLayer 加字段向后兼容（Optional 默认值），旧测试不破。
