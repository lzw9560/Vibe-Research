# -*- coding: utf-8 -*-
"""S170 摘帽历史公告采集——扫全 A 5226 股历史公告找"撤销风险警示"事件。

em_get announcements(code, limit=200) per 股 × 5226 = ~25min（0.3s/次限流）。
过滤 _ZHAIMAO_KEYWORDS（撤销风险警示/摘帽），排除"申请撤销"（待批非生效）。
缓存 .scratch/s170-st-removal/st_removal_events.json（{code, notice_date, title}）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from candidate_funnel.sources.st_play_radar import _ZHAIMAO_KEYWORDS  # noqa: E402
from data.sources.eastmoney import announcements  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402

CACHE = ROOT / "backend" / ".scratch" / "s170-st-removal" / "st_removal_events.json"


def scan():
    if CACHE.exists():
        data = json.loads(CACHE.read_bytes())
        print(f"[S170] cache hit: {len(data)} 摘帽 events")
        return data
    cache = _load_kline_cache()
    if not cache:
        print("[S170] 无 kline cache")
        return []
    codes = sorted(cache.keys())
    print(f"[S170] 扫 {len(codes)} 股历史公告找摘帽事件...")
    events: list[dict] = []
    t0 = time.time()
    for i, code in enumerate(codes):
        try:
            anns = announcements(code, limit=200)
        except Exception:
            anns = []
        for a in anns:
            title = a.get("title", "")
            if any(kw in title for kw in _ZHAIMAO_KEYWORDS):
                # 排除"申请撤销"（待批非生效，只取已生效的撤销）
                if "申请" in title:
                    continue
                events.append({
                    "code": code,
                    "pub_date": a.get("date", ""),
                    "notice_date": a.get("date", ""),
                    "title": title,
                })
        if (i + 1) % 200 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(codes)} events={len(events)} "
                  f"elapsed={el:.0f}s eta={el/(i+1)*(len(codes)-i-1):.0f}s", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[S170] collected {len(events)} 摘帽 events in {time.time()-t0:.0f}s → {CACHE}")
    return events


if __name__ == "__main__":
    scan()
