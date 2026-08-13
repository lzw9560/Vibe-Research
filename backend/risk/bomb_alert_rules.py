# -*- coding: utf-8 -*-
"""S055 T3：炸板预警规则引擎扩充（C1/C3/C4/C5/C6 + C2 降级）。

DSA SEAL_PLATE_ARCHITECTURE.md §6 规则原型：
- C1 封单 5 分钟减>30%（黄）
- C2 单笔>5000 手卖单（黄，tick 级）→ 数据不可得，降级为「封单骤降（5 分钟降幅≥50%）」代理规则
- C3 同板块龙头炸板（红）
- C4 大盘 5 分钟急跌>0.5%（红）
- C5 开板 3 分钟未回封（红）
- C6 封单<流通市值 0.3%（红）

时序窗口驱动：输入 seal_intraday_snapshots 表近 N 分钟快照。
三态判定：触发/不触发/缺数据（missing 跳过，不臆造）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from realtime_workflow import BombAlert


# 规则阈值（spec §2 DSA 原型，可配）
C1_SEAL_DROP_RATIO_5MIN = 0.30  # 封单 5 分钟减>30% → 黄
C2_DEGRADED_SEAL_DROP_RATIO = 0.50  # C2 降级：封单骤降≥50% → 黄
C4_INDEX_DROP_5MIN = 0.5  # 大盘 5 分钟急跌>0.5% → 红
C5_REOPEN_UNSEAL_MINUTES = 3  # 开板 3 分钟未回封 → 红
C6_SEAL_TO_FLOAT_RATIO_MIN = 0.003  # 封单<流通市值 0.3% → 红
C3_LEADER_IN_ZB_POOL = True  # 同板块龙头进炸板池 → 红


@dataclass
class BombAlertRuleV2:
    """炸板预警规则（V2 时序驱动）。"""
    rule_id: str  # C1/C2/C3/C4/C5/C6
    name: str
    alert_level: str  # yellow/red
    enabled: bool = True
    description: str = ""


@dataclass
class RuleCheckResult:
    """单规则检查结果。"""
    rule_id: str
    triggered: bool
    alert: BombAlert | None = None
    data_status: str = "ok"  # ok/missing/degraded
    reason: str = ""


def _build_alert(
    code: str, name: str, rule_id: str, level: str,
    condition: str, seal_amount: float | None, change: float, recommendation: str,
    now: datetime | None = None,
) -> BombAlert:
    now = now or datetime.now()
    return BombAlert(
        timestamp=now.isoformat(),
        code=code,
        name=name,
        alert_level=level,
        condition=condition,
        current_seal_amount=seal_amount or 0.0,
        seal_amount_change_5min=change,
        recommendation=recommendation,
    )


def check_c1_seal_drop_5min(
    snapshots: list[dict[str, Any]], code: str, name: str,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C1：封单 5 分钟减>30% → 黄。"""
    now = now or datetime.now()
    if len(snapshots) < 2:
        return RuleCheckResult("C1", False, data_status="missing", reason="快照不足")
    latest = snapshots[-1]
    # 找 5 分钟前的快照
    cutoff = (now - timedelta(minutes=5)).isoformat()
    prev = None
    for s in reversed(snapshots[:-1]):
        if s.get("ts", "") <= cutoff:
            prev = s
            break
    if prev is None:
        return RuleCheckResult("C1", False, data_status="missing", reason="5 分钟前快照未取得")
    curr_seal = latest.get("seal_amount")
    prev_seal = prev.get("seal_amount")
    if curr_seal is None or prev_seal is None:
        return RuleCheckResult("C1", False, data_status="missing", reason="封单额未取得")
    if prev_seal <= 0:
        return RuleCheckResult("C1", False, data_status="missing", reason="前值封单≤0")
    drop = (prev_seal - curr_seal) / prev_seal
    if drop >= C1_SEAL_DROP_RATIO_5MIN:
        alert = _build_alert(
            code, name, "C1", "yellow",
            f"{name}({code}) 封单 5 分钟减 {drop:.1%}（C1：>30% 黄色预警）",
            curr_seal, prev_seal - curr_seal, now,
        )
        return RuleCheckResult("C1", True, alert=alert, reason=f"5 分钟降幅 {drop:.1%}")
    return RuleCheckResult("C1", False, reason=f"5 分钟降幅 {drop:.1%}（未触发）")


