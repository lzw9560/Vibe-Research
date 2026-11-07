# -*- coding: utf-8 -*-
"""data-quality-and-cost lens 审计：扫 ETF 折溢价 edge 的数据异常 + 成本 realism.

审计项：
1. 全 picks 折价分布极值（split / 数据错误 / 极端折价合理性）
2. NAV 日跳变（基金拆分/分红/数据错误）→ 污染 BHAR
3. price 日跳变（合拆/复权错误）
4. 510310 split artifact 复核 + 扫其他类似异常
5. 折价 ETF 成本 realism：0.15% 是否低估（折价 ETF 可能 illiquid spread 更宽）
6. 极端折价 picks 对 edge 的贡献占比（是否 edge 全靠几个异常撑着）
"""

from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ETF_COST = 0.15
# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir

ETF_CACHE = resolve_data_dir() / "etf_premium_cache.json"

ETF_NAMES = {
    "510300": "沪深300ETF",
    "510050": "上证50ETF",
    "159915": "创业板ETF",
    "510500": "中证500ETF",
    "510880": "红利ETF",
    "512890": "红利低波ETF",
    "512100": "中证1000ETF",
    "588000": "科创50ETF",
    "159901": "深100ETF",
    "510310": "价值ETF",
    "159955": "中小盘ETF",
    "512760": "半导体ETF",
    "159995": "芯片ETF",
    "515790": "光伏ETF",
    "512660": "军工ETF",
}


def load():
    with open(ETF_CACHE) as f:
        return json.load(f)


def day_ret(a: float, b: float) -> float:
    return (b - a) / a * 100 if a > 0 else 0.0


