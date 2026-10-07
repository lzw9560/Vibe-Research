# -*- coding: utf-8 -*-
"""S232 -3% stop 风险审视——Kelly/破产/回撤/仓位（realistic vs ideal fill 对比）。

复用 explore_s232_stop_verify 的 build_records，输出风险管理需要的真实分布。
"""
from __future__ import annotations
import math
import statistics
from explore_s232_stop_verify import build_records, ev_stats


def realistic_rets(records, stop=-0.03):
    """realistic fill：gap 穿 stop 卖 t2_open，否则 stop 触发卖 stop，否则 T+2 close。"""
    out = []
    for r in records:
        entry = r["t1_open"]
        sp = entry * (1 + stop)
        trig = r["t2_low"] <= sp
        if trig:
            exit_p = r["t2_open"] if r["t2_open"] <= sp else sp
        else:
            exit_p = r["t2_close"]
        out.append((exit_p - entry) / entry * 100)
    return out


def ideal_rets(records, stop=-0.03):
    out = []
    for r in records:
        entry = r["t1_open"]
        sp = entry * (1 + stop)
        trig = r["t2_low"] <= sp
        exit_p = sp if trig else r["t2_close"]
        out.append((exit_p - entry) / entry * 100)
    return out


def baseline_rets(records):
    return [(r["t2_close"] - r["t1_open"]) / r["t1_open"] * 100 for r in records]


def kelly_continuous(rets_pct):
    """连续 Kelly f* = mean/var（returns 用小数）。返回 f* 与对应杠杆。"""
    rs = [r / 100 for r in rets_pct]
    n = len(rs)
    mean = sum(rs) / n
    var = statistics.pstdev(rs) ** 2
    f = mean / var if var > 0 else 0
    return f, mean, var


def kelly_logarithmic(rets_pct, gran=4001):
    """精确 Kelly：argmax E[log(1+f*r)]，f ∈ [0, 2] grid。"""
    rs = [r / 100 for r in rets_pct]
    n = len(rs)
    best_f, best_g = 0.0, -1e18
    for i in range(gran):
        f = i * 2.0 / (gran - 1)
        g = sum(math.log(1 + f * r) for r in rs if (1 + f * r) > 0)
        if g > best_g:
            best_g, best_f = g, f
    return best_f, best_g / n if n else 0


def risk_of_ruin(p_win, loss_frac=0.03, target=0.5, max_iter=2000):
    """破产风险（单笔固定 loss_frac，win 概率 p_win，win 大小变动用近似）。
    用最坏假设：win = +avg_win 但保守按 win 也只 +3% 对称算 RoR。
    经典公式 RoR = ((1-b)/(1+b))^u，b = edge/odds。
    这里用简化：把 stop 视为固定 -loss_frac，win 视为平均 win。"""
    # 二元化：win 平均 vs loss 固定
    return None  # placeholder, computed inline


