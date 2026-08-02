# 打板工作流 P1 打磨 · 设计文档

> 日期：2026-08-02
> 来源：用户 P1 验收反馈（5 项）
> 范围：分两批 — S021（1-4 项，因子解耦+可用性）、S022（第 5 项，拓扑展示）
> 合规：遵守 CLAUDE.md §1 弱合规 + AGENTS.md 工程底线（不臆造/私有数据隔离/防封）

---

## 背景与痛点

用户 P1 验收反馈 5 项：
1. 盘前简报没数据（走旧 pre_market_workflow，未接 P1 漏斗产出）
2. 子条目点不进详情（候选无点击进诊断卡交互）
3. 漏斗看不到每层筛选结果和筛选条件（FunnelLayers 只展示计数+被过滤，无规则/无通过候选/不可调参）
4. 真实数据不要 mock（sources 实为真实采集，但静默返空给人"假数据"观感）
5. 增加拓扑展示（关系网+流程拓扑+连板梯队树）

## 架构决策

**选股因子与工作流解耦**：选股因子作为独立可插拔组件，多套并存；工作流编排层调用因子，不绑死某一标准。

理由（用户）：① 现阶段无法评判两套选股标准优劣；② 因子应独立存在，工作流调用因子组件把流程串起来。

## 分批

- **S021「P1 漏斗可用性与因子解耦」**：痛点 1-4，本质是让 P1 漏斗真正可用、可观测、接通工作流。强耦合，一起做。
- **S022「拓扑展示」**：痛点 5，独立新维度，单独 spec。

---

## S021 设计

### 1. 选股因子接口（地基）

`backend/factors/base.py` 新建：

```
class FactorResult:
    factor_id: str            # "limitup_screener" / "candidate_funnel"
    factor_name: str
    candidates: list[Candidate]   # 候选（code/name/source_layer/命中规则）
    layers: list[FunnelLayer]      # 旧因子单层包装；漏斗多层
    config: dict                   # 本次阈值/参数（可复现）+ data_status
    as_of: str                     # 取数时点
    data_date: str                 # 数据日期（非交易时段=上一交易日）

class SelectionFactor(Protocol):
    factor_id: str
    def fetch(self, date, config) -> FactorResult: ...
    def describe(self) -> dict:    # 因子说明（怎么选的、用哪些维度）
```

- **LimitupScreenerFactor 适配**：复用旧 PreMarketWorkflow（八项标准+战法+仓位），包成 FactorResult（candidates 带战法/仓位/参考价位，layers=单层"八项标准过滤"）。旧代码不改，只加适配层。
- **CandidateFunnelFactor 适配**：复用 run_funnel，原生多层。
- **注册表**：`factors/registry.py`，因子按 id 注册，工作流/前端按 id 调用。新因子将来加一条注册即可。

### 2. 盘前简报接因子 + 工作流编排

- **端点**：`GET /api/workflow/pre-market` → `{ factors: FactorResult[], data_date, market_emotion }`，遍历注册表调每个因子 fetch。非交易时段 data_date=上一交易日。
- **前端 PreMarketBriefing**：顶部市场情绪；下方按因子分区（折叠区并列），每区含因子名+说明、候选数、漏斗层概览（可展开）、候选列表（可点进详情）。两套并列对比。
- **数据未取得处理**：因子 fetch 取不到 → candidates=[] + config.data_status="未取得"+reason，前端如实显示"该因子数据未取得：原因"，不静默空白。
- **工作流编排**：trading_workflow.run_pre_market 改调因子注册表，不直绑 PreMarketWorkflow。旧 PreMarketWorkflow 类保留，被 LimitupScreenerFactor 复用。

### 3. 候选详情页（依据链呈现）

- 漏斗各层"通过候选"清单每只票可点击 → `/workflow/candidates/:code` 路由。
- 详情页用 P1 DiagnosisCard，补全依据链：
  - 入口层（来源因子+来源层）
  - 命中规则 rules_applied（含情绪档位标注，如"换手≥10%（阴天自适应，基数8）"）
  - 六类指标实际取值 + 活跃度档位
  - missing 项"未取得"+原因（AC6）
  - 当时阈值/情绪档位（adjustment）
- 后端 candidates.py:59 诊断接口已有，candidates 新增 source_factor_id + source_layer 字段。

### 4. 漏斗每层可观测可调参

- FunnelLayers 每层卡片新增三块：
  1. 筛选条件（规则/阈值+情绪档位标注）
  2. 通过的候选清单（code/name，可点进详情）
  3. 当面调参重跑
