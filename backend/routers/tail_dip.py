# -*- coding: utf-8 -*-
"""策略4进化版（tail_dip_engine）API 路由。

v6.00：暴露 tail_dip_engine 的核心能力给前端/外部调用：
- GET  /api/strategy/tail-dip/scan        全市场尾盘错杀扫描
- GET  /api/strategy/tail-dip/deviation   个股实时偏离度时间序列
- POST /api/strategy/tail-dip/stop-loss   铁血止损决策
- GET  /api/strategy/tail-dip/drawdown    回撤断路器诊断+peak衰减方案
- GET  /api/strategy/tail-dip/financial   财务因子查询

合规：响应仅客观数据+因子值，无方向结论词、无参考价位。
"""
from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# 确保能 import strategies.tail_dip_engine
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from strategies.tail_dip_engine import (
    HARD_THRESHOLDS,
    calculate_anomalous_deviation,
    check_tail_volatility,
    diagnose_drawdown_lock,
    execute_iron_stop_loss,
    fetch_financial_substitute_factors,
    financial_red_line_shield,
    premarket_liquidity_fuse,
    propose_peak_decay,
    screen_tail_dip_candidate,
)

router = APIRouter(tags=["strategy-tail-dip"])


# ⚠️ 2026-10-17 归档：tail-dip 经8年walk-forward证伪（见 strategy4_backtest_result.md §5
# + memory tail-dip-falsified-2026-10-17）。所有 endpoint 返410证伪通告，不再返买入候选。
TAIL_DIP_FALSIFIED_NOTE: dict[str, Any] = {
    "falsified": True,
    "date": "2026-10-17",
    "reason": (
        "tail-dip(尾盘错杀低吸)经8年walk-forward证伪：原样本内-10%档+0.72%→8年-0.039%FAIL；"
        "walk-forward NOT confirmed(train负/test非显著)；R12相对alpha+0.36%为lottery中位负、"
        "不可长仓兑现。低吸类别结构性无edge。"
    ),
    "evidence": "strategy4_backtest_result.md §5 / backend/tools/_audit_tail_dip_full.py",
    "action": "本endpoint已下线，不再返回买入候选。引擎代码保留供复现(backend/strategies/tail_dip_engine.py)。",
}


def _falsified_gone() -> JSONResponse:
    """tail-dip已证伪归档，所有endpoint返410证伪通告（不再返买入候选）。"""
    return JSONResponse(status_code=410, content=TAIL_DIP_FALSIFIED_NOTE)


router = APIRouter(tags=["strategy-tail-dip"], dependencies=[Depends(_falsified_gone)])


# ─────────────────────────────────────────────────────────────────────────
# 1. 全市场尾盘错杀扫描
# ─────────────────────────────────────────────────────────────────────────

class TailDipScanResponse(BaseModel):
    """扫描结果响应体。"""
    candidates: list[dict[str, Any]]
    sector_change_pct: float
    sector_source: str
    thresholds: dict[str, float]
    total_scanned: int


