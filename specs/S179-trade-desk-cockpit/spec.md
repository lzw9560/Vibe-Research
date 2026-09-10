# S179 · Trade Desk Cockpit（页面架构重设计）

**状态**：草案（spec 定稿，待 plan → tasks → 实现）
**分级**：large（feature 分支 + grill + 分期迁移）
**创建**：2026-09-10
**关联**：[[page-architecture-redesign-2026-09-09]]（w3uzkmy39 verdict，12 agent 调研+专家+synthesis）· [[buy-what-when-buy-when-sell-three-questions]]（新页服务三问）· [[selection-candidate-pool-intraday-paradigm]]（选股=候选池+盘中=信号）· [[multi-strategy-toolbox-evolution]]（多策略对接）· [[ui-first-implementation-order]]（UI 先行）· S172（ETF floor）· S173（Trade Journal）· S175（Paper Trading）· S176（OFI collector）

---

## 1. 问题 / 目标

### 1.1 问题

当前前端 31 个 top-level 路由散布在 5 个内容域（daily-review / intel / sectors / sector-divergence / prediction 各自独立页），导航无分组层次、无全局联动、无命令面板。具体痛点（fresh 核实）：

- **首屏入口分散**：root `"/"` redirect 到 `/daily-review`（router.tsx:33），但 daily-review + intel + sectors + sector-divergence + prediction 五页散布，用户须手动跳 5 次才能看全市场。
- **导航扁平**：NAV_GROUPS（navigation.ts:29）当前 ~4 组扁平列表，无手风琴折叠，31 tab 平铺信息过载。
- **二级 tab 靠 pathname hack**：SUB_TABS（navigation.ts:98-155）14 个前缀键，Layout.tsx 用 `pathname.startsWith(prefix)` 匹配（:46/:50），改路径须同步改 SUB_TABS 否则 404 tab。
- **无全局股票联动**：grep `currentStock|selectedStock` 零命中——无跨页 currentStock store，/stock/:code（StockDeep.tsx）不可从选股器/命令面板直达。
- **无命令面板**：package.json 无 cmdk/kbar——每次跳页须手动在侧边栏找。
- **DailyReview 双结构死代码**：DailyReview.tsx（762 行，router.tsx:34 active）与 DailyReview/ folder（index.tsx + components/7 + pages/3）并存，folder 是死代码。
- **Workflow.tsx 承重逻辑未迁出**：stageToDefaultTab（:37）+ useMarketClock 调用（:156）是一日闭环逻辑，Workflow.tsx 解散须先迁出。
- **FirstBoardPipeline.tsx 1126 行**：单文件过大，拆分耦合紧（grill #10）。

### 1.2 目标

将前端重构为 **trade-desk cockpit** 架构：四层导航（L0 命令面板 + L1 侧边栏 7 组手风琴 + L2 页内 TabBar + L3 右侧面板）+ 双 Layout（标准单焦点 + Cockpit SplitLayout），31 tab → 17 tab（降 45%），服务三问（买什么/何时买/何时卖）+ 多策略工具箱对接。单屏 13 寸优化（不管移动端）。

---

## 2. 背景

### 2.1 设计来源

2026-09-09 w3uzkmy39 workflow（12 agent：6 调研 TradingView/Bloomberg/同花顺/东财/雪球/SeekingAlpha/finviz + 5 专家 judge panel + synthesis grill）出页面架构重设计 verdict。设计已定，本 spec 落盘。

借鉴：Bloomberg（命令面板 + 组件 Linking → currentStock + cockpit 密度 + 灰度迁移）/ TradingView（右侧面板 + SplitView + 列 tab）/ finviz（信号预设 + 6 类筛选 + treemap）/ 雪球（个股 7 tab + PB-ROE 散点）/ 同花顺（单组 5-7 tab 上限）/ qlib（Data→Strategy→Backtest→Recorder 反前视）。

### 2.2 现有前端 fresh 核实（file:line 证据）

