# Spec: S186 — 前端 UX 重构（62 路由精简 → 6 域 19 内容路由 + 死代码清理）

> 状态：草案
> 作者：Claude  日期：2026-09-11
> 关联：wgn6aqnjp 6 视角前端 UX 审查 / S179 trade-desk cockpit / S173 TradeJournal / S175 模拟盘 / S013 前端数据层 / memory page-architecture-redesign

## 1. 问题 / 目标

用户反馈：前端页面交互分散，部分标签页导航语义相近和重复。需深度分析 + 优秀实践对标 + 调整优化，有必要推到重建。

一句话：**partial-rebuild**——router.tsx + navigation.ts 配置层重写为 6 域 19 内容路由 + ~20 兼容 redirect，保留 S173/S175/S179 已落地的 ~7000 行工作页面代码，删除 ~2000 行死代码+死路由。核心病因是 S179 Phase 3 路由收敛标记 done 但从未执行，新旧两套入口并存。

## 2. 背景

wgn6aqnjp 6 视角审查发现：
- **62 路由 + 91 页面组件 + 7 导航组**——分散重复
- **CRITICAL**：/review 双重（交易台+复盘组）/ /daily-review redirect 误导 / 11 孤儿路由（/intraday 不可达最严重）/ Advisory+Recommendation 重叠 / LimitUp 5 子 tab 冗余
- **HIGH**：个股组名不符（6 tab 无 /stock/:code）/ Candidates vs ValueFunnel 重叠 / §44 验证 vs 价值因子验证重叠 / §44+OFI label 内部术语 / 研究中心仅 2 tab 不足以独立成组
- **优秀实践对标**：Bloomberg 命令驱动 + TradingView 图表中心 + 雪球组合中心 + linear.app 极简导航

## 3. 需求清单

### R1：6 域信息架构（navigation.ts 重写）

| 域 | 路由 | rationale |
|---|---|---|
| 看盘（盘中盯盘） | /market + /intraday + /sentiment + /sectors/:key | 用户盘中一切入口。/market 吸收 intel+sectors+divergence+prediction+debate 为页内 tab |
| 选股（买什么） | /screener + /watchlist + /limitup | 候选池非信号（§44 证否 selection edge）。/screener 吸收 candidates+value-funnel 为 preset |
| 个股（标的中心） | /stock/:code + /stock-data | Bloomberg 范式——个股页是单点聚合中心，侧边栏不列 |
| 模拟盘（统一闭环） | /journal + /portfolio + /advisory + /multiline | S175 统一 paper-trading 框架一域聚合 |
| 复盘策略（事后+验证） | /review + /strategy | 复盘+验证一域。/review 吸收 my-reports+notes+behavior-loop |
| 系统 | /settings + /scheduled-tasks + /health + /metrics | 系统管理不动 |

- [ ] R1.1 navigation.ts 重写为 6 域 19 tab（41→19 减 54%）
- [ ] R1.2 /intraday 加入交易台组（最严重可达性 bug 修复）
- [ ] R1.3 删交易台 /review 重复项（保留复盘组）
- [ ] R1.4 删 /daily-review tab（redirect→/market 不该在侧边栏）
- [ ] R1.5 删 /limitup/gene + /auction + /seats 三个子 tab（页内 TabBar 替代）
- [ ] R1.6 删 /my-reports + /notes + /behavior-loop 独立 tab（/review 页内 tab）
- [ ] R1.7 重命名 label：§44 验证→策略验证，OFI 看板→资金流看板
- [ ] R1.8 个股组重命名（6 tab 无 /stock/:code，改名"量化策略"或合入复盘）

### R2：路由精简（router.tsx 重写，62→19 内容路由 + ~20 redirect）

- [ ] R2.1 redirect /daily-review → /market（4 子路由全 redirect）
- [ ] R2.2 redirect /intel /sectors /sector-divergence /prediction /debate → /market?tab=
- [ ] R2.3 redirect /candidates /value-funnel → /screener?preset=
- [ ] R2.4 redirect /behavior-loop /my-reports /notes → /review?tab=
- [ ] R2.5 redirect /recommendation → /advisory
- [ ] R2.6 redirect /risk-dashboard → /portfolio?tab=risk
- [ ] R2.7 redirect /strategy-signals /backtest /verifier-records /value-verdict → /strategy?tab=
- [ ] R2.8 redirect /workflow/intraday /workflow/coach /workflow/alerts → /intraday?tab=
- [ ] R2.9 redirect /workflow/intraday/ofi → /intraday?tab=ofi
- [ ] R2.10 redirect /workflow/post-market /workflow/topology → /review?tab=
- [ ] R2.11 redirect /workflow/first-board /workflow/pre-market → /screener?preset= + /intraday?tab=
- [ ] R2.12 redirect /workflow/candidates/:code /workflow/factor/:factorId → /stock/:code?tab=
- [ ] R2.13 redirect /strategy/funnel/forward-test /strategy/funnel/config → /strategy?tab=
- [ ] R2.14 redirect /sentiment/weather/history /strategy /fuse → /sentiment?tab=
- [ ] R2.15 DELETE /workflow/selection 路由 + SelectionStageView 组件

### R3：死代码清理（~2000 行）

