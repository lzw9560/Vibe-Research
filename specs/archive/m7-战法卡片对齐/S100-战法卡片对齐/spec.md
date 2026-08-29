# Spec: S100 — 战法卡片对齐 match 条件（S097 收尾 + fa4514e 阈值同步）

> 状态：✅已实现（2026-08-27）
> 作者：Claude 会话  日期：2026-08-27
> 关联：S097（match 重构，§5.2 条件表已部分过期）、fa4514e（2026-08-27 阈值校准，漏改 docstring/spec/卡片）、S058（卡片创建时点）、S086（strategy_tools 读卡喂 AI 出口）

## 1. 问题 / 目标

S097 重构了 12 战法 `match()` 返回 `StrategyMatchResult`（全量条件 hit/miss/data_unavailable 三态），但 `cards/*.md` 12 张卡片**全部停在 S058/S053 时期未跟上**——卡片经 `backend/ai/tools/strategy_tools.py` 的 `query_strategy_card()` 读出后喂 chat/MCP/CLI 三个 AI 出口，卡片条件与 match 不一致 = AI 基于错误条件给判断，触工程底线「判断须可复现」。

12-agent 审计（2026-08-27）发现 42 处不一致，12/12 全有问题（10 stale_mismatch + 2 minor_drift）。同时发现 `fa4514e`（2026-08-27 阈值校准）改了 first_plate（60/20→40/6）与 end_of_day_sneak（次日溢价率 >40→>15）两个战法的 match 阈值，但**漏改三处**：match docstring（仍写 60/20、>40）、S097 spec §5.2 条件表（仍写 60/20、>40）、卡片（本就缺/错）。

**目标**：以**实际 `match()` 代码为唯一对齐基准**（不是 S097 §5.2——已知 2 处被 fa4514e 改写过期），重写 12 张卡片「入场条件/核心逻辑/退出参数」对齐代码真实条件+阈值+fire_rule；补 fa4514e 漏改的 2 处 docstring + S097 §5.2 修订；补「卡片 vs match 一致性」测试堵 test_s058 只测存在性的盲区。

## 2. 背景

- **卡片喂 AI 出口**：`strategy_tools.py` `query_strategy_card(code)` 读 `cards/<code>.md` 全文返 Markdown，AI 三出口（chat `TOOLS`/MCP `query_strategy_card`/cli_runtime）透明复用。卡片内容直接成 AI 判断依据。
- **registry entry_condition 也喂出口**：`STRATEGY_REGISTRY`（`strategy_funnel_registry.py`，12 项 StrategyConfig dataclass）的 `entry_condition` 字段经 `routers/strategy.py:32` 喂前端策略列表、`limitup_strategy.py:558`、`intraday_coach.py:438` 喂盯盘教练。审计指出 n_shape(:216)/platform_breakout(:234)/pattern_reversal(:304)/break_reseal(:166) 等陈旧（与卡片同漂移）。
- **退出参数 runtime 真值**：`StrategyConfig` 有 `stop_loss_pct/take_profit_pct/max_hold_days/stop_loss_condition/take_profit_condition` 字段，`position_advisor_v2.py:218` 实读。卡片「退出参数」段须与 registry 真值一致；止损基准是**入场价**（`strategy_base.py:332` `entry_price×(1+stop_pct)` + `position_advisor_v2.py:301` pnl 入场基准），非「前日收盘价」。
- **test_s058_strategy_cards.py 盲区**：现仅测卡片存在性（`test_all_cards_exist_for_registry`）+ 风险提醒（`test_card_has_risk_disclaimer`），**不测卡片内容与 match 条件一致性**——这正是 S097 后卡片漂移 14 天无人抓的根因。
- **fa4514e 阈值校准**（2026-08-27 07:20）：first_plate total_score 60→40 / 涨停频次 20→6（分位数支撑：全量 P75/P50）；end_of_day_sneak 次日溢价率 >40→>15（全量 P90=18.9/qualify P25=30.1）。理由：原阈值远超历史 max（涨停频次 max=39/P95=18，阈值 20 几乎无人能过）。**漏改**：match docstring（gene_based.py:28,321）、S097 spec §5.2（仍 60/20、>40）。
- **审计 agent 可信度**：12-agent 审计（glm-5.2）在 first_plate/end_of_day_sneak 两张**照抄 spec §5.2 阈值**（60/20、>40）而非读代码（40/6、>15），fix_suggestion 数值错；其余 10 张阈值与代码一致。本 spec 以代码为基准重写，不照搬审计数值。

