# -*- coding: utf-8 -*-
"""S076 首板流多源行情探查脚本——离线 mock 单测（spec §8 离线单测）。

不联网：mock astock.tencent_quote，验 probe_once 结构 + sane 逻辑 + 矩阵追加 round-trip。
mootdx/em_push2 探查逻辑是"记录 raw + error"，trivial 不单测（其复杂度在真实联网行为，归 live 验收）。
AAA 结构 + 描述性命名。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

import tools.first_board_quote_source_probe as probe  # noqa: E402


# ── 纯函数 ────────────────────────────────────────────────────────────────────

def test_secid_sh_sz_and_invalid():
    assert probe._secid("600127") == "1.600127"   # 沪市主板
    assert probe._secid("688981") == "1.688981"   # 科创板
    assert probe._secid("001358") == "0.001358"   # 深市主板
    assert probe._secid("300750") == "0.300750"   # 创业板
    assert probe._secid("1234") is None            # 长度不对
    assert probe._secid("abc123") is None          # 非数字
    assert probe._secid("") is None


def test_to_float_handles_garbage():
    assert probe._to_float(None) is None
    assert probe._to_float(True) is None
    assert probe._to_float("-") is None
    assert probe._to_float("--") is None
    assert probe._to_float("null") is None
    assert probe._to_float("3.14") == 3.14
    assert probe._to_float(3) == 3.0
    assert probe._to_float("1,234.5") == 1234.5


# ── probe_once（tencent mocked）───────────────────────────────────────────────

def _patch(monkeypatch, tmp_path, quotes: dict):
    """mock tencent + 固定 OUT_DIR/today，隔离文件 IO。"""
    monkeypatch.setattr("astock.tencent_quote", lambda codes: quotes)
    monkeypatch.setattr(probe, "OUT_DIR", tmp_path)
    monkeypatch.setattr(probe, "_today_str", lambda: "20260818")


def test_probe_once_tencent_mocked_structure_and_sane(monkeypatch, tmp_path):
    # Arrange：600127 高开 +6%/量比 1.8；001358 高开 +2.1%/量比 0.5
    quotes = {
        "600127": {"name": "金健米业", "price": 5.30, "last_close": 5.0,
                   "open": 5.30, "vol_ratio": 1.8, "amount_wan": 3000.0, "change_pct": 6.0},
        "001358": {"name": "兴欣新材", "price": 10.21, "last_close": 10.0,
                   "open": 10.21, "vol_ratio": 0.5, "amount_wan": 500.0, "change_pct": 2.1},
    }
    _patch(monkeypatch, tmp_path, quotes)

    # Act
    row = probe.probe_once(["600127", "001358"], sources=["tencent"])

    # Assert：结构 + sane
    assert row["time"]
    assert row["tencent"]["source"] == "tencent"
    assert row["tencent"]["ok"] is True
    assert row["tencent"]["latency_ms"] is not None
    pc = row["tencent"]["per_code"]["600127"]
    assert pc["open"]["non_empty"] is True
    assert pc["open"]["val"] == 5.30
    assert pc["last_close"]["non_empty"] is True
    assert pc["vol_ratio"]["non_empty"] is True
    assert pc["open_pct"]["val"] == 6.0
    assert pc["open_pct"]["sane"] is True       # +6% 在 (-11, 11)
    assert pc["vol_ratio"]["sane"] is True      # 1.8 在 (0, 30)
    pc2 = row["tencent"]["per_code"]["001358"]
    assert pc2["open_pct"]["val"] == 2.1
    assert pc2["vol_ratio"]["sane"] is True


def test_probe_once_tencent_empty_returns_non_empty_false(monkeypatch, tmp_path):
    # Arrange：tencent 返空 dict（模拟 9:25 open 未生成）
    _patch(monkeypatch, tmp_path, {})

    # Act
    row = probe.probe_once(["600127"], sources=["tencent"])

    # Assert
    assert row["tencent"]["ok"] is False
    assert row["tencent"]["per_code"]["600127"]["non_empty"] is False


def test_probe_once_tencent_insane_high_open_flagged(monkeypatch, tmp_path):
    # Arrange：高开 +20% 超过 SANE_OPEN_PCT 上限 11
    _patch(monkeypatch, tmp_path, {
        "600127": {"name": "X", "price": 6.0, "last_close": 5.0,
                   "open": 6.0, "vol_ratio": 1.5, "amount_wan": 100, "change_pct": 20.0}})

    # Act
    pc = probe.probe_once(["600127"], sources=["tencent"])["tencent"]["per_code"]["600127"]

    # Assert：sane=False 但仍记录原值（不丢数据）
    assert pc["open_pct"]["val"] == 20.0
    assert pc["open_pct"]["sane"] is False


# ── 矩阵追加 round-trip ──────────────────────────────────────────────────────

def test_append_row_matrix_round_trip(monkeypatch, tmp_path):
    # Arrange
    _patch(monkeypatch, tmp_path, {})

    # Act：追加两行
    probe._append_row(probe.probe_once(["600127"], sources=["tencent"]))
    probe._append_row(probe.probe_once(["001358"], sources=["tencent"]))

    # Assert：矩阵持久化 + 两行
    matrix = json.loads((tmp_path / "matrix_20260818.json").read_text(encoding="utf-8"))
    assert matrix["date"] == "20260818"
    assert len(matrix["rows"]) == 2
    assert matrix["rows"][0]["tencent"]["source"] == "tencent"
    assert matrix["rows"][1]["tencent"]["source"] == "tencent"
