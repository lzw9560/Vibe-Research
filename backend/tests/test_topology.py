# -*- coding: utf-8 -*-
"""S024 拓扑展示后端单测（离线）：EdgeProvider 注册表 + 4 provider + relation 聚合 + board-ladder 树。

TDD 红→绿。全离线：mock astock 数据源，不发网络。
合规 §1/A5：拓扑只客观关联，断言无方向结论词；连板梯队原始池如实呈现 code/name。
"""
from __future__ import annotations

import inspect

import pytest

from routers import topology
from routers.topology import (
    FundFlowEdgeProvider,
    LadderEdgeProvider,
    SeatEdgeProvider,
    SectorEdgeProvider,
    build_board_ladder_tree,
    build_relation_graph,
    get_all_edge_providers,
    register_edge_provider,
)

# ── 测试用候选（节点=候选标的，去重） ──
_CANDIDATES = [
    {"code": "600519", "name": "贵州茅台"},
    {"code": "000858", "name": "五粮液"},
    {"code": "300750", "name": "宁德时代"},
]


# ─────────────────────────── B1 · 注册表 ───────────────────────────


@pytest.fixture
def restore_providers():
    """快照/还原全局 _EDGE_PROVIDERS，防注册污染跨测试。"""
    saved = list(topology._EDGE_PROVIDERS)
    yield
    topology._EDGE_PROVIDERS[:] = saved


class _FakeProvider:
    """假 EdgeProvider：恒返一条 fake 边。"""

    edge_type = "fake"

    def build_edges(self, candidates, *, date=None):
        return [{"source": "a", "target": "b", "type": "fake", "weight": 1}]


def test_default_providers_registered(restore_providers):
    """模块加载即注册 4 个核心 provider。"""
    types = {p.edge_type for p in get_all_edge_providers()}
    assert {"sector", "fund_flow", "ladder", "seat"} <= types


def test_register_idempotent(restore_providers):
    """同 edge_type 重复注册不重复入表（幂等）。"""
    before = len(get_all_edge_providers())
    register_edge_provider(_FakeProvider())
    assert len(get_all_edge_providers()) == before + 1
    register_edge_provider(_FakeProvider())  # 同 edge_type 再注册
    assert len(get_all_edge_providers()) == before + 1


# ─────────────────────────── B2 · sector provider ───────────────────────────


def test_sector_provider_same_concept(monkeypatch):
    """两候选共享概念板块 → sector 边，权重=共享概念数。"""
    monkeypatch.setattr(
        topology.astock,
        "concept_blocks",
        lambda code: {
            "600519": {"concept_tags": ["白酒", "消费", "机构重仓"]},
            "000858": {"concept_tags": ["白酒", "消费"]},
            "300750": {"concept_tags": ["新能源"]},
        }[code],
    )
    edges = SectorEdgeProvider().build_edges(_CANDIDATES)
    sector_edges = [e for e in edges if e["type"] == "sector"]
    # 600519-000858 共享 白酒+消费 → weight=2
    pair = {e["source"] for e in sector_edges} | {e["target"] for e in sector_edges}
    assert "600519" in pair and "000858" in pair
    assert any(e["weight"] == 2 for e in sector_edges)
    # 300750 无共享概念 → 不出现
    assert not any("300750" in (e["source"], e["target"]) for e in sector_edges)


def test_sector_provider_resilient_on_error(monkeypatch):
    """concept_blocks 抛错 → 返空边 + 不阻塞（无异常上抛）。"""
    def _boom(code):
        raise RuntimeError("network down")

    monkeypatch.setattr(topology.astock, "concept_blocks", _boom)
    edges = SectorEdgeProvider().build_edges(_CANDIDATES)
    assert edges == []


def test_sector_provider_empty_when_no_tags(monkeypatch):
    """concept_blocks 返空概念标签 → 无边。"""
    monkeypatch.setattr(
        topology.astock,
        "concept_blocks",
        lambda code: {"concept_tags": []},
    )
    assert SectorEdgeProvider().build_edges(_CANDIDATES) == []


# ─────────────────────────── B3 · fund_flow provider ───────────────────────────


def _flow(rows):
    """构造 stock_fund_flow_120d 风格的 list[dict]。"""
    return [{"date": d, "main_net": v} for d, v in rows]


