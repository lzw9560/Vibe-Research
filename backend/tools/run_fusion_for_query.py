#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T4.2 全链路：给 stock+date 跑信号融合 → fusion_output + context 文本。

链路：bars(cache) → gap regime + breakout_score（信号适配器）→ R1 align_signals →
R2 fewshot retrieve（重建的 case 库）→ R3 FS2 权重（trade_journal reliability）→
R4 fusion_layer → build_fusion_context。验证 chat.run_chat(fusion_output=...) 注入链路通。

⚠️ ofi/fund_flow 信号本轮未接（同 T5.3 局限：ofi 历史逐笔无法回补；fund_flow 网络限流跳）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.bars_provider import KlineCacheBarsProvider
from engine.bayesian_signal_weight import BayesianSignalWeight
from engine.fewshot_retriever import FewshotRetriever
from engine.fusion_layer import build_fusion_context, fusion_layer
from engine.gap_classifier import _classify_gap_from_bars
from engine.signal_align import align_signals
from engine.trade_journal import TradeJournal
from strategies.premarket_selection import _compute_breakout

GAP_REGIME_ENCODE = {"无": 0.0, "噪声": 0.1, "反转": 0.5, "趋势中继": 0.7, "趋势启动": 0.9}


def compute_fusion_for_query(stock: str, date: str, case_library: list[dict]) -> dict:
    """给 stock+date 跑全链路信号融合 → fusion_output dict。"""
    bp = KlineCacheBarsProvider()
    bars = bp(stock)
    idx = next((i for i, b in enumerate(bars) if b.get("date") == date), None)

    signals: list[dict] = []
    gap_regime = "无"
    breakout_score = 0.0
    if idx is not None and idx >= 1:
        gap = _classify_gap_from_bars(bars, idx)
        gap_regime = gap.get("regime", "无")
        signals.append({"signal_name": "gap", "value": gap_regime,
                        "confidence": gap.get("confidence", 0.0), "timestamp": date, "source": "S193"})
    br = _compute_breakout(bars, date) if bars else None
    if br:
        breakout_score = br[0]
        signals.append({"signal_name": "breakout", "value": breakout_score,
                        "confidence": breakout_score, "timestamp": date, "source": "premarket_selection"})

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
    # R2 fewshot 检索（query 用 case 库同特征 breakout_score + gap_regime_encoded）
    query = {"breakout_score": breakout_score, "gap_regime_encoded": GAP_REGIME_ENCODE.get(gap_regime, 0.0)}
    top_cases = FewshotRetriever(case_library).retrieve(query, top_k=3)
    # R4 融合
    return fusion_layer(aligned, top_cases, fs2)


def main() -> None:
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    date = sys.argv[2] if len(sys.argv) > 2 else "2026-09-10"
    raw = Path("/tmp/s194_signals.json").read_text()
    case_library = json.loads(raw[raw.index("["):])
    out = compute_fusion_for_query(stock, date, case_library)
    print(f"=== {stock} @ {date} fusion_output ===")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"\n=== build_fusion_context（注入 chat.run_chat(fusion_output=...) 的 system prompt）===")
    print(build_fusion_context(out))


if __name__ == "__main__":
    main()
