# -*- coding: utf-8 -*-
"""trade_journal —— 实盘记录 + realistic gap-through 止损 + 滑点（S235 T07，spec §5.4）。

修复 Oracle 阻断 1.5 + R6（成交假设虚构）：止损不按止损价精确成交，
跳空穿仓按开盘价成交（更差）+ 滑点 0.3%。

记录信号价 vs 实际成交价，供 30 笔后归因（避免 survivorship：未成交信号在
signal_store 落库，本表只记成交的）。
"""

from __future__ import annotations
import sqlite3
from datetime import datetime
from pathlib import Path

from vr_paths import resolve_data_dir  # 复用现有私有数据目录解析

# 滑点（spec §5.4：0.2-0.5%，取 0.3%）
BUY_SLIPPAGE = 0.003  # 买入 fill = signal_price × 1.003（付更多）
SELL_SLIPPAGE = 0.003  # 卖出 fill = raw_exit × 0.997（得更少）
# 默认止损 -10%（spec §2.3：2×ATR，中位 4.9%×2≈10%，有数据支撑）
DEFAULT_STOP_PCT = -10

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    signal_id INTEGER,
    code TEXT,
    tactic TEXT,
    entry_time TEXT,
    entry_price REAL,
    fill_price REAL,
    stop_price REAL,
    exit_price REAL,
    exit_reason TEXT,
    exit_time TEXT,
    hold_days INTEGER,
    return_pct REAL,
    slippage_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_trade_signal ON trades(signal_id);
CREATE INDEX IF NOT EXISTS idx_trade_code ON trades(code);
"""


def calc_stop_loss(
    entry_price: float,
    stop_pct: float,
    next_bar: dict,
) -> tuple[float | None, str]:
    """realistic fill：跳空穿仓按开盘价成交。

    stop_pct 为负（-10 表示止损 -10%）。止损价 = entry × (1 + stop_pct/100)。
    返回 (成交价, 类型)：
      - gap_through：开盘价 <= 止损价（跳空穿仓，按开盘价，更差）
      - normal_stop：盘中最低 <= 止损价（按止损价成交）
      - no_stop：未触及
      - no_data：next_bar 无 open_price
    """
    if entry_price <= 0:
        return None, "no_data"
    stop_price = entry_price * (1 + stop_pct / 100)
    open_next = float(next_bar.get("open_price", 0) or 0)
    low_next = float(next_bar.get("low_price", 0) or 0)
    if open_next <= 0:
        return None, "no_data"
    if open_next <= stop_price:
        # 跳空穿仓：开盘已穿止损，按开盘价成交（比止损价更差）
        return open_next, "gap_through"
    if low_next <= stop_price:
        # 盘中触及止损价
        return stop_price, "normal_stop"
    return None, "no_stop"


class TradeJournal:
    """实盘记录。fill_price 含买入滑点；exit 含卖出滑点。"""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = resolve_data_dir() / "tactics_journal.db"
        self.db_path = str(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    def save_trade(
        self,
        *,
        signal_id: int,
        code: str,
        tactic: str,
        entry_price: float,
        entry_time: str | None = None,
        stop_pct: float = DEFAULT_STOP_PCT,
    ) -> int:
        """记录买入：fill_price = entry × (1 + BUY_SLIPPAGE)。返回 trade id。"""
        fill_price = entry_price * (1 + BUY_SLIPPAGE)
        stop_price = entry_price * (1 + stop_pct / 100)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO trades (signal_id, code, tactic, entry_time, "
                "entry_price, fill_price, stop_price, slippage_pct) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    signal_id,
                    code,
                    tactic,
                    entry_time or datetime.now().isoformat(timespec="seconds"),
                    entry_price,
                    fill_price,
                    stop_price,
                    BUY_SLIPPAGE,
                ),
            )
            return cur.lastrowid

    def record_exit(
        self,
        trade_id: int,
        exit_price: float,
        exit_reason: str,
        exit_time: str | None = None,
        hold_days: int = 0,
    ) -> float:
        """记录卖出：sell_fill = exit × (1 - SELL_SLIPPAGE)。返实际收益率。"""
        sell_fill = exit_price * (1 - SELL_SLIPPAGE)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT fill_price FROM trades WHERE id=?", (trade_id,)).fetchone()
            if not row:
                raise ValueError(f"trade {trade_id} 不存在")
            fill_price = float(row[0])
            ret = (sell_fill - fill_price) / fill_price if fill_price > 0 else 0.0
            conn.execute(
                "UPDATE trades SET exit_price=?, exit_reason=?, exit_time=?, hold_days=?, return_pct=? WHERE id=?",
                (
                    exit_price,
                    exit_reason,
                    exit_time or datetime.now().isoformat(timespec="seconds"),
                    hold_days,
                    ret,
                    trade_id,
                ),
            )
        return ret

    def get_trade(self, trade_id: int) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row) if row else None

    def get_trade_pnl(self, trade_id: int) -> float | None:
        """已记录 exit 的收益率；未 exit 返 None。"""
        t = self.get_trade(trade_id)
        if not t or t.get("return_pct") is None:
            return None
        return float(t["return_pct"])
