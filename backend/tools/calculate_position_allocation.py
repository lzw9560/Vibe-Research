# -*- coding: utf-8 -*-
"""calculate_position_allocation —— 情绪得分(0-100) → 长/中/短 仓位 + 风控止损 + 历史 verdict。

§44 v3 R26：仓位映射须透明文档化（非黑箱）。
§44 v3 R30：仓位建议须附该战法历史 verdict（诚实标注，不藏 falsified）。

仓位映射（文档化）：
- 0-35  冰点 → 长 70 / 中 20 / 短 10  （长线防御：红利低波 + 超跌核心）
- 36-70  常态 → 长 30 / 中 50 / 短 20  （中线波段：行业动量 + 小市值）
- 71-100 沸点 → 长 10 / 中 20 / 短 70  （短线高弹：龙头接力 + 1进2，已标 falsified + regime 未测）
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PositionAllocation:
    state: str  # 冰点/常态/沸点
    long_pct: int  # 长线仓位 %
    mid_pct: int  # 中线仓位 %
    short_pct: int  # 短线仓位 %
    stop_loss_rule: str  # 风控止损规则
    verdicts: dict  # 各战法历史 verdict（诚实标注，R30）


# 各战法历史 verdict（项目实测，不藏 falsified）
VERDICTS: dict[str, str] = {
    "红利低波_512890": "✅ 唯一诚实可落地（7-11% beta 倾斜）",
    "超跌核心资产波段": "⚠️ 均值回归 falsified 9/9 fail Bonf（但'超跌核心'≠均值回归，须基本面过滤）",
    "行业动量ETF级": "⚠️ blocked 须解封 ETF 数据（baostock fetch 0 行）",
    "小市值动量": "⚠️ size exploratory（CAPM alpha t=3.41）BUT 不可做空 + OOS fail + 衰减",
    "龙头接力_打板": "🔴 19 打板全样本 falsified + consecutive_relay direction-confirmed magnitude-uncertain (真值 -0.024%~-0.70%, 原-1.66%不可复现) BUT regime-conditional(仅沸点期)未测",
    "首板_1进2扫板": "🔴 consecutive_relay direction-confirmed falsified (原-1.66%不可复现, 真值-0.024%~-0.70%, chasing驱动+lottery结构) BUT regime-conditional 未测",
}

# 风控止损规则（按状态）
STOP_RULES: dict[str, str] = {
    "冰点": "长线持有为主，不追打板；破 60 日线减仓；红利低波 DRIP 不止损",
    "常态": "中线波段，破 20 日线离场；短线严 -5% 止损；不追连板",
    "沸点": "短线追高，破 5 日线无条件离场；核按钮（低开 > -5%）停接力 + 短线仓位立刻降半",
}


def allocate(score: int) -> PositionAllocation:
    """得分 → 仓位映射（透明，R26）。"""
    if score <= 35:
        state, long_pct, mid_pct, short_pct = "冰点", 70, 20, 10
    elif score <= 70:
        state, long_pct, mid_pct, short_pct = "常态", 30, 50, 20
    else:
        state, long_pct, mid_pct, short_pct = "沸点", 10, 20, 70
    return PositionAllocation(
        state=state,
        long_pct=long_pct,
        mid_pct=mid_pct,
        short_pct=short_pct,
        stop_loss_rule=STOP_RULES[state],
        verdicts=VERDICTS,
    )


if __name__ == "__main__":
    import sys

    score = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    r = allocate(score)
    print(f"得分 {score} → {r.state}")
    print(f"仓位 (长/中/短): {r.long_pct}/{r.mid_pct}/{r.short_pct}")
    print(f"风控: {r.stop_loss_rule}")
    print(f"\n各战法历史 verdict (R30 诚实标注):")
    for k, v in r.verdicts.items():
        print(f"  {k}: {v}")
