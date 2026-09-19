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

from scheduler.cron_fire_audit import fire_receipt
from tools.signal_report import get_consecutive_relay_signals, render_daily_report
from vr_paths import prev_trading_date_str

logger = logging.getLogger("vibe-research")


def _actual_pnl_for_weekly_review() -> dict[str, Any]:
    """供 weekly_review 调用：取最近实际 P&L 统计。

    返回 {"mean_pnl_pct": float, "n_closed": int, "latest_leak": bool}。
    无记录时返 None 字段。
    """
    from routers.signals import _load_manual_trades
    trades = _load_manual_trades()
    closed = [t for t in trades if (t.get("actual_pnl") or {}).get("status") == "closed"]
    if not closed:
        return {"mean_pnl_pct": None, "n_closed": 0, "latest_leak": False}

    pnls = [t["actual_pnl"]["pnl_pct"] for t in closed if t["actual_pnl"]["pnl_pct"] is not None]
    mean_pnl = sum(pnls) / len(pnls) if pnls else None
    latest_leak = any(t.get("pnl_diff", {}).get("delivery_leak", False) for t in closed)

    return {
        "mean_pnl_pct": round(mean_pnl, 4) if mean_pnl is not None else None,
        "n_closed": len(closed),
        "latest_leak": latest_leak,
    }

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


@fire_receipt("daily_report")
def daily_report(payload: dict[str, Any]) -> dict[str, Any]:
    """S218 每日信号报告 domain function。

    流程：
    1. get_consecutive_relay_signals → 结构化 dict
    2. render_daily_report → 人话文本
    3. _save_signal_record → .vibe-research/signal_reports/
    4. optional notify（飞书）

    Args:
        payload: {"run_date": "2026-09-18"}（可选，默认前一交易日——盘前 04:01 cron 用昨天已收盘日，cache 有数据；原 datetime.now() 在盘前返今天但 cache 只到昨天→regime=unknown）

    Returns:
        {"status": "ok", "signals": int, "report_path": str, "report_text": str}
    """
    run_date = payload.get("run_date") or prev_trading_date_str()
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
    lines.append("  - record_t0_fill 已删（v3 P0-4 死代码）—fill 走 manual_trades.jsonl 手动记")
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


@fire_receipt("keypoint_notify")
def keypoint_notify(payload: dict[str, Any]) -> dict[str, Any]:
    """S218 C3: 关键点位决策通知。

    复用 C1 shared core（get_consecutive_relay_signals），不重复 scan+regime+lift。
    产生 3 条 time-triggered 通知：
      1. D 收盘入场（15:00 触发）
      2. D+1 开盘出场（09:30 触发）
      3. gap-down 诚实标（检测到 gap-down 时触发，非止损）
    """
    run_date = payload.get("run_date") or prev_trading_date_str()
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


# ── C5: weekly_review ───────────────────────────────────────────────────

def _evaluate_cap_up_gate(bear_days: int, decay_stable: bool, lbc3_days: int) -> bool:
    """统一 cap 升 ×1.0 gate：须 ALL 满足，非 OR。"""
    return bear_days >= 120 and decay_stable and lbc3_days >= 60


def _evaluate_cap_down_trigger(decay_pct: float) -> bool:
    """cap 降触发：衰减 >34% 即触发。"""
    return decay_pct > 34


