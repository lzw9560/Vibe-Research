# -*- coding: utf-8 -*-
"""S169 PEAD 中线 event edge run——3 arms × 5 horizons = 15 verdict。

复用 pead_event_study.collect_forecast_reports（数据已缓存 forecast_reports.json
4972 事件 130 天）+ midline_event_harness.run_event_verdict。

修正 pead_event_study category mismatch（selection lift → event t-test）。
预期全 falsified（A 股预告后 drift 为负，与美国文献正漂移相反——散户主导+T+1+涨跌停闸门）。

n_comparisons=15（3 arms × 5 horizons，BH K=15 多重比较校正，verifier event 分支已加）。
input_files 传 forecast_reports + kline_cache hash（grill #5 复现锚点）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.pead_event_study import (  # noqa: E402
    BAD_NEWS_TYPES,
    CACHE_PATH,
    FORECAST_CACHE,
    GOOD_NEWS_TYPES,
    build_calendar,
    collect_forecast_reports,
)
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402
from tools.midline_event_harness import run_event_verdict  # noqa: E402

HORIZONS = [1, 5, 10, 15, 20]
COST = 0.0070  # decimal，非 0.70 百分比（与 gap run decimal 制一致）
N_COMPARISONS = 15  # 3 arms × 5 horizons（BH K=15 多重比较校正）


def run():
    events = collect_forecast_reports()  # 读 cache，0 收集
    if not events:
        print("[S169] 无预告事件（forecast_reports.json 空）")
        return
    cache = _load_kline_cache()
    if not cache:
        print("[S169] 无 kline cache")
        return
    calendar = build_calendar(cache)
    if not calendar:
        print("[S169] 无交易日历")
        return

    frozen = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT)
    ).decode().strip()[:8]

    arms = {
        "all": events,
        "good_news": [e for e in events if e.get("ftype") in GOOD_NEWS_TYPES],
        "bad_news": [e for e in events if e.get("ftype") in BAD_NEWS_TYPES],
    }

    input_files = {
        str(FORECAST_CACHE): "forecast_reports",
        str(CACHE_PATH): "kline_cache",
    }

    print(f"[S169] PEAD: {len(events)} events "
          f"({sum(len(v) for v in arms.values()) if False else len(events)} total, "
          f"good={len(arms['good_news'])} bad={len(arms['bad_news'])}), "
          f"{len(calendar)} calendar days, frozen={frozen}")
    for arm_name, arm_events in arms.items():
        for N in HORIZONS:
            run_event_verdict(
                line_id=f"midline_pead:{arm_name}:{N}d",
                events=arm_events,
                kline_cache=cache,
                calendar=calendar,
                horizon=N,
                cost=COST,
                frozen_commit=frozen,
                n_comparisons=N_COMPARISONS,
                params={"event_type": "pead", "arm": arm_name},
                input_files=input_files,
            )


if __name__ == "__main__":
    run()
