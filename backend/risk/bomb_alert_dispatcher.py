# -*- coding: utf-8 -*-
"""S055 T4 + S093 S2a：炸板预警去重冷却 + 历史持久化 + 飞书通知接线。

- 同股同规则 10 分钟冷却去重（BOMB_ALERT_COOLDOWN_MINUTES，可配）
- 预警分级 yellow/red/info/medium
- 预警历史落 bomb_alert_history 表（依据链 + data_status）
- 通知通道：S093 扩展为接 NotificationService.send() 推飞书卡片（含操作建议+风险提醒）
- S093 新增 process_market_alerts 处理市场级规则 C8(情绪恶化)/C9(连板断裂)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

from config import default_config, SEAL_INTRADAY_DB_PATH
from risk.bomb_alert_rules import RuleCheckResult, check_market_rules, RISK_DISCLAIMER
from vr_paths import last_trading_date_str

_logger = logging.getLogger(__name__)

# 预警级别中文映射（飞书卡片展示用）
_LEVEL_DISPLAY: dict[str, str] = {
    "yellow": "黄色",
    "red": "红色",
    "info": "INFO",
    "medium": "MEDIUM",
}

_DB_PATH = SEAL_INTRADAY_DB_PATH
_DB_LOCK = threading.Lock()

# 内存冷却记录：{(code, rule_id): last_triggered_ts}
_cooldown_cache: dict[tuple[str, str], datetime] = {}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def is_in_cooldown(code: str, rule_id: str, now: datetime | None = None) -> bool:
    """同股同规则在冷却期内不重复触发。"""
    now = now or datetime.now()
    key = (code, rule_id)
    last = _cooldown_cache.get(key)
    if last is None:
        return False
    return now < last + timedelta(minutes=default_config.BOMB_ALERT_COOLDOWN_MINUTES)


def _mark_triggered(code: str, rule_id: str, now: datetime | None = None) -> None:
    """标记触发时间，刷新冷却窗口。"""
    now = now or datetime.now()
    _cooldown_cache[(code, rule_id)] = now


def save_alert(
    code: str,
    name: str,
    result: RuleCheckResult,
    now: datetime | None = None,
) -> int | None:
    """落库炸板预警历史。返 id；冷却期内跳过返 None。"""
    now = now or datetime.now()
    if is_in_cooldown(code, result.rule_id, now):
        return None
    _mark_triggered(code, result.rule_id, now)

    if not result.alert:
        return None

    alert = result.alert
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.execute(
                """INSERT INTO bomb_alert_history
                (ts, date, code, name, rule_id, alert_level, condition_text,
                 input_snapshot, data_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now.isoformat(),
                    last_trading_date_str(now.date()),  # task 120：按交易日历落 date（非 now.strftime 日历今日，否则非交易日存写/查询错位）
                    code,
                    name,
                    result.rule_id,
                    alert.alert_level,
                    result.reason or alert.condition,
                    json.dumps({
                        "seal_amount": alert.current_seal_amount,
                        "change_5min": alert.seal_amount_change_5min,
                        "data_status": result.data_status,
                    }, ensure_ascii=False),
                    result.data_status,
                ),
            )
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def get_active_alerts(date: str | None = None) -> list[dict[str, Any]]:
    """查当日活跃预警（历史表）。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM bomb_alert_history WHERE date = ? ORDER BY ts DESC",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _build_feishu_card(
    code: str, name: str, result: RuleCheckResult,
) -> str:
    """构建飞书卡片 Markdown 内容（含操作建议 + 风险提醒）。

    历史统计特征标注："参考值，非执行指令；市场有风险"。
    """
    alert = result.alert
    if not alert:
        return ""
    level_text = _LEVEL_DISPLAY.get(alert.alert_level, alert.alert_level.upper())
    rec = alert.recommendation or "参考"
    lines = [
        f"## 🚨 炸板预警 {level_text}：{name}({code})",
        "",
        alert.condition,
        "",
        f"**操作建议**：{rec}（参考值，非执行指令）",
        "",
        f"---",
        f"⚠️ {RISK_DISCLAIMER}",
    ]
    return "\n".join(lines)


def notify_if_enabled(
    code: str, name: str, result: RuleCheckResult,
) -> bool:
    """通知通道接线（默认关）。

    S093 扩展：规则触发时接 NotificationService.send() 推飞书卡片
    （含操作建议 + 风险提醒标注）。通知失败不阻塞落库主流程，只 warning log。
    """
    if not getattr(default_config, "BOMB_ALERT_NOTIFY_ENABLE", False):
        return False
    if not result.alert:
        return False

    content = _build_feishu_card(code, name, result)
    if not content:
        return False

    try:
        # 延迟 import 避免循环依赖
        from notification.notification_service import NotificationService
        service = NotificationService()
        ok = service.send(content)
        if ok:
            _logger.info("[bomb_alert] 飞书通知已发送：%s %s(%s)", result.rule_id, name, code)
        else:
            _logger.warning("[bomb_alert] 飞书通知发送未成功（渠道可能未配置）：%s %s(%s)",
                            result.rule_id, name, code)
        return ok
    except Exception as exc:
        _logger.warning("[bomb_alert] 通知发送失败（不阻塞落库）：%s %s(%s) %s",
                        result.rule_id, name, code, exc)
        return False


def process_market_alerts(
    market_snapshot: dict[str, Any] | None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """处理市场级规则（C8/C9）：跑规则 + 去重 + 落库 + 通知。

    market_snapshot 为 intraday_sentiment 快照（含 zt_count/zb_count/ladder/max_boards）。
    返回活跃预警列表。
    """
    now = now or datetime.now()
    results = check_market_rules(market_snapshot, now)
    return process_alerts("MARKET", "市场", results, now)


def process_alerts(
    code: str,
    name: str,
    results: list[RuleCheckResult],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """处理一批规则结果：去重 + 落库 + 通知。返回活跃预警列表。"""
    now = now or datetime.now()
    active: list[dict[str, Any]] = []
    for r in results:
        if not r.triggered:
            continue
        alert_id = save_alert(code, name, r, now)
        if alert_id is None:
            continue  # 冷却期内
        notify_if_enabled(code, name, r)
        active.append({
            "id": alert_id,
            "rule_id": r.rule_id,
            "alert_level": r.alert.alert_level if r.alert else "unknown",
            "condition": r.alert.condition if r.alert else r.reason,
            "code": code,
            "name": name,
            "ts": now.isoformat(),
            "data_status": r.data_status,
        })
    return active
