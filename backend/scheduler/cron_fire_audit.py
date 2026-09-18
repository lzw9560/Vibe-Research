# -*- coding: utf-8 -*-
"""S218 #10 cron-fire audit——fire receipt 日志 + 跨日 audit 数 missed cron。

可观测性补丁（deep-review 2026-09-18 w1d19k2hl #10，reality-check verdict NEEDS WORK）：
delivery cron（daily_report / keypoint_notify entry+exit / weekly_review / fund_accumulation）
commit-state 显示 wired 但实测 scheduled_tasks.last_run_at=null 从未 fire。本模块把
"wired" 变 "observable wired"——每次 fire 写一行 jsonl receipt，audit cron 跨日数
哪些 task 该 fire 没 fire（last_run_at 旧或 null 且今日无 receipt）。

工程底线（CLAUDE.md §1.2）：
- 不臆造数据：receipt 只记真实 fire 产物（status/output_path/n_rows 从 result 提取）；
  audit 读真实 last_run_at + 真实 receipt，不猜不补。
- 私有数据隔离：cron_fire.log 落 .vibe-research/（VR_DATA_DIR，gitignored，绝不进 git）。
- 零网络：本模块只读写本地 jsonl，不调 requests。

receipt jsonl schema（稳定契约，executors/audit.py 解析依赖）：
    {"ts": iso-Beijing, "task_name": str, "status": str|None,
     "output_path": str|None, "n_rows": int|None, "duration_ms": float|None}
"""
from __future__ import annotations

import functools
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from vr_paths import BEIJING_TZ, resolve_data_dir

logger = logging.getLogger("vibe-research")

#: 默认 audit 的 delivery cron task_type（spec 要求可观测的 4 类；keypoint_notify
#: entry/exit 两条 cron 共 task_type，audit 按 task_type 聚合判 "今日有无 fire"）。
DEFAULT_AUDITED_TASK_TYPES: tuple[str, ...] = (
    "daily_report",
    "keypoint_notify",
    "weekly_review",
    "fund_accumulation",
)


def _fire_log_path() -> Path:
    """cron_fire.log 路径——.vibe-research/cron_fire.log（VR_DATA_DIR，gitignored）。

    每次调用读 resolve_data_dir()（读 VR_DATA_DIR env），支持测试 monkeypatch / setenv
    隔离到 tmp_path（防跨测试 receipt 污染）。
    """
    return resolve_data_dir() / "cron_fire.log"


def _extract_output_path(result: Any) -> str | None:
    """从 result dict 提取产出路径（容忍异构 key：output_path/report_path/record_path/path）。

    daily_report→report_path，keypoint_notify/weekly_review→record_path，
    fund_accumulation 无文件产出（写 DB）→ None。None 不视作 missed（仅无文件产出）。
    """
    if not isinstance(result, dict):
        return None
    for key in ("output_path", "report_path", "record_path", "path"):
        val = result.get(key)
        if val:
            return str(val)
    return None


def _extract_n_rows(result: Any) -> int | None:
    """从 result dict 提取产出行数（容忍异构 key：n_rows/signals/notifications_sent/n_updated/count/total）。

    daily_report→signals，keypoint_notify→notifications_sent，fund_accumulation→n_updated，
    weekly_review 无 count field → None。
    """
    if not isinstance(result, dict):
        return None
    for key in ("n_rows", "signals", "notifications_sent", "n_updated", "count", "total"):
        val = result.get(key)
        # bool 是 int 子类（True==1），排除避免误把布尔当行数
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return int(val)
    return None


def log_fire_receipt(
    task_name: str,
    payload: dict[str, Any] | None,
    result: dict[str, Any] | None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    """写一行 fire receipt 到 .vibe-research/cron_fire.log（jsonl append）。

    cron fire 后调（@fire_receipt 装饰器或 dispatch wrapper）。绝不抛异常——receipt 是
    观测副产物，写盘失败只 log.warning，不阻断 executor 返回值（caller 仍拿原 result）。

    Args:
        task_name: cron task_type 名（如 "daily_report"）——audit 按 task_name 聚合。
        payload: cron payload（仅做 context，不 dump 全量防泄 API key 等敏感字段）。
        result: executor 返回 dict——提取 status/output_path/n_rows。
        duration_ms: 可选执行耗时（ms）；spec signature 3-arg 调用时传 None（未测），
            @fire_receipt 装饰器测 perf_counter 后传入。

    Returns:
        写入的 receipt dict（便于 caller/测试断言）。
    """
    receipt = {
        "ts": datetime.now(BEIJING_TZ).isoformat(),
        "task_name": str(task_name) if task_name is not None else "",
        "status": result.get("status") if isinstance(result, dict) else None,
        "output_path": _extract_output_path(result),
        "n_rows": _extract_n_rows(result),
        "duration_ms": (
            round(duration_ms, 2)
            if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool)
            else None
        ),
    }
    try:
        path = _fire_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(receipt, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        # receipt 是观测副产物，写盘失败不阻断 executor（caller 仍拿原 result）
        logger.warning("[cron_fire_audit] receipt 写盘失败 task=%s: %s", task_name, e)
    return receipt


def fire_receipt(task_name: str) -> Callable[[Callable], Callable]:
    """装饰器：cron executor fire 后写 receipt（测 duration_ms，不侵入函数体）。

    用于 daily_report / keypoint_notify / weekly_review / fund_accumulation 4 executor——
    ``@fire_receipt("daily_report")`` 加在 def 上一行（1 行/executor），不改函数体/return，
    避免与 #2/#11 并发 commit 改动碰撞（只动 def 上一行，不碰 body/return 块）。

    - executor 正常返回（含 status=error/degraded dict）→ 写 receipt + 透传 result。
    - executor raise → 不写 receipt（caller __init__ wrapper 落 failed run，last_run_at
      仍设→audit 走 last_run_at 判 fired，不误判 missed）。
    - receipt 写盘失败（log_fire_receipt 内部 try/except）→ 不影响 executor 返回值。
    """
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(payload: dict[str, Any]) -> dict[str, Any]:
            t0 = time.perf_counter()
            result = fn(payload)
            log_fire_receipt(
                task_name, payload, result,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return result
        return wrapper
    return deco


def _read_receipts(log_path: Path | None = None) -> list[dict[str, Any]]:
    """读 cron_fire.log 全量 receipt（损坏行跳过，不抛）。

    Args:
        log_path: 测试注入路径；默认 _fire_log_path()。
    """
    path = log_path or _fire_log_path()
    if not path.exists():
        return []
    receipts: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    receipts.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 损坏行跳过（部分写/并发交错）
    except OSError as e:
        logger.warning("[cron_fire_audit] 读 receipt 日志失败: %s", e)
    return receipts


def _fired_task_types_today(
    receipts: Iterable[dict[str, Any]],
    today: str | None = None,
) -> set[str]:
    """从 receipts 取今日有 fire 记录的 task_type 集合（北京时间今日）。

    receipt.ts 是 Beijing tz-aware ISO；转 Beijing 取 date。同 task_type 今日多条 receipt
    （如 keypoint_notify entry+exit）算 1 个 fired task_type。
    """
    today = today or datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    fired: set[str] = set()
    for r in receipts:
        name = r.get("task_name")
        ts = r.get("ts")
        if not name or not ts:
            continue
        try:
            d = datetime.fromisoformat(str(ts)).astimezone(BEIJING_TZ).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if d == today:
            fired.add(str(name))
    return fired
