# -*- coding: utf-8 -*-
"""limitup_sti 服务层 —— STI 引擎核心逻辑。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, date as _date_cls
from typing import Optional

import market

from vr_paths import is_trading_day

from limitup_sti.models import (
    STIPhase,
    STIDimension,
    STIResult,
    STI_WEIGHTS,
    STI_DIRECTIONS,
    _MARKET_ACTIVE_MAP,
    _FALLBACK_PHASE_THRESHOLDS,
    PHASE_EXPLANATIONS,
    percentile_rank,
    _safe_float,
    _ema_3day,
)
from limitup_sti.data import (
    run_initial_migrations,
    get_db,
    migrate_schema,
    save_result,
    load_last_score,
    load_history_scores,
)

_BEIJING_TZ = datetime.now(market.BEIJING).astimezone().tzinfo
_logger = logging.getLogger(__name__)


class STIEngine:
    """情绪温度指数引擎（8 维加权 + 1 维独立过滤）。"""

    def __init__(self):
        self._db: Optional[sqlite3.Connection] = None
        self._db_lock = threading.Lock()
        self._run_initial_migrations()

    def _run_initial_migrations(self) -> None:
        """执行初始 schema 迁移（仅一次）。"""
        run_initial_migrations()

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            with self._db_lock:
                if self._db is None:
                    self._db = get_db()
        return self._db

    def _migrate_schema(self) -> None:
        """迁移旧 schema。"""
        db = self._get_db()
        migrate_schema(db)

    def _save_result(self, result: STIResult) -> None:
        """持久化 STI 结果到 sti_timeline 表。"""
        save_result(result)

    def _load_last_score(self) -> float | None:
        """加载昨日 STI 分数（用于动量计算）。"""
        return load_last_score()

    def _load_history_scores(self) -> list[float]:
        """加载历史 STI 分数（用于 3 日平滑 + 动态分位数）。"""
        return load_history_scores()

    def _normalize_dimension(
        self, value: float, history: list[float], direction: int
    ) -> float:
        """将原始值归一化到 0-100。"""
        score = percentile_rank(value, history)
        if direction == -1:
            score = 100.0 - score
        return round(score, 2)

    def _classify_phase(self, score: float, history_scores: list[float]) -> STIPhase:
        """基于滚动 252 日 STI 分布动态分位，或降级到固定阈值。"""
        smoothed = _ema_3day(score, history_scores[-2:]) if len(history_scores) >= 2 else score

        if len(history_scores) >= 252:
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

        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["高潮"]:
            return STIPhase.HIGH潮
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["启动"]:
            return STIPhase.START
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["分歧"]:
            return STIPhase.DIVERGENCE
        if smoothed >= _FALLBACK_PHASE_THRESHOLDS["冰点"]:
            return STIPhase.FREEZE
        return STIPhase.DECLINE

    def compute(self, emotion_data: dict, sentiment_data: dict) -> STIResult:
        """计算单日 STI 情绪温度。"""
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

        # Fix C：防御性断言——非交易日（周末/节假日）直接降级返回，
        # 即使调度层漏了守卫也不会产生垃圾行。emotion_data["date"] 形如 "2026-08-22"。
        _raw_date = emotion_data.get("date", "")
        try:
            _parsed = _date_cls.fromisoformat(str(_raw_date))
            if not is_trading_day(_parsed):
                return STIResult(
                    date=str(_raw_date),
                    score=None,
                    phase=None,
                    dimensions=None,
                    source_ok=False,
                    confidence="low",
                    change_from_yesterday=None,
                    data_updated=None,
                    data_freshness="expired",
                    data_age_seconds=0.0,
                )
        except (ValueError, TypeError):
            # 日期格式异常无法判定，交由下游正常流程处理（空串走原 if not emotion_data 分支）
            pass

        if not sentiment_data:
            sentiment_data = {"up": 0, "down": 1, "active": "中性"}

        date = emotion_data.get("date", "")
        dims = STIDimension()

        dims.limit_up_count = _safe_float(emotion_data.get("zt_count"))
        dims.limit_down_count = _safe_float(emotion_data.get("dt_count"))
        dims.seal_rate = _safe_float(emotion_data.get("seal_rate")) * 100
        # S063 T4 补齐：保留原始炸板率（0-1），盘前简报 T-1 直读。
        # 显式区分 None（数据缺失→DB NULL→简报 "--"）vs 0.0（valid: 无炸板），
        # 不能用 _safe_float（默认 0.0 会把 None 误存为 0.0 → 简报误显 "0.000"）。
        _br_raw = emotion_data.get("break_rate")
        raw_break_rate = float(_br_raw) if _br_raw is not None else None
        # T18：真实涨停数（akshare legu 源）——非加权维度，仅落库供盘前简报 T-1 直读。
        # 显式区分 None（历史日 _sentiment 返 {} → DB NULL → 简报 "--"）vs 数值（valid），
        # 不用 _safe_float（默认 0.0 会把 None 误存为 0.0），镜像 raw_break_rate 处理范式。
        _zt_real_raw = sentiment_data.get("zt_real")
        zt_real = float(_zt_real_raw) if _zt_real_raw is not None else None
        up = _safe_float(sentiment_data.get("up"))
        down = _safe_float(sentiment_data.get("down"))
        dims.advance_decline_ratio = up / max(down, 1)
        dims.promotion_rate = _safe_float(emotion_data.get("promotion_rate")) * 100
        zt = max(_safe_float(emotion_data.get("zt_count")), 1)
        yzt = _safe_float(emotion_data.get("yzt_count"))
        dims.prev_zt_performance = (zt / yzt) * 100 if yzt > 0 else 100.0
        dims.max_boards = _safe_float(emotion_data.get("max_boards"))
        active = sentiment_data.get("active", "")
        dims.market_factor = _MARKET_ACTIVE_MAP.get(active, 1.0)

        with self._db_lock:
            hist_scores = self._load_history_scores()

        # 2026-08-26（.scratch/sti-fix-timeline/issues/02）：dim_histories 查询改用 get_db()
        # 新建连接（不依赖单例 _db——long-lived 进程单例连接坏致查询静默失败→dim_histories
        # 空→score=50.0）；except log 不静默 pass，降级为空不阻断计算。
        dim_histories: dict[str, list[float]] = {}
        try:
            db = get_db()
            try:
                for dim_name in STI_WEIGHTS:
                    col = f"dimension_{dim_name}"
                    rows = db.execute(
                        f"SELECT {col} FROM sti_timeline WHERE {col} IS NOT NULL ORDER BY date DESC LIMIT 252"
                    ).fetchall()
                    dim_histories[dim_name] = [
                        float(r[col]) for r in rows if r[col] is not None
                    ][::-1]
            finally:
                db.close()
        except Exception as e:
            _logger.warning("compute dim_histories 查询失败（降级为空，不阻断）: %s", e)
            dim_histories = {}

        weighted_sum = 0.0
        total_weight = 0.0

        for dim_name, weight in STI_WEIGHTS.items():
            raw_value = getattr(dims, dim_name)
            direction = STI_DIRECTIONS[dim_name]
            history = dim_histories.get(dim_name, [])

            if len(history) >= 2:
                min_v = min(history + [raw_value])
                max_v = max(history + [raw_value])
                if min_v == max_v:
                    normalized = 50.0
                else:
                    normalized = self._normalize_dimension(raw_value, history, direction)
            else:
                normalized = 50.0

            weighted_sum += normalized * weight
            total_weight += weight

        if total_weight > 0:
            raw_score = weighted_sum / total_weight
        else:
            raw_score = 50.0

        score = max(0.0, min(100.0, raw_score))
        phase = self._classify_phase(score, hist_scores)
        yesterday_score = self._load_last_score()
        change_from_yesterday = round(score - yesterday_score, 2) if yesterday_score is not None else 0.0

        confidence = self._compute_confidence(emotion_data, sentiment_data, score, phase)

        with self._db_lock:
            hist_scores.append(score)
            if len(hist_scores) > 500:
                hist_scores[:] = hist_scores[-252:]

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
            data_freshness="fresh",
            data_age_seconds=0.0,
            raw_break_rate=raw_break_rate,
            zt_real=zt_real,
        )

        # 2026-08-26（review M2）：save 失败不抛——已算 score 不丢弃，log 降级返回 result。
        # workflow fallback（routers/workflow.py:391）依赖 compute 返回 sti 拿 score，若 save 抛
        # 会致 sti_score=None（回归）。run.status 记 save 失败见 backlog（M1，需改 execute()）。
        try:
            self._save_result(result)
        except Exception as e:
            _logger.warning("compute save_result 失败（已算 score 不丢弃，降级返回）: %s", e, exc_info=True)
        return result

    def _compute_confidence(
        self,
        emotion_data: dict,
        sentiment_data: dict,
        score: float,
        phase: STIPhase,
    ) -> str:
        """计算置信度等级。"""
        reasons_missing = 0
        total_required = 3

        if not emotion_data.get("zt_count") or emotion_data.get("zt_count") == 0:
            reasons_missing += 1
        if not emotion_data.get("seal_rate"):
            reasons_missing += 1
        if not emotion_data.get("promotion_rate"):
            reasons_missing += 1

        if reasons_missing >= 2:
            return "low"
        if score <= 10 or score >= 90:
            return "medium"
        return "high"

    def precompute_daily(self, date: str) -> STIResult:
        """预计算指定日期的 STI。"""
        # Fix A：交易日守卫——非交易日（周末/节假日）无交易数据输入通道，
        # 拒绝计算，防周末垃圾行污染 timeline（影响 phase 分类 + change_from_yesterday）。
        # STI 保持纯交易日指标，周末信息不进 STI。
        try:
            parsed = _date_cls.fromisoformat(date)
        except (ValueError, TypeError):
            return STIResult(
                date=date,
                score=None,
                phase=None,
                dimensions=None,
                source_ok=False,
                confidence="low",
                change_from_yesterday=None,
                data_updated=None,
                data_freshness="expired",
                data_age_seconds=0.0,
            )
        if not is_trading_day(parsed):
            # 非交易日无交易数据，拒绝计算（防周末垃圾行污染 timeline）
            return STIResult(
                date=date,
                score=None,
                phase=None,
                dimensions=None,
                source_ok=False,
                confidence="low",
                change_from_yesterday=None,
                data_updated=None,
                data_freshness="expired",
                data_age_seconds=0.0,
            )

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
                data_freshness="expired",
                data_age_seconds=0.0,
            )

        return self.compute(emotion_data, sentiment_data)

    def backfill(
        self, start_date: str, end_date: str | None = None
    ) -> list[STIResult]:
        """回填历史 STI 数据。"""
        if end_date is None:
            end_date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")

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
                pass
            current += timedelta(days=1)
            time.sleep(1.2)

        return results


_sti_engine: Optional[STIEngine] = None


def get_sti_engine() -> STIEngine:
    """获取 STI 引擎单例。"""
    global _sti_engine
    if _sti_engine is None:
        _sti_engine = STIEngine()
        _sti_engine._migrate_schema()
    return _sti_engine
