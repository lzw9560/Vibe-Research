# S225 · M5 财报季排雷

> 状态：进行中（2026-09-21）｜分级：medium（issue 层单轮 review，免 feature 分支）
> 关联：S216 P2 earnings_calendar、consecutive_relay arm、§1.2 工程底线（防跌停保护钱）
> 解冻：专家讨论 + 用户同意——earnings_calendar 已实现加 CB 是延伸非新基建，防跌停保护钱（工程底线）

## 1. 问题 / 目标

财报季 1/4/8 月（DANGER_MONTHS 监管强制披露窗口）未披露/财务异常股一字跌停风险。
consecutive_relay arm 选 lbc≥2 股，若 D+1 遇财报季未披露跌停 → gap_net_return 假象（D+1 open 卖不掉，realizability-bias）。

**目标**：ReportSeasonCircuitBreaker 拉黑财报季未披露股，arm 跳过，防一字跌停保护钱。

## 2. 需求

1. 财报季窗口判定（DANGER_MONTHS 已有 1/4/8 月）
2. 未披露检测（per-code announcements 在 DANGER_MONTHS 窗口内无 → 未披露）
3. CB 拉黑（arm 跳过，exit_reason="earnings_season_blacklist"）
4. 前端 M5 卡 planning→live + 数据徽章

## 3. 受影响文件

- `routers/earnings_calendar.py`：加 `is_earnings_season_unsafe(code, target_date)` 函数
- `strategies/journal_recorder.py`：consecutive_relay arm 加财报季拉黑检查（类似 _is_unbuyable_next_bar 模式）
- `frontend/src/pages/quant/modules.ts`：M5 status planning→live + liveSource
- `frontend/src/pages/quant/QuantModelsPage.tsx`：M5 卡加 LiveDataChip

## 4. 验收

- 财报季未披露股被拉黑，arm 跳过（exit_reason="earnings_season_blacklist"）
- 前端 M5 卡 live + 数据徽章
- tsc 0 错 + pytest 相关 test green

## 5. 合规自查

- 工程底线：不臆造（announcements 走 em_get 真数据）/ 防封（em_get）/ 私有数据隔离（code 用户提供）✅
- §1.2 防跌停保护钱——该做 ✅
- 弱合规（私人助理）——拉黑是风险标注非交易禁令，用户最终决策 ✅

## 6. plan（技术方案）

1. earnings_calendar 加 `is_earnings_season_unsafe(code, target_date) -> bool`
   - 判 target_date 月 in DANGER_MONTHS
   - 调 astock.announcements(code) 看窗口内有无 announcement
   - 无 → 未披露 → True（拉黑）；异常/失败 → False（不拉黑，不臆造）
2. journal_recorder consecutive_relay arm 加检查（_is_unbuyable_next_bar 前）
   - True → exit_reason="earnings_season_blacklist" is_realized=1（跳过交易）
3. 前端 modules.ts M5 status planning→live + liveSource="earningsCalendar"
4. QuantModelsPage M5 卡加 LiveDataChip（拉 /api/earnings-calendar 显 DANGER_MONTHS + 当前是否财报季）

**备选不选**：market-level hardstop（全市场扫描未披露比例，慢，留 follow-up）/ 财务异常 flag（数据源要核，留 follow-up）

## 7. tasks

- [ ] T1 earnings_calendar.py 加 is_earnings_season_unsafe(code, target_date)
- [ ] T2 journal_recorder consecutive_relay arm 加财报季拉黑检查
- [ ] T3 frontend modules.ts M5 status planning→live + liveSource
- [ ] T4 QuantModelsPage M5 卡加 LiveDataChip
- [ ] T5 tsc + pytest 验
- [ ] T6 commit
