# -*- coding: utf-8 -*-
"""candidate_funnel 自适应阈值解析。

对齐 specs/S002-plan.md §3.2 与 spec §5.2。
情绪 phase 词汇来自 routers/sentiment_weather 的 weather_state（晴天/阴天/暴风雨/极端反弹/未知）。
合规：只调档位边界，不引入方向判断；调整项写入 adjustment 以便可复现（AC5）。
"""

from __future__ import annotations

from candidate_funnel.models import BaseThreshold, ThresholdConfig

# 情绪 phase → 档位边界调整（spec §5.2：暴风雨换手下限提至 12%）。
# 仅收紧/放宽边界，不引入方向词。
PHASE_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "暴风雨": {"turnover_cold": 12.0},  # 风险期收紧活跃下限
    "阴天": {"turnover_cold": 10.0},  # 略收紧
    "极端反弹": {},  # 沿用基数
    "晴天": {},  # 沿用基数
    "未知": {},  # 沿用基数
}


def resolve_thresholds(cfg: ThresholdConfig, sti_phase: str | None) -> BaseThreshold:
    """基数 + 情绪调整 → 生效阈值。

    - manual：直用 base，不引入情绪调整。
    - auto/suggest：有 sti_phase 则按 PHASE_ADJUSTMENTS 调档位边界；缺 phase 降级为基数并标注。
    - 调整项与生效阈值写入 cfg.adjustment / cfg.effective 以便可复现。

    返回生效 BaseThreshold。注意：会就地写回 cfg.adjustment 与 cfg.effective（spec §3.2 约定）。
    """
    base = cfg.base

    if cfg.mode == "manual":
        eff = base.model_copy()
        cfg.adjustment = None
        cfg.effective = eff
        return eff

    if sti_phase is None:
        eff = base.model_copy()
        cfg.adjustment = {"phase": None, "降级": True, "note": "情绪档未取得，沿用基数"}
        cfg.effective = eff
        return eff

    adj = PHASE_ADJUSTMENTS.get(sti_phase, {})
    eff = base.model_copy()
    applied: dict[str, object] = {"phase": sti_phase}
    if adj:
        for field, value in adj.items():
            setattr(eff, field, value)
        applied.update(adj)
        applied["note"] = f"{sti_phase}调整档位边界"
    else:
        applied["note"] = f"{sti_phase}沿用基数"
    # suggest 模式额外标注建议依据（D3）
    if cfg.mode == "suggest":
        applied["依据"] = f"建议阈值：依据当日情绪档 {sti_phase} 调整档位边界，用户可一键接受或手调"
    cfg.adjustment = applied
    cfg.effective = eff
    return eff
