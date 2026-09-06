# -*- coding: utf-8 -*-
"""PEAD（业绩预告）event study — §44 v2 concrete edge validation.

因子: PEAD (Post Earnings Announcement Drift) — 业绩预告 pubDate 后的 drift。
数据源: baostock query_forecast_report (带 pubDate + 预告类型) + kline_cache (5226 股日K)。
样本: pubDate 在 kline_cache 窗口内 (2025-12-25 ~ 2026-09-04) 的预告股。
target: drift [D+1 open, D+N close] for N=1..5, 扣 0.70% round-trip 成本。
§44 v2 方法:
  ① 前置窗口 sanity: per-horizon mean + 胜率 + IC 定位 drift 在哪窗口
  ② day_paired lift (event vs universe, 非池化) + within-day permutation null + Bonferroni
  ③ 不外推 (选股 PEAD edge ≠ 整体 edge)
  ④ 扣成本 0.70% round-trip
  ⑤ 小 n 标 underpowered 不判劣于随机
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.first_board_premium_baseline import _load_kline_cache, _bs_code  # noqa: E402

# ── 常量 ──────────────────────────────────────────────────────────────────
CACHE_PATH = Path("/Users/lizhiwei/project/code/stock/Vibe-Research/.vibe-research/baostock_kline_cache.json")
FORECAST_CACHE = ROOT / "backend" / ".scratch" / "pead-event-study" / "forecast_reports.json"
OUT_DIR = ROOT / "backend" / ".scratch" / "pead-event-study"
COST_PCT = 0.70          # round-trip 成本（买+卖，佣金+滑点+印花税弱近似）
N_PERM = 500             # permutation 次数 (p-value 分辨率 0.002, alpha_adj=0.01 足够)
PERM_SEED = 42
ALPHA_ADJ = 0.05 / 5     # Bonferroni K=5（5 个 horizon，D+1~D+5）

GOOD_NEWS_TYPES = {"预增", "略增", "扭亏", "续盈", "减亏"}
BAD_NEWS_TYPES = {"预减", "略减", "首亏", "增亏", "续亏"}


def _to_float(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _winrate(returns: list[float]) -> float:
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns)


# ── Step 1: 收集预告数据 (cache 到磁盘) ─────────────────────────────────
def collect_forecast_reports() -> list[dict]:
    if FORECAST_CACHE.exists():
        data = json.loads(FORECAST_CACHE.read_bytes())
        print(f"[PEAD] forecast cache hit: {len(data)} events")
        return data

    import baostock as bs

    cache = _load_kline_cache()
    if not cache:
        return []
    codes = sorted(cache.keys())
    print(f"[PEAD] collecting forecast reports for {len(codes)} codes...")

    events: list[dict] = []
    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        return []

    t0 = time.time()
    for i, code in enumerate(codes):
        bsc = _bs_code(code)
        if not bsc:
            continue
        try:
            rs = bs.query_forecast_report(bsc, start_date="2025-01-01", end_date="2026-09-04")
        except Exception:
            continue
        while rs.error_code == "0" and rs.next():
            d = rs.get_row_data()
            if len(d) < 7 or not d[1]:
                continue
            events.append({
                "code": code, "bs_code": bsc,
                "pub_date": d[1], "stat_date": d[2], "ftype": d[3],
                "abstract": d[4],
                "chg_up": _to_float(d[5]), "chg_dwn": _to_float(d[6]),
            })
        if (i + 1) % 200 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(codes)} events={len(events)} "
                  f"elapsed={el:.0f}s eta={el/(i+1)*(len(codes)-i-1):.0f}s", flush=True)
        if (i + 1) % 500 == 0:
            try:
                bs.logout()
            except Exception:
                pass
            bs.login()

    try:
        bs.logout()
    except Exception:
        pass
    print(f"[PEAD] collected {len(events)} events in {time.time()-t0:.0f}s")
    FORECAST_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FORECAST_CACHE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    return events


# ── Step 2: 交易日历 + bar 查找 ──────────────────────────────────────────
def build_calendar(cache: dict) -> list[str]:
    dates = set()
    for bars in cache.values():
        for b in bars:
            if b.get("date"):
                dates.add(b["date"])
    return sorted(dates)


def next_trading_day(calendar: list[str], pub_date: str) -> str | None:
    import bisect
    idx = bisect.bisect(calendar, pub_date)
    return calendar[idx] if idx < len(calendar) else None


def nth_trading_day(calendar: list[str], entry_date: str, n: int) -> str | None:
    import bisect
    idx = bisect.bisect_left(calendar, entry_date)
    target = idx + n
    return calendar[target] if target < len(calendar) else None


# ── Step 3: 算 drift returns (event + universe, 一次性遍历) ─────────────
def compute_all_returns(
    cache: dict,
    events: list[dict],
    calendar: list[str],
    horizons: list[int],
) -> dict:
    """一次性遍历全 cache, 算 event + universe 的 drift returns per pubDate per horizon.

    优化: 对每个 pubDate, 预计算 entry_date + exit_dates, 然后遍历全 cache 一次
    收集 universe returns + event returns for ALL horizons.
    """
    from datetime import datetime, timedelta

    max_cache_date = calendar[-1] if calendar else ""
    min_cache_date = calendar[0] if calendar else ""
    max_pub = (datetime.strptime(max_cache_date, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")

    # 过滤 valid events + 预计算 entry_date
    valid_events: list[dict] = []
    for e in events:
        pub = e["pub_date"]
        if pub < min_cache_date or pub > max_pub:
            continue
        if e["code"] not in cache:
            continue
        entry_date = next_trading_day(calendar, pub)
        if not entry_date:
            continue
        last_exit = nth_trading_day(calendar, entry_date, max(horizons) - 1)
        if not last_exit:
            continue
        e["entry_date"] = entry_date
        valid_events.append(e)

    print(f"[PEAD] valid events: {len(valid_events)} / {len(events)}")
    type_counts = defaultdict(int)
    for e in valid_events:
        type_counts[e["ftype"]] += 1
    print(f"[PEAD] types: {dict(sorted(type_counts.items(), key=lambda x: -x[1]))}")

    # pubDate → event codes
    events_by_pub: dict[str, set[str]] = defaultdict(set)
    for e in valid_events:
        events_by_pub[e["pub_date"]].add(e["code"])
    unique_pubs = sorted(events_by_pub.keys())
    print(f"[PEAD] unique pubDates: {len(unique_pubs)}")

    # 对每个 pubDate, 预计算 entry_date + exit_dates per horizon
    pub_meta: dict[str, dict] = {}
    for pub in unique_pubs:
        entry_date = next_trading_day(calendar, pub)
        if not entry_date:
            continue
        exits = {}
        for N in horizons:
            ed = nth_trading_day(calendar, entry_date, N - 1)
            if ed:
                exits[N] = ed
        if len(exits) == len(horizons):
            pub_meta[pub] = {"entry_date": entry_date, "exits": exits}

    valid_pubs = sorted(pub_meta.keys())
    print(f"[PEAD] valid pubDates (all horizons reachable): {len(valid_pubs)}")

    # 预建 date → bar index per code
    print("[PEAD] building bar index...", flush=True)
    t0 = time.time()
    code_date_bar: dict[str, dict[str, dict]] = {}
    for code, bars in cache.items():
        d = {}
        for b in bars:
            if b.get("date"):
                d[b["date"]] = b
        code_date_bar[code] = d
    print(f"[PEAD] bar index built in {time.time()-t0:.1f}s ({len(code_date_bar)} codes)")

    # 对每个 pubDate, 遍历全 cache 一次, 收集 ALL horizons 的 returns
    result: dict = {}
    for N in horizons:
        result[N] = {
            "event_by_day": defaultdict(list),
            "universe_by_day": defaultdict(list),
        }

    # 收集 event 类型映射 (code, pub) → ftype
    event_type_map: dict[tuple[str, str], str] = {}
    for e in valid_events:
        event_type_map[(e["code"], e["pub_date"])] = e["ftype"]

    t0 = time.time()
    for pi, pub in enumerate(valid_pubs):
        entry_date = pub_meta[pub]["entry_date"]
        exits = pub_meta[pub]["exits"]
        event_codes = events_by_pub[pub]

        for N in horizons:
            exit_date = exits[N]
            for code, d_bar in code_date_bar.items():
                eb = d_bar.get(entry_date)
                xb = d_bar.get(exit_date)
                if not eb or not xb:
                    continue
                eo = _to_float(eb.get("open"))
                xc = _to_float(xb.get("close"))
                if eo is None or xc is None or eo <= 0:
                    continue
                net_ret = (xc - eo) / eo * 100 - COST_PCT
                result[N]["universe_by_day"][pub].append(net_ret)
                if code in event_codes:
                    result[N]["event_by_day"][pub].append(net_ret)

        if (pi + 1) % 20 == 0:
            print(f"  pubDate {pi+1}/{len(valid_pubs)} ({pub}) "
                  f"elapsed={time.time()-t0:.1f}s", flush=True)

    for N in horizons:
        ev = [r for rs in result[N]["event_by_day"].values() for r in rs]
        un = [r for rs in result[N]["universe_by_day"].values() for r in rs]
        print(f"[PEAD] D+{N}: event n={len(ev)} universe n={len(un)} days={len(result[N]['event_by_day'])}")

    # 附加: event_type_map + valid_events + code_date_bar 供后续 good/bad 分类
    return result, event_type_map, valid_events, code_date_bar


# ── Step 4: §44 分析 (优化版 permutation) ────────────────────────────────
def day_paired_lift_fast(
    event_by_day: dict[str, list[float]],
    universe_winrate_by_day: dict[str, float],
    universe_returns_by_day: dict[str, list[float]],
) -> dict:
    """逐日配对 lift (非池化) — 预计算 universe winrate, 只算 event side.

    比原 day_paired_lift 快 ~500× (universe winrate 只算一次).
    """
    day_lifts: list[float] = []
    for date in sorted(event_by_day.keys()):
        s = event_by_day.get(date, [])
        r_wr = universe_winrate_by_day.get(date)
        if not s or r_wr is None or r_wr <= 0:
            continue
        s_wr = _winrate(s)
        day_lifts.append(s_wr / r_wr)
    return {
        "n_days": len(day_lifts),
        "winrate_lift_avg": round(statistics.mean(day_lifts), 4) if day_lifts else None,
        "surv_n_pooled": sum(len(event_by_day.get(d, [])) for d in event_by_day),
    }


def _fast_sample(lst: list, k: int, rng: random.Random) -> list:
    """Sample k from lst without O(n) copy. O(k) for k << n (set-based)."""
    n = len(lst)
    if k >= n:
        return list(lst)
    if k == 0:
        return []
    selected: set[int] = set()
    result: list = []
    while len(result) < k:
        idx = rng.randrange(n)
        if idx not in selected:
            selected.add(idx)
            result.append(lst[idx])
    return result


def permutation_null_fast(
    event_by_day: dict[str, list[float]],
    universe_returns_by_day: dict[str, list[float]],
    universe_winrate_by_day: dict[str, float],
    n_perm: int = N_PERM,
    seed: int = PERM_SEED,
) -> list[float]:
    """within-day survivor resampling null — 优化版.

    预计算 universe winrate, permutation 只算 null survivor winrate.
    用 _fast_sample 避免 random.sample 的 O(n) copy (universe ~5000/day).
    O(n_perm × n_days × avg_event_size) 而非 O(n_perm × n_days × universe_size).
    """
    rng = random.Random(seed)
    nulls: list[float] = []
    event_days = sorted(event_by_day.keys())

    for _ in range(n_perm):
        day_lifts: list[float] = []
        for date in event_days:
            raw_rets = universe_returns_by_day.get(date, [])
            surv_rets = event_by_day.get(date, [])
            r_wr = universe_winrate_by_day.get(date)
            if not surv_rets or not raw_rets or len(raw_rets) < len(surv_rets):
                continue
            if r_wr is None or r_wr <= 0:
                continue
            null_surv = _fast_sample(raw_rets, len(surv_rets), rng)
            null_wr = _winrate(null_surv)
            day_lifts.append(null_wr / r_wr)
        if day_lifts:
            nulls.append(statistics.mean(day_lifts))
    return nulls


def spearman_ic(signal: list[float], ret: list[float]) -> float | None:
    if len(signal) < 10:
        return None
    try:
        def rank(lst):
            si = sorted(range(len(lst)), key=lambda i: lst[i])
            ranks = [0.0] * len(lst)
            for r, i in enumerate(si):
                ranks[i] = r + 1.0
            from collections import defaultdict as dd
            vtoc = dd(list)
            for i, v in enumerate(lst):
                vtoc[v].append(i)
            for v, idxs in vtoc.items():
                if len(idxs) > 1:
                    avg_r = sum(ranks[i] for i in idxs) / len(idxs)
                    for i in idxs:
                        ranks[i] = avg_r
            return ranks

        rs1 = rank(signal)
        rs2 = rank(ret)
        n = len(signal)
        d2 = sum((a - b) ** 2 for a, b in zip(rs1, rs2))
        return round(1 - 6 * d2 / (n * (n ** 2 - 1)), 4)
    except Exception:
        return None


def four_state(lift: float | None, n: int) -> str:
    if n < 30:
        return "underpowered"
    if lift is None:
        return "underpowered"
    if lift < 1.0:
        return "no_edge"
    if lift >= 2.0:
        return "edge"
    return "no_edge"


def analyze_subset(
    subset_by_day: dict[str, list[float]],
    universe_returns_by_day: dict[str, list[float]],
    universe_winrate_by_day: dict[str, float],
    horizons: list[int],
    all_returns: dict,
    label: str,
) -> dict:
    """对 good/bad/all 子集跑 day_paired lift + permutation per horizon。"""
    results: dict = {}
    for N in horizons:
        ev_by_day = subset_by_day.get(N, {})
        if not ev_by_day:
            results[f"D+{N}"] = {"n": 0, "verdict": "underpowered"}
            continue

        # pre-compute universe winrate (only for days that have events)
        u_wr_by_day = {d: universe_winrate_by_day[N].get(d) for d in ev_by_day}
        u_ret_by_day = {d: universe_returns_by_day[N].get(d, []) for d in ev_by_day}

        obs = day_paired_lift_fast(ev_by_day, u_wr_by_day, u_ret_by_day)
        obs_lift = obs["winrate_lift_avg"]
        n_event = obs["surv_n_pooled"]

        # permutation
        nulls: list[float] = []
        p_value = 1.0
        if n_event >= 30:
            nulls = permutation_null_fast(ev_by_day, u_ret_by_day, u_wr_by_day)
            if nulls:
                p_value = sum(1 for x in nulls if x >= (obs_lift or 0)) / len(nulls)

        ev_returns = [r for rs in ev_by_day.values() for r in rs]
        un_returns = [r for rs in u_ret_by_day.values() for r in rs]

        verdict = four_state(obs_lift, n_event)
        results[f"D+{N}"] = {
            "n_event": n_event,
            "n_universe": len(un_returns),
            "n_days": obs["n_days"],
            "event_winrate": round(_winrate(ev_returns), 4) if ev_returns else None,
            "universe_winrate": round(_winrate(un_returns), 4) if un_returns else None,
            "event_mean_pct": round(statistics.mean(ev_returns), 4) if ev_returns else None,
            "universe_mean_pct": round(statistics.mean(un_returns), 4) if un_returns else None,
            "winrate_lift": obs_lift,
            "p_value": round(p_value, 4),
            "alpha_adj": round(ALPHA_ADJ, 5),
            "is_significant": p_value < ALPHA_ADJ,
            "verdict": verdict,
            "n_perm": len(nulls),
        }
        print(f"[PEAD {label}] D+{N}: n={n_event} lift={obs_lift} "
              f"ev_wr={results[f'D+{N}']['event_winrate']} "
              f"un_wr={results[f'D+{N}']['universe_winrate']} "
              f"ev_mean={results[f'D+{N}']['event_mean_pct']} "
              f"un_mean={results[f'D+{N}']['universe_mean_pct']} "
              f"p={p_value:.4f} verdict={verdict}")
    return results


def run_pead_analysis() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: 预告数据
    events = collect_forecast_reports()
    if not events:
        return {"error": "no forecast events"}

    # Step 2: kline_cache + 索引
    cache = _load_kline_cache()
    if not cache:
        return {"error": "no kline cache"}
    print(f"[PEAD] kline cache: {len(cache)} codes")
    calendar = build_calendar(cache)
    print(f"[PEAD] calendar: {len(calendar)} days ({calendar[0]} ~ {calendar[-1]})")

    # Step 3: 算 returns
    horizons = [1, 2, 3, 4, 5]
    all_returns, event_type_map, valid_events, code_date_bar = compute_all_returns(
        cache, events, calendar, horizons
    )

    # 预计算 universe winrate + returns per horizon per day
    universe_winrate_by_day: dict = {}
    universe_returns_by_day: dict = {}
    for N in horizons:
        universe_winrate_by_day[N] = {}
        universe_returns_by_day[N] = {}
        for d, rets in all_returns[N]["universe_by_day"].items():
            universe_winrate_by_day[N][d] = _winrate(rets)
            universe_returns_by_day[N][d] = rets

    # 构建 good/bad/all event by_day per horizon
    from datetime import datetime, timedelta
    max_cache_date = calendar[-1]
    max_pub = (datetime.strptime(max_cache_date, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")

    all_by_day: dict = {N: {} for N in horizons}
    good_by_day: dict = {N: {} for N in horizons}
    bad_by_day: dict = {N: {} for N in horizons}

    for e in valid_events:
        pub = e["pub_date"]
        code = e["code"]
        ftype = e["ftype"]
        entry_date = e["entry_date"]

        for N in horizons:
            exit_date = nth_trading_day(calendar, entry_date, N - 1)
            if not exit_date:
                continue
            d_bar = code_date_bar.get(code, {})
            eb = d_bar.get(entry_date)
            xb = d_bar.get(exit_date)
            if not eb or not xb:
                continue
            eo = _to_float(eb.get("open"))
            xc = _to_float(xb.get("close"))
            if eo is None or xc is None or eo <= 0:
                continue
            net_ret = (xc - eo) / eo * 100 - COST_PCT
            all_by_day[N].setdefault(pub, []).append(net_ret)
            if ftype in GOOD_NEWS_TYPES:
                good_by_day[N].setdefault(pub, []).append(net_ret)
            elif ftype in BAD_NEWS_TYPES:
                bad_by_day[N].setdefault(pub, []).append(net_ret)

    # Step 4: §44 分析
    print("\n=== ALL EVENTS ===")
    all_results = analyze_subset(
        all_by_day, universe_returns_by_day, universe_winrate_by_day,
        horizons, all_returns, "all"
    )

    print("\n=== GOOD NEWS (预增/略增/扭亏/续盈/减亏) ===")
    good_results = analyze_subset(
        good_by_day, universe_returns_by_day, universe_winrate_by_day,
        horizons, all_returns, "good"
    )

    print("\n=== BAD NEWS (预减/略减/首亏/增亏/续亏) ===")
    bad_results = analyze_subset(
        bad_by_day, universe_returns_by_day, universe_winrate_by_day,
        horizons, all_returns, "bad"
    )

    # IC: forecast chg% vs drift return (all events)
    print("\n=== IC (forecast chg% vs drift) ===")
    ic_results: dict = {}
    for N in horizons:
        sig_ret: list[tuple[float, float]] = []
        for e in valid_events:
            pub = e["pub_date"]
            entry_date = e["entry_date"]
            exit_date = nth_trading_day(calendar, entry_date, N - 1)
            if not exit_date:
                continue
            code = e["code"]
            d_bar = code_date_bar.get(code, {})
            eb = d_bar.get(entry_date)
            xb = d_bar.get(exit_date)
            if not eb or not xb:
                continue
            eo = _to_float(eb.get("open"))
            xc = _to_float(xb.get("close"))
            if eo is None or xc is None or eo <= 0:
                continue
            net_ret = (xc - eo) / eo * 100 - COST_PCT
            cu = e.get("chg_up")
            cd = e.get("chg_dwn")
            if cu is not None and cd is not None:
                sig = (cu + cd) / 2
            elif cu is not None:
                sig = cu
            elif cd is not None:
                sig = cd
            else:
                continue
            sig_ret.append((sig, net_ret))
        ic_val = spearman_ic([s for s, _ in sig_ret], [r for _, r in sig_ret]) if len(sig_ret) >= 10 else None
        ic_results[f"D+{N}"] = {"n": len(sig_ret), "ic": ic_val}
        print(f"[PEAD IC] D+{N}: n={len(sig_ret)} IC={ic_val}")

    matrix = {
        "factor": "PEAD (业绩预告 drift)",
        "method": "§44 v2: day_paired non-pooled + within-day permutation null + Bonferroni K=5",
        "params": {
            "cost_pct": COST_PCT,
            "n_perm": N_PERM,
            "alpha_adj": round(ALPHA_ADJ, 5),
            "horizons": horizons,
            "cache_window": f"{calendar[0]} ~ {calendar[-1]}" if calendar else "",
            "n_cache_codes": len(cache),
        },
        "all_events": all_results,
        "good_news": good_results,
        "bad_news": bad_results,
        "ic": ic_results,
        "good_types": list(GOOD_NEWS_TYPES),
        "bad_types": list(BAD_NEWS_TYPES),
        "note": ("event drift = (D+N close - D+1 open)/D+1 open - 0.70% cost; "
                 "universe = all cache stocks same window; "
                 "day_paired lift non-pooled; within-day permutation null; "
                 "不外推: PEAD selection edge ≠ overall edge (盘中 60% 未测)"),
    }
    out_path = OUT_DIR / "matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[PEAD] matrix saved: {out_path}")
    return matrix


if __name__ == "__main__":
    run_pead_analysis()
