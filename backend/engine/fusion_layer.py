# -*- coding: utf-8 -*-
"""S194 R4 · fusion_layer——综合 FS1 检索 + FS2 权重 + 对齐信号 → 研判产出喂 AI。

fusion_layer(signals_aligned, fs1_results, fs2_weights) → {regime, direction, confidence,
top_similar_cases, signal_weights}。不直接触发买卖（喂 AI 综合研判 + 用户决策，spec §1 弱合规）。

- regime：取 gap 信号 value（缺口 regime 字符串，S193 classify_gap 产）；无 gap → "未知"。
- direction：regime 派生（趋势启动/中继→向上，反转/噪声/无→中性）——反转方向歧义（向下突破 vs 衰竭见顶），
  标中性由 AI 终判。
- confidence：FS2 加权信号置信度 = Σ(sig_conf × fs2_weight) / Σ(fs2_weight)，信号不在 fs2_weights → 权重 0 排除。
- top_similar_cases：FS1 检索结果透传（AI 看历史相似 case + outcome）。
- signal_weights：FS2 权重透传。
"""
from __future__ import annotations

# regime → direction 映射（反转方向歧义标中性由 AI 终判）
_REGIME_DIRECTION: dict[str, str] = {
    "趋势启动": "向上",
    "趋势中继": "向上",
    "反转": "中性",  # 反转歧义（向下突破=空头反转 vs 衰竭=见顶），标中性由 AI 终判
    "噪声": "中性",
    "无": "中性",
    "无缺口": "中性",
}


def fusion_layer(
    signals_aligned: list[dict],
    fs1_results: list[dict],
    fs2_weights: dict[str, float],
) -> dict:
    """综合 FS1 检索 + FS2 权重 + 对齐信号 → 研判产出（喂 AI，不触发买卖）。

    Args:
        signals_aligned: R1 align_signals 产出 [{signal_name, value, confidence, timestamp, source}]。
        fs1_results: R2 fewshot 检索 top-K [{case, similarity, outcome}]（不过 §44，定性）。
        fs2_weights: R3 贝叶斯权重 {signal_name: weight}（可 OOS）。

    Returns:
        {regime, direction, confidence, top_similar_cases, signal_weights}。
    """
    # regime：取 gap 信号 value（缺口 regime 字符串）；无 gap → 未知
    gap_signal = next((s for s in signals_aligned if s.get("signal_name") == "gap"), None)
    regime = gap_signal["value"] if gap_signal else "未知"
    direction = _REGIME_DIRECTION.get(regime, "中性")

    # confidence：FS2 加权信号置信度（信号不在 fs2_weights → 权重 0 排除）
    total_w = sum(fs2_weights.get(s["signal_name"], 0.0) for s in signals_aligned)
    if total_w > 0:
        confidence = sum(
            float(s["confidence"]) * fs2_weights.get(s["signal_name"], 0.0)
            for s in signals_aligned
        ) / total_w
    else:
        confidence = 0.0

    return {
        "regime": regime,
        "direction": direction,
        "confidence": confidence,
        "top_similar_cases": fs1_results,
        "signal_weights": fs2_weights,
    }


def build_fusion_context(fusion_output: dict) -> str:
    """把 fusion_layer 输出 dict 转成 system prompt 用的文本块（T4.2 注入 chat.run_chat）。

    喂 AI 综合研判：regime/方向/置信度 + 信号权重 + top 相似历史 case（FS1 检索，不过§44 定性参考）。
    """
    regime = fusion_output.get("regime", "未知")
    direction = fusion_output.get("direction", "中性")
    confidence = float(fusion_output.get("confidence", 0.0))
    top_cases = fusion_output.get("top_similar_cases") or []
    weights = fusion_output.get("signal_weights") or {}

    lines = [
        f"【信号融合研判】regime={regime} 方向={direction} 置信度={confidence:.2f}",
        "信号权重: " + (", ".join(f"{k}={v:.2f}" for k, v in weights.items()) or "（无）"),
    ]
    if top_cases:
        lines.append("历史相似 case（FS1 检索，不过§44，定性参考）:")
        for i, c in enumerate(top_cases[:3], 1):
            sim = float(c.get("similarity", 0.0))
            outcome = c.get("outcome", "?")
            stock = (c.get("case") or {}).get("stock", "?")
            lines.append(f"  {i}. {stock} 相似度={sim:.2f} 结果={outcome}")
    return "\n".join(lines)
