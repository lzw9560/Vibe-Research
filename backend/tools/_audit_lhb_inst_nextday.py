# -*- coding: utf-8 -*-
"""LHB 机构席位梯度 8 年审计——第二步：次日表现。

第一步（_audit_lhb_inst_gradient_8year.py）验证 R34 机构化（4.3%→50.6%）。
第二步：算 inst_dominant / lhb_mixed / inst_selling 三层次日表现（T+1open→T+2close）
+ day_paired t + Bonferroni×3——验证 grilling "inst_dominant +0.405% gross 但 stop -0.286%
无显著性 p=0.13"是否 8 年达显著性。

采样：inst_dominant 5000 + lhb_mixed 5000 + inst_selling 全部 2381（baostock kline N+1 慢）。
"""
import json
import sqlite3
import random
import statistics
from pathlib import Path
from collections import defaultdict
from math import erf

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"

INST_KEYWORDS = (
    "机构专用", "总部", "高盛", "瑞银", "股通", "摩根",
    "中信证券股份有限公司上海分公司", "国际金融",
)
ALPHA = 0.05


def load_picks_by_layer() -> dict:
    """8 年 LHB 上榜股分层（同第一步）。"""
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute("""
        SELECT trade_date, security_code, dept_name, buy, net
        FROM dragon_tiger_rows WHERE side='buy' AND buy > 0
    """).fetchall()
    conn.close()

    picks: dict[tuple, list] = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks[(date, code)].append((dept or "", buy or 0, net or 0))

    layers: dict[str, list] = {"inst_dominant": [], "lhb_mixed": [], "inst_selling": []}
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


def load_kline_dates(code: str) -> list:
    """取个股 bars 按 date 排序。"""
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


def compute_nextday_return(code: str, trade_date: str, kline_cache: dict) -> float | None:
    """T+1 open→T+2 close 收益（%）。

    grilling 用 close_ev（T+1open→T+2close），本项目对齐。
    """
    if code not in kline_cache:
        kline_cache[code] = load_kline_dates(code)
    bars = kline_cache[code]
    # 找 trade_date 之后的 bars（T+1, T+2）
    after = [b for b in bars if b.get("date", "") > trade_date]
    if len(after) < 2:
        return None
    t1_open = after[0].get("open")
    t2_close = after[1].get("close")
    if not t1_open or not t2_close or t1_open <= 0:
        return None
    return (t2_close / t1_open - 1) * 100


def day_paired_t(returns_by_date: dict) -> tuple:
    """day-paired t（同日 picks 平均后 day-mean t）。"""
    day_means = [statistics.mean(rs) for rs in returns_by_date.values() if rs]
    if len(day_means) < 2:
        return None, 0, None
    mean = statistics.mean(day_means)
    n = len(day_means)
    se = statistics.stdev(day_means) / (n ** 0.5) if n > 1 else 0
    t = mean / se if se > 0 else 0
    return mean, n, t


def normal_p(t: float) -> float:
    """正态近似 p 值（探索性，粗略）。"""
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / (2 ** 0.5))))


def audit_nextday(sample_n: int = 5000) -> dict:
    """采样三层算次日表现。"""
    layers = load_picks_by_layer()
    random.seed(42)
    kline_cache: dict = {}
    results: dict = {}

    print(f"=== LHB 机构席位梯度 8 年 次日表现（T+1open→T+2close）===")
    print(f"采样: inst_dominant/lhb_mixed 各 {sample_n} + inst_selling 全部\n")

    for layer_name, picks in layers.items():
        n = min(sample_n, len(picks))
        sampled = random.sample(picks, n) if n < len(picks) else picks
        returns_by_date: dict = defaultdict(list)
        all_returns: list = []
        for date, code in sampled:
            r = compute_nextday_return(code, date, kline_cache)
            if r is not None:
                returns_by_date[date].append(r)
                all_returns.append(r)

        mean, n_days, t = day_paired_t(returns_by_date)
        n_picks = len(all_returns)
        wr = sum(1 for r in all_returns if r > 0) / n_picks * 100 if n_picks else 0
        sorted_r = sorted(all_returns)
        median = sorted_r[n_picks // 2] if n_picks else 0
        results[layer_name] = {
            "n_picks": n_picks, "n_days": n_days, "mean": mean,
            "median": median, "wr": wr, "t": t,
        }
        print(f"  {layer_name}: n={n_picks} days={n_days} "
              f"mean={mean:.3f}% median={median:.3f}% WR={wr:.1f}% day_t={t:.2f}" if mean is not None
              else f"  {layer_name}: n={n_picks} 数据不足")

    # Bonferroni ×3
    print(f"\n  Bonferroni ×3（三层）:")
    for layer_name, r in results.items():
        if r["t"] is not None:
            p = normal_p(r["t"])
            p_bonf = min(1.0, p * 3)
            verdict = "PASS" if p_bonf < ALPHA else "FAIL"
            print(f"    {layer_name}: raw p={p:.4f} Bonf×3={p_bonf:.4f} {verdict}")

    # 梯度对比（inst_dominant vs inst_selling）
    if results.get("inst_dominant", {}).get("mean") and results.get("inst_selling", {}).get("mean"):
        spread = results["inst_dominant"]["mean"] - results["inst_selling"]["mean"]
        print(f"\n  梯度 spread（inst_dominant - inst_selling）= {spread:.3f}%")
        print(f"  grilling 1 年: inst_dominant +0.405% / inst_selling -0.843% spread=1.248%")
        print(f"  8 年: {'验证' if spread > 0 else '反转'} 梯度方向")

    return results


if __name__ == "__main__":
    audit_nextday(sample_n=5000)
