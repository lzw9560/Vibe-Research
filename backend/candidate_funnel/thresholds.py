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
# ⚠ 已停用（S072 STI 去噪，grill 2026-08-17）：STI 无 §44 edge（9 天数据 + 权重拍脑袋
# + 天气路由 lift 0.956<1），resolve_thresholds 不再按 phase 调阈值。保留作历史记录；
# 暴风雨极端由 §16.4 指数熔断（上证跌>3% 不开仓）+ Q7 仓位=0 兜底，不靠 R2 换手阈值。
PHASE_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "暴风雨": {"turnover_cold": 12.0},  # 风险期收紧活跃下限
    "阴天": {"turnover_cold": 10.0},  # 略收紧
    "极端反弹": {},  # 沿用基数
    "晴天": {},  # 沿用基数
    "未知": {},  # 沿用基数
}


def resolve_thresholds(cfg: ThresholdConfig, sti_phase: str | None) -> BaseThreshold:
    """基数 → 生效阈值。

    S072 STI 去噪（grill 2026-08-17）：sentiment_phase 不再调阈值——
    STI 无 §44 edge（9 天数据 + 权重拍脑袋 + 天气路由 lift 0.956<1），R2 情绪调阈值是
    同条无验证路径。固定基数。暴风雨极端由 §16.4 指数熔断 + Q7 仓位=0 兜底，不靠换手阈值。
    sti_phase 参数保留（不破坏签名），仅记录不改阈值。

    - manual：直用 base，不引入调整。
    - auto/suggest：固定 base，adjustment 标"STI 去噪固定基数"（可复现）。
    返回生效 BaseThreshold。会就地写回 cfg.adjustment / cfg.effective（spec §3.2 约定）。
    """
    base = cfg.base
    eff = base.model_copy()

    if cfg.mode == "manual":
        cfg.adjustment = None
        cfg.effective = eff
        return eff

    applied: dict[str, object] = {
        "phase": sti_phase,
        "note": "STI 去噪固定基数（sentiment_phase 不再调阈值，§44 grill 2026-08-17）",
    }
    if cfg.mode == "suggest":
        applied["依据"] = "STI 无 §44 edge，R2 阈值固定基数（暴风雨由指数熔断+仓位0兜底）"
    cfg.adjustment = applied
    cfg.effective = eff
    return eff


# ---------- S057：八项标准封顶配置 ----------
# 八项标准阈值（spec §2 DSA 原型，可在 thresholds.py 调整）
EIGHT_STANDARD_FLOAT_CAP_MIN = 30e8  # 流通市值下限 30 亿（元）
EIGHT_STANDARD_FLOAT_CAP_MAX = 150e8  # 流通市值上限 150 亿（元）
EIGHT_STANDARD_TURNOVER_MIN = 5.0  # 换手下限 %
EIGHT_STANDARD_TURNOVER_MAX = 20.0  # 换手上限 %
EIGHT_STANDARD_VOL_RATIO_MIN = 1.5  # 量比下限
EIGHT_STANDARD_SEAL_TIME_HOUR = 10  # 10:30 前封板
EIGHT_STANDARD_SEAL_TIME_MINUTE = 30
EIGHT_STANDARD_MAX_REOPENS = 1  # 开板次数上限
EIGHT_STANDARD_SEAL_RATIO_MIN = 0.01  # 封单>流通市值 1%
EIGHT_STANDARD_HOT_SECTOR_TOPN = 10  # 题材热度 TOP10
EIGHT_STANDARD_CAP_THRESHOLD = 55  # 封顶后最终得分上限
EIGHT_STANDARD_FAIL_CAP_COUNT = 3  # 未过数阈值
