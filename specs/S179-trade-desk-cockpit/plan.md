# S179 · Trade Desk Cockpit — 技术方案 (plan.md)

**关联**：spec S179（同目录 spec.md）
**创建**：2026-09-10
**定位**：spec §5 设计方案的"怎么做"——取舍、备选为何不选、模块拆分、4 期依赖序、数据流。

---

## 1. 取舍决策（含备选为何不选）

### P1. currentStock store：React Context + useReducer（选）vs zustand（弃）

**选 React Context + useReducer**：
- 0 新依赖（package.json 已有 react^19，Context 是内置 API）
- 当前无 currentStock store（grep `currentStock|selectedStock` 零命中），是从 0 建，无迁移
- 唯一消费者是跨页联动（/screener 选股 → /stock/:code 展示 → 右侧面板 toggle），状态简单（{code, name, source, browsedAt[]}），useReducer + memoized context 足够
- React 19 的 useContext + use 优化了 context 重渲染（provider value memoize + 按 selector 拆 context 避免全树重渲染）

**弃 zustand 理由**：新依赖引入成本（维护/版本/学习）；当前状态简单不值得引入全局状态库；未来若状态复杂（多 store + middleware）再迁 zustand 不迟（YAGNI）。

### P2. 命令面板：自建浮层组件（选）vs cmdk/kbar 库（弃）

**选自建**：
- 命令面板交互简单（输入框 + 模糊匹配 + 键盘导航 ↑↓ + Enter 跳转 + Cmd+K toggle + Esc 关闭 + 浮层 z-index）
- 已有 lucide-react 图标 + tailwind 样式体系，自建 ~200 行可控
- cmdk 库样式体系与项目 tailwind 不一致（cmdk 默认 styled-components），集成成本 > 自建

**弃 cmdk 理由**：样式不一致需大量 override；功能简单不值得引入依赖。

### P3. SplitLayout：CSS Grid 左右分栏（选）vs 第三方 split pane 库（弃）

**选 CSS Grid**：
- SplitLayout = `grid-template-columns: var(--split-left, 340px) 1fr` + 拖拽条改 CSS 变量
- 无新依赖，纯 CSS + ~60 行 JS（拖拽事件 + localStorage 持久化宽度）
- 单屏 13 寸固定（用户定），不需要移动端降级（用户定"不管移动端"），Grid 够用

**弃 react-split-pane/allotment 理由**：新依赖；13 寸单屏不需要复杂 split pane 功能（多区域/嵌套）。

### P4. treemap：ECharts（选）vs d3 自建（弃）

**选 ECharts**（package.json 已有 echarts^6.0.0）：
- 内置 treemap 类型 + 虚拟化（large 模式：`series.large: true` + `progressive`）
- 5000 标的聚合申万 30 板块：treemap 节点 = 30 个板块（value = 板块市值和），叶子可选展开看个股
- 性能：ECharts treemap large 模式 5000 点实测 ~60fps（待 Phase 1 验收 A6 压测确认）

**弃 d3 自建理由**：开发成本高（需自建 treemap 布局算法 + SVG 渲染 + 虚拟化）；ECharts 已装且团队熟悉。

### P5. 移除 SUB_TABS：页内 TabBar 组件替代 pathname hack（选）vs 保留 SUB_TABS（弃）

**选页内 TabBar 组件**：
- 每页内部管理 active tab 状态（useState），不通过 pathname 编码
- 消除 14 处 prefix-match（Layout.tsx:31/46/78/109/220/250 + navigation.ts:98-155）
- 消除 Layout.tsx:250 的 `tabTo` 拼接 hack（`pathname + ?tab=key`）
- URL 可保留 `?tab=xxx` query param 供分享/书签，但不依赖 pathname 前缀匹配

**弃保留 SUB_TABS 理由**：pathname hack 导致 404 tab（grill #3）、prefix-match 脆弱（路径变更需同步改 SUB_TABS）、2 层 tab 体验差。

---

## 2. 模块拆分

### 2.1 新建模块

