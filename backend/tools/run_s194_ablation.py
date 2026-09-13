#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S199 R2: 重跑 S194 F1 ablation — direction-aware (A) vs direction-agnostic (B).

S194 F1 消融结论 gap signal no_contribution（delta_ic≈0, p=0.33）。S193 R5 v2 诊断
真因=方向无关 regime 标量编码（GAP_REGIME_ENCODE 丢 direction）。A 股 long-only
（做空受限 §1.1）→ 向下 regime 不可交易，方向无关编码把空头信号当多头喂，稀释
upward edge。

v2（S199）：A/B 对照消融——
- Version A（方向感知）：regime_score × direction_weight（up=full, down=0, none=neutral）
- Version B（旧方向无关，对照组）：regime → scalar（direction 不进编码）
- 比对 delta_ic A vs B，证明 edge（若存在）来自方向感知非他因。

用法：python tools/run_s194_ablation.py [signals.json]
默认读 /tmp/s194_signals.json（reconstruct_s194_signals.py 输出）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.bayesian_signal_weight import BayesianSignalWeight
from engine.trade_journal import TradeJournal
from tools.ablation_runner import (
    composite_ablation_verdict,
    run_composite_ablation,
)
from tools.reconstruct_s194_signals import (
    encode_gap_direction_aware,
    encode_gap_direction_agnostic,
)


