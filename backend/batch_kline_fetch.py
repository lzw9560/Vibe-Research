#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量拉取A股过去90日K线数据。

使用 mootdx 数据源（TDX TCP协议，不封IP），将日线K线存入 SQLite。

用法:
    python batch_kline_fetch.py              # 默认全量拉取全部A股
    python batch_kline_fetch.py --codes 600519,000001  # 只拉指定股票
    python batch_kline_fetch.py --days 180     # 拉180日
    python batch_kline_fetch.py --limit 100    # 只拉前100只股票（测试用）
    python batch_kline_fetch.py --output json  # 输出为JSON而非SQLite
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("batch_kline_fetch")

# ─── 数据库路径 ───────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).parent
_DB_PATH = _BACKEND_DIR / "data" / "kline_history.db"
_JSON_PATH = _BACKEND_DIR / "data" / "kline_history.json"


# ─── 数据库初始化 ─────────────────────────────────────────────
def _init_db(db_path: Path) -> sqlite3.Connection:
    """创建/打开 SQLite 数据库，建表。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kline (
            code        TEXT NOT NULL,
            name        TEXT,
            date        TEXT NOT NULL,   -- YYYY-MM-DD
            open        REAL,
            close       REAL,
            high        REAL,
            low         REAL,
            volume      REAL,
            amount      REAL,
            fetched_at  TEXT NOT NULL,   -- 拉取时间戳
            PRIMARY KEY (code, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_code ON kline(code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON kline(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_date ON kline(code, date)")
    conn.commit()
    return conn


# ─── A股代码过滤 ──────────────────────────────────────────────
def _get_a_share_codes() -> List[str]:
    """从 mootdx 获取 A 股代码列表，过滤掉指数、债券等。"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        stocks = client.stocks()
        raw_codes = stocks["code"].astype(str).tolist()
    except Exception as e:
        logger.error("mootdx 获取股票列表失败: %s", e)
        return []

    a_shares = []
    for c in raw_codes:
        if len(c) != 6 or not c.isdigit():
            continue
        # 排除: 指数(399xxx, 999xxx), 特定指数(000001-000009), 债券(01xxxx, 20xxxx)
        if c.startswith(("399", "999")):
            continue
        if c in ("000001", "000002", "000003", "000004", "000005",
                 "000006", "000007", "000008", "000009"):
            continue
        if c[0] in ("0", "2"):
            # 0开头保留(深市主板/中小板), 2开头是债券排除
            if c[0] == "2":
                continue
        a_shares.append(c)
    return sorted(set(a_shares))


# ─── K线拉取 ──────────────────────────────────────────────────
def _fetch_kline(code: str, days: int = 90) -> Optional[List[Dict[str, Any]]]:
    """拉取单只股票的 K 线数据，返回格式化记录列表。"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        df = client.bars(symbol=code, category=4, offset=days + 10)  # 多拉一些防不足
        if df is None or df.empty:
            return None

        records = []
        for _, row in df.iterrows():
            dt = str(row.get("datetime", ""))
            # 只取日期部分 YYYY-MM-DD
            date_str = dt[:10] if len(dt) >= 10 else dt
            records.append({
                "date": date_str,
                "open": float(row.get("open", 0)),
                "close": float(row.get("close", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "volume": float(row.get("volume", 0)),
                "amount": float(row.get("amount", 0)),
            })
        return records
    except Exception as e:
        logger.warning("拉取 %s K线失败: %s", code, e)
        return None


def _get_stock_name(code: str) -> str:
    """从 mootdx 获取股票名称。"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        stocks = client.stocks()
        row = stocks[stocks["code"].astype(str) == code]
        if not row.empty:
            return str(row.iloc[0]["name"])
    except Exception:
        pass
    return ""


