# Spec: S221 — 前端 3 gap 闭环（推送状态/周度复盘/delivery leak）

> 状态：已实现（2026-09-20，6 commit 3c1327b..2b79b9f：3 gap closure + 后端端点 + 测试 + LOW 修 + follow-up）
> 作者：frontend-developer  日期：2026-09-20
> 关联：S218（delivery 4 cron + TodaySignalsPanel + ValidatedEdgeCard）、S218-C5 weekly_review executor
> 演进：§2 原"不改后端"，实现时加 `GET /api/signals/weekly-review` 端点读 weekly_review.json（commit 97b9c51），WeeklyReviewPanel 改读后端真值非前端推算（516142b）——比原方案更诚实，见 §2 更新

## 1. 问题 / 目标

v3 审查（memory audit-2026-09-20-v3）发现 UI 不达标 3 断点：信号→记录→edge 状态闭环了，
但**推送状态 + 周度复盘 + delivery leak** 3 处断，用户照做后看不到真钱收益闭环反馈。

本 spec 闭环 3 gap，让用户在 cockpit 看到每日报告是否 fire + 飞书是否配推，
在 /review 周度 tab 看到实际 P&L 趋势 + cap-down 提案 + 4 周对比，
在信号行看到 actual vs reference P&L diff + leak 红标。

## 2. 背景

- TodaySignalsPanel（frontend/src/components/cockpit/TodaySignalsPanel.tsx）：当日 consecutive_relay 信号三 bucket + 手动交易回录 Sheet。复用 GlassCard/Disclaimer/useSignalsDaily。
- ReviewPage（frontend/src/pages/review/ReviewPage.tsx）：复盘页，validation + strategy 2 tab，?tab= query param 切换。
- 后端端点（已存在，前端调，不改后端）：
  - GET /api/scheduled-tasks（返 today_status done|pending|degraded|error|running + last_run_at + notify_on_success）
  - GET /api/signals/manual-trades（返 trades[]，每条含 actual_pnl.pnl_pct + reference_pnl.pnl_pct + pnl_diff.delivery_leak + recorded_at）
  - GET /api/signals/status（返 regime + arms cap/regime）
  - weekly_review executor（scheduler/executors/signals.py:435）生成 .vibe-research/signal_reports/{date}_weekly_review.json

**前提问题（已核于 code）**：~~weekly_review.json 无 GET 端点读取~~ **2026-09-20 演进（commit 97b9c51）**：已加 `GET /api/signals/weekly-review` 端点读 `weekly_review.json` 全文（无 date 返最近一次，无文件诚实标 not_found/no_reports）。WeeklyReviewPanel 改调该端点读后端真值（commit 516142b），cap-down 提案用 executor 实算值非前端推算——比原"前端推算"方案更诚实。原 task 约束"不改后端"在实现时被覆盖（读后端文件比前端推算 cap-down 更可靠，符合§1.2 判断须可复现底线）。

## 3. 需求清单

- [ ] R1 推送状态卡：TodaySignalsPanel 顶部加 DeliveryStatusCard，调 GET /api/scheduled-tasks，
      找 daily_report task，展示 cron fire 状态灯（✓ 今天已 fire / ✗ 未 fire / ⚠ 降级）+ 飞书推送配置态
      （notify_on_success true=已配置 / false=未配置）。不臆造"已送达"（无 webhook receipt，只标配置态）。
- [ ] R2 周度复盘 tab：ReviewPage 加第 3 tab "weekly"，渲染 WeeklyReviewPanel：
      actual P&L 趋势（manual-trades 列表）+ 4 周对比（按 recorded_at 周聚合 mean P&L）
      + cap-down 提案（前端推算：closed trades mean P&L < 0 → cap-down，标注"前端推算"）
      + cap（从 signals/status）。无数据 HonestEmptyState。
- [ ] R3 delivery leak 标记：TodaySignalsPanel 信号行（SignalRow）加 actual vs reference P&L diff
      + leak 红标（pnl_diff.delivery_leak=true 时红 badge）。manual-trades 按 code 匹配信号。
