# S213 tasks — arm 级 kill switch 框架

## T1 arm_status 表 + query/set
- [x] T1.1 arm_status 表 schema（arm PK, is_active, weight_override, kill_reason, killed_at）
- [x] T1.2 query_arm_status 方法（无记录返 None = active 走 registry 默认）
- [x] T1.3 set_arm_status 方法（upsert，ON CONFLICT 更新所有字段）
- [x] T1.4 test: 表建 + query None 默认 + upsert 覆盖 + weight_override

## T2 lift_for_arm 读 override
- [x] T2.1 lift_for_arm 加读 arm_status override（优先于 registry）
- [x] T2.2 is_active=False → 返 0.0 停交易
- [x] T2.3 weight_override 设值 → 优先于 registry
- [x] T2.4 默认 None 走 registry（backward compat，不改当前 sizing）
- [x] T2.5 db error fallback registry（不阻塞，backward compat）
- [x] T2.6 test: override 优先 + is_active=False 返 0.0 + 默认走 registry + db error fallback

## T3 验收
- [x] T3.1 8 test green（test_s213_arm_kill_framework）
- [x] T3.2 59 相关 test green（S213 + S211 + engine）
- [x] T3.3 框架不改当前 sizing（override 默认 None 走 registry，consecutive_relay bull ×0.5 不变）

## T4 enforce（defer 60 天后 SDD）
- [ ] T4.1 kill criteria auto-write arm_status（consecutive_loss>=5 → is_active=False）
- [ ] T4.2 monitor endpoint enforce toggle（报告 + 60 天后 auto enforce）
- [ ] T4.3 60 天 forward OOS 数据够后 flip 开关

## 状态
- 框架 plumbing DONE（2026-09-17，commit 未单独标——含 1b9a4c2 后续）。enforce defer 60 天后。
