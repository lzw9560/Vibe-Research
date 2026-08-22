# -*- coding: utf-8 -*-
"""S095 gene_scores 写路径未来日期守卫 + 交叉校验单测。

覆盖 spec §3 AC1-AC5：
- AC1 `precompute_daily_async('2026-08-29')`（未来日期）返空结果 + 不查东财
- AC2 `precompute_daily_async('2026-08-21')`（历史交易日）正常走到算分路径
- AC3 `precompute_daily_async(last_trading_date_str())` 当天盘中请求合法
- AC4 `precompute_daily_async('2026-08-30')`（远期未来）返空
- AC5 交叉校验：zt_history final 快照与请求池不一致 → 拒绝写入返空

测试用 monkeypatch + asyncio.run（未装 pytest-asyncio），不打真东财。
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from limitup_screener import service as svc
from limitup_screener.service import (
    _assert_not_future_date,
    _cross_check_zt_history,
    precompute_daily_async,
)


# ─── 公共工具 ────────────────────────────────────────────────────────────

def _patch_last_trading(monkeypatch, fixed: str = "2026-08-21"):
    """patch last_trading_date_str 返固定值，保证测试稳定。"""
    monkeypatch.setattr(svc, "last_trading_date_str", lambda d=None: fixed)


def _empty_pool():
    """_fetch_zt_pool 调用计数器：返空三元组 + 记录调用次数。"""
    calls = {"count": 0}

    async def _fake(date):
        calls["count"] += 1
        return [], [], []

    return _fake, calls


def _fixed_pool(codes: list[str]):
    """_fetch_zt_pool 返固定非空 zt_pool（命中算分路径）。"""
    from models.market_snapshot import ZTPoolItem

    items = [ZTPoolItem(code=c, name=f"股票{c}", boards=1) for c in codes]
    calls = {"count": 0}

    async def _fake(date):
        calls["count"] += 1
        return items, [], []

    return _fake, calls


async def _empty_history_async(codes, date, lookback=252):
    """_collect_zt_history_batch stub：返空历史，避免真 em 请求。"""
    return {c: [] for c in codes}


# ─── AC1：未来日期返空 + 不查东财 ────────────────────────────────────────

def test_ac1_future_date_returns_empty_no_em(monkeypatch):
    """AC1：precompute_daily_async('2026-08-29')（周六，未来）→ 返空结果 + em 零调用。"""
    # 最近交易日 = 2026-08-21 周五；2026-08-29 周六 > 08-21 → 拒绝
    _patch_last_trading(monkeypatch, "2026-08-21")

    em_calls = {"count": 0}

    def _fake_em(*args, **kwargs):
        em_calls["count"] += 1
        return []

    monkeypatch.setattr(svc.astock, "em_zt_topic_pool", _fake_em)

    result = asyncio.run(precompute_daily_async("2026-08-29"))

    assert result.gene_scores == []
    assert result.qualified == []
    assert result.high_gene == []
    assert em_calls["count"] == 0, "未来日期不应查东财"


# ─── AC2：历史交易日正常走到算分路径 ───────────────────────────────────

def test_ac2_past_trading_day_reaches_scoring(monkeypatch):
    """AC2：precompute_daily_async('2026-08-21')（历史交易日）→ 正常走到算分路径。

    用 monkeypatch _fetch_zt_pool 返固定非空池，断言 em 被调用（通过算分路径）、
    save_gene_scores 被调用（写入成功），结果 date 正确。
    """
    _patch_last_trading(monkeypatch, "2026-08-21")

    fetch_fake, fetch_calls = _fixed_pool(["000001", "000002"])
    monkeypatch.setattr(svc, "_fetch_zt_pool", fetch_fake)

    # _collect_zt_history_batch 也走 em，stub 返空避免真请求
    monkeypatch.setattr(svc, "_collect_zt_history_batch", _empty_history_async)

    # _fetch_zt_next_pool 也走 em，stub 返空
    monkeypatch.setattr(svc, "_fetch_zt_next_pool", lambda d: [])

    save_calls = {"count": 0}

    def _fake_save(date_str, scores):
        save_calls["count"] += 1

    monkeypatch.setattr(svc, "save_gene_scores", _fake_save)

    result = asyncio.run(precompute_daily_async("2026-08-21"))

    # 走到了 _fetch_zt_pool（通过守卫）
    assert fetch_calls["count"] == 1, "应通过守卫走到 _fetch_zt_pool"
    # 走到了 save_gene_scores（算分路径完整跑完）
    assert save_calls["count"] == 1, "应走到 save_gene_scores（算分路径完整）"
    # 结果 date 标签正确（2026-08-21）
    assert result.date == "2026-08-21"
    # gene_scores 非空（两只票的得分都算出来了）
    assert len(result.gene_scores) == 2


# ─── AC3：当天盘中请求合法 ─────────────────────────────────────────────

def test_ac3_current_trading_day_allowed(monkeypatch):
    """AC3：precompute_daily_async(last_trading_date_str()) 当天请求合法（守卫放行）。

    验证 _assert_not_future_date 对当天返回 True（不拒绝）。
    """
    # last_trading_date_str 返 2026-08-21，请求同一天 → 放行
    _patch_last_trading(monkeypatch, "2026-08-21")

    # 直接验证守卫放行
    assert _assert_not_future_date("20260821") is True
    assert _assert_not_future_date("2026-08-21") is True

    # 并验证 precompute_daily_async 不被守卫拦截（走到 _fetch_zt_pool 即放行）
    fetch_fake, fetch_calls = _empty_pool()
    monkeypatch.setattr(svc, "_fetch_zt_pool", fetch_fake)

    result = asyncio.run(precompute_daily_async("2026-08-21"))

    # 当天放行 → 走到 _fetch_zt_pool（虽然池空返空结果，但说明守卫没拦）
    assert fetch_calls["count"] == 1, "当天请求应放行走到 _fetch_zt_pool"


# ─── AC4：远期未来返空 ────────────────────────────────────────────────

def test_ac4_far_future_returns_empty(monkeypatch):
    """AC4：precompute_daily_async('2026-08-30')（周日，远期未来）→ 返空。"""
    _patch_last_trading(monkeypatch, "2026-08-21")

    em_calls = {"count": 0}

    def _fake_em(*args, **kwargs):
        em_calls["count"] += 1
        return []

    monkeypatch.setattr(svc.astock, "em_zt_topic_pool", _fake_em)

    result = asyncio.run(precompute_daily_async("2026-08-30"))

    assert result.gene_scores == []
    assert em_calls["count"] == 0, "远期未来不应查东财"


# ─── AC5：交叉校验 final 不一致拒绝写入 ─────────────────────────────────

def test_ac5_cross_check_final_mismatch_rejects(monkeypatch, tmp_path):
    """AC5：zt_history final 快照 54 行，_fetch_zt_pool 返 50 只 → 拒绝写入返空。

    monkeypatch resolve_data_dir 指 tmp_path，在该目录建 zt_history.db 写入 54 行
    final 快照。请求 2026-08-21（≤ 最近交易日，过守卫），_fetch_zt_pool 返 50 只，
    交叉校验发现 54 != 50 且 final → 拒绝写入返空。
    """
    _patch_last_trading(monkeypatch, "2026-08-21")

    # resolve_data_dir 指 tmp_path（_cross_check_zt_history 内部 import）
    monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: tmp_path)

    # 建库 + 写 54 行 final 快照（date=2026-08-21）
    db_path = tmp_path / "zt_history.db"
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS zt_history (
            date TEXT NOT NULL, code TEXT NOT NULL, name TEXT,
            is_final INTEGER DEFAULT 0,
            PRIMARY KEY (date, code)
        )"""
    )
    conn.execute("DELETE FROM zt_history WHERE date = '2026-08-21'")
    conn.executemany(
        "INSERT INTO zt_history (date, code, name, is_final) VALUES (?, ?, ?, 1)",
        [("2026-08-21", f"{i:06d}", f"股票{i}") for i in range(54)],
    )
    conn.commit()
    conn.close()

    # 直接验证交叉校验函数：50 != 54 且 final → 拒绝
    assert _cross_check_zt_history("20260821", 50) is False
    assert _cross_check_zt_history("2026-08-21", 50) is False

    # 54 == 54 → 放行（final 且一致）
    assert _cross_check_zt_history("20260821", 54) is True

    # 端到端：precompute_daily_async 2026-08-21（过守卫）→ _fetch_zt_pool 返 50 只
    # → 交叉校验拒绝 → 返空
    fetch_fake, fetch_calls = _fixed_pool([f"{i:06d}" for i in range(50)])
    monkeypatch.setattr(svc, "_fetch_zt_pool", fetch_fake)
    monkeypatch.setattr(svc, "_collect_zt_history_batch", _empty_history_async)
    monkeypatch.setattr(svc, "_fetch_zt_next_pool", lambda d: [])

    save_calls = {"count": 0}

    def _fake_save(date_str, scores):
        save_calls["count"] += 1

    monkeypatch.setattr(svc, "save_gene_scores", _fake_save)

    result = asyncio.run(precompute_daily_async("2026-08-21"))

    # 交叉校验拒绝写入：走到 _fetch_zt_pool（过了守卫），但 save_gene_scores 不应被调
    assert fetch_calls["count"] == 1, "应过守卫走到 _fetch_zt_pool"
    assert save_calls["count"] == 0, "交叉校验不一致应拒绝写入（不 save）"
    assert result.gene_scores == [], "交叉校验拒绝 → 返空结果"
