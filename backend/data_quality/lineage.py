# -*- coding: utf-8 -*-
"""S163 R2：轻量血缘 —— provenance trail + 可复现脚手架。

每次 artifact 产出记录（spec R2）：
  script + commit hash + as_of / data-snapshot-id + inputs_hash + output_hash + timestamp。
落 ``.vibe-research/lineage/lineage.jsonl``，**write-once / append-only**（不覆盖不删）。

定位（spec §1 合规自查 + §0）：
- **lineage = provenance trail**（脚本→artifact 可追溯）+ **可复现脚手架**
  （artifact 存在性检查捕 lazy-agent missing-artifact + as_of 支撑 recompute-verify）。
- **对抗 sophisticated agent 臆造仍靠人 / verifier 读原始输出，不外推**：
  hash 是指纹（标识数据内容），非可复算状态；as_of / data-snapshot-id 指向 frozen 输入 bundle
  （复算需原始输入非仅指纹）。lineage 不声称"已验证复算"——除非显式跑过 recompute_verify。

as_of ≠ content hash（spec R2 显式）：
  - ``inputs_hash`` / ``output_hash`` = sha256(规范 JSON)，是指纹（标识"这份数据是什么"）。
  - ``as_of`` / data-snapshot-id = 指向可重算的 frozen 输入 bundle（PIT 标识："何时 / 哪份快照"）。
  复算 = 在 frozen_commit 上 pin as_of 输入 → 重算 output → hash 匹配（recompute_verify）。

工程底线（§1.2）：
- **私有数据隔离**：lineage 写 ``resolve_data_dir()/"lineage"``（VR_DATA_DIR，gitignored，不进 git）。
- **不臆造**：commit hash 实算（git rev-parse），hash 实算（sha256），不伪造。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from vr_paths import resolve_data_dir

logger = logging.getLogger("vibe-research")


class LineageError(RuntimeError):
    """血缘记录违规（write-once 违反 / 存储损坏 / 复算失败）。"""


@dataclass(frozen=True)
class LineageRecord:
    """单次 artifact 产出的血缘记录（不可变，append-only 落盘）。

    字段（spec R2）：
      - artifact_id：逻辑名（e.g. "baostock_kline_cache"），同一 artifact 多次产出多行记录。
      - script：产出脚本相对路径（e.g. "tools/overnight_gap_decomposition.py"），可追溯。
      - commit：产出时 git commit hash（git rev-parse HEAD，不在 git 仓库则 "unknown"）。
      - as_of：PIT 日期 / data-snapshot-id（指向 frozen 输入 bundle，复算锚点）。
      - inputs_hash：输入 bundle 的 sha256 指纹（标识"用了什么输入"，非复算状态）。
      - output_hash：输出 artifact 的 sha256 指纹。
      - produced_at：ISO8601 产出时刻（UTC，带时区）。
      - recompute_verified：是否跑过 recompute_verify（hash 匹配），默认 False（诚实）。
      - note：可选备注。
    """

    artifact_id: str
    script: str
    commit: str
    as_of: str
    inputs_hash: str
    output_hash: str
    produced_at: str
    recompute_verified: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# 哈希指纹（sha256 规范 JSON —— 指纹非复算状态，spec R2）
# ---------------------------------------------------------------------------

def compute_hash(data: Any) -> str:
    """sha256(规范 JSON) —— 数据内容指纹（sort_keys 确保顺序无关）。

    指纹用途：标识"这份数据是什么"（去重 / 比对），**非**可复算状态。
    非可复算：同内容不同对象哈希相同（指纹特性），但复算需原始输入非仅指纹。
    """
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_commit() -> str:
    """当前 git commit hash（git rev-parse HEAD）。

    不在 git 仓库 / git 不可用 → "unknown"（不臆造 hash，诚实标注）。
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(Path(__file__).resolve().parents[1]),  # repo root
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# 存储路径 + 读写
# ---------------------------------------------------------------------------

def _store_path() -> Path:
    """血缘存储路径：resolve_data_dir()/"lineage"/lineage.jsonl。

    用 resolve_data_dir()（VR_DATA_DIR，含 .vibe-research，测试 conftest 隔离到 tmp）。
    私有数据隔离（§1.2）：不进 git（.vibe-research gitignored）。
    """
    return resolve_data_dir() / "lineage" / "lineage.jsonl"


def _now_iso() -> str:
    """UTC ISO8601 时刻（带时区，可排序可追溯）。"""
    return datetime.now(timezone.utc).isoformat()


def _serialize(rec: LineageRecord) -> str:
    """记录 → 一行 JSON（append-only，每行独立可解析）。"""
    return json.dumps(asdict(rec), ensure_ascii=False, sort_keys=True)


def _deserialize(line: str) -> LineageRecord | None:
    """一行 JSON → 记录。损坏行返 None（不崩，记 warning，§1.2 不静默吞 → log 显式）。"""
    line = line.strip()
    if not line:
        return None
    try:
        d = json.loads(line)
        return LineageRecord(**d)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[lineage] 损坏行跳过：%s | line=%r", e, line[:120])
        return None


