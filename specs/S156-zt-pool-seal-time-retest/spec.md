# Spec: S156 — zt_pool 历史 re-test 封单量+封板时间+秒板（严格更好数据补 §44 缺口）

> 状态：草案
> 作者：Claude  日期：2026-09-06
> 关联：S153（day_paired 方法论已 grill）、S155（net-profit-verify 教训）、[s44-quant-validation-loop]、kline_ta_validation.py、first_plate_h2_lift.py

## 0. 触发缘由

S155 证伪 vol_surge/volatility 后，用户 challenge："为什么 B 不能拉旧数据模拟计算"。核实后**我之前"B 只能等 live"是 overstatement**：
- `akshare.stock_zt_pool_em(date)` 历史日期可拉（核实 20260903 → 44 行涨停股 + **封板资金** + **首次封板时间** + **最后封板时间** + 换手率 + 流通市值）。
- `akshare.stock_zh_a_minute(period='1')` 1-min intraday 历史可拉。

这是 §44 **自己标了 caveat 的缺口的严格更好数据**：
- §44 seal_amount：只 5 天探索性（n=177 days=5）——spec caveat 明写"待 60 日复验"。zt_pool 给 42 天封板资金 → 正经测。
- §44 H2 early_lock/late_lock：baostock 5min **推导**封板时间——spec caveat 明写"5min 粗、broken_duration<5min 漏标"。zt_pool 给**精确到秒的首封时间** → 严格更好。
- 秒板：H2 5min 测不了（首封=09:30 在 5min 首 bar 内）。zt_pool 首封时间直接判。

**非 re-mining**：补 §44 自己标的 caveat 缺口（5d 弱样本 + 5min 粗），数据严格更好。真 live-only 仅剩盘中 60s 封单**轨迹**（时序）+ 纯 9:15-9:25 竞价量——本 spec 不涉。

## 1. 问题 / 目标

**问题**：§44 seal_amount（5d 探索性）+ H2 封板时间（5min 推导）数据受限，verdict 带 caveat。zt_pool 历史给精确封板资金+首封时间，但没正经测过。

**目标**：用 zt_pool 42 天历史数据 re-test 封单量+封板时间+秒板三维度，**同时跑 hit-rate lift + net-profit-verify**（套 S155 教训：hit-rate edge≠tradeable，扣成本验）。复用 S153 day_paired 方法论（已 grill）+ S155 net harness 逻辑。

## 2. 背景

- zt_pool 端点：东财 datacenter（push2.eastmoney clist），42 call 低量，走 em_get/breaker 防封 + cache。
- 方法论复用：first_board_layer_lift.day_paired_lift（非池化）+ day_cluster_permutation（within-day survivor null）+ four_state + Bonferroni。**S153 已 grill**（look-ahead/池化/null/Bonferroni），本 spec 不重复 grill 方法论，只 grill 数据源新 aspects。
- net-profit-verify 复用 S155 harness 逻辑（/tmp/verify_net_profit.py）：simulate_holding -3/+8/3 + unbuyable 过滤 + 0.70% cost + top-vs-all。

## 3. 需求清单

- [ ] R1 zt_pool 历史 fetcher：`fetch_zt_pool(date)` → [{code, seal_amount(封板资金), first_lock_time(首封), last_lock_time(末封), turnover, float_mv}]。走 em_get/breaker 防封 + .vibe-research cache（同日去重）。42 eastmoney_live 日。
- [ ] R2 特征→维度（纯函数）：
  - seal_amount = 封板资金（绝对值 + 相对流通市值比 seal_amount/float_mv）
  - early_lock = 首封 ≤ 10:00；late_lock = 首封 > 14:00；秒板 = 首封 == 09:30:00
  - broken = 末封 ≠ 首封（盘中破板重封）或 open_count（若 zt_pool 无开板次数字段，用首封≠末封近似）
