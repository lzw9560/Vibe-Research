"""W-C 盯盘教练（S064）。

盘中高价值时刻表 + 候选条件状态清单 + attention_mode 读写。

- 时刻表 10 槽位纯静态（零外部调用，可单测）
- 条件清单读 workflow_state / funnel 缓存 / seal 快照（不触发采集）
- attention_mode 持久化 coach_config.json（跨日重置 A）

合规：教学点讲机制不讲动作（§12.4）；缺数据 missing 不臆造；无新 em_get。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from limitup_strategy import STRATEGY_REGISTRY
from limitup_screener import BEIJING_TZ
from vr_paths import is_trading_day

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
_COACH_CONFIG_PATH = _DATA_DIR / "coach_config.json"


# ---------------------------------------------------------------------------
# 1. 时刻表（纯静态，来自 workflow doc §12.2 时刻表种子）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimetableSlot:
    slot_id: str
    label: str
    start: str  # "HH:MM"
    end: str
    watch: str
    judge: str
    teaching: str
    mode_note: dict[str, str] = field(default_factory=dict)


TIMETABLE: list[TimetableSlot] = [
    TimetableSlot(
        slot_id="fake_auction",
        label="假竞价",
        start="09:15",
        end="09:20",
        watch="只看不动",
        judge="挂单可撤，大单常是诱饵",
        teaching="别被虚假高开骗——9:20 前挂单可撤，主力常挂大单试探",
        mode_note={
            "A": "观看竞价变化，记录异常大单",
            "B": "静默累积，不推送",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="real_auction",
        label="真竞价",
        start="09:20",
        end="09:25",
        watch="竞价价/量/未撤单",
        judge="9:20 后不可撤才是真金白银",
        teaching="竞价的钱最诚实——9:20 后不可撤单，量价反映真实意图",
        mode_note={
            "A": "逐只对照候选清单的竞价量比与高开幅度",
            "B": "静默累积，9:25 汇总推送",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="auction_confirm",
        label="竞价确认",
        start="09:25",
        end="09:30",
        watch="候选清单逐只对照战法入场区间",
        judge="高开/竞价量达标才算条件成立，超区间划掉",
        teaching="全天第一个决策点——竞价确认是日内唯一不可撤的竞价信号",
        mode_note={
            "A": "逐只核对入场条件，条件不成立坚决划掉",
            "B": "推送最终可执行清单 + 预埋单建议",
            "C": "禁开新仓（信号标'今日未确认、收盘过期'）",
        },
    ),
    TimetableSlot(
        slot_id="seal_main",
        label="封板主战场",
        start="09:30",
        end="10:00",
        watch="首封时间/封单额/炸板数",
        judge="封板强度≥阈值→战法条件点亮；炸板→等回封",
        teaching="9:40 前首封=强——早盘首封时间越早，封板质量越高",
        mode_note={
            "A": "实时盯首封时间与封单额变化",
            "B": "盘中信号静默累积在页面",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="divergence",
        label="分歧窗口",
        start="10:00",
        end="10:30",
        watch="龙头扛住否、跟风掉队否",
        judge="分歧不等于退潮，分歧期不加仓",
        teaching="看龙头不看杂毛——分歧期龙头扛住是强势信号，跟风掉队正常",
        mode_note={
            "A": "重点观察龙头股是否扛住分歧",
            "B": "盘中信号静默累积在页面",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="reseal_window",
        label="回封窗口",
        start="14:00",
        end="14:30",
        watch="炸板股回封否",
        judge="回封+强度≥0.6→炸板回封战法点亮",
        teaching="回封=共识修复——午后回封说明分歧后重新达成共识",
        mode_note={
            "A": "监控炸板股是否回封及回封强度",
            "B": "盘中信号静默累积在页面",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="stop_loss",
        label="止损执行窗",
        start="14:30",
        end="14:50",
        watch="持仓 vs 战法止损线",
        judge="破线未收回→按纪律执行",
        teaching="T+1 不执行=明日裸奔——止损是唯一不可妥协的纪律",
        mode_note={
            "A": "逐只核对持仓止损线，破线执行",
            "B": "推送止损窗口提醒",
            "C": "止损前置为条件单清单（盘前已推）",
        },
    ),
    TimetableSlot(
        slot_id="tail_session",
        label="尾盘",
        start="14:50",
        end="15:00",
        watch="急拉股辨别",
        judge="偷袭（弱）vs 共识（强）",
        teaching="偷袭板次日大概率挨打——尾盘急拉无量配合多为偷袭",
        mode_note={
            "A": "辨别尾盘急拉的性质",
            "B": "盘中信号静默累积在页面",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="lunch_break",
        label="垃圾时间",
        start="11:00",
        end="13:30",
        watch="原则上不新开仓",
        judge="午间量能低、假信号率高",
        teaching="管住手主战场——午间量能低、假信号率高，不新仓是纪律",
        mode_note={
            "A": "原则上不新开仓，只盯持仓",
            "B": "盘中信号静默累积在页面",
            "C": "缺席，不操作",
        },
    ),
    TimetableSlot(
        slot_id="post_review",
        label="复盘三问",
        start="15:00",
        end="22:00",
        watch="推了什么/中了多少/为什么漏了",
        judge="填结算票根",
        teaching="复盘产出迭代数据——每日复盘是胜率提升的反馈循环",
        mode_note={
            "A": "完整复盘三问 + 填结算票根",
            "B": "收盘后一次性复盘推送",
            "C": "收盘后一次性复盘推送",
        },
    ),
]


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def get_current_slot(now: datetime) -> tuple[TimetableSlot | None, str]:
    """返回 (当前槽位或下一槽位或 None, status)。

    status: "active"=在槽位内 / "gap"=槽位间隙，返回下一槽位 /
            "before_open"=9:15前 / "after_close"=22:后 / "weekend"=周末
    """
    if now.weekday() >= 5:
        return (None, "weekend")
    cur = now.hour * 60 + now.minute
    open_min = _to_minutes("09:15")
    close_min = _to_minutes("22:00")
    if cur < open_min:
        return (None, "before_open")
    if cur >= close_min:
        return (None, "after_close")

    active_slots = [s for s in TIMETABLE if s.slot_id != "lunch_break"]
    for s in active_slots:
        s_start = _to_minutes(s.start)
        s_end = _to_minutes(s.end)
        if s_start <= cur < s_end:
            return (s, "active")

    lunch = TIMETABLE[8]
    l_start = _to_minutes(lunch.start)
    l_end = _to_minutes(lunch.end)
    if l_start <= cur < l_end:
        return (lunch, "active")

    future = [s for s in TIMETABLE if _to_minutes(s.start) > cur]
    if future:
        return (future[0], "gap")
    return (None, "after_close")


# ---------------------------------------------------------------------------
# 2. attention_mode 读写
# ---------------------------------------------------------------------------

def get_attention_mode(date: str) -> str:
    """读当日 attention_mode；跨日或缺失返 'A'（默认全程盯盘）。"""
    try:
        if not _COACH_CONFIG_PATH.exists():
            return "A"
        data = json.loads(_COACH_CONFIG_PATH.read_text(encoding="utf-8"))
        if data.get("date") != date:
            return "A"
        return data.get("attention_mode", "A") or "A"
    except Exception as exc:
        logger.warning("[coach] 读 attention_mode 异常: %s", exc)
        return "A"


def set_attention_mode(date: str, mode: str) -> str:
    """写当日 attention_mode；mode 必须是 A/B/C。返回写入值。"""
    if mode not in ("A", "B", "C"):
        raise ValueError(f"attention_mode 必须是 A/B/C，收到 {mode!r}")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"date": date, "attention_mode": mode}
    _COACH_CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return mode


# ---------------------------------------------------------------------------
# 3. 降级模式规则文本（§12.2 D8d）
# ---------------------------------------------------------------------------

MODE_RULES: dict[str, dict[str, Any]] = {
    "A": {
        "label": "全程盯盘（默认）",
        "desc": "完整时刻表推送",
    },
    "B": {
        "label": "关键节点（约10分钟/天）",
        "desc": "只推两次：9:20 最终可执行清单+预埋单建议；14:25 止损窗口提醒；盘中信号静默累积在页面",
    },
    "C": {
        "label": "完全缺席",
        "desc": "四条铁律：① 禁开新仓（信号标'今日未确认、收盘过期'，宁可错过）"
        " ② 止损前置为条件单清单（盘前 9:15 前推：代码/止损价/数量/原因，用户在券商 App 挂单）"
        " ③ 触及 max_hold_days 的持仓置顶提醒，未操作则次日开盘前再推"
        " ④ 收盘后一次性复盘推送",
    },
}


# ---------------------------------------------------------------------------
# 4. 候选条件状态清单
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = ("watching", "monitoring", "holding")


def _strategy_meta(strategy_name: str | None) -> Any:
    """从 STRATEGY_REGISTRY 查战法元数据（max_hold_days/stop_loss_pct 等）。

    返回 StrategyConfig（dict-compat：.get 可用）或 {}；调用方一律 .get() 取字段。
    """
    if not strategy_name:
        return {}
    for s in STRATEGY_REGISTRY:
        if s.get("code") == strategy_name or s.get("name") == strategy_name:
            return s
    return {}


def _build_funnel_index(date: str) -> dict[str, dict[str, Any]]:
    """从 funnel 缓存读 R2 passed（matched_triggers 数据源）。

    S148 审计修复：原读 R3 layer，但 S148(b) 删了 R3 层（漏斗重构 R2=tradability 替代
    原 R2/R3）→ filter 恒 skip → 恒返 {} → coach checklist 静默丢全部 trigger 标签
    （竞价异动/公告催化/概念联动），即使 funnel 采集了 auction/catalyst。改读 R2
    （R2 passed 现 backfill matched_triggers/auction_open_pct/catalyst_summary，见 funnel.py）。
    缓存未预热时返空 dict（不触发采集，不臆造）。
    """
    try:
        from candidate_funnel.funnel import _FUNNEL_CACHE  # noqa: PLC0415
    except Exception:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for key, (_ts, result) in _FUNNEL_CACHE.items():
        if not key.startswith(f"{date}|"):
            continue
        for layer in result.layers:
            if layer.layer_id != "R2":
                continue
            for p in layer.passed:
                code = p.get("code")
                if code:
                    index[code] = p
    return index


def _build_bomb_index(date: str) -> dict[str, dict[str, Any]]:
    """从 seal 快照 + check_all_rules 组装炸板状态（缺数据 missing 不臆造）。"""
    try:
        from risk.seal_intraday_collector import get_latest_snapshots  # noqa: PLC0415
        from risk.bomb_alert_rules import check_all_rules  # noqa: PLC0415
    except Exception:
        return {}
    try:
        snapshots = get_latest_snapshots(date)
    except Exception as exc:
        logger.warning("[coach] 读 seal 快照异常: %s", exc)
        return {}
    by_code: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        code = snap.get("code")
        if not code:
            continue
        seal_amount = snap.get("seal_amount")
        by_code[code] = {
            "seal_amount": seal_amount,
            "data_status": "ok" if seal_amount is not None else "missing",
        }
    for code, snap_list in _group_snapshots_by_code(snapshots).items():
        try:
            checks = check_all_rules(snap_list, code, "", now=datetime.now())
            triggered = [c for c in checks if c.triggered]
            by_code.setdefault(code, {})
            by_code[code]["bomb_alerts"] = [
                {"rule_id": t.rule_id, "reason": t.reason} for t in triggered
            ]
            by_code[code]["data_status"] = (
                "missing" if any(c.data_status == "missing" for c in checks) else "ok"
            )
        except Exception as exc:
            logger.warning("[coach] check_all_rules %s 异常: %s", code, exc)
            by_code.setdefault(code, {})["bomb_alerts"] = []
    return by_code


def _group_snapshots_by_code(
    snapshots: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for s in snapshots:
        code = s.get("code")
        if code:
            grouped.setdefault(code, []).append(s)
    return grouped


def _compute_max_hold_warning(
    state: dict[str, Any], strategy_meta: dict[str, Any]
) -> str | None:
    """持仓天数 vs max_hold_days 警告。无持仓/无策略/缺数据返 None。"""
    if state.get("status") != "holding":
        return None
    max_hold = strategy_meta.get("max_hold_days")
    if not max_hold:
        return None
    entry_date = state.get("entry_date") or state.get("trade_date")
    if not entry_date:
        return None
    try:
        from datetime import date as date_cls  # noqa: PLC0415
        y, m, d = (int(x) for x in entry_date.split("-"))
        held = (date_cls.today() - date_cls(y, m, d)).days
    except Exception:
        return None
    if held >= max_hold:
        return f"持仓 {held} 日已达 max_hold_days={max_hold}，须处置"
    if held >= max_hold - 1:
        return f"持仓 {held} 日，临近 max_hold_days={max_hold}"
    return None


def build_condition_checklist(date: str) -> list[dict[str, Any]]:
    """逐只组装候选/持仓条件状态清单。

    数据源：workflow_state（watching/monitoring/holding）+ funnel 缓存 R3 passed
    + seal 快照/bomb_alert_rules。缺数据 missing 不臆造。
    """
    try:
        import workflow_state_repo as repo  # noqa: PLC0415
    except Exception:
        return []
    try:
        states = repo.list_states(date)
    except Exception as exc:
        logger.warning("[coach] list_states 异常: %s", exc)
        return []
    if not states:
        return []

    funnel_idx = _build_funnel_index(date)
    bomb_idx = _build_bomb_index(date)
    checklist: list[dict[str, Any]] = []
    for st in states:
        if st.get("status") not in _ACTIVE_STATUSES:
            continue
        code = st.get("code")
        if not code:
            continue
        strategy = st.get("strategy")
        smeta = _strategy_meta(strategy)
        funnel_p = funnel_idx.get(code, {})
        bomb = bomb_idx.get(code, {})
        checklist.append({
            "code": code,
            "name": st.get("name", ""),
            "status": st.get("status"),
            "strategy": strategy,
            "strategy_name": smeta.get("name", strategy or ""),
            "entry_condition": smeta.get("entry_condition", ""),
            "stop_loss_condition": smeta.get("stop_loss_condition", ""),
            "matched_triggers": funnel_p.get("matched_triggers", []),
            "seal_amount": bomb.get("seal_amount"),
            "bomb_alerts": bomb.get("bomb_alerts", []),
            "data_status": bomb.get("data_status", "missing"),
            "max_hold_warning": _compute_max_hold_warning(st, smeta),
            "attention_mode": st.get("attention_mode") or "A",
        })
    return checklist


# ---------------------------------------------------------------------------
# 5. 教练状态顶层组装
# ---------------------------------------------------------------------------

def build_coach_state(date: str, now: datetime | None = None) -> dict[str, Any]:
    """顶层组装：current_slot + attention_mode + checklist + mode_rules。"""
    now = now or datetime.now(BEIJING_TZ)
    slot, slot_status = get_current_slot(now)
    mode = get_attention_mode(date)
    return {
        "date": date,
        "current_time": now.strftime("%H:%M"),
        "current_slot": slot.__dict__ if slot else None,
        "slot_status": slot_status,
        "attention_mode": mode,
        "mode_rules": MODE_RULES.get(mode, MODE_RULES["A"]),
        "checklist": build_condition_checklist(date),
        "is_trading_day": is_trading_day(now.date()),
    }
