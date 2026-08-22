# Spec: S014 — 前端 UI 重设计（信息架构 + 交互统一 + 视觉系统 + AI 对话）

> 状态：已实现 2026-08-02
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 8 步）、`../S013`（hooks/client 前置）、`../S016`（测试网）、`../../docs/sentiment-weather-station-ui-design.md`（设计文档补落地）

---

## 1. 问题 / 目标

22 项扁平一级导航无分组；`DailyReview.tsx`(733) 单页 28 state/10 区块信息过载；11 个巨型 page >400 行（LimitUpStrategy 836、GeneScreener 608、StockDeep 587）；workflow 三页（Pre/Intraday/Post）1651 行雷同；三态 4 套分裂（Skeleton/Loader2/pending/EmptyState）；表格交互不一（PreMarket 可排序、DailyReview/StockDeep 不可）；移动端 22 项横滚 Tab + 侧栏不隐藏不可用；echarts 硬编码暗色不跟主题；暖橙主题配置无入口；`AskAiButton` 流式每 delta 全量 ReactMarkdown re-parse + 无历史持久化 + 只 9 页入口；设计文档落地率 ~30%。

**目标**：自顶向下 5 组信息架构；首页拆分下沉；巨型 page 拆分 <400 行；workflow 抽公共骨架；三态/表格/筛选统一契约；移动端重做；视觉系统补令牌 + echarts 跟主题；暖橙保留加入口；AI 对话重做。三个决策已定：首页拆分下沉、暖橙保留+加入口、工作流桩标灰不补。

## 2. 背景

- 调研事实见 UI agent 报告（22 项扁平 NAV `Layout.tsx:17-41`；DailyReview 28 state `:25-55`；三态分裂；移动端 `Layout.tsx:221-277` 22 项横滚；echarts `STITimelineChart.tsx:78-168` 硬编码 rgba；暖橙 `useDarkMode.ts:27-35` 无入口；AskAiButton `:108-214`）。
- 设计文档 `docs/sentiment-weather-station-ui-design.md` V2.0.3 的 P0 项 0 落地。
- 新合规边界（CLAUDE.md §1.1，2026-07-30）：UI 可呈现"研究参考性判断"卡片，挂轻量风险提醒（非强制免责墙）。

## 3. 需求清单

