#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T5.3 实测 v2（融合分消融）：重建信号值 + FS2 权重 → run_composite_ablation。

v1（feature 喂 walk_forward_cv）被 verify 报 CRITICAL（权重被 ML 吃掉）。v2 用融合分
Σ(值×权重) 作预测分数，消融时权重设 0，权重直接起乘数作用 → 真测 FS2 权重贡献。

⚠️ 本轮 caveat：FS2 权重用全量 reliability 算（lookahead）——n_days=49<60 underpowered，
verdict 本就 exploratory（不判），lookahead 不改结论。要严格 OOS 须 per-fold 重算权重
（reliability_fn 注入 train-fold outcomes 算），后续按需加。
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
    print(f"# FS2 权重: breakout={fs2_weights['breakout']:.4f} (wins={wins} losses={losses} n={n_picks} wr={wr:.3f}) | gap={fs2_weights['gap']:.4f} (prior)", file=sys.stderr)

    # 2. 准备 cases（信号值）+ outcomes + dates
    cases_vals = [
        {"breakout": d["breakout_score"] or 0.0, "gap": d["gap_regime_encoded"]}
        for d in data
    ]
    outcomes = [d["gross_return"] for d in data]
    dates = [d["entry_date"] for d in data]
    K = len(fs2_weights)  # 跨信号 Bonferroni

    # 3. 每信号融合分消融
    for signal in ["breakout", "gap"]:
        r = run_composite_ablation(cases_vals, fs2_weights, outcomes, dates, signal)
        v = composite_ablation_verdict(
            delta_ic=r["delta_ic"], delta_pval=r["delta_pval"],
            n_total=len(data), n_days=len(set(dates)), K=K,
        )
        print(f"\n=== 融合分消融信号: {signal} ===")
        print(f"  full_ic_mean={r['full_ic_mean']:+.4f}  ablated_ic_mean={r['ablated_ic_mean']:+.4f}  delta_ic={r['delta_ic']:+.4f}")
        print(f"  delta_pval={r['delta_pval']:.4f}  n_folds={r['n_folds']}  (full-IC - ablated-IC = 该信号权重移除后的预测力损失)")
        print(f"  verdict: {v['verdict']} (tier={v['tier']}, adjusted_alpha={v['adjusted_alpha']:.4f})")
        print(f"  caveat: {v['caveat']}")


if __name__ == "__main__":
    main()
