# Spec: S155 — vol_surge/volatility T-1 edge 利润验证（扣成本后是否仍 tradeable）

> 状态：**已废弃**（2026-09-06，premise 经 6 视角 grill + 独立 net 验证证伪）
> 作者：Claude  日期：2026-09-06
> 关联：S153（量化验证）、S151（评价层）、[s44-quant-validation-loop memory]、[edge-in-intraday-not-selection memory]、kline_ta_validation.py、platform_breakout_lift.py

## 0.1 Verdict（2026-09-06 证伪）

**Spec premise 证伪——vol_surge/volatility 非可交易 edge。**

6 视角对抗 grill（look-ahead/cost/survivorship/方法论/edge 真实性/诚实）+ 独立 net 验证 harness（/tmp/verify_net_profit.py，per-T quintile + simulate_holding -3/+8/3 + unbuyable 过滤 + 0.70% cost + top-vs-all）：

1. **C1 部分确认**：vol_surge pooled 2.046x（全局 quintile look-ahead）→ per-T 1.974x（**<2x，drop，非 validated**）。volatility pooled 7.597x → per-T 9.650x（grill 声称 2.17x 是臆造，实测更高）——但 9.65x 是 **C3 分母结构性假象**（bottom quintile 涨停率 0.37%，低波动/ST 股 5% 上限根本不涨停 → 近零分母）。
2. **C2 确认（net<1x）**：扣 0.70% cost 后——vol_surge top net-WR 40.61% vs all 42.96% = **0.945x 劣于随机**；volatility top 33.75% vs 42.96% = **0.786x 劣于随机**。这是**上限**（flat -3% stop 对 edge 有利、gap-down 未建模高估），真实更差。
3. **unbuyable negligible**（grill C6 担心过虑，实测仅 0.1% 排除）。

**结论**：vol_surge/volatility 的涨停命中 edge（hit-rate lift）扣成本后都劣于随机。§44"无可交易 T-1 选股 edge"verdict **确认 + profit-verified**。本 spec 废弃，Phase 2 不做（建在 cost-killed 非 edge 上 = grill-me"看起来正确但无价值"陷阱）。

DIMENSION_LIFT_REGISTRY vol_surge_ref 误标修正：pooled 2.046"validated/盘中" → per-T 1.974 未validated + net<1x 注（盘中 mislabel 也修，vol_surge 实为 T-1 非 盘中）。

## 0. 触发缘由（pivotal finding，后证伪）

S153 §44 闭合后裁决"选股层无可交易 edge"——但该裁决**漏了两个 validated T-1 涨停预测 edge**（重跑 kline_ta_validation.py 独立核实，2026-09-06）：

| T-1 特征 | lift | 状态 |
|---|---|---|
| **vol_surge**（T-1 量/前 5 日均量） | 2.046x（pooled）/ 1.974x（per-T） | pooled validated / per-T 未validated |
| **volatility**（5 日振幅/close） | 7.597x（pooled）/ 9.650x（per-T） | 分母结构性假象（bottom 0.37% 近零） |

- vol_surge 被 DIMENSION_LIFT_REGISTRY 误标"参照/盘中维度"——实为 T-1 特征。volatility 根本未登记。
- 用户 grill-me"结论偏差"concern 触发重查——经 grill + net 验证，**原 §44 verdict 是对的**（hit-rate edge 扣成本后劣于随机），"偏差"是 pooled artifact + 分母假象错觉。

**关键 nuance（spec 0.1 已证伪）**：这俩是涨停命中预测 edge ≠ 利润 edge。文献（华安 2026）警告滑点 0.05%→0.30% 收益塌 151.6%→18.4%。net 验证证实：扣 0.70% cost 后 vol_surge 0.945x、volatility 0.786x，均劣于随机。

## 1. 问题 / 目标

**问题**：vol_surge 2.046x + volatility 7.597x 是 validated 涨停预测 edge，但涨停预测 ≠ 利润（成本/滑点/退出可能击溃，文献警告）。当前 §44 path-winrate 无 cost 模型（forward_test/kline_returns 无 cost 字段，已 grep 确认）。

**目标**：建 profit-verify harness——选 top-quintile vol_surge/volatility 股 T-1 close→T open 入场→path exit（-3/+8/3）→**扣 round-trip cost 后**算 net path-winrate lift。≥2x + CI不重叠 → validated tradeable edge（加进 gene_scores）；<2x 或 <1 → 成本击溃，确认 §44 verdict。

## 2. 背景

- kline_ta_validation.py `_compute_ta`：vol_surge = T-1 vol / avg(T-2..T-6 vol)；volatility = (max_high5 - min_low5)/close_t1。全 T-1 数据（T-1 close 可知），无 look-ahead。
- universe = baostock_kline_cache（5226 股）× gene_scores eastmoney_live 42 T 日（同 kline_ta_validation）。
- §44 profit 范式：platform_breakout_lift.py 已用 day_paired_lift + simulate_holding_with_confirm + day_cluster_permutation + Bonferroni。本 spec 复用，signal 换成 quintile。
- DEFAULT_PATH_PARAMS = {stop -3%, take +8%, max_hold 3}（kline_returns.py:28）。
- **caveat（survivorship）**：baostock_kline_cache 仅含当前在市股（退市股无 cache），survivorship bias 偏高。结果 caveat 标注，不阻断。

## 3. 需求清单

