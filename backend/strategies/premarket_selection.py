# -*- coding: utf-8 -*-
"""S071：谨慎盘前选股——breakout_20d 弱正信号（§44 <2x 但 day-cluster robust>1 + PnL+0.523%）。

**诚实标注**：breakout_20d 在 §44 day-cluster 下 lift=1.67x（<2x，非 validated edge），
但 robust>1（90%CI 下界>1）+ premium spread +0.523%（正 PnL）。是最弱正信号，谨慎用作排序参考，
不宣称"validated edge"。edge 主要来自风控非对称（(b) ethos），breakout 是 weak ranking signal。

数据：baostock_kline_cache（1121 股 × 日K，本地缓存）。live 需日更 baostock kline（非东财，不被 IP 限流）。
universe：cache 1121 股（§44 测试的 broad set，历史涨停股）。
信号：breakout_20d = T-1 close >= 0.95 × max(high, 前 20 日) → 1（接近新高）+ 连续分数（越接近越高）。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KLINE_CACHE = ROOT.parent / ".vibe-research" / "baostock_kline_cache.json"

# 诚实标签（不改不撒谎）
HONEST_LABEL = (
    "弱信号（§44 day-cluster lift=1.67x <2x 非 validated edge，"
    "但 robust>1 + PnL spread +0.523%正）。谨慎排序参考，非预测保证。"
    "edge 主要来自风控非对称，breakout 是 weak ranking。"
)


@dataclass(frozen=True)
class PreMarketCandidate:
    code: str
    name: str
    breakout_score: float       # 0-1（T-1 close / 20日 max_high，越高越接近新高）
    breakout_binary: int        # 1 = close >= 0.95 × max_high（硬突破）
    t1_close: float
    t1_date: str


def _compute_breakout(bars: list[dict], target_date: str) -> tuple[float, int, float, str] | None:
    """T-1 的 breakout 分数。返 (score, binary, t1_close, t1_date) 或 None。"""
    t1_idx = None
    for i, b in enumerate(bars):
        if b["date"] >= target_date:
            break
        t1_idx = i
    if t1_idx is None or t1_idx < 20:
        return None
    t1 = bars[t1_idx]
    close_t1 = t1.get("close", 0)
    if not close_t1 or close_t1 <= 0:
        return None
    highs_prev = [bars[t1_idx - j].get("high", 0) or 0 for j in range(1, 21)]
    max_high = max(highs_prev) if highs_prev else 0
    if not max_high:
        return None
    score = close_t1 / max_high  # 越接近 1 越接近新高
    binary = 1 if score >= 0.95 else 0
    return round(score, 4), binary, close_t1, t1["date"]


def select_premarket_candidates(
    target_date: str, top_n: int = 20, min_score: float = 0.85,
) -> list[PreMarketCandidate]:
    """盘前选股：按 breakout_20d 排序 → top-N（score >= min_score）。

    target_date: T（选 T 的候选，用 T-1 kline 算 breakout）。
    返回 top-N candidates（breakout 分数降序）。
    """
    cache = json.loads(KLINE_CACHE.read_bytes())
    candidates: list[PreMarketCandidate] = []
    for code, bars in cache.items():
        if not bars:
            continue
        r = _compute_breakout(bars, target_date)
        if r is None:
            continue
        score, binary, t1_close, t1_date = r
        if score < min_score:
            continue
        # name from the last bar (approximate)
        name = bars[t1_idx]["name"] if (t1_idx := _find_t1_idx(bars, target_date)) is not None and "name" in bars[t1_idx] else ""
        candidates.append(PreMarketCandidate(
            code=code, name=name, breakout_score=score,
            breakout_binary=binary, t1_close=t1_close, t1_date=t1_date,
        ))
    candidates.sort(key=lambda c: c.breakout_score, reverse=True)
    return candidates[:top_n]


def _find_t1_idx(bars: list[dict], target_date: str) -> int | None:
    """找 T-1 的 index（最后一个 date < target_date）。"""
    t1_idx = None
    for i, b in enumerate(bars):
        if b["date"] >= target_date:
            break
        t1_idx = i
    return t1_idx


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-08-14"
    cands = select_premarket_candidates(d, top_n=20, min_score=0.90)
    print(f"=== 盘前选股（breakout）{d} ===")
    print(f"诚实标签: {HONEST_LABEL}")
    print(f"候选（breakout>=0.90, top-20）: {len(cands)}")
    for c in cands[:10]:
        print(f"  {c.code} score={c.breakout_score} binary={c.breakout_binary} "
              f"close={c.t1_close} T-1={c.t1_date}")
    if len(cands) > 10:
        print(f"  ... ({len(cands)-10} more)")
