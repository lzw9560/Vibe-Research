# -*- coding: utf-8 -*-
"""S168 共享接线 helper——12 harness 批量接 §44v2 verifier。

封装 wire_verdict() = verify() → _verdict_to_dict → Recorder.save → lineage.record。
从 s44_gap_run_60d.py:207 提取 _verdict_to_dict 去重（R9）。

fresh 心态（multiline design verdict）：基建是测谎仪不是打板机——12 harness
各调 wire_verdict 出正式 verdict（5 值 enum + edge_type），落 Recorder + lineage，
可复现。robust 才建 capture，falsified 就弃，不恋战。

R7: data_snapshot_id = frozen_commit[:8]:line_id:sha256(return_series)[:12]
（不依赖 pit_store——12 harness 数据已由 frozen_commit + 脚本内缓存锁定；
pit_store 留给需 pin live 数据的新线路如竞价量比等盘中线，YAGNI NOW）。
R8: 诚实标注——verify() R6 gate 内建（n<200 或 days_robust<60 → underpowered
不外推），接线方不 override。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from s44_verifier.verifier import Verdict, verify
from s44_verifier.recorder import Recorder
from data_quality.lineage import record as lineage_record


def _verdict_to_dict(v: Verdict) -> dict:
    """Verdict dataclass → JSON-safe dict (numpy scalars → native Python).

    ``dataclasses.asdict`` 递归转嵌套 dataclass（Verdict → EventMetrics）。
    numpy scalars (np.float64/np.int64) 经 ``.item()`` 转 native，使
    ``json.dumps`` 序列化为数字而非字符串。从 s44_gap_run_60d.py:207 提取（R9 去重）。
    """
    from dataclasses import asdict

    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(val) for k, val in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_clean(val) for val in obj]
        if hasattr(obj, "item") and callable(obj.item):
            try:
                return obj.item()
            except (ValueError, TypeError):
                return obj
        return obj

    return _clean(asdict(v))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wire_verdict(
    *,
    line_id: str,
    returns: list[float],
    edge_type: str,
    frozen_commit: str,
    dates: list[str] | None = None,
    survivors_by_day: dict | None = None,
    universe_by_day: dict | None = None,
    n_comparisons: int = 1,
    round_trip_cost: float = 0.0,
    script: str = "",
    params: dict | None = None,
) -> Verdict:
    """12 harness 共享接线——verify → Recorder → lineage → print 摘要。

    selection edge_type 须传 survivors_by_day + universe_by_day（测选股力）。
    event edge_type 传 returns + dates（测群体收益>0，不用 lift/permutation）。
    返 Verdict（调用方可读 status/note 决定建 capture 或弃）。
    """
    import numpy as np

    arr = np.asarray(returns, dtype=float)
    # ── data_snapshot_id (R7) ──
    rs_hash = _sha256(json.dumps(list(returns), default=str).encode("utf-8"))[:12]
    data_snapshot_id = f"{frozen_commit[:8]}:{line_id}:{rs_hash}"

    # ── verify (R8 诚实 gate 内建) ──
    v = verify(
        returns=arr,
        n_trials=n_comparisons,
        edge_type=edge_type,
        dates=dates,
        survivors_by_day=survivors_by_day,
        universe_by_day=universe_by_day,
        n_comparisons=n_comparisons,
        frozen_commit=frozen_commit,
        data_snapshot_id=data_snapshot_id,
        round_trip_cost=round_trip_cost,
    )
    verdict_dict = _verdict_to_dict(v)

    # ── input_hashes ──
    input_hashes = {
        "return_series": rs_hash,
        "dates": _sha256(json.dumps(dates or [], default=str).encode("utf-8"))[:12],
        "params": _sha256(
            json.dumps(params or {}, default=str, sort_keys=True).encode("utf-8")
        )[:12],
    }

    # ── Recorder.save (R4) ──
    recorder = Recorder()
    recorder_id = recorder.save(
        data_snapshot_id=data_snapshot_id,
        input_hashes=input_hashes,
        return_series=[float(x) for x in returns],
        dates=dates,
        params={"line_id": line_id, "edge_type": edge_type, **(params or {})},
        frozen_commit=frozen_commit,
        verdict=verdict_dict,
    )

    # ── lineage.record (R5, sidecar 不阻塞) ──
    try:
        lineage_record(
            artifact_id=f"verifier:{line_id}",
            script=script or line_id,
            as_of=_now_iso(),
            inputs={"params": params or {}, "n_returns": len(returns)},
            output=verdict_dict,
            commit=frozen_commit,
            note=f"S168 wire_verdict edge_type={edge_type}",
        )
    except Exception as e:
        print(f"[lineage] record failed (non-fatal, sidecar): {e}")

    # ── print 摘要 (R6, 与 s44_gap_run_60d 输出格式对齐) ──
    print(
        f"[verdict] {line_id} | status={v.status} edge_type={v.edge_type} "
        f"selection_lift={v.selection_lift} n={v.n} days_robust={v.days_robust} "
        f"recorder_id={recorder_id}"
    )
    if v.note:
        print(f"[verdict] note: {v.note}")

    return v
