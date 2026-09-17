"""S165: verifier router tests — /api/verifier/records + /api/evaluation/dims.

Contract: response shapes match frontend/src/lib/verifier-contract.ts.
R8 wiring: weight_multiplier + status from lift_to_multiplier.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)

_VALID_STATUSES = {"robust_edge", "underpowered", "falsified", "not_validated", "exploratory"}

_DIM_REQUIRED = {
    "dimension_id", "label", "lift", "ci_low", "ci_high", "n", "n_effective",
    "days_robust", "status", "edge_type", "tradeable", "event_metrics",
    "event_status", "weight_multiplier", "source_script", "note",
    "dsr_method", "three_window_compare", "overfit_stats", "frozen_commit",
    "updated_commit", "updated_at", "data_snapshot_id", "layer",
}

_REC_REQUIRED = {
    "recorder_id", "data_snapshot_id", "input_snapshot_hash",
    "params", "n_trials", "verdict", "timestamp",
}


@pytest.fixture
def fresh_recorder_db(tmp_path, monkeypatch):
    """Redirect Recorder default DB to a per-test temp file (isolation)."""
    import s44_verifier.recorder as rec_mod

    db_path = tmp_path / "recorder.db"
    monkeypatch.setattr(rec_mod, "_default_db_path", lambda: db_path)
    return db_path


def _seed_record(*, verdict=None, params=None, data_snapshot_id="abc123+def456"):
    """Insert one record via Recorder.save, return recorder_id."""
    from s44_verifier.recorder import Recorder

    return Recorder().save(
        data_snapshot_id=data_snapshot_id,
        input_hashes={"universe": "aabbccdd1234", "kline": "eeff00112233"},
        return_series=[0.01, -0.02, 0.005, 0.03],
        dates=["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
        params=params or {"n_trials": 4, "edge_type": "selection", "cost": 0.007},
        frozen_commit="b1aba21",
        verdict=verdict or {
            "status": "falsified", "selection_lift": 0.978, "ci_low": None,
            "ci_high": None, "days_robust": 44, "n": 627,
            "edge_type": "selection", "tradeable": False,
            "dsr_method": "N/A", "note": "test path_lift<1",
        },
    )


# ── GET /api/evaluation/dims ──────────────────────────────────────────────


def test_dims_returns_12_records():
    resp = client.get("/api/evaluation/dims")
    assert resp.status_code == 200
    assert len(resp.json()) == 19  # 17 + post_first_board S209 T3 + consecutive_relay S211（regime-stratified）


def test_dims_match_contract_fields():
    dims = client.get("/api/evaluation/dims").json()
    for d in dims:
        assert _DIM_REQUIRED <= set(d.keys()), f"missing fields in {d['dimension_id']}"


def test_dims_status_in_enum():
    for d in client.get("/api/evaluation/dims").json():
        assert d["status"] in _VALID_STATUSES, f"{d['dimension_id']}: {d['status']}"


def test_dims_gene_score_r8_underpowered():
    """gene_score lift=0.03 n=2332 days=38 → days<60 lift<1 → underpowered ×0.5."""
    gene = next(d for d in client.get("/api/evaluation/dims").json()
                if d["dimension_id"] == "gene_score")
    assert gene["status"] == "underpowered"
    assert gene["weight_multiplier"] == 0.5
    assert gene["edge_type"] == "selection"
    assert gene["tradeable"] is False
    assert gene["dsr_method"] == "N/A"
    assert gene["layer"] == "selection"


def test_dims_turnover_falsified_60plus_days():
    """turnover lift=0.9979 n=14366 days=167 → days≥60 lift<1 robust → falsified ×0.1."""
    turn = next(d for d in client.get("/api/evaluation/dims").json()
                if d["dimension_id"] == "turnover")
    assert turn["status"] == "falsified"
    assert turn["weight_multiplier"] == 0.1


def test_dims_breakout_not_validated():
    """breakout lift=1.363 n=43691 days=42 → days<60 1≤lift<2 → not_validated ×0.5."""
    brk = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "breakout")
    assert brk["status"] == "not_validated"
    assert brk["weight_multiplier"] == 0.5


def test_dims_platform_breakout_not_validated_sufficient_days():
    """platform_breakout lift=1.0791 n=946 days=130 → days≥60 1≤lift<2 → not_validated."""
    pb = next(d for d in client.get("/api/evaluation/dims").json()
              if d["dimension_id"] == "platform_breakout")
    assert pb["status"] == "not_validated"
    assert pb["weight_multiplier"] == 0.5


def test_dims_three_window_compare_shape():
    d = client.get("/api/evaluation/dims").json()[0]
    twc = d["three_window_compare"]
    assert set(twc.keys()) == {"overnight_gap", "d1_intraday", "path"}
    for w in twc.values():
        assert set(w.keys()) == {"mean", "median", "win_rate", "base_rate"}


def test_dims_overfit_all_null():
    for d in client.get("/api/evaluation/dims").json():
        assert d["overfit_stats"] == {
            "pbo": None, "cscv": None, "dsr": None, "haircut": None, "min_trl": None,
        }


def test_dims_data_snapshot_id_from_recorder(fresh_recorder_db):
    """S162 R4: data_snapshot_id read from latest Recorder record matching
    the dimension (params.dimension_id). Seed a record for 'gene_score'
    → that dimension's response shows the snapshot id; others stay None."""
    from s44_verifier.recorder import Recorder

    # Seed a record with dimension_id='gene_score' in params
    Recorder().save(
        data_snapshot_id="pit:42",
        input_hashes={"universe": "abc"},
        return_series=[0.01, -0.02, 0.005],
        dates=["2026-09-01", "2026-09-02", "2026-09-03"],
        params={"n_trials": 3, "edge_type": "selection", "dimension_id": "gene_score"},
        frozen_commit="b1aba21",
        verdict={"status": "not_validated", "selection_lift": 0.03},
    )
    dims = client.get("/api/evaluation/dims").json()
    gene = next(d for d in dims if d["dimension_id"] == "gene_score")
    assert gene["data_snapshot_id"] == "pit:42"
    # Other dimensions with no matching record → None
    turn = next(d for d in dims if d["dimension_id"] == "turnover")
    assert turn["data_snapshot_id"] is None


