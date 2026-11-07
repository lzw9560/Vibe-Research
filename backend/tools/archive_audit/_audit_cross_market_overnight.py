# -*- coding: utf-8 -*-
"""跨市场隔夜联动验证（2026-10-28，迹#6 唯一未测口径）。

美股隔夜收益（SOX/NDX/SPX/DJI）→ 次日A股开盘 gap selection_lift。
口径：gap-magnitude 连续值 SELECTION（非涨停 selection，避 base rate 0.82% 墙）。
  X = SOX[D-1]/SOX[D-2]-1（美股隔夜收益，point-in-time：美东D-1收盘在北京D凌晨，先于A股D开盘）
  Y = A股[D] open/close[D-1]-1（A股D日开盘gap，连续值每日有值）
§44v3：selection_lift + NW-HAC t + Bonferroni×{SOX,NDX,SPX,DJI} + walk_forward + window-sanity + regime分层。

判定门：SOX top-quartile日 A股均gap >+0.5% 且 p<0.05(未校正) → exploratory(R37)；不过归档。
"""
from __future__ import annotations
import json, sqlite3, sys, statistics, bisect
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data.sources.eastmoney import _DATACENTER_URL
import astock
from s44_verifier.ic_ir import _newey_west_std
from s44_verifier.stats import bonferroni_bh

KLINE_DB = ROOT / ".vibe-research" / "baostock_kline_cache.db"
NW_LAG = 5
PUSH2HIS_UT = "fa5fd1943c7b386f172d6893dbbd10d0"  # 东财公开 token


# ── 1. 拉美股指数历史 ──
def fetch_sox_history() -> dict[str, float]:
    """SOX datacenter RPT_INDUSTRY_INDEX EMI00055562 分页拉 32 年。返 {date: close}。"""
    out = {}
    # sortTypes="-1" 降序（最新在前）——升序分页在 datacenter 2013 处断（实测），
    # 降序能取到 2026（gstock.py:116 项目 _fetch_sox_datacenter 实测 2026-08-20）。
    # 覆盖 A股 cache 窗口（2018-2026 ~2136 日）需 ~6 页，拉 8 页保险。
    for page in range(1, 9):
        params = {
            "reportName": "RPT_INDUSTRY_INDEX", "columns": "ALL",
            "filter": '(INDICATOR_ID="EMI00055562")',
            "pageNumber": str(page), "pageSize": "400",
            "sortColumns": "REPORT_DATE", "sortTypes": "-1",
            "source": "WEB", "client": "WEB",
        }
        try:
            d = astock.em_get(_DATACENTER_URL, params=params, timeout=15).json()
        except Exception as e:
            print(f"  SOX page {page} err: {e}")
            break
        rows = (d.get("result") or {}).get("data") or []
        if not rows:
            break
        for r in rows:
            dt = r.get("REPORT_DATE", "")[:10]
            val = r.get("INDICATOR_VALUE")
            if dt and isinstance(val, (int, float)):
                out[dt] = float(val)
        if len(rows) < 400:
            break
    return out