# ─── 存储 ─────────────────────────────────────────────────────
def _store_to_db(conn: sqlite3.Connection, code: str, name: str,
                 records: List[Dict], fetched_at: str) -> int:
    """批量插入/更新 K 线记录到 SQLite。返回写入条数。"""
    count = 0
    for rec in records:
        try:
            conn.execute(
                """INSERT OR REPLACE INTO kline
                   (code, name, date, open, close, high, low, volume, amount, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, name, rec["date"], rec["open"], rec["close"],
                 rec["high"], rec["low"], rec["volume"], rec["amount"],
                 fetched_at),
            )
            count += 1
        except Exception as e:
            logger.error("插入 %s %s 失败: %s", code, rec["date"], e)
    return count


def _store_to_json(all_data: Dict[str, Any], json_path: Path) -> None:
    """将所有数据写入 JSON 文件。"""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    logger.info("JSON 文件已写入: %s (%d 只股票)", json_path, len(all_data))


# ─── 主流程 ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="批量拉取A股K线数据(过去N日)")
    parser.add_argument("--codes", type=str, default="",
                        help="逗号分隔的股票代码, 空=全量")
    parser.add_argument("--days", type=int, default=90,
                        help="拉取天数 (默认: 90)")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制拉取数量(测试用, 0=不限)")
    parser.add_argument("--output", type=str, choices=["db", "json", "both"],
                        default="db", help="输出格式 (默认: db)")
    parser.add_argument("--db-path", type=str, default=str(_DB_PATH),
                        help=f"SQLite 数据库路径 (默认: {_DB_PATH})")
    parser.add_argument("--json-path", type=str, default=str(_JSON_PATH),
                        help=f"JSON 输出路径 (默认: {_JSON_PATH})")
    parser.add_argument("--resume", action="store_true",
                        help="跳过已有数据的股票(基于fetched_at判断)")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    json_path = Path(args.json_path)
    now = datetime.now().isoformat()

    # 确定股票代码列表
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        logger.info("指定拉取 %d 只股票: %s...", len(codes), ", ".join(codes[:10]))
    else:
        logger.info("正在获取A股代码列表...")
        codes = _get_a_share_codes()
        logger.info("共获取 %d 只A股代码", len(codes))
        if not codes:
            logger.error("未获取到任何A股代码，退出")
            sys.exit(1)

    if args.limit > 0:
        codes = codes[:args.limit]
        logger.info("限制拉取 %d 只股票", len(codes))

    total = len(codes)
    success_count = 0
    fail_count = 0
    skip_count = 0
    total_records = 0

    # 打开数据库连接
    conn = _init_db(db_path)

    start_time = time.time()

    for i, code in enumerate(codes, 1):
        # 检查是否已有较新的数据(如果启用resume)
        if args.resume:
            existing = conn.execute(
                "SELECT MAX(fetched_at) FROM kline WHERE code=?", (code,)
            ).fetchone()
            if existing and existing[0]:
                last_fetched = existing[0]
                # 如果上次拉取是在今天或昨天，跳过
                last_dt = datetime.fromisoformat(last_fetched).replace(tzinfo=None)
                if (datetime.now() - last_dt).days < 1:
                    skip_count += 1
                    if i % 100 == 0:
                        elapsed = time.time() - start_time
                        rate = i / elapsed
                        eta = (total - i) / rate
                        logger.info(
                            "[%d/%d] 跳过 %s (上次: %s) | "
                            "成功=%d 失败=%d | %.1f只/分钟 ETA:%.1fm",
                            i, total, code, last_fetched[:10],
                            success_count, fail_count, rate * 60, eta / 60,
                        )
                    continue

        name = _get_stock_name(code)
        records = _fetch_kline(code, days=args.days)

        if records is None or len(records) == 0:
            fail_count += 1
            if i % 100 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed
                eta = (total - i) / rate
                logger.info(
                    "[%d/%d] %s 无数据 | "
                    "成功=%d 失败=%d 跳过=%d | %.1f只/分钟 ETA:%.1fm",
                    i, total, code, success_count, fail_count, skip_count,
                    rate * 60, eta / 60,
                )
            continue

        # 写入数据库
        count = _store_to_db(conn, code, name, records, now)
        success_count += 1
        total_records += count

        # 进度日志
        if i % 100 == 0 or i == total:
            elapsed = time.time() - start_time
            rate = i / elapsed
            eta = (total - i) / rate
            logger.info(
                "[%d/%d] %s (%s) %d条 | "
                "成功=%d 失败=%d 跳过=%d | %.1f只/分钟 ETA:%.1fm",
                i, total, code, name, count,
                success_count, fail_count, skip_count,
                rate * 60, eta / 60,
            )

        # 节流：避免过于频繁请求
        time.sleep(0.05)

    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    minutes = elapsed / 60

    logger.info("=" * 60)
    logger.info("批量K线拉取完成!")
    logger.info("总股票数: %d", total)
    logger.info("成功: %d | 失败: %d | 跳过: %d", success_count, fail_count, skip_count)
    logger.info("总记录数: %d 条", total_records)
    logger.info("耗时: %.1f 分钟 (%.1f秒/只)" % (minutes, elapsed / total))
    logger.info("数据库: %s", db_path)

    # 可选: 写入JSON汇总
    if args.output in ("json", "both"):
        all_data: Dict[str, Any] = {}
        for code in codes[:success_count]:
            name = _get_stock_name(code)
            all_data[code] = {"name": name}
        _store_to_json(all_data, json_path)

    # 统计信息
    conn.row_factory = sqlite3.Row
    stats = conn.execute(
        "SELECT COUNT(DISTINCT code) as stocks, MIN(date) as first_date, MAX(date) as last_date, COUNT(*) as total_records "
        "FROM kline"
    ).fetchone()
    logger.info("数据库中: %d 只股票, 首条=%s, 末条=%s, 总记录=%d",
                stats["stocks"], stats["first_date"], stats["last_date"], stats["total_records"])
    conn.close()


if __name__ == "__main__":
    main()
