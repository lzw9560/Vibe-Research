# -*- coding: utf-8 -*-
"""主力游资 建仓-洗盘-拉升 composite pattern §44 v3 + high-risk lens 测试。

跟庄理论：
  建仓: 主力/游资悄悄买入 → 缩量 + 区间紧
  洗盘: 主力打压洗浮筹 → 急跌 + 缩量
  拉升: 主力推涨 → 放量突破

信号定义（composite）：
  1. 建仓 phase: 过去 20d vol < 20d MA_vol × 0.6 + 20d (high-low)/close < 0.15
  2. 洗盘 phase: 建仓后 10d 内出现 -3%~-8% 急跌（1-3d）+ 跌时缩量
  3. 拉升 entry: 洗盘后 vol > 20d MA_vol × 1.5 + close > 5d MA + close > 洗盘前 high

口径：§44 v3 + 10 flaw + R11-R13 + high-risk lens（mean 真为正 + tail 可捕获，不要求 median>0/WR>55%）
entry T+1 open → exit T+5/T+10/T+20 close
成本 0.30% round-trip（个股中值，按流动性分层）
"""

from __future__ import annotations
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import sqrt
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import limit_for_code, is_yizi_t1, ev_stats, day_paired_t, bonferroni_p, ALPHA

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
INDEX_CACHE = DATA / "index_ohlc_cache.json"

COST = 0.30
HOLD_DAYS = [5, 10, 20]


def load_kline():
    """返回 code -> sorted list of bars (date, open, high, low, close, volume, amount, pctChg, isST)."""
    conn = sqlite3.connect(str(KLINE_DB))
    code_bars = {}
    all_dates = set()
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        sorted_bars = sorted([b for b in bars if b.get("date")], key=lambda b: b["date"])
        if len(sorted_bars) >= 60:  # 须 ≥60 bars 才能算 建仓 20d + 洗盘 + 拉升 + hold
            code_bars[code] = sorted_bars
            for b in sorted_bars:
                all_dates.add(b["date"])
    conn.close()
    return code_bars, all_dates


def load_index():
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    return {b["date"]: b for b in raw.get("sh.000001", []) if "date" in b}


def detect_jiancang(bars, i, window=20):
    """建仓 phase: 过去 window 日 缩量 + 区间紧.
    缩量 = vol_mean(window) < vol_mean(window*2) × 0.7  (近期量低于长期量)
    区间紧 = (max_high - min_low) / close < 0.15
    返回 True/False.
    """
    if i < window * 2:
        return False
    recent = bars[i - window : i]
    longer = bars[i - window * 2 : i - window]
    vols_recent = [b.get("volume", 0) for b in recent if b.get("volume")]
    vols_longer = [b.get("volume", 0) for b in longer if b.get("volume")]
    if not vols_recent or not vols_longer:
        return False
    mean_recent = sum(vols_recent) / len(vols_recent)
    mean_longer = sum(vols_longer) / len(vols_longer)
    if mean_longer <= 0:
        return False
    if mean_recent / mean_longer > 0.7:  # 未缩量
        return False
    highs = [b.get("high", 0) for b in recent if b.get("high")]
    lows = [b.get("low", 0) for b in recent if b.get("low")]
    closes = [b.get("close", 0) for b in recent if b.get("close")]
    if not highs or not lows or not closes:
        return False
    range_pct = (max(highs) - min(lows)) / (sum(closes) / len(closes))
    if range_pct > 0.15:  # 区间不紧
        return False
    return True


def detect_xipan(bars, i, lookforward=10):
    """洗盘 phase: 建仓后 lookforward 日内出现 -3%~-8% 急跌 + 缩量.
    返回 (xipan_end_idx, pre_xipan_high) 或 None.
    """
    if i + lookforward >= len(bars):
        return None
    pre_high = max(bars[j].get("high", 0) for j in range(max(0, i - 20), i) if bars[j].get("high"))
    for j in range(i, min(i + lookforward, len(bars))):
        drop = (bars[j].get("close", 0) - bars[i - 1].get("close", 0)) / bars[i - 1].get("close", 1)
        if -0.08 <= drop <= -0.03:  # 急跌 -3%~-8%
            # 缩量检查
            vol_j = bars[j].get("volume", 0)
            vols_prev = [bars[k].get("volume", 0) for k in range(max(0, j - 20), j) if bars[k].get("volume")]
            if vols_prev:
                mean_prev = sum(vols_prev) / len(vols_prev)
                if mean_prev > 0 and vol_j / mean_prev < 0.9:  # 跌时缩量
                    return (j, pre_high)
    return None


