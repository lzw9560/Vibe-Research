# S063 原子任务清单

| ID | 任务 | 依赖 | 文件 | AC | 估时 |
|---|---|---|---|---|---|
| **Phase 1: 后端基础设施** | | | | | |
| T1 | `sti_intraday` 迁移 SQL + data.py CRUD 函数 | — | `migrations/sti/20260813-001_create_sti_intraday.sql`、`limitup_sti/data.py`（新增 `save_intraday`/`load_intraday_day`/`prune_intraday`） | AC6 | 30m |
| T2 | `SentimentContext` 模块 | T1 | `backend/sentiment_context.py`（`@dataclass SentimentContext` + `build_context(decision_date)`：读 `sti_timeline` T-1 行 → 调 `_calculate_weather_state` → 调 `calc_weather_fit` 算 allowed/forbidden → 调 fuse 端点取 `fuse_state`） | AC1 | 45m |
| T3 | STI 盘后定时计算任务 | T2 | `backend/scheduled_tasks.py`（新增 `compute_sti_post_market`：交易日 15:30 → `market._emotion(T)` + `market._sentiment(T)` → `engine.compute()` → `save_result()`） | AC8 | 20m |
| T4 | 工作流简报改造：`_fetch_market_emotion` 读 T-1 | T2 | `backend/routers/workflow.py`（`_fetch_market_emotion(date)` 改为读 `sti_timeline` T-1 行 + dimension 映射；简报 JSON 响应增 `sentiment_context` 字段；`_fetch_sentiment_phase` 删除改从 ctx 取） | AC2,AC9 | 45m |
| T5 | `funnel.py` 改用 SentimentContext | T2 | `backend/candidate_funnel/funnel.py`（`_fetch_sentiment_phase` 删除；`_run_funnel_impl` 接收 `ctx: SentimentContext` 参数；`resolve_thresholds(cfg, ctx.weather_state)`；快照写 `sentiment_phase=ctx.weather_state` + `source_date=ctx.source_date`） | AC9 | 20m |
| T6 | `StrategySignal` 模型加 `weather_fit` 字段 | — | `backend/limitup_strategy.py`（`StrategySignal` 加 `weather_fit: str = "中性"`） | AC3 | 5m |
| T7 | `StrategyMatcher.match` 传 weather_state + 标注适配度 | T6 | `backend/strategies/strategy_matcher.py`（`match(gene, weather_state=None)` → 遍历 signals 调 `calc_weather_fit(code, weather_state)` 填 `weather_fit`）；`backend/routers/workflow.py`（match_strategy 端点传 ctx.weather_state） | AC3 | 25m |
| T8 | `PositionAdvisor.advise` 接 weather_state | — | `backend/strategies/position_advisor.py`（`advise(signal, weather_state=None)`：暴风雨→仓位上限=0，极端反弹→50%，晴天/阴天→正常）；`backend/routers/workflow.py`（调用处传 ctx.weather_state） | AC4 | 20m |
| T9 | 快照 schema 更新：写 `sentiment_context` 到 JSON | T4 | `backend/routers/workflow.py`（`_save_snapshot` payload 增 `sentiment_context` 字段；`_SNAPSHOT_SCHEMA` 不升版本，新字段可选向后兼容） | AC9 | 10m |
| **Phase 2: 盘中后端** | | | | | |
| T10 | 盘中采样器：ring buffer + asyncio task | T1 | `backend/routers/intraday_sentiment.py`（`_IntradaySampler` 类：内存 ring buffer `list[dict]`；`_sampler_loop` asyncio task：app startup 注册 → 交易日 09:25-15:00 运行 → 按黄金窗口频率调 `market._emotion(today)` → 存 ring buffer + `save_intraday` → shutdown cancel） | AC5 | 60m |
| T11 | 盘中评分模型：4 维度固定阈值 | T10 | `backend/routers/intraday_sentiment.py`（`_compute_score(emo)` 函数：4 维度固定阈值映射 → 加权平均 → score；`_compute_trend(score, prev_score)` → up/flat/down；`_compute_zone(score, t1_baseline)` → green/yellow/red） | AC5 | 25m |
| T12 | 盘中 5 GET + 1 POST 端点 | T10,T11 | `backend/routers/intraday_sentiment.py`（`GET /api/intraday/sentiment/latest`→ring buffer latest；`/timeline`→当日全量；`POST /snapshot`→手动触发采样） | AC5 | 30m |
| T13 | Layer 2 端点：持仓×情绪联动 | T10 | `backend/routers/intraday_sentiment.py`（`GET /api/intraday/sentiment/holdings`：读 `workflow_state_repo` holding 列表 → `astock.tencent_quote(codes)` 拉实时报价 → 判定封板状态 → 关联当前 snapshot 色带 → 双重压力行置顶排序） | AC5 | 40m |
| T14 | Layer 3 端点：条件场景推演 | T11 | `backend/routers/intraday_sentiment.py`（`GET /api/intraday/sentiment/scenarios`：基于当前 score/trend/zone → if-then 分支生成；历史参照查 `sti_intraday` 近 20 日类似走势 → 标注样本量） | AC5 | 35m |
| T15 | Layer 4 端点：T+1 预判 | T11 | `backend/routers/intraday_sentiment.py`（`GET /api/intraday/sentiment/t1-projection`：14:30 后可用 → 用当前 4 维度预推算 STI（调 `engine.compute` 但不 save）→ 双场景（维持/反弹）→ 写 `projected_t1_score`+`projected_t1_weather`；收盘后回填 `actual_score`） | AC7 | 40m |
| T16 | app.py 注册 + config | T12 | `backend/app.py`（`app.include_router(intraday_sentiment.router)`）；`backend/config.py`（`INTRADAY_SAMPLE_INTERVALS` 黄金窗口配置） | — | 10m |
| **Phase 3: 前端** | | | | | |
| T17 | 类型定义 | — | `frontend/src/lib/api/types.ts`（`SentimentContext`、`IntradaySnapshot`、`IntradayHolding`、`IntradayScenario`、`T1Projection` interface） | — | 15m |
| T18 | Query hooks | T17 | `frontend/src/lib/query/intraday.ts`（`useIntradayLatest`/`useIntradayTimeline`/`useIntradayHoldings`/`useIntradayScenarios`/`useIntradayT1Projection`；刷新频率 Layer 1/2 每 5min，3/4 随 1 联动） | — | 20m |
| T19 | `WeatherDecisionBar` 组件 | T17 | `frontend/src/components/workflow/WeatherDecisionBar.tsx`（全宽非卡片：天气图标+名+STI+阶段+允许/禁用 chips+熔断三灯+STI 迷你折线+天气色背景） | AC11 | 45m |
| T20 | `PreMarketBriefing` 改造 | T19,T18 | `frontend/src/pages/workflow/PreMarketBriefing.tsx`（顶部加 `WeatherDecisionBar` + `PipelineProgressBar`；`MarketEmotionBlock` 改读 `sentiment_context`；战法信号渲染 `weather_fit`） | AC11 | 35m |
| T21 | Layer 1 情绪走势图 | T18 | `frontend/src/components/intraday/EmotionTrendChart.tsx`（ECharts 折线+面积：T-1 基线虚线+三色区间带+当前点高亮+趋势箭头；4 维度小折线可折叠 `<details>`） | AC13 | 50m |
| T22 | Layer 2 持仓×情绪联动表 | T18 | `frontend/src/components/intraday/HoldingsEmotionTable.tsx`（紧凑表格：持仓/状态/盈亏/封板状态/情绪色带/决策上下文；双重压力行红色置顶；行可点击） | AC14 | 35m |
| T23 | Layer 3 条件场景推演 | T18 | `frontend/src/components/intraday/ScenarioCards.tsx`（两栏并列 if-then 卡片：条件→影响→建议→历史参照+样本量；14:30 前不显示） | AC15 | 30m |
| T24 | Layer 4 T+1 预判 | T18 | `frontend/src/components/intraday/T1ProjectionPanel.tsx`（14:30 后双场景卡片：维持/反弹→投影 STI→天气→战法切换→建议；标注"投影，非最终"；收盘后校准展示） | AC16 | 30m |
| T25 | 状态机看板 + Pipeline 进度条 | T18 | `frontend/src/components/intraday/StateMachineDashboard.tsx`（6 态计数+流转记录）；`frontend/src/components/workflow/PipelineProgressBar.tsx`（5 节点进度条，当前阶段脉冲） | AC12 | 40m |
| T26 | 路由重定向 + Workflow.tsx 链接更新 | — | `frontend/src/router.tsx`（`/sentiment/weather`→301 `/workflow/intraday`）；`frontend/src/pages/Workflow.tsx`（盘中卡链接改 `/workflow/intraday`） | AC17 | 10m |
| T27 | `PostMarketReview` 改造 | T18 | `frontend/src/pages/workflow/PostMarketReview.tsx`（当日 STI 结算条+盘中轨迹回放+T+1 预判校准面板+持仓结算表含状态流转列+T+1 准备面板） | — | 50m |
| T28 | 面包屑导航 + 详情 overlay 系统 | T20,T25,T27 | `frontend/src/components/workflow/BreadcrumbDetail.tsx`（详情 overlay：面包屑 `工作流/[当前页]/[子页面]`+返回按钮；`showDetail(type,id)` 函数路由；各页面 `.clickable` 项绑定） | — | 40m |
| T29 | `IntradayMonitor` 主页面组装 | T21-T25 | `frontend/src/pages/workflow/IntradayMonitor.tsx`（重写：紧凑 WeatherBar→状态机看板→Layer1-4 纵向布局→PipelineProgressBar） | AC12 | 30m |
| **Phase 4: 测试+验收** | | | | | |
| T30 | 后端单元测试 | T1-T8 | `backend/tests/test_s063_sentiment_context.py`（build_context T-1 映射）；`test_s063_intraday_scoring.py`（4 维度固定阈值+趋势+色带）；`test_s063_position_advisor.py`（暴风雨→0，极端反弹→50%） | AC1,AC4,AC5 | 45m |
| T31 | 后端集成测试 | T12-T15 | `backend/tests/test_s063_intraday_endpoints.py`（5 GET+1 POST 端点 mock 采样）；`test_s063_t1_projection.py`（14:30 预判+收盘回填） | AC5,AC7 | 35m |
| T32 | 前端 tsc + playwright | T20-T29 | `cd frontend && npx tsc --noEmit`（零错误）；`frontend/src/pages/workflow/__tests__/IntradayMonitor.test.tsx`（四层渲染 stub）；`PreMarketBriefing.test.tsx`（WeatherDecisionBar 渲染） | AC18,AC19 | 30m |
| T33 | `pytest -m "not live"` 全过 | T30,T31 | `cd backend && ../.venv/bin/python -m pytest -m "not live" -x` | AC10 | 10m |
| T34 | Live 冒烟（交易日） | T16,T29,T33 | 启动后端 8900+前端 5899 → 盘前验证 WeatherDecisionBar → 盘中验证 4 层 → 盘后验证 STI 结算+T+1 校准 | 全 AC | 手动 |

## 统计

- 总任务：34
- 后端：16（T1-T16）
- 前端：13（T17-T29）
- 测试：5（T30-T34）
- 预估总工时：~15 小时
