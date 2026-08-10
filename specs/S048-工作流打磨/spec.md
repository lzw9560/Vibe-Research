# Spec: S048 — 工作流打磨（固定阶段位 + 历史视角 + 缓存 + 拓扑精简）

> 状态：已实现（2026-08-10）
> 作者：Codex  日期：2026-08-10
> 级别：**medium**（跨前后端、>50 行；不接新外部源、无财务验算）
> 关联：grill 结论 `.scratch/grill-workflow-polish/plan.md`（7 决策锁定）；S026（盘前异步采集）、S036（盘中/盘后标灰）、S024（拓扑）、S032（状态机落库）、S046（空写防护同范式）
> 流程门（AGENTS.md 分级）：直接 develop 提交；`.scratch/` 单轮 review；简化验收（后端冒烟 + 关键路由）。用户指令：严格 SDD+TDD，测试先行。

## 1. 问题 / 目标

`/workflow` 三阶段页现有三个痛点：
1. **卡片重排**：Workflow.tsx `sortedStages` 按当前阶段动态重排，盘前/盘中/盘后位置随时间跳动，无法形成肌肉记忆。
2. **无历史回看**：盘前采集结果只存进程内存 `_cache`，重启即丢；选旧日期无处可查。
3. **缓存语义弱**：前端 staleTime 仅 30s/5min，页面切换/刷新反复拉数；后端重启后今日数据也要重采。
4. 附带：拓扑关系网边过密（fund_flow 共享 ≥1 天就连 + clique 爆炸），信息噪声大。

**目标**：阶段卡固定位；顶级日期选择器把历史视角传递到所有卡片；采集结果按日落盘快照（历史纯读盘、零外部请求）；历史不可变缓存 + 今日幂等不重拉；关系网按推荐方案精简。

## 2. 背景

- `backend/routers/workflow.py`：S026 异步采集 `_cache` 是进程内存 dict（注释自认"重启丢，盘前每日重采可接受"）；`refresh_pre_market(date)` 已支持 date 参数但 `get_pre_market_workflow(date)` **忽略** date 恒返内存态。
- `backend/vr_paths.py`：`resolve_data_dir()`（`VR_DATA_DIR` 可覆盖；backend/conftest.py 已在 import 前指临时目录隔离）、`last_trading_date_str()`。
- 前端：`usePreMarketBriefing` queryKey 无 date、staleTime 5min；QueryClient 全局 staleTime 30s、refetchOnWindowFocus false（main.tsx）；`useWorkflowStates(date)` 已存在（lib/query/workflow.ts）；`getWorkflowStates(date)` 已存在（lib/api/workflow.ts）。
- `backend/routers/topology.py`：`_pairwise_shared` 恒 `if shared`（≥1 即连）；sector/fund_flow/seat 走 `_collect_shared_sets` 骨架，ladder 独立；`build_relation_graph` 无度数封顶。
- 盘中/盘后页 S036 已标灰（`not_implemented` 结构化降级），本 spec 不改其端点行为。

## 3. 需求清单

