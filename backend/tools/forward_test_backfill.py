#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S066 Phase 0e 前向测试历史回填——补 §13.0 缺的数据验证（让数据决定架构是否 sound）。

§13.0 要求 paper trading 胜率>60% 才加复杂度，但 Phase 0e runner（run_daily_forward_test）
没接线 → forward_test_records 0 行 → §13.0 门没跑过。本脚本 retroactive 跑：对已有
eastmoney_live 历史日期，跑策略记录推荐（run_daily_forward_test）+ 用 backtest_samples
的 next-day 收益回填 T+1（record_actual_returns）→ §44 对照随机基准 + CI + lift。

caveat：weather_state=None（未接历史天气适配，测非天气适配的策略退化版——天气硬开关是
Phase 1 核心，此回填低估了完整架构，是下界）；31 天<30 + 488 样本跨 31 天有日聚类
（effective n≈31，CI 实偏窄）。合规（§1.2/§44）：策略推荐来自 score_candidates（实测
gene_scores）+ 收益来自 backtest_samples；结论前过 §44 三步（口径/CI/随机基准+lift）。

用法：cd backend && ../.venv/bin/python tools/forward_test_backfill.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from strategies.forward_test import (  # noqa: E402
    run_daily_forward_test,
    record_actual_returns,
    get_daily_recommendations,
    get_forward_test_summary,
)

DB = ROOT / ".vibe-research" / "gene_scores.db"
SAMPLES = ROOT / ".vibe-research" / "backtest_samples.json"


def load_returns_map() -> dict[tuple[str, str], dict]:
    """backtest_samples → {(date, code): {return_open2close, return_close2close, next_pctChg}}。"""
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    return {
        (s["date"], s["code"]): {
            "return_open2close": s.get("return_open2close"),
            "return_close2close": s.get("return_close2close"),
            "next_pctChg": s.get("next_pctChg"),
        }
        for s in data.get("samples", [])
    }


def load_src_map() -> dict[tuple[str, str], str]:
    """(date, code) -> data_source 映射（随机基准需过滤 eastmoney_live 段）。"""
    conn = sqlite3.connect(str(DB))
    try:
        return {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT date, code, data_source FROM gene_scores"
        ).fetchall()}
    finally:
        conn.close()


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def main() -> int:
    ret_map = load_returns_map()
    src_map = load_src_map()
    conn = sqlite3.connect(str(DB))
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date"
    ).fetchall()]
    conn.close()
    print(f"eastmoney_live 信号日数: {len(dates)}")
    if not dates:
        return 1

    total_recs = 0
    total_settled = 0
    for d in dates:
        r = run_daily_forward_test(d, weather_state=None)  # caveat: 未接历史天气适配
        n = r.get("recommendations", 0)
        if not n:
            continue
        recs = get_daily_recommendations(d)
        returns_data = {rec["code"]: ret_map.get((d, rec["code"]), {}) for rec in recs}
        total_settled += record_actual_returns(d, returns_data)
        total_recs += n
    print(f"回填 {len(dates)} 信号日，共 {total_recs} 条推荐，{total_settled} 条回填 T+1 收益")

    print("\n=== Phase 0e 汇总 ===")
    print(get_forward_test_summary(benchmark_win_rate=60.0, min_days=10))

    # §44 数据支撑优先（结论前必过）：策略胜率 vs 随机基准 + Wilson CI + lift
    conn = sqlite3.connect(str(DB))
    sn = conn.execute("SELECT COUNT(*) FROM forward_test_records WHERE return_open2close IS NOT NULL").fetchone()[0]
    sw = conn.execute("SELECT COUNT(*) FROM forward_test_records WHERE is_win=1").fetchone()[0]
    conn.close()
    samples_all = json.loads(SAMPLES.read_text(encoding="utf-8")).get("samples", [])
    el = [s for s in samples_all
          if src_map.get((s["date"], s["code"])) == "eastmoney_live"
          and s.get("return_open2close") is not None]
    rn = len(el)
    rw = sum(1 for s in el if s["return_open2close"] > 0)
    slo, shi = _wilson(sw, sn)
    rlo, rhi = _wilson(rw, rn)
    lift = (sw / sn) / (rw / rn) if rn and rw else 0.0
    print(f"\n§44 对照:")
    print(f"  策略胜率  {sw}/{sn} = {sw/sn*100:.1f}%  CI[{slo*100:.1f}, {shi*100:.1f}]%")
    print(f"  随机基准  {rw}/{rn} = {rw/rn*100:.1f}%  CI[{rlo*100:.1f}, {rhi*100:.1f}]%  (全体 eastmoney_live 涨停股次日 open2close>0)")
    print(f"  lift = {lift:.2f}x  →  {'噪声(<2x，不得作设计依据)' if lift < 2 else '≥2x 可作依据'}"
          f"  {'；策略 CI 与随机 CI 重叠（不显著优于随机）' if slo <= rhi else '；策略 CI 显著高于随机'}")
    print("caveat: weather=None（非天气适配退化版，下界）；31 天<30 探索性 + 日聚类（effective n≈31，CI 实偏窄）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
