# Plan: S237 — A组 T+10 组合实现方案

> 关联：spec.md（S237） / 同模式 S236（inst_dominant combo）

## 实现顺序（依赖序）

### P0: 数据管道（复用 S236 R6，已完成）
- baostock 假熔断修复：circuit_breaker.reset() + ensure_login 直连验证（S236 已做，S237 复用）
- baostock 黑名单（10001011）：用户决策忽略用 hithink 多源（不影响：回测用 cache，实时走 hithink）

### P1: R2 commander 集成（已完成）
- T1: commander_runner.load_a_group_today 加 mode=basic/combo（basic=top5 / combo=跳920北交所+top5）
- T2: _audit_a_group_t10_r6_stop 加 compute_t10_nostop + audit_a_group_combo（复现 mean+0.989% WR53.6%）
- T3: 测试 mode basic/combo（10-08 basic top5 / combo 跳920剩4只）

### P2: R5 §44 R3 复验（已完成，复用 S236 通用化脚本）
- T4: inst_dominant_replay_check.py 通用化（加 arm 参数，支持 inst_dominant/a_group_t10）
- T5: 保守规则（同 S236：<70%→weight 0.5；<30%或<0→停；60天门槛）
- T6: 测试两 arm（inst_dominant 1天<60只提醒 / a_group_t10 0 signal 待10-13买）

### P3: R3/R5 配套（已完成）
- trade_journal a_group_t10 arm 建库（is_active=1 weight=1.0）
- 数据缺处理（920北交所跳过，非920但hithink不识如实盘发现跳）

## 取舍
- nostop（-3% stop FAIL mean+0.180% 割反弹有害）
- 持有8天（vs inst_dominant 1天，风险大但 mean 高 +0.989% vs +0.414%）
- 仓位25%（<inst_dominant 30%，8天持有+nostop扛8天控风险）
- 不选 -3% stop（FAIL）；不选更长持有（T+15+ 衰减未测）
