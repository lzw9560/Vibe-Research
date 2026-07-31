# Tasks: S014 — 前端 UI 重设计

> 依赖 `../S013`（hooks/client，已 ✅ 全任务完成，T21 unblocked）。
> 状态更新 2026-07-31：① §7 合规对齐弱合规 2026-07-30；② 重排为分阶段（基建先行）；③ 修正依赖图（page 拆分依赖 T5/T6/T7 非 T4）；④ T25 由最终任务转为每 Phase 出口 gate；⑤ 加视觉回归（vitest 快照 + 浏览器 MCP 截图）；⑥ T1 解耦为低风险配置可前置。

## 评估对照表（2026-07-31 实测，基于真代码非二手数）

| R | spec 描述 | 实际代码状态（实测） | 落地率 |
|---|---|---|---|
| R1 导航 5 组 | 22 项扁平→5 组 | `navigation.ts:1-106` 有 `NavGroup`/`NavTab` 接口、`THEMES`(3 含暖橙)、`SUB_TABS`(13 组)，**无 `NAV_GROUPS` 5 组常量**；`Layout.tsx` 未消费 `SUB_TABS`——死代码；`SECTOR_LINKS` 内联硬编码 | 0% |
| R2 首页拆分 | DailyReview 28→~8 state | `DailyReview.tsx` **749 行**；`useState` **12 处**（非 28，已部分瘦身）；10 区块仍在单页 | ~15% |
| R3 巨型 page 拆 | 11 个 >400 行→<400 | 实测 **11 个 >400**：LimitUpStrategy 836、DailyReview 749、GeneScreener 585、StockDeep 584、PostMarketReview 562、IntradayMonitor 551、Workflow 513、PreMarketBriefing 494、BombAlertPanel 450、Settings 439、SectorDivergence 427 | 0% |
| R4 workflow 骨架 | 三页 1651→骨架~300 | 三页(494+551+562=1607)+Workflow 513+BombAlert 450=2117 行；各自独立 PageHeader/GlassCard/Skeleton/Badge 导入，骨架雷同 | 0% |
| R5 三态统一 | PageSkeleton/EmptyState/ErrorRetry | `State.tsx` ✅ 新建(180 行，含 LoadingState/EmptyState(re-export)/ErrorState/PageSkeleton)；`DataTable` 已含 loading+empty 三态(133 行)但**无排序**；Loader2/pending 散落 **18 文件**；`State.tsx` 内联 Loader2 为封装实现细节（可接受） | ~45% |
| R6 pctColor/hover | 统一 pctColor | `lib/utils.ts:9` `pctColor` 已存在，null-safe，红涨绿跌 A 股语义正确；已被 DailyReview/Industry/StockDeep 用；**实测仅 2 处真正涨跌百分比自定义**（PreMarketBriefing:374 美股绿涨bug、SectorDivergence:290）——其余 grep 命中是语义色(Health/RiskDashboard/Recommendation)或图表hex(T18 范畴)，pctColor 是错抽象 | ~85% |
| R7 移动端 | 侧栏 hidden+抽屉+5 项 Tab | `Layout.tsx:221-278` 移动端 24 项横滚 Tab（非 5 项）；`mobileMenuOpen` 只锁 body 滚动，无真实抽屉展开；侧栏 md 以下仍渲染 | 0% |
| R8 视觉系统 | echarts 跟主题+令牌 | `index.css` 有 `--chart-grid/text/axis` token(3 主题各 3 个)但**无 `--space-*`/`--text-*` 令牌**；`STITimelineChart.tsx:9-13` 硬编码 5 个 PHASE_LINE_COLOR 十六进制；:81-147 硬编码 8+ 处 `rgba(255,255,255,*)`/`rgba(20,20,25,*)` 不跟主题 | ~15% |
| R9 暖橙入口 | Settings 加切换入口 | `useDarkMode.ts`/`navigation.ts:27-31` `THEMES` 三选项含 warm-orange 已备；**Settings.tsx 无 warm-orange/useTheme 引用**——入口未落地 | 30%（主题逻辑有，入口无） |
| R10 情绪气象站 P0 | gauge/dataFreshness/aria/二级 Tab | `SentimentWeather.tsx` 328 行；`SUB_TABS:57-62` 已配 4 个 weather 子 tab 但 Layout 未消费；gauge/aria 待查 | ~20% |
| R11 AI 对话重做 | useChatStream+增量+全局入口 | `AskAiButton.tsx` 217 行；**无 useChatStream**（流式逻辑内联 :82-95）；onDelta 做了 `msg.content + t` 增量拼接但**每 delta 全量 ReactMarkdown re-parse**(:165)；无 localStorage 持久化；入口仅 7 页非顶栏常驻 | ~25% |
| R12 全局面包屑 | 不只 StockDeep | `Breadcrumbs.tsx`(35行)+`BreadcrumbContext.tsx`(16行) 已存在；仅 StockDeep+SectorDetail 2 页用 | ~30% |