@router.get("/api/strategy/tail-dip/scan")
def scan_tail_dip(
    min_drop: float = Query(-5.0, description="跌幅下限(负数)"),
    max_drop: float = Query(-3.0, description="跌幅上限(负数)"),
    min_amount: float = Query(1e7, description="成交额下限"),
    limit: int = Query(10, description="返回数量上限"),
    with_financial_filter: bool = Query(False, description="开启财务红线过滤(每只~16s)"),
) -> TailDipScanResponse:
    """全市场尾盘错杀扫描（进化版v6.00）。

    用全市场中位数涨跌幅作为板块近似，
    对每只票计算错杀偏离度（个股-板块 绝对值>=3%才算错杀）。
    """
    try:
        import subprocess
        import json
        import time as _time

        # v7.01：60秒缓存——盘中分钟级变化，避免重复拉5000只
        _CACHE_KEY = "_tail_dip_scan_cache"
        cache = getattr(scan_tail_dip, _CACHE_KEY, None)
        if cache and (_time.time() - cache[1]) < 60:
            all_stocks = cache[0]
        else:
            result = subprocess.run(
                ["/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance",
                 "market", "snapshot", "--limit", "5000",
                 "--output", "/tmp/tail_dip_scan.json"],
                capture_output=True, text=True, timeout=30,
            )
            try:
                with open("/tmp/tail_dip_scan.json") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return TailDipScanResponse(
                    candidates=[], sector_change_pct=0.0,
                    sector_source="数据拉取失败", thresholds={},
                    total_scanned=0,
                )
            all_stocks = data.get("data", {}).get("item", [])
            setattr(scan_tail_dip, _CACHE_KEY, (all_stocks, _time.time()))
        if not all_stocks:
            return TailDipScanResponse(
                candidates=[], sector_change_pct=0.0,
                sector_source="空数据", thresholds={},
                total_scanned=0,
            )

        # 全市场中位数涨跌幅
        valid = [s for s in all_stocks if s.get("price_change_ratio_pct") is not None]
        if valid:
            sorted_chgs = sorted(s["price_change_ratio_pct"] for s in valid)
            sector_pct = sorted_chgs[len(sorted_chgs) // 2]
            sector_src = f"全市场中位数(n={len(valid)})"
        else:
            sector_pct = 0.0
            sector_src = "无有效数据"

        candidates = []
        for s in all_stocks:
            chg = s.get("price_change_ratio_pct")
            turnover = s.get("turnover")
            price = s.get("last_price")
            volume = s.get("volume")
            if chg is None or turnover is None or price is None:
                continue

            # 基础筛选
            if chg > max_drop or chg < min_drop:
                continue
            if turnover < min_amount or price < HARD_THRESHOLDS["min_price"] or price > 80:
                continue

            # 错杀偏离度
            vol_ratio = s.get("vol_ratio", 1.0) or 1.0
            deviation = calculate_anomalous_deviation(
                code=s.get("thscode", ""),
                individual_change_pct=chg,
                sector_change_pct=sector_pct,
                volume_today=float(volume or 0),
                volume_ma5=float(volume or 0) / max(vol_ratio, 0.01),
            )
            if not deviation.is_anomalous:
                continue

            candidates.append({
                "code": s.get("thscode", ""),
                "name": s.get("name", ""),
                "price": price,
                "change_pct": chg,
                "turnover_yi": round(turnover / 1e8, 2),
                "deviation": deviation.anomalous_deviation,
                "confidence": deviation.confidence,
                "detail": deviation.detail,
                "stop_loss": HARD_THRESHOLDS["max_stop_loss"],
                "take_profit": HARD_THRESHOLDS["take_profit"],
            })

        candidates.sort(key=lambda x: x["deviation"], reverse=True)

        # v10.3：异步财务过滤——后台线程跑top20，结果写缓存，scan立即返回
        financial_summary = None
        if with_financial_filter and candidates:
            from strategies.tail_dip_engine import fetch_financial_substitute_factors
            import threading

            _FIN_CACHE_KEY = "_tail_dip_financial_cache"

            # 检查是否有缓存的财务过滤结果（5分钟有效）
            fin_cache = getattr(scan_tail_dip, _FIN_CACHE_KEY, None)
            if fin_cache and (_time.time() - fin_cache[1]) < 300:
                # 用缓存结果
                filtered = fin_cache[0]["filtered"]
                financial_summary = fin_cache[0]["summary"]
                candidates = filtered
            else:
                # 立即返回未过滤的候选 + 启动后台财务过滤
                # 前台只跑top3快速过滤（3×16s=48s < HTTP超时）
                top_fast = candidates[:3]
                filtered_fast = []
                blocked_fast = 0
                for c in top_fast:
                    code_raw = c["code"][:6]
                    factors = fetch_financial_substitute_factors(code_raw)
                    gw = factors.get("goodwill_ratio")
                    gw_blk = factors.get("goodwill_blocked", False)
                    ar = factors.get("ar_to_revenue_pct")
                    cf_neg = factors.get("cf_negative", False)
                    reduction = factors.get("has_reduction_recent", False)

                    blocked_reasons = []
                    if gw_blk and gw is not None: blocked_reasons.append(f"商誉{gw*100:.0f}%>=15%")
                    if ar and ar >= 40: blocked_reasons.append(f"应收{ar:.0f}%>=40%")
                    if cf_neg: blocked_reasons.append("现金流为负")
                    if reduction: blocked_reasons.append("有减持")
                    if not factors: blocked_reasons.append("财务数据缺失")

                    if blocked_reasons:
                        blocked_fast += 1
                    else:
                        c["financial_factors"] = {
                            "goodwill_ratio": gw,
                            "ar_to_revenue_pct": ar,
                            "cf_to_ni_pct": factors.get("cf_to_ni_pct"),
                            "debt_ratio": factors.get("debt_ratio"),
                        }
                        filtered_fast.append(c)

                # 启动后台线程跑剩余top20（不阻塞响应）
                def _bg_financial_filter():
                    try:
                        top20 = candidates[:20]
                        bg_filtered = []
                        bg_blocked = 0
                        for c in top20:
                            code_raw = c["code"][:6]
                            factors = fetch_financial_substitute_factors(code_raw)
                            gw = factors.get("goodwill_ratio")
                            gw_blk = factors.get("goodwill_blocked", False)
                            ar = factors.get("ar_to_revenue_pct")
                            cf_neg = factors.get("cf_negative", False)
                            reduction = factors.get("has_reduction_recent", False)

                            blocked_reasons = []
                            if gw_blk and gw is not None: blocked_reasons.append(f"商誉{gw*100:.0f}%>=15%")
                            if ar and ar >= 40: blocked_reasons.append(f"应收{ar:.0f}%>=40%")
                            if cf_neg: blocked_reasons.append("现金流为负")
                            if reduction: blocked_reasons.append("有减持")
                            if not factors: blocked_reasons.append("财务数据缺失")

                            if blocked_reasons:
                                bg_blocked += 1
                            else:
                                c["financial_factors"] = {
                                    "goodwill_ratio": gw,
                                    "ar_to_revenue_pct": ar,
                                    "cf_to_ni_pct": factors.get("cf_to_ni_pct"),
                                    "debt_ratio": factors.get("debt_ratio"),
                                }
                                bg_filtered.append(c)

                        bg_summary = {
                            "total_candidates": len(top20),
                            "blocked": bg_blocked,
                            "passed": len(bg_filtered),
                        }
                        setattr(scan_tail_dip, _FIN_CACHE_KEY,
                                ({"filtered": bg_filtered, "summary": bg_summary}, _time.time()))
                    except Exception:
                        pass  # 后台失败不影响前台

                t = threading.Thread(target=_bg_financial_filter, daemon=True)
                t.start()

                # 前台立即返回top3快速过滤结果
                financial_summary = {
                    "total_candidates": len(top_fast),
                    "blocked": blocked_fast,
                    "passed": len(filtered_fast),
                    "note": "top3快速过滤，top20后台计算中（5分钟后查询可见完整结果）",
                }
                candidates = filtered_fast

        return TailDipScanResponse(
            candidates=candidates[:limit],
            sector_change_pct=round(sector_pct, 2),
            sector_source=sector_src + (f" | 财务过滤: {financial_summary['passed']}/{financial_summary['total_candidates']}通过" if financial_summary else ""),
            thresholds={k: v for k, v in HARD_THRESHOLDS.items()
                        if isinstance(v, (int, float))},
            total_scanned=len(all_stocks),
        )
    except Exception as e:
        raise HTTPException(500, f"扫描失败: {e}") from e


# ─────────────────────────────────────────────────────────────────────────
# 2. 个股实时偏离度时间序列
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/tail-dip/deviation")
def get_deviation(
    code: str = Query(..., description="股票代码(不带后缀)"),
    date: str | None = Query(None, description="日期 YYYY-MM-DD(默认最新)"),
) -> dict:
    """个股vs全市场实时偏离度时间序列。"""
    from strategies.tail_dip_engine import compute_realtime_sector_deviation

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ".vibe-research", "intraday_accumulation", "intraday_microstructure.db",
    )
    results = compute_realtime_sector_deviation(code, db_path=db_path, date=date)
    if not results:
        raise HTTPException(404, f"无 {code} 的偏离度数据")
    return {
        "code": code,
        "date": date or results[0].ts[:10] if results else "",
        "data_points": [
            {
                "ts": r.ts,
                "stock_change": r.stock_change,
                "sector_median": r.sector_median,
                "sector_mean": r.sector_mean,
                "deviation_from_median": r.deviation_from_median,
                "deviation_from_mean": r.deviation_from_mean,
                "is_anomalous": r.is_anomalous,
                "sample_size": r.sample_size,
            }
            for r in results
        ],
        "max_deviation": max(r.deviation_from_median for r in results),
        "anomalous_count": sum(1 for r in results if r.is_anomalous),
    }


