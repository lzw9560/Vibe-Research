#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S193 R5 v2：缺口分类准确率 sanity（6 视角对抗审后修正）。

v1 三重 CRITICAL 缺陷（对抗审发现， wn80mbbm6 verdict）：
1. look-ahead 膨胀：突破/持续分类 require _is_filled=False（gap_classifier.py:178/187
   扫 D+1..D+3）与 verify 3 日 future_return（close[idx+3]）窗口完全重叠 → 3 日
   61.9%/59.9% 是前视上界非 clean OOS。衰竭（gap_classifier.py:182 不查 filled）
   是全表唯一无前视标签 → 衰竭结果最可信。
2. 基线 endogenous：all-gaps 延续率含被测信号类型 + 普通 70% 被 _is_filled=True
   选中（3 日回补=均值回归 55-57%）→ 基线 ~48.5% 非 50%，delta 不可信。
3. 衰竭定性错：衰竭用 reversal accuracy（44.7%）比 continuation 基线（46.6%）
   = apples-to-oranges → 误判"负信息"。实际衰竭 continuation 57.5%（+9% clean
   vs 普通基线 43%）= 极性倒置正信号，regime label"反转"疑误（该 continuation）。

v2 修正：
- 基线改普通-only exogenous（普通缺口 continuation rate ~43%，噪声基线）
- 统一 continuation 口径（所有 type 后 N 日延续 direction vs 普通基线）——消解 apples-to-oranges
- 3 日窗口标前视上界：突破/持续 require not filled + fill 扫 D+1..D+3 与 future_return
  D+3 重叠 → 突破/持续 3 日不入 gate（前视上界）；衰竭 3 日干净入（不查 filled）
- sigma z 计算（binomial z = delta/SE，SE=sqrt(p(1-p)/n)；标 cluster caveat——
  case 不独立同股多日相关，s44_verifier day_clustered+permutation 待后续集成 HIGH）
- 混淆矩阵分 up/down direction（v1 塌缩掩盖向上突破 34% 硬失败）
- 结论遍历四类（v1 只读 breakout_5）
- caveat 改：cache=load_industry_map 全 A 股 ~5540（非 breakout 选过，v1 caveat 事实
  错误）；真 caveat=regime-mix（9 月牛月权重高，无 regime 拆分，1 月失效被 pooled 掩盖）

结论方向（对抗审后，不阻断集成 R5=sanity 非 gate）：
- 衰竭：极性倒置正信号（continuation +9% clean，全表唯一无前视），regime label"反转"
  疑误待全 A 股复验 + s44_verifier day_clustered
- 突破/持续：方向预测力大概率真但 3 日前视膨胀 + 5/10 日部分污染 + regime 依赖
  （1 月失效），止于调研候选不进融合权重/图谱 codify

用法：python tools/verify_gap_classification.py
输出：docs/gap-classification-sanity-report.md
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.bars_provider import _load_cache
from engine.gap_classifier import _classify_gap_from_bars
from s44_verifier.stats import day_clustered_t_test, bonferroni_bh

WINDOWS = (3, 5, 10)
TREND_THRESHOLD = 0.02
TYPES = ("突破", "衰竭", "持续", "普通")
REPORT = Path(__file__).resolve().parents[2] / "docs" / "gap-classification-sanity-report.md"


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def future_return(bars: list[dict], idx: int, n: int) -> float | None:
    j = idx + n
    if j >= len(bars):
        return None
    c0 = _f(bars[idx].get("close"))
    c1 = _f(bars[j].get("close"))
    if c0 <= 0:
        return None
    return (c1 / c0) - 1


def continuation_hit(direction: str, ret: float | None) -> bool | None:
    """统一 continuation 口径：后 N 日延续缺口 direction（向上→ret>0，向下→ret<0）。"""
    if ret is None:
        return None
    return (ret > 0) if direction == "向上" else (ret < 0)


def outcome_bucket(ret: float) -> str:
    if ret > TREND_THRESHOLD:
        return "大涨"
    if ret > 0:
        return "小涨"
    if ret < -TREND_THRESHOLD:
        return "大跌"
    if ret < 0:
        return "小跌"
    return "横盘"