- [ ] R1 universe + 特征：复用 kline_ta_validation `_compute_ta`，对每 (T, code) 算 vol_surge + volatility（T-1）。分 quintile（top 20% / bottom 20%，per T 日内分位防跨日 look-ahead）。
- [ ] R2 net path-winrate：top-quintile 股 T open 入场 → simulate_holding（-3/+8/3）算 gross path return → **扣 round_trip_cost** → net return → win = net>0 → winrate。
- [ ] R3 day_paired_lift（非池化）：top-quintile net-winrate vs bottom-quintile net-winrate，per-T 配对（非池化防 day-cluster 假象）。复用 first_board_layer_lift.day_paired_lift。
- [ ] R4 within-day survivor resampling null + Bonferroni K=3（vol_surge / volatility / 交互 vol_surge×volatility 双高）。α_adj=0.05/3。
- [ ] R5 verdict + 诚实标注：
  - net lift ≥2x + CI不重叠 + n≥30 → **validated tradeable**（→ Phase 2 加进 gene_scores）
  - 1≤net lift<2 → 未validated（paper edge 成本击溃，不驱动交易）
  - net lift<1 robust → 劣于随机（成本击溃，确认 §44 verdict）
  - n<30 → 探索性
  - 预注册冻结 + 不事后调参 + matrix.json 落档 .scratch/s155-*/

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| backend/tools/vol_surge_volatility_profit_lift.py（新） | R1-R5：quintile + net path-winrate + day_paired_lift + null + verdict |
| backend/candidate_funnel/evaluation.py | R5 verdict 若 validated → DIMENSION_LIFT_REGISTRY 加 vol_surge/volatility（tradeable 口径，非"参照"）；若成本击溃 → 加登记为"未validated 劣于随机"闭合漏标 |
| backend/strategies/kline_returns.py（可选） | 若加 cost 模型复用——加 `ROUND_TRIP_COST` 常量 + simulate_holding cost 参数（YAGNI：仅本 harness 用则内联 harness 不改 kline_returns） |

## 5. 设计方案

**A. quintile 分位**：per T 日内分（防跨日 look-ahead + day-cluster）。top 20% = vol_surge 最高 20%（T 日内）；bottom 20% = 最低。每 T 独立分位 → day_paired 配对。

**B. net path-winrate**：
```
gross_return = simulate_holding(code, T, params=(-3,+8,3))  # 复用 kline_returns
net_return = gross_return - round_trip_cost   # 0.70% conservative
win = 1 if net_return > 0 else 0
winrate = sum(wins)/n
```
round_trip_cost = 0.70% = 0.30% entry slip + 0.30% exit slip + 0.10% fees（Hua'an 高端，conservative）。涨停锁定股 +8% take-profit 先于 +10% lock 触发 → 可卖（避 lock-exit 滑点爆）。

**C. day_paired_lift**：复用 platform_breakout_lift 范式——per-T top-quintile net-winrate vs bottom-quintile net-winrate，非池化。within-day survivor resampling null（day_cluster_permutation）。Bonferroni K=3。

**D. 交互（预注册单一）**：vol_surge top + volatility top 双高 → 测是否增强（非 data-mining 全组合，仅此一假设）。

**E. verdict + 诚实**：四态。net lift 是扣成本后的——这是与 kline_ta_validation（gross 涨停 hit-rate lift）的关键区别。若 net lift<1 → 成本击溃，确认 §44 verdict（"统计 edge"≠"tradeable edge"）；若 ≥2x → 真 tradeable edge，加进 gene_scores（Phase 2，另 spec）。

**cost 敏感性**：跑 3 档（0.05% / 0.17% / 0.30% slippage）看 edge 何时塌——诚实呈现成本击溃曲线（Hua'an 警告验证）。

## 6. 验收标准

- [ ] A1 net path-winrate 函数：gross - cost → win 判定（cost>0 时 win 可能翻负）
- [ ] A2 day_paired_lift 输出 net lift/n/CI/四态 + null_p95
- [ ] A3 cost 敏感性 3 档（0.05/0.17/0.30%）net lift 曲线
- [ ] A4 verdict 诚实（n<30 探索性；不事后调 cost 凑显著）
- [ ] A5 预注册冻结 commit hash（cost/exit/K/quintile 跑前写死）
- [ ] A6 pytest -m "not live" --deselect (newsradar+s032+s040) 全绿 + 新增 test_vol_surge_volatility_profit_lift（net path-winrate 纯函数 + cost 扣减 + quintile 分位）

## 7. 合规与工程底线自查（逐条确认）

- [x] 不臆造：net path-winrate 全从 baostock kline + simulate_holding 实算，禁心算；cost 模型显式 0.70% 不藏
- [x] 私有数据隔离：matrix.json 写 .scratch（vr_paths 隔离）不进 git
- [x] em_get 防封：本 harness 走 baostock cache（已缓存，无网络），不触防封底线
- [x] §44 已降级参考性建议：本验证不阻塞，但若 net validated 会影响 gene_scores 接入（Phase 2 另 spec）
- [x] verdict 外推禁令：只判 vol_surge/volatility net tradeability，不外推成"整体有/无 edge"（明示测了啥没测啥）
- [x] 研判/买卖时机：本 spec 只出 verdict（validated/未validated），不给买卖建议；Phase 2 接入才涉及信号

## 8. 测试计划

- net path-winrate 纯函数：gross 5% - cost 0.70% = 4.3% → win；gross 0.5% - 0.70% = -0.2% → loss（cost 翻负）
- quintile 分位：per-T 独立分（防跨日 look-ahead）
- cost 敏感：0.05% → lift 最高；0.30% → 若塌<2x = 成本击溃
- day_paired_lift + null 复用 platform_breakout_lift 测试范式

## 9. 分级

**large**（新 §44 profit-verify harness + verdict 影响选股层 + 可能 Phase 2 接入 gene_scores）。需 spec + adversarial grill（≥6 视角，统计方法论）+ 实现 + 验收。