| 项 | 实测值 | 证据 |
|---|---|---|
| package.json deps | echarts ^6.0.0 ✓ · react-router-dom ^7.1.0 · react ^19 · @tanstack/react-query · lucide-react · clsx · tailwind-merge · sonner · react-markdown · remark-gfm | package.json |
| zustand 在 deps | **否**（grill #1 确认） | package.json grep 无命中 |
| cmdk/kbar 在 deps | 否 | package.json grep 无命中 |
| react-window/virtuosa | 否 | package.json grep 无命中 |
| router.tsx path 数 | 56 | `grep -c "path:" src/router.tsx` = 56 |
| router.tsx top-level 段 | 32 个 distinct | grep -oE distinct |
| root redirect | `"/"` → Navigate `to="/daily-review"` | router.tsx:33 |
| SUB_TABS 定义 | navigation.ts:98，14 前缀键（:99-155） | navigation.ts |
| SUB_TABS 消费 | Layout.tsx prefix-match 6 处（:31/:46/:78/:109/:220/:250） | Layout.tsx |
| NAV_GROUPS 定义 | navigation.ts:29，当前 ~4 组（目标重组为 7） | navigation.ts |
| Layout.tsx | 292 行 | wc -l |
| currentStock store | **不存在**（grep 零命中） | grep currentStock |
| DailyReview.tsx | 762 行（router.tsx:34 active） | wc -l |
| DailyReview/ folder | index.tsx + components/7（IndexCards/EmotionSummary/GlobalMarket/ReviewReport/AiReviewPanel/SectorFundFlow/WatchlistGrid）+ pages/3（SectorDetail/ReviewDetail/EmotionDetail）= 死代码 | find src/pages/DailyReview |
| Workflow.tsx | 325 行 | wc -l |
| stageToDefaultTab | Workflow.tsx:37 | grep |
| useMarketClock | import @:17，调用 @:156 | Workflow.tsx |
| FirstBoardPipeline.tsx | 1126 行 | wc -l |
| FirstBoardPage.tsx | 204 行 | wc -l |
| components/ top-level dirs | 17 个（auction/candidate/charts/common/intraday/journal/layout/pipeline/prediction/recommendation/risk/seat/sentiment-weather/sti/topology/ui/winrate/workflow） | ls -d |
| pages/ tsx 文件 | 89（含子组件，非 31 路由页） | find |
| Advisory.tsx | 195 行（S042 建议中心，非空壳） | wc -l + head |
| Portfolio.tsx | 295 行（真实页） | wc -l |
| /stock/:code 现页 | StockDeep.tsx（router.tsx:43） | router.tsx |
| /workflow/intraday 现页 | IntradayMonitor.tsx（router.tsx:69） | router.tsx |
| /strategy 现页 | StrategyPage.tsx（router.tsx:78） | router.tsx |
| limitup 子路由 | 5（/limitup + /gene + /auction + /seats + /premarket） | router.tsx:50-54 |

### 2.3 15 grill 发现（承重，须 address）

详见 §9 风险表逐条 address。摘要：grill #1 zustand 不在 deps / #2 DailyReview 双结构 / #3 SUB_TABS 14 prefix-match 连锁 / #4 Workflow.tsx 承重逻辑迁移 / #5 选股器"统一"可能 trench coat / #6 盘中有位置没数据 / #7 multiline verdict 窗口口径 / #8 cockpit 密度 vs 13 寸 / #9 跨切改动不可域隔离 / #10 FirstBoardPipeline 1126 行耦合 / #11 treemap 5000 标的 / #12 选股器 preset 后端 gap / #13 /stock/:code 不可直达 / #14 送入菜单 schema 未定 / #15 verdict schema 异构。

---

## 3. 需求（按 4 期组织）

### R0 · Phase 0 基建（无路由变更，先于页迁移）

**R0.1 currentStock store**：建跨页 currentStock store（React Context + useReducer，0 新依赖——grill #1 决策：zustand 不在 package.json，用 React Context 避免新依赖；若后续状态复杂再评估 zustand）。store 持 {code, name, source, browsedAt[]}，支持 setCurrentStock / clearCurrentStock / pushBrowsed。无现有 store（grep 零命中，从 0 建）。

**R0.2 命令面板（L0）**：建全局浮层命令面板（Cmd+K toggle，macOS Cmd+K 避浏览器 Ctrl+K 冲突——用户已定）。模糊匹配三源：① 路由名（17 tab 中文名+path）② 股票代码（前 10 匹配，代码表来源待定——前端内置 vs 后端搜索 API，见 open_questions）③ 预设信号（breakout/gene/auction 等筛选 preset）。键盘导航 ↑↓ + Enter 跳转 + Esc 关闭。自建组件（不引入 cmdk/kbar——功能简单 + 样式体系一致）。

**R0.3 SplitLayout 基建**：建 SplitLayout 组件（左列表 + 右详情，CSS Grid `grid-template-columns: var(--split-left, 340px) 1fr`，拖拽条改 CSS 变量 + localStorage 持久化宽度）。13 寸单屏优化，不做移动端降级（用户已定"不管移动端"）。

**R0.4 honest label + 送入菜单**：建"送入"动作菜单组件（选股行 → {watchlist, portfolio, journal, research} 四向送入）。数据 schema 契约（grill #14）：`{code, name, source_page, timestamp, target}`。各 target 的后端 API 对接受影响文件表（§4）。