## 3. 需求清单

### A. 12 卡片对齐 match 条件（对齐基准 = 代码，见 §5.1）
- [ ] R1 **first_plate**：删「量比>1.5」（match 无，且与上游 first_board_filter 量比打分口径 0.8-1.5 满分相悖）；补「涨停频次≥6」（C2 硬门槛）；入场条件=基因得分≥40 + 涨停频次≥6；止损改「跌破入场价 -3%」（非前日收盘价）；止盈改「涨至 +8% 触发减仓」（非 +5%~10% 回落）
- [ ] R2 **consecutive_relay**：C1 改「250日涨停次数≥2（历史频次，非当下连板高度）」；C2 改「封板率≥60%」（卡片现 0.8=80% 是 S058 旧阈值）；删「板块热度配合」；核心逻辑弱化天气胜率断言（§13.0 天气已降软标注）
- [ ] R3 **break_reseal**：删「涨停后开板≥1次+回封确认」（match 无，开板次数是 funnel quality_standard 读 market_data.open_count）；C2 封板率口径明确「基因历史因子（250日 avg_fbt 归一化，非当日）」
- [ ] R4 **low_absorption**：删「STI 非冰点」+「资金净流入」（旧 S058 三条件版，match 无）；补「均线多头 ma_bullish=True」（C2）；入场条件=回调MA5(ma5_proximity≤3) + 均线多头；核心逻辑删「板块龙头/STI/资金净流入」
- [ ] R5 **n_shape_counterattack**：入场条件改「250日涨停次数 2~10 次（zt_count_250d∈[2,10]）」（非「2日内涨停」）；删「回调企稳」「再次放量」（match 是纯基因频次战法，S097 R14 已去「放量」标签）；核心逻辑删「涨停→回调→放量反弹」形态链
- [ ] R6 **platform_breakout**：C2「成交额放大2倍」改「成交量放大2倍（量比>2，今量/前5日均量）」（match factor=volume_breakout_ratio，非成交额 amount）；入场条件条目数对齐 2 条（「今日突破平台上沿」并入 C2 或标形态前提）
- [ ] R7 **end_of_day_sneak**：补「次日溢价率>15%（C2 溢价能力）」（fa4514e 改 >40→>15）；删「量比>2」「14:30后急拉」（match 不评）；C1 改「封板率≥40%」（非裸「封板」）；核心逻辑改「封板率≥40 ∧ 次日溢价率>15」
- [ ] R8 **dragon_head**：入场条件从 5 条删至 1 条「板块内个股排名 sector_rank≤3」（删相对强度/换手>5%/量比>1.5/板块催化）；适用天气改「晴天（软标注，S086 R3 后任意天气可触发）」；退出参数标「设计参数，runtime 尚未执行（dragon_head 无自动结算）」
- [ ] R9 **weak_turn_strong**：入场条件末补「≥4/5 命中即触发（5命中=高置信1.0，4命中=0.7，≤3不输出）」（match fire_rule，卡片现隐含全 5 条 AND）
- [ ] R10 **pattern_reversal**：删「昨日未封涨停」「最高涨幅≥7%」（旧 5 因子设计，S094 R5→S097 改 3 因子）；入场条件=3 条（上影线≥4 / 放量今量·前5日均量≥1.2 / 5日线向上）；补「≥2/3 命中（3命中1.0/2命中0.7）」；核心逻辑删「突破昨日最高价」（spec §3.R5 作废）
- [ ] R11 **reverse_package**：入场条件重写为「前日真炸板（炸板池 open_count≥2 含本 code，C1 全条件命中，confidence=0.4）」；旧 6 条 fanbao 条件（T-2/T-3涨停、T-1未涨停、成交额>15亿、均线多头、涨跌幅>-3%、游资席位）移「参考因子（历史 fanbao 口径，未接入 S097 match）」或删（注：「T-1未涨停」与 match 矛盾——炸板池成员是当日触及涨停后反复开板）；S053 对照段「match 待 S055 激活」改「S097 已激活（seal_intraday 月表 open_count≥2）」
- [ ] R12 **storm_reversal**：入场条件删「暴风雨天」「逆势涨停」（S086 R3 已删天气硬开关，match 仅按 fbt≤10:30 过滤，任意天气命中）；只保留「早盘封板（首封时间≤10:30，读涨停池 fbt）」；核心逻辑补「match 不检查天气/逆势，暴风雨为推荐场景软标注」

