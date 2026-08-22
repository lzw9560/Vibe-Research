"""
Win rate router.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from win_rate_tracker import WinRateTracker, WinRateRecord, generate_strategy_adjustments, get_trends, get_sector_stats, get_strategy_stats

router = APIRouter(tags=["winrate"])
_logger = logging.getLogger(__name__)
_tracker = WinRateTracker()


@router.get("/api/winrate/stats")
async def winrate_stats(window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取胜率统计。"""
    try:
        stats = _tracker.get_stats(window_size=window_size)
        return {
            "data": {
                "window_size": stats.window_size,
                "total_trades": stats.total_trades,
                "win_count": stats.win_count,
                "win_rate": stats.win_rate,
                "avg_return": stats.avg_return,
                "max_drawdown": stats.max_drawdown,
                "sharpe_ratio": stats.sharpe_ratio,
                "trend": stats.trend,
                "sector_breakdown": stats.sector_breakdown,
                "strategy_breakdown": stats.strategy_breakdown,
                "score_breakdown": stats.score_breakdown,
            }
        }
    except Exception as e:  # noqa: BLE001
        _logger.exception("胜率统计异常")
        raise HTTPException(502, "胜率统计异常，请稍后重试") from e


@router.get("/api/winrate/adjustments")
async def winrate_adjustments(window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取策略调整建议。"""
    try:
        stats = _tracker.get_stats(window_size=window_size)
        adjustments = generate_strategy_adjustments(stats)
        return {"data": adjustments}
    except Exception as e:  # noqa: BLE001
        _logger.exception("策略调整建议异常")
        raise HTTPException(502, "策略调整建议异常，请稍后重试") from e


@router.get("/api/winrate/trends")
async def winrate_trends(window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取胜率趋势图数据。"""
    try:
        trends = get_trends(window_size=window_size)
        return {"data": trends}
    except Exception as e:  # noqa: BLE001
        _logger.exception("胜率趋势异常")
        raise HTTPException(502, "胜率趋势异常，请稍后重试") from e


@router.get("/api/winrate/sector/{sector}")
async def winrate_sector(sector: str, window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取板块胜率拆分。"""
    try:
        stats = get_sector_stats(sector=sector, window_size=window_size)
        return {"data": stats}
    except ValueError:
        raise HTTPException(404, {"detail": "Sector not found"})
    except Exception as e:  # noqa: BLE001
        _logger.exception("板块胜率异常")
        raise HTTPException(502, "板块胜率异常，请稍后重试") from e


@router.get("/api/winrate/strategy/{strategy}")
async def winrate_strategy(strategy: str, window_size: int = Query(20, ge=5, le=100)) -> Dict[str, Any]:
    """获取战法胜率拆分。"""
    try:
        stats = get_strategy_stats(strategy=strategy, window_size=window_size)
        return {"data": stats}
    except ValueError:
        raise HTTPException(404, {"detail": "Strategy not found"})
    except Exception as e:  # noqa: BLE001
        _logger.exception("战法胜率异常")
        raise HTTPException(502, "战法胜率异常，请稍后重试") from e


@router.post("/api/winrate/records")
async def add_winrate_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """录入交易记录（批量）。"""
    if not records:
        raise HTTPException(400, "records 不能为空")

    added: list[str] = []
    errors: list[dict] = []
    for idx, rec in enumerate(records):
        try:
            record = WinRateRecord(
                stock_code=str(rec.get("stock_code", "")).strip(),
                stock_name=str(rec.get("stock_name", "")).strip(),
                strategy_used=str(rec.get("strategy_used", "")).strip(),
                entry_date=str(rec.get("entry_date", "")).strip(),
                entry_price=float(rec.get("entry_price", 0)),
                exit_date=str(rec.get("exit_date", "")).strip(),
                exit_price=float(rec.get("exit_price", 0)),
                return_pct=float(rec.get("return_pct", 0)),
                is_win=bool(rec.get("is_win", False)),
                gene_score=float(rec.get("gene_score", 0) or 0),
                sti_label=str(rec.get("sti_label", "")).strip(),
                sector=str(rec.get("sector", "")).strip(),
            )
            if not record.stock_code or not record.entry_date or not record.exit_date:
                raise ValueError("stock_code / entry_date / exit_date 必填")
            _tracker.add_record(record)
            added.append(record.stock_code)
        except Exception as e:  # noqa: BLE001
            _logger.exception("录入交易记录异常，index=%s", idx)
            errors.append({"index": idx, "error": "record processing failed"})

    return {
        "data": {
            "added": added,
            "added_count": len(added),
            "errors": errors,
            "error_count": len(errors),
        }
    }


__all__ = ["router"]


# ============ S050 W0：影子对照端点 ============


def _shadow_comparison_impl(window_days: int, tracker: WinRateTracker) -> Dict[str, Any]:
    """S050 R4：影子对照算账纯实现（端点薄壳调用，便于测试注入 tracker）。

    follow/feeling/missed 三桶 + 独立性指标；只读 winrate.db/快照/workflow_state/K 线本地库，零外呼。
    """
    import sqlite3
    from datetime import datetime, timedelta
    from snapshot_store import load_snapshot, list_snapshot_dates

    db_path = tracker.db_path
    today = datetime.now().date()
    since = (today - timedelta(days=window_days)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM winrate_records WHERE entry_date >= ? ORDER BY entry_date DESC", (since,),
    ).fetchall()]
    conn.close()

    # follow 桶：signal_source ∈ (funnel_candidate, strategy_hit)
    follow = [r for r in rows if r.get("signal_source") in ("funnel_candidate", "strategy_hit")]
    # feeling 桶：signal_source='feeling'（legacy NULL 不计两桶）
    feeling = [r for r in rows if r.get("signal_source") == "feeling"]

    def _bucket(trades: list[dict]) -> dict:
        n = len(trades)
        if n == 0:
            return {"n": 0, "win_rate": None, "avg_return": None}
        wins = sum(1 for t in trades if t.get("is_win"))
        rets = [t["return_pct"] for t in trades if t.get("return_pct") is not None]
        return {
            "n": n,
            "win_rate": round(wins / n, 4),
            "avg_return": round(sum(rets) / len(rets), 4) if rets else 0.0,
        }

    follow_b = _bucket(follow)
    feeling_b = _bucket(feeling)

    # missed 桶：窗口内各快照日 final_candidates − 当日 holding/settled codes → 影子收益
    import workflow_state_repo as wsr

    snap_dates = [d for d in list_snapshot_dates() if d >= since]
    missed_returns: list[float] = []
    no_suggestion_days = 0
    missing_kline = 0
    from backtest_lite import _calc_next_day_return

    kline_cache: dict = {}
    for d in snap_dates:
        snap = load_snapshot(d)
        if not snap:
            no_suggestion_days += 1
            continue
        finals = snap.get("final_candidates") or []
        candidate_codes = [fc.get("code") for fc in finals if isinstance(fc, dict) and fc.get("code")]
        if not candidate_codes:
            no_suggestion_days += 1
            continue
        # 当日 holding/settled codes（用户实际买入的）
        states = wsr.list_states(d)
        held = {s["code"] for s in states if s.get("status") in ("holding", "settled", "monitoring")}
        missed_codes = [c for c in candidate_codes if c not in held]
        for code in missed_codes:
            ret = _calc_next_day_return(code, d, kline_cache)
            if ret == 0.0:
                # 0.0 可能是真 0 或 K 线缺返兜底——近似口径下保守计入 missing
                missing_kline += 1
                continue
            missed_returns.append(ret)
    missed_b = {
        "n": len(missed_returns),
        "win_rate": round(sum(1 for r in missed_returns if r > 0) / len(missed_returns), 4) if missed_returns else None,
        "avg_return": round(sum(missed_returns) / len(missed_returns), 4) if missed_returns else None,
    }

    # 独立性指标：一致率 = follow_n / (follow_n + feeling_n)；feeling 胜率
    denom = follow_b["n"] + feeling_b["n"]
    agreement_rate = round(follow_b["n"] / denom, 4) if denom > 0 else None

    # 诚实标记：任一桶 n<5 → sufficient=false
    sufficient = all(b["n"] >= 5 for b in (follow_b, feeling_b, missed_b))

    return {
        "window_days": window_days,
        "follow": follow_b,
        "feeling": feeling_b,
        "missed": {**missed_b, "missing_kline": missing_kline, "approx_note": "信号日收盘→次日收盘，近似口径"},
        "independence": {
            "agreement_rate": agreement_rate,
            "feeling_win_rate": feeling_b["win_rate"],
        },
        "no_suggestion_days": no_suggestion_days,
        "sufficient": sufficient,
        "disclaimer": "历史统计特征，市场有风险，研究参考",
    }


@router.get("/api/winrate/shadow-comparison")
async def shadow_comparison(window_days: int = Query(28, ge=7, le=90)) -> Dict[str, Any]:
    """S050 W0：影子对照——系统建议单 vs 用户实际单并排算账。

    follow 桶（signal_source=funnel_candidate/strategy_hit）/ feeling 桶 / missed 桶
    （快照候选未买入的影子收益，close-to-close 近似口径）+ 独立性指标（一致率/feeling 胜率）。
    诚实标记：n<5 → sufficient=false；无快照日计数；K 线缺失排除计数。
    只读本地私有库，零新外部调用。
    """
    try:
        return _shadow_comparison_impl(window_days, _tracker)
    except Exception as e:  # noqa: BLE001
        _logger.exception("影子对照异常")
        raise HTTPException(502, f"影子对照异常：{e}") from e


# ============ S054 W0：盘后三问 daily-review 端点 ============


def _daily_review_impl(date: str, tracker: WinRateTracker) -> Dict[str, Any]:
    """S054 R1：盘后三问纯实现（端点薄壳调用，便于测试注入 tracker）。

    pushed：当日快照 final_candidates（code/name/gene_score/strategies/完整性标记）；无快照则 no_snapshot=true
    bought：当日 workflow_state 新建仓（entry_status=holding），逐只带占位标签「待判定」
    missed：pushed − bought 的 code 名单（无收益，留白）
    prev_day_missed：上一交易日 missed 的标的次日收益 + 汇总
    只读本地库，零外部调用。
    """
    from snapshot_store import load_snapshot
    from vr_paths import last_trading_date_str
    import workflow_state_repo as wsr
    from backtest_lite import _calc_next_day_return
    from limitup_screener.data import load_gene_scores

    today = date

    # pushed：当日快照
    snap = load_snapshot(today)
    if not snap:
        return {"date": today, "no_snapshot": True, "pushed": [], "bought": [], "missed": [],
                "prev_day_missed": {"items": [], "summary": None},
                "missing_kline": 0, "disclaimer": "历史统计特征，市场有风险，研究参考"}

    finals = snap.get("final_candidates") or []
    # 从 gene_scores.db 补 total_score（DiagnosisCard 无 gene_score 字段）
    gene_map: dict[str, float] = {}
    gs = load_gene_scores(today)
    if gs:
        gene_map = {g.code: g.total_score for g in gs}

    pushed = []
    for fc in finals:
        if not isinstance(fc, dict) or not fc.get("code"):
            continue
        code = fc["code"]
        pushed.append({
            "code": code,
            "name": fc.get("name") or "",
            "gene_score": gene_map.get(code) if code in gene_map else fc.get("gene_score"),
            "strategies": [],  # 战法匹配在回测引擎，非单股持久化字段；诚实留空
        })
    pushed_codes = {p["code"] for p in pushed}

    # bought：当日 holding 记录（entry 约等于 trade_date）
    states = wsr.list_states(today)
    bought = [
        {
            "code": s["code"],
            "name": s.get("name") or "",
            "entry_price": s.get("entry_price"),
            "strategy": s.get("strategy"),
            "status": s["status"],
            "placeholder": "待判定",
        }
        for s in states if s.get("status") == "holding"
    ]
    bought_codes = {b["code"] for b in bought}

    # missed：pushed − bought
    missed = [{"code": c} for c in pushed_codes if c not in bought_codes]

    # prev_day_missed：上一交易日的 missed，次日收益
    from datetime import datetime as _dt, timedelta as _td
    try:
        prev_td = _dt.strptime(today, "%Y-%m-%d").date()
        prev_td = _dt.strptime(last_trading_date_str(prev_td - _td(days=1)), "%Y-%m-%d").date()
        prev_str = prev_td.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        prev_str = None

    prev_items: list[Dict[str, Any]] = []
    missing_kline = 0
    if prev_str:
        prev_snap = load_snapshot(prev_str)
        if prev_snap:
            prev_finals = prev_snap.get("final_candidates") or []
            prev_pushed = [fc.get("code") for fc in prev_finals if isinstance(fc, dict) and fc.get("code")]
            prev_states = wsr.list_states(prev_str)
            prev_bought = {s["code"] for s in prev_states if s.get("status") in ("holding", "settled", "monitoring")}
            prev_missed = [c for c in prev_pushed if c not in prev_bought]
            kline_cache: dict = {}
            for code in prev_missed:
                ret = _calc_next_day_return(code, prev_str, kline_cache)
                if ret == 0.0:
                    missing_kline += 1
                    continue
                prev_items.append({"code": code, "next_day_return": round(ret, 4)})

    prev_summary = None
    if prev_items:
        rets = [it["next_day_return"] for it in prev_items]
        prev_summary = {
            "n": len(prev_items),
            "avg_return": round(sum(rets) / len(rets), 4),
            "win_rate": round(sum(1 for r in rets if r > 0) / len(rets), 4),
            "signal_date": prev_str,
        }

    return {
        "date": today,
        "no_snapshot": False,
        "pushed": pushed,
        "bought": bought,
        "missed": missed,
        "prev_day_missed": {"items": prev_items, "summary": prev_summary},
        "missing_kline": missing_kline,
        "disclaimer": "历史统计特征，市场有风险，研究参考",
    }


@router.get("/api/winrate/daily-review")
async def daily_review(date: Optional[str] = Query(None, description="YYYY-MM-DD，默认今日")) -> Dict[str, Any]:
    """S054 R1：盘后三问——系统推了什么 / 你买了什么 / 漏了什么。

    pushed：当日快照 final_candidates；bought：当日新建仓（占位「待判定」）；
    missed：pushed − bought；prev_day_missed：上一交易日漏单次日收益 + 汇总。
    无快照诚实返回 no_snapshot=true；零外部调用。
    """
    from datetime import datetime as _dt
    from vr_paths import last_trading_date_str  # noqa: PLC0415
    # 非交易日（周末/节假日）回退到最近交易日——周六默认显示周五数据（语义正确）。
    target = date or last_trading_date_str()
    try:
        return _daily_review_impl(target, _tracker)
    except Exception as e:  # noqa: BLE001
        _logger.exception("盘后三问异常")
        raise HTTPException(502, f"盘后三问异常：{e}") from e
