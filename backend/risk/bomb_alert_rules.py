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

# S093 新增规则阈值
C7_LIMIT_UP_GAIN_THRESHOLD = 9.8  # 涨幅≥9.8% 视为涨停（INFO 级）
C8_ZT_COUNT_MIN = 5  # 涨停数<5 触发情绪恶化（MEDIUM 级）
C9_MAX_BOARDS_THRESHOLD = 3  # 最高板>3 触发连板断裂检查（MEDIUM 级）

# 操作建议映射（飞书卡片附带，历史统计特征标注"参考值，非执行指令"）
RULE_RECOMMENDATIONS: dict[str, str] = {
    "C1": "建议关注",
    "C2": "建议关注",
    "C3": "建议减仓",
    "C4": "建议观望",
    "C5": "建议止损",
    "C6": "建议关注",
    "C7": "建议关注",
    "C8": "建议谨慎",
    "C9": "建议回避高位",
}

# 飞书卡片风险提醒（弱合规：历史统计特征标注）
RISK_DISCLAIMER = "历史统计特征，市场有风险，研究参考"


@dataclass
class BombAlertRuleV2:
    """炸板预警规则（V2 时序驱动）。"""
    rule_id: str  # C1-C9（C1-C6 既有 + C7-C9 S093 新增）
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
            curr_seal, prev_seal - curr_seal,
            recommendation=RULE_RECOMMENDATIONS["C1"], now=now,
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
            curr_seal, prev_seal - curr_seal,
            recommendation=RULE_RECOMMENDATIONS["C2"], now=now,
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
        latest.get("seal_amount"), 0.0,
        recommendation=RULE_RECOMMENDATIONS["C3"], now=now,
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
            latest.get("seal_amount"), 0.0,
            recommendation=RULE_RECOMMENDATIONS["C4"], now=now,
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
            latest.get("seal_amount"), 0.0,
            recommendation=RULE_RECOMMENDATIONS["C5"], now=now,
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
            seal, 0.0,
            recommendation=RULE_RECOMMENDATIONS["C6"], now=now,
        )
        return RuleCheckResult("C6", True, alert=alert, reason=f"封单市值比 {ratio:.3%}")
    return RuleCheckResult("C6", False, reason=f"封单市值比 {ratio:.3%}（未触发）")


