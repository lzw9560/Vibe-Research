# -*- coding: utf-8 -*-
"""S218: 信号报告路由——/api/signals/*。

GET /api/signals/daily ——当日 consecutive_relay 信号（结构化 dict）
GET /api/signals/daily-report ——人话版每日信号报告
GET /api/signals/status ——regime 新鲜度 + arm 状态
POST /api/signals/manual-trade ——记录手动真实交易（S218 P0 闭环反馈）
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from engine.trade_journal import TradeJournal
from tools.gap_regime_stratified import compute_regime_labels
from tools.signal_report import get_consecutive_relay_signals, render_daily_report
from vr_paths import resolve_data_dir

router = APIRouter(prefix="/signals", tags=["signals"])

# ── manual trade storage (.vibe-research/signal_reports/manual_trades.jsonl) ──
_MANUAL_TRADES_FILE = Path(resolve_data_dir()) / "signal_reports" / "manual_trades.jsonl"


class ManualTradeInput(BaseModel):
    """手动交易录入请求体。"""
    code: str = Field(..., description="股票代码 6 位")
    entry_price: float = Field(..., gt=0, description="实际买入价")
    entry_time: str = Field(..., description="买入时间 ISO")
    exit_price: float | None = Field(None, ge=0, description="实际卖出价（未平仓传 null）")
    exit_time: str | None = Field(None, description="卖出时间 ISO（未平仓传 null）")
    followed_reference: bool = Field(default=False, description="是否跟随参考信号")
    reference_signal_id: str | None = Field(None, description="关联参考信号 ID（followed_reference=True 时必填）")
    notes: str = Field(default="", description="用户备注")


def _load_manual_trades() -> list[dict]:
    """读所有已录手动交易记录。"""
    if not _MANUAL_TRADES_FILE.exists():
        return []
    trades = []
    with open(_MANUAL_TRADES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return trades


def _save_manual_trade(trade: dict) -> None:
    """追加写一条手动交易记录到 jsonl。"""
    _MANUAL_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_MANUAL_TRADES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(trade, ensure_ascii=False, sort_keys=True) + "\n")


def _get_reference_price_from_signal(signal_id: str) -> tuple[float | None, str, str | None]:
    """从 trade_journal 取参考信号的参考价 + arm。

    返回 (参考价, 来源说明, arm)。
    arm 用于 arm-specific reference_pnl 计算（仅 consecutive_relay 有 chrono edge）。
    arm 取 trade_journal.arm 列（权威源，不靠 parse signal_id——arm 名含下划线如 consecutive_relay）。
    """
    from strategies.journal_recorder import JournalRecorder
    try:
        recorder = JournalRecorder()
        # 从 trade_journal 读 fills_json 找参考信号对应记录
        tj = TradeJournal()
        # signal_id 格式如 "consecutive_relay_2026-09-18_000001"
        conn = tj._conn()
        try:
            row = conn.execute(
                "SELECT entry_price, arm FROM trade_journal WHERE signal_id=?",
                (signal_id,),
            ).fetchone()
            if row and row["entry_price"]:
                arm = row["arm"] if row["arm"] else None
                return float(row["entry_price"]), "trade_journal", arm
        finally:
            conn.close()
    except Exception:
        pass
    return None, "not_found", None


def _compute_actual_pnl(trade: dict) -> dict:
    """计算实际 P&L（百分比和绝对值）。

    未平仓时返回 None。
    """
    entry = trade.get("entry_price")
    exit_price = trade.get("exit_price")
    if entry is None or entry <= 0:
        return {"pnl_pct": None, "pnl_cny": None, "status": "invalid_entry"}
    if exit_price is None or exit_price <= 0:
        return {"pnl_pct": None, "pnl_cny": None, "status": "open"}
    pnl_pct = (exit_price - entry) / entry * 100.0
    # 假设 100 股，实际股数可从 notes 或后续扩展
    shares = 100
    pnl_cny = (exit_price - entry) * shares
    return {"pnl_pct": round(pnl_pct, 4), "pnl_cny": round(pnl_cny, 2), "status": "closed"}


def _compute_reference_implied_pnl(trade: dict) -> dict:
    """计算参考信号隐含 P&L（arm-specific——F3 修）。

    仅 consecutive_relay arm 有 chrono forward-OOS edge（test mean +1.04%，S217）。
    其他 arm（floor/breakout/trend_swing/等）无 validated chrono edge，
    诚实返 None（不套 consecutive_relay 的 edge 当 universal——floor/breakout 没这 edge）。
    """
    ref_price = trade.get("reference_price")
    if ref_price is None or ref_price <= 0:
        return {"pnl_pct": None, "source": "no_reference"}
    arm = trade.get("reference_arm")
    if arm != "consecutive_relay":
        # 非 consecutive_relay arm 无 chrono edge——诚实不套 +1.04%
        return {"pnl_pct": None, "source": "no_chrono_edge_for_arm"}
    # consecutive_relay chrono edge test mean = +1.04% (S217 forward-OOS)
    expected_return_pct = 1.04
    implied_exit = ref_price * (1 + expected_return_pct / 100.0)
    pnl_pct = (implied_exit - ref_price) / ref_price * 100.0
    return {
        "pnl_pct": round(pnl_pct, 4),
        "expected_return_pct": expected_return_pct,
        "source": "chrono_test_mean_1.04pct",
        "arm": arm,
    }


def _compute_pnl_diff(actual: dict, reference: dict) -> dict:
    """实际 vs 参考 P&L 差异（one-sided leak——F4 修）。

    返回 {diff_pct, delivery_leak, leak_reason}。
    delivery_leak: actual 远低于 reference（diff < -50%）时 True——edge 没交付 = leak。
    over-performance（actual >> reference，diff > 0）不标 leak（超预期是好事，非 leak）。
    """
    actual_pnl = actual.get("pnl_pct")
    ref_pnl = reference.get("pnl_pct")
    if actual_pnl is None or ref_pnl is None:
        return {"diff_pct": None, "delivery_leak": False, "leak_reason": "missing_data"}

    diff = actual_pnl - ref_pnl
    # one-sided: 仅 actual 远低于 reference（edge 没交付）才 leak
    delivery_leak = diff < -50.0
    reason = ""
    if delivery_leak:
        reason = f"实际{actual_pnl:.1f}% 低于参考{ref_pnl:.1f}% 达 {abs(diff):.1f}% > 50%"

    return {
        "diff_pct": round(diff, 4),
        "delivery_leak": delivery_leak,
        "leak_reason": reason,
    }


@router.get("/daily")
def _signals_daily() -> dict[str, Any]:
    """返回当日 consecutive_relay 信号报告（结构化 dict）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_consecutive_relay_signals(today)