- **逐层确认交互**：调参 → 只重跑该层 → 展示新结果 → 提供"下游全跑"按钮 → 用户点才往下重跑。
- 后端 FunnelLayer 新增 conditions: list[str]（规则可读描述）+ passed: list[Candidate]。get_layers 返回这些。

### 5. 真实数据链路

- `vr_paths.last_trading_date()`：非交易时段（周末/节假日/盘后）返回最近 A 股交易日。各因子 fetch 收到非交易日内部转上一交易日，data_date 如实标注。
- **去静默返空**：所有 source 取数失败返 data_status="未取得"+reason，不静默空 dict。漏斗层区分"采集到 0 个"和"采集失败"。
- watchlist_in 无自选标"无自选标的"（非采集失败），与"未取得"区分。
- 不动 astock/limitup_screener 采集逻辑，只改 candidate_funnel sources 错误处理口径。

### S021 验收标准

- AC1：盘前简报展示两套因子产出并列，数据未取得如实显示原因。
- AC2：候选标的可点击进入诊断卡详情，详情含完整依据链（入口层/规则/取值/missing/阈值档位）。
- AC3：漏斗每层展示筛选条件+通过候选+可调参；调参只重跑该层，结果确认后用户决定是否下游全跑。
- AC4：非交易时段漏斗用上一交易日数据正常跑，取不到标原因，不静默返空。
- AC5：因子接口可插拔，新因子加注册即可被工作流调用（扩展性）。
- AC6（合规）：详情/漏斗不输出方向结论词，只出客观分档+依据；连板梯队原始池如实呈现 code/name。

---

## S022 设计

### 共用图引擎

`frontend/src/components/topology/` 新建，基于 echarts graph/tree（已在依赖）。统一 `GraphData { nodes, edges }` 格式，三个拓扑各一个数据 builder。

### 5.1 关系网拓扑

- 节点 = 候选标的（漏斗定稿池 + 旧因子候选池，去重）
- 边核心集（先收敛四种）：
  - `sector` 同板块联动
  - `fund_flow` 资金流共流入
  - `ladder` 连板梯队
  - `seat` 龙虎榜共席位
- 边权重 = 关联强度；力导向布局，同板块聚簇；节点可点进诊断卡。
- **扩展位**：EdgeType 枚举 + EdgeProvider 注册表。新关系（题材发酵/北向共持/大宗关联）将来加 provider，不动视图。

### 5.2 漏斗流程拓扑

- 节点 = 漏斗层（R1→R2→R3 + 自选），旧因子单层节点
- 边 = 数据流向；每节点标 input/output/过滤条件，点节点展开该层候选
- 复用 FunnelLayer 数据，漏斗的流程图视角

### 5.3 连板梯队树

- 数据源 = astock.em_zt_topic_pool（涨停四池原始池）
- 树：根=当日涨停，按连板高度分层，同题材归枝
- 客观呈现 code/name（AGENTS.md 允许原始池出口）

### S022 扩展设计

- EdgeProvider 注册表：新边类型加 provider 即可，视图代码不动。
- 图引擎 GraphData 统一格式，新拓扑加 builder 即可。
- 节点点击复用 S021 详情页路由。

### S022 验收标准

- AC1：三拓扑视图渲染，数据来自真实采集（非 mock）。
- AC2：关系网四种边核心集生效，节点可点进诊断卡。
- AC3：EdgeProvider 注册表可扩展（加新边类型不改视图）。
- AC4：连板梯队树如实呈现 code/name，按高度分层。

---

## 影响文件

**S021 新增**：`backend/factors/{base,registry,limitup_screener_factor,candidate_funnel_factor}.py`、`frontend/src/pages/workflow/CandidateDetail.tsx`
**S021 改动**：`backend/routers/{workflow,candidates}.py`、`backend/trading_workflow.py`、`backend/candidate_funnel/{sources/*,models}.py`、`backend/vr_paths.py`、`frontend/src/pages/workflow/PreMarketBriefing.tsx`、`frontend/src/components/candidate/{FunnelLayers,DiagnosisCard}.tsx`
**S022 新增**：`frontend/src/components/topology/{GraphView,RelationGraph,FunnelFlow,BoardLadder}.tsx`、`backend/routers/topology.py`

## 不做

- P2 盘中信号、P3 盘后结算、P4 企稳触发器（各自独立 spec）
- 参考价位 opt-in（研究模式 spec）
- 拓扑的"一切维度"（S022 只做核心集，其余扩展位）
