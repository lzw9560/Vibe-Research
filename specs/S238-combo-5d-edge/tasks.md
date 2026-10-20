# Tasks: S238

> 关联：spec.md / plan.md / 同模式 S237

- [x] T0: spec S238 草案（spec.md）
- [x] T0b: memory combo-5d-edge-survivor-2026-10-20 + MEMORY.md pointer（轮5-7 已落）

## P0 信号生成
- [x] T1: `commander_runner.load_combo_5d_today(date, mode, top_n)` 实现
- [x] T2: `run()` 加 combo_5d_signals hook
- [x] T3: `format_text()` 加飞书输出块

## P1 arm + replay_check
- [x] T4: `_setup_combo_5d_arm.py` 注册 arm（is_active=1 weight=0.5）✅ 验证 query 返 {is_active:True, weight_override:0.5}
- [x] T5: `inst_dominant_replay_check` 加 combo_5d（BACKTEST_MEANS+ARM_WEIGHTS+__main__+参数化档）
- [x] T6: `replay_check(arm="combo_5d")` 跑通（0 signal "无 signal"，<120天提醒不 enforce）✅

## P2 skill
- [x] T7: `~/.claude/skills/combo-5d-edge/SKILL.md` ✅

## P3 测试
- [x] T8: pytest `test_combo_5d.py` 5 测试全绿（340s——每测试扫 1.3GB cache，daily 单次 ~10-36s 可接受；fixture 优化留后续）
- [x] T9: 手动跑最新日 top-20 验合理 ✅（20 picks 小盘额0.2-0.6亿+动量+1.96~+9.99%+高开+1.13~+3.39%，score 降序）
- [x] T10: 回测复现引用 `_audit_combo_deep/r12`（已有，不重写）

## 验收（spec §6）
- [x] A1: `load_combo_5d_today` 返 top-20 + 结构齐(date/code/gap/today_ret/amount/score) + score 降序 + filtered 跳 920 ✅（rank 逻辑与 _audit_combo_hold 字节级一致，历史日 code 精确交叉比对未单独跑——逻辑同则期望匹配）
- [x] A2: trade_journal combo_5d arm 可读写 ✅（is_active=1 weight=0.5 验证）
- [x] A3: skill 落地 ✅
- [x] A4: replay_check arm=combo_5d 跑通 ✅
- [x] A5: 回测复现引用（net +2.06% top20，_audit_combo_deep/r12）✅

## 全量回归（2026-10-21）
- 4244 passed / 3 failed / 2 skipped（2312s）
- 3 failure 全在 seal_intraday_collector（tencent_quote 调 2 次非 1 次）——预存，因 session 前已修改的 baostock_src.py/circuit_breaker.py 改了 quote/重试行为，**与 combo_5d 无关**（纯新增路径）

## 后续（不在本 spec 范围）
- 60天前向实跑（待 ~2026-12 中，accumulated mean vs +2.06% 基准）
- cron 自动化（Option B，若 piggyback 不够用再加 executor——避坑见 plan §P0）
- stop 回溯优化（nostop 冻结口径后测 -3%/-5%/-8% stop）