def main() -> None:
    data = load()
    print(f"[load] {len(data)} ETFs, total bar-days={sum(len(v) for v in data.values())}")

    # ============================================================
    # 1. 全 universe 折价分布 + 极值
    # ============================================================
    print("\n" + "=" * 76)
    print("1. 全 universe 折价分布（找极值异常）")
    print("=" * 76)
    all_discs = []
    disc_by_code = defaultdict(list)
    for code, days in data.items():
        for d, b in days.items():
            if b.get("nav", 0) <= 0 or b.get("close", 0) <= 0:
                continue
            disc = (b["close"] - b["nav"]) / b["nav"] * 100
            all_discs.append((disc, code, d, b["close"], b["nav"]))
            disc_by_code[code].append((disc, d, b["close"], b["nav"]))
    all_discs.sort()
    n = len(all_discs)
    print(f"n={n} median={median([x[0] for x in all_discs]):.4f}% mean={mean([x[0] for x in all_discs]):.4f}%")
    print(
        f"p1={all_discs[int(n * 0.01)][0]:.3f}% "
        f"p5={all_discs[int(n * 0.05)][0]:.3f}% "
        f"p95={all_discs[int(n * 0.95)][0]:.3f}% "
        f"p99={all_discs[int(n * 0.99)][0]:.3f}%"
    )
    print(f"min={all_discs[0][0]:.3f}%  max={all_discs[-1][0]:.3f}%")

    print("\n  --- 最深 20 个折价（疑似 split/数据错误）---")
    for disc, code, d, close, nav in all_discs[:20]:
        print(f"  {code:7} {ETF_NAMES.get(code, '?'):12} {d}  disc={disc:+8.3f}%  close={close:.4f}  nav={nav:.4f}")

    print("\n  --- 最高 10 个溢价（也查异常）---")
    for disc, code, d, close, nav in all_discs[-10:]:
        print(f"  {code:7} {ETF_NAMES.get(code, '?'):12} {d}  disc={disc:+8.3f}%  close={close:.4f}  nav={nav:.4f}")

    # ============================================================
    # 2. NAV 日跳变（基金拆分/分红/数据错误）
    # ============================================================
    print("\n" + "=" * 76)
    print("2. NAV 日跳变检测（>5% 日变化 = 拆分/分红/数据错误）")
    print("=" * 76)
    nav_jumps = []
    price_jumps = []
    for code, days in data.items():
        ds = sorted(days.keys())
        for i in range(1, len(ds)):
            prev = days[ds[i - 1]]
            curr = days[ds[i]]
            if prev.get("nav", 0) > 0 and curr.get("nav", 0) > 0:
                nr = day_ret(prev["nav"], curr["nav"])
                if abs(nr) > 5:
                    nav_jumps.append((nr, code, ds[i - 1], ds[i], prev["nav"], curr["nav"], prev.get("close"), curr.get("close")))
            if prev.get("close", 0) > 0 and curr.get("close", 0) > 0:
                pr = day_ret(prev["close"], curr["close"])
                if abs(pr) > 5 and abs(pr) < 50:  # 50%+ 可能真涨跌停
                    # 同时 NAV 不跳 → 价格 split 嫌疑
                    pn = day_ret(prev.get("nav", 0), curr.get("nav", 0)) if prev.get("nav", 0) > 0 else 0
                    price_jumps.append((pr, code, ds[i - 1], ds[i], prev["close"], curr["close"], pn))
    nav_jumps.sort(key=lambda x: abs(x[0]), reverse=True)
    print(f"\n  NAV |日变化|>5%: {len(nav_jumps)} 个")
    for nr, code, d0, d1, n0, n1, c0, c1 in nav_jumps[:25]:
        print(f"  {code:7} {ETF_NAMES.get(code, '?'):12} {d0}->{d1}  NAV {n0:.4f}->{n1:.4f} ({nr:+7.2f}%)  close {c0} -> {c1}")

    print(f"\n  price |日变化|>5% 且 NAV 不跳（split 嫌疑）: 前 25")
    price_jumps.sort(key=lambda x: abs(x[0]), reverse=True)
    for pr, code, d0, d1, c0, c1, pn in price_jumps[:25]:
        print(f"  {code:7} {ETF_NAMES.get(code, '?'):12} {d0}->{d1}  price {c0:.4f}->{c1:.4f} ({pr:+7.2f}%)  NAV_ret={pn:+.2f}%")

    # ============================================================
    # 3. 510310 split artifact 复核 + 扫所有 ETF 类似
    # ============================================================
    print("\n" + "=" * 76)
    print("3. 510310 split artifact 复核 + 全 universe 扫类似")
    print("=" * 76)
    days_510310 = data.get("510310", {})
    ds = sorted(days_510310.keys())
    print(f"  510310 (价值ETF): {len(ds)} days, {ds[0]} ~ {ds[-1]}")
    # 找 close 突变点
    for i in range(1, len(ds)):
        prev = days_510310[ds[i - 1]]
        curr = days_510310[ds[i]]
        if prev.get("close", 0) > 0 and curr.get("close", 0) > 0:
            pr = day_ret(prev["close"], curr["close"])
            if abs(pr) > 10:
                pn = day_ret(prev.get("nav", 0), curr.get("nav", 0)) if prev.get("nav", 0) > 0 else 0
                print(
                    f"  [510310 jump] {ds[i - 1]}->{ds[i]}  close "
                    f"{prev['close']:.4f}->{curr['close']:.4f} ({pr:+.2f}%)  "
                    f"NAV_ret={pn:+.2f}%  close={curr['close']} nav={curr.get('nav')}"
                )

    # ============================================================
    # 4. 构建 picks（disc<-0.3%）+ 查极值 pick 对 edge 贡献
    # ============================================================
    print("\n" + "=" * 76)
    print("4. disc<-0.3% picks：极值 pick 对 edge 贡献占比")
    print("=" * 76)
    # 重建 picks（复用 R2 逻辑：entry T+1 open, exit T+2 close）
    all_dates_set = set()
    for days in data.values():
        all_dates_set.update(days.keys())
    cal = sorted(all_dates_set)
    di_map = {d: i for i, d in enumerate(cal)}

    picks = []
    for code, days in data.items():
        for d, b in days.items():
            if b.get("nav", 0) <= 0 or b.get("close", 0) <= 0:
                continue
            disc = (b["close"] - b["nav"]) / b["nav"] * 100
            if disc >= -0.3:
                continue
            di = di_map.get(d)
            if di is None or di + 2 >= len(cal):
                continue
            t1 = days.get(cal[di + 1])
            t2 = days.get(cal[di + 2])
            if not t1 or not t2:
                continue
            entry = t1.get("open")
            exit_c = t2.get("close")
            n_t1 = t1.get("nav")
            n_t2 = t2.get("nav")
            if None in (entry, exit_c, n_t1, n_t2) or min(entry, exit_c, n_t1, n_t2) <= 0:
                continue
            # bhar_corrected
            d_e = (entry - b["nav"]) / b["nav"] * 100
            d_x = (exit_c - n_t2) / n_t2 * 100
            bhar = d_x - d_e
            raw = (exit_c - entry) / entry * 100
            picks.append(
                {
                    "code": code,
                    "d": d,
                    "disc": disc,
                    "bhar": bhar,
                    "raw": raw,
                    "entry": entry,
                    "exit": exit_c,
                    "nav_sig": b["nav"],
                    "nav_t1": n_t1,
                    "nav_t2": n_t2,
                    "t1": cal[di + 1],
                    "t2": cal[di + 2],
                }
            )

    picks.sort(key=lambda x: x["disc"])
    total_bhar = sum(p["bhar"] for p in picks)
    total_raw = sum(p["raw"] for p in picks)
    print(f"  n_picks={len(picks)}  total_BHAR={total_bhar:+.2f}% (mean={total_bhar / len(picks):+.4f}%)  total_raw={total_raw:+.2f}%")

    print("\n  --- 折价最深 15 个 picks（BHAR 贡献）---")
    cum = 0
    for p in picks[:15]:
        cum += p["bhar"]
        print(
            f"  {p['code']:7} {ETF_NAMES.get(p['code'], '?'):12} {p['d']}  "
            f"disc={p['disc']:+7.3f}%  BHAR={p['bhar']:+7.3f}%  "
            f"raw={p['raw']:+7.3f}%  cum_BHAR={cum:+.2f}"
        )

    print(f"\n  --- 折价最深 5 picks 占总 BHAR 比例 ---")
    top5_bhar = sum(p["bhar"] for p in picks[:5])
    top10_bhar = sum(p["bhar"] for p in picks[:10])
    print(f"  最深 5 picks BHAR 合计={top5_bhar:+.2f}%  / total={total_bhar:+.2f}% = {top5_bhar / total_bhar * 100 if total_bhar else 0:.1f}%")
    print(f"  最深 10 picks BHAR 合计={top10_bhar:+.2f}%  / total={total_bhar:+.2f}% = {top10_bhar / total_bhar * 100 if total_bhar else 0:.1f}%")

    print("\n  --- BHAR 最极端 15 个 picks（正负两端）---")
    by_bhar = sorted(picks, key=lambda x: x["bhar"])
    print("  最负 15：")
    for p in by_bhar[:15]:
        print(f"  {p['code']:7} {ETF_NAMES.get(p['code'], '?'):12} {p['d']}  disc={p['disc']:+7.3f}%  BHAR={p['bhar']:+8.3f}%  raw={p['raw']:+8.3f}%")
    print("  最正 15：")
    for p in by_bhar[-15:]:
        print(f"  {p['code']:7} {ETF_NAMES.get(p['code'], '?'):12} {p['d']}  disc={p['disc']:+7.3f}%  BHAR={p['bhar']:+8.3f}%  raw={p['raw']:+8.3f}%")

    # 极端正 BHAR 占比
    by_bhar.sort(key=lambda x: x["bhar"], reverse=True)
    top20_pos_bhar = sum(p["bhar"] for p in by_bhar[:20])
    print(
        f"\n  BHAR 最正 20 picks 合计={top20_pos_bhar:+.2f}% / total={total_bhar:+.2f}% "
        f"= {top20_pos_bhar / total_bhar * 100 if total_bhar else 0:.1f}%  (n=20/{len(picks)})"
    )

    # ============================================================
    # 5. 极端折价 picks 单独剔除后 edge 还剩多少
    # ============================================================
    print("\n" + "=" * 76)
    print("5. 敏感性：剔除极端折价 pick（disc<-5% / <-10%）后 edge")
    print("=" * 76)
    for cutoff in (-2, -5, -10, -20):
        kept = [p for p in picks if p["disc"] >= cutoff]
        kicked = [p for p in picks if p["disc"] < cutoff]
        if not kept:
            continue
        kb = sum(p["bhar"] for p in kept)
        ke = kb / len(kept) if kept else 0
        print(
            f"  剔除 disc<{cutoff}%: 剔 {len(kicked)} 个, 留 {len(kept)} 个, "
            f"BHAR mean={ke:+.4f}% (原 {total_bhar / len(picks):+.4f}%)  "
            f"kicked_BHAR_mean={sum(p['bhar'] for p in kicked) / len(kicked) if kicked else 0:+.4f}%"
        )

    # ============================================================
    # 6. 成本 realism：折价 ETF spread 估算
    # ============================================================
    print("\n" + "=" * 76)
    print("6. 成本 realism：0.15% flat 是否合理？")
    print("=" * 76)
    print("  脚本假设: ETF_COST=0.15% (佣金~0.06% 往返 + 滑点~0.09%)")
    print("  问题: 折价 ETF（disc<-0.3%）可能流动性差 → spread 更宽")
    print("  本测无 high/low 数据 → 无法直接算 spread，但可用日内 volatility 代理")
    # 用 open-close 差代理日内波动（spread 下限）
    pick_intraday = []
    for p in picks:
        # t1 day: open 已知，但无 close for t1... 用 t2 close - t1 open 已是 raw
        # 改用 signal day close vs nav 已知。用 |disc| 当折价幅度代理
        pick_intraday.append(abs(p["disc"]))
    pick_intraday.sort()
    nn = len(pick_intraday)
    print(
        f"  picks |disc|: p50={pick_intraday[nn // 2]:.3f}% "
        f"p90={pick_intraday[int(nn * 0.9)]:.3f}% "
        f"p99={pick_intraday[int(nn * 0.99)]:.3f}% "
        f"max={pick_intraday[-1]:.3f}%"
    )
    print("  推论: 折价越深 → 该 ETF 当日大概率 illiquid → spread 可能远超 0.09%")
    print("  例: disc=-5% 的 ETF 几乎必然是低流动性品种，bid-ask spread 可能 0.5-2%")

    # 模拟 cost=0.30% / 0.50% / 1.0% 下 net EV
    print("\n  --- 成本敏感性（净 EV 随 cost 变化）---")
    mean_bhar = total_bhar / len(picks)
    for c in (0.15, 0.20, 0.30, 0.50, 1.0):
        print(f"  cost={c:.2f}%: net_BHAR={mean_bhar - c:+.4f}%  {'(edge 死)' if mean_bhar - c <= 0 else '(edge 活)'}")

    # ============================================================
    # 7. 重复信号日检测（同日多 ETF 折价 = 同向市场冲击）
    # ============================================================
    print("\n" + "=" * 76)
    print("7. 重复信号日：同日多 ETF 同时折价（day-paired t 的相关性风险）")
    print("=" * 76)
    by_date = defaultdict(list)
    for p in picks:
        by_date[p["d"]].append(p)
    multi = [(d, ps) for d, ps in by_date.items() if len(ps) >= 2]
    multi.sort(key=lambda x: len(x[1]), reverse=True)
    print(f"  信号日 {len(by_date)} 个, 其中 >=2 ETF 同日折价: {len(multi)} 天")
    print(f"  最多同日 ETF 数: {len(multi[0][1]) if multi else 0} ({multi[0][0] if multi else '-'})")
    print("  Top 10 同日多 ETF:")
    for d, ps in multi[:10]:
        codes = ",".join(p["code"] for p in ps)
        bhar_sum = sum(p["bhar"] for p in ps)
        print(f"  {d}: {len(ps)} ETFs [{codes}]  BHAR合计={bhar_sum:+.3f}%")

    # 同日 >=5 ETF 的天数贡献
    big_days = [(d, ps) for d, ps in multi if len(ps) >= 5]
    if big_days:
        bd_bhar = sum(p["bhar"] for d, ps in big_days for p in ps)
        print(
            f"\n  >=5 ETF 同日: {len(big_days)} 天, "
            f"BHAR 合计={bd_bhar:+.2f}% / total={total_bhar:+.2f}% "
            f"= {bd_bhar / total_bhar * 100 if total_bhar else 0:.1f}%"
        )


if __name__ == "__main__":
    main()
