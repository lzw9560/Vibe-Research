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


def _load_code_name_map() -> dict[str, str]:
    """从 gene_scores 表加载 code→name 映射（spec §8 盲点 #6：breakout name 补名）。

    baostock kline bar 无 ``name`` 字段，breakout 候选 name 恒空。从 gene_scores 表
    按 code 查最近一次涨停的 name 补全。查不到的 code 仍返空串（不臆造）。
    """
    try:
        from config import GENE_SCORES_DB_PATH  # noqa: PLC0415
        from db_health import get_healthy_conn  # noqa: PLC0415
        conn = get_healthy_conn(GENE_SCORES_DB_PATH, check_same_thread=False)
        try:
            rows = conn.execute(
                "SELECT code, name FROM gene_scores "
                "WHERE name IS NOT NULL AND name != '' "
                "ORDER BY date DESC"
            ).fetchall()
        finally:
            conn.close()
        # ORDER BY date DESC → 首次出现 = 最新日期的 name
        return {row["code"]: row["name"] for row in rows}
    except Exception:
        return {}

# 诚实标签（不改不撒谎）——数值随 §44 重验更新（2026-08-16 cache 08-14 重验）
HONEST_LABEL = (
    "弱信号（§44 day-cluster lift=1.72x <2x 非 validated edge，"
    "但 robust>1 + PnL spread +0.486%正）。谨慎排序参考，非预测保证。"
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
    # spec §8 盲点 #6：baostock kline bar 无 name 字段，从 gene_scores 表补名
    code_names = _load_code_name_map()
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
        # name 从 gene_scores 表补全（bar 无 name 字段，spec §8 盲点 #6）
        name = code_names.get(code, "")
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


# ===========================================================================
# S071 (b) 风控层：弱信号靠风控非对称补（edge 主来自风控，非 breakout 信号本身）
# ===========================================================================

@dataclass(frozen=True)
class PreMarketRiskParams:
    """盘前选股风控参数（弱信号→小仓+紧止损+非对称 R:R+短持）。"""
    position_pct: float        # 单票仓位 %（× 日历因子后）
    max_positions: int         # 最大持仓数（集中度上限）
    stop_loss_pct: float       # 止损 %（负值，相对入场参考价）
    take_profit_pct: float     # 止盈 %（正值，R:R≈1:2 非对称）
    max_hold_days: int         # 最大持有日（短线，breakout 衰减快）


# 弱信号保守默认（breakout §44 day-cluster 1.72x <2x 非 validated → 小仓紧止损）
_PREMARKET_RISK_BASE = PreMarketRiskParams(
    position_pct=3.0,
    max_positions=3,
    stop_loss_pct=-4.0,
    take_profit_pct=8.0,
    max_hold_days=3,
)


@dataclass(frozen=True)
class PreMarketCandidateRisk:
    """候选 + 风控具体价（止损/止盈/仓位）。"""
    code: str
    name: str
    breakout_score: float
    breakout_binary: int
    t1_close: float
    t1_date: str
    entry_ref: float           # 入场参考价（= T-1 close；实盘以开盘竞价为准）
    stop_loss: float           # 止损价（entry_ref × (1+stop_loss_pct/100)）
    take_profit: float         # 止盈价（entry_ref × (1+take_profit_pct/100)）
    position_pct: float        # 仓位 %（已 × 日历因子）


@dataclass(frozen=True)
class PreMarketSelection:
    """盘前选股完整结果（候选+风控+诚实标签+日历+元信息）。"""
    target_date: str
    honest_label: str
    risk_params: PreMarketRiskParams
    calendar_multiplier: float
    calendar_reason: str
    candidates: list[PreMarketCandidateRisk]
    market_note: str


def select_premarket_with_risk(
    target_date: str, top_n: int = 20, min_score: float = 0.90,
) -> PreMarketSelection:
    """盘前选股 + 风控层（endpoint 入口）。

    breakout 排序 → top-N → 附加风控具体价（止损/止盈/仓位×日历）。
    诚实：honest_label 标弱信号；market_note 标盘前无法判 kill_switch（需盘中指数）。
    """
    from strategies.calendar_factor import calendar_factor

    raw = select_premarket_candidates(target_date, top_n=top_n, min_score=min_score)
    mult, reason = calendar_factor(target_date)
    pos_pct = round(_PREMARKET_RISK_BASE.position_pct * mult, 2)

    candidates = [
        PreMarketCandidateRisk(
            code=c.code, name=c.name, breakout_score=c.breakout_score,
            breakout_binary=c.breakout_binary, t1_close=c.t1_close, t1_date=c.t1_date,
            entry_ref=c.t1_close,
            stop_loss=round(c.t1_close * (1 + _PREMARKET_RISK_BASE.stop_loss_pct / 100), 2),
            take_profit=round(c.t1_close * (1 + _PREMARKET_RISK_BASE.take_profit_pct / 100), 2),
            position_pct=pos_pct,
        )
        for c in raw
    ]
    return PreMarketSelection(
        target_date=target_date,
        honest_label=HONEST_LABEL,
        risk_params=PreMarketRiskParams(
            position_pct=pos_pct,
            max_positions=_PREMARKET_RISK_BASE.max_positions,
            stop_loss_pct=_PREMARKET_RISK_BASE.stop_loss_pct,
            take_profit_pct=_PREMARKET_RISK_BASE.take_profit_pct,
            max_hold_days=_PREMARKET_RISK_BASE.max_hold_days,
        ),
        calendar_multiplier=mult,
        calendar_reason=reason,
        candidates=candidates,
        market_note="盘前选股：market_kill_switch 需盘中指数，盘前不判（开盘后实时核）",
    )


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
