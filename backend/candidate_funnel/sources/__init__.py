# -*- coding: utf-8 -*-
"""candidate_funnel 各来源采集器。

统一约定：
- R1 宽源（gene/board_ladder）以 date 为入参产出全市场片段。
- R2/R3 富集（activity/fund_flow/auction/catalyst）以 codes + as_of 为入参。
- 东财端点一律经 astock.em_get 限流（AC7）；缺失项记入 missing 不补全（AC6）。
"""

from . import (  # noqa: F401  显式绑定子模块，便于 funnel 与测试按 sources.<name> 访问
    _filters,
    activity,
    auction,
    board_ladder,
    catalyst,
    fund_flow,
    gene,
    watchlist_in,
)
