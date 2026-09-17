# -*- coding: utf-8 -*-
"""TaskExecutor——薄分发类。

26 个 `_execute_*` 方法保留为 bound method（测试 monkeypatch `TaskExecutor._execute_*`
类属性跨实例生效），body 委托到 8 域文件的模块级函数。dispatch dict 映射
task_type → `self._execute_xxx`（bound method），patch 类属性后新实例的 dispatch 自动拿 patched 版。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict

from scheduler.db import _manager, _task_timeout
from scheduler.models import ScheduledTask, TaskRun

logger = logging.getLogger("vibe-research")


# S177: executor 返回值 → run.status 映射（core-invariant「绝不静默吞掉错误」）
# degraded 信号不再被埋进 run.result JSON，status 列如实反映（backlog M1）
_DEGRADED_STATUSES = frozenset({
    "degraded", "partial", "source_fail", "no_emotion_data",
    "script_not_found", "baostock_unavailable",
})


def _resolve_run_status(result: Any) -> str:
    """executor 返回值 → run.status 映射。

    - dict 无 status 字段 / status 未匹配任何类 → success（backward-compat，不破坏 30+ executor）
    - error / error: * / timeout → failed（核心功能失败，executor 吞了异常返 dict）
    - degraded / partial / source_fail / no_emotion_data / script_not_found / baostock_unavailable → degraded
    - ok / due / skipped / not_due / nothing_to_settle / no_dir → success（正常完成或正常跳过，不误杀）
    """
    if not isinstance(result, dict):
        return "success"
    status = result.get("status")
    if status is None:
        return "success"
    if isinstance(status, str) and (status == "error" or status.startswith("error:") or status == "timeout"):
        return "failed"
    if isinstance(status, str) and status in _DEGRADED_STATUSES:
        return "degraded"
    return "success"


class TaskExecutor:
    """内置任务执行器。"""

    def __init__(self):
        self._executors = {
            "daily_data_refresh": self._execute_daily_data_refresh,
            "daily_review_notify": self._execute_daily_review_notify,
            "limitup_precompute": self._execute_limitup_precompute,
            "portfolio_refresh": self._execute_portfolio_refresh,
            "market_data_sync": self._execute_market_data_sync,
            "cleanup_old_runs": self._execute_cleanup_old_runs,
            "daily_backtest_run": self._execute_daily_backtest_run,
            "sti_post_market": self._execute_sti_post_market,
            "seal_intraday_collect": self._execute_seal_intraday_collect,
            "candidate_funnel_precompute": self._execute_candidate_funnel_precompute,
            "first_board_filter": self._execute_first_board_filter,
            "s066_validation_checkpoint": self._execute_s066_validation_checkpoint,
            "evaluation_backtest": self._execute_evaluation_backtest,
            "scan_watchlist_gaps": self._execute_scan_watchlist_gaps,
            "scan_price_alerts": self._execute_scan_price_alerts,
            "forward_test_daily": self._execute_forward_test_daily,
            "forward_test_t1_settle": self._execute_forward_test_t1_settle,
            "forward_test_backfill": self._execute_forward_test_backfill,  # S204 T3 — forward_test_records 回补 cron（≥60 天解 §44v2 R3 enforce 阻塞）
            "r3_enforce": self._execute_r3_enforce,  # S204 T8 — §44v2 verdict 定期 enforce 降级（days≥60 → lift_to_multiplier + write_override）
            "early_admission_scan": self._execute_early_admission_scan,  # S204 T10 — pre-涨停候选入池（manual trigger，auto-source deferred）
            "escalation_run": self._execute_escalation_run,  # S204 T11 — tracking→watching auto-promote（enabled=False 阈值未验证）
            "first_board_t1_review": self._execute_first_board_t1_review,
            "first_board_quote_probe": self._execute_first_board_quote_probe,
            "zt_history_snapshot": self._execute_zt_history_snapshot,
            "regime_cache_fetch": self._execute_regime_cache_fetch,  # S211 通电收尾——刷 regime cache 防 consecutive_relay regime=None
            "macro_fetch": self._execute_macro_fetch,  # S216 FRED 8 因子每日刷新 → macro_snapshot.json
            "derived_precompute": self._execute_derived_precompute,
            "monthly_vacuum": self._execute_monthly_vacuum,
            "kline_refresh": self._execute_kline_refresh,
            "daily_ai_summary": self._execute_daily_ai_summary,
            "premarket_auction_notify": self._execute_premarket_auction_notify,
            "premarket_open_notify": self._execute_premarket_open_notify,
            "premarket_t1_review": self._execute_premarket_t1_review,
            "daily_kg_audit": self._execute_daily_kg_audit,
            "daily_kg_sync": self._execute_daily_kg_sync,
            "st_play_radar": self._execute_st_play_radar,
            "intraday_microstructure_snapshot": self._execute_intraday_microstructure_snapshot,
            "intraday_auction_dense": self._execute_intraday_auction_dense,
            "baostock_5min_freeze": self._execute_baostock_5min_freeze,
            "trade_journal_daily": self._execute_trade_journal_daily,  # S175 R2 — 模拟盘闭环点火（BREAK-0 fix）
            "ofi_collect": self._execute_ofi_collect,  # S176 R5 — 盘中 OFI 五档收集（conditioning 数据收集器）
            "turso_sync": self._execute_turso_sync,  # S185 路径 A — Turso 云同步（VR_TURSO_URL 未设跳过）
            "healthcheck_ping": self._execute_healthcheck_ping,  # S188 RB-2 — 外部心跳防 cron 静默死（VR_HEALTHCHECKS_URL 未设跳过）
            "weekly_brainstorm_remind": self._execute_weekly_brainstorm_remind,  # S188 RB-9 — 每周头脑风暴提醒（飞书+待办）
            "daily_full_pull": self._execute_daily_full_pull,  # S191 RB-3 — 每日全量拉取沉淀 datalake
        }
        # S150 审查 HIGH1 根治：调度器独占 ThreadPoolExecutor，隔离 to_thread 泄漏——
        # 调度器线程全挂也不影响路由器的 asyncio.to_thread（71 调用方共享默认池）。
        self._thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scheduler")

    def execute(self, task: ScheduledTask) -> TaskRun:
        run = TaskRun(task_id=task.id or 0, status="running")
        run = _manager.add_run(run)
        started_at = run.started_at

        try:
            executor = self._executors.get(task.task_type)
            if executor is None:
                raise ValueError(f"未知任务类型: {task.task_type}")

            result = executor(task.payload)
            run.status = _resolve_run_status(result)
            run.result = result
            run.finished_at = datetime.now().isoformat()
            _manager.update_task_status(task.id or 0, run.status, started_at)

            # S177 通知：success→notify_on_success；degraded/failed→notify_on_failure（degraded 不再静默吞）
            if run.status == "success":
                if task.notify_on_success:
                    self._send_notification(task, run, "success")
            else:  # degraded 或 failed（来自 result dict，非异常）
                if task.notify_on_failure:
                    self._send_notification(task, run, run.status)

            return run
        except Exception as e:
            logger.exception("[scheduled_task] 任务执行失败: %s", e)
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now().isoformat()
            _manager.update_task_status(task.id or 0, "failed", started_at)

            # 失败通知
            if task.notify_on_failure:
                self._send_notification(task, run, "failed")

            return run
        finally:
            # R2：同一记录就地更新终态，不再二次 add_run（避免每次执行产生两条 run）
            _manager.update_run(run)

    async def execute_async(self, task: ScheduledTask) -> TaskRun:
        """协程版执行：落一条 run 记录（开头 add_run + 结尾 update_run）。

        - handler 为协程函数则直接 await，普通函数经 asyncio.to_thread 在线程执行
        - 未知任务类型 → 落一条 failed run，不抛异常
        - 成功/失败均 update_run + update_task_status + 通知，全程只一条 run 记录
        """
        run = TaskRun(task_id=task.id or 0, status="running")
        run = _manager.add_run(run)
        started_at = run.started_at

        handler = self._executors.get(task.task_type)
        if handler is None:
            run.status = "failed"
            run.error = f"未知任务类型: {task.task_type}"
            run.finished_at = datetime.now().isoformat()
            _manager.update_run(run)
            _manager.update_task_status(task.id or 0, "failed", started_at)
            if task.notify_on_failure:
                self._send_notification(task, run, "failed")
            return run

        try:
            if inspect.iscoroutinefunction(handler):  # py3.16: asyncio.iscoroutinefunction 已移除，用 inspect
                result = await asyncio.wait_for(handler(task.payload), timeout=_task_timeout(task))
            else:
                # S150 R1 + 审查 HIGH1 根治：同步 handler 走调度器独占 _thread_pool
                #（run_in_executor 替代 asyncio.to_thread），隔离泄漏——调度器线程全挂
                # 也不影响路由器默认池。wait_for 超时仍 cancel future（底层线程不可取消，
                # 但独占池爆炸半径限在调度器，不冻 API；HIGH3 重复写库另由 subprocess/async 根治）。
                result = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(self._thread_pool, handler, task.payload),
                    timeout=_task_timeout(task),
                )
            run.status = _resolve_run_status(result)
            run.result = result
            run.finished_at = datetime.now().isoformat()
            _manager.update_run(run)
            _manager.update_task_status(task.id or 0, run.status, started_at)

            # S177 通知：success→notify_on_success；degraded/failed→notify_on_failure（degraded 不再静默吞）
            if run.status == "success":
                if task.notify_on_success:
                    self._send_notification(task, run, "success")
            else:  # degraded 或 failed（来自 result dict，非异常）
                if task.notify_on_failure:
                    self._send_notification(task, run, run.status)

            return run
        except Exception as e:
            logger.exception("[scheduled_task] 任务执行失败: %s", e)
            run.status = "failed"
            # S150 R1：TimeoutError 标明确（str(asyncio.TimeoutError) 为空）
            if isinstance(e, asyncio.TimeoutError):
                run.error = f"timeout ({_task_timeout(task)}s, S150 R1)"
            else:
                run.error = str(e)
            run.finished_at = datetime.now().isoformat()
            _manager.update_run(run)
            _manager.update_task_status(task.id or 0, "failed", started_at)

            # 失败通知
            if task.notify_on_failure:
                self._send_notification(task, run, "failed")

            return run

    def _send_notification(self, task: ScheduledTask, run: TaskRun, status: str) -> None:
        """发送任务执行通知。"""
        try:
            from notification.notification_service import get_notification_service
            service = get_notification_service()

            status_text = {"success": "成功", "degraded": "降级", "failed": "失败"}.get(status, "未知")
            title = f"定时任务{status_text}: {task.name}"
            content = f"任务: {task.name}\n状态: {status_text}\n时间: {run.started_at}"
            if run.error:
                content += f"\n错误: {run.error}"

            # 使用通知服务发送（如果可用）
            if hasattr(service, "send"):
                try:
                    service.send(content)
                except Exception as e:  # L1 修复：不再静默吞异常
                    logger.warning("定时任务通知发送失败: %s", e)
        except Exception as e:  # L1 修复：不再静默吞异常
            logger.warning("定时任务通知构建失败: %s", e)

    # ── 26 个 thin wrapper（委托到域文件模块级函数）──────────────────────────
    # 保留 bound method 签名 (self, payload) 供测试 monkeypatch 类属性生效。

    def _execute_daily_data_refresh(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.data_ops import daily_data_refresh
        return daily_data_refresh(payload)

    def _execute_daily_review_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.ai_portfolio import daily_review_notify
        return daily_review_notify(payload)

    def _execute_limitup_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.limitup import limitup_precompute
        return limitup_precompute(payload)

    def _execute_portfolio_refresh(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.ai_portfolio import portfolio_refresh
        return portfolio_refresh(payload)

    def _execute_market_data_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.data_ops import market_data_sync
        return market_data_sync(payload)

    def _execute_cleanup_old_runs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.data_ops import cleanup_old_runs
        return cleanup_old_runs(payload)

    def _execute_daily_backtest_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.backtest import daily_backtest_run
        return daily_backtest_run(payload)

    def _execute_sti_post_market(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.limitup import sti_post_market
        return sti_post_market(payload)

    def _execute_seal_intraday_collect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.intraday import seal_intraday_collect
        return seal_intraday_collect(payload)

    def _execute_candidate_funnel_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.ai_portfolio import candidate_funnel_precompute
        return candidate_funnel_precompute(payload)

    def _execute_first_board_filter(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.first_board import first_board_filter
        return first_board_filter(payload)

    def _execute_s066_validation_checkpoint(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.backtest import s066_validation_checkpoint
        return s066_validation_checkpoint(payload)

    def _execute_evaluation_backtest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.backtest import evaluation_backtest
        return evaluation_backtest(payload)

    def _execute_scan_watchlist_gaps(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.gap_scan import scan_watchlist_gaps
        return scan_watchlist_gaps(payload)

    def _execute_scan_price_alerts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.price_monitor import scan_price_alerts
        return scan_price_alerts(payload)

    def _execute_forward_test_daily(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.backtest import forward_test_daily
        return forward_test_daily(payload)

    def _execute_forward_test_t1_settle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.backtest import forward_test_t1_settle
        return forward_test_t1_settle(payload)

    def _execute_forward_test_backfill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S204 T3: forward_test_records 回补（retroactive 重派 eastmoney_live 全信号日，幂等）。

        tools/forward_test_backfill.main() 删 forward_test_records 全量重派（幂等）；每日 cron 随
        eastmoney_live 增长重派，积累至 ≥60 天解 §44v2 R3 enforce 阻塞（days_robust<60 → ×0.5 cap）。
        use_weather=True 走 build_context 历史天气（完整架构）；早期日无 STI → weather=None 退化下界。
        """
        from tools.forward_test_backfill import main as backfill_main
        use_weather = bool(payload.get("use_weather", True))
        try:
            rc = backfill_main(use_weather=use_weather)
            return {"status": "ok" if rc == 0 else "error", "exit_code": rc, "use_weather": use_weather}
        except Exception as e:
            return {"status": "error", "error": repr(e)[:200], "use_weather": use_weather}

    def _execute_r3_enforce(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S204 T8: §44v2 R3 enforce——per-arm days_robust 跨 60 天阈 → lift_to_multiplier 升降级 + write_override。

        当前 forward_test ~20 天 → skip all underpowered（接线建好待 ≥60 天 bite，不造假 enforce）。
        非 arm 级 dimension（gene_score/turnover 等无 arm 映射）→ 保持 frozen 不重算。
        """
        from scheduler.executors.backtest import r3_enforce  # noqa: PLC0415
        return r3_enforce(payload)

    def _execute_early_admission_scan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S204 T10: early_admission 扫描入池（post-首板候选 → candidate_tracking_pool）。

        auto-source = S208 pre_limitup_scanner（scan_pre_limitup，查 zt_history T-1 lbc==1 首板 +
        sector_cycle 板块 zt count，**drop high_gene 死信号**）。替代 funnel 错源（funnel 是 post-涨停 lbc2-3 → 0 admits）。
        **专家 reframe**（panel w1iu01jnl）：high_gene >=80 死阈值（max 50.46）+ 证否 0.942x → DROP；
        relay_seed (lbc==1) post-首板（compound with sector activity）；真 edge 问题在 executor entry/exit 规则（并行设计）。
        manual override（payload.candidates）优先。pit guard T-1 only。zero em_get。
        """
        from early_admission import scan_early_admission
        import tracking_pool_repo as _repo
        from datetime import timedelta
        run_date = payload.get("run_date") or datetime.now().date().isoformat()
        # T-1（caller 传 or run_date - 1 day fallback）
        previous_trade_day = payload.get("previous_trade_day")
        if not previous_trade_day:
            try:
                previous_trade_day = (datetime.strptime(run_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            except ValueError:
                previous_trade_day = run_date
        # 候选源：manual payload.candidates 优先，否则 S208 pre_limitup_scanner（替代 funnel 错源）
        # funnel cache 是 post-涨停 lbc2-3 → 0 admits（错源）；scanner 查 zt_history T-1 lbc==1 首板（post-首板 pre-二板）。
        candidates = payload.get("candidates")
        if not candidates:
            from pre_limitup_scanner import scan_pre_limitup
            candidates = scan_pre_limitup(run_date, previous_trade_day=previous_trade_day)
        admitted = scan_early_admission(run_date, candidates, previous_trade_day=previous_trade_day)
        inserted = 0
        for a in admitted:
            if _repo.insert_tracking_record(a.code, a.admit_date, a.signal_type, a.indicators_t1):
                inserted += 1
            _repo.upsert_indicator_snapshot(a.code, a.admit_date, a.indicators_t1, snapshot_source="early_admit")
        return {"status": "ok", "candidates": len(candidates), "admitted": len(admitted),
                "inserted": inserted, "run_date": run_date, "previous_trade_day": previous_trade_day}

    def _execute_escalation_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S204 T11: escalation run（tracking→watching auto-promote + promoted→decayed）。

        **enabled=False（maturity 阈值未验证：min_age=3/gene+20%/sector_rank≤5 社区参数标 overfit）**——
        auto-escalate 会让 watching 列表噪声大。决策#11：只 candidate→watching 自动，watching 以上人工。
        T12 decay WATCHING→FILTERED reason='decayed'（非→CANDIDATE 防振荡）。manual trigger 验证阈值后改 enabled=True。
        """
        from escalation_engine import escalate
        run_date = payload.get("run_date") or datetime.now().date().isoformat()
        try:
            promoted = escalate(run_date)
            return {"status": "ok", "promoted": promoted, "promoted_count": len(promoted), "run_date": run_date}
        except Exception as e:
            return {"status": "error", "error": repr(e)[:200], "run_date": run_date}

    def _execute_first_board_t1_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.first_board import first_board_t1_review
        return first_board_t1_review(payload)

    def _execute_first_board_quote_probe(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.first_board import first_board_quote_probe
        return first_board_quote_probe(payload)

    def _execute_zt_history_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.limitup import zt_history_snapshot
        return zt_history_snapshot(payload)

    def _execute_regime_cache_fetch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.limitup import regime_cache_fetch
        return regime_cache_fetch(payload)

    def _execute_macro_fetch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.macro import macro_fetch
        return macro_fetch(payload)

    def _execute_derived_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.limitup import derived_precompute
        return derived_precompute(payload)

    def _execute_monthly_vacuum(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.data_ops import monthly_vacuum
        return monthly_vacuum(payload)

    def _execute_kline_refresh(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.data_ops import kline_refresh
        return kline_refresh(payload)

    def _execute_daily_ai_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.ai_portfolio import daily_ai_summary
        return daily_ai_summary(payload)

    def _execute_premarket_auction_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.premarket import premarket_auction_notify
        return premarket_auction_notify(payload)

    def _execute_premarket_open_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.premarket import premarket_open_notify
        return premarket_open_notify(payload)

    def _execute_premarket_t1_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.premarket import premarket_t1_review
        return premarket_t1_review(payload)

    def _execute_daily_kg_audit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.kg import daily_kg_audit
        return daily_kg_audit(payload)

    def _execute_daily_kg_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.kg import daily_kg_sync
        return daily_kg_sync(payload)

    def _execute_st_play_radar(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.limitup import st_play_radar
        return st_play_radar(payload)

    def _execute_intraday_microstructure_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.intraday import intraday_microstructure_snapshot
        return intraday_microstructure_snapshot(payload)

    def _execute_intraday_auction_dense(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.intraday import intraday_auction_dense
        return intraday_auction_dense(payload)

    def _execute_baostock_5min_freeze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from scheduler.executors.intraday import baostock_5min_freeze
        return baostock_5min_freeze(payload)

    def _execute_trade_journal_daily(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S175 R2 — 模拟盘闭环盘后跑（journal_recorder.run_daily 接 scheduler 点火）。"""
        from scheduler.executors.journal import trade_journal_daily
        return trade_journal_daily(payload)

    def _execute_ofi_collect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S176 R5 — 盘中 OFI 五档收集（tencent fetch_raw → collect_ofi → save_ofi）。"""
        from scheduler.executors.intraday import ofi_collect
        return ofi_collect(payload)

    def _execute_turso_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S185 路径 A — Turso 云同步（VR_TURSO_URL 未设→纯本地跳过，零侵入）。"""
        from data.turso_sync import sync_all
        return sync_all()

    def _execute_healthcheck_ping(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S188 RB-2 — 外部心跳（VR_HEALTHCHECKS_URL 未设→纯本地跳过）。"""
        from scheduler.executors.data_ops import healthcheck_ping
        return healthcheck_ping(payload)

    def _execute_weekly_brainstorm_remind(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S188 RB-9 — 每周头脑风暴提醒（飞书+待办标记）。"""
        from scheduler.executors.data_ops import weekly_brainstorm_remind
        return weekly_brainstorm_remind(payload)

    def _execute_daily_full_pull(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S191 RB-3 — 每日全量拉取沉淀 datalake（stoke + mootdx 分笔）。"""
        from scheduler.executors.data_ops import daily_full_pull
        return daily_full_pull(payload)