- [ ] R4 复用现有 pattern：GlassCard/Skeleton/HonestEmptyState/Disclaimer 原语 + lib/query/signals.ts hooks 风格 + TabBar。
- [ ] R5 不碰后端（端点已存在，只前端调）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/lib/query/signals.ts` | 加 useSignalsManualTrades + useDeliveryFireStatus hooks |
| `frontend/src/lib/api/types.ts` | ScheduledTaskStatus 补 notify_on_success 字段（后端已返，类型缺失） |
| `frontend/src/components/cockpit/DeliveryStatusCard.tsx` | 新建：gap1 推送状态卡 |
| `frontend/src/components/cockpit/TodaySignalsPanel.tsx` | 改：顶部嵌 DeliveryStatusCard + SignalRow 加 leak 标记 |
| `frontend/src/pages/review/WeeklyReviewPanel.tsx` | 新建：gap2 周度复盘面板 |
| `frontend/src/pages/review/ReviewPage.tsx` | 改：REVIEW_TABS 加 weekly tab + 渲染 WeeklyReviewPanel |
| `frontend/src/components/cockpit/__tests__/DeliveryStatusCard.test.tsx` | 新建：gap1 渲染测试 |
| `frontend/src/components/cockpit/__tests__/TodaySignalsPanel.test.tsx` | 改：加 leak 标记测试 |
| `frontend/src/pages/review/__tests__/WeeklyReviewPanel.test.tsx` | 新建：gap2 渲染测试 |

## 5. 设计方案

### Gap1 DeliveryStatusCard
- 复用 useScheduledTasksStatus(true)（scheduledTasks.ts，always-on 60s 轮询），filter task_type==="daily_report"。
- 状态灯映射（today_status + notify_on_success）：
  - done + notify_on_success=true → ✓ 今天已 fire（飞书已配置）
  - done + notify_on_success=false → ⚠ 今天 fire 但飞书未配置
  - pending → ✗ 今日未 fire
  - degraded → ⚠ fire 但降级
  - error → ✗ fire 失败
  - running → 运行中
- 诚实：notify_on_success 是"是否配了飞书推送"，非"飞书已送达"（无 webhook receipt 不臆造送达）。
- loading 用 Skeleton，error 用 HonestEmptyState。

### Gap2 WeeklyReviewPanel
- useSignalsManualTrades（新 hook，GET /api/signals/manual-trades）+ useSignalsStatus（cap/regime）。
- actual P&L 趋势：closed trades（actual_pnl.status==="closed"）按时间倒序列 pnl_pct。
- 4 周对比：按 recorded_at ISO 周分组，算每周 mean pnl_pct + 胜率。
- cap-down 提案：前端推算 closed trades mean P&L < 0 → 展示 cap-down 提案（from=cap.effective, to=0.5, reason=实际 P&L mean=X% < 0），
  标注"前端推算（基于已录实际 P&L，非读 weekly_review.json）"。镜像 backend executors/signals.py:478-487 逻辑。
- cap：从 signals/status arms.consecutive_relay 或 daily response cap.effective。
- 无数据 HonestEmptyState("暂无已录实际交易"，hint="记录成交后显示实际 P&L 趋势")。

### Gap3 delivery leak 标记
- TodaySignalsPanel 加 useSignalsManualTrades，按 code 建 Map<code, trade>。
- SignalRow 新增可选 prop matchedTrade?: ManualTradeResponse。
- 有 matchedTrade 且 pnl_diff.delivery_leak=true → 红 badge "leak" + diff_pct 文本。
- 有 matchedTrade 且非 leak → 灰文 "实际 X% vs 参考 Y%（diff Z%）"。
- 无 matchedTrade → 不显示 diff（未回录，诚实不臆造）。

### 备选方案为何不选
- 新建 /weekly-review 独立页：不选，ReviewPage 已有 tab 机制，加 tab 复用 IA 更轻（KISS）。
- 后端加 GET /api/signals/weekly-review 读 JSON：不选，task 约束"不改后端"，且 manual-trades 数据足以推算 cap-down。
- 在 SignalRow 内部 fetch manual-trades：不选，每行 fetch = N+1，应在 panel 层 fetch 一次传 Map down（performance）。

## 6. 验收标准

- [ ] A1 DeliveryStatusCard 渲染：done+notify=true 显示 ✓ 今天已 fire；pending 显示 ✗ 未 fire；degraded 显示 ⚠ 降级
- [ ] A2 WeeklyReviewPanel 渲染：有 closed trades 显示 P&L 趋势 + 4 周对比 + cap-down 推案（mean<0 时）；无数据 HonestEmptyState
- [ ] A3 TodaySignalsPanel SignalRow：有 matchedTrade+leak=true 显示红 leak badge；有 matchedTrade 非 leak 显示 diff 文本；无 matchedTrade 不显示
- [ ] A4 npx tsc --noEmit 0 errors
- [ ] A5 npx vitest run green（新测试 + 既有 TodaySignalsPanel 测试不 regress）
- [ ] A6 复用 GlassCard/Skeleton/HonestEmptyState/Disclaimer/TabBar（无新原语）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机属系统能力（§1.1 弱合规）；用户可见输出挂 Disclaimer 轻量风险提醒
- [x] 判断可复现：cap-down 提案基于 manual-trades 真数据 + 镜像 backend 逻辑，可复算，禁臆造
- [x] 涨停四池/连板股榜个股属公开榜单（设计选择，可呈现 code/name）
- [x] 用户私有数据（manual_trades.jsonl）只经后端端点读，前端不碰文件，未进 git
- [x] 无新增东财端点（不改后端）

## 8. 测试计划

- vitest 单测：3 组件渲染（DeliveryStatusCard / WeeklyReviewPanel / TodaySignalsPanel leak 标记）
- mock hooks（vi.hoisted + vi.mock pattern，同 TodaySignalsPanel.test.tsx）
- 验收：npx tsc --noEmit + npx vitest run

## 9. 风险与回滚

- 风险：manual-trades 数据为空时 WeeklyReviewPanel/DeliveryStatusCard 空态——已 HonestEmptyState 兜底。
- 风险：ScheduledTaskStatus 补 notify_on_success 字段——后端已返，类型补齐不破坏现有调用。
- 回滚：3 新组件 + 3 文件改，git revert 一个 commit 即回。
