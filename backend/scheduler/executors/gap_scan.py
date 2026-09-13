# -*- coding: utf-8 -*-
"""S193 R4：watchlist 缺口变盘扫描 + 飞书推送（executor）。

每日盘后扫 watchlist codes，跑 _classify_gap_from_bars，突破/衰竭变盘 → 飞书推送。
推送阈值（R5 v3 后定性，对抗审 wn80mbbm6 verdict partially-holds）：
- **突破**：趋势启动信号（cluster-robust t+9.98/Bonf0.0000 survive Bonferroni；3 日前视上界但 5/10 日稳）
- **衰竭**：continuation 正信号（全表唯一无前视 t+9.19/Bonf0.0000；regime label"反转"疑误实际延续——
  推送"衰竭出现"=趋势可能延续，非反转）
- 持续不推（中继，避免噪声）；普通不推（噪声）

复用 NotificationService.send + KlineCacheBarsProvider + _classify_gap_from_bars（cache bars 无网络）。
不直接触发买卖（§1 弱合规半自动化助手，缺口 regime 喂 AI 研判 + 用户决策）。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 推送阈值：只推突破+衰竭（spec §3 R4 + R5 v3 后定性）
ALERT_TYPES: tuple[str, ...] = ("突破", "衰竭")


def _build_gap_alert_content(alerts: list[dict], date_str: str) -> str:
    """格式化缺口变盘 alerts 为 markdown 推送内容。"""
    lines = [f"## ⚡ 缺口变盘提醒（{date_str}）", ""]
    lines.append(f"watchlist 扫到 **{len(alerts)}** 个缺口变盘：")
    lines.append("")
    for a in alerts:
        code = a["code"]
        gtype = a["type"]
        direction = a["direction"]
        regime = a["regime"]
        conf = a["confidence"]
        emoji = "🚀" if gtype == "突破" else "⚠️"
        if gtype == "突破":
            note = "趋势启动信号"
        else:  # 衰竭
            note = "continuation 信号（label 疑误，实际延续非反转）"
        lines.append(
            f"- {emoji} **{code}** {gtype}缺口（{direction}，{regime}，置信 {conf}）— {note}"
        )
    lines.append("")
    lines.append("> ⚠️ 历史统计特征，不代表未来行为。仅作研究参考，不构成投资建议。")
    return "\n".join(lines)


def scan_watchlist_gaps(payload: dict[str, Any]) -> dict[str, Any]:
    """扫 watchlist 缺口变盘 + 推送突破/衰竭。

    payload: {date: optional YYYY-MM-DD（默认扫最后 bar = 最近交易日）}
    返 {status, scanned, alerts, date, alert_codes}。推送失败不阻断（log warning）。
    """
    from candidate_funnel.sources.watchlist_in import get_watchlist_codes  # noqa: PLC0415
    from engine.bars_provider import KlineCacheBarsProvider  # noqa: PLC0415
    from engine.gap_classifier import _classify_gap_from_bars  # noqa: PLC0415
    from notification.notification_service import NotificationService  # noqa: PLC0415

    codes = get_watchlist_codes()
    if not codes:
        return {"status": "ok", "note": "watchlist 空，跳过", "scanned": 0, "alerts": 0}

    bp = KlineCacheBarsProvider()
    date_str = payload.get("date")

    alerts: list[dict] = []
    scanned = 0
    for code in codes:
        bars = bp(code)
        if not bars or len(bars) < 2:
            continue
        scanned += 1
        # 找 date_str 的 idx，默认最后 bar（最近交易日）
        idx = -1
        if date_str:
            for i, b in enumerate(bars):
                if str(b.get("date", ""))[:10] == date_str:
                    idx = i
                    break
        if idx < 0:
            idx = len(bars) - 1
        if idx < 1:
            continue
        gap = _classify_gap_from_bars(bars, idx)
        gtype = gap.get("type")
        if gtype in ALERT_TYPES:
            actual_date = str(bars[idx].get("date", ""))[:10]
            alerts.append({
                "code": code,
                "type": gtype,
                "direction": gap.get("direction"),
                "regime": gap.get("regime"),
                "confidence": gap.get("confidence"),
                "date": actual_date,
            })

    alert_date = alerts[0]["date"] if alerts else (date_str or "latest")
    if not alerts:
        return {"status": "ok", "scanned": scanned, "alerts": 0, "date": alert_date}

    content = _build_gap_alert_content(alerts, alert_date)
    try:
        ns = NotificationService()
        if ns.is_available():
            ns.send(
                content,
                route_type="alert",
                severity="info",
                dedup_key=f"gap_scan_{alert_date}",
            )
            logger.info("[gap_scan] 推送 %d 个缺口变盘（%s）", len(alerts), alert_date)
        else:
            logger.warning("[gap_scan] NotificationService 不可用，跳过推送（alerts=%d）", len(alerts))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[gap_scan] 推送失败: %s", exc)

    return {
        "status": "ok",
        "scanned": scanned,
        "alerts": len(alerts),
        "date": alert_date,
        "alert_codes": [a["code"] for a in alerts],
    }
