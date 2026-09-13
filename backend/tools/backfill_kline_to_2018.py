#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""baostock 回补 K 线到 2018-01-01（分批+断点续传+持续）。

当前 cache 5230 股 174 日（2025-12-25~09-11），补 2018-01-01~2025-12-24。
增量 merge（已有 date 不重拉）。断点 .vibe-research/backfill_progress.json。
用法：python tools/backfill_kline_to_2018.py [limit]  (limit=0 全量)
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.bars_provider import _load_cache

_DATA_DIR = Path(os.environ.get("VR_DATA_DIR", str(Path(__file__).resolve().parents[2] / ".vibe-research")))
CACHE_PATH = _DATA_DIR / "baostock_kline_cache.json"
PROGRESS_PATH = _DATA_DIR / "backfill_progress.json"
START = "2018-01-01"
END = "2025-12-24"
BATCH = 50  # 每批 50 股 commit 进度


def _bs_code(code: str) -> str:
    return ("sh." if code.startswith("6") else "sz.") + code


def _load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {"last_idx": 0}


def _save_progress(prog: dict) -> None:
    PROGRESS_PATH.write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")


def _save_cache(cache: dict) -> None:
    tmp = str(CACHE_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)


def backfill(limit: int = 0) -> None:
    import baostock as bs  # noqa: PLC0415
    bs.login()
    cache = _load_cache()
    codes = list(cache.keys())
    prog = _load_progress()
    start_idx = prog.get("last_idx", 0)
    print(f"# backfill: {len(codes)} 股, idx {start_idx} 起, {START}~{END}", file=sys.stderr)
    n_done = 0
    for i in range(start_idx, len(codes)):
        code = codes[i]
        existing = cache.get(code, [])
        existing_dates = {b.get("date") for b in existing}
        # 增量跳过：已有 2018 前数据则跳
        if any(d and d < "2019-01-01" for d in existing_dates):
            prog["last_idx"] = i + 1
            _save_progress(prog)
            continue
        bs_code = _bs_code(code)
        try:
            rs = bs.query_history_k_data_plus(
                bs_code, start_date=START, end_date=END,
                frequency="d", adjustflag="2",
                fields="date,open,high,low,close,volume,amount",
            )
            new_bars = []
            while rs.error_code == "0" and rs.next():
                row = rs.get_row_data()
                new_bars.append({
                    "date": row[0],
                    "open": float(row[1]) if row[1] else 0.0,
                    "high": float(row[2]) if row[2] else 0.0,
                    "low": float(row[3]) if row[3] else 0.0,
                    "close": float(row[4]) if row[4] else 0.0,
                    "volume": float(row[5]) if row[5] else 0.0,
                    "amount": float(row[6]) if row[6] else 0.0,
                })
            merged = {b["date"]: b for b in existing}
            for b in new_bars:
                if b["date"] not in merged:
                    merged[b["date"]] = b
            cache[code] = sorted(merged.values(), key=lambda x: x["date"])
        except Exception as e:  # noqa: BLE001
            print(f"# err {code}: {e}", file=sys.stderr)
        n_done += 1
        prog["last_idx"] = i + 1
        if n_done % BATCH == 0:
            _save_cache(cache)
            _save_progress(prog)
            print(f"# batch: {n_done} done, idx {i+1}/{len(codes)}", file=sys.stderr)
        if limit and n_done >= limit:
            break
        time.sleep(0.1)  # baostock 礼貌限速
    _save_cache(cache)
    _save_progress(prog)
    bs.logout()
    print(f"# backfill stop: {n_done} 股, idx {prog['last_idx']}/{len(codes)}", file=sys.stderr)


if __name__ == "__main__":
    backfill(limit=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
