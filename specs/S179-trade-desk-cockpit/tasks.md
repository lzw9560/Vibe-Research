# S179 · Trade Desk Cockpit — 任务清单 (tasks.md)

**关联**：spec S179（spec.md）+ plan S179（plan.md）
**创建**：2026-09-10
**原则**：TDD（先写测试 → 实现 → 绿 → 勾）；每 Phase 结束跑全量 `tsc --noEmit` + `vitest run`；每条带依赖序 + 验收点 + 测试命令。

---

## Phase 0 · 基建（无路由变更，先于页迁移）

### P0.T1 currentStock store（R0.1）
- **依赖**：无
- **验收**：A1.1/A1.2/A1.3
- **步骤**：
  - [ ] T1.1 写 `src/stores/__tests__/currentStock.test.tsx`：setCurrentStock → code 更新；clearCurrentStock → null；pushBrowsed → 去重追加（RED）
  - [ ] T1.2 建 `src/stores/currentStock.tsx`：React Context + useReducer，state `{code, name, source, browsedAt[]}`，expose `useCurrentStock()` hook（GREEN）
  - [ ] T1.3 跑 `npx vitest run src/stores/__tests__/currentStock.test.tsx` 绿
- **测试命令**：`npx vitest run src/stores/__tests__/currentStock.test.tsx`
- **grill#**：#1,#9,#13

### P0.T2 命令面板（R0.2）
- **依赖**：T1（路由索引引用现有 17 tab 名）
- **验收**：A2.1-A2.4
- **步骤**：
  - [ ] T2.1 写 `src/components/command-palette/__tests__/CommandPalette.test.tsx`：Cmd+K toggle、Esc 关闭、↑↓ 导航、Enter 跳转、模糊匹配路由名"选股"→/screener（RED）
  - [ ] T2.2 建 `searchIndex.ts`：路由名+path 索引（从 navigation.ts 读）+ 股票代码索引（数据源待定 open_question，先 mock 10 支）+ 预设信号索引
  - [ ] T2.3 建 `useCommandPalette.ts`：Cmd+K 监听 + open/close state
  - [ ] T2.4 建 `CommandPalette.tsx`：浮层 + 输入框 + 列表 + 键盘导航（GREEN）
  - [ ] T2.5 跑测试绿 + `grep -E "cmdk|kbar" package.json` 零命中
- **测试命令**：`npx vitest run src/components/command-palette/`
- **grill#**：#9

### P0.T3 SplitLayout（R0.3）
- **依赖**：无
- **验收**：A3.1-A3.3
- **步骤**：
  - [ ] T3.1 写 `src/components/layout/__tests__/SplitLayout.test.tsx`：左右渲染、拖拽改 CSS 变量、localStorage 持久化（RED）
  - [ ] T3.2 建 `SplitLayout.tsx`：CSS Grid `grid-template-columns: var(--split-left, 340px) 1fr` + 拖拽条 + localStorage（GREEN）
  - [ ] T3.3 建 `CockpitLayout.tsx`（SplitLayout 包裹 Outlet）+ `StandardLayout.tsx`（单 Outlet max-w-6xl）
  - [ ] T3.4 跑测试绿 + 13 寸视口无横滚（Playwright `npx playwright test` 视口 1280×800）
- **测试命令**：`npx vitest run src/components/layout/__tests__/SplitLayout.test.tsx`
- **grill#**：#8,#9

### P0.T4 送入菜单 + schema 契约（R0.4）
- **依赖**：T1（currentStock 提供 code/name）
- **验收**：A4.1-A4.3
- **步骤**：
  - [ ] T4.1 写 `src/components/layout/__tests__/SendToMenu.test.tsx`：4 向菜单、schema 校验 `{code,name,source_page,timestamp,target}`、POST mock（RED）
  - [ ] T4.2 建 `SendToMenu.tsx`：4 向（watchlist/portfolio/journal/research）+ schema 类型定义（GREEN）
  - [ ] T4.3 跑测试绿
