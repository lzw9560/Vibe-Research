# -*- coding: utf-8 -*-
"""pipeline——run_first_board_filter / attach_first_board_analysis 主入口。

实现范围：
- 串联 003-010（数据层 + 三层剔除）→ 011-021 评分排序落盘
- S148 Phase 2 (a)：attach_first_board_analysis 把首板评分接到涨停叉 lane
"""
from __future__ import annotations

import logging
import sys

from strategies.first_board import universe as _universe
from strategies.first_board import exclusions as _exclusions
from strategies.first_board import scoring as _scoring
from strategies.first_board import persistence as _persistence

_logger = logging.getLogger(__name__)


def run_first_board_filter(date: str, pool: list[dict] | None = None) -> dict:
    """主入口：串联 003-010（数据层 + 三层剔除）。

    Args:
        date: 交易日，YYYYMMDD 或 YYYY-MM-DD。
        pool: 可选，注入涨停池（list[dict]）——S148 Phase 2 (a) 接入涨停叉时由调用方
              共享 zt_pool 源传入，跳过自取 fetch_zt_pool（dedup + 让涨停叉 R1 过滤
              覆盖 first-board）。None（默认）→ 自取 fetch_zt_pool（向后兼容）。

    Returns:
        dict 含：
        - date: str（标准化为 YYYYMMDD）
        - zt_pool_count: int（涨停池总数）
        - first_board_count: int（首板数）
        - candidates: list[dict]（通过三层剔除的候选池）
        - excluded: list[dict]（全部剔除记录 [{code, layer, reason}]）
        - env_flags: dict（层3 市场环境标记）
    """
    # 日期标准化
    compact_date = date.replace("-", "") if "-" in date else date

    print(f"[fb_filter] 开始 date={compact_date}", flush=True)

    # 交易日守卫（日期语义完整性 P2）：东财涨停池对非交易日请求静默回退返回
    # 最近交易日数据，导致首板过滤结果标错日期（违反"不臆造数据"底线）。
    # 非交易日 → 直接返回空结果（与 fetch_zt_pool 返空 → 全链路空候选一致），
    # 不打东财、不重复在内部 3 处 em_zt_topic_pool 加守卫（避免散落）。
    # 显式历史交易日照常放行。
    from vr_paths import is_trading_day as _is_trading_day  # noqa: PLC0415
    try:
        from datetime import date as _fb_date
        _parsed = _fb_date.fromisoformat(date) if "-" in date else _fb_date(
            int(compact_date[:4]), int(compact_date[4:6]), int(compact_date[6:8])
        )
    except (ValueError, TypeError):
        _parsed = _fb_date.today()
    if not _is_trading_day(_parsed):
        _logger.warning("run_first_board_filter: 非交易日 %s 跳过 em_zt_topic_pool", compact_date)
        return {
            "date": compact_date,
            "zt_pool_count": 0,
            "first_board_count": 0,
            "candidates": [],
            "scored_candidates": [],
            "excluded": [],
            "env_flags": {},
        }

    # 003 取涨停池（S148 Phase 2 (a)：pool 注入时跳过自取，由调用方共享 zt_pool 源）
    pool = _universe.fetch_zt_pool(compact_date) if pool is None else pool
    zt_pool_count = len(pool)
    print(f"[fb_filter] 涨停池: {zt_pool_count}", flush=True)

    # 004 过滤首板
    first_boards = _universe.filter_first_board(pool)
    first_board_count = len(first_boards)
    print(f"[fb_filter] 首板: {first_board_count}", flush=True)

    excluded: list[dict] = []

    # 007 层1 封板质量
    after_l1, filtered_l1 = _exclusions.exclude_layer1_seal_quality(first_boards)
    excluded.extend(filtered_l1)
    print(f"[fb_filter] 层1剔除: {len(filtered_l1)} 剩余: {len(after_l1)}", flush=True)

    # 008 层2 筹码结构（传 date 取历史 K 线，无未来函数）
    after_l2, filtered_l2 = _exclusions.exclude_layer2_chip_structure(after_l1, compact_date)
    excluded.extend(filtered_l2)
    print(f"[fb_filter] 层2剔除: {len(filtered_l2)} 剩余: {len(after_l2)}", flush=True)

    # 009-010 层3 市场环境
    after_l3, filtered_l3, env_flags = _exclusions.exclude_layer3_market_env(
        after_l2, compact_date, first_boards=first_boards,
    )
    excluded.extend(filtered_l3)
    print(f"[fb_filter] 层3剔除: {len(filtered_l3)} 剩余: {len(after_l3)} "
          f"env={env_flags}", flush=True)

    # 011-021 9 维度评分 + 排序 + 落盘
    print(f"[fb_filter] 开始评分 {len(after_l3)} 只候选...", flush=True)
    scored_candidates = _scoring.rank_candidates(after_l3, compact_date)
    print(f"[fb_filter] 评分完成: {len(scored_candidates)} 只", flush=True)

    result = {
        "date": compact_date,
        "zt_pool_count": zt_pool_count,
        "first_board_count": first_board_count,
        "candidates": after_l3,
        "scored_candidates": scored_candidates,
        "excluded": excluded,
        "env_flags": env_flags,
    }
    try:
        _persistence.save_scores(scored_candidates, compact_date, full_result=result)
        print(f"[fb_filter] 落盘完成", flush=True)
    except Exception as e:
        _logger.warning("save_scores 落盘失败 date=%s err=%s", compact_date, e)

    return result