**R0.5 NAV_GROUPS 重组 7 组**：将 navigation.ts:29 的 NAV_GROUPS 重组为 7 组手风琴（交易台/选股/个股/投资管理/研究中心/系统+1），expandedGroup 单组展开状态。无路由变更，纯导航重组。

**R0.6 verdict per-type 渲染基建**：建 VerdictRenderer 组件（grill #15），按 verdict type 分发：selection（S168: lift/n_picks/days_robust/falsified|exploratory|underpowered）/ event（S169: t_stat/p_value/window/drift_direction）/ long_value（S171: pe_ratio/margin_of_safety/verdict_status）。per-type 独立子组件，不强拟合异构 schema。

### R1 · Phase 1 高价值新页（不碰旧路由，灰度验证）

**R1.1 /screener 选股器**：新建 /screener 页（6 类筛选 + 预设信号 + 顶部搜索框）。先做 filter 抽象层（grill #5：gene/auction/seats 独特交互，须 filter 抽象层统一而非 6 页穿 trench coat）。limitup 5 子路由（/gene /auction /seats /premarket）作为 preset 接入选股器，保留特色交互但统一 filter 框架。preset 接 hithink endpoint（grill #12：后端统一筛选 API vs 前端 fan-out——open_question）。送入菜单（R0.4）+ currentStock 联动（R0.1）。

**R1.2 /stock/:code cockpit**：新建 StockCockpit 页（图表中心 + 右侧面板 toggle：自选/资讯/财务/资金/信号/笔记/龙虎榜/AI 8 面板）。替代现有 StockDeep.tsx（router.tsx:43，Phase 3 redirect 旧→新）。currentStock 联动（R0.1）——选股器选股 → setCurrentStock → /stock/:code 自动展示。无 code 时显示最近浏览（currentStock.browsed）或 EmptyState"请先从选股器选股"（grill #13）。

**R1.3 /market 首屏 cockpit**：新建 /market 页（指数卡片 + 板块 treemap 热力图 + 涨停/炸板/连板摘要 + 情绪天气 + 全球情报折叠 + 涨跌预测）。ECharts treemap（package.json 已有 echarts^6——用户已定）聚合申万 30 板块 + 虚拟化（grill #11：5000 标的须聚合不裸渲染）。替代 daily-review+intel+sectors+sector-divergence+prediction 五页散布。Phase 3 root redirect "/" → /market。

### R2 · Phase 2 盘中 + 研究（加维度）

**R2.1 /intraday 盘中 cockpit**：新建 /intraday 页（SplitLayout 候选列表 + 个股预览 + 告警流 + 教练）。OFI 数据接 S176 ofi_snapshots（scheduler */3 9-14 已采）。honest empty state（grill #6：push2his IP 封 + hithink 有限，盘中 60% 未测，可能长期无数据 → 诚实空态不假装有数据）。IntradayMonitor.tsx（router.tsx:69）迁移为 /intraday 的右侧面板或 redirect。

**R2.2 /multiline 三列战略**：新建 /multiline 页（三列：短线打板 / 中线 event / 长线价值）。verdict 须标窗口口径（grill #7：§44v1 教训，verdict 窗口依赖，标"D+1开盘→D+4 path"等口径标签）。短线列接 S168 selection verdict（全 falsified/exploratory）；中线列接 S169 event verdict（gap robust_edge 60d）；长线列接 S171 long value（spec done R3，R2 verdict harness 待跑——此列标 honest placeholder "verdict 待跑"）。

**R2.3 /strategy 策略研究**：已有 StrategyPage.tsx（router.tsx:78，295 行），加维度（回测 + 前向测试 + 信号 + 风险指标集）。接 qlib 反前视 + Recorder 模式（memory: 开源量化框架调研采纳）。

**R2.4 /portfolio 投资管理**：已有 Portfolio.tsx（router.tsx:41，295 行），加维度（风险仪表盘 + 健康分 + PB-ROE 散点图）。接 S172 ETF floor + S175 PaperPortfolio。

**R2.5 /advisory AI 顾问**：已有 Advisory.tsx（router.tsx:56，195 行 S042 建议中心），重构为 cockpit（今日推荐 + 顾问团 + 大辩论）。今日推荐接 S175 follow-order；顾问团接 grill-me skill 6-lens；大辩论接现有 /debate。

**R2.6 /review 复盘中心**：新建 /review 页（行为模式 + 研报管理）。接 BehaviorLoop.tsx（router.tsx:68）+ MyReports.tsx（router.tsx:47）。胜率反馈闭环。

### R3 · Phase 3 清理（旧路由 redirect，保兼容）

**R3.1 root redirect**：router.tsx:33 `"/"` → Navigate `to="/market"`（替代 /daily-review）。

