# -*- coding: utf-8 -*-
"""inst_dominant T+n 溢价收益矩阵（2026-10-08）。

算 T+1 open 买 → T+n close 卖（n=1~15）的溢价矩阵，找最优持有期。
诚实口径：无 stop（纯持有），net EV（扣 0.3% 滑点双边）。

2 庄家对抗 caveat（2026-10-08）：
- 纸面 mean 经实盘摩擦（slippage + 前置收割 + stop gap）大概率归零
- T+1 公开 LHB → 量化庄 T+0 前置，T+2 高开割
- 手动跳单进射程（连亏 5 次跳过赢家）
T+n 矩阵找最优持有期，但实盘仍受摩擦衰减。
"""
from __future__ import annotations
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf, sqrt

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"

INST_KEYWORDS = (
    "机构专用", "总部", "高盛", "瑞银", "股通", "摩根",
    "中信证券股份有限公司上海分公司", "国际金融",
)
COST = 0.3  # 双边滑点 0.3%
MAX_N = 15


def load_picks() -> list:
    """inst_dominant picks: 机构占比>50% 的 (date, code)。"""
    if not DT_DB.exists():
        print(f"⚠️ {DT_DB} 不存在（dragon_tiger backfill 未完成）")
        return []
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy, net "
        "FROM dragon_tiger_rows WHERE side='buy' AND buy > 0"
    ).fetchall()
    conn.close()
    picks: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks[(date, code)].append((dept or "", buy or 0, net or 0))
    inst_picks = []
    for (date, code), seats in picks.items():
        total_buy = sum(s[1] for s in seats)
        if total_buy <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        if inst_buy / total_buy > 0.5:
            inst_picks.append((date, code))
    return inst_picks


def load_kline(code: str) -> list:
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        bars = json.loads(row[0])
        return sorted(bars, key=lambda b: b.get("date", ""))
    except Exception:
        return []


def compute_tn_returns(code: str, trade_date: str, kline_cache: dict, max_n: int = MAX_N) -> dict:
    """T+1 open 买 → T+n close 卖（n=1~max_n），返 {n: return}。

    LHB trade_date 是上榜日（T+0 收盘后公开）。T+1 = 次日 open 买 = after[0]。
    **robust 对齐**（2026-10-18 修 off-by-one）：`after = [b for b in bars if date > trade_date]`，
    buy=after[0].open，sell=after[n].close。55% picks 的信号日 bar 不在 cache，原
    `>= trade_date`+`idx+1` 会把这些买在 T+2（峰值左移 1 天）。现与 spec
    `compute_nostop_return` 同口径（n=1 = 1 天持有 = spec +0.457% gross）。
    """
    bars = kline_cache.get(code)
    if bars is None:
        bars = load_kline(code)
        kline_cache[code] = bars
    if not bars:
        return {}
    after = [b for b in bars if b.get("date", "") > trade_date]  # robust：信号日缺也正确
    if len(after) < 2:
        return {}
    buy_open = float(after[0].get("open", 0))
    if buy_open <= 0:
        return {}
    rets = {}
    for n in range(1, max_n + 1):
        if n >= len(after):  # after[n] 须存在
            break
        sell_close = float(after[n].get("close", 0))
        if sell_close <= 0:
            continue
        ret = (sell_close - buy_open) / buy_open * 100 - COST
        rets[n] = ret
    return rets


def stats(rets: list) -> dict:
    n = len(rets)
    if n == 0:
        return {'n': 0, 'mean': 0, 'wr': 0, 'median': 0, 't': 0, 'p': 1}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0
    se = std / sqrt(n) if n else 0
    t = mean / se if se > 0 else 0
    p = 0.5 * (1 - erf(t / sqrt(2))) if t > 0 else 1.0
    return {'n': n, 'mean': mean, 'wr': sum(1 for x in rets if x > 0) / n,
            'median': statistics.median(rets), 't': t, 'p': p}


def main() -> None:
    picks = load_picks()
    if not picks:
        print("无 inst_dominant picks（dragon_tiger_history.db 缺失或空）")
        print(f"需 backfill dragon_tiger（memory engineering-baseline: agent by24f1ko7 跑中）")
        return
    print(f"=== inst_dominant T+n 溢价收益矩阵（n=1~{MAX_N}）===")
    print(f"picks: {len(picks)}  买: T+1 open  卖: T+n close  成本: {COST}% 双边\n")
    kline_cache: dict = {}
    tn_rets: dict = defaultdict(list)
    for date, code in picks:
        rets = compute_tn_returns(code, date, kline_cache)
        for n, r in rets.items():
            tn_rets[n].append(r)
    print(f"{'T+n':>4} {'net EV%':>9} {'WR%':>6} {'median':>8} {'t':>6} {'p':>9} {'n_obs':>8}")
    print("-" * 55)
    best_n = None
    best_ev = -999
    for n in range(1, MAX_N + 1):
        s = stats(tn_rets.get(n, []))
        if s['n'] == 0:
            continue
        sig = '✅' if s['p'] < 0.05 else '❌'
        print(f"T+{n:>2} {s['mean']:>8.3f} {s['wr']*100:>5.1f}% {s['median']:>8.3f} "
              f"{s['t']:>6.2f} {s['p']:>8.4f}{sig} {s['n']:>8}")
        if s['mean'] > best_ev and s['p'] < 0.05:
            best_ev = s['mean']
            best_n = n
    print(f"\n最优 T+n（最高 EV + p<0.05）: T+{best_n} net EV+{best_ev:.3f}%")
    print(f"\n⚠️ 2 庄家对抗 caveat（2026-10-08）：")
    print(f"  - 纸面 EV 经实盘摩擦（slippage + 前置收割 + stop gap）大概率归零")
    print(f"  - T+1 公开 LHB → 量化庄 T+0 前置，T+2 高开割散户")
    print(f"  - lottery WR34.7% → 连亏 5 次跳单进射程（跳过赢家）")
    print(f"  - -8% stop = 霓虹灯，被打止损 trigger")
    print(f"  矩阵显示最优持有期，但实盘仍受摩擦衰减（量化庄：0.336% 大概率归零）")


if __name__ == "__main__":
    main()
