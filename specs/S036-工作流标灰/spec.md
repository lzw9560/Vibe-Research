# Spec: S036 — 工作流标灰（S012 修订版：适配 S033/S034 后的前端结构）

> 状态：已实现（2026-08-09）
> 作者：Codex  日期：2026-08-08
> 关联：`../S012-工作流标灰/spec.md`（原始 spec，草案状态，前提已变）、`../S033-状态机前端呈现/spec.md`（状态机 UI 已落地）、`../S034-结算接线/spec.md`（transition 即结算已落地）、`backend/realtime_workflow.py`、`backend/post_market_workflow.py`、`backend/routers/workflow.py`
>
> 级别：**medium**（跨前后端层，改端点返回体 + 前端页面改渲染逻辑 + 后端桩清理）

## 1. 问题 / 目标

S012（2026-07-29 草案）提出"realtime/post_market 桩标灰"，但 S033（状态机前端）和 S034（transition 即结算）落地后，S012 的前提已变：

- S034 已实装 transition 即结算（`record_settlement` 写 winrate.db），`post_market_workflow._settle_recommendations` 桩不再被结算路径调用——S034 spec 明确"不实现盘后批量结算（桩范围）"。
- S033 已建状态机前端（状态徽标 + 流转按钮 + 抽屉状态卡），但 `IntradayMonitor.tsx` / `PostMarketReview.tsx` / `BombAlertPanel.tsx` 三页**仍然调用桩端点**，把空结果当成品呈现：
  - `IntradayMonitor` 调 `useIntradayData()`（`/workflow/intraday`）→ signals 永远空 → 显示"暂无信号"；alerts 永远空 → 显示"暂无预警"。
  - `PostMarketReview` 调 `usePostMarketReview()`（`/workflow/post-market`）→ settlements 永远空 `[]`；llm_review 返回"盘后复盘功能待实现"。
  - `BombAlertPanel` 调 `useBombAlerts()`（`/workflow/alerts`）→ alerts 永远空。
- 后端五个端点（`/workflow/realtime`、`/workflow/intraday`、`/workflow/post-market`、`/workflow/signals`、`/workflow/alerts`、`/workflow/settle`）每次被调都跑桩逻辑——前端不调了就是死负载。
- `pre_market_workflow._build_strategy_match` 死代码——**已不存在**（S012 R3 已免做，grep 零命中）。

**目标**：前端三页停止调用桩端点，直接渲染"未实现"态；后端端点返回结构化 `not_implemented` 响应，不跑桩逻辑。不补任何功能。

## 2. 背景

- 打板工作流七态状态机（pending→…→settled，旁路 filtered）；`trading_workflow.py` 按时段分发 pre/intraday/post。
- S033 接线状态机落库 + 前端呈现；S034 transition 即结算。盘中信号 / 盘后批量结算 / LLM 复盘仍为桩。
- `realtime_workflow.py` 桩：`monitor_stock` return None（TODO: 接入实时行情）。
- `post_market_workflow.py` 桩：`_settle_recommendations` return []、`_generate_llm_review` return "盘后复盘功能待实现"、`_generate_next_day_strategy` return "次日策略待实现"。
- `check_bomb_alerts`（realtime_workflow）有部分实现（封单变化逻辑），但红色预警 TODO 依赖流通市值数据未接。alerts 页是否标灰取决于这部分是否可信——**判定**：`check_bomb_alerts` 需要调用方传入 `seal_amount` / `prev_seal_amount`，但 `run_intraday()` 不调它（只返 `self.intraday.signals` / `self.intraday.alerts`，均为空列表）。因此 alerts 前端拿到的永远是空——标灰。

## 3. 需求清单

### 后端

- [ ] R1 `routers/workflow.py`：`/workflow/realtime`（含 `/intraday` 别名）返回 `{"not_implemented": true, "message": "盘中监控未实现", "spec": "S0xx"}`，不调 `_workflow.run_intraday()`。
- [ ] R2 `/workflow/post-market` 返回 `{"not_implemented": true, "message": "盘后复盘未实现", "spec": "S0xx"}`，不调 `_workflow.run_post_market()`。
- [ ] R3 `/workflow/signals` 返回 `{"not_implemented": true, ...}`，不读 `_workflow.intraday.signals`。
- [ ] R4 `/workflow/alerts` 返回 `{"not_implemented": true, ...}`，不读 `_bomb_alert_system.active_alerts()`。
- [ ] R5 `/workflow/settle`（POST）返回 `{"not_implemented": true, "message": "盘后批量结算未实现，请用状态机流转 settled 触发结算（S034）", ...}`，不调 `_workflow.run_post_market()`。
- [ ] R6 `/workflow/refresh` 保留（不涉及桩，纯返回时间戳）。
- [ ] R7 `realtime_workflow.py` / `post_market_workflow.py` 桩方法保留签名但加 `# stub: 未实现，见 S036` 注释（不改 `raise NotImplementedError`——端点已 early return 不触达桩）。

