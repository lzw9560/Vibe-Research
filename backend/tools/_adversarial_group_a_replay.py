# -*- coding: utf-8 -*-
"""A组跟庄战法对抗复现测试.

playbook A组 = LHB日 + 涨幅-3%~+10%(非涨停) + 净买为正且<0.5亿 + 热度>100 + (二层)20日位置<50%+换手10-25%
项目已测 = 涨停连板接力(zt_history lbc>=2) → falsified. 但涨停连板 = playbook B组(陷阱),
非 A组. A组(非涨停低吸建仓)是否测过? 本脚本回答.

口径:
  T = LHB建仓日(dragon_tiger_history.trade_date)
  entry = T+2 open (playbook "T+2开盘分2笔买")
  exit  = first of {close<=entry*0.85 stop, close>=entry*1.20 TP, day-15 close timeout}
  cost  = _cost_pct (项目约定 ~0.15-0.30% round-trip)
  跳过 T+2 一字涨停(open==high==close at涨停, 买不到)

未测维度: 热度>100 不在 dragon_tiger DB (hithink字段) → 测 WITHOUT 热度 filter,
  若无热度仍 ~59% 则 edge 更强; 若 <59% 则 ambiguous (或 edge 假 或 需热度).
"""
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/lizhiwei/project/code/stock/Vibe-Research")
DT_DB = ROOT / ".vibe-research" / "dragon_tiger_history.db"
KL_DB = ROOT / ".vibe-research" / "baostock_kline_cache.db"
sys.path.insert(0, str(ROOT / "backend"))
from engine.accounting import _cost_pct  # noqa: E402


def load_klinebars() -> dict:
    """code -> {date: bar} lookup (dict for O(1) date access)."""
    conn = sqlite3.connect(str(KL_DB))
    cur = conn.execute("SELECT code, bars_json FROM kline")
    out = {}
    for code, bj in cur:
        try:
            bars = json.loads(bj)
        except Exception:
            continue
        m = {str(b.get("date", ""))[:10]: b for b in bars}
        out[code] = {"bars": bars, "by_date": m}
    conn.close()
    return out


