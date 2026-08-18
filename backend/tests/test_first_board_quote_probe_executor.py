# -*- coding: utf-8 -*-
"""S076 first_board_quote_probe 调度执行器——push2 状态门控单测。

验 _execute_first_board_quote_probe 的东财 push2 ≥10min 状态文件门控逻辑：
- 无状态文件 → push2 含（last=0，time-0>=600）
- 状态新（刚写）→ push2 不含
- 状态旧（700s 前）→ push2 含

mock 探查函数（不联网），只测调度门控 glue。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
sys.path.insert(0, str(ROOT))

import scheduled_tasks  # noqa: E402  conftest VR_DATA_DIR→tmp，_manager SQLite 开 tmp DB
import tools.first_board_quote_source_probe as probe  # noqa: E402


def _patch_probe(monkeypatch, tmp_path):
    """mock 探查函数 + 固定 OUT_DIR/间隔，隔离网络 + 文件。"""
    monkeypatch.setattr(probe, "probe_once",
                        lambda codes, sources=None: {"time": "09:20:00", "tencent": {"ok": True},
                                                      "mootdx": {"ok": False},
                                                      **({"em_push2": {"ok": True}}
                                                         if "em_push2" in (sources or []) else {})})
    monkeypatch.setattr(probe, "_append_row", lambda row: tmp_path / "matrix.json")
    monkeypatch.setattr(probe, "OUT_DIR", tmp_path)
    monkeypatch.setattr(probe, "EM_PUSH2_MIN_INTERVAL_S", 600)


def test_no_state_file_includes_push2_and_writes_state(monkeypatch, tmp_path):
    # Arrange：无状态文件
    _patch_probe(monkeypatch, tmp_path)
    (tmp_path / "push2_state.json").unlink(missing_ok=True)
    ex = scheduled_tasks.TaskExecutor()

    # Act
    r = ex._execute_first_board_quote_probe({})

    # Assert：push2 含 + 状态文件写
    assert "em_push2" in r["sources"]
    assert (tmp_path / "push2_state.json").exists()
    assert r["tencent_ok"] is True


def test_fresh_state_excludes_push2(monkeypatch, tmp_path):
    # Arrange：刚写过状态（call1），立即 call2
    _patch_probe(monkeypatch, tmp_path)
    ex = scheduled_tasks.TaskExecutor()
    ex._execute_first_board_quote_probe({})  # 写状态

    # Act：立即第二次
    r2 = ex._execute_first_board_quote_probe({})

    # Assert：push2 不含（<600s）
    assert "em_push2" not in r2["sources"]
    assert r2["sources"] == ["tencent", "mootdx"]


def test_stale_state_includes_push2(monkeypatch, tmp_path):
    # Arrange：状态 700s 前（≥600）
    _patch_probe(monkeypatch, tmp_path)
    (tmp_path / "push2_state.json").write_text(
        json.dumps({"last_push2_ts": time.time() - 700}))
    ex = scheduled_tasks.TaskExecutor()

    # Act
    r = ex._execute_first_board_quote_probe({})

    # Assert：push2 含
    assert "em_push2" in r["sources"]


def test_payload_codes_override_default(monkeypatch, tmp_path):
    # Arrange
    _patch_probe(monkeypatch, tmp_path)
    seen_codes = []
    monkeypatch.setattr(probe, "probe_once",
                        lambda codes, sources=None: (seen_codes.append(codes),
                                                     {"time": "09:20", "tencent": {"ok": True}})[1])
    ex = scheduled_tasks.TaskExecutor()

    # Act：payload 带 codes
    ex._execute_first_board_quote_probe({"codes": ["600519", "000001"]})

    # Assert：用 payload codes（probe_once 收到 codes list）
    assert seen_codes == [["600519", "000001"]]
