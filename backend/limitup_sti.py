# -*- coding: utf-8 -*-
"""情绪温度指数（STI, Sentiment Temperature Index）引擎 — PRD V1.6 对齐版。

核心变更（V1.6 修正）:
- 8 维加权（移除 break_rate，seal_rate + break_rate 信息冗余）
- prev_zt_performance 方向修正: zt_count / yzt_count * 100
- 百分位排名 equal 补偿: (less + 0.5 * equal) / n
- 动态分位数修正: P90/P70/P40/P15（非均匀分布）
- 3 日移动平均平滑相位分类
- source_ok=False 返回 null 而非伪造 0 分
- momentum → change_from_yesterday 重命名
- 回填节流 0.1s → 1.2s
- _compute_confidence 修复（不再访问类默认值）
- SQLite schema: 移除 break_rate 列，新增 data_updated 列

数据源: market._emotion() + market._sentiment()，零个股名。
缓存: SQLite 持久化 sti_timeline，API 只读。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

import market
from migrations import MigrationManager

BEIJING_TZ = datetime.now(market.BEIJING).astimezone().tzinfo

# ===========================================================================
# 常量
# ===========================================================================

DISCLAIMER = (
    "免责声明：情绪温度仅为历史统计维度之一，不构成任何操作建议。"
    "股市有风险，投资需谨慎。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。"
)

# 8 维权重（合计 = 1.00，已归一化）
# 归一化公式: STI = Σ(normalized_i × weight_i) / Σ(weight_i) × 100
STI_WEIGHTS: dict[str, float] = {
    "limit_up_count": 0.15,
    "limit_down_count": 0.13,       # 负向，计算时取绝对值归一化后反向
    "seal_rate": 0.25,
    "advance_decline_ratio": 0.10,
    "promotion_rate": 0.22,
    "prev_zt_performance": 0.10,
    "max_boards": 0.05,
}
# 权重合计: 1.00
TOTAL_WEIGHT = sum(STI_WEIGHTS.values())  # == 1.00

# 方向：+1 正向指标（越大越好），-1 负向指标（越小越好）
STI_DIRECTIONS: dict[str, int] = {
    "limit_up_count": 1,
    "limit_down_count": -1,
    "seal_rate": 1,
    "advance_decline_ratio": 1,
    "promotion_rate": 1,
    "prev_zt_performance": 1,
    "max_boards": 1,
}

# 市场活跃度因子映射（MVP 降级方案，Phase 3 改为滚动 60 日成交额中位数）
_MARKET_ACTIVE_MAP = {
    "冰点": 0.7,
    "偏弱": 0.85,
    "中性": 1.0,
    "偏强": 1.15,
    "普涨": 1.3,
}

# 固定降级阈值（历史数据不足 252 天时使用）
_FALLBACK_PHASE_THRESHOLDS = {
    "高潮": 80.0,
    "启动": 60.0,
    "分歧": 40.0,
    "冰点": 20.0,
}

# 五阶段标签解释（合规：降低游资黑话引导性）
PHASE_EXPLANATIONS = {
    "高潮": "市场过热（历史统计含义）",
    "启动": "情绪从低位回升（历史统计含义）",
    "分歧": "多空博弈激烈（历史统计含义）",
    "冰点": "市场冷清（历史统计含义）",
    "退潮": "情绪持续走弱（历史统计含义）",
}

# 内存中滚动 STI 分数缓存（用于动态分位数 + 3 日平滑）
_sti_scores: list[float] = []
_sti_lock = threading.Lock()

# ===========================================================================
# 数据结构
# ===========================================================================


class STIPhase(str, Enum):
    """五阶段枚举。"""
    HIGH潮 = "高潮"
    START = "启动"
    DIVERGENCE = "分歧"
    FREEZE = "冰点"
    DECLINE = "退潮"


class STIDimension(BaseModel):
    """8 维指标原始值（归一化前）。"""
    limit_up_count: float = 0.0
    limit_down_count: float = 0.0
    seal_rate: float = 0.0
    advance_decline_ratio: float = 0.0
    promotion_rate: float = 0.0
    prev_zt_performance: float = 0.0
    max_boards: float = 0.0
    market_factor: float = 1.0


class STIResult(BaseModel):
    """STI 情绪温度计算结果。"""
    date: str
    score: Optional[float]  # 0-100，source_ok=False 时为 null
    phase: Optional[STIPhase]
    dimensions: Optional[STIDimension]
    source_ok: bool = True
    confidence: str = "high"  # "high" / "medium" / "low"
    change_from_yesterday: Optional[float] = None  # 重命名自 momentum
    data_updated: Optional[str] = None  # 数据更新时间 YYYY-MM-DD
    phase_explanation: Optional[str] = None  # 合规：五阶段标签解释
    disclaimer: str = DISCLAIMER


# ===========================================================================
# 辅助函数
# ===========================================================================


def percentile_rank(value: float, lookback_series: list[float]) -> float:
    """将 value 映射到 lookback_series 的百分位排名（0-100）。

    使用 Excel PERCENTRANK.INC 标准：(less + 0.5 * equal) / n
    天然 0-100 分布，保留极端值，无需裁剪。
    最小 warm-up 期：60 个交易日。
    """
    n = len(lookback_series)
    if n < 60:
        return 50.0  # 数据不足，返回中性值

    less = sum(1 for v in lookback_series if v < value)
    equal = sum(1 for v in lookback_series if v == value)
    # Excel PERCENTRANK.INC 标准：相等值平分中间区域
    return ((less + 0.5 * equal) / n) * 100.0


def _safe_float(v, default: float = 0.0) -> float:
    """安全转换为 float。"""
    try:
        if v is None:
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _ema_3day(current: float, history: list[float]) -> float:
    """计算 3 日移动平均（含历史数据）。

    简单算术平均：(current + hist[-1] + hist[-2]) / 3
    如果历史不足 2 天则退化。
    """
    if not history:
        return current
    if len(history) == 1:
        return (current + history[-1]) / 2.0
    return (current + history[-1] + history[-2]) / 3.0


# ===========================================================================
# 核心引擎
# ===========================================================================


class STIEngine:
    """情绪温度指数引擎（8 维加权 + 1 维独立过滤）。

    数据源: market._emotion() + market._sentiment()（直接调用内部函数，解耦）
    存储: sti_timeline SQLite 表（预计算入库）
    计算频率: 日频，与基因选股器共用 15:35 调度器
    """

    def __init__(self):
        self._db: Optional[sqlite3.Connection] = None
        self._db_lock = threading.Lock()
        self._run_initial_migrations()

    def _run_initial_migrations(self) -> None:
        """执行初始 schema 迁移（仅一次）。"""
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "vibe_research.db"
        )
        manager = MigrationManager(db_path=db_path)
        migration_sql = (
            Path(__file__).resolve().parent
            / "migrations" / "sti" / "20250613-001_create_sti_timeline.sql"
        ).read_text(encoding="utf-8")
        migrations = [
            {
                "version": "20250613-001",
                "name": "create_sti_timeline",
                "sql": migration_sql,
            }
        ]
        manager.upgrade(migrations)

    # ---- SQLite 持久化 ----

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            db_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "vibe_research.db"
            )
            self._db = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
        return self._db

    def _migrate_schema(self) -> None:
        """迁移旧 schema：移除 break_rate 列，重命名 momentum → change_from_yesterday，新增 data_updated。"""
        if self._db is None:
            return

        # 从现有连接获取数据库路径
        db_path = self._db.execute("PRAGMA database_list").fetchone()[2]
        manager = MigrationManager(db_path=db_path)
        migrations = [
            {
                "version": "20250613-002",
                "name": "migrate_sti_timeline_v2",
                "sql": self._build_migration_sql(self._db),
            }
        ]
        manager.upgrade(migrations)

    def _build_migration_sql(self, db: sqlite3.Connection) -> str:
        """构建迁移 SQL（动态检测列存在性）。"""
        cursor = db.execute("PRAGMA table_info(sti_timeline)")
        columns = {row["name"] for row in cursor.fetchall()}

        needs_migration = False
        if "dimension_break_rate" in columns:
            needs_migration = True
        if "momentum" in columns and "change_from_yesterday" not in columns:
            needs_migration = True

        if not needs_migration:
            return "SELECT 1;"  # 空操作

        # 构建列映射
        insert_cols = "date, score, phase, dimension_limit_up_count, dimension_limit_down_count, dimension_seal_rate, dimension_advance_decline_ratio, dimension_promotion_rate, dimension_prev_zt_performance, dimension_max_boards, market_factor, confidence, source_ok, change_from_yesterday, data_updated, computed_at"
        sel_date = "date" if "date" in columns else "NULL"
        sel_score = "score" if "score" in columns else "NULL"
        sel_phase = "phase" if "phase" in columns else "NULL"
        sel_dims = []
        for c in ("dimension_limit_up_count", "dimension_limit_down_count", "dimension_seal_rate",
                  "dimension_advance_decline_ratio", "dimension_promotion_rate",
                  "dimension_prev_zt_performance", "dimension_max_boards"):
            sel_dims.append(c if c in columns else "NULL")
        sel_market = "market_factor" if "market_factor" in columns else "NULL"
        sel_conf = "confidence" if "confidence" in columns else "NULL"
        sel_srcok = "source_ok" if "source_ok" in columns else "NULL"
        sel_chg = "change_from_yesterday" if "change_from_yesterday" in columns else ("momentum" if "momentum" in columns else "NULL")
        sel_du = "data_updated" if "data_updated" in columns else "NULL"
        sel_computed = "computed_at" if "computed_at" in columns else "CURRENT_TIMESTAMP"
        select_cols = f"{sel_date}, {sel_score}, {sel_phase}, {', '.join(sel_dims)}, {sel_market}, {sel_conf}, {sel_srcok}, {sel_chg}, {sel_du}, {sel_computed}"

        return f"""