- [x] R1 **固定阶段位**（Q6）：删 `Workflow.tsx` `sortedStages` 重排，恒按 盘前→盘中→盘后 渲染；当前阶段用既有高亮/徽标表达，不靠位置。
- [x] R2 **顶级日期选择**（Q1/Q2）：Workflow 首页 PageHeader 加日期选择器（`<input type="date">` + "回到今日"）；选中日期写入 URL query `?date=YYYY-MM-DD`；不带参数=今日实时（现状行为不变）。首页卡片链接进子页时携带 date。
- [x] R3 **历史视角卡片**（Q6）：date 存在时——盘前卡显示该日快照候选数（usePreMarketBriefing(date)），盘中卡=该日 monitoring 计数、盘后卡=settled 计数（useWorkflowStates(date) 的 counts），无数据显示 "--"；今日视角维持现状（candidateCount/signalCount/winRate）。历史视角停用 60s 轮询。
- [x] R4 **快照持久化**（Q4）：`_collect` done 后整体写 `.vibe-research/workflow/pre-market/<date>.json`（经 `resolve_data_dir()`），永久保留不清理。payload：`{schema:1, data_date, as_of, run_id, market_emotion, factors, funnel_layers, is_backfill}`；`is_backfill = target_date < last_trading_date_str()`（采集时刻判定）。写盘失败只 log 不阻断 done。
- [x] R5 **GET 按日分级降级**（Q3，向后兼容）：`GET /api/workflow/pre-market?date=` 按序：① 内存 data_date==d 且 running/done/error → 返内存态；② 内存 data_date==d 且 idle → idle 提示；③ 盘上有 `<d>.json` → done + `from_snapshot:true`（读盘内容，零外部请求）；④ d==last_trading_date_str() → idle；⑤ 否则 → `{status:"no_snapshot"}`。非法日期格式 → 400。
- [x] R6 **快照日期列表**（Q4）：新增 `GET /api/workflow/pre-market/dates` → `{dates:[...]}` 降序（目录内合法 `<date>.json` 文件名），供日期选择器标注哪些日期有快照。
- [x] R7 **补采入口**（Q3）：`no_snapshot` 页显提示 + 显式"补采"按钮（复用 `refresh(date)`，不自动触发）；UI 标注"补采数据可能与当日实盘所见有出入"。历史日期 done 后刷新按钮置灰（不可变），唯 no_snapshot 可补采。
- [x] R8 **缓存语义**（Q5）：`usePreMarketBriefing(date)` queryKey 含 date；staleTime 动态——历史日期或 status done → Infinity（幂等不重拉），其余 30s；running 维持 5s 轮询（refetchInterval 不受 staleTime 约束）；显式重采走既有 invalidate（前缀 `["limitup","preMarketBriefing"]` 天然覆盖带 date 的 key）。浏览器硬刷新重建缓存时后端走盘上快照即返（零外部请求）。
- [x] R9 **历史漏斗层随快照**：`_collect` 经独立函数 `_build_funnel_layers(date)`（asyncio.to_thread 跑 `run_funnel("all", date, config)`，config 取 `routers.candidates._store["config"]` lazy import，同 topology.py `_load_candidates` 范式）写入快照；PreMarketBriefing 页在 `from_snapshot` 时渲染 `briefing.funnel_layers`、停用 `useFunnelLayers` live 查询（历史零外部请求）。
- [x] R10 **拓扑精简·阈值**（Q7①②）：`_pairwise_shared` 加 `min_shared` 参数；fund_flow ≥3 共享日、sector ≥2 共享概念才连边；seat 维持 ≥1、ladder 不动。
- [x] R11 **拓扑精简·度数封顶**（Q7④）：`build_relation_graph` 加 `max_degree=4`——全部边按 weight 降序贪心，两端点度数均 <4 才保留（杜绝 clique 爆炸）。
- [x] R12 **拓扑精简·图例开关**（Q7①③）：EdgeLegend 加 `hidden`/`onToggle` props 变可点击 toggle（无 onToggle 时保持纯展示，兼容他处用法）；RelationGraph 默认 `hidden={"fund_flow"}`，过滤后再喂 GraphView，图例按未过滤边集判存在性。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/workflow.py` | `_collect` 写快照 + `_build_funnel_layers`；GET 按日分级降级；新增 `/dates`；`_snapshot_dir/_load_snapshot/_save_snapshot/_list_snapshot_dates` |
| `backend/routers/topology.py` | `_pairwise_shared(min_shared)`；sector/fund_flow 阈值；`build_relation_graph(max_degree=4)` |
| `backend/tests/test_workflow_snapshot.py`（新） | R4-R6/R9 行为单测 |
| `backend/tests/test_workflow_async.py` | `_collect` 测试补 monkeypatch `_build_funnel_layers`（否则真跑 run_funnel 碰外部源） |
| `backend/tests/test_topology.py` | coinflow 改 3 共享日；sector 补 1 共享不连；新增 cap 测试；端到端聚合按新阈值调整 |
| `frontend/src/lib/api/types.ts` | PreMarketBriefing：status 加 `"no_snapshot"`；加 `funnel_layers/from_snapshot/is_backfill`；新增 `PreMarketDates` |
| `frontend/src/lib/api/workflow.ts` | `getPreMarketBriefing(date?)`、`getPreMarketDates()` |
| `frontend/src/lib/query/limitup.ts` | `usePreMarketBriefing(date?, options?)` 动态 staleTime；`usePreMarketDates()` |
| `frontend/src/pages/Workflow.tsx` | 删 sortedStages；日期选择器；历史视角卡片数据源切换 |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | date 感知（URL query）；no_snapshot 补采 UI；历史置灰；from_snapshot 漏斗层 |
| `frontend/src/components/topology/EdgeLegend.tsx` | hidden/onToggle props |
| `frontend/src/components/topology/RelationGraph.tsx` | 默认隐藏 fund_flow + toggle 状态 |
| 前端测试（Workflow/PreMarketBriefing/EdgeLegend/RelationGraph） | 见 §8 TDD 清单 |

## 5. 设计方案

**快照格式与位置（R4）**：选 JSON 文件而非 SQLite——单写者（一次一个采集任务）、按日天然分区、可读可 gitignore、与 `.vibe-research/` 私有目录约定一致（vr_paths.py 头注）。payload 自含 schema 版本号供将来迁移。`funnel_layers` 序列化 `[l.model_dump(mode="json") for l in result.layers]`。

**GET 兼容分级（R5）**：内存优先于盘（running 态只能来自内存）；盘上快照只补"内存 idle/重启后"的空档。此序保证 `test_workflow_async.py` 现有 GET 三测试（显式传 date 且与内存 data_date 一致）走 ①② 分支不改行为。今日日期无快照返 idle（与现状一致，前端既有 idle→自动 refresh 链路不动）；非今日无快照返 no_snapshot（新态，前端显式补采）。

**历史不可变（R8）**：历史日期 done/快照之后任何"刷新"都不发请求——react-query 侧 staleTime Infinity + UI 置灰按钮双保险；唯一例外是 no_snapshot 补采（用户显式行为，碰外部源，UI 标注数据可能与当日所见有出入）。今日 done 后同样幂等：staleTime 函数按 `query.state.data?.status` 动态返 Infinity；重采只能经显式 invalidate。

**拓扑精简（R10-R12）**：阈值在后端（省带宽、所有消费方一致）；fund_flow 前端再默认隐藏（双保险，grill 决策①）；cap 在聚合层贪心（按 weight top-N，客观计数不附方向语义）。EdgeLegend 改可点击但保持"无 onToggle 即纯展示"的兼容面（TopologyPanel 他处若引用不受影响）。

**不选的方案**：
- SQLite 存快照：读少写少场景引入查询层纯增复杂度。
- 历史日期允许静默重采：违背 grill"历史纯读盘零外部请求"，且外部源历史数据会变（补采≠当日所见），只能显式补采 + 标注。
- localStorage persistQueryClient 扛浏览器硬刷新：后端快照已使硬刷新取数零外部成本，前端持久层属过度设计。

## 6. 验收标准

- [x] A1 `/workflow` 三卡片恒按 盘前→盘中→盘后 顺序，跨时段不变（删 sortedStages，测试断言渲染序）
- [x] A2 首页选历史日期 → URL 出现 `?date=`，盘前卡显示快照候选数，盘中/盘后卡显示 monitoring/settled 计数或 "--"
- [x] A3 `GET /api/workflow/pre-market?date=<有快照>` 返 `status=done, from_snapshot=true`，零外部请求（单测断言不触 factor_registry/astock）
- [x] A4 `GET ?date=<无快照非今日>` 返 `no_snapshot`；前端显示补采按钮 + 出入标注；补采后快照落盘可读
- [x] A5 `GET /api/workflow/pre-market/dates` 返降序快照日期列表
- [x] A6 后端重启后今日 GET 仍返 done（盘上快照），无需重采
- [x] A7 前端：历史日期或 done 后路由切换/返回不重发请求（staleTime Infinity 测试）；running 仍 5s 轮询
- [x] A8 `pytest backend/tests -m "not live"` 全过（含改稿后 test_topology / test_workflow_async）— 948 passed / 9 deselected
- [x] A9 `npx vitest run` + `tsc` 全过 — 36 files / 252 tests passed；tsc exit 0
- [x] A10 关系网：fund_flow 默认不显示、图例可点开；sector 仅共享 ≥2 概念相连；任意节点边数 ≤4

## 7. 合规与工程底线自查（逐条确认）

- [x] 不臆造数据：历史视角纯读快照原文；no_snapshot 明示无数据而非编造；补采 UI 标注"可能与当日所见有出入"
- [x] 用户私有数据隔离：快照落 `.vibe-research/`（gitignored），经 `resolve_data_dir()`（测试 conftest 已隔离）；不进 git
- [x] 不新增东财端点：补采复用既有因子/漏斗链路（既有 em_get 限流）；历史读盘零外部请求
- [x] 拓扑精简不附方向语义：阈值/cap 为客观计数裁剪，图例文案不变（§0 弱合规）
- [x] 快照含 as_of/data_date 来源戳，判断可复现

## 8. 测试计划（严格 TDD：红→绿，测试先行）

**后端红**（先写先跑红）：
1. `test_workflow_snapshot.py`：`_collect` done 落盘（payload 字段全）；`is_backfill` 判定；写盘失败不阻断 done；GET 分级降级五分支（内存 running/done/error/idle、盘快照 from_snapshot、今日 idle、非今日 no_snapshot）；非法日期 400；`/dates` 空/排序/忽略非日期文件；`_build_funnel_layers` 被 monkeypatch 验证调用。
2. `test_topology.py` 改稿：coinflow 3 共享日→weight=3、2 共享日→无边；sector 1 共享概念→无边；cap：中心节点 >4 边 → 保留 top4 weight；端到端聚合适配新阈值。

**后端绿**：实现 workflow.py 快照层 + GET 改造；topology.py 阈值 + cap。跑 `pytest tests/test_workflow_snapshot.py tests/test_workflow_async.py tests/test_topology.py` 全绿，再全量 `-m "not live"` 无回归。

**前端红**：
3. Workflow.test：三卡片固定序（mock 不同 currentStage 也恒序）；日期选择器写 URL；历史视角卡片取数（mock briefing/states）。
4. PreMarketBriefing.test：no_snapshot 显示补采按钮与标注；历史 done 置灰刷新；from_snapshot 用快照 funnel_layers（不触发 live funnel 查询）。
5. EdgeLegend/RelationGraph.test：toggle 开/关过滤 fund_flow；默认隐藏。

**前端绿**：实现各组件；`npx vitest run` + `tsc --noEmit` 全绿。

**冒烟**：起后端 `uvicorn`，curl `/api/workflow/pre-market`（今日 idle/refresh/done 落盘）、`?date=` 快照分支、`/dates`；前端 dev server 手动过一遍：今日视角 → 选历史日期 → 补采 → 回到今日。

## 9. 风险与回滚

- **快照膨胀**：每日一个 JSON（百 KB 级），永久保留——可接受（grill 明确不清理）；风险低。
- **fund_flow ≥3 阈值过严**：边显著变少可能弱化真实共流入信号——前端默认隐藏本就打算弱化；若用户体感过严，阈值是 `_pairwise_shared` 单参数，回退一行。
- **cap=4 裁掉高权重边**：贪心按 weight 降序保留，弱边先丢；客观计数语义不变。
- **兼容回归**：GET 分级序若写错会破 `test_workflow_async.py` 三测试——CI 即见，回滚 `git revert` 单 commit（medium 一 spec 一 commit）。
- **工作树纠缠**：本 worktree 有他会话未提交改动（config.py/limitup 系列等），提交时只 `git add` 本 spec §4 清单内文件。
