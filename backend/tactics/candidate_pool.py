# -*- coding: utf-8 -*-
"""candidate_pool —— 竞价候选池生成（S235 T15）。

盘前 08:30 生成 <200 只候选池，09:20 只拉候选池的竞价数据（全市场 5000 只不可行）。
口径：盘前快照（A 股未开盘，price_change_ratio_pct = 前日涨跌幅）筛跌幅 > 5%。

⚠️ 当前仅实现"跌幅 > 5%"维度。spec §5.1 还提"炸板/连板断板"，需 zt_history 接入，
   Phase B T15 完整版补（标记 TODO）。

纯函数：接受 all_stocks 列表（调用方用 get_market_snapshot_all 取数），返回 thscode 列表。
   不直接调 CLI，便于 fixture 测试。
"""

from __future__ import annotations

# 候选池跌幅门槛（spec §2.2：前日跌 > 5%）
DROP_THRESHOLD = -5.0
# 候选池上限（spec §5.1：<200 只，2 批×100 竞价拉取）
MAX_CANDIDATES = 200


def generate_auction_candidates(
    all_stocks: list[dict],
    max_n: int = MAX_CANDIDATES,
    drop_threshold: float = DROP_THRESHOLD,
) -> list[str]:
    """从全市场快照筛竞价候选池。

    Args:
        all_stocks: 全市场快照（list[dict]，每项含 thscode + price_change_ratio_pct）。
        max_n: 上限（默认 200）。
        drop_threshold: 跌幅门槛（默认 -5，即跌 5%）。

    Returns:
        thscode 列表，跌幅最大的在前，截 max_n。

    盘前 08:30 调用时，A 股未开盘，快照 price_change_ratio_pct = 前日涨跌幅
    （spec §5.1 注释"从前日 K 线筛选"与此一致）。
    """
    candidates: list[tuple[str, float]] = []
    for s in all_stocks:
        code = s.get("thscode")
        chg = s.get("price_change_ratio_pct")
        if code is None or chg is None:
            continue
        try:
            chg_f = float(chg)
        except (TypeError, ValueError):
            continue
        if chg_f < drop_threshold:
            candidates.append((str(code), chg_f))
    # 跌幅最大的在前（chg 最负在前 = 升序）
    candidates.sort(key=lambda x: x[1])
    return [c[0] for c in candidates[:max_n]]


# TODO Phase B：加 count_zhaban（炸板，从 zt_history 取 limit-break-pool）
# TODO Phase B：加 count_lianban_duan（连板断板，从 zt_history 取 lbc 断板）
# 完整版 generate_auction_candidates 应并集（跌幅>5% ∪ 炸板 ∪ 连板断板）截 200。
