#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S066 Q17 板块阶段修饰系数验证（数据验证码）——039 接策略分前先验证。

口径（§5.3 警告）：只在 eastmoney_live 段（kline_rebuild 日均 6.2 条系统性低计数，
板块时序不可比）。当前 ~31 天，样本不足定系数，但能判方向有无信号——
若各阶段次日收益无单调差异（启动>发酵>高潮>退潮），修饰保持 label-only（grill Q2 修订 B）；
有方向信号再接策略分 placeholder（A），60 天后回归热换。

合规（§1.2）：phase 来自 sector_cycle.analyze_sector_phase（实测 industry 列），
收益来自 backtest_samples.json（实测 next-day return），data_source 来自 gene_scores。
禁臆造/不心算。

用法：cd backend && ../.venv/bin/python tools/sector_phase_regression.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 入 sys.path

from strategies.sector_cycle import analyze_sector_phase  # noqa: E402

SAMPLES_PATH = ROOT / ".vibe-research" / "backtest_samples.json"
DB_PATH = ROOT / ".vibe-research" / "gene_scores.db"
OUT_PATH = ROOT / ".vibe-research" / "sector_phase_significance.json"

PHASES = ["启动", "发酵", "高潮", "退潮", "冷门", "无历史"]
MODIFIER = {"启动": 1.1, "发酵": 1.0, "高潮": 0.9, "退潮": 0.7, "冷门": 0.8, "无历史": 1.0}
RETURN_METRIC = "return_close2close"


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return center - half, center + half


def load_src_map() -> dict[tuple[str, str], str]:
    """(date, code) -> data_source 映射（mirror factor_regression，samples 无 data_source 字段）。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        return {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT date, code, data_source FROM gene_scores"
        ).fetchall()}
    finally:
        conn.close()


def main() -> int:
    data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    src_map = load_src_map()
    samples = []
    for s in data.get("samples", []):
        if src_map.get((s.get("date"), s.get("code"))) != "eastmoney_live":
            continue
        if not s.get("industry"):
            continue
        if s.get(RETURN_METRIC) is None:
            continue
        samples.append(s)
    print(f"eastmoney_live + 有 industry + 有 {RETURN_METRIC}: {len(samples)} 样本")
    if not samples:
        print("⚠️ 无样本，未输出。")
        return 1

    cache: dict[tuple[str, str], str] = {}

    def phase_of(date: str, industry: str) -> str:
        key = (date, industry)
        if key not in cache:
            r = analyze_sector_phase(date, industry)
            cache[key] = r.phase if r else "无历史"
        return cache[key]

    by_phase: dict[str, list[float]] = defaultdict(list)
    by_date_phase: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for s in samples:
        ret = s[RETURN_METRIC]
        ph = phase_of(s["date"], s["industry"])
        by_phase[ph].append(ret)
        by_date_phase[s["date"]][ph].append(ret)

    rows = []
    for ph in PHASES:
        rets = by_phase.get(ph, [])
        n = len(rets)
        wins = sum(1 for r in rets if r > 0)
        lo, hi = wilson_ci(wins, n)
        # within-day 截面：该阶段在每个日期的均值（≥3 只才算），再跨日均值（防日间 confound）
        per_date_avg = []
        for _d, phs in by_date_phase.items():
            rs = phs.get(ph)
            if rs and len(rs) >= 3:
                per_date_avg.append(sum(rs) / len(rs))
        rows.append({
            "phase": ph, "modifier": MODIFIER[ph], "n": n, "wins": wins,
            "winrate": round(wins / n, 4) if n else None,
            "winrate_ci": [round(lo, 4), round(hi, 4)] if n else None,
            "avg_return_pct": round(sum(rets) / n * 100, 2) if n else None,
            "within_day_avg_return_pct": round(sum(per_date_avg) / len(per_date_avg) * 100, 2) if per_date_avg else None,
            "within_day_n_dates": len(per_date_avg),
        })

    # verdict：启动>发酵>高潮>退潮 的 avg_return 单调递减？（修饰系数方向：启动1.1>退潮0.7）
    seq = [r["avg_return_pct"] for r in rows
           if r["phase"] in ("启动", "发酵", "高潮", "退潮") and r["n"] > 0]
    monotonic = all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1)) if len(seq) >= 2 else False

    out = {
        "generated_at": datetime.now().isoformat(), "metric": RETURN_METRIC,
        "eastmoney_live_days": len(by_date_phase),
        "phases": rows,
        "verdict": {
            "modifier_direction_monotonic": monotonic,
            "note": ("启动>发酵>高潮>退潮 avg_return 单调递减——方向有数据支撑，可接 placeholder（A）"
                     if monotonic else "无单调——方向无数据支撑，修饰保持 label-only（B）"),
            "caveat": f"{len(by_date_phase)} 天 eastmoney_live（Q17 需 60 天定系数）；此刻只判方向有无信号。",
        },
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n板块阶段次日收益（{RETURN_METRIC}, eastmoney_live {len(by_date_phase)} 天）:")
    print(f"{'phase':<6}{'mod':>5}{'n':>6}{'winrate':>9}{'95%CI':>20}{'avgRet%':>9}{'withinRet%':>12}{'nDates':>7}")
    for r in rows:
        ci = f"[{r['winrate_ci'][0]},{r['winrate_ci'][1]}]" if r["winrate_ci"] else "—"
        print(f"{r['phase']:<6}{r['modifier']:>5}{r['n']:>6}{str(r['winrate']):>9}{ci:>20}"
              f"{str(r['avg_return_pct']):>9}{str(r['within_day_avg_return_pct']):>12}{r['within_day_n_dates']:>7}")
    print(f"\nverdict: 修饰方向单调={monotonic} | {out['verdict']['note']}")
    print(f"输出: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
