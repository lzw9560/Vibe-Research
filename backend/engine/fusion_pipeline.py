# -*- coding: utf-8 -*-
"""S194 融合管线：给 stock+date 跑全链路信号融合 → fusion_output（feishu bot 生产用）。

链路：bars(cache) → gap regime + breakout_score（信号适配器）→ R1 align_signals →
R2 fewshot retrieve（.vibe-research/s194_signal_values.json case 库）→ R3 FS2 权重
（trade_journal reliability）→ R4 fusion_layer → fusion_output dict。

date=None → 用 bars cache 里该股最新日（bot 问股无日期时用最近交易日）。
case 库模块级缓存（首次 load，后续查询不重读文件）。
ofi/fund_flow 信号未接（同 T5.3 局限：历史逐笔无法回补；fund_flow 网络限流）。
"""
from __future__ import annotations

import json

from engine.bars_provider import KlineCacheBarsProvider
from engine.bayesian_signal_weight import BayesianSignalWeight
from engine.fewshot_retriever import FewshotRetriever
from engine.fusion_layer import fusion_layer
from engine.gap_classifier import _classify_gap_from_bars
from engine.signal_align import align_signals
from engine.trade_journal import TradeJournal
from strategies.premarket_selection import _compute_breakout
from vr_paths import resolve_data_dir

GAP_REGIME_ENCODE: dict[str, float] = {
    "无": 0.0, "噪声": 0.1, "反转": 0.5, "动能延续": 0.5, "趋势中继": 0.7, "趋势启动": 0.9,  # S198 flip: 衰竭→动能延续(continuation, gate 5/5 PASS)，暂 0.5 不改 fusion 行为，S199 方向感知重测 re-tune
}

_EMPTY_FUSION: dict = {
    "regime": "未知", "direction": "中性", "confidence": 0.0,
    "top_similar_cases": [], "signal_weights": {},
}

_case_library_cache: list[dict] | None = None


def _load_case_library() -> list[dict]:
    """模块级缓存 load case 库（.vibe-research/s194_signal_values.json，容错 baostock 污染行）。"""
    global _case_library_cache
    if _case_library_cache is None:
        path = resolve_data_dir() / "s194_signal_values.json"
        if path.exists():
            raw = path.read_text()
            try:
                _case_library_cache = json.loads(raw[raw.index("["):])
            except (json.JSONDecodeError, ValueError):
                _case_library_cache = []
        else:
            _case_library_cache = []
    return _case_library_cache


def compute_fusion_for_query(stock: str, date: str | None = None) -> dict:
    """给 stock+date 跑全链路信号融合 → fusion_output dict。

    Args:
        stock: 6 位股票代码。
        date: YYYY-MM-DD；None → 用 bars cache 里该股最新交易日。

    Returns:
        fusion_output dict {regime, direction, confidence, top_similar_cases, signal_weights}。
        无 bars → 空 fusion（不臆造）。
    """
    bp = KlineCacheBarsProvider()
    bars = bp(stock)
    if not bars:
        return dict(_EMPTY_FUSION)

    # 定 idx：date 给定且在 bars → 用；否则最新日
    idx = None
    if date:
        idx = next((i for i, b in enumerate(bars) if b.get("date") == date), None)
    if idx is None:
        idx = len(bars) - 1
        date = bars[idx].get("date", date or "")

    # 信号适配器：gap（_classify_gap_from_bars）+ breakout（_compute_breakout）
    signals: list[dict] = []
    gap_regime = "无"
    breakout_score = 0.0
    if idx >= 1:
        gap = _classify_gap_from_bars(bars, idx)
        gap_regime = gap.get("regime", "无")
        signals.append({"signal_name": "gap", "value": gap_regime,
                        "confidence": gap.get("confidence", 0.0),
                        "timestamp": date, "source": "S193"})
    br = _compute_breakout(bars, date)
    if br:
        breakout_score = br[0]
        signals.append({"signal_name": "breakout", "value": breakout_score,
                        "confidence": breakout_score, "timestamp": date,
                        "source": "premarket_selection"})

    # R1 对齐
    aligned = align_signals(signals, date)
    # R3 FS2 权重（breakout 从 arm reliability；gap dead_arm 先验）
    tj = TradeJournal()
    agg = tj.aggregate_by_arm(arm="breakout")
    bk = agg.get("breakout", {})
    wr = float(bk.get("execution_winrate", 0.0) or 0.0)
    n = int(bk.get("n_picks", 0) or 0)
    wins = round(wr * n)
    losses = n - wins
    bsw = BayesianSignalWeight()
    fs2 = {"breakout": bsw.weight("breakout", wins, losses), "gap": bsw.weight("gap", 0, 0)}
    # R2 fewshot 检索
    query = {"breakout_score": breakout_score,
             "gap_regime_encoded": GAP_REGIME_ENCODE.get(gap_regime, 0.0)}
    top_cases = FewshotRetriever(_load_case_library()).retrieve(query, top_k=3)
    # R4 融合
    return fusion_layer(aligned, top_cases, fs2)
