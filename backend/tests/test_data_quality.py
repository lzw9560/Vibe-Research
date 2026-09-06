# -*- coding: utf-8 -*-
"""S163 数据质量门 + 轻量血缘测试（R1-R3）。

覆盖（spec §4 验收标准）：
- R1 schema 校验（5 源）拒绝 bad data 进 §44 —— shape/content/missing/anomaly/freshness 五维。
- R2 血缘记录（script+commit+as_of+io hash）可追溯 + write-once/append-only + recompute-verify。
- R3 9 脚本 ROOT 参数化（不硬编码，主 checkout 跑得通）。

纯离线：R1 直接调 validate（无联网，校验层不直连源，§1.2 em_get 防封）；
R2 用 monkeypatch.setenv("VR_DATA_DIR", tmp_path) 每测隔离 lineage store（conftest 全局
tmp 之外再 per-test 隔离，防 write-once 跨测污染）；R3 读源文件文本校验参数化（不执行
数据重型脚本，避免缺 cache/DB 崩）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from data_quality.schema_validator import (
    SCHEMA_REGISTRY,
    DataQualityError,
    validate,
    validate_or_reject,
)
from data_quality.lineage import (
    LineageError,
    compute_hash,
    current_commit,
    artifact_exists,
    list_records,
    record,
    recompute_verify,
)


# ===========================================================================
# R1：源边界 schema 校验 —— bad data 拒绝进 §44
# ===========================================================================

class TestBaostockKline:
    """baostock 日 K 线校验（OHLCV + 完整性 + 时效）。"""

    GOOD_ROWS = [
        {"date": "2026-09-01", "open": 10.0, "high": 10.5, "low": 9.8,
         "close": 10.3, "volume": 1000.0},
        {"date": "2026-09-02", "open": 10.3, "high": 10.8, "low": 10.1,
         "close": 10.6, "volume": 2000.0},
        {"date": "2026-09-03", "open": 10.6, "high": 11.0, "low": 10.4,
         "close": 10.9, "volume": 1500.0},
    ]

    def test_good_data_passes(self):
        result = validate("baostock_kline", self.GOOD_ROWS, as_of="2026-09-03")
        assert result.ok, f"应通过：{result.errors}"
        assert result.row_count == 3
        assert result.freshness_ok
        assert result.last_date == "2026-09-03"

    def test_missing_required_field_rejected(self):
        bad = [{"date": "2026-09-01", "open": 10.0, "high": 10.5, "low": 9.8}]  # 无 close
        result = validate("baostock_kline", bad, as_of="2026-09-01")
        assert not result.ok
        assert any("close" in e for e in result.errors)

    def test_negative_price_anomaly_rejected(self):
        bad = [{"date": "2026-09-01", "open": -10.0, "high": 10.5, "low": 9.8,
                "close": 10.3, "volume": 1000.0}]
        result = validate("baostock_kline", bad, as_of="2026-09-01")
        assert not result.ok
        assert any("越界" in e for e in result.errors)

    def test_high_below_low_integrity_rejected(self):
        # high < low = 坏 bar（OHLC 完整性违反，脏数据）
        bad = [{"date": "2026-09-01", "open": 10.0, "high": 9.5, "low": 10.5,
                "close": 10.3, "volume": 1000.0}]
        result = validate("baostock_kline", bad, as_of="2026-09-01")
        assert not result.ok
        assert any("完整性" in e for e in result.errors)

    def test_stale_data_rejected(self):
        # last_date 距 as_of 超 7 天 → stale → ok=False（不污染 verdict）
        stale = [{"date": "2026-08-20", "open": 10.0, "high": 10.5, "low": 9.8,
                  "close": 10.3, "volume": 1000.0}]
        result = validate("baostock_kline", stale, as_of="2026-09-06")
        assert not result.freshness_ok
        assert not result.ok
        assert any("stale" in e for e in result.errors)

    def test_empty_rows_below_min_rejected(self):
        result = validate("baostock_kline", [], as_of="2026-09-03")
        assert not result.ok
        assert any("行数" in e for e in result.errors)

    def test_wrong_shape_rejected(self):
        # 期望 list_of_dicts，给 dict → shape 不符
        result = validate("baostock_kline", {"000001": []}, as_of="2026-09-03")
        assert not result.ok
        assert any("shape" in e for e in result.errors)


class TestThsLimitUp:
    """同花顺涨停揭秘校验（code 承重，空池合法）。"""

    def test_good_data_passes(self):
        rows = [{"code": "000001", "reason": "5G", "high_days": "2天2板"},
                {"code": "600519", "reason": "白酒", "high_days": "1天1板"}]
        result = validate("ths_limit_up_pool", rows, as_of="2026-09-03")
        assert result.ok, f"应通过：{result.errors}"
        assert result.row_count == 2

    def test_empty_pool_is_valid(self):
        # 非涨停日 / 降级返空合法（min_rows=0）—— 非污染 verdict
        result = validate("ths_limit_up_pool", [], as_of="2026-09-03")
        assert result.ok, f"空池应合法：{result.errors}"

    def test_missing_code_exceeds_missing_rate(self):
        # code 缺失率超 2% → 拒绝
        rows = [{"code": None, "reason": "x"}, {"code": "000001", "reason": "y"}]
        result = validate("ths_limit_up_pool", rows, as_of="2026-09-03")
        assert not result.ok
        assert any("code" in e and "缺失" in e for e in result.errors)


class TestEmZtTopicPool:
    """东财涨停板行情池校验（lbc 承重，>=1）。"""

    def test_good_data_passes(self):
        rows = [{"code": "000001", "lbc": 2, "zbc": 0, "hybk": "通信"},
                {"code": "600519", "lbc": 1, "zbc": 1, "hybk": "白酒"}]
        result = validate("em_zt_topic_pool", rows, as_of="2026-09-03")
        assert result.ok, f"应通过：{result.errors}"

    def test_lbc_zero_rejected(self):
        # 涨停股连板数 >=1；lbc=0 = 坏数据（非涨停项混入）
        rows = [{"code": "000001", "lbc": 0, "zbc": 0}]
        result = validate("em_zt_topic_pool", rows, as_of="2026-09-03")
        assert not result.ok
        assert any("lbc" in e and "越界" in e for e in result.errors)


class TestHithinkValuation:
    """hithink 估值快照校验（PE/PB/PS/PCF 可 None，非数值 = 坏数据）。"""

    def test_good_data_passes(self):
        data = {"000001": {"pe_ttm": 15.2, "pb_mrq": 2.1, "ps_ttm": 3.5, "pcf_ttm": None}}
        result = validate("hithink_valuation", data, as_of="2026-09-03")
        assert result.ok, f"应通过：{result.errors}"
        assert result.row_count == 1

    def test_non_numeric_pe_rejected(self):
        # pe_ttm 是字符串 = 类型不符 = 坏数据
        data = {"000001": {"pe_ttm": "N/A", "ps_ttm": 3.5}}
        result = validate("hithink_valuation", data, as_of="2026-09-03")
        assert not result.ok
        assert any("pe_ttm" in e and "类型" in e for e in result.errors)

    def test_none_metric_values_not_rejected(self):
        # hithink 是补充源，各估值指标 None 正常（PE/PB 常缺）—— 不以缺失率拦，
        # 靠 type+value_range+shape 把关（None 不应触发拒绝）
        data = {"000001": {"pe_ttm": None, "ps_ttm": 3.5, "pcf_ttm": None}}
        result = validate("hithink_valuation", data, as_of="2026-09-03")
        assert result.ok, f"None 指标值不应拦：{result.errors}"


class TestAkshareForecast:
    """akshare 机构一致预期校验（列名浮动 → 结构 sanity）。"""

    def test_good_data_passes(self):
        rows = [{"机构": "中信", "预测年份": "2026", "每股收益预测": 2.1}]
        result = validate("akshare_profit_forecast", rows, as_of="2026-09-03")
        assert result.ok, f"应通过：{result.errors}"

    def test_empty_is_valid(self):
        # 无机构覆盖时空合法
        result = validate("akshare_profit_forecast", [], as_of="2026-09-03")
        assert result.ok, f"空应合法：{result.errors}"


class TestSchemaRegistry:
    """5 源注册表完整性 + 未知源拒绝 + validate_or_reject 接入点。"""

    def test_registry_has_five_sources(self):
        assert set(SCHEMA_REGISTRY.keys()) == {
            "baostock_kline", "ths_limit_up_pool", "em_zt_topic_pool",
            "hithink_valuation", "akshare_profit_forecast",
        }

    def test_unknown_source_rejected(self):
        result = validate("nonexistent_source", [{"x": 1}])
        assert not result.ok
        assert any("未知" in e for e in result.errors)

    def test_validate_or_reject_returns_data_on_good(self):
        rows = [{"code": "000001", "lbc": 1, "zbc": 0}]
        out = validate_or_reject("em_zt_topic_pool", rows, as_of="2026-09-03")
        assert out is rows  # 不可变，原样返

    def test_validate_or_reject_raises_on_bad(self):
        # bad data（lbc=0）→ 抛 DataQualityError，§44 verifier 不污染 verdict
        bad = [{"code": "000001", "lbc": 0, "zbc": 0}]
        with pytest.raises(DataQualityError) as ei:
            validate_or_reject("em_zt_topic_pool", bad, as_of="2026-09-03")
        assert not ei.value.result.ok


# ===========================================================================
# R2：轻量血缘 —— provenance trail + write-once/append-only + recompute-verify
# ===========================================================================

@pytest.fixture
def isolated_lineage(tmp_path, monkeypatch):
    """每测隔离 lineage store：VR_DATA_DIR → tmp_path（resolve_data_dir 读 env at call）。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    return tmp_path


