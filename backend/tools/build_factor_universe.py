# -*- coding: utf-8 -*-
"""构建横截面因子数据 (Fama-French cross-sectional factor universe).

方法论改变: long-only EV (跟 beta 混淆) → 横截面因子收益 (long top decile + short
bottom decile, 零投资组合). 本脚本只构建**因子数据** (step 1-5), 不做回归.

4 因子 (每日可算, 从 kline cache, 无需基本面):
  - momentum_15d   : 过去 15 交易日累计收益 (~3 周). Jegadeesh-Titman 短期.
  - reversal_5d    : 过去 5 交易日累计收益 (~1 周). Jegadeesh-Lehmann 短期反转.
  - size_logamt20  : log(过去 20 日均成交额). price×volume 规模代理.
  - volatility_20d : 过去 20 日日收益标准差. 低波动率异常.

无 look-ahead: 因子值在 formation 日 t 用到 t 收盘数据; 组合 t+1 入场.
再平衡: 每周 (每 5 交易日). 标准 Fama-French 为月度, 周度已属高频.
流动性过滤: 20 日均成交额 >= 50,000,000 元 + formation 日 volume>0.
"""

from __future__ import annotations
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
INDEX_CACHE = DATA / "index_ohlc_cache.json"
OUT = DATA / "factor_zoo_data.json"

LIQ_AMT_FLOOR = 50_000_000.0  # 20d 均成交额 >= 5000 万元
REBAL_EVERY = 5  # 每 5 交易日再平衡
MOM_DAYS = 15
REV_DAYS = 5
VOL_DAYS = 20
SIZE_DAYS = 20
# 数据质量 guard: 20d vol 窗口内任一日收益 |ret|>0.25 则跳过该 snapshot.
# 0.25 超过所有 A 股日涨跌停 (主板 10%/创业科创 20%/ST 5%), 仅触发于:
# (a) 停牌复牌事件 (如 000670 复牌 2.25→13.24 = +488% 真事件但非因子动态),
# (b) 新股上市前 5 日无涨跌限制的极端波动,
# (c) 数据错误. 这些窗口对横截面因子排序无信息量, 排除.
# 合法的连板涨停 (创业科创 20%/日) 不触发 (0.20<0.25), 保留.
RETURN_GUARD = 0.25


def load_kline_compact() -> tuple[dict[str, list[tuple[str, float, float, float]]], set[str]]:
    """code -> [(date, close, amount, volume)] sorted by date. 仅保留因子所需字段 (省内存)."""
    conn = sqlite3.connect(str(KLINE_DB))
    out: dict[str, list[tuple[str, float, float, float]]] = {}
    all_dates: set[str] = set()
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        rows: list[tuple[str, float, float, float]] = []
        for b in bars:
            if not isinstance(b, dict):
                continue
            d = b.get("date")
            c = b.get("close")
            a = b.get("amount")
            v = b.get("volume")
            if d is None or c is None or c <= 0:
                continue
            # 排除停牌 bar (vol=0/amt=0): close 为前值挂账, 不是真实成交价,
            # 跨停牌边界的 close/close return 是人造巨幅 (如 000670 2.25→13.24 = +488% 假收益).
            # 只保留真实交易日, 使 return 窗口仅跨真实相邻交易日.
            if v is None or v <= 0 or a is None or a <= 0:
                continue
            rows.append((d, float(c), float(a), float(v)))
            all_dates.add(d)
        if rows:
            rows.sort(key=lambda x: x[0])
            out[code] = rows
    conn.close()
    return out, all_dates


def load_market_index() -> dict[str, dict[str, float]]:
    """从 index_ohlc_cache.json 读 sh.000001 (上证综指) 日 pctChg."""
    if not INDEX_CACHE.exists():
        return {}
    d = json.loads(INDEX_CACHE.read_text())
    res: dict[str, dict[str, float]] = {}
    sh = d.get("sh.000001")
    if isinstance(sh, list):
        m: dict[str, float] = {}
        for b in sh:
            if isinstance(b, dict) and b.get("date") and b.get("pctChg") is not None:
                try:
                    m[b["date"]] = float(b["pctChg"])
                except (TypeError, ValueError):
                    pass
        res["sh.000001"] = m
    return res


