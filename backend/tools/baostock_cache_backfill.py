# -*- coding: utf-8 -*-
"""backfill baostock cache 更早 bars——consecutive_relay picks 去重股从 2025-06-01 补。

verdict 现受 cache 174 天限制（zt_history 315 天但 verdict 只用 78 天 obs）。
backfill 324 股（cache 最早 >= 2025-06-01）更早 bars 让 verdict 用满 315 天。

new_bars enrich_pctchg（0.0 复算覆盖，防一字板误判——harness 用 cache 直读不 enrich）。
baostock 不封 IP，sleep 0.3s/股限流。不碰 em_get。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data.sources.baostock_src import fetch_daily_bars, ensure_login  # noqa: E402
from engine.pctchg_injector import enrich_pctchg  # noqa: E402

CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
DB = ROOT / ".vibe-research" / "zt_history.db"
START = "2025-06-01"


def main() -> None:
    cache = json.loads(CACHE.read_bytes())
    conn = sqlite3.connect(str(DB))
    codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT code FROM zt_history WHERE lbc>=2 AND lbc<=3 AND is_final=1"
    ).fetchall()]
    conn.close()

    need: list[tuple[str, str | None]] = []
    for c in codes:
        bars = cache.get(c, [])
        if bars:
            earliest = bars[0].get("date", "")[:10]
            if earliest >= START:
                need.append((c, earliest))
        else:
            need.append((c, None))  # 无 cache 全补

    print(f"[backfill] 需 backfill: {len(need)} 股（cache 最早 >= {START}）", flush=True)
    ensure_login()
    n_filled = 0
    n_bars_added = 0
    for i, (code, earliest) in enumerate(need):
        prefix = "sh." if code.startswith("6") else "sz."
        bs_code = prefix + code
        end = earliest or "2025-12-25"
        try:
            bars = fetch_daily_bars(bs_code, START, end)
            if bars:
                bars = enrich_pctchg(bars)  # 0.0 复算覆盖防一字板误判
                existing = cache.get(code, [])
                existing_dates = {b["date"][:10] for b in existing}
                new_bars = [b for b in bars if b["date"][:10] not in existing_dates]
                if new_bars:
                    cache[code] = sorted(new_bars + existing, key=lambda b: b["date"][:10])
                    n_filled += 1
                    n_bars_added += len(new_bars)
                time.sleep(0.3)
            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(need)}: filled={n_filled} +{n_bars_added} bars", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {code} 失败: {e}", flush=True)
            time.sleep(0.5)

    tmp = CACHE.with_suffix(".tmp")
    tmp.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    tmp.replace(CACHE)
    print(f"\n[backfill] 完成: {n_filled} 股 +{n_bars_added} bars", flush=True)


if __name__ == "__main__":
    main()
