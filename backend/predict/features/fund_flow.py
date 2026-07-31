"""Fund-flow feature specs — S018 fund-flow (hot-money) group.

Hot-money / capital-flow features: main-net accumulation, dragon-tiger relay,
seal-fund strength, northbound segmented, margin balance, sector rotation,
block-trade discount.

All data sourced via astock.em_get (East Money push2, em_get throttled).
Pure computation functions have no side effects and no network access.

TODO: live fetchers (em_get calls) wired during S008 migration.
"""

from __future__ import annotations

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
