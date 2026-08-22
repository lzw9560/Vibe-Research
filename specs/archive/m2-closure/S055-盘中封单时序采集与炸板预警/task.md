# S055 原子任务清单

> 级别：large（新增外部数据源盘中轮询 → AGENTS.md 自动 large）
> 流程门：feature/S055-seal-intraday-alert off develop；git merge --squash；live 冒烟通过前不合
> 基线：后端 1022 passed / 前端 41 files 305 tests（S056 验收后）

## S1 T1 表 + 采集器 + 调度注册 + prune

- [x] T1 `risk/seal_intraday_collector.py` + `migrations/seal_intraday/20260811-001`：
  - `seal_intraday_snapshots` 表 + `bomb_alert_history` 表
  - `collect_once()` 交易时段门控 + em_zt_topic_pool 采集 + tencent_quote 指数/流通市值
  - `prune_old_snapshots(retention_days=30)`
  - 调度注册：`seal_intraday_collect` 任务类型
  - 单测：13 passed（迁移/门控/采集/失败降级/prune/查询）
- commit: `1723ce8` feat(S055) T1

## S2 T2 端点

- [x] T2 `routers/risk.py` 新增：
  - `GET /api/risk/bomb-alerts?date=`：当日活跃预警（历史表）
  - `GET /api/risk/seal-snapshots?code=&date=`：单股封单时序（sparkline 用）
  - 缺数据诚实标注 data_status=missing
  - 单测：4 passed（空/有预警/有快照/缺失）
- commit: 本批

## S3 T3 规则引擎

- [x] T3 `risk/bomb_alert_rules.py` C1/C3/C4/C5/C6 + C2 降级：
  - C1 封单 5 分钟减>30% → 黄
  - C2 降级：封单骤降≥50% → 黄（tick 级不可得，文案标注降级口径）
  - C3 同板块龙头进炸板池 → 红
  - C4 大盘 5 分钟急跌>0.5% → 红
  - C5 开板 3 分钟未回封 → 红
  - C6 封单<流通市值 0.3% → 红
  - 三态判定：触发/不触发/缺数据（missing 跳过，不臆造）
  - 单测：21 passed（六规则各触发/不触发/缺数据）
- commit: 本批

## S4 T4 去重 + 通知

- [x] T4 `risk/bomb_alert_dispatcher.py`：
  - 同股同规则 10 分钟冷却去重（BOMB_ALERT_COOLDOWN_MINUTES 可配）
  - 预警历史落 bomb_alert_history 表（依据链 + data_status）
  - 通知通道接线（BOMB_ALERT_NOTIFY_ENABLE 默认关）
  - 单测：3 passed（冷却/不同规则独立/不同股独立）
- commit: 本批

## S5 T5 前端

- [x] T5 前端横幅 + sparkline：
  - `components/risk/BombAlertBanner.tsx`：横幅（红/黄分级 + 时间 + 依据 + 可关闭）
  - `SealAmountSparkline`：纯 SVG sparkline（无第三方依赖）
  - `LimitUpStrategy.tsx` 顶部挂横幅
  - 前端类型：BombAlertItem + SealSnapshot + BombAlertsResult + SealSnapshotsResult
  - 单测：7 passed（无预警/红/黄/关闭/sparkline 不足/充足/加载中）
- commit: 本批

## S6 T6 live 冒烟 + 验收

- [ ] T6 live 冒烟（待用户在交易时段验证）：
  - 交易时段运行 ≥30 分钟，快照表持续写入
  - em_get 限流/熔断日志正常
  - 至少复现一条真实预警或说明未触发原因
  - 前端横幅走查

## 合规自查

- [x] 预警属风险标注，文案挂「历史统计特征，市场有风险」；无「必须卖出」式指令
- [x] 判断可复现：每条预警带触发时刻 + 输入值快照（依据链）
- [x] 新增东财调用走 em_get() 限流 + circuit_breaker，无直连并发
- [x] 不臆造：缺快照/缺市值 → 规则跳过并记 data_status
- [x] 私有数据（.vibe-research/seal_intraday.db）不进 git

## 门汇总

| 门 | 内容 | 状态 |
|---|---|---|
| G1 | T1 表+采集器+门控单测绿 | ✅ 13 passed |
| G2 | T2 端点测试绿 | ✅ 4 passed |
| G3 | T3 规则引擎单测绿 | ✅ 21 passed |
| G4 | T4 去重冷却单测绿 | ✅ 3 passed |
| G5 | T5 前端 vitest 绿 | ✅ 7 passed |
| G6 | T6 live 冒烟 + 用户走查 | 待交易时段验证 |
