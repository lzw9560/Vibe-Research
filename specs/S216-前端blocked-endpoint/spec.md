# S216 · 前端 blocked endpoint 接线

> 状态：**spec 草稿**（2026-09-17，调研 + spec，不实现代码）。
> 来源：前端未接线深度排查 Workflow w3z3lprlu（42 问题），A 类 6 个 blocked 后端 endpoint。
> 关联：[[./plan.md]]（待写）、[[./tasks.md]]（待写）。

## 1. 问题/目标

前端排查发现 6 个 A 类 blocked——前端页面有 UI 但没接后端 endpoint（mock/静态壳/待接线）。**深度调研发现部分 endpoint 已建前端没接（快赢），部分要新建（大块开发）**。本 spec 调研现状 + 定优先级 + 写需求，实现由后续 task 排。

## 2. 调研结果（grep 核于 2026-09-17，基于 origin/develop 99fe2b6）

| # | blocked 页面 | 后端现状 | 优先级 | 工作量 |
|---|---|---|---|---|
| 1 | BombAlertPanel | `/api/risk/bomb-alerts` **已建**（risk.py:195 调 `risk.bomb_alert_dispatcher.get_active_alerts` 返真实信号）+ `/api/workflow/alerts`（workflow.py:893）已建。前端没接 | **P0** | S |
| 2 | DimensionValidationGrid mock | `/api/evaluation/dims` **已建**（verifier.py:193 返 DIMENSION_LIFT_REGISTRY 12 维 + Recorder snapshot，缺数据诚实返 null 不臆造）。前端用 mock 没接 | **P0** | S |
| 3 | CognitionPage | `kg_tools.py` 有 `query_kg_entities`（:132）+ `query_kg_relations`（:154）。无 `/api/kg/*` router，要建 router 复用 | **P1** | M |
| 4 | EarningsCalendarPage | 无 endpoint，要建 `/api/earnings-calendar` 聚合（per-code /api/financials + /api/disclosure + /api/lockup 按 deadline 排序 + 未披露预警） | **P2** | L |
| 5 | S171ValueVerdict mock | `long_value_run.py` **不存在**（grep 确认）。S171 R3 在 `_s44_wire.py:163` 有线索（存月度方法论参数）。要建脚本跑 S171 R2 verdict harness 落 Recorder，前端 hook 自动返真值 | **P2** | M |
| 6 | QuantModelsPage M2/M4 | 无 endpoint，要建 `/api/expectation-gap` + `/api/transport/em-health` | **P2** | M |
| 7 | AdvisoryPage 顾问团 | 要集成 grill-me skill（后端跑 6-lens 对抗审查返结果），或前端直调 skill 产物 | **P2** | L |

## 3. 需求清单

### P0 快赢（已建 endpoint，前端接线即可）

**3.1 BombAlertPanel 接 /api/risk/bomb-alerts**
- 需求：前端 hook 调 `/api/risk/bomb-alerts?date=YYYY-MM-DD`，渲染 alerts 列表 + count。缺数据 HonestEmptyState 占位（不臆造）。
- 受影响文件：`frontend/src/components/.../BombAlertPanel.tsx`（或对应组件，grep 定位）、`frontend/src/lib/api.ts`（加 fetch 函数）。
- 验收：① 前端调 endpoint 渲染真实 alerts；② 缺数据返 HonestEmptyState 非 mock；③ 不破坏现有 /api/workflow/alerts（如有重复，二选一或分层）。

**3.2 DimensionValidationGrid 接 /api/evaluation/dims 替 mock**
- 需求：前端 hook 调 `/api/evaluation/dims`，用返值的 DIMENSION_LIFT_REGISTRY 12 维（status + weight_multiplier + ci_low/ci_high + data_snapshot_id）替 mock。
- 受影响文件：`frontend/src/components/DimensionValidationGrid.tsx`、`frontend/src/lib/api.ts`。
- 验收：① mock 数据全替；② 缺维度（ci null）诚实标"待验"不臆造；③ 12 维全渲染。

### P1 中等（复用现有函数建 endpoint）