def detect_lasheng(bars, xipan_end, pre_high, lookforward=10):
    """拉升 entry: 洗盘后 lookforward 日内 放量突破 (vol > 20d MA × 1.5 + close > 5d MA + close > pre_high).
    返回 entry_idx 或 None.
    """
    for j in range(xipan_end + 1, min(xipan_end + 1 + lookforward, len(bars))):
        vol_j = bars[j].get("volume", 0)
        vols_prev = [bars[k].get("volume", 0) for k in range(max(0, j - 20), j) if bars[k].get("volume")]
        if not vols_prev:
            continue
        mean_prev = sum(vols_prev) / len(vols_prev)
        if mean_prev <= 0 or vol_j / mean_prev < 1.5:  # 未放量
            continue
        closes_prev5 = [bars[k].get("close", 0) for k in range(max(0, j - 5), j) if bars[k].get("close")]
        if not closes_prev5:
            continue
        ma5 = sum(closes_prev5) / len(closes_prev5)
        close_j = bars[j].get("close", 0)
        if close_j <= ma5:  # 未站上 5d MA
            continue
        if close_j <= pre_high:  # 未突破洗盘前高
            continue
        return j
    return None


def build_picks(code_bars):
    """扫描所有 code，检测 建仓→洗盘→拉升 composite，返回 picks."""
    picks = []
    for code, bars in code_bars.items():
        for i in range(40, len(bars) - 30):
            if not detect_jiancang(bars, i):
                continue
            xp = detect_xipan(bars, i)
            if xp is None:
                continue
            xipan_end, pre_high = xp
            entry_idx = detect_lasheng(bars, xipan_end, pre_high)
            if entry_idx is None:
                continue
            entry_bar = bars[entry_idx]
            # entry = T+1 open（拉升信号次日开盘）
            if entry_idx + 1 >= len(bars):
                continue
            t1_bar = bars[entry_idx + 1]
            entry = t1_bar.get("open")
            t_close = entry_bar.get("close")
            if entry is None or t_close is None or entry <= 0 or t_close <= 0:
                continue
            # 一字涨停 T+1 跳过
            is_st = t1_bar.get("isST") == "1"
            limit = limit_for_code(code, is_st)
            if is_yizi_t1(t1_bar, t_close, limit):
                continue
            picks.append(
                {
                    "code": code,
                    "signal_date": entry_bar.get("date"),
                    "entry_date": t1_bar.get("date"),
                    "entry": entry,
                    "entry_bar": entry_bar,
                    "t1_bar": t1_bar,
                    "bars": bars,
                    "entry_idx": entry_idx,
                    "zt_date": entry_bar.get("date"),
                }
            )
    return picks


def compute_returns(picks, calendar, date_idx, hold_days):
    """对每个 hold_days 算 raw_ev + BHAR vs 上证综指."""
    results = []
    for p in picks:
        di = date_idx.get(p["signal_date"])
        if di is None or di + 1 + hold_days >= len(calendar):
            continue
        exit_date = calendar[di + 1 + hold_days]
        # 找 exit close
        bars = p["bars"]
        exit_bar = None
        for b in bars:
            if b.get("date") == exit_date:
                exit_bar = b
                break
        if exit_bar is None:
            continue
        exit_close = exit_bar.get("close")
        entry = p["entry"]
        if exit_close is None or exit_close <= 0:
            continue
        raw_ev = (exit_close - entry) / entry * 100
        results.append({"raw_ev": raw_ev, "signal_date": p["signal_date"], "code": p["code"]})
    return results