**R3.2 Workflow.tsx 解散**：迁 stageToDefaultTab（:37）+ useMarketClock 调用（:156）+ useDateTriplet（:16）到新模块（day-phase-rail 组件或 lib hook）。Workflow.tsx 325 行解散，7 态状态机逻辑迁入对应新页（pre-market→/screener, intraday→/intraday, post-market→/review）。

**R3.3 DailyReview 双结构清理**：删 DailyReview.tsx（762 行）+ DailyReview/ folder 死代码（index.tsx + components/7 + pages/3）。功能已迁 /market（R1.3）。router.tsx:34-37 四路由 redirect 到 /market 子区。

**R3.4 FirstBoardPipeline 拆分**：FirstBoardPipeline.tsx（1126 行）TDD 拆分（grill #10：codegraph CLI 摸依赖树 → 按职责拆模块 → 测试锁定行为不回归）。拆为 pipeline steps + data transform + render 分离。

**R3.5 SUB_TABS 消除**：删 navigation.ts:98-155 SUB_TABS 定义（14 键）+ Layout.tsx 6 处 prefix-match（:31/:46/:78/:109/:220/:250）。页内 TabBar 组件替代（每页内部 useState 管 active tab，不通过 pathname hack）。

**R3.6 旧路由 redirect 表**：建 redirect 映射表，旧 31 路由 → 新 17 路由，保兼容（memory: 灰度迁移旧路由 redirect 保兼容）。

---

## 4. 受影响文件表

| 文件 | 改动 | Phase | grill# |
|---|---|---|---|
| src/stores/currentStock.tsx（新建） | R0.1 currentStock Context store | P0 | #1,#9,#13 |
| src/components/command-palette/CommandPalette.tsx（新建） | R0.2 L0 命令面板 | P0 | #9 |
| src/components/command-palette/useCommandPalette.ts（新建） | R0.2 Cmd+K toggle hook | P0 | — |
| src/components/layout/SplitLayout.tsx（新建） | R0.3 SplitLayout 组件 | P0 | #8,#9 |
| src/components/layout/CockpitLayout.tsx（新建） | R0.3 双 Layout cockpit 版 | P0 | — |
| src/components/layout/StandardLayout.tsx（新建） | R0.3 双 Layout 标准版 | P0 | — |
| src/components/layout/SendToMenu.tsx（新建） | R0.4 送入菜单 + schema 契约 | P0 | #14 |
| src/components/layout/navigation.ts（改） | R0.5 NAV_GROUPS 重组 7 组 + R3.5 删 SUB_TABS | P0,P3 | #3 |
| src/components/layout/Layout.tsx（改） | R0.5 引 SplitLayout/StandardLayout + R3.5 删 prefix-match 6 处 | P0,P3 | #3,#8,#9 |
| src/components/verdict/VerdictRenderer.tsx（新建） | R0.6 per-type verdict 渲染 | P0 | #15 |
| src/components/verdict/SelectionVerdictCard.tsx（新建） | R0.6 S168 verdict 渲染 | P0 | #15 |
| src/components/verdict/EventVerdictCard.tsx（新建） | R0.6 S169 verdict 渲染 | P0 | #15 |
| src/components/verdict/LongValueVerdictCard.tsx（新建） | R0.6 S171 verdict 渲染 | P0 | #15 |
| src/pages/market/MarketPage.tsx（新建） | R1.3 /market 首屏 cockpit | P1 | #11 |
| src/pages/screener/ScreenerPage.tsx（新建） | R1.1 /screener 选股器 | P1 | #5,#12 |
| src/pages/screener/FilterPanel.tsx（新建） | R1.1 filter 抽象层 | P1 | #5 |
| src/pages/stock/StockCockpit.tsx（新建） | R1.2 /stock/:code cockpit | P1 | #13 |
| src/router.tsx（改） | 加 10 新页路由 + P3.1 root redirect + P3.6 redirect 表 | P1,P3 | — |
| src/pages/intraday/IntradayCockpit.tsx（新建） | R2.1 /intraday 盘中 cockpit | P2 | #6 |
| src/pages/multiline/MultilinePage.tsx（新建） | R2.2 /multiline 三列战略 | P2 | #7 |
| src/pages/strategy/StrategyPage.tsx（改） | R2.3 加维度 | P2 | — |
| src/pages/Portfolio.tsx（改） | R2.4 加维度 | P2 | — |
| src/pages/Advisory.tsx（改） | R2.5 重构为 cockpit | P2 | — |
| src/pages/review/ReviewPage.tsx（新建） | R2.6 /review 复盘中心 | P2 | — |
| src/pages/Workflow.tsx（改/删） | R3.2 解散，迁 stageToDefaultTab+useMarketClock | P3 | #4 |
| src/lib/useMarketClock.ts（改） | R3.2 确认独立于 Workflow（已有 @/lib/useMarketClock） | P3 | #4 |
| src/pages/DailyReview.tsx（删） | R3.3 删 762 行 | P3 | #2 |
| src/pages/DailyReview/（删 folder） | R3.3 删死代码（index.tsx+components/7+pages/3） | P3 | #2 |
| src/pages/workflow/components/FirstBoardPipeline.tsx（改/拆） | R3.4 TDD 拆分 1126 行 | P3 | #10 |

