# -*- coding: utf-8 -*-
"""backtest executors——日回测/§44 检查点/评价层回测/forward_test daily/T+1 settle。"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from scheduler.snapshots import _save_snapshot
# §44v2 P0：apply_revalidation 模块级 import（monkeypatch 友好；lift_override→evaluation 无循环）
from candidate_funnel.lift_override import apply_revalidation

logger = logging.getLogger("vibe-research")


def daily_backtest_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S041：每日回测快照——跑 backtest_lite + strategy_backtest，存入 backtest_daily_snapshots。

    lite 是 async，在 sync handler 里用 asyncio.run() 驱动；strategy 是 sync 直调。
    单引擎失败不阻断另一个——回测是增强，失败兜底记 error。

    S052 D1/D6：payload 增可选 as_of_date（YYYY-MM-DD）——point-in-time 回算。
    缺省=今天（行为不变）；给了则 snapshot_date=as_of、窗口终点=as_of、strategy 传 as_of。
    """
    from backtest_lite import run_backtest_async
    from strategies.strategy_backtest import run_strategy_backtest

    lookback = int(payload.get("lookback_days", 30))
    as_of = payload.get("as_of_date")  # S052 D1：可选 point-in-time 日期
    today_dt = datetime.now().date()
    if as_of:
        snapshot_date = as_of
        end = as_of
        start_dt = datetime.strptime(as_of, "%Y-%m-%d").date()
    else:
        snapshot_date = today_dt.strftime("%Y-%m-%d")
        end = snapshot_date
        start_dt = today_dt
    start = (start_dt - timedelta(days=lookback)).strftime("%Y-%m-%d")

    results: Dict[str, Any] = {"snapshot_date": snapshot_date, "lookback_days": lookback, "start": start, "as_of_date": as_of}

    # lite 引擎
    # L5 标注：asyncio.run() 在 execute() 同步路径经 asyncio.to_thread 包装在线程池中，
    # 无现有事件循环，安全。execute_async 异步路径不经过此同步方法。
    try:
        lite_result = asyncio.run(run_backtest_async(start, end))
        _save_snapshot(snapshot_date, "lite", lite_result)
        results["lite"] = {
            "hit_rate": lite_result.hit_rate,
            "avg_return": lite_result.avg_return,
            "total_signals": lite_result.total_signals,
        }
    except Exception as e:
        logger.warning("[daily_backtest_run] lite 回测失败: %s", e)
        results["lite"] = f"error: {e}"

    # strategy 引擎
    try:
        strat_results = run_strategy_backtest(lookback, as_of)
        _save_snapshot(snapshot_date, "strategy", strat_results)
        results["strategy"] = {
            "strategies": len(strat_results),
            "total_sample": sum(getattr(r, "sample_size", 0) for r in strat_results),
        }
    except Exception as e:
        logger.warning("[daily_backtest_run] strategy 回测失败: %s", e)
        results["strategy"] = f"error: {e}"

    return results


def s066_validation_checkpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """§44 60 天复验检查点（提醒任务，spec §13 ①/§44）。

    数 eastmoney_live 信号日；达 threshold（默认 60）→ 写 checkpoint 文件 + WARNING 日志
    + 返 DUE+操作指引（notify_on_success 兜底推送，若通道已配）；未到期 → 返进度（静默）。
    到点由人/会话跑 `tools/forward_test_backfill.py --weather` 查 lift——本任务只提醒不自动验证。
    """
    from config import GENE_SCORES_DB_PATH
    from vr_paths import resolve_data_dir
    from db_health import get_healthy_conn

    threshold = int(payload.get("threshold", 60))
    conn = get_healthy_conn(GENE_SCORES_DB_PATH)
    try:
        days = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM gene_scores WHERE data_source='eastmoney_live'"
        ).fetchone()[0]
    finally:
        conn.close()

    if days < threshold:
        return {"status": "not_due", "eastmoney_live_days": days, "target": threshold,
                "note": f"积累中 {days}/{threshold} 日，到点自动提醒 §44 复验"}

    # 到期：写 checkpoint + WARNING + 返操作指引
    ckpt = {"status": "due", "eastmoney_live_days": days, "target": threshold,
            "action": "cd backend && .venv/bin/python tools/forward_test_backfill.py --weather "
                      "→ 查 get_forward_test_summary 的 lift：破 2x + within-day r 显著 → alpha 成立；"
                      "否则确认无 edge（spec §13 ①/§44）",
            "checked_at": datetime.now().isoformat()}
    try:
        ckpt_path = Path(resolve_data_dir()) / "s066_60day_due.json"
        ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    logger.warning(
        "[s066_checkpoint] §44 60 天复验 DUE：eastmoney_live=%d 日 → 跑 backfill --weather 查 lift", days)
    return ckpt