### 前端

- [ ] R8 `IntradayMonitor.tsx`：不调 `useIntradayData()`；渲染未实现横幅（灰底 badge + 说明文案），signals/alerts 区域显示"此功能未实现"。
- [ ] R9 `PostMarketReview.tsx`：不调 `usePostMarketReview()`；同上未实现态。
- [ ] R10 `BombAlertPanel.tsx`：不调 `useBombAlerts()`；同上未实现态。
- [ ] R11 三页保留路由和导航入口（不删 `router.tsx` / `navigation.ts` 条目），将来补实现时恢复即可。
- [ ] R12 `WorkflowStage` 骨架组件适配：加 `notImplemented` prop，为 true 时渲染未实现横幅替代 children。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/workflow.py` | R1-R6 端点改 early return not_implemented |
| `backend/realtime_workflow.py` | R7 桩方法加注释 |
| `backend/post_market_workflow.py` | R7 桩方法加注释 |
| `frontend/src/pages/workflow/IntradayMonitor.tsx` | R8 不调 hook + 渲染未实现态 |
| `frontend/src/pages/workflow/PostMarketReview.tsx` | R9 同上 |
| `frontend/src/pages/workflow/BombAlertPanel.tsx` | R10 同上 |
| `frontend/src/pages/workflow/components/WorkflowStage.tsx` | R12 加 notImplemented prop |

## 5. 设计方案

### D1 后端 early return（不抛异常）

端点内不跑任何桩逻辑，直接返回 `{"not_implemented": true, "message": "...", "spec": "S0xx"}`。不抛 `NotImplementedError`——抛异常会让其他调用方拿到 500，不如返回结构化状态。端点签名和路由路径不变，API 契约兼容。

### D2 前端不调 hook（不 guard clause）

页面组件直接渲染未实现态，不调 `useIntradayData` / `usePostMarketReview` / `useBombAlerts`。不保留 hook 调用加 guard——零网络请求、零桩逻辑执行。hook 定义保留（`lib/query/limitup.ts`），将来恢复调用时无需重建。

### D3 不删路由和导航

`router.tsx` 的三个路由路径和 `navigation.ts` 的三个 nav item 保留。用户仍可导航到页面，看到的是未实现横幅——这比删入口（用户找不到页面以为系统坏了）更诚实。

### D4 与 S012 原方案的差异

| 维度 | S012 原方案 | S036 修订 |
|---|---|---|
| 桩方法处理 | `raise NotImplementedError` | 端点 early return，桩方法加注释（不触达） |
| 前端 | 标灰徽标 + 禁用操作 | 不调 hook + 未实现横幅 |
| `_build_strategy_match` | 删死代码 | 已不存在，免做 |
| 适配 S033/S034 | 无（spec 写于 S033 前） | 全部适配 |

## 6. 验收标准

- [ ] A1 `GET /api/workflow/realtime` 返回 `{"not_implemented": true, ...}`，不跑 `run_intraday()`
- [ ] A2 `GET /api/workflow/post-market` 同上，不跑 `run_post_market()`
- [ ] A3 `GET /api/workflow/signals` / `GET /api/workflow/alerts` / `POST /api/workflow/settle` 同上
- [ ] A4 `GET /api/workflow/refresh` 正常返回（不受影响）
- [ ] A5 前端三页显示未实现横幅，不发网络请求
- [ ] A6 `npx tsc --noEmit` 通过
- [ ] A7 vitest 新测试通过（三页未实现态渲染 + WorkflowStage notImplemented prop）
- [ ] A8 `pytest -m "not live"` 全过
- [ ] A9 不新增任何功能逻辑（diff 审查无新实现）

## 7. 合规与工程底线自查

- [ ] 桩不输出任何方向性判断或买卖时机
- [ ] 「未实现」横幅客观，不误导
- [ ] 不涉及研究性判断输出（桩无输出）
- [ ] 不涉及用户私有数据
- [ ] 不涉及东财端点

## 8. 测试计划

- 后端：`test_workflow_not_implemented`——五个端点断言返回 `not_implemented: true`，不跑桩逻辑（mock `_workflow` 确认 `run_intraday` / `run_post_market` 零调用）
- 前端 vitest：三页未实现横幅渲染；WorkflowStage `notImplemented=true` 渲染
- 离线全量：`cd backend && .venv/bin/python -m pytest -m "not live"` + `cd frontend && npx tsc --noEmit && npx vitest run`

## 9. 风险与回滚

- 🟡 前端 hook 保留但不调——React Query cache 不再刷新，如果其他页面间接依赖这些 cache 会拿到 stale data。**实际排查**：`useIntradayData` / `usePostMarketReview` / `useBombAlerts` 只在三页调用，无交叉消费——风险消除。
- 🟢 后端端点签名不变，外部脚本调到会拿到 not_implemented 而非崩溃——可接受降级。
- 🟢 回滚：`git revert`（medium 直接 develop 提交）。
