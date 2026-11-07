# -*- coding: utf-8 -*-
"""A组 T+10 combo cache 污染审计——验 +0.989% 是否同 inst_dominant 同款假。

inst_dominant 已证：kline cache 56% 残缺 → 53% picks 信号日不在 cache →
`after=[date>signal]` 买在 cache 起始（信号后数月）→ correct-period 零 edge，
wrong-period 贡献全部假 edge。本脚本对 A组T+10（S237 +0.989%）跑同款拆分。

A组口径（S237）：涨幅 -3~+10% + 净买<0.5亿(5e7) + 净买>0 → T+2 open 买 → T+10 close 卖 nostop。
关联：S237 / memory a-group-t10-walkforward-oos-edge-confirmed（若污染则 stale）
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from math import erf, sqrt
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"
COST = 0.3  # 双边滑点


def load_a_group_picks() -> list:
    """A组 picks（涨幅-3~+10% + 净买<0.5亿 + 净买>0）。返 [(date, code)]。"""
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy, net, change_rate, close_price "
        "FROM dragon_tiger_rows WHERE side='buy' AND buy>0"
    ).fetchall()
    conn.close()
    by_dc: dict = defaultdict(list)
    for d, c, dept, buy, net, chg, cp in rows:
        by_dc[(d, c)].append((dept or "", buy or 0, net or 0, chg, cp))
    picks: list = []
    for (d, c), seats in by_dc.items():
        chg = seats[0][3]
        total_net = sum(s[2] for s in seats)
        if chg is None or not (-3 <= chg <= 10):
            continue
        if not (0 < total_net < 5e7):  # 净买>0 且 <0.5亿
            continue
        picks.append((d, c))
    return picks


def load_kline(code: str) -> list:
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        return sorted(json.loads(row[0]), key=lambda b: b.get("date", ""))
    except Exception:
        return []


def compute_t2_t10_return(code: str, trade_date: str, kc: dict) -> float | None:
    """A组口径：T+2 open 买 → T+10 close 卖（after[1].open → after[9].close）。"""
    bars = kc.get(code)
    if bars is None:
        bars = load_kline(code)
        kc[code] = bars
    if not bars:
        return None
    after = [b for b in bars if b.get("date", "") > trade_date]  # after[0]=T+1
    if len(after) < 10:  # 须有 after[1]..after[9]
        return None
    buy_open = float(after[1].get("open", 0))  # T+2 open
    sell_close = float(after[9].get("close", 0))  # T+10 close
    if buy_open <= 0 or sell_close <= 0:
        return None
    return (sell_close - buy_open) / buy_open * 100 - COST


def classify_and_stats(picks: list) -> None:
    kc: dict = {}
    correct, wrong = [], []
    for d, c in picks:
        bars = kc.get(c) or load_kline(c)
        kc[c] = bars
        if not bars:
            continue
        first_date = bars[0].get("date", "")
        (wrong if first_date > d else correct).append((d, c))

    def stats(label: str, group: list) -> None:
        rets = [r for r in (compute_t2_t10_return(c, d, kc) for d, c in group) if r is not None]
        if not rets:
            print(f"  {label}: 无收益数据")
            return
        n = len(rets)
        mean = sum(rets) / n
        wr = sum(1 for r in rets if r > 0) / n * 100
        med = statistics.median(rets)
        std = statistics.pstdev(rets) if n > 1 else 0
        se = std / sqrt(n) if n else 0
        t = mean / se if se > 0 else 0
        p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
        sig = "✅" if p < 0.05 else "❌"
        print(f"  {label} (n_picks={len(group)}, n_ret={n}): mean {mean:+.3f}% WR {wr:.1f}% "
              f"median {med:+.3f} p={p:.4f}{sig}")

    print(f"A组 T+10 picks 总 {len(picks)} → correct {len(correct)} ({len(correct)/len(picks)*100:.1f}%) / "
          f"wrong {len(wrong)} ({len(wrong)/len(picks)*100:.1f}%)")
    print()
    stats("correct-period", correct)
    stats("wrong-period  ", wrong)
    stats("ALL (污染)    ", picks)


def main() -> None:
    picks = load_a_group_picks()
    if not picks:
        print("无 A组 picks（dragon_tiger_history.db 缺/空）")
        return
    print(f"=== A组 T+10 (S237) cache 污染审计 ===")
    print(f"口径：涨幅-3~+10% + 净买<0.5亿 + 净买>0 → T+2 open → T+10 close nostop (扣{COST}%成本)\n")
    classify_and_stats(picks)


if __name__ == "__main__":
    main()
