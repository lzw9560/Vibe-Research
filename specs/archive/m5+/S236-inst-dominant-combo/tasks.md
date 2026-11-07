# Tasks: S236

> 关联：spec.md / plan.md

- [x] T0a: skill SKILL.md 落地（基础+进阶，`~/.claude/skills/inst-dominant-combo/`）
- [x] T0b: spec S236 草案
- [x] T0c: trade_journal inst_dominant arm 建库（is_active=1 weight=1.0）+ 10-09 top6 记录（6条 signal）
- [x] T0d: 飞书 send_feishu 战法总结（已发）
- [x] T0e: memory inst-dominant-combo-tradable 更新（进阶版+命名修正+落地）

## P0 R6 baostock 假熔断修复
- [x] T1: circuit_breaker.py 加 reset() 方法
- [x] T2: baostock_src.py ensure_login 熔断时直连验证+reset
- [x] T3: 测试假熔断解除（逻辑验证正确：HALF_OPEN名额耗尽→直连验证→成功reset/失败真熔断）
- [ ] T3a: ⚠baostock 黑名单用户（10001011）——需用户决策（联系管理员/换源/忽略用hithink）

## P1 R2/R3 commander 集成
- [x] T4: commander_runner.load_inst_dominant_today 加 mode=basic/advanced（>80%纯化+top6+因子过滤）
- [x] T5: _audit_lhb_inst_full 加 compute_nostop_return + audit_top6_combo（固化 top6+因子分层回测，测试复现 mean+0.457%/+0.875%）
- [x] T6: 测试 mode basic/advanced（10-08 basic top6全跌抄底 / advanced 出2只涨的603906/603538）
- [ ] T6a: ⚠诚实标注：用户实盘口径=basic top6主观调整版（跳高价+剔退潮递补），回测未测此具体口径

## P2 R5 §44 R3 复验（保守规则，用户2026-10-09拍板）
- [x] T7: trade_journal 累积收益查询（inst_dominant_replay_check.py 内）
- [x] T8: 保守规则定（<回测70%→weight 0.5；<30%或<0→停；60交易日首次复验门槛）
- [x] T9a: 复验脚本 tools/inst_dominant_replay_check.py（测试通过，60天门槛保护）
- [ ] T9b: scheduled_tasks cron 接入（改 scheduler/seed.py + executor + 同步 test_task_executor/test_regression_bugs 两处，memory scheduler-executor-test-registry-pattern 警告）——待 inst_dominant 累积接近60天（约12月初）接入

## 验收（spec §6）
- [ ] A1-A8
