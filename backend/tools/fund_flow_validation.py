#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44 60日复验窗口验证：T-1 资金流（main_net 净流入）→ T 涨停（盘前选股假设）。

假设：一只股 T-1 主力净流入高 → T 涨停概率↑（资金驱动涨停，causal）。盘前选股用 T-1 资金流筛 T 涨停候选。
§44 60日复验窗口：lift>=2x（高 T-1 资金流股的 T 涨停率 / 低 T-1 资金流股）+ CI 不重叠 + n>=30 → validated；
<2x 标未 validated（复验日满60天后定权重），不阻断接入跑通。本脚本计算逻辑不变，只改注释口径。

设计：对每个 T（eastmoney_live 日）：
  正类 = 涨停-T 股（gene_scores T）；负类 = 对照样本（非涨停-T，从 code_industry 随机抽）
  特征 = T-1 main_net（stock_fund_flow_120d 取 T-1 行）
  lift = top-quintile T-1 main_net 的涨停率 / bottom-quintile

数据依赖：stock_fund_flow_120d（push2his 120 日，需 IP 未被封；push2his 断连时降级 push2delay 只给最新 1 日→不可用）。
限流：em_get 熔断 + 2-3s 间隔；样本化降 scale（默认 100 正类 + 100 对照/日）。

用法：cd backend && .venv/bin/python tools/fund_flow_validation.py
（IP 封时 push2his 断连 → 多数 fetch 失败 → n 小；需 IP 解封后跑）
"""
from __future__ import annotations

import sqlite3
import sys
import time
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

DB = ROOT / ".vibe-research" / "gene_scores.db"


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def _t1_main_net(code: str, t1_date: str) -> float | None:
    """取 code 在 t1_date 的 main_net。先直连（stock_fund_flow_120d），断连/只1日 → 代理池 fallback。"""
    import astock
    from proxy_pool import fetch_fund_flow_via_pool
    rows = None
    try:
        rows = astock.stock_fund_flow_120d(code)
    except Exception:
        rows = None
    if not rows or len(rows) < 2:  # direct 断连/只 1 日 → 走代理池（fresh IP 绕限流）
        rows = fetch_fund_flow_via_pool(code) or None
    if not rows or len(rows) < 2:
        return None
    for r in rows:
        if r.get("date") == t1_date:
            return r.get("main_net")
    return None


def main(sample_per_day: int = 100, sleep_s: float = 2.5) -> int:
    conn = sqlite3.connect(str(DB), timeout=10)
    try:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date"
        ).fetchall()]
        date_set = set(dates)
        all_codes = [r[0] for r in conn.execute("SELECT code FROM code_industry").fetchall()]
    finally:
        conn.close()

    samples: list[tuple[int, float | None]] = []  # (is_涨停_T, t1_main_net)
    fetch_ok = fetch_fail = 0
    random.seed(42)
    for i, d in enumerate(dates[:-1]):
        d1 = dates[i + 1]  # T（涨停日）
        if d1 not in date_set:
            continue
        t1 = d  # T-1
        conn = sqlite3.connect(str(DB), timeout=10)
        zt_T = {r[0] for r in conn.execute(
            "SELECT DISTINCT code FROM gene_scores WHERE date=? AND data_source='eastmoney_live'", (d1,)).fetchall()}
        conn.close()
        pos = list(zt_T)[:sample_per_day]
        neg_pool = [c for c in all_codes if c not in zt_T]
        neg = random.sample(neg_pool, min(sample_per_day, len(neg_pool)))
        for code in pos + neg:
            mn = _t1_main_net(code, t1)
            if mn is None:
                fetch_fail += 1
            else:
                fetch_ok += 1
                samples.append((1 if code in zt_T else 0, mn))
            time.sleep(sleep_s)
        print(f"  {d}→{d1}: pos={len(pos)} neg={len(neg)} fetched ok={fetch_ok} fail={fetch_fail}", flush=True)

    if not samples:
        print("无可用样本（push2his 断连？IP 限流？）—— 需 IP 解封后跑。")
        return 1
    # 按 T-1 main_net 分位，算 top/bottom quintile 的涨停率
    samples.sort(key=lambda x: x[1])
    n = len(samples)
    q = max(1, n // 5)
    bottom = samples[:q]
    top = samples[-q:]
    b_pos = sum(1 for s, _ in bottom if s)
    t_pos = sum(1 for s, _ in top if s)
    b_rate = b_pos / q
    t_rate = t_pos / q
    lift = t_rate / b_rate if b_rate else 0.0
    tb_lo, tb_hi = _wilson(t_pos, q)
    bb_lo, bb_hi = _wilson(b_pos, q)
    print(f"\n=== T-1 资金流 → T 涨停 §44 60日复验窗口验证 ===")
    print(f"样本: {n}（fetched ok={fetch_ok} fail={fetch_fail}）")
    print(f"top-quintile T-1 main_net: 涨停 {t_pos}/{q} = {t_rate*100:.2f}% CI[{tb_lo*100:.2f},{tb_hi*100:.2f}]")
    print(f"bottom-quintile          : 涨停 {b_pos}/{q} = {b_rate*100:.2f}% CI[{bb_lo*100:.2f},{bb_hi*100:.2f}]")
    print(f"lift = {lift:.3f}x → {'≥2x §44 validated' if lift >= 2.0 else '<2x §44 未 validated（不阻断，60日后复验）'}"
          f"{'；CI 不重叠（显著）' if tb_lo > bb_hi else '；CI 重叠（不显著）'}")
    print(f"caveat: sample_per_day={sample_per_day}（样本化降 scale）；push2his 断连则 fail 多、n 小。")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100, help="每日正/负类样本数（降 scale）")
    ap.add_argument("--sleep", type=float, default=2.5, help="fetch 间隔秒（限流防封）")
    a = ap.parse_args()
    raise SystemExit(main(a.sample, a.sleep))
