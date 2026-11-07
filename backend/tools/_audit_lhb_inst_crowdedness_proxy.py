# -*- coding: utf-8 -*-
"""拥挤度≥5%则负 claim 验证（用户"专家"意见，未验证）。

用户称"8年金工实证：机构买入额/自由流通盘 >= 5%，次日期望收益率由正转负"。
但项目无 free_float 历史批量数据（em_get 会封 IP，25327 picks 太多）。
用 proxy：inst_buy / 20d_avg_amt（机构买入额 / 20日均成交额）。
proxy 阈值≠free_float 5%，但可看 >5% proxy 组是否显著更差（claim 方向验证）。
"""

import json
import sqlite3
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
INST_KEYWORDS = ("机构专用", "总部", "高盛", "瑞银", "股通", "摩根", "中信证券股份有限公司上海分公司", "国际金融")
STOP_PCT = -3.0


def load_inst_dominant_picks() -> list:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT trade_date, security_code, dept_name, buy, net FROM dragon_tiger_rows WHERE side='buy' AND buy > 0"
    ).fetchall()
    conn.close()
    picks_by_dc: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks_by_dc[(date, code)].append((dept or "", buy or 0, net or 0))
    inst: list = []
    for (date, code), seats in picks_by_dc.items():
        total = sum(s[1] for s in seats)
        if total <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        if inst_buy / total > 0.5:
            inst.append((date, code, inst_buy, total))
    return inst


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


_KLINE_CACHE: dict = {}


def get_20d_avg_amt(code: str, trade_date: str) -> float | None:
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    before = [b for b in bars if b.get("date", "") <= trade_date][-20:]
    if len(before) < 10:
        return None
    return sum(b.get("amount", 0) or 0 for b in before) / len(before)


def compute_stop_intraday(code: str, trade_date: str) -> float | None:
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 2:
        return None
    t1 = after[0]
    t2 = after[1]
    t1_open = t1.get("open")
    t1_low = t1.get("low")
    t2_close = t2.get("close")
    if not t1_open or t1_open <= 0:
        return None
    stop_price = t1_open * (1 + STOP_PCT / 100)
    if t1_low is not None and t1_low <= stop_price:
        return (stop_price / t1_open - 1) * 100
    if not t2_close:
        return None
    return (t2_close / t1_open - 1) * 100


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2**0.5))))


def stats(rets: list) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": 0.0, "t": 0.0, "p": 1.0, "wr": 0.0}
    mean = sum(rets) / n
    std = statistics.pstdev(rets) if n > 1 else 0.0
    se = std / (n**0.5) if n > 0 else 0.0
    t = mean / se if se > 0 else 0.0
    p = normal_p(t)
    wr = sum(1 for r in rets if r > 0) / n * 100
    return {"n": n, "mean": mean, "t": t, "p": p, "wr": wr}


def audit_crowdedness() -> None:
    picks = load_inst_dominant_picks()
    print(f"=== 拥挤度≥5%则负 claim 验证（proxy: inst_buy/20d_amt）===")
    print(f"inst_dominant picks: {len(picks)}\n")

    high = []  # proxy >= 5%
    low = []  # proxy < 5%
    for date, code, inst_buy, total_buy in picks:
        amt = get_20d_avg_amt(code, date)
        if not amt:
            continue
        crowdedness = inst_buy / amt * 100  # proxy %
        bhar = compute_stop_intraday(code, date)
        if bhar is None:
            continue
        if crowdedness >= 5:
            high.append(bhar)
        else:
            low.append(bhar)

    high_s = stats(high)
    low_s = stats(low)
    print(
        f"  proxy>=5% (机构买/20d成交额): n={high_s['n']} mean={high_s['mean']:.3f}% WR={high_s['wr']:.1f}% t={high_s['t']:.2f} p={high_s['p']:.4f}"
    )
    print(
        f"  proxy<5%:                    n={low_s['n']} mean={low_s['mean']:.3f}% WR={low_s['wr']:.1f}% t={low_s['t']:.2f} p={low_s['p']:.4f}"
    )
    print(f"\n  → {'claim 方向成立（>=5% 组 mean 更低）' if high_s['mean'] < low_s['mean'] else 'claim 方向证否（>=5% 组未更差）'}")
    print(f"  注：proxy=inst_buy/20d_amt 非用户 claim 的 free_float 阈值，proxy 5% 阈值须校准")
    print(f"  但如果 >5% 组显著更差，claim 方向成立（机构买占比高 → 次日差）")


if __name__ == "__main__":
    audit_crowdedness()