# ─────────────────────────────────────────────────────────────────────────
# 3. 铁血止损决策
# ─────────────────────────────────────────────────────────────────────────

class StopLossReq(BaseModel):
    code: str
    entry_price: float
    current_price: float
    intraday_low: float
    intraday_high: float
    days_held: int
    is_weekend_eve: bool = False
    sector_crash_pct: float = 0.0
    position_size_multiplier: float = 1.0


@router.post("/api/strategy/tail-dip/stop-loss")
def stop_loss_decision(req: StopLossReq) -> dict:
    """铁血止损决策（T+1动态跨领域风控）。"""
    result = execute_iron_stop_loss(
        code=req.code,
        entry_price=req.entry_price,
        current_price=req.current_price,
        intraday_low=req.intraday_low,
        intraday_high=req.intraday_high,
        days_held=req.days_held,
        is_weekend_eve=req.is_weekend_eve,
        sector_crash_pct=req.sector_crash_pct,
        position_size_multiplier=req.position_size_multiplier,
    )
    return {
        "code": result.code,
        "action": result.action,
        "trigger_price": result.trigger_price,
        "current_price": result.current_price,
        "entry_price": result.entry_price,
        "pnl_pct": result.pnl_pct,
        "reason": result.reason,
        "urgency": result.urgency,
    }


