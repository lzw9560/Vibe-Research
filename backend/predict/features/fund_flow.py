"""Fund-flow feature specs — S018 fund-flow (hot-money) group.

Hot-money / capital-flow features: main-net accumulation, dragon-tiger relay,
seal-fund strength, northbound segmented, margin balance, sector rotation,
block-trade discount.

All data sourced via astock.em_get (East Money push2, em_get throttled).
Pure computation functions have no side effects and no network access.

TODO: live fetchers (em_get calls) wired during S008 migration.
"""

from __future__ import annotations

import astock  # 数据门面；fetcher 经 astock.eastmoney_datacenter 走 em_get 限流（防封底线）

from predict.features.registry import FeatureSpec, Registry


# ── Module-level immutable spec declarations ────────────────────────

FUND_FLOW_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="main_net_5d",
        source="astock.em_get",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description="主力净流入5日累计，T+1后(S1)公布",
    ),
    FeatureSpec(
        name="dt_hot_money_relay",
        source="astock.em_get",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description="龙虎榜游资接力频次（聚合，不依赖个体席位标签），T+1旑后(S1)公布",
    ),
    FeatureSpec(
        name="seal_fund_strength",
        source="limitup_sti",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="aggregate_only",
        description="涨停封板资金强度（封单/流通市值比，来自涨停四池聚合），T+1旑后(S1)公布",
    ),
    FeatureSpec(
        name="northbound_net_segmented",
        source="astock.em_get",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description="北向净流入分段（2024-08-19规则变更前后），T+1旑后(S1)公布",
    ),
    FeatureSpec(
        name="margin_balance_change",
        source="astock.em_get",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description="融资余额变化，T+1旑后(S1)公布",
    ),
    FeatureSpec(
        name="sector_flow_rotation",
        source="astock.em_get",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description="板块资金净流入排名与轮动速度，T+1旑后(S1)公布",
    ),
    FeatureSpec(
        name="block_trade_discount",
        source="astock.em_get",
        category="fund_flow",
        availability_offset=1,
        stage="s1",
        compliance_flag="ok",
        description="大宗交易折价率，T+1旑后(S1)公布",
    ),
)


# ── Registration ────────────────────────────────────────────────────

def register_fund_flow(registry: Registry) -> None:
    """Register all fund-flow FeatureSpecs into the given Registry.

    Raises:
        KeyError: If any feature name is already registered.
    """
    for spec in FUND_FLOW_SPECS:
        registry.register(spec)


# ── Pure computation (no side effects, no network) ──────────────────

def accumulate_main_net(daily_main_nets: list[float | None]) -> float | None:
    """Sum the non-None daily main net inflows over the last 5 days.

    Parameters
    ----------
    daily_main_nets:
        List of daily main net inflow values (float or None).

    Returns
    -------
    float | None
        Sum of all non-None values, or None if the list is empty or
        all values are None.
    """
    valid = [v for v in daily_main_nets if v is not None]
    if not valid:
        return None
    return sum(valid)


class NorthFlowSegmenter:
    """Segment north-bound capital flow by the 2024 rule-change date.

    The rule change on 2024-08-19 cancelled real-time north-bound
    quota display. Before the change real-time net inflow was
    available; after the change only post-close net inflow is usable.
    """

    RULE_CHANGE_DATE = "2024-08-19"

    def segment(self, date: str) -> str:
        """Return the segment label for *date*.

        Returns
        -------
        str
            "pre_change"  – before or on the rule-change date (but the
            change-day itself is treated as post_change for safety).
            "post_change" – on or after the rule-change date.
        """
        if date >= self.RULE_CHANGE_DATE:
            return "post_change"
        return "pre_change"

    def is_realtime_allowed(self, date: str) -> bool:
        """Return whether real-time north-bound data was allowed on *date*."""
        return date < self.RULE_CHANGE_DATE

    def can_cross_segment(self, date1: str, date2: str) -> bool:
        """Return True if *date1* and *date2* belong to the same segment.

        This guards against fitting models across the rule-change boundary.
        """
        return self.segment(date1) == self.segment(date2)


def sector_rotation_speed(
    sectors_today: list[dict] | None,
    sectors_prev: list[dict] | None,
) -> float | None:
    """Measure sector rotation speed via rank-change absolute sum.

    Parameters
    ----------
    sectors_today:
        List of sector dicts (shape from market._sectors):
        each dict must contain ``name`` (str) and ``net`` (float).
    sectors_prev:
        Same shape as *sectors_today* for the previous trading day.

    Returns
    -------
    float | None
        Sum of absolute rank differences between today and yesterday.
        Returns None when inputs are None, empty, or sector sets mismatch.
    """
    if sectors_today is None or sectors_prev is None:
        return None
    if not sectors_today or not sectors_prev:
        return None

    today_names = {s["name"] for s in sectors_today}
    prev_names = {s["name"] for s in sectors_prev}
    if today_names != prev_names:
        return None

    # Rank by net descending (most positive net = rank 1).
    # net may be None per the Sector contract — coalesce to 0.0 so
    # sorted() never compares None against float (would raise TypeError).
    def _net(s: dict) -> float:
        v = s.get("net")
        return v if isinstance(v, (int, float)) else 0.0

    today_sorted = sorted(sectors_today, key=_net, reverse=True)
    prev_sorted = sorted(sectors_prev, key=_net, reverse=True)

    today_rank = {s["name"]: i for i, s in enumerate(today_sorted)}
    prev_rank = {s["name"]: i for i, s in enumerate(prev_sorted)}

    total_diff = 0.0
    for name in today_rank:
        total_diff += abs(today_rank[name] - prev_rank[name])

    return total_diff