def test_fund_flow_provider_coinflow(monkeypatch):
    """两候选近期同日主力净流入（同向）→ fund_flow 边。"""
    shared_dates = [("2026-08-01", 1e8), ("2026-08-02", 2e8)]
    monkeypatch.setattr(
        topology.astock,
        "stock_fund_flow_120d",
        lambda code: {
            "600519": _flow(shared_dates + [("2026-08-03", -1e8)]),
            "000858": _flow(shared_dates),  # 两天共享正流入
            "300750": _flow([("2026-08-01", -5e7)]),  # 净流出 → 无共享
        }[code],
    )
    edges = FundFlowEdgeProvider().build_edges(_CANDIDATES)
    ff = [e for e in edges if e["type"] == "fund_flow"]
    pair = {e["source"] for e in ff} | {e["target"] for e in ff}
    assert "600519" in pair and "000858" in pair
    assert not any("300750" in (e["source"], e["target"]) for e in ff)
    assert any(e["weight"] == 2 for e in ff)  # 2 共享日 → weight=2（原 >=1 恒真假绿，off-by-one 抓不到）


def test_fund_flow_provider_resilient(monkeypatch):
    """数据源异常 → 空边不崩溃。"""
    monkeypatch.setattr(topology.astock, "stock_fund_flow_120d", lambda code: (_ for _ in ()).throw(RuntimeError("x")))
    assert FundFlowEdgeProvider().build_edges(_CANDIDATES) == []


def test_fund_flow_window_excludes_old_dates(monkeypatch):
    """review #6：fund_flow 仅取最近 20 日（[-_FUND_RECENT_DAYS:]）；窗口外早期正流入日不计入共享集。

    喂 25 条（前 5 早期含共享正流入日 + 后 20 窗口内全净流出）→ 无 fund_flow 边。
    闭浅覆盖：原 coinflow 测试只喂 2-3 日，未触 [-20:] 切片边界——off-by-one 抓不到。
    """
    # 前 5 条（窗口外）：含共享正流入日（07-10..07-14）
    early = [("2026-07-%02d" % (10 + i), 1e8) for i in range(5)]
    # 后 20 条（窗口内 [-20:]）：全净流出 → 无正日
    recent = [("2026-08-%02d" % (i + 1), -1e7) for i in range(20)]
    flow_rows = early + recent
    assert len(flow_rows) == 25  # 守卫：>20 条
    monkeypatch.setattr(
        topology.astock,
        "stock_fund_flow_120d",
        lambda code: _flow(flow_rows),  # 三候选完全相同 → 仅窗口外有共享正日
    )
    edges = FundFlowEdgeProvider().build_edges(_CANDIDATES)
    ff = [e for e in edges if e["type"] == "fund_flow"]
    # 共享正流入日全在窗口外 → 不计入共享集 → 无 fund_flow 边
    assert ff == []


# ─────────────────────────── B4 · ladder provider ───────────────────────────


def _pool_item(code, name, lbc, hybk):
    return {"c": code, "n": name, "lbc": lbc, "hybk": hybk}


def test_ladder_provider_same_height(monkeypatch):
    """同连板高度候选 → ladder 边；同行业额外加权。"""
    monkeypatch.setattr(
        topology.astock,
        "em_zt_topic_pool",
        lambda endpoint, date, sort="fbt:asc": [
            _pool_item("600519", "贵州茅台", 3, "白酒"),
            _pool_item("000858", "五粮液", 3, "白酒"),
            _pool_item("300750", "宁德时代", 1, "新能源"),
        ],
    )
    edges = LadderEdgeProvider().build_edges(_CANDIDATES)
    ld = [e for e in edges if e["type"] == "ladder"]
    # 600519-000858 同 3 板 + 同白酒 → weight=2
    pair = {e["source"] for e in ld} | {e["target"] for e in ld}
    assert "600519" in pair and "000858" in pair
    assert any(e["weight"] == 2 for e in ld)
    # 300750 1 板，无同高度伙伴 → 不出现
    assert not any("300750" in (e["source"], e["target"]) for e in ld)


