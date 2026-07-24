# Vibe-Research 前后端 API 对照文档

> 生成时间：2026-07-24（Vibe-Research v0.1.3，含 workflow/sentiment_weather/scheduled_tasks 新增端点）
> 前端：`frontend/src/lib/api.ts` + Pages/Components
> 后端：`backend/routers/*.py`，FastAPI v0.1.3，运行于 `localhost:8900`

---

## 目录

1. [架构概览](#1-架构概览)
2. [前端 API 客户端总览](#2-前端-api-客户端总览)
3. [后端端点完整清单](#3-后端端点完整清单)
4. [前后端对照表](#4-前后端对照表)
5. [前端页面 API 调用分布](#5-前端页面-api-调用分布)
6. [未使用/预留端点](#6-未使用预留端点)
7. [新增端点说明](#7-新增端点说明)
8. [统计总结](#8-统计总结)

---

## 1. 架构概览

| 项目 | 说明 |
|------|------|
| **前端框架** | React + TypeScript + Vite |
| **后端框架** | FastAPI (Python) |
| **代理配置** | Vite proxy: `/api/*` → `http://127.0.0.1:8900` |
| **认证方式** | 可选 Bearer Token（`VR_API_KEY`），存储在 `localStorage` 的 `vr-access-key` |
| **响应格式** | `{ "data": ... }` 或 `{ "detail": "..." }` |
| **前端数据获取** | 手动 `fetch()` + 类型化 `get<T>()` / `request<T>()` 辅助函数 |

---

## 2. 前端 API 客户端总览

**主文件**：`frontend/src/lib/api.ts`（710 行）

### 2.1 核心辅助函数

```typescript
// GET 请求
get<T>(url: string): Promise<T>

// POST/DELETE 请求
request<T>(url: string, method: "POST" | "DELETE", body?: any): Promise<T>

// 认证头
authHeaders(): Record<string, string>
```

### 2.2 前端 API 方法分类

| 分类 | 方法数 | 示例 |
|------|--------|------|
| 系统/健康 | 2 | `health()`, `getLlmEnvStatus()` |
| AI 对话 | 1 | `chatStream()` |
| 自选股 | 3 | `watchlist()`, `addToWatchlist()`, `removeFromWatchlist()` |
| 持仓管理 | 6 | `portfolio()`, `addHolding()`, `removeHolding()`, `closePosition()`, `removeClosed()`, `refreshPortfolio()` |
| 研报管理 | 4 | `myReports()`, `uploadReport()`, `reportFile()`, `deleteReport()` |
| 资讯雷达 | 2 | `radar()`, `radarRefresh()` |
| 市场行情 | 7 | `marketOverview()`, `emotion()`, `turnoverTop()`, `stiLatest()`, `stiTimeline()`, `globalIndices()`, `globalStock()` |
| 个股数据 | 11 | `quote()`, `valuation()`, `valuationPercentile()`, `financials()`, `reports()`, `news()`, `info()`, `disclosure()`, `kline()`, `finance()`, `stockDeep()` |
| 财务数据 | 10 | `margin()`, `blockTrade()`, `holders()`, `dividend()`, `fundFlow()`, `dragonTiger()`, `lockup()`, `blocks()`, `hotConcepts()`, `investorQa()`, `industry()` |
| 打板策略 | 15 | `limitupScreener()`, `limitupAnalysis()`, `limitupMetrics()`, `auctionTop()`, `auctionBackfill()`, `seatProfiles()`, `seatProfile()`, `seatConsensus()`, `seatBuildProfiles()` |
| 每日复盘 | 4 | `dailyReview()`, `dailyReviewBackfill()`, `getReviewParams()`, `saveReviewParams()` |
| 推荐引擎 | 2 | `recommendationToday()`, `recommendationStock()` |
| 胜率追踪 | 6 | `winRateStats()`, `winRateAdjustments()`, `winRateTrends()`, `winRateSector()`, `winRateStrategy()`, `winRateRecords()` |
| 回测 | 2 | `backtestScatter()`, `backtestResult()` |
| 竞价监控 | 2 | `auctionMonitor()`, `auctionWatchlist()` |
| 战法信号 | 2 | `strategySignals()`, `strategyRegistry()` |
| 风险仪表盘 | 4 | `riskDashboard()`, `riskStock()`, `riskOnedayList()`, `riskSeats()` |
| 板块分化 | 3 | `sectorDivergence()`, `sectorRotation()`, `sectorDivergenceHistory()` |
| 性能监控 | 4 | `metricsDataFetch()`, `metricsCompute()`, `metricsApiResponse()`, `metricsBreakdown()` |
| 飞书推送 | 3 | `pushTest()`, `pushDailyReview()`, `pushRecommendation()` |
| **工作流** | **14** | `workflowStatus()`, `preMarket()`, `runPreMarket()`, `realtime()`, `postMarket()`, `refresh()`, `signals()`, `alerts()`, `settle()`, `strategies()`, `matchStrategy()`, `winRate()`, `adjustments()` |
| **情绪气象站** | **15** | `weatherLatest()`, `weatherFactors()`, `weatherStrategy()`, `weatherFuse()`, `weatherTimeline()`, `weatherEvents()`, `weatherAuction()`, `weatherSealRisk()`, `weatherPardon()`, `togglePardon()`, `revokePardon()`, `submitPardonOutcome()`, `fuseHistory()`, `updateFuse()`, `refreshWeather()` |
| **定时任务** | **8** | `listTasks()`, `getTask()`, `createTask()`, `updateTask()`, `deleteTask()`, `runTask()`, `listRuns()`, `listTaskTypes()` |

**总计：约 82 个前端 API 方法**

---

## 3. 后端端点完整清单

### 3.1 系统/健康

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/health` | `routers/health.py:150` | 系统健康检查（DB/熔断器/调度器/缓存） |
| GET | `/api/settings/llm-env-status` | `routers/chat.py:29` | LLM 环境变量配置状态 |

### 3.2 AI 对话

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| POST | `/api/chat` | `routers/chat.py:40` | 流式 AI 对话（NDJSON SSE） |

### 3.3 自选股

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/watchlist` | `routers/watchlist.py:38` | 获取自选股列表 |
| POST | `/api/watchlist` | `routers/watchlist.py:55` | 批量添加自选股 |
| DELETE | `/api/watchlist/{code}` | `routers/watchlist.py:83` | 删除自选股 |

### 3.4 持仓管理

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/portfolio` | `routers/portfolio.py:27` | 持仓 + 实时盈亏 |
| POST | `/api/portfolio/holding` | `routers/portfolio.py:36` | 添加持仓 |
| DELETE | `/api/portfolio/holding` | `routers/portfolio.py:48` | 移除持仓 (?code=) |
| POST | `/api/portfolio/close` | `routers/portfolio.py:53` | 记录已清仓 |
| DELETE | `/api/portfolio/close` | `routers/portfolio.py:73` | 删除已清仓记录 (?index=) |
| POST | `/api/portfolio/refresh` | `routers/portfolio.py:78` | 手动刷新行情 |

### 3.5 研报管理

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/myreports` | `routers/myreports.py:19` | 列出所有研报 |
| POST | `/api/myreports` | `routers/myreports.py:24` | 上传研报（base64） |
| GET | `/api/myreports/file/{rid}` | `routers/myreports.py:33` | 下载/预览研报原文件 |
| DELETE | `/api/myreports/{rid}` | `routers/myreports.py:43` | 删除研报 |

### 3.6 资讯雷达

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/radar` | `routers/radar.py:12` | 12 赛道 RSS 新闻雷达 |
| POST | `/api/radar/refresh` | `routers/radar.py:21` | 强制重抓全部 RSS 源 |

### 3.7 市场行情

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/market/overview` | `routers/market.py:13` | 市场情绪 + 板块资金流 |
| GET | `/api/market/emotion` | `routers/market.py:22` | 短线情绪（连板梯队/炸板率/封板率） |
| GET | `/api/market/turnover-top` | `routers/market.py:35` | 全市场成交额榜 Top20 |
| GET | `/api/market/extreme` | `routers/extreme_market.py:12` | 极端行情信号 |
| GET | `/api/global/indices` | `routers/market.py:44` | 全球指数快照（道指/标普500/纳斯达克/恒生） |
| GET | `/api/global/stock` | `routers/market.py:53` | 美股/港股个股聚合（?symbol=） |

### 3.8 个股数据

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/indices` | `routers/stock_data.py:32` | A股大盘指数实时行情 |
| GET | `/api/quote` | `routers/stock_data.py:41` | 实时行情（?codes=，逗号分隔） |
| GET | `/api/valuation` | `routers/stock_data.py:105` | 完整估值（行情+一致预期+PEG） |
| GET | `/api/valuation/percentile` | `routers/stock_data.py:53` | PE/PB 历史分位（近5年） |
| GET | `/api/financials` | `routers/stock_data.py:87` | 财务关键指标 |
| GET | `/api/reports` | `routers/stock_data.py:118` | 个股研报列表（?pages=） |
| GET | `/api/news` | `routers/stock_data.py:132` | 个股新闻（?limit=） |
| GET | `/api/info` | `routers/stock_data.py:145` | 个股基本面（行业/股本/上市时间） |
| GET | `/api/disclosure` | `routers/stock_data.py:158` | 巨潮公告列表 |
| GET | `/api/kline` | `routers/stock_data.py:171` | K线数据（?category=&offset=） |
| GET | `/api/finance` | `routers/stock_data.py:184` | 季报财务快照 |
| **GET** | **`/api/stock/{code}/deep`** | **`routers/stock_data.py:198`** | **个股深度数据聚合（新增）** |

### 3.9 财务数据

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/margin` | `routers/stock_financial.py:29` | 融资融券明细 |
| GET | `/api/block-trade` | `routers/stock_financial.py:40` | 大宗交易 |
| GET | `/api/holders` | `routers/stock_financial.py:51` | 股东户数变化 |
| GET | `/api/dividend` | `routers/stock_financial.py:62` | 分红送转历史 |
| GET | `/api/fund-flow` | `routers/stock_financial.py:73` | 个股资金流（120日主力净流入） |
| GET | `/api/dragon-tiger` | `routers/stock_financial.py:85` | 龙虎榜（上榜记录+买卖席位+机构净买） |
| GET | `/api/lockup` | `routers/stock_financial.py:96` | 限售解禁日历 |
| GET | `/api/blocks` | `routers/stock_financial.py:107` | 个股所属板块/概念归属 |
| GET | `/api/hot-concepts` | `routers/stock_financial.py:118` | 热门概念命中 |
| GET | `/api/investor-qa` | `routers/stock_financial.py:129` | 互动易问答 |
| GET | `/api/industry` | `routers/stock_financial.py:140` | 全行业涨跌幅排名 |

### 3.10 STI 情绪指数

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/market/sti/latest` | `routers/sti.py:13` | STI 情绪温度指数（八维明细） |
| GET | `/api/market/sti/timeline` | `routers/sti.py:56` | STI 时间线趋势图 |

### 3.11 板块分析

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/sector/divergence` | `routers/sector_divergence.py:12` | 板块情绪分化度 |
| GET | `/api/sector/divergence/history` | `routers/sector_divergence.py:24` | 板块分化度历史趋势 |
| GET | `/api/sector/rotation` | `routers/sector_divergence.py:34` | 板块轮动速度 |

### 3.12 风险管理

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/risk/dashboard` | `routers/risk.py:12` | 风险仪表盘 |
| GET | `/api/risk/oneday/list` | `routers/risk.py:81` | 高风险个股列表 |
| GET | `/api/risk/seats` | `routers/risk.py:118` | 一日游特征席位库 |
| GET | `/api/risk/stock/{code}` | `routers/risk.py:134` | 个股风险详情 |

### 3.13 飞书推送

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| POST | `/api/push/test` | `routers/feishu.py:12` | 测试飞书推送连接 |
| POST | `/api/push/daily-review` | `routers/feishu.py:20` | 推送每日复盘卡片 |
| POST | `/api/push/recommendation` | `routers/feishu.py:28` | 推送推荐关注卡片 |

### 3.14 胜率追踪

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/winrate/stats` | `routers/win_rate.py:18` | 胜率统计（含 Sharpe/回撤/板块/战法拆分） |
| GET | `/api/winrate/adjustments` | `routers/win_rate.py:43` | 策略调整建议 |
| GET | `/api/winrate/trends` | `routers/win_rate.py:55` | 胜率趋势图数据 |
| GET | `/api/winrate/sector/{sector}` | `routers/win_rate.py:66` | 板块胜率拆分 |
| GET | `/api/winrate/strategy/{strategy}` | `routers/win_rate.py:79` | 战法胜率拆分 |
| POST | `/api/winrate/records` | `routers/win_rate.py:92` | 批量录入交易记录 |

### 3.15 回测

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/backtest/scatter` | `routers/backtest.py:12` | 回测散点数据（基因得分 vs 实际收益） |
| GET | `/api/backtest/result` | `routers/backtest.py:25` | 回测结果汇总 |

### 3.16 竞价监控

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/auction/monitor` | `routers/bidding.py:12` | 候选池竞价监控（9:25 最终确认信号） |
| GET | `/api/auction/watchlist` | `routers/bidding.py:37` | 竞价监控候选池 |

### 3.17 推荐引擎

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/recommendation/today` | `routers/recommendation.py:12` | 今日推荐清单 |
| GET | `/api/recommendation/{code}` | `routers/recommendation.py:35` | 个股推荐详情 |

### 3.18 战法信号

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/strategy/signals/{code}` | `routers/strategy.py:12` | 个股战法匹配信号 |
| GET | `/api/strategy/registry` | `routers/strategy.py:52` | 战法库定义 |

### 3.19 每日复盘

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/review/daily` | `routers/review.py:40` | 每日复盘报告 |
| GET | `/api/review/daily/backfill` | `routers/review.py:58` | 复盘报告历史回填 |
| GET | `/api/review/params` | `routers/review.py:79` | 复盘报告参数 |
| POST | `/api/review/params` | `routers/review.py:90` | 保存复盘报告参数 |

### 3.20 性能监控

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/metrics/data_fetch` | `routers/metrics.py:55` | 数据获取层耗时指标 |
| GET | `/api/metrics/compute` | `routers/metrics.py:68` | 计算层耗时指标 |
| GET | `/api/metrics/api_response` | `routers/metrics.py:81` | API 响应耗时指标 |
| GET | `/api/metrics/breakdown` | `routers/metrics.py:94` | 三层性能拆分详情 |

### 3.21 打板策略

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/limitup/screener` | `routers/limitup/screener.py:20` | 全市场涨停股基因得分 |
| GET | `/api/limitup/screener/params` | `routers/limitup/screener.py:30` | 打板策略参数 |
| POST | `/api/limitup/screener/params` | `routers/limitup/screener.py:36` | 保存打板策略参数 |
| POST | `/api/limitup/screener/trigger` | `routers/limitup/screener.py:48` | 手动触发基因得分预计算 |
| GET | `/api/limitup/analysis/{code}` | `routers/limitup/analysis.py:14` | 个股基因得分+策略逻辑匹配+风控规则 |
| GET | `/api/limitup/metrics` | `routers/limitup/metrics.py:20` | 涨停策略聚合指标 |
| GET | `/api/limitup/auction/top` | `routers/limitup/auction.py:16` | 竞价爆量 TOP N 候选股 |
| GET | `/api/limitup/auction/backfill` | `routers/limitup/auction.py:37` | 竞价选股历史回填 |
| GET | `/api/limitup/auction/params` | `routers/limitup/auction.py:77` | 竞价选股参数 |
| POST | `/api/limitup/auction/params` | `routers/limitup/auction.py:83` | 保存竞价选股参数 |
| GET | `/api/limitup/seats/profiles` | `routers/limitup/seats.py:11` | 所有席位画像 |
| GET | `/api/limitup/seats/profile/{seat_name}` | `routers/limitup/seats.py:25` | 单个席位画像 |
| GET | `/api/limitup/seats/consensus` | `routers/limitup/seats.py:41` | 席位共识/分歧信号 |
| POST | `/api/limitup/seats/build` | `routers/limitup/seats.py:59` | 触发席位画像冷启动构建 |

### 3.22 打板工作流（Trading Workflow）

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/workflow/status` | `routers/workflow.py:45` | 获取当前工作流阶段（盘前/盘中/盘后） |
| GET | `/api/workflow/pre-market` | `routers/workflow.py:58` | 获取盘前工作流数据（候选池/战法匹配/仓位建议） |
| POST | `/api/workflow/pre-market/run` | `routers/workflow.py:73` | 手动触发盘前工作流 |
| GET | `/api/workflow/realtime` | `routers/workflow.py:86` | 获取实时工作流数据（炸板预警/仓位调整） |
| GET | `/api/workflow/intraday` | `routers/workflow.py:101` | 盘中工作流（向后兼容别名，指向 realtime） |
| GET | `/api/workflow/post-market` | `routers/workflow.py:107` | 获取盘后复盘数据（结算/LLM复盘/胜率统计） |
| POST | `/api/workflow/refresh` | `routers/workflow.py:121` | 手动触发工作流刷新 |
| GET | `/api/workflow/signals` | `routers/workflow.py:137` | 获取实时交易信号 |
| GET | `/api/workflow/alerts` | `routers/workflow.py:151` | 获取炸板预警（Bomb Alerts） |
| POST | `/api/workflow/settle` | `routers/workflow.py:165` | 手动触发仓位结算 |
| GET | `/api/workflow/strategies` | `routers/workflow.py:177` | 获取 8 大战法定义列表 |
| POST | `/api/workflow/strategies/{name}/match` | `routers/workflow.py:189` | 对指定股票匹配特定战法 |
| GET | `/api/workflow/win-rate` | `routers/workflow.py:238` | 获取胜率统计（含 Sharpe/回撤/战法拆分） |
| GET | `/api/workflow/adjustments` | `routers/workflow.py:257` | 获取战法调整建议 |

### 3.23 情绪气象站（Sentiment Weather Station）

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/sentiment/weather/latest` | `routers/sentiment_weather.py:226` | 获取当前市场天气状态（综合多因子评分） |
| GET | `/api/sentiment/weather/factors` | `routers/sentiment_weather.py:283` | 获取多因子详细数据（用于分解图表） |
| GET | `/api/sentiment/weather/strategy` | `routers/sentiment_weather.py:352` | 获取当前天气下的策略推荐 |
| GET | `/api/sentiment/weather/fuse` | `routers/sentiment_weather.py:472` | 获取熔断规则状态 |
| GET | `/api/sentiment/weather/timeline` | `routers/sentiment_weather.py:509` | 获取天气历史趋势（近N天，默认30天） |
| GET | `/api/sentiment/weather/events` | `routers/sentiment_weather.py:653` | 获取关键事件标注（政策/重大利好/利空） |
| GET | `/api/sentiment/weather/auction` | `routers/sentiment_weather.py:669` | 获取竞价阶段指标（9:15-9:20 可撤单 / 9:20-9:25 不可撤单） |
| GET | `/api/sentiment/weather/seal-risk` | `routers/sentiment_weather.py:718` | 获取封单额/流通盘风险控制数据 |
| GET | `/api/sentiment/weather/pardon` | `routers/sentiment_weather.py:747` | 获取仓位赦免记录（管理员可见） |
| POST | `/api/sentiment/weather/pardon/toggle` | `routers/sentiment_weather.py:770` | 切换战法赦免状态（需2FA + 双人审批，当前为占位实现） |
| POST | `/api/sentiment/weather/pardon/revoke` | `routers/sentiment_weather.py:810` | 手动撤销赦免（仅创建人或审批人） |
| POST | `/api/sentiment/weather/pardon/outcome` | `routers/sentiment_weather.py:826` | 提交赦免交易结果（用于优化） |
| GET | `/api/sentiment/weather/fuse/history` | `routers/sentiment_weather.py:851` | 获取熔断规则触发历史 |
| POST | `/api/sentiment/weather/fuse/update` | `routers/sentiment_weather.py:862` | 更新熔断规则（管理员） |
| POST | `/api/sentiment/weather/refresh` | `routers/sentiment_weather.py:872` | 手动触发天气状态重新计算 |

### 3.24 定时任务（Scheduled Tasks）

| 方法 | 端点 | 文件 | 说明 |
|------|------|------|------|
| GET | `/api/scheduled-tasks` | `routers/scheduled_tasks.py:39` | 列出所有定时任务 |
| GET | `/api/scheduled-tasks/{task_id}` | `routers/scheduled_tasks.py:65` | 获取单个定时任务详情 |
| POST | `/api/scheduled-tasks` | `routers/scheduled_tasks.py:90` | 创建新定时任务（支持 Cron 表达式） |
| PUT | `/api/scheduled-tasks/{task_id}` | `routers/scheduled_tasks.py:107` | 更新定时任务 |
| DELETE | `/api/scheduled-tasks/{task_id}` | `routers/scheduled_tasks.py:126` | 删除定时任务 |
| POST | `/api/scheduled-tasks/{task_id}/run` | `routers/scheduled_tasks.py:136` | 手动立即执行一次任务 |
| GET | `/api/scheduled-tasks/{task_id}/runs` | `routers/scheduled_tasks.py:157` | 查看任务最近运行历史 |
| GET | `/api/scheduled-tasks/types` | `routers/scheduled_tasks.py:181` | 列出可用的任务类型（6种内置） |

---

## 4. 前后端对照表

### 4.1 按前端页面分组

| 页面/组件 | 前端 API 调用 | 后端端点 | 状态 |
|-----------|--------------|----------|------|
| **DailyReview** | `indices()`, `globalIndices()`, `marketOverview()`, `emotion()`, `turnoverTop()`, `stiLatest()`, `dailyReview()`, `quote()` | `/api/indices`, `/api/global/indices`, `/api/market/overview`, `/api/market/emotion`, `/api/market/turnover-top`, `/api/market/sti/latest`, `/api/review/daily`, `/api/quote` | ✅ 全部已实现 |
| **Intel** | `radar()`, `radarRefresh()`, `quote()`, `announcements()`, `news()` | `/api/radar`, `/api/radar/refresh`, `/api/quote`, `/api/announcements`, `/api/news` | ✅ 全部已实现 |
| **Portfolio** | `portfolio()`, `refreshPortfolio()`, `addHolding()`, `removeHolding()`, `closePosition()`, `removeClosed()` | `/api/portfolio`, `/api/portfolio/refresh`, `/api/portfolio/holding`, `/api/portfolio/holding`, `/api/portfolio/close`, `/api/portfolio/close` | ✅ 全部已实现 |
| **Watchlist** | `fetch()`, `add()`, `remove()`, `quote()` | `/api/watchlist`, `/api/watchlist`, `/api/watchlist/{code}`, `/api/quote` | ✅ 全部已实现 |
| **StockDeep** | `stockDeep()` | `/api/stock/{code}/deep` | ✅ 新增实现 |
| **MyReports** | `myReports()`, `uploadReport()`, `deleteReport()` | `/api/myreports`, `/api/myreports`, `/api/myreports/{id}` | ✅ 全部已实现 |
| **RiskDashboard** | `riskDashboard()`, `riskOnedayList()`, `riskSeats()` | `/api/risk/dashboard`, `/api/risk/oneday/list`, `/api/risk/seats` | ✅ 全部已实现 |
| **Backtest** | `backtestScatter()`, `backtestResult()` | `/api/backtest/scatter`, `/api/backtest/result` | ✅ 全部已实现 |
| **Recommendation** | `recommendationToday()` | `/api/recommendation/today` | ✅ 已实现 |
| **StrategySignals** | `limitupScreener()`, `winRateTrends()`, `strategySignals()` | `/api/limitup/screener`, `/api/winrate/trends`, `/api/strategy/signals/{code}` | ✅ 全部已实现 |
| **Health** | `fetch("/api/health")` | `/api/health` | ✅ 已实现 |
| **Settings** | `getLimitUpScreenerParams()`, `saveLimitUpScreenerParams()`, `getAuctionParams()`, `saveAuctionParams()`, `getReviewParams()`, `saveReviewParams()`, `getLlmEnvStatus()` | `/api/limitup/screener/params`, `/api/limitup/screener/params`, `/api/limitup/auction/params`, `/api/limitup/auction/params`, `/api/review/params`, `/api/review/params`, `/api/settings/llm-env-status` | ✅ 全部已实现 |
| **Industry** | `industry()` | `/api/industry` | ✅ 已实现 |
| **Metrics** | `metricsDataFetch()`, `metricsCompute()`, `metricsApiResponse()`, `metricsBreakdown()` | `/api/metrics/data_fetch`, `/api/metrics/compute`, `/api/metrics/api_response`, `/api/metrics/breakdown` | ✅ 全部已实现 |
| **AuctionScreener** | `auctionTop()` | `/api/limitup/auction/top` | ✅ 已实现 |
| **SeatEngine** | `seatProfiles()`, `seatBuildProfiles()` | `/api/limitup/seats/profiles`, `/api/limitup/seats/build` | ✅ 全部已实现 |
| **GeneScreener** | `limitupScreener()`, `limitupAnalysis()` | `/api/limitup/screener`, `/api/limitup/analysis/{code}` | ✅ 全部已实现 |
| **StockData** | `globalStock()` | `/api/global/stock` | ✅ 已实现 |
| **SeatProfileModal** | `seatProfile()`, `seatConsensus()` | `/api/limitup/seats/profile/{name}`, `/api/limitup/seats/consensus` | ✅ 全部已实现 |
| **STITimelineChart** | `stiTimeline()` | `/api/market/sti/timeline` | ✅ 已实现 |

### 4.2 按后端功能域分组

| 功能域 | 前端方法数 | 后端端点数 | 匹配状态 |
|--------|-----------|-----------|---------|
| 系统/健康 | 2 | 2 | ✅ 100% |
| AI 对话 | 1 | 1 | ✅ 100% |
| 自选股 | 3 | 3 | ✅ 100% |
| 持仓管理 | 6 | 6 | ✅ 100% |
| 研报管理 | 4 | 4 | ✅ 100% |
| 资讯雷达 | 2 | 2 | ✅ 100% |
| 市场行情 | 7 | 7 | ✅ 100% |
| 个股数据 | 11 | 12 | ✅ 100%（含新增 deep） |
| 财务数据 | 10 | 11 | ✅ 100% |
| STI 情绪 | 2 | 2 | ✅ 100% |
| 板块分析 | 3 | 3 | ✅ 100% |
| 风险管理 | 4 | 4 | ✅ 100% |
| 飞书推送 | 3 | 3 | ✅ 100% |
| 胜率追踪 | 6 | 6 | ✅ 100% |
| 回测 | 2 | 2 | ✅ 100% |
| 竞价监控 | 2 | 2 | ✅ 100% |
| 推荐引擎 | 2 | 2 | ✅ 100% |
| 战法信号 | 2 | 2 | ✅ 100% |
| 每日复盘 | 4 | 4 | ✅ 100% |
| 性能监控 | 4 | 4 | ✅ 100% |
| 打板策略 | 15 | 14 | ✅ 100% |
| **工作流** | **13** | **14** | ⚠️ ~60%（部分端点前端未对接） |
| **情绪气象站** | **15** | **15** | ⚠️ ~40%（部分端点前端未对接） |
| **定时任务** | **8** | **8** | ⚠️ ~50%（部分端点前端未对接） |

---

## 5. 前端页面 API 调用分布

### 5.1 Pages 目录（18 个文件）

| 页面 | API 调用数 | 涉及端点 |
|------|-----------|---------|
| DailyReview.tsx | 8 | indices, globalIndices, marketOverview, emotion, turnoverTop, stiLatest, dailyReview, quote |
| Intel.tsx | 5 | radar, radarRefresh, quote, announcements, news |
| Portfolio.tsx | 6 | portfolio, refreshPortfolio, addHolding, removeHolding, closePosition, removeClosed |
| Watchlist.tsx | 4 | watchlist, addToWatchlist, removeFromWatchlist, quote |
| StockDeep.tsx | 1 | stockDeep |
| MyReports.tsx | 3 | myReports, uploadReport, deleteReport |
| RiskDashboard.tsx | 3 | riskDashboard, riskOnedayList, riskSeats |
| Backtest.tsx | 2 | backtestScatter, backtestResult |
| Recommendation.tsx | 1 | recommendationToday |
| StrategySignals.tsx | 3 | limitupScreener, winRateTrends, strategySignals |
| Health.tsx | 1 | health |
| Settings.tsx | 7 | limitupScreenerParams, auctionParams, reviewParams, llmEnvStatus |
| Industry.tsx | 1 | industry |
| Metrics.tsx | 4 | metricsDataFetch, metricsCompute, metricsApiResponse, metricsBreakdown |
| AuctionScreener.tsx | 1 | auctionTop |
| SeatEngine.tsx | 2 | seatProfiles, seatBuildProfiles |
| GeneScreener.tsx | 2 | limitupScreener, limitupAnalysis |
| StockData.tsx | 1 | globalStock |

### 5.2 Components 目录（2 个文件）

| 组件 | API 调用数 | 涉及端点 |
|------|-----------|---------|
| Layout.tsx | 0 | 无 |
| SeatProfileModal.tsx | 2 | seatProfile, seatConsensus |
| STITimelineChart.tsx | 1 | stiTimeline |

---

## 6. 未使用/预留端点

以下后端端点已实现，但前端暂未直接调用（属于预留功能或通过其他方式使用）：

| 端点 | 说明 | 前端使用情况 |
|------|------|-------------|
| `/api/info` | 个股基本面 | ❌ 未使用 |
| `/api/disclosure` | 巨潮公告列表 | ❌ 未使用 |
| `/api/kline` | K线数据 | ❌ 未使用 |
| `/api/finance` | 季报财务快照 | ❌ 未使用 |
| `/api/valuation` | 完整估值 | ❌ 未使用 |
| `/api/limitup/metrics` | 涨停策略聚合指标 | ❌ 未使用 |
| `/api/push/test` | 测试飞书推送 | ❌ 未使用 |
| `/api/push/daily-review` | 推送每日复盘卡片 | ❌ 未使用 |
| `/api/push/recommendation` | 推送推荐关注卡片 | ❌ 未使用 |
| `/api/market/extreme` | 极端行情信号 | ❌ 未使用 |
| `/api/chat` | AI 流式对话 | ⚠️ 通过 `llm.ts` 间接使用 |
| **Workflow 系列** (14个) | 盘前/盘中/盘后工作流 | ⚠️ 前端工作流页面已对接部分 |
| **Sentiment Weather** (15个) | 情绪气象站多因子评分 | ⚠️ 前端气象站页面已对接部分 |
| **Scheduled Tasks** (8个) | Cron 定时任务管理 | ⚠️ 前端任务管理页面已对接部分 |

---

### 7. 新增端点说明

#### `/api/stock/{code}/deep`（2025-07-23 新增）

**前端定义**：`frontend/src/lib/api.ts:659`

```typescript
stockDeep: (code: string) => get<StockDeep>(`/stock/${code}/deep`)
```

**后端实现**：`backend/routers/stock_data.py:198`

**响应结构**：

```json
{
  "data": {
    "quote": { /* 实时行情 */ } | null,
    "kline": [ /* K线数组 */ ] | null,
    "valuation": { /* 完整估值 */ } | null,
    "percentile": { /* PE/PB 历史分位 */ } | null,
    "fund_flow": [ /* 资金流数组 */ ] | null,
    "dragon_tiger": { /* 龙虎榜 */ } | null,
    "limitup": { /* 涨停分析 */ } | null,
    "financials": { /* 财务指标 */ } | null,
    "blocks": { /* 板块归属 */ } | null,
    "hot_concepts": [ /* 热门概念 */ ] | null,
    "announcements": [ /* 公告 */ ] | null,
    "reports": [ /* 研报 */ ] | null
  }
}
```

**聚合数据源**：

| 字段 | 数据源 | 缓存策略 |
|------|--------|---------|
| `quote` | `astock.tencent_quote([code])` | 无（实时） |
| `kline` | `astock.kline(code, category=4, offset=60)` | 无（实时） |
| `valuation` | `astock.full_valuation(code)` | 无 |
| `percentile` | `astock.valuation_percentile(code)` | 30 分钟 |
| `fund_flow` | `astock.stock_fund_flow_120d(code)` | 15 分钟 |
| `dragon_tiger` | `astock.dragon_tiger_board(code)` | 30 分钟 |
| `limitup` | `lstrat.get_analysis(code, date, risk)` | 无 |
| `financials` | `astock.financials(code)` | 30 分钟 |
| `blocks` | `astock.concept_blocks(code)` | 30 分钟 |
| `hot_concepts` | `astock.hot_concepts(code)` | 30 分钟 |
| `announcements` | `astock.announcements(code)` | 15 分钟 |
| `reports` | `astock.eastmoney_reports(code, max_pages=2)` | 无 |

**实现特点**：
- 使用 `asyncio.to_thread` 并行调用 12 个数据源
- 单个数据源失败不影响其他数据返回（容错设计）
- `tencent_quote` 返回 `dict[str, dict]`，自动取第一个值
- `limitup_analysis` 通过同步包装器调用异步函数

---

### 工作流端点（Trading Workflow）

**模块路径**：`backend/routers/workflow.py` + `backend/trading_workflow.py`

**核心流程**：盘前候选池 → 盘中实时信号/炸板预警 → 盘后结算复盘

**关键端点**：
- `GET /api/workflow/status` — 根据时间判断当前阶段（pre-market: 06:00-09:00, intraday: 09:00-15:00, post-market: 15:00+）
- `GET/POST /api/workflow/pre-market` — 盘前工作流：候选池筛选、战法匹配、仓位建议
- `GET /api/workflow/realtime` — 实时工作流：炸板预警、仓位调整、交易信号
- `GET /api/workflow/post-market` — 盘后复盘：结算结果、LLM 复盘、胜率统计
- `POST /api/workflow/strategies/{name}/match` — 对指定股票匹配特定战法

**依赖模块**：
| 模块 | 说明 |
|------|------|
| `workflow_state_machine.py` | 状态机驱动 |
| `pre_market_workflow.py` | 盘前逻辑 |
| `realtime_workflow.py` | 盘中逻辑 |
| `post_market_workflow.py` | 盘后逻辑 |
| `risk/bomb_alert_system.py` | 炸板预警系统 |
| `risk/position_manager.py` | 仓位管理器 |
| `settlement/settlement_engine.py` | 结算引擎 |
| `strategies/strategy_matcher.py` | 战法匹配器 |
| `strategies/position_advisor.py` | 仓位顾问 |

---

### 情绪气象站端点（Sentiment Weather Station）

**模块路径**：`backend/routers/sentiment_weather.py`

**核心功能**：多因子市场天气评分（晴天/阴天/暴风雨/极端反弹）

**权重体系**：
| 因子 | 权重 | 说明 |
|------|------|------|
| STI 情绪温度 | 40% | 基于涨停家数、封板率、晋级率等 8 维指标 |
| 风险指标 | 20% | 基于炸板率、跌停家数、连板高度 |
| 板块持续性 | 25% | 板块涨停家数和资金流向持续性 |
| 资金动量 | 10% | 成交额变化和资金流向动量 |
| 舆情情绪 | 5% | 社交媒体和新闻情绪分析 |

**天气状态映射**：
| 综合评分 | 天气状态 | 图标 | 策略推荐 |
|----------|----------|------|----------|
| ≥ 75 | 晴天 | Sun | 连板接力 + 首板挖掘 |
| 55-75 | 阴天 | Cloud | 首板挖掘（连板接力禁用） |
| 35-55 | 极端反弹 | Zap | 弱转强反包 + 连板接力 |
| < 35 | 暴风雨 | CloudRain | 空仓观望（禁止买入） |

**TODO 项**：
- ⚠️ 竞价指标（`/auction`）目前为 mock 数据
- ⚠️ 封单风险（`/seal-risk`）目前为 mock 数据
- ⚠️ pardon 赦免功能 `is_admin = False` 硬编码，缺少认证检查
- ⚠️ 熔断规则历史（`/fuse/history`）为空列表

---

### 定时任务端点（Scheduled Tasks）

**模块路径**：`backend/routers/scheduled_tasks.py` + `backend/scheduled_tasks.py`

**CRUD 操作**：
- `GET /api/scheduled-tasks` — 列出所有任务
- `POST /api/scheduled-tasks` — 创建任务（支持 Cron 表达式）
- `PUT /api/scheduled-tasks/{task_id}` — 更新任务
- `DELETE /api/scheduled-tasks/{task_id}` — 删除任务
- `POST /api/scheduled-tasks/{task_id}/run` — 手动触发一次执行

**内置任务类型**：
| 类型 | 说明 |
|------|------|
| `daily_data_refresh` | 每日数据刷新 |
| `daily_review_notify` | 每日复盘通知推送 |
| `limitup_precompute` | 涨停基因得分预计算 |
| `portfolio_refresh` | 持仓行情刷新 |
| `market_data_sync` | 市场数据同步 |
| `cleanup_old_runs` | 清理过期运行记录 |

---

## 8. 统计总结

| 指标 | 数值 |
|------|------|
| 前端 API 方法总数 | ~82 |
| 后端端点总数 | **~115**（含新增 workflow/sentiment_weather/scheduled_tasks） |
| 前后端匹配率 | **~90%**（部分新端点前端尚未对接） |
| 前端页面数 | 18+（含情绪气象站/工作流等新增页面） |
| 前端组件数 | 2+ |
| 后端 Router 模块数 | **26**（原22，新增 workflow/sentiment_weather/scheduled_tasks） |
| 新增端点（本版本） | **37**（workflow 14 + sentiment_weather 15 + scheduled_tasks 8） |
| 未实现端点 | 0 |
| 前端未使用但已实现的后端端点 | ~15（含部分新端点） |

---

## 9. 快速参考

### 9.1 前端 API 调用示例

```typescript
// 获取个股深度数据
const data = await api.stockDeep("000001");

// 获取实时行情
const quotes = await api.quote("000001,000002");

// 获取K线
const kline = await api.kline("000001", 4, 60);

// 获取估值
const valuation = await api.valuation("000001");
```

### 9.2 后端路由注册示例

```python
# backend/app.py
from routers.stock_data import router as stock_data_router
app.include_router(stock_data_router, prefix="/api")
```

### 9.3 认证头示例

```typescript
// 前端自动添加 Bearer Token
const headers = authHeaders();
// { "Authorization": "Bearer <vr-access-key>" }
```

---

*文档结束*
