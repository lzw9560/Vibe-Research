# -*- coding: utf-8 -*-
"""intraday executors——封单采集/微结构快照/竞价密集/5min 冻结。"""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Dict

from scheduler.db import _SEAL_COLLECT_SUBPROCESS_TIMEOUT

logger = logging.getLogger("vibe-research")


def seal_intraday_collect(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S055：盘中封单时序采集（S150 T0.7 根治：subprocess 跑全逻辑）。

    全逻辑（prune + collect_once + rules + trajectory/derived）在子进程跑——
    asyncio 线程（run_in_executor/to_thread）不可中断，R1 wait_for 超时后底层线程
    继续跑：孤儿线程并发 em_get（rate limiter TOCTOU→跳限流→IP 封禁，HIGH1）+ 写库
    （INSERT OR REPLACE 覆盖 seal_derived/intraday_features 陈旧派生 / bomb_alert_history
    重复行 / 若线程持 _DB_LOCK 瞬间超时→锁泄漏死线程永久持有→后续 collect_once 永久
    阻塞 acquire()，HIGH3）。subprocess.run(timeout=110) 超时 SIGKILL 子进程，OS 回收
    DB 连接+lock，根治孤儿线程+死锁。逻辑在 risk.seal_intraday_collect_cli（线程→子进程，
    逻辑不变）。timeout=110 < R1 wait_for 120 避免竞态（subprocess 先 kill+线程返回）。
    """
    import json as _json

    backend_dir = str(Path(__file__).resolve().parents[2])
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "risk.seal_intraday_collect_cli"],
            input=_json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, timeout=_SEAL_COLLECT_SUBPROCESS_TIMEOUT, cwd=backend_dir,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"collect subprocess timeout {_SEAL_COLLECT_SUBPROCESS_TIMEOUT}s (SIGKILL, no orphan thread)",
                "timeout": True, "date": _dt.now().strftime("%Y-%m-%d")}
    try:
        result = _json.loads(proc.stdout) if proc.stdout.strip() else {}
    except _json.JSONDecodeError:
        result = {"error": f"subprocess stdout not JSON: {(proc.stdout or '')[-200:]}"}
    if proc.returncode != 0:
        result.setdefault(
            "error", f"subprocess exit {proc.returncode}: {(proc.stderr or '')[-200:]}")
    return result


def ofi_collect(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S176 R5 — 盘中 OFI 五档收集（cron `* 9-14 * * 1-5`）。

    payload: {codes: [...], regime: str}（codes 来自 zt_pool/premarket，executor 调方提供；
    生产 wiring 取 zt_pool 涨停股另接）。tencent fetch_raw（不封 IP 无限流）→
    collect_ofi_for_codes → save_ofi（intraday_accumulation_store，不喂 trade_journal）。
    返 {n_codes, n_collected, n_skipped}。
    """
    from engine.intraday_ofi_collector import collect_ofi_for_codes  # noqa: PLC0415
    from vr_paths import last_trading_date_str  # noqa: PLC0415

    codes = payload.get("codes") or []
    if not codes:
        return {"n_codes": 0, "n_collected": 0, "n_skipped": 0,
                "note": "no codes in payload（生产 wiring 取 zt_pool 另接）"}
    date = last_trading_date_str()
    ts = _dt.now().strftime("%H:%M")
    regime = payload.get("regime")
    return collect_ofi_for_codes(codes, date, ts, regime)


def intraday_microstructure_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S167 盘中微结构周期快照——每 10min 快照 hithink 排名 + tencent 量比 +
    集合竞价 → 累积 DB。

    cron `*/10 9-15 * * 0-4` 触发，executor 内 ``vr_paths.is_intraday_time``
    （09:25-11:30 / 13:01-15:05）∪ ``is_auction_time``（09:15-09:25）门控——
    两窗口外 no-op（防封 + 省请求）。竞价窗口（盘前未开盘）只采竞价 live 演化，
    跳过排名/量比（无意义）；盘中窗口采排名 + 量比 + 竞价 final 终态（守门只采
    一次，避免静态终态伪 trajectory）。涨停池 codes 走 hithink ``limit_up_pool``
    （非 em_get 防封）；hithink 端点走 circuit_breaker，失败记 data_status=degraded
    不抛（S120：skyrocket/hot_stock/anomaly_list 失败 raise RuntimeError，此处 catch）。
    tencent urllib 免费不限流。

    竞价 codes 取 ``prev_trading_date`` 涨停池（昨日涨停 = 今日竞价 continuation
    候选集，§44 reframe 标记的最未证否盘中 edge）；盘中 ranking/quote codes 取
    ``last_trading_date``（今日 forming 涨停池，今日空属正常）。
    """
    from vr_paths import is_intraday_time, is_auction_time, last_trading_date_str, prev_trading_date_str
    now = _dt.now()
    intraday = is_intraday_time(now)
    auction = is_auction_time(now)
    if not intraday and not auction:
        return {"status": "skipped", "reason": "非盘中交易时段且非竞价时段"}

    from data.sources import hithink_src
    from data.sources.tencent import fetch_raw
    from data.intraday_accumulation_store import (
        save_ranking_snapshots, save_quote_snapshots, save_auction_snapshots,
        has_auction_snapshot,
    )

    date = last_trading_date_str()
    ts = now.strftime("%Y-%m-%dT%H:%M")
    degraded: list[str] = []

    # 1. hithink 三榜（飙升/热股/异动）——仅盘中（竞价窗口盘前未开盘，无意义）
    ranking_items: dict[str, list[dict]] = {}
    if intraday:
        for source, fn in (
            ("skyrocket", hithink_src.skyrocket),
            ("hot_stock", hithink_src.hot_stock),
            ("anomaly", hithink_src.anomaly_list),
        ):
            try:
                ranking_items[source] = fn()
            except RuntimeError as e:
                degraded.append(f"{source}: {str(e)[:60]}")
                ranking_items[source] = []
            except Exception as e:  # noqa: BLE001
                degraded.append(f"{source}: {type(e).__name__}")
                ranking_items[source] = []
        for source, items in ranking_items.items():
            save_ranking_snapshots(date, ts, source, items)
    else:
        ranking_items = {"skyrocket": [], "hot_stock": [], "anomaly": []}

    # 2. tencent 量比——涨停池 codes ∪ 排名 codes，一次批量（仅盘中）
    quotes: dict[str, dict] = {}
    zt_codes: list[str] = []
    if intraday:
        try:
            zt_codes = [r["code"] for r in hithink_src.limit_up_pool(date) if r.get("code")]
        except Exception:  # noqa: BLE001 — hithink 涨停池失败不影响排名快照
            pass
        rank_codes = {it["code"] for items in ranking_items.values() for it in items if it.get("code")}
        quote_codes = list({*zt_codes, *rank_codes})
        quotes = fetch_raw(quote_codes) if quote_codes else {}
        save_quote_snapshots(date, ts, quotes)

    # 3. hithink 集合竞价快照——§44 reframe 标记的最未证否盘中 edge（auction_volume_ratio）
    #    竞价窗口取 live（9:15-9:25 trajectory），盘中首周期取 final（09:25 match 终态，
    #    守门只采一次避免静态终态伪 trajectory）。codes 取 prev 涨停池（continuation 候选集）。
    auction_stage = "live" if (auction and not intraday) else "final"
    auction_items: list[dict] = []
    fetch_final = auction_stage == "final" and not has_auction_snapshot(date, "final")
    if auction or fetch_final:
        # 竞价 codes：prev_trading_date 涨停池（昨日涨停 = 今日竞价 continuation 候选）
        auction_codes: list[str] = []
        try:
            auction_codes = [r["code"] for r in hithink_src.limit_up_pool(prev_trading_date_str())
                             if r.get("code")]
        except Exception as e:  # noqa: BLE001 — 涨停池失败则竞价 codes 空，跳过竞价
            degraded.append(f"auction_pool: {type(e).__name__}")
        if auction_codes:
            try:
                auction_items = hithink_src.auction_snapshot(auction_codes, stage=auction_stage)
            except Exception as e:  # noqa: BLE001
                degraded.append(f"auction_{auction_stage}: {type(e).__name__}")
        save_auction_snapshots(date, ts, auction_stage, auction_items)

    ok = any(ranking_items.values()) or bool(quotes) or bool(auction_items)
    return {
        "date": date, "ts": ts,
        "rankings": {s: len(v) for s, v in ranking_items.items()},
        "quotes": len(quotes), "zt_codes": len(zt_codes),
        "auction": {"stage": auction_stage, "count": len(auction_items)},
        "data_status": "degraded" if degraded else ("ok" if ok else "empty"),
        "degraded_sources": degraded,
    }


def intraday_auction_dense(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S167 竞价密集采集——09:15-09:25 每 2min 采 auction_snapshot(live) 累积 trajectory。

    比 ``intraday_microstructure_snapshot`` 更密（cron */2 vs */10），但只采竞价
    live（跳过排名/量比——盘前未开盘无意义）。cron ``*/2 9-9 * * 0-4`` 触发
    09:00-09:59，但 ``vr_paths.is_auction_time`` 门控（09:15-09:25 交易日）——窗口外
    no-op（防封 + 省请求）。竞价窗口约 5 ticks（09:16/18/20/22/24，``*/2`` 偶数分），
    相比原 ``*/10 9-15`` 在竞价窗口只命中 09:20 一次，trajectory 密度提升 5x。

    codes 取 ``prev_trading_date`` 涨停池（昨日涨停 = 今日竞价 continuation 候选集，
    §44 reframe 标记的最未证否盘中 edge）。save_auction_snapshots PK(date,ts,stage,code)
    INSERT OR REPLACE 幂等——与 microstructure 同 ts 同 code 重跑覆盖不翻倍。
    hithink 端点走 circuit_breaker，失败记 degraded 不抛（与 microstructure 同范式）。
    """
    from vr_paths import is_auction_time, last_trading_date_str, prev_trading_date_str
    now = _dt.now()
    if not is_auction_time(now):
        return {"status": "skipped", "reason": "非竞价时段（09:15-09:25 交易日）"}

    from data.sources import hithink_src
    from data.intraday_accumulation_store import save_auction_snapshots

    date = last_trading_date_str()
    ts = now.strftime("%Y-%m-%dT%H:%M")
    degraded: list[str] = []

    # 竞价 codes：prev_trading_date 涨停池（昨日涨停 = 今日竞价 continuation 候选）
    auction_codes: list[str] = []
    try:
        auction_codes = [r["code"] for r in hithink_src.limit_up_pool(prev_trading_date_str())
                         if r.get("code")]
    except Exception as e:  # noqa: BLE001 — 涨停池失败则竞价 codes 空，跳过竞价
        degraded.append(f"auction_pool: {type(e).__name__}")

    auction_items: list[dict] = []
    if auction_codes:
        try:
            auction_items = hithink_src.auction_snapshot(auction_codes, stage="live")
        except Exception as e:  # noqa: BLE001
            degraded.append(f"auction_live: {type(e).__name__}")
    save_auction_snapshots(date, ts, "live", auction_items)

    return {
        "date": date, "ts": ts,
        "auction": {"stage": "live", "count": len(auction_items)},
        "codes": len(auction_codes),
        "data_status": "degraded" if degraded else ("ok" if auction_items else "empty"),
        "degraded_sources": degraded,
    }


def baostock_5min_freeze(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S167 次日冻结——09:00 冻结 prev_trading_date 涨停股 5min bars（bars 稳定）。

    baostock 当日 5min bar T+1 lag（当日未稳定），故次日 09:00 冻结前一交易日
    涨停股 bars。涨停 codes 走 hithink ``limit_up_pool(prev_date)``。baostock 无 IP
    限制，单次 login。is_trading_day(today) 门控（节假日跳，prev 由下个交易日补）。
    幂等：INSERT OR REPLACE，重跑覆盖不翻倍。空 bars 仍写（bar_count=0 诚实记录）。
    """
    from vr_paths import is_trading_day, prev_trading_date_str
    if not is_trading_day():
        return {"status": "skipped", "reason": "非交易日（节假日跳，prev 由下交易日补）"}

    from data.sources import hithink_src, baostock_src
    from data.intraday_accumulation_store import freeze_baostock_5min

    prev_date = prev_trading_date_str()
    try:
        pool = hithink_src.limit_up_pool(prev_date)
    except Exception as e:  # noqa: BLE001
        return {"status": f"error: hithink 涨停池 {e}"}

    if not pool:
        return {"date": prev_date, "frozen": 0, "reason": "hithink 涨停池空（无涨停/源断）"}

    # end = prev_date（baostock 区间闭）；单日 bars
    frozen = 0
    empty = 0
    for item in pool:
        code = item.get("code")
        if not code:
            continue
        bars = baostock_src.fetch_5min_bars(code, prev_date, prev_date)
        freeze_baostock_5min(prev_date, code, item.get("name"), bars)
        frozen += 1
        if not bars:
            empty += 1
    return {
        "date": prev_date, "frozen": frozen, "empty_bars": empty,
        "pool_size": len(pool), "status": "ok",
    }
