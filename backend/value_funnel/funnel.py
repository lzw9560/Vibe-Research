"""S005 价值漏斗编排：L1 全市场扫描 → L2 去劣粗筛 → L3 精细分析 → L4 四大师深度。

合规：每层留/弃有可复现原因；L2 未通过者弃出、豁免命中者保留、护城河不剔除；
数据不足(missing/inapplicable)不弃出（标待人工判断）；L4 文字交 AI。
"""

from __future__ import annotations

import time
from datetime import datetime

from . import models
from .sources import l1_scan, l3_analysis, l4_deep_skeleton
from . import quality


def run_value_funnel(direction: str, stage: str = "all",
                     top_n_l1: int = 60, top_n_l4: int = 3) -> models.ValueFunnelResult:
    """运行价值漏斗。stage: L1/L2/L3/L4/all。"""
    run_id = f"vf-{int(time.time())}"
    result = models.ValueFunnelResult(run_id=run_id, direction=direction)
    do = stage == "all"

    # ---- L1 ----
    if stage in ("L1", "all"):
        layer = models.ValueFunnelLayer(layer_id="L1", name="全市场扫描",
                                        as_of=datetime.now())
        try:
            cands = l1_scan.scan_universe(direction, top_n=top_n_l1)
        except Exception as e:
            cands = []
            layer.filtered_out.append(models.ValueFilterRecord(
                code="", name="", layer="L1", reason=f"扫描异常: {e}"))
        layer.input_count = len(cands)
        layer.output_codes = [c["code"] for c in cands]
        layer.output_count = len(cands)
        result.layers.append(layer)
        if not cands or stage == "L1":
            return result

    # ---- L2 去劣粗筛 ----
    if stage in ("L2", "all"):
        prev = result.layers[-1].output_codes
        layer = models.ValueFunnelLayer(layer_id="L2", name="去劣粗筛",
                                        as_of=datetime.now(), input_count=len(prev))
        survivors = []
        for code in prev:
            try:
                qa = quality.compute_quality(code)
            except Exception as e:
                layer.filtered_out.append(models.ValueFilterRecord(
                    code=code, layer="L2", reason=f"去劣计算异常: {e}"))
                continue
            result.l2_assessments[code] = qa
            # 弃出条件：存在硬失败(passed=False 且 未豁免)
            hard_fail = [m for m in qa.metrics
                         if m.passed is False and not m.exempt and not m.inapplicable]
            if hard_fail:
                layer.filtered_out.append(models.ValueFilterRecord(
                    code=code, layer="L2",
                    reason="去劣未通过: " + "；".join(m.name for m in hard_fail)))
            else:
                survivors.append(code)
        layer.output_codes = survivors
        layer.output_count = len(survivors)
        result.layers.append(layer)
        if not survivors or stage == "L2":
            return result

    # ---- L3 精细分析骨架 ----
    if stage in ("L3", "all"):
        prev = result.layers[-1].output_codes
        layer = models.ValueFunnelLayer(layer_id="L3", name="精细分析",
                                        as_of=datetime.now(), input_count=len(prev))
        for code in prev:
            name = _name_of(code)
            try:
                result.l3_analyses[code] = l3_analysis.build_analysis_skeleton(code, name)
            except Exception as e:
                layer.filtered_out.append(models.ValueFilterRecord(
                    code=code, name=name, layer="L3", reason=f"分析骨架异常: {e}"))
        layer.output_codes = prev  # L3 不剔除（仅标骨架）
        layer.output_count = len(prev)
        result.layers.append(layer)
        if stage == "L3":
            return result

    # ---- L4 四大师深度（终选 top_n_l4） ----
    if stage in ("L4", "all"):
        prev = result.layers[-1].output_codes
        layer = models.ValueFunnelLayer(layer_id="L4", name="四大师深度",
                                        as_of=datetime.now(), input_count=len(prev))
        # 按 L2 调整通过率排序取前 N
        ranked = sorted(prev, key=lambda c: (result.l2_assessments[c].pass_rate_adjusted or 0),
                        reverse=True)
        finals = ranked[:top_n_l4]
        dropped = set(prev) - set(finals)
        for code in dropped:
            layer.filtered_out.append(models.ValueFilterRecord(
                code=code, name=_name_of(code), layer="L4",
                reason=f"终选截断(取前{top_n_l4}名)"))
        for code in finals:
            name = _name_of(code)
            summary = ""
            if code in result.l3_analyses:
                a = result.l3_analyses[code]
                summary = f"{a.financials_summary} | {a.valuation_position}"
            result.l4_finals.append(l4_deep_skeleton.build_deep_skeleton(code, name, summary))
        # S108：L4 finals 财报异常5信号（≤3 只，新浪三表 → detect_anomalies）
        # 限 L4 finals 不进 L2 全量（请求风暴防线：新浪 urllib 单表 12-25s ×3 表 ×60 候选会卡死）
        try:
            from data.sources.sina_financial import fetch_merged_periods
            from value_funnel.anomaly import detect_anomalies
            for code in finals:
                periods = fetch_merged_periods(code)
                if len(periods) >= 2:  # 不足2期 detect_anomalies 自标 inapplicable，这里省请求
                    result.l4_anomalies[code] = detect_anomalies(periods)
        except Exception:  # noqa: BLE001 — anomaly 故障不阻断 L4 主流程
            pass
        layer.output_codes = finals
        layer.output_count = len(finals)
        result.layers.append(layer)

    return result


def _name_of(code: str) -> str:
    """从 L1/L3 缓存取名称，失败返回空。"""
    # 简化：调用 astock 取名称（轻量），失败返回空
    try:
        import astock
        from data.mappers import quote_from_tencent
        raw = astock.tencent_quote([code]) or {}
        return quote_from_tencent(code, raw.get(code, {})).name or ""
    except Exception:
        return ""
