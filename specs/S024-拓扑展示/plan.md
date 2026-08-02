# 技术方案 · S024 拓扑展示

> 对应：`spec.md`、`tasks.md`
> 原则：复用 S023 因子产出/详情路由；echarts 6 已在依赖；不写方向（合规）。

## 1. 文件结构

### 新增 `frontend/src/components/topology/`
| 文件 | 职责 |
|---|---|
| `GraphView.tsx` | 共用图引擎：接收 GraphData，渲染 echarts graph/tree，节点点击回调 |
| `RelationGraph.tsx` | 关系网：调 `/api/topology/relation`，传 GraphData 给 GraphView |
| `FunnelFlow.tsx` | 漏斗流程拓扑：复用 funnel/layers 数据，构树形 GraphData |
| `BoardLadder.tsx` | 连板梯队树：调 `/api/topology/board-ladder` |

### 新增 `backend/routers/topology.py`
- `GET /api/topology/relation` → 关系网 GraphData（节点=候选，边=四核心集）
- `GET /api/topology/board-ladder` → 连板梯队树（em_zt_topic_pool）
- 漏斗流程拓扑数据复用 `/api/workflow/funnel/layers`（S023），前端构建

## 2. 数据结构

```typescript
// GraphData 统一格式
interface GraphNode { id: string; name: string; category?: string; value?: number; code?: string }
interface GraphEdge { source: string; target: string; type: EdgeType; weight: number }
interface GraphData { nodes: GraphNode[]; edges: GraphEdge[] }
type EdgeType = 'sector' | 'fund_flow' | 'ladder' | 'seat'  // 可扩展
```

```python
# backend EdgeProvider 注册表
class EdgeProvider(Protocol):
    edge_type: str
    def build_edges(self, candidates: list) -> list[dict]: ...

# 注册：sector/fund_flow/ladder/seat 四个 provider
```

## 3. 三视图设计

### 关系网
- 节点=候选标的（漏斗定稿池+旧因子候选池，去重）
- 边四核心集：sector（同板块，查 astock.concept_blocks）/fund_flow（共流入，查 stock_fund_flow_120d）/ladder（连板梯队，em_zt_topic_pool）/seat（共席位，dragon_tiger_board）
- 力导向布局，同板块聚簇；节点点击→S023 详情路由
- 边权重：seat=3(强)/ladder=2/fund_flow=2/sector=1(中)

### 漏斗流程拓扑
- 节点=漏斗层（R1→R2→R3+自选），旧因子单层
- 边=数据流向；每节点标 input/output/conditions，点节点展开该层 passed 候选
- echarts tree 布局

### 连板梯队树
- em_zt_topic_pool 涨停四池原始池
- 树：根=当日涨停，按连板高度分层（1板/2板/3板…），同题材归枝
- 如实呈现 code/name（AGENTS.md 允许）
