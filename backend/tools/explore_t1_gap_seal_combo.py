# -*- coding: utf-8 -*-
"""S232 T+1 gap × 封板强度(pctChg 代理) 组合 EV 分析。

t1_gap_analysis 扩展：在 gap（T+1 开盘 gap）第一维度基础上，加 T+1 涨幅(pctChg)作
"封板强度代理"第二维度，找 gap×pctChg 组合中比低开-5%~-2%（+0.70%）更强的正 EV。

为什么用 pctChg 代理而非真实封单/封板时间：
- baostock_5min_freeze 仅 16 天 + 只存涨停股（survivorship）→ 无法作全 watchlist 维度
- seal_intraday_2026.db first_seal_time 仅 21 天 + 只涨停股（em_zt_topic_pool 来源）
- watchlist 是 T 日未涨停股，T+1 仅 ~4% 涨停 → 封单数据只覆盖 ~4% 记录，不可作维度
- T+1 pctChg = 封板强度连续代理（涨停≈+10/+20% / 强势 / 温和 / 弱势），180 天全覆盖无 survivorship

跑法：cd backend && .venv/bin/python tools/explore_t1_gap_seal_combo.py
"""

import json
import sqlite3
import sys
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
KLINE = resolve_data_dir() / "baostock_kline_cache.json"
ZT_DB = resolve_data_dir() / "zt_history.db"

TURN_THRESHOLD = 20.0
VR5_THRESHOLD = 2.0


def load_kline() -> dict[str, list[dict]]:
    """从 JSON 读全量 kline（db 0 byte 留存，真实数据在 json）。"""
    with open(KLINE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, list[dict]] = {}
    for code, bars in raw.items():
        if isinstance(bars, list) and bars:
            out[code] = sorted(bars, key=lambda b: b.get("date", ""))
    return out


def load_zt_by_date() -> dict[str, set[str]]:
    c = sqlite3.connect(str(ZT_DB))
    try:
        zt: dict[str, set[str]] = {}
        for d, code in c.execute("SELECT date, code FROM zt_history"):
            zt.setdefault(d, set()).add(code)
        return zt
    finally:
        c.close()


def vol_ratio_5(bars: list[dict], idx: int) -> float | None:
    if idx < 5:
        return None
    vol = bars[idx].get("volume")
    if not vol:
        return None
    prev = bars[idx - 5 : idx]
    pv = [b.get("volume") for b in prev]
    if any(v is None or v == 0 for v in pv):
        return None
    avg5 = sum(pv) / 5.0
    if avg5 == 0:
        return None
    return vol / avg5


def gen_watchlist(t: str, all_bars: dict[str, list[dict]], zt_t: set[str]) -> list[str]:
    """T 日 watchlist codes（turn>20%+vr5>2+未涨停+非ST）。"""
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


