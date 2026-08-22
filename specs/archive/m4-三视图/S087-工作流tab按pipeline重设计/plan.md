# 技术方案 · S087 工作流 tab 按 pipeline 步骤重设计

> 对应 spec.md（2026-08-20，grill 锁定 13 项需求 + 3-agent 战法分叉分析）
> 分阶段：A 后端缓存表（已先做）→ B 前端 5-tab 重写 → C 联调验收

---

## 0. 依据与复用清单

| spec 需求 | 复用的现有能力 | 代码事实 |
|---|---|---|
| R1 5-tab pipeline | `PipelineProgressBar`（5 节点 t1/ctx/pre/intraday/post，current 驱动） | components/workflow/PipelineProgressBar.tsx |
| R4/R5 盘前选股步 | `FunnelLayers` + `SelectionPipeline` 组件 + `run_funnel` R1-only | components/candidate/FunnelLayers.tsx, components/pipeline/SelectionPipeline.tsx |
| R6 战法匹配双视图 | `dispatch_match` 12 战法命中（S086） | strategy_base.dispatch_match；前端新建 StrategyMatchMatrix |
| R7 仓位步 | `PositionAdvisor` + advisory 端点 | position_advisor*.py, /api/advisory/* |
| R8 盘中统一 | `IntradayMonitor`/`BombAlertPanel`/`IntradayCoach` 子页 | pages/workflow/*.tsx |
| R9 盘后聚合 | `PostMarketReview` 子页 + backtest/daily_review 端点 | pages/workflow/PostMarketReview.tsx |
| R10 缓存优先 | `run_funnel` 内存 `_FUNNEL_CACHE`（进程级，重启丢）→ 落表持久化 | funnel.py:57；新建 funnel_cache.py |
| R11 legacy 保留 | 现有 StageCard 状态机视图 → 折叠卡 | Workflow.tsx StageCard |
| R13 AskAiButton | 现有 `AskAiButton context=` 已用 | components/ui/AskAiButton.tsx |
| 分叉分析 | 3-agent workflow 结论：分叉主轴=匹配，R1/R3/盘中不分叉，R2/match/入场/仓位/卖出/结算分叉 | spec §2 + workflow journal |

---

## 1. 目录结构

### 1.1 新增文件
```
backend/
└── candidate_funnel/funnel_cache.py          # 【已建】run_funnel 结果落库（save/load/list）
frontend/src/
├── components/workflow/
│   ├── T1Tab.tsx                              # 【新】T-1 数据就绪状态卡（薄）
│   ├── ContextTab.tsx                         # 【新】SentimentContext 决策语境卡（薄）
│   └── StrategyMatchMatrix.tsx                # 【新】票×战法命中 matrix + 按战法分列双视图
└── pages/Workflow.tsx                         # 【改】5-tab pipeline 重写
```

### 1.2 改动文件
```
backend/routers/candidates.py                 # 【已改】POST 写缓存 + GET /cache + GET /dates
frontend/src/
├── lib/candidates.ts                         # 【改】加 readFunnelCache + runFunnel 保留
├── lib/query.ts                              # 【改】选股池 query 缓存优先（读 cache，fallback POST）
└── components/workflow/PipelineProgressBar.tsx # 【改】节点可点击跳 tab（可选）
```

---

## 2. 分阶段计划

### 阶段 A：后端缓存表（R10）—— ✅ 已完成

| 任务 | 文件 | 状态 |
|---|---|---|
| A1 `funnel_cache.py`：save/load/list_cached_dates（sqlite，VR_DATA_DIR/funnel_cache.db） | candidate_funnel/funnel_cache.py | ✅ |
| A2 candidates 端点：POST 实跑+写缓存 / GET /cache 读 / GET /dates | routers/candidates.py | ✅ |
| A3 round-trip 验证（save→load→dump equal=True） | 手测 | ✅ |
| A4 POST 2026-08-18 写缓存（供前端读秒开） | 后台跑 | ⏳ 进行中 |

### 阶段 B：前端 5-tab 重写

| 任务 | 文件 | 内容 |
|---|---|---|
| B1 `Workflow.tsx` 重写 | pages/Workflow.tsx | 5-tab（T-1/语境/盘前/盘中/盘后）+ PipelineProgressBar current 驱动默认 tab；删两级 tab + legacy 视图降为折叠卡 |
| B2 `T1Tab.tsx` | 新建 | T-1 数据就绪状态卡：gene_scores/STI/天气/derived 新鲜度 |
| B3 `ContextTab.tsx` | 新建 | SentimentContext 卡：天气/熔断软标注/allowed_styles/4率 |
| B4 `StrategyMatchMatrix.tsx` | 新建 | 盘前②步：票×战法命中 matrix（默认）+ 按战法分列（可切）；复用 10 战法卡片数据 |
| B5 `lib/candidates.ts` + `lib/query.ts` | 改 | 选股池 query 缓存优先：读 GET /cache 秒开，fallback POST 实跑 + 重跑按钮 |
| B6 盘前 tab 三步 | Workflow.tsx 内 | ①选股（FunnelLayers+SelectionPipeline 读缓存）→ ②匹配（StrategyMatchMatrix）→ ③仓位（advisory） |
| B7 盘中/盘后 tab | Workflow.tsx 内 | 盘中=IntradayMonitor+BombAlertPanel+IntradayCoach（统一，持仓行标 max_hold）；盘后=PostMarketReview+拓扑入口 |
| B8 R13 AskAiButton | 每 tab | 5 tab 各带 AskAiButton + 该 tab 上下文构造（T-1=数据状态/语境=SentimentContext/盘前=候选命中仓位/盘中=持仓预警/盘后=结算胜率） |
| B9 legacy 状态机保留 | Workflow.tsx 内 | StageCard 三阶段折叠卡（盘前 tab 内，不删能力）+ 非涨停池站位 |

### 阶段 C：联调 + 验收

| 任务 | 内容 |
|---|---|
| C1 `npm run build` 通过 + tsc 无错 | 前端构建 |
| C2 浏览器手动验收 | 5 tab 切换 + 默认跟 stageKey + 双视图切 + 缓存秒开 + AskAiButton 各 tab 带上下文 |
| C3 后端回归 | `pytest -m "not live"`（funnel_cache 单测 + 既有端点 0 回归）|
| C4 提交 | commit S087（spec + plan + tasks + 后端缓存表 + 前端 5 tab） |

---

## 3. 依赖顺序

```
A 后端缓存表（✅ 已完成，前端 B5 依赖 A2 的 cache 端点）
    ↓
B 前端 5-tab 重写（B1 主干 ← B2/B3/B4 子组件 ← B5 缓存优先 ← B6/B7/B8/B9 接线）
    ↓
C 联调验收
```

B2/B3/B4 可并行（独立子组件），B1 依赖 B2/B3/B4 的 props 接口（先定接口再写）。B5 依赖 A2（已就绪）。

---

## 4. 取舍

- **复用既有子页面 vs 全重写**：选复用（PreMarketBriefing 等 6 个子页作 tab 内容/链接），降工作量 + 不丢能力。
- **5 tab 真独立 vs 3 tab + 5 进度段**：选 5 真独立（grill 确认，T-1/语境显式化前置步骤）。
- **缓存落库 vs 分步端点 vs 前端超时**：选落库（run_funnel 结果持久化，盘后定时跑，前端读秒开，实跑按钮兜底）。
- **匹配双视图 vs 单视图**：选双视图（票×战法 matrix 默认 + 按战法分列可切，grill 确认 c）。
- **盘中分叉 vs 统一**：选统一（炸板=市场事件，3-agent 确认不分叉）。

---

## 5. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| Workflow.tsx 大重写 | 中 | 分组件拆（B2/B3/B4 独立），legacy 折叠卡不删能力 |
| 前端预存改动（战法卡片更新） | 低 | 已确认是用户之前更新（非并发重设计），重写时迁移 10 战法卡片数据到 B4 按战法分列 |
| funnel_cache.db schema | 低 | 纯落库无迁移；表不存在时 _get_db 建表；load 损坏返 None fallback 实跑 |
| 并发编辑器 | 中 | 显式 git add 具体文件，绝不 add -A |

回滚：前端 git revert + 删 funnel_cache.py + candidates 端点 revert（纯代码 + 1 本地表，无数据迁移）。
