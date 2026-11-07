# -*- coding: utf-8 -*-
"""LHB inst_dominant 8 年 + -3% stop EV（验证可交易性）。

`_audit_lhb_inst_nextday.py` 发现 inst_dominant 8 年 mean +0.336% day_t=3.29 p=0.001 PASS（无 stop）。
但 grilling 1 年发现 stop -0.286% 无显著性。本脚本算 8 年 + -3% stop EV。

stop 逻辑（简化，R6 realistic fill 待完整 intraday）：
  T+1 open 买入，T+1 close 跌破 -3% 按 T+1 close stop，否则 T+2 close 卖。
"""

import json
import sqlite3
import random
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"

INST_KEYWORDS = (
    "机构专用",
    "总部",
    "高盛",
    "瑞银",
    "股通",
    "摩根",
    "中信证券股份有限公司上海分公司",
    "国际金融",
)
STOP_PCT = -3.0  # -3% stop
ALPHA = 0.05


def load_picks_by_layer() -> dict:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy, net FROM dragon_tiger_rows WHERE side='buy' AND buy > 0"
    ).fetchall()
    conn.close()
    picks: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks[(date, code)].append((dept or "", buy or 0, net or 0))
    layers: dict = {"inst_dominant": [], "lhb_mixed": [], "inst_selling": []}
    for (date, code), seats in picks.items():
        total_buy = sum(s[1] for s in seats)
        if total_buy <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        inst_net_pct = inst_buy / total_buy
        net_total = sum(s[2] for s in seats)
        if inst_net_pct > 0.5:
            layers["inst_dominant"].append((date, code))
        elif net_total < 0:
            layers["inst_selling"].append((date, code))
        else:
            layers["lhb_mixed"].append((date, code))
    return layers


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


def compute_stop_return(code: str, trade_date: str, kline_cache: dict) -> tuple:
    """T+1 open 买入，-3% stop（T+1 close 跌破触发 → T+2 open 成交）。

    诚实口径修正（2026-10-07，工程底线 #1）：
    原逻辑 T+1 close 跌破按 T+1 close stop——违反 A 股 T+1（买入当天不能卖）。
    改为 T+1 close 跌破 -3% 触发信号 → T+2 open 成交（gap-through 自动：
    跳空穿仓按 T+2 open 更差，反弹也按 T+2 open——信号次日开盘执行）。
    未触发则 T+2 close 卖。

    返回 (return%, status)。status: stop_t2_open / hold / hold_t1_only / None。
    """
    if code not in kline_cache:
        kline_cache[code] = load_kline(code)
    bars = kline_cache[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 2:
        return None, None
    t1 = after[0]
    t2 = after[1]
    t1_open = t1.get("open")
    t1_close = t1.get("close")
    t2_open = t2.get("open")
    t2_close = t2.get("close")
    if not t1_open or t1_open <= 0:
        return None, None
    # T+1 收盘收益（判断是否触发止损信号）
    t1_ret = (t1_close / t1_open - 1) * 100 if t1_close else None
    # stop: T+1 close 跌破 -3% 触发 → T+2 open 成交（A 股 T+1 当天不能卖，次日开盘执行）
    if t1_ret is not None and t1_ret <= STOP_PCT:
        if not t2_open or t2_open <= 0:
            return None, None  # 无 T+2 数据
        # gap-through 自动：t2_open <= stop_price（跳空）则按 t2_open 更差；反弹也按 t2_open（信号次日开盘卖）
        stop_ret = (t2_open / t1_open - 1) * 100
        return stop_ret, "stop_t2_open"
    # 未触发 → T+2 close 卖
    if not t2_close:
        return t1_ret, "hold_t1_only"
    t2_ret = (t2_close / t1_open - 1) * 100
    return t2_ret, "hold"


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2**0.5))))


def audit_stop(sample_n: int = 5000) -> None:
    layers = load_picks_by_layer()
    random.seed(42)
    kline_cache: dict = {}
    print(f"=== LHB inst_dominant 8 年 + -3% stop EV ===")
    print(f"stop 逻辑: T+1 open 买入, T+1 close 跌破-3% 触发→T+2 open 成交(A 股 T+1 当天不能卖), 否则 T+2 close 卖\n")

    for layer_name, picks in layers.items():
        n = min(sample_n, len(picks))
        sampled = random.sample(picks, n) if n < len(picks) else picks
        returns_by_date: dict = defaultdict(list)
        all_returns: list = []
        stop_count = 0
        for date, code in sampled:
            r, status = compute_stop_return(code, date, kline_cache)
            if r is not None:
                returns_by_date[date].append(r)
                all_returns.append(r)
                if status == "stop_t2_open":
                    stop_count += 1
        day_means = [statistics.mean(rs) for rs in returns_by_date.values() if rs]
        if len(day_means) < 2:
            print(f"  {layer_name}: 数据不足")
            continue
        mean = statistics.mean(day_means)
        n_days = len(day_means)
        se = statistics.stdev(day_means) / (n_days**0.5) if n_days > 1 else 0
        t = mean / se if se > 0 else 0
        n_picks = len(all_returns)
        wr = sum(1 for r in all_returns if r > 0) / n_picks * 100 if n_picks else 0
        sorted_r = sorted(all_returns)
        median = sorted_r[n_picks // 2] if n_picks else 0
        stop_rate = stop_count / n_picks * 100 if n_picks else 0
        p = normal_p(t)
        p_bonf = min(1.0, p * 3)
        verdict = "PASS" if p_bonf < ALPHA else "FAIL"
        print(
            f"  {layer_name}: n={n_picks} days={n_days} mean={mean:.3f}% median={median:.3f}% "
            f"WR={wr:.1f}% stop_rate={stop_rate:.1f}% day_t={t:.2f} "
            f"p={p:.4f} Bonf×3={p_bonf:.4f} {verdict}"
        )

    # 对比无 stop
    print(f"\n  对比（无 stop vs -3% stop）:")
    print(f"    inst_dominant 无 stop: mean=+0.336% day_t=3.29 p=0.001 PASS（_nextday.py）")
    print(f"    inst_dominant -3% stop: 见上（验证 grilling 1 年 stop -0.286% 是否 8 年转正）")


if __name__ == "__main__":
    audit_stop(sample_n=5000)
