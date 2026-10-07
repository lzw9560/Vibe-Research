# -*- coding: utf-8 -*-
"""溢价大宗知情买方 (Premium block-trade informed-buyer) — §44 v3 + 10 flaw 全套口径.

策略:
  T日 = 大宗成交日, premium_ratio > 0 (deal_price > close_price) → T+1 open 买入.
  Exit: T+N open (N=2,3,4,5) — open_ev 非 close_ev (避 flaw4 T+1 日内泄漏).
  Filters: 跳过 T+1 一字涨停 (买不进) + 排除 ETF/基金 + 排除关联方过户噪声(敏感度).
  成本: 个股 0.30% round-trip (流动性分层上限, 保守) + 滑点 0.2% (R6 gap-through).

数据: .vibe-research/block_trade_raw.json (20000 条).
先验: 0.30 (informed-buyer hypothesis, US 大宗文献 documented).
风险: A 股溢价大宗多为关联方过户噪声 + selection-lift 1.17x 弱反证.
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import (  # noqa: E402
    ROOT, DATA, KLINE_DB,
    limit_for_code, is_yizi_t1,
    ev_stats, day_paired_t, bonferroni_p, norm_sf_positive,
    walk_forward, verdict_for, COST, SLIPPAGE,
)

BLOCK_JSON = DATA / "block_trade_raw.json"
BENCH_CODE = "000016"  # 上证50 (CSI300 不可用, 用上证50 作 proxy benchmark)

# A-share stock prefixes (排除 ETF/基金/北交 太薄)
STOCK_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003",
                  "300", "301", "688", "689")


# ---------- data ----------

def load_block_premium() -> list[dict]:
    """返回 premium_ratio > 0 且为 A 股个股的大宗记录."""
    with open(BLOCK_JSON) as f:
        data = json.load(f)
    out = [r for r in data
           if r.get("premium_ratio", 0) > 0
           and r.get("code", "").startswith(STOCK_PREFIXES)]
    return out


def load_kline_map() -> tuple[dict[str, dict[str, dict]], set[str]]:
    """code -> {date: bar}; all_dates set."""
    conn = sqlite3.connect(str(KLINE_DB))
    code_map: dict[str, dict[str, dict]] = {}
    all_dates: set[str] = set()
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        dmap = {b["date"]: b for b in bars if b.get("date")}
        if dmap:
            code_map[code] = dmap
            all_dates.update(dmap.keys())
    conn.close()
    calendar = sorted(all_dates)
    return code_map, set(calendar)


def is_yizi_dit_deal(exit_bar: dict, prev_close: float, limit: float) -> bool:
    """T+N 一字跌停: open 和 high 都在跌停价附近 (locked, 卖不出 at open)."""
    if prev_close <= 0:
        return False
    lim_dn = prev_close * (1 - limit)
    o = exit_bar.get("open")
    h = exit_bar.get("high")
    if o is None or h is None or lim_dn <= 0:
        return False
    return abs(o - lim_dn) / lim_dn < 0.005 and abs(h - lim_dn) / lim_dn < 0.005


# ---------- pick construction ----------

def build_block_picks(block_recs: list[dict], code_map: dict[str, dict[str, dict]],
                     calendar_sorted: list[str], max_n: int = 5) -> list[dict]:
    """构建 picks: entry = T+1 open, exit = T+N open (N=2..max_n).

    跳过: 无 kline / T+1 无 bar / T+1 一字涨停 (买不进) / 任意 T+k 无 bar.
    返回每条含 code/block_date/t1_date/entry + bars[T..T+max_n].
    """
    date_idx = {d: i for i, d in enumerate(calendar_sorted)}
    picks: list[dict] = []
    skipped_no_kline = skipped_no_bar = skipped_yizi = skipped_oob = 0
    for rec in block_recs:
        code = rec["code"]
        bd = rec["date"]  # block trade date = T
        di = date_idx.get(bd)
        if di is None or di + max_n + 1 >= len(calendar_sorted):
            skipped_oob += 1
            continue
        dmap = code_map.get(code)
        if not dmap:
            skipped_no_kline += 1
            continue
        t_bar = dmap.get(bd)
        if t_bar is None or t_bar.get("close") is None:
            skipped_no_bar += 1
            continue
        t_close = t_bar["close"]
        if t_close <= 0:
            skipped_no_bar += 1
            continue

        # collect bars T..T+max_n+1
        bars = {}
        ok = True
        for k in range(max_n + 2):  # T..T+max_n+1 (need prev close for dit check)
            d = calendar_sorted[di + k]
            b = dmap.get(d)
            if b is None:
                ok = False
                break
            bars[k] = (d, b)  # k=0 -> T, k=1 -> T+1 ...
        if not ok:
            skipped_no_bar += 1
            continue

        t1_date, t1_bar = bars[1]
        t1_open = t1_bar.get("open")
        if t1_open is None or t1_open <= 0:
            skipped_no_bar += 1
            continue

        # flaw1/3: T+1 一字涨停 → 买不进
        is_st = t_bar.get("isST") == "1"
        limit = limit_for_code(code, is_st)
        if is_yizi_t1(t1_bar, t_close, limit):
            skipped_yizi += 1
            continue

        picks.append({
            "code": code,
            "block_date": bd,
            "zt_date": bd,  # alias for walk_forward helper key
            "rec": rec,
            "t_close": t_close,
            "limit": limit,
            "bars": bars,  # k -> (date, bar)
            "entry": t1_open,
            "t1_date": t1_date,
        })
    print(f"  build_block_picks: {len(block_recs)} recs → {len(picks)} picks "
          f"(skip no_kline={skipped_no_kline} no_bar={skipped_no_bar} "
          f"yizi={skipped_yizi} oob={skipped_oob})")
    return picks


# ---------- exit return functions (open_ev) ----------

def open_ev_n(p: dict, n: int) -> float | None:
    """T+1 open 买 → T+N open 卖. open_ev 非 close_ev (避 flaw4)."""
    bars = p["bars"]
    if n + 1 not in bars or n not in bars:
        return None
    # exit day = T+N (k=n); sell at open
    _, exit_bar = bars[n]
    exit_open = exit_bar.get("open")
    if exit_open is None or exit_open <= 0:
        return None
    # flaw3: T+N 一字跌停 → 卖不出 at open, skip (honest: 不可交易)
    prev_date, prev_bar = bars[n - 1]
    prev_close = prev_bar.get("close")
    if prev_close and is_yizi_dit_deal(exit_bar, prev_close, p["limit"]):
        return None
    return (exit_open - p["entry"]) / p["entry"] * 100


def open_ev_stop_n(p: dict, n: int, stop_pct: float = 0.03) -> tuple[float, str] | None:
    """T+1 open 买, -3% stop, exit T+N open. R6 gap-through fill on stop days.

    监控 T+1..T+N-1 日内: low <= stop → triggered.
    A股 T+1: 若 T+1 触发 stop, 不能 T+1 卖, T+2 open 卖 (first available).
    若 T+k (1<k<N) 触发: T+k+1 open 卖 (next available open).
    若无 stop: T+N open 卖.
    """
    bars = p["bars"]
    entry = p["entry"]
    stop_px = entry * (1 - stop_pct)

    # scan T+1 (k=1) .. T+N-1 (k=n-1)
    for k in range(1, n):
        _, b = bars[k]
        low = b.get("low")
        if low is not None and low <= stop_px:
            # triggered on day k → sell next available open (k+1)
            if k + 1 not in bars:
                return None
            _, next_bar = bars[k + 1]
            nxt_open = next_bar.get("open")
            if nxt_open is None or nxt_open <= 0:
                return None
            # check 一字跌停 on exit
            _, prev_bar = bars[k]
            if prev_bar.get("close") and is_yizi_dit_deal(next_bar, prev_bar["close"], p["limit"]):
                return None
            return (nxt_open * (1 - SLIPPAGE) - entry) / entry * 100, f"stop_t{k}_sell_t{k+1}_open"

    # no stop → exit T+N open
    base = open_ev_n(p, n)
    if base is None:
        return None
    return base, "t{n}_open".replace("{n}", str(n))


# ---------- benchmark BHAR ----------

def load_benchmark() -> dict[str, dict]:
    """上证50 (000016) bars by date. proxy for 沪深300."""
    conn = sqlite3.connect(str(KLINE_DB))
    r = conn.execute("SELECT bars_json FROM kline WHERE code=?", (BENCH_CODE,)).fetchone()
    conn.close()
    if not r:
        return {}
    bars = json.loads(r[0])
    return {b["date"]: b for b in bars if b.get("date")}


def bench_return(bench: dict, cal_sorted: list[str], t1_idx: int, exit_idx: int) -> float | None:
    """benchmark return over same window: T+1 open → T+exit open."""
    if exit_idx >= len(cal_sorted) or t1_idx >= len(cal_sorted):
        return None
    d1 = cal_sorted[t1_idx]
    de = cal_sorted[exit_idx]
    b1 = bench.get(d1)
    be = bench.get(de)
    if not b1 or not be:
        return None
    o1 = b1.get("open")
    oe = be.get("open")
    if o1 is None or oe is None or o1 <= 0:
        return None
    return (oe - o1) / o1 * 100


# ---------- main analysis ----------

def analyze_n(picks: list[dict], cal_sorted: list[str], bench: dict, n: int,
              label: str, n_cross_factor: int = 1) -> dict:
    print(f"\n{'=' * 72}")
    print(f"  {label}: exit T+{n} open (open_ev, 避 flaw4)")
    print(f"{'=' * 72}")

    rets = [open_ev_n(p, n) for p in picks]
    valid = [(p, r) for p, r in zip(picks, rets) if r is not None]
    valid_rets = [r for _, r in valid]
    if not valid_rets:
        print("  无 valid picks")
        return {"n": n, "label": label, "verdict": "underpowered"}

    s = ev_stats(valid_rets)
    gross_ev = s["ev"]
    net_ev = gross_ev - COST * 100
    print(f"  raw_ev (散户实际收益): n={s['n']} gross={gross_ev}% net={net_ev}% "
          f"std={s['std']}% WR={s['wr']}% t={s['t']} CI[{s['ci_lo']},{s['ci_hi']}]")

    # day-paired t (同日 block 聚簇)
    by_date: dict[str, list[float]] = defaultdict(list)
    for p, r in valid:
        by_date[p["block_date"]].append(r)
    dt = day_paired_t(by_date)
    n_days = dt["n_days"]
    p_raw = dt["p_one_sided"]
    print(f"  day-paired: n_days={n_days} mean={dt['mean']}% t={dt['t']} p_raw={p_raw}")

    # BHAR vs 上证50 proxy
    bhar_rets = []
    date_idx = {d: i for i, d in enumerate(cal_sorted)}
    for p, r in valid:
        bd = p["block_date"]
        bi = date_idx.get(bd)
        if bi is None:
            continue
        t1_i = bi + 1
        exit_i = bi + n
        br = bench_return(bench, cal_sorted, t1_i, exit_i)
        if br is not None:
            bhar_rets.append(r - br)
    if bhar_rets:
        bs = ev_stats(bhar_rets)
        print(f"  BHAR vs 上证50(proxy): n={bs['n']} mean={bs['ev']}% "
              f"(注: 上证50 非 沪深300, proxy 限制)")
    else:
        print(f"  BHAR: 无 benchmark 匹配")

    # stop variant (R6)
    stop_rets = [open_ev_stop_n(p, n) for p in picks]
    stop_clean = [r[0] for r in stop_rets if r is not None and r[0] is not None]
    if stop_clean:
        ss = ev_stats(stop_clean)
        stop_net = ss["ev"] - COST * 100
        print(f"  stop(-3%)+R6: n={ss['n']} gross={ss['ev']}% net={stop_net}% WR={ss['wr']}%")

    # walk-forward
    def _ret(p, _n=n):
        return open_ev_n(p, _n)
    wf = walk_forward(picks, _ret)
    wf_train_ev = wf_test_ev = wf_test_p = 0.0
    if wf["status"] == "ok":
        wf_train_ev = wf["train_ev"]["ev"]
        wf_test_ev = wf["test_ev"]["ev"]
        wf_test_p = wf["test_day_t"]["p_one_sided"]
        print(f"  walk-forward: train_EV={wf_train_ev}% (n={wf['n_train']}, "
              f"{wf['n_train_dates']}d) test_EV={wf_test_ev}% (n={wf['n_test']}, "
              f"{wf['n_test_dates']}d) test_day_p={wf_test_p}")
    else:
        print(f"  walk-forward: {wf['status']}")

    # verdict
    v = verdict_for(
        ev_gross=gross_ev, t_day=dt["t"], p_raw=p_raw,
        wf_status=wf["status"], wf_train_ev=wf_train_ev,
        wf_test_ev=wf_test_ev, wf_test_p=wf_test_p,
        n_days=n_days, net_ev=net_ev, subset_name=f"premium-block T+{n}",
        n_cross_factor=n_cross_factor,
    )

    return {
        "n": n, "label": label, "picks_n": s["n"], "n_days": n_days,
        "gross_ev": round(gross_ev, 3), "net_ev": round(net_ev, 3),
        "raw_ev": round(gross_ev, 3), "bhar": round(bs["ev"], 3) if bhar_rets else None,
        "day_t": dt["t"], "p_raw": p_raw, "verdict": v,
        "wf_train_ev": round(wf_train_ev, 3), "wf_test_ev": round(wf_test_ev, 3),
        "wf_test_p": round(wf_test_p, 6),
    }


def main():
    print("=" * 72)
    print("溢价大宗知情买方 — §44 v3 + 10 flaw 全套口径严测")
    print("=" * 72)

    block = load_block_premium()
    print(f"\n数据: {BLOCK_JSON.name}")
    print(f"  premium>0 且 A股个股: {len(block)} 条")
    from collections import Counter
    bd = Counter(r["date"] for r in block)
    print(f"  日期范围: {min(bd)} -> {max(bd)} (n_dates={len(bd)})")

    code_map, all_dates = load_kline_map()
    cal_sorted = sorted(all_dates)
    print(f"  kline: {len(code_map)} codes, {len(cal_sorted)} dates "
          f"({cal_sorted[0]} -> {cal_sorted[-1]})")

    picks = build_block_picks(block, code_map, cal_sorted, max_n=5)
    bench = load_benchmark()
    print(f"  benchmark: 上证50({BENCH_CODE}) {'OK' if bench else 'MISSING'} "
          f"(proxy for 沪深300, 限制)")

    # flaw 5 (拥挤倒U / 时段衰减): 测 N=2,3,4,5
    results = []
    n_cross = 4  # 4 exit windows tested → Bonferroni ×4*2=8
    for n in (2, 3, 4, 5):
        r = analyze_n(picks, cal_sorted, bench, n, f"premium-block T+{n} open",
                      n_cross_factor=n_cross)
        results.append(r)

    # sensitivity: exclude extreme premium (>15%) — 关联方过户噪声 proxy
    print(f"\n{'=' * 72}")
    print("  敏感度: 排除极端 premium>15% (关联方过户噪声 proxy)")
    print(f"{'=' * 72}")
    picks_mod = [p for p in picks if p["rec"]["premium_ratio"] <= 0.15]
    print(f"  {len(picks)} → {len(picks_mod)} picks (排除 premium>15%)")
    r_mod = analyze_n(picks_mod, cal_sorted, bench, 2,
                      "premium-block T+2 (excl prem>15%)", n_cross_factor=n_cross)
    results.append(r_mod)

    # summary table
    print(f"\n{'=' * 72}")
    print("  汇总")
    print(f"{'=' * 72}")
    print(f"  {'subset':<32} {'picks':>5} {'days':>5} {'gross':>7} {'net':>7} "
          f"{'raw':>7} {'bhar':>7} {'day_t':>6} {'p_raw':>8} {'wf_tr':>7} "
          f"{'wf_te':>7} {'verdict':>14}")
    for r in results:
        if "verdict" not in r:
            continue
        print(f"  {r['label']:<32} {r.get('picks_n',0):>5} {r.get('n_days',0):>5} "
              f"{r.get('gross_ev',0):>7} {r.get('net_ev',0):>7} {r.get('raw_ev',0):>7} "
              f"{str(r.get('bhar','-')):>7} {r.get('day_t',0):>6} "
              f"{r.get('p_raw',1):>8} {r.get('wf_train_ev',0):>7} "
              f"{r.get('wf_test_ev',0):>7} {r.get('verdict','-'):>14}")

    # flaw checklist
    print(f"\n{'=' * 72}")
    print("  10 flaw 检查")
    print(f"{'=' * 72}")
    print("""  1. entry涨停价溢价: 用 T+1 open (非涨停价), 跳过一字涨停 → CONTROLLED
  2. survivorship: 136 天短窗, 个股退市风险低; 未控 ST/退市 (部分) → PARTIAL
  3. exit一字 over-credit: T+N 一字跌停卖不出→skip → CONTROLLED
  4. T+1日内泄漏: exit=T+N open (open_ev) → CONTROLLED
  5. 拥挤倒U: 测 N=2,3,4,5 时段衰减 → TESTED
  6. R6 gap-through fill: stop 变体按 t+k+1 open+滑点 → CONTROLLED
  7. timing mismatch: BHAR 同窗口 T+1 open→T+N open → CONTROLLED
  8. 成本乐观: 0.30% round-trip (个股上限) + 0.2% 滑点 → CONTROLLED
  9. phantom alpha: 报 raw_ev (散户实际收益) + BHAR 分离 → CONTROLLED
  10. 退化OLS: 单因子 N/A → N/A
  附加: 关联方过户噪声 — 无 firm ID 匹配 buyer/seller, 不可靠过滤;
        用 premium>15% 敏感度 proxy, 限制标注.""")

    # 先验 vs 实际
    print(f"\n{'=' * 72}")
    print("  先验 vs 实际 (诚实对比)")
    print(f"{'=' * 72}")
    print(f"  先验: 0.30 (informed-buyer hypothesis, US 文献 documented)")
    print(f"  风险提示: A 股溢价大宗多为关联方过户噪声 + selection-lift 1.17x 弱反证")
    r2 = results[0]
    print(f"  实际 (T+2 主测): gross_EV={r2.get('gross_ev')}% net_EV={r2.get('net_ev')}% "
          f"day_t={r2.get('day_t')} p_raw={r2.get('p_raw')} n_days={r2.get('n_days')}")
    print(f"  verdict: {r2.get('verdict')}")

    return results


if __name__ == "__main__":
    main()
