# -*- coding: utf-8 -*-
"""S024 拓扑展示路由：关系网（候选标的四种边）+ 连板梯队树。

挂 /api/topology/*。
合规 §1（弱合规·工程底线）/ spec A5：拓扑只客观关联，不输出方向结论词；
边基于公开数据（板块/资金流/连板/席位），规则可查、可复现。连板梯队原始
池如实呈现 code/name（公开榜单客观事实）。用户私有数据未进 git；复用现有
em_zt_topic_pool，不新增东财端点。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as _date
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Query

import astock
from vr_paths import is_trading_day, last_trading_date_str
# cache_response 定义在 app.py（cache_response 段之后才 include 本路由）。
# 用守卫 import：app 先加载（生产/uvicorn）时拿到真装饰器；topology 被单独
# import（单测）时触发循环 import，回退到透传装饰器，纯逻辑仍可独立测试。
try:
    from app import cache_response
except (ImportError, AttributeError):  # noqa: BLE001 — 循环 import 回退

    def cache_response(ttl: int = 300):  # type: ignore[no-redef]
        """循环 import 回退：透传装饰器（端点不缓存，仅 standalone 导入场景）。"""
        def deco(func):
            return func
        return deco

from candidate_funnel import funnel as funnel_mod

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/topology", tags=["topology"])

# 边权重上限：共享元素数封顶，避免极端值压垮力导向布局（客观计数，非方向强度）。
_WEIGHT_CAP = 5
# 资金流共流入取最近 N 个交易日（够稳定、不拖慢）。
_FUND_RECENT_DAYS = 20


# ─────────────────────── B1 · EdgeProvider Protocol + 注册表 ───────────────────────


class EdgeProvider(Protocol):
    """关系网边提供者：给定候选标的，返回它们之间的客观关联边。

    边 dict 形如 {source, target, type, weight}；weight 为共享元素计数（封顶），
    不含方向结论。实现须自行捕获数据源异常并返空边，不阻塞其他 provider。
    """

    edge_type: str

    def build_edges(self, candidates: list[dict], *, date: str | None = None) -> list[dict]: ...


_EDGE_PROVIDERS: list[EdgeProvider] = []


def register_edge_provider(provider: EdgeProvider) -> None:
    """注册 EdgeProvider（幂等：同 edge_type 不重复注册）。"""
    if any(getattr(p, "edge_type", None) == provider.edge_type for p in _EDGE_PROVIDERS):
        return
    _EDGE_PROVIDERS.append(provider)


def get_all_edge_providers() -> list[EdgeProvider]:
    """返回全部已注册 EdgeProvider（按注册序）。"""
    return list(_EDGE_PROVIDERS)


# ─────────────────────── B2 · sector：同板块联动 ───────────────────────


class SectorEdgeProvider:
    """同板块联动：候选共享所属概念板块 → sector 边。"""

    edge_type = "sector"

    def build_edges(self, candidates: list[dict], *, date: str | None = None) -> list[dict]:
        return _collect_shared_sets(
            candidates,
            fetch_fn=lambda code, _d: astock.concept_blocks(code, raise_on_failure=True),  # S131 R4.2: 源断 raise→_collect_shared_sets try/except 兜底+log（非静默空 dict 当合法空）
            extract_fn=lambda blocks: set((blocks or {}).get("concept_tags", []) or []),
            edge_type="sector",
            date=date,
            min_shared=2,  # S048 R9：共享概念 ≥2 才连边（<2 噪声过密）
        )


# ─────────────────────── B3 · fund_flow：共流入 ───────────────────────


class FundFlowEdgeProvider:
    """共流入：候选近期同日主力净流入（同向）→ fund_flow 边。"""

    edge_type = "fund_flow"

    def build_edges(self, candidates: list[dict], *, date: str | None = None) -> list[dict]:
        return _collect_shared_sets(
            candidates,
            fetch_fn=lambda code, d: astock.stock_fund_flow_120d(code, date=d),  # S085 A6 残留：传 d 修 replay 误取今日
            extract_fn=lambda flow: {
                r.get("date", "")
                for r in (flow or [])[-_FUND_RECENT_DAYS:]
                if (r.get("main_net") or 0) > 0
            },
            edge_type="fund_flow",
            date=date,
            min_shared=3,  # S048 R9：共享 ≥3 天才连边（<3 偶发同向不构成关联）
        )


# ─────────────────────── B4 · ladder：连板梯队 ───────────────────────


class LadderEdgeProvider:
    """连板梯队：候选同处一个连板高度 → ladder 边；同行业额外加权。"""

    edge_type = "ladder"

    def build_edges(self, candidates: list[dict], *, date: str | None = None) -> list[dict]:
        pool_date = _compact(date or _today_iso())
        # 交易日守卫（日期语义完整性 P2）：东财涨停池对非交易日请求静默回退返回
        # 最近交易日数据，导致边指向错误日期的连板梯队。非交易日 → 空边（与
        # em_zt_topic_pool 异常时 return [] 一致）。显式历史交易日照常放行。
        try:
            parsed = _date.fromisoformat(date) if date else _date.today()
        except ValueError:
            parsed = _date.today()
        if not is_trading_day(parsed):
            logger.warning("ladder provider: 非交易日 %s 跳过 em_zt_topic_pool", parsed.isoformat())
            return []
        try:
            pool = astock.em_zt_topic_pool(
                "getTopicZTPool", pool_date, "fbt:asc", raise_on_failure=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ladder provider: em_zt_topic_pool 失败: %s", exc)
            return []
        # code -> (连板高度, 行业)
        info = {
            str(it.get("c", "")): (it.get("lbc"), it.get("hybk"))
            for it in (pool or [])
        }
        edges: list[dict] = []
        # review fix #11：去重候选 code，否则重复 code 在 i/i+1 配对时产自环边
        # {source:a,target:a}（dict.fromkeys 保序去重，同 build_relation_graph 节点去重范式）。
        cand_codes = list(dict.fromkeys(c.get("code", "") for c in candidates if c.get("code")))
        for i, a in enumerate(cand_codes):
            if a not in info:
                continue
            for b in cand_codes[i + 1:]:
                if b not in info:
                    continue
                a_boards, a_ind = info[a]
                b_boards, b_ind = info[b]
                if a_boards and a_boards == b_boards:
                    same_ind = bool(a_ind and a_ind == b_ind)
                    edges.append({
                        "source": a, "target": b, "type": "ladder",
                        "weight": 2 if same_ind else 1,
                    })
        return edges


# ─────────────────────── B5 · seat：共席位 ───────────────────────


class SeatEdgeProvider:
    """共席位：候选共享龙虎榜营业部 → seat 边。"""

    edge_type = "seat"

    def build_edges(self, candidates: list[dict], *, date: str | None = None) -> list[dict]:
        # review fix #1：透传 trade_date，否则龙虎榜恒取今日（席位永远今天）。
        # 参 LadderEdgeProvider 传 date 范式（dragon_tiger_board(trade_date=date)）。
        return _collect_shared_sets(
            candidates,
            fetch_fn=lambda code, d: astock.dragon_tiger_board(code, trade_date=d),
            extract_fn=lambda board: {
                s.get("name", "")
                for side in ("buy", "sell")
                for s in ((board or {}).get("seats", {}) or {}).get(side, []) or []
                if s.get("name", "")
            },
            edge_type="seat",
            date=date,
        )


# ─────────────────────── 共用工具 ───────────────────────


def _pairwise_shared(code_sets: dict[str, set[str]], edge_type: str, min_shared: int = 1) -> list[dict]:
    """两两候选共享元素 → 边；weight = 共享数（封顶 _WEIGHT_CAP）。

    S048 R9：min_shared 阈值——共享数 <min_shared 不产边（降噪，防 clique 过密）。
    """
    edges: list[dict] = []
    codes = list(code_sets)
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            shared = code_sets[a] & code_sets[b]
            if len(shared) >= min_shared:
                edges.append({
                    "source": a, "target": b, "type": edge_type,
                    "weight": min(len(shared), _WEIGHT_CAP),
                })
    return edges


def _collect_shared_sets(
    candidates: list[dict],
    fetch_fn: "Callable[[str, str | None], Any]",
    extract_fn: "Callable[[Any], set[str]]",
    edge_type: str,
    *,
    date: str | None = None,
    min_shared: int = 1,
) -> list[dict]:
    """通用骨架：逐候选 fetch_fn(code, date) → extract_fn(raw) → 共享集 → 两两配对成边。

    Sector/FundFlow/Seat 三 provider 同骨架：遍历候选取数、extract 为共享集、
    再 _pairwise_shared 配对。单候选取数抛错 → 记空集、不阻塞其他候选（原隔离语义）。
    fetch_fn 接收 (code, date)；忽略 date 的 provider 在闭包内弃用 _d 即可。
    LadderEdgeProvider 逻辑不同（同高度配对+行业加权），保持独立不并入本骨架。
    S048 R9：min_shared 透传 _pairwise_shared（sector=2 / fund_flow=3 / seat=1 默认）。
    """
    code_sets: dict[str, set[str]] = {}
    for c in candidates:
        code = c.get("code", "")
        if not code:
            continue
        try:
            raw = fetch_fn(code, date)
        except Exception as exc:  # noqa: BLE001 — 单候选数据源失败不阻塞其他候选
            logger.warning("%s provider: 取数(%s) 失败: %s", edge_type, code, exc)
            code_sets[code] = set()
            continue
        code_sets[code] = extract_fn(raw)
    return _pairwise_shared(code_sets, edge_type, min_shared=min_shared)


def _today_iso() -> str:
    # S149 修复：默认 pool/funnel date 用最近交易日（非今日）——周末/节假日/盘前
    # 今日无 zt 池→run_funnel 0 候选→关系图/梯队树空。改 last_trading_date_str 后
    # 自动回退最近交易日（有数据）。3 个 call site（126/324/380）一并生效。
    return last_trading_date_str()


def _compact(iso_date: str) -> str:
    """ISO(YYYY-MM-DD) → YYYYMMDD（em_zt_topic_pool 期望紧凑日期）。"""
    return iso_date.replace("-", "") if "-" in iso_date else iso_date


# ─────────────────────── B6 · relation 聚合 ───────────────────────


# S048 R9：每节点度数封顶（贪心按 weight 降序保留，两端任一超限即弃）。
_MAX_DEGREE = 4


def _cap_degree(edges: list[dict], max_degree: int = _MAX_DEGREE) -> list[dict]:
    """S048 R9：每节点边数封顶 max_degree——贪心按 weight 降序保留。

    同 weight 保持 provider 产出原序（sorted 稳定）；两端点当前度数均
    <max_degree 才保留该边，否则弃（杜绝 hub 节点 clique 爆炸）。
    """
    degree: dict[str, int] = {}
    kept: list[dict] = []
    for e in sorted(edges, key=lambda e: -(e.get("weight") or 0)):
        s, t = e.get("source", ""), e.get("target", "")
        if degree.get(s, 0) < max_degree and degree.get(t, 0) < max_degree:
            kept.append(e)
            degree[s] = degree.get(s, 0) + 1
            degree[t] = degree.get(t, 0) + 1
    return kept


def build_relation_graph(
    candidates: list[dict],
    providers: list[EdgeProvider] | None = None,
    date: str | None = None,
) -> dict:
    """聚合各 provider → GraphData{nodes,edges}。节点=候选去重，边=客观关联。

    单个 provider 抛错则跳过该 provider，不阻塞整体（隔离故障）。
    S048 R9：聚合后经 _cap_degree 封顶每节点边数（_MAX_DEGREE=4）。
    """
    # 节点去重（按 code）
    seen: set[str] = set()
    nodes: list[dict] = []
    for c in candidates:
        code = c.get("code", "")
        if not code or code in seen:
            continue
        seen.add(code)
        nodes.append({
            "id": code,
            "name": c.get("name") or code,
            "code": code,
            "category": "candidate",
        })

    edges: list[dict] = []
    for p in (providers if providers is not None else get_all_edge_providers()):
        try:
            edges.extend(p.build_edges(candidates, date=date))
        except Exception as exc:  # noqa: BLE001 — 单 provider 故障隔离
            logger.warning("relation: provider %s 失败: %s", getattr(p, "edge_type", "?"), exc)
    return {"nodes": nodes, "edges": _cap_degree(edges)}


# ─────────────────────── D1 · board-ladder 梯队树 ───────────────────────


def build_board_ladder_tree(date: str | None = None) -> dict:
    """em_zt_topic_pool 涨停池 → 梯队树：根=当日涨停，按连板高度分层，同题材归枝。

    树形：{name, children:[{name:"N板", children:[{name:题材, children:[{name,code,value}]}]}]}
    叶节点如实呈现 code/name（公开榜单客观事实）。
    """
    pool_date = _compact(date or _today_iso())
    # 交易日守卫（日期语义完整性 P2）：东财涨停池对非交易日请求静默回退返回
    # 最近交易日数据，导致梯队树标错日期。非交易日 → 空树（与 em_zt_topic_pool
    # 异常时 pool=[] 最终返回 {"name":"当日涨停","children":[]} 一致）。
    # 显式历史交易日照常放行（用户手动选历史日查梯队是合法场景）。
    try:
        parsed = _date.fromisoformat(date) if date else _date.today()
    except ValueError:
        parsed = _date.today()
    if not is_trading_day(parsed):
        logger.warning("board-ladder: 非交易日 %s 跳过 em_zt_topic_pool", parsed.isoformat())
        return {"name": "当日涨停", "children": []}
    try:
        pool = astock.em_zt_topic_pool(
            "getTopicZTPool", pool_date, "fbt:asc", raise_on_failure=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("board-ladder: em_zt_topic_pool 失败: %s", exc)
        pool = []
    # lbc(连板数) → hybk(行业) → 个股列表
    by_height: dict[int, dict[str, list[dict]]] = {}
    for it in pool or []:
        code = str(it.get("c", ""))
        if not code:
            continue
        lbc = int(it.get("lbc") or 1)
        ind = it.get("hybk") or "未分类"
        by_height.setdefault(lbc, {}).setdefault(ind, []).append({
            "name": f"{code} {it.get('n', '')}".strip(),
            "code": code,
            "value": lbc,
        })
    # 高连板层在前
    height_children = []
    for lbc in sorted(by_height, reverse=True):
        ind_children = [
            {"name": ind, "children": stocks}
            for ind, stocks in sorted(by_height[lbc].items())
        ]
        height_children.append({"name": f"{lbc}板", "children": ind_children})
    return {"name": "当日涨停", "children": height_children}


# ─────────────────────── 漏斗候选加载 ───────────────────────


def _load_candidates(date: str | None) -> list[dict]:
    """跑漏斗取定稿候选 → [{code,name}]。节点来源=漏斗定稿池（去重）。

    review fix #2：复用 candidates 路由的运行时 _store["config"]（用户调参后的
    live config），而非本地 _default_config()——否则关系图用默认 config、候选页用
    调参后 config，会分裂成两套候选池。lazy import 避免模块加载期 import 环
    （candidates.py 顶部 from app import cache_response 无回退，topology 单独
    导入时若硬 import 会触发 app 部分加载循环）。
    """
    from routers.candidates import _store  # noqa: PLC0415 — 防 import 环，运行时取 live config
    result = funnel_mod.run_funnel("all", date or _today_iso(), _store["config"])
    return [{"code": c.code, "name": c.name} for c in result.final_candidates]


# ─────────────────────── 注册 4 个核心 provider ───────────────────────

register_edge_provider(SectorEdgeProvider())
register_edge_provider(FundFlowEdgeProvider())
register_edge_provider(LadderEdgeProvider())
register_edge_provider(SeatEdgeProvider())


# ─────────────────────── HTTP 端点 ───────────────────────


@router.get("/relation")
@cache_response(ttl=60)
async def get_relation(date: str | None = Query(default=None, description="ISO 日期，默认今日")):
    """关系网 GraphData：节点=候选标的（漏斗定稿池去重），边=各 provider 客观关联聚合。

    合规：只呈现客观关联，不含方向结论。
    """
    candidates = await asyncio.to_thread(_load_candidates, date)
    # review fix HIGH-1：build_relation_graph 内 O(N) em_get 阻塞 → to_thread 释放事件循环（同 :334/:345，防 freeze 回归）
    return await asyncio.to_thread(build_relation_graph, candidates, providers=get_all_edge_providers(), date=date)


@router.get("/board-ladder")
@cache_response(ttl=300)
async def get_board_ladder(date: str | None = Query(default=None, description="ISO 日期，默认今日")):
    """连板梯队树：em_zt_topic_pool 涨停池，按连板高度分层，同题材归枝。

    如实呈现 code/name（公开榜单客观事实）。
    """
    return await asyncio.to_thread(build_board_ladder_tree, date)