- **测试命令**：`npx vitest run src/components/layout/__tests__/SendToMenu.test.tsx`
- **grill#**：#14

### P0.T5 NAV_GROUPS 重组 7 组（R0.5）
- **依赖**：无（纯导航重组，无路由删）
- **验收**：A5.1/A5.2
- **步骤**：
  - [ ] T5.1 读 `src/components/layout/navigation.ts:29-64` 现有 NAV_GROUPS（~4 组）
  - [ ] T5.2 重组为 7 组手风琴：交易台（/intraday /workflow）/ 选股（/screener /limitup）/ 个股（/stock /stock-data）/ 投资管理（/portfolio /advisory /journal /watchlist）/ 研究中心（/market /strategy /backtest /review /my-reports）/ 系统（/settings /metrics /health /scheduled-tasks）+ 1
  - [ ] T5.3 expandedGroup 单组展开 + collapsed 保留
  - [ ] T5.4 跑 `npx vitest run` 全量绿（旧路由仍可达无 404）
- **测试命令**：`npx vitest run`
- **grill#**：#8

### P0.T6 verdict per-type 渲染（R0.6）
- **依赖**：无
- **验收**：VerdictRenderer 分发 3 type
- **步骤**：
  - [ ] T6.1 写 `src/components/verdict/__tests__/VerdictRenderer.test.tsx`：selection verdict → SelectionVerdictCard；event → EventVerdictCard；long_value → LongValueVerdictCard（RED）
  - [ ] T6.2 建 `VerdictRenderer.tsx` + 3 子组件（schema 各异：S168 lift/n_picks/days_robust、S169 t_stat/p_value/window、S171 pe_ratio/margin_of_safety）（GREEN）
  - [ ] T6.3 跑测试绿
- **测试命令**：`npx vitest run src/components/verdict/`
- **grill#**：#15

### P0.T7 Phase 0 全量回归
- [ ] T7.1 `npx tsc --noEmit` 零 error
- [ ] T7.2 `npx vitest run` 全量绿（含现有 188+ tests）
- [ ] T7.3 `npx madge --circular src/` 无新循环依赖

---

## Phase 1 · 高价值新页（不碰旧路由，灰度验证）

### P1.T1 /screener 选股器（R1.1）
- **依赖**：P0.T1（currentStock）+ P0.T4（送入菜单）
- **验收**：A7.1-A7.3
- **步骤**：
  - [ ] T1.1 写 `src/pages/screener/__tests__/ScreenerPage.test.tsx` + `FilterPanel.test.tsx`：filter 抽象层条件组、preset 切换、送入菜单联动（RED）
  - [ ] T1.2 建 `FilterPanel.tsx`：条件组（行业/市值/PE/PB/涨跌幅/成交量）+ preset 框架（grill #5：非 6 页 trench coat，统一 filter 抽象）
  - [ ] T1.3 建 `presets/` 目录：breakout / gene / auction / seats / premarket 5 preset（保留特色交互，统一 filter 接口）
  - [ ] T1.4 建 `ScreenerPage.tsx`：FilterPanel + 结果表 + 顶部搜索框 + 送入菜单 + currentStock 联动（GREEN）
  - [ ] T1.5 router.tsx 加 `/screener` 路由（不动旧 limitup 路由）
  - [ ] T1.6 跑测试绿
- **测试命令**：`npx vitest run src/pages/screener/`
- **grill#**：#5,#12