**3.3 Cognition /api/kg/* 三 endpoint**
- 需求：建 `/api/kg/entities`（Obsidian Vault investing/ 实体目录，复用 `kg_tools.query_kg_entities`）+ `/api/kg/inbox`（M7 注入待审公告队列）+ `/api/kg/flow`（实体关系流）。
- 受影响文件：新建 `backend/routers/kg.py`、`backend/app.py`（include_router）、`frontend/src/lib/api.ts` + CognitionPage。
- 验收：① 三 endpoint 返客观数据（实体元数据/关系链接）；② 复用 kg_tools 不重写；③ 私有数据（持仓/研报）不进 endpoint；④ 缺数据返空 + data_status 不臆造。
- 合规：只返图谱客观数据，无私有数据，不碰选股分/§44v2。

### P2 大块（新建脚本/endpoint）

**3.4 EarningsCalendar /api/earnings-calendar 聚合**
- 需求：建 `/api/earnings-calendar` 聚合 per-code `/api/financials` + `/api/disclosure` + `/api/lockup`，按 deadline 排序 + 未披露预警。前端 EarningsCalendarPage 用 useQuery 替硬编码 DANGER_MONTHS。
- 受影响文件：`backend/routers/stock_data.py`（或新建 earnings_calendar.py）、`backend/app.py`、`frontend/src/pages/workspace/EarningsCalendarPage.tsx`、`frontend/src/lib/api.ts`。
- 验收：① 聚合三源按 deadline 排序；② 未披露预警标红；③ 缺数据 HonestEmptyState；④ 东财端点走 em_get 防封（disclosure/lockup）。
- 合规：东财走 em_get 不裸调 requests。

**3.5 S171ValueVerdict mock 消除**
- 需求：建 `backend/tools/long_value_run.py` 跑 S171 R2 verdict harness 落 Recorder（复用 _s44_wire.wire_verdict，S171 R3 存月度方法论参数见 _s44_wire.py:163）。前端 hook 自动返真值（/api/evaluation/dims 已返 Recorder snapshot）。
- 受影响文件：新建 `backend/tools/long_value_run.py`、`backend/scheduler/seed.py`（加 cron 定期跑）、`frontend/src/pages/S171ValueVerdict.tsx`。
- 验收：① long_value_run.py 跑 S171 verdict 落 Recorder；② 前端 mock 替真值（通过 /api/evaluation/dims）；③ verdict 可复现（不臆造）。
- 合规：判断可复现（公开数据 + 既定规则），不臆造/心算。

**3.6 QuantModels M2/M4**
- 需求：建 `/api/expectation-gap`（M2 预期差）+ `/api/transport/em-health`（M4 em_get 健康度）。
- 受影响文件：新建 `backend/routers/quant.py`（或加 stock_data）、`backend/app.py`、`frontend/src/pages/quant/QuantModelsPage.tsx`。
- 验收：① M2/M4 endpoint 返真实数据；② em-health 走 em_get 防封；③ 缺数据 HonestEmptyState。
- 合规：em_get 防封。

**3.7 AdvisoryPage 顾问团集成 grill-me**
- 需求：后端集成 grill-me skill（跑 6-lens 对抗审查返结果），或前端直调 skill 产物（跨工具备份）。
- 受影响文件：`backend/routers/advisory.py`（或新建）、`backend/ai/`、`frontend/src/pages/advisory/AdvisoryPage.tsx`。
- 验收：① 顾问团返 6-lens 对抗结果；② 不破坏现有 advisory endpoint；③ 守 §44/spec grill 规则（重大方法论变更才起 6-lens）。
- 合规：grill-me skill 已是 SDD 内嵌行为（CLAUDE.md §7），集成进后端 endpoint。

## 4. 验收标准（整体）

- P0 两项（BombAlert + DimensionGrid）接通后前端无 mock/静态壳。
- P1 Cognition 三 endpoint 复用 kg_tools 不重写。
- P2 四项新建脚本/endpoint 走 SDD（spec→plan→tasks→TDD）。
- 所有 endpoint 缺数据返 HonestEmptyState + data_status，不臆造。
- 东财端点走 em_get 防封。
- 私有数据（持仓/研报/API key）不进 endpoint。

## 5. 合规自查（工程底线）

- ✅ 不臆造数据：缺数据返 None + data_status（/api/evaluation/dims 已这么做，其他 endpoint 照做）。
- ✅ 私有数据隔离：endpoint 返客观图谱/估值/风控数据，私有持仓/研报只存 .vibe-research。
- ✅ em_get 防封：EarningsCalendar（disclosure/lockup）+ QuantModels em-health 走 em_get 不裸调 requests。
- ⚠️ §44 关联：S171ValueVerdict + DimensionGrid 涉及 §44 verdict，但本 spec 只接线/落 Recorder，不改 §44v2 守护区（lift_for_arm regime_caps 不动）。

## 6. 优先级 + 执行顺序

1. **P0 快赢**（S 工作量，已建 endpoint 前端接线）：BombAlert + DimensionGrid
2. **P1 中等**（M，复用建 router）：Cognition /api/kg/*
3. **P2 大块**（L，新建脚本/endpoint，走 SDD）：EarningsCalendar + S171 long_value_run + QuantModels + Advisory grill-me

## 7. 待定（需用户决策）

- Advisory 顾问团：后端集成 grill-me vs 前端直调 skill 产物（跨工具备份）——用户定。
- QuantModels M2/M4：预期差/em-health 数据源具体口径——用户定或后续 spec 细化。