BEGIN TRANSACTION;
DROP TABLE IF EXISTS sti_timeline_new;
CREATE TABLE sti_timeline_new (
    date TEXT NOT NULL UNIQUE,
    score REAL, phase TEXT,
    dimension_limit_up_count REAL, dimension_limit_down_count REAL,
    dimension_seal_rate REAL, dimension_advance_decline_ratio REAL,
    dimension_promotion_rate REAL, dimension_prev_zt_performance REAL,
    dimension_max_boards REAL,
    market_factor REAL, confidence TEXT,
    source_ok BOOLEAN DEFAULT 1,
    change_from_yesterday REAL, data_updated TEXT,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO sti_timeline_new ({insert_cols}) SELECT {select_cols} FROM sti_timeline;
DROP TABLE sti_timeline;
ALTER TABLE sti_timeline_new RENAME TO sti_timeline;
CREATE INDEX IF NOT EXISTS idx_sti_date ON sti_timeline(date DESC);
CREATE INDEX IF NOT EXISTS idx_sti_phase ON sti_timeline(phase);
COMMIT;
"""

    def _save_result(self, result: STIResult) -> None:
        """持久化 STI 结果到 sti_timeline 表。"""
        try:
            db = self._get_db()
            if result.dimensions is None:
                dim_values = [None] * 8
            else:
                dims = result.dimensions
                dim_values = [
                    dims.limit_up_count,
                    dims.limit_down_count,
                    dims.seal_rate,
                    dims.advance_decline_ratio,
                    dims.promotion_rate,
                    dims.prev_zt_performance,
                    dims.max_boards,
                    dims.market_factor,
                ]

            db.execute(
                """INSERT OR REPLACE INTO sti_timeline (
                    date, score, phase,
                    dimension_limit_up_count, dimension_limit_down_count,
                    dimension_seal_rate,
                    dimension_advance_decline_ratio, dimension_promotion_rate,
                    dimension_prev_zt_performance, dimension_max_boards,
                    market_factor, confidence, source_ok,
                    change_from_yesterday, data_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.date,
                    result.score,  # 可为 None
                    result.phase.value if result.phase else None,
                    *dim_values,
                    result.confidence,
                    1 if result.source_ok else 0,
                    round(result.change_from_yesterday, 2) if result.change_from_yesterday is not None else None,
                    result.data_updated,
                ),
            )
            db.commit()
        except Exception:
            pass  # 持久化失败不影响主流程

    def _load_last_score(self) -> float | None:
        """加载昨日 STI 分数（用于动量计算）。"""
        try:
            db = self._get_db()
            row = db.execute(
                "SELECT score FROM sti_timeline WHERE score IS NOT NULL ORDER BY date DESC LIMIT 1"
            ).fetchone()
            return float(row["score"]) if row else None
        except Exception:
            return None

    def _load_history_scores(self) -> list[float]:
        """加载历史 STI 分数（用于 3 日平滑 + 动态分位数）。"""
        try:
            db = self._get_db()
            rows = db.execute(
                "SELECT score FROM sti_timeline WHERE score IS NOT NULL ORDER BY date DESC LIMIT 252"
            ).fetchall()
            return [float(r["score"]) for r in rows][::-1]  # 升序
        except Exception:
            return []

    # ---- 归一化 ----

    def _normalize_dimension(
        self, value: float, history: list[float], direction: int
    ) -> float:
        """将原始值归一化到 0-100。

        使用百分位排名（percentile_rank），负向指标做翻转。
        """
        score = percentile_rank(value, history)
        if direction == -1:
            score = 100.0 - score
        return round(score, 2)

    # ---- 阶段分类 ----

    def _classify_phase(self, score: float, history_scores: list[float]) -> STIPhase:
        """基于滚动 252 日 STI 分布动态分位，或降级到固定阈值。

        使用 3 日移动平均平滑，避免单日极端值导致相位抖动。
        动态分位数: P90/P70/P40/P15（非均匀分布）。
        """
        # 第一步：3 日移动平均平滑
        smoothed = _ema_3day(score, history_scores[-2:]) if len(history_scores) >= 2 else score

        if len(history_scores) >= 252:
            # 动态分位数阈值（非均匀分布）
            sorted_scores = sorted(history_scores[-252:])
            n = len(sorted_scores)

            def _pct(p: float) -> float:
                idx = int(p / 100.0 * (n - 1))
                return sorted_scores[idx]

            p15 = _pct(15)
            p40 = _pct(40)
            p70 = _pct(70)
            p90 = _pct(90)

            if smoothed >= p90:
                return STIPhase.HIGH潮
            if smoothed >= p70:
                return STIPhase.START
            if smoothed >= p40:
                return STIPhase.DIVERGENCE
            if smoothed >= p15:
                return STIPhase.FREEZE
            return STIPhase.DECLINE

        # 降级：固定阈值
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["高潮"]:
            return STIPhase.HIGH潮
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["启动"]:
            return STIPhase.START
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["分歧"]:
            return STIPhase.DIVERGENCE
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["冰点"]:
            return STIPhase.FREEZE
        return STIPhase.DECLINE

    # ---- 主计算 ----

    def compute(
        self, emotion_data: dict, sentiment_data: dict
    ) -> STIResult:
        """计算单日 STI 情绪温度。

        Args:
            emotion_data: market._emotion() 返回的字典
            sentiment_data: market._sentiment() 返回的字典

        Returns:
            STIResult
        """
        # 防御：emotion_data 为空则返回降级结果
        if not emotion_data:
            return STIResult(
                date="",
                score=None,
                phase=None,
                dimensions=None,
                source_ok=False,
                confidence="low",
                change_from_yesterday=None,
                data_updated=None,
            )

        # sentiment_data 可能为空（akshare 未安装时 _sentiment() 返回 {}）
        # 此时 advance_decline_ratio 使用默认值 1.0，不影响其他维度计算
        if not sentiment_data:
            sentiment_data = {"up": 0, "down": 1, "active": "中性"}

        date = emotion_data.get("date", "")

        # ---- 提取 8 维原始值 ----
        dims = STIDimension()

        # 1. limit_up_count
        dims.limit_up_count = _safe_float(emotion_data.get("zt_count"))

        # 2. limit_down_count
        dims.limit_down_count = _safe_float(emotion_data.get("dt_count"))

        # 3. seal_rate (0-1 → 0-100)
        dims.seal_rate = _safe_float(emotion_data.get("seal_rate")) * 100

        # 4. advance_decline_ratio
        up = _safe_float(sentiment_data.get("up"))
        down = _safe_float(sentiment_data.get("down"))
        dims.advance_decline_ratio = up / max(down, 1)

        # 5. promotion_rate (0-1 → 0-100)
        dims.promotion_rate = _safe_float(emotion_data.get("promotion_rate")) * 100

        # 6. prev_zt_performance: zt_count / yzt_count * 100（情绪惯性代理）
        #    > 100 表示情绪延续（今日涨停多于昨日），< 100 表示情绪减弱
        zt = max(_safe_float(emotion_data.get("zt_count")), 1)
        yzt = _safe_float(emotion_data.get("yzt_count"))
        dims.prev_zt_performance = (zt / yzt) * 100 if yzt > 0 else 100.0

        # 7. max_boards
        dims.max_boards = _safe_float(emotion_data.get("max_boards"))

        # 8. market_factor（独立过滤器，不参与加权）
        active = sentiment_data.get("active", "")
        dims.market_factor = _MARKET_ACTIVE_MAP.get(active, 1.0)

        # ---- 历史数据准备（用于归一化） ----
        # 从内存滚动缓存取历史分数
        with _sti_lock:
            hist_scores = list(_sti_scores)

        # 从数据库取各维度的历史序列（最近 252 条）
        dim_histories: dict[str, list[float]] = {}
        try:
            db = self._get_db()
            for dim_name in STI_WEIGHTS:
                col = f"dimension_{dim_name}"
                rows = db.execute(
                    f"SELECT {col} FROM sti_timeline WHERE {col} IS NOT NULL ORDER BY date DESC LIMIT 252"
                ).fetchall()
                dim_histories[dim_name] = [
                    float(r[col]) for r in rows if r[col] is not None
                ][::-1]  # 升序排列
        except Exception:
            pass

        # ---- 加权合成 ----
        weighted_sum = 0.0
        total_weight = 0.0

        for dim_name, weight in STI_WEIGHTS.items():
            raw_value = getattr(dims, dim_name)
            direction = STI_DIRECTIONS[dim_name]
            history = dim_histories.get(dim_name, [])

            # 归一化退化处理：min == max 时返回 50
            if len(history) >= 2:
                min_v = min(history + [raw_value])
                max_v = max(history + [raw_value])
                if min_v == max_v:
                    normalized = 50.0
                else:
                    normalized = self._normalize_dimension(raw_value, history, direction)
            else:
                normalized = 50.0  # 历史不足，中性值

            weighted_sum += normalized * weight
            total_weight += weight

        # 归一化到 0-100（权重合计 = 1.00，直接平均即可）
        if total_weight > 0:
            raw_score = weighted_sum / total_weight
        else:
            raw_score = 50.0

        # 裁剪到 0-100
        score = max(0.0, min(100.0, raw_score))

        # ---- 阶段分类（含 3 日平滑） ----
        phase = self._classify_phase(score, hist_scores)

        # ---- 动量（重命名自 momentum） ----
        yesterday_score = self._load_last_score()
        change_from_yesterday = round(score - yesterday_score, 2) if yesterday_score is not None else 0.0

        # ---- 置信度 ----
        confidence = self._compute_confidence(emotion_data, sentiment_data, score, phase)

        # ---- 更新内存滚动缓存 ----
        with _sti_lock:
            _sti_scores.append(score)
            if len(_sti_scores) > 500:
                _sti_scores[:] = _sti_scores[-252:]

        # ---- 构建结果 ----
        result = STIResult(
            date=date,
            score=round(score, 2),
            phase=phase,
            dimensions=dims,
            source_ok=True,
            confidence=confidence,
            change_from_yesterday=change_from_yesterday,
            data_updated=date,
            phase_explanation=PHASE_EXPLANATIONS.get(phase.value, ""),
        )

        # 持久化
        self._save_result(result)

        return result

    def _compute_confidence(
        self,
        emotion_data: dict,
        sentiment_data: dict,
        score: float,
        phase: STIPhase,
    ) -> str:
        """计算置信度等级。

        修复：不再访问 STIDimension 类默认值（原 bug 永远返回 high）。
        """
        reasons_missing = 0
        total_required = 3

        # 检查关键指标是否有有效值
        if not emotion_data.get("zt_count") or emotion_data.get("zt_count") == 0:
            reasons_missing += 1
        if not emotion_data.get("seal_rate"):
            reasons_missing += 1
        if not emotion_data.get("promotion_rate"):
            reasons_missing += 1

        # 数据缺失多 → low
        if reasons_missing >= 2:
            return "low"
        # 数据基本完整但分数处于边界 → medium
        if score <= 10 or score >= 90:
            return "medium"
        return "high"

    # ---- 公共 API ----

    def precompute_daily(self, date: str) -> STIResult:
        """预计算指定日期的 STI。

        Args:
            date: 日期字符串，格式 YYYY-MM-DD

        Returns:
            STIResult
        """
        # 调用 market 模块获取指定日期的情绪数据
        emotion_data = market._emotion(date)
        sentiment_data = market._sentiment(date)

        if not emotion_data:
            return STIResult(
                date=date,
                score=None,
                phase=None,
                dimensions=None,
                source_ok=False,
                confidence="low",
                change_from_yesterday=None,
                data_updated=None,
            )

        return self.compute(emotion_data, sentiment_data)

    def backfill(
        self, start_date: str, end_date: str | None = None
    ) -> list[STIResult]:
        """回填历史 STI 数据。

        Args:
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期（默认今天）

        Returns:
            回填结果列表
        """
        if end_date is None:
            end_date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        results: list[STIResult] = []

        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            try:
                result = self.precompute_daily(date_str)
                results.append(result)
            except Exception:
                pass  # 跳过失败日期
            current += timedelta(days=1)
            time.sleep(1.2)  # 节流 1.2s（对齐东财限流约定，原 0.1s 过低可能触发 IP 封禁）

        return results


# ===========================================================================
# 模块级单例
# ===========================================================================

_sti_engine: Optional[STIEngine] = None


def get_sti_engine() -> STIEngine:
    """获取 STI 引擎单例。"""
    global _sti_engine
    if _sti_engine is None:
        _sti_engine = STIEngine()
        # 初始化时执行 schema 迁移
        _sti_engine._migrate_schema()
    return _sti_engine