### P1.T2 /stock/:code cockpit（R1.2）
- **依赖**：P0.T1（currentStock）+ P0.T3（SplitLayout）
- **验收**：A8.1-A8.3
- **步骤**：
  - [ ] T2.1 写 `src/pages/stock/__tests__/StockCockpit.test.tsx`：图表中心渲染、8 面板 toggle、currentStock 联动、无 code 时 EmptyState（RED）
  - [ ] T2.2 建 `StockCockpit.tsx`：图表中心（K线）+ 右侧 8 面板竖排图标栏（自选/资讯/财务/资金/信号/笔记/龙虎榜/AI）+ currentStock.browsed fallback（GREEN）
  - [ ] T2.3 router.tsx 加 `/stock/:code/cockpit` 新路由（不动旧 `/stock/:code` → StockDeep，Phase 3 redirect）
  - [ ] T2.4 跑测试绿
- **测试命令**：`npx vitest run src/pages/stock/`
- **grill#**：#13

### P1.T3 /market 首屏 cockpit（R1.3）
- **依赖**：P0.T3（CockpitLayout）+ ECharts（已装）
- **验收**：A6.1-A6.4
- **步骤**：
  - [ ] T3.1 写 `src/pages/market/__tests__/MarketPage.test.tsx`：treemap 渲染 30 板块、click 板块 navigate、click 个股 setCurrentStock（RED）
  - [ ] T3.2 建 `MarketPage.tsx`：指数卡片 + ECharts treemap（large 模式聚合申万 30 板块，grill #11 不裸渲染 5000）+ 涨停/炸板/连板摘要 + 情绪天气 + 全球情报折叠 + 涨跌预测（GREEN）
  - [ ] T3.3 router.tsx 加 `/market` 路由（不动 root redirect，Phase 3 改）
  - [ ] T3.4 跑测试绿 + 13 寸 treemap 渲染 < 500ms（Playwright performance）
- **测试命令**：`npx vitest run src/pages/market/ && npx playwright test market-perf`
- **grill#**：#11