- [ ] R1 导航：22 项扁平 → 5 组（市场总览/个股研究/交易工作台/投资管理/系统），侧栏组可折叠、默认当前组展开；消费 `navigation.ts` 的 SUB_TABS（删死代码或落地）
- [ ] R2 首页拆分下沉：DailyReview 28 state → ~8 state，只留指数+STI+自选速览+AI 复盘入口；情绪/板块资金/复盘报告下沉子页或 Tab
- [ ] R3 巨型 page 拆分：11 个 >400 行 → <400 行（LimitUpStrategy/DailyReview/GeneScreener/StockDeep/SectorDivergence/Settings 等）
- [ ] R4 workflow 三页抽 `<WorkflowStage stage=...>` 公共骨架（1651 → 骨架 ~300 + 配置）
- [ ] R5 三态统一：`<PageSkeleton>`/`<EmptyState>`/`<ErrorRetry>`；废弃 Loader2/pending 文字；全用 `<DataTable>`（三态+排序+onRowClick）；`<FilterBar>` 统一筛选
- [ ] R6 统一 `pctColor()` 涨跌色（`lib/utils`，替各页自定义）；hover 统一 `muted/30`
- [ ] R7 移动端：侧栏 `hidden` md 以下 + 汉堡→全屏抽屉分组折叠；底部 Tab Bar 5 项常驻（首页/自选/工作台/持仓/更多）；修 `mobileMenuOpen` 只锁滚动不展开的错位
- [ ] R8 视觉系统：补间距/字号令牌；echarts 消费 `--chart-*` token + `useTheme` 监听切换；Badge warning 用 `--warning`；Button 加实心 `primary-solid` 变体
- [ ] R9 暖橙主题保留 + 加设置页切换入口（不删）
- [ ] R10 情绪气象站补设计文档 P0：WeatherHero 的 dataFreshness/STI gauge（非 CSS div）/Layout 级二级 Tab/aria 属性；实现或删占位 Tab
- [ ] R11 AI 对话重做：抽 `useChatStream` hook（AskAi/DailyReview 复盘/Intel 要点三处共用）；增量渲染（不全量 ReactMarkdown re-parse）+ 打字机光标；历史 localStorage 持久化；AskAi 升全局入口（顶栏常驻）；抽屉遮罩统一 backdrop-blur + 响应式窄屏全屏
- [ ] R12 全局面包屑 `<Breadcrumbs>`（不只 StockDeep）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/components/layout/Layout.tsx`(285) | 🔥拆侧栏/移动端 Header/TabBar/Backdrop；NAV 分组外移 |
| `frontend/src/components/layout/navigation.ts` | ✏️22 项→5 组；落地 SUB_TABS |
| `frontend/src/router.tsx` | ✏️二级 Tab（Layout 级） |
| `frontend/src/pages/DailyReview.tsx`(733) | 🔥首页骨架+下沉子页 |
| 11 巨型 page | 🔥拆子组件 |
| `frontend/src/pages/workflow/{Pre,Intraday,Post}*.tsx` | 🔥抽 `<WorkflowStage>` |
| ➕`components/ui/{PageSkeleton,ErrorRetry,FilterBar}.tsx` | ➕新增 |
| `components/ui/{Badge,Button}.tsx`、`index.css` | ✏️令牌化 |
| `components/sti/STITimelineChart.tsx` | ✏️echarts 消费 token+跟主题 |
| `components/ui/AskAiButton.tsx`(217) | 🔥重做 |
| ➕`lib/useChatStream.ts` | ➕新增 |
| `frontend/src/index.css` | ✏️补间距/字号令牌 |

## 5. 设计方案

- **信息架构**：5 组对齐用户心智模型（市场总览/个股研究/交易工作台/投资管理/系统），非数据来源。侧栏默认只露组标题 + 当前组展开。
- **首页**：概览层（指数+STI+自选速览+AI 复盘入口）一屏可读；下沉链接到情绪/板块资金/复盘报告子页。28→~8 state。
- **WorkflowStage**：`<WorkflowStage stage header filters table aiPanel />`，三页只填数据契约。
- **交互契约**：统一三态 + DataTable + FilterBar + pctColor；废弃各页手写。
- **AI 对话**：useChatStream 抽象 + 增量渲染（按段 patch）+ 全局入口。
- **合规（弱合规，私人助理定位 2026-07-30）**：判断卡片挂轻量风险提醒「历史统计特征，市场有风险」，不强制免责墙；可给方向性研判/买卖时机，不承诺确定性收益。设计文档原"建议空仓/买入价"可如实呈现（用户即决策者），挂轻量提醒即可。涨停四池/连板股榜可呈现个股 code/name（公开榜单）。工程底线保留：判断可复现/不臆造、私有数据隔离（VR_DATA_DIR）、东财走 em_get（本 spec 为前端 UI，后端端点不在此改）。

## 6. 验收标准

- [ ] A1 导航 5 组可折叠；`navigation.ts` SUB_TABS 落地非死代码
- [ ] A2 首页 ≤8 state；情绪/板块资金/复盘报告下沉
- [ ] A3 11 巨型 page 均 <400 行
- [ ] A4 workflow 三页共享 `<WorkflowStage>`，无重复骨架
- [ ] A5 三态统一（PageSkeleton/EmptyState/ErrorRetry）；无散落 Loader2/pending；State.tsx 封装的内联 spinner 不计
- [ ] A6 表格全用 DataTable（可排序）；hover 色统一
- [ ] A7 移动端：侧栏 md 以下隐藏 + 全屏抽屉 + 5 项 Tab
- [ ] A8 echarts 跟主题切换；无硬编码 rgba
- [ ] A9 暖橙主题有切换入口；切主题图表/Toast 跟随
- [ ] A10 情绪气象站 P0 补全（gauge/二级Tab/aria/dataFreshness）
- [ ] A11 AskAi 全局入口；useChatStream 三处共用；流式无全量 re-parse；历史持久化
- [ ] A12 `npm run build` + `npx vitest run` 通过
- [ ] A13 判断卡片挂轻量风险提醒「历史统计特征，市场有风险」（弱合规，非强制免责墙）

## 7. 合规自查（按 CLAUDE.md §1 弱合规 2026-07-30；私人助理定位）

**仪式类（已降为风险提醒，非硬门槛）**：
- [ ] 研判输出挂轻量风险提醒「历史统计特征，市场有风险」，不强制「不构成投资建议」墙
- [ ] 可给方向性研判/买卖时机/操作建议，不承诺确定性收益（用户即决策者，半自动化）
- [ ] 涨停四池/连板股榜可如实呈现个股 code/name（公开榜单，用户自己的工具）
- [ ] 暖橙主题/UI 改动不涉及合规门槛

**工程底线（保留，保护用户自身的钱与数据）**：
- [ ] 判断可复现/不臆造/不心算（涉及财务数据跑 `financial_rigor.py`/`report_audit.py`）
- [ ] 无私有数据（持仓/研报/key）进 UI 或 git；VR_DATA_DIR 隔离
- [ ] 东财端点走 em_get（本 spec 为前端 UI，后端端点不在此改）

## 8. 测试计划

- vitest：WorkflowStage 渲染、useChatStream 流式、pctColor、三态组件
- `npm run build` 通过
- live：逐页点击、移动端、主题切换、AI 对话流式、情绪气象站各 Tab
- 合规：判断卡片免责声明人工审查

## 9. 风险与回滚

- 🟡 11 巨型 page 拆分工作量大：分批拆，每批 vitest 快照锁行为
- 🟡 echarts 跟主题需重写图表配置：保留暗色基线快照比对
- 🟡 首页下沉改变用户习惯：保留下沉链接可达
- 🟢 回滚：git revert（UI 改动隔离在 S014）
