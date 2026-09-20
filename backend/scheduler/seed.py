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

    # S184 P1-1 迁移：candidate_funnel_precompute cron 17:15 → 17:25（晚 kline_refresh 17:15 +10min，避免并发读 stale cache）
    for t in _manager.list_tasks():
        if t.name == "candidate_funnel_precompute" and t.cron_expr != "25 17 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "25 17 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] candidate_funnel_precompute cron 迁移 %s → 25 17 * * 0-4"
                "（S184 P1-1：晚 kline_refresh 17:15 +10min，避免并发读 stale cache）",
                old_cron,
            )

    # S184 迁移：kline_refresh + trade_journal_daily cron 16:30/16:45 → 17:15/17:30
    # （baostock 17:00+ 当日 bar 更新后，16:30 T+1 延迟未就绪导致 retry storm timeout）
    for t in _manager.list_tasks():
        if t.name == "kline_refresh" and t.cron_expr == "30 16 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "15 17 * * 0-4"
            _manager.update_task(t)
            logger.info("[scheduler] kline_refresh cron 迁移 %s → 15 17 * * 0-4（S184: baostock 17:00+ 更新后）", old_cron)
        elif t.name == "trade_journal_daily" and t.cron_expr == "45 16 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "30 17 * * 0-4"
            _manager.update_task(t)
            logger.info("[scheduler] trade_journal_daily cron 迁移 %s → 30 17 * * 0-4（S184: 晚 kline_refresh 17:15）", old_cron)

    # S190 R5：盘后链 depends_on 硬门控（上游今日未 success/degraded 则跳过，防下游吃陈旧数据）
    # 当前靠 cron 时序错开（17:15→17:25→17:30）脆，加硬门控兜底
    for t in _manager.list_tasks():
        if t.name == "candidate_funnel_precompute" and not t.depends_on:
            t.depends_on = "kline_refresh"
            _manager.update_task(t)
            logger.info("[scheduler] candidate_funnel_precompute 声明 depends_on=kline_refresh（S190 R5）")
        elif t.name == "trade_journal_daily" and not t.depends_on:
            t.depends_on = "candidate_funnel_precompute,kline_refresh"
            _manager.update_task(t)
            logger.info("[scheduler] trade_journal_daily 声明 depends_on=candidate_funnel_precompute,kline_refresh（S190 R5）")
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

    # S203 T6：吃大面 enforce gate 盘后跑（17:35 晚 trade_journal_daily 17:30 让 MTM 先更新）。
    # 单笔>5% 禁加仓 / 合计>8% 禁开新仓+冷却。⛔ 不碰 final_size sizing——只算+返 enforce 状态。
    if "loss_breaker_enforce" not in existing:
        _manager.create_task(ScheduledTask(
            name="loss_breaker_enforce",
            description="S203 T6 吃大面 enforce gate：持仓浮亏 block_add/block_new+冷却（不碰 final_size sizing）",
            task_type="loss_breaker_enforce",
            cron_expr="35 17 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 loss_breaker_enforce 已创建（cron 35 17 * * 0-4）")

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
            cron_expr="25 17 * * 0-4",  # S184 P1-1: 17:25（晚 kline_refresh 17:15 +10min，避免并发读 stale cache）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 candidate_funnel_precompute 已创建（cron 25 17 * * 0-4）")

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
            cron_expr="15 17 * * 0-4",  # S184: 17:15（baostock 17:00+ 当日 bar 更新后，16:30 T+1 延迟未就绪）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 kline_refresh 已创建（cron 15 17 * * 0-4，S184 baostock 17:00+ 更新后）")

    # S175 R2：模拟盘闭环盘后跑（journal_recorder.run_daily 接 scheduler 点火，BREAK-0 fix）。
    # 16:45 盘后（晚 kline_refresh 16:30 确保 baostock_kline_cache.json 已刷当日 bar）。
    # ETF bars 走 fetch_etf_hist（akshare push2delay，非 cache）。
    if "trade_journal_daily" not in existing:
        _manager.create_task(ScheduledTask(
            name="trade_journal_daily",
            description="S175 R2：盘后闭环（settle_pending + run_daily floor+breakout + floor MTM）",
            task_type="trade_journal_daily",
            cron_expr="30 17 * * 0-4",  # S184: 17:30（晚 kline_refresh 17:15 +15min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 trade_journal_daily 已创建（cron 30 17 * * 0-4，晚 kline_refresh 17:15）")

    # S176 R5：盘中 OFI 五档收集（conditioning 数据收集器，不喂 trade_journal）。
    # 每 3 分钟盘中跑（9:00-14:59，A股盘中 9:30-11:30+13:00-15:00 近似覆盖）。
    # tencent fetch_raw（不封 IP 无限流）→ collect_ofi_for_codes → save_ofi。
    # codes 来自 payload（生产 wiring 取 zt_pool 涨停股另接）。
    if "ofi_collect" not in existing:
        _manager.create_task(ScheduledTask(
            name="ofi_collect",
            description="S176 R5：盘中 OFI 五档收集（conditioning 数据收集器，独立 store 不喂 trade_journal）",
            task_type="ofi_collect",
            cron_expr="*/3 9-14 * * 1-5",  # 每 3 分钟盘中（9:00-14:59）
            payload={},  # codes 生产 wiring 另接（zt_pool 涨停股）
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 ofi_collect 已创建（cron */3 9-14 * * 1-5）")

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

    # S193 R4：盘后扫 watchlist 缺口变盘（突破+衰竭）→ 飞书推送。17:30（kline_refresh 17:15 写当日 bar 后）。
    # 推送阈值 R5 v3 后定性：突破（趋势启动）+衰竭（continuation 正信号，label 疑误实际延续）；持续/普通不推。
    if "scan_watchlist_gaps" not in existing:
        _manager.create_task(ScheduledTask(
            name="scan_watchlist_gaps",
            description="S193 R4：盘后扫 watchlist 缺口变盘（突破+衰竭）→ 飞书推送",
            task_type="scan_watchlist_gaps",
            cron_expr="30 17 * * 0-4",  # 17:30 盘后（kline_refresh 17:15 后，当日 bar 在 cache）
            payload={},
            enabled=True,
            notify_on_success=False,  # gap_scan 自身调 NotificationService.send 推飞书，不再 task notify
        ))
        logger.info("[scheduler] seed 默认任务 scan_watchlist_gaps 已创建（cron 30 17 * * 0-4，S193 R4 缺口变盘推送）")

    # S206：盘中扫 price_alerts 支撑/压力位触及 → 飞书推送（价格预警+新闻+研判，9:00-14:55 每 5 分钟）
    if "scan_price_alerts" not in existing:
        _manager.create_task(ScheduledTask(
            name="scan_price_alerts",
            description="S206：盘中扫 price_alerts 支撑/压力位触及 → 飞书推送（价格预警+相关新闻+AI研判）",
            task_type="scan_price_alerts",
            cron_expr="*/5 9-14 * * 0-4",  # 盘中每 5 分钟（9:00-14:55，周一-周五）
            payload={},
            enabled=True,
            notify_on_success=False,  # 自身调 NotificationService.send 推飞书
        ))
        logger.info("[scheduler] seed 默认任务 scan_price_alerts 已创建（cron */5 9-14 * * 0-4，S206 价格预警）")

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

    # S204 T3：forward_test_records 回补 cron（每日 18:00 retroactive 重派，accumulate 至 ≥60 天解 §44v2 R3 enforce 阻塞）。
    # main() 幂等（删 + 全量重派），随 eastmoney_live 信号日增（daily_data_refresh 日积 1/trading day）增长。
    if "forward_test_backfill" not in existing:
        _manager.create_task(ScheduledTask(
            name="forward_test_backfill",
            description="S204 T3：forward_test_records 回补（retroactive 重派 eastmoney_live 全信号日，幂等；积累至 ≥60 天解 §44v2 R3 enforce days_robust 阻塞）",
            task_type="forward_test_backfill",
            cron_expr="0 18 * * 0-4",  # 18:00（盘后晚于 forward_test_daily 15:45 + t1_settle 15:50，重派含当日）
            payload={"target_days": 60, "use_weather": True},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 forward_test_backfill 已创建（cron 0 18 * * 0-4，S204 T3）")

    # S204 T8: R3 enforce——§44v2 verdict 定期 enforce 降级（盘前 06:00，per-arm days_robust 跨 60 天阈
    # → lift_to_multiplier 升降级 + write_override 刷新 override）。当前 forward_test ~20 天 → skip all
    # underpowered（接线建好待 ≥60 天 bite）。非 reminder（evaluation_backtest 是 reminder+apply_revalidation），
    # T8 是直接 enforce：调 backtest.r3_enforce 算 per-arm distinct exit_date + write_override。
    if "r3_enforce" not in existing:
        _manager.create_task(ScheduledTask(
            name="r3_enforce",
            description="S204 T8：§44v2 R3 enforce——per-arm days_robust 跨 60 天阈 → lift_to_multiplier 升降级 + write_override",
            task_type="r3_enforce",
            cron_expr="0 6 * * 0-4",  # 盘前 06:00（周一-周五，开盘前 enforce）
            payload={"enforce": True, "threshold_days": 60},
            enabled=True,
            notify_on_success=True,
        ))
        logger.info("[scheduler] seed 默认任务 r3_enforce 已创建（cron 0 6 * * 0-4，S204 T8 §44v2 enforce）")

    # S204 T10: early_admission 扫描入池（pre-涨停候选 → candidate_tracking_pool）。
    # auto-source=funnel cache 是**错源**（验证 2026-09-16：funnel final_candidates 是 post-涨停 lbc2-3，
    # early_admission 要 pre-涨停 lbc=1/sector_startup → 0 admits 正确但无用）。
    # 真 auto-source 须建 pre-涨停 scanner（future）——非涨停 funnel。当前 manual trigger 是唯一有效输入。
    # enabled=False：adapter 产出待 pre-涨停 scanner 建好后验证。
    if "early_admission_scan" not in existing:
        _manager.create_task(ScheduledTask(
            name="early_admission_scan",
            description="S204 T10：pre-涨停候选入池（auto-source 错源 funnel 是 post-涨停；须建 pre-涨停 scanner；enabled=False）",
            task_type="early_admission_scan",
            cron_expr="0 9 * * 0-4",  # 盘前 09:00（pre-涨停 scanner 建好后改 enabled=True）
            payload={},
            enabled=False,
        ))
        logger.info("[scheduler] seed 默认任务 early_admission_scan 已创建（enabled=False，S204 T10，auto-source 须 pre-涨停 scanner）")

    # S204 T11: escalation run（tracking→watching auto-promote + promoted→decayed）。
    # enabled=False：maturity 阈值（min_age=3/gene+20%/sector_rank≤5）社区参数未验证→auto-escalate 会让 watching 噪声大。
    # 决策#11：只 candidate→watching 自动。manual trigger 验证阈值后改 enabled=True。
    if "escalation_run" not in existing:
        _manager.create_task(ScheduledTask(
            name="escalation_run",
            description="S204 T11：escalation（tracking→watching auto-promote + decay；enabled=False 阈值未验证）",
            task_type="escalation_run",
            cron_expr="15 9 * * 0-4",  # 盘前 09:15（晚 early_admission 09:00，manual trigger 为主）
            payload={},
            enabled=False,
        ))
        logger.info("[scheduler] seed 默认任务 escalation_run 已创建（enabled=False，S204 T11，maturity 阈值未验证）")

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

    # S218: 关键点位决策通知——D 收盘入场 (15:00) + D+1 开盘出场 (09:30)
    # 使用单一 task_type="keypoint_notify"，payload 区分 trigger_time
    if "keypoint_notify_entry" not in existing:
        _manager.create_task(ScheduledTask(
            name="keypoint_notify_entry",
            description="S218 C3 D 收盘入场通知（15:00：今日收盘买这些，复用 C1 shared core）",
            task_type="keypoint_notify",
            cron_expr="0 15 * * 0-4",  # 15:00 D 收盘
            payload={"notify": True, "trigger": "d_close_entry"},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 keypoint_notify_entry 已创建（cron 0 15 * * 0-4，S218 C3）")

    if "keypoint_notify_exit" not in existing:
        _manager.create_task(ScheduledTask(
            name="keypoint_notify_exit",
            description="S218 C3 D+1 开盘出场通知（09:30：开盘卖这些，复用 C1 shared core）",
            task_type="keypoint_notify",
            cron_expr="30 9 * * 0-4",  # 09:30 D+1 开盘
            payload={"notify": True, "trigger": "d1_open_exit"},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 keypoint_notify_exit 已创建（cron 30 9 * * 0-4，S218 C3）")

    # S218: 每日信号报告——14:50 盘前生成（regime 已知 + zt_history T-1 已知）
    if "daily_report" not in existing:
        _manager.create_task(ScheduledTask(
            name="daily_report",
            description="S218 每日信号报告（consecutive_relay 验证信号 → 结构化 dict + 人话报告）",
            task_type="daily_report",
            cron_expr="50 14 * * 0-4",  # 14:50 盘前（regime 已知 + zt_history T-1 已知）
            payload={"notify": True},  # S218 #5（deep-review 2026-09-18）：notify:False→True 让 daily_report 推 Feishu（信号到用户手机）
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 daily_report 已创建（cron 50 14 * * 0-4，S218）")

    # S222: regime-flip tripwire——09:10 盘前检测（daily_report 14:50 次日、开盘前 9:30）。
    # 连续 3 天 bull 才 alert（hysteresis 防 raw regime 天天翻误报）。
    # consecutive_relay live 验证启动器：bull 回来时通知用户照做 4 周真 P&L。
    if "regime_flip_notify" not in existing:
        _manager.create_task(ScheduledTask(
            name="regime_flip_notify",
            description="S222 regime→bull tripwire（连续 3 天 bull 才 alert，consecutive_relay live 验证启动器）",
            task_type="regime_flip_notify",
            cron_expr="10 9 * * 0-4",  # 09:10 盘前（daily_report 14:50 次日、开盘 9:30 前）
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 regime_flip_notify 已创建（cron 10 9 * * 0-4，S222）")

    # S211 通电收尾（2026-09-17）：regime_cache_fetch——17:20（kline_refresh 17:15 后、
    # trade_journal_daily 17:30 前）。刷 index_ma20_regime.json 防 consecutive_relay
    # regime=None 误保守 ×0.5（升 bull ×1.0 前必须接 cron，否则 bull 被当未知误保守）。
    # fork 发现 index_ma20_regime_fetch.py 原 hardcoded "2026-09-06" → cache 停 09-06，
    # 已改 dynamic today()；本 task 跑脚本刷 cache。
    if "regime_cache_fetch" not in existing:
        _manager.create_task(ScheduledTask(
            name="regime_cache_fetch",
            description="S211 刷 index_ma20_regime.json（baostock sh.000001 + MA20 + regime 标签），consecutive_relay regime-stratified cap 依赖",
            task_type="regime_cache_fetch",
            cron_expr="20 17 * * 0-4",  # 17:20（kline_refresh 17:15 后、trade_journal_daily 17:30 前）
            payload={},
            enabled=True,
            depends_on="kline_refresh",  # S190 R5：晚 kline_refresh 后跑
        ))
        logger.info("[scheduler] seed 默认任务 regime_cache_fetch 已创建（cron 20 17 * * 0-4，depends_on=kline_refresh）")

    # S216 macro_fetch——06:35 盘前（FRED T+1 数据更新后 + A 股盘前 09:30 前）。
    # 调 macro.py fetch_fred_series 取 8 因子最新值写 .vibe-research/macro_snapshot.json。
    # 前端 MacroPanel（/api/macro/snapshot）+ storm_predictor 读 cache。FRED 走 key 不裸调（防封底线）。
    if "macro_fetch" not in existing:
        _manager.create_task(ScheduledTask(
            name="macro_fetch",
            description="S216 FRED 8 因子每日刷新→macro_snapshot.json（VIX/美元/美债/油/铜，前端 MacroPanel+storm 读）",
            task_type="macro_fetch",
            cron_expr="35 6 * * 1-5",  # 06:35 周一-周五盘前（FRED T+1 数据更新后）
            payload={},
            enabled=True,
            # 独立不依赖 kline_refresh（FRED 走自己 API 非本地 cache）
        ))
        logger.info("[scheduler] seed 默认任务 macro_fetch 已创建（cron 35 6 * * 1-5 盘前）")

    # S219 #11 fund_accumulation——16:30 盘后（sti_post_market 15:35 已 snapshot 当日行 +
    # em 终盘 fund/fundamt 稳定）。前向累积 fund/fundamt（em 历史日全空 + hithink/ths 不带 fund，
    # 只能逐日累积），~60 天后 S219 un-defer 条件3（fund≥60）满足。
    # UPDATE-only-fund（不 DELETE+INSERT，不毁 consecutive_relay 生产 lbc——deep-review #8
    # finding 3）；不翻 is_final，不碰 lbc/fbt/source。
    # ⚠️ dispatch 注册须等 #8 done：scheduler/executors/__init__.py _executors dict 加
    # "fund_accumulation": self._execute_fund_accumulation + 方法。未接线前 cron 触发落
    # failed run（未知任务类型）——预期行为，#8 接线后生效。enabled=True + notify_on_failure=
    # False：未接线前 failed run 不刷通知（避免每周一-五 16:30 噪音），#8 接线后自动生效；
    # 后续 em 瞬态断连也静默（daily accumulator 次日自愈，不需打扰用户）。
    if "fund_accumulation" not in existing:
        _manager.create_task(ScheduledTask(
            name="fund_accumulation",
            description="S219 #11 fund 前向累积：每日盘后 UPDATE zt_history.fund/fundamt"
                        "（UPDATE-only 不毁 lbc；~60 天后 S219 un-defer 条件3）",
            task_type="fund_accumulation",
            cron_expr="30 16 * * 0-4",  # 16:30 工作日盘后（Mon-Fri，weekday 0=周一）
            payload={},
            enabled=True,
            notify_on_failure=False,  # dispatch 未接线前 + em 瞬态断连均静默（详见上注释）
            # 独立不依赖 kline_refresh（em 自取数非本地 cache）
        ))
        logger.info(
            "[scheduler] seed 默认任务 fund_accumulation 已创建（cron 30 16 * * 0-4，"
            "dispatch 注册须等 #8 done）"
        )

    # S066 §9 通电（#13 follow-up research note lhb-axis-a-research-2026-09-19，数据 prep 非 spec S220
    # ——freeze 维持）：hot_money_seats_update——每周一 06:00 周更聚合 60 日龙虎榜画像 → seat_profiles.db
    # B 字段（next_day_sell_rate/appearance_count/confidence/source/note）。
    # 原 strategies.hot_money_seats.update_hot_money_seats() 全 backend 零调用，S066 §9 聚合器建了
    # 从未通电，轴 A（席位类型）n=0 不够 §44。本 cron 通电 aggregator，积累后供
    # compute_seat_risk_factor 读画像 + 轴 A §44 复测。~18 次 em_get（防封已守：0.3s 限流 + 熔断 +
    # 代理，S079 AC6）。06:00 周一盘前低负载（macro_fetch 06:35 / r3_enforce 06:00 同窗口不抢盘中）。
    # notify_on_failure=False：em 瞬态断连次周自愈，不刷通知（receipt + last_run_at 由 cron_audit
    # S218 #10 审，不靠通知）。
    if "hot_money_seats_update" not in existing:
        _manager.create_task(ScheduledTask(
            name="hot_money_seats_update",
            description="S066 §9 游资席位周更聚合（60 日龙虎榜 → 画像 → seat_profiles.db B 字段，#13 follow-up 数据 prep）",
            task_type="hot_money_seats_update",
            cron_expr="0 6 * * 1",  # 每周一 06:00 周更（盘前低负载）
            payload={"days": 60},
            enabled=True,
            notify_on_failure=False,  # em 瞬态断连次周自愈，不刷通知（cron_audit 审 receipt+last_run_at）
        ))
        logger.info("[scheduler] seed 默认任务 hot_money_seats_update 已创建（cron 0 6 * * 1，S066 §9 通电）")

    # S218 #12 sector_heat_reverify——每 30 天 06:00 重跑 sector_heat §44（非-arm 补救）。
    # sector_heat（evaluation.py:175，zt≥3 lift=1.359/n=466/days=41/×0.5，note"60 天后复验"）
    # 是全 registry 离 2.0 floor 最近的非 validated 信号（regime probe zt≥5 2.218 最近）。但
    # r3_enforce 只处理 arm-mapped dims（breakout/trend/post_first_board/consecutive_relay via
    # DIM_ARM_MAP），sector_heat 无 arm → skip_non_arm 永远冻 ×0.5。本 cron 补洞：每 30 天重跑
    # tools/sector_heat_validation.compute()（真实 §44 重跑，不臆造），days_robust 跨 60 调
    # write_override：lift≥2→×1.0 / lift<1→×0.1 / 1≤lift<2→skip×0.5（§44v2 规约④ 一致）。
    # 06:00 盘前（同 r3_enforce 时段，enforce 类 cron 集中盘前不抢盘中）。非 event edge
    # （lift!=None 无 regime_caps）→ lift_to_multiplier 正常路径（不像 consecutive_relay 走 weekly_review）。
    if "sector_heat_reverify" not in existing:
        _manager.create_task(ScheduledTask(
            name="sector_heat_reverify",
            description="S218 #12：sector_heat 非-arm 重验（每 30 天重跑 §44，days≥60 → write_override 升降级）",
            task_type="sector_heat_reverify",
            cron_expr="0 6 */30 * *",  # 每 30 天 06:00（盘前，同 r3_enforce 时段）
            payload={"threshold_days": 60, "heat_def": "zt>=3"},  # zt>=3 = registry canonical arm
            enabled=True,
            notify_on_success=True,
        ))
        logger.info("[scheduler] seed 默认任务 sector_heat_reverify 已创建（cron 0 6 */30 * *，S218 #12）")

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

    # S185 路径 A：Turso 云同步（可选——VR_TURSO_URL 未设时 sync_all 返纯本地跳过，零降级）
    if "turso_sync" not in existing:
        _manager.create_task(ScheduledTask(
            name="turso_sync",
            description="S185 Turso 云同步（读本地 SQLite→HTTP POST Turso REST，VR_TURSO_URL 未设跳过）",
            task_type="turso_sync",
            cron_expr="0 10 * * 0",  # 周日 10:00（盘后周末同步全周数据）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 turso_sync 已创建（cron 0 10 * * 0，S185 可选）")

    # S188 RB-2：healthchecks.io 外部心跳（可选——VR_HEALTHCHECKS_URL 未设时跳过，零降级）
    # 防 CronScheduler 进程死→全 cron 静默停；ping 停→healthchecks.io 邮件告警
    if "healthcheck_ping" not in existing:
        _manager.create_task(ScheduledTask(
            name="healthcheck_ping",
            description="S188 RB-2 外部心跳（每小时 ping healthchecks.io，进程死→ping 停→邮件告警，VR_HEALTHCHECKS_URL 未设跳过）",
            task_type="healthcheck_ping",
            cron_expr="0 * * * *",  # 每小时整点
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 healthcheck_ping 已创建（cron 0 * * * *，S188 RB-2 可选）")

    # S188 RB-9：每周全局优化头脑风暴提醒（每周一 9:00，飞书+待办标记，用户手动触发 workflow）
    if "weekly_brainstorm_remind" not in existing:
        _manager.create_task(ScheduledTask(
            name="weekly_brainstorm_remind",
            description="S188 RB-9 每周头脑风暴提醒（周一 9:00 飞书通知+待办标记，backend 跑不了 workflow 用户手动触发）",
            task_type="weekly_brainstorm_remind",
            cron_expr="0 9 * * 1",  # 每周一 9:00
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 weekly_brainstorm_remind 已创建（cron 0 9 * * 1，S188 RB-9）")

    # S191 RB-3：每日盘后全量拉取沉淀 datalake（stoke + mootdx 分笔，晚 journal 17:30）
    if "daily_full_pull" not in existing:
        _manager.create_task(ScheduledTask(
            name="daily_full_pull",
            description="S191 RB-3 每日全量拉取沉淀 datalake（stoke 研报/新闻/涨停归因 + mootdx 分笔→datalake/，供 replay.py 回放）",
            task_type="daily_full_pull",
            cron_expr="35 17 * * 0-4",  # 17:35 晚 journal 17:30
            payload={},
            enabled=True,
            depends_on="trade_journal_daily",  # S190 R5 硬门控
        ))
        logger.info("[scheduler] seed 默认任务 daily_full_pull 已创建（cron 35 17 * * 0-4，depends_on=trade_journal_daily）")

    # S218 C5: 周度汇总复盘——每周日 18:00 盘后（weekly_review）
    if "weekly_review" not in existing:
        _manager.create_task(ScheduledTask(
            name="weekly_review",
            description="S218 C5 周度汇总复盘（consecutive_relay paper P&L + cap gate + process-theater 自检）",
            task_type="weekly_review",
            cron_expr="0 18 * * 0",  # 每周日 18:00
            payload={"notify": True},  # S218 #5（deep-review 2026-09-18）：notify:False→True 让 weekly_review 推 Feishu
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 weekly_review 已创建（cron 0 18 * * 0，S218 C5）")

    # S218 #10 cron-fire audit——每晚 20:00 扫 cron_fire.log receipt + scheduled_tasks
    # last_run_at 数 missed delivery cron（reality-check verdict NEEDS WORK：delivery cron
    # wired 但 last_run_at=null 从未 fire；本 audit 把 "wired" 变可观测：receipt + last_run_at
    # 双正证，皆空=missed）。周日也跑（核一周：weekly_review 周日 18:00 是否真 fire）。
    # cron 0-6 = 周一至周日（cron_match 用 weekday()，0=周一..6=周日，见 _ensure_seed_tasks docstring）。
    if "cron_audit" not in existing:
        _manager.create_task(ScheduledTask(
            name="cron_audit",
            description="S218 #10 cron-fire audit（扫 cron_fire.log receipt + last_run_at 数 missed delivery cron，每晚 20:00）",
            task_type="cron_audit",
            cron_expr="0 20 * * 0-6",  # 每晚 20:00（0-6=周一至周日，周日也跑核一周）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 cron_audit 已创建（cron 0 20 * * 0-6，S218 #10）")
