# -*- coding: utf-8 -*-
"""S206 价格预警：持仓/自选支撑压力位实时监控 + 飞书推送（executor）。

盘中扫 price_alerts 标的，tencent_quote 取现价，触及支撑1/2/压力1/2 → 飞书推送。
复用 astock.tencent_quote + NotificationService.send + R4 gap_scan 模式。
不直接触发买卖（§1 弱合规半自动化助手）。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 默认标的（用户 2026-09-13 给的 5 只科技股 + 支撑/压力位）
DEFAULT_ALERTS = [
    {"code": "002156", "name": "通富微电", "support1": 58.50, "support2": 57.97, "resistance1": 60.00, "resistance2": 61.50},
    {"code": "002185", "name": "华天科技", "support1": 15.80, "support2": 15.50, "resistance1": 16.50, "resistance2": 17.00},
    {"code": "002281", "name": "光迅科技", "support1": 180.00, "support2": 178.00, "resistance1": 185.00, "resistance2": 190.00},
    {"code": "600522", "name": "中天科技", "support1": 32.50, "support2": 32.00, "resistance1": 33.50, "resistance2": 34.00},
    {"code": "600584", "name": "长电科技", "support1": 68.00, "support2": 67.50, "resistance1": 70.00, "resistance2": 71.50},
]

_ALERTS_DB: str | None = None


def _get_alerts_db() -> str:
    """price_alerts 表 DB 路径（复用 vr.db）。"""
    global _ALERTS_DB
    if _ALERTS_DB is None:
        from vr_paths import resolve_data_dir
        _ALERTS_DB = str(resolve_data_dir() / "vr.db")
    return _ALERTS_DB


def _ensure_price_alerts_table() -> None:
    """建 price_alerts 表（code PK + name + 支撑1/2 + 压力1/2）+ seed 默认 5 标的。"""
    import sqlite3
    db = sqlite3.connect(_get_alerts_db(), timeout=10)
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS price_alerts (
                code TEXT PRIMARY KEY,
                name TEXT,
                support1 REAL,
                support2 REAL,
                resistance1 REAL,
                resistance2 REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for a in DEFAULT_ALERTS:
            db.execute("""
                INSERT OR IGNORE INTO price_alerts (code, name, support1, support2, resistance1, resistance2)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (a["code"], a["name"], a["support1"], a["support2"], a["resistance1"], a["resistance2"]))
        db.commit()
    finally:
        db.close()


def _get_alerts() -> list[dict]:
    """取所有 price_alerts。"""
    import sqlite3
    _ensure_price_alerts_table()
    db = sqlite3.connect(_get_alerts_db(), timeout=10)
    try:
        rows = db.execute(
            "SELECT code, name, support1, support2, resistance1, resistance2 FROM price_alerts"
        ).fetchall()
        return [
            {"code": r[0], "name": r[1], "support1": r[2], "support2": r[3],
             "resistance1": r[4], "resistance2": r[5]}
            for r in rows
        ]
    finally:
        db.close()


def _extract_price(quote: dict) -> float:
    """从容错多字段取现价（quote_from_tencent 返 model_dump）。"""
    for k in ("price", "current_price", "last", "close", "current"):
        v = quote.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _check_alerts(prices: dict, alerts: list[dict]) -> list[dict]:
    """比对现价 vs 支撑/压力位，返触及预警列表。"""
    triggered = []
    for a in alerts:
        q = prices.get(a["code"])
        if not q:
            continue
        price = _extract_price(q)
        if price <= 0:
            continue
        name, code = a["name"], a["code"]
        # 压力位（向上突破/触及）
        if a["resistance2"] and price >= a["resistance2"]:
            triggered.append({"code": code, "name": name, "price": price,
                               "level": f"压力2 {a['resistance2']}", "direction": "突破压力2"})
        elif a["resistance1"] and price >= a["resistance1"]:
            triggered.append({"code": code, "name": name, "price": price,
                               "level": f"压力1 {a['resistance1']}", "direction": "触及压力1"})
        # 支撑位（向下跌破/触及）
        if a["support2"] and price <= a["support2"]:
            triggered.append({"code": code, "name": name, "price": price,
                               "level": f"支撑2 {a['support2']}", "direction": "跌破支撑2"})
        elif a["support1"] and price <= a["support1"]:
            triggered.append({"code": code, "name": name, "price": price,
                               "level": f"支撑1 {a['support1']}", "direction": "触及支撑1"})
    return triggered


