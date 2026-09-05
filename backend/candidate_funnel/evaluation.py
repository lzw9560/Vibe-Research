# -*- coding: utf-8 -*-
"""S151 漏斗评价层：预登记冻结 + 降权梯度 + 诚实标注 + 即时处理。

5 支柱（spec S151）：
- R1 DIMENSION_LIFT_REGISTRY：§44 已测值静态冻结表（commit hash 锁定事后不调）
- R2 lift_to_multiplier：lift/n/CI/robust → (status, multiplier) 纯函数，复用 judge_lift_four_states + PASS_LIFT_FLOOR
- R5 _apply_evaluation_layer：在 funnel.py:466 card 构建后注入降权+即时处理+诚实标注

降权梯度：lift<1 robust→×0.1 / 1≤lift<2→×0.5 / ≥2+CI不重叠→×1.0 / n<30→×1.0 探索性
不硬剔（tradability 硬剔保留 R2 _filter_tradability），降权维度保留采数不参与排序。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# 预注册冻结 commit hash（S151 spec 创建时锁定，事后不调参）
FROZEN_COMMIT = "b1aba21"  # S150/S153/S151 spec 首次 commit（2026-09-05）

# §44 阈值常量（复用 forward_test.py，避免重复定义）
PASS_LIFT_FLOOR = 2.0        # validated 门槛
PASS_LIFT_HARD_FLOOR = 1.0   # 劣于随机 门槛


@dataclass(frozen=True)
class DimensionValidation:
    """单维度的 §44 验证结果 + 降权权重（冻结值，回溯后可更新 updated_*）。"""
    dimension_id: str
    label: str
    lift: Optional[float]          # rho for gene（无方向性 → 视为 <1）
    n: int
    days_robust: int               # day-cluster robust 日数
    validation_status: str         # validated/未validated/劣于随机/探索性
    weight_multiplier: float       # ×1.0/×0.5/×0.1
    source_script: str             # 来源脚本（可追溯，禁臆造）
    note: str = ""
    frozen_commit: str = FROZEN_COMMIT
    frozen_at: str = "2026-09-05"


# R1：DIMENSION_LIFT_REGISTRY 初始冻结值（全部来自 §44 已跑脚本输出，禁臆造）
DIMENSION_LIFT_REGISTRY: dict[str, DimensionValidation] = {
    "gene_score": DimensionValidation(
        dimension_id="gene_score", label="gene 综合分",
        lift=0.030, n=2332, days_robust=38,              # rho≈0.030（Spearman，无单调→视为劣于随机）
        validation_status="劣于随机", weight_multiplier=0.1,
        source_script="tools/gene_score_directionality.py",
        note="rho≈0.030 robust null，无方向预测力（52bedf8）",
    ),
    "breakout": DimensionValidation(
        dimension_id="breakout", label="breakout_20d",
        lift=1.363, n=43691, days_robust=42,
        validation_status="未validated", weight_multiplier=0.5,   # §F：按梯度 ×0.5（非用户框架 ×0.1）
        source_script="tools/kline_ta_validation.py",
        note="4 方向特征里最弱，CI 不重叠非纯噪声但 <2x",
    ),
    "turnover": DimensionValidation(
        dimension_id="turnover", label="换手剔除(>30%)",
        lift=0.9979, n=14366, days_robust=167,           # 167 日大样本 robust
        validation_status="劣于随机", weight_multiplier=0.1,
        source_script="tools/first_board_layer_lift.py --baostock",
        note="换手>30% 剔除后 lift<1，越剔越差（本会话跑）",
    ),
    "seal_amount": DimensionValidation(
        dimension_id="seal_amount", label="封板质量(炸板/封单)",
        lift=0.9897, n=177, days_robust=5,              # 5 日弱样本
        validation_status="探索性", weight_multiplier=1.0,       # n 小 + 5 日非 robust → 探索性待 60 日
        source_script="tools/first_board_layer_lift.py --baostock-history",
        note="5 日弱样本方向性但非 robust，待 60 日复验",
    ),
    "path_lift": DimensionValidation(
        dimension_id="path_lift", label="选股整体 path_lift",
        lift=0.978, n=627, days_robust=44,              # 627 picks / 2708 universe
        validation_status="劣于随机", weight_multiplier=0.1,
        source_script="tools/s145_recompute_path.py",
        note="选股整体 path_lift<1，s145 敏感性 5 组 0.87-0.97 robust",
    ),
    # S152 盘中 H2（baostock 5min 历史补，突破 seal_intraday 30 天 live 卡点）
    "first_plate_h2": DimensionValidation(
        dimension_id="first_plate_h2", label="盘中 H2 早封板(<=10:00)",
        lift=0.8273, n=1125, days_robust=31,           # full run 2717 features / 31 日
        validation_status="劣于随机", weight_multiplier=0.1,
        source_script="tools/first_plate_h2_lift.py --full",
        note="S152 baostock 5min 早封板 lift<1（null_p95=1.048，pass_filter_edge=False）；"
             "盘中封板时间无 edge；caveat: T+0 o2c+5min 粒度",
    ),
    "late_lock": DimensionValidation(
        dimension_id="late_lock", label="盘中晚封板/尾盘突袭(>14:00)",
        lift=1.3559, n=422, days_robust=31,             # full run robust（preliminary 1.33 n=94 → full 1.36 n=422）
        validation_status="未validated", weight_multiplier=0.5,   # 1≤lift<2 → ×0.5（<2 不 validated）
        source_script="tools/first_plate_h2_lift.py --full",
        note="S152 全量唯一弱正（>null_p95=1.117 pass_filter_edge=True 但<2）；尾盘突袭 end_of_day_sneak 近似；"
             "raw-shadow 观察，不驱动交易；caveat: T+0 o2c+5min 粒度+top15/full 一致",
    ),
    # 参照（非选股层，不参与降权）— S155 证伪：pooled 2.046 look-ahead，per-T 1.974<2 + net<1x cost-killed
    "vol_surge_ref": DimensionValidation(
        dimension_id="vol_surge_ref", label="vol_surge(参照,非选股层,T-1非盘中)",
        lift=1.974, n=43691, days_robust=42,   # per-T quintile（无 look-ahead；pooled 2.046 是全局 quintile artifact）
        validation_status="未validated", weight_multiplier=0.5,  # per-T<2→未validated；参照不参与选股降权(never applied)
        source_script="tools/kline_ta_validation.py",
        note="S155 证伪：pooled 2.046(全局quintile look-ahead)→per-T 1.974(<2未validated); "
             "net path-winrate 扣0.70%cost=0.945x 劣于随机(cost-killed,非tradeable); "
             "原'盘中维度'是mislabel(实为T-1特征); 参照不参与选股降权",
    ),
    # S153 R7/R8 选股层 breakout 精细化（闭合 breakout 家族，2026-09-05 跑出）
    "platform_breakout": DimensionValidation(
        dimension_id="platform_breakout", label="平台突破(breakout精细化)",
        lift=1.0791, n=946, days_robust=130,   # confirm 臂（D+1 high>cons_max 无 look-ahead，n=946 最稳健）
        validation_status="未validated", weight_multiplier=0.5,
        source_script="tools/platform_breakout_lift.py",
        note="S153 R7 tight0.9606劣于随机/confirm1.0791/both1.2177全<2x is_sig=False; "
             "regime_bull both1.4152 p=0.018 但 Bonferroni α_adj=0.00625 fail; "
             "walk-forward0.77-1.05; pre_register 74295b9; 闭合 breakout 家族",
    ),
    "low_absorption": DimensionValidation(
        dimension_id="low_absorption", label="低吸缩量(C3 vol_brk<1)",
        lift=1.0015, n=92308, days_robust=145,   # lift≈1.0 null（大样本）
        validation_status="未validated", weight_multiplier=0.5,
        source_script="tools/low_absorption_c3_lift.py",
        note="S153 R8 C3 vol_brk<1.0 lift≈1.0 null n=92308; regime_strong0.997<1; "
             "walk-forward0.99-1.04; pre_register 74295b9; 无 edge",
    ),
    # 板块/regime 层（2026-09-05 跑出，闭合 verdict 外推缺口——此层原未测）
    "sector_heat": DimensionValidation(
        dimension_id="sector_heat", label="板块热度→次日新涨停",
        lift=1.359, n=466, days_robust=41,   # zt≥3 臂（CI 不重叠但<2x，最高）
        validation_status="未validated", weight_multiplier=0.5,
        source_script="tools/sector_heat_validation.py",
        note="5 定义全<2x(top1 1.23/top3 1.07/top5 1.29/zt≥3 1.359 CI不重叠/zt≥5 1.28); "
             "n=41日 eastmoney_live; 情绪/regime 是 moderator 非 standalone signal; 60日后复验",
    ),
    "sector_phase": DimensionValidation(
        dimension_id="sector_phase", label="板块周期相位",
        lift=None, n=2319, days_robust=25,   # winrate-based 非 lift（非单调→无方向 edge）
        validation_status="劣于随机", weight_multiplier=0.1,
        source_script="tools/sector_phase_regression.py",
        note="winrate 0.52-0.60 非单调(启动0.563→发酵0.565→高潮0.605→退潮0.569回落); "
             "CI 重叠; label-only(B); 修饰方向单调=False; 无 edge",
    ),
}


def lift_to_multiplier(
    lift: Optional[float], n: int, ci_overlap: bool = True, robust: bool = True,
) -> tuple[str, float]:
    """R2：lift/n/CI/robust → (status, multiplier) 纯函数。

    复用 judge_lift_four_states 四态逻辑 + PASS_LIFT_FLOOR/PASS_LIFT_HARD_FLOOR 常量。
    映射：lift<1.0 robust → ('劣于随机', 0.1) / 1.0≤lift<2.0 → ('未validated', 0.5) /
    lift≥2.0 且 CI 不重叠 → ('validated', 1.0) / n<30 → ('探索性', 1.0)。
    robust=False 时即使 lift≥2 也不判 validated（标'待复验'×1.0）。
    """
    if n < 30:
        return ("探索性", 1.0)
    if lift is None:
        return ("探索性", 1.0)
    if lift < PASS_LIFT_HARD_FLOOR and robust:
        return ("劣于随机", 0.1)
    if lift >= PASS_LIFT_FLOOR and not ci_overlap and robust:
        return ("validated", 1.0)
    if PASS_LIFT_HARD_FLOOR <= lift < PASS_LIFT_FLOOR:
        return ("未validated", 0.5)
    # lift≥2 但 CI 重叠或非 robust
    return ("待复验", 1.0)


def _apply_evaluation_layer(
    cards: list, genes: dict, activity: dict, eff, date: str,
) -> tuple[list, dict]:
    """R5：在 funnel.py:466（card 构建循环后、return FunnelResult 前）注入评价层。

    三步：
    (1) 即时处理：turnover robust<1 → score_weight×0.1 + status='demoted'（踢出排序留审计）；
        gene_score 存在 → ×0.1 + status='unranked'（保留采数不参与排序）
    (2) 降权梯度：每卡按命中维度查 DIMENSION_LIFT_REGISTRY + lift_to_multiplier 映射
    (3) 诚实标注：构建 evaluation_summary 挂 FunnelResult

    返 (mutated_cards, evaluation_summary)。函数签名遵循 _filter_tradability 范式，
    复用 attach_first_board_analysis post-hoc card-mutation 模式（不改 build_diagnosis_card 参数）。
    """
    turnover_dim = DIMENSION_LIFT_REGISTRY.get("turnover")
    gene_dim = DIMENSION_LIFT_REGISTRY.get("gene_score")

    for card in cards:
        code = getattr(card, "code", None) or ""
        # (1) 即时处理
        demoted_dims: list[str] = []
        score_weight = 1.0
        # turnover：activity[code].turnover_pct 存在 + turnover 维度 robust<1 → ×0.1 demoted
        act = activity.get(code, {}) if isinstance(activity, dict) else {}
        turnover_pct = act.get("turnover_pct") if isinstance(act, dict) else None
        if turnover_pct is not None and turnover_dim and turnover_dim.lift is not None \
                and turnover_dim.lift < PASS_LIFT_HARD_FLOOR and turnover_dim.days_robust >= 30:
            score_weight *= turnover_dim.weight_multiplier  # ×0.1
            demoted_dims.append("turnover")

        # gene_score：card.gene_score 存在 + gene 维度 rho≈0 → ×0.1 unranked
        gene_score = getattr(card, "gene_score", None)
        if gene_score is not None and gene_dim and gene_dim.validation_status == "劣于随机":
            score_weight *= gene_dim.weight_multiplier  # ×0.1
            demoted_dims.append("gene_score")

        # (2) 降权梯度（breakout 等其他维度按 lift_to_multiplier 映射，此处只标 turnover/gene
        #     即时处理，其他维度降权在 compute_strategy_score 注入 multiplier）
        status = "demoted" if "turnover" in demoted_dims else (
            "unranked" if "gene_score" in demoted_dims else "normal")
        honest_label = "选股层无validated维度,edge待盘中验证"

        # 注入 card.evaluation（R4 models.py 加 Optional[dict] 字段）
        try:
            card.evaluation = {
                "score_weight": round(score_weight, 2),
                "lift_status": status,
                "demoted_dims": demoted_dims,
                "honest_label": honest_label,
                "validation_note": f"frozen_commit={FROZEN_COMMIT}",
            }
        except (AttributeError, TypeError):
            # DiagnosisCard 未加 evaluation 字段（R4 未实现）→ 跳过，不阻断
            pass

    # (3) 诚实标注：evaluation_summary
    evaluation_summary = {
        "honest_label": "选股层无validated维度,edge待盘中验证",
        "dimensions": [
            {
                "dimension_id": d.dimension_id, "label": d.label,
                "lift": d.lift, "n": d.n, "status": d.validation_status,
                "weight_multiplier": d.weight_multiplier, "note": d.note,
            }
            for d in DIMENSION_LIFT_REGISTRY.values() if not d.dimension_id.endswith("_ref")
        ],
        "pending_dims": [d.dimension_id for d in DIMENSION_LIFT_REGISTRY.values()
                         if d.validation_status == "探索性"],
        "frozen_commit": FROZEN_COMMIT,
    }
    return cards, evaluation_summary