class TestLineageRecord:
    """血缘记录 + 可追溯 + write-once/append-only（spec R2 acceptance）。"""

    def test_record_and_list_provenance_trail(self, isolated_lineage):
        rec = record(
            artifact_id="baostock_kline_cache", script="tools/overnight_gap_decomposition.py",
            as_of="2026-09-03", inputs={"pin": 1}, output={"rows": 3362},
        )
        assert rec.artifact_id == "baostock_kline_cache"
        assert rec.as_of == "2026-09-03"
        assert rec.inputs_hash == compute_hash({"pin": 1})
        assert rec.output_hash == compute_hash({"rows": 3362})
        assert rec.recompute_verified is False  # 诚实：未验证复算
        assert rec.commit  # commit 非空（git rev-parse 或 "unknown"）

        trail = list_records("baostock_kline_cache")
        assert len(trail) == 1
        assert trail[0].output_hash == rec.output_hash

    def test_write_once_rejects_exact_duplicate(self, isolated_lineage):
        # 同 (artifact_id, as_of, commit, output_hash) 已存在 → raise（不静默覆盖）
        record(artifact_id="X", script="s.py", as_of="2026-09-01",
               inputs={}, output={"v": 1})
        with pytest.raises(LineageError, match="write-once"):
            record(artifact_id="X", script="s.py", as_of="2026-09-01",
                   inputs={}, output={"v": 1})  # 完全相同

    def test_append_only_allows_different_as_of(self, isolated_lineage):
        # 不同 as_of 的重跑 = 新记录（append-only，合法）
        record(artifact_id="X", script="s.py", as_of="2026-09-01",
               inputs={}, output={"v": 1})
        record(artifact_id="X", script="s.py", as_of="2026-09-02",
               inputs={}, output={"v": 2})
        trail = list_records("X")
        assert len(trail) == 2  # append-only，两条都保留

    def test_compute_hash_canonical_and_deterministic(self):
        # 规范 JSON：key 顺序无关（sort_keys），同内容同哈希
        a = compute_hash({"a": 1, "b": [2, 3]})
        b = compute_hash({"b": [2, 3], "a": 1})
        assert a == b
        assert a != compute_hash({"a": 1, "b": [2, 4]})  # 内容不同 → 不同哈希

    def test_artifact_exists_catches_missing_artifact(self, isolated_lineage):
        # lazy-agent 声称已产出但无记录 → False → 暴露臆造（spec §0）
        assert not artifact_exists("never_produced")
        record(artifact_id="Y", script="s.py", as_of="2026-09-03",
               inputs={}, output={"v": 1})
        assert artifact_exists("Y")
        assert artifact_exists("Y", as_of="2026-09-03")
        assert not artifact_exists("Y", as_of="2026-09-01")  # as_of 不匹配

    def test_recompute_verify_match(self, isolated_lineage):
        output = {"verdict": "robust_edge", "lift": 2.1}
        record(artifact_id="Z", script="s.py", as_of="2026-09-03",
               inputs={"frozen": True}, output=output)
        # recompute_fn 返同 output → hash 匹配 → (True, ...)
        ok, rec, msg = recompute_verify(
            "Z", "2026-09-03", lambda as_of: output)
        assert ok, f"应复算一致：{msg}"
        assert rec is not None
        assert "一致" in msg

    def test_recompute_verify_mismatch(self, isolated_lineage):
        record(artifact_id="Z", script="s.py", as_of="2026-09-03",
               inputs={"frozen": True}, output={"v": 1})
        # recompute_fn 返不同 output → hash 不匹配 → (False, ...)
        ok, rec, msg = recompute_verify(
            "Z", "2026-09-03", lambda as_of: {"v": 999})
        assert not ok
        assert "不匹配" in msg

    def test_recompute_verify_missing_record(self, isolated_lineage):
        ok, rec, msg = recompute_verify(
            "nope", "2026-09-03", lambda as_of: {"v": 1})
        assert not ok
        assert rec is None
        assert "无记录" in msg

    def test_current_commit_returns_nonempty(self):
        # git rev-parse HEAD（本仓库）或 "unknown"——不臆造 hash
        c = current_commit()
        assert isinstance(c, str) and len(c) > 0


