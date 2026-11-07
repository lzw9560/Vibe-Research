# Plan: S238 — combo-5d-edge 实现方案

> 关联：spec.md（S238）/ 同模式 S237（A组T+10）/ S236（inst_dominant）

## 实现顺序（依赖序）

### P0: 信号生成（R1）
- T1: `commander_runner.load_combo_5d_today(date, mode, top_n)`——读 baostock_kline_cache，rank(gap)+rank(today_ret)+rank(-amount) top-20。从末尾反向找 date==D（live 即时命中，历史日早停于 bd<date）。mode=filtered 跳 ST+北交所920。
- T2: `run()` 加 combo_5d_signals hook（piggyback 14:50 commander cron，**Option A**——不加新 executor，避 `scheduler-executor-test-registry-pattern` 三处同步坑）
- T3: `format_text()` 加飞书输出块

### P1: arm 注册 + replay_check（R2/R4）
- T4: `_setup_combo_5d_arm.py` 注册 arm（is_active=1 weight_override=0.5，UPSERT idempotent；replay_check 用 UPDATE 非 UPSERT 须先建行）
- T5: `inst_dominant_replay_check` 加 combo_5d 到 BACKTEST_MEANS(2.06) + ARM_WEIGHTS(0.5/0.25/0) + __main__ + 参数化权重档
- T6: `replay_check(arm="combo_5d")` 跑通（0 signal <120天提醒不 enforce）

### P2: skill + 文档（R3）
- T7: `~/.claude/skills/combo-5d-edge/SKILL.md`（6要素 + Stats + Limitations + 关联）

### P3: 测试 + 验收
- T8: pytest 加 `load_combo_5d_today` 单测（mock cache 验 rank 顺序 + filtered 跳 ST/920）
- T9: 手动跑 `load_combo_5d_today()` 最新日，验 top-20 合理（小盘+涨得多+高开）
- T10: 回测复现引用 `_audit_combo_deep/r12`（不重写，已有）

## 取舍

- **Option A（piggyback cron）非 B（新 executor）**：KISS + 避 seed.py+executors/__init__+test 三处同步坑（memory `scheduler-executor-test-registry-pattern`）
- **mode=filtered 默认**（跳 ST+920 实盘安全）vs basic（复现回测 universe）—— live 用 filtered，universe 略异于回测 edge 略变，caveat 标 skill
- **weight 0.5 非 1.0**：test-set-selection 偏差（spec §7.1），60天前向是真 OOS
- **nostop**：stop 未测，先冻结回测口径，stop 留回溯优化
- **次日开盘入场**：实盘可执行（回测 close-to-close 口径微调，alpha +1.8% 容错）
- **基准用 net +2.06%**（非 raw +2.52% 或 alpha +1.61%）：live net_pnl 对比 net 基准 apples-to-apples（都扣成本）