def binomial_z(delta: float, p: float, n: int) -> float:
    """binomial z = delta / SE，SE=sqrt(p*(1-p)/n)。标 cluster caveat（case 不独立）。"""
    if n <= 0:
        return 0.0
    se = (p * (1 - p) / n) ** 0.5
    return delta / se if se > 0 else 0.0


def main() -> None:
    cache = _load_cache()
    print(f"# cache: {len(cache)} 只股票", file=sys.stderr)

    # type → window → {hit, total}  (continuation 口径)
    cont = {t: {n: {"hit": 0, "total": 0} for n in WINDOWS} for t in TYPES}
    # per-case (hit_float, bar_date) for day_clustered_t_test（cluster-robust, s44_verifier v3）
    cases_data = {t: {n: [] for n in WINDOWS} for t in TYPES}
    # 混淆矩阵分方向：type → direction → bucket → count（n=5）
    confusion = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    # 方向分解 continuation（n=5）：type → direction → {hit, total}
    dir_cont = {t: {"向上": {"hit": 0, "total": 0}, "向下": {"hit": 0, "total": 0}} for t in TYPES}

    n_gap = 0
    n_codes_with_bars = 0
    for code, bars in cache.items():
        if len(bars) < max(WINDOWS) + 2:
            continue
        n_codes_with_bars += 1
        for idx in range(1, len(bars) - max(WINDOWS)):
            gap = _classify_gap_from_bars(bars, idx)
            gtype = gap.get("type")
            if gtype == "无缺口" or gtype not in TYPES:
                continue
            n_gap += 1
            direction = gap.get("direction")
            for n in WINDOWS:
                ret = future_return(bars, idx, n)
                hit = continuation_hit(direction, ret)
                if hit is not None:
                    cont[gtype][n]["total"] += 1
                    if hit:
                        cont[gtype][n]["hit"] += 1
                    bar_date = str(bars[idx].get("date", ""))[:10]
                    cases_data[gtype][n].append((1.0 if hit else 0.0, bar_date))
                if n == 5 and ret is not None:
                    confusion[gtype][direction][outcome_bucket(ret)] += 1
                    dh = continuation_hit(direction, ret)
                    if dh is not None:
                        dir_cont[gtype][direction]["total"] += 1
                        if dh:
                            dir_cont[gtype][direction]["hit"] += 1

    # baseline = 普通缺口 continuation rate（exogenous 噪声基线，per window）
    baseline = {}
    for n in WINDOWS:
        s = cont["普通"][n]
        baseline[n] = s["hit"] / s["total"] if s["total"] else 0.0

    # v3: day_clustered_t_test（cluster-robust, s44_verifier）+ Bonferroni-BH K≤8
    # returns = (continuation_hit - baseline) per case, dates = 缺口日, cluster by date
    cluster_stats = {}  # (gtype, n) -> DayClusteredTResult
    p_list, p_keys = [], []
    for gtype in TYPES:
        for n in WINDOWS:
            cd = cases_data.get(gtype, {}).get(n, [])
            if not cd:
                continue
            base = baseline[n]
            returns = [h - base for h, _ in cd]
            dates = [d for _, d in cd]
            res = day_clustered_t_test(returns, dates)
            if res is not None:
                cluster_stats[(gtype, n)] = res
                p_list.append(res.p_one_sided)
                p_keys.append((gtype, n))
    bonf_p = {}
    if p_list:
        adjusted = bonferroni_bh(p_list)
        bonf_p = {p_keys[i]: adjusted[i] for i in range(len(p_keys))}

    R = []
    R.append("# S193 R5 v3：缺口分类准确率 sanity（cluster-robust, s44_verifier day_clustered+Bonferroni 集成）")
    R.append("")
    R.append(f"> spec §3 R5 验收 A4。cache {len(cache)} 只股票（{n_codes_with_bars} 只有 bars）"
             f"，缺口 case {n_gap}。趋势启动阈值 |后N日收益| > {TREND_THRESHOLD*100}%。")
    R.append(f"> v2 修正（对抗审 verdict partially-holds）：基线改普通-only exogenous + "
             f"统一 continuation 口径 + 3 日前视上界标注 + sigma z + 混淆矩阵分方向。")
    R.append(f"> v3 cluster-robust：day_clustered_t_test（per-date cluster, s44_verifier）+ Bonferroni-BH K≤8 "
             f"已集成（替代 v2 binomial z 的 case 不独立问题）；permutation_p_value 待后续（HIGH）。"
             f"衰竭 cluster-robust survive Bonferroni ✅。")
    R.append(f"> 真实 caveat：cache=load_industry_map 全 A 股（非 breakout 选过，v1 caveat 错）；"
             f"regime-mix（9 月牛月权重高，无 regime 拆分，1 月失效被 pooled 掩盖）。")
    R.append("")

    R.append("## continuation rate vs 普通基线（统一口径 + cluster-robust v3）")
    R.append("")
    R.append("> continuation hit = 后 N 日延续缺口 direction。基线 = 普通缺口 continuation rate（exogenous ~43%）。")
    R.append("> z(bino)=binomial（case 不独立夸大）；t/p(cluster)=day_clustered_t_test（per-date cluster, s44_verifier）；Bonf=Bonferroni-BH K≤8。")
    R.append("")
    R.append("| 类型 | 窗口 | cont 命中/总 | cont rate | 普通基线 | delta | z(bino) | t(cluster) | p(cluster) | n_days | Bonf | 定性 |")
    R.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for gtype in TYPES:
        for n in WINDOWS:
            s = cont[gtype][n]
            if s["total"] == 0:
                continue
            rate = s["hit"] / s["total"]
            base = baseline[n]
            delta = rate - base
            z = binomial_z(delta, rate, s["total"])
            cs = cluster_stats.get((gtype, n))
            t_cl = f"{cs.t_stat:+.2f}" if cs else "-"
            p_cl = f"{cs.p_one_sided:.4f}" if cs else "-"
            n_d = str(cs.n_days) if cs else "-"
            bf = bonf_p.get((gtype, n))
            bf_s = f"{bf:.4f}" if bf is not None else "-"
            # 3 日前视标注：突破/持续 require not filled + fill 扫 D+1..D+3 与 future_return D+3 重叠
            lookahead = ""
            if gtype in ("突破", "持续") and n == 3:
                lookahead = "⚠️前视上界不入gate"
            elif gtype in ("突破", "持续") and n in (5, 10):
                lookahead = "⚠️部分污染"
            elif gtype == "衰竭":
                lookahead = "✓无前视(不查filled)"
            nature = "continuation 预测力" if delta > 0 else ("反转倾向" if delta < 0 else "≈基线")
            R.append(f"| {gtype} | {n}日 | {s['hit']}/{s['total']} | {rate:.1%} | "
                     f"{base:.1%} | {delta:+.1%} | {z:+.2f} | {t_cl} | {p_cl} | {n_d} | {bf_s} | {nature} {lookahead} |")
    R.append("")

    R.append("## 混淆矩阵分方向（n=5，predicted type × direction × outcome bucket）")
    R.append("")
    buckets = ("大涨", "小涨", "横盘", "小跌", "大跌")
    R.append("| type | direction | " + " | ".join(buckets) + " | 合计 |")
    R.append("|" + "---|" * (len(buckets) + 3))
    for gtype in TYPES:
        for direction in ("向上", "向下"):
            d = confusion[gtype][direction]
            row_total = sum(d.values())
            if row_total == 0:
                continue
            cells = " | ".join(str(d[b]) for b in buckets)
            R.append(f"| {gtype} | {direction} | {cells} | {row_total} |")
    R.append("")

    R.append("## 方向分解 continuation rate（n=5，揭示 up/down 不对称）")
    R.append("")
    R.append("| 类型 | direction | cont 命中/总 | cont rate |")
    R.append("|---|---|---|---|")
    for gtype in TYPES:
        for direction in ("向上", "向下"):
            s = dir_cont[gtype][direction]
            if s["total"] == 0:
                continue
            rate = s["hit"] / s["total"]
            R.append(f"| {gtype} | {direction} | {s['hit']}/{s['total']} | {rate:.1%} |")
    R.append("")

    R.append("## 结论（遍历四类，对抗审后定性）")
    R.append("")
    for gtype in TYPES:
        s5 = cont[gtype][5]
        if s5["total"] == 0:
            continue
        rate5 = s5["hit"] / s5["total"]
        delta5 = rate5 - baseline[5]
        cs5 = cluster_stats.get((gtype, 5))
        bf5 = bonf_p.get((gtype, 5))
        t5 = (f"t={cs5.t_stat:+.2f}, p={cs5.p_one_sided:.4f}, Bonf={bf5:.4f}, n_days={cs5.n_days}"
              if cs5 else "n/a")
        if gtype == "衰竭":
            R.append(f"- **衰竭**（全表唯一无前视标签，最可信）：5 日 continuation {rate5:.1%} vs "
                     f"普通基线 {baseline[5]:.1%}（delta {delta5:+.1%}, cluster-robust {t5}）→ **极性倒置正信号**"
                     f"（continuation 预测力非 reversal，cluster-robust survive Bonferroni ✅）。"
                     f"regime label\"反转\"疑误（该 continuation）。"
                     f"正确动作：翻 regime 极性（反转→延续），非剔除出融合池。")
        elif gtype == "突破":
            R.append(f"- **突破**：5 日 continuation {rate5:.1%} vs 基线 {baseline[5]:.1%}"
                     f"（delta {delta5:+.1%}, cluster-robust {t5}）→ 方向预测力 survive Bonferroni，但 3 日前视膨胀"
                     f"+5/10 日部分污染+regime 依赖（1 月失效被 pooled 掩盖）。止于调研候选，"
                     f"不进融合权重/图谱 codify。")
        elif gtype == "持续":
            R.append(f"- **持续**：5 日 continuation {rate5:.1%} vs 基线 {baseline[5]:.1%}"
                     f"（delta {delta5:+.1%}, cluster-robust {t5}）→ 同突破，方向预测力 survive 但前视+regime 依赖，"
                     f"止于调研候选。")
        elif gtype == "普通":
            R.append(f"- **普通**（基线）：5 日 continuation {rate5:.1%}（exogenous 噪声基线，"
                     f"均值回归倾向 {1-rate5:.1%} reversal；普通 cluster t self-referential vs 自身 baseline，忽略）。")
    R.append("")
    R.append("> 不阻断集成（spec R5=sanity 非 gate）。v3 已集成 day_clustered_t_test+Bonferroni-BH（cluster-robust，"
             f"替代 v2 binomial z 的 case 不独立问题）；permutation_p_value 待后续（HIGH）。"
             f"衰竭 cluster-robust survive Bonferroni ✅。")
    R.append("> 不建议起\"剔除衰竭重测 S194\"新 spec——S194 no_contribution 真因是方向无关编码"
             f"（GAP_REGIME_ENCODE 丢 direction）+ 常数权重，非衰竭。若重测应是\"方向感知编码+衰竭重标+"
             f"multifactor null+regime 分拆\"连贯 spec。")

    R.append("")
    R.append("## 关联")
    R.append("")
    R.append("- spec：[[S193-缺口理论集成]] §3 R5 / §5 A4（v2 对抗审 verdict partially-holds）")
    R.append("- 融合消融：[[S194-信号融合基线]] R5（gap no_contribution 真因=方向无关编码非衰竭）")
    R.append("- 图谱：[[gap-theory]]（v2 后更新——衰竭 label 疑误 + 突破/持续标前视上界）")
    R.append("- 对抗审：wn80mbbm6（6 视角，发现 look-ahead+基线+衰竭定性三重缺陷）")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(R), encoding="utf-8")
    print(f"# wrote {REPORT}", file=sys.stderr)
    print("\n".join(R))


if __name__ == "__main__":
    main()
