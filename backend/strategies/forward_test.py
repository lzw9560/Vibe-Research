# -*- coding: utf-8 -*-
"""S066 Phase 0e 前向测试（paper trading）框架——spec §13.0 上线路径最后验证关。

spec §13.0/§0e：
- 用 0d 权重跑系统：涨停股 × 策略分排序 × 板块周期 × 日历因子
- 每日记录推荐 vs 实际表现
- 通过标准：系统无崩溃 + 推荐胜率 >= 回测 × 0.8
- 不通过 → 修 bug 再跑 20 天
- 前向测试期间不投真金

本模块建框架（task 024），20 天运行（task 025）需日历时间积累。
每日盘后调用 record_daily_recommendations → 次日 record_actual_returns 回填。
诚实边界：无 next_bar 收益的推荐标 missing，不臆造。
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import GENE_SCORES_DB_PATH
from vr_paths import resolve_data_dir

_DB = GENE_SCORES_DB_PATH


# ===========================================================================
# 表结构（幂等迁移）
# ===========================================================================

_FORWARD_TEST_SQL = """
CREATE TABLE IF NOT EXISTS forward_test_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,              -- 信号日（推荐日）
    code TEXT NOT NULL,                     -- 推荐股票代码
    name TEXT,                              -- 股票名称
    strategy_code TEXT NOT NULL,            -- 战法 code
    strategy_score REAL,                    -- 策略分
    weather_state TEXT,                     -- 当日天气
    position_multiplier REAL,               -- 日历因子仓位乘数
    recommended_position REAL,              -- 建议仓位 %
    return_open2close REAL,                -- 次日开盘到收盘收益 %
    return_close2close REAL,               -- 收盘到收盘收益 %
    next_pctChg REAL,                       -- 次日涨跌幅 %
    is_win INTEGER DEFAULT 0,                    -- 是否盈利（return_open2close > 0）
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, code, strategy_code)
);
CREATE INDEX IF NOT EXISTS idx_forward_test_date ON forward_test_records(signal_date);
CREATE INDEX IF NOT EXISTS idx_forward_test_code ON forward_test_records(code);
"""


def _ensure_table() -> None:
    """幂等建表（import 时调用一次）。"""
    try:
        conn = sqlite3.connect(_DB, timeout=10)
        conn.executescript(_FORWARD_TEST_SQL)
        conn.commit()
        conn.close()
    except Exception:
        pass


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass(frozen=True)
class DailyRecommendation:
    """单条每日推荐记录。"""
    signal_date: str
    code: str
    name: str
    strategy_code: str
    strategy_score: float
    weather_state: str | None = None
    position_multiplier: float = 1.0
    recommended_position: float = 0.0


@dataclass(frozen=True)
class ForwardTestResult:
    """前向测试汇总结果。"""
    total_days: int
    total_recommendations: int
    settled_count: int            # 有 next_bar 收益的记录数
    win_count: int
    win_rate: float               # 0-100
    avg_return: float             # 平均 open2close 收益 %
    benchmark_win_rate: float     # 回测基准胜率（Phase 0b）
    pass_threshold: float         = 0.0  # 基准 × 0.8
    passed: bool                  = False
    consecutive_loss: int         = 0
    note: str                     = ""


# ===========================================================================
# 写入：每日推荐（信号日）
# ===========================================================================

def record_daily_recommendations(
    signal_date: str,
    recommendations: list[DailyRecommendation],
) -> int:
    """记录某信号日的全部推荐（UPSERT 幂等）。

    信号日盘后调用：跑策略系统 → 记录推荐代码/策略分/天气/仓位。
    返回写入条数。
    """
    _ensure_table()
    if not recommendations:
        return 0
    conn = sqlite3.connect(_DB, timeout=10)
    inserted = 0
    try:
        for rec in recommendations:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO forward_test_records
                    (signal_date, code, name, strategy_code, strategy_score,
                     weather_state, position_multiplier, recommended_position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rec.signal_date, rec.code, rec.name, rec.strategy_code,
                     rec.strategy_score, rec.weather_state, rec.position_multiplier,
                     rec.recommended_position),
                )
                inserted += 1
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()
    return inserted


# ===========================================================================
# 回填：次日实际收益（T+1 盘后）
# ===========================================================================

def record_actual_returns(
    signal_date: str,
    returns_data: dict[str, dict[str, float | None]],
) -> int:
    """回填某信号日推荐的次日实际收益。

    signal_date: 信号日（推荐日），不是次日
    returns_data: {code: {return_open2close, return_close2close, next_pctChg}}

    次日盘后调用：拉 kline → 算次日收益 → 回填。
    缺 next_bar 的标 None（不臆造）。
    返回更新条数。
    """
    _ensure_table()
    if not returns_data:
        return 0
    conn = sqlite3.connect(_DB, timeout=10)
    updated = 0
    try:
        for code, returns in returns_data.items():
            o2c = returns.get("return_open2close")
            c2c = returns.get("return_close2close")
            pct = returns.get("next_pctChg")
            is_win = 1 if (o2c is not None and o2c > 0) else 0
            try:
                cur = conn.execute(
                    """UPDATE forward_test_records
                    SET return_open2close = ?, return_close2close = ?,
                        next_pctChg = ?, is_win = ?
                    WHERE signal_date = ? AND code = ?""",
                    (o2c, c2c, pct, is_win, signal_date, code),
                )
                if cur.rowcount > 0:
                    updated += 1
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()
    return updated


# ===========================================================================
# 汇总：前向测试结果
# ===========================================================================

def get_forward_test_summary(
    benchmark_win_rate: float = 60.57,  # Phase 0b benchmark_A
    min_days: int = 20,
) -> ForwardTestResult:
    """汇总前向测试结果（spec §0e 通过标准）。

    通过标准：
    - total_days >= min_days（20 交易日）
    - win_rate >= benchmark × 0.8
    - 无崩溃（consecutive_loss < 8，kill criteria 未触发）
    """
    _ensure_table()
    conn = sqlite3.connect(_DB, timeout=10)
    try:
        # 总记录数 + 已结算数
        total = conn.execute("SELECT COUNT(*) FROM forward_test_records").fetchone()[0]
        settled = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE return_open2close IS NOT NULL"
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE is_win = 1"
        ).fetchone()[0]

        # 独立信号日数
        days = conn.execute(
            "SELECT COUNT(DISTINCT signal_date) FROM forward_test_records"
        ).fetchone()[0]

        # 平均收益
        avg_row = conn.execute(
            "SELECT AVG(return_open2close) FROM forward_test_records WHERE return_open2close IS NOT NULL"
        ).fetchone()
        avg_return = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0

        # 连续亏损笔数（最近 N 笔）
        recent = conn.execute(
            """SELECT is_win FROM forward_test_records
            WHERE return_open2close IS NOT NULL
            ORDER BY signal_date DESC, id DESC LIMIT 20"""
        ).fetchall()
        consecutive_loss = 0
        for r in recent:
            if r[0] == 0:
                consecutive_loss += 1
            else:
                break
    finally:
        conn.close()

    win_rate = round(wins / settled * 100, 2) if settled > 0 else 0.0
    pass_threshold = round(benchmark_win_rate * 0.8, 2)

    # 通过判定
    passed = (
        days >= min_days
        and settled > 0
        and win_rate >= pass_threshold
        and consecutive_loss < 8
    )

    note_parts = []
    if days < min_days:
        note_parts.append(f"样本不足：{days}/{min_days} 交易日")
    if settled == 0:
        note_parts.append("无已结算记录（需次日回填收益）")
    if win_rate < pass_threshold and settled > 0:
        note_parts.append(f"胜率 {win_rate}% < 阈值 {pass_threshold}%")
    if consecutive_loss >= 8:
        note_parts.append(f"连续亏损 {consecutive_loss} 笔（kill criteria 触发）")
    if not note_parts:
        note_parts.append("前向测试通过")

    return ForwardTestResult(
        total_days=days,
        total_recommendations=total,
        settled_count=settled,
        win_count=wins,
        win_rate=win_rate,
        avg_return=round(avg_return, 4),
        benchmark_win_rate=benchmark_win_rate,
        pass_threshold=pass_threshold,
        passed=passed,
        consecutive_loss=consecutive_loss,
        note="；".join(note_parts),
    )


# ===========================================================================
# 查询：单日推荐明细
# ===========================================================================

def get_daily_recommendations(signal_date: str) -> list[dict]:
    """取某信号日的全部推荐记录。"""
    _ensure_table()
    conn = sqlite3.connect(_DB, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM forward_test_records WHERE signal_date = ?
            ORDER BY strategy_score DESC""",
            (signal_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ===========================================================================
# 运行入口（盘后调度调用）
# ===========================================================================

def run_daily_forward_test(signal_date: str, weather_state: str | None = None) -> dict:
    """每日盘后前向测试入口。

    1. 跑策略系统（天气 → 策略组 → 策略分排序）→ 记录推荐
    2. 次日盘后回填收益（由调用方拉 kline 后调 record_actual_returns）
    3. 返回当日推荐数

    本函数只做第 1 步（记录推荐），收益回填需次日数据可用后单独调。
    """
    from limitup_screener.data import load_gene_scores
    from strategies.strategy_funnel_registry import score_candidates
    from strategies.calendar_factor import calendar_factor

    # 取当日 gene_scores
    genes = load_gene_scores(signal_date)
    if not genes:
        return {"signal_date": signal_date, "recommendations": 0, "note": "当日无 gene_scores 数据"}

    # 构造候选 + 策略分排序
    candidates = [
        {
            "code": g.code,
            "name": getattr(g, "name", ""),
            "factors": {
                "factor_seal_rate": getattr(g, "factor_seal_rate", 0) or 0,
                "factor_rebound_rate": getattr(g, "factor_rebound_rate", 0) or 0,
                "factor_red_rate": getattr(g, "factor_red_rate", 0) or 0,
                "factor_premium_rate": getattr(g, "factor_premium_rate", 0) or 0,
                "factor_freq_score": getattr(g, "factor_freq_score", 0) or 0,
            },
        }
        for g in genes
    ]

    scored = score_candidates(candidates, weather_state)
    mult, _ = calendar_factor(signal_date)

    recommendations = [
        DailyRecommendation(
            signal_date=signal_date,
            code=s["code"],
            name=s.get("name", ""),
            strategy_code=s["strategy_code"],
            strategy_score=s["strategy_score"],
            weather_state=weather_state,
            position_multiplier=mult,
            recommended_position=round(5.0 * mult, 2),  # base 5% × 日历因子
        )
        for s in scored[:20]  # top-20 推荐
    ]

    count = record_daily_recommendations(signal_date, recommendations)
    return {
        "signal_date": signal_date,
        "recommendations": count,
        "weather_state": weather_state,
        "position_multiplier": mult,
    }
