#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""baostock_kline_cache.json 增量刷新器（S071 数据地基）。

cache 缺生产方（原 backfill_kline_samples.py 已不在仓库），本脚为唯一生产/刷新方。
增量：每股从其最新 bar 之后拉到 last_trading_date，只 append 新 bar（date > newest）。
原子写（temp→rename）防中断损坏 31MB cache。re-login 防 BaoStock 长会话超时返空。

baostock 非东财，不被 IP 限流（§44 grill 资金流被 push2his 限流，kline 不受影响）。
用法：cd backend && .venv/bin/python tools/refresh_kline_cache.py [--max N]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg,isST"

# 每 RELOGIN_BATCH 股 re-login 一次（BaoStock 长会话超时返空）
RELOGIN_BATCH = 150
# T21 R20：新股全量拉取起点（扩容到非涨停股时，cache 无此 code 的从此日起拉）
FULL_START = "2025-12-25"


def _bs_code(code: str) -> str:
    if not code or len(code) != 6:
        return ""
    return f"sh.{code}" if code.startswith("6") else f"sz.{code}"


def _last_trading_date() -> str:
    """最近交易日（周末/节假日回退）。优先 vr_paths，失败返今日。"""
    try:
        from vr_paths import last_trading_date_str
        return last_trading_date_str()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _fetch_since(bs_code: str, start_date: str, end_date: str, bs) -> list[dict]:
    """baostock qfq 日K（start..end）。返 bars（全部字段）。空/错返 []。"""
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, FIELDS, start_date=start_date, end_date=end_date, adjustflag="2",
        )
    except Exception:
        return []
    if rs.error_code != "0":
        return []
    bars: list[dict] = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({
                "date": d[0],
                "open": float(d[1]) if d[1] else 0.0,
                "high": float(d[2]) if d[2] else 0.0,
                "low": float(d[3]) if d[3] else 0.0,
                "close": float(d[4]) if d[4] else 0.0,
                "volume": float(d[5]) if d[5] else 0.0,
                "amount": float(d[6]) if d[6] else 0.0,
                "turn": float(d[7]) if d[7] else 0.0,
                "pctChg": float(d[8]) if d[8] else 0.0,
                "isST": d[9] if len(d) > 9 and d[9] else "0",
            })
        except (ValueError, IndexError):
            continue
    return bars


def main(max_stocks: int | None = None) -> int:
    # T21 R20：cache 不存在时建空（首次全 A 扩容），不再 return 1
    cache: dict[str, list[dict]] = (
        json.loads(CACHE.read_bytes()) if CACHE.exists() else {}
    )
    end_date = _last_trading_date()
    # T21 R20：universe = load_industry_map() 全 A（~5540），非增量 list(cache.keys())
    try:
        from strategies.pattern_scan import load_industry_map
        codes = list(load_industry_map().keys())
    except Exception as e:
        print(f"[refresh] load_industry_map 失败，降级增量 list(cache.keys()): {e}")
        codes = list(cache.keys())
    # S094 audit LOW: universe 空(load_industry_map 返空 + cache 空,baostock login 失败?)→ 中止不写回,避免伪装成功
    if not codes:
        print(f"[refresh] universe 空(load_industry_map+cache 均空),中止不写回(防伪装成功)")
        return 1
    if max_stocks:
        codes = codes[:max_stocks]

    try:
        import baostock as bs
    except ImportError:
        print("[refresh] baostock 未安装")
        return 1

    def _login():
        lg = bs.login()
        return getattr(lg, "error_code", "0") == "0"

    if not _login():
        print("[refresh] baostock login 失败")
        return 1

    updated = 0
    skipped = 0
    new_codes_added = 0
    new_bars_total = 0
    t0 = time.time()

    try:
        for i, code in enumerate(codes):
            if i and i % RELOGIN_BATCH == 0:
                try:
                    bs.logout()
                except Exception:
                    pass
                if not _login():
                    print(f"[refresh] re-login 失败 @ {i}, 中止")
                    break
                print(f"[refresh] re-login @ {i}/{len(codes)} elapsed={time.time()-t0:.0f}s")

            existing = cache.get(code)
            if existing:
                newest = existing[-1]["date"] if existing else FULL_START
                if newest >= end_date:
                    skipped += 1
                    continue
                start = (datetime.strptime(newest, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # T21 R20：新股（非涨停股扩容）——cache 无此 code，从 FULL_START 全量拉
                newest = ""
                start = FULL_START
            bsc = _bs_code(code)
            if not bsc:
                continue
            new_bars = _fetch_since(bsc, start, end_date, bs)
            if not new_bars:
                # re-login 重试一次（长会话超时返空）
                if not _login():
                    continue
                new_bars = _fetch_since(bsc, start, end_date, bs)
            if not new_bars:
                continue
            if existing:
                # 只 append 严格新于 newest 的 bar
                appended = [b for b in new_bars if b["date"] > newest]
                if appended:
                    cache[code] = existing + appended
                    new_bars_total += len(appended)
                    updated += 1
            else:
                # T21 R20：新股全量插入
                cache[code] = new_bars
                new_bars_total += len(new_bars)
                new_codes_added += 1

            if (i + 1) % 100 == 0:
                print(f"[refresh] {i+1}/{len(codes)} updated={updated} new={new_codes_added} "
                      f"new_bars={new_bars_total} elapsed={time.time()-t0:.0f}s", flush=True)
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    # 原子写：temp → rename
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    tmp.replace(CACHE)

    print(f"[refresh] done: {updated}/{len(codes)} updated, {new_codes_added} new codes, "
          f"{new_bars_total} new bars, {skipped} already-fresh, elapsed={time.time()-t0:.0f}s")
    print(f"[refresh] end_date={end_date} cache_size={len(cache)} "
          f"newest now={max((b['date'] for c in cache.values() for b in c[-1:]), default='?')}")
    return 0


if __name__ == "__main__":
    mx = None
    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        mx = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else None
    raise SystemExit(main(mx))
