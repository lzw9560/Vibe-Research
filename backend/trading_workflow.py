"""
打板工作流编排入口。

职责：
1. 根据当前时间自动判断所处阶段
2. 调度对应阶段的工作流
3. 提供统一的工作流状态查询
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pre_market_workflow import PreMarketWorkflow, PreMarketReport
from factors import registry as factor_registry
from factors.base import FactorResult
from realtime_workflow import RealtimeWorkflow
from post_market_workflow import PostMarketWorkflow, PostMarketReport
from workflow_state_machine import WorkflowStatus
from vr_paths import last_trading_date_str, is_trading_day

logger = logging.getLogger(__name__)

# A 股按北京时间运作；阶段判定须用北京时区，否则 Docker/云（非北京时区）会报错阶段。
_BEIJING = timezone(timedelta(hours=8))


class TradingWorkflow:
    """打板工作流编排器。"""

    def __init__(self, date: str | None = None):
        self.date = date or last_trading_date_str()
        self.pre_market = PreMarketWorkflow(self.date)
        self.intraday = RealtimeWorkflow()
        self.post_market = PostMarketWorkflow(self.date)

    def get_current_stage(self, now: datetime | None = None) -> dict[str, Any]:
        """根据北京时间判断所处阶段。now 可注入供测试。

        边界（A 股北京时间）：08:00 盘前 → 09:30 开盘 → 15:00 收盘 → 22:00 盘后。
        09:00-09:30 竞价归盘前（原实现误归 intraday 上午盘）。
        """
        now = now or datetime.now(_BEIJING)
        hour = now.hour
        minute = now.minute
        time_str = f"{hour:02d}:{minute:02d}"

        # 非交易日（周末/法定节假日）整日不随时间推进阶段——固定"非交易日"
        # （is_trading_day 含节假日表；原实现只看时分，周六 10:00 误显 intraday）
        if not is_trading_day(now.date()):
            return {
                "stage": "pre-market",
                "current_time": time_str,
                "market_status": "非交易日",
                "next_stage": "pre-market",
                "next_stage_time": "下一交易日 08:00",
            }

        if hour >= 8 and (hour < 9 or (hour == 9 and minute < 30)):
            # 08:00-09:30 盘前（含 09:15-09:30 竞价与竞价确认）
            stage = "pre-market"
            market_status = "盘前准备中"
            next_stage = "intraday"
            next_stage_time = "09:30"
        elif hour >= 9 and hour < 15:
            stage = "intraday"
            market_status = "上午盘" if hour < 12 else "下午盘"
            next_stage = "post-market"
            next_stage_time = "15:00"
        elif hour >= 15 and hour < 22:
            stage = "post-market"
            market_status = "盘后复盘"
            next_stage = "pre-market"
            next_stage_time = "次日 08:00"
        else:
            stage = "pre-market"
            market_status = "非交易时段"
            next_stage = "intraday"
            next_stage_time = "09:30"

        return {
            "stage": stage,
            "current_time": time_str,
            "market_status": market_status,
            "next_stage": next_stage,
            "next_stage_time": next_stage_time,
        }

    async def run_pre_market(self) -> PreMarketReport:
        """执行盘前工作流。"""
        logger.info("开始执行盘前工作流: date=%s", self.date)
        report = await self.pre_market.run()
        logger.info("盘前工作流完成: candidates=%d", len(report.candidates))
        return report

    async def run_pre_market_factors(self) -> list[FactorResult]:
        """执行盘前工作流（因子接口版，S023 D2）：遍历因子注册表。"""
        logger.info("开始执行盘前因子采集: date=%s", self.date)
        factor_registry.register_default_factors()
        results = factor_registry.fetch_all(self.date)
        logger.info("盘前因子采集完成: %d 个因子", len(results))
        return results

    async def run_intraday(self) -> dict[str, Any]:
        """执行盘中工作流。"""
        logger.info("开始执行盘中工作流")
        status = await self.intraday.get_market_status()
        return {
            "stage": "intraday",
            "market_status": status,
            "signals": [s.__dict__ for s in self.intraday.signals],
            "alerts": [a.__dict__ for a in self.intraday.alerts],
            "adjustments": [a.__dict__ for a in self.intraday.adjustments],
        }

    async def run_post_market(self) -> PostMarketReport:
        """执行盘后工作流。"""
        logger.info("开始执行盘后工作流: date=%s", self.date)
        report = await self.post_market.run()
        logger.info("盘后工作流完成: win_rate=%.1f%%", report.win_rate)
        return report

    async def run(self, stage: str | None = None) -> dict[str, Any]:
        """根据阶段执行对应工作流。"""
        if stage is None:
            stage = self.get_current_stage()["stage"]

        if stage == "pre-market":
            report = await self.run_pre_market()
            return {"stage": "pre-market", "data": report.__dict__}
        elif stage == "intraday":
            result = await self.run_intraday()
            return {"stage": "intraday", "data": result}
        elif stage == "post-market":
            report = await self.run_post_market()
            return {"stage": "post-market", "data": report.__dict__}
        else:
            raise ValueError(f"未知阶段: {stage}")
