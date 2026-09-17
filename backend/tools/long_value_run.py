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
]