def fetch_push2his_index(secid: str, name: str) -> dict[str, float]:
    """push2his kline/get 拉指数历史（NDX/SPX/DJI）。熔断则返 {}。"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "klt": "101", "fqt": "0",
        "beg": "19900101", "end": "20261028",
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ut": PUSH2HIS_UT,
    }
    try:
        d = astock.em_get(url, params=params, timeout=15).json()
    except Exception as e:
        print(f"  {name} push2his err: {e}")
        return {}
    klines = (d.get("data") or {}).get("klines") or []
    out = {}
    for k in klines:
        parts = k.split(",")
        if len(parts) >= 3:
            out[parts[0]] = float(parts[2])  # f51=date, f52=open, f53=close
    return out


# ── 2. A股每日 gap + window-sanity（单遍历 baostock cache，8.8M bar 一次过）──
def compute_a_share_gap_and_window() -> tuple[dict[str, list[float]], dict[str, float], dict]:
    """单遍历返 (by_date_per_stock, by_date_mean, window_stats)。
    window_stats: overnight(D收→D+1开) + D+1 intraday(开→收) 全市场分布。"""
    conn = sqlite3.connect(str(KLINE_DB), timeout=10)
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date = {}
    prev_close = {}  # code -> prev_close
    overnight_vals = []
    intraday_vals = []
    for code, bj in rows:
        try:
            bars = json.loads(bj)
        except Exception:
            continue
        for b in bars:
            d = b.get("date", "")
            o = float(b.get("open", 0) or 0)
            c = float(b.get("close", 0) or 0)
            if not d or not o or not c:
                continue
            if code in prev_close and prev_close[code] > 0:
                gap = (o - prev_close[code]) / prev_close[code] * 100
                by_date.setdefault(d, []).append(gap)
                overnight_vals.append(gap)
                if o:
                    intraday_vals.append((c - o) / o * 100)
            prev_close[code] = c
    by_date_mean = {d: statistics.mean(gs) for d, gs in by_date.items() if gs}

    def _s(vals):
        if not vals:
            return None
        return {"n": len(vals), "mean": round(statistics.mean(vals), 4),
                "wr": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)}
    window = {"overnight_D_to_D1_open": _s(overnight_vals),
              "D1_intraday_open_to_close": _s(intraday_vals)}
    return by_date, by_date_mean, window


# ── 3. 对齐 + selection_lift + NW-HAC t ──
def selection_lift(us_close_by_date: dict[str, float], a_gap_mean: dict[str, float], label: str) -> dict:
    """美股 D-1 收益 top-quartile 日 vs control 的 A股 D gap 均值差异 + NW-HAC t。"""
    us_dates = sorted(us_close_by_date.keys())
    aligned = []  # (us_ret, a_gap, date)
    a_dates = sorted(a_gap_mean.keys())
    for ad in a_dates:
        idx = bisect.bisect_left(us_dates, ad) - 1
        if idx < 1:
            continue
        d1, d2 = us_dates[idx], us_dates[idx - 1]
        c1, c2 = us_close_by_date.get(d1), us_close_by_date.get(d2)
        if not c1 or not c2:
            continue
        us_ret = (c1 - c2) / c2 * 100
        aligned.append((us_ret, a_gap_mean[ad], ad))
    if len(aligned) < 60:
        return {"label": label, "n": len(aligned), "verdict": "underpowered"}
    sox_rets = [x[0] for x in aligned]
    q75 = float(np.percentile(sox_rets, 75))
    q25 = float(np.percentile(sox_rets, 25))
    top_gaps = [g for s, g, d in aligned if s >= q75]
    ctrl_gaps = [g for s, g, d in aligned if s < q75]
    bot_gaps = [g for s, g, d in aligned if s <= q25]
    if not top_gaps or not ctrl_gaps:
        return {"label": label, "n": len(aligned), "verdict": "no_split"}
    top_mean = statistics.mean(top_gaps)
    ctrl_mean = statistics.mean(ctrl_gaps)
    diff = top_mean - ctrl_mean
    top_nw = _newey_west_std(top_gaps, lag=NW_LAG)
    ctrl_nw = _newey_west_std(ctrl_gaps, lag=NW_LAG)
    pooled_se = (top_nw**2 / len(top_gaps) + ctrl_nw**2 / len(ctrl_gaps))**0.5
    t = diff / pooled_se if pooled_se > 0 else 0
    from statistics import NormalDist
    p = 2 * (1 - NormalDist().cdf(abs(t)))
    # walk-forward：按时间 70/30 split
    cut = int(len(aligned) * 0.7)
    train = aligned[:cut]
    test = aligned[cut:]
    def _lift(seg):
        if not seg:
            return None
        sr = [x[0] for x in seg]
        q = np.percentile(sr, 75)
        tg = [g for s, g, d in seg if s >= q]
        cg = [g for s, g, d in seg if s < q]
        if not tg or not cg:
            return None
        return round(statistics.mean(tg) - statistics.mean(cg), 4)
    return {
        "label": label, "n": len(aligned), "n_top": len(top_gaps), "n_ctrl": len(ctrl_gaps),
        "top_mean_gap_pct": round(top_mean, 4), "ctrl_mean_gap_pct": round(ctrl_mean, 4),
        "diff_pct": round(diff, 4), "nw_t": round(t, 2), "p_uncorr": round(p, 4),
        "us_q75_pct": round(q75, 2),
        "bot_mean_gap_pct": round(statistics.mean(bot_gaps), 4) if bot_gaps else None,
        "walk_train_diff": _lift(train), "walk_test_diff": _lift(test),
    }


# ── 4. regime 分层（breadth，用 ashare_regime_monitor 口径简化）──
def regime_stratify(us_close: dict, a_gap_mean: dict, a_gap_per_stock: dict) -> dict:
    """breadth<40%（熊段）vs >40%（牛段）分层。简化：用每日 gap>0 比例代理 breadth。"""
    # 简化 breadth：每日 gap>0 的股占比
    breadth = {d: sum(1 for g in gs if g > 0)/len(gs) for d, gs in a_gap_per_stock.items() if gs}
    us_dates = sorted(us_close.keys())
    bull, bear = [], []
    for ad, br in breadth.items():
        idx = bisect.bisect_left(us_dates, ad) - 1
        if idx < 1:
            continue
        c1, c2 = us_close.get(us_dates[idx]), us_close.get(us_dates[idx-1])
        if not c1 or not c2:
            continue
        us_ret = (c1 - c2) / c2 * 100
        if us_ret < float(np.percentile([us_ret], 75)):  # 只看 top SOX 日
            continue
        slot = bull if br > 0.4 else bear
        slot.append(a_gap_mean.get(ad, 0))
    def _s(vals):
        if not vals:
            return None
        return {"n": len(vals), "mean_gap_pct": round(statistics.mean(vals), 4)}
    return {"bull_breadth_gt40": _s(bull), "bear_breadth_lt40": _s(bear)}


# ── main ──
def main():
    print("=== 拉美股指数历史 ===")
    print("SOX datacenter 分页...")
    sox = fetch_sox_history()
    print(f"  SOX: {len(sox)} 日, {min(sox)}~{max(sox)}")
    ndx = fetch_push2his_index("100.NDX", "NDX")
    print(f"  NDX: {len(ndx)} 日")
    spx = fetch_push2his_index("100.SPX", "SPX")
    print(f"  SPX: {len(spx)} 日")
    dji = fetch_push2his_index("100.DJIA", "DJI")
    print(f"  DJI: {len(dji)} 日")

    print("\n=== A股每日 gap + window-sanity（baostock cache 单遍历）===")
    a_per_stock, a_mean, ws = compute_a_share_gap_and_window()
    print(f"  A股: {len(a_mean)} 日, gap 均值 {statistics.mean(a_mean.values()):.4f}%")
    print(f"  overnight(D收→D+1开): {ws['overnight_D_to_D1_open']}")
    print(f"  D+1 intraday(开→收): {ws['D1_intraday_open_to_close']}")

    print("\n=== selection_lift（top-quartile 美股日 vs control）===")
    results = []
    for label, us in [("SOX", sox), ("NDX", ndx), ("SPX", spx), ("DJI", dji)]:
        if len(us) < 60:
            print(f"  {label}: data-blocked (n={len(us)})")
            results.append({"label": label, "verdict": "data_blocked", "n": len(us)})
            continue
        r = selection_lift(us, a_mean, label)
        results.append(r)
        if r.get("verdict") in ("underpowered", "no_split", "data_blocked"):
            print(f"  {label}: {r.get('verdict')} (n={r.get('n')})")
        else:
            print(f"  {label}: n={r['n']} top={r['top_mean_gap_pct']}% ctrl={r['ctrl_mean_gap_pct']}% diff={r['diff_pct']}% NW-t={r['nw_t']} p={r['p_uncorr']} walk_train={r['walk_train_diff']} walk_test={r['walk_test_diff']}")

    print("\n=== Bonferroni 校正 ===")
    valid_p = [r["p_uncorr"] for r in results if "p_uncorr" in r and r.get("p_uncorr") is not None]
    if valid_p:
        adj = bonferroni_bh(valid_p, n=len(valid_p), method="bonferroni")
        for r, pa in zip([r for r in results if "p_uncorr" in r], adj):
            r["p_bonf"] = round(pa, 4)
            print(f"  {r['label']}: p_uncorr={r['p_uncorr']} p_bonf={pa:.4f}")

    print("\n=== regime 分层（SOX top-quartile 日，breadth>40% vs <40%）===")
    if sox:
        rs = regime_stratify(sox, a_mean, a_per_stock)
        print(f"  牛段(breadth>40%): {rs['bull_breadth_gt40']}")
        print(f"  熊段(breadth<40%): {rs['bear_breadth_lt40']}")

    print("\n=== 判定 ===")
    sox_r = next((r for r in results if r.get("label") == "SOX"), {})
    if sox_r.get("top_mean_gap_pct") is not None:
        top_gap = sox_r["top_mean_gap_pct"]
        p = sox_r.get("p_uncorr", 1)
        if top_gap > 0.5 and p < 0.05:
            print(f"  ✅ SOX top-quartile 日 A股均gap {top_gap}% >+0.5% 且 p={p}<0.05 → exploratory(R37)")
            print(f"  过门，值得回补 NDX 多年跑真 walk-forward 开 spec")
        else:
            print(f"  ❌ SOX top-quartile 日 A股均gap {top_gap}% 或 p={p} 不过门 → 归档同迹1-5")
        print(f"  net 可交易性 caveat: 即便显著，realistic US→A lift 1.5-3x net<0.3% 低于可交易门槛")


if __name__ == "__main__":
    main()
