# -*- coding: utf-8 -*-
"""股东户数变化——主力意图信号 definitive 测试。

数据：akshare stock_zh_a_gdhs_detail_em(symbol) 返回逐股完整历史（2013-2026，季度级）
信号：公告日 change_ratio<0（户数减少=筹码集中=主力吸筹）→ T+1 open 买入
口径：§44 v3 + 10 flaw 规避（entry T+1 open / close_ev / BHAR / per-day-t / Bonferroni / walk-forward / R6 / timing / cost / phantom / 退化 OLS）

Phase 1: backfill 全市场股东户数到 .vibe-research/shareholder_count_cache.json
Phase 2: §44 v3 严测
"""
from __future__ import annotations
import json
import sys
import time
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from math import erf, sqrt

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
HOLDER_CACHE = DATA / "shareholder_count_cache.json"

# arg parsing in __main__


def get_all_codes() -> list[str]:
    """从 kline cache 拿所有 6 位纯数字 code."""
    conn = sqlite3.connect(str(KLINE_DB))
    codes = [r[0] for r in conn.execute("SELECT DISTINCT code FROM kline")]
    conn.close()
    return sorted(codes)


def fetch_holder_detail(code: str):
    """akshare stock_zh_a_gdhs_detail_em 拿逐股股东户数历史."""
    try:
        import akshare as ak
        # akshare 需要 6 位 code，项目 DB 是纯数字，akshare 接受 sh/sz 前缀 or 6 位
        df = ak.stock_zh_a_gdhs_detail_em(symbol=code)
        if df is None or len(df) == 0:
            return None
        records = []
        for _, row in df.iterrows():
            rec = {
                "code": code,
                "end_date": str(row.get("股东户数统计截止日", "")),
                "holder_num": int(row["股东户数-本次"]) if row.get("股东户数-本次") is not None else None,
                "prev_num": int(row["股东户数-上次"]) if row.get("股东户数-上次") is not None else None,
                "change_ratio": float(row["股东户数-增减比例"]) if row.get("股东户数-增减比例") is not None else None,
                "notice_date": str(row.get("股东户数公告日期", "")),
                "avg_hold": float(row["户均持股数量"]) if row.get("户均持股数量") is not None else None,
                "range_pct": float(row.get("区间涨跌幅")) if row.get("区间涨跌幅") is not None else None,
            }
            records.append(rec)
        return records
    except Exception as e:
        return f"ERR: {type(e).__name__}: {str(e)[:80]}"


def backfill(limit: int = 0):
    codes = get_all_codes()
    if limit > 0:
        codes = codes[:limit]
    print(f"[backfill] {len(codes)} codes, 预计 {len(codes)*0.28/60:.1f} min")

    cache: dict[str, list] = {}
    ok = err = empty = 0
    t0 = time.time()
    for i, code in enumerate(codes):
        if i % 100 == 0 and i > 0:
            print(f"  {i}/{len(codes)} ok={ok} empty={empty} err={err} "
                  f"elapsed={time.time()-t0:.0f}s rate={i/(time.time()-t0):.1f}/s")
        res = fetch_holder_detail(code)
        if isinstance(res, str):
            err += 1
            continue
        if res is None or len(res) == 0:
            empty += 1
            continue
        cache[code] = res
        ok += 1
        time.sleep(0.15)  # 限流防封

    with open(HOLDER_CACHE, "w") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"\n[done] ok={ok} empty={empty} err={err} "
          f"total={len(codes)} elapsed={time.time()-t0:.0f}s")
    print(f"[saved] {HOLDER_CACHE} ({HOLDER_CACHE.stat().st_size/1024:.0f}KB)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        backfill(n)
    elif len(sys.argv) > 1 and sys.argv[1] == "codes":
        codes = get_all_codes()
        print(f"total codes: {len(codes)}")
        print("first 10:", codes[:10])
    else:
        print("用法:")
        print("  backfill [N]  - backfill N 股（0=全量）")
        print("  codes         - 显示总股数")
