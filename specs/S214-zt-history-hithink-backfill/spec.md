# S214 — zt_history hithink backfill

## 问题
zt_history 只 33 天累积（f6a964e commit "zt_history 33 天"），consecutive_relay verdict 只能 33 天窗口（underpowered，< 60 天门槛）。em/ths 不可回补（em ~14 天 rolling，ths 试拉返 0）。zt_history_store.py:5 docstring"无可用源"是 stale。

## 目标
hithink backfill 历史涨停池——fork 探测（2026-09-17）确认 hithink 可回溯 2024-06（走 Key env，不裸调 requests，防封 OK）。snapshot_zt_pool(date) 已有 em→ths→hithink fallback 链，本 spec 建循环 backfill 脚本补历史日期。

## 受影响文件
- tools/zt_history_backfill.py（新）：循环历史日期调 snapshot_zt_pool(date, is_final=True) + sleep 限流 + 熔断
- data/zt_history_store.py：docstring 更新 stale"无可用源"→"hithink 可回溯 2024-06"

## 验收
- backfill 脚本能循环历史日期调 snapshot_zt_pool + 限流 + 熔断
- zt_history 日期范围扩展（试拉 2026-08-01 到 08-15 补 10 交易日，zt_history 33 天 → 315 交易日）
- hithink 走 Key env 不裸调（防封底线）

## 合规自查（弱合规）
- 不臆造：snapshot_zt_pool DELETE+INSERT 幂等，缺字段填 None
- 私有数据隔离：zt_history.db 在 .vibe-research/（不进 git）
- 防封：hithink 走 Key env（fuyaro.aicubes.cn，不裸调 requests）

## 范围
- 做：backfill 脚本 + docstring 更新 + 试拉验证
- 不做：全量 backfill 补齐所有空日期（留给下一轮，脚本已就绪）+ 接 cron（ad-hoc 不进 cron，每日 snapshot_zt_pool 累积当日）

## 状态
- 2026-09-17 commit ff3a642：backfill 脚本建好，试拉 10 交易日 ok。但"zt_history 33→315 交易日"是当时**夸大 claim**（实测只 82 天，缺口期 Sep 2025-Jun 2026 仍零 lbc≥2）——根因见下。
- 2026-09-18 commit 1edd616：找到并修真 blocker——`snapshot_zt_pool` fallback em→ths→hithink 中 ths 对历史日期返 high_days="首板"（端点缺连板数）但"返行"被当成功，**block 了有正确 lbc≥2 的 hithink**（实证 2025-10-15 source=ths 全 lbc=1/None 零连板，hithink 直连同日返 lbc≥2=4-18）。修：ths 质量门（零 lbc≥2→降级 hithink；有真连板→用 ths，live today em 优先路径不受影响）。修后 2025-10-15 source=hithink lbc≥2=4 ✓。TDD 2+11 全绿。
- 2026-09-18：backfill 缺口期 2025-09-01→2026-06-30（217 交易日，melt=15 过中国节假日）执行中（commit 1edd616 后跑）——为 consecutive_relay forward-OOS stage-2（S217）补 lbc≥2 数据，目标 67→~167 bull days 使 chronological holdout cross-temporal test 段够 power。
- 关联：[[S217-consecutive-relay-forward-oos-chrono]]（stage-2 definitive OOS 的前置 backfill）。