### B. fa4514e 残局 + 一致性测试
- [ ] R13 first_plate/end_of_day_sneak match docstring 修正（gene_based.py:28 `score≥60∧涨停频次>20`→`≥40∧≥6`；gene_based.py:321 `溢价率>40`→`>15`）——fa4514e 漏改
- [ ] R14 S097 spec §5.2 条件表 first_plate/end_of_day_sneak 两行阈值更新为代码真实值（40/6、>15）+ 加 fa4514e 修订注记（spec 卫生，防未来读 spec 误用 60/20）
- [ ] R15 registry `entry_condition` 字段对齐 match（逐个核实 12 战法，审计已指 n_shape:216/platform_breakout:234/pattern_reversal:304/break_reseal:166 等陈旧点；`entry_condition` 喂前端+coach，与卡片同性质须同改）
- [ ] R16 补一致性测试（test_s058_strategy_cards.py）：卡片入场条件 bullet 数 = match `StrategyMatchResult.total_count`（防 dragon_head 5→1/reverse_package 6→1 大漂移）+ 卡片含每个条件的阈值数值（防 first_plate 60→40/end_of_day_sneak >40→>15 阈值漂移）

### C. follow-up（不在本 spec）
- [ ] registry `quality_standards`（list[QualityCheck] 结构体）对齐——更复杂，单独评估
- [ ] 前端总分筛选滑块 §44 safeguard（S098 follow-up #1）
- [ ] 飞书多点通知（S098 follow-up #3）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/cards/*.md`（12 张） | 入场条件/核心逻辑/退出参数对齐 match 代码（R1-R12） |
| `backend/strategies/impl/gene_based.py` | first_plate(:28)/end_of_day_sneak(:321) docstring 阈值修正（R13，fa4514e 漏改） |
| `specs/S097-逐条件因子过滤/spec.md` | §5.2 条件表 first_plate/end_of_day_sneak 两行阈值更新 + fa4514e 修订注记（R14） |
| `backend/strategies/strategy_funnel_registry.py` | 12 战法 `entry_condition` 字段对齐 match（R15） |
| `backend/tests/test_s058_strategy_cards.py` | 补卡片一致性测试（R16） |

## 5. 设计方案

### 5.1 12 战法真实条件基准表（对齐基准 = 实际 match() 代码，2026-08-27 fa4514e 后）

| 战法 | C1 | C2 | C3 | C4 | C5 | fire_rule | confidence |
|---|---|---|---|---|---|---|---|
| first_plate | total_score≥**40** | 涨停频次≥**6** | — | — | — | 全条件命中 | score/100 动态 |
| consecutive_relay | zt_count_250d≥2 | 封板率≥60 | — | — | — | 全条件命中 | 封板率/100 动态 |
| break_reseal | zt_count_250d∈[3,5] | 封板率≥80 | — | — | — | 全条件命中 | 0.7 |
| low_absorption | ma5_proximity≤3 | ma_bullish=True | — | — | — | 全条件命中 | 0.5 |
| n_shape_counterattack | zt_count_250d∈[2,10] | — | — | — | — | 全条件命中 | 0.5 |
| platform_breakout | consolidation_days≥5 | volume_breakout_ratio>2 | — | — | — | 全条件命中 | 0.5 |
| end_of_day_sneak | 封板率≥40 | 次日溢价率>**15** | — | — | — | 全条件命中 | 0.4 |
| dragon_head | sector_rank≤3 | — | — | — | — | 全条件命中 | 0.5 |
| weak_turn_strong | lbc≥1 | broken_duration_min≥20 | max_drop_pct≥5.0 | last_lock_time≥14:40 | vol_ratio_1d∈[1.8,3.0] | ≥4/5 命中 | 5命中1.0/4命中0.7 |
| pattern_reversal | shadow_length_pct≥4 | volume_breakout_ratio≥1.2 | ma5_slope>0 | — | — | ≥2/3 命中 | 3命中1.0/2命中0.7 |
| reverse_package | open_count≥2（炸板池含code） | — | — | — | — | 全条件命中 | 0.4 |
| storm_reversal | fbt≤103000 | — | — | — | — | 全条件命中 | 0.7 |