def attach_first_board_analysis(final_cards: list[dict], target_date: str) -> None:
    """S148 Phase 2 (a)：把首板 9 维评分（load_scores 缓存）接到涨停叉 lane final_candidates。

    首板子集（code 在 cached.scored_candidates）→ card 加 first_board_analysis
    ={scores,total,market_phase}。非首板/缓存空/失败 → 不加（None 降级，不阻断 briefing）。
    §44：total 是未 validated 复合分，前端须标"§44 未 validated"（不作物买卖信号）。
    """
    try:
        compact = target_date.replace("-", "") if "-" in target_date else target_date
        cached = _persistence.load_scores(compact)
        if not cached:
            return
        fb_map = {s.get("code"): s for s in cached.get("scored_candidates", []) if s.get("code")}
        for c in final_cards:
            code = c.get("code")
            if code in fb_map:
                s = fb_map[code]
                c["first_board_analysis"] = {
                    "scores": s.get("scores", {}),
                    "total": s.get("total"),
                    "market_phase": s.get("market_phase"),
                }
    except Exception as e:  # noqa: BLE001 — 9 维是增强，失败不阻断 briefing
        _logger.warning("attach_first_board_analysis 失败 date=%s err=%s", target_date, e)


if __name__ == "__main__":
    # 骨架自测：python -m strategies.first_board_filter 20260818
    d = sys.argv[1] if len(sys.argv) > 1 else "20260818"
    result = run_first_board_filter(d)
    print(f"日期: {result['date']}")
    print(f"涨停池: {result['zt_pool_count']}")
    print(f"首板: {result['first_board_count']}")
    print(f"候选: {len(result['candidates'])}")
    print(f"评分后: {len(result.get('scored_candidates', []))}")
    print(f"剔除: {len(result['excluded'])}")
    print(f"env_flags: {result['env_flags']}")
    print("剔除记录（前 10）:")
    for e in result["excluded"][:10]:
        print(f"  L{e['layer']} {e['code']} {e['reason']}")
    print("评分 TOP 5:")
    for c in result.get("scored_candidates", [])[:5]:
        print(f"  #{c['rank']} {c['code']} {c.get('name','')} total={c['total']:.1f}")
        print(f"    scores: {c['scores']}")
