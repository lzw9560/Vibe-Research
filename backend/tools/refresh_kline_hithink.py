# -*- coding: utf-8 -*-
"""refresh_kline_hithink: hithink-finance CLI 刷 21 picks K 线 → kline_cache_store。

短期数据 fix（tools/ 级，免 spec）：baostock 黑名单 + 东财 IP 封刷不了，
hithink CLI 立即可用。cache 停在 09-18，daily_report 09-23 01:26 fire 21 picks
全"别碰"（缺 09-22 bar）。本脚本用 hithink 刷 21 picks cache 到 09-22。

流程：hithink CLI 拉 bars → 转 dict（date/open/high/low/close/volume/amount）
→ merge 进 existing cache（保留 turn/isST）→ enrich_pctchg 算 pctChg
→ upsert_many 注入 SQLite。

工程底线：不臆造——CLI 失败标 missing 不编，log warning + 继续。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # repo root
sys.path.insert(0, str(ROOT / "backend"))

from engine.kline_cache_store import get_bars, invalidate, upsert_many  # noqa: E402
from engine.pctchg_injector import enrich_pctchg  # noqa: E402

# 21 picks codes (09-22 连板股，daily_report 09-23 01:26 fire)
PICKS: list[str] = [
    "000607", "000756", "002614", "600743", "600825",
    "601811", "603636", "001234", "002303", "600664",
    "000560", "001317", "603020", "002178", "603580",
    "603068", "002259", "600721", "300110", "000910",
    "600503",
]

# hithink CLI 日期范围 (UTC ms, UTC+8)
# 1789660800000 = 2026-09-18, 1790092800000 = 2026-09-23
START_MS = 1789660800000
END_MS = 1790092800000

# UTC+8 时区（A 股交易日）
_TZ_CN = timezone(timedelta(hours=8))


def to_thscode(code: str) -> str:
    """A 股代码转同花顺 thscode：6→.SH / 0,3→.SZ / 8,4→.BJ。"""
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("8", "4")):
        return f"{code}.BJ"
    raise ValueError(f"未知 code 前缀: {code}")


def fetch_hithink_bars(thscode: str) -> list[dict[str, Any]]:
    """subprocess 调 hithink-finance CLI 拉 K 线，返 bars dict list。

    CLI 失败 raise（调用方 catch + log warning + 继续，不静默吞错）。
    """
    cmd = [
        "hithink-finance", "market", "history",
        "--thscode", thscode,
        "--start-ms", str(START_MS),
        "--end-ms", str(END_MS),
        "--adjust", "none",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"exit={result.returncode} stderr={result.stderr[:200]}")
    data = json.loads(result.stdout)
    if not data.get("ok"):
        raise RuntimeError(f"ok=false: {data}")
    items = data.get("data", {}).get("item", [])
    if not items:
        raise RuntimeError("返 0 bars")
    bars: list[dict[str, Any]] = []
    for item in items:
        dt = datetime.fromtimestamp(item["date_ms"] / 1000, tz=_TZ_CN)
        bars.append({
            "date": dt.strftime("%Y-%m-%d"),
            "open": item["open_price"],
            "high": item["high_price"],
            "low": item["low_price"],
            "close": item["close_price"],
            "volume": float(item["volume"]),
            "amount": float(item["turnover"]),
        })
    return bars


def merge_bars(
    existing: list[dict[str, Any]], new_bars: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """merge hithink bars into existing cache bars（immutable，返新 list）。

    - Dedup by date: hithink OHLCV overrides existing（fresh data）
    - 保留 existing 的 turn/isST（overlapping dates）
    - 新 date：turn=0.0, isST="0"（不臆造，标 unknown）
    - pctChg 不在此算——enrich_pctchg 统一注入
    - 按 date 排序
    """
    by_date: dict[str, dict[str, Any]] = {b["date"]: b for b in existing}
    for nb in new_bars:
        date = nb["date"]
        if date in by_date:
            # hithink OHLCV override，保留 existing 的 turn/isST/pctChg
            by_date[date] = {**by_date[date], **nb}
        else:
            # 新 date：turn/isST 标 unknown（不臆造）
            by_date[date] = {**nb, "turn": 0.0, "isST": "0"}
    return sorted(by_date.values(), key=lambda b: b["date"])


def main() -> None:
    print(
        f"[refresh_kline_hithink] 21 picks, range={START_MS}..{END_MS}",
        flush=True,
    )
    items: list[tuple[str, list[dict[str, Any]]]] = []
    failed: list[str] = []
    for i, code in enumerate(PICKS):
        ths = to_thscode(code)
        try:
            new_bars = fetch_hithink_bars(ths)
            existing = get_bars(code)
            merged = merge_bars(existing, new_bars)
            enriched = enrich_pctchg(merged)
            items.append((code, enriched))
            latest = enriched[-1]["date"] if enriched else "?"
            print(
                f"  [{i + 1}/21] {code} ({ths}): "
                f"+{len(new_bars)} bars, total={len(enriched)}, latest={latest}",
                flush=True,
            )
            time.sleep(0.2)  # gentle rate limit
        except Exception as e:  # noqa: BLE001
            print(f"  [{i + 1}/21] {code} ({ths}) FAILED: {e}", flush=True)
            failed.append(code)
    if not items:
        print("[refresh_kline_hithink] 全部失败，无 upsert", flush=True)
        return
    n = upsert_many(items)
    invalidate()
    print(
        f"\n[refresh_kline_hithink] upsert {n} codes, "
        f"failed={failed or 'none'}",
        flush=True,
    )
    for code, bars in items:
        latest = bars[-1]["date"] if bars else "?"
        print(f"  {code}: {len(bars)} bars, latest={latest}")


if __name__ == "__main__":
    main()
