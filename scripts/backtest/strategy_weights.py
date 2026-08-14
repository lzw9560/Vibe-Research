# -*- coding: utf-8 -*-
"""S066 Phase 0d: 策略分权重定稿 → strategy_weights.json

基于 Phase 0b factor_significance.json 的结果确定 3 套权重：
- 涨停类：只保留 CI 排除 0 的因子，按 |r| 分配权重
- 非涨停类：等权起步（Phase 2 有数据后调）
- 暴风暴：固定 seal_rate 0.60 + (100-freq) 0.40

输出：.vibe-research/strategy_weights.json

规则（spec §4.0/§4.1）：
- CI 排除 0 的因子 → 进入策略分公式，按 |r| 归一化分配权重
- CI 包含 0 的因子 → 降为等权或权重 0
- 不显著的因子不强行进入——复杂性是 alpha 的敌人
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SIG_PATH = REPO / ".vibe-research" / "factor_significance.json"
OUT = REPO / ".vibe-research" / "strategy_weights.json"

# 因子名 → 反向标记（spec §4.4：premium/freq 用 100-value 反转）
REVERSE_FACTORS = {"factor_premium_rate", "factor_freq_score"}

# 因子显示名
FACTOR_LABELS = {
    "factor_premium_rate": "连板率(premium)",
    "factor_red_rate": "红盘率(red)",
    "factor_seal_rate": "封板率(seal)",
    "factor_rebound_rate": "炸板后溢价(rebound)",
    "factor_freq_score": "涨停频次(freq)",
    "zt_count_250d": "涨停频次(zt_count)",
    "total_score": "总分(total)",
    "wilson_adjusted": "Wilson调整",
}


def load_significance() -> dict:
    return json.loads(SIG_PATH.read_text())


def determine_weights(sig: dict) -> dict:
    """根据 0b 回归结果确定涨停类权重。"""
    factor_sig = sig.get("factor_significance", {})
    significant_factors = []
    for f, res in factor_sig.items():
        if f == "total_score" or f == "wilson_adjusted":
            continue  # 不把总分/Wilson 作为策略分因子（它们是聚合指标不是原始因子）
        if not isinstance(res, dict) or res.get("r") is None:
            continue
        ci_excludes_zero = res.get("ci_excludes_zero", False)
        if ci_excludes_zero:
            significant_factors.append({
                "factor": f,
                "label": FACTOR_LABELS.get(f, f),
                "r": res["r"],
                "ci_low": res["ci_low"],
                "ci_high": res["ci_high"],
                "reverse": f in REVERSE_FACTORS,
            })

    if not significant_factors:
        # 无显著因子 → 等权起步（spec §4.1 候选初始值）
        return {
            "method": "equal_weight_fallback",
            "note": "无因子 CI 排除 0，使用 spec §4.1 候选初始等权",
            "weights": {
                "factor_seal_rate": {"weight": 0.40, "reverse": False, "label": "封板率"},
                "factor_premium_rate": {"weight": 0.15, "reverse": True, "label": "连板率(反向)"},
                "factor_freq_score": {"weight": 0.25, "reverse": True, "label": "涨停频次(反向)"},
                "zt_count_250d": {"weight": 0.20, "reverse": False, "label": "涨停频次golden"},
            },
        }

    # 按 |r| 归一化分配权重
    total_abs_r = sum(abs(f["r"]) for f in significant_factors)
    weights = {}
    for f in significant_factors:
        w = abs(f["r"]) / total_abs_r
        weights[f["factor"]] = {
            "weight": round(w, 4),
            "reverse": f["reverse"],
            "label": f["label"],
            "r": f["r"],
            "ci": [f["ci_low"], f["ci_high"]],
        }

    return {
        "method": "r_normalized",
        "note": f"基于 {len(significant_factors)} 个显著因子（CI 排除 0）按 |r| 归一化",
        "weights": weights,
    }


def main() -> int:
    if not SIG_PATH.exists():
        print(f"[0d] 错误: {SIG_PATH} 不存在，请先跑 Phase 0b", flush=True)
        return 1

    sig = load_significance()

    limitup_weights = determine_weights(sig)

    output = {
        "meta": {
            "source": "factor_significance.json",
            "benchmark_A": sig.get("meta", {}).get("benchmark_A"),
            "valid_samples": sig.get("meta", {}).get("valid_samples"),
            "overall_win_rate_o2c": sig.get("overall_win_rates", {}).get("open2close"),
            "generated_note": "权重由 Phase 0b 全样本回归确定，非拍脑袋",
        },
        "weight_sets": {
            "limitup": {
                "applicable_strategies": ["first_plate", "consecutive_relay", "break_reseal", "end_of_day_sneak", "n_shape_counterattack"],
                "formula": "score = Σ(factor_value [× reverse ? (100-x) : x] × weight)",
                **limitup_weights,
            },
            "non_limitup": {
                "applicable_strategies": ["low_absorption", "reverse_package", "platform_breakout", "dragon_head"],
                "method": "equal_weight_pending",
                "note": "等权起步，Phase 2 有数据后单独估参",
                "weights": {
                    "relative_strength": {"weight": 0.25, "label": "相对强度"},
                    "ma_bullish": {"weight": 0.25, "label": "均线多头"},
                    "volume_signal": {"weight": 0.25, "label": "量能信号"},
                    "sector_strength": {"weight": 0.25, "label": "板块强度"},
                },
            },
            "storm_reversal": {
                "applicable_strategies": ["storm_reversal"],
                "method": "fixed",
                "note": "暴风雨逆势涨停，样本极少，固定权重",
                "weights": {
                    "factor_seal_rate": {"weight": 0.60, "reverse": False, "label": "封板率"},
                    "factor_freq_score": {"weight": 0.40, "reverse": True, "label": "涨停频次(反向)"},
                },
            },
        },
        "qualify_threshold": sig.get("qualify_threshold_analysis", {}),
    }

    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"[0d] 输出: {OUT}")
    print(f"[0d] 涨停类权重方法: {limitup_weights['method']}")
    for f, w in limitup_weights.get("weights", {}).items():
        rev = "(反向)" if w.get("reverse") else ""
        print(f"[0d]   {w.get('label', f)}: {w['weight']}{rev}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