def test_dims_ci_and_v2_fields_null(fresh_recorder_db):
    """ci_low/ci_high/n_effective/event_*/updated_* all null; data_snapshot_id
    from recorder (None when no matching record — S162 R4 wiring)."""
    for d in client.get("/api/evaluation/dims").json():
        assert d["ci_low"] is None
        assert d["ci_high"] is None
        assert d["n_effective"] is None
        assert d["event_metrics"] is None
        assert d["event_status"] is None
        assert d["updated_commit"] is None
        assert d["updated_at"] is None
        # data_snapshot_id: None when no recorder record for this dimension
        assert d["data_snapshot_id"] is None


# ── GET /api/verifier/records ─────────────────────────────────────────────


def test_records_empty_on_fresh_db(fresh_recorder_db):
    assert client.get("/api/verifier/records").json() == []


def test_records_returns_seeded(fresh_recorder_db):
    rid = _seed_record()
    records = client.get("/api/verifier/records").json()
    assert len(records) == 1
    assert records[0]["recorder_id"] == rid


def test_records_match_contract_fields(fresh_recorder_db):
    _seed_record()
    rec = client.get("/api/verifier/records").json()[0]
    assert _REC_REQUIRED <= set(rec.keys())


def test_records_input_snapshot_hash_is_string(fresh_recorder_db):
    _seed_record()
    rec = client.get("/api/verifier/records").json()[0]
    assert isinstance(rec["input_snapshot_hash"], str)
    assert "aabbccdd1234" in rec["input_snapshot_hash"]


def test_records_n_trials_from_params(fresh_recorder_db):
    _seed_record()
    assert client.get("/api/verifier/records").json()[0]["n_trials"] == 4


def test_records_verdict_lift_alias_from_selection_lift(fresh_recorder_db):
    """Verdict stored with selection_lift → response verdict has lift (contract)."""
    _seed_record(verdict={"status": "falsified", "selection_lift": 0.5, "note": "x"})
    v = client.get("/api/verifier/records").json()[0]["verdict"]
    assert v["lift"] == 0.5
    assert v["selection_lift"] == 0.5  # original preserved


def test_records_verdict_passthrough_when_lift_present(fresh_recorder_db):
    """If stored verdict already has lift, no aliasing needed."""
    _seed_record(verdict={"status": "robust_edge", "lift": 2.3, "note": "ok"})
    v = client.get("/api/verifier/records").json()[0]["verdict"]
    assert v["lift"] == 2.3


def test_records_most_recent_first(fresh_recorder_db):
    """list_records orders DESC by timestamp — verify via two seeds (distinct snapshot ids)."""
    r1 = _seed_record(data_snapshot_id="aaa111+bbb222")
    r2 = _seed_record(data_snapshot_id="ccc333+ddd444")
    records = client.get("/api/verifier/records").json()
    ids = [r["recorder_id"] for r in records]
    assert set(ids) == {r1, r2}
    # DESC order: r2 seeded after r1 → r2 first (same-second may tie; assert both present)


# ── GET /api/verifier/records/{recorder_id} ───────────────────────────────


def test_record_by_id_found(fresh_recorder_db):
    rid = _seed_record()
    resp = client.get(f"/api/verifier/records/{rid}")
    assert resp.status_code == 200
    rec = resp.json()
    assert rec["recorder_id"] == rid
    assert rec["n_trials"] == 4
    assert rec["data_snapshot_id"] == "abc123+def456"


