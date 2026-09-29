# Spec: S231 — 打板纪律门禁工作流闭环

> 状态：草案（Stage 1 已实现 / Stage 2-5 DEFERRED）| 日期：2026-09-29（降标 2026-09-30）| 分级：medium（风控工具非 edge 基建，接线为主）
> 作者：claude
> 关联：S229（§44 v3）、[[consecutive-relay-falsified-2026-09-23]]、[[edge-exhaustive-5batch-2026-09-28]]、[[investment-expert-r2-2026-09-28]]、[[audit-2026-09-26-v5]]
>
> **2026-09-30 降标**：10-agent 对抗审查确认 spec 原"5 Stage 闭环"是设计叙事非实现范围——仅 Stage 1 端到端通电，Stage 2-5 全断（discipline_mult 零编码 / journal 不触发 / keypoint_notify 不读 verdict / cooldown 回灌未接线）。cap=0 三重锁死不可自动恢复 + 5 批穷尽 300+ 候选 0 alpha → 解冻结构性不可能 → Stage 2-5 永久 dead path。R3/A10 标 DEFERRED，§5 数据流图按实际状态重标。详见 §5/§6。

## 1. 问题 / 目标

项目 consecutive_relay 已 definitive falsified（真 edge -1.66% p=1.0 n_test 89/65≥60），5 批搜索穷尽 300+ 候选 0 alpha，cap=0 ARCHIVED hardstop。但用户需要**打板纪律门禁**——在无 edge 前提下，告诉你"什么时候别打"+"环境达标时小仓位试错条件"。

**目标**：建打板纪律门禁工作流闭环——7 条件门禁（C1-C7）+ 5 Stage 闭环（盘前判断→仓位→入场→退出→盘后归因回灌）+ 飞书通知 + cron 每日触发。

> **2026-09-30 降标**：5 Stage 闭环中**仅 Stage 1（盘前门禁）端到端通电并交付**。Stage 2-5 因 cap=0 三重锁死 + edge 结构性无（5 批穷尽 300+ 候选 0 alpha）成为永久 dead path，标 DEFERRED（详见 §5/§6）。完整 5 Stage 闭环须等"发现新 edge 解冻 cap>0"——当前结构性不可能。

**定位声明（最高优先级）**：这是**风控/纪律/信息聚合工具，非 edge 基建**。叠在 cap=0 hardstop 之上，只读现有数据源，不创造 alpha、不输出买卖标的、不重建 consecutive_relay 证否基建。措辞锁定"纪律门禁"（discipline gate）非"打板时机"（后者暗示交易）。

> **cap=0 下的诚实范围**：当前 consecutive_relay definitive falsified（真 edge -1.66% p=1.0 n_test 89/65≥60），cap=0 terminal BLOCK 短路，每日产出"市场天气 + 不交易提醒"。Stage 2-5 在 cap=0 下永不触发——这是约束必然结果非偷工，**没有可交易 edge 就没有打板工作流可接**。

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
- [ ] R3 ~~5 Stage 闭环~~ **DEFERRED**（2026-09-30 降标）：原设计盘前判断→仓位→入场→退出→盘后归因回灌。**实际仅 Stage 1 端到端通电**。Stage 2-5 因 cap=0 三重锁死 + edge 结构性无成永久 dead path。详见 §5 各 Stage 实际状态。完整闭环须解冻后补（解冻条件=发现新 edge，当前结构性不可能）。
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

### 5 Stage 数据流（2026-09-30 按实际状态重标）

> 原 spec 画"5 Stage 闭环物理实现"是 over-claim——10-agent 对抗审查确认仅 Stage 1 端到端通电，Stage 2-5 全断。此处按实际状态重标，删"闭环物理实现"叙事。

