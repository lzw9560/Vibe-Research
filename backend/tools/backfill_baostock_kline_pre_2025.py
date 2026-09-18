# -*- coding: utf-8 -*-
"""backfill baostock cache 早期 bars（pre-2025-06）——解 S218 #3 ×1.0 真 blocker。

问题：bear chrono train third（2024-06..2025-12）bar 覆盖率仅 28.4%（pre-2025-06-03
picks 762/2685 有 bars）。baostock cache 多数股最早 bar=2025-06-01（老 backfill
START=2025-06-01 只填前向 gap，不补 pre-2025-06 历史）→ train third picks 的 D_idx
is None → compute_obs 跳过 → train 稀疏 → train_mean=-0.074% 几乎确定是稀疏/偏选
bars artifact（老股有缓存、新 IPO 无）。

本脚本：对 pre-2025-06-03 lbc>=2 picks 的 codes，补 2024-06-01..existing_earliest
（或 2025-12-31 如无 cache）的 baostock 日K bars，enrich_pctchg 后 dedup-merge 进
baostock_kline_cache.json。覆盖完整 train third（2024-06..2025-12）。

不臆造——baostock 真实 bars，缺数据返 [] 跳过。baostock 不封 IP，sleep 0.3s/股限流。
不碰 harness 逻辑/evaluation.py——只补 cache 数据 + 原子写。
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
START = "2024-06-01"
# 覆盖 train third（team-lead 测 bear train third = 2024-06..2025-12）。
# 有 existing earliest 的股 fetch 到 earliest（gap-fill 最小 overlap）；
# 无 cache 的股 fetch 到 2026-09-18（today，含 test third 防 no-cache 股缺 2026 bars）。
END_DEFAULT = "2025-12-31"
END_TODAY = "2026-09-18"


def _codes_needing_backfill(cache: dict) -> list[tuple[str, str | None]]:
    """train-third（2024-06..2025-12）lbc>=2 picks 的 codes，仅取 cache earliest > 该股最早 pick
    date 或无 cache 的（gap-fill 精确判据——已 backfill 股 earliest<=first_pick 自动跳过）。

    返 [(code, existing_earliest_or_None), ...]。
    """
    conn = sqlite3.connect(str(DB))
    # train third 全量 picks（team-lead 测 bear train third = 2024-06..2025-12）
    rows = conn.execute(
        "SELECT date, code FROM zt_history "
        "WHERE date>='2024-06-01' AND date<='2025-12-31' "
        "AND lbc>=2 AND is_final=1"
    ).fetchall()
    conn.close()

    # 每股最早 pick date
    first_pick: dict[str, str] = {}
    for D, code in rows:
        if code not in first_pick or D < first_pick[code]:
            first_pick[code] = D

    need: list[tuple[str, str | None]] = []
    for c, fp in first_pick.items():
        bars = cache.get(c, [])
        if not bars:
            need.append((c, None))
            continue
        earliest = str(bars[0].get("date", ""))[:10]
        # cache 已覆盖到 first pick date 或更早 → 跳过（已 backfill 股 earliest<=fp）
        if earliest <= fp:
            continue
        need.append((c, earliest))
    return need


def _save(cache: dict) -> None:
    """原子写 cache（tmp + replace，防半写损坏 435MB）。"""
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    tmp.replace(CACHE)


def main() -> None:
    print(f"[backfill] loading cache ({CACHE.stat().st_size // 1_000_000}MB)...", flush=True)
    cache = json.loads(CACHE.read_bytes())
    print(f"[backfill] cache codes={len(cache)}", flush=True)

    need = _codes_needing_backfill(cache)
    print(f"[backfill] 需 backfill: {len(need)} 股（earliest>{START} 或无 cache）", flush=True)
    if not need:
        print("[backfill] 无需 backfill", flush=True)
        return

    ensure_login()
    n_filled = 0
    n_bars_added = 0
    n_failed = 0
    t0 = time.time()
    for i, (code, earliest) in enumerate(need):
        prefix = "sh." if code.startswith("6") else "sz."
        bs_code = prefix + code
        # gap-fill：fetch START → existing earliest（dedup 兜底 overlap）；
        # 无 cache → fetch 到 today（含 test third bars 防 no-cache 缺 2026）
        end = earliest or END_TODAY
        # 有 earliest 但 earliest > END_DEFAULT（如 2025-12）的也 fetch 到 earliest（gap-fill 到 existing）
        try:
            bars = fetch_daily_bars(bs_code, START, end)
            if bars:
                bars = enrich_pctchg(bars)  # S204 T1：一字板 pctChg=0.0 复算覆盖防误判可买
                existing = cache.get(code, [])
                existing_dates = {b["date"][:10] for b in existing}
                new_bars = [b for b in bars if b["date"][:10] not in existing_dates]
                if new_bars:
                    cache[code] = sorted(
                        new_bars + existing, key=lambda b: b["date"][:10]
                    )
                    n_filled += 1
                    n_bars_added += len(new_bars)
                time.sleep(0.3)
            else:
                # baostock 返空（新股/IPO 在 START 之后上市，无 pre 数据）——不臆造
                n_failed += 1
                time.sleep(0.2)
        except Exception as e:  # noqa: BLE001
            print(f"  {code} 失败: {e}", flush=True)
            n_failed += 1
            time.sleep(0.5)
            continue

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(need) - i - 1) / rate if rate > 0 else 0
            print(
                f"  {i+1}/{len(need)}: filled={n_filled} +{n_bars_added} bars "
                f"failed={n_failed} | {elapsed:.0f}s elapsed ETA {eta:.0f}s",
                flush=True,
            )
            _save(cache)  # 周期存盘防 crash 丢 25min 工作

    _save(cache)
    print(
        f"\n[backfill] 完成: {n_filled} 股 +{n_bars_added} bars "
        f"({n_failed} 股无数据/失败) in {time.time()-t0:.0f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
