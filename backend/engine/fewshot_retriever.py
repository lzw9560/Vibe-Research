# -*- coding: utf-8 -*-
"""S194 R2 · fewshot_retriever——FS1 检索历史相似 case 喂 AI 研判（不过 §44）。

检索 trade_journal 历史 case（用 reconstruct_s194_signals.py 重建的信号值 breakout_score +
gap_regime_encoded 作特征）→ cosine 相似度 top-K → [{case, similarity, outcome}] 喂 AI 综合研判。

⚠️ FS1 不过 §44（spec §2.1 + §3 R2 + spec grill HIGH#3）：
- 非确定：AI 推理同输入不同次跑结论不同；
- 全库 lookahead：检索全历史 case 不区分 in/out-sample（无法 walk-forward OOS 划分）。
→ §44v2 verifier 套不上，FS1 价值靠「AI 研判 + 用户反馈」定性评估，不参与 F1 消融 §44 验证（spec §3 R5 只测 FS2）。
"""
from __future__ import annotations

import numpy as np

# 默认相似度特征（与 reconstruct_s194_signals.py 输出字段一致）
DEFAULT_FEATURE_NAMES: list[str] = ["breakout_score", "gap_regime_encoded"]


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度。任一向量 norm=0 → 0.0（防除零，不崩）。"""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def encode_case(case: dict, feature_names: list[str]) -> np.ndarray:
    """提取 case 的信号值向量（缺/None → 0.0，不臆造）。"""
    return np.array([float(case.get(f, 0.0) or 0.0) for f in feature_names])


def _classify_outcome(net_pnl: float | None) -> str:
    """按 net_pnl 符号分类 outcome（喂 AI 研判用）。"""
    pnl = float(net_pnl) if net_pnl is not None else 0.0
    if pnl > 0:
        return "hit"
    if pnl < 0:
        return "miss"
    return "neutral"


def retrieve(
    query: dict,
    cases: list[dict],
    feature_names: list[str],
    top_k: int = 5,
) -> list[dict]:
    """检索 top-K 相似 case。返 [{case, similarity, outcome}] 按 similarity 降序。

    query: 当天对齐后信号（R1 align_signals 产出 + 适配器抽值）。
    cases: 历史 case 库（reconstruct_s194_signals.py 重建的信号值 + net_pnl）。
    """
    if not cases:
        return []
    q_vec = encode_case(query, feature_names)
    scored = [
        {
            "case": c,
            "similarity": cosine_sim(q_vec, encode_case(c, feature_names)),
            "outcome": _classify_outcome(c.get("net_pnl")),
        }
        for c in cases
    ]
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


class FewshotRetriever:
    """FS1 few-shot 检索器（不过 §44——非确定 AI + 全库 lookahead，spec §2.1 caveat）。

    持 case 库 + feature_names，retrieve 查询当天信号组合 → top-K 相似历史 case 喂 AI。
    """

    def __init__(
        self,
        cases: list[dict],
        feature_names: list[str] | None = None,
    ) -> None:
        self._cases = cases
        self._feature_names = list(feature_names) if feature_names else list(DEFAULT_FEATURE_NAMES)

    def retrieve(self, query: dict, top_k: int = 5) -> list[dict]:
        """查询当天信号组合 → top-K 相似历史 case [{case, similarity, outcome}]。"""
        return retrieve(query, self._cases, self._feature_names, top_k)
