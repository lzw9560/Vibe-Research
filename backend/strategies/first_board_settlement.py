# -*- coding: utf-8 -*-
"""S075 Phase 4 结算 + 验证（tasks.md 053-062）——T+1 盘后盈亏归因 + forward_test 信号账。

实现范围：
- 053-056 结算归因：settle_pnl / settle_missed / calc_target_return /
                   calc_position_return / apply_transaction_cost
- 055-057 forward_test 接入：record_first_board_signals / settle_first_board_t1 /
                   get_first_board_forward_test_summary / judge_lift_four_states
- 058-062 主入口：run_first_board_settlement

**关键约束**：
1. 交易成本 0.4% 固定（TRANSACTION_COST_PCT=0.004，待回测校准）。
   spec plan.md 要求简化版成本，不复用 execution_model.compute_transaction_cost
   （后者按订单额/日成交动态算滑点，首板流未到回测阶段先用固定值）。
2. 收益排名口径：标的收益（T+1 收盘 vs T 日开盘），不含仓位/执行——
   用于比较各战法选股能力。
3. §44 未 validated 不阻断接入跑通：lift<2x 标"未 validated"但系统仍推进，
   60 日后复验定权重。
4. 复用 forward_test 表（forward_test_records），strategy_code="first_board"，
   不新建信号账表。
5. T+1 必卖：hold_days 恒=1（首板流策略 spec 要求）。

**字段对齐（经核实 first_board_filter.py:1012-1018）**：
- scored_candidates 每项含 {code, name, scores, total, rank}。
- total 是 9 维度加权总分（0-100），用作 forward_test 的 strategy_score。

**forward_test DailyRecommendation 实际类名**：@dataclass(frozen=True)，
字段：signal_date/code/name/strategy_code/strategy_score/weather_state/
position_multiplier/recommended_position（forward_test.py:106-116）。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.forward_test import (  # noqa: E402
    DailyRecommendation,
    record_daily_recommendations,
    record_actual_returns,
    get_forward_test_summary,
)

_logger = logging.getLogger(__name__)

# ===========================================================================
# 常量
# ===========================================================================

#: 0.4% 固定交易成本（佣金 0.05% + 印花 0.05% + 过户 0.002% + 滑点 0.3%）。
#: spec plan.md 简化版，**待回测校准**（30 天后用实际数据调，见 tasks.md）。
#: 不复用 execution_model.compute_transaction_cost（后者按订单额动态算滑点，
#: 首板流未到回测阶段先用固定值）。
TRANSACTION_COST_PCT: float = 0.004

#: forward_test 战法 code（strategy_code 字段值）。
STRATEGY_CODE: str = "first_board"

#: T+1 必卖，持仓天数恒=1（首板流 spec 要求）。
HOLD_DAYS: int = 1


# ===========================================================================
# 4a：结算归因（053-056）
# ===========================================================================

def calc_target_return(t_open: float, t1_close: float) -> float:
    """标的收益（排名用）——T+1 收盘 vs T 日开盘，不含仓位/执行。

    spec plan.md：收益排名只看标的收益，比较各战法选股能力。
    与 forward_test 的 return_open2close 同口径（T+1 close vs T open）。

    Args:
        t_open: T 日开盘价（建仓日开盘）。
        t1_close: T+1 收盘价（次日收盘）。

    Returns:
        收益率 %，4 位小数。输入 ≤0 返 0.0（防除零）。
    """
    if not t_open or t_open <= 0:
        return 0.0
    return round((t1_close - t_open) / t_open * 100, 4)


def calc_position_return(entry: float, exit_price: float) -> float:
    """持仓收益（执行用）——entry→exit，含仓位/止损/人工。

    spec plan.md：forward_test 用此口径。与 settle_pnl 的 return_pct 同口径
    （exit-entry/entry*100），但语义上强调"执行层"（含止损/人工干预）。

    Args:
        entry: 建仓价。
        exit_price: 卖出价（T+1 卖出）。

    Returns:
        持仓收益率 %，4 位小数。输入 ≤0 返 0.0（防除零）。
    """
    if not entry or entry <= 0:
        return 0.0
    return round((exit_price - entry) / entry * 100, 4)


def apply_transaction_cost(gross_return_pct: float) -> float:
    """扣交易成本 0.4%。

    net = gross_return_pct - 0.4

    Args:
        gross_return_pct: 毛收益率 %（持仓收益或标的收益）。

    Returns:
        净收益率 %，4 位小数。
    """
    return round(gross_return_pct - TRANSACTION_COST_PCT * 100, 4)


def settle_pnl(holding: dict, exit_price: float, entry_price: float) -> dict:
    """T+1 盘后盈亏归因。

    Args:
        holding: 建仓记录 dict，至少含 {code, total}。
                 - code: 股票代码
                 - total: 建仓时 9 维度评分（供归因，来自 first_board_filter）
            额外字段（name 等）透传到结果。
        exit_price: T+1 卖出价。
        entry_price: T 日建仓价（建仓实际成交价）。

    Returns:
        dict：
        - code: 股票代码
        - name: 股票名称（透传，默认空）
        - entry_price: 建仓价
        - exit_price: 卖出价
        - return_pct: 持仓收益 %（exit-entry/entry*100）
        - net_return_pct: 净收益 %（扣 0.4% 成本）
        - cost_pct: 交易成本 %（0.4）
        - total_score: 建仓时评分（供归因分析）
        - hold_days: 持仓天数（恒=1，T+1 必卖）
    """
    return_pct = calc_position_return(entry_price, exit_price)
    net = apply_transaction_cost(return_pct)
    return {
        "code": holding.get("code", ""),
        "name": holding.get("name", ""),
        "entry_price": round(entry_price, 4) if entry_price else 0.0,
        "exit_price": round(exit_price, 4) if exit_price else 0.0,
        "return_pct": return_pct,
        "net_return_pct": net,
        "cost_pct": TRANSACTION_COST_PCT * 100,  # 0.4
        "total_score": holding.get("total", 0.0),
        "hold_days": HOLD_DAYS,
    }


def settle_missed(
    candidates: list[dict],
    t1_open: dict,
    t1_close: dict,
) -> list[dict]:
    """漏单对账——候选池未建仓的标的记录 T+1 收益（漏单次日收益）。

    candidates 来自 first_board_filter 的 scored_candidates（全量候选，含未建仓的）。
    漏单 = candidates 中 code 不在 holdings（已建仓）的标的。
    本函数不直接拿 holdings，由调用方传入 candidates（已剔除已建仓的），
    或直接传全量 candidates——本函数对 candidates 全量算漏单收益
    （调用方负责从 candidates 中减去 holdings 的 codes 得到"漏单子集"）。

    Args:
        candidates: 候选池 list[dict]（含 code/name/total，来自 scored_candidates）。
        t1_open: {code: t1_open_price}，T+1 开盘价。
        t1_close: {code: t1_close_price}，T+1 收盘价。

    Returns:
        list[dict]，每项：
        - code: 股票代码
        - name: 股票名称
        - t1_open: T+1 开盘价
        - t1_close: T+1 收盘价
        - return_pct: T+1 收益 %（t1_close - t1_open）/t1_open*100
        - missed: True（标记漏单）
        - total_score: 建仓时评分（供归因，看漏了哪些高分票）
    """
    out: list[dict] = []
    for c in candidates:
        code = c.get("code", "")
        if not code:
            continue
        t1o = t1_open.get(code)
        t1c = t1_close.get(code)
        if t1o is None or t1c is None:
            # T+1 数据缺失，不臆造，跳过（不崩）
            continue
        if not t1o or t1o <= 0:
            continue
        ret = round((t1c - t1o) / t1o * 100, 4)
        out.append({
            "code": code,
            "name": c.get("name", ""),
            "t1_open": round(t1o, 4) if t1o else 0.0,
            "t1_close": round(t1c, 4) if t1c else 0.0,
            "return_pct": ret,
            "missed": True,
            "total_score": c.get("total", 0.0),
        })
    return out


# ===========================================================================
# 4b：forward_test 接入（055-057）
# ===========================================================================

def record_first_board_signals(
    signal_date: str,
    scored_candidates: list[dict],
    weather_state: str | None = None,
) -> int:
    """把首板流 picks 记入 forward_test_records 表。

    复用 forward_test.record_daily_recommendations。
    strategy_code="first_board"，strategy_score=total 评分（9 维度加权总分）。

    Args:
        signal_date: 信号日（推荐日，YYYYMMDD 或 YYYY-MM-DD）。
        scored_candidates: 首板评分候选 list[dict]（含 code/name/total）。
        weather_state: 当日天气状态（来自 first_board_market_env）。

    Returns:
        写入条数。
    """
    if not scored_candidates:
        return 0
    recs = [
        DailyRecommendation(
            signal_date=signal_date,
            code=c.get("code", ""),
            name=c.get("name", ""),
            strategy_code=STRATEGY_CODE,
            strategy_score=float(c.get("total", 0.0) or 0.0),
            weather_state=weather_state,
            position_multiplier=1.0,  # 首板流未接 calendar_factor，占位
            recommended_position=0.0,  # 等权 placeholder，待 Phase 5 接仓位
        )
        for c in scored_candidates
    ]
    return record_daily_recommendations(signal_date, recs)


def settle_first_board_t1(signal_date: str, t1_data: dict[str, dict]) -> int:
    """回填首板流 picks 的 T+1 收益。

    复用 forward_test.record_actual_returns。
    t1_data 的 return_open2close 就是标的收益口径（T+1 收盘 vs T 日开盘）。

    Args:
        signal_date: 信号日（推荐日，不是次日）。
        t1_data: {code: {return_open2close, return_close2close, next_pctChg}}
                 - return_open2close: 标的收益 %（T+1 close - T open）/T open*100
                 - return_close2close: 收盘到收盘 %（可选）
                 - next_pctChg: 次日涨跌幅 %（可选）

    Returns:
        更新条数。
    """
    if not t1_data:
        return 0
    return record_actual_returns(signal_date, t1_data)


def judge_lift_four_states(lift: float, n: int) -> str:
    """lift 四态判定（spec plan.md 4b）。

    §44 60 日复验窗口口径：
    - validated: lift>=2.0 AND n>=30
    - 未 validated: 1.0<=lift<2.0 AND n>=30
    - 探索性: n<30（数据不足非定论，最高优先）
    - 劣于随机: lift<1.0（硬底线，移除/权重0）

    §44 未 validated 不阻断接入跑通——标注用，非门。

    Args:
        lift: strategy / random 胜率提升倍数。
        n: 已结算样本数（settled_count）。

    Returns:
        四态之一字符串。
    """
    # n<30 探索性最高优先（数据不足非定论，即使 lift<1 也标探索性）
    if n < 30:
        return "探索性"
    if lift < 1.0:
        return "劣于随机"
    if lift >= 2.0:
        return "validated"
    # 1.0 <= lift < 2.0
    return "未 validated"


def get_first_board_forward_test_summary() -> dict:
    """首板流前向测试汇总——算 lift（标的收益口径）。

    复用 forward_test.get_forward_test_summary。
    forward_test 表为全战法共用（多 strategy_code），summary 不分战法——
    本函数取全表汇总后标注"首板流标的收益口径"。

    Returns:
        dict：
        - total_days: 交易日数
        - total_picks: 推荐总数
        - settled: 已结算数
        - win_rate: 胜率 %
        - avg_return: 平均标的收益 %
        - lift: strategy/random
        - validation_status: 四态之一
        - passed: forward_test 内部 passed（非接入阻断）
        - is_exploratory: n<30
        - note: 口径说明（§44 未 validated 不阻断）
    """
    result = get_forward_test_summary()
    status = judge_lift_four_states(result.lift, result.settled_count)
    return {
        "total_days": result.total_days,
        "total_picks": result.total_recommendations,
        "settled": result.settled_count,
        "win_rate": result.win_rate,
        "avg_return": result.avg_return,
        "lift": result.lift,
        "validation_status": status,
        "passed": result.passed,
        "is_exploratory": result.is_exploratory,
        "note": (
            "首板流标的收益口径（T+1 收盘 vs T 日开盘），"
            "§44 未 validated 不阻断接入跑通"
        ),
    }


# ===========================================================================
# 4c：主入口（058-062）
# ===========================================================================

def run_first_board_settlement(
    signal_date: str,
    holdings: list[dict],
    candidates: list[dict],
    t1_data: dict | None = None,
) -> dict:
    """Phase 4 主入口。

    Args:
        signal_date: 信号日（推荐日，YYYYMMDD 或 YYYY-MM-DD）。
        holdings: 已建仓 list[dict]，每项至少含 {code, total, entry_price}。
                  entry_price 为建仓实际成交价（T 日）。
        candidates: 全量候选 list[dict]（含漏单，来自 first_board_filter
                    的 scored_candidates，含 code/name/total）。
        t1_data: T+1 数据，可 None。结构：
                 {code: {return_open2close, return_close2close, next_pctChg,
                         t1_open, t1_close, entry_price}}
                 - return_open2close: 标的收益 %（T+1 close - T open）/T open*100
                 - t1_open / t1_close: T+1 开盘/收盘价（漏单对账用）
                 - entry_price: T 日建仓价（持仓归因用，若 holding 无则取此）
                 若 None → 持仓归因/漏单对账/forward_test 回填全部降级（空列表/0）。

    Returns:
        dict：
        - settled: list[dict]（盈亏归因，持仓）
        - missed: list[dict]（漏单对账）
        - forward_test_recorded: int（forward_test 写入条数）
        - forward_test_summary: dict（lift 汇总）
        - verdict: str（整体判定）
    """
    t1_data = t1_data or {}

    # ── 1. forward_test 写入 picks（信号日盘后，先于 T+1 回填）────────
    # 即使 t1_data=None，picks 仍写入（次日再回填收益）
    recorded = record_first_board_signals(signal_date, candidates)

    # ── 2. 持仓盈亏归因 ─────────────────────────────────────────────
    settled: list[dict] = []
    for h in holdings:
        code = h.get("code", "")
        t1 = t1_data.get(code, {}) if t1_data else {}
        # exit_price 优先取 holding.exit_price，其次 t1_data[code].t1_close
        exit_price = h.get("exit_price") or t1.get("t1_close") or 0.0
        entry_price = h.get("entry_price") or t1.get("entry_price") or 0.0
        if exit_price <= 0 or entry_price <= 0:
            # T+1 数据缺失，不臆造，跳过该持仓归因（不崩）
            continue
        settled.append(settle_pnl(h, exit_price, entry_price))

    # ── 3. 漏单对账 ────────────────────────────────────────────────
    # 漏单 = candidates 中不在 holdings codes 的
    holding_codes = {h.get("code", "") for h in holdings}
    missed_candidates = [c for c in candidates if c.get("code", "") not in holding_codes]
    t1_open_map = {}
    t1_close_map = {}
    for code, d in (t1_data or {}).items():
        if isinstance(d, dict):
            if d.get("t1_open") is not None:
                t1_open_map[code] = d["t1_open"]
            if d.get("t1_close") is not None:
                t1_close_map[code] = d["t1_close"]
    missed = settle_missed(missed_candidates, t1_open_map, t1_close_map)

    # ── 4. forward_test 回填 T+1 收益 ────────────────────────────────
    # t1_data 的 return_open2close 字段直接喂给 record_actual_returns
    t1_returns = {}
    for code, d in (t1_data or {}).items():
        if isinstance(d, dict) and d.get("return_open2close") is not None:
            t1_returns[code] = {
                "return_open2close": d.get("return_open2close"),
                "return_close2close": d.get("return_close2close"),
                "next_pctChg": d.get("next_pctChg"),
            }
    if t1_returns:
        settle_first_board_t1(signal_date, t1_returns)

    # ── 5. forward_test 汇总 + verdict ────────────────────────────────
    summary = get_first_board_forward_test_summary()
    status = summary.get("validation_status", "未 validated")
    if not settled and not missed:
        verdict = "T+1 数据缺失，归因降级（forward_test picks 已写入，待次日回填）"
    elif status == "劣于随机":
        verdict = f"§44 硬底线触发（lift={summary.get('lift', 0)}x<1.0），移除/权重0"
    elif status == "探索性":
        verdict = f"探索性（n<30，非定论）——§44 未 validated 不阻断接入跑通"
    elif status == "validated":
        verdict = "§44 validated（lift>=2x + n>=30）"
    else:
        verdict = "§44 未 validated（lift<2x）——不阻断接入跑通，60 日后复验"

    return {
        "settled": settled,
        "missed": missed,
        "forward_test_recorded": recorded,
        "forward_test_summary": summary,
        "verdict": verdict,
    }


# ===========================================================================
# 4d：T+1 溢价评分 + 复盘报告（盘后调度用，tasks.md 060-062 调度）
# ===========================================================================

def _normalize_date_iso(date: str) -> str:
    """YYYYMMDD → YYYY-MM-DD（baostock bar.date 格式）。

    baostock_kline_cache 的 bar.date 形如 "2025-12-25"（ISO 格式），
    而 signal_date 来自快照文件名（YYYYMMDD 紧凑格式）。日期比较必须同格式。
    已是 YYYY-MM-DD 的直接返回。
    """
    if not date:
        return ""
    if "-" in date:
        return date
    if len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return date


def run_t1_premium_review(signal_date: str) -> dict:
    """T+1 溢价评分——对 T-1 候选做收益评价（盘后调度用）。

    流程：
    1. 读 T-1 快照（load_scores）取候选
    2. 从 baostock_kline_cache 取 T 日 K 线（signal_date 后第一个 bar）
    3. 算每只候选的标的收益（T 日 close vs T-1 open）——spec plan.md 口径
    4. 算整体统计（平均收益/正收益占比/最佳/最差）
    5. 调 judge_lift_four_states 判定选股质量

    Args:
        signal_date: T-1 日期（选股日）YYYYMMDD 或 YYYY-MM-DD。

    Returns:
        dict：
        - signal_date: str（YYYYMMDD）
        - candidates: list[dict]，每项 {code, name, rank, total_score,
                       t0_date, t1_date, t1_close, t1_open, t1_return_pct}
        - stats: dict {n, mean_return_pct, pos_ratio, pos_count,
                   best_return, worst_return}
        - verdict: str（lift 四态）
        - error: str（仅失败时，无快照/无 T+1 数据）
        无 T+1 数据 → {"error": "...", "candidates": [...]}
    """
    from strategies.first_board_filter import load_scores
    from vr_paths import resolve_data_dir
    import json

    cached = load_scores(signal_date)
    if not cached or not cached.get("scored_candidates"):
        return {"error": f"T-1({signal_date})无候选快照"}

    candidates = cached["scored_candidates"]
    compact_date = signal_date.replace("-", "") if "-" in signal_date else signal_date
    iso_date = _normalize_date_iso(signal_date)

    # baostock K 线缓存（与 first_board_filter._get_kline_cache 同路径）
    cache_path = resolve_data_dir() / "baostock_kline_cache.json"
    cache: dict = {}
    try:
        if cache_path.exists():
            cache = json.loads(cache_path.read_bytes())
    except Exception as e:
        _logger.warning("run_t1_premium_review 读 baostock 缓存失败 err=%s", e)
        cache = {}

    t1_returns: list[dict] = []
    for c in candidates:
        code = c.get("code", "")
        bars = cache.get(code, [])
        # T 日 = bars 中 date > signal_date 的第一个 bar
        # baostock bar.date 为 ISO "YYYY-MM-DD"，统一用 ISO 比较
        t1_bar = None
        t0_bar = None
        for b in bars:
            b_date = b.get("date", "")
            # b_date 可能是 ISO 或紧凑，统一转 ISO 比较
            b_iso = b_date if "-" in b_date else _normalize_date_iso(b_date)
            if b_iso > iso_date:
                t1_bar = b
                break
            # S115 R1：精确匹配 signal_date 当日 bar（对齐 S111 R6
            # _bar_close:scheduled_tasks.py:1885 '==' 范式 + first_board_filter:324
            # R6 同款）。旧 '<=' 取"当日或之前最近 bar"，当日 bar 缺（停牌/新股
            # 缺口/baostock 缓存未含该日）时静默回退数日/周前 bar 冒充当日 open
            # → wildly wrong return_pct 喂 lift/胜率/verdict（§44 承重链撒谎）。
            # 改 '==' 精确匹配，缺当日 bar→t0_bar=None→t1_return_pct=None 跳过，
            # 不取邻近 bar 冒充（不臆造，§1.2 工程底线）。
            if b_iso == iso_date:
                t0_bar = b

        ret: float | None = None
        t1_close = None
        t1_open = None
        t1_date = None
        # t0_date provenance：下游可见 T-1 bar 实际日期（非黑盒）；缺当日 bar→None
        t0_date = t0_bar.get("date") if t0_bar is not None else None
        if t1_bar is not None:
            t1_close = t1_bar.get("close")
            t1_date = t1_bar.get("date")
            # 标的收益口径（spec plan.md）：(T 日 close - T-1 open) / T-1 open * 100
            # T-1 open 用 t0_bar.open（signal_date 当日 open）
            if t0_bar is not None:
                t1_open = t0_bar.get("open")
            # 缺当日 t0_bar（停牌/缺口）→ t1_open=None → ret=None 跳过，不冒充
            if t1_open and t1_open > 0 and t1_close is not None:
                ret = round((t1_close - t1_open) / t1_open * 100, 4)

        t1_returns.append({
            "code": code,
            "name": c.get("name", ""),
            "rank": c.get("rank", 0),
            "total_score": c.get("total", 0.0),
            "t0_date": t0_date,
            "t1_date": t1_date,
            "t1_close": t1_close,
            "t1_open": t1_open,
            "t1_return_pct": ret,
        })

    # 整体统计
    valid_returns = [
        r["t1_return_pct"] for r in t1_returns
        if r["t1_return_pct"] is not None
    ]
    n = len(valid_returns)
    if n == 0:
        return {
            "error": "无T+1收益数据（baostock 缓存无 signal_date 后的 bar）",
            "signal_date": compact_date,
            "candidates": t1_returns,
        }

    mean_ret = sum(valid_returns) / n
    pos_count = sum(1 for r in valid_returns if r > 0)
    pos_ratio = pos_count / n
    # lift 近似：策略胜率 vs 随机基准 50%（简化，无 universe 数据时）
    # judge_lift_four_states 用 lift+n 判四态；此处 lift 用胜率/50 近似（诚实标注简化）
    strategy_winrate = pos_ratio * 100
    random_winrate = 50.0  # 简化随机基准（无 universe_returns，标注待回测）
    lift = round(strategy_winrate / random_winrate, 3) if random_winrate > 0 else 0.0

    verdict = judge_lift_four_states(lift, n)

    return {
        "signal_date": compact_date,
        "candidates": t1_returns,
        "stats": {
            "n": n,
            "mean_return_pct": round(mean_ret, 2),
            "pos_ratio": round(pos_ratio, 2),
            "pos_count": pos_count,
            "best_return": round(max(valid_returns), 2),
            "worst_return": round(min(valid_returns), 2),
            "lift": lift,
        },
        "verdict": verdict,
        "note": "lift 近似：策略胜率/50%随机基准（无 universe，待回测校准）",
    }


def build_review_report(t1_review: dict) -> str:
    """构造飞书复盘报告 Markdown。

    内容：
    - 首板流 T+1 溢价评分
    - 候选名单表格（排名/代码/名称/评分/T+1收益）
    - 整体统计（平均收益/正收益占比/最佳/最差）
    - 选股质量判定（lift 四态）
    - §44 未 validated 标注

    Args:
        t1_review: run_t1_premium_review 返回的 dict。

    Returns:
        Markdown 字符串。
    """
    if t1_review.get("error"):
        signal_date = t1_review.get("signal_date", "")
        candidates = t1_review.get("candidates", [])
        lines = [
            "**首板流 T+1 溢价评分报告**",
            "",
            f"选股日：{signal_date}",
            f"⚠ {t1_review['error']}",
            "",
        ]
        if candidates:
            lines.append("| 排名 | 代码 | 名称 | 评分 | T+1收益 |")
            lines.append("|---|---|---|---|---|")
            for c in candidates:
                ret = c.get("t1_return_pct")
                ret_str = f"{ret:+.2f}%" if ret is not None else "—"
                lines.append(
                    f"| {c.get('rank', '')} | {c.get('code', '')} | "
                    f"{c.get('name', '')} | {c.get('total_score', 0):.1f} | {ret_str} |"
                )
        lines.append("⚠ §44 未 validated 仅参考；阈值/权重待回测校准")
        lines.append("⚠ 历史统计特征，不构成投资建议")
        return "\n".join(lines)

    candidates = t1_review.get("candidates", [])
    stats = t1_review.get("stats", {})
    lines = ["**首板流 T+1 溢价评分报告**", ""]
    lines.append(f"选股日：{t1_review.get('signal_date', '')}")
    lines.append(f"候选数：{stats.get('n', 0)} 只")
    lines.append(f"平均收益：{stats.get('mean_return_pct', 0):+.2f}%")
    lines.append(
        f"正收益占比：{stats.get('pos_ratio', 0):.0%}"
        f"（{stats.get('pos_count', 0)}/{stats.get('n', 0)}）"
    )
    lines.append(f"最佳收益：{stats.get('best_return', 0):+.2f}%")
    lines.append(f"最差收益：{stats.get('worst_return', 0):+.2f}%")
    lines.append(f"选股质量：{t1_review.get('verdict', '')}")
    lines.append("")
    lines.append("| 排名 | 代码 | 名称 | 评分 | T+1收益 |")
    lines.append("|---|---|---|---|---|")
    for c in candidates:
        ret = c.get("t1_return_pct")
        ret_str = f"{ret:+.2f}%" if ret is not None else "—"
        lines.append(
            f"| {c.get('rank', '')} | {c.get('code', '')} | "
            f"{c.get('name', '')} | {c.get('total_score', 0):.1f} | {ret_str} |"
        )
    lines.append("")
    lines.append("⚠ §44 未 validated 仅参考；阈值/权重待回测校准")
    lines.append("⚠ 历史统计特征，不构成投资建议")
    return "\n".join(lines)
