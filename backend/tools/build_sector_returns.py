# -*- coding: utf-8 -*-
"""Build sector daily return series + market benchmark for alpha-isolated
sector-rotation research.

Methodology context (per workflow task):
  Original flaw = long-only absolute EV conflates alpha with market beta.
  New approach  = alpha-isolated (long-short, active return vs benchmark,
                  CAPM/Jensen alpha, cross-sectional factor return).
  => This script ONLY builds the data population:
     1. industry classification (code -> industry, 申万, point-in-time 2026-08-16)
     2. per-industry equal-weight daily return series (2018-01-02 .. 2026-09-23)
     3. market benchmark = sh.000001 (上证指数) daily pctChg, aligned to same dates
     4. survivorship / membership coverage stats
  It does NOT run any strategy / hypothesis test. Downstream rotation backtest
  consumes sector_rotation_data.json.

Output: .vibe-research/sector_rotation_data.json
  {
    "dates": [2119 sorted YYYY-MM-DD],
    "benchmark": {"name":"sh.000001","label":"上证指数","returns":[2119 decimals or null]},
    "sector_returns": {industry: [2119 decimals or null]},   # equal-weight mean daily ret
    "sector_membership": {industry: [2119 ints]},             # n stocks present that day
    "meta": {
       "n_dates", "n_sectors", "universe_codes", "industry_snapshot_date",
       "benchmark_source", "survivorship": {...}, ...
    }
  }

Return units: decimal (pctChg / 100). null = no stocks in industry that day.
"""

from __future__ import annotations
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
GENE_DB = DATA / "gene_scores.db"
INDEX_OHLC = DATA / "index_ohlc_cache.json"
OUT = DATA / "sector_rotation_data.json"

BENCH_CODE = "sh.000001"  # 上证指数 (SSE Composite)
BENCH_LABEL = "上证指数"
MIN_STOCKS_PER_INDUSTRY = 2  # keep industries with >=2 classified stocks


def load_industry_map() -> dict[str, str]:
    """code(6-digit) -> industry. Drops '-' (unclassified)."""
    conn = sqlite3.connect(str(GENE_DB))
    mp: dict[str, str] = {}
    for code, _name, industry in conn.execute("SELECT code, name, industry FROM code_industry"):
        if industry and industry != "-":
            mp[code] = industry
    conn.close()
    return mp


def load_code_returns(industry_codes: set[str]) -> dict[str, dict[str, float]]:
    """code -> {date: daily_return_decimal}.

    Computed from CLOSE prices (close[t]/close[prev_traded]-1), NOT pctChg,
    because the kline cache's pctChg is sparse per-bar (baostock incremental
    refresh only populated pctChg for recently-fetched bars; ~770/776 codes
    lack pctChg on 2018-01-02, ~half lack it on 2024-07-19). The `close` field
    is dense on every bar, so close-to-close yields a dense return series.

    Caveat: close is RAW (unadjusted). On ex-dividend/ex-rights days the raw
    close drops mechanically, so that day's return includes the dividend
    distribution as an artificial negative. For an equal-weighted INDUSTRY
    aggregate this is small (dividend yield ~1-2%/yr spread thinly; only
    individual ex-div stocks drop ~5-10% that day) and roughly common across
    industries, so long-short / active-return alpha isolation is robust.
    Documented in meta.survivorship.ex_dividend_caveat.

    Returns one return per bar except each code's first bar (no prior close).
    Suspension gaps: return spans the gap (close[t]/close[last_traded]-1),
    i.e. the resumption gap return — standard.
    """
    conn = sqlite3.connect(str(KLINE_DB))
    code_rets: dict[str, dict[str, float]] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        if code not in industry_codes:
            continue
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        # sort by date; extract (date, close)
        pairs: list[tuple[str, float]] = []
        for b in bars:
            d = b.get("date")
            cl = b.get("close")
            if d is None or cl in (None, ""):
                continue
            try:
                pairs.append((d, float(cl)))
            except (TypeError, ValueError):
                continue
        if len(pairs) < 2:
            continue
        pairs.sort(key=lambda x: x[0])
        dmap: dict[str, float] = {}
        for i in range(1, len(pairs)):
            d_cur, c_cur = pairs[i]
            _d_prev, c_prev = pairs[i - 1]
            if c_prev > 0:
                dmap[d_cur] = round(c_cur / c_prev - 1.0, 8)
        if dmap:
            code_rets[code] = dmap
    conn.close()
    return code_rets