- [ ] R3 hit-rate lift：day_paired_lift（非池化，per-T quintile top vs all——套 S155 C6 教训非 top vs bottom 避分母假象）+ within-day survivor null + Bonferroni K=4（seal_amount/early_lock/late_lock/秒板）。
- [ ] R4 net-profit-verify（套 S155 教训）：对每维度 top-quintile，simulate_holding -3/+8/3 + unbuyable 过滤 + 0.70% cost → net path-winrate vs all。**hit-rate lift≥2x 仍需 net≥1x 才算 tradeable**（S155 证伪的 vol_surge 2.046x hit 但 0.945x net）。
- [ ] R5 verdict + 诚实：四态（hit-rate + net 双标）+ matrix.json 落档 .scratch/s156-*/。预注册冻结（cost 0.70%/exit -3,+8,3/K=4/quintile top-vs-all 跑前写死）。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/tools/zt_pool_seal_time_lift.py（新） | R1-R5：zt_pool fetcher + 维度 + day_paired + net-verify + verdict |
| backend/data/transport.py 或 astock.py | R1：zt_pool fetcher 走 em_get/breaker（若 em_get 不支持 datacenter clist，加 wrapper） |
| backend/candidate_funnel/evaluation.py | R5 verdict 若 net validated → DIMENSION_LIFT_REGISTRY 升级 seal_amount（5d→42d）+ 加秒板；若 net<1 → 登记确认无 edge |

## 5. 设计方案

**A. zt_pool fetcher 防封**：42 call 低量，走 em_get（若支持 datacenter clist URL）+ circuit_breaker("eastmoney") + .vibe-research cache（keyed by date）。失败降级 push2delay 或标 missing（不臆造）。

**B. 维度提取**：首封时间字符串 → early/late/秒板 谓词（复用 first_plate_h2_lift 的 _is_early_lock/_is_late_lock 逻辑，但 time 源是 zt_pool 精确首封非 5min bar）。seal_amount 取封板资金 + 算 seal/float_mv 比（practitioner 启发：seal/volume>10 → 高开；<50M → 低开）。

**C. day_paired 非池化**：per-T top-quintile（日内分位，无 look-ahead，套 S155 C1 教训）vs all-universe。within-day survivor null（surv=top⊆raw=all）。Bonferroni K=4。

**D. net-profit-verify**：复用 /tmp/verify_net_profit.py 逻辑（simulate_holding signal_date=T-1 → T open 入场 + unbuyable 过滤 + 0.70% cost）。**双标 verdict**：hit-rate lift≥2x 是必要非充分——须 net≥1x 才 tradeable（S155 vol_surge 2.046x hit 但 0.945x net 教训）。

**E. 不重复 grill 方法论**：day_paired+null+Bonferroni S153 已 grill。本 spec 只需 light grill 数据源新 aspects（见 §7）。

## 6. 验收标准

- [ ] A1 fetch_zt_pool(date) 返封板资金+首封/末封时间（核实字段，不臆造）
- [ ] A2 维度谓词：early_lock(首封≤10:00)/late_lock(>14:00)/秒板(首封=09:30)/broken(首封≠末封)
- [ ] A3 day_paired_lift hit-rate + net 双 lift/n/CI/四态 + null_p95
- [ ] A4 verdict 双标（hit≥2x AND net≥1x → tradeable；否则非）
- [ ] A5 预注册冻结 commit hash
- [ ] A6 pytest -m "not live" --deselect (newsradar+s032+s040) 全绿 + 新增 test_zt_pool_seal_time_lift

## 7. 合规与工程底线自查

- [x] 不臆造：zt_pool 字段实拉实算（已核实封板资金+首封时间存在），net 用 simulate_holding 实算
- [x] 私有数据隔离：cache + matrix.json 写 .vibe-research/.scratch（不进 git）
- [x] em_get 防封：zt_pool 走 em_get/breaker（datacenter 低量 42 call + 代理降级），不裸调 requests
- [x] §44 降级参考性建议：不阻塞，但 net validated 会影响 seal_amount 接入
- [x] verdict 外推禁令：只判 seal_amount/封板时间/秒板 net tradeability，不外推整体
- [x] S155 教训：hit-rate≥2x 非充分，须 net≥1x（防 cost-killed 假 edge 进实盘）

## 8. 数据源新 aspects（需 light grill）

- zt_pool 首封时间是 D 日值 → 预测 D+1，entry D+1 open → 无 look-ahead（同 H2 逻辑）
- zt_pool universe = 当日涨停股（非全市场）——与 kline_ta_validation 全市场不同，是涨停股 sub-universe（对齐 H2 first_plate 口径）
- survivorship：zt_pool 按日拉历史涨停池，退市涨停股可能缺（caveat 标注）
- 封板资金字段口径：东财"封板资金"=涨停价挂单量（买一封单），非成交——practitioner 用，本 spec 直接用不换算
