# -*- coding: utf-8 -*-
"""S079 龙虎榜席位三分级风控（R1-R5）。

spec §3.1 + plan §2 R1-R5 设计：
- R1：复用 seat_engine.compute_consensus_signal 取 T-1 龙虎榜买卖席位 + 机构占比
- R2：黑名单硬剔除 —— 买入前五席位中≥1 个黑名单席位且占比>15% → 硬剔除 + 标【拒绝介入】
  - R2.2 子串模糊匹配（应对席位写法差异）
- R3：独食独大软标记 —— 买一占比≥55%（前五）或≥10%（全天）→ 标 risk_flags + 仓位砍半
- R4：散户霸榜软标记 —— 买入前五中拉萨席位≥3 个 → 标 risk_flags + 置信度降权
- R5：数据缺失处置 —— 龙虎榜"未取得"时硬剔除不可执行 + 警示 + 用户决策

复用：
- seat_engine.compute_consensus_signal(trade_date, stock_code) 取 buy_seats + total_buy_amount
- hot_money_seats.SeatRiskFactor 的 score_modifier 先例（仓位砍半）

不新增：
- akshare 通道（复用既有 seat_engine datacenter 通道）
- 新数据源

合规（CLAUDE.md §1.1 弱合规，2026-07-30）：
- 输出含【拒绝介入】/独食独大/散户霸榜等量化方向参数，挂轻量风险提醒
- 历史统计特征，市场有风险
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from strategies.position_advisor import PositionSuggestion
from seat_engine.service import SeatEngine

_logger = logging.getLogger("vibe-research")

# config 路径（repo 根 config/seat_blacklist.yaml）
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "seat_blacklist.yaml"

# 轻量风险提醒（CLAUDE.md §1.1 弱合规）
RISK_DISCLAIMER = "历史统计特征，市场有风险"


def load_blacklist_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """加载 seat_blacklist.yaml 配置。

    Args:
        config_path: 配置文件路径，默认 config/seat_blacklist.yaml

    Returns:
        解析后的配置 dict。文件缺失时返回默认配置（不臆造，标探索性）。
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        _logger.warning("seat_blacklist.yaml 未找到 path=%s，用默认配置", path)
        return _default_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        # 补默认值（防止 yaml 字段缺失）
        defaults = _default_config()
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        if isinstance(cfg.get("threshold"), dict):
            for k, v in defaults["threshold"].items():
                cfg["threshold"].setdefault(k, v)
        return cfg
    except Exception as e:
        _logger.warning("seat_blacklist.yaml 解析失败 err=%s，用默认配置", e)
        return _default_config()


def _default_config() -> dict[str, Any]:
    """默认配置（探索性，PRD §3 拍定，进 config 可配）。"""
    return {
        "blacklist": ["拉萨团结路", "拉萨东环路", "拉萨金融路", "东方财富拉萨"],
        "retail_seats": ["拉萨团结路", "拉萨东环路", "拉萨金融路", "东方财富拉萨"],
        "threshold": {
            "blacklist_ratio": 0.15,
            "buy_one_ratio": 0.55,
            "buy_one_ratio_daily": 0.10,
            "retail_seat_count": 3,
        },
        "monopoly_position_modifier": 0.5,
        "retail_confidence_modifier": 0.8,
    }


# ===========================================================================
# R2.2 子串模糊匹配工具
# ===========================================================================

def match_seat_substring(blacklist_name: str, seat_name: str) -> bool:
    """子串模糊匹配（R2.2，应对席位写法差异）。

    应对"中国国际金融上海分公司" vs "中金公司上海分公司"等写法差异。
    双向子串包含：bl_name in seat_name or seat_name in bl_name

    Args:
        blacklist_name: 黑名单名单中的席位名（可能是简称/子串）
        seat_name: 龙虎榜 buy_seats 中的实际席位名

    Returns:
        True 如果匹配（双向子串包含）
    """
    if not blacklist_name or not seat_name:
        return False
    # 双向子串包含
    return blacklist_name in seat_name or seat_name in blacklist_name


# ===========================================================================
# DragonTigerSeatFilter 主类
# ===========================================================================

