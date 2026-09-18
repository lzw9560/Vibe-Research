# S218 — 投研参考交付系统（验证→可行动参考→收益闭环）

> 状态：spec（2026-09-18）。里程碑 freeze 已解（consecutive_relay forward-OOS 有答案）。本 spec 是"验证产出接成可行动参考"的交付层——不是新验证机器，是把 validated edge（consecutive_relay + 后续再验的）包装成用户能照着做的参考。
> 触发：用户 2026-09-18 纠正"process theater 不产收益"+ 要"通过研究验证获得实际收益，给用户正确的投研参考"。

## 问题
§44 验证产出 verdict + cap（抽象数），没接成"可行动参考"——×0.75 是数不是"今日哪些接力股、怎么进、怎么出、风险多大"。验证→参考→收益闭环断了。

## 目标（5 组件，各复用现有基建，都要实现）
1. **每日信号报告**：scheduled task，每日盘后产 consecutive_relay 信号报告——lbc≥2 bull regime picks + 入场（D 收盘买）/出场（D+1 开盘卖）+ edge（+1.04% 衰减中）+ 胜率（52.7% 薄）+ 仓位（75%）+ 风险（gap-down 一字跌停 1.1%）→ UI + 持久记录。
2. **实时报警**：intraday 监控信号触发（涨停封板 lbc≥2 + bull regime）→ Feishu/notify 实时 alert。
3. **关键点位决策通知**：D 收盘入场通知（"这些股今日收盘买"）/ D+1 开盘出场通知（"这些开盘卖"）/ gap-down >3% 止损通知——time-triggered。
4. **dashboard 强化**：trade-desk-cockpit（S179）加"validated edge 信号"卡——当前信号 + 验证状态（validated/证否/未验）+ 历史战绩 + 衰减轨迹。
5. **阶段性汇总复盘**：周度复盘信号实际表现（edge hold？用户照着做的收益？decay 恶化？）→ feed 回验证（调 cap / 再验证否战法）。

## 受影响文件
- `tools/signal_report.py`（新）：每日信号报告生成器（复用 pre_limitup_scanner.scan_consecutive_relay + compute_regime_labels + evaluation.lift_for_arm）。
- `scheduler/scheduled_tasks.py` + `scheduler/executors/`：新 task types（daily_report / intraday_alert / keypoint_notify / weekly_review）。
- `routers/`：新 endpoint（GET /api/signals/daily + /api/signals/status）。
- `frontend/`：trade-desk-cockpit 加 validated-edge 信号卡 + 信号状态。
- 复用：consecutive_relay arm（S211 journal_recorder）+ S101 Feishu notify + S179 trade-desk-cockpit + S183 胜率曲线 + scheduled_tasks cron 框架。

## 验收
- 每日盘后出报告："今日 consecutive_relay N 只可做（code/name + 入场价/出场价预估 + edge/胜率/仓位/风险），M 只别碰（一字板/非 bull regime）"。
- 实时：lbc≥2 涨停封板 + bull regime 触发 Feishu alert。
- 关键点位：D 收盘（15:00）入场通知 + D+1 开盘（09:30）出场通知 + gap-down >3% 止损通知。
- dashboard：trade-desk-cockpit 显示当前信号 + 验证状态 + 历史战绩 + 衰减轨迹。
- 周度复盘：本周信号实际表现 + cap/验证调整建议。

## 合规自查（弱合规——私人助理，给方向性参考+风险标注，用户最终决策）
- 不臆造：信号来自现成 scanner + regime + lift_for_arm，报告标 edge/胜率/衰减/风险。
- 私有数据隔离：信号记录在 .vibe-research/（不进 git）。
- 防封：scanner 复用 em_get + baostock（不裸调）。
- 不代客决策：给参考 + 风险标注，用户最终拍板做不做。

## 实现顺序（每组件 commit + review）
1. 每日信号报告（最直接产收益——用户能立刻照着做）← 先做
2. 关键点位决策通知（D 收盘入场 / D+1 开盘出场 / gap-down 止损）
3. dashboard 强化（信号卡）
4. 实时报警（intraday Feishu alert）
5. 阶段性汇总复盘（周度）

## 关联
- [[consecutive-relay-chrono-oos-supporting]]：唯一 validated edge，每日信号的来源。
- [[process-theater-over-returns-and-§44-not-ground-truth]]：本 spec 是对那纠正的响应——验证→可行动参考→收益。
- [[milestone-2026-09-18-pivot]]：freeze 解后转"验证唯一发现→交付参考"。