@router.get("/daily-report")
def _signals_daily_report() -> dict[str, str]:
    """返回人话版每日信号报告（Markdown 文本）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    signals = get_consecutive_relay_signals(today)
    return {"report": render_daily_report(signals)}


@router.get("/status")
def _signals_status() -> dict[str, Any]:
    """返回 regime 新鲜度 + 各 arm 状态。"""
    today = datetime.now().strftime("%Y-%m-%d")
    regime_map = compute_regime_labels()
    regime = regime_map.get(today)

    # regime cache freshness
    from tools.signal_report import _regime_freshness
    freshness = _regime_freshness()

    # arm status
    tj = TradeJournal()
    arms = ["consecutive_relay", "breakout", "trend_swing", "floor"]
    arm_statuses = {}
    for arm in arms:
        status = tj.query_arm_status(arm)
        if status is None:
            arm_statuses[arm] = {"is_active": True, "weight_override": None}
        else:
            arm_statuses[arm] = {
                "is_active": status["is_active"],
                "weight_override": status["weight_override"],
                "kill_reason": status.get("kill_reason"),
            }

    return {
        "regime": {
            "current": regime,
            "freshness": freshness,
        },
        "arms": arm_statuses,
    }


@router.post("/manual-trade")
def _post_manual_trade(body: ManualTradeInput) -> dict[str, Any]:
    """S218 P0: 记录手动真实交易，并计算实际 vs 参考 P&L 差异。

    - 写入 .vibe-research/signal_reports/manual_trades.jsonl
    - 若 followed_reference=True 且关联了 signal_id，
      自动计算实际 P&L vs 参考 P&L（arm-specific：仅 consecutive_relay 套 chrono edge +1.04%，
      其他 arm 无 chrono edge 返 None——诚实不套 universal edge）
    - delivery_leak one-sided：仅 actual 远低于 reference（edge 没交付）才 leak
    - 返回 trade_id + actual_pnl + reference_pnl + diff + delivery_leak
    """
    trade_id = f"manual_{uuid.uuid4().hex[:16]}"
    now = datetime.now().isoformat()

    # 尝试取参考价 + arm（arm 用于 arm-specific reference_pnl）
    ref_price = None
    ref_source = "none"
    ref_arm = None
    if body.followed_reference and body.reference_signal_id:
        ref_price, ref_source, ref_arm = _get_reference_price_from_signal(body.reference_signal_id)

    trade_record = {
        "trade_id": trade_id,
        "code": body.code,
        "entry_price": body.entry_price,
        "entry_time": body.entry_time,
        "exit_price": body.exit_price,
        "exit_time": body.exit_time,
        "followed_reference": body.followed_reference,
        "reference_signal_id": body.reference_signal_id,
        "reference_price": ref_price,
        "reference_price_source": ref_source,
        "reference_arm": ref_arm,
        "notes": body.notes,
        "recorded_at": now,
    }

    # 计算实际 P&L
    actual_pnl = _compute_actual_pnl(trade_record)
    trade_record["actual_pnl"] = actual_pnl

    # 计算参考隐含 P&L
    reference_pnl = _compute_reference_implied_pnl(trade_record)
    trade_record["reference_pnl"] = reference_pnl

    # 计算差异
    diff = _compute_pnl_diff(actual_pnl, reference_pnl)
    trade_record["pnl_diff"] = diff

    # 持久化
    _save_manual_trade(trade_record)

    return {
        "trade_id": trade_id,
        "code": body.code,
        "actual_pnl": actual_pnl,
        "reference_pnl": reference_pnl,
        "pnl_diff": diff,
        "delivery_leak": diff["delivery_leak"],
        "recorded_at": now,
    }


@router.get("/manual-trades")
def _get_manual_trades(limit: int = 50) -> dict[str, Any]:
    """S218 P0: 查询已录手动交易（按时间倒序）。"""
    trades = _load_manual_trades()
    # 按时间倒序，限制条数
    trades.reverse()
    trades = trades[:limit]
    return {
        "trades": trades,
        "count": len(trades),
    }


@router.get("/weekly-review")
def _get_weekly_review(date: str | None = None) -> dict[str, Any]:
    """S221: 读 weekly_review.json 全文（actual P&L + cap_down 提案 + decay_stats）。

    前端 WeeklyReviewPanel 之前从 manual-trades 推算 cap-down（无端点），
    现直读后端真值（weekly_review executor 生成 {date}_weekly_review.json）。
    无 date 返最近一次。无文件诚实标 not_found/no_reports（不臆造）。
    """
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    _dir = Path(resolve_data_dir()) / "signal_reports"
    if date:
        path = _dir / f"{date}_weekly_review.json"
        if not path.exists():
            return {"status": "not_found", "date": date}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if not _dir.exists():
        return {"status": "no_reports"}
    files = sorted(_dir.glob("*_weekly_review.json"), reverse=True)
    if not files:
        return {"status": "no_reports"}
    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"status": "ok", **data, "file": files[0].name}


# ── helper: weekly_review 用实际 P&L ──

def _actual_pnl_for_weekly_review() -> dict[str, Any]:
    """供 weekly_review 调用：取最近实际 P&L 统计。

    返回 {"mean_pnl_pct": float, "n_closed": int, "latest_leak": bool}。
    无记录时返 None 字段。
    """
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