## 审批机制（替代原「待审批」模糊 gate）

> 私人项目，用户即决策者。原 17 个「待审批」转为**可执行 checklist**：客观 gate 我（Claude）可自动核，品味/不可逆调用归用户。

- **自动 gate（我可自验）**：`npm run build` 绿 + `npx vitest run`绿 + spec 验收条对齐 + 拆分行数 <400 实测 + 浏览器 MCP（playwright/chrome-devtools）渲染截图比对 + 财务数据 `financial_rigor.py`/`report_audit.py` 验算。
- **升级用户（品味/不可逆）**：首页下沉改用户习惯(T8/T9)、暖橙入口位置(T20)、nav 5 组分组语义(T1)、占位 Tab 删 vs 实现(T23)、视觉接受度阈值（何为"可接受回归"）。
- 规则：客观 gate 全绿 + 我附截图与 diff → 我给「技术通过」结论；品味调用我给推荐 + 理由，用户拍板。

## 分阶段计划（基建先行，每 Phase 独立可合并、出口必绿）

### Phase 0 — 基建件（契约层，零/低回归）
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T4 | `ui/State.tsx` 三态统一 | — | LoadingState/EmptyState/ErrorState/PageSkeleton | ✅ 完成（2026-07-31） |
| T5 | `DataTable` 增强 `sortable` 列契约 | T4 | 已存在 133 行三态，加列级 sortable + 排序指示 | 未开始 |
| T6 | `ui/FilterBar` 新建（搜索+pill+排序trigger） | T4 | 组件不存在，纯新建 | 未开始 |
| T7 | `pctColor` 迁移（实测仅 2 处真涨跌百分比：PreMarketBriefing:374 修美股绿涨→A股红涨 bug、SectorDivergence:290；语义色/图表hex 不属此任务） | — | ✅ 完成（2 处迁移 + 1 bug 修复） |
| T17 | `index.css` 补 `--space-1..8`/`--text-xs..2xl` 令牌 | — | 令牌定义层，零迁移 | 未开始 |

> Phase 0 出口 gate：build 绿 + vitest(State/DataTable/FilterBar 单测) 绿。

### Phase 1 — 试点单页（验证契约全链路，**先于 mass 拆分**）
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T8 | `DailyReview.tsx` 首页骨架（12→~8 state）+ 接 State/DataTable/FilterBar/pctColor | T5,T6,T7 | 情绪/板块资金/复盘报告下沉 | 升级用户（首页习惯） |
| T9 | 下沉子页/Tab（情绪详情/板块资金/复盘报告） | T8 | 下沉链接可达 | 升级用户 |

> Phase 1 出口 gate：build + vitest 快照(DailyReview 重构后) + 浏览器 MCP 截图 vs 拆前对比。**此 Phase 验证契约可用，再进 Phase 3 mass 拆分。**

### Phase 2 — workflow 骨架
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T10 | `<WorkflowStage>` 骨架（含 notImplemented 分支，S012 标灰不补） | T5,T6 | 含 notImplemented | 未开始 |
| T11 | workflow 三页迁移骨架（Pre/Intraday/Post + Workflow + BombAlert） | T10 | 2117→骨架+配置 | 升级用户 |

