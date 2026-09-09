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
from strategies.first_board.scoring import (
    score_dim_seal_time,
    score_dim_sector_link,
    score_dim_market_cap,
    score_dim_seal_ratio,
    score_dim_turnover,
    score_dim2_hot_money,
    score_dim4_chip,
    score_dim7_institution,
    score_dim8_theme,
    score_dim9_event,
    score_dim5_auction,
    score_dim6_northbound,
)
from strategies.first_board.universe import MARKET_PHASE_WEIGHTS, _market_phase, _emotion

_logger = logging.getLogger(__name__)


# 维度函数映射表（score_candidate 用）。
# grill 收紧：5 核心维度（seal_time/sector_link/market_cap/seal_ratio/turnover）
# + 保留 5 旧维度 + 废弃 2 维度（auction/northbound 返 -1 不参与加权）。
_SCORE_DIMS = [
    ("seal_time", score_dim_seal_time),       # 核心：封板时间
    ("sector_link", score_dim_sector_link),   # 核心：板块联动
    ("market_cap", score_dim_market_cap),     # 核心：市值
    ("seal_ratio", score_dim_seal_ratio),     # 核心：封单比
    ("turnover", score_dim_turnover),         # 核心：换手率（grill 收紧：换手改评分）
    ("hot_money", score_dim2_hot_money),      # 保留：游资画像
    ("chip", score_dim4_chip),                # 保留：筹码结构
    ("institution", score_dim7_institution),  # 保留：龙虎榜机构
    ("theme", score_dim8_theme),              # 保留：题材热度
    ("event", score_dim9_event),              # 保留：事件评分
    # 废弃（数据缺失，返 -1 不参与加权）：
    ("auction", score_dim5_auction),          # 竞价（T-1 盘后无数据→-1）
    ("northbound", score_dim6_northbound),    # 北向（2024-08-19 后停更→-1）
]


def score_candidate(candidate: dict, date: str, market_phase: str = "普通") -> dict:
    """评分——权重按市场状态分层，数据缺失维度不参与加权。

    grill 锁定决策：
    - 权重按 zt_count 4 档分层（冰点/普通/活跃/亢奋），见 MARKET_PHASE_WEIGHTS；
    - 数据缺失维度 score=-1 不参与加权，权重重分配到其他有效维度
      （weighted_sum / active_weight_sum 归一化）；
    - 保留维度（hot_money/chip/institution/theme/event）权重固定 0，
      不参与分层加权（grill 决策：核心 4 维度 seal_time/sector_link/market_cap/seal_ratio
      参与分层，其余维度作辅助参考不参与 total 加权——待回测校准后调整）。

    Args:
        candidate: filter_first_board 产出的候选 dict。
        date: YYYYMMDD。
        market_phase: 市场档位 "冰点"/"普通"/"活跃"/"亢奋"。

    Returns:
        dict 含 code/name/scores/raw_values/total/rank/market_phase。
    """
    phase_weights = MARKET_PHASE_WEIGHTS.get(market_phase, MARKET_PHASE_WEIGHTS["普通"])

    scores: dict = {}
    raw_values: dict = {}
    weighted_sum = 0.0
    active_weight_sum = 0.0  # 有效权重和（排除数据缺失维度）

    for dim_name, dim_fn in _SCORE_DIMS:
        result = dim_fn(candidate, date)
        # 兼容旧签名（只返 float）和新签名（返 tuple）
        if isinstance(result, tuple):
            score, raw = result
        else:
            score, raw = float(result), {}
        # 钳制 -1 到 100（-1=数据缺失）
        score = max(-1.0, min(100.0, score))
        scores[dim_name] = score
        raw_values[dim_name] = raw

        # 数据缺失（score=-1）不参与加权；有效维度按分层权重加权
        if score >= 0 and dim_name in phase_weights:
            weight = phase_weights[dim_name]
            weighted_sum += score * weight
            active_weight_sum += weight

    # 重分配：有效权重和归一化
    total = weighted_sum / active_weight_sum if active_weight_sum > 0 else 50.0

    return {
        "code": candidate.get("code", ""),
        "name": candidate.get("name", ""),
        "scores": scores,
        "raw_values": raw_values,
        "total": round(total, 1),
        "rank": 0,  # rank_candidates 填
        "market_phase": market_phase,
    }


def rank_candidates(candidates: list[dict], date: str) -> list[dict]:
    """按总分降序排序 + 按板块分组（主板在前，创业板在后）。

    grill 决策：不截断——全部候选展示。权重按 zt_count 市场档位分层。

    Args:
        candidates: 通过三层剔除的候选 list[dict]。
        date: YYYYMMDD。

    Returns:
        list[dict]，每项含 scores+total+rank（1-based，分组排序后连续）+board_type
        +market_phase。

    排序规则：
    - 主板（60/00 开头）在前，创业板（300/301 开头）在后，其他最后；
    - 每组内按 total 降序；
    - rank 从 1 开始连续编号（不分段重置，整体连续）。

    进度日志：每 5 只打一条进度（flush=True，后台跑实时输出）。
    兜底：单只 score_candidate 失败 try/except 跳过（不进 scored，不阻塞整批）。
    """
    # 取 zt_count 判定市场档位（用于权重分层）
    try:
        emotion = _emotion(date) or {}
        zt_count = emotion.get("zt_count")
    except Exception as e:
        _logger.warning("rank_candidates _emotion 取 zt_count 失败 err=%s", e)
        zt_count = None
    phase = _market_phase(zt_count)
    print(f"[fb_filter] 市场档位: {phase}（zt_count={zt_count}）", flush=True)

    scored: list[dict] = []
    n = len(candidates)
    for i, c in enumerate(candidates):
        if i % 5 == 0 or i == n - 1:
            print(f"[fb_filter] 评分进度: {i}/{n} code={c.get('code')}", flush=True)
        try:
            scored.append(score_candidate(c, date, phase))
        except Exception as e:
            _logger.warning("score_candidate 失败 code=%s err=%s", c.get("code"), e)
    print(f"[fb_filter] 评分进度: {n}/{n} 完成", flush=True)

    # 标记板块类型
    for s in scored:
        code = s.get("code", "")
        if code.startswith(("300", "301")):
            s["board_type"] = "创业板"
        elif code.startswith(("60", "00")):
            s["board_type"] = "主板"
        else:
            s["board_type"] = "其他"

    # 按板块分组+组内降序：主板(0) 在前，创业板(1) 在后，其他(2) 最后
    _board_order = {"主板": 0, "创业板": 1, "其他": 2}
    scored.sort(key=lambda x: (_board_order.get(x["board_type"], 9), -x["total"]))

    # rank 从 1 开始连续编号（整体连续，不分段重置）
    for i, s in enumerate(scored):
        s["rank"] = i + 1

    # P70 分位精选池（grill 收紧：评分前 30% 标"精选"，后 70% 标"观察"）
    if len(scored) >= 3:
        # 前 30% 的最后一个 index（向下取整，至少 1 只精选）
        cutoff_idx = max(1, int(len(scored) * 0.3)) - 1
        cutoff_score = scored[cutoff_idx]["total"]
        for s in scored:
            s["pool_type"] = "精选" if s["total"] >= cutoff_score else "观察"
    else:
        # 候选<3 只时全部精选
        for s in scored:
            s["pool_type"] = "精选"
    print(f"[fb_filter] 精选池: {sum(1 for s in scored if s.get('pool_type')=='精选')}/{len(scored)}", flush=True)

    return scored


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
    scored_candidates = rank_candidates(after_l3, compact_date)
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
