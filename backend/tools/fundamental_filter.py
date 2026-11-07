"""基本面过滤（P0-4 部分接，用户 2026-10-12 拍板只接应收）。

应收/营收>=40% 过滤（新浪三表 fetch_merged_periods）。
商誉/质押/减持 待新源（标 TODO，hithink/value_funnel 无现成字段）。

关联：specs/S236 / specs/S237 / 基本面专家审查
"""

from data.sources.sina_financial import fetch_merged_periods

RECEIVABLE_THRESHOLD = 0.40  # 应收/营收>=40% 过滤（用户最初 prompt 红线）


def filter_receivable(codes: list[str]) -> dict:
    """批量过滤应收/营收>=40%的票。返回 {code: ratio_or_None}。

    ratio>=0.4 的应过滤掉；None=无数据不滤（不臆造）。
    """
    result: dict = {}
    for code in codes:
        try:
            periods = fetch_merged_periods(code)
            if not periods:
                result[code] = None
                continue
            p = periods[0]
            ar = getattr(p, "accounts_receivable", None)
            rev = getattr(p, "revenue", None) or getattr(p, "operating_revenue", None)
            if ar and rev and rev > 0:
                result[code] = ar / rev
            else:
                result[code] = None
        except Exception:
            result[code] = None
    return result


def passes_receivable(code: str) -> tuple[bool, float | None]:
    """单只票应收过滤。返回 (passes, ratio)。

    passes=True 若 ratio<40% 或无数据（不滤）；False 若 ratio>=40%。
    """
    r = filter_receivable([code])
    ratio = r.get(code)
    if ratio is None:
        return True, None  # 无数据不滤（不臆造）
    return ratio < RECEIVABLE_THRESHOLD, ratio


# TODO: 商誉/净资产>=15%（新浪三表无现成字段，待 akshare/东财 datacenter 接）
# TODO: 大股东质押>=50%（无现成源，待接）
# TODO: 近90天减持公告（无现成源，待接）
# 用户2026-10-12拍板：只接应收，商誉/质押/减持标 TODO 盲区
