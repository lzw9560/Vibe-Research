# -*- coding: utf-8 -*-
"""S219 #11 fund 前向累积 executor 离线单测。

验证工程底线（deep-review #8 finding 3）：
- UPDATE-only-fund：仅改 fund/fundamt 两列，绝不 DELETE+INSERT 整日
  （DELETE+INSERT 会毁 consecutive_relay 生产 lbc）
- 不翻 is_final（终盘标记不被非终盘 fund 刷新翻动）
- 不碰 lbc/fbt/source/name/hybk（连板数/首封时间/来源/名称/行业保持原值）

不联网：monkeypatch astock.em_zt_topic_pool 返预填池（同 snapshot_zt_pool 测试范式）。
AAA + 描述性命名。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

import astock  # noqa: E402
import data.zt_history_store as zth  # noqa: E402
from scheduler.executors.fund_accum import fund_accumulation  # noqa: E402


# 预填涨停池——3 只（snapshot_zt_pool 写入 fund/fundamt/lbc/fbt/is_final）
_SEED_POOL = [
    {"c": "600127", "n": "金健米业", "lbc": 2, "zbc": 0, "fbt": 93500, "fund": 1e8,
     "zje": 5.30, "p": 5.30, "ltsz": 1e9, "fundamt": 2e8, "hybk": "AI"},
    {"c": "001358", "n": "兴欣新材", "lbc": 1, "zbc": 1, "fbt": 101500, "fund": 5e5,
     "zje": 10.21, "p": 10.21, "ltsz": 5e8, "fundamt": 3e7, "hybk": "芯片"},
    {"c": "300044", "n": "赛为智能", "lbc": 3, "zbc": 0, "fbt": 92500, "fund": 8e7,
     "zje": 7.5, "p": 7.5, "ltsz": 2e9, "fundamt": 9e7, "hybk": "AI"},
]

# em 当日涨停池——只含 2 只（300044 不在 em 池 → 证 no DELETE：若 DELETE+INSERT，
# 300044 会被删；UPDATE-only 则 300044 原值保留）。fund/fundamt 给新值，lbc/fbt/hybk 给
# 扰动值（证这些列不被 fund 刷新碰）
_EM_POOL = [
    {"c": "600127", "n": "FAKE_NAME", "lbc": 99, "fbt": 99999, "fund": 1.5e8,
     "fundamt": 2.5e8, "hybk": "FAKE_HYBK"},
    {"c": "001358", "n": "FAKE_NAME", "lbc": 88, "fbt": 88888, "fund": 9e5,
     "fundamt": 5e7, "hybk": "FAKE_HYBK"},
]


def _seed(monkeypatch, tmp_path, *, is_final: bool = True) -> str:
    """把 zt_history _DB_PATH 指到 tmp + 预填 3 行。返回 date。"""
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")
    date = "2026-09-18"
    zth.snapshot_zt_pool(date, pool=_SEED_POOL, is_final=is_final)
    return date


# ── UPDATE-only-fund：核心红线 ─────────────────────────────────────────────

def test_fund_accumulation_updates_only_fund_preserves_lbc_fbt_is_final(monkeypatch, tmp_path):
    # Arrange：预填 3 行（is_final=True，证 fund 刷新不翻 is_final）+ mock em 返 2 只
    date = _seed(monkeypatch, tmp_path, is_final=True)
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: _EM_POOL)

    # Act
    result = fund_accumulation({"date": date})

    # Assert：返结构
    assert result["status"] == "ok"
    assert result["date"] == date
    assert result["n_updated"] == 2  # 600127 + 001358 命中；300044 不在 em 池不算
    assert result["source"] == "em"

    rows = {r["code"]: r for r in zth.load_zt_history(date, date)}
    assert len(rows) == 3  # 行数不变 → no DELETE+INSERT（300044 未被删）

    # 600127：fund/fundamt 刷新为新值；lbc/fbt/source/name/hybk/is_final 全保留原值
    r = rows["600127"]
    assert r["fund"] == 1.5e8          # 新值（原 1e8）
    assert r["fundamt"] == 2.5e8      # 新值（原 2e8）
    assert r["lbc"] == 2              # 原值（em 给 99 但不读 lbc → 保留）
    assert r["fbt"] == 93500.0        # 原值（em 给 99999 但不碰 fbt）
    assert r["source"] == "predefined"  # 原值（不碰 source）
    assert r["name"] == "金健米业"     # 原值（em 给 FAKE_NAME 但不碰 name）
    assert r["hybk"] == "AI"          # 原值（em 给 FAKE_HYBK 但不碰 hybk）
    assert r["is_final"] == 1         # 不翻 is_final（仍 True）

    # 001358：同上
    r = rows["001358"]
    assert r["fund"] == 9e5
    assert r["fundamt"] == 5e7
    assert r["lbc"] == 1
    assert r["fbt"] == 101500.0
    assert r["is_final"] == 1

    # 300044：不在 em 池 → 全列原值保留（证 no DELETE：若 DELETE+INSERT 此行已消失）
    r = rows["300044"]
    assert r["fund"] == 8e7           # 原值未动
    assert r["fundamt"] == 9e7
    assert r["lbc"] == 3
    assert r["fbt"] == 92500.0
    assert r["is_final"] == 1


def test_fund_accumulation_does_not_flip_is_final_when_seeded_non_final(monkeypatch, tmp_path):
    # Arrange：预填 3 行 is_final=False + mock em 返 2 只
    date = _seed(monkeypatch, tmp_path, is_final=False)
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: _EM_POOL)

    # Act
    result = fund_accumulation({"date": date})

    # Assert：is_final 仍 0（fund 刷新不把非终盘翻成终盘，也不反向翻）
    assert result["status"] == "ok"
    rows = {r["code"]: r for r in zth.load_zt_history(date, date)}
    assert all(r["is_final"] == 0 for r in rows.values())
    assert rows["600127"]["fund"] == 1.5e8  # fund 确实刷了


# ── 降级路径 ────────────────────────────────────────────────────────────────

def test_fund_accumulation_empty_pool_degraded(monkeypatch, tmp_path):
    # Arrange：预填 3 行 + mock em 返空池（非交易日/端点空）
    date = _seed(monkeypatch, tmp_path, is_final=True)
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: [])

    # Act
    result = fund_accumulation({"date": date})

    # Assert：degraded + 0 行更新 + 原行不动
    assert result["status"] == "degraded"
    assert result["n_updated"] == 0
    rows = zth.load_zt_history(date, date)
    assert len(rows) == 3
    assert {r["code"] for r in rows} == {"600127", "001358", "300044"}
    # 原值保留
    r = next(r for r in rows if r["code"] == "600127")
    assert r["fund"] == 1e8 and r["lbc"] == 2


def test_fund_accumulation_em_error(monkeypatch, tmp_path):
    # Arrange：预填 3 行 + mock em raise
    date = _seed(monkeypatch, tmp_path, is_final=True)

    def _boom(*a, **k):
        raise RuntimeError("em 断连")

    monkeypatch.setattr(astock, "em_zt_topic_pool", _boom)

    # Act
    result = fund_accumulation({"date": date})

    # Assert：error + 0 行更新 + 原行不动（不 crash）
    assert result["status"] == "error"
    assert result["n_updated"] == 0
    assert "em 断连" in result["error"]
    rows = zth.load_zt_history(date, date)
    assert len(rows) == 3
    r = next(r for r in rows if r["code"] == "600127")
    assert r["fund"] == 1e8  # 未被破坏


# ── helper 边界 ─────────────────────────────────────────────────────────────

def test_backfill_fund_only_empty_date_or_map_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")
    zth.snapshot_zt_pool("2026-09-18", pool=_SEED_POOL, is_final=True)

    assert zth.backfill_fund_only("", {"600127": {"fund": 1, "fundamt": 2}}) == 0
    assert zth.backfill_fund_only("2026-09-18", {}) == 0
    assert zth.backfill_fund_only("2026-09-18", None) == 0


def test_backfill_fund_only_skips_codes_not_in_db(monkeypatch, tmp_path):
    # Arrange：只预填 600127 一行 + 不在 DB 的 code
    monkeypatch.setattr(zth, "_DB_PATH", tmp_path / "zt_history.db")
    zth.snapshot_zt_pool("2026-09-18", pool=[_SEED_POOL[0]], is_final=True)

    # Act：fund_map 含 DB 有的 600127 + DB 没的 999999
    n = zth.backfill_fund_only("2026-09-18", {
        "600127": {"fund": 1.5e8, "fundamt": 2.5e8},
        "999999": {"fund": 1e9, "fundamt": 2e9},  # 不在 DB → 0 命中
    })

    # Assert：只 1 行命中（999999 不算，不 INSERT 新行）
    assert n == 1
    rows = zth.load_zt_history("2026-09-18", "2026-09-18")
    assert len(rows) == 1  # 没 INSERT 999999
    assert rows[0]["code"] == "600127"
    assert rows[0]["fund"] == 1.5e8
