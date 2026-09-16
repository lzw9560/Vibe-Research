# -*- coding: utf-8 -*-
"""S203 consecutive_relay deep dive——split bull regime picks by lbc 高度/市值/主题，
找 edge 最强子集（从 +1.055% drift-adjusted 往上提）。

探索性（stats only，不跑 verdict——verdict 是 confirm，深挖是 find）。
复用 s203_consecutive_relay_harness 的 compute_obs 口径（decimal gap_ret + D 日一字板 filter）。
"""
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402
from tools.gap_regime_stratified import compute_regime_labels  # noqa: E402
from strategies.kline_returns import _is_unbuyable_next_bar  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402

KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZT_DB = ROOT / ".vibe-research" / "zt_history.db"


def _zt_picks_with_meta() -> list[dict]:
    """zt_history lbc>=2 picks with lbc/hybk/ltsz meta。"""
    if not ZT_DB.exists():
        return []
    conn = sqlite3.connect(str(ZT_DB))
    try:
        rows = conn.execute(
            "SELECT date, code, lbc, hybk, ltsz FROM zt_history "
            "WHERE lbc>=2 AND is_final=1 ORDER BY date"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"date": r[0], "code": r[1], "lbc": r[2], "hybk": r[3], "ltsz": r[4]}
        for r in rows if r[0] and r[1]
    ]


def compute_obs_with_meta(
    cache: dict[str, list[dict]],
    picks: list[dict],
    *,
    cost_fn=_cost_pct,
) -> list[dict]:
    """obs with lbc/hybk/ltsz（decimal gap_ret + D 日一字板 filter）。"""
    obs: list[dict] = []
    for p in picks:
        D, code = p["date"], p["code"]
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
        close_d = float(bars[d_idx].get("close", 0) or 0)
        open_d1 = float(bars[d_idx + 1].get("open", 0) or 0)
        if close_d <= 0 or open_d1 <= 0:
            continue
        gap_ret = (open_d1 - close_d) / close_d  # decimal
        cost_pct = cost_fn(open_d1, 100.0, D) if open_d1 > 0 else 0.0
        cost_dec = cost_pct / 100.0
        net = gap_ret - cost_dec
        obs.append({**p, "net": net, "win": 1 if net > 0 else 0, "cost": cost_dec})
    return obs


def _stats(obs: list[dict]) -> dict:
    if not obs:
        return {"n": 0, "days": 0, "net_mean_pct": None, "wr": None}
    rets = [o["net"] for o in obs]
    days = len(set(o["date"] for o in obs))
    return {
        "n": len(obs),
        "days": days,
        "net_mean_pct": round(statistics.mean(rets) * 100, 4),
        "wr": round(sum(o["win"] for o in obs) / len(obs), 4),
    }


def main() -> dict:
    cache = _load_kline_cache()
    picks = _zt_picks_with_meta()
    regime_map = compute_regime_labels()
    print(f"picks={len(picks)} (lbc>=2)", flush=True)
    if not picks:
        print("[deep_dive] 无 picks")
        return {}

    obs = compute_obs_with_meta(cache, picks)
    bull_obs = [o for o in obs if regime_map.get(o["date"]) == "bull"]
    print(f"obs={len(obs)} bull_obs={len(bull_obs)}", flush=True)

    results: dict = {}

    # ── lbc 高度 split ──
    print("\n=== lbc 高度 split（bull）===")
    lbc_splits = results.setdefault("lbc", {})
    for lbc_val, label in [(2, "lbc=2"), (3, "lbc=3"), (4, "lbc>=4")]:
        sub = bull_obs if lbc_val == 4 else [o for o in bull_obs if o["lbc"] == lbc_val]
        if lbc_val == 4:
            sub = [o for o in bull_obs if o["lbc"] >= 4]
        s = _stats(sub)
        lbc_splits[label] = s
        print(f"  {label}: n={s['n']} days={s['days']} net_mean={s['net_mean_pct']}% wr={s['wr']}")

    # ── 市值 split ──
    print("\n=== 市值 split（bull，ltsz 亿）===")
    cap_splits = results.setdefault("cap", {})
    for lo, hi, label in [(0, 50, "小盘<50亿"), (50, 200, "中盘50-200亿"), (200, 99999, "大盘>=200亿")]:
        sub = [o for o in bull_obs if o["ltsz"] and lo <= float(o["ltsz"]) < hi]
        s = _stats(sub)
        cap_splits[label] = s
        print(f"  {label}: n={s['n']} days={s['days']} net_mean={s['net_mean_pct']}% wr={s['wr']}")

    # ── 主题 top 5 ──
    print("\n=== 主题 top 5（bull）===")
    theme_groups: dict[str, list[dict]] = defaultdict(list)
    for o in bull_obs:
        if o["hybk"]:
            theme_groups[o["hybk"]].append(o)
    theme_splits = results.setdefault("theme", {})
    for theme, sub in sorted(theme_groups.items(), key=lambda x: -len(x[1]))[:5]:
        s = _stats(sub)
        theme_splits[theme] = s
        print(f"  {theme}: n={s['n']} days={s['days']} net_mean={s['net_mean_pct']}% wr={s['wr']}")

    return results


if __name__ == "__main__":
    main()
