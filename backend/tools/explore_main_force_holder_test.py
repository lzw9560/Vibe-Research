# -*- coding: utf-8 -*-
"""股东户数变化——主力意图信号 §44 v3 严测。

信号：公告日 change_ratio<0（户数减少=筹码集中=主力吸筹）→ T+1 open 买入
口径：§44 v3 + 10 flaw（entry T+1 open / close_ev / BHAR / per-day-t / Bonferroni / walk-forward / R6 / timing / cost / phantom / 退化 OLS）

数据：shareholder_count_cache.json (5187 股, 430927 records, 2013-2026) + baostock_kline_cache.db (5248 股, 但多数仅 2024-2026 近期)
Caveat：kline 仅近期 → 测的是 2024-2026 子集（survivorship 偏差 + 单 regime）
"""

from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import limit_for_code, is_yizi_t1, ev_stats, day_paired_t, bonferroni_p, ALPHA

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
HOLDER_CACHE = DATA / "shareholder_count_cache.json"
KLINE_DB = DATA / "baostock_kline_cache.db"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

COST = 0.30  # 个股 round-trip 0.30%（佣金+印花+滑点，按流动性分层中值）
HOLD_DAYS = 20  # T+20 close exit（pilot 显示 T+20 +0.77%）
THRESHOLDS = [-3.0, -5.0, -8.0]  # change_ratio 分档


def load_holder():
    with open(HOLDER_CACHE) as f:
        return json.load(f)


def load_kline():
    """返回 code -> {date: bar} + all_dates set."""
    conn = sqlite3.connect(str(KLINE_DB))
    code_map = {}
    all_dates = set()
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        dmap = {}
        for b in bars:
            d = b.get("date")
            if d:
                dmap[d] = b
                all_dates.add(d)
        if dmap:
            code_map[code] = dmap
    conn.close()
    return code_map, all_dates


def load_index():
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    bars = raw.get("sh.000001", [])
    return {b["date"]: b for b in bars if "date" in b}


def build_picks(holder_cache, kline_map, calendar, threshold, hold_days=HOLD_DAYS):
    """公告日 change_ratio<threshold → T+1 open 买 → T+(1+hold) close 卖。
    跳过：无 kline / T+1 一字涨停 / ST / 次新（无 isST 字段则用 change_ratio 源）.
    """
    date_idx = {d: i for i, d in enumerate(calendar)}
    exit_offset = 1 + hold_days
    picks = []
    for code, recs in holder_cache.items():
        dmap = kline_map.get(code)
        if not dmap:
            continue
        for r in recs:
            nd = r.get("notice_date")
            cr = r.get("change_ratio")
            if not nd or nd == "nan" or cr is None:
                continue
            if cr >= threshold:  # threshold 负，cr<threshold 才纳入
                continue
            di = date_idx.get(nd)
            if di is None or di + exit_offset >= len(calendar):
                continue
            t1_date = calendar[di + 1]
            exit_date = calendar[di + exit_offset]
            t1 = dmap.get(t1_date)
            ex = dmap.get(exit_date)
            if t1 is None or ex is None:
                continue
            entry = t1.get("open")
            exit_close = ex.get("close")
            if entry is None or exit_close is None or entry <= 0 or exit_close <= 0:
                continue
            # 一字涨停 T+1 跳过
            t_bar = dmap.get(nd)
            if t_bar is None:
                continue
            t_close = t_bar.get("close")
            if t_close is None or t_close <= 0:
                continue
            is_st = t_bar.get("isST") == "1"
            limit = limit_for_code(code, is_st)
            if is_yizi_t1(t1, t_close, limit):
                continue
            picks.append(
                {
                    "code": code,
                    "notice_date": nd,
                    "t1_date": t1_date,
                    "exit_date": exit_date,
                    "change_ratio": cr,
                    "entry": entry,
                    "exit_close": exit_close,
                    "t_close": t_close,
                    "t1_bar": t1,
                    "ex_bar": ex,
                    "is_st": is_st,
                    "zt_date": nd,  # 兼容 helper.walk_forward 排序
                }
            )
    return picks


def raw_ev(p):
    """散户实际收益 %（含市场 beta）."""
    return (p["exit_close"] - p["entry"]) / p["entry"] * 100