> 注：first_plate/end_of_day_sneak 粗线阈值为 fa4514e（2026-08-27）校准值，S097 §5.2 旧值 60/20、>40 已过期（R14 同步更新）。

### 5.2 退出参数基准（registry 真值，卡片「退出参数」段须一致）

止损基准一律**入场价**（非前日收盘价/前日最低价等卡片旧表述）。各战法 registry `stop_loss_pct/take_profit_pct/max_hold_days`（strategy_funnel_registry.py:116-323）：

| 战法 | stop_loss | take_profit | max_hold |
|---|---|---|---|
| first_plate | -3% 入场价 | +8% 入场价 | 3日 |
| consecutive_relay | -5% | +12% | 2日 |
| break_reseal | -3% | +6% | 1日 |
| low_absorption | -5% | +10% | 5日 |
| n_shape_counterattack | -3% | +8% | 3日 |
| platform_breakout | -5% | +12% | 7日 |
| end_of_day_sneak | -2% | +4% | 1日 |
| dragon_head | -5% | +15% | 5日（设计参数，runtime 未执行） |
| weak_turn_strong | -5% | +10% | 2日 |
| pattern_reversal | -4% | +12% | 3日 |
| reverse_package | -3% | +6% | 1日 |
| storm_reversal | -3% | +10% | 1日 |

### 5.3 一致性测试设计（R16）

- `test_card_entry_condition_count_matches`：对每战法，解析卡片「入场条件」bullet 数 == 该战法 `match()` 返回的 `total_count`（弱对齐，抓数量级大漂移：dragon_head 5→1、reverse_package 6→1）。
- `test_card_contains_threshold_values`：对每战法，卡片全文含 §5.1 表中该战法每个条件的阈值数值（如 first_plate 卡片含「40」「6」；end_of_day_sneak 含「15」；consecutive_relay 含「60」）——抓阈值漂移。
- 解析卡片用行首 `-`/`*` bullet 计数（markdown 简单解析，不引新依赖）。

### 5.4 关键设计决策

- **对齐基准 = 代码，非 spec §5.2**：fa4514e 改了 2 战法阈值但 spec §5.2 没跟，以代码为真相才与 runtime 一致（卡片喂 AI 须复现 runtime 判断）。
- **registry entry_condition 纳入**：与卡片同源同喂出口（前端/coach），不修则留另一半债。
- **quality_standards 列 follow-up**：结构体（list[QualityCheck]）改动复杂度高于字符串 entry_condition，单独评估，不阻塞本 spec。
- **不改 match 逻辑**：本 spec 只改卡片/docstring/registry 字符串字段/测试，不动 match() 代码体（fa4514e 已改阈值，本 spec 追认对齐展示层）。
- **reverse_package「T-1未涨停」与 match 矛盾**：match 用 open_count≥2 炸板池（反复开板的真炸板=当日触及涨停后打开），卡片旧「T-1未涨停」是相反语义——必须删或明确移参考因子栏。

## 6. 验收标准

