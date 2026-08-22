# Spec: S074 — market_phase 统一判定与盘后桩对接

> **状态**：spec 草案，待 grill
> **级别**：large（工作流主架构改动 + 盘后桩对接 + 前端状态机对齐）
> **起因**：用户主张"盘前盘后时间段应该统一（当日收盘到次日开盘）"——当前 22:00-08:00 非交易时段在 post-market 和 pre-market 之间断裂，且 `/api/workflow/post-market` 端点返回 `_not_implemented` 但 PostMarketReview 页面已绕过桩直接调子端点。

## 1. SOURCE_OF_TRUTH

### 1.1 现有实现基线（代码事实）

| 层 | 文件:行 | 现状 |
|---|---|---|
| **时间段判定** | `trading_workflow.py:38-88` `get_current_stage()` | ✅ 已有：08:00-09:30 pre-market / 09:30-15:00 intraday / 15:00-22:00 post-market / 22:00-08:00 "非交易时段"归 pre-market / 非交易日固定 pre-market |
| **盘后桩方法** | `workflow.py:552-554` `get_post_market_workflow()` | ❌ 返回 `_not_implemented("盘后复盘未实现")`——过时，PostMarketReview 页面已绕过 |
| **PostMarketReview 页面** | `PostMarketReview.tsx` | ✅ 已完整：三问（推了什么/买了什么/漏了什么）+ STI结算条 + 漏单结算 + 结算入口；调 `useDailyWinReview` + `useShadowComparison` + `useTransitionWorkflowState` + `usePreMarketBriefing`（绕过 post-market 端点） |
| **盘后调度** | `scheduled_tasks.py:447-452` | ✅ 已有4个任务：`sti_post_market`(15:30) / `candidate_funnel_precompute` / `forward_test_daily` / `forward_test_t1_settle` |
| **post_market_workflow 模块** | `post_market_workflow.py` | ✅ 模块存在：`PostMarketWorkflow` + `SettlementResult` dataclass |
| **前端状态机** | `Workflow.tsx:134` `STAGE_ORDER` | ✅ `["pre-market", "intraday", "post-market"]` 三段 |
| **死代码 hook** | `winrate.ts:166` `usePostMarketReview` | ⚠️ 定义了但 PostMarketReview.tsx 未调用 |

### 1.2 核心矛盾

1. **时间段断裂**：22:00-08:00 归 pre-market（"非交易时段"），但用户视角下收盘后到次日开盘是一个连续时段
2. **桩方法过时**：`/api/workflow/post-market` 返回"未实现"，但 PostMarketReview 页面已完整实现——API 与实际不一致
3. **死代码**：`usePostMarketReview` hook 定义但未调用，`getPostMarketReview` API 函数同

## 2. ARCHITECTURE_ROADMAP

### 2.1 market_phase 统一判定（核心）

**当前**：`get_current_stage()` 三段（pre-market/intraday/post-market），但 22:00-08:00 非交易时段归 pre-market 是错位——这段既不是盘前准备也不是盘中。

**目标**：仍是三段，但时间段边界修正——除了盘中（09:30-15:00），剩下的时间要么盘前要么盘后：

```
pre_market   = T 日 08:00 ~ T 日 09:30（竞价准备）
intraday     = T 日 09:30 ~ T 日 15:00（交易时段）
post_market  = T 日 15:00 ~ T+1 日 08:00（盘后总结+夜间+次日开盘前）
非交易日     = 固定 post_market（不推进到 intraday）
```

**唯一改动**：22:00-08:00 从"非交易时段归 pre-market"改为"归 post-market"——盘后从收盘到次日开盘是一个连续时段。

**关键决策点（待 grill）**：
- **Q1**：`market_phase` 函数放哪？`trading_workflow.py` 提取为独立模块，还是保持 `trading_workflow.get_current_stage()` 原地改？
- **Q2**：前端 STAGE_ORDER 保持三段不变（只改后端判定），还是同步调整？
- **Q3**：post_market 内部是否需子阶段标注（15:00-22:00 总结 / 22:00-08:00 夜间 / 08:00-09:30 盘前准备）？还是统一标 post_market？

### 2.2 盘后桩方法对接

**当前**：`workflow.py:552` 返回 `_not_implemented`

**目标**：桩方法返回真实 PostMarketReview 数据

**实现路径**：
- `get_post_market_workflow()` 改为调 `post_market_workflow.PostMarketWorkflow` 或聚合各子端点数据
- 返回 `PostMarketReport` 结构（`types.ts:1333` 已定义）
- **注意**：PostMarketReview.tsx 当前绕过端点直接调子端点——桩方法对接后，是否让页面改用端点？还是保持绕过？

### 2.3 死代码清理

- `usePostMarketReview` hook + `getPostMarketReview` API 函数——若桩方法对接后页面改用，则保留；若保持绕过，则删除

## 3. TODO_WORKFLOW

### Phase 1：market_phase 共享判定（medium）
- [ ] 提取 `get_current_stage()` 为共享 `market_phase` 函数
- [ ] 各路由（pre-market/intraday/post-market）统一调用
- [ ] 时间段定义对齐（22:00-08:00 归 post-market 或合并）
- [ ] 前端 STAGE_ORDER 对齐

### Phase 2：盘后桩对接（medium）
- [ ] `workflow.py:552` 桩方法改为真实实现
- [ ] 对接 `PostMarketWorkflow` 或聚合子端点
- [ ] 返回 `PostMarketReport` 结构

### Phase 3：死代码清理 + 测试（small）
- [ ] `usePostMarketReview` hook 处置（保留或删除）
- [ ] 测试：market_phase 判定边界 + post-market 端点返回真实数据

## 4. spec 逻辑冲突审查

| 历史 spec | 冲突点 | 处置 |
|---|---|---|
| **S026**（异步采集） | pre-market 异步采集内存缓存——market_phase 判定不改采集逻辑 | 不冲突 |
| **S036**（工作流标灰） | 标灰 post-market 端点——S074 取消标灰改为真实实现 | **替换**：S036 标灰 post-market 的决议被 S074 取代 |
| **S054**（盘后复盘） | PostMarketReview 三问已实现——S074 不重写页面，只对接端点 | 不冲突 |
| **S063**（T-1 硬标准） | pre-market 读 T-1 STI——market_phase 判定不改 T-1 视角 | 不冲突 |
| **S068**（工作流触发） | scheduled_tasks 盘后调度——market_phase 判定不改调度逻辑 | 不冲突 |

## 5. 数据支撑

- 当前 `get_current_stage()` 已有时间段判定，S074 是提取+统一，非从零实现
- PostMarketReview 页面已完整（三问+结算），S074 只对接端点，非重写
- 盘后调度4个任务已在跑，S074 不改调度

## 6. 验收标准

1. `market_phase` 共享判定函数存在，各路由统一调用
2. `/api/workflow/post-market` 返回真实 PostMarketReport（非 `_not_implemented`）
3. 前端 STAGE_ORDER 与后端 market_phase 对齐
4. 死代码（usePostMarketReview）处置完成
5. 测试：market_phase 边界（08:00/09:30/15:00/22:00/非交易日）+ post-market 端点返回真实数据

## 7. grill 决策树

- Q1：post_market + pre_market 合并还是保持两段？
- Q2：market_phase 函数放哪？
- Q3：前端 STAGE_ORDER 对齐？
- Q4：桩方法对接后页面改用端点还是保持绕过？
- Q5：死代码 hook 保留还是删除？
