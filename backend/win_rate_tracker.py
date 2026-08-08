# -*- coding: utf-8 -*-
"""胜率追踪 —— 滚动胜率 + 板块拆分 + 自动调参建议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlite3
import json

from config import WINRATE_DB_PATH

from migrations import MigrationManager


@dataclass
class WinRateRecord:
    """单笔交易记录。"""
    stock_code: str
    stock_name: str
    strategy_used: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    is_win: bool
    gene_score: float
    sti_label: str
    sector: str


@dataclass
class WinRateStats:
    """胜率统计。"""
    window_size: int
    total_trades: int
    win_count: int
    win_rate: float
    avg_return: float
    max_drawdown: float
    sharpe_ratio: float
    trend: str
    sector_breakdown: dict[str, Any]
    strategy_breakdown: dict[str, Any]
    score_breakdown: dict[str, Any]


class WinRateTracker:
    """胜率追踪器（SQLite 持久化）。"""

    def __init__(self, db_path: str = WINRATE_DB_PATH):
        self.db_path = db_path
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """执行数据库迁移。"""
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        manager = MigrationManager(db_path=self.db_path)
        migration_v1 = (
            Path(__file__).resolve().parent
            / "migrations" / "win_rate_tracker" / "20250613-001_create_winrate_records.sql"
        ).read_text(encoding="utf-8")
        migration_v2 = (
            Path(__file__).resolve().parent
            / "migrations" / "win_rate_tracker" / "20250613-002_add_winrate_indexes.sql"
        ).read_text(encoding="utf-8")
        migrations = [
            {
                "version": "20250613-001",
                "name": "create_winrate_records",
                "sql": migration_v1,
            },
            {
                "version": "20250613-002",
                "name": "add_winrate_indexes",
                "sql": migration_v2,
            },
        ]
        manager.upgrade(migrations)

    def add_record(self, record: WinRateRecord) -> None:
        """新增交易记录。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO winrate_records (
                stock_code, stock_name, strategy_used, entry_date, entry_price,
                exit_date, exit_price, return_pct, is_win, gene_score, sti_label, sector, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.stock_code,
                record.stock_name,
                record.strategy_used,
                record.entry_date,
                record.entry_price,
                record.exit_date,
                record.exit_price,
                record.return_pct,
                1 if record.is_win else 0,
                record.gene_score,
                record.sti_label,
                record.sector,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def get_stats(self, window_size: int = 20) -> WinRateStats:
        """获取滚动窗口胜率统计。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # 最近 N 笔
        rows = conn.execute(
            """
            SELECT * FROM winrate_records
            ORDER BY entry_date DESC
            LIMIT ?
            """,
            (window_size,),
        ).fetchall()
        conn.close()

        if not rows:
            return WinRateStats(
                window_size=window_size,
                total_trades=0,
                win_count=0,
                win_rate=0.0,
                avg_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                trend="stable",
                sector_breakdown={},
                strategy_breakdown={},
                score_breakdown={},
            )

        trades = [dict(r) for r in rows]
        total = len(trades)
        wins = sum(1 for t in trades if t["is_win"])
        win_rate = wins / total if total else 0.0
        returns = [t["return_pct"] for t in trades if t["return_pct"] is not None]
        avg_return = sum(returns) / len(returns) if returns else 0.0

        # 最大回撤（简化：基于累计收益）
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        max_drawdown = max_dd

        # 夏普比率（简化）
        if len(returns) > 1:
            mean = avg_return
            variance = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = variance ** 0.5
            sharpe_ratio = (mean / std) if std > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # 趋势判断（简化：前半段胜率 vs 后半段胜率）
        half = total // 2
        if half > 0:
            first_half_wins = sum(1 for t in trades[:half] if t["is_win"])
            second_half_wins = sum(1 for t in trades[half:] if t["is_win"])
            first_rate = first_half_wins / half
            second_rate = second_half_wins / (total - half)
            if second_rate > first_rate + 0.1:
                trend = "improving"
            elif second_rate < first_rate - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # 板块拆分
        sector_breakdown: dict[str, Any] = {}
        for t in trades:
            sector = t.get("sector") or "未知"
            if sector not in sector_breakdown:
                sector_breakdown[sector] = {"total": 0, "wins": 0}
            sector_breakdown[sector]["total"] += 1
            if t["is_win"]:
                sector_breakdown[sector]["wins"] += 1

        # 战法拆分
        strategy_breakdown: dict[str, Any] = {}
        for t in trades:
            strategy = t.get("strategy_used") or "未知"
            if strategy not in strategy_breakdown:
                strategy_breakdown[strategy] = {"total": 0, "wins": 0}
            strategy_breakdown[strategy]["total"] += 1
            if t["is_win"]:
                strategy_breakdown[strategy]["wins"] += 1

        # 基因得分区间拆分
        score_breakdown: dict[str, Any] = {
            "high": {"total": 0, "wins": 0},
            "medium": {"total": 0, "wins": 0},
            "low": {"total": 0, "wins": 0},
        }
        for t in trades:
            score = t.get("gene_score", 0)
            if score >= 75:
                bucket = "high"
            elif score >= 60:
                bucket = "medium"
            else:
                bucket = "low"
            score_breakdown[bucket]["total"] += 1
            if t["is_win"]:
                score_breakdown[bucket]["wins"] += 1

        return WinRateStats(
            window_size=window_size,
            total_trades=total,
            win_count=wins,
            win_rate=round(win_rate, 4),
            avg_return=round(avg_return, 4),
            max_drawdown=round(max_drawdown, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            trend=trend,
            sector_breakdown=sector_breakdown,
            strategy_breakdown=strategy_breakdown,
            score_breakdown=score_breakdown,
        )


def generate_strategy_adjustments(stats: WinRateStats) -> list[dict]:
    """根据胜率趋势自动生成策略调整建议。"""
    adjustments: list[dict] = []

    if stats.trend == "declining" and stats.win_rate < 0.4:
        adjustments.append({
            "type": "reduce_exposure",
            "reason": f"胜率下降至{stats.win_rate:.1%}，建议降低仓位",
            "action": "将HIGH等级仓位从30%降至20%",
        })

    # 板块维度：识别弱势板块
    for sector, data in stats.sector_breakdown.items():
        rate = data["wins"] / data["total"] if data["total"] else 0
        if rate < 0.3 and data["total"] >= 3:
            adjustments.append({
                "type": "avoid_sector",
                "reason": f"{sector}板块胜率仅{rate:.1%}",
                "action": f"建议暂时回避{sector}板块",
            })

    # 战法维度：识别弱势战法
    for strategy, data in stats.strategy_breakdown.items():
        rate = data["wins"] / data["total"] if data["total"] else 0
        if rate < 0.35 and data["total"] >= 3:
            adjustments.append({
                "type": "disable_strategy",
                "reason": f"{strategy}战法胜率仅{rate:.1%}",
                "action": f"建议暂停使用{strategy}战法",
            })

    return adjustments


def get_trends(window_size: int = 20) -> list[dict]:
    """获取胜率趋势数据（按日期聚合）。"""
    conn = sqlite3.connect(WINRATE_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT entry_date, COUNT(*) as total, SUM(is_win) as wins
        FROM winrate_records
        GROUP BY entry_date
        ORDER BY entry_date DESC
        LIMIT ?
        """,
        (window_size,),
    ).fetchall()
    conn.close()
    return [
        {
            "date": r["entry_date"],
            "total_trades": r["total"],
            "win_count": r["wins"],
            "win_rate": round(r["wins"] / r["total"], 4) if r["total"] else 0.0,
        }
        for r in reversed(rows)
    ]