---

## 5. 设计方案

### 5.1 导航四层

**L0 命令面板**（全局浮层，非路由）：Cmd+K toggle，模糊匹配路由名 + 股票代码 + 预设信号，替代 Bloomberg 助记码。自建组件（不引 cmdk/kbar）。

**L1 侧边栏 7 组手风琴**：交易台 / 选股 / 个股 / 投资管理 / 研究中心 / 系统 + 1。expandedGroup 单组展开（手风琴），collapsed 状态保留（Layout.tsx 现有 collapsed 逻辑）。系统组底部齿轮 icon。

**L2 页内 TabBar**：消除 SUB_TABS pathname hack（navigation.ts:98 + Layout.tsx:46/50）。每页内部 useState 管 active tab，URL 用 `?tab=xxx` query param（可分享/书签）但不依赖 pathname 前缀。

**L3 右侧面板 toggle**：个股工作台竖排图标栏（自选/资讯/财务/资金/信号/笔记/龙虎榜/AI），toggle 展开收起，currentStock.code 驱动。

### 5.2 双 Layout

**StandardLayout**：单 Outlet max-w-6xl，单焦点页（/screener /strategy /portfolio /advisory /review）。

**CockpitLayout**：SplitLayout 左列表 + 右详情，单屏 13 寸（/market /stock/:code /intraday /multiline）。SplitLayout 拖拽条 + localStorage 持久化宽度，不做移动端降级。

### 5.3 10 新页

| 新页 | Layout | 服务三问 | 对接 |
|---|---|---|---|
| /market | Cockpit | 一屏看全市场（发现） | 市场 regime |
| /screener | Standard | 买什么·候选池 | 多策略出标的 |
| /stock/:code | Cockpit | 研究 | currentStock 联动 |
| /intraday | Cockpit | 何时买·盘中信号 | S176 OFI |
| /multiline | Cockpit | 多策略总览 | S168/S169/S171 verdict |
| /strategy | Standard | 胜率反馈 | qlib 反前视 |
| /portfolio | Standard | 何时卖·持仓出场 | S172/S175 |
| /advisory | Standard | 决策辅助 | grill-me 6-lens |
| /review | Standard | 复盘 | BehaviorLoop+MyReports |
| 基建（store/命令面板/SplitLayout/day-phase-rail） | — | — | — |

### 5.4 31→17 tab 收敛

旧 31 top-level → 新 17 tab（降 45%）：daily-review+intel+sectors+sector-divergence+prediction → /market；limitup 5 子 → /screener preset；workflow 7 态 → /screener+/intraday+/review；behavior-loop+my-reports → /review；stock-data+notes → /stock/:code 面板；debate → /advisory。

---

## 6. 验收标准

### A1 currentStock store（P0）
- [ ] A1.1 `grep -r "useCurrentStock" src/` 命中 ≥3 文件（store 消费者）
- [ ] A1.2 currentStock store 单测：setCurrentStock → code 更新；clearCurrentStock → null；pushBrowsed → browsed 数组追加去重
- [ ] A1.3 跨页联动：/screener 选股 → setCurrentStock → navigate /stock/:code → StockCockpit 读 currentStock.code 渲染

### A2 命令面板（P0）
- [ ] A2.1 Cmd+K 打开浮层，Esc 关闭，↑↓ 键盘导航，Enter 跳转
- [ ] A2.2 模糊匹配路由名（输入"选股"匹配 /screener）
- [ ] A2.3 模糊匹配股票代码（输入"600519"匹配贵州茅台——数据源待定见 open_questions）
- [ ] A2.4 无 cmdk/kbar 新依赖（`grep -E "cmdk|kbar" package.json` 零命中）

### A3 SplitLayout（P0）
- [ ] A3.1 左右分栏渲染，拖拽条改宽度，localStorage 持久化
- [ ] A3.2 无第三方 split pane 库依赖
- [ ] A3.3 13 寸单屏无横向滚动条