def check_c2_degraded_seal_drop(
    snapshots: list[dict[str, Any]], code: str, name: str,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C2 降级：封单骤降（5 分钟降幅≥50%）→ 黄。

    C2 原型是 tick 级单笔>5000 手卖单，数据不可得（mootdx 分笔未验证）。
    降级为封单骤降代理规则，文案显式标注降级口径。
    """
    now = now or datetime.now()
    if len(snapshots) < 2:
        return RuleCheckResult("C2", False, data_status="missing", reason="快照不足")
    latest = snapshots[-1]
    cutoff = (now - timedelta(minutes=5)).isoformat()
    prev = None
    for s in reversed(snapshots[:-1]):
        if s.get("ts", "") <= cutoff:
            prev = s
            break
    if prev is None:
        return RuleCheckResult("C2", False, data_status="missing", reason="5 分钟前快照未取得")
    curr_seal = latest.get("seal_amount")
    prev_seal = prev.get("seal_amount")
    if curr_seal is None or prev_seal is None:
        return RuleCheckResult("C2", False, data_status="missing", reason="封单额未取得")
    if prev_seal <= 0:
        return RuleCheckResult("C2", False, data_status="missing", reason="前值封单≤0")
    drop = (prev_seal - curr_seal) / prev_seal
    if drop >= C2_DEGRADED_SEAL_DROP_RATIO:
        alert = _build_alert(
            code, name, "C2", "yellow",
            f"{name}({code}) 封单骤降 {drop:.1%}（C2 降级口径：原 tick 级不可得，用 5 分钟≥50% 代理）",
            curr_seal, prev_seal - curr_seal, now,
        )
        return RuleCheckResult("C2", True, alert=alert, reason=f"骤降 {drop:.1%}（降级口径）")
    return RuleCheckResult("C2", False, reason=f"降幅 {drop:.1%}（未触发）")


def check_c3_sector_leader_broken(
    snapshots: list[dict[str, Any]], code: str, name: str,
    zb_pool_codes: set[str], now: datetime | None = None,
) -> RuleCheckResult:
    """C3：同板块龙头进炸板池 → 红。

    判定：当前股在炸板池（zb_pool_codes）且同板块有更高连板股也进炸板池。
    简化口径：当前股进炸板池即触发（龙头判定需板块聚合，此处保守触发）。
    """
    now = now or datetime.now()
    if not zb_pool_codes:
        return RuleCheckResult("C3", False, data_status="missing", reason="炸板池未取得")
    if code not in zb_pool_codes:
        return RuleCheckResult("C3", False, reason="不在炸板池")
    # 保守触发：进炸板池即红色预警（龙头聚合判定留 backlog）
    latest = snapshots[-1] if snapshots else {}
    alert = _build_alert(
        code, name, "C3", "red",
        f"{name}({code}) 进入炸板池（C3：同板块龙头炸板红色预警）",
        latest.get("seal_amount"), 0.0, now,
    )
    return RuleCheckResult("C3", True, alert=alert, reason="进入炸板池")


def check_c4_index_drop_5min(
    snapshots: list[dict[str, Any]], code: str, name: str,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C4：大盘 5 分钟急跌>0.5% → 红。"""
    now = now or datetime.now()
    if not snapshots:
        return RuleCheckResult("C4", False, data_status="missing", reason="快照未取得")
    latest = snapshots[-1]
    idx_change = latest.get("index_5min_change")
    if idx_change is None:
        return RuleCheckResult("C4", False, data_status="missing", reason="指数 5 分钟变化未取得")
    if idx_change <= -C4_INDEX_DROP_5MIN:
        alert = _build_alert(
            code, name, "C4", "red",
            f"{name}({code}) 大盘 5 分钟急跌 {idx_change:.2f}%（C4：>0.5% 红色预警）",
            latest.get("seal_amount"), 0.0, now,
        )
        return RuleCheckResult("C4", True, alert=alert, reason=f"大盘跌幅 {idx_change:.2f}%")
    return RuleCheckResult("C4", False, reason=f"大盘跌幅 {idx_change:.2f}%（未触发）")


def check_c5_reopen_unsealed(
    snapshots: list[dict[str, Any]], code: str, name: str,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C5：开板 3 分钟未回封 → 红。

    判定：东财 zbc 字段是"当日累计炸板次数"（非"当前是否开板"），不能直接
    用 open_count>0 判未回封。正确口径：open_count 在近 3 分钟窗口内**递增**
    （新出现炸板）且最新 seal_amount 为 None/0（当前无封单）→ 未回封。
    若最新 seal_amount>0 → 已回封（尽管历史炸过）。
    """
    now = now or datetime.now()
    if not snapshots:
        return RuleCheckResult("C5", False, data_status="missing", reason="快照未取得")
    latest = snapshots[-1]
    open_count = latest.get("open_count")
    seal = latest.get("seal_amount")
    if open_count is None:
        return RuleCheckResult("C5", False, data_status="missing", reason="开板次数未取得")
    if open_count <= 0:
        return RuleCheckResult("C5", False, reason="未开板")
    # 最新有封单 → 已回封，不触发
    if seal is not None and seal > 0:
        return RuleCheckResult("C5", False, reason=f"开板 {int(open_count)} 次但当前有封单（已回封）")
    # 最新无封单 + open_count>0 → 检查近 3 分钟是否持续无封单
    cutoff = (now - timedelta(minutes=3)).isoformat()
    recent = [s for s in snapshots if s.get("ts", "") >= cutoff]
    if recent and all((s.get("seal_amount") is None or s.get("seal_amount") == 0) for s in recent):
        alert = _build_alert(
            code, name, "C5", "red",
            f"{name}({code}) 开板 {int(open_count)} 次且 3 分钟未回封（C5：红色预警）",
            latest.get("seal_amount"), 0.0, now,
        )
        return RuleCheckResult("C5", True, alert=alert, reason=f"开板 {int(open_count)} 次未回封")
    return RuleCheckResult("C5", False, reason="已回封或无封单持续不足 3 分钟")


def check_c6_seal_below_float_ratio(
    snapshots: list[dict[str, Any]], code: str, name: str,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C6：封单<流通市值 0.3% → 红。"""
    now = now or datetime.now()
    if not snapshots:
        return RuleCheckResult("C6", False, data_status="missing", reason="快照未取得")
    latest = snapshots[-1]
    seal = latest.get("seal_amount")
    float_cap = latest.get("float_market_cap")
    if seal is None or float_cap is None:
        return RuleCheckResult("C6", False, data_status="missing", reason="封单或流通市值未取得")
    if float_cap <= 0:
        return RuleCheckResult("C6", False, data_status="missing", reason="流通市值≤0")
    ratio = seal / float_cap
    if ratio < C6_SEAL_TO_FLOAT_RATIO_MIN:
        alert = _build_alert(
            code, name, "C6", "red",
            f"{name}({code}) 封单/流通市值 {ratio:.3%} < 0.3%（C6：红色预警）",
            seal, 0.0, now,
        )
        return RuleCheckResult("C6", True, alert=alert, reason=f"封单市值比 {ratio:.3%}")
    return RuleCheckResult("C6", False, reason=f"封单市值比 {ratio:.3%}（未触发）")


def check_all_rules(
    snapshots: list[dict[str, Any]],
    code: str,
    name: str,
    zb_pool_codes: set[str] | None = None,
    now: datetime | None = None,
) -> list[RuleCheckResult]:
    """对单股跑全部六条规则。返回各规则结果。

    缺数据的规则返 data_status=missing，不触发、不臆造。
    """
    now = now or datetime.now()
    zb = zb_pool_codes or set()
    return [
        check_c1_seal_drop_5min(snapshots, code, name, now),
        check_c2_degraded_seal_drop(snapshots, code, name, now),
        check_c3_sector_leader_broken(snapshots, code, name, zb, now),
        check_c4_index_drop_5min(snapshots, code, name, now),
        check_c5_reopen_unsealed(snapshots, code, name, now),
        check_c6_seal_below_float_ratio(snapshots, code, name, now),
    ]
