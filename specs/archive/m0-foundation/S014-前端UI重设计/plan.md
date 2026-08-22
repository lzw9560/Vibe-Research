# Plan: S014 — 前端 UI 重设计技术方案

> 对应 `spec.md`。细化 5 组导航、首页骨架、WorkflowStage、三态组件、移动端、视觉、useChatStream。

## 1. 5 组导航（navigation.ts 重构）

```typescript
export const NAV_GROUPS = [
  { id: "overview", name: "市场总览", items: ["/daily-review","/sentiment/weather","/radar","/sectors","/industries"] },
  { id: "stock", name: "个股研究", items: ["/stock-data","/stock/:code","/watchlist","/notes"] },
  { id: "trade", name: "交易工作台", items: ["/candidates","/workflow","/recommendation","/strategy-signals","/risk-dashboard","/backtest","/sector-divergence"] },
  { id: "portfolio", name: "投资管理", items: ["/portfolio","/my-reports","/value-funnel"] },
  { id: "system", name: "系统", items: ["/settings","/health","/scheduled-tasks"] },
];
```
- 侧栏默认只露组标题 + 当前组展开；`SUB_TABS` 落地（Layout 级二级 Tab）
- `Layout.tsx` 拆 `<Sidebar>`/`<MobileHeader>`/`<MobileTabBar>`/`<Backdrop>` 子组件；NAV 配置外移

## 2. 首页骨架（DailyReview 28→~8 state）

```
<PageHeader title="每日复盘" actions={[<AskAiButton/>, <RefreshBtn/>]}/>
<IndexRow/> <GlobalRow/> <StOneLiner/>          // 概览层
<WatchlistGrid/>                                  // 自选速览
<AiReviewPanel stream={useChatStream(...)}/>      // 唯一 AI 入口
<SunkenLinks tabs={["情绪详情","板块资金","复盘报告"]}/>
```
- 情绪/板块资金/复盘报告下沉子页或 Tab

## 3. WorkflowStage 骨架

```typescript
<WorkflowStage
  stage="pre|intraday|post"
  header={<StageHeader status signalsCount lastUpdate/>}
  filters={<FilterBar .../>}
  table={<DataTable sortable .../>}
  aiPanel={<AiInsight stage/>}
  notImplemented={stage!=="pre"}  // S012 标灰
/>
```
- 三页只填数据契约，骨架共享；1651→骨架~300+配置

## 4. 三态组件

- `PageSkeleton`（按区块形状 shimmer）、`EmptyState`、`ErrorRetry`（AlertCircle+重试）
- `DataTable`（三态+排序+onRowClick）、`FilterBar`（搜索+pill+排序）
- `pctColor()` 统一涨跌色；hover `muted/30`

## 5. 移动端

- 侧栏 `hidden md:flex`；汉堡→全屏抽屉分组折叠
- 底部 5 项 Tab：首页/自选/工作台/持仓/更多
- 修 `mobileMenuOpen` 只锁滚动不展开 → 接真实抽屉

## 6. 视觉系统

- `index.css` 补 `--space-1..8`、`--text-xs..2xl` 令牌
- `STITimelineChart` echarts 消费 `--chart-*` token + `useTheme` 监听
- `Badge` warning 用 `--warning`；`Button` 加 `primary-solid` 实心变体
- 暖橙入口在 Settings（三主题切换）

## 7. useChatStream

```typescript
export const useChatStream = () => {
  const [msgs, setMsgs] = useState<Msg[]>(loadHistory());
  const stream = useCallback((q) => { chatStream({ onDelta: patchLast(msgs,q), onTool, onDone: saveHistory }); }, []);
  return { msgs, stream, abort };
};
```
- 增量渲染：按段 patch（不全量 ReactMarkdown re-parse）+ 打字机光标
- 历史 localStorage 持久化；AskAi 升顶栏全局入口；遮罩 backdrop-blur

## 8. 情绪气象站补 P0
- WeatherHero：dataFreshness + STI gauge（echarts gauge 非 CSS div）+ aria-live
- Layout 级二级 Tab（替页内 useLocation）；实现或删占位 Tab

## 9. 实现步骤
1. navigation.ts 5 组 + Layout 拆分
2. 三态+DataTable+FilterBar 组件
3. 首页骨架 + 下沉
4. WorkflowStage + 三页迁移
5. 移动端重做
6. 视觉令牌 + echarts 跟主题 + 暖橙入口
7. useChatStream + AskAi 全局
8. 情绪气象站 P0
9. `npm run build` + vitest 快照

## 10. 风险点
- 11 巨型 page 拆分量大 → 分批 + vitest 快照锁
- echarts 跟主题重写配置 → 暗色基线快照比对
- 首页下沉改习惯 → 下沉链接可达
