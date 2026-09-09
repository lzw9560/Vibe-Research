# -*- coding: utf-8 -*-
"""默认定时任务 seed——_ensure_seed_tasks（26 个 seed 任务定义）。

幂等（重名跳过），含 cron 迁移逻辑（旧 cron → 新 cron 一次性修正）。
"""
from __future__ import annotations

import logging

from scheduler.db import _manager
from scheduler.models import ScheduledTask

logger = logging.getLogger("vibe-research")


def _ensure_seed_tasks() -> None:
    """R13：seed 默认定时任务——盘后涨停预计算（工作日 15:30）。幂等（重名跳过）。

    cron `30 15 * * 0-4`：cron_match 用 Python datetime.weekday()（0=周一..6=周日，
    见 test_cron_should_run），故工作日=0-4（Mon-Fri）。spec 原写 `1-5`（标准 cron 习惯）
    在本约定下=周二至周六，与"跳周末"意图不符，已按 0=周一 约定修正为 0-4。
    节假日精确判断推 S011b（trading_calendar.json 本轮不建，非交易日由 screener
    返空涨停池自然处理）。

    S101 迁移：candidate_funnel_precompute cron 曾被手改为 16:05（`5 16`），早于
    gene_scores 写入完成（limitup_precompute 15:30 起，全量基因得分+STI 跑 >30min
    未写完），致漏斗 R1 宽源输入 0 → final_candidates=0 → 通知"0 只"。改回 17:15
    （晚 derived_precompute 16:30 +15min，龙虎榜 16:30 后 + gene_scores 写完）。
    """
    existing = {t.name for t in _manager.list_tasks()}

    # S101 迁移：把偏离的 candidate_funnel_precompute cron 拉回 17:15（一次，幂等）
    for t in _manager.list_tasks():
        if t.name == "candidate_funnel_precompute" and t.cron_expr != "15 17 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "15 17 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] candidate_funnel_precompute cron 迁移 %s → 15 17 * * 0-4"
                "（S101：等 gene_scores 写入完成 + 龙虎榜 16:30 后）",
                old_cron,
            )
    if "limitup_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="limitup_precompute",
            description="盘后涨停板基因得分+STI+竞价+复盘预计算（S031 R13 seed）",
            task_type="limitup_precompute",
            cron_expr="30 15 * * 0-4",
            payload={"back_days": 10},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 limitup_precompute 已创建（cron 30 15 * * 0-4）")

    if "sti_post_market" not in existing:
        _manager.create_task(ScheduledTask(
            name="sti_post_market",
            description="S063 盘后 STI 定时计算（交易日 15:30，持久化成为 T+1 硬标准）",
            task_type="sti_post_market",
            cron_expr="35 15 * * 0-4",  # 15:35（晚 precompute 5min，避免并发抢 DB）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 sti_post_market 已创建（cron 35 15 * * 0-4）")

    # S055：盘中封单时序采集——交易时段每分钟 tick。
    # cron `* 9-15 * * 0-4` 触发 09:00-15:59（末次触发延至 15:59，含 15:00 收盘
    # 集合竞价终态）。实际写入由 is_intraday_trading_time（09:25-11:30 / 13:01-15:05）
    # 在 collect_once 内门控——15:06-15:59 的 no-op 触发在 em_get 前早返 skipped
    # （防封安全，已实锤：collect_once 第一行门在 em_zt_topic_pool 之前）。
    if "seal_intraday_collect" not in existing:
        _manager.create_task(ScheduledTask(
            name="seal_intraday_collect",
            description="S055 盘中封单时序采集（交易时段 09:25-15:05 每 60s 轮询 em_zt_topic_pool）",
            task_type="seal_intraday_collect",
            cron_expr="* 9-15 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 seal_intraday_collect 已创建（cron * 9-15 * * 0-4）")

    # S148 R3：盘后 ST-play radar——摘帽/重组/扭亏 白名单（供 classify_tradability ST carve-out）。
    # 17:30 工作日：晚 candidate_funnel_precompute 17:15（gene_scores 写完）+ zt_history_snapshot 17:15 后。
    if "st_play_radar" not in existing:
        _manager.create_task(ScheduledTask(
            name="st_play_radar",
            description="S148 盘后 ST-play radar：扫 ST 股公告 → 摘帽/重组/扭亏 白名单（ST carve-out）",
            task_type="st_play_radar",
            cron_expr="30 17 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 st_play_radar 已创建（cron 30 17 * * 0-4）")

    # S167：盘中微结构数据累积（"等 live" 路径）——累积实时无历史源供 §44v2 复测。
    # 周期快照：每 10min（09:00-15:00 触发，is_intraday_time 门控 09:25-11:30/13:01-15:05）。
    # 诚实：accumulation for future §44v2, prior LOW (S152/S156 refuted), no edge claim yet。
    if "intraday_microstructure_snapshot" not in existing:
        _manager.create_task(ScheduledTask(
            name="intraday_microstructure_snapshot",
            description="S167 盘中微结构周期快照（hithink 排名 + tencent 量比，每 10min 累积供 §44v2 复测）",
            task_type="intraday_microstructure_snapshot",
            cron_expr="*/10 9-15 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 intraday_microstructure_snapshot 已创建（cron */10 9-15 * * 0-4）")

    # S167 竞价密集采集——09:15-09:25 每 2min 采 auction_snapshot(live) 累积 trajectory。
    # cron `*/2 9-9 * * 0-4` 触发 09:00-09:59（偶数分），is_auction_time 门控只放行
    # 09:15-09:25（约 5 ticks：09:16/18/20/22/24）。原 `*/10` 在竞价窗口只命中 09:20
    # 一次，trajectory 过稀无法刻画 auction_volume_ratio 演化（§44 reframe 标记最未证否
    # 盘中 edge）。轻量 auction-only（跳过排名/量比，盘前无意义），save_auction_snapshots
    # PK 幂等——与 microstructure 同 ts 重跑覆盖不翻倍。
    if "intraday_auction_dense" not in existing:
        _manager.create_task(ScheduledTask(
            name="intraday_auction_dense",
            description="S167 竞价密集采集（auction live only，每 2min，is_auction_time 门控 09:15-09:25）",
            task_type="intraday_auction_dense",
            cron_expr="*/2 9-9 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 intraday_auction_dense 已创建（cron */2 9-9 * * 0-4）")

    # S167 baostock 5min 次日冻结——09:00 冻结 prev_trading_date 涨停股 5min bars
    # （当日 bar T+1 lag，次日 09:00 bars 稳定）。is_trading_day 门控（节假日跳）。
    if "baostock_5min_freeze" not in existing:
        _manager.create_task(ScheduledTask(
            name="baostock_5min_freeze",
            description="S167 次日冻结 prev_trading_date 涨停股 baostock 5min bars（秒板/封板时间派生，供 §44v2）",
            task_type="baostock_5min_freeze",
            cron_expr="0 9 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 baostock_5min_freeze 已创建（cron 0 9 * * 0-4）")

    # S123 R3：既有 DB 迁移——seed 仅 `if not in existing` 建任务，旧库仍存 cron
    # `* 9-14 * * 0-4`（末次触发 14:59，漏采 15:00 收盘集合竞价终态）。幂等更新：
    # 仅旧 cron 才改（新 cron 已是目标值→no-op），对齐 candidate_funnel_precompute 迁移范式。
    for t in _manager.list_tasks():
        if t.name == "seal_intraday_collect" and t.cron_expr == "* 9-14 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "* 9-15 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] seal_intraday_collect cron 迁移 %s → * 9-15 * * 0-4"
                "（S123 R3：覆盖 15:00 收盘集合竞价终态，写入由 is_intraday_trading_time 门控）",
                old_cron,
            )

    # S004 R5：盘后漏斗预计算——晚 derived_precompute 15min（读 derived 预采集）+ 龙虎榜 16:30 后。
    # candidate_funnel 走 fund_flow 取龙虎榜（dragon_tiger_board，东财 16:30 后才更新），
    # 故漏斗预计算须在 16:30 后；且 derived_source 读 derived 预采集，须晚 derived_precompute。
    if "candidate_funnel_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="candidate_funnel_precompute",
            description="S004 盘后漏斗预计算（预热 _FUNNEL_CACHE，龙虎榜 16:30 后 + 读 derived 预采集）",
            task_type="candidate_funnel_precompute",
            cron_expr="15 17 * * 0-4",  # 17:15（晚 derived_precompute 17:00 +15min，龙虎榜 16:30 后）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 candidate_funnel_precompute 已创建（cron 15 17 * * 0-4）")

    # S075：盘后首板流筛选——16:15（晚 forward_test_t1_settle 15:50，避抢 DB；
    #   candidate_funnel_precompute 已后移 17:15，与 first_board 不再同刻抢 DB）。
    if "first_board_filter" not in existing:
        _manager.create_task(ScheduledTask(
            name="first_board_filter",
            description="S075 盘后首板流筛选（首板过滤+三层剔除+9维度评分，15:30后跑）",
            task_type="first_board_filter",
            cron_expr="15 16 * * 0-4",  # 16:15（晚 forward_test_t1_settle 15:50）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 first_board_filter 已创建（cron 15 16 * * 0-4）")

    # S090 B：kline 日更——盘后 16:30 增量刷新 baostock_kline_cache（premarket breakout 数据源）。
    # baostock 非东财不被限流；晚 first_board_filter 16:15 +15min，盘后拉当日新 bar。
    if "kline_refresh" not in existing:
        _manager.create_task(ScheduledTask(
            name="kline_refresh",
            description="S090 B：盘后 baostock_kline_cache 增量刷新（premarket breakout 数据源日更）",
            task_type="kline_refresh",
            cron_expr="30 16 * * 0-4",  # 16:30（晚 first_board_filter 16:15 +15min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 kline_refresh 已创建（cron 30 16 * * 0-4）")

    # §44 60 天复验检查点（提醒任务）：周一 18:00 数 eastmoney_live 日数，达 60 →
    # 写 s066_60day_due.json + WARNING + notify_on_success 推送（通道未配则静默）。
    # 到点由人/会话跑 backfill --weather 查 lift；本任务只提醒不自动验证。
    if "s066_validation_checkpoint" not in existing:
        _manager.create_task(ScheduledTask(
            name="s066_validation_checkpoint",
            description="§44 60 天复验检查点：eastmoney_live 达 60 日提醒重跑 Phase 0b/0e（spec §13 ①）",
            task_type="s066_validation_checkpoint",
            cron_expr="0 18 * * 1",  # 周一 18:00（每周检查一次，到点提醒）
            payload={"threshold": 60},
            enabled=True,
            notify_on_success=True,
        ))
        logger.info("[scheduler] seed 默认任务 s066_validation_checkpoint 已创建（cron 0 18 * * 1，§44 60 天复验提醒）")

    # S151 R3：评价层回溯检查点（提醒任务）：周一 18:05 数 forward_test 信号日 + buyable picks，
    # 30 日 + n≥100 → 首次回溯 DUE（写 s151_evaluation_backtest_due.json + WARNING）；
    # 60 日 → 复验 DUE。到点只提醒不自动验证（同 s066）——由人/会话跑 day_paired_lift harness。
    if "evaluation_backtest" not in existing:
        _manager.create_task(ScheduledTask(
            name="evaluation_backtest",
            description="S151 R3：评价层 30日首次/60日复验回溯检查点（§44 per-dimension lift 提醒）",
            task_type="evaluation_backtest",
            cron_expr="5 18 * * 1",  # 周一 18:05（晚 s066 18:00，同窗口周一一次）
            payload={"first_threshold": 30, "reverify_threshold": 60, "min_n": 100},
            enabled=True,
            notify_on_success=True,
        ))
        logger.info("[scheduler] seed 默认任务 evaluation_backtest 已创建（cron 5 18 * * 1，S151 回溯提醒）")

    # S069 R1：每日 post-market 记当日 forward_test picks + universe（晚 limitup_precompute 15min）。
    # weather 用 build_context（完整架构）；T+1 收益由 R2 次日回填（待接）。
    if "forward_test_daily" not in existing:
        _manager.create_task(ScheduledTask(
            name="forward_test_daily",
            description="S069 R1：每日 post-market 记当日 forward_test picks+universe（§44 数据日积）",
            task_type="forward_test_daily",
            cron_expr="45 15 * * 0-4",  # 15:45（晚 precompute 15:30 + sti 15:35）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 forward_test_daily 已创建（cron 45 15 * * 0-4）")

    # S069 R2：每日 post-market 回填昨日 forward_test T+1 收益（baostock kline 次日 bar）。
    if "forward_test_t1_settle" not in existing:
        _manager.create_task(ScheduledTask(
            name="forward_test_t1_settle",
            description="S069 R2：每日 post-market 回填昨日 forward_test picks+universe 的 T+1 收益",
            task_type="forward_test_t1_settle",
            cron_expr="50 15 * * 0-4",  # 15:50（晚 R1 15:45，next_bar 今日收盘后可得）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 forward_test_t1_settle 已创建（cron 50 15 * * 0-4）")

    # S075：盘后 T+1 溢价评分 + 复盘报告 + 飞书通知（晚 first_board_filter 16:15 +15min）。
    # 对 T-1 候选做 T+1 收益评价，构造 Markdown 复盘报告，飞书推送用户。
    if "first_board_t1_review" not in existing:
        _manager.create_task(ScheduledTask(
            name="first_board_t1_review",
            description="S075 T+1 溢价评分+复盘报告+飞书通知（盘后对 T-1 候选做收益评价）",
            task_type="first_board_t1_review",
            cron_expr="30 16 * * 0-4",  # 16:30（晚 first_board_filter 16:15 +15min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 first_board_t1_review 已创建（cron 30 16 * * 0-4）")

    # S084 C1：盘后 derived 异步预采集——17:00 对昨日涨停股全量算派生落 seal_derived_features，
    # 选股池 derived_source 读预采集（不 per-code 实时算）。龙虎榜 16:30 后统一盘后跑，
    # derived 不依赖龙虎榜但提前 candidate_funnel_precompute 17:15（漏斗读 derived 预采集）。
    if "derived_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="derived_precompute",
            description="S084 盘后 derived 异步预采集（昨日涨停股全量算派生落 seal_derived_features，选股池读预采集）",
            task_type="derived_precompute",
            cron_expr="0 17 * * 0-4",  # 17:00 工作日（0=周一约定，龙虎榜 16:30 后 + 早 candidate 17:15）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 derived_precompute 已创建（cron 0 17 * * 0-4）")

    # S089 D2：月度 VACUUM + wal_checkpoint(TRUNCATE)——月初 02:00 跑（低负载时段，
    # 避开盘后批处理 15:30-17:15）。当年热库 VACUUM 回收碎片 + 截断 -wal 防膨胀。
    if "monthly_vacuum" not in existing:
        _manager.create_task(ScheduledTask(
            name="monthly_vacuum",
            description="S089 月度 VACUUM + wal_checkpoint(TRUNCATE)——当年热库回收碎片+截断 -wal 防膨胀",
            task_type="monthly_vacuum",
            cron_expr="0 2 1 * *",  # 每月 1 日 02:00
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 monthly_vacuum 已创建（cron 0 2 1 * *，月初 02:00）")

    # S093 R12：AI 盘后总结 stub——15:30（与 stage 推进点 intraday→post_transition 15:30 对齐）。
    # S094 完整实现：LLM 汇总当日信号 + 持仓表现。本 stub 返空串 + 落存储位。
    if "daily_ai_summary" not in existing:
        _manager.create_task(ScheduledTask(
            name="daily_ai_summary",
            description="S093 R12：AI 盘后总结 stub（cron 15:30，S094 完整实现 LLM 汇总）",
            task_type="daily_ai_summary",
            cron_expr="30 15 * * 0-4",  # 15:30（与 limitup_precompute 同刻，stub 无 DB 写不抢锁）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 daily_ai_summary 已创建（cron 30 15 * * 0-4）")

    # S101：飞书多点通知——9:25 竞价 / 9:35 开盘 / T+1 16:35 复盘
    # 前瞻标的从 F 日 funnel_cache 读（17:15 已存），不重跑漏斗。
    if "premarket_auction_notify" not in existing:
        _manager.create_task(ScheduledTask(
            name="premarket_auction_notify",
            description="S101 9:25 竞价确认通知（前瞻标的 F 日 final_candidates 开盘竞价表现）",
            task_type="premarket_auction_notify",
            cron_expr="25 9 * * 0-4",  # 工作日 9:25（集合竞价完成后）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 premarket_auction_notify 已创建（cron 25 9 * * 0-4）")

    if "premarket_open_notify" not in existing:
        _manager.create_task(ScheduledTask(
            name="premarket_open_notify",
            description="S101 9:35 开盘表现通知（前瞻标的开盘 5min 现价/涨跌幅/封板）",
            task_type="premarket_open_notify",
            cron_expr="35 9 * * 0-4",  # 工作日 9:35（开盘后 5min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 premarket_open_notify 已创建（cron 35 9 * * 0-4）")

    if "premarket_t1_review" not in existing:
        _manager.create_task(ScheduledTask(
            name="premarket_t1_review",
            description="S101 T+1 复盘通知（前瞻标的 F→T 收益评价，§44 诚实口径）",
            task_type="premarket_t1_review",
            cron_expr="35 16 * * 0-4",  # 16:35（晚 first_board_t1_review 5min 避抢 DB）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 premarket_t1_review 已创建（cron 35 16 * * 0-4）")

    # S078：盘后终盘涨停池 snapshot——17:15（过稳定点写 is_final=true，zt_history.db）。
    # 旧 cron "0 16"（16:00 写 is_final=false，无 17:15 final run → is_final 从不自动 true）。
    # 迁移到 "15 17"（仿 :2233 candidate_funnel 范式）。幂等：存在跳过 create，旧 cron 才迁移。
    if "zt_history_snapshot" not in existing:
        _manager.create_task(ScheduledTask(
            name="zt_history_snapshot",
            description="S078 盘后终盘涨停池 snapshot（17:15 过稳定点写 is_final=true，zt_history.db 数据地基）",
            task_type="zt_history_snapshot",
            cron_expr="15 17 * * 0-4",  # 17:15（东财池盘后稳定，写 is_final=true）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 zt_history_snapshot 已创建（cron 15 17 * * 0-4）")
    for t in _manager.list_tasks():
        if t.name == "zt_history_snapshot" and t.cron_expr == "0 16 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "15 17 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] zt_history_snapshot cron 迁移 %s → 15 17 * * 0-4"
                "（17:15 过稳定点写 is_final=true，旧 16:00 写 is_final=false 无 final run）",
                old_cron,
            )

    # 知识图谱每日数据同步——16:00（收盘后，工作日）。跑 vault/scripts/daily_sync.py：
    # 拉 /api/market/emotion + /api/indices → 写 scores/ + 刷情绪仪表盘 → 重跑 precompile/
    # refresh_stats/daily_audit → git commit + push。超时 300s，错误不阻断主调度循环。
    # 与 daily_kg_audit 分工：sync 拉数据写文件（16:00），audit 跑结构审查（可晚于 sync）。
    if "daily_kg_sync" not in existing:
        _manager.create_task(ScheduledTask(
            name="daily_kg_sync",
            description="知识图谱每日数据同步（拉后端 API 情绪数据更新 scores/ + 情绪仪表盘，16:00 收盘后）",
            task_type="daily_kg_sync",
            cron_expr="0 16 * * 0-4",  # 16:00 工作日（收盘后）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 daily_kg_sync 已创建（cron 0 16 * * 0-4，16:00 收盘后）")

    # ── P0 active bugs 清理（2026-09-09 项目瘦身）──────────────────────────

    # P0-1：删除 n8n-trigger 重复任务（type=limitup_precompute，cron 1-5=错——
    # 1-5 在 weekday() 约定下=周二至周六。limitup_precompute 已有正确 seed 0-4，
    # 此为遗留重复，删除）。
    for t in _manager.list_tasks():
        if t.name == "n8n-trigger":
            _manager.delete_task(t.id)
            logger.info(
                "[scheduler] 删除重复任务 n8n-trigger（type=limitup_precompute，"
                "cron 1-5 错误，limitup_precompute 0-4 已正确 seed）"
            )
            break

    # P0-2：每日回测快照 cron 迁移 1-5→0-4（1-5=周二至周六，周日不应跑 backtest）。
    for t in _manager.list_tasks():
        if t.name == "每日回测快照" and "1-5" in t.cron_expr:
            old_cron = t.cron_expr
            t.cron_expr = t.cron_expr.replace("1-5", "0-4")
            _manager.update_task(t)
            logger.info(
                "[scheduler] 每日回测快照 cron 迁移 %s → %s"
                "（1-5=周二至周六，修正为 0-4=周一至周五，周日不跑 backtest）",
                old_cron, t.cron_expr,
            )
            break

    # P0-3：disable first_board_quote_probe（S076 临时研究任务——
    # "收 3-5 个交易日稳定结论后 disable"，已过研究期，探测占用资源，禁用）。
    for t in _manager.list_tasks():
        if t.name == "first_board_quote_probe" and t.enabled:
            t.enabled = False
            _manager.update_task(t)
            logger.info(
                "[scheduler] first_board_quote_probe 已 disable"
                "（S076 临时研究任务完成，探测占用资源）"
            )
            break

    # P0-4：seed daily_kg_audit（知识图谱每日结构审查——断链/孤立/coverage/confidence。
    # 晚 daily_kg_sync 16:00 +30min，sync 拉数据写文件后 audit 跑结构审查）。
    if "daily_kg_audit" not in existing:
        _manager.create_task(ScheduledTask(
            name="daily_kg_audit",
            description="知识图谱每日结构审查（断链/孤立/coverage/confidence，晚 daily_kg_sync 16:00 +30min）",
            task_type="daily_kg_audit",
            cron_expr="30 16 * * 0-4",  # 16:30 工作日（晚 sync 30min，sync 先拉数据 audit 后审查）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 daily_kg_audit 已创建（cron 30 16 * * 0-4）")