### Phase 3 — 巨型 page 拆分（消费已验证契约）
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T12 | `LimitUpStrategy.tsx`(836) 拆 → `limitup/components/` | T5,T6,T7 | <400 行 | 升级用户 |
| T13 | `GeneScreener.tsx`(585) 拆 | T5,T6,T7 | <400 行 | 升级用户 |
| T14 | `StockDeep.tsx`(584) 拆 | T5,T6,T7 | <400 行 | 升级用户 |
| T15 | 其余巨型 page 拆（PostMarketReview/IntradayMonitor/Workflow/SectorDivergence/Settings/BombAlertPanel/PreMarketBriefing，部分已在 Phase 2 消化） | T5,T6,T7 | 均 <400 行 | 升级用户 |

> 拆分点建议见下表。每批 vitest 快照锁行为，逐页提交。

### Phase 4 — 壳层（nav/Layout/移动端）
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T1 | `navigation.ts` 建 `NAV_GROUPS` 5 组（低风险配置，**可前置到 Phase 0 后**） | — | 22 项→5 组 | 升级用户（分组语义） |
| T2 | `Layout.tsx` 拆 `<Sidebar>`/`<MobileHeader>`/`<MobileTabBar>`/`<Backdrop>` | T1 | Layout <100 行 | 升级用户 |
| T16 | 移动端：侧栏 `hidden md:flex` + 全屏抽屉 + 5 项 Tab | T2 | mobileMenuOpen 接真实抽屉 | 升级用户 |
| T3 | `SUB_TABS` 落地（Layout 级二级 Tab，非死代码） | T1,T2 | 13 组消费 | 未开始 |

### Phase 5 — 视觉系统
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T18 | `STITimelineChart` echarts 消费 `--chart-*` token + `useTheme` 监听 | T17 | 8+ 处硬编码 rgba 消除，切主题图表跟随 | 升级用户（视觉接受度） |
| T19 | `Badge` warning 用 `--warning`；`Button` 加 `primary-solid` | T17 | 令牌化 | 未开始 |
| T20 | Settings 加暖橙主题切换入口 | T17 | 三主题可切 | 升级用户（入口位置） |

### Phase 6 — AI 对话
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T21 | `useChatStream` hook（增量渲染 patch + localStorage 持久化） | S013✅ | 不全量 re-parse | 未开始 |
| T22 | `AskAiButton` 重做（顶栏全局入口 + backdrop-blur + 响应式窄屏全屏） | T21 | 顶栏常驻 | 升级用户 |

### Phase 7 — 情绪气象站 P0
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T23 | 补 P0：WeatherHero dataFreshness + STI gauge(echarts gauge 非 CSS div) + aria-live + Layout 二级 Tab；占位 Tab 实现或删 | T18 | 占位 Tab 实现/删 | 升级用户（删 vs 实现） |

### Phase 8 — 收尾
| ID | 任务 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T24 | 全局 `<Breadcrumbs>` 推广（组件已存在，仅 2 页用） | — | 不只 StockDeep | 未开始 |
| T25 | **连续 gate**：每 Phase 出口 `npm run build` + `npx vitest run` + 浏览器 MCP 截图比对；非最终任务 | 各 Phase | 每 Phase 必绿 | 阻塞（依赖前序） |

## 巨型 page 拆分建议（只评估拆分点，不实际拆）

