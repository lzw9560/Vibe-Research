# -*- coding: utf-8 -*-
"""S233 打板工作流闭环——S232 watchlist + 二次确认 + -3% stop exit 规则。

打板工作流（基于 -3% stop OOS 4 段全正 +1.38% net/笔 突破）：
  Stage 1: T 日 15:10 watchlist 生成（turn>20%+vr5>2 未涨停，S232 已有）
  Stage 2: T+1 09:25 二次确认（gap 低开-5%~-2%）
  Stage 3: T+1 09:30 open 买（用户手动，系统不自动下单）
  Stage 4: T+2 盘中 -3% stop（low 触及止损卖）/ 否则 T+2 close 卖
  Stage 5: T+2 收盘 回填 t1_zt + 归因

诚实：-3% stop OOS 4 段全正但 in-sample 分段非真正 walk-forward，需实盘验证。
定位：打板工作流操作建议工具，非自动交易系统。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from tools.t1_forecast import (
    _forecast_dir,
    _generate_from_preloaded,
    _load_kline_bars,
    _zt_db_path,
    generate_t1_watchlist,
)

_logger = logging.getLogger("vibe-research")

# 工作流参数（-3% stop OOS 验证，t1_exit_optimization 最优组合）
GAP_LO = -5.0  # 二次确认低开下界
GAP_HI = -2.0  # 二次确认低开上界
STOP_PCT = -0.03  # T+2 盘中止损 -3%（OOS 最优）

# ⚠️ 诚实修正（2026-10-05，审视 workflow 戳破）：
# -3% stop +1.75% EV 是 fill 假设虚构（56.4% T+2 跳空穿 stop，真实成交=t2_open 更差）。
# realistic fill 后 EV ≈ baseline +0.70%（mechanical mean-reversion 非 alpha）。
# 第 3 次 V1 假 edge 覆辙（consecutive_relay +1.04% / gap open_ev +0.70% / -3% stop +1.75%）。
# Stage 4 exit 无 edge——baseline T+2 close 卖是 mean-reversion 非 alpha。
# 工作流定位：观察工具（Stage 1-3 watchlist+二次确认+open 买）+ Stage 4 exit 无 edge + Stage 5 归因。
# 不进 sizing 承重墙，不自动下单，用户手动操作 + 纪律止损（但纪律不创 EV）。
EXIT_EDGE_STATUS = "fill-fiction-fake-edge"
EXIT_HONEST_CAVEAT = (
    "-3% stop +1.75% 是 fill 假设虚构（56.4% T+2 跳空穿 stop 真实成交=t2_open 更差），"
    "realistic fill 后 EV ≈ baseline +0.70%（mechanical mean-reversion 非 alpha）。"
    "Stage 4 exit 无 edge——工作流定位观察工具，exit 规则不赚钱。"
    "第 3 次 V1 假 edge 覆辙，新根因'成交假设虚构'已加入 §44 v3。"
)


def limitup_workflow(target_date: str) -> dict[str, Any]:
    """打板工作流操作建议（T 日 watchlist + T+1 二次确认 + exit 规则）。

    Args:
        target_date: T 日 YYYY-MM-DD

    Returns:
        workflow dict{date, t1_date, workflow_stages, watchlist_count,
        confirmed_count, confirmed_stocks, exit_rules, operation_steps}
    """
    # Stage 1: 读 T 日 watchlist（优先持久化，否则实时生成）
    wl_path = _forecast_dir() / f"{target_date}_watchlist.json"
    if wl_path.exists():
        try:
            with open(wl_path, "r", encoding="utf-8") as f:
                watchlist = json.load(f)
        except (json.JSONDecodeError, OSError):
            watchlist = generate_t1_watchlist(target_date)
    else:
        watchlist = generate_t1_watchlist(target_date)

    # 查 T+1 date（next trading day after target_date，用 zt_history 日历）
    t1_date: str | None = None
    zt_db = _zt_db_path()
    if zt_db.exists():
        conn = sqlite3.connect(str(zt_db))
        try:
            cal = [r[0] for r in conn.execute("SELECT DISTINCT date FROM zt_history ORDER BY date").fetchall()]
            for i, d in enumerate(cal):
                if d == target_date and i + 1 < len(cal):
                    t1_date = cal[i + 1]
                    break
        finally:
            conn.close()

    # Stage 2: T+1 二次确认（如果 T+1 bar 已有，算 gap 标记触发）
    all_bars = _load_kline_bars() if t1_date else {}
    confirmed_stocks: list[dict[str, Any]] = []
    for s in watchlist.get("stocks", []):
        code = s["code"]
        t_close = s.get("close")
        if t_close is None or t1_date is None:
            s["gap"] = None
            s["confirmed"] = False
            continue
        bars = all_bars.get(code, [])
        t1_bar = next((b for b in bars if b.get("date") == t1_date), None)
        if t1_bar is None:
            s["gap"] = None
            s["confirmed"] = False
            continue
        t1_open = t1_bar.get("open")
        if t1_open is None or t1_open == 0:
            s["gap"] = None
            s["confirmed"] = False
            continue
        gap = (t1_open - t_close) / t_close * 100
        s["gap"] = round(gap, 2)
        s["confirmed"] = GAP_LO <= gap < GAP_HI
        if s["confirmed"]:
            # Stage 3/4: exit 规则
            s["entry_price"] = t1_open
            s["stop_price"] = round(t1_open * (1 + STOP_PCT), 2)
            s["exit_rule"] = f"T+1 open {t1_open} 买，T+2 盘中 low<={s['stop_price']} 止损卖 / 否则 T+2 close 卖"
            confirmed_stocks.append(s)

    watchlist_count = watchlist.get("count", len(watchlist.get("stocks", [])))
    return {
        "date": target_date,
        "t1_date": t1_date,
        "signal": watchlist.get("signal"),
        "signal_lift": watchlist.get("signal_lift"),
        "edge_status": watchlist.get("edge_status"),
        "honest_caveat": watchlist.get("honest_caveat"),
        "workflow_stages": [
            {
                "stage": 1,
                "name": "T 日 watchlist 生成",
                "time": "15:10",
                "desc": f"{target_date} turn>20%+vr5>2 未涨停股 {watchlist_count} 只",
                "status": "done" if watchlist_count > 0 else "pending",
            },
            {
                "stage": 2,
                "name": "T+1 二次确认",
                "time": "09:25",
                "desc": f"gap 低开 {GAP_LO}~{GAP_HI}%，{len(confirmed_stocks)} 只触发",
                "status": "done" if t1_date and len(confirmed_stocks) > 0 else ("pending" if t1_date else "waiting_t1"),
            },
            {
                "stage": 3,
                "name": "T+1 open 买",
                "time": "09:30",
                "desc": "二次确认触发股，T+1 open 买入（用户手动）",
                "status": "manual",
            },
            {
                "stage": 4,
                "name": "T+2 exit",
                "time": "盘中",
                "desc": f"-{abs(STOP_PCT) * 100:.0f}% stop（low 触及止损卖）/ 否则 T+2 close 卖",
                "status": "pending",
            },
            {
                "stage": 5,
                "name": "T+2 回填归因",
                "time": "收盘",
                "desc": "记录收益 + 回填 t1_zt + 累积验证",
                "status": "pending",
            },
        ],
        "watchlist_count": watchlist_count,
        "confirmed_count": len(confirmed_stocks),
        "confirmed_stocks": confirmed_stocks,
        "exit_rules": {
            "gap_range": f"{GAP_LO}~{GAP_HI}%",
            "stop": f"{STOP_PCT * 100:+.0f}%",
            "entry": "T+1 open（gap 已知后买）",
            "exit": f"T+2 盘中 {STOP_PCT * 100:+.0f}% stop / T+2 close",
            "oos_ev": "+1.38% net/笔（in-sample 180 天 636 只 OOS 4 段全正，但审视 workflow 戳破 fill 虚构，realistic ≈ baseline +0.70% mean-reversion 非 alpha）",
            "edge_status": EXIT_EDGE_STATUS,
            "exit_honest_caveat": EXIT_HONEST_CAVEAT,
        },
        "operation_steps": [
            f"① T 日 {target_date} 15:10 看 watchlist（{watchlist_count} 只信号股）",
            f"② T+1 {t1_date or '?'} 09:25 看竞价/开盘 gap，筛低开 {GAP_LO}~{GAP_HI}% 的股",
            "③ T+1 09:30 T+1 open 买入（用户手动，系统不自动下单）",
            f"④ T+2 盘中盯 {STOP_PCT * 100:+.0f}% stop（low 触及止损卖）/ 否则 T+2 close 卖",
            "⑤ T+2 收盘记录收益 + 回填 t1_zt",
        ],
    }


def render_workflow_report(workflow: dict[str, Any]) -> str:
    """人话报告——打板工作流操作建议。"""
    lines: list[str] = []
    lines.append(f"📋 打板工作流（{workflow['date']}）")
    if workflow.get("t1_date"):
        lines.append(f"T+1 = {workflow['t1_date']}")
    lines.append("")
    lines.append("Stage 流程：")
    for st in workflow["workflow_stages"]:
        mark = {"done": "✅", "pending": "⏳", "manual": "👤", "waiting_t1": "⏳"}.get(st["status"], "⏳")
        lines.append(f"  {mark} Stage {st['stage']} [{st['time']}] {st['name']}: {st['desc']}")
    lines.append("")
    lines.append(f"二次确认触发：{workflow['confirmed_count']} 只（gap {workflow['exit_rules']['gap_range']}）")
    if workflow["confirmed_stocks"]:
        lines.append("触发股 + exit 规则：")
        for s in workflow["confirmed_stocks"][:10]:
            lines.append(f"  {s['code']} gap={s['gap']}% entry={s['entry_price']} stop={s['stop_price']}")
    lines.append("")
    lines.append(f"exit 规则：{workflow['exit_rules']['entry']} / {workflow['exit_rules']['exit']}")
    lines.append(f"OOS EV：{workflow['exit_rules']['oos_ev']}")
    lines.append(f"⚠️ exit edge_status: {EXIT_EDGE_STATUS}")
    lines.append(f"⚠️ {EXIT_HONEST_CAVEAT}")
    lines.append("")
    if workflow.get("honest_caveat"):
        lines.append(f"⚠️ {workflow['honest_caveat']}")
    lines.append("⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。")
    return "\n".join(lines)
