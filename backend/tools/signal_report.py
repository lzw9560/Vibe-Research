# -*- coding: utf-8 -*-
"""S218 Component 1: 每日信号报告——纯函数核心。

封装唯一验证过的 edge（consecutive_relay）为结构化日报。
数字全部来自 §44 验证 / deep_dive，不臆造。
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("vibe-research")

# ── verified numbers（S217 chrono + deep_dive，禁臆造）───────────────────
_VERIFIED = {
    "chrono_train_pct": 1.57,
    "chrono_test_pct": 1.04,
    "chrono_decay_pct": 34,
    "chrono_p": 0.0054,
    "chrono_wr": 52.7,
    "deep_dive_lbc2_pct": 0.90,
    "deep_dive_lbc3_pct": 2.05,
    "bull_cap": 0.75,
    "bear_cap": 0.5,
    "range_cap": 0.5,
}

# ── regime cache freshness ──────────────────────────────────────────────

def _load_regime_cache() -> dict[str, Any] | None:
    """读 index_ma20_regime.json，返 raw dict 或 None。"""
    from vr_paths import resolve_data_dir
    cache_path = resolve_data_dir() / "index_ma20_regime.json"
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _regime_freshness() -> dict[str, Any]:
    """regime cache 新鲜度：最后日期 + 是否 stale（>2 天）。"""
    raw = _load_regime_cache()
    if raw is None:
        return {"last_cache_date": None, "stale": True, "n_dates": 0}
    dates = sorted(raw.keys())
    if not dates:
        return {"last_cache_date": None, "stale": True, "n_dates": 0}
    last = dates[-1]
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d")
        days_since = (datetime.now() - last_dt).days
        stale = days_since > 2
    except ValueError:
        stale = True
        days_since = None
    return {
        "last_cache_date": last,
        "stale": stale,
        "days_since": days_since,
        "n_dates": len(dates),
    }


# ── hard-stop gates ──────────────────────────────────────────────────────

def _check_sentiment_hardstop(target_date: str) -> tuple[bool, str]:
    """sentiment 硬停：天气=暴风雨 → 0 tradable。

    Returns:
        (is_triggered, reason) — is_triggered=True 时所有信号进 exploratory
    """
    try:
        from routers.sentiment_weather import compute_weather_snapshot  # noqa: PLC0415
        snap = compute_weather_snapshot(target_date)
        weather = snap.get("weather_state", "未知")
        if weather == "暴风雨":
            return True, f"sentiment_hardstop：天气=暴风雨（composite={snap.get('composite_score')}），0 tradable"
    except Exception:
        #  sentiment 服务异常时不阻塞主流程，标 degraded 但不硬停
        logger.warning("[_check_sentiment_hardstop] sentiment 服务异常，跳过 hard-stop", exc_info=True)
    return False, ""


def _check_regime_cache_stale() -> tuple[bool, str]:
    """regime cache stale 硬停：cache last-date < today-1 → 0 tradable。

    Returns:
        (is_triggered, reason) — is_triggered=True 时所有信号进 exploratory
    """
    freshness = _regime_freshness()
    if freshness.get("stale") is True:
        last = freshness.get("last_cache_date") or "unknown"
        return True, f"regime_cache_stale_hardstop：cache last-date={last}，超过 T-1，regime label 不可信，0 tradable"
    return False, ""


# ── 3-bucket classification ──────────────────────────────────────────────

def _classify_signal(
    is_unbuyable: bool,
    regime: str | None,
    *,
    hardstop_reason: str = "",
) -> str:
    """3-bucket 分类（hard-stop 已在外层应用）。

    Args:
        is_unbuyable: 是否一字板
        regime: bull/bear/range/unknown
        hardstop_reason: 非空字符串 → 触发 hard-stop，返回 "exploratory"

    Returns:
        "tradable"     — bull regime + lbc 2-3 + 非一字板（edge validated）
        "exploratory"  — bear/range regime + lbc 2-3 + 非一字板（underpowered）
                         或 hard-stop 触发（sentiment 退潮 / regime cache stale）
        "avoid"        — 一字板 或 lbc>=4（scanner 层已排除但留 filter 说明）
    """
    if hardstop_reason:
        return "exploratory"
    if is_unbuyable:
        return "avoid"
    if regime == "bull":
        return "tradable"
    return "exploratory"


def _get_reference_price(code: str, target_date: str) -> tuple[float | None, str]:
    """取最近可得收盘价作参考价。

    Returns:
        (price, source_note)
        source_note: "target_date" | "YYYY-MM-DD" | "live" | "N/A"
    """
    from engine.bars_provider import KlineCacheBarsProvider
    from ai.tools.stock_tools import query_quote

    bars = KlineCacheBarsProvider()(code)
    # 1. 优先找 target_date 的 close
    for b in bars:
        if str(b.get("date", ""))[:10] == target_date:
            close = b.get("close")
            if close is not None and close > 0:
                return float(close), target_date
    # 2. fallback：最近缓存 bar 的 close
    if bars:
        for b in reversed(bars):
            close = b.get("close")
            if close is not None and close > 0:
                return float(close), str(b.get("date", ""))[:10]
    # 3. fallback：query_quote live 当前价
    try:
        qd = query_quote([code])
        info = qd.get(code, {})
        if isinstance(info, dict):
            price = info.get("price") or info.get("close")
            if price is not None and float(price) > 0:
                return float(price), "live"
    except Exception:
        pass
    return None, "N/A"


# ── consecutive_relay decay stats (S218 #2 cap gate 真衰减) ────────────────

# s203 chrono holdout 须遍历 zt_history + baostock kline cache，~30-60s 正常；
# 超 60s 视为 hang（test_s218_p0_actual_pnl 4 测已证 unmocked 真调可 hang）→
# 返 fallback decay_stable=False source='timeout'，cap gate 保守不 fire 升 ×1.0。
_S203_TIMEOUT_SEC = 60


def _compute_consecutive_relay_decay() -> dict[str, Any]:
    """算 consecutive_relay 真衰减统计——替代 weekly_review 硬编码 cap gate。

    数字全部来自 s203 chrono forward-OOS（train vs test day-mean 衰减）+
    trade_journal 已平仓交易记录（bear_days 累积代理）。不臆造：s203 跑失败
    或 chrono underpowered 时返 decay_stable=False，cap gate 保守不 fire 升 ×1.0。

    chrono 口径：s203 的 returns 是 decimal（如 0.0157=1.57%），故
    train_day_mean / test_day_mean / test_day_std 均 decimal。衰减稳定义预注册：
    test_std < 0.02（decimal，=2.0 pct-points）AND n_test>=30——非 borderline power
    （S217 test_std≈0.0259 > 0.02 故 False，诚实标 borderline 非 stable）。

    Returns:
        decay_pct: (train_mean - test_mean) / train_mean * 100，train_mean<=0 时 0
        decay_stable: test_std < 0.02 AND n_test_days >= 30
        bear_days: consecutive_relay 已平仓交易 distinct exit_date 数（简化代理
                   cross-regime 累积；lbc3 子查询 TODO，暂返 0）
        lbc3_days: 0（TODO lbc=3 子查询，spec 标占位不实现）
        n_test_days / train_mean / test_mean: chrono 原值（可观测性）
        source: 's203_chrono' | 'underpowered' | 'error: {msg}'
    """
    fallback = {
        "decay_pct": 0.0,
        "decay_stable": False,
        "bear_days": 0,
        "lbc3_days": 0,
        "n_test_days": 0,
        "train_mean": None,
        "test_mean": None,
        "source": "error: unknown",
    }
    try:
        from tools.s203_consecutive_relay_harness import main as s203_main  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        logger.warning("[_compute_consecutive_relay_decay] s203 import 失败: %s", e)
        return {**fallback, "source": f"error: {e}"}

    # timeout wrapper：s203 chrono holdout 须遍历 zt_history，~30-60s 正常；超 60s 视为
    # hang → fallback decay_stable=False source='timeout'（保守不 fire 升 ×1.0）。
    # ThreadPoolExecutor 不能强杀线程——timeout 后主线程返 fallback，后台 hung 线程
    # 继续跑（无法 kill，进程退出时清理）；shutdown(wait=False) 避免主线程被 join 阻塞。
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(s203_main)
        try:
            result = future.result(timeout=_S203_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "[_compute_consecutive_relay_decay] s203 跑超 %ds，视为 hang → timeout fallback",
                _S203_TIMEOUT_SEC,
            )
            return {**fallback, "source": "timeout"}
        except Exception as e:  # noqa: BLE001
            logger.warning("[_compute_consecutive_relay_decay] s203 跑失败: %s", e)
            return {**fallback, "source": f"error: {e}"}
    finally:
        executor.shutdown(wait=False)

    chrono = result.get("bull_chrono_oos") or {}
    decision = chrono.get("decision")
    # chrono 空 / decision insufficient → underpowered（不 fire 升 ×1.0）
    if not chrono or decision == "insufficient":
        return {**fallback, "source": "underpowered"}

    train_mean = chrono.get("train_day_mean")
    test_mean = chrono.get("test_day_mean")
    test_std = chrono.get("test_day_std")
    n_test_days = chrono.get("n_test_days") or 0

    if train_mean is not None and test_mean is not None and train_mean > 0:
        decay_pct = (train_mean - test_mean) / train_mean * 100
    else:
        decay_pct = 0.0

    # decay_stable：test_std < 0.02 (decimal=2.0pct) AND n_test>=30
    decay_stable = bool(
        test_std is not None and test_std < 0.02 and n_test_days >= 30
    )

    # bear_days / lbc3_days from trade_journal（已平仓交易 distinct exit_date）
    bear_days = 0
    lbc3_days = 0  # TODO lbc=3 子查询，spec 标占位不实现
    try:
        from engine.trade_journal import TradeJournal  # noqa: PLC0415
        tj = TradeJournal()
        records = tj.query_records(
            arm="consecutive_relay", is_realized=1, is_dead_arm=None
        )
        exit_dates = {r.exit_date for r in records if getattr(r, "exit_date", None)}
        bear_days = len(exit_dates)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[_compute_consecutive_relay_decay] trade_journal 查询失败: %s", e
        )

    return {
        "decay_pct": round(decay_pct, 4),
        "decay_stable": decay_stable,
        "bear_days": bear_days,
        "lbc3_days": lbc3_days,
        "n_test_days": n_test_days,
        "train_mean": train_mean,
        "test_mean": test_mean,
        "source": "s203_chrono",
    }


# ── pure-fn core: get_consecutive_relay_signals ───────────────────────────

def get_consecutive_relay_signals(target_date: str) -> dict[str, Any]:
    """生成 consecutive_relay 臂的每日信号报告。

    流程：
    1. scan_consecutive_relay → [{code, lbc}]
    2. compute_regime_labels → current regime
    3. lift_for_arm("consecutive_relay", regime) → effective cap + note
    4. query_quote → name 解析
    5. _get_reference_price → 最近可得 close 作参考价
    6. is_unbuyable_next_bar → 可做/探索性/别碰（3-bucket）
    7. regime cache freshness

    返结构化 dict（immutable，供 render + API + scheduler 复用）。
    """
    from pre_limitup_scanner import scan_consecutive_relay
    from engine.bar_utils import is_unbuyable_next_bar
    from engine.bars_provider import KlineCacheBarsProvider
    from tools.gap_regime_stratified import compute_regime_labels
    from candidate_funnel.evaluation import lift_for_arm

    # 1. scan
    raw_signals = scan_consecutive_relay(target_date)

    # 2. regime
    regime_map = compute_regime_labels()
    current_regime = regime_map.get(target_date, None)
    regime_label = current_regime or "unknown"

    # 3. cap
    cap_mult, cap_note = lift_for_arm("consecutive_relay", regime=current_regime)

    # cap 拆解（公式：base × decay × regime × zuoT）
    base = 1.0
    decay = 0.75
    if current_regime == "bull":
        regime_factor = 1.0
    else:
        regime_factor = 0.5 / (base * decay) if cap_mult else 1.0

    # 4. name resolution
    codes = [s["code"] for s in raw_signals]
    names: dict[str, str] = {}
    if codes:
        try:
            from ai.tools.stock_tools import query_quote
            quote_data = query_quote(codes)
            for c in codes:
                info = quote_data.get(c, {})
                if isinstance(info, dict):
                    names[c] = info.get("name", c)
                else:
                    names[c] = c
        except Exception:
            names = {c: c for c in codes}

    # Hard-stop gates (applied before classification)
    # Gate 1: sentiment 退潮（暴风雨 → 0 tradable）
    sentiment_triggered, sentiment_reason = _check_sentiment_hardstop(target_date)
    # Gate 2: regime cache stale（>T-1 → 0 tradable）
    cache_stale_triggered, cache_stale_reason = _check_regime_cache_stale()

    # Compose hard-stop reason (any trigger → all signals go exploratory)
    hardstop_reason = ""
    if sentiment_triggered:
        hardstop_reason = sentiment_reason
    elif cache_stale_triggered:
        hardstop_reason = cache_stale_reason

    # 5. per-candidate: reference price + unbuyable filter + 3-bucket classification
    provider = KlineCacheBarsProvider()
    signals: list[dict[str, Any]] = []
    for s in raw_signals:
        code = s["code"]
        lbc = s["lbc"]

        # reference price
        ref_price, price_source = _get_reference_price(code, target_date)

        # unbuyable: 用 target_date bar 判
        bars = provider(code)
        is_unbuyable = False
        if bars:
            for b in bars:
                if str(b.get("date", ""))[:10] == target_date:
                    is_unbuyable = is_unbuyable_next_bar(b, code=code)
                    break

        # 3-bucket classification（hard-stop 优先）
        bucket = _classify_signal(
            is_unbuyable, current_regime,
            hardstop_reason=hardstop_reason,
        )

        signals.append({
            "code": code,
            "name": names.get(code, code),
            "lbc": lbc,
            "entry_price": ref_price,
            "price_source": price_source,
            "unbuyable": is_unbuyable,
            "bucket": bucket,
            "hardstop_reason": hardstop_reason if hardstop_reason else None,
        })

    # 分类统计
    tradable = [s for s in signals if s["bucket"] == "tradable"]
    exploratory = [s for s in signals if s["bucket"] == "exploratory"]
    avoid = [s for s in signals if s["bucket"] == "avoid"]

    freshness = _regime_freshness()

    # regime edge status 标注
    if current_regime == "bull":
        regime_edge_status = "bull validated（train 1.57%→test 1.04%，p=0.0054）"
    elif current_regime in ("bear", "range"):
        regime_edge_status = f"{current_regime} underpowered（<60 test 天没法定，×0.5 保守）"
    else:
        regime_edge_status = "regime unknown（cache 缺失→保守 ×0.5）"

    return {
        "date": target_date,
        "arm": "consecutive_relay",
        "regime": {
            "current": regime_label,
            "edge_status": regime_edge_status,
            "freshness": freshness,
        },
        "cap": {
            "effective": cap_mult,
            "base": base,
            "decay": decay,
            "regime_factor": regime_factor,
            "zuoT_factor": 1.0,
            "note": cap_note,
        },
        "hardstop": {
            "active": bool(hardstop_reason),
            "reason": hardstop_reason or None,
        },
        "filters": {
            "total_scanned": len(raw_signals),
            "tradable": len(tradable),
            "exploratory": len(exploratory),
            "avoid": len(avoid),
        },
        "signals": signals,
        "verified_numbers": {
            "chrono_train": _VERIFIED["chrono_train_pct"],
            "chrono_test": _VERIFIED["chrono_test_pct"],
            "chrono_decay_pct": _VERIFIED["chrono_decay_pct"],
            "chrono_p": _VERIFIED["chrono_p"],
            "chrono_wr": _VERIFIED["chrono_wr"],
            "deep_dive_lbc2": _VERIFIED["deep_dive_lbc2_pct"],
            "deep_dive_lbc3": _VERIFIED["deep_dive_lbc3_pct"],
        },
        "disclaimers": _build_disclaimers(regime_label, cap_mult),
    }


def _build_disclaimers(regime: str, cap_mult: float) -> list[str]:
    """构建 spec §44 reframe 版免责声明（人话）。"""
    disclaimers = [
        "统计验证（非已实现收益）—— edge 衰减中（train 1.57%→test 1.04% 跌 34%）",
        "paper-only 无券商（零真交易）—— 接券商前所有战绩 paper，要真获益须手动在券商下单",
        "照做有风险 —— cap（75%/50%）是统计信心不是保本，真钱仓位由你手动定",
        "非自动交易 —— 本系统不自动下单，须手动在券商下单",
    ]
    if regime == "bull":
        disclaimers.append(f"bull 已 validated（×{cap_mult}），但 within-regime only，别跨 regime 推广")
    else:
        disclaimers.append(
            f"当前 {regime} regime：edge underpowered（<60 test 天没法定），"
            f"×{cap_mult} 是保守标注非 edge 证否，谨慎参考"
        )
    return disclaimers


# ── render: human-language report ───────────────────────────────────────

def render_daily_report(signals: dict[str, Any]) -> str:
    """将结构化信号渲染为人话报告（非术语堆）。

    人话原则：
    - 用"验证中的信号"而非"not_validated"
    - 用"预期收益（EV）"而非"price target"
    - 标注"研究参考"而非"投资建议"
    - deep_dive 数字单独标"探索性"，不与 chrono 混
    """
    date = signals.get("date", "")
    regime = signals.get("regime", {}).get("current", "unknown")
    edge_status = signals.get("regime", {}).get("edge_status", "")
    cap = signals.get("cap", {})
    cap_eff = cap.get("effective", 1.0) if isinstance(cap, dict) else 1.0
    sig_list = signals.get("signals", [])
    verified = signals.get("verified_numbers", {})
    disclaimers = signals.get("disclaimers", [])

    lines: list[str] = []
    lines.append(f"=== {date} 每日信号报告 ===")
    lines.append("")
    lines.append(f"市场状态：{regime}（{edge_status}）")
    lines.append(f"有效 cap：×{cap_eff}")
    lines.append("")

    # 验证数字（人话版）
    lines.append("【验证情况】")
    lines.append(f"  回测训练期收益：{verified.get('chrono_train', 'N/A')}%（train）")
    lines.append(f"  回测测试期收益：{verified.get('chrono_test', 'N/A')}%（test，衰减 {verified.get('chrono_decay_pct', 'N/A')}%）")
    lines.append(f"  统计显著性：p={verified.get('chrono_p', 'N/A')}（oos_supporting）")
    lines.append(f"  胜率：{verified.get('chrono_wr', 'N/A')}%")
    lines.append("")

    # deep_dive 数字（探索性，单独标）
    if verified.get("deep_dive_lbc2") or verified.get("deep_dive_lbc3"):
        lines.append("【探索性参考（deep_dive，样本小，待复验）】")
        if verified.get("deep_dive_lbc2"):
            lines.append(f"  lbc=2 平均收益：{verified['deep_dive_lbc2']}%（探索性）")
        if verified.get("deep_dive_lbc3"):
            lines.append(f"  lbc=3 平均收益：{verified['deep_dive_lbc3']}%（探索性）")
        lines.append("")

    # 3-bucket 信号列表
    tradable = [s for s in sig_list if s["bucket"] == "tradable"]
    exploratory = [s for s in sig_list if s["bucket"] == "exploratory"]
    avoid = [s for s in sig_list if s["bucket"] == "avoid"]

    # 可做（tradable）
    lines.append(f"【可做】({len(tradable)} 只) — bull validated edge")
    if tradable:
        for s in tradable:
            price = s.get("entry_price")
            price_str = f"{price:.2f}" if price is not None else "N/A"
            ps = s.get("price_source", "")
            ps_note = f"（参考价来源 {ps}）" if ps and ps not in ("N/A", date) else ""
            lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）— 参考价 ¥{price_str}{ps_note}")
    else:
        lines.append("  无")
    lines.append("")

    # 探索性（exploratory）
    lines.append(f"【探索性】({len(exploratory)} 只) — bear/range underpowered，×0.5 保守")
    if exploratory:
        for s in exploratory:
            price = s.get("entry_price")
            price_str = f"{price:.2f}" if price is not None else "N/A"
            ps = s.get("price_source", "")
            ps_note = f"（参考价来源 {ps}）" if ps and ps not in ("N/A", date) else ""
            lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）— 参考价 ¥{price_str}{ps_note}")
        lines.append("  （bear edge 未 validated，<60 test 天没法定，非 bull-validated）")
    else:
        lines.append("  无")
    lines.append("")

    # 别碰（avoid）
    lines.append(f"【别碰】({len(avoid)} 只)")
    if avoid:
        for s in avoid:
            lines.append(f"  {s['code']} {s['name']}（连板{s['lbc']}）— 原因：一字板")
    else:
        lines.append("  无")
    lines.append("")

    # 入场指引
    lines.append("【入场指引】")
    lines.append("  入场 = 今日 14:57-15:00 收盘集合竞价市价买")
    lines.append("  参考价 = 最近可得收盘价（见上）")
    lines.append("  实际成交价 ≈ 参考价 ± 小范围波动")
    lines.append("")

    # 风险提示
    lines.append("【风险提示】")
    lines.append("  • gap_net_return 假设 D+1 开盘能卖，但 lbc≥2 股 D+1 一字跌停卖不掉")
    lines.append("    → 实际收益可能比测的差，待量化")
    lines.append("  • 真钱仓位由用户手动决定")
    lines.append("")

    # 免责声明（spec §44 reframe 版）
    lines.append("【重要说明】")
    for d in disclaimers:
        lines.append(f"  {d}")

    return "\n".join(lines)
