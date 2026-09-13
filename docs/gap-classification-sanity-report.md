# S193 R5 v2：缺口分类准确率 sanity（6 视角对抗审后修正）

> spec §3 R5 验收 A4。cache 5230 只股票（5214 只有 bars），缺口 case 30020。趋势启动阈值 |后N日收益| > 2.0%。
> v2 修正（对抗审 verdict partially-holds）：基线改普通-only exogenous + 统一 continuation 口径 + 3 日前视上界标注 + sigma z + 混淆矩阵分方向。
> ⚠️ cluster caveat：case 不独立（同股多日相关），binomial z 夸大显著性；s44_verifier day_clustered+permutation 待后续集成（HIGH）。
> 真实 caveat：cache=load_industry_map 全 A 股（非 breakout 选过，v1 caveat 错）；regime-mix（9 月牛月权重高，无 regime 拆分，1 月失效被 pooled 掩盖）。

## continuation rate vs 普通基线（统一口径，消解 apples-to-oranges）

> continuation hit = 后 N 日延续缺口 direction。基线 = 普通缺口 continuation rate（exogenous 噪声 ~43%）。
> delta > 0 = 有 continuation 预测力；delta < 0 = 反转倾向。z = binomial（标 cluster caveat）。

| 类型 | 窗口 | cont 命中/总 | cont rate | 普通基线 | delta | z(binomial) | 定性 |
|---|---|---|---|---|---|---|---|
| 突破 | 3日 | 1151/1859 | 61.9% | 44.1% | +17.8% | +15.82 | continuation 预测力 ⚠️前视上界不入gate |
| 突破 | 5日 | 1017/1859 | 54.7% | 43.0% | +11.7% | +10.16 | continuation 预测力 ⚠️部分污染 |
| 突破 | 10日 | 1014/1859 | 54.5% | 46.2% | +8.4% | +7.25 | continuation 预测力 ⚠️部分污染 |
| 衰竭 | 3日 | 2323/4114 | 56.5% | 44.1% | +12.4% | +16.00 | continuation 预测力 ✓无前视(不查filled) |
| 衰竭 | 5日 | 2253/4114 | 54.8% | 43.0% | +11.8% | +15.19 | continuation 预测力 ✓无前视(不查filled) |
| 衰竭 | 10日 | 2293/4114 | 55.7% | 46.2% | +9.6% | +12.35 | continuation 预测力 ✓无前视(不查filled) |
| 持续 | 3日 | 1766/2946 | 59.9% | 44.1% | +15.8% | +17.55 | continuation 预测力 ⚠️前视上界不入gate |
| 持续 | 5日 | 1656/2946 | 56.2% | 43.0% | +13.2% | +14.48 | continuation 预测力 ⚠️部分污染 |
| 持续 | 10日 | 1716/2946 | 58.2% | 46.2% | +12.1% | +13.29 | continuation 预测力 ⚠️部分污染 |
| 普通 | 3日 | 9305/21101 | 44.1% | 44.1% | +0.0% | +0.00 | ≈基线  |
| 普通 | 5日 | 9068/21101 | 43.0% | 43.0% | +0.0% | +0.00 | ≈基线  |
| 普通 | 10日 | 9743/21101 | 46.2% | 46.2% | +0.0% | +0.00 | ≈基线  |

## 混淆矩阵分方向（n=5，predicted type × direction × outcome bucket）

| type | direction | 大涨 | 小涨 | 横盘 | 小跌 | 大跌 | 合计 |
|---|---|---|---|---|---|---|---|
| 突破 | 向上 | 588 | 139 | 12 | 131 | 449 | 1319 |
| 突破 | 向下 | 177 | 68 | 5 | 81 | 209 | 540 |
| 衰竭 | 向上 | 771 | 210 | 12 | 217 | 706 | 1916 |
| 衰竭 | 向下 | 719 | 196 | 11 | 216 | 1056 | 2198 |
| 持续 | 向上 | 890 | 307 | 15 | 329 | 501 | 2042 |
| 持续 | 向下 | 310 | 131 | 4 | 135 | 324 | 904 |
| 普通 | 向上 | 3554 | 1323 | 54 | 1601 | 4685 | 11217 |
| 普通 | 向下 | 4577 | 1075 | 41 | 1027 | 3164 | 9884 |

## 方向分解 continuation rate（n=5，揭示 up/down 不对称）

| 类型 | direction | cont 命中/总 | cont rate |
|---|---|---|---|
| 突破 | 向上 | 727/1319 | 55.1% |
| 突破 | 向下 | 290/540 | 53.7% |
| 衰竭 | 向上 | 981/1916 | 51.2% |
| 衰竭 | 向下 | 1272/2198 | 57.9% |
| 持续 | 向上 | 1197/2042 | 58.6% |
| 持续 | 向下 | 459/904 | 50.8% |
| 普通 | 向上 | 4877/11217 | 43.5% |
| 普通 | 向下 | 4191/9884 | 42.4% |

## 结论（遍历四类，对抗审后定性）

- **突破**：5 日 continuation 54.7% vs 基线 43.0%（delta +11.7%, z=+10.16）→ 方向预测力大概率真，但 3 日前视膨胀+5/10 日部分污染+regime 依赖（1 月失效被 pooled 掩盖）。止于调研候选，不进融合权重/图谱 codify。
- **衰竭**（全表唯一无前视标签，最可信）：5 日 continuation 54.8% vs 普通基线 43.0%（delta +11.8%, z=+15.19）→ **极性倒置正信号**（continuation 预测力非 reversal）。regime label"反转"疑误（该 continuation）。正确动作：翻 regime 极性（反转→延续），非剔除出融合池。
- **持续**：5 日 continuation 56.2% vs 基线 43.0%（delta +13.2%, z=+14.48）→ 同突破，方向预测力大概率真但前视+regime 依赖，止于调研候选。
- **普通**（基线）：5 日 continuation 43.0%（exogenous 噪声基线，均值回归倾向 57.0% reversal）。

> 不阻断集成（spec R5=sanity 非 gate）。当前数字仍标 cluster caveat（case 不独立），s44_verifier day_clustered+permutation+Bonferroni 待后续集成后才有 cluster-robust 显著性。
> 不建议起"剔除衰竭重测 S194"新 spec——S194 no_contribution 真因是方向无关编码（GAP_REGIME_ENCODE 丢 direction）+ 常数权重，非衰竭。若重测应是"方向感知编码+衰竭重标+multifactor null+regime 分拆"连贯 spec。

## 关联

- spec：[[S193-缺口理论集成]] §3 R5 / §5 A4（v2 对抗审 verdict partially-holds）
- 融合消融：[[S194-信号融合基线]] R5（gap no_contribution 真因=方向无关编码非衰竭）
- 图谱：[[gap-theory]]（v2 后更新——衰竭 label 疑误 + 突破/持续标前视上界）
- 对抗审：wn80mbbm6（6 视角，发现 look-ahead+基线+衰竭定性三重缺陷）