### A4 送入菜单（P0）
- [ ] A4.1 选股行"送入"菜单 4 向（watchlist/portfolio/journal/research）
- [ ] A4.2 schema 契约 `{code, name, source_page, timestamp, target}` 落盘
- [ ] A4.3 送入 watchlist → POST /api/watchlist 命中后端（后端契约见受影响文件表）

### A5 NAV_GROUPS 7 组（P0）
- [ ] A5.1 navigation.ts NAV_GROUPS 7 组，手风琴单组展开
- [ ] A5.2 旧路由仍可达（无 404，redirect 保兼容）

### A6 /market treemap（P1）
- [ ] A6.1 ECharts treemap 渲染申万 30 板块聚合
- [ ] A6.2 5000 标的聚合后 ≤30 节点（不裸渲染 5000 叶子）
- [ ] A6.3 首屏 treemap 渲染 < 500ms（13 寸 Chrome）
- [ ] A6.4 click 板块 → navigate /screener?sector=xxx；click 个股 → setCurrentStock + navigate /stock/:code

### A7 /screener 选股器（P1）
- [ ] A7.1 filter 抽象层（条件组 + preset），非 6 页穿 trench coat
- [ ] A7.2 limitup 5 preset（gene/auction/seats/premarket/LimitUpStrategy）作为 preset 接入
- [ ] A7.3 顶部搜索框 + currentStock 联动 + 送入菜单

### A8 /stock/:code cockpit（P1）
- [ ] A8.1 图表中心 + 右侧 8 面板 toggle
- [ ] A8.2 currentStock 联动（选股器选股 → 自动展示）
- [ ] A8.3 无 code 时 EmptyState"请先从选股器选股"或显示最近浏览

### A9 /intraday honest empty state（P2）
- [ ] A9.1 OFI 数据接 S176 ofi_snapshots
- [ ] A9.2 无数据时 HonestEmptyState（不假装有数据）
- [ ] A9.3 SplitLayout 候选列表 + 个股预览 + 告警流 + 教练

### A10 /multiline verdict 窗口口径（P2）
- [ ] A10.1 三列 verdict 各标窗口口径标签（如"D+1开盘→D+4 path"）
- [ ] A10.2 长线列标 honest placeholder"verdict 待跑"（S171 R2 未跑）
- [ ] A10.3 verdict per-type 渲染（VerdictRenderer 分发）

### A11 Phase 3 清理（P3）
- [ ] A11.1 root "/" → /market redirect
- [ ] A11.2 Workflow.tsx 解散，stageToDefaultTab+useMarketClock 迁出且单测绿
- [ ] A11.3 DailyReview.tsx(762行)+folder 死代码删，功能不丢（/market 覆盖）
- [ ] A11.4 FirstBoardPipeline.tsx(1126行)拆分后各模块 <300 行，单测绿
- [ ] A11.5 SUB_TABS 删，Layout.tsx 6 处 prefix-match 删，无 404 tab
- [ ] A11.6 旧路由 redirect 表 31→17，全量 `vitest run` + `tsc --noEmit` 绿

### A12 全局
- [ ] A12.1 `tsc --noEmit` 零 error
- [ ] A12.2 `vitest run` 全量绿（含现有 188+ tests）
- [ ] A12.3 `npm run build` 成功（无新依赖除非 plan 批准）

---

## 7. 合规自查

### 7.1 弱合规（风险提醒级，私人助理定位）

- [x] 免责声明：cockpit 各页保留轻量风险提醒（如 /advisory "历史统计特征，市场有风险"），不强制免责墙
- [x] 个股呈现：/screener /stock/:code 如实呈现个股 code/name（用户自己工具，公开榜单）
- [x] 不代客决策：/advisory 给方向性研判但用户最终决策

### 7.2 工程底线（保留）

- [x] **不臆造数据**：所有"现有 X"声称已 fresh grep/Read 核实（§2.2 file:line 证据）；未核实的标"待核实"或"open_question"
- [x] **私有数据隔离**：currentStock store 纯前端状态，不碰 .vibe-research/ 私有数据；送入菜单后端 API 走项目内 VR_DATA_DIR
- [x] **em_get 防封**：本 spec 纯前端，不直接调东财端点；/market treemap 数据源走后端 API（后端若调东财走 em_get 限流，不在本 spec scope 但受影响文件表标注）

---

## 8. 测试计划

### 8.1 单元测试
- currentStock store：setCurrentStock / clear / pushBrowsed 去重
- 命令面板：模糊匹配路由/股票/信号索引
- SplitLayout：拖拽改宽度 + localStorage 持久化
- 送入菜单：schema 契约校验
- VerdictRenderer：per-type 分发（selection/event/long_value 各 mock verdict）
- FilterPanel：条件组 + preset 切换