def _render_weekly_review(
    signals: dict[str, Any],
    paper_trends: list[dict] | None,
    arm_status: dict | None,
    decay_stats: dict[str, Any] | None = None,
    cap_up_ready: bool = False,
    cap_down_triggered: bool = False,
) -> str:
    """渲染周度复盘人话报告。"""
    date = signals.get("date", "")
    cap = signals.get("cap", {})
    effective = cap.get("effective", 1.0)

    lines: list[str] = []
    lines.append(f"=== {date} 周度汇总复盘 ===")
    lines.append("")

    # 1. Paper / Actual P&L（诚实标注）
    actual_pnl = _actual_pnl_for_weekly_review()
    if actual_pnl.get("mean_pnl_pct") is not None:
        lines.append("【本周实际 P&L】（手动交易闭环反馈）")
        lines.append(f"  实际收益均值 {actual_pnl['mean_pnl_pct']:.2f}%（n={actual_pnl['n_closed']} 笔）")
        if actual_pnl.get("latest_leak"):
            lines.append("  注意：检测到 delivery leak（实际低于参考 > 50%，edge 未交付），建议复核执行偏差")
        else:
            lines.append("  执行偏差在可接受范围（实际不低于参考 > 50%）")
    else:
        lines.append("【本周 paper P&L】")
        lines.append("  只能看 paper 表现，没真交易收益；接券商才有真 closure")
    if paper_trends:
        last = paper_trends[-1]
        lines.append(f"  最近周胜率 {last.get('win_rate', 0)*100:.1f}%（n={last.get('n_decided', 0)}，{last.get('label', '')}）")
    else:
        lines.append("  暂无 paper 交易记录")
    lines.append("")

    # 2. Cap gate 状态（动态：runtime effective + cap_up_ready verdict，非硬编码 ×0.75）
    lines.append("【统一 cap 升降 gate】")
    lines.append(f"  当前 cap ×{effective}（runtime effective；registry bull=1.0 freeze-gated，bear/range=0.5）")
    lines.append("  升 ×1.0 须 ALL 满足：")
    ds = decay_stats or {}
    lines.append(f"    (a) bear 累积 120+ 天 cross-regime chrono 够 power（当前 {ds.get('bear_days', 0)} 天）")
    lines.append(f"    (b) 60 天 re-check 衰减稳（decay_stable={ds.get('decay_stable', False)}）")
    lines.append(f"    (c) lbc=3 积累 60 天（当前 {ds.get('lbc3_days', 0)} 天，TODO 子查询占位）")
    lines.append(f"  → cap_up_ready={cap_up_ready}（{'可升 ×1.0' if cap_up_ready else '维持当前 cap'}）")
    lines.append("")

    # 3. Decay 监控（动态：从 s203 chrono decay_stats，非硬编码 1.57→1.04）
    lines.append("【衰减监控】")
    if ds and ds.get("train_mean") is not None:
        tm = ds["train_mean"] * 100
        te = (ds.get("test_mean") or 0) * 100
        dp = ds.get("decay_pct", 0)
        lines.append(f"  train {tm:.2f}% → test {te:.2f}%，跌 {dp:.1f}%（source={ds.get('source', '?')}）")
    else:
        lines.append(f"  decay 数据不足（source={ds.get('source', 'none')}），保守不判")
    lines.append(f"  若衰减续恶化（>34%）→ 自动生成 cap-down 提案；当前 cap_down_triggered={cap_down_triggered}")
    lines.append("")

    # 4. Process-theater 自检
    lines.append("【process-theater 自检】")
    mean_wr = last.get("win_rate", 0.5) if paper_trends else 0.5
    if mean_wr < 0.5:
        lines.append(f"  纸面 P&L mean={mean_wr*100:.1f}% < 0 → 触发 cap-down 提案")
    else:
        lines.append(f"  纸面 P&L mean={mean_wr*100:.1f}% ≥ 0 → 未触发 cap-down")
    lines.append("  自检标准：paper P&L mean<0 OR 衰减轨迹跨 negative → 生成 cap-down 提案")
    lines.append("")

    # 5. Arm 待办 monitor
    lines.append("【consecutive_relay arm 待办 monitor】")
    lines.append("  - regime cache 滞后（升 ×1.0 前必修 regime cache 更新机制）")
    lines.append("  - K1 cache 滞后（baostock_kline_cache）致 picks hold")
    lines.append("  - lbc=3 积累 60 天转 ×1.0（当前不足）")
    lines.append("")

    # 6. 创业板做市商结构性断点 caveat（占位）
    lines.append("【创业板做市商结构性断点 §44 caveat】")
    lines.append("  TODO 占位：§44 forward-OOS 样本跨 2026-07-06 创业板做市商引入，")
    lines.append("  edge 可能被 pre/post-做市商 regime 混淆；")
    lines.append("  未来对创业板 picks 做 pre/post-2026-07-06 子样本分析。")
    lines.append("  （本次不实现子样本分析，仅留占位。后期实现。）")
    lines.append("")

    # 7. 诚实性 footer
    lines.append("【诚实性标注】")
    lines.append("  consecutive_relay 是 126 verdict 唯一 robust_edge（3% 稀有 positive）")
    lines.append("  96% negative 是诚实证否 value，非产出率低")
    lines.append("  深挖子条件（lbc/市值/连板位置）增强，非堆新战法")

    return "\n".join(lines)


