# -*- coding: utf-8 -*-
"""S204 T11+T12: escalation_engine——指标成熟→candidate→watching 自动晋级 + decay。

决策#11：只 candidate→watching 自动晋级（观察级非交易级），watching 以上人工
（A 股 T+1 容错率低，auto-fire holding=自动买入不可当日卖）。

**maturity 量化**（§8 HIGH，社区阈值标探索性须 sweep）：
tracking_age≥3 AND gene_improvement≥20% AND sector_rank≤5 → promote。

**T12 decay**（R5/R6 对抗审修正）：promoted track（workflow_state watching）5 日无指标改善 →
WATCHING→FILTERED reason='decayed'（非→CANDIDATE 防振荡 loop），tracking_pool label='decayed'。
tracking_pool.current_status 是 tracking 级 label，NOT workflow_state enum（词表分离）。

**R7 两池同步**：escalation run date T 查 tracking_pool 活跃 track → 对每 track 用 (code,T)
查 workflow_state；无行 → ensure_candidate 再 transition（pre-涨停候选不在 workflow_state）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import tracking_pool_repo as tracking_repo_mod
import workflow_state_repo as workflow_repo_mod


@dataclass(frozen=True)
class MaturityCriteria:
    """maturity 量化（探索性阈值，社区未验证，须 sensitivity sweep S204 R13）。"""

    min_tracking_age: int = 3
    min_gene_improvement_pct: float = 20.0  # vs admit-day
    max_sector_rank: int = 5
    decay_grace_days: int = 5  # watching 后 N 日无改善 → decayed


def _latest_indicator(snapshots: list, key: str) -> Optional[float]:
    """从 snapshots（按 date asc）取最近一个含 key 的指标值。"""
    for s in reversed(snapshots):
        try:
            ind = json.loads(s.indicators_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if key in ind and ind[key] is not None:
            try:
                return float(ind[key])
            except (TypeError, ValueError):
                continue
    return None


def _gene_improvement(snapshots: list, admit_gene: Optional[float]) -> float:
    """gene_score 改善 % vs admit-day。无 admit_gene 或无 latest → 0。"""
    if not admit_gene:
        return 0.0
    latest = _latest_indicator(snapshots, "gene_score")
    if latest is None or admit_gene == 0:
        return 0.0
    return (latest - admit_gene) / admit_gene * 100


def _latest_sector_rank(snapshots: list) -> int:
    """最近 sector_rank（无 → 999 不命中 max_sector_rank）。"""
    sr = _latest_indicator(snapshots, "sector_rank")
    return int(sr) if sr is not None else 999


def should_promote(track, snapshots: list) -> bool:
    """maturity 评估（全标探索性，社区阈值未验证）。

    tracking_age≥3 AND gene_improvement≥20% AND sector_rank≤5。
    """
    mc = MaturityCriteria()
    age_ok = track.tracking_age_days >= mc.min_tracking_age
    admit_ind = _safe_json(track.admit_indicators_json)
    admit_gene = admit_ind.get("gene_score")
    gene_ok = _gene_improvement(snapshots, admit_gene) >= mc.min_gene_improvement_pct
    rank_ok = _latest_sector_rank(snapshots) <= mc.max_sector_rank
    return age_ok and gene_ok and rank_ok


def _should_decay(track, snapshots: list) -> bool:
    """decay 评估：watching 后 decay_grace_days 内无 gene 改善 → decayed。

    gene 改善<0（下降）或 tracking_age≥grace 且无改善 → decay。
    """
    mc = MaturityCriteria()
    if track.tracking_age_days < mc.decay_grace_days:
        return False
    admit_ind = _safe_json(track.admit_indicators_json)
    admit_gene = admit_ind.get("gene_score")
    improvement = _gene_improvement(snapshots, admit_gene)
    return improvement < 0  # gene 下降 → decay（5 日无改善 + gene 跌）


def _safe_json(s: str) -> dict:
    try:
        return json.loads(s) if s else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def escalate(
    run_date: str,
    tracking_repo: Any = tracking_repo_mod,
    workflow_repo: Any = workflow_repo_mod,
) -> list[str]:
    """escalation 主入口：promote 'tracking' tracks + decay 'promoted' tracks。

    Args:
        run_date: escalation run 日期（盘后 T 日收盘数据）。
        tracking_repo: tracking_pool_repo（默认真实模块，test 传 fake）。
        workflow_repo: workflow_state_repo（默认真实模块，test 传 fake）。

    Returns:
        promoted code 列表（decayed 不在列表）。

    决策#11：只 candidate→watching 自动，watching 以上人工（不 transition monitoring/holding）。
    T12：promoted track 5 日无改善 → decayed（WATCHING→FILTERED 非→CANDIDATE 防振荡）。
    R7：pre-涨停候选不在 workflow_state → ensure_candidate 联动。
    """
    promoted: list[str] = []

    # 1. 'tracking' tracks → evaluate promote（candidate→watching）
    for t in tracking_repo.get_active_tracks("tracking"):
        snaps = tracking_repo.get_snapshots_for(t.code, up_to_date=run_date)
        # R7 两池同步：若 workflow_state 无 (code, run_date) → ensure_candidate 再 transition
        if not workflow_repo.get_state(t.code, run_date):
            workflow_repo.ensure_candidate(t.code, t.code, run_date, reason="escalation from first_admit")
        if should_promote(t, snaps):
            workflow_repo.transition(t.code, run_date, "watching", reason="maturity_promote")
            tracking_repo.update_tracking_status(t.code, t.first_admit_date, "promoted")
            promoted.append(t.code)

    # 2. 'promoted' tracks（workflow_state watching）→ evaluate decay（T12）
    for t in tracking_repo.get_active_tracks("promoted"):
        snaps = tracking_repo.get_snapshots_for(t.code, up_to_date=run_date)
        if _should_decay(t, snaps):
            # T12 decay: WATCHING→FILTERED reason='decayed'（非→CANDIDATE 防振荡 loop）
            workflow_repo.transition(t.code, run_date, "filtered", reason="decayed")
            tracking_repo.update_tracking_status(t.code, t.first_admit_date, "decayed", tracking_age_days=t.tracking_age_days)

    return promoted