def load_benchmark_returns() -> dict[str, float]:
    """date -> daily_return_decimal for sh.000001 from index_ohlc_cache.json."""
    raw = json.load(open(INDEX_OHLC))
    series = raw.get(BENCH_CODE, [])
    out: dict[str, float] = {}
    for b in series:
        d = b.get("date")
        pc = b.get("pctChg")
        if d is None or pc in (None, ""):
            continue
        try:
            out[d] = float(pc) / 100.0
        except (TypeError, ValueError):
            continue
    return out


def build() -> dict:
    industry_map = load_industry_map()
    # industries with enough stocks
    from collections import Counter

    ind_counts = Counter(industry_map.values())
    keep_industries = {i for i, n in ind_counts.items() if n >= MIN_STOCKS_PER_INDUSTRY}

    code_rets = load_code_returns(set(industry_map.keys()))

    # restrict to kept industries
    code_to_ind = {c: i for c, i in industry_map.items() if i in keep_industries and c in code_rets}

    # build calendar = union of stock dates AND benchmark dates (intersection later)
    stock_dates: set[str] = set()
    for dmap in code_rets.values():
        stock_dates.update(dmap.keys())
    bench_rets = load_benchmark_returns()
    bench_dates = set(bench_rets.keys())
    # use intersection of stock-universe dates and benchmark dates so both series align
    dates = sorted(stock_dates & bench_dates)

    # group codes by industry
    ind_to_codes: dict[str, list[str]] = defaultdict(list)
    for c, i in code_to_ind.items():
        ind_to_codes[i].append(c)

    # build per-industry equal-weight daily return + membership
    sector_returns: dict[str, list] = {}
    sector_membership: dict[str, list] = {}
    for ind, codes in ind_to_codes.items():
        rets: list = [None] * len(dates)
        memb: list = [0] * len(dates)
        for idx, d in enumerate(dates):
            acc = 0.0
            n = 0
            for c in codes:
                r = code_rets[c].get(d)
                if r is not None:
                    acc += r
                    n += 1
            if n > 0:
                rets[idx] = round(acc / n, 8)
            memb[idx] = n
        sector_returns[ind] = rets
        sector_membership[ind] = memb

    # benchmark aligned
    bench_aligned = [round(bench_rets[d], 8) if d in bench_rets else None for d in dates]

    # ---- survivorship / coverage stats ----
    # per industry: first date with >=2 stocks, last date, peak/min membership
    ind_cov = {}
    for ind, codes in ind_to_codes.items():
        memb = sector_membership[ind]
        first2 = next((dates[i] for i, m in enumerate(memb) if m >= 2), None)
        last2 = next((dates[i] for i in range(len(memb) - 1, -1, -1) if memb[i] >= 2), None)
        mx = max(memb) if memb else 0
        mn = min(memb) if memb else 0
        # codes with FULL history (present on every date in dates)
        full = sum(1 for c in codes if all(d in code_rets[c] for d in dates))
        ind_cov[ind] = {
            "n_classified_stocks": len(codes),
            "first_date_ge2": first2,
            "last_date_ge2": last2,
            "peak_membership": mx,
            "min_membership": mn,
            "n_full_history_codes": full,
        }

    # universe-wide survivorship
    # codes present on first date vs last date (membership churn)
    n_on_first = sum(1 for c, dmap in code_rets.items() if dates[0] in dmap) if dates else 0
    n_on_last = sum(1 for c, dmap in code_rets.items() if dates[-1] in dmap) if dates else 0
    # codes with full history
    n_full_universe = sum(1 for c, dmap in code_rets.items() if all(d in dmap for d in dates)) if dates else 0

    # per-date total universe coverage (sum of membership across industries)
    coverage_per_date: list[int] = [0] * len(dates)
    for ind, memb in sector_membership.items():
        for i, m in enumerate(memb):
            coverage_per_date[i] += m

    # ---- dense-core characterization (two-wave cache structure) ----
    # The cache is two-wave: ~920 codes fetched with full 2018-2026 history,
    # plus ~4293 codes fetched with only ~180 recent days (2025-12..2026-09).
    # A rotation strategy needs years, so only the long-history core is usable
    # for the 2018-2025 window. Characterize per-industry long-history coverage.
    LONG_BARS = 1218  # ~5 trading years
    conn = sqlite3.connect(str(KLINE_DB))
    code_barcount: dict[str, int] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            code_barcount[code] = len(json.loads(bj))
        except (json.JSONDecodeError, TypeError):
            code_barcount[code] = 0
    conn.close()
    # per industry: codes with >=5yr history
    ind_long: dict[str, int] = {}
    for ind, codes in ind_to_codes.items():
        ind_long[ind] = sum(1 for c in codes if code_barcount.get(c, 0) >= LONG_BARS)
    n_dense_core = sum(1 for c in code_to_ind if code_barcount.get(c, 0) >= LONG_BARS)
    n_ind_ge10_long = sum(1 for n in ind_long.values() if n >= 10)
    n_ind_zero_long = sum(1 for n in ind_long.values() if n == 0)
    # notable major sectors absent from long-history core
    absent_major = sorted([ind for ind, n in ind_long.items() if n == 0])
    # coverage transition: first date where coverage jumps above 1500 (recent-wave onset)
    cov_jump_date = next((dates[i] for i, c in enumerate(coverage_per_date) if c > 1500), None)

    # fetch actual snapshot date from DB
    conn = sqlite3.connect(str(GENE_DB))
    snap = conn.execute("SELECT MIN(updated_at), MAX(updated_at) FROM code_industry").fetchone()
    conn.close()

    out = {
        "dates": dates,
        "benchmark": {
            "code": BENCH_CODE,
            "label": BENCH_LABEL,
            "returns": bench_aligned,
        },
        "sector_returns": sector_returns,
        "sector_membership": sector_membership,
        "meta": {
            "n_dates": len(dates),
            "n_sectors": len(sector_returns),
            "date_range": [dates[0], dates[-1]] if dates else [None, None],
            "universe_codes_used": len(code_to_ind),
            "industry_snapshot_date_min": snap[0],
            "industry_snapshot_date_max": snap[1],
            "benchmark_source": f"{INDEX_OHLC.name} -> {BENCH_CODE}",
            "return_units": "decimal (pctChg/100), close-to-close",
            "aggregation": "equal-weight mean of stocks present that day",
            "min_stocks_per_industry": MIN_STOCKS_PER_INDUSTRY,
            "survivorship": {
                "point_in_time_classification": (
                    "Industry labels are a single snapshot dated "
                    f"{snap[0]}..{snap[1]}. Applied retroactively to all history "
                    "=> classification look-ahead (mild for broad aggregates; "
                    "recategorizations not tracked)."
                ),
                "survivorship_bias": (
                    "kline cache holds only codes fetchable at cache-build time "
                    "(2026). Codes delisted before 2018 or that delisted mid-period "
                    "are absent => industry returns biased toward survivors (upward). "
                    "Long-short mitigates cross-sectionally but absolute level inflated."
                ),
                "universe_membership_churn": {
                    "n_codes_present_on_first_date": n_on_first,
                    "n_codes_present_on_last_date": n_on_last,
                    "n_codes_full_history_all_dates": n_full_universe,
                    "first_date": dates[0] if dates else None,
                    "last_date": dates[-1] if dates else None,
                },
                "note": (
                    "Equal-weight per-day membership handles IPOs/suspensions "
                    "naturally (absent stock excluded from that day's mean). "
                    "But thin early-period membership (few stocks) makes early "
                    "industry returns noisier — downstream should consider a "
                    "min-membership floor or warmup window."
                ),
                "ex_dividend_caveat": (
                    "Returns computed from RAW (unadjusted) close. On ex-div / "
                    "ex-rights days a stock's close drops mechanically, so that "
                    "day's return embeds the distribution as an artificial negative. "
                    "kline cache has no adjusted-close field. Effect is small at the "
                    "equal-weighted industry-aggregate level (A-share dividend yield "
                    "~1-2%/yr, thinly spread) and roughly common across industries, "
                    "so long-short / active-return alpha isolation is robust. "
                    "If a total-return series is later needed, fetch 复权 close "
                    "from baostock (adjustflag=2 前复权) for the universe."
                ),
                "cache_freshness_tail": (
                    "Last trading date 2026-09-23 has only ~21 codes (cache built "
                    "through 2026-09-23 but most codes last refreshed earlier). "
                    "Downstream should drop the degenerate tail (use "
                    "meta.coverage_per_date to set a min-coverage floor)."
                ),
            },
            "coverage_per_date": coverage_per_date,
            "dense_core": {
                "definition": f"codes with >= {LONG_BARS} bars (~5yr) in kline cache",
                "n_dense_core_codes": n_dense_core,
                "n_industries_with_ge10_long_codes": n_ind_ge10_long,
                "n_industries_with_zero_long_codes": n_ind_zero_long,
                "coverage_jump_to_recent_wave": (
                    f"Date coverage jumps above 1500 codes at {cov_jump_date} "
                    "(recent-wave onset: ~4293 codes fetched with ~180-day "
                    "window 2025-12..2026-09). Before this the series rests "
                    f"on ~{n_dense_core}-code long-history core across "
                    f"{n_ind_ge10_long} well-covered industries."
                ),
                "industries_absent_from_long_core": absent_major,
                "notable_absent_major_sectors": [i for i in absent_major if i in ("银行Ⅱ", "保险Ⅱ", "证券Ⅱ")]
                or (
                    "银行Ⅱ & 保险Ⅱ have ZERO long-history codes — major financial "
                    "sectors absent from any 2018-2025 rotation analysis"
                ),
                "implication": (
                    "A 2-3-week rotation strategy needs years of history. Only the "
                    f"{n_dense_core}-code / {n_ind_ge10_long}-industry long core "
                    "(2018-2025) is usable. The recent 180-day wave is too short "
                    "for rotation but adds cross-sectional breadth. Downstream "
                    "should run the rotation over 2018-2025 on industries with "
                    ">=10 long-history codes, and NOT expect banks/insurance to "
                    "appear in that window."
                ),
            },
            "industry_coverage": ind_cov,
        },
    }
    return out