def bhar_vs_index(p, index_map, calendar, date_idx, hold_days=HOLD_DAYS):
    """BHAR vs 沪深300 同窗口 %."""
    di = date_idx.get(p["notice_date"])
    if di is None or di + 1 + hold_days >= len(calendar):
        return None
    t1_date = calendar[di + 1]
    exit_date = calendar[di + 1 + hold_days]
    t1_idx = index_map.get(t1_date)
    ex_idx = index_map.get(exit_date)
    if t1_idx is None or ex_idx is None:
        return None
    t1_close = t1_idx.get("close")
    ex_close = ex_idx.get("close")
    if t1_close is None or ex_close is None or t1_close <= 0:
        return None
    idx_ret = (ex_close - t1_close) / t1_close * 100
    return raw_ev(p) - idx_ret


def walk_forward(picks, ret_fn, calendar):
    """前半 train → 后半 test, 按 notice_date 排序."""
    if not picks:
        return {"status": "no_picks"}
    ps = sorted(picks, key=lambda p: p["notice_date"])
    dates = sorted(set(p["notice_date"] for p in ps))
    if len(dates) < 4:
        return {"status": "too_few_dates", "n_dates": len(dates)}
    mid = len(dates) // 2
    train_dates = set(dates[:mid])
    test_dates = set(dates[mid:])
    train_picks = [p for p in ps if p["notice_date"] in train_dates]
    test_picks = [p for p in ps if p["notice_date"] in test_dates]
    train_rets = [ret_fn(p) for p in train_picks]
    train_rets = [r for r in train_rets if r is not None]
    test_rets = [ret_fn(p) for p in test_picks]
    test_rets = [r for r in test_rets if r is not None]
    train_by_date = defaultdict(list)
    for p in train_picks:
        r = ret_fn(p)
        if r is not None:
            train_by_date[p["notice_date"]].append(r)
    test_by_date = defaultdict(list)
    for p in test_picks:
        r = ret_fn(p)
        if r is not None:
            test_by_date[p["notice_date"]].append(r)
    return {
        "status": "ok",
        "n_train": len(train_rets),
        "n_test": len(test_rets),
        "n_train_dates": len(train_dates),
        "n_test_dates": len(test_dates),
        "train_ev": ev_stats(train_rets),
        "test_ev": ev_stats(test_rets),
        "train_day_t": day_paired_t(train_by_date),
        "test_day_t": day_paired_t(test_by_date),
    }


def verdict_for_holder(ev_gross, t_day, p_raw, wf, n_days, net_ev, label, n_bonf):
    p_bonf = bonferroni_p(p_raw, n_bonf)
    print(f"\n  {label}:")
    print(f"    gross_EV={ev_gross}% net_EV={net_ev}% day_t={t_day} Bonf_p(×{n_bonf})={p_bonf:.6f} n_days={n_days}")
    if wf["status"] == "ok":
        tr = wf["train_ev"]
        te = wf["test_ev"]
        print(f"    walk-forward: train_EV={tr['ev']}% test_EV={te['ev']}% test_p={wf['test_day_t']['p_one_sided']}")
    if ev_gross < 0:
        print(f"    → FALSIFIED: gross EV < 0")
        return "falsified"
    if n_days < 60:
        print(f"    → UNDERPOWERED: n_days={n_days} < 60")
        return "underpowered"
    if p_bonf >= ALPHA:
        print(f"    → FALSIFIED: Bonferroni p={p_bonf} >= {ALPHA}")
        return "falsified"
    if net_ev <= 0:
        print(f"    → FALSIFIED: net EV={net_ev}% <= 0")
        return "falsified"
    if wf["status"] == "ok":
        if wf["train_ev"]["ev"] <= 0:
            print(f"    → EXPLORATORY: train_EV<=0 (regime overfitting)")
            return "exploratory"
        if wf["test_ev"]["ev"] <= 0:
            print(f"    → FALSIFIED: walk-forward test_EV<=0")
            return "falsified"
        wf_test_p_bonf = bonferroni_p(wf["test_day_t"]["p_one_sided"], n_bonf)
        if wf_test_p_bonf >= ALPHA:
            print(f"    → EXPLORATORY: OOS test not significant (Bonf)")
            return "exploratory"
        print(f"    → EDGE-CONFIRMED")
        return "edge-confirmed"
    print(f"    → EXPLORATORY: walk-forward not available")
    return "exploratory"