def main() -> None:
    signals_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/s194_signals.json"
    raw = Path(signals_path).read_text()
    data = json.loads(raw[raw.index("["):])  # 容错 baostock login/logout 污染

    # 1. FS2 权重：breakout 从 arm reliability；gap dead_arm 先验
    tj = TradeJournal()
    agg = tj.aggregate_by_arm(arm="breakout")
    bk = agg.get("breakout", {})
    wr = float(bk.get("execution_winrate", 0.0) or 0.0)
    n_picks = int(bk.get("n_picks", 0) or 0)
    wins = round(wr * n_picks)
    losses = n_picks - wins
    bsw = BayesianSignalWeight()
    fs2_weights = {
        "breakout": bsw.weight("breakout", wins, losses),
        "gap": bsw.weight("gap", 0, 0),  # dead_arm 先验
    }
    print(f"# FS2 权重: breakout={fs2_weights['breakout']:.4f} (wins={wins} losses={losses} "
          f"n={n_picks} wr={wr:.3f}) | gap={fs2_weights['gap']:.4f} (prior)", file=sys.stderr)

    # 2. 准备 cases——A/B 两版 gap 编码（从 gap_regime + gap_direction 即时算，
    #    兼容旧 signals 文件无 gap_regime_encoded_a/b 字段的情况）
    cases_a = [
        {"breakout": d["breakout_score"] or 0.0,
         "gap": encode_gap_direction_aware(d.get("gap_regime", "无"), d.get("gap_direction", "无"))}
        for d in data
    ]
    cases_b = [
        {"breakout": d["breakout_score"] or 0.0,
         "gap": encode_gap_direction_agnostic(d.get("gap_regime", "无"))}
        for d in data
    ]
    outcomes = [d["gross_return"] for d in data]
    dates = [d["entry_date"] for d in data]
    K = len(fs2_weights)  # 跨信号 Bonferroni

    # 统计 A vs B 差异
    n_gap_a = sum(1 for c in cases_a if c["gap"] > 0)
    n_gap_b = sum(1 for c in cases_b if c["gap"] > 0)
    n_down_zeroed = n_gap_b - n_gap_a
    print(f"\n# 编码差异: version_A gap>0={n_gap_a} | version_B gap>0={n_gap_b} "
          f"| 向下 zeroed={n_down_zeroed} (A 股 long-only)", file=sys.stderr)

    # 3. breakout 消融（基线参照，A=B 因 breakout 不受 gap 编码影响）
    r_bk = run_composite_ablation(cases_a, fs2_weights, outcomes, dates, "breakout")
    v_bk = composite_ablation_verdict(
        delta_ic=r_bk["delta_ic"], delta_pval=r_bk["delta_pval"],
        n_total=len(data), n_days=len(set(dates)), K=K,
    )
    print(f"\n=== breakout 消融（基线参照）===")
    print(f"  full_ic_mean={r_bk['full_ic_mean']:+.4f}  ablated_ic_mean={r_bk['ablated_ic_mean']:+.4f}  "
          f"delta_ic={r_bk['delta_ic']:+.4f}")
    print(f"  delta_pval={r_bk['delta_pval']:.4f}  n_folds={r_bk['n_folds']}")
    print(f"  verdict: {v_bk['verdict']} (tier={v_bk['tier']})")

    # 4. gap 消融——Version A（方向感知）
    r_gap_a = run_composite_ablation(cases_a, fs2_weights, outcomes, dates, "gap")
    v_gap_a = composite_ablation_verdict(
        delta_ic=r_gap_a["delta_ic"], delta_pval=r_gap_a["delta_pval"],
        n_total=len(data), n_days=len(set(dates)), K=K,
    )
    print(f"\n=== gap 消融 · Version A（方向感知）===")
    print(f"  full_ic_mean={r_gap_a['full_ic_mean']:+.4f}  ablated_ic_mean={r_gap_a['ablated_ic_mean']:+.4f}  "
          f"delta_ic={r_gap_a['delta_ic']:+.4f}")
    print(f"  delta_pval={r_gap_a['delta_pval']:.4f}  n_folds={r_gap_a['n_folds']}")
    print(f"  verdict: {v_gap_a['verdict']} (tier={v_gap_a['tier']}, "
          f"adjusted_alpha={v_gap_a['adjusted_alpha']:.4f})")
    print(f"  caveat: {v_gap_a['caveat']}")

    # 5. gap 消融——Version B（旧方向无关，对照）
    r_gap_b = run_composite_ablation(cases_b, fs2_weights, outcomes, dates, "gap")
    v_gap_b = composite_ablation_verdict(
        delta_ic=r_gap_b["delta_ic"], delta_pval=r_gap_b["delta_pval"],
        n_total=len(data), n_days=len(set(dates)), K=K,
    )
    print(f"\n=== gap 消融 · Version B（旧方向无关，对照）===")
    print(f"  full_ic_mean={r_gap_b['full_ic_mean']:+.4f}  ablated_ic_mean={r_gap_b['ablated_ic_mean']:+.4f}  "
          f"delta_ic={r_gap_b['delta_ic']:+.4f}")
    print(f"  delta_pval={r_gap_b['delta_pval']:.4f}  n_folds={r_gap_b['n_folds']}")
    print(f"  verdict: {v_gap_b['verdict']} (tier={v_gap_b['tier']}, "
          f"adjusted_alpha={v_gap_b['adjusted_alpha']:.4f})")
    print(f"  caveat: {v_gap_b['caveat']}")

    # 6. A vs B delta_ic 对照
    delta_diff = r_gap_a["delta_ic"] - r_gap_b["delta_ic"]
    print(f"\n{'='*60}")
    print(f"=== A vs B delta_ic 对照 ===")
    print(f"  A (方向感知)  delta_ic={r_gap_a['delta_ic']:+.4f}  p={r_gap_a['delta_pval']:.4f}  verdict={v_gap_a['verdict']}")
    print(f"  B (方向无关)  delta_ic={r_gap_b['delta_ic']:+.4f}  p={r_gap_b['delta_pval']:.4f}  verdict={v_gap_b['verdict']}")
    print(f"  A - B         delta_ic={delta_diff:+.4f}")
    if delta_diff > 0 and r_gap_a["delta_ic"] > r_gap_b["delta_ic"]:
        print(f"  → 方向感知编码 delta_ic 提升（+{delta_diff:.4f}），edge 可能来自方向感知")
    elif abs(delta_diff) < 0.001:
        print(f"  → A vs B 无差异（delta_diff ≈ 0），方向感知未改变结论")
    else:
        print(f"  → 方向感知编码 delta_ic 下降（{delta_diff:+.4f}），需进一步分析")
    print(f"  n_total={len(data)}  n_days={len(set(dates))}  K={K}")
    print(f"  tier={v_gap_a['tier']}")


if __name__ == "__main__":
    main()