### 8.2 集成测试
- /screener 选股 → setCurrentStock → /stock/:code 联动（React Router TestEnvironment）
- /market treemap click → navigate + setCurrentStock
- 送入 watchlist → POST mock → 刷新
- 命令面板 Cmd+K → 模糊匹配 → Enter 跳转

### 8.3 E2E（Playwright，已装 @playwright/test）
- 13 寸视口：/market 首屏无横向滚动
- Cmd+K 命令面板全流程
- /screener → /stock/:code → 右侧面板 toggle
- /intraday honest empty state（无 OFI 数据时）
- Phase 3 redirect：旧路由 → 新路由不 404

### 8.4 回归
- 全量 `vitest run`（现有 188+ tests）每 Phase 结束跑
- `tsc --noEmit` 零 error
- `madge --circular src/`（已装 madge^8）查循环依赖

---

## 9. 风险与回滚

| grill# | 风险 | address（spec/tasks 对应）| 回滚 |
|---|---|---|---|
| #1 | zustand 不在 deps，store 技术选型 | R0.1 决策 React Context + useReducer（0 新依赖）；open_question 若后续复杂再评估 zustand | 回滚：删 currentStock.tsx，各页自管 state |
| #2 | DailyReview 双结构（.tsx 762行 + folder 死代码）| R3.3 先 repoint router.tsx:34 → 验收 /market 覆盖功能 → 删 .tsx + folder；open_question repoint vs /market 替代 | 回滚：git revert router.tsx redirect，DailyReview.tsx 恢复 |
| #3 | SUB_TABS 14 prefix-match 连锁 | R3.5 同步删 navigation.ts:98-155 + Layout.tsx 6 处 prefix-match；每页建页内 TabBar 组件替代；A11.5 验收无 404 tab | 回滚：SUB_TABS 恢复，prefix-match 恢复 |
| #4 | Workflow.tsx 解散须迁承重逻辑 | R3.2 先迁 stageToDefaultTab(:37)+useMarketClock(:156) 到 day-phase-rail 组件/lib → 单测绿 → 再解散 Workflow.tsx | 回滚：Workflow.tsx 恢复 |
| #5 | 选股器"统一"可能 6 页 trench coat | R1.1 先做 filter 抽象层（条件组 + preset）spec → gene/auction/seats 保留特色交互但统一 filter 框架；open_question preset 保留 vs 真统一 | 回滚：filter 抽象层删，limitup 5 子路由恢复独立 |
| #6 | 盘中有位置没数据（push2his 封 + hithink 有限）| R2.1 HonestEmptyState 组件（不假装有数据）；OFI 接 S176 已采数据 | 回滚：/intraday 页删，IntradayMonitor.tsx 恢复 |
| #7 | /multiline verdict 窗口口径 | R2.2 verdict 各标窗口口径标签（§44v1 教训）；长线列 honest placeholder | 回滚：/multiline 页删 |
| #8 | cockpit 密度 vs 13 寸过载 | R0.5 default-collapse（手风琴单组展开 + L3 面板默认收起）；A3.3 13 寸无横滚 | 回滚：collapse 状态改全展开 |
| #9 | 跨切改动不可域隔离 | Phase 0 基建先行（currentStock+SplitLayout+NAV_GROUPS）→ 每 Phase 结束全量 tsc+vitest | 回滚：Phase 级 git revert |
| #10 | FirstBoardPipeline 1126 行耦合紧 | R3.4 codegraph CLI 摸依赖树 → TDD 拆（先写测试锁定行为 → 拆模块 → 测试仍绿）| 回滚：拆分 revert，1126 行恢复 |
| #11 | treemap 5000 标的性 | R1.3 ECharts large 模式 + 聚合申万 30 板块（不裸渲染 5000 叶子）；A6.3 <500ms 验收 | 回滚：treemap 降级为板块列表 |
| #12 | 选股器 preset 后端 gap | R1.1 open_question：统一筛选 API vs 前端 fan-out；preset 接 hithink endpoint 后端契约待定 | 回滚：preset 前端硬编码 |
| #13 | /stock/:code 侧边栏不可直达 | R1.2 currentStock.browsed fallback → 无 code 显示最近浏览或 EmptyState"请先选股" | 回滚：/stock/:code 无 code 时 redirect /screener |
| #14 | 送入菜单 schema 未定 | R0.4 落盘 schema 契约 `{code,name,source_page,timestamp,target}`；受影响文件表标注各 target 后端 API | 回滚：送入菜单删 |
| #15 | verdict schema 异构 | R0.6 VerdictRenderer per-type 分发（selection/event/long_value 各子组件，不强拟合）| 回滚：VerdictRenderer 删，各页自管 verdict 渲染 |

---

## 10. 开放问题（主 agent 审后定）