# ─────────────────────────────────────────────────────────────────────────
# 4. 回撤断路器诊断+peak衰减方案
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/tail-dip/drawdown")
def drawdown_diagnosis(
    equity: float = Query(..., description="当前权益"),
    peak: float = Query(..., description="历史峰值"),
    initial_capital: float = Query(100000.0, description="初始资金"),
    days: int = Query(..., description="跟踪天数"),
) -> dict:
    """回撤断路器诊断+peak渐进衰减方案。"""
    diag = diagnose_drawdown_lock(equity, peak, initial_capital, days)
    proposal = propose_peak_decay(equity, peak, initial_capital, days)

    return {
        "diagnosis": {
            "current_equity": diag.current_equity,
            "peak_equity": diag.peak_equity,
            "drawdown_cny": diag.drawdown_cny,
            "drawdown_pct": diag.drawdown_pct,
            "size_multiplier": diag.size_multiplier,
            "status": diag.status,
            "days_tracked": diag.days_tracked,
            "is_permanently_locked": diag.is_permanently_locked,
            "recovery_target": diag.recovery_target,
            "recovery_needed": diag.recovery_needed,
            "diagnosis": diag.diagnosis,
        },
        "peak_decay_proposal": {
            "current_peak": proposal.current_peak if proposal else None,
            "proposed_peak": proposal.proposed_peak if proposal else None,
            "decay_factor": proposal.decay_factor if proposal else None,
            "trigger_reason": proposal.trigger_reason if proposal else None,
            "new_recovery_needed": proposal.new_recovery_needed if proposal else None,
            "new_recovery_pct": proposal.new_recovery_pct if proposal else None,
            "size_mult_cap": proposal.size_mult_cap if proposal else None,
            "recommendation": proposal.recommendation if proposal else "无需衰减",
        } if proposal else None,
    }


