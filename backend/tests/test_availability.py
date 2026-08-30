# -*- coding: utf-8 -*-
"""诚实缺陷项 + chip-cyq availability 测试（S113 R4.2/R4.3 + S114 R10）。

对齐 S111 ``test_data_honesty.py`` 的 AAA + monkeypatch + 独立 fixture 风格。

R4.2 premarket 缺 cache 守卫（S113，``premarket_selection.select_premarket_candidates``）
    registry ``premarket-selection-unguarded-cache-read``：原裸读无 exists() 检查，文件缺失
    抛 FileNotFoundError 冒泡至 endpoint 全局 handler 返 500（违 S069「dev 无 baostock 降级
    不崩」契约）。S113 加 exists()+try→返 []，对齐 ``first_board_filter:359-371`` 守卫范式。

R4.3 scheduled_tasks t1_review 同型守卫（S113，``_compute_t1_returns``）
    registry 兄弟项 ``scheduled_tasks.py:1860``：t1 路径同型裸读同崩（不臆造）。S113 加
    同款 try/except→返 []，缺 cache 不崩（对齐 premarket R4.2 守卫范式）。

R4.1 chip-breaker 自愈（S113）→ **S114 supersede**：S114 把 chip_distribution 取数层
    改自建走 em_get（R10），em_get 自带 breaker('eastmoney') 已覆盖熔断自愈，chip 级
    breaker（_CHIP_BREAKER_NAME）冗余已删（对齐 hot_money_seats 复用范式）。R4.1 测试随
    S114 删除，em_get breaker-OPEN 路径由 R10 ``test_chip_distribution_em_get_breaker_open_returns_empty`` 覆盖。

R10 chip-cyq 自建走 em_get（S114）：offline fallback 4 态 + live AC1，见下文。
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from data.sources import akshare_src


# ===========================================================================
# R4.2 premarket 缺 cache 守卫：KLINE_CACHE 不存在→返 [] 非 500 + note
# ===========================================================================


def test_premarket_missing_cache_returns_empty_not_500(monkeypatch, tmp_path):
    """R4.2：KLINE_CACHE 不存在→select_premarket_candidates 返 []（非抛 FileNotFoundError 非 500）。

    registry ``premarket-selection-unguarded-cache-read``：原裸读无 exists() 检查，文件缺失
    抛 FileNotFoundError 冒泡至 endpoint 全局 handler 返 500（违 S069「dev 无 baostock 降级
    不崩」契约）。S113 加 exists()+try→返 []，对齐 first_board_filter:359-371 守卫范式。
    """
    from strategies import premarket_selection as pm

    # Arrange：KLINE_CACHE 指向不存在的文件（baostock 未装/首次运行场景）
    missing_cache = tmp_path / "does_not_exist_kline.json"
    assert not missing_cache.exists()
    monkeypatch.setattr(pm, "KLINE_CACHE", missing_cache)

    # Act + Assert：返 [] 非 500 崩（FileNotFoundError 不冒泡）
    assert pm.select_premarket_candidates("2026-08-15") == []


def test_premarket_missing_cache_carries_data_missing_note(monkeypatch, tmp_path):
    """R4.2 配套：缺 cache→select_premarket_with_risk 返空候选 + market_note 标 data-missing
    （下游可见「候选空系降级非无信号」，非旧裸 500）。

    对齐 spec R2「附 data-missing 备注」。calendar_factor 纯本地（holidays.json，零 API），
    无需 mock；cache 缺失时 select_premarket_candidates 早期返 []，_load_code_name_map
    （DB）不被触达，无联网/DB 副作用。
    """
    from strategies import premarket_selection as pm

    # Arrange：KLINE_CACHE 不存在
    monkeypatch.setattr(pm, "KLINE_CACHE", tmp_path / "nope.json")

    # Act
    result = pm.select_premarket_with_risk("2026-08-15")

    # Assert：空候选 + note 标降级（非 500 崩）
    assert result.candidates == []
    assert "缺失" in result.market_note  # data-missing 备注


# ===========================================================================
# R4.3 scheduled_tasks t1_review 同型守卫：缺 cache 不崩
# ===========================================================================


def test_scheduled_tasks_t1_missing_cache_returns_empty_not_crash(monkeypatch, tmp_path):
    """R4.3：scheduled_tasks t1_review 路径缺 cache→_compute_t1_returns 返 [] 不崩（同型守卫）。

    registry 兄弟项 ``scheduled_tasks.py:1860``：t1 路径同型裸读 KLINE_CACHE 同崩（不臆造）。
    S113 加同款 try/except→返 []，缺 cache 不崩（对齐 premarket R4.2 守卫范式）。
    ``_compute_t1_returns`` 内 ``from strategies.premarket_selection import KLINE_CACHE``
    运行时取被 monkeypatch 的常量值，文件不存在→FileNotFoundError 被 except 接住→返 []。
    """
    from strategies import premarket_selection as pm
    import scheduled_tasks as st

    # Arrange：KLINE_CACHE 不存在
    monkeypatch.setattr(pm, "KLINE_CACHE", tmp_path / "nope.json")
    final_cards = [{"code": "600519", "name": "贵州茅台"}]

    # Act + Assert：缺 cache 返 [] 非 FileNotFoundError 崩
    assert st._compute_t1_returns(final_cards, "2026-08-14", "2026-08-15") == []


# ===========================================================================
# S114 R10：chip_distribution 自建走 em_get —— offline fallback 4 态 + live AC1
# 对齐 S111/S113 AAA + monkeypatch 风格。impl 并行做中，测试针对 spec 期望行为，
# 完成时可能 RED（正常）——不为过而弱化断言。
#
# 范式：S114 把 chip_distribution 取数层从 ak.stock_cyq_em 黑盒（裸 requests 无防封）
# 改为自建 _fetch_cyq_klines 走 em_get（push2his kline/get + ut=_ZTB_UT 日K token）。
# em_get 自带 breaker('eastmoney') + 0.3s 限流 + 代理探测 + UA + timeout=8（真实
# socket 超时，根因消除 S094 daemon 8s 线程硬截断）。计算层保真复用东财原 JS
# （cyq_js.CYQ_JS + py_mini_racer，策略 A）。返 {} 4 态诚实降级（R3），不臆造数值。
#
# 关键 mock 目标：_fetch_cyq_klines 内 `from data.transport import eastmoney_get as
# em_get`（late import，每次 call 重读 data.transport.eastmoney_get 属性）→ patch
# data.transport.eastmoney_get 即拦截（非模块级 em_get，后者 inert）。兜底 patch
# akshare_src.em_get（raising=False）覆盖未来改为模块级 `as em_get` 绑定形态。
# ===========================================================================


@pytest.fixture
def em_get_mock(monkeypatch):
    """拦截 ``_fetch_cyq_klines`` 的 em_get（late-import ``data.transport.eastmoney_get``
    + 兜底 ``akshare_src.em_get`` raising=False，覆盖 late-import 与模块级绑定两形态）。

    用例设 ``.fn``（callable，控 raise / return response）；``.calls`` 计数验证 fallback
    路径真触达 em_get（非被某早返路径绕过，对齐 S113 ``_FakeAk.call_count`` 验证范式）。
    """
    holder = SimpleNamespace(fn=None, calls=0)

    def _fake(url, *a, **k):
        holder.calls += 1
        if holder.fn is None:
            raise AssertionError("test 未设 em_get 行为")
        return holder.fn(url, *a, **k)

    monkeypatch.setattr("data.transport.eastmoney_get", _fake)
    # 兜底：若 impl 改为模块级 `from data.transport import eastmoney_get as em_get`，
    # patch data.transport.eastmoney_get 对已绑定名 inert → 此处 patch akshare_src.em_get
    # 接管（raising=False 容许当前 late-import 形态下该名不存在）。
    monkeypatch.setattr(akshare_src, "em_get", _fake, raising=False)
    return holder


def test_chip_distribution_em_get_breaker_open_returns_empty(em_get_mock):
    """R3-1：em_get 熔断 OPEN（raise RuntimeError，transport.py:74 breaker-OPEN 快速失败
    信号）→ chip_distribution 返 {}（不抛冒泡至 diagnosis.py:229）。

    S114 自建走 em_get，em_get 内 breaker('eastmoney') OPEN 时 raise RuntimeError
    快速失败。chip_distribution try/except（akshare_src._fetch_cyq_klines:162）接住 →
    返 None → chip_distribution:218 ``if not klines: return {}``。钉死熔断信号不冒泡。
    """
    # Arrange：em_get 熔断 OPEN raise（transport.py:74 真实信号）
    def _breaker_open(url, *a, **k):
        raise RuntimeError("[CircuitBreaker:eastmoney] 东财数据源熔断中，快速失败")
    em_get_mock.fn = _breaker_open

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert：fallback 路径真触达 em_get + 返 falsy {}（非抛、非 truthy dict）
    assert em_get_mock.calls >= 1
    assert result == {}                              # R3：empty fallback
    assert not result                                # A5：falsy → diagnosis if _result 走 missing
    assert "chip_profit_ratio" not in result         # R4：非 {chip_profit_ratio:None} truthy 绕过


def test_chip_distribution_em_get_request_exception_returns_empty(em_get_mock):
    """R3-2：em_get 请求异常（连接断 / socket 超时，非 breaker-OPEN 短路）→ {}。

    区别 R3-1：此为 em_get 内 requests 抛 ConnectionError/Timeout（transport:101-103
    record_failure 后 re-raise），非 breaker 短路 raise RuntimeError。chip_distribution
    同 except（_fetch_cyq_klines:162）接住 → None → {}。钉死两类异常都不冒泡至 diagnosis。
    """
    # Arrange：em_get 请求异常（非熔断短路，是传输层 re-raise）
    def _conn_err(url, *a, **k):
        raise ConnectionError("push2his 断连/超时")
    em_get_mock.fn = _conn_err

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert
    assert em_get_mock.calls >= 1
    assert result == {}
    assert not result
    assert "chip_profit_ratio" not in result


def test_chip_distribution_no_chip_data_returns_empty(em_get_mock):
    """R3-3：em_get 200 但无筹码（body klines 空 / 该股无 CYQ 行，如新股）→ {}。

    push2his 对无筹码股返 ``{"data": {"klines": []}}``（200 body 空非服务故障）。
    _fetch_cyq_klines:168-170 ``klines = (data.get('data') or {}).get('klines')`` →
    空 → ``if not klines: return None`` → chip_distribution:218 返 {}。诚实降级不臆造。
    """
    # Arrange：200 但 klines 空（该股无筹码，非服务故障）
    em_get_mock.fn = lambda url, *a, **k: SimpleNamespace(
        json=lambda: {"data": {"klines": []}})

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert
    assert em_get_mock.calls >= 1
    assert result == {}
    assert not result
    assert "chip_profit_ratio" not in result


def test_chip_distribution_malformed_klines_returns_empty(em_get_mock):
    """R3-4：em_get 200 但 klines 坏格式（字段缺失，无法解析为 CYQ 输入）→ {}。

    _fetch_cyq_klines:179-195 逐行 split + 校验：``len(parts) < 11`` 的行 continue 跳过；
    有效行不足 90 条（R9 guard）→ 返 None → chip_distribution:218 返 {}。钉死坏格式
    不崩、诚实降级（非抛、非 truthy dict 喂 diagnosis 假信号）。
    """
    # Arrange：klines 坏格式——每行仅 2 字段（< f51..f61 共 11 字段）→ 全 skip → 有效 0 < 90
    bad_klines = ["bad,format"] * 95
    em_get_mock.fn = lambda url, *a, **k: SimpleNamespace(
        json=lambda: {"data": {"klines": bad_klines}})

    # Act
    result = akshare_src.chip_distribution("600519")

    # Assert
    assert em_get_mock.calls >= 1
    assert result == {}
    assert not result
    assert "chip_profit_ratio" not in result


@pytest.mark.live
def test_chip_distribution_live_returns_nonempty_with_numeric_ratio():
    """R10 AC1：chip_distribution('600519') 实跑，返非空 dict 含 chip_profit_ratio 数值。

    验证 ut=_ZTB_UT（日K通用公开 token）+ py_mini_racer 保真：600519（贵州茅台，长期
    流通有筹码）push2his 日K + hsl 取数成功 → CYQCalculator 算出 benefitPart（0-1 获利
    比例，CYQCalculator:205 below/totalChips）。offline ``-m 'not live'`` 跳过本用例。
    R6 5 键 shape 不变：chip_profit_ratio / avg_cost / concentration / 90_cost / 70_cost。

    注：若本机被东财 push2his kline/get 拒连（RemoteDisconnected，反爬/IP 针对性拒绝，
    akshare 原版同款拒连），换网络环境或待东财恢复再跑——非实现缺陷（em_get 防封工作，
    失败诚实返 {}）。
    """
    # Act：实跑（联网，em_get 走真实 push2his kline/get）
    result = akshare_src.chip_distribution("600519")

    # Assert：非空 dict + chip_profit_ratio 数值（AC1，ut + py_mini_racer 保真）
    assert isinstance(result, dict) and result, "live chip_distribution 应返非空 dict"
    ratio = result.get("chip_profit_ratio")
    assert ratio is not None and isinstance(ratio, (int, float)), \
        f"chip_profit_ratio 应为数值（AC1），实得 {ratio!r}"
    assert 0 <= ratio <= 1, f"benefitPart 获利比例应 0-1（below/totalChips），实得 {ratio}"
    # R6：5 键 shape 不变（值可 None 经 g() 清洗，键必在）
    for key in ("avg_cost", "concentration", "90_cost", "70_cost"):
        assert key in result, f"R6 5-key shape 缺键 {key}"


# ===========================================================================
# S116 R4：storm-daemon snapshot availability —— bad 不遮蔽 good + 全坏诚实
# 对齐 S111/S113/S114 AAA + monkeypatch 风格。impl 并行做中，测试针对 spec 期望
# 行为，完成时可能 RED（正常）——不为过而弱化断言。
#
# 范式：storm_daemon.get_t1_global_snapshot 原 last-write-wins（盲返 snaps[-1]），
# 若 T-1 最后一次跑（23:55 抖动返空 / 进程死前 14:00 美股盘前）是降级/陈旧快照，
# 静默遮蔽同日更早（21:00）的好夜间快照。S116 R1 fetch_snapshot 加 provenance
# （fetch_ok/is_degraded）落盘；R2 get_t1_global_snapshot 过滤 empty/degraded 取最近
# 好快照（非盲 snaps[-1]）；R3 storm_predictor 读 provenance 标 degraded（非 ok 假装）。
# mock 对象：storm_daemon._SNAP_DIR（快照目录）+ vr_paths.prev_trading_date（钉死前日，
# 免依赖 holidays.json）+ storm_daemon.get_t1_global_snapshot（直接注 snap）+ market.
# get_global_indices（fallback 当前外围），均经 test_s088_storm_predictor 验证可用。
# ===========================================================================


def test_get_t1_snapshot_bad_does_not_mask_good(tmp_path, monkeypatch):
    """R4.1/A1：bad snapshot（empty + fetch_ok=False）不遮蔽 good——get_t1_global_snapshot
    取到最近好快照（非盲 snaps[-1] 的坏快照）。

    S116 R2：原 get_t1_global_snapshot 盲返 snaps[-1]，T-1 最后一次跑（23:55 抖动
    返空）的坏快照遮蔽同日更早（21:00）的好夜间快照。R2 改过滤 empty/degraded
    （fetch_ok=False），取最近好快照。本用例 snaps=[good(21:00), bad(23:55 empty)]
    （bad 在末尾=snaps[-1]），断言返 good 的 indices 非 [] + ts=21:00，非 bad 的空。
    盲 snaps[-1] 的旧逻辑必 RED（返 bad 空 []）——这正是要钉死的遮蔽 bug。
    """
    from strategies import storm_daemon as sd

    # Arrange：T-1 日两快照——good(21:00) 在前，bad(23:55 empty+fetch_ok=False) 在后
    good_snap = {
        "ts": "2026-08-28T21:00:00", "date": "2026-08-28",
        "global_indices": [{"name": "道琼斯", "change_pct": -1.5},
                            {"name": "标普500", "change_pct": -1.2}],
        "fetch_ok": True,  # S116 R1 provenance：成功
    }
    bad_snap = {
        "ts": "2026-08-28T23:55:00", "date": "2026-08-28",
        "global_indices": [],          # empty——fetch 抖动返空/降级
        "fetch_ok": False,             # S116 R1 provenance：失败/空→False
        "is_degraded": True,
    }
    monkeypatch.setattr(sd, "_SNAP_DIR", tmp_path)
    # prev_trading_date 钉死（纯测过滤逻辑，免依赖 holidays.json 日历）
    monkeypatch.setattr("vr_paths.prev_trading_date",
                        lambda d: datetime(2026, 8, 28))
    (tmp_path / "2026-08-28.json").write_text(
        json.dumps([good_snap, bad_snap], ensure_ascii=False), encoding="utf-8")

    # Act
    result = sd.get_t1_global_snapshot("2026-08-30")

    # Assert：返 good 快照（ts=21:00 + indices 非空），非盲 snaps[-1] 的 bad 空
    assert result is not None
    assert result["ts"] == good_snap["ts"]                            # 21:00 good 非 23:55 bad
    assert result["global_indices"] == good_snap["global_indices"]   # good 的非空 indices
    assert result["global_indices"]                                   # 非 []（非 bad 的空）


def test_collect_global_factor_all_degraded_snap_not_ok(monkeypatch):
    """R4.2/A2：全坏快照（empty + fetch_ok=False）→ _collect_global_factor 标
    degraded/fallback_current/missing（诚实，非 'ok' 假装）。

    S116 R3：storm_predictor 读 snapshot provenance，degraded 快照→data_status='degraded'
    （非 ok）。本用例 mock get_t1_global_snapshot 返 degraded 快照（fetch_ok=False /
    is_degraded=True / global_indices=[]），mock market.get_global_indices 返当前非空
    数据（fallback 可得），断言即便 fallback 取到当前数据，data_status 仍非 'ok'——
    不假装 degraded 的 T-1 夜间快照是干净的 ok 读。诚实降级范式对齐 S115 fallback_current
    （degraded/fallback_current 均诚实，spec A2 接受二者，本测只钉死"非 ok 假装"）。
    """
    from strategies import storm_daemon, storm_predictor
    import market

    # Arrange：T-1 快照全坏（empty + fetch_ok=False + is_degraded）
    degraded_snap = {
        "ts": "2026-08-28T23:55:00", "date": "2026-08-28",
        "global_indices": [],
        "fetch_ok": False,
        "is_degraded": True,
    }
    monkeypatch.setattr(storm_daemon, "get_t1_global_snapshot",
                        lambda d: degraded_snap)
    # fallback 当前外围非空（测"fallback 取到但不得假装 ok"路径，非全空→missing 的退化态）
    monkeypatch.setattr(market, "get_global_indices",
                        lambda: [{"name": "道琼斯", "change_pct": -0.8},
                                 {"name": "标普500", "change_pct": -0.5}])

    # Act
    factor = storm_predictor._collect_global_factor("2026-08-30")

    # Assert：data_status 诚实（degraded/fallback_current/missing），非 'ok' 假装
    assert factor.data_status != "ok"
    assert factor.data_status in ("degraded", "fallback_current", "missing")


def test_get_t1_snapshot_all_bad_returns_most_recent_with_degraded(tmp_path, monkeypatch):
    """MEDIUM review fix：全部坏快照（empty+fetch_ok=False）→ get_t1_global_snapshot
    返最近坏（reversed）+ 强制 is_degraded=True（钉死全坏分支 provenance 产出，非 ok 假装）。

    R4.2 mock 掉 get_t1_global_snapshot 绕过全坏分支（storm_daemon.py:116-118），本测直接
    喂 [bad1,bad2] 到真实 get_t1（bad 无 is_degraded 字段，仅 fetch_ok=False），断言返 bad2
    （reversed 最近）+ is_degraded=True（分支 {**s,is_degraded:True} 强制标）。若分支漏标
    或 reversed 取错，predictor 拿无 is_degraded 快照→标 ok→A2 端到端诚实降级失效。
    """
    from strategies import storm_daemon as sd

    # Arrange：T-1 日两坏快照——bad1(22:00) 在前，bad2(23:30 empty) 在后=snaps[-1]，
    # 均无 is_degraded 字段（仅 fetch_ok=False），测全坏分支强制标 is_degraded
    bad1 = {"ts": "2026-08-28T22:00:00", "date": "2026-08-28",
            "global_indices": [], "fetch_ok": False}
    bad2 = {"ts": "2026-08-28T23:30:00", "date": "2026-08-28",
            "global_indices": [], "fetch_ok": False}
    monkeypatch.setattr(sd, "_SNAP_DIR", tmp_path)
    monkeypatch.setattr("vr_paths.prev_trading_date", lambda d: datetime(2026, 8, 28))
    (tmp_path / "2026-08-28.json").write_text(
        json.dumps([bad1, bad2], ensure_ascii=False), encoding="utf-8")

    # Act
    result = sd.get_t1_global_snapshot("2026-08-30")

    # Assert：返最近坏（bad2, reversed 取最近）+ 强制 is_degraded=True（全坏分支产出 provenance）
    assert result is not None
    assert result["ts"] == bad2["ts"]        # reversed 取最近坏（非盲 snaps[-1]=bad2，但经 reversed 逻辑确认）
    assert result["is_degraded"] is True    # 全坏分支强制标 degraded（非 ok 假装好快照）
    # 不可变拷贝：原 snaps 文件未被 {**s,is_degraded} 污染（bad2 原无 is_degraded，落盘仍无）
    reloaded = json.loads((tmp_path / "2026-08-28.json").read_text(encoding="utf-8"))
    assert "is_degraded" not in reloaded[1]  # 原始 bad2 未被污染（分支返新 dict 非原地改）


# ===========================================================================
# S117：premarket S101 f_date off-by-one —— prev_trading_date_str 非 last
# ===========================================================================


def test_prev_trading_date_str_returns_prev_not_same_day():
    """S117：prev_trading_date_str(d) 返 d 之前交易日（非 d 本身）——off-by-one 修复核心。

    S101 原用 last_trading_date_str()（d 为交易日→返 d 本身=T 日），final_candidates 存在
    F 日→_load_final_cards(T 日)找不到→no_candidates→S101 整式空转。prev_trading_date_str()
    返 F 日（严格前一交易日）。钉死 prev≠last（d=交易日时 last 返 d，prev 返前一）。
    """
    import vr_paths
    from datetime import date

    # Arrange：d=2026-08-28（周五，交易日）
    d = date(2026, 8, 28)

    # Act
    last = vr_paths.last_trading_date_str(d)   # 旧逻辑（bug 源）：交易日返 d 本身
    prev = vr_paths.prev_trading_date_str(d)   # S117 修：前一交易日

    # Assert：prev=前一交易日（2026-08-27 周四），非 d 本身；last=d 本身（off-by-one 源）
    assert prev == "2026-08-27"
    assert last == "2026-08-28"  # last 返 d 本身——这正是 S101 原 bug 源
    assert prev != last  # prev≠last，钉死 S101 须用 prev 非 last


def test_premarket_t1_review_uses_prev_trading_day_for_f_date(monkeypatch):
    """S117 behavioral：t1_review 空 payload → f_date=prev trading day（F 日）非 today（T 日），
    _load_final_cards 以 F 日调用 → candidates 找到 → notified（非 no_candidates 整式空转）。

    钉死 S101 三时点通知 off-by-one 修复：若有人回退 f_date=last_trading_date_str()（T 日），
    _load_final_cards(T 日)找不到 candidates→no_candidates 跳过→notified=False，本测 RED。
    """
    import scheduled_tasks as st
    import vr_paths

    # Arrange：mock prev_trading_date_str 返固定 F 日（测 S101 调它 + 用其值，vr_paths 逻辑由上测覆盖）
    F_DATE = "2026-08-27"
    monkeypatch.setattr(vr_paths, "prev_trading_date_str", lambda d=None: F_DATE)

    # mock _load_final_cards：记录 f_date + 返非空 candidates（让任务过 no_candidates 分支）
    captured = {"f_date": None}
    def _fake_load(fd):
        captured["f_date"] = fd
        return [{"code": "600519", "name": "贵州茅台"}]  # 非空 → 不跳过
    monkeypatch.setattr(st, "_load_final_cards", _fake_load)
    # mock _compute_t1_returns + _build_t1_review_content + _send_notify（避免真实计算/网络）
    monkeypatch.setattr(st, "_compute_t1_returns",
                        lambda cards, f, t: [{"code": "600519", "t1_return_pct": 5.0}])
    monkeypatch.setattr(st, "_build_t1_review_content", lambda f, t, r: "t1 review content")
    monkeypatch.setattr(st, "_send_notify", lambda content: True)

    # Act：空 payload（seed 默认 payload={}），任务内部 f_date = prev_trading_date_str() = F_DATE
    executor = st.TaskExecutor()
    result = executor._execute_premarket_t1_review({})

    # Assert：f_date=F 日（prev trading day），_load_final_cards 以 F 日调用非 T 日
    assert captured["f_date"] == F_DATE  # F 日，非 today（T 日）
    assert result["status"] == "ok"
    assert result.get("notified") is True  # candidates 找到 → 发了通知（非 no_candidates 空转）
