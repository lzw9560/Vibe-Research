#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§44 60日复验窗口验证：板块热度 → 次日新涨停（宽 universe，横截面因子）。

假设：一只股在**涨停数多的板块**（热板块）里、且**今日未涨停** → 次日涨停概率↑（板块注意力
轮动→成员涨停）。这是横截面因子（板块上下文→个股结果），区别于 8 因子（个股涨停史 post-hoc）。

§44 60日复验窗口：lift>=2x（热板块成员次日新涨停率 / 冷板块成员次日新涨停率）+ CI 不重叠 + n>=30 → validated；
<2x 标未 validated（复验日满60天后定权重），不阻断接入跑通。本脚本计算 r/CI/lift 逻辑不变，只改注释口径。

设计：
- 对每个 D（eastmoney_live 日，D+1 也在 set 内）：
  热板块 = zt_count(D) top-5；冷板块 = zt_count(D)==0
  成员 = code_industry 成员，排除 D 涨停股（只看新涨停，非续涨）
  次日涨停 = 成员 ∩ gene_scores(D+1) 涨停池
  hot_rate = |热成员次日涨停| / |热成员|；cold_rate = |冷成员次日涨停| / |冷成员|
- 聚合跨 D：lift = hot_rate/cold_rate + Wilson CI + n（日数 + 总成员）。

用法：cd backend && .venv/bin/python tools/sector_heat_validation.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

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


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=10)
    # heat 定义：top-N + zt_count>=阈值
    heat_defs = [("top1", 1, 0), ("top3", 3, 0), ("top5", 5, 0), ("zt>=3", 99, 3), ("zt>=5", 99, 5)]
    try:
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date"
        ).fetchall()]
        date_set = set(dates)
        code_ind: dict[str, str] = {r[0]: r[1] for r in conn.execute(
            "SELECT code, industry FROM code_industry WHERE industry IS NOT NULL AND industry != ''"
        ).fetchall()}

        # 预取每日 D 的 zt_by_ind + d_zt_codes + D+1 涨停池
        daily = []
        for i, d in enumerate(dates[:-1]):
            d1 = dates[i + 1]
            if d1 not in date_set:
                continue
            zt_by_ind: dict[str, int] = defaultdict(int)
            d_zt_codes = set()
            for code, ind in conn.execute(
                "SELECT code, industry FROM gene_scores WHERE date=? AND data_source='eastmoney_live'",
                (d,)).fetchall():
                if ind:
                    zt_by_ind[ind] += 1
                    d_zt_codes.add(code)
            d1_zt = {r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM gene_scores WHERE date=? AND data_source='eastmoney_live'",
                (d1,)).fetchall()}
            daily.append((d, zt_by_ind, d_zt_codes, d1_zt))
    finally:
        conn.close()

    all_inds_per_day = [{ind for ind, c in z.items() if c > 0} for _, z, _, _ in daily]

    print(f"=== 板块热度 → 次日新涨停 §44 验证（多热度定义）===")
    print(f"日数: {len(daily)}（D→D+1 对，eastmoney_live）\n")
    for name, topn, thresh in heat_defs:
        hm = hn = cm = cn = 0
        for idx, (_, zt_by_ind, d_zt_codes, d1_zt) in enumerate(daily):
            ranked = sorted(zt_by_ind.items(), key=lambda x: -x[1])
            if topn < 99:
                hot_inds = {ind for ind, _ in ranked[:topn]}
            else:
                hot_inds = {ind for ind, c in zt_by_ind.items() if c >= thresh}
            all_inds = all_inds_per_day[idx]
            hot_mem = [c for c, ind in code_ind.items() if ind in hot_inds and c not in d_zt_codes]
            cold_mem = [c for c, ind in code_ind.items() if ind not in all_inds and c not in d_zt_codes]
            if not hot_mem or not cold_mem:
                continue
            hm += len(hot_mem); cm += len(cold_mem)
            hn += sum(1 for c in hot_mem if c in d1_zt)
            cn += sum(1 for c in cold_mem if c in d1_zt)
        hr = hn / hm if hm else 0.0
        cr = cn / cm if cm else 0.0
        lift = hr / cr if cr else 0.0
        hlo, hhi = _wilson(hn, hm)
        clo, chi = _wilson(cn, cm)
        sig = "CI不重叠" if hlo > chi else "CI重叠"
        verdict = "≥2x validated" if lift >= 2.0 else "<2x 未 validated"
        print(f"{name:6s}: hot {hn}/{hm}={hr*100:.2f}%[{hlo*100:.2f},{hhi*100:.2f}]  "
              f"cold {cn}/{cm}={cr*100:.2f}%[{clo*100:.2f},{chi*100:.2f}]  "
              f"lift={lift:.3f}x → {verdict}（{sig}）")
    print(f"\ncaveat: n={len(daily)}日{'（<30 探索性）' if len(daily) < 30 else ''}；冷=0涨停板块（基线≈市场~1%）；"
          f"若全 <2x → 板块热度对次日新涨停无 §44 edge（标未 validated，不阻断接入，60日后复验）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