def get_sector_stats(sector: str, window_size: int = 20) -> dict:
    """获取指定板块的胜率统计。"""
    conn = sqlite3.connect(WINRATE_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM winrate_records
        WHERE sector = ?
        ORDER BY entry_date DESC
        LIMIT ?
        """,
        (sector, window_size),
    ).fetchall()
    conn.close()
    if not rows:
        raise ValueError(f"Sector not found: {sector}")
    trades = [dict(r) for r in rows]
    total = len(trades)
    wins = sum(1 for t in trades if t["is_win"])
    win_rate = wins / total if total else 0.0
    returns = [t["return_pct"] for t in trades if t["return_pct"] is not None]
    avg_return = sum(returns) / len(returns) if returns else 0.0
    return {
        "sector": sector,
        "total_trades": total,
        "win_count": wins,
        "win_rate": round(win_rate, 4),
        "avg_return": round(avg_return, 4),
    }


def get_strategy_stats(strategy: str, window_size: int = 20) -> dict:
    """获取指定战法的胜率统计。"""
    conn = sqlite3.connect(WINRATE_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM winrate_records
        WHERE strategy_used = ?
        ORDER BY entry_date DESC
        LIMIT ?
        """,
        (strategy, window_size),
    ).fetchall()
    conn.close()
    if not rows:
        raise ValueError(f"Strategy not found: {strategy}")
    trades = [dict(r) for r in rows]
    total = len(trades)
    wins = sum(1 for t in trades if t["is_win"])
    win_rate = wins / total if total else 0.0
    returns = [t["return_pct"] for t in trades if t["return_pct"] is not None]
    avg_return = sum(returns) / len(returns) if returns else 0.0
    return {
        "strategy": strategy,
        "total_trades": total,
        "win_count": wins,
        "win_rate": round(win_rate, 4),
        "avg_return": round(avg_return, 4),
    }