- [x] A1 12 张卡片「入场条件」与 §5.1 基准表逐条一致（条件数+因子+阈值+fire_rule）
- [x] A2 12 张卡片「退出参数」与 §5.2 registry 真值一致（止损基准=入场价）
- [x] A3 first_plate/end_of_day_sneak match docstring 阈值对齐代码（R13）
- [x] A4 S097 spec §5.2 两行阈值更新 + fa4514e 修订注记（R14）
- [x] A5 registry 12 战法 entry_condition 对齐 match（R15）
- [x] A6 一致性测试 R16 全绿（卡片条件数 + 阈值数值双断言）
- [x] A7 离线全测绿（全量 2281 passed，1 pre-existing `test_spec_consistency` 硬编码 S066 非 S100；S100 零回归破坏）

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：S100 是卡片展示对齐，非买卖推荐，卡片尾保留「历史统计特征，市场有风险」轻量提醒（test_card_has_risk_disclaimer 已测，不破坏）
- [x] 判断可复现：**本 spec 核心**——卡片喂 AI 出口须与 match runtime 一致才可复现；fa4514e 阈值校准有分位数支撑（非臆造），本 spec 以代码为基准对齐展示层，不臆造条件
- [x] 涨停四池/连板股榜：不涉
- [x] 用户私有数据：reverse_package 卡片描述 open_count 炸板池是已有 DB 查询（不新增私有数据），无数据落 home
- [x] em_get 防封：不涉外部端点

## 8. 测试计划

- `pytest backend/tests/test_s058_strategy_cards.py -v`（卡片完整性 + 风险提醒 + 新增一致性测试 R16）
- `pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_workflow_state.py --no-cov`（全量回归， deselected flaky 见 memory）
- 手动：`query_strategy_card("first_plate")` 等抽查 12 战法卡片输出，确认入场条件与 §5.1 一致

## 9. 风险与回滚

- **风险低**：纯文档/字符串字段/测试，不动 match 逻辑、不动数据、不动 AI 提示词结构。最坏情况是卡片措辞调整不当，回滚 `git revert` S100 commit。
- **一致性测试 brittle 风险**：R16 卡片解析用 bullet 计数 + 阈值数值断言，卡片措辞若不含精确数值（如写「涨停频次达标」不写「6」）会误红——实现时确认每卡片「入场条件」bullet 含数值，或测试用宽松匹配（如 first_plate 含「6」且含「涨停频次」即可）。
- **registry entry_condition 改动影响前端展示**：entry_condition 喂 routers/strategy.py:32 前端策略列表，改文案前端展示变（变好），无契约破坏（字符串字段）。

## 10. 实现记录（2026-08-27）

**R1-R12 12 卡片对齐**：12 张 `cards/*.md` 入场条件/核心逻辑/退出参数全量重写对齐 match 代码（§5.1 基准表）。一致性测试 `TestCardConditionAlignment`（条件数 + 阈值数值双断言）全绿。

**R13 fa4514e docstring 残局**：first_plate/end_of_day_sneak match docstring（`gene_based.py:28,321`）阈值同步 40/6、>15。

**R14 S097 §5.2 修订**：first_plate/end_of_day_sneak 两行阈值更新 + §10.1 fa4514e 修订注记。

**R15 registry entry_condition**：12 战法 `entry_condition` 字段对齐 match（`quality_standards` 列 follow-up，含 reverse_package「T-1未涨停」与 match 矛盾等优先项）。

**R16 一致性测试**：`test_s058_strategy_cards.py` 补 `TestCardConditionAlignment`（2 测：条件数 + 阈值数值）。

**fa4514e 测试残局（顺手修，A7 要求）**：fa4514e（2026-08-27）改 first_plate/end_of_day_sneak 阈值但漏改 5 处测试 data（用旧边界值 55/50/10/30）：
- `test_s086_strategy_impl.py`：test_miss_low_score（total 55→35）/test_miss_low_premium（premium 30→10）
- `test_s097_first_plate.py`：test_c1_miss_c2_hit（total 50→35）/test_c1_hit_c2_miss（freq 10→3）
- `test_s097_funnel_aggregation.py`：test_limitup_first_plate_funnel_summary（B total 55→35、C freq 10→3 + 注释）
- S100 一并修（fa4514e 残局完整收拾）。

**test_s062 断言更新**（S100 直接回归）：dragon_head entry_condition 断言旧 5 关键词 → 改为 sector_rank/≤3；reverse_package fanbao 五条件吸收 → 改为 open_count 炸板核心 + fanbao 历史参考；S053 结论断言 → S097 已激活。

**验收**：全量 2281 passed + 1 pre-existing failed（`test_spec_consistency` 硬编码 S066 已归档，非 S100，见 memory `test-plan-tasks-s066-archive-stale`）+ 1 skipped + 39 deselected（newsradar/s032 flaky）。S100 零回归破坏（A7 达成）。
