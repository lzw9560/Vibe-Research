# S213 — arm 级 kill switch 框架

## 问题
consecutive_relay arm 通电生产（50 股/笔 ×0.5 provisional），但无 arm 级 kill switch。
`lift_for_arm`（evaluation.py:283）只读 dimension 级 lift_override（get_effective_dimension），
无 arm 级 override。60 天 forward OOS 后要 enforce kill（auto-pause 连亏臂）需 arm 级 override。

当前报告型 monitor（/api/journal/arm-forward-monitor，commit 0fed616）只报告 kill criteria
（consecutive_loss>=5 / winrate<50 / days<60），不 enforce。要 enforce 需 arm 级 override
让 lift_for_arm 读到 kill 状态返 0.0（停交易）。

## 目标
建 arm 级 override 框架（plumbing）——**不 enforce，只建框架**：
- arm_status 表（arm PK, is_active, weight_override, kill_reason, killed_at）
- lift_for_arm 读 arm_status override（优先于 registry，默认 None 走 registry 不变）
- monitor endpoint 报告 is_active 状态（验证 lift_for_arm 能读到 arm_status）

enforce（auto-pause flip 开关）defer 60 天 forward OOS 数据后——届时 kill criteria 触发
写 arm_status.is_active=False，lift_for_arm 读到返 0.0 停交易。

## 受影响文件
- engine/trade_journal.py：arm_status 表 schema + query_arm_status / set_arm_status 方法
- candidate_funnel/evaluation.py：lift_for_arm 加读 arm_status override（优先于 registry）
- routers/journal.py：monitor endpoint 报告 is_active 状态
- tests/test_s213_arm_kill_framework.py：override 优先 + 默认 None 走 registry + is_active=False 返 0.0

## 验收
- arm_status 表建（schema + query/set 方法）
- lift_for_arm 读 arm_status override（默认 None 走 registry，backward compat；override 设值时优先）
- test 验：override=None 走 registry（不变）+ is_active=False 返 0.0 + weight_override 设值时优先
- monitor endpoint 报告 is_active 状态
- 全相关 test green

## 合规自查（弱合规）
- 不臆造：arm_status 表存真实 kill 状态，不编造
- 私有数据隔离：arm_status 在 .vibe-research/trade_journal.db（不进 git）
- 防封：不涉 em_get（arm_status 是本地 DB）
- 交易信号 sizing 改动：lift_for_arm 读 override 影响 sizing——但 override 默认 None 走 registry 不变，
  enforce defer 60 天后，框架 plumbing 不改当前 sizing 行为

## 范围
- 不做：enforce auto-pause（defer 60 天后 SDD）+ kill criteria auto-write arm_status（defer）
- 做：arm_status 表 + lift_for_arm 读 override（plumbing）+ monitor 报告 is_active

## 状态
- 草案（2026-09-17，第七轮多轮闭环）