```
src/
├── stores/
│   └── currentStock.tsx          # P1: Context + useReducer + hook useCurrentStock
├── components/
│   ├── command-palette/
│   │   ├── CommandPalette.tsx   # P2: 浮层 + 模糊匹配 + 键盘导航
│   │   ├── useCommandPalette.ts  # toggle/open/close + Cmd+K 监听
│   │   └── searchIndex.ts        # 路由名 + 股票代码 + 预设信号索引
│   ├── layout/
│   │   ├── SplitLayout.tsx       # P3: CSS Grid + 拖拽条 + localStorage
│   │   └── DayPhaseRail.tsx      # 日阶段轨道（pre-market→intraday→post-market）
│   │   └── CockpitLayout.tsx    # 双 Layout 之 cockpit（SplitLayout 包裹）
│   │   └── StandardLayout.tsx    # 双 Layout 之标准（单 Outlet max-w-6xl）
│   ├── intraday/
│   │   └── HonestEmptyState.tsx  # P6: 盘中无数据诚实空态
│   └── verdict/
│       └── VerdictRenderer.tsx   # P7: per-type verdict 渲染分发
├── pages/
│   ├── market/
│   │   └── MarketPage.tsx        # /market 首屏 cockpit
│   ├── screener/
│   │   ├── ScreenerPage.tsx      # /screener 选股器
│   │   ├── FilterPanel.tsx       # P5: filter 抽象层（条件组 + preset）
│   │   └── presets/              # 预设信号（breakout/gene/auction/seats/...）
│   ├── stock/
│   │   └── StockCockpit.tsx       # /stock/:code cockpit（替代 StockDeep）
│   ├── intraday/
│   │   └── IntradayCockpit.tsx    # /intraday 盘中 cockpit（SplitLayout）
│   ├── multiline/
│   │   └── MultilinePage.tsx     # /multiline 三列战略
│   ├── strategy/
│   │   └── ... (已有 StrategyPage.tsx，加维度）
│   ├── portfolio/
│   │   └── ... (已有 Portfolio.tsx，加维度）
│   ├── advisory/
│   │   └── ... (已有 Advisory.tsx，重构为 cockpit）
│   └── review/
│       └── ReviewPage.tsx        # /review 复盘中心
```

### 2.2 改造模块（不新建，改现有）

| 文件 | 改什么 | grill# |
|---|---|---|
| navigation.ts:29-64 | NAV_GROUPS 重组为 7 组手风琴 | — |
| navigation.ts:98-155 | SUB_TABS 删除（Phase 3）| #3 |
| Layout.tsx:31/46/78/109/220/250 | prefix-match 删除 + 引用 SplitLayout/StandardLayout | #3,#9 |
| Layout.tsx 全文(292行) | collapsed 侧边栏 + expandedGroup 重组 | #8 |
| router.tsx:33 | root "/" → /market redirect | — |
| router.tsx 全文(56 path) | 加 10 新页路由 + 旧路由 redirect | — |
| Workflow.tsx:37/156 | stageToDefaultTab + useMarketClock 迁出 | #4 |
| DailyReview.tsx(762行) | Phase 3 删或 repoint | #2 |
| DailyReview/ folder | Phase 3 验收后删 dead code | #2 |
| FirstBoardPipeline.tsx(1126行) | Phase 3 TDD 拆分 | #10 |

---

## 3. 4 期依赖序（拓扑序）

```
Phase 0 (基建，无路由变)
  ├── P0.1 currentStock store ──────────────┐
  ├── P0.2 命令面板 (依赖 0.1 的路由索引)    │
  ├── P0.3 SplitLayout + CockpitLayout       │ (SplitLayout 是 cockpit 页的前提)
  ├── P0.4 honest label + 送入菜单 schema    │
  └── P0.5 NAV_GROUPS 重组 7 组 (无路由删)    │
                                            │
Phase 1 (高价值新页，不碰旧路由)              │
  ├── P1.1 /screener (依赖 0.1 currentStock + 0.4 送入菜单) ←─┘
  ├── P1.2 /stock/:code cockpit (依赖 0.1 currentStock + 0.3 SplitLayout)
  └── P1.3 /market (依赖 0.3 cockpit layout + ECharts treemap)

Phase 2 (盘中 + 研究，加维度)
  ├── P2.1 /intraday (依赖 0.1 + 0.3 + OFI S176 + 0.4 honest empty)
  ├── P2.2 /multiline (依赖 verdict per-type renderer P0.6)
  ├── P2.3 /strategy 加维度 (已有页，加回测+前向+信号+风险)
  ├── P2.4 /advisory 重构 (已有 195 行，加顾问团+大辩论)
  ├── P2.5 /review 新建 (行为模式 + 研报管理)
  └── P2.6 /portfolio 加维度 (已有 295 行，加风险仪表盘+PB-ROE)

Phase 3 (清理，旧路由 redirect)
  ├── P3.1 root "/" → /market redirect (router.tsx:33)
  ├── P3.2 Workflow.tsx 解散 (迁 stageToDefaultTab:37 + useMarketClock:156)
  ├── P3.3 DailyReview.tsx(762行) + folder dead code 删
  ├── P3.4 FirstBoardPipeline.tsx(1126行) TDD 拆分
  └── P3.5 SUB_TABS 删 (navigation.ts:98-155 + Layout.tsx 6 处 prefix-match)
```

