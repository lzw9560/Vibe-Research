# -*- coding: utf-8 -*-
"""S052 D2/D4：回测快照缺口补跑。

- _compute_backfill_gap：查 backtest_daily_snapshots 最大日期 last_have，
  gene_scores 已有日中 (last_have, 昨天] 的缺失日列表（幂等，无快照记录时回溯上限 60 日）
- backfill_backtest_snapshots：串行逐日调 _execute_daily_backtest_run，单日失败不阻断
- 启动缺口补跑：lifespan 调 _startup_backfill_gap_check
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

logger = logging.getLogger("vibe-research")


def _get_snapshot_max_date() -> str | None:
    """查 backtest_daily_snapshots 最大 snapshot_date（任一 engine）。"""
    try:
        import sqlite3
        from scheduled_tasks import _DB_PATH
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT MAX(snapshot_date) as mx FROM backtest_daily_snapshots"
        ).fetchone()
        conn.close()
        return row["mx"] if row and row["mx"] else None
    except Exception:
        return None


def _get_gene_scores_dates_since(since: str | None, limit_days: int = 60) -> List[str]:
    """查 gene_scores 已有日（date > since 时取后续，否则取最近 limit_days 日）。降序。"""
    try:
        from limitup_screener.data import get_db
        conn = get_db()
        if since is not None:
            rows = conn.execute(
                "SELECT DISTINCT date FROM gene_scores WHERE date > ? "
                "ORDER BY date DESC LIMIT ?",
                (since, limit_days),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT date FROM gene_scores ORDER BY date DESC LIMIT ?",
                (limit_days,),
            ).fetchall()
        conn.close()
        return [r["date"] for r in rows]
    except Exception:
        return []


def _compute_backfill_gap(yesterday: str | None = None) -> List[str]:
    """S052 D2/D4：计算需回填的缺失日列表。

    - last_have = backtest_daily_snapshots 最大日期（无记录=None）
    - 候选日 = gene_scores 已有日中 > last_have 且 ≤ 昨天 的日期
    - last_have=None 时回溯上限 60 日（防首次启动全量打爆）
    - 幂等：已有快照日自动排除（last_have 之后才有候选）
    """
    last_have = _get_snapshot_max_date()
    yest = yesterday or (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 候选日（last_have 之后 or 最近 60 日 if last_have=None）
    candidates = _get_gene_scores_dates_since(last_have, limit_days=60)
    # 只保留 <= 昨天（今天可能未收盘，不补）
    gap = [d for d in candidates if d <= yest]
    # 升序（早的先补）
    gap.sort()
    return gap


def _get_existing_snapshot_dates() -> set[str]:
    """查 backtest_daily_snapshots 已有的 snapshot_date 集合（任一 engine）。"""
    try:
        import sqlite3
        from scheduled_tasks import _DB_PATH
        conn = sqlite3.connect(_DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT snapshot_date FROM backtest_daily_snapshots"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _compute_historical_gap(days: int = 60) -> List[str]:
    """S052 D1：一次性回填缺口——回溯历史 N 个交易日。

    目标日 = gene_scores 已有日 ∩ 最近 days 个交易日 − 已有快照日（幂等）。
    与 _compute_backfill_gap（启动增量补跑，只看 last_have 之后）不同：
    本函数回溯历史，补 last_have 之前的缺口。
    返回升序列表（早的先补）。
    """
    target_dates = _get_gene_scores_dates_since(None, limit_days=days)
    existing = _get_existing_snapshot_dates()
    gap = [d for d in target_dates if d not in existing]
    gap.sort()
    return gap


def backfill_backtest_snapshots(days: int = 60) -> Dict[str, Any]:
    """S052 D2：一次性回填入口——逐日调 _execute_daily_backtest_run。

    目标日 = gene_scores 已有日 ∩ 最近 days 个交易日 − 已有快照日（幂等）。
    单日失败记 warning 不阻断整批；串行后台跑。
    回溯历史 N 日（与启动增量补跑 _compute_backfill_gap 互补）。
    """
    import scheduled_tasks as st

    gap = _compute_historical_gap(days)
    if not gap:
        return {"backfilled": 0, "days": [], "msg": "无缺口，快照已齐"}

    executor = st.TaskExecutor()
    results: List[Dict[str, Any]] = []
    success = 0
    failed = 0
    for d in gap:
        try:
            r = executor._execute_daily_backtest_run({"lookback_days": 30, "as_of_date": d})
            r["_status"] = "ok"
            success += 1
        except Exception as exc:  # noqa: BLE001 — 单日失败不阻断
            r = {"snapshot_date": d, "_status": "error", "error": str(exc)}
            failed += 1
            logger.warning("[backfill] %s 回填失败: %s", d, exc)
        results.append(r)
    return {
        "backfilled": success,
        "failed": failed,
        "days": results,
        "msg": f"回填 {success} 日成功，{failed} 日失败" if failed else f"回填 {success} 日成功",
    }


async def startup_backfill_gap_check() -> None:
    """S052 D4：后端启动时查缺口，后台排队回填。

    查 backtest_daily_snapshots 最大日期 last_have；gene_scores 已有日中
    (last_have, 昨天] 的缺失日排队回填；无快照记录时回溯上限 60 日。
    """
    try:
        gap = _compute_backfill_gap()
        if not gap:
            logger.info("[startup_backfill] 无回测快照缺口")
            return
        logger.info("[startup_backfill] 检测到 %d 日缺口，后台排队回填: %s", len(gap), gap)
        # 后台线程跑（不阻塞 lifespan）
        import threading
        t = threading.Thread(target=backfill_backtest_snapshots, args=(60,), daemon=True)
        t.start()
    except Exception as exc:  # noqa: BLE001 — 启动补跑失败不影响主服务
        logger.warning("[startup_backfill] 启动缺口补跑失败: %s", exc)