def aggregate_lhb() -> list:
    """dragon_tiger → per (date, code) aggregated row.

    code_net = sum(net) across all seats (playbook "净买入")
    change_rate / close_price / accum_amount = code-level (same per code per day)
    seats = distinct dept_name count
    inst_net = sum(net) where dept_name LIKE '机构%' (机构净买)
    """
    conn = sqlite3.connect(str(DT_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT trade_date, security_code, change_rate, close_price, accum_amount, "
        "dept_name, net FROM dragon_tiger_rows WHERE security_code IS NOT NULL "
        "AND length(security_code)=6"
    ).fetchall()
    agg = defaultdict(lambda: {"net": 0.0, "inst_net": 0.0, "seats": set(),
                                "cr": None, "close": None, "amount": None})
    for r in rows:
        key = (r["trade_date"], r["security_code"])
        a = agg[key]
        n = r["net"] or 0.0
        a["net"] += n
        if (r["dept_name"] or "").startswith("机构"):
            a["inst_net"] += n
        a["seats"].add(r["dept_name"])
        if a["cr"] is None:
            a["cr"] = r["change_rate"]
            a["close"] = r["close_price"]
            a["amount"] = r["accum_amount"]
    conn.close()
    out = []
    for (d, c), a in agg.items():
        out.append({"date": d, "code": c, "cr": a["cr"], "net": a["net"],
                    "inst_net": a["inst_net"], "n_seats": len(a["seats"]),
                    "close": a["close"], "amount": a["amount"]})
    return out


def classify(row):
    """A组 / B组 / other per playbook.

    A组: -3 <= cr <= 10 AND 0 < net < 0.5e8 AND cr <= 9.5 (排除涨停)
    B组(陷阱): cr > 9.5 (涨停/暴涨) OR net > 0.5e8
    """
    cr = row["cr"]
    net = row["net"]
    if cr is None or net is None:
        return "other"
    in_range = -3.0 <= cr <= 10.0
    net_ok = 0 < net < 0.5e8
    not_limitup = cr <= 9.5
    if in_range and net_ok and not_limitup:
        return "A"
    if cr > 9.5 or net > 0.5e8:
        return "B"
    return "other"  # e.g. cr<-3%, or net<=0


def is_unbuyable_open(bar, cr_threshold=9.5):
    """T+2 一字涨停封死(open==high==close 且 pctChg>=threshold)."""
    if not bar:
        return True
    o, h, l, c = bar.get("open", 0), bar.get("high", 0), bar.get("low", 0), bar.get("close", 0)
    pct = bar.get("pctChg", 0) or 0
    if o <= 0 or c <= 0:
        return True
    # 一字: open==high==low==close 且 涨幅达 threshold
    if abs(o - h) < 1e-6 and abs(h - l) < 1e-6 and abs(l - c) < 1e-6 and pct >= cr_threshold:
        return True
    # 开盘即涨停且全天封死: open==high==close (low 可能略低但不开板)
    if abs(o - h) < 1e-6 and abs(h - c) < 1e-6 and pct >= cr_threshold:
        return True
    return False


def pos20_and_turn(kl, row):
    """二层漏斗: 20日位置<50% + 换手10-25% at T日.

    20日位置 = (T日close - 20日low) / (20日high - 20日low)
    换手 = T日turn (kline bar field)
    Returns (pos20, turn, pass_filter) — None if data missing.
    """
    rec = kl.get(row["code"])
    if not rec:
        return None, None, False
    bars = rec["bars"]
    t_idx = next((i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == row["date"]), None)
    if t_idx is None or t_idx < 20:
        return None, None, False
    window = bars[t_idx - 20: t_idx + 1]  # 20 days up to & incl T
    hi = max(float(b.get("high", 0)) for b in window)
    lo = min(float(b.get("low", 0)) for b in window)
    c = float(bars[t_idx].get("close", 0))
    pos = (c - lo) / (hi - lo) if hi > lo else 0.5
    turn = float(bars[t_idx].get("turn", 0) or 0)
    return pos, turn, (pos < 0.50 and 10.0 <= turn <= 25.0)


def compute_trade(kl, row, max_hold=15):
    """T+2 open entry → stop/TP/timeout exit. Returns dict or None."""
    code = row["code"]
    tdate = row["date"]
    rec = kl.get(code)
    if not rec:
        return None
    bars = rec["bars"]
    # find T index
    t_idx = next((i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == tdate), None)
    if t_idx is None:
        return None
    entry_idx = t_idx + 2  # T+2
    if entry_idx + 1 >= len(bars):  # need at least entry bar
        return None
    entry_bar = bars[entry_idx]
    if is_unbuyable_open(entry_bar):
        return None
    entry_price = float(entry_bar.get("open", 0))
    if entry_price <= 0:
        return None
    cost_dec = _cost_pct(entry_price, 100.0, tdate) / 100.0
    # scan hold days for stop/TP
    exit_price = None
    exit_reason = None
    end = min(entry_idx + max_hold, len(bars) - 1)
    for j in range(entry_idx, end + 1):
        b = bars[j]
        c = float(b.get("close", 0))
        if c <= 0:
            continue
        if c <= entry_price * 0.85:
            exit_price = c
            exit_reason = "stop"
            break
        if c >= entry_price * 1.20:
            exit_price = c
            exit_reason = "tp"
            break
        if j == end:
            exit_price = c
            exit_reason = "timeout"
    if exit_price is None or exit_price <= 0:
        return None
    gross = (exit_price - entry_price) / entry_price
    net = gross - cost_dec
    return {"net": net, "gross": gross, "win": 1 if net > 0 else 0,
            "reason": exit_reason, "cost": cost_dec, "date": tdate, "code": code,
            "cr": row["cr"], "net_buy": row["net"]}


def day_paired_t(rets, dates):
    """Cluster returns by date, t-test on day-means vs 0."""
    by_day = defaultdict(list)
    for r, d in zip(rets, dates):
        by_day[d].append(r)
    day_means = [statistics.mean(v) for v in by_day.values() if v]
    if len(day_means) < 2:
        return float("nan"), len(day_means)
    m = statistics.mean(day_means)
    sd = statistics.stdev(day_means)
    se = sd / (len(day_means) ** 0.5)
    t = m / se if se > 0 else float("nan")
    return t, len(day_means)


def summarize(trades, label):
    if not trades:
        print(f"  [{label}] n=0 (empty)")
        return None
    rets = [t["net"] for t in trades]
    gross = [t["gross"] for t in trades]
    dates = [t["date"] for t in trades]
    n = len(rets)
    wr = sum(t["win"] for t in trades) / n
    mean_net = statistics.mean(rets) * 100
    mean_gross = statistics.mean(gross) * 100
    med = statistics.median(rets) * 100
    t_val, ndays = day_paired_t(rets, dates)
    # reason breakdown
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
    print(f"  [{label}] n={n} days={ndays} WR={wr*100:.1f}% "
          f"mean_gross={mean_gross:+.3f}% mean_net={mean_net:+.3f}% "
          f"median={med:+.3f}% day_t={t_val:+.2f}")
    print(f"           exits: {dict(reasons)}")
    return {"n": n, "wr": wr, "mean_net": mean_net, "median": med, "day_t": t_val}


def main():
    print("=" * 70)
    print("A组跟庄战法对抗复现 (LHB非涨停低吸 vs 涨停连板接力已falsified)")
    print("=" * 70)
    kl = load_klinebars()
    print(f"[kline] codes={len(kl)}")
    rows = aggregate_lhb()
    print(f"[lhb] aggregated code-days={len(rows)} "
          f"dates={min(r['date'] for r in rows)}..{max(r['date'] for r in rows)}")
    # classify
    groups = defaultdict(list)
    for r in rows:
        groups[classify(r)].append(r)
    print(f"[classify] A={len(groups['A'])} B={len(groups['B'])} other={len(groups['other'])}")
    # A组 sub: by net bucket
    a_rows = groups["A"]
    a_low = [r for r in a_rows if 0 < r["net"] < 0.2e8]   # 净买<0.2亿(playbook⭐⭐⭐最佳)
    a_mid = [r for r in a_rows if 0.2e8 <= r["net"] < 0.4e8]  # 0.2-0.4亿
    a_hi = [r for r in a_rows if 0.4e8 <= r["net"] < 0.5e8]
    print(f"[A net-bucket] <0.2亿={len(a_low)} 0.2-0.4亿={len(a_mid)} 0.4-0.5亿={len(a_hi)}")
    # compute trades
    print("\n--- 主结果: T+2 open entry, 15d hold, -15%stop/+20%TP ---")
    a_trades = [t for r in a_rows if (t := compute_trade(kl, r)) is not None]
    b_trades = [t for r in groups["B"] if (t := compute_trade(kl, r)) is not None]
    base_trades = [t for r in rows if (t := compute_trade(kl, r)) is not None]
    summarize(a_trades, "A组(非涨停低吸)")
    summarize(b_trades, "B组(陷阱)")
    summarize(base_trades, "ALL-LHB-baseline")

    print("\n--- A组净买分桶 ---")
    summarize([t for r in a_low if (t := compute_trade(kl, r)) is not None], "A-净买<0.2亿(最佳)")
    summarize([t for r in a_mid if (t := compute_trade(kl, r)) is not None], "A-净买0.2-0.4亿")
    summarize([t for r in a_hi if (t := compute_trade(kl, r)) is not None], "A-净买0.4-0.5亿")

    print("\n--- A组涨幅分桶 (chasing bias 检测) ---")
    a_neg = [r for r in a_rows if r["cr"] < 0]      # 跌(低吸)
    a_lowpos = [r for r in a_rows if 0 <= r["cr"] < 3]
    a_midpos = [r for r in a_rows if 3 <= r["cr"] < 6]
    a_highpos = [r for r in a_rows if 6 <= r["cr"] <= 9.5]
    summarize([t for r in a_neg if (t := compute_trade(kl, r)) is not None], "A-跌幅(-3~0%)")
    summarize([t for r in a_lowpos if (t := compute_trade(kl, r)) is not None], "A-微涨(0-3%)")
    summarize([t for r in a_midpos if (t := compute_trade(kl, r)) is not None], "A-中涨(3-6%)")
    summarize([t for r in a_highpos if (t := compute_trade(kl, r)) is not None], "A-高涨(6-9.5%)")

    # 机构净买分层 (playbook "机构净买>0")
    print("\n--- A组机构净买分层 ---")
    a_inst = [r for r in a_rows if r["inst_net"] > 0]
    a_noinst = [r for r in a_rows if r["inst_net"] <= 0]
    print(f"[A inst] 机构净买>0={len(a_inst)} 机构净买<=0={len(a_noinst)}")
    summarize([t for r in a_inst if (t := compute_trade(kl, r)) is not None], "A-机构净买>0")
    summarize([t for r in a_noinst if (t := compute_trade(kl, r)) is not None], "A-机构净买<=0")

    print("\n--- 关键判定 ---")
    if a_trades:
        wr = sum(t["win"] for t in a_trades) / len(a_trades)
        mn = statistics.mean(t["net"] for t in a_trades) * 100
        print(f"A组 WR={wr*100:.1f}% mean_net={mn:+.3f}% | playbook claim: 59% / +5.3%")
        if wr >= 0.50 and mn > 0:
            print("→ A组 edge 可能存在 (WR>=50% & mean>0) — 未测维度浮现")
        else:
            print("→ A组 edge 不成立 (WR<50% 或 mean<=0) — falsification 维持")

    # 二层漏斗: A组 + 20日位置<50% + 换手10-25%
    print("\n--- 二层漏斗: A组 + 20日位置<50% + 换手10-25% ---")
    a_layer2 = []
    for r in a_rows:
        pos, turn, ok = pos20_and_turn(kl, r)
        if ok:
            a_layer2.append(r)
    print(f"[二层] A组过20日位置+换手: {len(a_layer2)} (of {len(a_rows)})")
    summarize([t for r in a_layer2 if (t := compute_trade(kl, r)) is not None], "A+二层漏斗")

    # 20日位置单因子分层 (是否低位=edge)
    print("\n--- A组 20日位置分层 ---")
    a_lowpos = []
    a_highpos = []
    for r in a_rows:
        pos, turn, ok = pos20_and_turn(kl, r)
        if pos is None:
            continue
        (a_lowpos if pos < 0.50 else a_highpos).append(r)
    print(f"[pos] 低位<50%={len(a_lowpos)} 高位>=50%={len(a_highpos)}")
    summarize([t for r in a_lowpos if (t := compute_trade(kl, r)) is not None], "A-低位<50%")
    summarize([t for r in a_highpos if (t := compute_trade(kl, r)) is not None], "A-高位>=50%")

    # playbook 精确3个月窗口 (2026-07-01~09-30)
    print("\n--- playbook 精确窗口 2026-07-01~09-30 (3个月) ---")
    a_3mo = [r for r in a_rows if "2026-07-01" <= r["date"] <= "2026-09-30"]
    b_3mo = [r for r in groups["B"] if "2026-07-01" <= r["date"] <= "2026-09-30"]
    print(f"[3mo] A={len(a_3mo)} B={len(b_3mo)}")
    summarize([t for r in a_3mo if (t := compute_trade(kl, r)) is not None], "A组-3个月窗口")
    summarize([t for r in b_3mo if (t := compute_trade(kl, r)) is not None], "B组-3个月窗口")

    # 二层漏斗 + 3个月窗口 (最接近playbook口径)
    print("\n--- 最接近playbook: A+二层漏斗+3个月窗口 ---")
    a_best = [r for r in a_3mo if (lambda: pos20_and_turn(kl, r)[2])()]
    print(f"[best] A+二层+3mo={len(a_best)}")
    summarize([t for r in a_best if (t := compute_trade(kl, r)) is not None], "A+二层+3mo(playbook口径)")


if __name__ == "__main__":
    main()
