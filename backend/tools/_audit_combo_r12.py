# -*- coding: utf-8 -*-
"""轮7 R12 size-matched（2026-10-20）。

combo edge 分解出是"小盘效应"。R12 问：挑出的低成交额票，跑赢**同市值档**同龄票吗？
- alpha = pick_fwd5 - 同市值档同龄平均 fwd5
- alpha≈0 → 纯 size premium（买小=买风险，挣的是风险溢价）
- alpha>0 显著 → 有选股 alpha（低流动性/换手异常，超出 size）

流通股本 = volume / turn；流通市值 = 股本 × close。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / ".vibe-research" / "baostock_kline_cache.db"
SPLIT = "2023-01-01"
COST = 0.004


def _board_limit(code: str) -> float:
    """涨停板阈值——主板 10% / 创业板科创板 20% / 北交 30%。"""
    if code.startswith(("30", "68")):
        return 0.198
    if code.startswith(("8", "9")):
        return 0.298
    return 0.098


def build_by_date() -> dict:
    """每日：每只票 {gap, tr, amt, cap, fwd5}。cap=流通市值(亿)。"""
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = defaultdict(list)
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 70:
            continue
        for i in range(60, len(bars) - 5):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            vol = float(bars[i].get("volume", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            turn = float(bars[i].get("turn", 0) or 0)
            if not prev_c or not c or not o or not vol or not turn:
                continue
            nc = float(bars[i + 5].get("close", 0) or 0)
            if not nc:
                continue
            float_shares = vol / (turn / 100.0)  # turn 是百分数
            cap = float_shares * c / 1e8  # 亿
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": (o - prev_c) / prev_c,
                "tr": (c - prev_c) / prev_c, "amt": amt, "cap": cap,
                "fwd5": (nc - c) / c, "is_zt": (c - prev_c) / prev_c >= _board_limit(code),
            })
    return by_date


def rank_scores(lst: list, use_gap=True, use_tr=True, use_amt=True) -> list:
    n = len(lst)
    sg = sorted(range(n), key=lambda k: lst[k]["gap"])
    st = sorted(range(n), key=lambda k: lst[k]["tr"])
    sa = sorted(range(n), key=lambda k: lst[k]["amt"])
    rg = {o: r / n for r, o in enumerate(sg)}
    rt = {o: r / n for r, o in enumerate(st)}
    ra = {o: (1 - r / n) for r, o in enumerate(sa)}

    def s(k):
        x = 0.0
        if use_gap: x += rg[k]
        if use_tr: x += rt[k]
        if use_amt: x += ra[k]
        return x
    return sorted(range(n), key=s, reverse=True)


def cap_deciles(lst: list) -> list:
    """返回每只票的市值档 0(最小)-9(最大)。"""
    n = len(lst)
    order = sorted(range(n), key=lambda k: lst[k]["cap"])
    dec = [0] * n
    for rank_pos, orig in enumerate(order):
        dec[orig] = min(9, rank_pos * 10 // n)
    return dec


def r12_for(dates: list, by_date: dict, use_gap=True, use_tr=True, use_amt=True,
            top_n: int | None = None, exclude_zt: bool = False) -> dict | None:
    """挑 top → 每只 vs 同档同龄 → alpha。exclude_zt=True 时挑出后滤涨停（去涨停版 R12）。"""
    daily_raw, daily_peer, daily_alpha = [], [], []
    for d in dates:
        lst = by_date[d]
        if len(lst) < 100:  # 要够多才能分 10 档
            continue
        dec = cap_deciles(lst)
        scored = rank_scores(lst, use_gap, use_tr, use_amt)
        if top_n is None:
            k = max(1, len(lst) // 10)
        else:
            if len(lst) < top_n * 10:
                continue
            k = top_n
        picks = scored[:k]
        if exclude_zt:
            picks = [p for p in picks if not lst[p]["is_zt"]]
            if len(picks) < 10:
                continue  # 去涨停后太少，跳该日
        # 同档同龄平均 fwd5
        by_dec = defaultdict(list)
        for idx in range(len(lst)):
            by_dec[dec[idx]].append(lst[idx]["fwd5"])
        dec_avg = {dk: (statistics.mean(v) if v else 0.0) for dk, v in by_dec.items()}
        day_raw, day_peer, day_alpha = [], [], []
        for p in picks:
            r = lst[p]["fwd5"]
            peer = dec_avg[dec[p]]
            day_raw.append(r)
            day_peer.append(peer)
            day_alpha.append(r - peer)
        if not day_raw:
            continue
        daily_raw.append(statistics.mean(day_raw))
        daily_peer.append(statistics.mean(day_peer))
        daily_alpha.append(statistics.mean(day_alpha))
    if not daily_alpha:
        return None

    def tstat(series):
        std = statistics.pstdev(series) if len(series) > 1 else 0
        se = std / (len(series) ** 0.5) if series else 0
        return statistics.mean(series) / se if se > 0 else 0

    return {
        "n_days": len(daily_alpha),
        "raw": statistics.mean(daily_raw), "raw_t": tstat(daily_raw),
        "peer": statistics.mean(daily_peer), "peer_t": tstat(daily_peer),
        "alpha": statistics.mean(daily_alpha), "alpha_t": tstat(daily_alpha),
        "alpha_share": statistics.mean(daily_alpha) / statistics.mean(daily_raw)
            if statistics.mean(daily_raw) else 0,
    }


def main() -> None:
    by_date = build_by_date()
    test = sorted(d for d in by_date if d >= SPLIT)
    print(f"=== 轮7 R12 size-matched（test {len(test)} 日）===\n")
    print("问：挑出的票跑赢同市值档同龄票吗？alpha=挑出-同龄均值。alpha≈0→纯size premium\n")
    for label, g, tr, a, tn in [
        ("全 combo top20", True, True, True, 20),
        ("小盘单 top20", False, False, True, 20),
        ("动量+小盘 top20", False, True, True, 20),
        ("全 combo decile", True, True, True, None),
        ("小盘单 decile", False, False, True, None),
    ]:
        r = r12_for(test, by_date, use_gap=g, use_tr=tr, use_amt=a, top_n=tn)
        if not r:
            print(f"{label:<18} (n不足)")
            continue
        print(f"--- {label} ---")
        print(f"  挑出 raw:  mean {r['raw']*100:+.4f}%  t={r['raw_t']:.2f}")
        print(f"  同龄 peer: mean {r['peer']*100:+.4f}%  t={r['peer_t']:.2f}")
        print(f"  alpha:     mean {r['alpha']*100:+.4f}%  t={r['alpha_t']:.2f}  "
              f"({'✅alpha在' if r['alpha'] > 0 and r['alpha_t'] > 2.4 else '❌alpha没了=纯size' if abs(r['alpha']) < 0.0005 else '⚠️alpha弱'})")
        print(f"  alpha占raw: {r['alpha_share']*100:.1f}%")
        print()

    # 去涨停版 R12（tradeable 真 edge：去涨停后 alpha 还在否？非 size premium？）
    print("=== 去涨停版 R12（tradeable 真 edge，R4 后定 alpha 非 size）===\n")
    r = r12_for(test, by_date, use_gap=True, use_tr=True, use_amt=True, top_n=20, exclude_zt=True)
    if r:
        print(f"--- 全 combo top20 去涨停 ---")
        print(f"  挑出 raw:  mean {r['raw']*100:+.4f}%  t={r['raw_t']:.2f}")
        print(f"  同龄 peer: mean {r['peer']*100:+.4f}%  t={r['peer_t']:.2f}")
        print(f"  alpha:     mean {r['alpha']*100:+.4f}%  t={r['alpha_t']:.2f}  "
              f"({'✅alpha在(真edge非size)' if r['alpha'] > 0 and r['alpha_t'] > 2.4 else '❌alpha没了=去涨停后纯size' if abs(r['alpha']) < 0.0005 else '⚠️alpha弱'})")
        print(f"  alpha占raw: {r['alpha_share']*100:.1f}%")
        print()
    else:
        print("(n不足)\n")

    # regime 分层：alpha 在 2026 死没死？
    print("=== regime 分层：全 combo top20 的 alpha 跨 regime ===\n")
    for label, ds in [
        ("全 test", test),
        ("2023-2024", sorted(d for d in test if d < "2025-01-01")),
        ("2025-2026", sorted(d for d in test if d >= "2025-01-01")),
        ("2025", sorted(d for d in test if d.startswith("2025"))),
        ("2026", sorted(d for d in test if d.startswith("2026"))),
    ]:
        r = r12_for(ds, by_date, use_gap=True, use_tr=True, use_amt=True, top_n=20)
        if not r:
            print(f"{label:<12} (n不足)")
            continue
        alpha_ok = r['alpha'] > 0 and r['alpha_t'] > 2.4
        print(f"{label:<12} raw {r['raw']*100:+.4f}%(t={r['raw_t']:.2f}) "
              f"peer {r['peer']*100:+.4f}%(t={r['peer_t']:.2f}) "
              f"alpha {r['alpha']*100:+.4f}%(t={r['alpha_t']:.2f}) "
              f"{'✅' if alpha_ok else '⚠️alpha弱/没' if r['alpha_t'] < 2.4 else ''} "
              f"[{r['n_days']}日]")
    print("\n读法：alpha t>2.4 = 选股 alpha 还在；alpha t<2.4 或转负 = 2026 衰减吃掉了 alpha")


if __name__ == "__main__":
    main()