# ── Live fetchers（S044 补 S018 R11 TODO）──────────────────────────────────

def fetch_northbound(code: str, date: str | None = None) -> float | None:
    """个股北向净流入（万元，盘后可得）。S044 R1。

    走 astock.eastmoney_datacenter（datacenter 端点，em_get 限流防封），reportName
    RPT_MUTUAL_HOLDSTOCKNDATE_STA（沪深港通持股明细），取 HMC_CHANGE（持股市值变化=北向净流入,元）→ 万元。

    2024-08-19 北向规则变更后个股日级北向数据停更（见 NorthFlowSegmenter.RULE_CHANGE_DATE）：
    近期日期（post-change）取不到行 → 返 None（missing 保留，spec §9 回退），不臆造数值。
    历史 backfill（pre-change）有数据。date 给定取对应日，None 取最新行。

    availability_offset=1（T+1 盘后公布，见 northbound_net_segmented FeatureSpec）。
    """
    try:
        rows = astock.eastmoney_datacenter(
            "RPT_MUTUAL_HOLDSTOCKNDATE_STA",
            filter_str=f'(SECURITY_CODE="{code}")(INTERVAL_TYPE="1")',
            page_size=500, sort_columns="TRADE_DATE", sort_types="-1")
    except Exception:
        return None
    if not rows:
        return None
    if date:
        target = date[:10]
        row = next((r for r in rows if str(r.get("TRADE_DATE", ""))[:10] == target), None)
    else:
        row = rows[0]  # sort TRADE_DATE desc → 首行最新
    if not row:
        return None
    val = row.get("HMC_CHANGE")
    if val is None:
        return None
    try:
        return round(float(val) / 10000.0, 1)  # 元 → 万元
    except (TypeError, ValueError):
        return None


def fetch_dt_hot_money_relay(code: str, date: str | None = None, look_back: int = 30) -> float | None:
    """龙虎榜游资席位接力强度（万元，聚合，不输出个体席位名）。S044 R4。

    走 astock.eastmoney_datacenter（datacenter，em_get 防封）：RPT_BILLBOARD_DAILYDETAILSBUY/SELL
    取 look_back 日内该股所有上榜日买卖席位明细，聚合席位出现频次——同一 OPERATEDEPT_NAME
    在 >=2 个交易日出现 = 接力型席位，返回接力型席位净买入额合计（万元）。
    合规：只输出聚合强度，不输出个体席位名（S018 R11：个体席位标签 alpha 已衰减，只用聚合频次）。
    无上榜记录 → None（missing）；有上榜但无接力席位 → 0.0。availability_offset=1（T+1 盘后公布）。
    """
    from datetime import datetime, timedelta
    ref = date or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(ref, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")
    flt = f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{ref}\')'
    try:
        buy = astock.eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=flt, page_size=200, sort_columns="TRADE_DATE", sort_types="-1")
        sell = astock.eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=flt, page_size=200, sort_columns="TRADE_DATE", sort_types="-1")
    except Exception:
        return None
    rows = list(buy or []) + list(sell or [])
    if not rows:
        return None
    seat_dates: dict[str, dict[str, float]] = {}
    for r in rows:
        name = (r.get("OPERATEDEPT_NAME") or "").strip()
        if not name:
            continue
        d = str(r.get("TRADE_DATE", ""))[:10]
        try:
            net = float(r.get("NET")) if r.get("NET") is not None else 0.0
        except (TypeError, ValueError):
            net = 0.0
        seat_dates.setdefault(name, {})[d] = seat_dates.get(name, {}).get(d, 0.0) + net
    relay_total = 0.0
    has_relay = False
    for dates in seat_dates.values():
        if len(dates) >= 2:
            has_relay = True
            relay_total += sum(dates.values())
    if not has_relay:
        return 0.0
    return round(relay_total / 10000.0, 1)  # 元 → 万元


# 东财 push2 端点公开 token（缺则 push2 clist/slist 返空或断连——根因非端点宕，是 astock 旧函数缺 ut）
_EM_PUSH2_UT = "fa5fd1943c7b386f172d6893dbbd1"


def fetch_sector_flow(code: str, date: str | None = None) -> float | None:
    """个股所属行业板块当日主力净流入（万元）。S044 R2。

    走 astock.em_get push2 clist(fid=f62, ut=...) 取行业板块主力净流入（东财 push2 端点需 ut token，
    旧 astock.concept_blocks/stock_fund_flow_120d 缺 ut 故返空/断连——根因非端点宕）；个股行业经
    astock.individual_info 取；行业名匹配 clist f14 → f62(元)→万元。取不到（行业/匹配/端点限流）→ None(missing)。
    """
    try:
        info = astock.individual_info(code) or {}
    except Exception:
        return None
    industry = (info.get("行业") or "").strip() if isinstance(info, dict) else ""
    if not industry:
        return None
    try:
        r = astock.em_get("https://push2.eastmoney.com/api/qt/clist/get",
            params={"fid": "f62", "po": "1", "pz": "200", "pn": "1",
                    "fs": "m:90+t:2+f:!50", "fields": "f12,f14,f62", "ut": _EM_PUSH2_UT},
            timeout=15)
        d = r.json()
    except Exception:
        return None
    diff = (d.get("data") or {}).get("diff") or {}
    items = list(diff.values()) if isinstance(diff, dict) else (diff or [])
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("f14", "")).strip() == industry:
            f62 = it.get("f62")
            try:
                return round(float(f62) / 10000.0, 1)  # 元 → 万元
            except (TypeError, ValueError):
                return None
    return None