def main():
    print("=" * 70)
    print("股东户数变化 §44 v3 严测（主力意图角度）")
    print("=" * 70)
    print(f"Caveat: kline cache 仅 2024-2026 近期 → 测的是近期子集（survivorship+单regime）")
    print(f"信号: change_ratio<threshold → T+1 open 买 → T+{HOLD_DAYS} close 卖")
    print(f"成本: {COST}% round-trip（个股中值）")

    holder = load_holder()
    kline_map, all_dates = load_kline()
    index_map = load_index()
    calendar = sorted(all_dates)
    date_idx = {d: i for i, d in enumerate(calendar)}
    print(
        f"\n[数据] holder codes={len(holder)}, kline codes={len(kline_map)}, calendar {calendar[0]}~{calendar[-1]} ({len(calendar)} dates)"
    )

    # BHAR 需要 index 同窗口
    def bhar_fn(p):
        return bhar_vs_index(p, index_map, calendar, date_idx, HOLD_DAYS)

    # 多档阈值 + Bonferroni
    n_bonf = len(THRESHOLDS) * 2  # 3 thresholds × 2 subsets (decrease vs all)
    print(f"Bonferroni ×{n_bonf}（{len(THRESHOLDS)} 阈值×2）")

    for thr in THRESHOLDS:
        picks = build_picks(holder, kline_map, calendar, thr, HOLD_DAYS)
        print(f"\n{'=' * 60}")
        print(f"阈值 change_ratio<{thr}%: n_picks={len(picks)}")
        print(f"{'=' * 60}")
        if not picks:
            print("  无 picks")
            continue

        # raw_ev
        raw_rets = [raw_ev(p) for p in picks]
        raw_s = ev_stats(raw_rets)
        by_date = defaultdict(list)
        for p in picks:
            by_date[p["notice_date"]].append(raw_ev(p))
        raw_dt = day_paired_t(by_date)

        # BHAR vs index
        bhar_rets = [bhar_fn(p) for p in picks]
        bhar_rets = [r for r in bhar_rets if r is not None]
        bhar_s = ev_stats(bhar_rets) if bhar_rets else None
        bhar_by_date = defaultdict(list)
        for p in picks:
            r = bhar_fn(p)
            if r is not None:
                bhar_by_date[p["notice_date"]].append(r)
        bhar_dt = day_paired_t(bhar_by_date) if bhar_by_date else None

        print(
            f"\n  raw_ev: gross={raw_s['ev']:+.4f}% net={raw_s['ev'] - COST:+.4f}% "
            f"WR={raw_s['wr']}% day_t={raw_dt['t']} p={raw_dt['p_one_sided']} "
            f"n_days={raw_dt['n_days']}"
        )
        if bhar_s:
            print(
                f"  BHAR(vs沪深300): gross={bhar_s['ev']:+.4f}% net={bhar_s['ev'] - COST:+.4f}% "
                f"day_t={bhar_dt['t']} p={bhar_dt['p_one_sided']}"
            )
        print(f"  beta 漂移 = raw - BHAR = {raw_s['ev'] - bhar_s['ev'] if bhar_s else 0:+.4f}%")

        # walk-forward
        wf = walk_forward(picks, raw_ev, calendar)

        # verdict (用 raw_ev 主口径, BHAR 辅助)
        v = verdict_for_holder(
            ev_gross=raw_s["ev"],
            t_day=raw_dt["t"],
            p_raw=raw_dt["p_one_sided"],
            wf=wf,
            n_days=raw_dt["n_days"],
            net_ev=raw_s["ev"] - COST,
            label=f"change_ratio<{thr}% (raw_ev)",
            n_bonf=n_bonf,
        )

        # flaw 检查
        print(f"\n  --- flaw 检查 ---")
        # flaw 5: 拥挤倒U（时段衰减）
        if wf["status"] == "ok":
            tr_ev = wf["train_ev"]["ev"]
            te_ev = wf["test_ev"]["ev"]
            if tr_ev != 0:
                decay = (tr_ev - te_ev) / abs(tr_ev) * 100
                print(f"  flaw5 拥挤倒U: train={tr_ev}% test={te_ev}% decay={decay:.0f}%")
        # flaw 9: phantom alpha（BHAR vs raw_ev 差）
        if bhar_s:
            phantom = bhar_s["ev"] - raw_s["ev"]
            print(f"  flaw9 phantom: BHAR-raw={phantom:+.4f}% ({'BHAR>raw=可能虚增' if phantom > 0.1 else 'BHAR<=raw=保守'})")
        # flaw 1: 一字涨停跳过数
        # flaw 2: survivorship (kline 仅有近期=已知)
        print(f"  flaw2 survivorship: kline 仅近期 → 测的是存活股（已知偏差）")
        # flaw 7: timing (BHAR 同窗口 ✓)
        print(f"  flaw7 timing: BHAR 用同 T+1→T+{HOLD_DAYS} 窗口 ✓")


if __name__ == "__main__":
    main()