| 文件 | 行数 | 拆分点建议 | 估拆后页行数 |
|---|---|---|---|
| `LimitUpStrategy.tsx` | 836 | 抽 `<LimitUpFilters>`(筛选区) + `<ZTPoolTable>`(涨停池表) + `<HighGeneTable>`(高基因表) + `<LimitUpAiPanel>`(AskAi 包装) → `pages/limitup/components/` | ~250 |
| `DailyReview.tsx` | 749 | 抽 `<IndexGlobalRow>` + `<WatchlistGrid>` + `<AiReviewPanel>` + `<SunkenReviewTabs>` → 配合 T8 下沉 | ~200 |
| `GeneScreener.tsx` | 585 | 抽 `<GeneFilterForm>` + `<GeneResultTable>` + `<GeneDetailDrawer>` | ~180 |
| `StockDeep.tsx` | 584 | 抽 `<StockHeader>` + `<GeneTab>` + `<CapitalTab>` + `<AiTab>`（配合已有 Breadcrumbs） | ~200 |
| `PostMarketReview.tsx` | 562 | 配合 T10/T11 抽 `<WorkflowStage>` 骨架后剩余配置 | ~200 |
| `IntradayMonitor.tsx` | 551 | 同上，抽 `<WorkflowStage>` + `<SignalList>` + `<AlertList>` | ~200 |
| `Workflow.tsx` | 513 | 配合 T11 迁骨架 | ~150 |
| `PreMarketBriefing.tsx` | 494 | 配合 T10/T11 抽 `<WorkflowStage>` + `<SentimentSummary>` | ~200 |
| `BombAlertPanel.tsx` | 450 | 配合 T11 抽 `<WorkflowStage>` + `<AlertTable>` | ~180 |
| `Settings.tsx` | 439 | 抽 `<LlmConfigSection>` + `<ThemeSwitcher>`(T20 暖橙入口落此) + `<ApiTokenSection>` | ~200 |
| `SectorDivergence.tsx` | 427 | 抽 `<DivergenceChart>` + `<RotationChart>` + `<DivergenceTable>` | ~180 |

## 依赖图（修正版）
```
Phase 0: T4✅ → T5,T6 ; T7,T17 独立
Phase 1: T5,T6,T7 → T8 → T9          （试点单页，验证契约）
Phase 2: T5,T6 → T10 → T11
Phase 3: T5,T6,T7 → T12,T13,T14,T15  （page 拆分依赖基建件，非 T4）
Phase 4: T1(独立,可前置) → T2 → T16 ; T2 → T3
Phase 5: T17 → T18,T19,T20
Phase 6: S013✅ → T21 → T22
Phase 7: T18 → T23
Phase 8: T24 独立；T25 = 每 Phase 出口 gate（连续）
```

> **关键修正**：原依赖图 `T4 ─ T12-T15` 让 page 拆分绕过 T5/T6/T7，会使 11 个拆分后 page 各自手写排序/筛选/涨跌色。现改为 `T5,T6,T7 ─ T12-T15`，拆分时直接消费已验证契约。

## 合规检查点（弱合规 2026-07-30）
- 判断卡片挂轻量风险提醒「历史统计特征，市场有风险」（非强制免责墙）
- 涨停四池/连板股榜可如实呈现个股 code/name（公开榜单，不强制剥离）
- T23 设计文档"建议空仓/买入价"可如实呈现（用户即决策者），挂轻量提醒即可
- 工程底线：财务数据可复现验算 / 私有数据 VR_DATA_DIR 隔离 / 东财走 em_get

## 本轮完成项
- ✅ §7 合规对齐弱合规 2026-07-30（S014 + S006 + S017 + S010 补完 + S007 加注）
- ✅ T4 `ui/State.tsx`（零迁移零回归，tsc 通过）
- ✅ 现状评估对照表（12 个 R 全部基于真代码实测）
- ✅ 11 个巨型 page 拆分点建议清单
- ✅ 分阶段重排（基建先行）+ 依赖图修正（page 拆分依赖 T5/T6/T7）+ T25 转连续 gate + 审批 checklist 化
- ✅ **Phase 0 完成（2026-07-31，gate 全绿）**：
  - T5 `DataTable` 增强 `sortable` 受控契约（export `Column`/`SortState`/`DataTableProps`；aria-sort；9 单测）
  - T6 `ui/FilterBar.tsx` 新建（search/pills/sort/right 全受控；5 单测）
  - T7 `pctColor` 迁移实测仅 2 处（PreMarketBriefing:374 修美股绿涨→A股红涨 bug、SectorDivergence:290）；订正评估表"49 处"为臆造
  - T17 `index.css` 补 `--space-1..8`/`--text-xs..2xl` 令牌（theme-invariant，仅 :root）
  - gate：`npm run build` ✓（含迁移文件）/ `npx vitest run` 3 files 15 tests ✓
  - 视觉截图 gate 待 Phase 1（Phase 0 组件/令牌未接页，无可见页变化可比对）
