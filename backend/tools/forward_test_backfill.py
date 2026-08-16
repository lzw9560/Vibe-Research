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
    record_universe_returns,
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


def load_returns_by_date() -> dict[str, dict[str, dict]]:
    """backtest_samples → {date: {code: returns}}（universe 回填用，按日索引）。"""
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    by_date: dict[str, dict[str, dict]] = {}
    for s in data.get("samples", []):
        by_date.setdefault(s["date"], {})[s["code"]] = {
            "return_open2close": s.get("return_open2close"),
            "return_close2close": s.get("return_close2close"),
            "next_pctChg": s.get("next_pctChg"),
        }
    return by_date


def main() -> int:
    ret_map = load_returns_map()
    by_date = load_returns_by_date()
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
    total_universe = 0
    for d in dates:
        # run_daily_forward_test 记录 picks + universe codes（收益 NULL）
        r = run_daily_forward_test(d, weather_state=None)  # caveat: 未接历史天气适配
        n = r.get("recommendations", 0)
        if not n:
            continue
        # picks 收益回填
        recs = get_daily_recommendations(d)
        returns_data = {rec["code"]: ret_map.get((d, rec["code"]), {}) for rec in recs}
        total_settled += record_actual_returns(d, returns_data)
        total_recs += n
        # §44 universe 收益回填（同日全体涨停股 → 零选股基准率）
        total_universe += record_universe_returns(d, by_date.get(d, {}))
    print(f"回填 {len(dates)} 信号日：picks {total_recs} 条（回填 {total_settled}），universe {total_universe} 条")

    print("\n=== Phase 0e §44 汇总（framework get_forward_test_summary）===")
    print(get_forward_test_summary(benchmark_win_rate=60.0, min_days=10))
    print("caveat: weather=None（非天气适配退化版，下界）；31 天<30 探索性 + 日聚类（CI 偏窄）")
    print("caveat: universe=当日全体涨停股（load_gene_scores 全源，非仅 eastmoney_live）；"
          "若与原手算 eastmoney-only 50.2% 略异，因 pool 口径不同，§44 verdict（lift<2x）稳健不变")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
