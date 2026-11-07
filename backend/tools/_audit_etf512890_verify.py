# -*- coding: utf-8 -*-
"""核实红利低波 512890 ETF beta（工程底线 #2，2026-10-07）。

memory VERDICTS['红利低波_512890'] = '✅ 唯一诚实可落地 7-11% beta'——7-11% 数字来源不明，
fork 审查发现 ETF 从未回测（baostock rows=0）。本脚本用 hithink fund history 拉数据核实。

512890 上市于 2021（pre 2018 段无数据），5 年（2021-2026）是全部上市历史。
"""

from __future__ import annotations
import json
import subprocess
from datetime import datetime

THSCODE = "512890.SH"
START_MS = 1633536000000  # 2021-10-07
END_MS = 1791302400000  # 2026-10-07


def pull_history() -> list:
    out = "/tmp/etf512890_verify.json"
    cmd = [
        "hithink-finance",
        "fund",
        "history",
        "--thscode",
        THSCODE,
        "--start-ms",
        str(START_MS),
        "--end-ms",
        str(END_MS),
        "--output",
        out,
        "--format",
        "json",
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)
    d = json.load(open(out))
    return d.get("data", {}).get("item", [])


def compute(items: list) -> dict | None:
    bars = [(it.get("date_ms"), float(it.get("close_price", 0))) for it in items if it.get("close_price")]
    bars = [(ms, c) for ms, c in bars if c > 0]
    if len(bars) < 10:
        return None
    rets = [(bars[i][1] / bars[i - 1][1] - 1) for i in range(1, len(bars))]
    n = len(rets)
    years = n / 252
    total = bars[-1][1] / bars[0][1]
    ann = total ** (1 / years) - 1
    mean_r = sum(rets) / n
    std_r = (sum((r - mean_r) ** 2 for r in rets) / n) ** 0.5
    vol = std_r * (252**0.5)
    sharpe = mean_r * 252 / vol if vol > 0 else 0
    peak = bars[0][1]
    mdd = 0.0
    for _, c in bars:
        if c > peak:
            peak = c
        dd = (c - peak) / peak
        if dd < mdd:
            mdd = dd
    return {
        "n": n,
        "years": years,
        "total": total - 1,
        "ann": ann,
        "vol": vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "first_close": bars[0][1],
        "last_close": bars[-1][1],
    }


def main() -> None:
    items = pull_history()
    print(f"=== 红利低波 512890 ETF 核实（工程底线 #2）===")
    print(f"thscode: {THSCODE}, 拉到 {len(items)} bars")
    s = compute(items)
    if not s:
        print("数据不足")
        return
    print(f"区间: {s['years']:.2f} 年, {s['n']} 交易日")
    print(f"总收益: {s['total']:+.2%} ({s['first_close']:.3f}→{s['last_close']:.3f})")
    print(f"年化收益(价格): {s['ann']:+.2%}")
    print(f"年化波动: {s['vol']:.2%}, Sharpe(rf=0): {s['sharpe']:.2f}")
    print(f"max drawdown: {s['mdd']:.2%}")
    in_range = 0.07 <= s["ann"] <= 0.11
    print(f"\nmemory 7-11% beta 核实: {'✅ PASS' if in_range else '❌ FAIL'} (实际 {s['ann']:+.2%}, 价格不含分红)")
    print(f"加分红 ~1-2% → 总收益 ~{s['ann'] + 0.015:.1%}")


if __name__ == "__main__":
    main()
