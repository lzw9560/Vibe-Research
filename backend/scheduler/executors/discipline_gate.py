# -*- coding: utf-8 -*-
"""S231 打板纪律门禁 cron executor——09:15 工作日盘前触发 + 飞书通知。

风控/纪律工具非 edge 基建。cap=0 时每日推"市场天气+不交易提醒"（纪律提醒非交易信号）。
"""
import json
import logging
from pathlib import Path
from typing import Any

from scheduler.cron_fire_audit import fire_receipt  # 复用现有 cron fire 审计
from scheduler.executors.signals import _send_text_notification
from tools.discipline_gate import evaluate_discipline_gate, render_discipline_report
from vr_paths import resolve_data_dir, prev_trading_date_str

_logger = logging.getLogger("vibe-research")

_DISCIPLINE_DIR = Path(resolve_data_dir()) / "discipline_gate"


@fire_receipt("discipline_gate_morning")
def discipline_gate_morning(payload: dict[str, Any]) -> dict[str, Any]:
    """S231 打板纪律门禁——09:15 工作日盘前触发。

    流程：
    1. evaluate_discipline_gate(date)——cap=0 terminal BLOCK 或 C1-C7 评估
    2. render_discipline_report——人话报告
    3. 持久化 {date}_verdict.json
    4. 飞书通知（cap=0 推纪律提醒 + 时机变化推 + 节前推禁入）

    Returns:
        {"status": "ok", "date": str, "verdict": dict}
    """
    target_date = payload.get("run_date") or prev_trading_date_str()
    _logger.info("[S231] discipline_gate_morning start: date=%s", target_date)

    verdict = evaluate_discipline_gate(target_date)
    report_text = render_discipline_report(verdict)

    # 持久化
    try:
        _DISCIPLINE_DIR.mkdir(parents=True, exist_ok=True)
        record_path = _DISCIPLINE_DIR / f"{target_date}_verdict.json"
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(verdict, f, ensure_ascii=False, indent=2, default=str)
    except OSError as e:  # noqa: BLE001
        _logger.warning("[S231] discipline_gate 持久化失败: %s", e)
        record_path = None

    # 飞书通知（cap=0 也推纪律提醒非跳过——反转 cap=0 guard pattern）
    if payload.get("notify", True):  # 默认推
        try:
            _send_text_notification(report_text)
            _logger.info("[S231] discipline_gate 飞书通知已发送: status=%s", verdict.get("status"))
        except Exception as e:  # noqa: BLE001
            _logger.warning("[S231] discipline_gate 飞书通知失败: %s", e)

    return {
        "status": "ok",
        "date": target_date,
        "gate_status": verdict.get("status"),
        "merged_light": verdict.get("merged_light"),
        "verdict": verdict,
        "record_path": str(record_path) if record_path else None,
    }