# ─────────────────────────────────────────────────────────────────────────
# 5. 财务因子查询
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/tail-dip/financial")
def financial_factors(code: str = Query(..., description="股票代码")) -> dict:
    """财务因子查询（akshare生产模式，2-3秒/票）。"""
    factors = fetch_financial_substitute_factors(code)
    if not factors:
        raise HTTPException(404, f"无 {code} 的财务因子数据")
    return {"code": code, "factors": factors}


# ─────────────────────────────────────────────────────────────────────────
# 6. 尾盘波动率检查（轻量版——用14:50→15:00快照）
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/tail-dip/tail-volatility")
def tail_volatility_check(code: str = Query(..., description="股票代码")) -> dict:
    """尾盘波动率检查（轻量版——用14:50→15:00快照替代5分钟bar）。"""
    from strategies.tail_dip_engine import check_tail_volatility_from_snapshots

    import os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db = os.path.join(_root, ".vibe-research", "intraday_accumulation", "intraday_microstructure.db")
    kdb = os.path.join(_root, ".vibe-research", "baostock_kline_cache.db")

    r = check_tail_volatility_from_snapshots(code, db_path=db, kline_db_path=kdb)
    return {
        "code": r.code,
        "passed": r.passed,
        "tail_volatility": r.tail_volatility,
        "daily_volatility": r.daily_volatility,
        "volatility_ratio": r.volatility_ratio,
        "sample_days": r.sample_days,
        "is_manipulated": r.is_manipulated,
        "detail": r.detail,
    }


