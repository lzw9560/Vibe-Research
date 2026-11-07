# -*- coding: utf-8 -*-
"""S231 打板纪律门禁工作流闭环——风控/纪律工具非 edge 基建。

叠在 cap=0 hardstop 之上，只读现有数据源（sti_timeline/sentiment_weather/execution_model/vr_paths），
不创造 alpha、不输出买卖标的。措辞"纪律门禁"非"打板时机"。

7 条件门禁（C1-C7）OR-BLOCK：任一红线 fail → BLOCK；全绿 → PASS；其余 → CAUTION。
terminal master switch: cap=0（consecutive_relay falsified）→ 短路 BLOCK。

实现状态（2026-09-30 对抗审查降标，详见 specs/S231-discipline-gate-workflow/spec.md §5）：
- Stage 1 门禁判断 ✅ DONE——唯一端到端通电环节（evaluate_discipline_gate + cron 09:15 + 飞书 + 持久化 + router + 前端）。
- C1-C7 分支（见下 evaluate_discipline_gate :120-218）⚠️ 永久 dead code——cap=0 terminal 短路在 :108-118 先返回，C1-C7 永不执行。保留作"cap>0 解冻备用骨架"，但解冻结构性不可能（cap=0 三重锁死 + 5 批穷尽 300+ 候选 0 alpha）。
- Stage 2 仓位 discipline_mult 第5层 ❌ 未建——违 risk_rules.py:565 "⛔ 不碰 final_size sizing"，DEFERRED。
- Stage 3 入场 journal.add_trade ⚠️ 设计本就不自动（spec"用户手动不自动下单"），非断线。
- Stage 4 退出 keypoint_notify ❌ 不读门禁 verdict（读已证否 consecutive_relay），独立 cron。
- Stage 5 归因回灌 ❌ 闭环断裂——loss_breaker 产出 cooldown（risk_rules._load_cooldown:517）但本模块不读它。回灌本身不违冻结（spec §4 risk_rules.py 列"复用只读"），延后因 cap=0 下 moot + 解冻不可能。
- verdict 产出后无下游消费者——verdict 产出即终点。这是"为什么只有门禁"的物理根因。

跑法：cd backend && .venv/bin/python -c "from tools.discipline_gate import evaluate_discipline_gate; print(evaluate_discipline_gate('2026-09-29'))"
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_logger = logging.getLogger("vibe-research")


def _load_sti_row(db_path: Path, target_date: str | None = None) -> dict[str, Any] | None:
    """读 sti_timeline 最新行（或指定 date 行）。返 dimension_* 字段。"""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        if target_date:
            row = conn.execute(
                "SELECT * FROM sti_timeline WHERE date <= ? AND score IS NOT NULL ORDER BY date DESC LIMIT 1",
                (target_date,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM sti_timeline WHERE score IS NOT NULL ORDER BY date DESC LIMIT 1"
            ).fetchone()
        conn.close()
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}
    except Exception as e:  # noqa: BLE001
        _logger.warning("[discipline_gate] sti_timeline 读取失败: %s", e)
        return None


def _sti_consecutive_above(db_path: Path, threshold: float, n_days: int) -> tuple[bool, list[float]]:
    """C2: STI 连续 n_days 个交易日 score > threshold。返 (is_pass, scores)。"""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT score FROM sti_timeline WHERE score IS NOT NULL ORDER BY date DESC LIMIT ?",
            (n_days,),
        ).fetchall()
        conn.close()
        scores = [float(r["score"]) for r in rows if r["score"] is not None]
        if len(scores) < n_days:
            return False, scores
        is_pass = all(s > threshold for s in scores)
        return is_pass, scores
    except Exception as e:  # noqa: BLE001
        _logger.warning("[discipline_gate] STI 连续读取失败: %s", e)
        return False, []


def _is_pre_holiday_lock(target_date: str) -> bool:
    """C7: 节前禁入——买入日后 T+1 卖出日，如果中间跨连续≥3 自然日休市（如国庆 10/1-7）→ 锁仓风险。

    买入日 +1 自然日 = T+1 卖出日。如果 T+1 卖出日不在 is_trading_day（节假日），
    且买入日到下一个交易日跨≥3 自然日 → 节前禁入。
    """
    try:
        from vr_paths import is_trading_day  # noqa: PLC0415

        buy_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
        # T+1 卖出日 = 下一交易日
        next_td = buy_dt + timedelta(days=1)
        while not is_trading_day(next_td):
            next_td += timedelta(days=1)
        gap_days = (next_td - buy_dt).days
        return gap_days >= 3  # 跨≥3 自然日 = 节前锁仓（如 09-30 买→10-08 卖 = 8 天）
    except Exception:  # noqa: BLE001
        return False


def evaluate_discipline_gate(target_date: str) -> dict[str, Any]:
    """S231 打板纪律门禁——7 条件 OR-BLOCK + cap=0 terminal。

    Args:
        target_date: YYYY-MM-DD（买入日）

    Returns:
        verdict{status, cap, conditions[], merged_light, reasons[], date}
        status: "BLOCK"（terminal/红线 fail）/ "PASS"（全绿）/ "CAUTION"（非红线 fail）
        merged_light: "red"（BLOCK）/ "green"（PASS）/ "yellow"（CAUTION）
    """
    conditions: list[dict[str, Any]] = []
    reasons: list[str] = []

    # Terminal master switch: cap=0（consecutive_relay falsified）
    try:
        from candidate_funnel.evaluation import lift_for_arm  # noqa: PLC0415

        cap, _cap_note = lift_for_arm("consecutive_relay", regime="bull")
    except Exception as e:  # noqa: BLE001
        _logger.warning("[discipline_gate] lift_for_arm 读取失败: %s", e)
        cap = 0.0  # 保守

    if cap <= 0.0:
        # cap=0 terminal BLOCK（短路，不评估 C1-C7）
        return {
            "date": target_date,
            "status": "BLOCK",
            "cap": cap,
            "terminal": True,
            "conditions": [],
            "merged_light": "red",
            "reasons": [f"cap=0 terminal BLOCK（consecutive_relay falsified ARCHIVED，不评估 C1-C7）"],
        }

    # cap>0 评估 C1-C7（当前 cap=0 永不触发，留未来解冻用）
    # 数据源：sti_timeline DB
    try:
        from config import STI_TIMELINE_DB_PATH  # noqa: PLC0415

        db_path = Path(STI_TIMELINE_DB_PATH)
    except Exception:  # noqa: BLE001
        from vr_paths import resolve_data_dir  # noqa: PLC0415

        db_path = resolve_data_dir() / "sti_timeline.db"

    sti_row = _load_sti_row(db_path, target_date)

    # C1: composite≥75 晴天
    try:
        from routers.sentiment_weather import compute_weather_snapshot  # noqa: PLC0415

        snap = compute_weather_snapshot(target_date)
        composite = float(snap.get("composite_score", 0) or 0)
        weather = snap.get("weather_state", "未知")
    except Exception as e:  # noqa: BLE001
        composite = 0.0
        weather = "未知"
        _logger.warning("[discipline_gate] C1 composite 读取失败: %s", e)
    c1_pass = composite >= 75
    conditions.append(
        {
            "id": "C1",
            "name": "composite≥75 晴天",
            "value": composite,
            "threshold": 75,
            "pass": c1_pass,
            "red_line": True,
        }
    )
    if not c1_pass:
        reasons.append(f"C1 fail: composite={composite} <75（{weather}）")

    # C2: STI 连续 3 天>50
    c2_pass, c2_scores = _sti_consecutive_above(db_path, 50.0, 3)
    conditions.append(
        {"id": "C2", "name": "STI 连续 3 天>50", "value": c2_scores, "threshold": 50, "pass": c2_pass, "red_line": True}
    )
    if not c2_pass:
        reasons.append(f"C2 fail: STI 连续 3 天>50 未达（scores={c2_scores}）")

    # C3-C5 从 sti_row
    if sti_row:
        # C3: promotion_rate>15%
        promo = float(sti_row.get("dimension_promotion_rate", 0) or 0)
        c3_pass = promo > 15
        conditions.append(
            {
                "id": "C3",
                "name": "promotion_rate>15%",
                "value": promo,
                "threshold": 15,
                "pass": c3_pass,
                "red_line": True,
            }
        )
        if not c3_pass:
            reasons.append(f"C3 fail: promotion_rate={promo} <=15%")

        # C4: advance_decline_ratio>1.0
        ad = float(sti_row.get("dimension_advance_decline_ratio", 1.0) or 1.0)
        c4_pass = ad > 1.0
        conditions.append(
            {
                "id": "C4",
                "name": "advance_decline_ratio>1.0（广度>50%）",
                "value": ad,
                "threshold": 1.0,
                "pass": c4_pass,
                "red_line": True,
            }
        )
        if not c4_pass:
            reasons.append(f"C4 fail: ad_ratio={ad} <=1.0（涨<=跌）")

        # C5: 跌停<涨停
        lu = float(sti_row.get("dimension_limit_up_count", 0) or 0)
        ld = float(sti_row.get("dimension_limit_down_count", 0) or 0)
        c5_pass = ld < lu
        conditions.append(
            {
                "id": "C5",
                "name": "跌停<涨停",
                "value": {"limit_up": lu, "limit_down": ld},
                "threshold": "ld<lu",
                "pass": c5_pass,
                "red_line": True,
            }
        )
        if not c5_pass:
            reasons.append(f"C5 fail: 跌停{ld}>=涨停{lu}（高位补跌）")
    else:
        for cid, cname in [("C3", "promotion_rate>15%"), ("C4", "ad_ratio>1.0"), ("C5", "跌停<涨停")]:
            conditions.append(
                {
                    "id": cid,
                    "name": cname,
                    "value": None,
                    "threshold": None,
                    "pass": False,
                    "red_line": True,
                    "missing": True,
                }
            )
            reasons.append(f"{cid} missing: sti_timeline 无数据")

    # C6: kill switch 未触发（通知级 CAUTION 非 BLOCK）
    # 复用 scheduled_tasks._check_pmarket_kill_switch（如果可调）或标 CAUTION
    try:
        from scheduled_tasks import _check_pmarket_kill_switch  # noqa: PLC0415

        kill_triggered, kill_reason = _check_pmarket_kill_switch()
    except Exception:  # noqa: BLE001
        kill_triggered = False
        kill_reason = "kill_switch 接口未确认（标 CAUTION）"
    c6_pass = not kill_triggered
    conditions.append(
        {
            "id": "C6",
            "name": "kill switch 未触发（上证<-3%/创业板<-4%）",
            "value": not kill_triggered,
            "threshold": "未触发",
            "pass": c6_pass,
            "red_line": False,
            "notify_level": True,
        }
    )  # 通知级非阻断
    if not c6_pass:
        reasons.append(f"C6 CAUTION: kill_switch 触发——{kill_reason}")

    # C7: 节前禁入（T+1 锁仓≥3 自然日）
    c7_pass = not _is_pre_holiday_lock(target_date)
    conditions.append(
        {
            "id": "C7",
            "name": "节前禁入（T+1 锁仓<3 自然日）",
            "value": not c7_pass,
            "threshold": "gap<3",
            "pass": c7_pass,
            "red_line": True,
        }
    )
    if not c7_pass:
        reasons.append("C7 fail: 节前禁入（T+1=≥3 自然日锁仓，如 09-30 买→10-08 卖=8 天）")

    # OR-BLOCK 逻辑
    red_line_fails = [c for c in conditions if not c.get("pass", False) and c.get("red_line", False)]
    non_red_fails = [c for c in conditions if not c.get("pass", False) and not c.get("red_line", False)]

    if red_line_fails:
        status = "BLOCK"
        merged_light = "red"
    elif non_red_fails:
        status = "CAUTION"
        merged_light = "yellow"
    else:
        status = "PASS"
        merged_light = "green"

    return {
        "date": target_date,
        "status": status,
        "cap": cap,
        "terminal": False,
        "conditions": conditions,
        "merged_light": merged_light,
        "reasons": reasons,
    }


def render_discipline_report(verdict: dict[str, Any]) -> str:
    """人话报告：市场天气 + 7 条件 + 不交易理由。"""
    lines = []
    lines.append(f"📊 打板纪律门禁报告 | {verdict['date']}")
    lines.append("")
    status_emoji = {"BLOCK": "🔴", "CAUTION": "🟡", "PASS": "🟢"}
    lines.append(
        f"{status_emoji.get(verdict['status'], '⚪')} 当前判定：{verdict['status']}（cap={verdict.get('cap', '?')}）"
    )

    if verdict.get("terminal"):
        lines.append("")
        lines.append("⚠️ Terminal BLOCK: cap=0（consecutive_relay falsified ARCHIVED）")
        lines.append("   不评估 C1-C7——每日产出'市场天气+不交易提醒'")
        lines.append("")
        lines.append(" ".join(verdict.get("reasons", [])))
        lines.append("")
        lines.append("⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。")
        return "\n".join(lines)

    lines.append("")
    lines.append("【7 条件门禁】")
    for c in verdict.get("conditions", []):
        pass_emoji = "✅" if c.get("pass") else ("❌" if c.get("red_line") else "⚠️")
        val = c.get("value")
        if isinstance(val, dict):
            val_str = ", ".join(f"{k}={v}" for k, v in val.items())
        elif isinstance(val, list):
            val_str = f"scores={val}"
        else:
            val_str = str(val)
        missing = " (missing)" if c.get("missing") else ""
        lines.append(f"  {pass_emoji} {c['id']} {c['name']}: {val_str} (阈值 {c.get('threshold')}){missing}")

    if verdict.get("reasons"):
        lines.append("")
        lines.append("【不交易理由】")
        for r in verdict["reasons"]:
            lines.append(f"  • {r}")

    lines.append("")
    lines.append("⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。")
    return "\n".join(lines)


if __name__ == "__main__":
    v = evaluate_discipline_gate("2026-09-29")
    print(render_discipline_report(v))