- [ ] R3.1 DELETE pages/Advisory.tsx（195 行，grep 确认零 import）
- [ ] R3.2 DELETE pages/Portfolio.tsx（295 行，已迁 PortfolioPage）
- [ ] R3.3 DELETE 6 个零引用 workflow 组件：CandidateProgressiveCard(231)+SectorCyclePanel(82)+StrategyGroupTabs(77)+T1Tab(63)+TaskStatusCard(274)+StrategyMatchMatrix(163) = ~890 行
- [ ] R3.4 DELETE components/layout/CockpitLayout.tsx（零引用）
- [ ] R3.5 Layout.tsx 3 处品牌链接 /daily-review → /market（line 53/170/189）

### R4：验证

- [ ] R4.1 tsc0（类型检查通过）
- [ ] R4.2 vitest 全绿（~450 测试无回归）
- [ ] R4.3 所有 redirect 路由可达（不 404）
- [ ] R4.4 /intraday 从侧边栏可达
- [ ] R4.5 命令面板 Cmd+K 覆盖 19 路由

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| frontend/src/router.tsx | 62→19 内容路由 + ~20 redirect（配置层重写） |
| frontend/src/components/layout/navigation.ts | 7 组 41 tab → 6 域 19 tab |
| frontend/src/components/layout/Layout.tsx | 品牌链接 /daily-review→/market（3 处） |
| pages/Advisory.tsx | DELETE（195 行死代码） |
| pages/Portfolio.tsx | DELETE（295 行死代码） |
| components/workflow/ 6 组件 | DELETE（~890 行死代码） |
| components/layout/CockpitLayout.tsx | DELETE |
| pages/workflow/SelectionStageView.tsx | DELETE（死路由组件） |

## 5. 设计方案

### 5.1 partial-rebuild（非 full-rebuild 非 incremental）

wgn6aqnjp verdict: **partial-rebuild**——配置层（router.tsx + navigation.ts）大爆炸重写，保留 ~7000 行工作页面代码（S173/S175/S179 已落地），删 ~2000 行死代码。

理由：S179 Phase 3 路由收敛标记 done 但从未执行 → 新旧两套入口并存。不是增量重构（死路由太多），不是全推重建（7000 行工作页面保留）。

### 5.2 6 域信息架构

对标 professional 平台（Bloomberg/TradingView/linear.app）：
- 命令面板（Cmd+K）主入口 → 减少导航点击
- 标的页 cockpit（/stock/:code）聚合中心 → 侧边栏不列
- 模拟盘中心（/journal）聚合多臂+曲线+portfolio
- 6 域 ≤ professional 平台 10-15 主路由

### 5.3 redirect 策略

旧路由全 redirect（非 DELETE）保兼容：
- 外部链接（飞书/书签）不 404
- Phase 3 灰度迁移——先 redirect 再删
- redirect 用 `<Navigate to="..." replace />`（router.tsx 已有范式）

### 5.4 页内 TabBar 替代子路由

- /limitup?tab=gene|auction|seats|premarket（替代 4 子路由）
- /sentiment?tab=weather|history|strategy|fuse（替代 4 子路由）
- /market?tab=intel|sectors|divergence|prediction|debate（吸收 5 散页）
- /review?tab=behavior|reports|notes|post|topology（吸收 5 散页）

## 6. 验收标准

- [ ] A1：router.tsx 19 内容路由 + ~20 redirect（62→19 减 66%）
- [ ] A2：navigation.ts 6 域 19 tab（41→19 减 54%）
- [ ] A3：~2000 行死代码删除（Advisory+Portfolio+6 workflow 组件+CockpitLayout+SelectionStageView）
- [ ] A4：/intraday 从侧边栏可达（最严重 bug 修复）
- [ ] A5：tsc0 + vitest 全绿
- [ ] A6：所有 redirect 路由可达（curl 200 非 404）

## 7. 合规与工程底线自查

- [x] 不臆造：基于 wgn6aqnjp 6 视角审查 + 代码实读
- [x] 保留工作页面：S173/S175/S179 ~7000 行不删
- [x] redirect 保兼容：旧路由不 DELETE 保外部链接
- [x] 私有数据不涉：纯前端路由配置

## 8. 测试计划

- tsc --noEmit（类型检查）
- vitest run（~450 测试全绿）
- curl/agent-browser 验证 redirect 路由 200
- /intraday 从侧边栏可达
- Cmd+K 命令面板覆盖 19 路由

## 9. 迁移路径

Phase 1（immediate_actions，零风险）：
1. 删死文件 Advisory.tsx + Portfolio.tsx + 6 workflow 组件 + CockpitLayout（~1380 行）
2. 删 /workflow/selection 死路由
3. navigation.ts 删 /review 重复 + /daily-review tab + /limitup 子 tab + /my-reports+/notes+/behavior-loop
4. Layout.tsx 品牌链接修正
5. /intraday 加入交易台
6. label 重命名

Phase 2（redirect 路由）：
7. router.tsx 加 ~20 redirect 路由
8. 页内 TabBar 替代子路由（?tab=）

Phase 3（死路由 DELETE）：
9. 确认 redirect 无 404 后 DELETE 旧路由
10. 最终 19 内容路由 + 0 redirect（或保留兼容 redirect）