def evaluation_backtest(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S151 R3：评价层回溯检查点（§44v2 P0 闭环——到点自动写回，非 reminder-only）。

    数 forward_test_records 信号日 + buyable picks；两档门槛：
    - 30 日 + n≥100 → 首次回溯 DUE（apply_revalidation 算 per-dimension day_paired_lift，
      写 evaluation_lifts.db dimension_lift_overrides；reader override 优先 fallback frozen）
    - 60 日 → 复验 DUE（重跑 lift + 经 lift_to_multiplier 升降级：lift≥2+days≥60+CI不重叠→
      validated×1.0；lift<1+days≥60+robust→劣于随机×0.1；days<60→待复验×0.5 规约④ cap）

    自动写回 best-effort：compute 不可用/返空（baostock down 等）→ 降级 reminder（status due
    + action 命令串指引人跑），不崩 scheduled task。未到期返 not_due + 进度（静默）。
    不改 frozen DIMENSION_LIFT_REGISTRY（FROZEN_COMMIT b1aba21 read-only）——override 躺新表。
    """
    from config import GENE_SCORES_DB_PATH
    from vr_paths import resolve_data_dir
    from db_health import get_healthy_conn

    first_threshold = int(payload.get("first_threshold", 30))
    reverify_threshold = int(payload.get("reverify_threshold", 60))
    min_n = int(payload.get("min_n", 100))

    conn = get_healthy_conn(GENE_SCORES_DB_PATH)
    try:
        days = conn.execute(
            "SELECT COUNT(DISTINCT signal_date) FROM forward_test_records"
        ).fetchone()[0]
        # S144 buyable 口径（剔 is_unbuyable=1 一字板，与 verdict 同源）
        n = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE is_unbuyable = 0"
        ).fetchone()[0]
    finally:
        conn.close()

    # 未到期：返进度（静默）
    if days < first_threshold:
        return {"status": "not_due", "signal_days": days, "picks_n": n,
                "first_threshold": first_threshold, "reverify_threshold": reverify_threshold,
                "min_n": min_n,
                "note": f"日数积累中 {days}/{first_threshold}（n={n}），到点提醒 §44 首次回溯"}
    if n < min_n:
        return {"status": "not_due", "signal_days": days, "picks_n": n,
                "first_threshold": first_threshold, "reverify_threshold": reverify_threshold,
                "min_n": min_n,
                "note": f"日数 {days}≥{first_threshold} 达首档但 n={n}/{min_n} 不足，picks 积累中"}

    # 到期：判阶段 + 自动写回 + checkpoint + WARNING + 操作指引（fallback）
    # §44v2 P0（S159 R4 回溯主场）：不再 reminder-only——到点调 apply_revalidation
    # 自动写回 dimension_lift_overrides（不改 frozen dict）。compute 不可用/返空 → reminder fallback。
    phase = "first_retrospective" if days < reverify_threshold else "reverify"
    written_back: list = []
    write_errors: list = []
    try:
        wb = apply_revalidation(phase)
        written_back = wb.get("written", [])
        write_errors = wb.get("errors", [])
    except Exception as e:  # noqa: BLE001 — 写回崩不阻断 scheduled task，降级 reminder
        logger.warning("[evaluation_backtest] 自动写回失败，降级 reminder: %s", e)

    # fallback 操作指引（compute 不可用或部分维度未接线时仍指引人跑）
    if phase == "first_retrospective":
        action = (
            "cd backend && .venv/bin/python tools/first_board_layer_lift.py --baostock-history "
            "→ 跑 per-dimension day_paired_lift（非池化防 4.686x→1.723x 假象）写 "
            "evaluation_lifts.db → DIMENSION_LIFT_REGISTRY 升级 DB-backed 动态读（spec S151 R3）"
        )
    else:
        action = (
            "cd backend && .venv/bin/python tools/first_board_layer_lift.py --baostock-history "
            "→ 重跑 lift + 判升级/降级（lift≥2+CI不重叠→validated×1.0；lift<1 robust→劣于随机×0.1；"
            "1≤lift<2→未validated×0.5）——更新 DIMENSION_LIFT_REGISTRY updated_*"
        )
    ckpt = {"status": "due", "phase": phase, "signal_days": days, "picks_n": n,
            "first_threshold": first_threshold, "reverify_threshold": reverify_threshold,
            "min_n": min_n, "action": action,
            "written_back": written_back,  # 自动写回的维度（§44v2 P0）
            "write_errors": write_errors,
            "checked_at": datetime.now().isoformat()}
    try:
        ckpt_path = Path(resolve_data_dir()) / "s151_evaluation_backtest_due.json"
        ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    if written_back:
        logger.warning(
            "[evaluation_backtest] S151 回溯 DUE（%s）自动写回 %d 维度：%s；signal_days=%d picks_n=%d",
            phase, len(written_back), written_back, days, n)
    else:
        logger.warning(
            "[evaluation_backtest] S151 回溯 DUE（%s）自动写回空（compute 不可用）→ reminder：%s",
            phase, action)
    return ckpt


def r3_enforce(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S204 T8: R3 enforce——§44v2 verdict 定期 enforce 降级。

    非 reminder（evaluation_backtest 是 reminder+apply_revalidation）——T8 是直接 enforce：
    per-arm 算 current days_robust（trade_journal distinct exit_date），≥60 阈 → 调
    lift_to_multiplier + write_override 刷新 override。当前 forward_test ~20 天 → skip all underpowered。

    非 arm 级 dimension（gene_score/turnover/seal_amount 等无 arm 映射）→ skip（保持 frozen baseline，
    不重算 days）——只 arm 级 dimension（breakout/trend/post_first_board 及其盘中因子）有
    forward_test records 可重算 days。
    """
    from candidate_funnel.evaluation import (  # noqa: PLC0415
        DIMENSION_LIFT_REGISTRY, DIM_ARM_MAP, lift_to_multiplier,
    )
    from candidate_funnel.lift_override import write_override  # noqa: PLC0415
    from engine.trade_journal import TradeJournal  # noqa: PLC0415

    threshold_days = int(payload.get("threshold_days", 60))
    journal = TradeJournal()

    # 反查 DIM_ARM_MAP: dimension → arm
    dim_to_arm: dict[str, str] = {}
    for arm, dims in DIM_ARM_MAP.items():
        if dims:
            for dim_id in dims:
                dim_to_arm[dim_id] = arm

    enforced: list[dict] = []
    skipped_underpowered: list[dict] = []
    skipped_non_arm: list[str] = []
    skipped_event_edge: list[dict] = []  # S219-deep-review（2026-09-18 w1d19k2hl）：event-edge (lift=None/regime_caps) → weekly_review cap gate 管

    for dim_id, dim in DIMENSION_LIFT_REGISTRY.items():
        if dim_id.endswith("_ref"):
            continue  # 参照不参与
        arm = dim_to_arm.get(dim_id)
        if arm is None:
            # 非 arm 级（gene_score/turnover/sector_heat 等）→ 保持 frozen，不重算
            skipped_non_arm.append(dim_id)
            continue
        # arm 级：算 current days_robust（distinct exit_date，含死臂历史）
        records = journal.query_records(arm=arm, is_realized=1, is_dead_arm=None)
        current_days = len({r.exit_date for r in records if r.exit_date})
        if current_days < threshold_days:
            skipped_underpowered.append({
                "dimension_id": dim_id, "arm": arm,
                "current_days": current_days, "threshold": threshold_days,
            })
            continue
        # S219-deep-review event-edge 守卫（2026-09-18 w1d19k2hl）：consecutive_relay lift=None +
        # regime_caps 不走 lift_to_multiplier(None→×1.0) 路径——lift is None 分支返 ('探索性', 1.0)
        # 当 days_sufficient=True，write_override 不保 regime_caps → 静默绕过 bull×0.75 cap +
        # 34%衰减门 + bear_days≥120 + lbc3_days≥60，最该门控时刻自动升满仓。
        # consecutive_relay cap 由 weekly_review cap gate 管（_evaluate_cap_up_gate/_evaluate_cap_down_trigger），
        # 非 r3_enforce selection-lift 逻辑。
        if dim.lift is None or dim.regime_caps is not None:
            skipped_event_edge.append({
                "dimension_id": dim_id, "arm": arm, "current_days": current_days,
                "lift": dim.lift, "regime_caps": dim.regime_caps,
                "reason": "event-edge (lift=None/regime_caps) → weekly_review cap gate 管，非 r3_enforce",
            })
            continue
        # ≥60 → enforce: lift_to_multiplier + write_override 刷新
        status, mult = lift_to_multiplier(
            dim.lift, dim.n, days_robust=current_days,
        )
        write_override(
            dim_id, dim.lift, dim.n, current_days,
            phase="r3_enforce",
            source_script="scheduler/executors/backtest.py::r3_enforce",
        )
        enforced.append({
            "dimension_id": dim_id, "arm": arm,
            "current_days": current_days,
            "lift": dim.lift, "n": dim.n,
            "status": status, "weight_multiplier": mult,
        })

    summary = (
        f"R3 enforce: {len(enforced)} enforced, "
        f"{len(skipped_underpowered)} underpowered (<{threshold_days}d), "
        f"{len(skipped_non_arm)} non-arm (frozen), "
        f"{len(skipped_event_edge)} event-edge (→weekly_review cap gate)"
    )
    logger.warning("[r3_enforce] %s", summary)
    return {
        "status": "ok",
        "enforced": enforced,
        "skipped_underpowered": skipped_underpowered,
        "skipped_non_arm": skipped_non_arm,
        "skipped_event_edge": skipped_event_edge,
        "threshold_days": threshold_days,
        "summary": summary,
    }


def forward_test_daily(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S069 R1：每日 post-market 记当日 forward_test picks + universe codes（收益 NULL，R2 次日回填）。

    晚 limitup_precompute（gene_scores 已写 15:30）。weather 用 build_context（完整架构非退化）。
    信号日 = last_trading_date_str（当日交易日；周末跑记最近交易日，幂等）。
    """
    from vr_paths import last_trading_date_str
    from sentiment_context import build_context
    from strategies.forward_test import run_daily_forward_test

    signal_date = last_trading_date_str()
    try:
        weather = build_context(signal_date).weather_state
    except Exception:
        weather = None
    r = run_daily_forward_test(signal_date, weather_state=weather)
    logger.info("[forward_test_daily] %s picks=%s universe=%s weather=%s",
               signal_date, r.get("recommendations", 0), r.get("universe_codes", 0), weather)
    return {"signal_date": signal_date, "weather": weather,
            "picks": r.get("recommendations", 0), "universe_codes": r.get("universe_codes", 0)}


def forward_test_t1_settle(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S069 R2：回填最近未结算 signal_date 的 T+1 收益（baostock kline→return_open2close）。

    每日 post-market 跑。处理 newest 3 个 signal_date<今日 且 return_open2close IS NULL 的
    （其 next_bar 今日收盘后可得）→ compute_returns_for_codes → record_actual_returns（picks）+
    record_universe_returns（universe）。缺 next_bar 的 code 留 NULL（下次重试）。
    **stuck-date 处理**：0-settle 的日期（如调休补班 baostock 无 bar）标 no_bar（JSON，7 日后重试），
    避免每日卡死循环在同一 stuck date。
    """
    import sqlite3
    from config import GENE_SCORES_DB_PATH
    from datetime import datetime, timedelta
    from db_health import get_healthy_conn
    from vr_paths import last_trading_date_str, resolve_data_dir
    from strategies.forward_test import record_actual_returns, record_universe_returns
    from strategies.kline_returns import compute_returns_for_codes

    today = last_trading_date_str()
    # stuck-mark：7 日内 0-settle 的日期不重试（避免卡死；7 日后重试，防 baostock 暂态）
    stuck_path = Path(resolve_data_dir()) / "t1_stuck_dates.json"
    stuck: dict[str, str] = {}
    try:
        stuck = json.loads(stuck_path.read_text(encoding="utf-8"))
    except Exception:
        stuck = {}
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    stuck = {d: t for d, t in stuck.items() if t >= cutoff}  # 清 7 日前的 stuck（重试）

    conn = get_healthy_conn(GENE_SCORES_DB_PATH)
    try:
        # S151 fix：stuck 在 SQL 内排除（LIMIT 前），避免 newest 3 全 stuck 时够不着
        # 非 stuck 旧日期（原 post-filter 在 LIMIT 后，stuck 占满 LIMIT→空）。
        # bulk=True 提 LIMIT 处理全 non-stuck（默认 3=每日 cron 轻量）。
        bulk = bool(payload.get("bulk"))
        limit = 50 if bulk else 3
        stuck_dates = list(stuck.keys())
        if stuck_dates:
            stuck_ph = ",".join("?" * len(stuck_dates))
            rows = conn.execute(
                "SELECT DISTINCT signal_date FROM forward_test_records "
                "WHERE return_open2close IS NULL AND signal_date < ? "
                f"AND signal_date NOT IN ({stuck_ph}) "
                "ORDER BY signal_date DESC LIMIT ?",
                [today] + stuck_dates + [limit],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT signal_date FROM forward_test_records "
                "WHERE return_open2close IS NULL AND signal_date < ? "
                "ORDER BY signal_date DESC LIMIT ?",
                [today, limit],
            ).fetchall()
        dates = [r[0] for r in rows]  # stuck 已在 SQL 排除
    finally:
        conn.close()
    if not dates:
        return {"status": "nothing_to_settle", "today": today, "stuck": len(stuck)}

    summary = []
    for signal_date in dates:
        conn = get_healthy_conn(GENE_SCORES_DB_PATH)
        try:
            # S145：picks 取 code + strategy_code（建 strategy_params_map 供 path 模拟用其战法 params）
            pick_rows = conn.execute(
                "SELECT code, strategy_code FROM forward_test_records "
                "WHERE signal_date=? AND return_open2close IS NULL", (signal_date,)).fetchall()
            pick_codes = list(dict.fromkeys(r[0] for r in pick_rows))
            uni_codes = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM universe_returns "
                "WHERE signal_date=? AND return_open2close IS NULL", (signal_date,)).fetchall()]
        finally:
            conn.close()
        all_codes = list(dict.fromkeys(pick_codes + uni_codes))
        if not all_codes:
            continue
        # S145 R2：每 pick code 取首个战法 params（多战法同 code 时按 code UPDATE 全行同 path）
        from strategies.kline_returns import strategy_params_for  # noqa: PLC0415
        strategy_params_map: dict[str, dict] = {}
        for code, sc in pick_rows:
            if code not in strategy_params_map and sc:
                strategy_params_map[code] = strategy_params_for(sc)
        returns_map = compute_returns_for_codes(signal_date, all_codes,
                                                strategy_params_map=strategy_params_map or None)
        if not returns_map:
            summary.append({"signal_date": signal_date, "status": "baostock_unavailable"})
            break  # baostock 不可用，后续日也跑不了
        picks_returns = {c: returns_map[c] for c in pick_codes
                         if c in returns_map and returns_map[c]["return_open2close"] is not None}
        uni_returns = {c: returns_map[c] for c in uni_codes
                       if c in returns_map and returns_map[c]["return_open2close"] is not None}
        n_picks = record_actual_returns(signal_date, picks_returns)
        n_uni = record_universe_returns(signal_date, uni_returns)
        settled = n_picks + n_uni
        # 0-settle → 标 stuck（如调休补班 baostock 无 bar），7 日内不重试
        if settled == 0:
            stuck[signal_date] = datetime.now().isoformat()
        logger.info("[forward_test_t1_settle] %s settled picks=%s/%s universe=%s/%s%s",
                   signal_date, n_picks, len(pick_codes), n_uni, len(uni_codes),
                   " [stuck-mark]" if settled == 0 else "")
        summary.append({"signal_date": signal_date, "settled_picks": n_picks,
                        "settled_universe": n_uni, "total": settled})

    try:
        stuck_path.write_text(json.dumps(stuck, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"today": today, "dates_processed": summary, "stuck": len(stuck)}