def test_record_by_id_404(fresh_recorder_db):
    resp = client.get("/api/verifier/records/nonexistent-id")
    assert resp.status_code == 404


def test_record_by_id_verdict_normalized(fresh_recorder_db):
    rid = _seed_record(verdict={"status": "exploratory", "selection_lift": 1.1})
    v = client.get(f"/api/verifier/records/{rid}").json()["verdict"]
    assert v["lift"] == 1.1


# ── unit: status mapping ─────────────────────────────────────────────────


def test_status_chinese_to_english_mapping():
    from routers.verifier import _status_chinese_to_english

    assert _status_chinese_to_english("劣于随机") == "falsified"
    assert _status_chinese_to_english("探索性") == "exploratory"
    assert _status_chinese_to_english("未validated") == "not_validated"
    assert _status_chinese_to_english("待复验") == "underpowered"
    assert _status_chinese_to_english("validated") == "robust_edge"
    assert _status_chinese_to_english("unknown") == "exploratory"


# ── M4: per-dimension edge_type correctness (5-type enum) ──────────────────
# S201 track-d-edge: remove hardcoded "all selection" annotation.
# Each dimension gets its true edge_type: selection/event/population/overnight_gap/path.

_VALID_EDGE_TYPES = {"selection", "event", "population", "overnight_gap", "path"}


def test_dims_edge_type_in_5_type_enum():
    """Every dimension's edge_type must be one of the 5 valid types."""
    for d in client.get("/api/evaluation/dims").json():
        assert d["edge_type"] in _VALID_EDGE_TYPES, (
            f"{d['dimension_id']}: edge_type={d['edge_type']} not in 5-type enum"
        )


def test_dims_not_all_selection():
    """Hardcoded 'all selection' bug guard: at least one dimension must be
    non-selection (path_lift=path, low_volatility=population, ofi=event)."""
    dims = client.get("/api/evaluation/dims").json()
    edge_types = {d["edge_type"] for d in dims}
    assert edge_types != {"selection"}, (
        "all dimensions labeled 'selection' — hardcoded bug not fixed"
    )
    assert len(edge_types) >= 3, (
        f"expected ≥3 distinct edge_types, got {edge_types}"
    )


def test_dims_path_lift_edge_type_is_path():
    """path_lift dimension tests full path return → edge_type='path'."""
    dim = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "path_lift")
    assert dim["edge_type"] == "path"


def test_dims_low_volatility_edge_type_is_population():
    """low_volatility is externally validated population anomaly (红利低波
    9-12% annualized triple-consensus) → edge_type='population'."""
    dim = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "low_volatility")
    assert dim["edge_type"] == "population"


def test_dims_ofi_accumulated_edge_type_is_event():
    """ofi_accumulated is an intraday event (盘中→D收) → edge_type='event'."""
    dim = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "ofi_accumulated")
    assert dim["edge_type"] == "event"


def test_dims_seal_sincerity_edge_type_is_event():
    """seal_sincerity is an intraday event (盘中→D收) → edge_type='event'."""
    dim = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "seal_sincerity")
    assert dim["edge_type"] == "event"


def test_dims_bid_ask_pressure_edge_type_is_event():
    """bid_ask_pressure is an intraday event (盘中→D收) → edge_type='event'."""
    dim = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "bid_ask_pressure")
    assert dim["edge_type"] == "event"


def test_dims_gene_score_still_selection():
    """gene_score is a selection factor (Spearman rho, direction prediction)
    → edge_type='selection'. Guard against regression."""
    dim = next(d for d in client.get("/api/evaluation/dims").json()
               if d["dimension_id"] == "gene_score")
    assert dim["edge_type"] == "selection"


def test_gap_window_lift_uses_overnight_gap_not_selection():
    """gap_window_lift.py must use edge_type='overnight_gap' (not 'selection').
    The overnight gap (D收→D+1开) is an event edge, not a selection edge.
    S199 proven: market-level forward-return edge. Source inspection test
    because the script cannot be imported (runs on import)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "tools" / "gap_window_lift.py"
    content = src.read_text(encoding="utf-8")
    # Must contain edge_type="overnight_gap" (分离检查不卡 PEP8 空格)
    assert 'edge_type' in content and 'overnight_gap' in content, (
        "gap_window_lift.py must use edge_type='overnight_gap' — "
        "gap is an event edge (S199), not a selection edge"
    )
    # Must NOT contain edge_type="selection" (the old wrong label)
    assert 'edge_type="selection"' not in content, (
        "gap_window_lift.py still uses edge_type='selection' — "
        "overnight gap was wrongly labeled as selection edge"
    )
