# Tasks: S237

> 关联：spec.md / plan.md / 同模式 S236

- [x] T0a: skill SKILL.md 落地（`~/.claude/skills/a-group-t10-combo/`）
- [x] T0b: spec S237 草案
- [x] T0c: trade_journal a_group_t10 arm 建库（is_active=1 weight=1.0）
- [x] T0d: memory a-group-t10-combo-tradable-2026-10-09 + MEMORY.md pointer
- [x] T0e: 飞书 A组 T+10 战法总结发送

## P1 R2 commander 集成
- [x] T1: commander_runner.load_a_group_today 加 mode=basic/combo（跳920北交所）
- [x] T2: _audit_a_group_t10_r6_stop 加 compute_t10_nostop + audit_a_group_combo（复现 mean+0.989% WR53.6%）
- [x] T3: 测试 mode basic/combo（10-08 basic top5含920025 / combo 跳920剩4只）

## P2 R5 §44 R3 复验（复用 S236 通用化）
- [x] T4: inst_dominant_replay_check.py 通用化（arm 参数，支持 inst_dominant/a_group_t10）
- [x] T5: 保守规则（同 S236：<70%→weight 0.5；<30%或<0→停；60天门槛）
- [x] T6: 测试两 arm（inst_dominant 6 signals 1天<60只提醒 / a_group_t10 0 signal 待10-13买）
- [ ] T7: 60天复验实跑（待12月初，inst_dominant + a_group_t10 都跑）

## P3 待办
- [ ] T8: S236 T9b cron 接入（待12月，改 scheduler/seed.py + executor + 同步 test，memory scheduler-executor-test-registry-pattern 警告）
- [ ] T9: 10-13 操作（用户：inst_dominant 收盘卖 + A组 open 买 002074/301689/002962）
- [ ] T10: 10-13 盘后跑下个 inst_dominant + A组候选

## 验收（spec §6）
- [x] A1: skill 落地
- [x] A2: 组合口径回测复现 mean+0.989% WR53.6%
- [x] A3: trade_journal a_group_t10 arm 记录可读写
- [ ] A4: §44 R3 60天复验（待12月）