# ===========================================================================
# R3：9 脚本 ROOT 参数化（不硬编码，主 checkout 跑得通）
# ===========================================================================

# spec R3：9 脚本（grep Vibe-Research-S151 在 backend/tools/ 命中）
_HARNESS_SCRIPTS = [
    "overnight_gap_decomposition.py",
    "lianban_lift.py",
    "zt_pool_seal_time_lift.py",
    "gap_window_lift.py",
    "index_ma20_regime_fetch.py",
    "valuation_pe_lift.py",
    "block_trade_lift.py",
    "miaoban_superset_31d_lift.py",
    "index_ma20_regime_lift.py",
]


class TestHarnessRootParameterized:
    """9 脚本不再硬编码绝对路径，主 checkout 跑得通（spec R3 acceptance）。"""

    @pytest.mark.parametrize("name", _HARNESS_SCRIPTS)
    def test_no_hardcoded_absolute_path(self, name):
        path = Path(__file__).resolve().parent.parent / "tools" / name
        text = path.read_text(encoding="utf-8")
        # 硬编码 Vibe-Research-S151 绝对路径已清除（主 checkout 跑得通的前提）
        assert "Vibe-Research-S151" not in text, f"{name} 仍含硬编码绝对路径"
        # 已参数化为 repo root（与 ~25 兄弟脚本同约定）
        assert "parents[2]" in text, f"{name} 未参数化 ROOT"

    def test_root_resolves_to_repo_root(self):
        # parents[2] 从 backend/tools/X.py → repo 根（Vibe-Research/），主 checkout 跑得通
        sample = Path(__file__).resolve().parent.parent / "tools" / _HARNESS_SCRIPTS[0]
        repo_root = sample.resolve().parents[2]
        # repo 根含 backend/ + CLAUDE.md（主 checkout 标志）
        assert (repo_root / "backend").is_dir()
        assert (repo_root / "CLAUDE.md").is_file()
        # .vibe-research 在 repo 根下（数据文件 ROOT/'.vibe-research'/X 指向正确位置）
        assert (repo_root / ".vibe-research").exists()
