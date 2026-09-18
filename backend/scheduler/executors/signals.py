# -*- coding: utf-8 -*-
"""S218: 每日信号报告 + 关键点位决策通知 scheduler executor。

daily_report ——生成并可选推送每日信号报告（C1）。
keypoint_notify ——关键点位提醒：D 收盘入场 / D+1 开盘出场 / gap-down 诚实标（C3）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.signal_report import get_consecutive_relay_signals, render_daily_report

logger = logging.getLogger("vibe-research")

#: 信号记录存储路径（.vibe-research/，不进 git）
_SIGNAL_DIR = Path(__file__).resolve().parents[3] / ".vibe-research" / "signal_reports"


def _save_signal_record(signals: dict[str, Any]) -> Path:
    """保存信号记录到 .vibe-research/signal_reports/（gitignored）。"""
    _SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    date = signals.get("date", datetime.now().strftime("%Y-%m-%d"))
    path = _SIGNAL_DIR / f"{date}_signal_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(signals, f, ensure_ascii=False, indent=2, default=str)
    return path


def daily_report(payload: dict[str, Any]) -> dict[str, Any]:
    """S218 每日信号报告 domain function。

    流程：
    1. get_consecutive_relay_signals → 结构化 dict
    2. render_daily_report → 人话文本
    3. _save_signal_record → .vibe-research/signal_reports/
    4. optional notify（飞书）

    Args:
        payload: {"run_date": "2026-09-18"}（可选，默认今天）

    Returns:
        {"status": "ok", "signals": int, "report_path": str, "report_text": str}
    """
    run_date = payload.get("run_date") or datetime.now().strftime("%Y-%m-%d")
    logger.info("[S218] daily_report start: date=%s", run_date)

    # 1. 生成信号
    signals = get_consecutive_relay_signals(run_date)

    # 2. 渲染报告
    report_text = render_daily_report(signals)

    # 3. 保存记录
    try:
        report_path = _save_signal_record(signals)
    except OSError as e:
        logger.warning("[S218] 保存信号记录失败: %s", e)
        report_path = None

    # 4. 可选推送（飞书）
    if payload.get("notify"):
        try:
            from notification.notification_service import get_notification_service
            service = get_notification_service()
            if hasattr(service, "send"):
                service.send(report_text)
        except Exception as e:  # noqa: BLE001
            logger.warning("[S218] 通知推送失败: %s", e)

    return {
        "status": "ok",
        "date": run_date,
        "signals": len(signals.get("signals", [])),
        "report_path": str(report_path) if report_path else None,
        "report_text": report_text,
    }


# ── C3: keypoint_notify ───────────────────────────────────────────────────

def _send_text_notification(text: str) -> None:
    """通过 NotificationService 发送纯文本通知（复用 _send_notification 路径）。"""
    try:
        from notification.notification_service import get_notification_service
        service = get_notification_service()
        if hasattr(service, "send"):
            service.send(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("[S218] 通知推送失败: %s", e)


def _render_d_close_entry(signals: dict[str, Any]) -> str:
    """D 收盘入场通知：今日收盘买这些。"""
    date = signals.get("date", "")
    sig_list = signals.get("signals", [])
    regime = signals.get("regime", {}).get("current", "unknown")
    cap = signals.get("cap", {}).get("effective", 1.0)

    tradable = [s for s in sig_list if s.get("bucket") == "tradable"]
    exploratory = [s for s in sig_list if s.get("bucket") == "exploratory"]

    lines: list[str] = []
    lines.append(f"=== {date} D 收盘入场通知 ===")
    lines.append("")
    lines.append(f"今日 {len(tradable)} 只可做 + {len(exploratory)} 只探索性（bear underpowered）")
    lines.append("")

    # 可做（bull validated）
    lines.append("【可做】—— bull edge validated，×0.75")
    for s in tradable:
        price = s.get("entry_price")
        price_str = f"¥{price:.2f}" if price is not None else "N/A"
        lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）— 参考价 {price_str}")
    if not tradable:
        lines.append("  无")
    lines.append("")

    # 探索性（bear/range underpowered）
    if exploratory:
        lines.append("【探索性】—— bear/range underpowered（<60 test 天没法定），×0.5 保守")
        for s in exploratory:
            price = s.get("entry_price")
            price_str = f"¥{price:.2f}" if price is not None else "N/A"
            lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）— 参考价 {price_str}")
        lines.append("  （bear edge 未 validated，谨慎参考）")
        lines.append("")

    # 入场指引
    lines.append("【入场指引】")
    lines.append("  入场 = 今日 14:57-15:00 收盘集合竞价市价买")
    lines.append("  实际成交价 ≈ 参考价 ± 小范围波动")
    lines.append("")

    # §44 诚实性标注
    lines.append("【重要说明】")
    lines.append("  统计验证（非已实现收益）—— edge 衰减中（train 1.57%→test 1.04% 跌 34%）")
    lines.append("  paper-only 无券商（零真交易）—— 接券商前所有战绩 paper")
    lines.append(f"  照做有风险 —— cap ×{cap} 是统计信心不是保本，真钱仓位由你手动定")
    lines.append("  非自动交易 —— 须手动在券商下单")
    lines.append("")

    # 一字跌停 gotcha
    lines.append("【风险提示】")
    lines.append("  若 D+1 开盘一字跌停，出场可能卖不掉，实际收益比预估差")
    lines.append("")

    return "\n".join(lines)


def _render_d1_open_exit(signals: dict[str, Any]) -> str:
    """D+1 开盘出场通知：开盘卖这些。"""
    date = signals.get("date", "")
    sig_list = signals.get("signals", [])
    regime = signals.get("regime", {}).get("current", "unknown")
    cap = signals.get("cap", {}).get("effective", 1.0)

    # 出场只关注 tradable + exploratory（avoid 不交易）
    active = [s for s in sig_list if s.get("bucket") in ("tradable", "exploratory")]

    lines: list[str] = []
    lines.append(f"=== {date} D+1 开盘出场通知 ===")
    lines.append("")
    lines.append(f"{len(active)} 只待出场 —— D+1 09:30 开盘市价卖")
    lines.append("")

    for s in active:
        price = s.get("entry_price")
        price_str = f"¥{price:.2f}" if price is not None else "N/A"
        lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）— 参考入场价 {price_str}")
    if not active:
        lines.append("  无")
    lines.append("")

    lines.append("【出场指引】")
    lines.append("  出场 = D+1 09:30 开盘市价卖")
    lines.append("  gap_net_return 假设 D+1 开盘能卖，但 lbc≥2 股 D+1 一字跌停卖不掉")
    lines.append("  → 实际收益可能比测的差，待量化")
    lines.append("")

    # §44 诚实性
    lines.append("【重要说明】")
    lines.append("  统计验证（非已实现收益）—— paper-only 无券商（零真交易）")
    lines.append(f"  照做有风险 —— cap ×{cap} 是统计信心不是保本")
    lines.append("  非自动交易 —— 须手动在券商下单")

    return "\n".join(lines)


def _render_gapdown_honest_label(signals: dict[str, Any]) -> str:
    """gap-down 诚实标通知：非止损，是诚实风险标签。"""
    date = signals.get("date", "")
    sig_list = signals.get("signals", [])
    cap = signals.get("cap", {}).get("effective", 1.0)

    active = [s for s in sig_list if s.get("bucket") in ("tradable", "exploratory")]

    lines: list[str] = []
    lines.append(f"=== {date} gap-down 诚实标通知 ===")
    lines.append("")
    lines.append("【这不是止损提醒】")
    lines.append("  做T/补救对 1-bar gap 结构性不适用：")
    lines.append("  - 无日内窗口（1-bar gap）")
    lines.append("  - T+1 禁同日卖，无底仓")
    lines.append("  - exit=D+1 开盘 gap-down 点实现，非 preempt")
    lines.append("  - record_t0_fill 生产零调用")
    lines.append("")
    lines.append("【真实风控】")
    lines.append(f"  仓位 sizing（×{cap}）+ gap-down 诚实标")
    lines.append("  非 stop-loss 保护 —— stop 对隔夜 gap-down 是仪式非保护")
    lines.append("  停损价只在能成交价位生效，隔夜跳空可击穿停损价开盘")
    lines.append("")

    lines.append(f"{len(active)} 只持仓待观察：")
    for s in active:
        lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）")
    if not active:
        lines.append("  无")
    lines.append("")

    # 一字跌停 gotcha
    lines.append("【风险提示】")
    lines.append("  若 D+1 开盘一字跌停，出场可能卖不掉，实际收益比预估差")
    lines.append("")

    # §44 诚实性
    lines.append("【重要说明】")
    lines.append("  统计验证（非已实现收益）—— paper-only 无券商（零真交易）")
    lines.append(f"  照做有风险 —— cap ×{cap} 是统计信心不是保本，真钱仓位由你手动定")
    lines.append("  非自动交易 —— 须手动在券商下单")

    return "\n".join(lines)


def keypoint_notify(payload: dict[str, Any]) -> dict[str, Any]:
    """S218 C3: 关键点位决策通知。

    复用 C1 shared core（get_consecutive_relay_signals），不重复 scan+regime+lift。
    产生 3 条 time-triggered 通知：
      1. D 收盘入场（15:00 触发）
      2. D+1 开盘出场（09:30 触发）
      3. gap-down 诚实标（检测到 gap-down 时触发，非止损）
    """
    run_date = payload.get("run_date") or datetime.now().strftime("%Y-%m-%d")
    logger.info("[S218] keypoint_notify start: date=%s", run_date)

    # 1. 复用 C1 shared core（不重复 scan+regime+lift）
    signals = get_consecutive_relay_signals(run_date)

    # 2. 生成 3 条通知
    d_close_text = _render_d_close_entry(signals)
    d1_open_text = _render_d1_open_exit(signals)
    gapdown_text = _render_gapdown_honest_label(signals)

    notifications = [
        {"title": f"{run_date} D 收盘入场", "body": d_close_text, "type": "d_close_entry"},
        {"title": f"{run_date} D+1 开盘出场", "body": d1_open_text, "type": "d1_open_exit"},
        {"title": f"{run_date} gap-down 诚实标", "body": gapdown_text, "type": "gapdown_honest"},
    ]

    # 3. 保存通知记录（.vibe-research/，gitignored）
    try:
        _SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
        record_path = _SIGNAL_DIR / f"{run_date}_keypoint_notify.json"
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(
                {"date": run_date, "notifications": notifications},
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
    except OSError as e:
        logger.warning("[S218] 保存 keypoint_notify 记录失败: %s", e)
        record_path = None

    # 4. 可选推送（飞书）
    if payload.get("notify"):
        for note in notifications:
            full_text = f"{note['title']}\n\n{note['body']}"
            _send_text_notification(full_text)

    return {
        "status": "ok",
        "date": run_date,
        "notifications_sent": len(notifications),
        "notifications": notifications,
        "record_path": str(record_path) if record_path else None,
    }


# ── Stub / TODO for future S218 components ──────────────────────────────

def intraday_alert(payload: dict[str, Any]) -> dict[str, Any]:
    """TODO: 盘中异动预警（量比突增/封板异动）。"""
    return {"status": "skipped", "reason": "TODO: S218 P2 intraday_alert stub"}


def weekly_review(payload: dict[str, Any]) -> dict[str, Any]:
    """TODO: 周度回顾（信号准确率 + 收益归因）。"""
    return {"status": "skipped", "reason": "TODO: S218 P2 weekly_review stub"}


def falsified_retest(payload: dict[str, Any]) -> dict[str, Any]:
    """TODO: 已证否策略定期复测（防假阴性）。"""
    return {"status": "skipped", "reason": "TODO: S218 P2 falsified_retest stub"}