def check_c7_forward_limit_up(
    snapshots: list[dict[str, Any]], code: str, name: str,
    forward_candidates: set[str] | None = None,
    zt_pool_codes: set[str] | None = None,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C7：前瞻标的涨停 → INFO。

    触发条件：code 在前瞻 final_candidates 集合 + 实时涨停
    （zt_pool 含该 code 或快照涨幅≥9.8%）。
    数据来源复用 C3 的 zt_pool 口径（涨停池集合），涨幅降级读快照 gain 字段。
    zt_pool 未传入（None）且快照无涨幅字段 → missing（不臆造）。
    """
    now = now or datetime.now()
    fwd = forward_candidates or set()
    if code not in fwd:
        return RuleCheckResult("C7", False, reason="不在前瞻候选集合")

    zt_pool_provided = zt_pool_codes is not None
    zt_pool = zt_pool_codes or set()
    is_limit_up = code in zt_pool

    # 降级：zt_pool 未取得时，从快照涨幅字段判断
    if not is_limit_up and snapshots:
        latest = snapshots[-1]
        for field in ("gain_pct", "pct_chg", "change_pct", "gain"):
            gain = latest.get(field)
            if gain is not None and gain >= C7_LIMIT_UP_GAIN_THRESHOLD:
                is_limit_up = True
                break

    if is_limit_up:
        alert = _build_alert(
            code, name, "C7", "info",
            f"{name}({code}) 前瞻标的涨停（C7：INFO 提示）",
            None, 0.0,
            recommendation=RULE_RECOMMENDATIONS["C7"], now=now,
        )
        return RuleCheckResult("C7", True, alert=alert, reason="前瞻标的涨停")

    # 无法判定涨停状态：zt_pool 未传入且快照无法判断
    if not zt_pool_provided:
        return RuleCheckResult("C7", False, data_status="missing",
                               reason="zt_pool 未取得且无法从快照判断涨停")

    return RuleCheckResult("C7", False, reason="未涨停")


def check_c8_sentiment_deterioration(
    market_snapshot: dict[str, Any] | None,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C8：情绪恶化 → MEDIUM。

    触发条件（天气降 1 档即触发，连降 1 档已信号显著）：
    zt_count < 5 且 zb_count > zt_count（涨停稀少 + 炸板反超）。
    字段从 intraday_sentiment 快照取（zt_count/zb_count）。
    不用 ad_ratio（ad_ratio 是连板/跌停代理非涨跌家数比，Oracle 阻断 #3）。
    极端反弹/未知状态不触发。
    """
    now = now or datetime.now()
    if not market_snapshot:
        return RuleCheckResult("C8", False, data_status="missing", reason="市场快照未取得")

    zt_count = market_snapshot.get("zt_count")
    zb_count = market_snapshot.get("zb_count")
    if zt_count is None or zb_count is None:
        return RuleCheckResult("C8", False, data_status="missing", reason="zt_count/zb_count 未取得")

    zt = float(zt_count)
    zb = float(zb_count)

    if zt < C8_ZT_COUNT_MIN and zb > zt:
        alert = _build_alert(
            "MARKET", "市场情绪", "C8", "medium",
            f"情绪恶化：涨停 {int(zt)} 只 < {C8_ZT_COUNT_MIN}，炸板 {int(zb)} 只 > 涨停"
            f"（C8：天气降档 MEDIUM 预警）",
            None, 0.0,
            recommendation=RULE_RECOMMENDATIONS["C8"], now=now,
        )
        return RuleCheckResult("C8", True, alert=alert, reason=f"zt={int(zt)} zb={int(zb)}")

    return RuleCheckResult("C8", False, reason=f"zt={int(zt)} zb={int(zb)}（未触发）")


def check_c9_ladder_break(
    market_snapshot: dict[str, Any] | None,
    now: datetime | None = None,
) -> RuleCheckResult:
    """C9：连板断裂 → MEDIUM。

    触发条件：最高板 > 3 且无 2 板接力（ladder max_boards>3 且 2 板连板数=0）。
    字段 ladder/max_boards 从快照取。
    ladder 格式：dict[int, int]（板数→连板家数）或 None。
    """
    now = now or datetime.now()
    if not market_snapshot:
        return RuleCheckResult("C9", False, data_status="missing", reason="市场快照未取得")

    max_boards = market_snapshot.get("max_boards")
    ladder = market_snapshot.get("ladder")
    if max_boards is None or ladder is None:
        return RuleCheckResult("C9", False, data_status="missing", reason="max_boards/ladder 未取得")

    max_b = float(max_boards)
    if max_b <= C9_MAX_BOARDS_THRESHOLD:
        return RuleCheckResult("C9", False, reason=f"最高板 {int(max_b)} ≤ {C9_MAX_BOARDS_THRESHOLD}（未触发）")

    # ladder 取 2 板连板家数；兼容 dict 和 list 格式
    # dict: {1: count, 2: count, ...} → ladder.get(2, 0)
    # list: [1板count, 2板count, 3板count, ...] → ladder[1]
    board2_count = 0
    if isinstance(ladder, dict):
        board2_count = int(ladder.get(2, 0) or 0)
    elif isinstance(ladder, (list, tuple)) and len(ladder) >= 2:
        board2_count = int(ladder[1] or 0)

    if board2_count == 0:
        alert = _build_alert(
            "MARKET", "连板梯队", "C9", "medium",
            f"连板断裂：最高 {int(max_b)} 板但无 2 板接力（C9：MEDIUM 预警）",
            None, 0.0,
            recommendation=RULE_RECOMMENDATIONS["C9"], now=now,
        )
        return RuleCheckResult("C9", True, alert=alert, reason=f"max_boards={int(max_b)} board2=0")

    return RuleCheckResult("C9", False, reason=f"max_boards={int(max_b)} board2={board2_count}（未触发）")


def check_all_rules(
    snapshots: list[dict[str, Any]],
    code: str,
    name: str,
    zb_pool_codes: set[str] | None = None,
    now: datetime | None = None,
    forward_candidates: set[str] | None = None,
    zt_pool_codes: set[str] | None = None,
) -> list[RuleCheckResult]:
    """对单股跑全部七条规则（C1-C7）。返回各规则结果。

    缺数据的规则返 data_status=missing，不触发、不臆造。
    C7 需 forward_candidates + zt_pool_codes（前瞻标的涨停）。
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
        check_c7_forward_limit_up(snapshots, code, name, forward_candidates, zt_pool_codes, now),
    ]


def check_market_rules(
    market_snapshot: dict[str, Any] | None,
    now: datetime | None = None,
) -> list[RuleCheckResult]:
    """对市场级快照跑 C8/C9 规则（情绪恶化 + 连板断裂）。

    缺数据的规则返 data_status=missing，不触发、不臆造。
    market_snapshot 为 intraday_sentiment 快照（含 zt_count/zb_count/ladder/max_boards）。
    """
    now = now or datetime.now()
    return [
        check_c8_sentiment_deterioration(market_snapshot, now),
        check_c9_ladder_break(market_snapshot, now),
    ]
