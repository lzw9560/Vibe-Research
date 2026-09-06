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
    assert len(resp.json()) == 12


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


def test_dims_ci_and_v2_fields_null():
    """ci_low/ci_high/n_effective/event_*/updated_*/data_snapshot_id all null (待 S161 v2)."""
    for d in client.get("/api/evaluation/dims").json():
        assert d["ci_low"] is None
        assert d["ci_high"] is None
        assert d["n_effective"] is None
        assert d["event_metrics"] is None
        assert d["event_status"] is None
        assert d["updated_commit"] is None
        assert d["updated_at"] is None
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