class DragonTigerSeatFilter:
    """龙虎榜席位三分级风控（R1-R5）。

    串在 PositionAdvisor.advise_batch 输出之后：
        suggestions → DragonTigerSeatFilter.filter(...) → filtered + risk_flags
    """

    def __init__(
        self,
        seat_engine: SeatEngine | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        """
        Args:
            seat_engine: SeatEngine 实例（复用，不新建）。None 时用 get_engine() 单例
            config_path: seat_blacklist.yaml 路径，默认 config/seat_blacklist.yaml
        """
        # 复用既有 seat_engine 实例（不新建）
        self._seat_engine = seat_engine
        self._config = load_blacklist_config(config_path)

    @property
    def seat_engine(self) -> SeatEngine:
        """惰性获取 seat_engine（避免 import 时初始化）。"""
        if self._seat_engine is None:
            from seat_engine.service import get_engine
            self._seat_engine = get_engine()
        return self._seat_engine

    # -------------------------------------------------------------------
    # R1 龙虎榜取数
    # -------------------------------------------------------------------

    def fetch_consensus(
        self, stock_code: str, trade_date: str
    ) -> dict[str, Any] | None:
        """R1 龙虎榜取数：复用 seat_engine.compute_consensus_signal。

        Args:
            stock_code: 股票代码
            trade_date: T-1 交易日（龙虎榜为盘后数据，T+1 盘前使用）

        Returns:
            compute_consensus_signal 返回的 dict（含 details.buy_seats 等），
            取数失败返回 None（交由 R5 数据缺失处置）。
        """
        try:
            return self.seat_engine.compute_consensus_signal(trade_date, stock_code)
        except Exception as e:
            _logger.warning(
                "fetch_consensus 取数失败 code=%s date=%s err=%s",
                stock_code, trade_date, e,
            )
            return None

    # -------------------------------------------------------------------
    # R2 黑名单硬剔除
    # -------------------------------------------------------------------

    def _calc_blacklist_ratio(
        self, buy_seats: list[dict], total_buy_amount: float
    ) -> tuple[float, list[str]]:
        """计算黑名单席位占比（R2）。

        Args:
            buy_seats: compute_consensus_signal 返回的 details.buy_seats
            total_buy_amount: details.total_buy_amount

        Returns:
            (blacklist_ratio, matched_seat_names)
            - blacklist_ratio: 匹配席位的 buy_amt 之和 / total_buy_amount
            - matched_seat_names: 匹配的席位名列表（供 risk_flags 展示）
        """
        if not buy_seats or total_buy_amount <= 0:
            return 0.0, []

        blacklist = self._config.get("blacklist", [])
        matched_amt = 0.0
        matched_names: list[str] = []

        for seat in buy_seats:
            seat_name = seat.get("name", "")
            seat_buy_amt = seat.get("buy_amt", 0)
            for bl_name in blacklist:
                if match_seat_substring(bl_name, seat_name):
                    matched_amt += seat_buy_amt
                    if seat_name not in matched_names:
                        matched_names.append(seat_name)
                    break  # 一个席位匹配一个黑名单即可，避免重复累加

        ratio = round(matched_amt / total_buy_amount, 4)
        return ratio, matched_names

    def _filter_by_blacklist(
        self,
        suggestion: PositionSuggestion,
        consensus: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """R2 黑名单硬剔除判定（单个标的）。

        Returns:
            (should_reject, risk_flags)
            - should_reject: True 表示硬剔除（占比>15%）
            - risk_flags: 风控标记列表
        """
        details = consensus.get("details") or {}
        buy_seats = details.get("buy_seats") or []
        total_buy_amount = details.get("total_buy_amount") or 0

        ratio, matched_names = self._calc_blacklist_ratio(buy_seats, total_buy_amount)
        threshold = self._config.get("threshold", {}).get("blacklist_ratio", 0.15)

        if ratio > threshold:
            flag = f"【拒绝介入】黑名单占比 {ratio:.1%}（{', '.join(matched_names)}）"
            return True, [flag]
        return False, []

    # -------------------------------------------------------------------
    # R3 独食独大软标记
    # -------------------------------------------------------------------

    def _check_monopoly(
        self,
        consensus: dict[str, Any],
        daily_amount: float | None = None,
    ) -> list[str]:
        """R3 独食独大软标记。

        判定（spec R3）：
        - buy_one_ratio >= 0.55（前五买入额占比）→ 标"独食独大"
        - 或 buy_seats[0].buy_amt / daily_amount >= 0.10（全天成交额占比）→ 标"独食独大"

        Args:
            consensus: compute_consensus_signal 返回的 dict（含 details.buy_one_ratio）
            daily_amount: 全天成交额（万元）。None 时跳过全天占比判定。

        Returns:
            risk_flags 列表（空列表 = 无标记）
        """
        details = consensus.get("details") or {}
        buy_one_ratio = details.get("buy_one_ratio") or 0
        buy_seats = details.get("buy_seats") or []
        threshold_cfg = self._config.get("threshold", {})

        # 判定 1：买一占比 ≥ 55%（前五买入额）
        buy_one_threshold = threshold_cfg.get("buy_one_ratio", 0.55)
        if buy_one_ratio >= buy_one_threshold:
            return ["独食独大"]

        # 判定 2：买一占全天成交额 ≥ 10%
        if daily_amount and daily_amount > 0 and buy_seats:
            buy_one_amt = buy_seats[0].get("buy_amt", 0)
            daily_threshold = threshold_cfg.get("buy_one_ratio_daily", 0.10)
            if (buy_one_amt / daily_amount) >= daily_threshold:
                return ["独食独大"]

        return []

    # -------------------------------------------------------------------
    # R4 散户霸榜软标记
    # -------------------------------------------------------------------

    def _check_retail_dominance(
        self, buy_seats: list[dict]
    ) -> list[str]:
        """R4 散户霸榜软标记。

        判定（spec R4）：
        - buy_seats 前五中，匹配 retail_seats_config（拉萨团结路/东环路等）的席位 >= 3 个
          → 标"散户霸榜"

        Args:
            buy_seats: compute_consensus_signal 返回的 details.buy_seats

        Returns:
            risk_flags 列表（空列表 = 无标记）
        """
        if not buy_seats:
            return []

        retail_seats_cfg = self._config.get("retail_seats", [])
        threshold_cfg = self._config.get("threshold", {})
        retail_threshold = threshold_cfg.get("retail_seat_count", 3)

        # 前 5 席位计数（buy_seats 已按 datacenter 返回顺序，通常前五）
        top_seats = buy_seats[:5]
        matched_count = 0
        for seat in top_seats:
            seat_name = seat.get("name", "")
            for retail_name in retail_seats_cfg:
                if match_seat_substring(retail_name, seat_name):
                    matched_count += 1
                    break  # 一个席位匹配一次

        if matched_count >= retail_threshold:
            return ["散户霸榜"]
        return []

    # -------------------------------------------------------------------
    # R5 数据缺失处置
    # -------------------------------------------------------------------

    def _handle_data_missing(
        self, suggestion: PositionSuggestion
    ) -> tuple[bool, list[str], str | None]:
        """R5 数据缺失处置（龙虎榜"未取得"时）。

        spec R5/AC4：
        - 硬剔除不可执行（不默认放行 = 风控绕过）
        - 不剔除（不默认拒绝 = 数据抖动误杀）
        - 标"席位风控数据未取得，硬剔除不可执行" + 显著警示
        - 由用户决策

        Returns:
            (should_reject, risk_flags, data_missing_flag)
            - should_reject: False（不剔除）
            - risk_flags: []（无硬剔除标记）
            - data_missing_flag: 警示字符串
        """
        flag = "席位风控数据未取得，硬剔除不可执行"
        return False, [], flag

    # -------------------------------------------------------------------
    # R3 仓位砍半 + R4 置信度降权（软标记后处理）
    # -------------------------------------------------------------------

    def _apply_soft_flags(
        self,
        suggestion: PositionSuggestion,
        seat_risk_flags: list[str],
    ) -> None:
        """R3/R4 软标记后处理：仓位砍半 + 置信度降权（原地修改）。

        Args:
            suggestion: PositionSuggestion（原地修改 suggested_pct / confidence）
            seat_risk_flags: 该标的的龙虎榜风控标记列表
        """
        # R3 独食独大：仓位砍半（复用 hot_money_seats.SeatRiskFactor score_modifier 先例）
        if "独食独大" in seat_risk_flags:
            modifier = self._config.get("monopoly_position_modifier", 0.5)
            suggestion.suggested_pct = round(suggestion.suggested_pct * modifier, 4)

        # R4 散户霸榜：战法匹配置信度降权
        if "散户霸榜" in seat_risk_flags:
            modifier = self._config.get("retail_confidence_modifier", 0.8)
            # confidence 是字符串（high/medium/low），降权一档
            confidence_order = {"high": 2, "medium": 1, "low": 0}
            cur_level = confidence_order.get(suggestion.confidence, 1)
            new_level = max(0, int(cur_level * modifier))
            reverse = {v: k for k, v in confidence_order.items()}
            suggestion.confidence = reverse.get(new_level, "low")

    # -------------------------------------------------------------------
    # R1-R5 串入口
    # -------------------------------------------------------------------

    def filter(
        self,
        suggestions: list[PositionSuggestion],
        trade_date: str,
        daily_amounts: dict[str, float] | None = None,
    ) -> tuple[
        list[PositionSuggestion],
        dict[str, list[str]],
        dict[str, str],
    ]:
        """R1-R5 龙虎榜席位三分级风控主入口（A12 串入口）。

        Args:
            suggestions: PositionSuggestion 列表（advise_batch 输出）
            trade_date: T-1 交易日（龙虎榜盘后数据）
            daily_amounts: {stock_code: 全天成交额（万元）}，供 R3 独食独大全天占比判定。
                          None 时跳过全天占比判定。

        Returns:
            (filtered_suggestions, seat_risk_flags, data_missing_flags)
            - filtered_suggestions: 硬剔除后的 PositionSuggestion 列表
              （R2 黑名单硬剔除的标的从列表移除；R5 数据缺失的标的保留）
            - seat_risk_flags: {stock_code: [风控标记]}（含【拒绝介入】/独食独大/散户霸榜）
            - data_missing_flags: {stock_code: 警示字符串}（R5 数据缺失标记）
        """
        daily_amounts = daily_amounts or {}
        filtered: list[PositionSuggestion] = []
        seat_risk_flags: dict[str, list[str]] = {}
        data_missing_flags: dict[str, str] = {}

        for sug in suggestions:
            # R1 龙虎榜取数
            consensus = self.fetch_consensus(sug.code, trade_date)

            # R5 数据缺失处置（龙虎榜"未取得"时）
            if consensus is None or consensus.get("signal") in (None, "未取得"):
                should_reject, flags, missing_flag = self._handle_data_missing(sug)
                filtered.append(sug)  # 不剔除，保留由用户决策
                if missing_flag:
                    data_missing_flags[sug.code] = missing_flag
                if flags:
                    seat_risk_flags[sug.code] = flags
                continue

            # R2 黑名单硬剔除
            should_reject, reject_flags = self._filter_by_blacklist(sug, consensus)
            if should_reject:
                seat_risk_flags[sug.code] = reject_flags
                # 硬剔除：从 filtered 移除（不 append）
                continue

            # R3 独食独大软标记
            daily_amt = daily_amounts.get(sug.code)
            monopoly_flags = self._check_monopoly(consensus, daily_amt)

            # R4 散户霸榜软标记
            details = consensus.get("details") or {}
            buy_seats = details.get("buy_seats") or []
            retail_flags = self._check_retail_dominance(buy_seats)

            # 合并软标记
            soft_flags = monopoly_flags + retail_flags
            if soft_flags:
                seat_risk_flags[sug.code] = soft_flags
                # R3 仓位砍半 + R4 置信度降权
                self._apply_soft_flags(sug, soft_flags)

            filtered.append(sug)

        return filtered, seat_risk_flags, data_missing_flags
