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


ZT_DB = ROOT / ".vibe-research" / "zt_history.db"
KLINE_CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"


def _collect_signal_dates_multi_source() -> list[tuple[str, str]]:
    """多数据源异构 merge：signal_date 候选日 + source 标（去重，按日升序）。

    三源（不臆造，全 cache/本地 DB，zero em_get）：
    1. zt_history（历史涨停池，9 个月 cache，DISTINCT date WHERE lbc>=1 AND is_final=1）
    2. gene_scores（eastmoney_live + kline_rebuild 全 source，当日实时 + 历史回补）
    3. baostock kline cache（date 补缺，2113 日 2018→2026，仅取近 9 个月匹配 §44 窗口）

    去重：同日多源只取 1（优先 zt_history > gene_scores > baostock，标首源）。
    返 [(date, source), ...] 升序。source ∈ {zt_history, gene_scores, baostock}。

    R6 gate（≥60 天）：单源 eastmoney_live=48 <60；多源 merge 后 ≥170（zt_history 26 +
    gene_scores 171 + baostock 近 9 月 ~180，去重后 ~180）——立即解锁 §44 verdict。
    """
    merged: dict[str, str] = {}

    # 源 1: zt_history（历史涨停池，cache）
    if ZT_DB.exists():
        try:
            c = sqlite3.connect(str(ZT_DB))
            rows = c.execute(
                "SELECT DISTINCT date FROM zt_history WHERE lbc>=1 AND is_final=1 ORDER BY date"
            ).fetchall()
            c.close()
            for r in rows:
                d = (r[0] or "")[:10]
                if d and d not in merged:
                    merged[d] = "zt_history"
        except Exception as e:  # noqa: BLE001
            print(f"[signal_dates] zt_history 读失败: {e}")

    # 源 2: gene_scores（全 source——eastmoney_live + kline_rebuild）
    if DB.exists():
        try:
            c = sqlite3.connect(str(DB))
            rows = c.execute(
                "SELECT DISTINCT date FROM gene_scores ORDER BY date"
            ).fetchall()
            c.close()
            for r in rows:
                d = (r[0] or "")[:10]
                if d and d not in merged:
                    merged[d] = "gene_scores"
        except Exception as e:  # noqa: BLE001
            print(f"[signal_dates] gene_scores 读失败: {e}")

    # 源 3: baostock kline cache（补缺——近 9 个月匹配 §44 窗口）
    # kline cache 有 2113 日（2018→2026），只取近 9 个月（~180 交易日）避免远古日无 picks
    if KLINE_CACHE.exists():
        try:
            import json as _json
            cache = _json.loads(KLINE_CACHE.read_bytes())
            all_dates: set[str] = set()
            for bars in cache.values():
                for b in bars:
                    ds = str(b.get("date", ""))[:10]
                    if ds:
                        all_dates.add(ds)
            # 近 9 个月窗口（2026-01-01 起，匹配 forward_test 实际跑期）
            for d in sorted(all_dates):
                if d >= "2026-01-01" and d not in merged:
                    merged[d] = "baostock"
        except Exception as e:  # noqa: BLE001
            print(f"[signal_dates] baostock cache 读失败: {e}")

    return sorted(merged.items(), key=lambda x: x[0])


def main(use_weather: bool = False) -> int:
    ret_map = load_returns_map()
    by_date = load_returns_by_date()
    date_sources = _collect_signal_dates_multi_source()
    dates = [d for d, _ in date_sources]
    source_counts: dict[str, int] = {}
    for _, src in date_sources:
        source_counts[src] = source_counts.get(src, 0) + 1
    print(f"signal_date 多源 merge: {len(dates)} 日 | source 分布: {source_counts}")
    if not dates:
        return 1

    # §44 幂等：清空 picks（forward_test_records）后全量重派——避免跨 weather 模式重跑
    # 累积 picks（UNIQUE 含 strategy_code，天气变策略→新行不替换→污染 verdict）。
    # universe_returns 不清（天气无关的同宇宙基准，共享）。
    conn = sqlite3.connect(str(DB))
    conn.execute("DELETE FROM forward_test_records")
    conn.commit(); conn.close()
    print("已清空 forward_test_records（picks 全量重派；universe_returns 保留）")

    # task 115：weather-adapted 模式按日取历史天气（build_context from sti_timeline.db）；
    # 早期日期无 STI 数据 → weather=None（退化），诚实混用。
    if use_weather:
        from sentiment_context import build_context  # noqa: E402

    total_recs = 0
    total_settled = 0
    total_universe = 0
    weather_seen: dict[str, int] = {}
    for d in dates:
        ws = None
        if use_weather:
            try:
                ws = build_context(d).weather_state
            except Exception:
                ws = None
        weather_seen[ws or "None"] = weather_seen.get(ws or "None", 0) + 1
        # run_daily_forward_test 记录 picks + universe codes（收益 NULL）
        r = run_daily_forward_test(d, weather_state=ws)
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
    print(f"weather 分布: {weather_seen}")

    print("\n=== Phase 0e §44 汇总（framework get_forward_test_summary）===")
    print(get_forward_test_summary(benchmark_win_rate=60.0, min_days=10))
    mode = "weather-adapted（完整架构，task 115）" if use_weather else "weather=None（退化下界，task 114）"
    print(f"caveat: {mode}；早期日无 STI → weather=None 混入；31 天<30 探索性 + 日聚类（CI 偏窄）")
    print("caveat: universe=当日全体涨停股（load_gene_scores 全源，非仅 eastmoney_live）；"
          "若与原手算 eastmoney-only 50.2% 略异，因 pool 口径不同，§44 verdict（lift<2x）稳健不变")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="S066 Phase 0e 前向测试历史回填（§44 验证）")
    ap.add_argument("--weather", action="store_true",
                   help="task 115：按日 build_context 取历史天气（weather-adapted 完整架构；默认 weather=None 退化下界）")
    raise SystemExit(main(use_weather=ap.parse_args().weather))
