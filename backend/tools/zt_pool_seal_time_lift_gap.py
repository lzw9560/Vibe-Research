# -*- coding: utf-8 -*-
# GAP-WINDOW VARIANT of zt_pool_seal_time_lift.py (2026-09-18, T+1 research lever).
#
# §44 v1 wrong-window bug: zt_pool_seal_time_lift.py tested late_lock on the PATH
# window (D+1-open→D+4-close, simulate_holding -3/+8/3) = the reversal NEGATIVE
# segment after the overnight gap, and concluded "no edge" (S156 0.663x / recorder
# 0.6201 n=63 d=11). The real edge (if any) lives in the GAP window (D-close→D+1-open)
# where consecutive_relay's edge lives. This variant swaps path_return→gap_net_return,
# keeping late_lock definition + data source IDENTICAL so gap vs path is apples-to-apples
# (only the return window differs).
#
# CONFLICT RESOLUTION (0.663 vs 1.356): two DIFFERENT harnesses measure "late_lock":
#   (A) zt_pool_seal_time_lift.py — akshare em `首次封板时间` (first_lock HHMMSS),
#       late_lock = first_lock > "140000". Verdict 0.6201 (n=63 d=11). = "0.663x" S156.
#   (B) first_plate_h2_lift.py — H2 5min-bar-DERIVED first_lock_time (baostock 5min),
#       late_lock = suffix > LATE_LOCK_CUTOFF. Verdict 1.3326 (n=94 d=38). = "1.356".
# (A) is the authoritative em-reported seal timestamp; (B) is a 5min-granularity
# DERIVED approximation (when price first touches limit-up) — methodology variance.
# UNIFY on (A) em-sourced fbt: akshare cache + zt_history em-source rows, both from
# em push2ex getTopicZTPool, same `首次封板时间` field. late_lock = fbt > 14:00:00.
#
# DATA LIMITATION (honest): the 315-day zt_history backfill is hithink-sourced and
# hithink does NOT provide fbt (首封时间) — 12590 hithink rows have fbt=NULL. fbt is
# only non-null for em-source rows (26 dates) + akshare cache (16 non-empty dates) =
# ~52 dates union. So late_lock CANNOT be run on 315 days; max ~52 em-fbt dates.
# (H2 5min-derived covers 31 dates — a cross-check, not the unified source.)
#
# REALIZABILITY CAVEAT: late_lock stocks sealed AFTER 14:00 → at D close they ARE
# limit-up/sealed → buying at D close is NOT realizable (no sellers). Same caveat as
# consecutive_relay gap measurement (sealed D收买不到, 需盘中打板). The gap return here is
# a MEASUREMENT of the overnight gap for late-seal stocks, not a directly tradeable P&L.
"""GAP-window re-run of late_lock (尾盘突袭, 首封>14:00).

Swap path_return (simulate_holding -3/+8/3, D+1-open→D+4-close) → gap_net_return
(accounting.py:262, D-close→D+1-open, no stop/take). late_lock definition + em fbt
data source IDENTICAL to zt_pool_seal_time_lift.py — only the return window changes.
"""
import datetime
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from data_quality.schema_validator import validate_or_reject
from engine.accounting import _cost_pct, gap_net_return  # noqa: E402
from tools._s44_wire import wire_verdict  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402

KLINE_CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZT_CACHE = ROOT / ".vibe-research" / "zt_pool_hist_cache.json"
ZT_HISTORY_DB = ROOT / ".vibe-research" / "zt_history.db"
DB = ROOT / ".vibe-research" / "gene_scores.db"
FROZEN = "lategap1"  # gap-window variant (methodology pre-register, not path harness)
TOL = 0.01  # 一字板价格容差


def _hhmmss(v) -> str:
    """归一 首封时间 → 6 位 HHMMSS，左填零（非右填）。

    em fbt float 92500.0 = 09:25:00 → "092500"（float str "92500.0" 去点会误加尾零，
    故 numeric 走 int 格式化）；akshare str "092500"/"142650" 已 6 位。
    """
    if v is None:
        return "000000"
    if isinstance(v, (int, float)):
        return f"{int(round(v)):06d}"  # 92500.0→"092500", 142650.0→"142650"
    digits = "".join(c for c in str(v) if c.isdigit())
    return digits.rjust(6, "0")[-6:] if len(digits) >= 6 else digits.rjust(6, "0")


