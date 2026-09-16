# S214 tasks — zt_history hithink backfill

## T1 backfill 脚本
- [x] T1.1 tools/zt_history_backfill.py：循环历史日期调 snapshot_zt_pool(date, is_final=True)
- [x] T1.2 限流 sleep 0.5s/日期 + 熔断（连续 5 空日期跳过）
- [x] T1.3 trading_days 生成（跳过周末，节假日空日期 snapshot 返 0 自动跳过）
- [x] T1.4 验证 zt_history 日期范围 + 行数

## T2 docstring 更新
- [x] T2.1 zt_history_store.py:5 stale"无可用源"→"hithink 可回溯 2024-06"

## T3 试拉验证
- [x] T3.1 试拉 2026-08-01 到 08-15（10 交易日全部 ok，+75~137 行/日）
- [x] T3.2 zt_history 33 天 → 315 交易日（2025-06-03 到 2026-09-16，20185 行）
- [x] T3.3 hithink 走 Key env 不裸调（防封底线 OK）

## T4 verdict 重跑（跨 60 天门槛）
- [x] T4.1 consecutive_relay verdict 315 天重跑：bull robust_edge +1.131%（n=269 days=65，比 33 天 +1.055% 略升更稳）
- [x] T4.2 registry 更新 n=276→269 days=66→65 note +1.055%→+1.131%（commit 35319e1）
- [x] T4.3 sizing 不变（bull ×0.5 provisional，verdict robust_edge 但综合 refuted）
- [ ] T4.4 baostock cache backfill 更早 bars（fork 进行中）→ verdict 用满 315 天（现受 cache 174 天限制只用 78 天）

## T5 全量 backfill（defer）
- [ ] T5.1 全量 backfill 补齐 2025-06 到 2026-09 所有空日期（脚本就绪，ad-hoc 跑）
- [ ] T5.2 接 cron？（ad-hoc 不进 cron，每日 snapshot_zt_pool 累积当日）

## 状态
- backfill 脚本 + 试拉 + verdict 重跑 DONE（2026-09-17，commit ff3a642 + 35319e1）。baostock cache backfill 进行中（T4.4）。全量 backfill defer。
