# -*- coding: utf-8 -*-
"""S111 R8：Tier-1 数据诚实测试套件（TDD）。

一条 Tier-1 修复裂缝一条断言。断言源断（mock）→ 返 missing/degraded 标记、
不戳 last_updated=now、不返基于陈旧的非零 signal。对齐 S110（2d29a14）测试
断言对齐降级行为范式 + test_fallback_empty_write 的 isolated_cache fixture 风格。

裂缝映射（spec §2 Tier-1 表 / registry.md）：
1. fallback-get-with-fallback-stale-cache-as-fresh  → get_with_fallback_meta
2. realtime-capital-flow-stale-cache-mask           → _get_realtime_capital_flow
3. risk-realtime-capital-flow-empty-as-neutral-signal → _get_realtime_capital_flow
4. fund-flow-120d-sina-cross-source-silent-substitute → stock_fund_flow_120d
5. chip-structure-stale-nearest-bar-fallback        → extract_chip_structure
6. risk-base-score-silent-50                        → calculate_base_risk
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from types import SimpleNamespace

import fallback
import pytest
import risk_models
from data.sources import eastmoney
from strategies import first_board_filter as fbf


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """每个用例用独立缓存目录 + 干净内存缓存（对齐 test_fallback_empty_write）。"""
    monkeypatch.setattr(fallback, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(fallback, "_MEM_CACHE", {})
    return tmp_path


# ===========================================================================
# 裂缝 #1：fallback get_with_fallback_meta —— fetch 失败+缓存命中不静默当 fresh
# ===========================================================================


def test_get_with_fallback_meta_fetch_fail_cache_hit_marks_stale(isolated_cache):
    """裂缝#1：fetch 抛异常 + 缓存命中 → 返 (data, meta{from_cache:true, is_stale:true})。

    旧 get_with_fallback 失败时原样返缓存、返回值无 stale 元数据，调用方无法区分
    live 与缓存（6 消费方级联污染）。meta 旁路让断源/陈旧可见，不再伪装 fresh。
    """
    # Arrange：既有好缓存
    good = [{"main_net": 100}]
    fallback.save_cache("k", good)

    def boom():
        raise RuntimeError("throttled")

    # Act：fetch 失败 → 降级缓存
    data, meta = fallback.get_with_fallback_meta("k", boom, ttl=600, fallback_value=[])

    # Assert：返缓存数据 + 诚实 meta（标 from_cache+stale，cache_ts 可溯）
    assert data == good
    assert meta["from_cache"] is True
    assert meta["is_stale"] is True
    assert meta["cache_ts"] is not None


def test_get_with_fallback_meta_live_fetch_not_marked_stale(isolated_cache):
    """裂缝#1 互补：live fetch 成功 → meta 标 fresh（from_cache=False, is_stale=False）。

    证明 meta 真区分 live 与缓存，不是恒标 stale——诚实标记的二值契约。"""
    # Arrange
    live = [{"main_net": 7}]

    # Act
    data, meta = fallback.get_with_fallback_meta("k", lambda: live, ttl=600, fallback_value=[])

    # Assert：live 数据 + fresh meta
    assert data == live
    assert meta["from_cache"] is False
    assert meta["is_stale"] is False


# ===========================================================================
# 裂缝 #2：_get_realtime_capital_flow —— 源断+陈旧缓存命中标 degraded
# ===========================================================================


def test_realtime_capital_flow_stale_cache_marks_degraded_not_fresh_signal(isolated_cache, monkeypatch):
    """裂缝#2：源断 + 陈旧缓存命中 → data_status='degraded'，不戳 now，signal 不基于陈旧算非零。

    旧逻辑把 ≤10min 陈旧缓存当实时资金流算出非零 capital_flow_signal，且 last_updated=now
    伪标刚更新。修复：命中陈旧缓存标 degraded，signal=0.0（不基于陈旧算），data_time 用缓存
    写入时刻（不戳 now 伪装刚算完）。
    """
    import astock

    code = "600519"
    # 陈旧缓存：5 日资金流，主力净流入巨大——若按旧逻辑算 signal 会得非零 1.0
    stale_rows = [
        {"date": f"2026-07-2{d}", "main_net": 999999.0, "super_net": 1.0, "large_net": 1.0}
        for d in (9, 8, 7, 6, 5)
    ]
    # 注入 5 分钟前写入的内存缓存（TTL=600 内 → 命中，但非 live → 陈旧）
    cache_ts = time.time() - 300
    fallback._MEM_CACHE[f"capital_flow:{code}"] = (cache_ts, stale_rows)

    # 源断：实时取数抛异常 → get_with_fallback_meta 降级到陈旧缓存
    def boom(_code):
        raise ConnectionError("push2his 断连")

    monkeypatch.setattr(astock, "stock_fund_flow_120d", boom)

    # Act
    cf = risk_models._get_realtime_capital_flow(code)

    # Assert：标 degraded，signal=0.0（非基于陈旧的 1.0），data_time=缓存时刻（非 now）
    assert cf["data_status"] == "degraded"
    assert cf["capital_flow_signal"] == 0.0
    assert cf["big_fund_detected"] is False
    assert cf["data_time"] == datetime.fromtimestamp(cache_ts).isoformat()
    # 不戳 now：data_time 是缓存写入时刻，不是当前 now
    assert cf["data_time"] != datetime.now().isoformat()


# ===========================================================================
# 裂缝 #3：_get_realtime_capital_flow —— fetch 空+缓存也 miss 标 missing
# ===========================================================================


def test_realtime_capital_flow_fetch_empty_cache_miss_marks_missing(isolated_cache, monkeypatch):
    """裂缝#3：fetch 空 + 缓存也 miss → data_status='missing'，非 0.0 中性伪装。

    旧逻辑返 {capital_flow_signal:0.0,...} 与"净流入≈0/无大资金"合法中性信号同形无
    data_status 区分，断源被呈现成"平稳市"喂打板/情绪。修复：空 history 标 missing，
    下游可见这是断源不是真中性。
    """
    import astock

    code = "600519"
    # fetch 返空（断源/限流返 []），缓存也空（fixture 已清空）
    monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda _code: [])

    # Act
    cf = risk_models._get_realtime_capital_flow(code)

    # Assert：标 missing（不伪装成"净流入≈0 合法中性"）
    assert cf["data_status"] == "missing"
    assert cf["capital_flow_signal"] == 0.0
    assert cf["fund_flow_history"] == []


# ===========================================================================
# 裂缝 #4：stock_fund_flow_120d —— 新浪降级路径带 source provenance
# ===========================================================================


def test_stock_fund_flow_120d_sina_degradation_carries_source(monkeypatch):
    """裂缝#4：东财双 host 断 → 新浪降级，返回行带 source='sina_fallback'（下游可见来源）。

    旧逻辑东财断静默切新浪，返回与东财同字段/形状/单位的 rows 无来源标记，下游当东财
    正典数据归一化算 signal/big_fund，跨源口径混算失真。修复：新浪降级行加 source 标记。
    """
    # Arrange：新浪降级返 5 行（>=5 过 S115 R2 min-bars 门，对齐 test_s008 5-kline 范式，mock 不联网）
    sina_rows = [
        {"date": "2026-07-29", "main_net": 100.0, "small_net": -50.0,
         "mid_net": 20.0, "large_net": 30.0, "super_net": 80.0},
        {"date": "2026-07-28", "main_net": 200.0, "small_net": -60.0,
         "mid_net": 30.0, "large_net": 40.0, "super_net": 90.0},
        {"date": "2026-07-27", "main_net": 150.0, "small_net": -40.0,
         "mid_net": 25.0, "large_net": 35.0, "super_net": 70.0},
        {"date": "2026-07-26", "main_net": 180.0, "small_net": -55.0,
         "mid_net": 28.0, "large_net": 38.0, "super_net": 75.0},
        {"date": "2026-07-25", "main_net": 120.0, "small_net": -45.0,
         "mid_net": 22.0, "large_net": 32.0, "super_net": 82.0},
    ]
    monkeypatch.setattr(eastmoney, "_sina_fund_flow_fallback",
                        lambda code, num=120: sina_rows)

    # 东财双 host 全断 → 降级新浪
    def fake_em_get(url, *a, **k):
        raise ConnectionError("eastmoney down")

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    # Act
    rows = eastmoney.stock_fund_flow_120d("600519")

    # Assert：降级行带来源标记，下游可见"这是新浪降级数据非东财"（>=5 过 R2 门；
    # <5→[]→missing 由 #16 test_realtime_capital_flow_sina_few_rows 覆盖）
    assert len(rows) == 5
    assert all(r.get("source") == "sina_fallback" for r in rows)


# ===========================================================================
# 裂缝 #5：extract_chip_structure —— 请求日 bar 不在 cache 返 {} 非昨日值
# ===========================================================================


def test_extract_chip_structure_missing_day_bar_returns_empty_not_yesterday(monkeypatch):
    """裂缝#5：请求日 bar 不在 cache → 返 {}，不回退前一日值打分。

    旧逻辑 `bars[i].date <= d` 取"当日或之前最近 bar"，当日 bar 缺（baostock 16:30 才入
    cache，first_board 16:15 跑早 15min）时静默回退昨日 turnover/量比/成交额冒充当日打分。
    修复：`<=`→`==` 精确匹配，缺当日 bar 返 {}（对齐 _bar_close:1885 == 范式）。
    """
    # Arrange：cache 有"前一日"bar（带实质值），但无"请求日"bar
    bars = {
        "600519": [
            {"date": "2026-08-13", "turn": 5.0, "amount": 1.0e8, "volume": 100000.0},
            {"date": "2026-08-14", "turn": 8.5, "amount": 2.0e8, "volume": 120000.0},  # 昨日
        ]
    }
    monkeypatch.setattr(fbf, "_get_kline_cache", lambda: bars)

    # Act：请求日 2026-08-15 不在 cache
    result = fbf.extract_chip_structure("600519", "2026-08-15")

    # Assert：返 {}（不回退昨日 8.5/2e8 冒充当日）
    assert result == {}


# ===========================================================================
# 裂缝 #6：calculate_base_risk —— 取数故障标 missing 区分无 gene-score 中性先验
# ===========================================================================


def test_calculate_base_risk_fetch_fault_marks_missing(monkeypatch):
    """裂缝#6a：取数故障（DB/import 错误）→ (50.0, 'missing')，区分故障 vs 中性先验。

    旧逻辑 bare `except: pass` 把"取数故障"压成 50.0 无 data_status 区分。修复：收窄 except，
    裸失败设 data_status=missing。
    """
    import limitup_screener as ls

    # Arrange：get_screener_result 抛 RuntimeError（取数故障）
    async def fake_raise(date=None):
        raise RuntimeError("DB down")

    monkeypatch.setattr(ls, "get_screener_result", fake_raise)

    # Act
    score, status = asyncio.run(risk_models.calculate_base_risk("600519"))

    # Assert：故障标 missing（非 ok）
    assert score == 50.0
    assert status == "missing"


def test_calculate_base_risk_no_gene_score_is_ok_neutral(monkeypatch):
    """裂缝#6b：未入 screener（合法中性先验）→ (50.0, 'ok')，与取数故障区分。

    同样返 50.0 但 data_status='ok'——证明"无 gene score 中性先验"与"取数故障"被区分，
    不再把两类压成同一无标 50.0。"""
    import limitup_screener as ls

    # Arrange：screener 正常返回但该 code 不在 gene_scores
    async def fake_empty(date=None):
        return SimpleNamespace(gene_scores=[])

    monkeypatch.setattr(ls, "get_screener_result", fake_empty)

    # Act
    score, status = asyncio.run(risk_models.calculate_base_risk("600519"))

    # Assert：合法中性先验标 ok（非 missing）
    assert score == 50.0
    assert status == "ok"


# ===========================================================================
# 裂缝 #4 消费侧：_get_realtime_capital_flow 读 source → 跨源降级标 degraded
# ===========================================================================


def test_realtime_capital_flow_sina_cross_source_marks_degraded(isolated_cache, monkeypatch):
    """裂缝#4 消费侧：live fetch 返新浪降级行（source='sina_fallback'）→ data_status='degraded'。

    关闭跨源混算毒窗口：review 指出 #4 标记孤立——_get_realtime_capital_flow 从不读
    source，live-sina 仍当东财正典算 signal 标 ok，跨源 max_abs 混算失真当正常行情。
    修复：读 source 字段，含新浪降级行标 degraded，下游勿当东财正典。
    """
    import astock

    code = "600519"
    # 新浪降级行（source 字段由 eastmoney._with_source 嵌入）
    sina_rows = [
        {"date": "2026-07-29", "main_net": 100.0, "super_net": 80.0, "large_net": 30.0,
         "source": "sina_fallback"},
        {"date": "2026-07-28", "main_net": 200.0, "super_net": 90.0, "large_net": 40.0,
         "source": "sina_fallback"},
    ]
    monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda _code: sina_rows)

    # Act
    cf = risk_models._get_realtime_capital_flow(code)

    # Assert：跨源降级标 degraded（非 ok），关闭"新浪当东财正典"毒窗口
    assert cf["data_status"] == "degraded"


# ===========================================================================
# 裂缝 #6c：calculate_base_risk —— 真实 DB 故障（sqlite3.OperationalError）
# ===========================================================================


def test_calculate_base_risk_db_operational_error_marks_missing(monkeypatch):
    """裂缝#6c：真实 DB 故障（sqlite3.OperationalError，load_gene_scores conn.execute 可抛）→ missing。

    review MEDIUM：R7 原 narrowed except 漏 sqlite3.OperationalError → DB 锁/无表/损坏
    会 propagate 成 502（原 bare except 吞的现在崩）。broad except(Exception) 修复后 catch
    住，标 missing 不崩——关闭 test-reality gap（旧测试用 RuntimeError 模拟 DB 故障，
    真实是 OperationalError，narrowed except 漏它）。
    """
    import sqlite3
    import limitup_screener as ls

    # Arrange：get_screener_result 抛 sqlite3.OperationalError（DB 锁，真实故障）
    async def fake_db_fault(date=None):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ls, "get_screener_result", fake_db_fault)

    # Act
    score, status = asyncio.run(risk_models.calculate_base_risk("600519"))

    # Assert：DB 故障标 missing（非崩 502，非 ok）——broad except catch 住 OperationalError
    assert score == 50.0
    assert status == "missing"


# ===========================================================================
# S112 Tier-2 撒谎裂缝（8 条，每裂缝一断言：源断→missing/degraded/is_delayed）
# 对齐 S111 AAA + monkeypatch + isolated_cache 范式。R1-R5 已实现（GREEN），
# R6-R8 impl 并行中（RED 正常）——测试针对 spec 期望行为，不为过而弱化断言。
# 裂缝映射（registry.md Tier-2 节）：
# 7. risk-dragon-tiger-silent-zero           → _get_dragon_tiger_risk
# 8. risk-seat-info-silent-empty             → _get_seat_info
# 9. risk-concentration-silent-zero          → _calculate_concentration_risk_meta
# 10. sector-divergence-silent-empty          → calculate_sector_divergence
# 11. extreme-market-broken-zt-pool-as-normal → detect_extreme_market
# 12. score-dim4-chip-silent-50-neutral-fallback → score_dim4_chip
# 13. gstock-push2delay-permanent-latch-no-delay-flag → global_indices
# 14. newsradar-cache-no-ttl-stale-as-fresh   → get_radar/load_cache
# ===========================================================================


def test_dragon_tiger_risk_fetch_fault_marks_missing(isolated_cache, monkeypatch):
    """裂缝#7（R1）：_get_dragon_tiger_risk 取数故障（源断）→ (0.0, 'missing')，非 silent 0.0。

    旧逻辑 bare except: return 0.0 无日志无标记，与"近期未上榜=0风险"同形——源断被
    呈现成 0 风险喂打板（risk_level 可能 HIGH→MEDIUM）。修复：源断标 data_status=missing
    + logger，对齐 _get_realtime_capital_flow (S111 R4) 范式 + :374/:398/:418 warning sibling。
    风险评分仍 0.0（不臆造风险），仅 data_status 区分"无数据"与"确认无风险"。
    """
    import astock

    code = "600519"
    # 源断：dragon_tiger_board 取数抛异常（东财 push2 断连）
    def boom(*a, **k):
        raise ConnectionError("dragon_tiger_board 源断")

    monkeypatch.setattr(astock, "dragon_tiger_board", boom)

    # Act
    score, status = asyncio.run(risk_models._get_dragon_tiger_risk(code))

    # Assert：源断标 missing（非 ok，非旧 silent 0.0 无标记）
    assert score == 0.0
    assert status == "missing"


def test_seat_info_fetch_fault_marks_missing(isolated_cache, monkeypatch):
    """裂缝#8（R2）：_get_seat_info 取数故障（源断）→ data_status='missing'，非空 dict 当真。

    旧逻辑 compute_consensus_signal 任一异常或 fallback=None → 返空 dict
    {one_day_seats:[],multi_seat_signal:False,seat_confidence:0.0}，与"当日无特征席位"
    合法结果同形无 data_status——席位共识信号源断时漏报。修复：空 dict 加 data_status=missing
    + logger（原 bare except 无日志），对齐 R1/R4 范式。
    """
    import seat_engine

    code = "600519"
    # 源断：席位引擎 compute_consensus_signal 抛异常
    class _BrokenEngine:
        def compute_consensus_signal(self, *a, **k):
            raise ConnectionError("seat source 源断")

    monkeypatch.setattr(seat_engine, "get_engine", lambda: _BrokenEngine())

    # Act
    seat = asyncio.run(risk_models._get_seat_info(code))

    # Assert：源断标 missing（非 ok，非旧空 dict 无标记伪装"无特征席位"）
    assert seat["data_status"] == "missing"
    assert seat["one_day_seats"] == []
    assert seat["multi_seat_signal"] is False
    assert seat["seat_confidence"] == 0.0


def test_concentration_risk_fetch_fault_marks_missing(isolated_cache, monkeypatch):
    """裂缝#9（R3）：_calculate_concentration_risk 取数故障（源断）→ (0.0, 'missing')。

    旧逻辑直调 astock.dragon_tiger_board（未走 get_with_fallback 缓存层，更脆，单次断连
    即返空）→ records 空 return 0.0 或 bare except return 0.0，无日志无标记，集中度维度
    被低估。修复：套 get_with_fallback_meta 缓存层（对齐同模块 dragon_tiger）+ 0.0→missing
    + logger。
    """
    import astock

    code = "600519"
    # 源断：dragon_tiger_board 取数抛异常
    def boom(*a, **k):
        raise ConnectionError("concentration 源断")

    monkeypatch.setattr(astock, "dragon_tiger_board", boom)

    # Act
    score, status = asyncio.run(risk_models._calculate_concentration_risk_meta(code))

    # Assert：源断标 missing（非 ok，非旧 silent 0.0 无标记）
    assert score == 0.0
    assert status == "missing"


def test_dragon_tiger_risk_not_listed_live_empty_marks_ok(isolated_cache, monkeypatch):
    """S112 over-reporting fix：股票近期未上龙虎榜（源正常返空 records）→ (0.0, 'ok')，非 missing。

    关 risk-trio over-report 毒窗口：旧 S112 impl 把"源正常返空(未上榜)"与"源断"都标
    missing（_is_empty 分不开），致 ~99% 非上榜股永久 missing、data_status 失效。
    fetch_ok fix：fetch_ok=True（源正常返空）→ ok（合法未上榜，非断源）；fetch_ok=False（源断）→ missing。
    与 test_dragon_tiger_risk_fetch_fault_marks_missing 互补：源断=missing / 未上榜=ok 现可区分。
    """
    import astock

    code = "600519"
    # 源正常：股票近期未上龙虎榜，dragon_tiger_board 返空 records（fetch_ok=True）
    monkeypatch.setattr(astock, "dragon_tiger_board", lambda *a, **k: {"records": []})

    # Act
    score, status = asyncio.run(risk_models._get_dragon_tiger_risk(code))

    # Assert：未上榜标 ok（非 missing）——over-report 毒窗口关闭
    assert score == 0.0
    assert status == "ok"


def test_seat_info_no_seats_live_empty_marks_ok(isolated_cache, monkeypatch):
    """S112 over-reporting fix：当日无特征席位（源正常返 None）→ data_status='ok'，非 missing。

    seat_engine 对未上榜股返 None（非异常）。fetch_ok=True → ok（合法无席位）。
    与 test_seat_info_fetch_fault_marks_missing 互补：源断=missing / 无席位=ok。
    """
    import seat_engine

    code = "600519"
    # 源正常：当日无特征席位，compute_consensus_signal 返 None（fetch_ok=True）
    class _EmptyEngine:
        def compute_consensus_signal(self, *a, **k):
            return None

    monkeypatch.setattr(seat_engine, "get_engine", lambda: _EmptyEngine())

    # Act
    seat = asyncio.run(risk_models._get_seat_info(code))

    # Assert：无席位标 ok（非 missing）——over-report 毒窗口关闭
    assert seat["data_status"] == "ok"
    assert seat["one_day_seats"] == []


def test_concentration_risk_not_listed_live_empty_marks_ok(isolated_cache, monkeypatch):
    """S112 over-reporting fix：近期无上榜（源正常返空 records）→ (0.0, 'ok')，非 missing。

    与 test_concentration_risk_fetch_fault_marks_missing 互补：源断=missing / 无上榜=ok。
    """
    import astock

    code = "600519"
    # 源正常：近期无上榜，dragon_tiger_board 返空 records（fetch_ok=True）
    monkeypatch.setattr(astock, "dragon_tiger_board", lambda *a, **k: {"records": []})

    # Act
    score, status = asyncio.run(risk_models._calculate_concentration_risk_meta(code))

    # Assert：无上榜标 ok（非 missing）——over-report 毒窗口关闭
    assert score == 0.0
    assert status == "ok"


def test_sector_divergence_source_break_marks_missing_not_now(isolated_cache, monkeypatch):
    """裂缝#10（R4）：calculate_sector_divergence industry_comparison 源断 → data_status='missing'
    + last_updated 不戳 now（源断不伪装刚更新）。

    旧逻辑源断 → fallback_value 空板块 → return[]，或 bare except return[]（无 logger 无标记）；
    last_updated=now 把陈旧标 fresh。修复：[]→data_status=missing + logger（:172/:227/:313 三处）；
    last_updated 源断留空不戳 now，对齐 S111 R4 范式。
    """
    import astock
    import sector_divergence as sd

    # 源断：industry_comparison 取数抛异常（东财行业板块源断）
    def boom(*a, **k):
        raise ConnectionError("industry_comparison 源断")

    monkeypatch.setattr(astock, "industry_comparison", boom)

    # Act：传显式日期避开 _resolve_date 联网
    result = asyncio.run(sd.calculate_sector_divergence("2026-08-28"))

    # Assert：源断标 missing（非 ok），last_updated 留空（不戳 now 伪装刚更新）
    assert len(result) == 1
    assert result[0].data_status == "missing"
    assert result[0].last_updated == ""
    assert result[0].last_updated != datetime.now().isoformat()


def test_extreme_market_pool_source_break_marks_missing_not_normal(isolated_cache, monkeypatch):
    """裂缝#11（R5）：涨停/跌停/炸板池源断且缓存失效 → data_status='missing'，signal_type 非 '正常'
    （与"真平静"区分）。

    旧逻辑空池（源断）→ zt_count=0 → signal_type='正常'、is_extreme=False，无 data_status，
    把断源呈现成"平静市"喂情绪面板/打板信号，盘中断源期触发天气熔断/仓位闸误判。修复：
    空池(源断)→missing/degraded 不判"正常"，与"真平静"区分（ExtremeMarketSignal 已有
    data_status 字段 S111 R5）。
    """
    import astock
    import extreme_market_detector as emd

    # 绕过交易日历守卫（避免非交易日直接返 None，掩盖源断路径）
    monkeypatch.setattr(emd, "is_trading_day", lambda d: True)

    # 源断：涨停/跌停/炸板池取数抛异常（东财 em_zt_topic_pool 断连）
    def boom(*a, **k):
        raise ConnectionError("zt_topic_pool 源断")

    monkeypatch.setattr(astock, "em_zt_topic_pool", boom)

    # Act：传显式日期避开 _resolve_date 联网
    signal = asyncio.run(emd.detect_extreme_market("2026-08-28"))

    # Assert：源断标 missing（非 ok），signal_type 非"正常"（与真平静区分），不判极端
    assert signal is not None
    assert signal.data_status == "missing"
    assert signal.signal_type != "正常"
    assert signal.is_extreme is False


def test_score_dim4_chip_missing_data_returns_negative_one_not_50():
    """裂缝#12（R6）：score_dim4_chip 筹码数据缺失 → 返 -1（不参与加权），非 50.0（伪装"中等"）。

    旧逻辑子项换手/量比/成交额缺数据各默认 50.0，整函数异常 try/except 返 50.0，把"数据断裂"
    伪装成"筹码结构中等"。raw_values 诚实 None 但 scores['chip']=50 已撒谎。当前 chip 不在
    MARKET_PHASE_WEIGHTS（权重 0）→ 50 既不进 total（latent 不污染），但一旦给 chip 非零权重，
    缺失→50 掩盖真实筹码松动/过冷。修复：50.0→-1 对齐 score_dim_turnover:1274 sibling
    （缺失不参与加权，权重重分配）。
    """
    # Arrange：candidate 筹码结构为空（extract_chip_structure 缺当日 bar 返 {}，S111 R5）
    candidate = {"code": "600519", "_chip_structure": {}}

    # Act
    score, raw = fbf.score_dim4_chip(candidate, "2026-08-15")

    # Assert：缺数据返 -1（不参与加权），非 50.0（伪装中等）；raw 字段均 None（诚实）
    assert score == -1.0
    assert raw["turnover"] is None
    assert raw["vol_ratio"] is None
    assert raw["amount"] is None


def test_gstock_push2delay_latch_marks_is_delayed(monkeypatch):
    """裂缝#13（R7）：push2 实时源断 → latch 到 push2delay（延时镜像），返回带 is_delayed=True 标记。

    旧逻辑 push2 失败一次后 _gs_host[0] 永久 latch 到 push2delay（延时~15min 镜像），整进程后续
    所有 global_indices/us_hk_stock 调用永久走延时且不回探 push2，返回 d 无 is_delayed/latency
    标记。routers/market 直接当前态返前端——单次 push2 瞬断后整进程给前端喂延时美港股/指数当
    "实时"。修复：保留 latch（保 fast-fail，§10 Q4 选此非 per-call 重试）但加 is_delayed 标记
    透传 global_indices（对齐 market._emotion data_source），前端可见"这是延时数据非实时"。
    """
    import astock
    import gstock

    # 重置 latch 到 push2（index 0），清锁前态
    monkeypatch.setattr(gstock, "_gs_host", [0])

    def fake_em_get(url, *a, **k):
        # push2（实时，index 0）源断
        if "push2.eastmoney.com" in url and "push2delay" not in url:
            raise ConnectionError("push2 实时源断")
        # push2delay（延时镜像，index 1）可用，返数据
        if "push2delay.eastmoney.com" in url:
            return SimpleNamespace(json=lambda: {
                "data": {"f43": 35000, "f57": "100.DJIA", "f58": "道琼斯",
                         "f59": 2, "f60": 34500, "f170": 144}
            })
        raise ConnectionError("unknown host")

    monkeypatch.setattr(astock, "em_get", fake_em_get)
    # SOX 走 datacenter，mock 为空避免联网
    monkeypatch.setattr(astock, "eastmoney_datacenter", lambda *a, **k: [])

    # Act
    indices = gstock.global_indices()

    # Assert：latch 到 push2delay 后所有指数项带 is_delayed=True（前端可见延时，非伪装实时）
    assert len(indices) > 0
    assert all(idx.get("is_delayed") is True for idx in indices)


def test_newsradar_stale_cache_returns_skeleton_not_stale(monkeypatch, tmp_path):
    """裂缝#14（R8）：newsradar 缓存过期（generated_at 远早于 TTL）→ 返 skeleton（诚实空），
    非旧缓存当新。

    旧逻辑 load_cache 仅 FileNotFoundError/JSONDecodeError→None，无 TTL/时间戳校验——调度
    fetch 断/未跑时返上次成功写的旧缓存当新 radar，recent_days 时效窗口在调度断期间静默
    失真（比 fallback.py 更糟，无 TTL 上界）。修复：load_cache 加 TTL 比较 + 过期返 skeleton
    （诚实空，对齐 fallback.py TTL 范式）。
    """
    import json as _json
    import newsradar

    # Arrange：写一份明显过期的缓存（generated_at 远早于任何合理 TTL）
    stale_cache = {
        "generated_at": "2026-06-01 10:00",  # 近 3 个月前，远超任何 TTL
        "recent_days": 7,
        "industries": [{"key": "chip", "name": "半导体", "accent": "blue", "total": 1,
                        "items": [{"title": "stale news", "url": "x", "time": "",
                                   "ts": 0, "summary": "", "source": "stale"}]}],
        "stats": {"industries": 1, "total_sources": 1},
    }
    cache_file = tmp_path / "radar.json"
    cache_file.write_text(_json.dumps(stale_cache, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(newsradar, "CACHE_FILE", str(cache_file))

    # Act：force=False → 走 load_cache 路径
    result = newsradar.get_radar(force=False)

    # Assert：过期缓存→skeleton（generated_at=None），非旧缓存当新（旧 generated_at 非 None）；
    # skeleton 的 industries 来自配置（items 空），非旧缓存的 stale item
    assert result["generated_at"] is None
    assert all(i.get("items") == [] for i in result["industries"])


# ===========================================================================
# S115 三撒谎修复（R4）：3 confirmed_lying 各一断言（AAA + monkeypatch，
# 对齐 S111/S112 范式）。impl 并行修复中，测试针对 spec 期望行为——完成时
# 可能 RED（正常），不为过而弱化断言。裂缝映射（spec S115 §2 表）：
# 15. first-board-settlement-t0-bar-lte-fallback      → run_t1_premium_review
# 16. sina-fallback-no-min-bars-maxabs-drift          → _get_realtime_capital_flow
# 17. storm-predictor-internal-null-sti-as-zero-calm  → _collect_internal_factor
# ===========================================================================


def test_first_board_settlement_missing_signal_date_bar_returns_none_not_neighbor(
        tmp_path, monkeypatch):
    """裂缝#15（S115 R1）：baostock 缓存有前一日 bar 但无 signal_date 当日 bar
    → t1_return_pct=None（非邻近 bar 冒充的 wrong value）+ t0_date=None provenance。

    旧逻辑 `<=` 取"当日或之前最近 bar"，signal_date 当日 bar 缺（停牌/新股缺口/
    baostock 缓存未含该日）时静默回退前一日 bar，用前一日 open 当 signal_date
    当日 open 算 t1_return_pct → wildly wrong ret 喂 lift/胜率/verdict（§44 承重链）。
    修复：`<=`→`==` 精确匹配（对齐 S111 R6 _bar_close:1885 范式），缺当日 bar→
    t0_bar=None→t1_open=None→ret=None 跳过；t0_date=None 诚实记"缺 signal_date bar"。
    """
    # Arrange：VR_DATA_DIR→tmp，写 baostock 缓存：前一日 bar（真实 open）+
    # T1 bar（close），但故意缺 signal_date(2026-08-15) 当日 bar
    import json as _json
    from strategies import first_board_filter as _fbf
    from strategies.first_board_settlement import run_t1_premium_review

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    signal_date = "2026-08-15"
    cache = {"600519": [
        {"date": "2026-08-14", "open": 1800.0, "close": 1850.0},  # 前一日（邻近）
        {"date": "2026-08-16", "open": 1880.0, "close": 1900.0},   # T1（次日）
    ]}
    (tmp_path / "baostock_kline_cache.json").write_text(
        _json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # load_scores 返候选快照（mock，避开磁盘/联网）
    monkeypatch.setattr(_fbf, "load_scores", lambda d: {
        "scored_candidates": [
            {"code": "600519", "name": "贵州茅台", "rank": 1, "total": 80.0},
        ],
    })

    # Act
    result = run_t1_premium_review(signal_date)

    # Assert：t1_return_pct=None（非旧 `<=` 用 08-14 open=1800 算出的 ~5.5556 wrong value）；
    # t0_date=None provenance 诚实记"缺 signal_date 当日 bar"（不冒充邻近 bar 日期）
    cand = result["candidates"][0]
    assert cand["t1_return_pct"] is None
    assert cand["t0_date"] is None
    # 反证：旧 `<=` bug 会算 (1900-1800)/1800*100≈5.5556，确认不是该 wrong value
    wrong_value = round((1900.0 - 1800.0) / 1800.0 * 100, 4)
    assert cand["t1_return_pct"] != wrong_value


def test_realtime_capital_flow_sina_few_rows_marks_missing_not_full_signal(
        isolated_cache, monkeypatch):
    """裂缝#16（S115 R2）：新浪降级返<5 条 → _get_realtime_capital_flow
    data_status='missing'（非满格 signal）。

    旧逻辑新浪降级路径无 len>=5 门（东财路径有 :466），新浪返 1-4 条当 120d
    历史喂 risk_models，在退化序列算 max_abs→signal 满格 ±1.0→adjustment
    扭曲 risk_level（口径漂移~25×）。修复：新浪降级路径加对称 len>=5 门（<5 返 []），
    落回 risk_models not history→missing 诚实返空（S111 R3 范式）。
    """
    code = "600519"
    # 新浪降级返 2 条（<5 门阈值），主力净流入巨大——若无门会算出非零满格 signal
    sina_rows = [
        {"date": "2026-08-14", "main_net": 999999.0, "super_net": 8.0e5,
         "large_net": 3.0e5, "small_net": -5.0e4, "mid_net": 2.0e4},
        {"date": "2026-08-13", "main_net": 888888.0, "super_net": 7.0e5,
         "large_net": 2.0e5, "small_net": -4.0e4, "mid_net": 1.5e4},
    ]
    monkeypatch.setattr(eastmoney, "_sina_fund_flow_fallback",
                        lambda code_, num=120: sina_rows)

    # 东财双 host 全断 → 降级新浪（em_get 由 astock/eastmoney 共用模块全局）
    def fake_em_get(url, *a, **k):
        raise ConnectionError("eastmoney down")

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    # Act：_get_realtime_capital_flow → astock.stock_fund_flow_120d（= eastmoney 同函数）
    cf = risk_models._get_realtime_capital_flow(code)

    # Assert：<5 条新浪降级行被 R2 门挡返 [] → history 空 → missing
    # （非旧满格 signal ±1.0 / degraded 当有效行情）
    assert cf["data_status"] == "missing"
    assert cf["capital_flow_signal"] == 0.0
    assert cf["fund_flow_history"] == []


def test_storm_internal_factor_null_sti_marks_missing_not_calm(
        tmp_path, monkeypatch):
    """裂缝#17（S115 R3）：sti_timeline 行存在但 raw_break_rate=NULL →
    data_status='missing' + score 50.0（非 0.0+ok 假平静）。

    旧逻辑 `if ... is not None` 漏 NULL→break_rate 保持 0.0+data_status='ok'，
    降级日（写侧 source_ok=0/列 NULL 诚实标记）冒充真平静→内部因子(权重0.35)
    假性偏低→风暴概率低估→suggested_position 偏高。修复：NULL 列/source_ok=0/
    无行→None→missing+50.0 中性基线（函数已用 50.0 for acknowledged-missing）。
    """
    import sqlite3
    import config
    from strategies import storm_predictor
    from limitup_screener import data as ls_data

    # Arrange：t1 固定（避开 _prev_trading_day 联网/日历），gene_scores 非空
    # （避开"无 gene→早返 missing"假阳性——本测专测 NULL sti 路径）
    t1 = "2026-08-14"
    monkeypatch.setattr(storm_predictor, "_prev_trading_day", lambda date: t1)
    monkeypatch.setattr(ls_data, "load_gene_scores", lambda d: [
        SimpleNamespace(factors={"封板率": 80.0, "炸板后溢价": 0.5}),
    ])

    # sti_timeline DB：行存在，dimension_max_boards=6（非 NULL），raw_break_rate=NULL
    # （降级日写侧诚实标 NULL），source_ok=1（隔离 NULL 列路径，非 source_ok=0 路径）
    db_path = tmp_path / "sti_timeline.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE sti_timeline (date TEXT, dimension_max_boards REAL, "
        "raw_break_rate REAL, source_ok INTEGER)")
    conn.execute(
        "INSERT INTO sti_timeline (date, dimension_max_boards, raw_break_rate, source_ok) "
        "VALUES (?, ?, ?, ?)", (t1, 6.0, None, 1))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "STI_TIMELINE_DB_PATH", str(db_path))

    # Act
    factor = storm_predictor._collect_internal_factor("2026-08-15")

    # Assert：NULL raw_break_rate→missing+50.0（中性基线），非旧 0.0+ok 假平静
    # （旧 bug：max_boards=6/break_rate=0(NULL)→score=(90+0+49)/3≈46.3+ok）
    assert factor.data_status == "missing"
    assert factor.score == 50.0