def max_drawdown_pct(rets_pct, trades_per_day=1):
    """把每笔当作顺序 equity curve，算最大回撤（% of peak equity）。"""
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in rets_pct:
        eq *= (1 + r / 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > mdd:
            mdd = dd
    return mdd * 100, eq


def by_day_concentration(records):
    """每天多少笔交易——同日 trades 高度相关（共市场 regime）。"""
    from collections import Counter
    days = Counter()
    for r in records:
        # records 没存 date，用 t1_open 排序无法恢复；用 index 近似
        pass
    return None


def main():
    records, _ = build_records()
    if not records:
        print("ERR no records")
        return
    n = len(records)

    base = baseline_rets(records)
    ideal = ideal_rets(records)
    real = realistic_rets(records)

    print(f"=== n={n} trades ===\n")

    for label, rets in [("baseline(no stop)", base), ("-3%stop IDEAL(over-credit)", ideal), ("-3%stop REALISTIC", real)]:
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        s = ev_stats(rets)
        wr = len(wins) / n * 100
        avg_w = statistics.mean(wins) if wins else 0
        avg_l = statistics.mean(losses) if losses else 0
        # worst losses (gap through reality)
        worst = sorted(rets)[:5]
        # Kelly continuous
        f_cont, mu, var = kelly_continuous(rets)
        # Kelly log
        f_log, g_log = kelly_logarithmic(rets)
        # binary Kelly approximation: b = avg_win/|avg_loss|, p = wr
        p = wr / 100
        b = avg_w / abs(avg_l) if avg_l != 0 else 0
        f_bin = (p * b - (1 - p)) / b if b > 0 else 0
        # max drawdown
        mdd, final_eq = max_drawdown_pct(rets)
        print(f"--- {label} ---")
        print(f"  EV={s['ev']}% std={s['std']}% t={s['t']} CI[{s['ci_lo']},{s['ci_hi']}]")
        print(f"  WR={wr:.1f}% (wins={len(wins)} losses={len(losses)})")
        print(f"  avg_win={avg_w:.2f}% avg_loss={avg_l:.2f}% R:R(b)={b:.2f}")
        print(f"  worst5={ [round(x,2) for x in worst] }")
        print(f"  Kelly continuous f*={f_cont:.3f} (mu={mu:.4f} var={var:.4f})")
        print(f"  Kelly log-search  f*={f_log:.3f} (growth={g_log:.5f})")
        print(f"  Kelly binary(approx) f*={max(f_bin,0):.3f}")
        print(f"  MaxDD={mdd:.1f}% final_equity={final_eq:.3f}x")
        print()

    # ---- trades per day concentration (用 records 顺序无法恢复日期，改用 build 时记录) ----
    print("=== 同日 trades 集中度（市场共因子风险）===")
    # 重建 date→trades
    import sqlite3, json
    from pathlib import Path
    from explore_s232_stop_verify import load_kline_db, load_zt_by_date, vol_ratio_5, TURN_THRESHOLD, VR5_THRESHOLD, KLINE_DB
    # 简化：用 build_records 改造——直接重新跑一次带日期
    all_bars = load_kline_db()
    zt = load_zt_by_date()
    cal = sorted(zt.keys())
    end_date = "2026-09-17"
    days = 180
    end_idx = cal.index(end_date)
    date_idx = {d: i for i, d in enumerate(cal)}
    pairs = [(cal[i], cal[i + 1]) for i in range(max(0, end_idx - days), end_idx) if i + 1 < len(cal)]
    per_day = {}
    for t, t1 in pairs:
        zt_t = zt.get(t, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        wl = []
        for code, bars in all_bars.items():
            tbar = None; tidx = -1
            for i, bb in enumerate(bars):
                if bb.get("date") == t:
                    tbar = bb; tidx = i; break
            if tbar is None: continue
            if code in zt_t: continue
            if tbar.get("isST") in ("1", 1, True): continue
            turn = tbar.get("turn")
            if turn is None or turn <= TURN_THRESHOLD: continue
            vr5 = vol_ratio_5(bars, tidx)
            if vr5 is None or vr5 <= VR5_THRESHOLD: continue
            wl.append(code)
        # count records with low-open on this t1
        cnt = 0
        for code in wl:
            bars = all_bars.get(code, [])
            tbar = next((bb for bb in bars if bb.get("date") == t), None)
            if not tbar or tbar.get("close") is None: continue
            t_close = tbar["close"]
            t1bar = next((bb for bb in bars if bb.get("date") == t1), None)
            if not t1bar or t1bar.get("open") is None or t1bar["open"] == 0: continue
            gap = (t1bar["open"] - t_close) / t_close * 100
            if not (-5 <= gap < -2): continue
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            if t1bar["open"] >= t_close * (1 + zt_limit) * 0.999: continue
            cnt += 1
        per_day[t1] = per_day.get(t1, 0) + cnt
    cnts = sorted(per_day.values(), reverse=True)
    active_days = [c for c in cnts if c > 0]
    print(f"  active trade days={len(active_days)}/{len(per_day)}")
    print(f"  trades/day: max={max(cnts)} p90={cnts[len(cnts)//10]} median={statistics.median(cnts) if cnts else 0} mean={statistics.mean(cnts) if cnts else 0:.1f}")
    print(f"  top5 days trades: {cnts[:5]}")
    print(f"  → 同日 trades 共享 regime/市场情绪，effective N 远小于 {n}")


if __name__ == "__main__":
    main()
