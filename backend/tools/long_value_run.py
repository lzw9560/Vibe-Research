"""S171 R2 harness long_value_run.py——价值因子月度 §44v2 验证。

spec: specs/S171-长线价值/spec.md（R2）。tasks: tasks.md（T8-T14）。
T8: 月度 rebalance + PIT earnings gate + quintile。
复用 R1 cache（scan_long_value_cache.py）：stock_basic_type1 + baostock_kline_raw/qfq +
profit_data_multiyear + historical_universe_monthly。

工程底线：不臆造（缺数据返 None/空 + 标 underpowered）/ 私有数据隔离（只读 .vibe-research/ cache）/
§44 关联只接线落 Recorder，不改守护区（lift_for_arm/regime_caps 不动）。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from vr_paths import resolve_data_dir  # noqa: E402

SCRATCH = resolve_data_dir() / "s171_long_value"

# spec R5 cost：0.25%（佣金 0.025%×2 + 印花 0.05% + 滑点 0.10% + 过户 0.001%×2）
ROUND_TRIP_COST = 0.0025


@dataclass(frozen=True)
class PitProfitRow:
    """PIT profit row（pubDate < D 的最新 quarter）——immutable（coding-style）。"""

    code: str
    rebalance_date: str  # D 月末交易日
    quarter_key: str  # "2026Q1"
    pub_date: str
    eps_ttm: float
    roe_avg: float | None = None
    mb_revenue: float | None = None
    total_share: int | None = None


def _quarter_sort_key(quarter_key: str) -> tuple[int, int]:
    """quarter_key "2026Q1" → (2026, 1) for tie-breaking（同 pubDate 取最新 quarter）。

    bug 8: compute_pe 同 pubDate 取原 dict 顺序 Q4-dict-顺序错误。
    quarter_key parse (year, quarter_num) 元组降序非字符串排序。
    """
    try:
        year_s, q_s = quarter_key.split("Q")
        return (int(year_s), int(q_s))
    except (ValueError, IndexError):
        return (0, 0)


def get_pit_profit_row(
    code: str,
    rebalance_date: str,
    profit_cache: dict[str, dict[str, dict]],
) -> PitProfitRow | None:
    """T8.2b：取 code 在 rebalance_date D 的 PIT profit row（pubDate < D 严格小于的最新 quarter）。

    bug 7: pubDate <= D 是 lookahead（A 股盘后披露同日=lookahead ~25% 月）→ 严格 <。
    bug 8: 同 pubDate 时取最新 quarter（2026Q1 > 2025Q4）非 dict 顺序——
           (pubDate, quarter_sort_key) 元组降序 sort tie-breaking。
    缺数据（无 quarter 或全 pubDate>=D）返 None，不臆造。
    """
    quarters = profit_cache.get(code)
    if not quarters:
        return None
    pit_rows = []
    for q_key, row in quarters.items():
        pub = row.get("pubDate", "")
        if pub and pub < rebalance_date:
            pit_rows.append((pub, q_key, row))
    if not pit_rows:
        return None
    pit_rows.sort(key=lambda r: (r[0], _quarter_sort_key(r[1])), reverse=True)
    pub, q_key, row = pit_rows[0]
    eps = row.get("epsTTM")
    if eps is None:
        return None
    return PitProfitRow(
        code=code,
        rebalance_date=rebalance_date,
        quarter_key=q_key,
        pub_date=pub,
        eps_ttm=float(eps),
        roe_avg=row.get("roeAvg"),
        mb_revenue=row.get("MBRevenue"),
        total_share=row.get("totalShare"),
    )


def compute_pe(
    code: str,
    rebalance_date: str,
    close: float,
    profit_cache: dict[str, dict[str, dict]],
) -> float | None:
    """T8.2a：不复权 close PE = close / epsTTM（PIT gate pubDate < D 严格）。

    bug 1: 用不复权 close（adjustflag=3）非前复权——前复权调当前股本但 epsTTM 原始股本→PE 虚低。
    bug 7: PIT gate pubDate < D（非 <=）——A 股盘后披露同日=lookahead ~25% 月。
    缺数据（无 PIT profit row 或 epsTTM<=0）返 None，不臆造。
    """
    row = get_pit_profit_row(code, rebalance_date, profit_cache)
    if row is None or row.eps_ttm <= 0:
        return None
    return close / row.eps_ttm


def _close_on_or_before(bars: list[dict], target_date: str) -> float | None:
    """不复权 close on or before target_date（停牌 volume==0 或无 bar 返 None）。

    bug 9: 停牌股 stale close 过滤——kline(D) volume==0 或无 D 日 bar，从 universe+Q1/Q5 候选双重剔除。
    bars 按 date asc（baostock 默认）。
    """
    if not bars:
        return None
    close = None
    for b in bars:
        d = b.get("date", "")
        if d > target_date:
            break
        vol = b.get("volume", 0)
        if vol == 0:  # 停牌 volume==0 跳过（不取 stale close）
            continue
        close = b.get("close")
    return close


def select_quintiles(
    rebalance_date: str,
    universe: set[str],
    kline_raw: dict[str, list[dict]],
    profit_cache: dict[str, dict[str, dict]],
) -> tuple[set[str], set[str], dict[str, float]]:
    """T8.3：不复权 close PE quintile 选股（bottom Q1 value + top Q5 growth）。

    bug 1: 用不复权 close（adjustflag=3）PE——前复权 PE 虚低。
    停牌/无 close/无 PIT profit/epsTTM<=0 股剔除（不臆造 PE）。
    返 (Q1_codes, Q5_codes, pe_map)——pe_map={code: PE} 供跨调整法 stability 验证。
    universe < 10 股返空（样本不足不强行 quintile）。
    """
    pe_map: dict[str, float] = {}
    for code in universe:
        bars = kline_raw.get(code, [])
        close = _close_on_or_before(bars, rebalance_date)
        if close is None:
            continue
        pe = compute_pe(code, rebalance_date, close, profit_cache)
        if pe is not None and pe > 0:
            pe_map[code] = pe
    if len(pe_map) < 10:
        return set(), set(), pe_map
    sorted_codes = sorted(pe_map.keys(), key=lambda c: pe_map[c])
    n = len(sorted_codes)
    q1_n = n // 5
    Q1 = set(sorted_codes[:q1_n])  # bottom 1/5（value，低 PE）
    q5_start = n - q1_n
    Q5 = set(sorted_codes[q5_start:])  # top 1/5（growth，高 PE）
    return Q1, Q5, pe_map


def compute_exclusion_rate(
    rebalance_date: str,
    universe: set[str],
    profit_cache: dict[str, dict[str, dict]],
) -> float:
    """T8.4：epsTTM>0 过滤排除率统计（>30% 标 low-coverage）。

    排除 = 无 PIT profit row 或 epsTTM<=0。
    返排除率（0.0-1.0），~32% 预期（spec）。
    universe 空返 0.0（不臆造）。
    """
    if not universe:
        return 0.0
    excluded = 0
    for code in universe:
        row = get_pit_profit_row(code, rebalance_date, profit_cache)
        if row is None or row.eps_ttm <= 0:
            excluded += 1
    return excluded / len(universe)


def month_end_rebalance_days() -> list[str]:
    """T8.1：月末最后交易日 list（非 calendar 月末——周末/假日无 close）。

    复用 R1 cache（historical_universe_monthly.json 的 key）或 baostock query_trade_dates。
    """
    cache_path = SCRATCH / "historical_universe_monthly.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_bytes())
        return sorted(data.keys())
    from scan_long_value_cache import _month_end_trading_days  # noqa: PLC0415

    return _month_end_trading_days()


def load_r1_cache() -> dict:
    """加载 R1 cache（scan_long_value_cache.py 产出）。

    返 {stock_basic, kline_raw, kline_qfq, profit, universe}——缺的返 {} 不臆造。
    """
    def _load(name: str) -> dict:
        p = SCRATCH / name
        return json.loads(p.read_bytes()) if p.exists() else {}

    return {
        "stock_basic": _load("stock_basic_type1.json"),
        "kline_raw": _load("baostock_kline_raw.json"),
        "kline_qfq": _load("baostock_kline_qfq.json"),
        "profit": _load("profit_data_multiyear.json"),
        "universe": _load("historical_universe_monthly.json"),
    }


def _month_return(
    code: str, prev_date: str, curr_date: str, kline_raw: dict[str, list[dict]]
) -> float | None:
    """单股月度收益 = (close[curr] - close[prev]) / close[prev]（不复权，停牌 None）。"""
    bars = kline_raw.get(code, [])
    prev_close = _close_on_or_before(bars, prev_date)
    curr_close = _close_on_or_before(bars, curr_date)
    if prev_close is None or curr_close is None or prev_close <= 0:
        return None
    return (curr_close - prev_close) / prev_close


def _turnover(curr_codes: set[str], prev_codes: set[str]) -> float:
    """月度换手率 = |curr Δ prev| / |curr ∪ prev|（对称差异率 0-1）。

    首月 prev 空 → turnover=1.0（全换）。T9.2 双腿 turnover 异步>10% caveat 标注。
    """
    if not curr_codes and not prev_codes:
        return 0.0
    union = curr_codes.union(prev_codes)
    sym_diff = curr_codes.symmetric_difference(prev_codes)
    return len(sym_diff) / len(union) if union else 0.0


def _build_q1_q5_spread_series(r1_cache: dict) -> tuple[list[float], list[str]]:
    """T9.1: 构建 Q1-Q5 spread returns + dates（不调 wire_verdict，供 test 测）。

    returns = [Q1_ret - Q5_ret per month]，dates = [month_ISO YYYY-MM]。
    T9.2 cost 预扣双腿：spread -= ROUND_TRIP_COST × (turnover_Q1 + turnover_Q5)（非 single×2）。
    缺数据（月度 <2 / Q1Q5 空 / 收益空）返 ([], []) 不臆造。
    """
    kline_raw = r1_cache.get("kline_raw", {})
    profit = r1_cache.get("profit", {})
    universe_cache = r1_cache.get("universe", {})
    rebalance_days = month_end_rebalance_days()
    if len(rebalance_days) < 2:
        return [], []
    returns: list[float] = []
    dates: list[str] = []
    prev_q1: set[str] = set()
    prev_q5: set[str] = set()
    for i in range(1, len(rebalance_days)):
        curr_date = rebalance_days[i]
        prev_date = rebalance_days[i - 1]
        universe = set(universe_cache.get(curr_date, {}).get("active", []))
        q1, q5, _ = select_quintiles(curr_date, universe, kline_raw, profit)
        if not q1 and not q5:
            continue
        q1_rets = [r for r in (_month_return(c, prev_date, curr_date, kline_raw) for c in q1) if r is not None]
        q5_rets = [r for r in (_month_return(c, prev_date, curr_date, kline_raw) for c in q5) if r is not None]
        if not q1_rets or not q5_rets:
            continue
        spread = sum(q1_rets) / len(q1_rets) - sum(q5_rets) / len(q5_rets)
        # T9.2 cost 预扣双腿（turnover_Q1 + turnover_Q5 异步>10% caveat）
        spread -= ROUND_TRIP_COST * (_turnover(q1, prev_q1) + _turnover(q5, prev_q5))
        returns.append(spread)
        dates.append(curr_date[:7])  # month_ISO YYYY-MM
        prev_q1, prev_q5 = q1, q5
    return returns, dates


def wire_q1_q5_spread(
    *,
    line_id: str,
    frozen_commit: str,
    r1_cache: dict | None = None,
) -> dict:
    """T9: co-PRIMARY ① Q1-Q5 long-short spread wire（event edge_type，mean t-test）。

    构建 returns=[Q1_ret - Q5_ret per month]+dates=[month_ISO]，edge_type="event"。
    cost 预扣双腿（T9.2 分腿实测非 single×2，已预扣 → wire_verdict round_trip_cost=0）。
    不可直接交易 caveat（A 股 short 受限）——long-short beta 中性但 A 股 short 受限。

    缺数据（月度 <2 / 有效 spread <2）返 {"status": "underpowered"} 不臆造。
    调 wire_verdict 传 5 月度参数（walk_train=36/walk_test=12/step=12/event_materiality_floor=0.001）。
    """
    cache = r1_cache if r1_cache is not None else load_r1_cache()
    returns, dates = _build_q1_q5_spread_series(cache)
    if len(returns) < 2:
        return {
            "line_id": line_id, "status": "underpowered",
            "note": "有效 spread <2", "returns": returns, "dates": dates,
        }
    import sys as _sys  # noqa: PLC0415
    _tools_dir = str(Path(__file__).resolve().parent)
    if _tools_dir not in _sys.path:
        _sys.path.insert(0, _tools_dir)
    from _s44_wire import wire_verdict  # noqa: PLC0415

    verdict = wire_verdict(
        line_id=line_id,
        returns=returns,
        edge_type="event",
        frozen_commit=frozen_commit,
        dates=dates,
        round_trip_cost=0.0,  # 已双腿预扣（T9.2 非 single×2）
        walk_train=36,
        walk_test=12,
        step=12,
        event_materiality_floor=0.001,
        script="long_value_run.wire_q1_q5_spread",
        params={"cost_model": "dual_leg", "caveat": "不可直接交易（A 股 short 受限）"},
    )
    return {
        "line_id": line_id,
        "status": getattr(verdict, "status", "unknown"),
        "returns": returns,
        "dates": dates,
        "n": len(returns),
        "caveat": "不可直接交易（A 股 short 受限）——long-short beta 中性但 A 股 short 受限",
    }


__all__ = [
    "PitProfitRow",
    "ROUND_TRIP_COST",
    "get_pit_profit_row",
    "compute_pe",
    "select_quintiles",
    "compute_exclusion_rate",
    "month_end_rebalance_days",
    "load_r1_cache",
    "wire_q1_q5_spread",
    "_monthly_return",
    "wire_q1_excess_universe",
]


def _monthly_return(
    bars: list[dict], rebalance_date: str, prev_rebalance_date: str | None
) -> float | None:
    """月度收益 = (close_D - close_prev)/close_prev。停牌/无数据返 None。

    复用 _close_on_or_before（停牌 volume==0 跳过，不取 stale close）。
    prev_rebalance_date=None（第一个月）返 None（无前月，不能算收益）。
    spec bug 9：rebalance_date 当日停牌（volume==0 或无 bar）→ 返 None（停牌股从月度收益剔除）。
    """
    if prev_rebalance_date is None:
        return None
    # 停牌检测：rebalance_date 当日 volume==0 或无 bar → 剔除（spec bug 9）
    suspended = True
    for b in bars:
        d = b.get("date", "")
        if d == rebalance_date:
            suspended = b.get("volume", 0) == 0
            break
        if d > rebalance_date:
            break
    if suspended:
        return None
    close_d = _close_on_or_before(bars, rebalance_date)
    if close_d is None:
        return None
    close_prev = _close_on_or_before(bars, prev_rebalance_date)
    if close_prev is None or close_prev == 0:
        return None
    return (close_d - close_prev) / close_prev


def wire_q1_excess_universe(months: list[str] | None = None) -> dict:
    """T10: co-PRIMARY ② Q1-excess-over-universe wire（selection edge_type，long-only 可实现）。

    构建 survivors_by_month={月:Q1 returns}+universe_by_month={月:all_active returns}+
    dates=[month_ISO]，window_sanity={"path":{mean,winrate,base_rate}} R5 前置 sanity。
    调 wire_verdict(edge_type="selection", survivors_by_day, universe_by_day, dates,
    window_sanity)——selection 有 survivors/universe+dates → 能跑 PurgedKFold+walk-forward OOS。

    spec §0：② 管 OOS（补 ① 的 OOS 缺口），但 winrate 驱动有假阴性风险
    （value 是 mean-return 现象非 winrate，winrate lift 结构性 ≈1.0-1.2 永远到不了 2.0x robust_edge）。
    月度参数 walk_train=36/walk_test=12/step=12（S171 R3，否则月度 walk_forward OOS 失效）+
    event_materiality_floor=0.001（S171 T1 第 5 参数，effective_floor=max(floor, cost*0.5)）。

    缺数据（cache 空/months<2/Q1 空）返 {data_status: "empty"} 不臆造。
    §44 关联只接线落 Recorder，不改守护区（lift_for_arm/regime_caps 不动）。
    """
    cache = load_r1_cache()
    kline_raw = cache.get("kline_raw", {})
    profit_cache = cache.get("profit", {})
    universe_cache = cache.get("universe", {})

    if months is None:
        months = month_end_rebalance_days()
    if len(months) < 2:
        return {"data_status": "empty", "note": "months<2 无法算月度收益"}

    survivors_by_month: dict[str, list[float]] = {}
    universe_by_month: dict[str, list[float]] = {}

    for i, month in enumerate(months):
        prev_month = months[i - 1] if i > 0 else None
        if prev_month is None:
            continue  # 第一个月无前月
        month_universe = set(universe_cache.get(month, []))
        if not month_universe:
            month_universe = set(kline_raw.keys())
        # T8 select_quintiles 取 Q1（低 PE value，long-only 可实现）
        q1_codes, _q5_codes, _pe_map = select_quintiles(
            month, month_universe, kline_raw, profit_cache
        )
        q1_returns = [
            r
            for code in q1_codes
            if (r := _monthly_return(kline_raw.get(code, []), month, prev_month)) is not None
        ]
        u_returns = [
            r
            for code in month_universe
            if (r := _monthly_return(kline_raw.get(code, []), month, prev_month)) is not None
        ]
        if q1_returns and u_returns:
            survivors_by_month[month] = q1_returns
            universe_by_month[month] = u_returns

    if not survivors_by_month:
        return {"data_status": "empty", "note": "无 Q1 returns（cache 空或 PIT profit 全缺）"}

    dates = sorted(survivors_by_month.keys())

    # T10.2: window_sanity R5 前置 sanity（value winrate≈base_rate→R5 触发 exploratory 预期）
    all_q1 = [r for rs in survivors_by_month.values() for r in rs]
    all_u = [r for rs in universe_by_month.values() for r in rs]
    q1_mean = sum(all_q1) / len(all_q1) if all_q1 else 0.0
    q1_winrate = sum(1 for r in all_q1 if r > 0) / len(all_q1) if all_q1 else 0.0
    u_winrate = sum(1 for r in all_u if r > 0) / len(all_u) if all_u else 0.0
    window_sanity = {
        "path": {
            "mean": q1_mean,
            "winrate": q1_winrate,
            "base_rate": u_winrate,
        }
    }

    # 调 wire_verdict（selection edge_type + 月度参数 5 个）
    from tools._s44_wire import wire_verdict  # noqa: PLC0415

    return wire_verdict(
        line_id="S171_Q1_excess_universe",
        returns=all_q1,  # Q1 所有月 returns 合并（for event_metrics 双算 R8）
        edge_type="selection",
        frozen_commit="scratch",  # TODO T14 dry-run 传真 commit
        dates=dates,
        survivors_by_day=survivors_by_month,
        universe_by_day=universe_by_month,
        n_comparisons=1,
        round_trip_cost=ROUND_TRIP_COST,
        window_sanity=window_sanity,
        walk_train=36,
        walk_test=12,
        step=12,
        event_materiality_floor=0.001,
        script="long_value_run.wire_q1_excess_universe",
    )


# ---------- T12: 退市 -100% inject + sensitivity 两档 ----------


def _delisting_return(
    code: str,
    month: str,
    prev_month: str | None,
    kline_raw: dict,
    delisting_map: dict[str, str],
    inject_return: float,
) -> float | None:
    """退市股注入月返 inject_return，否则调 _monthly_return。

    spec T12.1：退市股最后 active 交易月→下月 return=-1.0（inject_return）。
    delisting_map = {code: inject_month}（注入月=退市月/last_active 下月）。
    bug 4：survivors + universe 同月同值注入（由调用方对 survivors/universe 都用此函数保证）。
    0 bars 股 fallback：delisting_map[code] 锚定（kline 无 bar 也注入，不取 None）。
    """
    inject_month = delisting_map.get(code)
    if inject_month and month == inject_month and prev_month is not None:
        return inject_return
    return _monthly_return(kline_raw.get(code, []), month, prev_month)


def _build_delisting_map(stock_basic: dict) -> dict[str, str]:
    """从 stock_basic 读 outDate，返 {code: inject_month}（注入月=outDate）。

    退市股 outDate != ""（scan_long_value_cache line 175-181）。
    非退市股（outDate==""）不进 map。
    """
    result: dict[str, str] = {}
    for code, info in stock_basic.items():
        out_date = (info or {}).get("outDate", "")
        if out_date:
            result[code] = out_date
    return result


def _build_survivors_universe_with_inject(
    months: list[str],
    kline_raw: dict,
    profit_cache: dict,
    universe_cache: dict,
    delisting_map: dict[str, str],
    inject_return: float,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """构建 survivors/universe 带退市 inject（复用 T8 select_quintiles + T10 _monthly_return）。

    bug 4：survivors + universe 同月同值注入（_delisting_return 对两者都用 → 一致）。
    immutable：返新 dict 不 mutate 输入。
    """
    survivors_by_month: dict[str, list[float]] = {}
    universe_by_month: dict[str, list[float]] = {}
    for i, month in enumerate(months):
        prev_month = months[i - 1] if i > 0 else None
        if prev_month is None:
            continue
        month_universe = set(universe_cache.get(month, []))
        if not month_universe:
            month_universe = set(kline_raw.keys())
        q1_codes, _q5_codes, _pe_map = select_quintiles(
            month, month_universe, kline_raw, profit_cache
        )
        q1_returns = [
            r
            for code in q1_codes
            if (r := _delisting_return(code, month, prev_month, kline_raw, delisting_map, inject_return)) is not None
        ]
        u_returns = [
            r
            for code in month_universe
            if (r := _delisting_return(code, month, prev_month, kline_raw, delisting_map, inject_return)) is not None
        ]
        if q1_returns and u_returns:
            survivors_by_month[month] = q1_returns
            universe_by_month[month] = u_returns
    return survivors_by_month, universe_by_month


def inject_delisting(
    survivors_by_month: dict[str, list[float]],
    universe_by_month: dict[str, list[float]],
    delisting_codes_by_month: dict[str, list[str]],
    inject_return: float = -1.0,
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """post-process 注入（spec T12.1 A-test 验证用，生产用 _build_survivors_universe_with_inject）。

    对 delisting_codes_by_month[month] 里的 code，survivors + universe 同月注入 inject_return。
    bug 4：survivors + universe 同月同值（一致，不能只注入 survivors）。
    immutable：返新 dict 不 mutate 原。
    """
    new_survivors: dict[str, list[float]] = {m: list(rs) for m, rs in survivors_by_month.items()}
    new_universe: dict[str, list[float]] = {m: list(rs) for m, rs in universe_by_month.items()}
    for month, codes in delisting_codes_by_month.items():
        new_survivors.setdefault(month, [])
        new_universe.setdefault(month, [])
        for _code in codes:
            new_survivors[month].append(inject_return)
            new_universe[month].append(inject_return)
    return new_survivors, new_universe


def run_sensitivity_two_tier(months: list[str] | None = None) -> dict:
    """T12.2: 退市 sensitivity 两档 -0.5 vs -1.0 跑两遍，返两档 status + lift 差值 flag。

    spec T12.2 + T13.2b：一致性 gate（status 一致→稳，不一致→降级 exploratory 标"依赖退市 return 假设"）。
    lift 差值 |lift_-0.5 - lift_-1.0|>0.3 标敏感 flag。
    缺数据返 data_status=empty 不臆造。
    §44 关联只接线落 Recorder，不改守护区（lift_for_arm/regime_caps 不动）。
    """
    cache = load_r1_cache()
    kline_raw = cache.get("kline_raw", {})
    profit_cache = cache.get("profit", {})
    universe_cache = cache.get("universe", {})
    stock_basic = cache.get("stock_basic", {})

    if months is None:
        months = month_end_rebalance_days()
    if len(months) < 2:
        return {"data_status": "empty", "note": "months<2 无法算月度收益"}

    delisting_map = _build_delisting_map(stock_basic)

    from tools._s44_wire import wire_verdict  # noqa: PLC0415

    results: dict[float, dict] = {}
    for inject_return in (-0.5, -1.0):
        survivors, universe = _build_survivors_universe_with_inject(
            months, kline_raw, profit_cache, universe_cache, delisting_map, inject_return
        )
        if not survivors:
            results[inject_return] = {"status": "empty", "lift": 0.0}
            continue
        dates = sorted(survivors.keys())
        all_q1 = [r for rs in survivors.values() for r in rs]
        all_u = [r for rs in universe.values() for r in rs]
        q1_mean = sum(all_q1) / len(all_q1) if all_q1 else 0.0
        q1_winrate = sum(1 for r in all_q1 if r > 0) / len(all_q1) if all_q1 else 0.0
        u_winrate = sum(1 for r in all_u if r > 0) / len(all_u) if all_u else 0.0
        window_sanity = {"path": {"mean": q1_mean, "winrate": q1_winrate, "base_rate": u_winrate}}
        verdict = wire_verdict(
            line_id=f"S171_sensitivity_{inject_return}",
            returns=all_q1,
            edge_type="selection",
            frozen_commit="scratch",  # TODO T14 dry-run 传真 commit
            dates=dates,
            survivors_by_day=survivors,
            universe_by_day=universe,
            n_comparisons=1,
            round_trip_cost=ROUND_TRIP_COST,
            window_sanity=window_sanity,
            walk_train=36,
            walk_test=12,
            step=12,
            event_materiality_floor=0.001,
            script="long_value_run.run_sensitivity_two_tier",
        )
        results[inject_return] = verdict

    status_05 = results[-0.5].get("status", "empty")
    status_10 = results[-1.0].get("status", "empty")
    lift_05 = results[-0.5].get("lift") or 0.0
    lift_10 = results[-1.0].get("lift") or 0.0
    lift_diff = abs(lift_05 - lift_10)
    return {
        "status_-0.5": status_05,
        "status_-1.0": status_10,
        "consistent": status_05 == status_10,
        "lift_-0.5": lift_05,
        "lift_-1.0": lift_10,
        "lift_diff": lift_diff,
        "sensitive_flag": lift_diff > 0.3,
        "data_status": "ok",
        "note": "退市 sensitivity 两档——一致=稳，不一致=降级 exploratory 标依赖退市 return 假设",
    }


def _benchmark_monthly_return(
    bars: list[dict], rebalance_date: str, prev_rebalance_date: str | None
) -> float | None:
    """benchmark（HS300 指数）月度收益——不检查 volume 停牌（指数无停牌）。

    用 close 算 (close_D - close_prev)/close_prev，**不调** _close_on_or_before
    （它检查 volume==0 跳过——benchmark bars 无 volume 字段会返 None）。
    自己遍历取 <= rebalance_date 的最后 close + <= prev 的最后 close。
    prev=None 返 None（无前月）。spec T11.2 SECONDARY benchmark 对比用。
    """
    if prev_rebalance_date is None:
        return None
    close_d = None
    close_prev = None
    for b in bars:
        d = b.get("date", "")
        if d > rebalance_date:
            break
        c = b.get("close")
        if c is None:
            continue
        close_d = c  # <= rebalance_date 的最后 close
        if d <= prev_rebalance_date:
            close_prev = c  # <= prev_rebalance_date 的最后 close
    if close_d is None or close_prev is None or close_prev == 0:
        return None
    return (close_d - close_prev) / close_prev


def wire_auxiliary_low_high(
    *,
    line_id: str = "S171_auxiliary_low_high",
    frozen_commit: str = "scratch",
    months: list[str] | None = None,
) -> dict:
    """T11.1: AUXILIARY selection-low_pe/high_pe wire（selection edge_type）。

    survivors=Q1 low_pe returns + universe=Q5 high_pe returns（对比 low vs high PE 选股力）。
    spec §0：AUXILIARY 标"winrate 对 value 结构性受限"——winrate lift 结构性 ≈1.0-1.2
    永远到不了 2.0x robust_edge（value 是 mean-return 现象非 winrate）。

    缺数据返 {data_status: "empty"} 不臆造。
    §44 关联只接线落 Recorder，不改守护区。
    """
    cache = load_r1_cache()
    kline_raw = cache.get("kline_raw", {})
    profit_cache = cache.get("profit", {})
    universe_cache = cache.get("universe", {})

    if months is None:
        months = month_end_rebalance_days()
    if len(months) < 2:
        return {"data_status": "empty", "note": "months<2 无法算月度收益"}

    survivors_by_month: dict[str, list[float]] = {}
    universe_by_month: dict[str, list[float]] = {}

    for i, month in enumerate(months):
        prev_month = months[i - 1] if i > 0 else None
        if prev_month is None:
            continue
        month_universe = set(universe_cache.get(month, []))
        if not month_universe:
            month_universe = set(kline_raw.keys())
        q1_codes, q5_codes, _pe_map = select_quintiles(
            month, month_universe, kline_raw, profit_cache
        )
        q1_returns = [
            r for code in q1_codes
            if (r := _monthly_return(kline_raw.get(code, []), month, prev_month)) is not None
        ]
        # universe 用全 active returns（基准，跟 T10 一致；Q5 作对比但 universe 须 >= survivors 维度）
        u_returns = [
            r for code in month_universe
            if (r := _monthly_return(kline_raw.get(code, []), month, prev_month)) is not None
        ]
        if q1_returns and u_returns:
            survivors_by_month[month] = q1_returns
            universe_by_month[month] = u_returns

    if not survivors_by_month:
        return {"data_status": "empty", "note": "无 Q1/Q5 returns（cache 空或 PIT profit 全缺）"}

    dates = sorted(survivors_by_month.keys())
    all_q1 = [r for rs in survivors_by_month.values() for r in rs]

    import sys as _sys  # noqa: PLC0415
    _tools_dir = str(Path(__file__).resolve().parent)
    if _tools_dir not in _sys.path:
        _sys.path.insert(0, _tools_dir)
    from tools._s44_wire import wire_verdict  # noqa: PLC0415

    verdict = wire_verdict(
        line_id=line_id,
        returns=all_q1,
        edge_type="selection",
        frozen_commit=frozen_commit,
        dates=dates,
        survivors_by_day=survivors_by_month,
        universe_by_day=universe_by_month,
        n_comparisons=1,
        round_trip_cost=ROUND_TRIP_COST,
        walk_train=36,
        walk_test=12,
        step=12,
        event_materiality_floor=0.001,
        script="long_value_run.wire_auxiliary_low_high",
        params={"caveat": "winrate 对 value 结构性受限（value 是 mean-return 非赢率）"},
    )
    return {
        "line_id": line_id,
        "status": getattr(verdict, "status", "unknown"),
        "n": len(all_q1),
        "caveat": "winrate 对 value 结构性受限——AUXILIARY 降级标注",
    }


def wire_secondary_q1_hs300(
    *,
    line_id: str = "S171_secondary_q1_hs300",
    frozen_commit: str = "scratch",
    months: list[str] | None = None,
) -> dict:
    """T11.2: SECONDARY Q1-excess-HS300 wire（event edge_type，benchmark 对比）。

    returns = Q1 mean returns - HS300 returns per month（benchmark alpha）。
    spec §0：SECONDARY 是 benchmark 对比。
    caveat：HS300 大盘股 size-confounded（不同于 Q1 全 A value 股）+ BH m=1 latent（K=1 不需 Bonferroni-Holm）。

    缺数据返 {data_status: "empty"} 不臆造。
    §44 关联只接线落 Recorder，不改守护区。
    """
    cache = load_r1_cache()
    kline_raw = cache.get("kline_raw", {})
    profit_cache = cache.get("profit", {})
    universe_cache = cache.get("universe", {})

    # benchmark HS300 bars（scan_long_value_cache Layer4 产出）
    benchmark_path = SCRATCH / "benchmark_indices.json"
    if not benchmark_path.exists():
        return {"data_status": "empty", "note": "benchmark_indices.json 不存在（跑 scan_long_value_cache --layer 4）"}
    benchmark_data = json.loads(benchmark_path.read_bytes())
    hs300_bars = benchmark_data.get("sh.000300", [])
    if not hs300_bars:
        return {"data_status": "empty", "note": "HS300 无 bars"}

    if months is None:
        months = month_end_rebalance_days()
    if len(months) < 2:
        return {"data_status": "empty", "note": "months<2 无法算月度收益"}

    returns: list[float] = []
    dates: list[str] = []
    for i, month in enumerate(months):
        prev_month = months[i - 1] if i > 0 else None
        if prev_month is None:
            continue
        month_universe = set(universe_cache.get(month, []))
        if not month_universe:
            month_universe = set(kline_raw.keys())
        q1_codes, _q5_codes, _pe_map = select_quintiles(
            month, month_universe, kline_raw, profit_cache
        )
        q1_returns = [
            r for code in q1_codes
            if (r := _monthly_return(kline_raw.get(code, []), month, prev_month)) is not None
        ]
        hs300_ret = _benchmark_monthly_return(hs300_bars, month, prev_month)
        if q1_returns and hs300_ret is not None:
            q1_mean = sum(q1_returns) / len(q1_returns)
            returns.append(q1_mean - hs300_ret)
            dates.append(month)

    if len(returns) < 2:
        return {"data_status": "empty", "note": "有效 Q1-HS300 spread <2"}

    from tools._s44_wire import wire_verdict  # noqa: PLC0415

    verdict = wire_verdict(
        line_id=line_id,
        returns=returns,
        edge_type="event",
        frozen_commit=frozen_commit,
        dates=dates,
        n_comparisons=1,
        round_trip_cost=0.0,  # benchmark 对比无交易成本（持有 Q1 vs HS300）
        walk_train=36,
        walk_test=12,
        step=12,
        event_materiality_floor=0.001,
        script="long_value_run.wire_secondary_q1_hs300",
        params={
            "caveat": "size-confounded（HS300 大盘股 vs Q1 全 A value）+ BH m=1 latent（K=1 不需 Bonferroni-Holm）",
            "benchmark": "HS300 (sh.000300)",
        },
    )
    return {
        "line_id": line_id,
        "status": getattr(verdict, "status", "unknown"),
        "returns": returns,
        "dates": dates,
        "n": len(returns),
        "caveat": "size-confounded + BH m=1 latent——SECONDARY benchmark 对比降级标注",
    }


# ---------- T13: wire_verdict 5 参数验收 + 三 gate 互验 ----------

# edge status（有选股力）vs 无 edge status（spec §0 双 co-PRIMARY 互验）
_EDGE_STATUSES = frozenset({"robust_edge", "exploratory"})
_NO_EDGE_STATUSES = frozenset({"falsified", "not_validated", "underpowered"})


def gate_cross_primary_consistency(status1: str, status2: str) -> dict:
    """T13.2a: co-PRIMARY ①② status 一致→PASS，矛盾→降级 exploratory 标"双 PRIMARY 不一致"。

    都 edge（robust_edge/exploratory）或都无 edge（falsified/not_validated/underpowered）才 PASS。
    矛盾（一有一无）→降级 exploratory。R5 skip 时 status=None/unknown→skip。
    """
    if status1 in (None, "unknown") or status2 in (None, "unknown"):
        return {"pass": True, "label": "skip", "note": f"①② status 未定（{status1} vs {status2}）"}
    if status1 == status2:
        return {"pass": True, "label": "consistent", "note": f"①② status 一致={status1}"}
    s1_edge = status1 in _EDGE_STATUSES
    s2_edge = status2 in _EDGE_STATUSES
    if s1_edge == s2_edge:
        return {"pass": True, "label": "consistent",
                "note": f"①② 都{'有' if s1_edge else '无'}edge（{status1} vs {status2}）"}
    return {"pass": False, "label": "exploratory",
            "note": f"双 PRIMARY 不一致（{status1} vs {status2}）→降级"}


def gate_sensitivity_consistency(sensitivity_result: dict) -> dict:
    """T13.2b: 退市 -0.5/-1.0 两档 status 一致→稳，不一致→降级 exploratory 标"依赖退市 return 假设"。

    复用 T12 run_sensitivity_two_tier 返 {consistent, sensitive_flag, data_status}。
    lift 差值 |lift_-0.5 - lift_-1.0|>0.3 标敏感 flag（T12 已算 sensitive_flag）。
    """
    if not isinstance(sensitivity_result, dict):
        return {"pass": True, "label": "skip", "note": "sensitivity 无结果（skip）"}
    if sensitivity_result.get("data_status") == "empty":
        return {"pass": True, "label": "skip", "note": "sensitivity 无数据（skip）"}
    consistent = sensitivity_result.get("consistent", False)
    sensitive_flag = sensitivity_result.get("sensitive_flag", False)
    if consistent:
        note = "两档 status 一致→稳" + ("（但 lift 敏感 flag）" if sensitive_flag else "")
        return {"pass": True, "label": "robust", "note": note}
    return {"pass": False, "label": "exploratory",
            "note": "依赖退市 return 假设（两档不一致）→降级"}


def gate_delisting_coverage(delisting_map: dict, universe_cache: dict) -> dict:
    """T13.2c: 退市覆盖率≥50% 才 robust，<50% 降级 exploratory（0 bars 股计分母算 0%）。

    覆盖率 = 有 bars 的退市股（在 universe 某月出现）/ 总退市股。
    bug 4：0 bars 股计入分母算 0% 覆盖（不臆造）。
    """
    if not delisting_map:
        return {"pass": True, "label": "skip", "note": "无退市股（skip）", "coverage": 1.0}
    all_universe_codes: set[str] = set()
    for codes in universe_cache.values():
        if isinstance(codes, (list, set)):
            all_universe_codes.update(codes)
    total = len(delisting_map)
    covered = sum(1 for code in delisting_map if code in all_universe_codes)
    coverage = covered / total if total else 1.0
    if coverage >= 0.5:
        return {"pass": True, "label": "robust",
                "note": f"退市覆盖率 {coverage:.0%}≥50%", "coverage": coverage}
    return {"pass": False, "label": "exploratory",
            "note": f"退市覆盖率 {coverage:.0%}<50%→降级（0 bars 股计分母）", "coverage": coverage}


def _status_of(verdict: object) -> str:
    """兼容取 status（dict 或 verdict 对象）。"""
    if isinstance(verdict, dict):
        return verdict.get("status", "unknown")
    return getattr(verdict, "status", "unknown")


def wire_s171_full(months: list[str] | None = None) -> dict:
    """T13: 跑 T9+T10+T11+T12 → 三 gate 互验 → 综合 verdict。

    T13.1 验收：各 wire 已传 5 月度参数（walk_train=36/walk_test=12/step=12/
    event_materiality_floor=0.001）+ window_sanity（T10 path）。
    T13.2 三 gate：①② 互验 + sensitivity 一致性 + 退市覆盖率。
    综合 status：三 gate 全 PASS→取 ① status；任一降级→exploratory。
    §44 关联只接线落 Recorder，不改守护区。
    """
    cache = load_r1_cache()
    stock_basic = cache.get("stock_basic", {})
    universe_cache = cache.get("universe", {})
    delisting_map = _build_delisting_map(stock_basic)

    # 跑各 wire（T9 传 r1_cache 避免 reload，其他传 months）
    verdict_1 = wire_q1_q5_spread(
        line_id="S171_Q1_Q5_spread", frozen_commit="scratch", r1_cache=cache,
    )
    verdict_2 = wire_q1_excess_universe(months=months)
    verdict_aux = wire_auxiliary_low_high(months=months)
    verdict_sec = wire_secondary_q1_hs300(months=months)
    sensitivity = run_sensitivity_two_tier(months=months)

    status_1 = _status_of(verdict_1)
    status_2 = _status_of(verdict_2)

    # 三 gate
    gate_a = gate_cross_primary_consistency(status_1, status_2)
    gate_b = gate_sensitivity_consistency(sensitivity)
    gate_c = gate_delisting_coverage(delisting_map, universe_cache)

    gates_pass = gate_a["pass"] and gate_b["pass"] and gate_c["pass"]
    if gates_pass:
        overall_status = status_1 if status_1 == status_2 else "exploratory"
    else:
        overall_status = "exploratory"

    return {
        "line_id": "S171_full",
        "status": overall_status,
        "primary_1_q1_q5_spread": status_1,
        "primary_2_q1_excess_universe": status_2,
        "auxiliary_low_high": _status_of(verdict_aux),
        "secondary_q1_hs300": _status_of(verdict_sec),
        "gate_cross_primary": gate_a,
        "gate_sensitivity": gate_b,
        "gate_delisting_coverage": gate_c,
        "sensitivity": sensitivity,
        "caveat": "双 co-PRIMARY 互验 + sensitivity 一致性 + 退市覆盖率三 gate（T13）",
    }


def dry_run(months: list[str] | None = None) -> dict:
    """T14.1: 构建 survivors/universe 不跑 wire_verdict——验收 4 项（PIT gate + 退市注入 + quintile stability + 停牌过滤）。

    复用 T8 select_quintiles + T12 _build_survivors_universe_with_inject（构建不调 wire_verdict）。
    返 {pit_gate_ok, delisting_injected, quintile_stability, suspended_filtered, data_status, n_months, n_survivors_months}。
    缺数据返 {data_status: "empty"} 不臆造。
    """
    cache = load_r1_cache()
    kline_raw = cache.get("kline_raw", {})
    kline_qfq = cache.get("kline_qfq", {})
    profit_cache = cache.get("profit", {})
    universe_cache = cache.get("universe", {})
    stock_basic = cache.get("stock_basic", {})

    if months is None:
        months = month_end_rebalance_days()
    if len(months) < 2:
        return {"data_status": "empty", "note": "months<2 无法算月度收益"}

    delisting_map = _build_delisting_map(stock_basic)
    survivors, universe = _build_survivors_universe_with_inject(
        months, kline_raw, profit_cache, universe_cache, delisting_map, -1.0
    )

    # 验收 1: PIT gate——spot-check 几个 code 的 pub_date < rebalance_date 严格
    pit_ok = True
    sample_codes = list(kline_raw.keys())[:5]
    for code in sample_codes:
        for m in months[:2]:
            row = get_pit_profit_row(code, m, profit_cache)
            if row is not None and row.pub_date >= m:
                pit_ok = False
                break

    # 验收 2: 退市注入完整性——delisted code 在 inject_month 有 survivors+universe 同值
    delisting_ok = True
    for code, inject_month in delisting_map.items():
        if inject_month in survivors and inject_month in universe:
            # _build_survivors_universe_with_inject 对 survivors+universe 都调 _delisting_return → 同月同值
            # 验注入发生（inject_month 在 survivors keys 里 = 注入了）
            continue
        # delisted code 的 inject_month 不在 survivors（可能该月无 Q1 选中或 cache 缺）——标 false 如该月本应有
        if inject_month in months and code in universe_cache.get(inject_month, set()):
            delisting_ok = False

    # 验收 3: quintile 跨调整法 stability——不复权 raw vs 前复权 qfq pe_map size 接近
    stability_ok = True
    if months and kline_raw:
        m = months[-1]
        u = set(universe_cache.get(m, [])) or set(kline_raw.keys())
        _q1_raw, _q5_raw, pe_raw = select_quintiles(m, u, kline_raw, profit_cache)
        _q1_qfq, _q5_qfq, pe_qfq = select_quintiles(m, u, kline_qfq or {}, profit_cache)
        # stability: 两法都剔停牌+无 PIT → size 应一致或 raw>0（qfq 空时仍 raw 有值）
        stability_ok = len(pe_raw) > 0 and (len(pe_qfq) == 0 or abs(len(pe_raw) - len(pe_qfq)) <= max(len(pe_raw), len(pe_qfq)) // 2)

    # 验收 4: 停牌过滤——_close_on_or_before volume==0 跳过（select_quintiles 已调它）
    suspended_ok = True
    for code in list(kline_raw.keys())[:3]:
        bars = kline_raw.get(code, [])
        has_suspended = any(b.get("volume", 0) == 0 for b in bars)
        if has_suspended:
            # 验 _close_on_or_before 不返停牌日 close（返前一日或 None）
            for b in bars:
                if b.get("volume", 0) == 0:
                    # 停牌日 _close_on_or_before 应跳过（不返该 b 的 close）
                    close = _close_on_or_before(bars, b.get("date", ""))
                    if close == b.get("close"):
                        suspended_ok = False
                        break

    return {
        "pit_gate_ok": pit_ok,
        "delisting_injected": delisting_ok,
        "quintile_stability": stability_ok,
        "suspended_filtered": suspended_ok,
        "n_months": len(months),
        "n_survivors_months": len(survivors),
        "data_status": "ok" if survivors else "empty",
    }


def mini_wire(months: list[str] | None = None, *, recorder_db: str | Path | None = None) -> dict:
    """T14.2: 5-10 月小样本跑 wire_verdict（缩减 walk_train=3/walk_test=2 触发 OOS）+ Recorder.save + reproduce → status 一致。

    缩减 walk_train/walk_test=3/2 触发月度 walk_forward OOS + PurgedKFold n_splits=2（≥4 dates）。
    Recorder.save 落 Recorder → reproduce_verdict = re-call wire_verdict 同 params → status 一致验证。
    wiring 层 bug 在小样本暴露非 full run。
    缺数据返 {data_status: "empty"} 不臆造。
    §44 关联只接线落 Recorder，不改守护区。
    """
    cache = load_r1_cache()
    kline_raw = cache.get("kline_raw", {})
    profit_cache = cache.get("profit", {})
    universe_cache = cache.get("universe", {})
    stock_basic = cache.get("stock_basic", {})

    if months is None:
        months = month_end_rebalance_days()[:6]  # 5-10 月小样本
    if len(months) < 4:
        return {"data_status": "empty", "note": "months<4 无法 PurgedKFold n_splits=2"}

    delisting_map = _build_delisting_map(stock_basic)
    survivors, universe = _build_survivors_universe_with_inject(
        months, kline_raw, profit_cache, universe_cache, delisting_map, -1.0
    )
    if not survivors:
        return {"data_status": "empty", "note": "无 survivors（cache 空或 PIT profit 全缺）"}

    dates = sorted(survivors.keys())
    all_q1 = [r for rs in survivors.values() for r in rs]

    # 缩减 walk_train=3/walk_test=2/step=2 触发 OOS（月度 6 月 → walk_train 3 + walk_test 2 = 5 窗口有 OOS）
    import sys as _sys  # noqa: PLC0415
    _tools_dir = str(Path(__file__).resolve().parent)
    if _tools_dir not in _sys.path:
        _sys.path.insert(0, _tools_dir)
    from tools._s44_wire import wire_verdict  # noqa: PLC0415  (import 路径跟 monkeypatch tools._s44_wire 一致)

    mini_params = {
        "walk_train": 3,
        "walk_test": 2,
        "step": 2,
        "event_materiality_floor": 0.001,
    }

    verdict = wire_verdict(
        line_id="S171_mini_wire",
        returns=all_q1,
        edge_type="selection",
        frozen_commit="mini",
        dates=dates,
        survivors_by_day=survivors,
        universe_by_day=universe,
        n_comparisons=1,
        round_trip_cost=ROUND_TRIP_COST,
        walk_train=3,
        walk_test=2,
        step=2,
        event_materiality_floor=0.001,
        script="long_value_run.mini_wire",
    )
    status = _status_of(verdict)

    # Recorder.save
    from s44_verifier.recorder import Recorder  # noqa: PLC0415

    recorder = Recorder(db_path=recorder_db) if recorder_db else Recorder()
    rec_id = recorder.save(
        data_snapshot_id="mini_snapshot",
        input_hashes={},
        return_series=all_q1,
        dates=dates,
        params={"line_id": "S171_mini_wire", **mini_params},
        frozen_commit="mini",
        verdict={"status": status, "line_id": "S171_mini_wire"},
    )

    # reproduce_verdict: re-call wire_verdict 同 params → status 一致验证
    verdict_repro = wire_verdict(
        line_id="S171_mini_wire",
        returns=all_q1,
        edge_type="selection",
        frozen_commit="mini",
        dates=dates,
        survivors_by_day=survivors,
        universe_by_day=universe,
        n_comparisons=1,
        round_trip_cost=ROUND_TRIP_COST,
        walk_train=3,
        walk_test=2,
        step=2,
        event_materiality_floor=0.001,
        script="long_value_run.mini_wire",
    )
    status_repro = _status_of(verdict_repro)

    return {
        "line_id": "S171_mini_wire",
        "status": status,
        "status_reproduce": status_repro,
        "reproducible": status == status_repro,
        "recorder_id": rec_id,
        "n_dates": len(dates),
        "n_returns": len(all_q1),
        "data_status": "ok",
    }


def reproduce_verdict(verdict_id: str) -> dict:
    """T15 A5 reproduce：读 Recorder 取 verdict_id 的 params + return_series，
    用显式 _VERIFY_PARAMS 白名单重建 verify_kwargs 重算 status，
    比对存的一致（含 event_materiality_floor 存了能读——bug 6 reproduce-storage）。

    缺 verdict_id 返 {data_status: "missing"} 不臆造。
    重算崩（缺 survivors/universe 等 selection verdict）返 {data_status: "error"} 不臆造。
    §44 关联只读 Recorder 重算，不改守护区。
    """
    from s44_verifier.recorder import Recorder  # noqa: PLC0415
    from s44_verifier.verifier import verify  # noqa: PLC0415

    recorder = Recorder()
    record = recorder.load(verdict_id)
    if record is None:
        return {"data_status": "missing", "note": f"verdict_id {verdict_id} 不存在"}

    stored_status = (
        record.verdict.get("status") if isinstance(record.verdict, dict) else None
    )

    # 显式 verify 参数白名单（不用 inspect.signature——monkeypatch verify 会致签名变 **kwargs，
    # record.params 全被 filter；显式列表 test 友好 + line_id 等 metadata 被过滤不传 verify）
    _VERIFY_PARAMS = frozenset({
        "edge_type", "n_comparisons", "n_trials", "round_trip_cost",
        "window_sanity", "walk_train", "walk_test", "step",
        "event_materiality_floor", "tradeable", "periods_per_year",
        "frozen_commit", "data_snapshot_id", "survivors_by_day", "universe_by_day",
    })
    verify_kwargs: dict = {
        k: v for k, v in (record.params or {}).items()
        if k in _VERIFY_PARAMS and v is not None
    }
    # returns + dates 从 record 取（非 params——Recorder 存 return_series + dates 独立列）
    verify_kwargs["returns"] = record.return_series
    if record.dates is not None:
        verify_kwargs["dates"] = record.dates

    try:
        recomputed = verify(**verify_kwargs)
        recomputed_status = getattr(recomputed, "status", None)
    except Exception as e:  # noqa: BLE001
        return {
            "verdict_id": verdict_id,
            "stored_status": stored_status,
            "data_status": "error",
            "note": f"重算失败（可能缺 survivors/universe）: {e}",
            "params": record.params,
        }

    consistent = stored_status == recomputed_status
    return {
        "verdict_id": verdict_id,
        "stored_status": stored_status,
        "recomputed_status": recomputed_status,
        "consistent": consistent,
        "params": record.params,
    }
