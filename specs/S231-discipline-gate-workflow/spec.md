# Spec: S231 — 打板纪律门禁工作流闭环

> 状态：草案 | 日期：2026-09-29 | 分级：medium（风控工具非 edge 基建，接线为主）
> 作者：claude
> 关联：S229（§44 v3）、[[consecutive-relay-falsified-2026-09-23]]、[[edge-exhaustive-5batch-2026-09-28]]、[[investment-expert-r2-2026-09-28]]、[[audit-2026-09-26-v5]]

## 1. 问题 / 目标

项目 consecutive_relay 已 definitive falsified（真 edge -1.66% p=1.0 n_test 89/65≥60），5 批搜索穷尽 300+ 候选 0 alpha，cap=0 ARCHIVED hardstop。但用户需要**打板纪律门禁**——在无 edge 前提下，告诉你"什么时候别打"+"环境达标时小仓位试错条件"。

**目标**：建打板纪律门禁工作流闭环——7 条件门禁（C1-C7）+ 5 Stage 闭环（盘前判断→仓位→入场→退出→盘后归因回灌）+ 飞书通知 + cron 每日触发。

**定位声明（最高优先级）**：这是**风控/纪律/信息聚合工具，非 edge 基建**。叠在 cap=0 hardstop 之上，只读现有数据源，不创造 alpha、不输出买卖标的、不重建 consecutive_relay 证否基建。措辞锁定"纪律门禁"（discipline gate）非"打板时机"（后者暗示交易）。

## 2. 背景

- cap=0 ARCHIVED（evaluation.py:89-103）：consecutive_relay falsified，weight_multiplier=0.0，regime_caps 全 0
- 4 cron 推送 cap=0 guard 已接线（signals.py: daily_report/keypoint_notify/weekly_review/regime_flip_notify）
- sentiment_weather composite≥75 晴天判断已建（:54-64）
- execution_model kill_switch 已建（:116 上证<-3%/创业板<-4%）
- intraday_loss_breaker + drawdown_breaker + risk_rules 已建（risk sizing 承重墙）
- vr_paths _A_SHARE_HOLIDAYS 节假日集已建
- 用户接受"风控工具非 edge 基建"定位（2026-09-29 多轮专家共识）

## 3. 需求清单

- [ ] R1 `evaluate_discipline_gate(date)` 纯函数：cap=0 → terminal BLOCK；cap>0 → 评估 C1-C7 各 pass/fail/missing，OR-BLOCK 逻辑（任一红线 fail → BLOCK，全绿 → PASS，其余 → CAUTION）
- [ ] R2 7 条件门禁（C1-C7）：
  - C1 composite≥75 晴天（sentiment_weather）
  - C2 STI 连续 3 个交易日>50（sti_timeline dimension_score）
  - C3 promotion_rate>15%（sti_timeline dimension_promotion_rate）
  - C4 advance_decline_ratio>1.0（sti_timeline dimension_advance_decline_ratio）
  - C5 跌停<涨停（sti_timeline dimension_limit_down/up_count）
  - C6 kill switch 未触发（execution_model:116 上证<-3%/创业板<-4%）
  - C7 节前禁入（vr_paths 连续≥3 自然日休市）
- [ ] R3 5 Stage 闭环：盘前判断 → 仓位（cap>0 激活）→ 入场记录（复用 journal.add_trade）→ 盘中退出（复用 keypoint_notify cron 09:30）→ 盘后归因（复用 loss_breaker/DrawdownBreaker/weekly_review 回灌 Stage 1）
- [ ] R4 `render_discipline_report(verdict)` 人话报告：市场天气 + 7 条件 pass/fail + 纪律提醒 + 不交易理由
- [ ] R5 cron executor `discipline_gate_morning(payload)`：09:15 工作日触发（盘前门禁）
- [ ] R6 飞书通知：cap=0 推"市场天气+不交易提醒"；时机打开推"窗口打开+7 条件"；关闭推"当前不打+哪条 fail"；节前推"绝对禁入"；假恢复 STI>15 推"假恢复风险"
- [ ] R7 持久化：`.vibe-research/discipline_gate/{date}_verdict.json`
- [ ] R8 假恢复陷阱识别：STI 30 天暴跌→反弹→再暴跌模式，反弹>15 不追

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/discipline_gate.py` | **新增**：evaluate_discipline_gate(date) + render_discipline_report(verdict) 纯函数 |
| `backend/scheduler/executors/discipline_gate.py` | **新增**：discipline_gate_morning(payload) cron executor |
| `backend/scheduler/executors/__init__.py` | 注册 executor（:61 `_executors` dict）|
| `backend/scheduler/seed.py` | 新增 discipline_gate_morning cron seed（09:15 工作日）|
| `.vibe-research/discipline_gate/` | **新目录**：{date}_verdict.json 持久化 |

**复用现有（0 改动，只读）**：evaluation.py（lift_for_arm cap=0）+ signals.py（_send_text_notification + 4 cron guard pattern）+ sentiment_weather.py（compute_weather_snapshot + composite≥75）+ execution_model.py（kill_switch）+ signal_report.py（_check_sentiment_hardstop pattern + _build_disclaimers）+ at_risk.py（honest_risk_labels）+ intraday_loss_breaker.py + drawdown_breaker.py + risk_rules.py（loss_breaker_enforce 回灌）+ vr_paths.py（_A_SHARE_HOLIDAYS/is_trading_day）+ cron_fire_audit.py（@fire_receipt）+ notification_service.py

## 5. 设计方案

### 5 Stage 闭环数据流

```
数据源层（全已建，0 新数据源）
  sti_timeline + sentiment_weather + execution_model + evaluation.py + vr_paths
  ↓