# ─────────────────────────────────────────────────────────────────────────
# 7. 小成交额错杀扫描（2026年唯一统计显著alpha p=0.026）
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/lvd/scan")
def lvd_scan(
    limit: int = Query(5, description="返回数量上限"),
) -> dict:
    """小成交额错杀低吸扫描（LVD策略）。

    2026年1-9月前向验证：
    - 日组合 n=158 mean=+0.99% WR=44% t=1.96 p=0.026（统计显著）
    - 单只 n=5517 mean=+1.60% WR=48% 止损-5% 持有2周

    筛选：成交额最低10% + 当日跌<-3% + 价格2~100元
    操作：次日开盘买，持有10个交易日，-5%止损，不设止盈
    """
    import subprocess
    import json as _json
    import time as _time

    # 60秒缓存
    _LVD_CACHE_KEY = "_lvd_scan_cache"
    cache = getattr(lvd_scan, _LVD_CACHE_KEY, None)
    if cache and (_time.time() - cache[1]) < 60:
        all_stocks = cache[0]
    else:
        result = subprocess.run(
            ["/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance",
             "market", "snapshot", "--limit", "5000",
             "--output", "/tmp/lvd_scan.json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            with open("/tmp/lvd_scan.json") as f:
                data = _json.load(f)
        except (FileNotFoundError, _json.JSONDecodeError):
            return {"candidates": [], "total_scanned": 0, "error": "数据拉取失败"}
        all_stocks = data.get("data", {}).get("item", [])
        setattr(lvd_scan, _LVD_CACHE_KEY, (all_stocks, _time.time()))

    from strategies.low_volume_dip import screen_low_volume_dip

    result = screen_low_volume_dip(all_stocks, max_stocks=limit)

    return {
        "candidates": [
            {
                "code": c.code,
                "name": c.name,
                "close": c.close,
                "change_pct": c.change_pct,
                "amount_yi": round(c.amount / 1e8, 2),
                "amount_percentile": c.amount_percentile,
                "stop_loss": c.stop_loss,
                "hold_days": c.hold_days,
                "score": c.score,
                "detail": c.detail,
            }
            for c in result.candidates
        ],
        "total_scanned": result.total_scanned,
        "sector_median_pct": result.sector_median_pct,
        "sector_source": result.sector_source,
        "edge_stats": result.edge_stats,
        "params": result.params,
    }


# ─────────────────────────────────────────────────────────────────────────
# 8. RSI择时信号（最强统计显著alpha p=0.0001）
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/rsi-timing/signal")
def rsi_timing_signal() -> dict:
    """RSI择时信号——检查4个指数RSI是否触发买入。

    回测：创业板RSI<25 mean+6.24% WR93% p=0.0001
    操作：买入指数ETF，持有20天，-8%止损
    """
    import subprocess
    import json as _json
    from strategies.rsi_timing import calculate_rsi, check_rsi_signal, RSI_PARAMS

    end_ms = int(__import__("time").time() * 1000)
    start_ms = end_ms - 60 * 86400000  # 近60天

    signals = []
    for code, params in RSI_PARAMS["indices"].items():
        r = subprocess.run(
            ["/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance",
             "index", "history", "--thscode", code,
             "--start-ms", str(start_ms), "--end-ms", str(end_ms)],
            capture_output=True, text=True, timeout=15,
        )
        try:
            d = _json.loads(r.stdout)
            items = d.get("data", {}).get("item", [])
            closes = [i["close_price"] for i in items if i.get("close_price")]
            if len(closes) < 20:
                continue
            sig = check_rsi_signal(code, closes)
            signals.append({
                "index_code": sig.index_code,
                "index_name": sig.index_name,
                "current_rsi": sig.current_rsi,
                "threshold": sig.threshold,
                "is_triggered": sig.is_triggered,
                "hold_days": sig.hold_days,
                "stop_loss_pct": sig.stop_loss_pct,
                "expected_return": sig.expected_return,
                "win_rate": sig.win_rate,
                "p_value": sig.p_value,
                "sample_size": sig.sample_size,
                "detail": sig.detail,
            })
        except Exception:
            continue

    any_triggered = any(s["is_triggered"] for s in signals)
    return {
        "signals": signals,
        "any_triggered": any_triggered,
        "recommendation": (
            "买入指数ETF，持有20天，-8%止损" if any_triggered else "等待RSI<30"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────
# 9. RSI+MACD组合信号（最强：mean+9.53% WR100%）
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/strategy/rsi-macd/signal")
def rsi_macd_signal() -> dict:
    """RSI+MACD组合信号——回测最强alpha。

    RSI<30+MACD金叉(±5天): n=16 mean+9.53% WR100% p=0.0000
    """
    import subprocess
    import json as _json
    from strategies.rsi_timing import check_rsi_macd_combo, RSI_PARAMS

    end_ms = int(__import__("time").time() * 1000)
    start_ms = end_ms - 60 * 86400000

    signals = []
    for code, params in RSI_PARAMS["indices"].items():
        if not params.get("p") or params["p"] > 0.01:
            continue
        r = subprocess.run(
            ["/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance",
             "index", "history", "--thscode", code,
             "--start-ms", str(start_ms), "--end-ms", str(end_ms)],
            capture_output=True, text=True, timeout=15,
        )
        try:
            d = _json.loads(r.stdout)
            items = d.get("data", {}).get("item", [])
            closes = [i["close_price"] for i in items if i.get("close_price")]
            if len(closes) < 30:
                continue
            sig = check_rsi_macd_combo(params["name"], closes)
            signals.append({
                "index_name": sig.index_name,
                "rsi": sig.rsi,
                "rsi_triggered": sig.rsi_triggered,
                "macd_dif": sig.macd_dif,
                "macd_dea": sig.macd_dea,
                "macd_hist": sig.macd_hist,
                "is_golden_cross": sig.is_golden_cross,
                "has_recent_cross": sig.has_recent_cross,
                "combo_signal": sig.combo_signal,
                "expected_60d": sig.expected_60d,
                "win_rate_60d": sig.win_rate_60d,
                "detail": sig.detail,
            })
        except Exception:
            continue

    buy_signals = [s for s in signals if s["combo_signal"] == "买入"]
    wait_signals = [s for s in signals if s["combo_signal"] == "等待"]

    return {
        "signals": signals,
        "buy_count": len(buy_signals),
        "wait_count": len(wait_signals),
        "recommendation": (
            "买入（RSI+MACD金叉确认）" if buy_signals
            else "等待MACD金叉确认" if wait_signals
            else "无信号"
        ),
    }