def combo_analysis(end_date: str = "2026-09-17", days: int = 180) -> dict:
    all_bars = load_kline()
    zt_by_date = load_zt_by_date()
    cal = sorted(zt_by_date.keys())
    if end_date not in cal:
        return {"status": "no_end_date", "end_date": end_date}
    end_idx = cal.index(end_date)
    start_idx = max(0, end_idx - days)
    pairs = [(cal[i], cal[i + 1]) for i in range(start_idx, end_idx) if i + 1 < len(cal)]
    date_idx = {d: i for i, d in enumerate(cal)}

    records = []
    for t, t1 in pairs:
        zt_t = zt_by_date.get(t, set())
        zt_t1 = zt_by_date.get(t1, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        zt_t2 = zt_by_date.get(t2, set())
        wl = gen_watchlist(t, all_bars, zt_t)
        for code in wl:
            bars = all_bars.get(code, [])
            tbar = next((b for b in bars if b.get("date") == t), None)
            t1bar = next((b for b in bars if b.get("date") == t1), None)
            t2bar = next((b for b in bars if b.get("date") == t2), None)
            if not tbar or not t1bar or not t2bar:
                continue
            t_close = tbar.get("close")
            t1_open = t1bar.get("open")
            t1_close = t1bar.get("close")
            t1_pct = t1bar.get("pctChg")
            t2_open = t2bar.get("open")
            if None in (t_close, t1_open, t1_close, t1_pct, t2_open) or t1_open == 0:
                continue
            gap = (t1_open - t_close) / t_close * 100
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            zt_price_t2 = t1_close * (1 + zt_limit)
            was_zt_t1 = code in zt_t1
            was_zt_t2 = code in zt_t2
            # open_ret: T+1 open → T+2（含 T+1 日内涨幅，对 T+1-close 信号有 look-ahead 泄漏）
            open_ret = ((zt_price_t2 - t1_open) / t1_open * 100) if was_zt_t2 else ((t2_open - t1_open) / t1_open * 100)
            # close_ret: T+1 close → T+2（post-confirmation，隔离 pctChg 信号真 edge）
            close_ret = (
                ((zt_price_t2 - t1_close) / t1_close * 100) if was_zt_t2 else ((t2_open - t1_close) / t1_close * 100)
            )
            records.append(
                {
                    "code": code,
                    "gap": round(gap, 2),
                    "t1_pct": round(float(t1_pct), 2),
                    "was_zt_t1": was_zt_t1,
                    "was_zt_t2": was_zt_t2,
                    "open_ret": round(open_ret, 2),
                    "close_ret": round(close_ret, 2),
                }
            )

    # gap buckets
    gap_defs = [
        ("低开<-5%", lambda g: g < -5),
        ("低开-5%~-2%", lambda g: -5 <= g < -2),
        ("平开-2%~+2%", lambda g: -2 <= g <= 2),
        ("高开+2%~+5%", lambda g: 2 < g <= 5),
        ("高开>+5%", lambda g: g > 5),
    ]
    # T+1 pctChg buckets (封板强度代理)
    pct_defs = [
        ("大跌<-5%", lambda p: p < -5),
        ("弱势-5%~0%", lambda p: -5 <= p < 0),
        ("温和0%~+5%", lambda p: 0 <= p < 5),
        ("强势≥+5%", lambda p: p >= 5),
    ]

    # gap-only buckets (reproduce baseline, open-anchored)
    gap_buckets = []
    for name, fn in gap_defs:
        sub = [r for r in records if fn(r["gap"])]
        n = len(sub)
        hit = sum(1 for r in sub if r["was_zt_t2"])
        ev = sum(r["open_ret"] for r in sub) / n if n else 0.0
        gap_buckets.append(
            {"bucket": name, "n": n, "hit": hit, "rate": round(hit / n, 4) if n else 0, "ev": round(ev, 2)}
        )

    # pctChg-only buckets (both open-anchored and close-anchored/post-confirmation)
    pct_buckets = []
    for name, fn in pct_defs:
        sub = [r for r in records if fn(r["t1_pct"])]
        n = len(sub)
        hit = sum(1 for r in sub if r["was_zt_t2"])
        oev = sum(r["open_ret"] for r in sub) / n if n else 0.0
        cev = sum(r["close_ret"] for r in sub) / n if n else 0.0
        pct_buckets.append(
            {
                "bucket": name,
                "n": n,
                "hit": hit,
                "rate": round(hit / n, 4) if n else 0,
                "open_ev": round(oev, 2),
                "close_ev": round(cev, 2),
            }
        )

    # combo buckets (gap × pctChg) — close_ret is the methodologically correct EV for a T+1-close signal
    combo_buckets = []
    for gname, gfn in gap_defs:
        for pname, pfn in pct_defs:
            sub = [r for r in records if gfn(r["gap"]) and pfn(r["t1_pct"])]
            n = len(sub)
            hit = sum(1 for r in sub if r["was_zt_t2"])
            oev = sum(r["open_ret"] for r in sub) / n if n else 0.0
            cev = sum(r["close_ret"] for r in sub) / n if n else 0.0
            combo_buckets.append(
                {
                    "combo": f"{gname} × {pname}",
                    "gap": gname,
                    "pct": pname,
                    "n": n,
                    "hit": hit,
                    "rate": round(hit / n, 4) if n else 0,
                    "open_ev": round(oev, 2),
                    "close_ev": round(cev, 2),
                    "positive_ev": cev > 0,
                }
            )

    total_n = len(records)
    total_hit = sum(1 for r in records if r["was_zt_t2"])
    total_oev = sum(r["open_ret"] for r in records) / total_n if total_n else 0.0
    total_cev = sum(r["close_ret"] for r in records) / total_n if total_n else 0.0
    baseline = {
        "n": total_n,
        "hit": total_hit,
        "rate": round(total_hit / total_n, 4) if total_n else 0,
        "open_ev": round(total_oev, 2),
        "close_ev": round(total_cev, 2),
    }

    return {
        "status": "ok",
        "days": len(pairs),
        "total_records": total_n,
        "baseline": baseline,
        "gap_buckets": gap_buckets,
        "pct_buckets": pct_buckets,
        "combo_buckets": combo_buckets,
    }


if __name__ == "__main__":
    r = combo_analysis()
    print(f"days={r['days']} records={r['total_records']}")
    b = r["baseline"]
    print(f"baseline open_ev={b['open_ev']}% close_ev={b['close_ev']}% rate={b['rate'] * 100:.2f}%")
    print("\n=== gap buckets (open-anchored, T+1 open 信号 so open_ret 正确) ===")
    for x in r["gap_buckets"]:
        print(f"  {x['bucket']}: n={x['n']} hit={x['hit']} rate={x['rate'] * 100:.2f}% ev={x['ev']}%")
    print("\n=== pctChg buckets (封板强度代理) — open_ev 含 T+1 日内泄漏, close_ev 隔离真 edge ===")
    for x in r["pct_buckets"]:
        print(
            f"  {x['bucket']}: n={x['n']} hit={x['hit']} rate={x['rate'] * 100:.2f}% "
            f"open_ev={x['open_ev']}% close_ev={x['close_ev']}%"
        )
    print("\n=== gap × pctChg combos (n>=30) by close_ev (post-confirmation 真实 edge) ===")
    for x in sorted([c for c in r["combo_buckets"] if c["n"] >= 30], key=lambda c: -c["close_ev"]):
        flag = " ★" if x["close_ev"] > 0.7 else ""
        print(
            f"  {x['combo']}: n={x['n']} hit={x['hit']} rate={x['rate'] * 100:.2f}% "
            f"open_ev={x['open_ev']}% close_ev={x['close_ev']}%{flag}"
        )
    print("\n=== 同 combo open_ev vs close_ev 对比（看 T+1 日内泄漏大小）===")
    for x in sorted([c for c in r["combo_buckets"] if c["n"] >= 30], key=lambda c: -(c["open_ev"] - c["close_ev"])):
        print(
            f"  {x['combo']}: open_ev={x['open_ev']}% close_ev={x['close_ev']}% 泄漏={round(x['open_ev'] - x['close_ev'], 2)}%"
        )
