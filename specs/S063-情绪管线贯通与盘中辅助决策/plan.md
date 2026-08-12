# S063 实现计划

## 分支

`feature/S063-sentiment-pipeline` off `develop`

## 实现阶段

### Phase 1: 后端基础设施（T1-T9）

无外部依赖，可独立开发+测试。先建数据层和 SentimentContext，再重构工作流接线。

依赖链：
```
T1 sti_intraday 迁移 → T2 SentimentContext 模块
T2 → T3 STI 盘后定时任务
T2 → T4 工作流简报改造（T-1 读取）
T2 → T5 funnel.py 改用 ctx
T6 StrategySignal 模型 + T7 StrategyMatcher weather_fit → 可并行
T8 PositionAdvisor weather_state → 独立
T9 快照 schema 更新 → 依赖 T4
```

### Phase 2: 盘中后端（T10-T16）

依赖 Phase 1 的 SentimentContext（T2 提供 t1_baseline）和 sti_intraday 表（T1）。

```
T10 采样器 ring buffer + asyncio task → T11 评分 → T12 端点
T13 持仓联动 → 依赖 T10（snapshot 数据）
T14 场景推演 → 依赖 T11（score/trend）
T15 T+1 预判 → 依赖 T11（4 维度数据）
T16 app.py 注册 + config → 依赖 T12
```

### Phase 3: 前端（T17-T28）

依赖 Phase 1+2 的 API 端点。先类型+hooks，再组件，最后页面组装。

```
T17 类型定义 → T18 Query hooks → 可并行
T19 WeatherDecisionBar → T20 PreMarketBriefing 改造
T21-T24 盘中四层组件 → T25 状态机看板+进度条
T26 路由重定向 → 独立
T27 盘后页面改造 → 独立
T28 面包屑导航 → 依赖 T20/T25/T27
```

### Phase 4: 测试+验收（T29-T32）

```
T29 后端单元测试 → T30 后端集成测试 → T31 前端 tsc+playwright → T32 live 冒烟
```

## 合并策略

- Phase 1+2 后端合入 develop 一次（squash commit `feat(S063): 后端情绪管线+盘中采集`）
- Phase 3 前端合入 develop 一次（squash commit `feat(S063): 前端三页重写+详情导航`）
- Phase 4 测试随各 phase commit 附带，最终 live 冒烟通过后删分支
