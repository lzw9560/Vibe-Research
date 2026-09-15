#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S206 T6: baostock 5min 多日回补脚本——唯一可回补盘中价格序列源。

遍历历史丢失交易日，对每日涨停股 codes：
1. hithink limit_up_pool(date) 取涨停股 codes（实测远期日期支持——8/18 返 50 codes ✅）
2. baostock fetch_5min_bars(code, date, date) 取 5min K 线
3. freeze_baostock_5min(date, code, name, bars) 写入 baostock_5min_freeze 表（幂等）
4. em_get getTopicZBPool(date) 同步取炸板事件（dual_pressure 重建须用）

先 3 天小批验证（--days 3）再全量 22 天。baostock 无 IP 限（单 login），安全批量。

用法：
    .venv/bin/python -m tools.backfill_baostock_5min --days 3
    .venv/bin/python -m tools.backfill_baostock_5min --start 2026-08-18 --end 2026-08-31
"""
from __future__ import annotations
import argparse
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger("vibe-research")


def _trading_days_between(start: str, end: str) -> list[str]:
    """列出 start~end 间的交易日（用 zt_history.db 的已有交易日集过滤周末）。"""
    try:
        import sqlite3
        from vr_paths import resolve_data_dir
        db = resolve_data_dir() / "zt_history.db"
        conn = sqlite3.connect(str(db))
        # zt_history.date 格式是 'YYYY-MM-DD'（实测），直接用 start/end
        rows = conn.execute(
            "SELECT DISTINCT date FROM zt_history WHERE date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows] if rows else []
    except Exception as e:
        logger.warning("trading_days 查询失败 %s，降级自然日过滤周末", e)
        out = []
        d = datetime.strptime(start, "%Y-%m-%d")
        end_d = datetime.strptime(end, "%Y-%m-%d")
        while d <= end_d:
            if d.weekday() < 5:  # 0-4=Mon-Fri
                out.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
        return out


def backfill_one_day(date: str) -> dict:
    """回补单日：涨停 codes × 5min bars × freeze + ZBPool 炸板事件。

    返回 {date, zt_codes, freeze_ok, zb_events, errors}。
    """
    from data.sources.hithink_src import limit_up_pool
    from data.sources.baostock_src import fetch_5min_bars
    from data.intraday_accumulation_store import freeze_baostock_5min

    result = {"date": date, "zt_codes": [], "freeze_ok": 0, "zb_events": [], "errors": []}
    try:
        codes_items = limit_up_pool(date) or []
    except Exception as e:
        result["errors"].append(f"hithink limit_up_pool({date}): {e}")
        return result
    result["zt_codes"] = [it.get("code") if isinstance(it, dict) else it for it in codes_items]

    # em_get 炸板池（dual_pressure 重建须用）
    try:
        import astock
        zb = astock.em_zt_topic_pool("getTopicZBPool", date.replace("-", ""), "fbt:asc")
        result["zb_events"] = [it.get("c") for it in (zb or []) if it.get("c")]
    except Exception as e:
        result["errors"].append(f"getTopicZBPool({date}): {e}")

    # baostock 5min bars × freeze（per-query throttle 防登录态丢）
    for item in codes_items:
        code = item.get("code") if isinstance(item, dict) else item
        name = item.get("name") if isinstance(item, dict) else ""
        if not code or not code.isdigit() or len(code) != 6:
            continue
        try:
            bars = fetch_5min_bars(code, date, date)
            if bars:
                freeze_baostock_5min(date, code, name, bars)
                result["freeze_ok"] += 1
            time.sleep(0.05)  # throttle（baostock 无 IP 限但防 login 抖动）
        except Exception as e:
            result["errors"].append(f"freeze {code} {date}: {e}")

    return result


def run_backfill(start: str, end: str, max_days: int | None = None) -> list[dict]:
    """回补 start~end 间交易日。max_days 限制批量（先 3 天小批验证）。"""
    days = _trading_days_between(start, end)
    if max_days:
        days = days[:max_days]
    logger.info("[backfill_baostock_5min] 回补 %d 个交易日: %s~%s", len(days), days[0] if days else "?", days[-1] if days else "?")
    results = []
    for d in days:
        r = backfill_one_day(d)
        logger.info("[backfill] %s: zt=%d freeze_ok=%d zb=%d errs=%d",
                    d, len(r["zt_codes"]), r["freeze_ok"], len(r["zb_events"]), len(r["errors"]))
        results.append(r)
    return results


def main() -> int:
    p = argparse.ArgumentParser(description="baostock 5min 多日回补（S206 T6）")
    p.add_argument("--start", default="2026-08-18", help="起始日 YYYY-MM-DD")
    p.add_argument("--end", default="2026-09-14", help="结束日 YYYY-MM-DD")
    p.add_argument("--days", type=int, default=None, help="小批验证天数（如 --days 3）")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    results = run_backfill(a.start, a.end, a.days)
    total_freeze = sum(r["freeze_ok"] for r in results)
    total_err = sum(len(r["errors"]) for r in results)
    print(f"\n=== 回补完成：{len(results)} 交易日，freeze {total_freeze} 只，错误 {total_err} 条 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
