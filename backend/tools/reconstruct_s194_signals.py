#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T5.3 数据重建：给 trade_journal 1092 case 重建 per-case 信号值（breakout + gap）。

输出 JSON 喂 ablation_runner.build_fusion_composite（v2 融合分消融）作 per-case 信号值。
- breakout_score：_compute_breakout(bars, entry_date)（cache bars，无网络）；
- gap_regime：_classify_gap_from_bars(bars, idx) → 序数编码（无=0/噪声=0.1/反转=0.5/中继=0.7/启动=0.9）；
- y=gross_return（% 收益，scale-invariant 优于 net_pnl CNY）；
- ofi（盘中逐笔历史无法回补）+ fund_flow（网络限流慢）本轮跳过，标 missing→0。

用法：python tools/reconstruct_s194_signals.py [limit]  (默认全量，样本先 20)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.bars_provider import KlineCacheBarsProvider
from engine.gap_classifier import _classify_gap_from_bars
from engine.trade_journal import TradeJournal
from strategies.premarket_selection import _compute_breakout

# gap regime → 序数编码（方向性强弱；非严谨验证值，仅喂模型用，下游 ablation 测其预测力）
GAP_REGIME_ENCODE = {
    "无": 0.0,
    "噪声": 0.1,
    "反转": 0.5,  # breakaway down 空头反转（gap_classifier.py:194，仍保留）
    "动能延续": 0.5,  # S198 flip: 衰竭→continuation（gate 5/5 PASS），暂 0.5，S199 方向感知重测 re-tune
    "趋势中继": 0.7,
    "趋势启动": 0.9,
}


def find_idx(bars: list[dict], date: str) -> int | None:
    for i, b in enumerate(bars):
        if b.get("date") == date:
            return i
    return None


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    bp = KlineCacheBarsProvider()
    tj = TradeJournal()
    cases = tj.query_records(is_realized=1, is_dead_arm=0, limit=10000)
    if limit:
        cases = cases[:limit]

    bars_cache: dict[str, list[dict]] = {}

    def get_bars(code: str) -> list[dict]:
        if code not in bars_cache:
            bars_cache[code] = bp(code)
        return bars_cache[code]

    out = []
    skipped_no_bar = skipped_no_idx = 0
    for rec in cases:
        bars = get_bars(rec.stock_code)
        if not bars:
            skipped_no_bar += 1
            continue
        idx = find_idx(bars, rec.entry_date)
        if idx is None or idx < 1:
            skipped_no_idx += 1
            continue
        br = _compute_breakout(bars, rec.entry_date)
        breakout_score = br[0] if br else None
        breakout_binary = br[1] if br else None
        gap = _classify_gap_from_bars(bars, idx)
        regime = gap.get("regime", "无")
        out.append({
            "signal_id": rec.signal_id,
            "stock": rec.stock_code,
            "entry_date": rec.entry_date,
            "arm": rec.arm,
            "gross_return": rec.gross_return,
            "net_pnl": rec.net_pnl,
            "breakout_score": breakout_score,
            "breakout_binary": breakout_binary,
            "gap_regime": regime,
            "gap_regime_encoded": GAP_REGIME_ENCODE.get(regime, 0.0),
            "gap_confidence": gap.get("confidence", 0.0),
            "gap_type": gap.get("type"),
            "gap_direction": gap.get("direction"),
        })

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"# reconstructed {len(out)}/{len(cases)} (skip no_bar={skipped_no_bar} no_idx={skipped_no_idx})",
          file=sys.stderr)


if __name__ == "__main__":
    main()
