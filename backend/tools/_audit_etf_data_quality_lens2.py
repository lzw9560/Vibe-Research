# -*- coding: utf-8 -*-
"""data-quality-and-cost lens 深挖 2：NAV split 精确贡献 + 危机日集中 + 真实成本.
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ETF_CACHE = resolve_data_dir() / "etf_premium_cache.json"
ETF_NAMES = {
    "510300": "沪深300ETF", "510050": "上证50ETF", "159915": "创业板ETF",
    "510500": "中证500ETF", "510880": "红利ETF", "512890": "红利低波ETF",
    "512100": "中证1000ETF", "588000": "科创50ETF", "159901": "深100ETF",
    "510310": "价值ETF", "159955": "中小盘ETF", "512760": "半导体ETF",
    "159995": "芯片ETF", "515790": "光伏ETF", "512660": "军工ETF",
}


def load():
    with open(ETF_CACHE) as f:
        return json.load(f)


def main() -> None:
    data = load()
    all_dates_set = set()
    for days in data.values():
        all_dates_set.update(days.keys())
    cal = sorted(all_dates_set)
    di_map = {d: i for i, d in enumerate(cal)}

    # ============================================================
    # A. 精确识别 NAV split artifact picks（NAV 日跳 |Δ|>10% 且 price 不跳）
    # ============================================================
    print("=" * 76)
    print("A. NAV split artifact 精确识别（|NAV日Δ|>10% 且 price 不跳或滞后跳）")
    print("=" * 76)
    nav_split_days = set()  # (code, date) where NAV jumped >10% — suspect artifact
    for code, days in data.items():
        ds = sorted(days.keys())
        for i in range(1, len(ds)):
            prev, curr = days[ds[i-1]], days[ds[i]]
            if prev.get("nav",0) > 0 and curr.get("nav",0) > 0:
                nr = (curr["nav"] - prev["nav"]) / prev["nav"]
                if abs(nr) > 0.10:
                    # price 同向同幅度 → 真 split（两源都调了，disc 不假）
                    pr = ((curr["close"]-prev["close"])/prev["close"]
                          if prev.get("close",0)>0 else 0)
                    # 若 price 没跟着跳 → NAV 单源 split = 数据源不同步 = 假 disc
                    price_lagged = abs(pr) < abs(nr) * 0.5
                    nav_split_days.add((code, ds[i]))
                    if price_lagged:
                        print(f"  [NAV跳 price不跟] {code} {ETF_NAMES.get(code)} "
                              f"{ds[i-1]}->{ds[i]} NAV {prev['nav']:.4f}->{curr['nav']:.4f} "
                              f"({nr*100:+.1f}%) price_ret={pr*100:+.1f}%  → 当日 disc 假")
    print(f"\n  NAV |Δ|>10% 的 (code,date) 共 {len(nav_split_days)} 个")

    # 重建 picks 标记是否落在 NAV-split 日
    picks = []
    for code, days in data.items():
        for d, b in days.items():
            if b.get("nav",0) <= 0 or b.get("close",0) <= 0:
                continue
            disc = (b["close"] - b["nav"]) / b["nav"] * 100
            if disc >= -0.3:
                continue
            di = di_map.get(d)
            if di is None or di + 2 >= len(cal):
                continue
            t1 = days.get(cal[di+1]); t2 = days.get(cal[di+2])
            if not t1 or not t2:
                continue
            entry, exit_c = t1.get("open"), t2.get("close")
            n_t1, n_t2 = t1.get("nav"), t2.get("nav")
            if None in (entry, exit_c, n_t1, n_t2) or min(entry,exit_c,n_t1,n_t2) <= 0:
                continue
            d_e = (entry - b["nav"]) / b["nav"] * 100
            d_x = (exit_c - n_t2) / n_t2 * 100
            bhar = d_x - d_e
            raw = (exit_c - entry) / entry * 100
            is_split = (code, d) in nav_split_days
            picks.append({"code": code, "d": d, "disc": disc, "bhar": bhar,
                          "raw": raw, "is_split": is_split})

    total_bhar = sum(p["bhar"] for p in picks)
    split_picks = [p for p in picks if p["is_split"]]
    clean_picks = [p for p in picks if not p["is_split"]]
    print(f"\n  picks 总 {len(picks)}: split-artifact {len(split_picks)} / clean {len(clean_picks)}")
    print(f"  total BHAR={total_bhar:+.2f}%  mean={total_bhar/len(picks):+.4f}%")
    if split_picks:
        sp_bhar = sum(p["bhar"] for p in split_picks)
        print(f"  split picks BHAR 合计={sp_bhar:+.2f}% mean={sp_bhar/len(split_picks):+.4f}%")
    cl_bhar = sum(p["bhar"] for p in clean_picks)
    print(f"  clean picks BHAR 合计={cl_bhar:+.2f}% mean={cl_bhar/len(clean_picks):+.4f}%")
    print(f"  → 剔除 NAV-split artifact 后 mean BHAR: "
          f"{cl_bhar/len(clean_picks):+.4f}% (原 {total_bhar/len(picks):+.4f}%)")

    # ============================================================
    # B. 2015-07-08 单日贡献（8 ETF 同日深折价）
    # ============================================================
    print("\n" + "=" * 76)
    print("B. 危机日集中：2015-07-07/08/09 + 2008-10-27/29 贡献")
    print("=" * 76)
    crisis_days = {"2015-07-06","2015-07-07","2015-07-08","2015-07-09",
                   "2015-07-10","2015-08-24","2015-08-25","2015-09-01","2015-09-02",
                   "2008-10-27","2008-10-28","2008-10-29","2008-11-03","2008-11-04",
                   "2008-11-06","2008-11-07","2008-11-10"}
    crisis_picks = [p for p in picks if p["d"] in crisis_days]
    crisis_bhar = sum(p["bhar"] for p in crisis_picks)
    print(f"  危机日 picks: {len(crisis_picks)} 个, BHAR 合计={crisis_bhar:+.2f}% "
          f"mean={crisis_bhar/len(crisis_picks) if crisis_picks else 0:+.4f}%")
    print(f"  / total={total_bhar:+.2f}% = {crisis_bhar/total_bhar*100 if total_bhar else 0:.1f}%")
    print(f"  / n_picks={len(picks)} = {len(crisis_picks)/len(picks)*100:.1f}% picks 贡献 "
          f"{crisis_bhar/total_bhar*100 if total_bhar else 0:.1f}% BHAR")

    # 单看 2015-07-08
    d0708 = [p for p in picks if p["d"] == "2015-07-08"]
    b0708 = sum(p["bhar"] for p in d0708)
    print(f"\n  仅 2015-07-08 一天: {len(d0708)} picks, BHAR 合计={b0708:+.2f}% "
          f"/ total={total_bhar:+.2f}% = {b0708/total_bhar*100 if total_bhar else 0:.1f}%")
    print("  这 1 天的 day-mean 在 day-paired t 里算 1 个观测值")

    # ============================================================
    # C. 剔除 NAV-split + 危机日 后 edge
    # ============================================================
    print("\n" + "=" * 76)
    print("C. 双重剔除：NAV-split artifact + 危机日")
    print("=" * 76)
    ultra_clean = [p for p in picks if not p["is_split"] and p["d"] not in crisis_days]
    uc_bhar = sum(p["bhar"] for p in ultra_clean)
    print(f"  ultra_clean picks: {len(ultra_clean)} (剔 {len(picks)-len(ultra_clean)})")
    print(f"  BHAR 合计={uc_bhar:+.2f}% mean={uc_bhar/len(ultra_clean):+.4f}% "
          f"(原 mean={total_bhar/len(picks):+.4f}%)")
    print(f"  net@0.15%={uc_bhar/len(ultra_clean)-0.15:+.4f}%  "
          f"net@0.30%={uc_bhar/len(ultra_clean)-0.30:+.4f}%")

    # ============================================================
    # D. 真实成本估计：按 ETF 流动性分层
    # ============================================================
    print("\n" + "=" * 76)
    print("D. 真实成本估计——折价深度代理 illiquidity")
    print("=" * 76)
    # 折价越深 → 越可能 illiquid → spread 越宽
    # 分层算 mean BHAR + 假设真实 cost
    tiers = [
        ("浅折价 -0.3%~-0.5%", -0.5, -0.3),
        ("中折价 -0.5%~-1.0%", -1.0, -0.5),
        ("深折价 -1.0%~-2.0%", -2.0, -1.0),
        ("极深折价 <-2.0%", -999, -2.0),
    ]
    print(f"{'分层':<26} {'n':>6} {'BHAR%':>9} {'|disc|p50':>10} {'net@0.15':>9} {'net@0.30':>9} {'net@0.50':>9}")
    for label, lo, hi in tiers:
        tp = [p for p in picks if lo <= p["disc"] < hi]
        if not tp:
            continue
        mb = sum(p["bhar"] for p in tp)/len(tp)
        discs = sorted(abs(p["disc"]) for p in tp)
        p50 = discs[len(discs)//2]
        print(f"{label:<26} {len(tp):>6} {mb:>+9.4f} {p50:>10.3f} "
              f"{mb-0.15:>+9.4f} {mb-0.30:>+9.4f} {mb-0.50:>+9.4f}")
    print("\n  推论：极深折价（<-2%）BHAR 高但 spread 必然极宽（disc 本身证明 illiquid）")
    print("  浅折价（-0.3%~-0.5%）n 最多但 BHAR 低，0.15% cost 后 net 接近 0")

    # ============================================================
    # E. NAV-split artifact 是否系统性 inflate BHAR（机制分析）
    # ============================================================
    print("\n" + "=" * 76)
    print("E. NAV-split artifact 机制：是否系统性制造正 BHAR？")
    print("=" * 76)
    print("  机制：NAV 源记录 split/distribution，price 源滞后调整")
    print("  case 510310 2024-09-20: NAV 1.5977→3.2021 (+100%), price 1.597→1.599 (不动)")
    print("  → disc = (1.599-3.2021)/3.2021 = -50% (假折价)")
    print("  → entry = T+1 open (09-23) = price 已调到 ~3.2")
    print("  → d_entry = (entry - nav_signal)/nav_signal")
    print("     nav_signal = 3.2021 (split 后 NAV), entry ≈ 3.2 → d_entry ≈ 0")
    print("  → d_exit = (exit_close - nav_exit)/nav_exit ≈ 0")
    print("  → BHAR = d_exit - d_entry ≈ 0 (split artifact 的 BHAR ≈ 0)")
    print()
    # 验证：split picks 的 BHAR 是否接近 0
    if split_picks:
        sp_bhar_vals = [p["bhar"] for p in split_picks]
        print(f"  split picks BHAR: n={len(split_picks)} mean={mean(sp_bhar_vals):+.4f}% "
              f"median={median(sp_bhar_vals):+.4f}%")
        print("  → 若 mean≈0：split artifact 不直接 inflate BHAR（d_entry/d_exit 都在 split 后）")
        print("  → 但 raw EV 巨大（price 跳空追赶 NAV）→ raw EV 被污染")
        sp_raw = [p["raw"] for p in split_picks]
        print(f"  split picks raw EV: mean={mean(sp_raw):+.4f}% (vs 全体 raw mean="
              f"{sum(p['raw'] for p in picks)/len(picks):+.4f}%)")
        print("  → raw EV 被严重污染（price 跳空是 split 调整非 alpha）")

    # ============================================================
    # F. 价格 split 嫌疑（price 跳 NAV 不跳）——更危险，直接造假 BHAR
    # ============================================================
    print("\n" + "=" * 76)
    print("F. 价格 split 嫌疑（price 跳 NAV 不跟）——直接造假 BHAR")
    print("=" * 76)
    price_split_picks = []
    for code, days in data.items():
        ds = sorted(days.keys())
        for i in range(1, len(ds)):
            prev, curr = days[ds[i-1]], days[ds[i]]
            if prev.get("close",0) > 0 and curr.get("close",0) > 0 and prev.get("nav",0) > 0:
                pr = (curr["close"] - prev["close"]) / prev["close"]
                nr = (curr["nav"] - prev["nav"]) / prev["nav"]
                # price 大跳 + NAV 不跟 = price 单源 split（disc 假）
                if abs(pr) > 0.20 and abs(nr) < abs(pr) * 0.3:
                    price_split_picks.append((code, ds[i], pr, nr))
    print(f"  price |Δ|>20% 且 NAV 不跟（price 单源 split 嫌疑）: {len(price_split_picks)} 个")
    for code, d, pr, nr in price_split_picks[:15]:
        print(f"  {code} {ETF_NAMES.get(code)} {d}: price_ret={pr*100:+.2f}% nav_ret={nr*100:+.2f}%")
    # 这些日子的 picks
    psp_days = {(c,d) for c,d,_,_ in price_split_picks}
    psp_picks = [p for p in picks if (p["code"], p["d"]) in psp_days]
    if psp_picks:
        psp_bhar = sum(p["bhar"] for p in psp_picks)
        print(f"\n  落在这些日子的 picks: {len(psp_picks)} 个, BHAR 合计={psp_bhar:+.2f}% "
              f"mean={psp_bhar/len(psp_picks):+.4f}%")

    # ============================================================
    # G. 2024-09-30 / 10-08 暴涨簇（ETF 涨停日，多 ETF 同日 +10~20%）
    # ============================================================
    print("\n" + "=" * 76)
    print("G. 2024-09-30 / 10-08 ETF 涨停簇——折价是真还是NAV滞后？")
    print("=" * 76)
    surge_days = {"2024-09-27","2024-09-30","2024-10-08","2024-10-09"}
    surge_picks = [p for p in picks if p["d"] in surge_days]
    surge_bhar = sum(p["bhar"] for p in surge_picks)
    print(f"  暴涨簇 picks: {len(surge_picks)}, BHAR 合计={surge_bhar:+.2f}% "
          f"mean={surge_bhar/len(surge_picks) if surge_picks else 0:+.4f}%")
    print("  机制质疑：ETF 连续涨停时，NAV (T 日收盘后公告) vs price (T 日收盘实时)")
    print("  → price 涨停封板 close = 涨停价，NAV 当晚公告可能未反映涨停全部预期")
    print("  → 次日 NAV 追涨 → 假折价（price 已涨 NAV 没涨完）")
    print("  → 这是 look-ahead：NAV_T 用公告值但 price_T 已含涨停信息")


if __name__ == "__main__":
    main()
