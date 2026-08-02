# Spec: S024 — 拓扑展示

> 状态：草案
> 作者：Codex（brainstorming 对齐用户）  日期：2026-08-02
> 关联：`../S023-漏斗可用性与因子解耦/spec.md`（因子产出/详情路由）、`../../ARCHITECTURE.md`、`../../CLAUDE.md` §1
> 设计文档：`../../docs/superpowers/specs/2026-08-02-daban-workflow-p1-polish-design.md`

---

## 1. 问题 / 目标

打板工作流缺拓扑视角：候选标的关系（板块/资金/连板/席位）不可见、漏斗数据流向不可视、连板梯队接力结构不直观。目标：新增三类拓扑视图——关系网、漏斗流程、连板梯队树，共用图引擎，先收敛核心边集并留 EdgeProvider 扩展位。

## 2. 背景

- 候选标的关系需多维度关联：板块联动、资金流共流入、连板梯队、龙虎榜共席位（用户："一切可能影响交易的维度"，先收敛核心集）。
- 漏斗 FunnelLayer 数据已有（S023 加 conditions/passed），可复用为流程拓扑节点。
- 连板梯队数据源 `astock.em_zt_topic_pool`（涨停四池原始池）已实现，AGENTS.md 允许如实呈现 code/name。
- 前端 echarts 6 已在依赖（graph/tree 组件）。

## 3. 需求清单

- [ ] R1 共用图引擎：`components/topology/GraphView` 基于 echarts，统一 `GraphData { nodes, edges }` 格式。
- [ ] R2 关系网拓扑：候选标的为节点，四种边（sector/fund_flow/ladder/seat），力导向布局，节点可点进诊断卡。
- [ ] R3 漏斗流程拓扑：漏斗层为节点，数据流向为边，点节点展开该层候选。
- [ ] R4 连板梯队树：em_zt_topic_pool 数据，按连板高度分层，同题材归枝，如实呈现 code/name。
- [ ] R5 扩展位：EdgeType 枚举 + EdgeProvider 注册表，新边类型加 provider 不动视图。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/components/topology/GraphView.tsx` | 新建：共用图引擎 |
| `frontend/src/components/topology/RelationGraph.tsx` | 新建：关系网 |
| `frontend/src/components/topology/FunnelFlow.tsx` | 新建：漏斗流程拓扑 |
| `frontend/src/components/topology/BoardLadder.tsx` | 新建：连板梯队树 |
| `backend/routers/topology.py` | 新建：拓扑数据接口 |
| `frontend/src/pages/workflow/` | 改：加拓扑视图入口 |
| `frontend/src/router.tsx` | 改：加拓扑路由 |

## 5. 设计方案

详见设计文档 §S024。要点：
- 共用 GraphData 格式，三视图各一 builder。
- 关系网边核心集：sector（同板块）/fund_flow（共流入）/ladder（连板梯队）/seat（共席位）。权重=关联强度，同板块聚簇。
- EdgeProvider 注册表：新关系（题材发酵/北向共持/大宗关联）将来加 provider。
- 连板梯队树如实呈现 code/name（AGENTS.md 允许原始池出口）。
- 节点点击复用 S023 详情路由。
- 备选（不选）：一次做"一切维度"——范围无限膨胀拖慢落地，故先收敛核心集+扩展位。

## 6. 验收标准

- [ ] A1 三拓扑视图渲染，数据来自真实采集（非 mock）
- [ ] A2 关系网四种边核心集生效，节点可点进诊断卡
- [ ] A3 EdgeProvider 注册表可扩展（加新边类型不改视图代码）
- [ ] A4 连板梯队树如实呈现 code/name，按高度分层
- [ ] A5 合规：拓扑只呈现客观关联，不输出方向结论；连板梯队原始池如实呈现

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力；拓扑只呈现客观关联
- [x] 判断可复现：边基于公开数据（板块/资金流/连板/席位），规则可查
- [x] 涨停四池/连板股榜个股属公开榜单客观事实，可呈现 code/name
- [x] 用户私有数据未进 git
- [x] 新增东财端点走 `em_get()` 限流（复用现有 em_zt_topic_pool，不新增）

## 8. 测试计划

- 离线：拓扑 builder 单测（mock GraphData 构造）
- live 冒烟：起 uvicorn → `GET /api/topology/relation` 返回节点边 → `GET /api/topology/board-ladder` 返回梯队树
- 前端：`npx tsc --noEmit`；vite 起 → 三拓扑视图渲染 + 节点点击进详情

## 9. 风险与回滚

- 拓扑组件独立目录，回滚=删 `components/topology/` + 还原 router。
- 关系网边计算量大时考虑后端预聚合缓存（首版可前端实时算，候选规模有限）。