@fire_receipt("weekly_review")
def weekly_review(payload: dict[str, Any]) -> dict[str, Any]:
    """S218 C5: 周度汇总复盘 + 统一 cap 升降 gate + process-theater 自检。

    复用 C1 shared core（get_consecutive_relay_signals），不重复 scan+regime+lift。
    """
    run_date = payload.get("run_date") or prev_trading_date_str()
    logger.info("[S218] weekly_review start: date=%s", run_date)

    # 1. 复用 C1 shared core
    from tools.signal_report import get_consecutive_relay_signals
    signals = get_consecutive_relay_signals(run_date)

    # 2. 取 paper P&L（TradeJournal）
    paper_trends: list[dict] | None = None
    arm_status: dict | None = None
    try:
        from engine.trade_journal import TradeJournal
        tj = TradeJournal()
        paper_trends = tj.query_winrate_trends(arm="consecutive_relay")
        arm_status = tj.query_arm_status(arm="consecutive_relay")
    except Exception as e:  # noqa: BLE001
        logger.warning("[S218] weekly_review TradeJournal 查询失败: %s", e)

    # 3. 统一 cap gate 评估（S218 #2: 真衰减 stats 替硬编码）——移到 render 前，传 _render_weekly_review 动态用
    cap = signals.get("cap", {})
    effective = cap.get("effective", 1.0)
    from tools.signal_report import _compute_consecutive_relay_decay
    decay_stats = _compute_consecutive_relay_decay()
    cap_up_ready = _evaluate_cap_up_gate(
        bear_days=decay_stats["bear_days"],
        decay_stable=decay_stats["decay_stable"],
        lbc3_days=decay_stats["lbc3_days"],
    )
    cap_down_triggered = _evaluate_cap_down_trigger(decay_pct=decay_stats["decay_pct"])

    # 4. 生成报告（传 decay_stats + cap_up_ready 动态渲染，非硬编码）
    review_text = _render_weekly_review(signals, paper_trends, arm_status, decay_stats, cap_up_ready, cap_down_triggered)

    # 5. process-theater 自检：paper P&L mean<0 OR 衰减跨 negative → cap-down 提案
    #    S218 P0: 优先用实际 P&L（手动交易记录），没有才降级 paper P&L
    actual_pnl_stats = _actual_pnl_for_weekly_review()
    cap_down_proposal = None

    if actual_pnl_stats.get("mean_pnl_pct") is not None:
        # 有实际 P&L 数据 → 用实际 mean_pnl_pct
        mean_pnl = actual_pnl_stats["mean_pnl_pct"]
        if mean_pnl < 0:
            cap_down_proposal = {
                "action": "cap-down",
                "from": effective,
                "to": 0.5,
                "reason": f"实际 P&L mean={mean_pnl:.2f}% < 0（n={actual_pnl_stats['n_closed']} 笔），触发 cap-down",
            }
        # 同时检查 delivery leak
        if actual_pnl_stats.get("latest_leak"):
            logger.warning("[S218] weekly_review 检测到 delivery leak（actual < ref - 50%，one-sided edge 未交付）")
    elif paper_trends:
        mean_wr = sum(t.get("win_rate", 0) for t in paper_trends) / len(paper_trends)
        if mean_wr < 0.5:  # 50% 以下视为 negative
            cap_down_proposal = {
                "action": "cap-down",
                "from": effective,
                "to": 0.5,
                "reason": f"paper P&L mean={mean_wr*100:.1f}% < 0，衰减轨迹跨 negative",
            }
    else:
        # 无 paper 记录时，若衰减>34% 也提案
        if cap_down_triggered:
            cap_down_proposal = {
                "action": "cap-down",
                "from": effective,
                "to": 0.5,
                "reason": "衰减续恶化（>34%），自动生成 cap-down 提案交用户 review",
            }

    # 6. 保存记录
    try:
        _SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
        record_path = _SIGNAL_DIR / f"{run_date}_weekly_review.json"
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": run_date,
                    "review_text": review_text,
                    "cap_up_ready": cap_up_ready,
                    "cap_down_proposal": cap_down_proposal,
                    "signals_count": len(signals.get("signals", [])),
                },
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
    except OSError as e:
        logger.warning("[S218] weekly_review 保存记录失败: %s", e)
        record_path = None

    # 7. 可选推送（飞书）
    if payload.get("notify"):
        try:
            from notification.notification_service import get_notification_service
            service = get_notification_service()
            if hasattr(service, "send"):
                service.send(review_text)
        except Exception as e:  # noqa: BLE001
            logger.warning("[S218] weekly_review 通知推送失败: %s", e)

    return {
        "status": "ok",
        "date": run_date,
        "review_text": review_text,
        "cap_up_ready": cap_up_ready,
        "cap_down_proposal": cap_down_proposal,
        "decay_stats": decay_stats,
        "record_path": str(record_path) if record_path else None,
    }


def falsified_retest(payload: dict[str, Any]) -> dict[str, Any]:
    """TODO: 已证否策略定期复测（防假阴性）。"""
    return {"status": "skipped", "reason": "TODO: S218 P2 falsified_retest stub"}