def test_ladder_provider_resilient(monkeypatch):
    """em_zt_topic_pool 异常 → 空边。"""
    monkeypatch.setattr(topology.astock, "em_zt_topic_pool", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert LadderEdgeProvider().build_edges(_CANDIDATES) == []


def test_ladder_provider_no_selfloop_on_dup_code(monkeypatch):
    """review fix #11：候选含重复 code → 去重，无 {source=x,target=x} 自环边。

    未修前 cand_codes 不去重 → 重复 code 在 i/i+1 配对产自环边。
    """
    monkeypatch.setattr(
        topology.astock,
        "em_zt_topic_pool",
        lambda endpoint, date, sort="fbt:asc": [
            _pool_item("600519", "贵州茅台", 3, "白酒"),
            _pool_item("000858", "五粮液", 3, "白酒"),
        ],
    )
    dup_candidates = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "600519", "name": "茅台(重复)"},  # 同 code 重复
        {"code": "000858", "name": "五粮液"},
    ]
    edges = LadderEdgeProvider().build_edges(dup_candidates)
    ld = [e for e in edges if e["type"] == "ladder"]
    # 去重后 600519/000858 各 1 个 → 恰 1 条 ladder 边，无自环
    assert len(ld) == 1
    assert not any(e["source"] == e["target"] for e in ld)
    assert {ld[0]["source"], ld[0]["target"]} == {"600519", "000858"}


# ─────────────────────────── B5 · seat provider ───────────────────────────


def _board(buy_names, sell_names):
    return {
        "seats": {
            "buy": [{"name": n, "buy_amt": 1, "sell_amt": 0, "net": 1} for n in buy_names],
            "sell": [{"name": n, "buy_amt": 0, "sell_amt": 1, "net": -1} for n in sell_names],
        },
    }


def test_seat_provider_shared_seat(monkeypatch):
    """两候选共享龙虎榜营业部 → seat 边，权重=共享席位数。"""
    monkeypatch.setattr(
        topology.astock,
        "dragon_tiger_board",
        # review fix #1 后 build_edges 透传 trade_date；mock 须接受该 kwarg
        lambda code, trade_date=None, **kw: {
            "600519": _board(["营业部A", "营业部B"], []),
            "000858": _board(["营业部A"], ["营业部C"]),
            "300750": _board(["营业部D"], []),
        }[code],
    )
    edges = SeatEdgeProvider().build_edges(_CANDIDATES)
    st = [e for e in edges if e["type"] == "seat"]
    pair = {e["source"] for e in st} | {e["target"] for e in st}
    assert "600519" in pair and "000858" in pair
    assert any(e["weight"] == 1 for e in st)  # 共享 营业部A
    assert not any("300750" in (e["source"], e["target"]) for e in st)


def test_seat_provider_passes_trade_date(monkeypatch):
    """review fix #1：build_edges(date=...) 透传 trade_date 给 dragon_tiger_board。

    未修前 dragon_tiger_board(code) 不传 trade_date → 龙虎榜恒取今日（席位永远今天）。
    """
    seen: dict[str, object] = {}

    def _spy(code, trade_date=None, **kw):
        seen[code] = trade_date
        return _board([], [])

    monkeypatch.setattr(topology.astock, "dragon_tiger_board", _spy)
    SeatEdgeProvider().build_edges(_CANDIDATES, date="2026-07-15")
    # 每个候选收到的 trade_date 均为传入日期（非 None/默认今日）
    assert seen.get("600519") == "2026-07-15"
    assert seen.get("000858") == "2026-07-15"
    assert seen.get("300750") == "2026-07-15"


