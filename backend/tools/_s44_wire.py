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
    # S171 R3: 月度参数透传（None=不传→verify 用自身日频默认，保 14 旧 harness
    # 向后兼容；月度 harness 传 walk_train=36/walk_test=12/step=12，否则月度
    # walk_forward OOS 失效——默认 step=20 日步长对月度 60 月仅 0 窗口）
    window_sanity: dict | None = None,
    walk_train: int | None = None,
    walk_test: int | None = None,
    step: int | None = None,
    # S171 T1: event_materiality_floor 第 5 月度参数（bug 6 reproduce-storage：
    # verifier.py:370-374 effective_floor=max(event_materiality_floor, cost*0.5)
    # 是唯一直接影响 status 的参数，不存→reproduce 用默认 0.003 非 harness 值→status 翻）
    event_materiality_floor: float | None = None,
    script: str = "",
    params: dict | None = None,
    input_files: dict[str, str] | None = None,
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
    # S171 R3: 条件透传月度参数（None 不传→verify 用自身默认，非 None-override
    # ——否则 verify 的 int 默认被 None 覆盖致 walk_forward_oos(surv,univ,None,None) 崩）
    verify_kwargs = dict(
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
    if window_sanity is not None:
        verify_kwargs["window_sanity"] = window_sanity
    if walk_train is not None:
        verify_kwargs["walk_train"] = walk_train
    if walk_test is not None:
        verify_kwargs["walk_test"] = walk_test
    if step is not None:
        verify_kwargs["step"] = step
    if event_materiality_floor is not None:
        verify_kwargs["event_materiality_floor"] = event_materiality_floor
    v = verify(**verify_kwargs)
    verdict_dict = _verdict_to_dict(v)

    # ── input_hashes ──
    input_hashes = {
        "return_series": rs_hash,
        "dates": _sha256(json.dumps(dates or [], default=str).encode("utf-8"))[:12],
        "params": _sha256(
            json.dumps(params or {}, default=str, sort_keys=True).encode("utf-8")
        )[:12],
    }
    # S169 grill #5: pin input data files (forecast_reports/kline_cache) so
    # data-revalidation can detect 前复权 mutation. Caller passes {path: name}.
    if input_files:
        import os
        for path, name in input_files.items():
            try:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        input_hashes[name] = _sha256(f.read())[:12]
            except Exception:
                pass

    # ── Recorder.save (R4) ──
    # params 存 round_trip_cost + n_comparisons（reproduce_verdict 重算 verify 要，
    # 否则 reproduce 缺这些 verify 参数；line_id 是 metadata 被 reproduce whitelist 过滤）
    recorder = Recorder()
    recorder_id = recorder.save(
        data_snapshot_id=data_snapshot_id,
        input_hashes=input_hashes,
        return_series=[float(x) for x in returns],
        dates=dates,
        params={
            "line_id": line_id,
            "edge_type": edge_type,
            "n_trials": n_comparisons,
            "round_trip_cost": round_trip_cost,
            "n_comparisons": n_comparisons,
            **(params or {}),
            # S171 R3: 存月度方法论参数供 reproduce_verdict 重算（criterion a：
            # reproduce_verdict 用 inspect.signature(verify) 白名单重建 verify_kwargs，
            # 4 参数在 verify 签名内→存了才能 re-pass，否则 reproduce 用默认 step=20
            # ≠ 原录 step=12 verdict→walk_forward status mismatch）
            **({"window_sanity": window_sanity} if window_sanity is not None else {}),
            **({"walk_train": walk_train} if walk_train is not None else {}),
            **({"walk_test": walk_test} if walk_test is not None else {}),
            **({"step": step} if step is not None else {}),
            # S171 T1: event_materiality_floor 须存——verifier.py:370-374 唯一
            # 直接影响 status 的参数，不存→reproduce 用默认 0.003 非 harness 0.001
            # →effective_floor 翻→event_robust↔thin_positive 翻→A5 status 炸
            **({"event_materiality_floor": event_materiality_floor} if event_materiality_floor is not None else {}),
        },
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