def _build_alert_content(triggered: list[dict]) -> str:
    """格式化价格预警为 markdown。"""
    lines = [f"## ⚡ 价格预警（{len(triggered)} 只触及支撑/压力位）", ""]
    for t in triggered:
        emoji = "🔴" if "跌破" in t["direction"] else "🟢" if "突破" in t["direction"] else "⚠️"
        lines.append(
            f"- {emoji} **{t['name']}**({t['code']}) 现价 {t['price']} — {t['direction']}（{t['level']}）"
        )
    # 相关新闻 + AI 研判（触及标的实时推送）
    for t in triggered:
        news = t.get("news", [])
        fusion = t.get("fusion", "")
        if news or fusion:
            lines.append(f"\n### {t['name']}({t['code']}) 相关信息")
            if news:
                lines.append("**近期研报/资讯**：")
                for n in news[:3]:
                    title = n.get("title", "") if isinstance(n, dict) else str(n)
                    lines.append(f"  - {title}")
            if fusion:
                lines.append(f"\n**AI 研判（融合：缺口 regime + 融合分 + 相似 case）**：\n{fusion}")
    lines.append("")
    lines.append("> ⚠️ 历史统计特征，不代表未来行为。仅作研究参考，不构成投资建议。")
    return "\n".join(lines)


def scan_price_alerts(payload: dict[str, Any]) -> dict[str, Any]:
    """扫 price_alerts 标的现价 + 比对支撑/压力位 + 推送触及预警。

    payload: {date: optional}
    返 {status, scanned, alerts, triggered_codes}。推送失败不阻断。
    """
    import astock  # noqa: PLC0415
    from data import mappers  # noqa: PLC0415
    from notification.notification_service import NotificationService  # noqa: PLC0415

    alerts = _get_alerts()
    if not alerts:
        return {"status": "ok", "note": "price_alerts 空", "scanned": 0, "alerts": 0}

    codes = [a["code"] for a in alerts]
    try:
        raw = astock.tencent_quote(codes)
        prices = {c: mappers.quote_from_tencent(c, r).model_dump(mode="json") for c, r in raw.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[price_monitor] tencent_quote 失败: %s", exc)
        return {"status": "error", "scanned": 0, "alerts": 0, "error": str(exc)}

    triggered = _check_alerts(prices, alerts)
    if not triggered:
        return {"status": "ok", "scanned": len(codes), "alerts": 0, "triggered": 0}

    # 触及 → 加相关新闻 + AI 研判（fusion context：缺口 regime + 融合分 + 相似 case）
    for t in triggered:
        code = t["code"]
        try:
            from ai.tools.stock_tools import query_reports  # noqa: PLC0415
            t["news"] = query_reports(code)[:3]
        except Exception:  # noqa: BLE001
            t["news"] = []
        try:
            from engine.fusion_pipeline import compute_fusion_for_query  # noqa: PLC0415
            from engine.fusion_layer import build_fusion_context  # noqa: PLC0415
            fusion = compute_fusion_for_query(code)
            t["fusion"] = build_fusion_context(fusion)
        except Exception:  # noqa: BLE001
            t["fusion"] = ""

    content = _build_alert_content(triggered)
    try:
        ns = NotificationService()
        if ns.is_available():
            import datetime
            today = datetime.date.today().isoformat()
            ns.send(content, route_type="alert", severity="warning",
                    dedup_key=f"price_alert_{today}")
            logger.info("[price_monitor] 推送 %d 只价格预警", len(triggered))
        else:
            logger.warning("[price_monitor] NotificationService 不可用，跳过推送（triggered=%d）", len(triggered))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[price_monitor] 推送失败: %s", exc)

    return {
        "status": "ok",
        "scanned": len(codes),
        "alerts": len(triggered),
        "triggered_codes": [t["code"] for t in triggered],
    }
