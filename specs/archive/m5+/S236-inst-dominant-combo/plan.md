# Plan: S236 — 机构资金延续组合实现方案

> 关联：spec.md（S236）

## 实现顺序（依赖序）

### P0: R6 baostock 假熔断正式修复（数据管道基础）
- T1: circuit_breaker.py 加 reset() 方法（强制重置 CLOSED，解除 HALF_OPEN 试探名额耗尽卡死）
- T2: baostock_src.py ensure_login 熔断快速失败前直连验证 bs.login()，成功→reset+复用login，失败→维持快速失败
- T3: 测试假熔断场景（手动 OPEN→HALF_OPEN 试探名额耗尽→ensure_login 直连验证解除）

### P1: R2/R3 commander 集成组合候选
- T4: commander_runner.py load_inst_dominant_today 加 mode 参数（basic= >80%+top6 / advanced= +追高+外资+中价20-100）
- T5: _audit_lhb_inst_full.py 加 top6 口径 + 进阶版因子分层回测函数（复用本次会话脚本）
- T6: 单测 load_inst_dominant_today mode=basic/advanced

### P2: R5 §44 R3 60天复验机制（需用户决策阈值）
- T7: trade_journal 查询累积收益 vs 回测 mean 基准（基础版+0.457% / 进阶版+0.879%）
- T8: 衰减阈值 + weight 降权规则定义（⚠需用户决策：衰减多少→weight多少？60天怎么定义？）
- T9: scheduled_tasks 加 inst_dominant 60天复验 cron（衰减→降权/停）

### P3: R7/R8 已完成
- 龙虎榜 backfill 每日补全（datacenter 通，已验证）
- 飞书通知 send_feishu（已验证可用）

## 取舍
- R6 先做：数据管道稳定是一切基础，本次会话遇2次假熔断
- R5 需用户决策：衰减阈值/weight 规则是"技术路线分叉+重大权衡"，推进到 T8 停
- 进阶版 post-hoc：复验前 weight=0.5，复验通过→1.0（spec 已定）
- 不选"追高+高价>50"双因子（mean+0.940%最高）——高价买不满1手，实操受限