Stage 1: 盘前门禁判断（新增 evaluate_discipline_gate）
  cap=0? → terminal BLOCK（短路，不评估 C1-C7）
  cap>0 → 评估 C1-C7 各 pass/fail/missing，OR-BLOCK
  输出 verdict{status, cap, conditions[], merged_light, reasons[]}
  持久化 .vibe-research/discipline_gate/{date}_verdict.json
  ↓
Stage 2: 仓位（cap>0 时激活，当前休眠）
  final_size = arm×portfolio×lift×intraday×discipline_mult（第5层新增）
  约束: 单票≤1% / 总≤5%-已用 / ×env 乘数
  ↓
Stage 3: 入场记录（复用 journal.add_trade，用户手动决策，系统不自动下单）
  ↓
Stage 4: 盘中退出（复用 keypoint_notify exit cron 09:30，已存在）
  ↓
Stage 5: 盘后归因（复用 loss_breaker_enforce 17:35 + DrawdownBreaker + weekly_review）
  回灌 Stage 1: cooldown 活跃→is_blocked_new=True→次日门禁直接 BLOCK（闭环物理实现）
```

### 7 条件门禁逻辑

- **terminal master switch**：cap=0（consecutive_relay falsified）→ 短路 BLOCK
- **C1-C7 OR-BLOCK**：任一红线 fail → BLOCK；全绿 → PASS；其余 → CAUTION
- **C6 kill switch 通知级非阻断**（CAUTION 非 BLOCK——kill switch 是市场级警报非纪律门禁）
- **C7 节前禁入**：09-30 买→10-08 卖（T+1=8 天锁仓）绝对 BLOCK

### 飞书通知触发

- **cap=0（当前）**：每日推"市场天气报告 + 不交易提醒"（纪律提醒非交易信号，复用 cap=0 guard pattern 反转用——cap=0 也推非跳过）
- **时机打开（cap>0 + 7 条件全过）**：推"打板窗口打开" + 7 条件详情
- **时机关闭（任一 fail）**：每日报告"当前不打 + 哪条 fail"
- **节前禁入**：09-30 推"绝对禁入 T+1=8 天锁仓"
- **假恢复陷阱**：STI 反弹>15 推"假恢复风险"（不追不加仓不改变空仓判断）

## 6. 验收标准

- [ ] A1 evaluate_discipline_gate(date) 返 verdict{status, cap, conditions[], reasons[]}
- [ ] A2 cap=0 时 terminal BLOCK（短路，不评估 C1-C7）
- [ ] A3 C1-C7 各条件 pass/fail/missing 判断正确（数据源读对）
- [ ] A4 OR-BLOCK 逻辑：任一红线 fail → BLOCK；全绿 → PASS；其余 → CAUTION
- [ ] A5 render_discipline_report 人话报告含市场天气 + 7 条件 + 不交易理由
- [ ] A6 cron discipline_gate_morning 09:15 工作日触发
- [ ] A7 飞书通知发送（cap=0 推纪律提醒 + 时机变化推 + 节前推禁入）
- [ ] A8 持久化 {date}_verdict.json
- [ ] A9 假恢复陷阱识别（STI 30 天暴跌→反弹→再暴跌 + 反弹>15 标风险）
- [ ] A10 盘后归因回灌 Stage 1（cooldown 活跃→次日 BLOCK）
- [ ] A11 pytest + full suite green

## 7. 合规与工程底线自查

- [ ] 研判/推荐属系统能力（§1.1），用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」
- [ ] 判断可复现：复用现有数据源（sti_timeline/sentiment_weather/execution_model），禁臆造/心算
- [ ] 用户私有数据未进 git（.vibe-research/discipline_gate/ gitignored）
- [ ] 无新增东财端点（不涉 em_get）
- [ ] **定位诚实**：风控/纪律工具非 edge 基建——不创造 alpha，只读现有数据源，措辞"纪律门禁"非"打板时机"

## 7.1 §44 v3 anti-fake-edge sanity

- [ ] R1 entry close 涨停价审：本 spec **不涉及选股 entry**（纪律门禁非选股），不适用
- [ ] R3 exit 一字跌停审：不涉及 exit（复用现有 keypoint_notify）
- [ ] R4 涨停 vs 未涨停对比：本 spec 是 regime 过滤非选股 edge，不适用
- [ ] R2 窗口语义标注：本 spec 是"纪律门禁"（告诉你什么时候别打）非"打板 edge"，措辞锁定
- [ ] A5 回归测试：cap=0 时 terminal BLOCK（验证不评估 C1-C7）

## 8. 测试计划

- `pytest tests/test_discipline_gate.py`（新增）：
  - cap=0 terminal BLOCK
  - C1-C7 各 pass/fail/missing
  - OR-BLOCK 逻辑
  - 节前禁入（09-30）
  - 假恢复陷阱（STI 反弹>15）
  - render_discipline_report 格式
- `pytest -m "not live"` full suite green
- cron fire 验证（09:15 触发 + 飞书通知发送）

## 9. 风险与回滚

- **爆炸半径小**：新增 2 文件（纯函数 + cron executor）+ 3 接线（executors dict + seed + 目录），复用 20+ 现有，不改现有代码
- **回滚**：删 discipline_gate.py + executors 注册 + seed + 目录
- **cap=0 恒 BLOCK**：当前 consecutive_relay falsified，门禁恒拦截，每日产出"市场天气+不交易提醒"——无交易风险
- **风控工具非 edge**：不创造 alpha，不输出买卖标的，只读现有数据源——符合投研看板定位
