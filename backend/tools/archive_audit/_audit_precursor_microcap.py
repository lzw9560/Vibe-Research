# -*- coding: utf-8 -*-
"""前兆预测 - 微盘小容量子集测试（2026-10-20）。

broad 前兆（+5~7%+量比2）lift 2.4x 但 mean -0.186%（能预测涨停概率但亏钱）。
假设：微盘小容量子集（大基金进不去）前兆 mean 可能转正。

微盘代理 = 按 8 年日均成交额排序，取 bottom tertile（低流动性≈小盘）+ bottom decile（最小）。
前兆 A = 今日 +5~7% + 量比≥2。对比 broad（lift 2.4x, mean -0.186%）。
关联：_audit_precursor_prediction.py（broad）/ memory edge-exhaustive-5batch
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"


def limit_pct(code: str) -> float:
    if code.startswith(("688", "300", "301")):
        return 0.198
    if code.startswith(("8", "920", "43")):
        return 0.298
    return 0.098


def main() -> None:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    # 1. 算每只 8 年日均成交额（amount），排序切微盘
    amt = {}
    parsed = {}
    for code, bj in rows:
        try:
            bars = sorted(json.loads(bj), key=lambda b: b.get("date", ""))
        except Exception:
            continue
        if len(bars) < 25:
            continue
        parsed[code] = bars
        amounts = [float(b.get("amount", 0) or 0) for b in bars]
        amt[code] = statistics.mean(amounts) if amounts else 0
    ranked = sorted(amt.items(), key=lambda x: x[1])
    n = len(ranked)
    tertile_cut = n // 3
    decile_cut = n // 10
    microcodes = {c for c, _ in ranked[:tertile_cut]}
    tinycodes = {c for c, _ in ranked[:decile_cut]}
    print(f"=== 前兆预测 微盘子集（{n} stocks）===")
    print(f"微盘(bottom tertile)={len(microcodes)} 只｜超微(bottom decile)={len(tinycodes)} 只")
    print(f"前兆 = 今日 +5~7% + 量比≥2\n")

    def run(subset, label):
        base_n = base_lim = prec_n = prec_lim = 0
        base_rets, prec_rets = [], []
        for code in subset:
            bars = parsed[code]
            vols = [float(b.get("volume", 0) or 0) for b in bars]
            lim = limit_pct(code)
            for i in range(1, len(bars) - 1):
                prev_c = float(bars[i-1].get("close",0) or 0)
                close = float(bars[i].get("close",0) or 0)
                if not prev_c or not close: continue
                pct = (close - prev_c) / prev_c
                ma20 = statistics.mean(vols[max(0,i-20):i]) if i >= 1 else 0
                vr = (vols[i]/ma20) if ma20 else 0
                nxt_c = float(bars[i+1].get("close",0) or 0)
                if not nxt_c: continue
                np_ = (nxt_c - close) / close
                nlu = np_ >= lim
                base_n += 1; base_rets.append(np_)
                if nlu: base_lim += 1
                if 0.05 <= pct <= 0.07 and vr >= 2:
                    prec_n += 1; prec_rets.append(np_)
                    if nlu: prec_lim += 1
        br = base_lim/base_n if base_n else 0
        pr = prec_lim/prec_n if prec_n else 0
        lift = pr/br if br else 0
        bm = statistics.mean(base_rets) if base_rets else 0
        pm = statistics.mean(prec_rets) if prec_rets else 0
        print(f"{label:<22} n_base={base_n:>8} 涨停率 {br*100:.3f}%  mean {bm*100:+.3f}%")
        print(f"{'':<22}   前兆 n={prec_n:>7} 涨停率 {pr*100:.3f}%  lift {lift:.2f}x  mean {pm*100:+.3f}%")
        print()

    print(f"{'前兆/子集':<22}{'n':>10}{'次日涨停率':>12}{'lift':>8}{'次日mean':>11}")
    print("-" * 63)
    run(microcodes, "微盘(bottom tertile)")
    run(tinycodes, "超微(bottom decile)")
    print("对比 broad: 前兆 lift 2.40x, mean -0.186%")
    print("读法：微盘 mean 若转正（或负得少）→ 小容量 niche 有可交易 edge；仍负 → 简单前兆在哪都亏")


if __name__ == "__main__":
    main()
