# 任务拆分 · S087 工作流 tab 按 pipeline 步骤重设计

> 对应 spec.md + plan.md（分阶段 A/B/C）
> 规则：每阶段完成即验证；复用既有子页面不重写；前端预存改动迁移不覆盖。

---

## 阶段 A · 后端缓存表（R10）—— ✅ 已完成

| ID | 任务 | 改动文件 | 状态 |
|---|---|---|---|
| A1 | `funnel_cache.py`：save/load/list_cached_dates（sqlite VR_DATA_DIR/funnel_cache.db，OR REPLACE） | candidate_funnel/funnel_cache.py | ✅ |
| A2 | candidates 端点：POST 实跑+写缓存 / GET /candidates/funnel/cache 读 / GET /candidates/funnel/dates | routers/candidates.py | ✅ |
| A3 | round-trip 验证（非交易日 run_funnel → save → load → dump equal=True） | 手测 | ✅ |
| A4 | POST 2026-08-18 实跑写缓存（供前端读秒开） | 后台 | ⏳ 进行中 |

---

## 阶段 B · 前端 5-tab 重写

### B1：主干 Workflow.tsx 重写（依赖 B2/B3/B4 接口先定）

| ID | 任务 | 改动文件 | 验收 |
|---|---|---|---|
| B1.1 | Workflow.tsx 改 5-tab 结构（T-1/语境/盘前/盘中/盘后），PipelineProgressBar current 驱动默认 tab（stageKey 映射） | pages/Workflow.tsx | 5 tab 渲染 + 默认跟阶段 |
| B1.2 | 删两级 tab（战法/选股池）+ legacy 状态机降为盘前 tab 内折叠卡 | pages/Workflow.tsx | 旧入口不丢（折叠卡内） |
| B1.3 | 非涨停池站位（R12，独立来源提示，不混 dispatch_match） | pages/Workflow.tsx | 占位卡 |

### B2/B3/B4：新子组件（可并行）

| ID | 任务 | 改动文件 | 验收 |
|---|---|---|---|
| B2 | T1Tab.tsx：T-1 数据就绪卡（gene_scores/STI/天气/derived 新鲜度） | components/workflow/T1Tab.tsx | 状态卡渲染 |
| B3 | ContextTab.tsx：SentimentContext 卡（天气/熔断软标注/allowed_styles/4率） | components/workflow/ContextTab.tsx | 状态卡渲染 |
| B4.1 | StrategyMatchMatrix.tsx：票×战法命中 matrix（默认视图，每只票标命中战法） | components/workflow/StrategyMatchMatrix.tsx | matrix 渲染 |
| B4.2 | 按战法分列视图（可切，复用 10 战法卡片数据迁移） | components/workflow/StrategyMatchMatrix.tsx | 双视图切换 |

### B5：选股池缓存优先

| ID | 任务 | 改动文件 | 验收 |
|---|---|---|---|
| B5.1 | lib/candidates.ts 加 readFunnelCache（GET /cache）+ 保留 runFunnel（POST 实跑） | lib/candidates.ts | API 可调 |
| B5.2 | lib/query.ts 选股池 query 改缓存优先（读 cache，404→fallback POST 或空态+"重跑"按钮） | lib/query.ts | 秒开 + 重跑按钮触发实跑 |

### B6/B7：盘前/盘中/盘后 tab 内容接线

| ID | 任务 | 改动文件 | 验收 |
|---|---|---|---|
| B6.1 | 盘前①选股步：FunnelLayers + SelectionPipeline（读缓存，B5） | pages/Workflow.tsx | 选股步渲染 |
| B6.2 | 盘前②匹配步：StrategyMatchMatrix（B4） | pages/Workflow.tsx | 双视图 |
| B6.3 | 盘前③仓位步：advisory 结果 | pages/Workflow.tsx | 仓位卡 |
| B7.1 | 盘中 tab：IntradayMonitor + BombAlertPanel + IntradayCoach（统一，持仓行标 max_hold） | pages/Workflow.tsx | 盘中统一 |
| B7.2 | 盘后 tab：PostMarketReview + 拓扑入口 | pages/Workflow.tsx | 盘后聚合 |
| B7.3 | legacy 状态机折叠卡（StageCard 三阶段，盘前 tab 内） | pages/Workflow.tsx | 能力保留 |

### B8：R13 AskAiButton 各 tab 带上下文

| ID | 任务 | 改动文件 | 验收 |
|---|---|---|---|
| B8.1 | T-1/语境/盘前/盘中/盘后 5 tab 各带 AskAiButton + 该 tab 上下文构造 | pages/Workflow.tsx + 子组件 | 每 tab 有问 AI + context |

---

## 阶段 C · 联调验收

| ID | 任务 | 验收 |
|---|---|---|
| C1 | `npm run build` + tsc 无错 | 构建通过 |
| C2 | 浏览器手动验收：5 tab 切换 + 默认跟 stageKey + 双视图 + 缓存秒开 + AskAiButton 各 tab | 全绿 |
| C3 | 后端回归：`pytest -m "not live"`（funnel_cache 单测 + 既有端点 0 回归） | 全绿 |
| C4 | commit S087（spec + plan + tasks + A 后端 + B 前端） | 提交 |

---

## 依赖顺序

```
A（✅ 完成）── B5（缓存优先，依赖 A2 cache 端点）
            └ B2/B3/B4（独立子组件，可并行）── B1（主干，依赖子组件接口）── B6/B7（接线）── B8（AskAiButton）── C（联调）
```

B2/B3/B4 可并行（独立组件）；B1 依赖子组件 props 接口先定；B5 依赖 A2（已就绪）；B6/B7 依赖 B1+B4+B5；B8 贯穿各 tab；C 依赖 B 全完成。
