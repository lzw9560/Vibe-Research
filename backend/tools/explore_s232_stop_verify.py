# -*- coding: utf-8 -*-
"""验证 S232 -3% stop 是否真 edge——4 维审视。

1. 复现 exit_optimization grid（确认 636 records, -3% stop +1.75%, baseline +0.70%）
2. stop-fill over-credit：t2_open < stop_price（gap 穿 stop）时真实成交 = t2_open 非 stop_price
3. honest close_ev -3% stop：entry T+1 close（post-confirmation 隔离 T+1 日内泄漏），
   看 -3% stop 在诚实口径下是否还正
4. t-stat + Bonferroni：20 grid cells，best vs baseline 显著性

跑法：cd backend && .venv/bin/python tools/explore_s232_stop_verify.py
"""
from __future__ import annotations
import json
import math
import sqlite3
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".vibe-research"
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

TURN_THRESHOLD = 20.0
VR5_THRESHOLD = 2.0


def load_kline_db() -> dict[str, list[dict]]:
    """从 SQLite 读 kline（code -> sorted bars）。"""
    conn = sqlite3.connect(str(KLINE_DB))
    out: dict[str, list[dict]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(bars, list) and bars:
            out[code] = sorted(bars, key=lambda b: b.get("date", ""))
    conn.close()
    return out


def load_zt_by_date() -> dict[str, set[str]]:
    c = sqlite3.connect(str(ZT_DB))
    zt: dict[str, set[str]] = {}
    for d, code in c.execute("SELECT date, code FROM zt_history"):
        zt.setdefault(d, set()).add(code)
    c.close()
    return zt


def vol_ratio_5(bars: list[dict], idx: int) -> float | None:
    if idx < 5:
        return None
    vol = bars[idx].get("volume")
    if not vol:
        return None
    pv = [b.get("volume") for b in bars[idx - 5:idx]]
    if any(v is None or v == 0 for v in pv):
        return None
    avg5 = sum(pv) / 5.0
    return vol / avg5 if avg5 else None


def gen_watchlist(t: str, all_bars, zt_t: set[str]) -> list[str]:
    out = []
    for code, bars in all_bars.items():
        tbar = None
        tidx = -1
        for i, b in enumerate(bars):
            if b.get("date") == t:
                tbar = b
                tidx = i
                break
        if tbar is None:
            continue
        if code in zt_t:
            continue
        if tbar.get("isST") in ("1", 1, True):
            continue
        turn = tbar.get("turn")
        if turn is None or turn <= TURN_THRESHOLD:
            continue
        vr5 = vol_ratio_5(bars, tidx)
        if vr5 is None or vr5 <= VR5_THRESHOLD:
            continue
        out.append(code)
    return out


def build_records(end_date="2026-09-17", days=180):
    """复现 t1_exit_optimization 的 records（low-open -5%~-2%，T+1 open entry，T+2 OHLC）。"""
    all_bars = load_kline_db()
    zt = load_zt_by_date()
    cal = sorted(zt.keys())
    if end_date not in cal:
        return None, "no_end_date"
    end_idx = cal.index(end_date)
    date_idx = {d: i for i, d in enumerate(cal)}
    pairs = [(cal[i], cal[i + 1]) for i in range(max(0, end_idx - days), end_idx) if i + 1 < len(cal)]
    records = []
    for t, t1 in pairs:
        zt_t = zt.get(t, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        wl = gen_watchlist(t, all_bars, zt_t)
        for code in wl:
            bars = all_bars.get(code, [])
            tbar = next((b for b in bars if b.get("date") == t), None)
            if not tbar or tbar.get("close") is None:
                continue
            t_close = tbar["close"]
            t1bar = next((b for b in bars if b.get("date") == t1), None)
            if not t1bar or t1bar.get("open") is None or t1bar["open"] == 0:
                continue
            t1_open = t1bar["open"]
            t1_close = t1bar.get("close")
            gap = (t1_open - t_close) / t_close * 100
            if not (-5 <= gap < -2):
                continue
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            if t1_open >= t_close * (1 + zt_limit) * 0.999:  # 一字买不进
                continue
            t2bar = next((b for b in bars if b.get("date") == t2), None)
            if not t2bar:
                continue
            if None in (t2bar.get("open"), t2bar.get("high"), t2bar.get("low"), t2bar.get("close")):
                continue
            records.append({
                "code": code, "t1_open": t1_open, "t1_close": t1_close,
                "t2_open": t2bar["open"], "t2_high": t2bar["high"],
                "t2_low": t2bar["low"], "t2_close": t2bar["close"],
            })
    return records, len(pairs)


def ev_stats(rets):
    n = len(rets)
    if n == 0:
        return {"n": 0, "ev": 0, "std": 0, "t": 0, "ci_lo": 0, "ci_hi": 0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0
    se = std / math.sqrt(n) if n > 0 else 0
    t = mean / se if se > 0 else 0
    ci_lo = mean - 1.96 * se if se > 0 else mean
    ci_hi = mean + 1.96 * se if se > 0 else mean
    return {"n": n, "ev": round(mean, 3), "std": round(std, 3),
            "t": round(t, 2), "ci_lo": round(ci_lo, 3), "ci_hi": round(ci_hi, 3)}


def main():
    print("加载数据…")
    records, npairs = build_records()
    if records is None:
        print("ERR:", npairs)
        return
    print(f"pairs={npairs} records={len(records)}")

    # ---- 1. 复现 grid（open-anchored entry T+1 open, exit T+2 stop/close）----
    print("\n=== 1. 复现 exit_optimization grid（open-anchored, 代码同款逻辑）===")
    stops = [0.0, -0.03, -0.05, -0.08]
    takes = [0.0, 0.03, 0.05, 0.08, 0.10]
    grid = []
    for stop in stops:
        for take in takes:
            rets = []
            for r in records:
                entry = r["t1_open"]
                sp = entry * (1 + stop) if stop < 0 else None
                tp = entry * (1 + take) if take > 0 else None
                st_trig = sp is not None and r["t2_low"] <= sp
                tk_trig = tp is not None and r["t2_high"] >= tp
                if st_trig and sp is not None:
                    exit_p = sp
                elif tk_trig and tp is not None:
                    exit_p = tp
                else:
                    exit_p = r["t2_close"]
                rets.append((exit_p - entry) / entry * 100)
            s = ev_stats(rets)
            grid.append({"stop": stop, "take": take, **s})
    baseline = next(g for g in grid if g["stop"] == 0.0 and g["take"] == 0.0)
    best = max(grid, key=lambda g: g["ev"])
    print(f"baseline (stop0/take0): EV={baseline['ev']}% std={baseline['std']}% t={baseline['t']} CI[{baseline['ci_lo']},{baseline['ci_hi']}] n={baseline['n']}")
    print(f"best: stop={best['stop']} take={best['take']} EV={best['ev']}% std={best['std']}% t={best['t']} CI[{best['ci_lo']},{best['ci_hi']}]")
    print("-3% stop +0 take:")
    m3 = next(g for g in grid if g["stop"] == -0.03 and g["take"] == 0.0)
    print(f"  EV={m3['ev']}% std={m3['std']}% t={m3['t']} CI[{m3['ci_lo']},{m3['ci_hi']}] n={m3['n']}")

    # ---- 2. stop-fill over-credit：realistic fill ----
    print("\n=== 2. stop-fill over-credit（realistic: gap 穿 stop 按 t2_open 成交）===")
    stop = -0.03
    rets_ideal = []   # 代码同款：stop 触发卖 stop_price
    rets_real = []    # 真实：t2_open < stop → 卖 t2_open；否则 stop 触发卖 stop，否则 close
    gap_through = 0
    for r in records:
        entry = r["t1_open"]
        sp = entry * (1 + stop)
        st_trig = sp is not None and r["t2_low"] <= sp
        # ideal
        if st_trig:
            exit_ideal = sp
        else:
            exit_ideal = r["t2_close"]
        rets_ideal.append((exit_ideal - entry) / entry * 100)
        # realistic
        if st_trig:
            if r["t2_open"] <= sp:  # 开盘已穿 stop → 成交 t2_open（更差）
                exit_real = r["t2_open"]
                gap_through += 1
            else:
                exit_real = sp  # 盘中触及，stop 限价单近似成交
        else:
            exit_real = r["t2_close"]
        rets_real.append((exit_real - entry) / entry * 100)
    si = ev_stats(rets_ideal)
    sr = ev_stats(rets_real)
    trig_total = sum(1 for r in records if r["t2_low"] <= r["t1_open"] * 0.97)
    print(f"stop 触发总数: {trig_total}/{len(records)} ({trig_total/len(records)*100:.1f}%)")
    print(f"其中 gap 穿 stop (t2_open<=stop): {gap_through} ({gap_through/max(trig_total,1)*100:.1f}% of triggers)")
    print(f"ideal (代码同款):     EV={si['ev']}% std={si['std']}% t={si['t']}")
    print(f"realistic (gap穿按open): EV={sr['ev']}% std={sr['std']}% t={sr['t']}")
    print(f"over-credit = {round(si['ev']-sr['ev'],3)}% （理想 - 真实）")

    # ---- 3. honest close_ev -3% stop（entry T+1 close, 隔离 T+1 日内泄漏）----
    print("\n=== 3. honest close_ev -3% stop（entry=T+1 close, 隔离 T+1 日内泄漏）===")
    rec_close = [r for r in records if r.get("t1_close") and r["t1_close"] != 0]
    # baseline close_ev: T+1 close 买 T+2 close 卖（hold full T+2 day, post-confirmation）
    rets_close_base = [(r["t2_close"] - r["t1_close"]) / r["t1_close"] * 100 for r in rec_close]
    # close_ev honest (commit 33a93e7 口径): T+1 close 买 T+2 open 卖（overnight only）
    rets_close_ovnt = [(r["t2_open"] - r["t1_close"]) / r["t1_close"] * 100 for r in rec_close]
    # -3% stop on close-anchored: stop = t1_close*0.97, T+2 low 触及
    rets_close_stop = []
    for r in rec_close:
        entry = r["t1_close"]
        sp = entry * 0.97
        if r["t2_low"] <= sp:
            exit_p = sp if r["t2_open"] > sp else r["t2_open"]  # realistic
        else:
            exit_p = r["t2_close"]
        rets_close_stop.append((exit_p - entry) / entry * 100)
    sb = ev_stats(rets_close_base)
    so = ev_stats(rets_close_ovnt)
    ss = ev_stats(rets_close_stop)
    print(f"close-anchored baseline (T+1close→T+2close): EV={sb['ev']}% t={sb['t']} CI[{sb['ci_lo']},{sb['ci_hi']}] n={sb['n']}")
    print(f"close-anchored overnight (T+1close→T+2open, commit33a93e7口径): EV={so['ev']}% t={so['t']} CI[{so['ci_lo']},{so['ci_hi']}]")
    print(f"close-anchored -3% stop (realistic fill):           EV={ss['ev']}% t={ss['t']} CI[{ss['ci_lo']},{ss['ci_hi']}]")

    # ---- 4. Bonferroni：20 cells, best vs baseline ----
    print("\n=== 4. Bonferroni（20 grid cells, best -3%stop/0take vs baseline 0/0）===")
    # 配对 t: 差值 mean / (std_diff/sqrt(n))
    diffs = []
    for r in records:
        entry = r["t1_open"]
        sp = entry * 0.97
        st_trig = r["t2_low"] <= sp
        ret_stop = ((sp if (st_trig and r["t2_open"] > sp) else (r["t2_open"] if st_trig else r["t2_close"])) - entry) / entry * 100
        ret_base = (r["t2_close"] - entry) / entry * 100
        diffs.append(ret_stop - ret_base)
    nd = len(diffs)
    md = sum(diffs) / nd
    sd = statistics.pstdev(diffs)
    sed = sd / math.sqrt(nd)
    td = md / sed if sed > 0 else 0
    p_bonf = 0.05 / 20
    # 简单 z 近似
    from math import erf, sqrt
    def norm_sf(t):
        return 0.5 * (1 - erf(abs(t) / sqrt(2)))
    p_raw = norm_sf(td)
    print(f"stop-vs-baseline 配对差: mean={round(md,3)}% std={round(sd,3)}% t={round(td,2)} p(one-sided)≈{round(p_raw,4)}")
    print(f"Bonferroni 阈值 (20 cells): p < {p_bonf} → {'PASS' if p_raw < p_bonf else 'FAIL (overfit risk)'}")
    print(f"原始 p={round(p_raw,4)} vs Bonferroni p<{p_bonf}")


if __name__ == "__main__":
    main()