### P1.T4 Phase 1 全量回归
- [ ] T4.1 `npx tsc --noEmit` 零 error
- [ ] T4.2 `npx vitest run` 全量绿
- [ ] T4.3 旧路由仍可达（/daily-review /limitup/* /workflow 全无 404）

---

## Phase 2 · 盘中 + 研究（加维度）

### P2.T1 /intraday 盘中 cockpit（R2.1）
- **依赖**：P0.T1 + P0.T3 + S176（OFI snapshots）
- **验收**：A9.1-A9.3
- **步骤**：
  - [ ] T1.1 写 `src/pages/intraday/__tests__/IntradayCockpit.test.tsx`：SplitLayout 候选列表+个股预览、OFI 数据渲染、无数据 HonestEmptyState（RED）
  - [ ] T1.2 建 `IntradayCockpit.tsx`：SplitLayout + OFI 接 S176 ofi_snapshots + 告警流 + 教练 + HonestEmptyState（grill #6 不假装有数据）（GREEN）
  - [ ] T1.3 router.tsx 加 `/intraday` 新路由（不动旧 /workflow/intraday，Phase 3 redirect）
  - [ ] T1.4 跑测试绿
- **测试命令**：`npx vitest run src/pages/intraday/`
- **grill#**：#6

### P2.T2 /multiline 三列战略（R2.2）
- **依赖**：P0.T6（VerdictRenderer）
- **验收**：A10.1-A10.3
- **步骤**：
  - [ ] T2.1 写 `src/pages/multiline/__tests__/MultilinePage.test.tsx`：三列渲染、verdict 窗口口径标签、长线列 honest placeholder（RED）
  - [ ] T2.2 建 `MultilinePage.tsx`：三列（短线打板 S168 selection / 中线 event S169 / 长线价值 S171）+ VerdictRenderer per-type + 窗口口径标签（grill #7 §44v1 教训）（GREEN）
  - [ ] T2.3 router.tsx 加 `/multiline` 路由
  - [ ] T2.4 跑测试绿
- **测试命令**：`npx vitest run src/pages/multiline/`
- **grill#**：#7

### P2.T3 /strategy 加维度（R2.3）
- **依赖**：无（改现有 StrategyPage.tsx 295 行）
- **验收**：回测+前向+信号+风险指标 4 区渲染
- **步骤**：
  - [ ] T3.1 读 `src/pages/strategy/StrategyPage.tsx` 现有结构
  - [ ] T3.2 加维度：回测（接 Backtest.tsx）/ 前向测试（接 ForwardTestPage.tsx）/ 信号 / 风险指标集
  - [ ] T3.3 跑测试绿
- **测试命令**：`npx vitest run src/pages/strategy/`

### P2.T4 /portfolio 加维度（R2.4）
- **依赖**：无（改现有 Portfolio.tsx 295 行）
- **验收**：风险仪表盘+健康分+PB-ROE 散点
- **步骤**：
  - [ ] T4.1 读 `src/pages/Portfolio.tsx` 现有结构
  - [ ] T4.2 加维度：风险仪表盘 + 健康分 + PB-ROE 散点图（ECharts scatter）
  - [ ] T4.3 跑测试绿
- **测试命令**：`npx vitest run src/pages/Portfolio.test.tsx`

### P2.T5 /advisory 重构（R2.5）
- **依赖**：无（改现有 Advisory.tsx 195 行）
- **验收**：今日推荐+顾问团+大辩论三区
- **步骤**：
  - [ ] T5.1 读 `src/pages/Advisory.tsx` 现有 S042 结构（195 行，三场景建议）
  - [ ] T5.2 重构为 cockpit：今日推荐（接 S175 follow-order）+ 顾问团（grill-me 6-lens 结构展示）+ 大辩论（接 /debate）
  - [ ] T5.3 跑测试绿
- **测试命令**：`npx vitest run src/pages/Advisory.test.tsx`

### P2.T6 /review 复盘中心（R2.6）
- **依赖**：无
- **验收**：行为模式+研报管理
- **步骤**：
  - [ ] T6.1 写 `src/pages/review/__tests__/ReviewPage.test.tsx`：行为模式区+研报管理区（RED）
  - [ ] T6.2 建 `ReviewPage.tsx`：接 BehaviorLoop.tsx + MyReports.tsx，胜率反馈闭环（GREEN）
  - [ ] T6.3 router.tsx 加 `/review` 路由
  - [ ] T6.4 跑测试绿
- **测试命令**：`npx vitest run src/pages/review/`

### P2.T7 Phase 2 全量回归
- [ ] T7.1 `npx tsc --noEmit` 零 error
- [ ] T7.2 `npx vitest run` 全量绿
- [ ] T7.3 旧路由仍可达

---

## Phase 3 · 清理（旧路由 redirect，保兼容）

### P3.T1 root redirect + redirect 表（R3.1/R3.6）
- **依赖**：Phase 1+2 新页全建好
- **验收**：A11.1/A11.6
- **步骤**：
  - [ ] T1.1 router.tsx:33 root `"/"` → Navigate `to="/market"`
  - [ ] T1.2 建 redirect 映射表（旧 31 → 新 17）：/daily-review→/market /intel→/market /sectors→/market /sector-divergence→/market /prediction→/market /limitup→/screener /limitup/gene→/screener?preset=gene /workflow/intraday→/intraday /behavior-loop→/review /my-reports→/review /debate→/advisory 等
  - [ ] T1.3 跑 `npx vitest run` + Playwright 旧路由 redirect 不 404
- **测试命令**：`npx vitest run && npx playwright test redirect`
- **grill#**：—

### P3.T2 Workflow.tsx 解散（R3.2）
- **依赖**：T1（redirect 表）
- **验收**：A11.2
- **步骤**：
  - [ ] T2.1 读 `src/pages/Workflow.tsx`（325 行）：stageToDefaultTab(:37) + useMarketClock(:156) + useDateTriplet(:16)
  - [ ] T2.2 迁 stageToDefaultTab 到 `src/lib/dayPhase.ts` 或 day-phase-rail 组件
  - [ ] T2.3 确认 useMarketClock 已在 `src/lib/useMarketClock.ts`（独立模块），Workflow.tsx 只是调用方
  - [ ] T2.4 写 `src/lib/__tests__/dayPhase.test.tsx`：stageToDefaultTab 单测绿
  - [ ] T2.5 解散 Workflow.tsx：7 态逻辑迁入 /screener（pre-market）+ /intraday（intraday）+ /review（post-market）
  - [ ] T2.6 跑测试绿
- **测试命令**：`npx vitest run src/lib/__tests__/dayPhase.test.tsx`
- **grill#**：#4

### P3.T3 DailyReview 双结构清理（R3.3）
- **依赖**：T1（/market 已覆盖功能）
- **验收**：A11.3
- **步骤**：
  - [ ] T3.1 验收 /market 覆盖 DailyReview.tsx 全部功能（指数卡片/板块/情绪/全球情报/涨跌预测）
  - [ ] T3.2 删 `src/pages/DailyReview.tsx`（762 行）
  - [ ] T3.3 删 `src/pages/DailyReview/` folder（index.tsx + components/7 + pages/3 死代码）
  - [ ] T3.4 router.tsx:34-37 四路由 redirect → /market 子区
  - [ ] T3.5 跑 `npx vitest run` + `grep -r "DailyReview" src/` 零命中（除 redirect 注释）
- **测试命令**：`npx vitest run && grep -r "DailyReview" src/`
- **grill#**：#2

### P3.T4 FirstBoardPipeline 拆分（R3.4）
- **依赖**：T2（Workflow 解散后依赖清晰）
- **验收**：A11.4
- **步骤**：
  - [ ] T4.1 `npx codegraph explore "FirstBoardPipeline"` 摸依赖树（grill #10）
  - [ ] T4.2 读 `src/pages/workflow/components/FirstBoardPipeline.tsx`（1126 行）按职责分区
  - [ ] T4.3 TDD 拆：先写测试锁定现有行为 → 拆为 pipeline-steps / data-transform / render 分离 → 测试仍绿
  - [ ] T4.4 各拆出模块 < 300 行
  - [ ] T4.5 跑 `npx vitest run src/pages/workflow/` 绿
- **测试命令**：`npx codegraph explore "FirstBoardPipeline" && npx vitest run src/pages/workflow/`
- **grill#**：#10

### P3.T5 SUB_TABS 消除（R3.5）
- **依赖**：T2（Workflow 解散）+ T3（DailyReview 删）+ T4（FirstBoardPipeline 拆，因 workflow sub tab 自管）
- **验收**：A11.5
- **步骤**：
  - [ ] T5.1 各页建页内 TabBar 组件（useState 管 active tab，`?tab=xxx` query param 可分享但不依赖 pathname）
  - [ ] T5.2 删 `navigation.ts:98-155` SUB_TABS 定义（14 键）
  - [ ] T5.3 删 `Layout.tsx` 6 处 prefix-match（:31/:46/:78/:109/:220/:250）
  - [ ] T5.4 跑 `npx vitest run` 绿 + `grep -r "SUB_TABS\|startsWith" src/components/layout/` 零命中
  - [ ] T5.5 Playwright 全 tab 可达无 404
- **测试命令**：`npx vitest run && npx playwright test all-tabs && grep -r "SUB_TABS" src/components/layout/`
- **grill#**：#3

### P3.T6 Phase 3 全量回归
- [ ] T6.1 `npx tsc --noEmit` 零 error
- [ ] T6.2 `npx vitest run` 全量绿（含现有 188+ + 新增 tests）
- [ ] T6.3 `npm run build` 成功
- [ ] T6.4 `npx madge --circular src/` 无循环依赖
- [ ] T6.5 Playwright 全量 E2E：旧路由 redirect 不 404 + 新页全可达 + 13 寸无横滚
- [ ] T6.6 `grep -r "DailyReview\|SUB_TABS" src/` 零命中（除 redirect 注释 + 历史 git）