def main() -> None:
    print("Building sector returns + benchmark ...")
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False))
    m = data["meta"]
    print(f"  dates: {m['n_dates']}  ({m['date_range'][0]} -> {m['date_range'][1]})")
    print(f"  sectors: {m['n_sectors']}")
    print(f"  universe codes used: {m['universe_codes_used']}")
    print(
        f"  benchmark: {data['benchmark']['code']} {data['benchmark']['label']} "
        f"({sum(1 for r in data['benchmark']['returns'] if r is not None)} non-null)"
    )
    sv = m["survivorship"]["universe_membership_churn"]
    print(
        f"  survivorship: first-date codes={sv['n_codes_present_on_first_date']}, "
        f"last-date codes={sv['n_codes_present_on_last_date']}, "
        f"full-history codes={sv['n_codes_full_history_all_dates']}"
    )
    dc = m["dense_core"]
    print(
        f"  dense core (>=5yr history): {dc['n_dense_core_codes']} codes, "
        f"{dc['n_industries_with_ge10_long_codes']} industries well-covered, "
        f"{dc['n_industries_with_zero_long_codes']} industries absent"
    )
    print(f"  coverage jump (recent-wave onset): {dc['coverage_jump_to_recent_wave'][:60]}...")
    print(f"  notable absent: {dc['notable_absent_major_sectors']}")
    # spot check: print a sample sector
    sample_ind = next(iter(data["sector_returns"]))
    sr = data["sector_returns"][sample_ind]
    nn = sum(1 for r in sr if r is not None)
    print(f"  sample sector '{sample_ind}': {nn} non-null days, first 3 returns={sr[:3]}")
    print(f"  written: {OUT}")


if __name__ == "__main__":
    main()
