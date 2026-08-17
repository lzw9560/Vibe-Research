# -*- coding: utf-8 -*-
"""S060：明日验证条件对账卡。

盘后（T 日）生成「明日验证条件」——每条带今日基准值 + 变动阈值；
T+1 盘后用实际数据对账，status 从 pending → met_up/met_down/within/data_missing。

数据源全部现成：``market._emotion``（封板率/炸板率/晋级率/连板/涨跌停家数）。
纯规则模板（客观可测），AI 出口可读卡片内容作上下文，不作为生成源。

工程底线：缺数据 → data_missing 诚实标注，不臆造。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from config import PRIVATE_DATA_DIR
from vr_paths import is_trading_day, last_trading_date_str

_logger = logging.getLogger(__name__)

_DB_PATH = str(Path(PRIVATE_DATA_DIR) / "verification_card.db")
_DB_LOCK = threading.Lock()

Status = Literal["pending", "met_up", "met_down", "within", "data_missing"]


@dataclass(frozen=True)
class VerificationCondition:
    """单条验证条件。"""
    date: str          # 生成日 YYYY-MM-DD
    metric: str        # 指标名
    subject: str       # 主体（主线板块名/空）
    baseline: float | None
    threshold_up: float | None   # 上行阈值（变动超此 → met_up）
    threshold_down: float | None  # 下行阈值（变动超此 → met_down）
    actual: float | None = None  # T+1 实际值
    status: Status = "pending"
    note: str = ""


def run_migrations() -> None:
    """执行 verification_card 迁移（幂等）。"""
    from migrations import MigrationManager

    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    manager = MigrationManager(db_path=_DB_PATH)
    migration_v1 = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "verification_card" / "20260812-001_create_verification_conditions.sql"
    ).read_text(encoding="utf-8")
    manager.upgrade([
        {"version": "20260812-001", "name": "create_verification_conditions", "sql": migration_v1},
    ])


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────── 规则模板生成器 ───────────────────────


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def generate_conditions(emotion_data: dict, date_str: str | None = None) -> list[VerificationCondition]:
    """从当日 ``market._emotion`` 数据生成 ≥5 条验证条件模板。

    模板：
    1. 涨停家数（baseline=zt_count, ±20%）
    2. 炸板率（baseline=break_rate, ±5pct）
    3. 连板高度（baseline=max_boards, ±1 板）
    4. 封板率（baseline=seal_rate, ±5pct）
    5. 晋级率（baseline=promotion_rate, ±3pct）
    6. 昨涨停今日溢价（baseline=yzt_count, 阈值=正负翻转）
    """
    date_str = date_str or emotion_data.get("date", datetime.now().strftime("%Y-%m-%d"))
    conditions: list[VerificationCondition] = []

    zt = _safe_float(emotion_data.get("zt_count"))
    br = _safe_float(emotion_data.get("break_rate"))
    mb = _safe_float(emotion_data.get("max_boards"))
    sr = _safe_float(emotion_data.get("seal_rate"))
    pr = _safe_float(emotion_data.get("promotion_rate"))
    yzt = _safe_float(emotion_data.get("yzt_count"))

    # 1. 涨停家数 ±20%
    if zt is not None and zt > 0:
        conditions.append(VerificationCondition(
            date=date_str, metric="zt_count", subject="全市场",
            baseline=zt, threshold_up=zt * 1.2, threshold_down=zt * 0.8,
            note=f"涨停家数 {int(zt)} ±20%",
        ))

    # 2. 炸板率 ±5pct
    if br is not None:
        conditions.append(VerificationCondition(
            date=date_str, metric="break_rate", subject="全市场",
            baseline=br, threshold_up=br + 0.05, threshold_down=max(0.0, br - 0.05),
            note=f"炸板率 {br:.1%} ±5pct",
        ))

    # 3. 连板高度 ±1 板
    if mb is not None and mb > 0:
        conditions.append(VerificationCondition(
            date=date_str, metric="max_boards", subject="全市场",
            baseline=mb, threshold_up=mb + 1, threshold_down=max(1.0, mb - 1),
            note=f"最高连板 {int(mb)} ±1 板",
        ))

    # 4. 封板率 ±5pct
    if sr is not None:
        conditions.append(VerificationCondition(
            date=date_str, metric="seal_rate", subject="全市场",
            baseline=sr, threshold_up=min(1.0, sr + 0.05), threshold_down=max(0.0, sr - 0.05),
            note=f"封板率 {sr:.1%} ±5pct",
        ))

    # 5. 晋级率 ±3pct
    if pr is not None:
        conditions.append(VerificationCondition(
            date=date_str, metric="promotion_rate", subject="全市场",
            baseline=pr, threshold_up=min(1.0, pr + 0.03), threshold_down=max(0.0, pr - 0.03),
            note=f"晋级率 {pr:.1%} ±3pct",
        ))

    # 6. 昨涨停家数（主线延续代理指标，-30% 视为断档）
    if yzt is not None and yzt > 0:
        conditions.append(VerificationCondition(
            date=date_str, metric="yzt_count", subject="昨涨停",
            baseline=yzt, threshold_up=yzt * 1.3, threshold_down=yzt * 0.7,
            note=f"昨涨停 {int(yzt)} ±30%（主线延续代理）",
        ))

    return conditions


# ─────────────────────── 对账器 ───────────────────────


def verify_conditions(
    pending: list[VerificationCondition],
    next_day_emotion: dict,
) -> list[VerificationCondition]:
    """T+1 盘后对账：用 next_day_emotion 实际值算 status。

    对账口径：
    - zt_count/yzt_count/max_boards：直接比 baseline vs actual（next_day 的同字段）
    - break_rate/seal_rate/promotion_rate：next_day 的同字段 vs baseline
    - yzt_count：next_day 的 zt_count（昨涨停今日溢价代理 → 今日涨停家数）
    """
    # next_day_emotion 字段映射：metric → next_day_emotion 取值 key
    metric_to_next_key = {
        "zt_count": "zt_count",
        "break_rate": "break_rate",
        "max_boards": "max_boards",
        "seal_rate": "seal_rate",
        "promotion_rate": "promotion_rate",
        "yzt_count": "zt_count",  # 昨涨停的次日对账用今日涨停家数
    }

    verified: list[VerificationCondition] = []
    for cond in pending:
        next_key = metric_to_next_key.get(cond.metric)
        if next_key is None:
            verified.append(_replace(cond, actual=None, status="data_missing",
                                     note=cond.note + "；对账字段未知"))
            continue

        actual = _safe_float(next_day_emotion.get(next_key))
        if actual is None:
            verified.append(_replace(cond, actual=None, status="data_missing",
                                     note=cond.note + "；T+1 数据缺失"))
            continue

        # 对账判定
        if cond.baseline is None:
            verified.append(_replace(cond, actual=actual, status="data_missing",
                                     note=cond.note + "；基准值缺失"))
            continue

        up = cond.threshold_up
        down = cond.threshold_down
        if up is not None and actual >= up:
            verified.append(_replace(cond, actual=actual, status="met_up",
                                     note=cond.note + f"；实际 {actual} ≥ {up}"))
        elif down is not None and actual <= down:
            verified.append(_replace(cond, actual=actual, status="met_down",
                                     note=cond.note + f"；实际 {actual} ≤ {down}"))
        else:
            verified.append(_replace(cond, actual=actual, status="within",
                                     note=cond.note + f"；实际 {actual} 在区间内"))

    return verified


def _replace(cond: VerificationCondition, **kw) -> VerificationCondition:
    """不可变更新（frozen dataclass）。"""
    return VerificationCondition(
        date=cond.date,
        metric=cond.metric,
        subject=cond.subject,
        baseline=cond.baseline,
        threshold_up=cond.threshold_up,
        threshold_down=cond.threshold_down,
        actual=kw.get("actual", cond.actual),
        status=kw.get("status", cond.status),
        note=kw.get("note", cond.note),
    )


# ─────────────────────── 持久化 ───────────────────────


def save_conditions(conditions: list[VerificationCondition]) -> int:
    """批量写入条件。返回写入行数。"""
    if not conditions:
        return 0
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.executemany(
                """INSERT INTO verification_conditions
                (date, metric, subject, baseline, threshold_up, threshold_down,
                 actual, status, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(c.date, c.metric, c.subject, c.baseline, c.threshold_up,
                  c.threshold_down, c.actual, c.status, c.note) for c in conditions],
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def update_verified(conditions: list[VerificationCondition]) -> int:
    """T+1 对账后更新 actual/status/note/verified_at。按 date+metric 匹配。"""
    if not conditions:
        return 0
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.executemany(
                """UPDATE verification_conditions
                SET actual = ?, status = ?, note = ?, verified_at = ?
                WHERE date = ? AND metric = ? AND status = 'pending'""",
                [(c.actual, c.status, c.note, now, c.date, c.metric) for c in conditions],
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def get_conditions(date_str: str | None = None) -> list[dict[str, Any]]:
    """查指定日的条件（含对账结果）。date 缺省取最近交易日。"""
    date_str = date_str or last_trading_date_str()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM verification_conditions WHERE date = ? ORDER BY id",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_conditions() -> list[dict[str, Any]]:
    """查所有 pending 条件（T+1 对账用）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM verification_conditions WHERE status = 'pending' ORDER BY date, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────── 生成 + 对账编排 ───────────────────────


def generate_and_save(emotion_data: dict, date_str: str | None = None) -> list[VerificationCondition]:
    """盘后生成条件并落库。返回生成的条件列表。"""
    conditions = generate_conditions(emotion_data, date_str)
    save_conditions(conditions)
    _logger.info("[verification_card] 生成 %d 条条件（date=%s）", len(conditions), conditions[0].date if conditions else "?")
    return conditions


def verify_and_update() -> list[VerificationCondition]:
    """T+1 盘后对账：取所有 pending 条件，用昨日情绪数据对账并更新。

    返回对账后的条件列表（含 verified status）。
    """
    import market

    pending_rows = get_pending_conditions()
    if not pending_rows:
        return []

    # 按 date 分组，每组用 date+1 的情绪对账
    by_date: dict[str, list[VerificationCondition]] = {}
    for r in pending_rows:
        cond = VerificationCondition(
            date=r["date"], metric=r["metric"], subject=r["subject"] or "",
            baseline=r["baseline"], threshold_up=r["threshold_up"],
            threshold_down=r["threshold_down"], actual=r["actual"],
            status=r["status"], note=r["note"] or "",
        )
        by_date.setdefault(r["date"], []).append(cond)

    all_verified: list[VerificationCondition] = []
    for gen_date, conds in by_date.items():
        # 对账日 = gen_date 的下一交易日
        gen_d = datetime.strptime(gen_date, "%Y-%m-%d").date()
        next_d = gen_d + timedelta(days=1)
        while not is_trading_day(next_d) and (next_d - gen_d).days < 10:
            next_d = next_d + timedelta(days=1)
        next_date_str = next_d.isoformat()
        try:
            next_emotion = market._emotion(next_date_str)
        except Exception as exc:
            _logger.warning("[verification_card] 取 %s 情绪失败: %s", next_date_str, exc)
            next_emotion = {}

        if not next_emotion:
            # 数据缺失 → 全标 data_missing
            for c in conds:
                all_verified.append(_replace(c, actual=None, status="data_missing",
                                             note=c.note + "；T+1 情绪数据未取得"))
        else:
            verified = verify_conditions(conds, next_emotion)
            all_verified.extend(verified)

    update_verified(all_verified)
    _logger.info("[verification_card] 对账 %d 条条件", len(all_verified))
    return all_verified


# ─────────────────────── 启动时迁移 ───────────────────────

_migrations_applied = False


def ensure_migrations() -> None:
    """启动时调用一次，幂等。请求路径不再调 run_migrations。

    `run_migrations()` 无 try/except，SQLite 并发锁或文件系统异常会抛异常。
    旧实现将其挂在三个请求路径函数（get_conditions/generate_and_save/
    verify_and_update）里，每次请求触发 → 路由层 `except Exception` 转 502。
    现移到 app lifespan startup 执行一次，并以 `_migrations_applied` 缓存。
    """
    global _migrations_applied
    if _migrations_applied:
        return
    run_migrations()
    _migrations_applied = True
