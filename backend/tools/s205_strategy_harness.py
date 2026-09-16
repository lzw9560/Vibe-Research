# -*- coding: utf-8 -*-
"""S212 S205 4 战法 caller——跑历史 picks 算 returns 传 regime-stratified harness。

套 consecutive_relay caller 模板（s203_consecutive_relay_harness.py）+ s205_match。
4 战法（除 auction_signal BLOCKER）：ruozhuanqiang/nzi_fanji/dixi_longtou/xingtai_fanbao。

msc=None（market_scan_ctx 历史难 get——_msc_* helpers 返 0，诚实不臆造）。
bars-based indicators（compute_volume_rhythm/pullback/reversal_confirm）从 baostock bars 算。
命中 = s205_match composite > 30（MATCH_THRESHOLD 0.3 × 100）。

口径：decimal gap_ret + D 日一字板 filter + _cost_pct/100 + drift fix（universe_by_day）。

跑法：cd backend && .venv/bin/python tools/s205_strategy_harness.py [战法名]
"""
import importlib
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data_quality.schema_validator import validate_or_reject  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402
from tools.gap_regime_stratified import (  # noqa: E402
    compute_market_o2c_gap_by_date,
    compute_regime_labels,
)
from strategies import s205_match  # noqa: E402
from strategies.kline_returns import _is_unbuyable_next_bar  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402

KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZT_DB = ROOT / ".vibe-research" / "zt_history.db"

STRATEGY_FUNCS = {
    "ruozhuanqiang": s205_match.match_ruozhuanqiang,
    "nzi_fanji": s205_match.match_nzi_fanji,
    "dixi_longtou": s205_match.match_dixi_longtou,
    "xingtai_fanbao": s205_match.match_xingtai_fanbao,
}
HARNESS_MODULES = {
    "ruozhuanqiang": "tools.regime_stratified_ruozhuanqiang_lift",
    "nzi_fanji": "tools.regime_stratified_nzi_fanji_lift",
    "dixi_longtou": "tools.regime_stratified_dixi_longtou_lift",
    "xingtai_fanbao": "tools.regime_stratified_xingtai_fanbao_lift",
}


def _zt_picks() -> list[tuple[str, str]]:
    """zt_history lbc>=1 涨停池 picks（date, code）。"""
    if not ZT_DB.exists():
        return []
    conn = sqlite3.connect(str(ZT_DB))
    try:
        rows = conn.execute(
            "SELECT date, code FROM zt_history WHERE lbc>=1 AND is_final=1 ORDER BY date"
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], r[1]) for r in rows if r[0] and r[1]]


def compute_obs(
    cache: dict[str, list[dict]],
    picks: list[tuple[str, str]],
    match_fn,
    *,
    msc: dict | None = None,
    cost_fn=_cost_pct,
) -> list[dict]:
    """命中 picks 算 returns（match threshold + decimal gap + D 日一字板 filter）。

    match_fn(code, date, bars, msc) 返 composite or None（None=不命中）。
    命中后算 gap_ret=(open[D+1]-close[D])/close[D]（decimal）+ cost。
    """
    obs: list[dict] = []
    for D, code in picks:
        bars = cache.get(code)
        if not bars:
            continue
        d_idx = next(
            (i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == D),
            None,
        )
        if d_idx is None or d_idx + 1 >= len(bars):
            continue
        if _is_unbuyable_next_bar(bars[d_idx]):
            continue  # D 日一字板封死（入场日 close 买不到）
        score = match_fn(code, D, bars=bars, msc=msc)
        if score is None:
            continue  # 不命中（composite <= 30）
        close_d = float(bars[d_idx].get("close", 0) or 0)
        open_d1 = float(bars[d_idx + 1].get("open", 0) or 0)
        if close_d <= 0 or open_d1 <= 0:
            continue
        gap_ret = (open_d1 - close_d) / close_d  # decimal
        cost_pct = cost_fn(open_d1, 100.0, D) if open_d1 > 0 else 0.0
        cost_dec = cost_pct / 100.0
        net = gap_ret - cost_dec
        obs.append(
            {"D": D, "code": code, "net": net, "win": 1 if net > 0 else 0,
             "cost": cost_dec, "score": score}
        )
    return obs


def main(战法: str = "ruozhuanqiang") -> dict:
    """跑指定战法 §44 regime-stratified verdict。"""
    if 战法 not in STRATEGY_FUNCS:
        print(f"[S205] 未知战法 {战法}，可选: {list(STRATEGY_FUNCS)}")
        return {}
    cache = _load_kline_cache()
    import datetime  # noqa: PLC0415
    validate_or_reject(
        "baostock_kline",
        [b for bars in cache.values() for b in bars],
        as_of=datetime.date.today().isoformat(),
    )
    picks = _zt_picks()
    regime_map = compute_regime_labels()
    print(f"[{战法}] picks={len(picks)} (lbc>=1)", flush=True)
    if not picks:
        print(f"[{战法}] 无 picks → underpowered")
        return {"status": "underpowered", "n": 0, "reason": "no picks"}

    match_fn = STRATEGY_FUNCS[战法]
    obs = compute_obs(cache, picks, match_fn, msc=None)  # msc 历史难 get → None
    n_obs = len(obs)
    days = len(set(o["D"] for o in obs))
    print(f"[{战法}] 命中 obs={n_obs} days={days} (msc=None，bars-based indicators)", flush=True)
    if n_obs < 30:
        print(f"[{战法}] n={n_obs}<30 → underpowered（诚实，R6 gate）")
        return {"status": "underpowered", "n": n_obs, "days": days, "reason": "n<30"}

    rets = [o["net"] for o in obs]
    dts = [o["D"] for o in obs]
    mean_cost = sum(o["cost"] for o in obs) / n_obs
    universe_by_day = compute_market_o2c_gap_by_date()
    print(f"[{战法}] drift market o2c gap: {len(universe_by_day)} 天", flush=True)

    harness_mod = importlib.import_module(HARNESS_MODULES[战法])
    results = harness_mod.run(
        returns=rets, dates=dts, regime_map=regime_map,
        universe_by_day=universe_by_day,
        round_trip_cost=round(mean_cost, 6),
    )
    wr = sum(o["win"] for o in obs) / n_obs
    net_mean = statistics.mean(rets)
    print(
        f"[{战法}] all net-WR: {wr*100:.2f}% net_mean={net_mean*100:.2f}% "
        f"(扣 cost ~{mean_cost*100:.2f}%)",
        flush=True,
    )
    print(f"\n[{战法}] verdict:")
    for tag, r in results.items():
        st = r.get("verdict_status", "?")
        print(
            f"  {tag}: n={r.get('n_picks')} days={r.get('n_days')} "
            f"net_mean={r.get('net_mean_pct')} wr={r.get('win_rate')} verdict={st}"
        )
    return {"results": results, "n_obs": n_obs, "days": days,
            "net_mean_pct": round(net_mean * 100, 4), "net_wr": round(wr, 4)}


if __name__ == "__main__":
    战法 = sys.argv[1] if len(sys.argv) > 1 else "ruozhuanqiang"
    main(战法)
