# Spec: S055 — 盘中封单时序采集与炸板预警规则引擎

> 状态：草案
> 作者：Codex（DSA 借鉴 grill 会话）  日期：2026-08-11
> 级别：**large**（新增外部数据源盘中轮询 → AGENTS.md 自动 large）
> 流程门：`feature/S055-seal-intraday-alert` off develop；`git merge --squash` 一 spec 一 commit；**live 冒烟通过前不合**；合并后删分支
> 关联：`.scratch/dsa-board-borrowing/issues/01`（Q2/Q3 裁决）、`risk/bomb_alert_system.py`（已有 1 条规则）、`routers/sentiment_weather.py`（weather_fuse）、S050（W0 行动闭环）、DSA `SEAL_PLATE_ARCHITECTURE.md` §6（C1-C6 规则原型）

## 1. 问题 / 目标

`risk/bomb_alert_system.py` 仅有 1 条规则（封单降幅≥50%），`lookback_seconds` 未用、无持久化，且**上游没有盘中封单时序采集**——`check()` 依赖调用方喂 `prev_seal_amount`，无人喂。炸板预警（DSA C1-C6）与撤单熔断（S056）都缺输入。

目标：建盘中封单时序采集层（东财涨停池轮询 + SQLite），扩充炸板预警至 C1/C3/C4/C5/C6 五条规则（C2 tick 级降级处理），接通知与前端展示。

## 2. 背景

- 数据源：`astock.em_zt_topic_pool()`（东财涨停四池，含封单额/开板次数/封板时间/连板/板块）必须走 `em_get()`（QPS≤2 + 熔断）；腾讯 `tencent_quote` 底座不封 IP（指数/市值）；mootdx TCP:7709 惰性导入（C2 候选）。
- 调度：`scheduled_tasks.py` CronScheduler 每分钟 tick + SQLite 持久化，已有任务注册模式。
- 现状：`BombAlertSystem` 内存 history[-200:]，无去重、无通知、无端点。
- DSA C1-C6 原型：C1 封单 5 分钟减>30%（黄）/ C2 单笔>5000 手卖单（黄，tick 级）/ C3 同板块龙头炸板（红）/ C4 大盘 5 分钟急跌>0.5%（红）/ C5 开板 3 分钟未回封（红）/ C6 封单<流通市值 0.3%（红）。

## 3. 需求清单

- [ ] R1 采集层：交易时段（09:25-15:05）每 60s（可配，下限 30s）轮询 `em_zt_topic_pool()` 一次，写 SQLite 表 `seal_intraday_snapshots`（ts/date/code/name/pool/price/seal_amount/open_count/first_seal_time/consec_boards/sector），库文件遵循 S037 惯例存 `.vibe-research/`；同周期用 `tencent_quote` 取指数快照（大盘 5 分钟跌幅，C4 输入）与候选股流通市值（C6 输入）
- [ ] R2 数据保留：按交易日保留近 30 日（可配），启动时 prune；单日规模预估 ≤ 涨停池 150 只 × 240 分钟 ≈ 3.6 万行
- [ ] R3 规则引擎：`BombAlertSystem` 扩充为时序窗口驱动，新增 C1/C3/C4/C5/C6；C2 实施时评估 mootdx 分笔/五档可得性——拿不到则降级为「封单骤降（5 分钟降幅≥50%）」代理规则，预警文案显式标注降级口径
- [ ] R4 告警治理：同股同规则冷却 10 分钟去重；预警分级（黄/红）；接 `notification/` 通道（`.env` 开关，默认关）
- [ ] R5 API：`GET /api/risk/bomb-alerts?date=`（当日活跃+历史）、`GET /api/risk/seal-snapshots?date=&code=`（单股封单时序）
- [ ] R6 前端：涨停页（LimitUp）加炸板预警横幅（红/黄分级 + 时间 + 依据文案）+ 个股封单额 sparkline（读 R5 端点）
- [ ] R7 `realtime_workflow.py` 接线：采集-检测-告警循环由调度器驱动，dataclass 契约不变（BombAlert 已有字段直接用）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/risk/bomb_alert_system.py` | 规则扩充（C1/C3/C4/C5/C6 + C2 降级）、时序窗口输入、去重 |
| `backend/risk/seal_intraday_collector.py`（新） | 采集调度 + SQLite 读写 + prune |
| `backend/routers/risk.py` | bomb-alerts / seal-snapshots 端点 |
| `backend/scheduled_tasks.py` | 注册盘中采集任务（交易时段门控） |
| `backend/config.py` | 采集间隔/保留天数/通知开关配置项 |
| `frontend/src/pages/.../LimitUp*` | 预警横幅 + sparkline |

## 5. 设计方案

- **轮询而非推送**：东财无免费推送；60s 全池一次请求（单次 em_get），QPS 占用 1/60，防封风险低；熔断触发自动降频至 5 分钟并标记数据降级。
- **时序窗口计算**：C1/C5 用 `seal_intraday_snapshots` 近 5 分钟窗口；C4 用指数快照窗口；C3 用「板块内最高连板股进入炸板池」判定；C6 用最新快照封单额 / 流通市值。
- **不做**：自动下单/撤单（VR 定位）；tick 级 C2 原样实现（数据不可得）。
- 备选不选：mootdx 全量轮询（TCP 长连稳定性未验证，仅作 C2 评估项）；内存环形缓冲（重启丢数据，复盘无依据）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：五条规则各用合成时序单测（触发/不触发/缺数据三态）
- [ ] A2 非交易时段采集任务不落库、不请求东财（门控测试）
- [ ] A3 live 冒烟：交易时段运行 ≥30 分钟，快照表持续写入，em_get 限流/熔断日志正常；至少复现一条真实预警或说明未触发原因
- [ ] A4 缺数据诚实：东财不可用时端点返降级标记，不臆造封单值
- [ ] A5 tsc + vitest 过；预警横幅红/黄分级渲染正确

## 7. 合规与工程底线自查（逐条确认）

- [ ] 预警属风险标注（系统能力，§1.1），文案挂「历史统计特征，市场有风险」；不出现「必须卖出」式指令
- [ ] 判断可复现：每条预警带触发时刻 + 输入值快照（依据链）
- [ ] 新增东财调用走 `em_get()` 限流 + circuit_breaker，无直连并发
- [ ] 不臆造数据：缺快照/缺市值 → 规则跳过并记 data_status，不补默认值
- [ ] 私有数据（.vibe-research/ 快照库）不进 git

## 8. 测试计划

离线：规则引擎单测（合成时序）、调度门控单测、端点测试（mock 快照）。联网：live 冒烟（A3）。手动：前端横幅走查 + 通知开关验证。

## 9. 风险与回滚

- 轮询被封：默认 60s 保守 + 熔断降频；回滚＝停采集任务。
- 快照量超预期：prune 保留 30 日；表有索引，查询限 date+code。
- 前端依赖端点：端点降级返空数组，横幅隐藏。

## 10. 任务拆分（large 必备）

| # | 任务 | 依赖 | 验收 |
|---|------|------|------|
| T1 | 表 + 采集器 + 调度注册 + prune | — | A2 + 本地落库 |
| T2 | seal-snapshots / bomb-alerts 端点 | T1 | 端点测试 |
| T3 | 规则引擎 C1/C3/C4/C5/C6（+C2 评估降级） | T1 | A1 |
| T4 | 去重 + 通知接线 | T3 | 冷却窗口单测 |
| T5 | 前端横幅 + sparkline | T2 | A5 |
| T6 | live 冒烟 + 验收报告 | T1-T5 | A3/A4 |
