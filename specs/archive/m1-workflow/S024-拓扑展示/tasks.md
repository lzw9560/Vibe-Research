# 任务拆分 · S024 拓扑展示

> 对应：`spec.md`、`plan.md`
> 依赖：S023（因子产出/Candidate 详情路由/FunnelLayer conditions+passed）

---

## 阶段 A · 共用图引擎（R1）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| A1 | GraphView 组件：接收 GraphData，echarts graph 渲染，节点点击回调 | — | `topology/GraphView.tsx` | mock GraphData → 渲染节点边 |
| A2 | GraphData 类型定义 + EdgeType 枚举 | — | `topology/types.ts` | tsc 过 |

## 阶段 B · 关系网（R2，AC2）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| B1 | backend EdgeProvider Protocol + 注册表 | — | `routers/topology.py` | 注册假 provider → 返回边 |
| B2 | sector provider（同板块联动，查 concept_blocks） | B1 | `routers/topology.py` | mock 候选 → 返回 sector 边 |
| B3 | fund_flow provider（共流入，查 stock_fund_flow_120d） | B1 | `routers/topology.py` | mock → 返回 fund_flow 边 |
| B4 | ladder provider（连板梯队，em_zt_topic_pool） | B1 | `routers/topology.py` | mock → 返回 ladder 边 |
| B5 | seat provider（共席位，dragon_tiger_board） | B1 | `routers/topology.py` | mock → 返回 seat 边 |
| B6 | `GET /api/topology/relation` 聚合四 provider | B2-B5 | `routers/topology.py` | curl → GraphData 含四类边 |
| B7 | RelationGraph 前端：调接口，传 GraphView，节点点击进详情 | A1,B6 | `topology/RelationGraph.tsx` | 渲染；点击跳 CandidateDetail |

## 阶段 C · 漏斗流程拓扑（R3）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| C1 | FunnelFlow 前端：复用 funnel/layers 数据，构树形 GraphData | A1 | `topology/FunnelFlow.tsx` | 渲染漏斗层节点+流向边 |
| C2 | 节点点击展开该层 passed 候选 | C1 | `topology/FunnelFlow.tsx` | 点节点 → 展开候选列表 |

## 阶段 D · 连板梯队树（R4，AC4）

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| D1 | `GET /api/topology/board-ladder` 调 em_zt_topic_pool，构梯队树 | — | `routers/topology.py` | curl → 树含连板高度分层 |
| D2 | BoardLadder 前端：echarts tree，按高度分层，同题材归枝，呈现 code/name | A1,D1 | `topology/BoardLadder.tsx` | 渲染；code/name 如实呈现 |

## 阶段 E · 集成与扩展位

| ID | 任务 | 依赖 | 改动文件 | 验收方式 |
|---|---|---|---|---|
| E1 | 拓扑视图入口（workflow 页加 tab/路由） | B7,C1,D2 | `pages/workflow/`、`router.tsx` | 三视图可切换 |
| E2 | EdgeProvider 扩展位验证：加假新边类型不改视图 | B1 | — | 新 provider 注册 → 视图自动显示 |
| E3 | 全量 tsc + live 冒烟 | A-D | — | tsc 过；三拓扑 live 渲染 |
| E4 | 合规自查：拓扑只客观关联，无方向词 | — | — | grep 无方向词 |