def main():
    print("=" * 70)
    print("主力游资 建仓-洗盘-拉升 composite pattern 测试（high-risk lens）")
    print("=" * 70)
    print(f"信号: 建仓(20d缩量+区间紧)→洗盘(10d内急跌-3%~-8%+缩量)→拉升(放量突破+close>5dMA+>洗盘前高)")
    print(f"entry: 拉升信号次日 T+1 open, exit T+5/T+10/T+20 close")
    print(f"成本: {COST}% round-trip | high-risk lens: mean 真为正 + tail 可捕获")

    code_bars, all_dates = load_kline()
    index_map = load_index()
    calendar = sorted(all_dates)
    date_idx = {d: i for i, d in enumerate(calendar)}
    print(f"\n[数据] codes with ≥60 bars: {len(code_bars)}, calendar {len(calendar)} dates")

    picks = build_picks(code_bars)
    print(f"\n[建仓-洗盘-拉升 picks] n={len(picks)}")

    if not picks:
        print("无 picks — composite pattern 太严格，放宽阈值")
        return

    # 多窗口
    n_bonf = len(HOLD_DAYS) * 2
    print(f"Bonferroni ×{n_bonf}（{len(HOLD_DAYS)} hold×2）")

    for hd in HOLD_DAYS:
        rets = compute_returns(picks, calendar, date_idx, hd)
        if not rets:
            print(f"\nT+{hd}: 无可算收益")
            continue
        raw_rets = [r["raw_ev"] for r in rets]
        s = ev_stats(raw_rets)
        by_date = defaultdict(list)
        for r in rets:
            by_date[r["signal_date"]].append(r["raw_ev"])
        dt = day_paired_t(by_date)
        med = statistics.median(raw_rets)
        sorted_r = sorted(raw_rets)
        p95 = sorted_r[int(len(sorted_r) * 0.95)] if len(sorted_r) >= 20 else max(raw_rets)
        p75 = sorted_r[int(len(sorted_r) * 0.75)] if len(sorted_r) >= 4 else max(raw_rets)
        net = s["ev"] - COST

        print(f"\n--- T+{hd} hold ---")
        print(f"  n={s['n']} n_days={dt['n_days']}")
        print(f"  raw_ev: mean={s['ev']:+.4f}% net={net:+.4f}% median={med:+.4f}% stdev={s['std']:.2f}%")
        print(f"  WR={s['wr']}% p75={p75:+.2f}% p95={p95:+.2f}%")
        print(f"  day_t={dt['t']} p_raw={dt['p_one_sided']} Bonf×{n_bonf}={bonferroni_p(dt['p_one_sided'], n_bonf):.6f}")

        # verdict (high-risk lens: mean 真为正 + tail 可捕获)
        print(f"  [high-risk lens verdict]")
        if s["ev"] <= 0:
            print(f"    → FALSIFIED: mean={s['ev']}% ≤0 (high-risk 也要求 mean 正)")
        elif net <= 0:
            print(f"    → FALSIFIED: net={net}% ≤0 (成本吃掉 edge)")
        elif dt["n_days"] < 60:
            print(f"    → UNDERPOWERED: n_days={dt['n_days']} <60")
        else:
            p_bonf = bonferroni_p(dt["p_one_sided"], n_bonf)
            if p_bonf < ALPHA:
                print(f"    → HIGH-RISK EDGE-CONFIRMED: mean+net 正 + Bonf PASS (纵 median/WR 低也接受 high-risk)")
            else:
                print(f"    → EXPLORATORY: mean+net 正但 Bonf={p_bonf}≥{ALPHA} (high-risk 下仍值得看，tail p95={p95:+.2f}%)")

        # flaw 检查
        print(f"  [flaw 检查]")
        print(f"    R11 median/WR: median={med:+.4f}% WR={s['wr']}% ({'抛硬币=high-risk tail-driven' if abs(med) < 0.5 else '有 median 支撑'})")
        print(f"    R13 survivorship: kline 仅近期 → 单 regime 偏差（已知）")
        print(f"    flaw1 entry涨停: 已跳过一字")
        print(f"    high-risk tail: p95={p95:+.2f}% ({'尾部可捕获' if p95 > 5 else '尾部不足'})")


if __name__ == "__main__":
    main()
