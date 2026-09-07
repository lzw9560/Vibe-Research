# -*- coding: utf-8 -*-
"""S170 摘帽中线 event edge run——5 horizons verdict（复用 midline_event_harness）。

读 st_removal_events.json（scan_st_removal_history 采集）→ build_return_series +
run_event_verdict（edge_type="event"）→ 5 horizon verdict 落 Recorder + lineage。

摘帽 event edge：撤销风险警示公告后 drift（A 股摘帽效应，文献较少）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.first_board_premium_baseline import CACHE_PATH, _load_kline_cache  # noqa: E402
from tools.pead_event_study import build_calendar  # noqa: E402
from tools.midline_event_harness import run_event_verdict  # noqa: E402
from tools.scan_st_removal_history import CACHE as REMOVAL_CACHE, scan  # noqa: E402

HORIZONS = [1, 5, 10, 15, 20]
COST = 0.0070
N_COMPARISONS = 5  # 5 horizons（BH K=5 多重比较校正）


def run():
    events = scan()  # cache hit or collect（collect 25min）
    if not events:
        print("[S170] 无摘帽事件")
        return
    cache = _load_kline_cache()
    if not cache:
        print("[S170] 无 kline cache")
        return
    calendar = build_calendar(cache)
    if not calendar:
        print("[S170] 无交易日历")
        return

    frozen = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT)
    ).decode().strip()[:8]

    input_files = {
        str(REMOVAL_CACHE): "st_removal_events",
        str(CACHE_PATH): "kline_cache",
    }

    print(f"[S170] 摘帽: {len(events)} events, {len(calendar)} calendar days, frozen={frozen}")
    for N in HORIZONS:
        run_event_verdict(
            line_id=f"midline_st_removal:{N}d",
            events=events,
            kline_cache=cache,
            calendar=calendar,
            horizon=N,
            cost=COST,
            frozen_commit=frozen,
            n_comparisons=N_COMPARISONS,
            params={"event_type": "st_removal"},
            input_files=input_files,
        )


if __name__ == "__main__":
    run()