def test_seat_provider_resilient(monkeypatch):
    """dragon_tiger_board 异常 → 空边。"""
    monkeypatch.setattr(topology.astock, "dragon_tiger_board", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert SeatEdgeProvider().build_edges(_CANDIDATES) == []


# ─────────────────────────── B6 · relation 聚合 ───────────────────────────


def test_relation_aggregation_nodes_and_edges(monkeypatch):
    """聚合多 provider → GraphData{nodes,edges}；节点=候选去重。"""
    # review fix 防封：mock concept_blocks 防离线测试发真实东财请求（§1.2 防封底线）
    monkeypatch.setattr(topology.astock, "concept_blocks", lambda code: {"concept_tags": []})
    providers = [_FakeProvider(), SectorEdgeProvider()]  # fake + sector
    graph = build_relation_graph(_CANDIDATES, providers=providers)
    assert set(graph.keys()) == {"nodes", "edges"}
    # 节点去重：3 个候选 → 3 节点，含 id/name/code/category
    assert len(graph["nodes"]) == 3
    node = graph["nodes"][0]
    assert {"id", "name", "code", "category"} <= set(node.keys())
    assert node["category"] == "candidate"
    # fake provider 的边必然出现（至少 1 条）
    types = {e["type"] for e in graph["edges"]}
    assert "fake" in types


def test_relation_nodes_dedup_by_code():
    """候选含重复 code → 节点去重。"""
    dup_candidates = _CANDIDATES + [{"code": "600519", "name": "茅台(重复)"}]
    graph = build_relation_graph(dup_candidates, providers=[])
    codes = [n["code"] for n in graph["nodes"]]
    assert codes.count("600519") == 1
    assert len(graph["nodes"]) == 3


def test_relation_provider_failure_isolated():
    """单个 provider 抛错 → 跳过该 provider，其余边照常返回（不阻塞）。"""

    class _Ok:
        edge_type = "ok"
        def build_edges(self, c, *, date=None):
            return [{"source": "600519", "target": "000858", "type": "ok", "weight": 1}]

    class _Boom:
        edge_type = "boom"
        def build_edges(self, c, *, date=None):
            raise RuntimeError("provider died")

    graph = build_relation_graph(_CANDIDATES, providers=[_Boom(), _Ok()])
    types = {e["type"] for e in graph["edges"]}
    assert "ok" in types and "boom" not in types


# ─────────────────────────── D1 · board-ladder 树 ───────────────────────────


def test_board_ladder_tree_structure(monkeypatch):
    """梯队树：根=当日涨停 → 按连板高度分层 → 同题材归枝 → 叶=个股(code/name 如实呈现)。"""
    monkeypatch.setattr(
        topology.astock,
        "em_zt_topic_pool",
        lambda endpoint, date, sort="fbt:asc": [
            _pool_item("600519", "贵州茅台", 3, "白酒"),
            _pool_item("000858", "五粮液", 3, "白酒"),
            _pool_item("300750", "宁德时代", 1, "新能源"),
        ],
    )
    tree = build_board_ladder_tree()
    assert tree["name"] == "当日涨停"
    heights = tree["children"]
    # 高连板在前（3 板层先于 1 板层）
    assert heights[0]["name"] == "3板"
    assert heights[1]["name"] == "1板"
    # 3 板层 → 白酒枝 → 两股叶
    baijiu = heights[0]["children"][0]
    assert baijiu["name"] == "白酒"
    leaf_names = [s["name"] for s in baijiu["children"]]
    assert any("600519" in n and "贵州茅台" in n for n in leaf_names)
    assert any("000858" in n and "五粮液" in n for n in leaf_names)
    # 叶节点带 code
    assert all("code" in s for s in baijiu["children"])


def test_board_ladder_empty_pool(monkeypatch):
    """空池 → 根 + 空 children。"""
    monkeypatch.setattr(topology.astock, "em_zt_topic_pool", lambda *a, **k: [])
    tree = build_board_ladder_tree()
    assert tree["name"] == "当日涨停"
    assert tree["children"] == []


def test_board_ladder_resilient(monkeypatch):
    """数据源异常 → 根 + 空 children（不崩）。"""
    monkeypatch.setattr(topology.astock, "em_zt_topic_pool", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    tree = build_board_ladder_tree()
    assert tree["children"] == []


# ─────────────────────────── 漏斗候选加载：live config ───────────────────────────


def test_load_candidates_uses_live_config(monkeypatch):
    """review fix #2：_load_candidates 复用 candidates 路由 _store["config"]（live），
    非 _default_config() 新建默认 → 关系图与候选页用同一套调参后候选池。

    未修前关系图用默认 config、候选页用用户调参后 config → 两套候选池。
    """
    import app as app_module  # noqa: F401 — 触发 app 加载，candidates 才完整可用
    from routers.candidates import _store

    sentinel = object()  # 任意可识别对象，证 live config 被透传
    monkeypatch.setitem(_store, "config", sentinel)

    captured: dict[str, object] = {}

    def _fake_run(stage, d, cfg):
        captured["cfg"] = cfg
        captured["date"] = d

        class _Result:
            final_candidates = []
        return _Result()

    monkeypatch.setattr(topology.funnel_mod, "run_funnel", _fake_run)
    topology._load_candidates("2026-07-15")
    assert captured["cfg"] is sentinel  # live config 透传，非新建默认
    assert captured["date"] == "2026-07-15"


# ─────────────────────────── A5 · 合规：无方向词 ───────────────────────────


_FORBIDDEN = ["推荐", "建议买", "建议卖", "目标价", "止损", "加仓", "减仓", "买入信号", "卖出信号"]


def test_compliance_no_directional_words_in_source():
    """topology.py 源码/输出标签无方向结论词（拓扑只客观关联）。"""
    src = inspect.getsource(topology)
    for word in _FORBIDDEN:
        assert word not in src, f"合规违规：topology.py 出现方向词「{word}」"


# ─────────────────────── HTTP 端点接线（TestClient） ───────────────────────


def test_endpoint_board_ladder_wired(monkeypatch):
    """GET /api/topology/board-ladder 200 且返梯队树（端点已注册+接线）。"""
    from fastapi.testclient import TestClient
    import app as app_module

    monkeypatch.setattr(
        topology.astock,
        "em_zt_topic_pool",
        lambda endpoint, d, sort="fbt:asc": [_pool_item("600519", "贵州茅台", 3, "白酒")],
    )
    app_module._RESPONSE_CACHE.clear()
    client = TestClient(app_module.app)
    r = client.get("/api/topology/board-ladder")
    assert r.status_code == 200
    tree = r.json()
    assert tree["name"] == "当日涨停"
    assert tree["children"][0]["name"] == "3板"


def test_endpoint_relation_wired(monkeypatch):
    """GET /api/topology/relation 200 且返 GraphData{nodes,edges}（端点已注册+接线）。

    聚焦接线：mock _load_candidates 喂定稿候选 + 各数据源返空 → 节点齐全、边可空。
    """
    from fastapi.testclient import TestClient
    import app as app_module

    monkeypatch.setattr(
        topology,
        "_load_candidates",
        lambda date: [
            {"code": "600519", "name": "贵州茅台"},
            {"code": "000858", "name": "五粮液"},
        ],
    )
    # 各 provider 数据源返空（不重复测 provider 逻辑，聚焦端点聚合接线）
    monkeypatch.setattr(topology.astock, "concept_blocks", lambda c: {"concept_tags": []})
    monkeypatch.setattr(topology.astock, "stock_fund_flow_120d", lambda c: [])
    monkeypatch.setattr(topology.astock, "em_zt_topic_pool", lambda *a, **k: [])
    monkeypatch.setattr(topology.astock, "dragon_tiger_board", lambda *a, **k: {"seats": {"buy": [], "sell": []}})
    app_module._RESPONSE_CACHE.clear()
    client = TestClient(app_module.app)
    r = client.get("/api/topology/relation")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"nodes", "edges"}
    assert len(data["nodes"]) == 2
    assert {n["code"] for n in data["nodes"]} == {"600519", "000858"}


def test_endpoint_relation_all_four_edge_types(monkeypatch):
    """review #7：端点集成（A2 端到端）——4 源各返非空 → response edges 含全部 4 种 type。

    原 test_endpoint_relation_wired 4 源全空（仅验接线+节点去重）；补用例验
    4 源各产边 → 端到端聚合 sector/fund_flow/ladder/seat 全出现。
    """
    from fastapi.testclient import TestClient
    import app as app_module

    monkeypatch.setattr(
        topology,
        "_load_candidates",
        lambda date: [
            {"code": "600519", "name": "贵州茅台"},
            {"code": "000858", "name": "五粮液"},
        ],
    )
    # sector：共享白酒+消费
    monkeypatch.setattr(
        topology.astock,
        "concept_blocks",
        lambda code: {"concept_tags": ["白酒", "消费"]},
    )
    # fund_flow：共享 2026-08-01 正流入（窗口内）
    monkeypatch.setattr(
        topology.astock,
        "stock_fund_flow_120d",
        lambda code: _flow([("2026-08-01", 1e8)]),
    )
    # ladder：同 3 板 + 同白酒行业
    monkeypatch.setattr(
        topology.astock,
        "em_zt_topic_pool",
        lambda endpoint, date, sort="fbt:asc": [
            _pool_item("600519", "贵州茅台", 3, "白酒"),
            _pool_item("000858", "五粮液", 3, "白酒"),
        ],
    )
    # seat：共享营业部A（trade_date 透传，mock 须接受该 kwarg）
    monkeypatch.setattr(
        topology.astock,
        "dragon_tiger_board",
        lambda code, trade_date=None, **kw: _board(["营业部A"], []),
    )
    app_module._RESPONSE_CACHE.clear()
    client = TestClient(app_module.app)
    r = client.get("/api/topology/relation")
    assert r.status_code == 200
    data = r.json()
    types = {e["type"] for e in data["edges"]}
    # 4 种 EdgeType 全出现（端到端聚合，非单 provider 隔离测）
    assert {"sector", "fund_flow", "ladder", "seat"} <= types
