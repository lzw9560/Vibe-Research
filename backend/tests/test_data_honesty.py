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
    # Arrange：新浪降级返 2 行（对齐 S110 test_s008 fixture 风格，mock 不联网）
    sina_rows = [
        {"date": "2026-07-29", "main_net": 100.0, "small_net": -50.0,
         "mid_net": 20.0, "large_net": 30.0, "super_net": 80.0},
        {"date": "2026-07-28", "main_net": 200.0, "small_net": -60.0,
         "mid_net": 30.0, "large_net": 40.0, "super_net": 90.0},
    ]
    monkeypatch.setattr(eastmoney, "_sina_fund_flow_fallback",
                        lambda code, num=120: sina_rows)

    # 东财双 host 全断 → 降级新浪
    def fake_em_get(url, *a, **k):
        raise ConnectionError("eastmoney down")

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    # Act
    rows = eastmoney.stock_fund_flow_120d("600519")

    # Assert：降级行带来源标记，下游可见"这是新浪降级数据非东财"
    assert len(rows) == 2
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