def _read_all() -> list[LineageRecord]:
    """读全部记录（provenance trail）。文件不存在 → []（首次产出）。"""
    path = _store_path()
    if not path.exists():
        return []
    recs: list[LineageRecord] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = _deserialize(line)
            if rec is not None:
                recs.append(rec)
    return recs


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def record(
    *,
    artifact_id: str,
    script: str,
    as_of: str,
    inputs: Any,
    output: Any,
    commit: str | None = None,
    note: str = "",
) -> LineageRecord:
    """记录一次 artifact 产出（append-only，write-once 守卫）。

    实算 inputs_hash / output_hash（compute_hash）+ commit（current_commit，None 则实算）。
    **write-once 守卫**：同 (artifact_id, as_of, commit, output_hash) 已存在 → raise
    （防静默重复写同一记录；不同 commit/output 的重跑 = 新记录，合法）。
    返回写入的 :class:`LineageRecord`（recompute_verified=False，诚实未验证）。
    """
    commit_hash = commit if commit is not None else current_commit()
    rec = LineageRecord(
        artifact_id=artifact_id,
        script=script,
        commit=commit_hash,
        as_of=as_of,
        inputs_hash=compute_hash(inputs),
        output_hash=compute_hash(output),
        produced_at=_now_iso(),
        recompute_verified=False,
        note=note,
    )
    # write-once 守卫：完全相同的记录已存在 → 拒绝静默重复
    existing = _read_all()
    for ex in existing:
        if (ex.artifact_id == rec.artifact_id and ex.as_of == rec.as_of
                and ex.commit == rec.commit and ex.output_hash == rec.output_hash):
            raise LineageError(
                f"write-once 违反：记录已存在 artifact={artifact_id} as_of={as_of} "
                f"commit={commit_hash} output_hash={rec.output_hash[:8]}…"
            )
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 'a' 模式 = append-only（不覆盖不删，spec R2）
    with path.open("a", encoding="utf-8") as f:
        f.write(_serialize(rec) + "\n")
    return rec


def list_records(artifact_id: str | None = None) -> list[LineageRecord]:
    """provenance trail —— 全部记录，可按 artifact_id 过滤（时间序 = append 序）。"""
    recs = _read_all()
    if artifact_id is None:
        return recs
    return [r for r in recs if r.artifact_id == artifact_id]


def latest_record(artifact_id: str) -> LineageRecord | None:
    """某 artifact 最近一条记录（append 序末项）。无 → None。"""
    recs = list_records(artifact_id)
    return recs[-1] if recs else None


def artifact_exists(artifact_id: str, as_of: str | None = None) -> bool:
    """artifact 是否已记录（存在性检查 —— 捕 lazy-agent missing-artifact）。

    agent 声称"已产出 X"但无 lineage 记录 → False → 暴露臆造（spec §0）。
    as_of 给定时进一步核 (artifact_id, as_of) 是否匹配。
    """
    recs = list_records(artifact_id)
    if not recs:
        return False
    if as_of is None:
        return True
    return any(r.as_of == as_of for r in recs)


def recompute_verify(
    artifact_id: str,
    as_of: str,
    recompute_fn: Callable[[str], Any],
) -> tuple[bool, LineageRecord | None, str]:
    """复算验证（spec R2 acceptance）：frozen_commit 上 pin as_of 输入 → 重算 output → hash 匹配。

    定位（spec §1）：
    - 这是**可复现脚手架**的验证步骤——lineage 记录指纹 + as_of 锚点，复算逻辑由调用方提供
      （recompute_fn：输入 as_of → 产出 output；§44 脚本 / 测试知晓如何从 frozen 输入重算）。
    - 不声称"已验证复算"除非此函数返 True。匹配 → 标 recompute_verified=True 落新记录（审计迹）。
    - 对抗 sophisticated 臆造仍靠人 / verifier 读原始输出，不外推（spec §1 合规自查）。

    返回 (ok, record, message)：
      - record 缺失 → (False, None, "无记录")；
      - 重算 output hash != 记录 output_hash → (False, record, "hash 不匹配")；
      - 匹配 → (True, record, "复算一致")。
    """
    recs = [r for r in list_records(artifact_id) if r.as_of == as_of]
    if not recs:
        return False, None, f"无记录 artifact={artifact_id} as_of={as_of}"
    rec = recs[-1]
    try:
        recomputed = recompute_fn(as_of)
    except Exception as e:  # 复算失败不崩，诚实标失败（§1.2 不静默吞 → 返 message）
        return False, rec, f"复算失败：{e}"
    recomputed_hash = compute_hash(recomputed)
    if recomputed_hash != rec.output_hash:
        return False, rec, (
            f"hash 不匹配：记录 {rec.output_hash[:8]}… vs 复算 {recomputed_hash[:8]}…"
        )
    # 匹配 → 追加一条 recompute_verified=True 审计记录（append-only，不覆盖原记录）
    verified = LineageRecord(
        artifact_id=artifact_id, script=rec.script, commit=rec.commit,
        as_of=rec.as_of, inputs_hash=rec.inputs_hash, output_hash=rec.output_hash,
        produced_at=_now_iso(), recompute_verified=True,
        note=f"recompute_verify 一致 @ {rec.commit}",
    )
    path = _store_path()
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(_serialize(verified) + "\n")
    except OSError as e:
        logger.warning("[lineage] 审计记录写盘失败（不阻断复算结论）：%s", e)
    return True, rec, "复算一致"