```
数据源层（全已建，0 新数据源）
  sti_timeline + sentiment_weather + execution_model + evaluation.py + vr_paths
  ↓
Stage 1: 盘前门禁判断 ✅ DONE（已交付）
  cap=0? → terminal BLOCK（短路，不评估 C1-C7）
  cap>0 → 评估 C1-C7 各 pass/fail/missing，OR-BLOCK
  输出 verdict{status, cap, conditions[], merged_light, reasons[]}
  持久化 .vibe-research/discipline_gate/{date}_verdict.json
  ↓（verdict 产出后无下游消费者——Stage 2-5 全断）
Stage 2: 仓位 ❌ DEFERRED（discipline_mult 第5层零编码）
  spec 设计：final_size = arm×portfolio×lift×intraday×discipline_mult（第5层新增）
  实际：生产 sizing 是 4 层（paper_portfolio.py:62 arm×arm_mult×port_mult×lift×intraday_mult）
        discipline_mult 全仓 grep 零编码；且 risk_rules.py:565 "⛔ 不碰 final_size sizing——
        生产 sizing 是否复合 intraday_mult 由用户 review 决定"——连第4层都没接，跳建第5层无依据
  延后理由：违 risk_rules.py:565 显式禁止 + §1.3 冻结新基建；cap=0 下 moot（lift=0 主导 size=0）
  ↓（门禁 verdict 不喂 sizing——gate 与 sizing 解耦）
Stage 3: 入场记录 ⚠️ 设计本就不自动（非断线）
  spec 设计：复用 journal.add_trade，用户手动决策，系统不自动下单
  实际：journal.add_trade 存在（journal.py:473），唯一调用方是手动 REST（POST /api/journal/trades）
        门禁 executor 不调 add_trade——这是 spec 自己写"用户手动不自动下单"的设计意图
  状态：recorder≠selector 不违冻结；cap=0 恒 BLOCK 下无交易可记
  ↓
Stage 4: 盘中退出 ❌ 不读门禁 verdict（读已证否 consecutive_relay）
  spec 设计：复用 keypoint_notify exit cron 09:30
  实际：keypoint_notify 存在（signals.py:278）但读 get_consecutive_relay_signals（已 definitive falsified）
        非读门禁 verdict；有自己的 cap=0 guard（signals.py:320-324 巧合非接线）
  状态：pre-existing 独立 cron，与门禁完全解耦；cap=0 下连飞书都不推
  ↓
Stage 5: 盘后归因回灌 ❌ 闭环断裂（cooldown 产出但门禁不读）
  spec 设计：复用 loss_breaker_enforce 17:35 + DrawdownBreaker + weekly_review
            回灌 Stage 1: cooldown 活跃→is_blocked_new=True→次日门禁直接 BLOCK
  实际：loss_breaker_enforce 产出并持久化 cooldown（risk_rules.py:517-536 _load/_save_cooldown）
        但 evaluate_discipline_gate 对 cooldown/is_blocked grep 零命中——门禁不读 cooldown
        ❌ 原 spec "闭环物理实现"是 over-claim，回灌未接线
  延后理由：Stage 5 回灌本身不违冻结（spec §4 把 risk_rules.py 列"复用只读"，读 _load_cooldown 正此范畴）
            延后因 cap=0 下 moot（cap=0 短路在 cooldown 检查之前，回灌不改 BLOCK 结果）
            + 解冻结构性不可能（dead path 永不执行）
```

**verdict 消费现状**：discipline_gate_morning 产出 verdict→持久化 json→飞书推报告→return。下游消费者（Stage 2 sizing / Stage 4 exit / Stage 5 attribution）grep 全空——**verdict 产出即终点**。这是用户"为什么只有门禁"的物理根因。

**cap>0 解冻可行性**：cap=0 三重锁死均不可自动恢复——① arm_status kill（is_active=False，set_arm_status 生产零调用，须手动 DB 写）② frozen registry regime_caps 全 0.0（须改源码）③ override 永不自动写 consecutive_relay（apply_revalidation 跳过）。+ 5 批穷尽 300+ 候选 0 alpha → A 股散户可交易 alpha edge 结构性无 → 解冻永不发生 → Stage 2-5 + C1-C7 分支（discipline_gate.py:120-228）均为永久 dead code。

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

- [x] A1 evaluate_discipline_gate(date) 返 verdict{status, cap, conditions[], reasons[]}
- [x] A2 cap=0 时 terminal BLOCK（短路，不评估 C1-C7）
- [x] A3 C1-C7 各条件 pass/fail/missing 判断正确（数据源读对）
- [x] A4 OR-BLOCK 逻辑：任一红线 fail → BLOCK；全绿 → PASS；其余 → CAUTION
- [x] A5 render_discipline_report 人话报告含市场天气 + 7 条件 + 不交易理由
- [x] A6 cron discipline_gate_morning 09:15 工作日触发
- [x] A7 飞书通知发送（cap=0 推纪律提醒 + 时机变化推 + 节前推禁入）
- [x] A8 持久化 {date}_verdict.json
- [ ] A9 假恢复陷阱识别（STI 30 天暴跌→反弹→再暴跌 + 反弹>15 标风险）— cap=0 下 dead path，未实现
- [ ] A10 ~~盘后归因回灌 Stage 1（cooldown 活跃→次日 BLOCK）~ → **DEFERRED**（2026-09-30 降标）：回灌未接线（门禁不读 cooldown）。回灌本身不违冻结（spec §4 risk_rules.py 列"复用只读"），延后因 cap=0 下 moot（短路在 cooldown 检查前）+ 解冻结构性不可能。解冻后补：evaluate_discipline_gate 开头读 _load_cooldown→active 则 terminal BLOCK
- [x] A11 pytest + full suite green（4101 passed + 2 已修 b88ed1b）

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
