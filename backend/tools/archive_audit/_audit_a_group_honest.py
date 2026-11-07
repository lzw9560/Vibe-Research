# -*- coding: utf-8 -*-
"""A组跟庄 8 步 honest-test（backfill unlock ①，253→2123 天）。

A组 panel 结论：playbook 59%+5.3% 不 sound（5 缺陷），但 A组排除封死涨停=未直接测过切片，
§1.2 verdict 外推禁令禁止预判。本脚本跑 8 步定 A组生死。

A组条件（playbook）：涨幅-3%~+10% + 净买<0.5亿 + 净买>0 + 热度>100（热度无字段 blocked）
本脚本跑 ① 扩 253→2123 天 + 基础 EV（T+2 open→T+3 close，playbook T+2 跟进口径）。
完整 8 步（R12/R13/R5/walk-forward/Bonf/R6/R11）后续。
"""
import json
import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"
ALPHA = 0.05


def load_a_group_picks() -> list:
    """A组条件：涨幅-3%~+10% + 净买<0.5亿 + 净买>0（dragon_tiger_history）。

    dragon_tiger_rows 有 change_rate（涨幅）+ net（净买，元）。
    净买<0.5亿 = net < 5e7（元）。
    热度>100 无字段（blocked，标 TODO）。
    """
    conn = sqlite3.connect(str(DT_DB))
    # 每个 (date, code) 算总净买 + 涨幅（取该 code 当日 change_rate）
    rows = conn.execute("""
        SELECT trade_date, security_code, SUM(net) as total_net, MAX(change_rate) as chg
        FROM dragon_tiger_rows
        WHERE side='buy' AND net IS NOT NULL
        GROUP BY trade_date, security_code
    """).fetchall()
    conn.close()

    picks = []
    for date, code, total_net, chg in rows:
        if total_net is None or chg is None:
            continue
        # A组条件：涨幅 -3%~+10% + 净买>0 + 净买<0.5亿（5e7 元）
        if not (-3 <= chg <= 10):
            continue
        if total_net <= 0:
            continue
        if total_net > 5e7:
            continue
        picks.append((date, code, total_net, chg))
    return sorted(picks)


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


def compute_t2_return(code: str, trade_date: str) -> float | None:
    """T+2 open→T+3 close（playbook T+2 跟进口径，T+2 买 T+3 卖）。"""
    if code not in _KLINE_CACHE:
        _KLINE_CACHE[code] = load_kline(code)
    bars = _KLINE_CACHE[code]
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 3:
        return None
    t2_open = after[1].get("open")  # T+2 open（买）
    t3_close = after[2].get("close")  # T+3 close（卖）
    if not t2_open or t2_open <= 0 or not t3_close:
        return None
    return (t3_close / t2_open - 1) * 100


def normal_p(t: float) -> float:
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def audit_a_group() -> None:
    picks = load_a_group_picks()
    print(f"=== A组 8 步 honest-test ① 扩 253→2123 天 + 基础 EV ===")
    print(f"A组条件: 涨幅-3%~+10% + 净买<0.5亿 + 净买>0 (热度>100 blocked)")
    print(f"A组 picks: {len(picks)}\n")

    rbd: dict = defaultdict(list)
    ar: list = []
    for date, code, net, chg in picks:
        r = compute_t2_return(code, date)
        if r is not None:
            rbd[date].append(r)
            ar.append(r)

    if not ar:
        print("无收益数据")
        return

    day_means = [statistics.mean(rs) for rs in rbd.values() if rs]
    mean = statistics.mean(day_means)
    n_days = len(day_means)
    se = statistics.stdev(day_means) / (n_days ** 0.5) if n_days > 1 else 0
    t = mean / se if se > 0 else 0
    n = len(ar)
    wr = sum(1 for r in ar if r > 0) / n * 100 if n else 0
    sr = sorted(ar)
    median = sr[n // 2] if n else 0
    p = normal_p(t)
    print(f"基础 EV (T+2open→T+3close, 无 stop):")
    print(f"  n={n} days={n_days} mean={mean:.3f}% median={median:.3f}% WR={wr:.1f}% day_t={t:.2f} p={p:.4f}")
    print(f"\n注：完整 8 步待补：②R12 size-matched ③R13 survivorship ④R5多窗口 ⑤walk-forward ⑥Bonferroni ⑦R6 stop ⑧R11 median")
    print(f"playbook 称 59%+5.3%——本脚本诚实口径 T+2open→T+3close 无 stop 基础 EV 对比")


if __name__ == "__main__":
    audit_a_group()