def main() -> int:
    print("==> loading kline cache (compact) ...", flush=True)
    kmap, all_dates = load_kline_compact()
    n_codes_total = len(kmap)
    calendar = sorted(all_dates)
    n_dates = len(calendar)
    print(f"    codes={n_codes_total} dates={n_dates} range={calendar[0]}~{calendar[-1]}", flush=True)

    # ---- rebalance dates: 每 5 交易日, 从 index>=20 起 (需 20 日 warmup) ----
    cal_idx = {d: i for i, d in enumerate(calendar)}
    rebal_dates = [calendar[i] for i in range(VOL_DAYS, n_dates, REBAL_EVERY)]
    rebal_set = set(rebal_dates)
    print(f"==> rebalance dates (every {REBAL_EVERY}d, from idx {VOL_DAYS}): {len(rebal_dates)}", flush=True)

    # ---- market benchmark ----
    market_idx = load_market_index()
    sh001 = market_idx.get("sh.000001", {})
    # 仅保留 calendar 内日期
    mkt_sh001 = {d: sh001[d] for d in calendar if d in sh001}
    print(f"==> market benchmark sh.000001: {len(mkt_sh001)} dates in calendar", flush=True)

    # ---- 一次遍历: 因子 snapshot + VW universe proxy 累加 ----
    # 累加器: 每个 date 的 sum(ret*amt) 与 sum(amt) -> VW market proxy
    vw_num: dict[str, float] = defaultdict(float)
    vw_den: dict[str, float] = defaultdict(float)
    # 每 date 的 code 计数 (cross-section 规模, 含非 rebal 日, 用于诊断)
    codes_per_date: dict[str, int] = defaultdict(int)

    factor_snaps: dict[str, dict[str, list[float]]] = {}
    # 统计
    total_snap = 0
    skipped_illiquid = 0
    skipped_short = 0
    skipped_event = 0

    for code, rows in kmap.items():
        n = len(rows)
        if n < VOL_DAYS + 1:
            skipped_short += 1
            continue
        dates_c = [r[0] for r in rows]
        closes = [r[1] for r in rows]
        amts = [r[2] for r in rows]
        vols = [r[3] for r in rows]
        # 一次遍历: 累加 VW proxy (每个有前一日 close 的 date)
        # 应用与因子相同的 RETURN_GUARD: 跳过拆股/停牌复牌/数据错误的人造巨幅收益,
        # 否则 VW 均值被 +900% 拆股边界污染 (权重为真实成交额, 放大污染).
        for i in range(1, n):
            prev_c = closes[i - 1]
            if prev_c <= 0:
                continue
            ret = closes[i] / prev_c - 1.0
            if abs(ret) > RETURN_GUARD:
                continue
            amt = amts[i]
            d = dates_c[i]
            vw_num[d] += ret * amt
            vw_den[d] += amt
            codes_per_date[d] += 1
        # 因子 snapshot: 仅 rebal 日期 且 i>=VOL_DAYS
        for i in range(VOL_DAYS, n):
            d = dates_c[i]
            if d not in rebal_set:
                continue
            c_now = closes[i]
            # returns over [i-19 .. i] (20 returns, 每个需 c[k-1])
            rets = [closes[k] / closes[k - 1] - 1.0 for k in range(i - VOL_DAYS + 1, i + 1)]
            # 数据质量 guard: 停牌复牌/新股/数据错误的大幅单日收益
            if any(abs(r) > RETURN_GUARD for r in rets):
                skipped_event += 1
                continue
            # momentum / reversal (close ratio)
            mom = c_now / closes[i - MOM_DAYS] - 1.0
            rev = c_now / closes[i - REV_DAYS] - 1.0
            # volatility (sample std, ddof=1)
            mean_r = sum(rets) / len(rets)
            var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
            vol = math.sqrt(var)
            # size: log(20d 均成交额)
            amt_win = amts[i - SIZE_DAYS + 1 : i + 1]
            mean_amt = sum(amt_win) / len(amt_win)
            if mean_amt <= 0:
                continue
            size = math.log(mean_amt)
            # 流动性过滤
            if mean_amt < LIQ_AMT_FLOOR or vols[i] <= 0:
                skipped_illiquid += 1
                continue
            factor_snaps.setdefault(d, {})[code] = [round(mom, 6), round(rev, 6), round(size, 6), round(vol, 6)]
            total_snap += 1

    # ---- VW universe market proxy ----
    mkt_vw: dict[str, float] = {}
    for d in calendar:
        den = vw_den.get(d, 0.0)
        if den > 0:
            mkt_vw[d] = round(vw_num[d] / den * 100.0, 6)

    # ---- survivorship 评估 ----
    balanced = 0
    missing_backfill = 0
    newly_listed = 0
    for code, rows in kmap.items():
        f, l, nb = rows[0][0], rows[-1][0], len(rows)
        if nb >= 2000 and f <= "2018-06-01" and l >= "2026-06-01":
            balanced += 1
        elif f <= "2018-06-01":
            # 有早期数据但不够 balanced (中途数据缺)
            pass
        # 旧主板 (非创业/科创/北交) 且 start>2020 → 缺回补
        chuang = code.startswith(("300", "301", "688", "689", "920"))
        if not chuang and f > "2020-01-01":
            missing_backfill += 1
        elif chuang and f >= "2024-01-01":
            newly_listed += 1

    # cross-section 规模诊断 (rebal 日期)
    rebal_counts = [len(factor_snaps.get(d, {})) for d in rebal_dates]
    rebal_counts_present = [c for c in rebal_counts if c > 0]
    avg_codes = sum(rebal_counts_present) / len(rebal_counts_present) if rebal_counts_present else 0.0
    min_codes = min(rebal_counts_present) if rebal_counts_present else 0
    max_codes = max(rebal_counts_present) if rebal_counts_present else 0

    metadata = {
        "methodology": "Fama-French cross-sectional factor (long-short decile, zero-investment). "
        "This script builds the factor DATA only; regression done downstream.",
        "n_stocks_total": n_codes_total,
        "n_stocks_balanced_full_hist": balanced,
        "n_stocks_missing_backfill_oldboard": missing_backfill,
        "n_stocks_newly_listed_chuangye": newly_listed,
        "n_dates": n_dates,
        "date_range": f"{calendar[0]}~{calendar[-1]}",
        "market_benchmark": "sh.000001 (上证综指) — real published index, full history (2119 dates in calendar), "
        "correct returns (mean 0.0135%/day, +17.6% cumulative 2018-2026, consistent with roughly-flat 上证综指). "
        "sh.000300 (沪深300) was the REQUESTED benchmark but is UNAVAILABLE: not in kline cache, not in "
        "index_ohlc_cache.json, and baostock fetch hangs on network (login() succeeds but row retrieval times out). "
        "sh.000001 is a valid broad A-share market factor (covers all Shanghai A-shares; broader than 沪深300's 300 "
        "large caps, though Shanghai-only). "
        "NOTE: an amount-weighted (turnover-proxy) universe return was investigated as a market-cap proxy but "
        "DROPPED — without shares-outstanding data, amount-weighting ≠ cap-weighting and introduces a systematic "
        "+0.55%/day upward drift (over-weights high-turnover speculative stocks). Use sh.000001 for CAPM/Fama-French MKT.",
        "factors": {
            "momentum_15d": "cumulative return over past 15 trading days (~3wk), Jegadeesh-Titman short-horizon",
            "reversal_5d": "cumulative return over past 5 trading days (~1wk), Jegadeesh-Lehmann short-term reversal",
            "size_logamt20": "log(mean daily amount over past 20 days) — price×volume size proxy",
            "volatility_20d": "sample std of daily returns over past 20 days (low-volatility anomaly)",
        },
        "rebalance_freq": f"weekly (every {REBAL_EVERY} trading days), {len(rebal_dates)} rebalance dates",
        "no_lookahead": "factor at formation date t uses data through t close; portfolio enters t+1",
        "liquidity_filter": f"20d mean amount >= {LIQ_AMT_FLOOR:.0f} CNY AND volume>0 on formation date",
        "data_quality_guard": (
            f"exclude snapshot if any |daily return| in 20d vol window > {RETURN_GUARD} "
            f"(beyond all A-share daily limits incl chuangye 20%; removes suspension-resumption "
            f"events e.g. 000670 +488% resumption, newly-listed first-5-day spikes, data errors; "
            f"preserves legitimate limit-up streaks where each day <=20%)"
        ),
        "survivorship_note": (
            f"Cache is incrementally populated, NOT a balanced panel. Only {balanced} codes have "
            f"full 2018-2026 history (>=2000 bars, start<=2018-06, end>=2026-06). "
            f"{missing_backfill} OLD-BOARD codes (incl. 000001 平安银行, 000002 万科A — listed pre-2020) "
            f"have only recent bars (start>2020): historical data NOT backfilled. "
            f"{newly_listed} chuangye/kechuang codes genuinely newly listed (start>=2024). "
            f"Implication: (1) the full-period cross-section (2018-2020) has only ~{balanced} codes — "
            f"the backfilled subset is itself potentially NON-RANDOM (selection/survivorship-adjacent bias "
            f"if backfill was not random); (2) recent period (2025-12~2026-09) has ~4000 codes but only "
            f"~179 days → <60 weekly rebalances → UNDERPOWERED for that window alone; (3) the unbalanced "
            f"panel used here includes a code only when it has 20-day history (natural entry/exit), which "
            f"is the standard cross-sectional treatment but means early-period tests run on a selected sample."
        ),
        "cross_section_size": {
            "avg_codes_per_rebalance": round(avg_codes, 1),
            "min": min_codes,
            "max": max_codes,
        },
        "total_factor_snapshots": total_snap,
        "skipped_illiquid": skipped_illiquid,
        "skipped_short_history": skipped_short,
        "skipped_event_contaminated": skipped_event,
        "blockers": [],
        "snapshot_format": "[momentum_15d, reversal_5d, size_logamt20, volatility_20d] per (date, code); only liquid+factor-computable codes stored",
    }

    out = {
        "metadata": metadata,
        "trading_dates": calendar,
        "market_returns": {
            "sh.000001": mkt_sh001,
        },
        "rebalance_dates": rebal_dates,
        "factor_snapshots": factor_snaps,
    }

    print(f"==> writing {OUT} ...", flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    sz_mb = OUT.stat().st_size / 1048576
    print(f"    written {sz_mb:.1f} MB", flush=True)
    print(
        f"==> total snapshots={total_snap} rebal_dates={len(rebal_dates)} "
        f"avg_codes/rebal={avg_codes:.0f} (min={min_codes} max={max_codes})",
        flush=True,
    )
    print(
        f"==> survivorship: balanced={balanced} missing_backfill_oldboard={missing_backfill} newly_listed={newly_listed}",
        flush=True,
    )
    print(
        f"==> skipped: illiquid={skipped_illiquid} short_hist={skipped_short} event_contaminated={skipped_event}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