**依赖序约束**：Phase 0 必须先于 Phase 1（currentStock + SplitLayout 是新页前提）；Phase 1 先于 Phase 2（/stock/:code cockpit 是 /intraday 右侧面板的前提）；Phase 3 最后（旧路由在 0-2 期保兼容，3 期才删）。Phase 0-1 可并行（不碰旧路由），Phase 2 内部各页独立可并行，Phase 3 内部须按 P3.2→P3.5 序（Workflow 解散 → DailyReview 删 → FirstBoardPipeline 拆 → SUB_TABS 删，因 SUB_TABS 删影响全局需最后）。

---

## 4. 数据流

### 4.1 currentStock 联动流（Bloomberg Linking）

```
/screener 选股行 click → setCurrentStock({code, name, source:'screener'})
  → /stock/:code 自动导航 + StockCockpit 读 currentStock.code
  → 右侧面板 toggle（自选/资讯/财务/资金/信号/笔记/龙虎榜/AI）均读 currentStock.code
  → 浏览历史 push currentStock.browsed（供 /stock/:code 无 code 时 fallback 显示最近浏览）
```

### 4.2 送入动作数据流

```
选股行 "送入" 菜单 click → schema: {code, name, source_page, timestamp}
  → 送入 watchlist:  POST /api/watchlist {code} → 刷新 Watchlist
  → 送入 portfolio:  POST /api/paper-portfolio {code, source:'screener'} → S175 PaperPortfolio 建仓
  → 送入 journal:    POST /api/journal {signal_id, code, entry_source:'screener'} → S173 TradeJournal 预填
  → 送入 research:   POST /api/notes {code, link_type:'research'} → Notes 关联
```

### 4.3 /market treemap 数据流

```
GET /api/market-treemap → [{sector: '申万一级名', value: 市值和, stocks: [{code, name, pct_change}]}]
  → ECharts treemap: 30 板块节点（value=市值）→ hover 展开看个股
  → click 板块节点 → setCurrentStock? 不，navigate /screener?sector=xxx
  → click 个股 → setCurrentStock + navigate /stock/:code
```

### 4.4 盘中数据流（honest empty state）

```
/intraday SplitLayout:
  左列表: 候选池（来自 /screener preset 或 currentStock.browsed）
  右详情: 个股预览（K线 + 五档 + OFI）
  OFI 数据源: S176 ofi_snapshots（scheduler */3 9-14 已采）
  若 ofi_snapshots 当日无数据 → HonestEmptyState（grill #6）
  告警流: GET /api/alerts（涨停封板/炸板/异动）
  教练: GET /api/intraday-coach（S175 follow-order 推荐）
```

---

## 5. verdict per-type 渲染分发（grill #15）

```typescript
// VerdictRenderer.tsx
type VerdictType = 'selection' | 'event' | 'long_value';
// selection (S168): {lift, n_picks, days_robust, falsified|exploratory|underpowered}
// event (S169): {t_stat, p_value, window, drift_direction, edge_thickness}
// long_value (S171): {verdict_status: 'spec_done_R3_shared'|'pending_R2', pe_ratio, margin_of_safety}

function VerdictRenderer({ verdict }: { verdict: Verdict }) {
  switch (verdict.type) {
    case 'selection': return <SelectionVerdictCard {...verdict} />;
    case 'event': return <EventVerdictCard {...verdict} />;
    case 'long_value': return <LongValueVerdictCard {...verdict} />;
  }
}
```

每个 type 独立组件，字段不同不共享 schema，避免强拟合。

---

## 6. 风险技术缓解

| grill# | 风险 | 技术缓解 |
|---|---|---|
| #8 密度过载 | default-collapse：L1 手风琴单组展开 + L3 右侧面板默认收起 + SplitLayout 左列默认 340px 可拖 |
| #9 跨切改动 | Phase 0 基建先行 + 每 Phase 结束跑全量 `tsc --noEmit` + `vitest run` |
| #10 FirstBoardPipeline 1126行 | Phase 3 用 codegraph CLI 摸依赖树 → TDD 拆（先写测试锁定行为 → 拆模块 → 测试仍绿）|
| #11 treemap 5000 | ECharts large 模式 + 聚合 30 板块（不渲染 5000 叶子，hover 才展开）|
| #13 /stock/:code 无 code | currentStock.browsed fallback → 若空显示"请先从选股器或命令面板选股"EmptyState |