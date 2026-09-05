# -*- coding: utf-8 -*-
"""S150 T0.7 根治：seal_intraday_collect 全逻辑 subprocess CLI。

子进程可 SIGKILL——asyncio 线程（run_in_executor/to_thread）不可中断，R1 wait_for
超时后底层线程继续跑：孤儿线程并发 em_get（rate limiter TOCTOU→跳限流→IP 封禁，HIGH1）+
写库（INSERT OR REPLACE 覆盖 seal_derived/intraday_features 陈旧派生 / bomb_alert_history
重复行 / 若线程持 _DB_LOCK 瞬间超时→锁泄漏死线程永久持有→后续 collect_once 永久阻塞
acquire()，HIGH3）。subprocess.run(timeout=110) 超时 SIGKILL 子进程，OS 回收 DB 连接+lock，
根治孤儿线程+死锁。executor 调本 CLI，parse stdout JSON。

环境：subprocess 继承 env（VR_DATA_DIR/.vibe-research），cwd=backend/（risk 包可 import）。
"""
from __future__ import annotations

import json
import sys


def run_collect(payload: dict) -> dict:
    """全逻辑：prune + collect_once + rules + trajectory/derived。

    从 scheduled_tasks._execute_seal_intraday_collect 原地搬移——逻辑不变，仅换执行容器
    （线程→子进程，可 SIGKILL）。失败 catch 不抛，标 degraded（采集是增强，不阻塞主流程）。
    """
    from datetime import datetime

    from risk.seal_intraday_collector import (
        archive_old_partitions, collect_once, get_latest_snapshots, get_snapshots_by_code,
        _get_conn, _DB_LOCK,
    )
    from risk.bomb_alert_rules import check_all_rules
    from risk.bomb_alert_dispatcher import process_alerts

    # S089 C4：每日首调归档（payload 带 prune=True 触发，不删数据只标冷热）
    if payload.get("prune"):
        retention = int(payload.get("retention_days", 30))
        archive_result = archive_old_partitions(retention)
        pruned = archive_result.get("archived", 0)
    else:
        pruned = 0

    result = collect_once()
    result["pruned"] = pruned  # 向后兼容（archive 后恒 0，未删行）
    # 补写 date（collect_once 内部用 datetime.now()，CLI 回填便于追溯）
    _now = datetime.now()
    if "date" not in result:
        result["date"] = _now.strftime("%Y-%m-%d")

    # 采集成功后跑规则引擎（仅对本次采集的票）+ S070 R3 派生
    if result.get("written", 0) > 0:
        now = datetime.now()
        date_str = result.get("date") or now.strftime("%Y-%m-%d")
        latest_snaps = get_latest_snapshots(date_str)
        triggered_total = 0
        for snap in latest_snaps:
            code = snap.get("code")
            name = snap.get("name") or code
            if not code:
                continue
            snaps = get_snapshots_by_code(code, date_str)
            results = check_all_rules(snaps, code, name, now=now)
            active = process_alerts(code, name, results, now=now)
            triggered_total += len(active)
        result["alerts_triggered"] = triggered_total

        # S070 R3：R1 trajectory + R7 派生落库（失败不阻塞主采集，标 degraded）
        traj_written = 0
        derived_written = 0
        try:
            from strategies.intraday_features import (
                compute_derived_features, compute_trajectory,
                persist_derived_features, persist_trajectory,
            )
            conn = _get_conn()
            try:
                with _DB_LOCK:
                    for snap in latest_snaps:
                        code = snap.get("code")
                        name = snap.get("name") or code
                        if not code:
                            continue
                        snaps = get_snapshots_by_code(code, date_str)
                        if not snaps:
                            continue  # 缺快照跳过派生，不臆造
                        traj = compute_trajectory(snaps)
                        persist_trajectory(date_str, code, name, traj, conn)
                        traj_written += 1
                        derived = compute_derived_features(snaps)
                        persist_derived_features(date_str, code, name, derived, conn)
                        derived_written += 1
                    conn.commit()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 — 派生失败不阻塞主采集
            result["derived_status"] = "degraded"
            result["derived_error"] = str(exc)
        else:
            result["derived_status"] = "ok"
        result["trajectory_written"] = traj_written
        result["derived_written"] = derived_written

    return result


def main() -> None:
    """读 stdin JSON payload → run_collect → stdout JSON。失败→JSON error + exit 1。"""
    payload: dict = {}
    if sys.stdin and not sys.stdin.isatty():
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            payload = {}
    try:
        result = run_collect(payload)
        print(json.dumps(result, ensure_ascii=False, default=str))
    except Exception as exc:  # noqa: BLE001 — 采集失败不抛，返 JSON error
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, default=str))
        sys.exit(1)


if __name__ == "__main__":
    main()
