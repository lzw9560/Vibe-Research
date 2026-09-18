# -*- coding: utf-8 -*-
"""S218 Component 1: 每日信号报告——纯函数核心。

封装唯一验证过的 edge（consecutive_relay）为结构化日报。
数字全部来自 §44 验证 / deep_dive，不臆造。
"""
from __future__ import annotations

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


# ── 3-bucket classification ──────────────────────────────────────────────

def _classify_signal(is_unbuyable: bool, regime: str | None) -> str:
    """3-bucket 分类。

    Returns:
        "tradable"     — bull regime + lbc 2-3 + 非一字板（edge validated）
        "exploratory"  — bear/range regime + lbc 2-3 + 非一字板（underpowered）
        "avoid"        — 一字板 或 lbc>=4（scanner 层已排除但留 filter 说明）
    """
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

        # 3-bucket classification
        bucket = _classify_signal(is_unbuyable, current_regime)

        signals.append({
            "code": code,
            "name": names.get(code, code),
            "lbc": lbc,
            "entry_price": ref_price,
            "price_source": price_source,
            "unbuyable": is_unbuyable,
            "bucket": bucket,
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
