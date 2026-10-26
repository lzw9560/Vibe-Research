# -*- coding: utf-8 -*-
"""§44 R4 涨停贡献审计（S238，2026-10-26）。

combo edge 第一天 live -3% + 涨停票 -12.72%/-7.35% 崩 → 怀疑 combo edge 部分是
涨停封板溢价（买涨停次日跌，live 不可兑现）。R4 测：滤掉涨停 picks 后 edge 还在否？

涨停定义（signal 日 today_ret >= 板涨幅阈）：
- 60xxxx/00xxxx 主板 10% → >= 9.8%
- 30xxxx 创业板 / 68xxxx 科创板 20% → >= 19.8%
- 8xxxxx/9xxxxx 北交 30% → >= 29.8%

读法：
- 涨停 picks 贡献 >70% edge → 假 edge（涨停封板溢价，live 不可交易）
- 涨停 picks 贡献 <30% → 真 edge（小盘动量，涨停附带的）
- 中间 → 部分涨停驱动，须滤涨停后重测
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


def board_threshold(code: str) -> float:
    if code.startswith(("30", "68")):
        return 0.198  # 创业板/科创板 20%
    if code.startswith(("8", "920", "9")):
        return 0.298  # 北交 30%
    return 0.098  # 主板 10%


def build_by_date() -> dict:
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
        thr = board_threshold(code)
        for i in range(60, len(bars) - 5):
            prev_c = float(bars[i - 1].get("close", 0) or 0)
            o = float(bars[i].get("open", 0) or 0)
            c = float(bars[i].get("close", 0) or 0)
            amt = float(bars[i].get("amount", 0) or 0)
            if not prev_c or not c or not o or not amt:
                continue
            nc = float(bars[i + 5].get("close", 0) or 0)
            if not nc:
                continue
            today_ret = (c - prev_c) / prev_c
            by_date[bars[i].get("date", "")].append({
                "code": code, "gap": (o - prev_c) / prev_c, "tr": today_ret,
                "amt": amt, "fwd5": (nc - c) / c, "is_zt": today_ret >= thr,
            })
    return by_date


def combo_top_fwd(dates, by_date, exclude_zt: bool = False):
    daily_mean = []
    n_zt_picks = 0
    n_total_picks = 0
    for d in dates:
        lst = by_date[d]
        if len(lst) < 200:
            continue
        n = len(lst)
        sg = sorted(range(n), key=lambda k: lst[k]["gap"])
        st = sorted(range(n), key=lambda k: lst[k]["tr"])
        sa = sorted(range(n), key=lambda k: lst[k]["amt"])
        rg = {o: r / n for r, o in enumerate(sg)}
        rt = {o: r / n for r, o in enumerate(st)}
        ra = {o: (1 - r / n) for r, o in enumerate(sa)}
        scored = sorted(range(n), key=lambda k: rg[k] + rt[k] + ra[k], reverse=True)
        dec = 20  # top-20（tradeable 版本，live 用的）
        picks = [lst[k] for k in scored[:dec]]
        if exclude_zt:
            picks = [p for p in picks if not p["is_zt"]]
            if len(picks) < 10:
                continue
        fwds = [p["fwd5"] for p in picks]
        if not fwds:
            continue
        daily_mean.append(statistics.mean(fwds))
        n_zt_picks += sum(1 for p in picks if p["is_zt"])
        n_total_picks += len(picks)
    if not daily_mean:
        return None
    m = statistics.mean(daily_mean)
    std = statistics.pstdev(daily_mean) if len(daily_mean) > 1 else 0
    se = std / (len(daily_mean) ** 0.5) if daily_mean else 0
    return {"mean": m, "net": m - COST, "t": m / se if se > 0 else 0,
            "n_days": len(daily_mean), "n_picks": n_total_picks, "n_zt": n_zt_picks}


def main() -> None:
    by_date = build_by_date()
    test = sorted(d for d in by_date if d >= SPLIT)
    print(f"=== R4 涨停贡献审计（test {len(test)} 日，combo top-decile 5日）===\n")

    full = combo_top_fwd(test, by_date, exclude_zt=False)
    no_zt = combo_top_fwd(test, by_date, exclude_zt=True)

    if full:
        print(f"全 combo（含涨停）: mean {full['mean']*100:+.4f}% net {full['net']*100:+.4f}% t={full['t']:.2f} "
              f"[{full['n_days']}日, {full['n_picks']} picks, 涨停 {full['n_zt']}={full['n_zt']/full['n_picks']*100:.1f}%]")
    if no_zt:
        print(f"去涨停 combo:       mean {no_zt['mean']*100:+.4f}% net {no_zt['net']*100:+.4f}% t={no_zt['t']:.2f} "
              f"[{no_zt['n_days']}日, {no_zt['n_picks']} picks]")

    if full and no_zt:
        # 涨停 picks 贡献 = (full_mean - no_zt_mean) / full_mean （涨停 picks 拉高 full 的部分）
        # 但更准：涨停 picks 的 mean = (full_mean*n_full - no_zt_mean*n_nozt) / n_zt_picks
        # 简化：看 full vs no_zt 的差。no_zt >= full 的 70% → 涨停贡献 <30% → 真 edge
        ratio = no_zt["mean"] / full["mean"] if full["mean"] else 0
        print()
        print(f"去涨停/全 = {ratio*100:.1f}%")
        if ratio >= 0.7:
            print(f"→ ✅ 真 edge（涨停贡献 <30%，去涨停后 edge 仍在 {no_zt['mean']*100:+.3f}%）")
        elif ratio >= 0.3:
            print(f"→ ⚠️ 部分涨停驱动（涨停贡献 {100-ratio*100:.0f}%，须滤涨停后用）")
        else:
            print(f"→ ❌ 假 edge（涨停封板溢价，去涨停后 edge 崩到 {no_zt['mean']*100:+.3f}%）")


if __name__ == "__main__":
    main()