见 StructuredOutput.open_questions_remaining 字段。

---

## 11. 用户决策（2026-09-10 已定）+ grill 11 findings 修法

### 11.1 用户 4 决策（已定，override open_questions）

1. **currentStock store**：React Context + useReducer（零依赖，不引 zustand）。R0.1 定。13 寸密集 cockpit 重渲染风险用 selector 拆 context 缓解。
2. **FirstBoardPipeline 1126 行**：Phase 3 拆（TDD + codegraph 摸依赖先）。R3.4 定。盘中 reframe 可能用部分逻辑，拆后模块化可复用，TDD 锁定行为不丢。
3. **DailyReview 双结构**：repoint 再删（folder 三 detail 页 repoint 到 /market 子区后删 .tsx + folder）。R3.3 定。repoint 前先 grep 核实 pages/3 是否活路由（grill F1）。
4. **31→17 收敛**：主 agent 定具体映射（核证据：NAV_GROUPS 实际 5 组 35 tabs 非 31；SUB_TABS 14 prefix）。映射草见 §11.3，impl Phase 3 精化。

### 11.2 grill 11 findings 修法

| # | sev | finding | 修法 |
|---|---|---|---|
| F1 | HIGH | DailyReview folder pages/3 被误标死代码（实际活路由）| R3.3 repoint 前先 grep 核实 pages/3 活路由，活的 repoint 非删 |
| F2 | MED | 31→17 映射不完整 ~15 路由成孤儿 | §11.3 定具体映射，Phase 3 redirect 旧路由 |
| F3 | MED | Phase 0 NAV_GROUPS 重组可能指向没建的新路由→死链 | Phase 0 NAV_GROUPS 只重组现有 tab，新路由 Phase 1 建后才加入 |
| F4 | MED | R0.6 新建 LongValueVerdictCard 但 S171ValueVerdict 已存在→重复 | R0.6 改为复用 S171ValueVerdict.tsx 非新建 |
| F5 | MED | Phase 3 拆 FirstBoardPipeline 与"无 edge"战略矛盾 | 用户已定拆——盘中 reframe 可能用部分逻辑，TDD 锁定行为不丢，拆后模块化 |
| F6 | MED | currentStock Context 13 寸密集 cockpit 重渲染风险 | R0.1 用 useReducer + memoized context + 按 selector 拆 context（code/browsedAt 分 provider）|
| F7 | MED | VerdictRenderer verdict 数据源未指定 | R0.6 VerdictRenderer 数据源 = GET /api/verifier/records（S165 已有）|
| F8 | LOW | open_question 说"6 limitup preset"实际 5 条 | 改为 5 条（gene/auction/seats/premarket + limitup 父）|
| F9 | LOW | 数量小错（NAV_GROUPS 4 实 5 / components 17 实 18 / router 32 含糊）| spec §2 改：NAV_GROUPS 5 组 35 tabs / components 18 顶层 / router 56 path |
| F10 | LOW | ECharts 5000 点 60fps 未实测 | R1.3 改为"待 Phase 1 A6 压测确认"非"60fps"结论 |
| F11 | LOW | L2 TabBar §5.1 提但新建模块清单没共享 TabBar 组件 | §2.1 新建模块加 components/layout/TabBar.tsx 共享组件 |

### 11.3 31→17 映射草（主 agent 定，impl Phase 3 精化）

现状 35 tabs（5 组）→ 17 tabs（6 内容组+1 系统）：

| 新组 | 新 tab | 收纳旧 tab |
|---|---|---|
| 交易台 | /market | daily-review + intel + sectors + sector-divergence + prediction + debate |
|  | /intraday | workflow 盘中 |
| 选股 | /screener | candidates + value-funnel + limitup(5 子) + stock-data |
|  | /stock/:code | stock-data 个股 |
|  | /watchlist | watchlist |
| 个股 | /multiline | （新）|
|  | /strategy | strategy + backtest + strategy-signals + verifier-records + value-verdict |
| 投资管理 | /portfolio | portfolio + risk-dashboard |
|  | /advisory | advisory + recommendation |
|  | /journal | journal + behavior-loop |
|  | /review | my-reports + notes |
| 研究中心 | /sentiment/weather | sentiment/weather |
|  | /industry | industry |
| 系统 | /settings | settings |
|  | /scheduled-tasks | scheduled-tasks |
|  | /health | health |
|  | /metrics | metrics |

**17 条**：/market /intraday /screener /stock/:code /watchlist /multiline /strategy /portfolio /advisory /journal /review /sentiment/weather /industry /settings /scheduled-tasks /health /metrics

Phase 3 验证映射 + redirect 旧路由（旧路由 Phase 0-2 保兼容，3 期才删）。