def is_one_word_d(bar: dict) -> bool:
    """D 日一字板：open≈high≈low≈close（封死不可买）。late_lock 股晚封非一字，但守门。"""
    o, h, l, c = bar.get("open") or 0, bar.get("high") or 0, bar.get("low") or 0, bar.get("close") or 0
    if not (o and h and l and c):
        return False
    return abs(h - l) <= TOL and abs(o - c) <= TOL and abs(h - o) <= TOL


def load_em_fbt_lookup() -> dict:
    """UNION em 首封时间：akshare cache (first_lock str) + zt_history em (fbt float)。
    返 {(date_iso, code6): hhmmss_str}。两源同 em push2ex getTopicZTPool，字段一致。"""
    lookup: dict[str, str] = {}
    # 1. akshare cache (YYYYMMDD keys)
    if ZT_CACHE.exists():
        cache = json.loads(ZT_CACHE.read_text())
        for dc, rows in cache.items():
            if not rows:
                continue
            d_iso = f"{dc[:4]}-{dc[4:6]}-{dc[6:]}"
            for r in rows:
                fl = _hhmmss(r.get("first_lock"))
                if fl and fl != "000000":
                    lookup[(d_iso, str(r.get("code", "")).zfill(6))] = fl
    # 2. zt_history em-source fbt (YYYY-MM-DD, float HHMMSS)
    if ZT_HISTORY_DB.exists():
        conn = sqlite3.connect(str(ZT_HISTORY_DB), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            for r in conn.execute(
                "SELECT date, code, fbt FROM zt_history WHERE source='em' AND fbt IS NOT NULL"
            ):
                fl = _hhmmss(r["fbt"])
                if fl and fl != "000000":
                    lookup[(r["date"], str(r["code"]).zfill(6))] = fl
        finally:
            conn.close()
    return lookup


def build_obs(kline: dict, fbt_lookup: dict) -> list[dict]:
    """逐 (D, code) 算 gap_net_return(D close→D+1 open)。返 obs list。"""
    obs: list[dict] = []
    for (d_iso, code), fl in fbt_lookup.items():
        bars = kline.get(code)
        if not bars:
            continue
        d_idx = next((i for i, b in enumerate(bars) if str(b["date"])[:10] == d_iso), None)
        if d_idx is None or d_idx + 1 >= len(bars):
            continue
        d_bar, d1_bar = bars[d_idx], bars[d_idx + 1]
        if is_one_word_d(d_bar):
            continue  # D 日一字板封死（late_lock 罕见但守门）
        close_d = float(d_bar.get("close") or 0)
        open_d1 = float(d1_bar.get("open") or 0)
        if close_d <= 0 or open_d1 <= 0:
            continue
        net_ratio, cost_pct, gross_ratio = gap_net_return(close_d, open_d1, d_iso, 100.0)
        net_pct = net_ratio * 100.0  # ratio→percentage points (与 path harness net 同单位)
        is_late = fl > "140000"
        obs.append({
            "D": d_iso, "code": code, "first_lock": fl, "is_late": is_late,
            "net_pct": net_pct, "gross_pct": gross_ratio * 100.0, "cost_pct": cost_pct,
            "win": 1 if net_pct > 0 else 0,
        })
    return obs


def winrate_lift(obs: list[dict], key: str, wr_all: float) -> tuple[float, int] | None:
    """逐日聚合 survivor winrate / universe winrate → lift。matching path harness lift_for。"""
    top_wins, top_n = 0, 0
    for d_iso in {o["D"] for o in obs}:
        day = [o for o in obs if o["D"] == d_iso]
        if len(day) < 5:
            continue
        top = [o for o in day if o[key]]
        top_wins += sum(o["win"] for o in top)
        top_n += len(top)
    if not top_n:
        return None
    return (top_wins / top_n) / wr_all if wr_all else 0.0, top_n


def mean_lift(obs: list[dict], key: str, mean_all: float) -> tuple[float, int] | None:
    """逐日聚合 survivor mean-net / universe mean-net → mean lift（gap 连续收益更合 mean）。"""
    top_rets, top_n = [], 0
    for d_iso in {o["D"] for o in obs}:
        day = [o for o in obs if o["D"] == d_iso]
        if len(day) < 5:
            continue
        top = [o for o in day if o[key]]
        top_rets += [o["net_pct"] for o in top]
        top_n += len(top)
    if not top_n:
        return None
    return (statistics.mean(top_rets) / mean_all) if mean_all else 0.0, top_n


def main() -> None:
    kline = _load_kline_cache()
    validate_or_reject(
        "baostock_kline",
        [b for bars in kline.values() for b in bars],
        as_of=datetime.date.today().isoformat(),
    )
    fbt_lookup = load_em_fbt_lookup()
    print(f"em fbt lookup: {len(fbt_lookup)} (date,code) pairs", flush=True)
    obs = build_obs(kline, fbt_lookup)
    days = len({o["D"] for o in obs})
    late_obs = [o for o in obs if o["is_late"]]
    late_days = len({o["D"] for o in late_obs})
    if len(obs) < 30:
        print(f"n={len(obs)} <30 探索性 (315-day hithink backfill 缺 fbt，无法补)")
        return
    wr_all = sum(o["win"] for o in obs) / len(obs)
    mean_all = statistics.mean(o["net_pct"] for o in obs)
    print(f"\nGAP window (D收→D+1开) all: n={len(obs)} days={days} "
          f"net_mean={mean_all:.3f}% net_WR={wr_all*100:.1f}% "
          f"(扣 cost~{sum(o['cost_pct'] for o in obs)/len(obs):.2f}%)")
    print(f"late_lock(首封>14:00): n={len(late_obs)} days={late_days}\n")

    # winrate lift (comparable to path harness)
    wl = winrate_lift(obs, "is_late", wr_all)
    if wl:
        wl_lift, wl_n = wl
        st = "VALIDATED(≥2)" if wl_lift >= 2 else ("未validated(≥1)" if wl_lift >= 1 else "劣于随机")
        print(f"  late_lock winrate-lift = {wl_lift:.3f}x (n={wl_n}) vs all {wr_all*100:.1f}% | {st}")
    # mean lift (gap is continuous return — mean more honest than winrate)
    ml = mean_lift(obs, "is_late", mean_all)
    if ml:
        ml_lift, ml_n = ml
        st = "VALIDATED(≥2)" if ml_lift >= 2 else ("未validated(≥1)" if ml_lift >= 1 else "劣于随机")
        print(f"  late_lock mean-lift    = {ml_lift:.3f}x (n={ml_n}) vs all {mean_all:.3f}% | {st}")

    # ── §44 wire (selection edge: does late-seal predict bigger gap among 涨停股) ──
    universe_by_day, surv_by_day = {}, {}
    for d_iso in {o["D"] for o in obs}:
        day = [o for o in obs if o["D"] == d_iso]
        if len(day) < 5:
            continue
        universe_by_day[d_iso] = [o["net_pct"] for o in day]
        top = [o["net_pct"] for o in day if o["is_late"]]
        if top:
            surv_by_day[d_iso] = top
    rets = [r for rs in surv_by_day.values() for r in rs]
    dts = [d for d, rs in surv_by_day.items() for _ in rs]
    if len(rets) >= 2:
        v = wire_verdict(
            line_id="zt_pool_seal_time_gap:late_lock",
            returns=rets,
            dates=dts,
            edge_type="selection",
            frozen_commit=FROZEN,
            survivors_by_day=surv_by_day,
            universe_by_day=universe_by_day,
            n_comparisons=1,
            round_trip_cost=round(sum(o["cost_pct"] for o in obs) / len(obs), 4) if obs else 0.0,
            script="tools/zt_pool_seal_time_lift_gap.py",
            params={
                "arm": "late_lock", "window": "gap(D收→D+1开)",
                "source": "em_fbt(akshare+zt_history)", "cutoff": "14:00:00",
                "realizability": "sealed_at_close(not_tradeable)",
            },
        )
        print(f"\n[§44] zt_pool_seal_time_gap:late_lock → status={v.status} "
              f"selection_lift={v.selection_lift} n={v.n} days_robust={v.days_robust}")
        print(f"       note: {v.note}")
    else:
        print(f"\n[§44] skips (n={len(rets)}<2 survivors)")


if __name__ == "__main__":
    main()
