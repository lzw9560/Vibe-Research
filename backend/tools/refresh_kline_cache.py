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

from data.sources.baostock_src import fetch_daily_bars, ensure_login, logout, DependencyMissing

CACHE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg,isST"

# 每 RELOGIN_BATCH 股 re-login 一次（BaoStock 长会话超时返空）
RELOGIN_BATCH = 150
# T21 R20：新股全量拉取起点（扩容到非涨停股时，cache 无此 code 的从此日起拉）
FULL_START = "2025-10-13"  # S188 扩到 250 天回溯（gap 250 复验用，2026-09-12 改）


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


def _resolve_refresh_end_date(default_end: str, fetch_fn) -> tuple[str, bool]:
    """当日 bar 就绪检：未就绪回退到前一交易日，返 (end_date, skipped_today)。

    baostock 17:00+ 才更新当日 bar。kline_refresh 17:15 cron 跑时当日 bar
    可能未就绪。未就绪时回退到 prev_trading_date 继续刷新（不跳过整轮——
    前几天 bars 仍需补，否则 cache 停在上次成功日期越积越 stale）。

    Args:
        default_end: 默认 end_date（last_trading_date，今天交易日）
        fetch_fn: fetch_daily_bars 签名的 callable（code, start, end）

    Returns:
        (end_date, skipped_today): end_date 用于 refresh；skipped_today=True
        时当日 bar 未就绪（用前一天数据刷）。
    """
    test_bars = fetch_fn("sh.600000", default_end, default_end)
    if not test_bars:
        from vr_paths import prev_trading_date_str
        prev = prev_trading_date_str()
        print(f"[refresh] baostock 当日 bar 未就绪 end_date={default_end}，回退到 {prev}（刷前一天数据，不跳过整轮）")
        return prev, True
    return default_end, False


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

    # C3 fix：baostock login 加 3 次重试 + backoff（17:15 登录偶发失败无重试致整轮跳过 cache degraded）
    for attempt in range(3):
        try:
            ensure_login()
            break
        except (ImportError, DependencyMissing) as e:
            if attempt == 2:
                print(f"[refresh] baostock login 3 次失败: {e}")
                return 1
            time.sleep(2 ** attempt)  # 1s, 2s backoff

    # S184 grill（方案 0）：数据就绪预检——baostock 当日 bar 17:00+ 更新。
    # 未就绪时回退到前一交易日继续刷新（不跳过整轮——前几天 bars 仍需补，
    # 否则 cache 停在上次成功日期越积越 stale，v3 审查发现停 09-16 达 3 天）。
    end_date, _skipped_today = _resolve_refresh_end_date(end_date, fetch_daily_bars)

    updated = 0
    skipped = 0
    new_codes_added = 0
    new_bars_total = 0
    t0 = time.time()

    try:
        for i, code in enumerate(codes):
            if i and i % RELOGIN_BATCH == 0:
                logout()
                try:
                    ensure_login()
                except (ImportError, DependencyMissing):
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
            new_bars = fetch_daily_bars(bsc, start, end_date)
            if not new_bars:
                # re-login 重试一次（长会话超时返空）
                logout()
                try:
                    ensure_login()
                except (ImportError, DependencyMissing):
                    continue
                new_bars = fetch_daily_bars(bsc, start, end_date)
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
        logout()

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
