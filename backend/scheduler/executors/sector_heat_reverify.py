# -*- coding: utf-8 -*-
"""S218 #12 sector_heat 非-arm 重验 cron——每 30 天重跑 §44，days≥60 跨阈 → write_override。

背景（deep-review 2026-09-18 w1d19k2hl #12）：
sector_heat（evaluation.py:175，zt≥3 臂 lift=1.359/n=466/days_robust=41/×0.5，note"60 天后复验"）
是全 registry 离 2.0 floor 最近的非 validated 信号（regime-stratified probe zt≥5 range 2.218 最近）。
但 r3_enforce（backtest.py:210）只处理 arm-mapped dims（breakout/trend/post_first_board/consecutive_relay
via DIM_ARM_MAP），sector_heat 无 arm → skip_non_arm 永远冻 ×0.5。本 executor 补这个洞：
每 30 天重跑 tools/sector_heat_validation.compute()，days_robust 跨 60 调 write_override 升降级。

决策门（§44v2 规约④ cap 一致，CLAUDE.md §1.2 lift_to_multiplier 同源逻辑）：
- days<60 → skip（underpowered，保持 ×0.5，不臆造 enforce——§44v2 days<60 不判）
- days≥60 + lift≥2.0 → write_override 升 ×1.0（lift_to_multiplier: validated/待复验 均 ×1.0）
- days≥60 + lift<1.0 → write_override 降 ×0.1（劣于随机 robust）
- else（1≤lift<2）→ skip（保持 ×0.5，无变化不写 override 避免无意义 write）

非 event edge（sector_heat lift!=None 无 regime_caps）→ write_override 内部 lift_to_multiplier
正常路径（不像 consecutive_relay lift=None/regime_caps 走 weekly_review cap gate——见
backtest.py:265 event-edge 守卫）。canonical arm = zt>=3（匹配 registry frozen baseline 语义一致）。

工程底线：
- 不臆造数据（compute() 真实重跑 sector_heat_validation 逻辑，查 gene_scores.db eastmoney_live）
- 不碰 signal_report.py（#2）/ s203（#6）/ evaluation.py（#7）/ fund_accum.py（#11）边界
- 私有 DB 在 .vibe-research/gene_scores.db（compute() 内部 _connect 路径，不落 home）
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def sector_heat_reverify(payload: Dict[str, Any]) -> Dict[str, Any]:
    """每 30 天重跑 sector_heat §44，days≥60 跨阈 → write_override 升降级（S218 #12）。

    调 tools.sector_heat_validation.compute() 取结构化结果（不解析 stdout），挑 canonical
    heat_def（默认 zt>=3，匹配 registry frozen baseline），算 lift/n/ci_overlap，决策门
    判升/降/skip，跨阈调 write_override（phase=r3_reverify）。

    Args:
        payload: {"threshold_days": 60, "heat_def": "zt>=3"}。threshold_days 默认 60
            （§44v2 规约④ days≥60 才下定论）；heat_def 默认 zt>=3（registry canonical arm）。

    Returns:
        ok/skip_*：{status, days_robust, lift, n, heat_def, verdict, n_updated[, override]}；
        error：compute() 异常或 heat_def 缺失（已 log，不 crash scheduled task）。
    """
    from tools.sector_heat_validation import compute  # noqa: PLC0415
    from candidate_funnel.lift_override import write_override  # noqa: PLC0415

    threshold_days = int(payload.get("threshold_days", 60))
    canonical_arm = str(payload.get("heat_def", "zt>=3"))  # registry canonical（zt≥3 臂）
    src = "scheduler/executors/sector_heat_reverify.py"

    # 真实重跑 sector_heat §44（查 gene_scores.db eastmoney_live，不臆造）
    try:
        data = compute()
    except Exception as e:  # noqa: BLE001 — compute 崩不阻断 scheduled task，降级 error run
        logger.warning("[sector_heat_reverify] compute() 失败: %s", e)
        return {"status": "error", "error": repr(e)[:200], "heat_def": canonical_arm,
                "threshold_days": threshold_days}

    days = int(data.get("days", 0))
    defs = {d["name"]: d for d in data.get("heat_defs", [])}
    arm = defs.get(canonical_arm)
    if arm is None:
        logger.warning("[sector_heat_reverify] heat_def %s 未在 compute() 结果中（可用: %s）",
                       canonical_arm, list(defs.keys()))
        return {"status": "error", "days_robust": days, "heat_def": canonical_arm,
                "error": f"heat_def {canonical_arm} not found in compute() results",
                "available": list(defs.keys())}

    lift = float(arm["lift"])
    n = int(arm["hot_n"]) + int(arm["cold_n"])
    ci_overlap = bool(arm["ci_overlap"])

    # §44v2 规约④：days<60 标 underpowered 不判（保持 ×0.5 skip，不臆造 enforce）
    if days < threshold_days:
        logger.info("[sector_heat_reverify] days=%d<%d underpowered，skip（保持 ×0.5）lift=%.3f",
                    days, threshold_days, lift)
        return {"status": "skip_underpowered", "days_robust": days, "lift": lift, "n": n,
                "heat_def": canonical_arm, "threshold": threshold_days,
                "verdict": f"underpowered (days<{threshold_days}) keep ×0.5", "n_updated": 0}

    # days≥60: decision gate
    if lift >= 2.0:
        # 升 ×1.0（lift_to_multiplier: lift≥2+CI不重叠+robust→validated ×1.0 /
        # CI重叠→待复验 ×1.0，均 ×1.0；write_override 内部算 status/mult）
        wb = write_override("sector_heat", lift, n, days, phase="r3_reverify",
                            source_script=src, ci_overlap=ci_overlap, robust=True)
        logger.warning("[sector_heat_reverify] 升级 days=%d lift=%.3f≥2.0 → ×%.2f (phase=r3_reverify)",
                       days, lift, wb.get("weight_multiplier", 1.0))
        return {"status": "upgraded", "days_robust": days, "lift": lift, "n": n,
                "heat_def": canonical_arm,
                "verdict": "validated (lift≥2.0 days≥60) → ×1.0",
                "n_updated": 1, "override": wb}
    if lift < 1.0:
        # 降 ×0.1（劣于随机 robust；write_override 内 lift_to_multiplier: lift<1+robust→×0.1）
        wb = write_override("sector_heat", lift, n, days, phase="r3_reverify",
                            source_script=src, ci_overlap=ci_overlap, robust=True)
        logger.warning("[sector_heat_reverify] 降级 days=%d lift=%.3f<1.0 → ×%.2f (phase=r3_reverify)",
                       days, lift, wb.get("weight_multiplier", 0.1))
        return {"status": "downgraded", "days_robust": days, "lift": lift, "n": n,
                "heat_def": canonical_arm,
                "verdict": "劣于随机 (lift<1.0 days≥60) → ×0.1",
                "n_updated": 1, "override": wb}

    # 1≤lift<2 → skip（保持 ×0.5，无变化不写 override 避免无意义 write）
    logger.info("[sector_heat_reverify] days=%d lift=%.3f（1≤lift<2）skip（保持 ×0.5）",
                days, lift)
    return {"status": "skip_no_change", "days_robust": days, "lift": lift, "n": n,
            "heat_def": canonical_arm,
            "verdict": "未validated (1≤lift<2 days≥60) keep ×0.5", "n_updated": 0}
