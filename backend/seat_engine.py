# -*- coding: utf-8 -*-
"""龙虎榜席位智能引擎（Seat Engine）。

定位：客观数据展示，非行动建议。席位标签基于历史统计特征，不代表对未来行为的预测。
数据源：东财数据中心龙虎榜三大报表（RPT_DAILYBILLBOARD_DETAILSNEW / RPT_BILLBOARD_DAILYDETAILSBUY / RPT_BILLBOARD_DAILYDETAILSSELL）。
缓存：TTL 12 小时日频预计算 + 内存缓存 + JSON 文件持久化。
"""

from __future__ import annotations

import json
import logging
import os
import time
import threading as _threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import astock

BEIJING_TZ = datetime.now().astimezone().tzinfo

# ===========================================================================
# Configuration (env overrides)
# ===========================================================================

SEAT_LOOKBACK_DAYS = int(os.getenv("SEAT_LOOKBACK_DAYS", "180"))
SEAT_QUANT_THRESHOLD = int(os.getenv("SEAT_QUANT_THRESHOLD", "30"))
SEAT_ACTIVE_MIN = int(os.getenv("SEAT_ACTIVE_MIN", "10"))
SEAT_LARGE_POS = float(os.getenv("SEAT_LARGE_POS", "10000"))   # 万元
SEAT_SMALL_POS = float(os.getenv("SEAT_SMALL_POS", "3000"))    # 万元

# ===========================================================================
# Cache & Persistence
# ===========================================================================

_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时
_LOCK = _threading.Lock()

_PROFILES_PATH = Path(__file__).parent / "seat_profiles.json"


def _load_profiles_from_disk() -> dict:
    """Load persisted seat profiles from JSON file."""
    if _PROFILES_PATH.exists():
        try:
            with open(_PROFILES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_profiles_to_disk(profiles: dict) -> None:
    """Persist seat profiles to JSON file."""
    try:
        with open(_PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
    except IOError:
        pass


# ===========================================================================
# Disclaimer
# ===========================================================================

SEAT_DISCLAIMER = (
    "免责声明：席位标签基于龙虎榜历史数据统计特征，不代表对未来行为的预测，"
    "不构成投资建议。股市有风险，投资需谨慎。"
)

# ===========================================================================
# 1. Data Structures (Pydantic Models)
# ===========================================================================


class SeatProfile(BaseModel):
    """单个席位的统计画像。"""

    seat_name: str
    total_appearances: int = 0
    total_buy_amt: float = 0.0          # 万元
    total_sell_amt: float = 0.0         # 万元
    net_amt: float = 0.0                # 万元
    avg_buy_amt: float = 0.0            # 万元
    avg_sell_amt: float = 0.0           # 万元
    stock_cooldown: int = 0             # 交易过多少只不同的股票
    last_seen: str = ""                 # YYYY-MM-DD
    seat_type: str = "inactive"         # 分类标签

    # 内部累计字段（构建 profile 时用，不暴露到外部 API）
    _buy_appearances: int = 0
    _sell_appearances: int = 0
    _stocks_traded: set = set()
    _stock_buy_sell_pairs: set = set()  # (stock, seat) 同时出现在买卖的记录


class ConsensusSignal(BaseModel):
    """共识/分歧信号。"""

    signal: str | None           # "多资金共识" / "分歧信号" / "机构主导" / "游资主导" / None
    details: dict[str, Any] = {}
    date: str = ""
    stock_code: str = ""
    disclaimer: str = SEAT_DISCLAIMER


# ===========================================================================
# 2. Seat Engine Core
# ===========================================================================


class SeatEngine:
    """
    龙虎榜席位智能引擎。

    功能：
    - 从东财数据中心批量拉取龙虎榜数据，构建席位画像
    - 基于历史统计特征对席位进行分类（机构/量化/游资/跟风/inactive）
    - 计算多席位共识/分歧信号
    - 支持每日增量更新和历史回填
    """

    def __init__(self):
        """初始化：从磁盘加载已有 profiles，或冷启动空字典。"""
        self._profiles: dict[str, SeatProfile] = {}
        self._lock = _threading.Lock()

        # 加载持久化的 profiles
        raw = _load_profiles_from_disk()
        if raw:
            for name, data in raw.items():
                try:
                    profile = SeatProfile(**data)
                    self._profiles[name] = profile
                except Exception:
                    continue

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pull_records(self, report_name: str, columns: str,
                      filter_str: str, page_size: int = 5000,
                      sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
        """Wrapper around astock.eastmoney_datacenter with pagination."""
        all_data: list[dict] = []
        page = 1
        while True:
            data = astock.eastmoney_datacenter(
                report_name=report_name,
                columns=columns,
                filter_str=filter_str,
                page_size=page_size,
                sort_columns=sort_columns,
                sort_types=sort_types,
            )
            if not data:
                break
            all_data.extend(data)
            if len(data) < page_size:
                break
            page += 1
            # Safety: prevent infinite loops
            if page > 20:
                break
        return all_data

    def _classify_seat_type(self, profile: SeatProfile) -> str:
        """
        根据统计特征对席位进行分类。

        分类规则（按优先级从高到低）：
        1. "机构专用" — 固定分类（OPERATEDEPT_CODE == "0"）
        2. "量化席位" — 高频出现(>threshold) AND 同时在买卖两侧出现 AND 中小仓位
        3. "活跃游资" — 中频(10-30) AND 净买入倾向 AND 大仓位
        4. "跟风席位" — 频繁出现但仓位小
        5. "inactive" — 默认低活跃度
        """
        if profile.total_appearances == 0:
            return "inactive"

        # 机构专用是东财政位编码决定的，不在这里判断（在 build 时单独处理）
        if profile.seat_name == "机构专用":
            return "机构专用"

        # 量化席位判定
        is_quant = (
            profile.total_appearances >= SEAT_QUANT_THRESHOLD
            and len(profile._stock_buy_sell_pairs) > 0
            and profile.avg_buy_amt < SEAT_LARGE_POS
        )
        if is_quant:
            return "量化席位"

        # 活跃游资判定
        is_active_youzi = (
            SEAT_ACTIVE_MIN <= profile.total_appearances < SEAT_QUANT_THRESHOLD
            and profile.net_amt > 0
            and profile.avg_buy_amt >= SEAT_LARGE_POS
        )
        if is_active_youzi:
            return "活跃游资"

        # 跟风席位判定
        is_follower = (
            profile.total_appearances >= SEAT_ACTIVE_MIN
            and profile.avg_buy_amt < SEAT_SMALL_POS
        )
        if is_follower:
            return "跟风席位"

        # 低活跃度默认
        return "inactive"

    def _merge_record_into_profile(self, record: dict, profile: SeatProfile,
                                    side: str) -> None:
        """将一条龙虎榜明细记录合并到席位画像中。"""
        buy_amt = astock._numf(record.get("BUY", 0)) or 0
        sell_amt = astock._numf(record.get("SELL", 0)) or 0
        net_amt = astock._numf(record.get("NET", 0)) or 0
        stock_code = str(record.get("SECURITY_CODE", ""))
        trade_date = str(record.get("TRADE_DATE", ""))[:10]

        # 更新统计
        profile.total_appearances += 1
        profile.total_buy_amt += buy_amt
        profile.total_sell_amt += sell_amt
        profile.net_amt += net_amt

        if side == "buy":
            profile._buy_appearances += 1
        else:
            profile._sell_appearances += 1

        # 股票去重
        profile._stocks_traded.add(stock_code)

        # 记录同时出现在买卖的股票对（用于量化判定）
        if buy_amt > 0 and sell_amt > 0:
            profile._stock_buy_sell_pairs.add((stock_code, profile.seat_name))

        # 更新最后出现日期
        if trade_date and (not profile.last_seen or trade_date > profile.last_seen):
            profile.last_seen = trade_date

    # ------------------------------------------------------------------
    # Public API: build_seat_profiles
    # ------------------------------------------------------------------

    def build_seat_profiles(self, lookback_days: int | None = None) -> dict[str, dict]:
        """
        冷启动：批量拉取历史龙虎榜数据，构建所有席位画像。

        Args:
            lookback_days: 回溯天数，默认 SEAT_LOOKBACK_DAYS (180)

        Returns:
            {seat_name: profile_dict} 所有席位的统计画像
        """
        if lookback_days is None:
            lookback_days = SEAT_LOOKBACK_DAYS

        end_date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        start_dt = datetime.now(BEIJING_TZ) - timedelta(days=lookback_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        filter_str = f'(TRADE_DATE>=\'{start_date}\')(TRADE_DATE<=\'{end_date}\')'

        # 拉取买入席位明细
        buy_data = self._pull_records(
            report_name="RPT_BILLBOARD_DAILYDETAILSBUY",
            columns="ALL",
            filter_str=filter_str,
        )

        # 拉取卖出席位明细
        sell_data = self._pull_records(
            report_name="RPT_BILLBOARD_DAILYDETAILSSELL",
            columns="ALL",
            filter_str=filter_str,
        )

        # 构建 seat_name → profile 映射
        profiles: dict[str, SeatProfile] = {}

        for record in buy_data:
            seat_name = str(record.get("OPERATEDEPT_NAME", "") or "")
            if not seat_name:
                continue
            if seat_name not in profiles:
                profiles[seat_name] = SeatProfile(seat_name=seat_name)
            self._merge_record_into_profile(record, profiles[seat_name], side="buy")

        for record in sell_data:
            seat_name = str(record.get("OPERATEDEPT_NAME", "") or "")
            if not seat_name:
                continue
            if seat_name not in profiles:
                profiles[seat_name] = SeatProfile(seat_name=seat_name)
            self._merge_record_into_profile(record, profiles[seat_name], side="sell")

        # 计算均值 & 分类
        result: dict[str, dict] = {}
        for seat_name, profile in profiles.items():
            # 计算平均值
            buy_count = profile._buy_appearances
            sell_count = profile._sell_appearances
            total = profile.total_appearances

            profile.avg_buy_amt = round(profile.total_buy_amt / max(buy_count, 1), 1)
            profile.avg_sell_amt = round(profile.total_sell_amt / max(sell_count, 1), 1)
            profile.stock_cooldown = len(profile._stocks_traded)

            # 分类
            profile.seat_type = self._classify_seat_type(profile)

            # 清理内部字段后存入结果
            profile_dict = profile.model_dump()
            profile_dict.pop("_buy_appearances", None)
            profile_dict.pop("_sell_appearances", None)
            profile_dict.pop("_stocks_traded", None)
            profile_dict.pop("_stock_buy_sell_pairs", None)
            result[seat_name] = profile_dict

        # 更新内存缓存
        with self._lock:
            self._profiles = profiles
            # 持久化到磁盘
            save_dict = {}
            for name, p in profiles.items():
                pd = p.model_dump()
                pd.pop("_buy_appearances", None)
                pd.pop("_sell_appearances", None)
                pd.pop("_stocks_traded", None)
                pd.pop("_stock_buy_sell_pairs", None)
                save_dict[name] = pd
            _save_profiles_to_disk(save_dict)

        return result

    # ------------------------------------------------------------------
    # Public API: get_seat_profile
    # ------------------------------------------------------------------

    def get_seat_profile(self, seat_name: str) -> dict[str, Any] | None:
        """
        获取指定席位的缓存画像。

        Args:
            seat_name: 席位名称（如 "机构专用", "华泰证券上海分公司"）

        Returns:
            profile dict 或 None
        """
        with self._lock:
            profile = self._profiles.get(seat_name)
        if profile is None:
            return None

        result = profile.model_dump()
        result.pop("_buy_appearances", None)
        result.pop("_sell_appearances", None)
        result.pop("_stocks_traded", None)
        result.pop("_stock_buy_sell_pairs", None)
        return result

    # ------------------------------------------------------------------
    # Public API: compute_consensus_signal
    # ------------------------------------------------------------------

    def compute_consensus_signal(self, trade_date: str, stock_code: str) -> dict[str, Any] | None:
        """
        计算某只股票在特定日期的多席位共识/分歧信号。

        Steps:
        1. 拉取该股票该日的龙虎榜记录
        2. 拉取买入/卖出席位明细
        3. 查找每个席位的画像
        4. 根据席位类型和买卖方向判定信号

        Args:
            trade_date: 交易日期 YYYY-MM-DD
            stock_code: 股票代码（6位）

        Returns:
            {signal, details} 或 None
        """
        # 1. 拉取上榜记录
        filter_str = f"(TRADE_DATE='{trade_date}')(SECURITY_CODE='{stock_code}')"
        records = self._pull_records(
            report_name="RPT_DAILYBILLBOARD_DETAILSNEW",
            columns="ALL",
            filter_str=filter_str,
        )
        if not records:
            return None

        # 2. 拉取买卖席位明细
        buy_details = self._pull_records(
            report_name="RPT_BILLBOARD_DAILYDETAILSBUY",
            columns="ALL",
            filter_str=filter_str,
        )
        sell_details = self._pull_records(
            report_name="RPT_BILLBOARD_DAILYDETAILSSELL",
            columns="ALL",
            filter_str=filter_str,
        )

        if not buy_details and not sell_details:
            return None

        # 3. 收集买方席位信息
        buy_seats: list[dict[str, Any]] = []
        buy_seat_types: set[str] = set()
        total_buy_amount = 0.0
        institution_buy_amt = 0.0

        for rec in buy_details:
            seat_name = str(rec.get("OPERATEDEPT_NAME", "") or "")
            if not seat_name:
                continue
            buy_amt = astock._numf(rec.get("BUY", 0)) or 0
            sell_amt = astock._numf(rec.get("SELL", 0)) or 0
            net = astock._numf(rec.get("NET", 0)) or 0
            total_buy_amount += buy_amt

            profile = self.get_seat_profile(seat_name)
            if profile:
                seat_type = profile.get("seat_type", "inactive")
                buy_seat_types.add(seat_type)
            else:
                # 无 profile 时，根据 OPERATEDEPT_CODE 判断
                code_val = str(rec.get("OPERATEDEPT_CODE", ""))
                seat_type = "机构专用" if code_val == "0" else "未知席位"
                if seat_type == "机构专用":
                    buy_seat_types.add("机构专用")

            if seat_name == "机构专用" or (profile and profile.get("seat_type") == "机构专用"):
                institution_buy_amt += buy_amt

            buy_seats.append({
                "name": seat_name,
                "buy_amt": round(buy_amt / 10000, 1),
                "sell_amt": round(sell_amt / 10000, 1),
                "net": round(net / 10000, 1),
                "seat_type": seat_type if profile else "未知席位",
            })

        # 4. 收集卖方席位信息
        sell_seats: list[dict[str, Any]] = []
        sell_seat_types: set[str] = set()
        institution_sell_amt = 0.0

        for rec in sell_details:
            seat_name = str(rec.get("OPERATEDEPT_NAME", "") or "")
            if not seat_name:
                continue
            buy_amt = astock._numf(rec.get("BUY", 0)) or 0
            sell_amt = astock._numf(rec.get("SELL", 0)) or 0
            net = astock._numf(rec.get("NET", 0)) or 0

            profile = self.get_seat_profile(seat_name)
            if profile:
                seat_type = profile.get("seat_type", "inactive")
                sell_seat_types.add(seat_type)
            else:
                code_val = str(rec.get("OPERATEDEPT_CODE", ""))
                seat_type = "机构专用" if code_val == "0" else "未知席位"
                if seat_type == "机构专用":
                    sell_seat_types.add("机构专用")

            if seat_name == "机构专用" or (profile and profile.get("seat_type") == "机构专用"):
                institution_sell_amt += sell_amt

            sell_seats.append({
                "name": seat_name,
                "buy_amt": round(buy_amt / 10000, 1),
                "sell_amt": round(sell_amt / 10000, 1),
                "net": round(net / 10000, 1),
                "seat_type": seat_type if profile else "未知席位",
            })

        # 5. 判定信号
        signal = self._determine_signal(
            buy_seat_types=buy_seat_types,
            sell_seat_types=sell_seat_types,
            institution_buy_amt=institution_buy_amt,
            institution_sell_amt=institution_sell_amt,
            total_buy_amount=total_buy_amount,
            buy_seats=buy_seats,
            sell_seats=sell_seats,
        )

        if signal is None:
            return None

        return {
            "signal": signal,
            "details": {
                "date": trade_date,
                "stock_code": stock_code,
                "buy_seats": buy_seats,
                "sell_seats": sell_seats,
                "buy_seat_types": sorted(buy_seat_types),
                "sell_seat_types": sorted(sell_seat_types),
                "institution_buy_amt": round(institution_buy_amt / 10000, 1),
                "institution_sell_amt": round(institution_sell_amt / 10000, 1),
                "total_buy_amount": round(total_buy_amount / 10000, 1),
            },
            "disclaimer": SEAT_DISCLAIMER,
        }

    def _determine_signal(
        self,
        buy_seat_types: set[str],
        sell_seat_types: set[str],
        institution_buy_amt: float,
        institution_sell_amt: float,
        total_buy_amount: float,
        buy_seats: list[dict],
        sell_seats: list[dict],
    ) -> str | None:
        """
        根据席位类型分布判定共识/分歧信号。

        规则：
        1. "机构主导" — 机构是主要买方且净买入额 > 总买入额的 50%
        2. "多资金共识" — 2+ 种不同类型的资金都在净买入
        3. "分歧信号" — 游资买入 AND 量化/机构卖出
        4. "游资主导" — 游资席位占据买入侧主导
        5. None — 无明显信号
        """
        # 识别游资类型
        youzi_types = {"活跃游资", "跟风席位", "量化席位"}
        has_institution_buy = "机构专用" in buy_seat_types
        has_institution_sell = "机构专用" in sell_seat_types
        has_youzi_buy = bool(buy_seat_types & youzi_types)
        has_quant_or_inst_sell = bool(sell_seat_types & {"量化席位", "机构专用"})

        # 1. 机构主导：机构是主要买方
        if has_institution_buy and total_buy_amount > 0:
            inst_ratio = institution_buy_amt / total_buy_amount
            if inst_ratio > 0.5:
                return "机构主导"

        # 2. 多资金共识：2+ 不同类型资金净买入
        net_buying_types = set()
        for seat in buy_seats:
            if seat["net"] > 0:
                net_buying_types.add(seat["seat_type"])
        # 过滤 "未知席位"
        meaningful_types = {t for t in net_buying_types if t != "未知席位"}
        if len(meaningful_types) >= 2:
            return "多资金共识"

        # 3. 分歧信号：游资买入 AND 量化/机构卖出
        if has_youzi_buy and has_quant_or_inst_sell:
            return "分歧信号"

        # 4. 游资主导：游资席位占据买入侧
        if has_youzi_buy and not has_institution_buy:
            return "游资主导"

        # 5. 有机构买卖也算一种信号
        if has_institution_buy and not has_youzi_buy:
            return "机构主导"

        return None

    # ------------------------------------------------------------------
    # Public API: precompute_daily
    # ------------------------------------------------------------------

    def precompute_daily(self, date: str) -> dict[str, Any]:
        """
        每日 T+1 增量更新：拉取指定日期的龙虎榜数据，更新席位画像。

        Args:
            date: 交易日期 YYYY-MM-DD

        Returns:
            更新摘要
        """
        filter_str = f"(TRADE_DATE='{date}')"

        # 拉取新数据
        buy_data = self._pull_records(
            report_name="RPT_BILLBOARD_DAILYDETAILSBUY",
            columns="ALL",
            filter_str=filter_str,
        )
        sell_data = self._pull_records(
            report_name="RPT_BILLBOARD_DAILYDETAILSSELL",
            columns="ALL",
            filter_str=filter_str,
        )

        updated_seats: set[str] = set()

        with self._lock:
            for record in buy_data:
                seat_name = str(record.get("OPERATEDEPT_NAME", "") or "")
                if not seat_name:
                    continue
                if seat_name not in self._profiles:
                    self._profiles[seat_name] = SeatProfile(seat_name=seat_name)
                self._merge_record_into_profile(record, self._profiles[seat_name], side="buy")
                updated_seats.add(seat_name)

            for record in sell_data:
                seat_name = str(record.get("OPERATEDEPT_NAME", "") or "")
                if not seat_name:
                    continue
                if seat_name not in self._profiles:
                    self._profiles[seat_name] = SeatProfile(seat_name=seat_name)
                self._merge_record_into_profile(record, self._profiles[seat_name], side="sell")
                updated_seats.add(seat_name)

            # 重新分类更新的席位
            for seat_name in updated_seats:
                profile = self._profiles[seat_name]
                profile.avg_buy_amt = round(
                    profile.total_buy_amt / max(profile._buy_appearances, 1), 1
                )
                profile.avg_sell_amt = round(
                    profile.total_sell_amt / max(profile._sell_appearances, 1), 1
                )
                profile.stock_cooldown = len(profile._stocks_traded)
                profile.seat_type = self._classify_seat_type(profile)

            # 持久化
            save_dict = {}
            for name, p in self._profiles.items():
                pd = p.model_dump()
                pd.pop("_buy_appearances", None)
                pd.pop("_sell_appearances", None)
                pd.pop("_stocks_traded", None)
                pd.pop("_stock_buy_sell_pairs", None)
                save_dict[name] = pd
            _save_profiles_to_disk(save_dict)

        return {
            "date": date,
            "updated_seats": sorted(updated_seats),
            "total_seats": len(self._profiles),
            "buy_records": len(buy_data),
            "sell_records": len(sell_data),
        }

    # ------------------------------------------------------------------
    # Public API: backfill
    # ------------------------------------------------------------------

    def backfill(self, start_date: str, end_date: str | None = None) -> list[dict]:
        """
        历史回填：逐日拉取龙虎榜数据，构建完整席位画像。

        Args:
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期，默认今天

        Returns:
            每日更新摘要列表
        """
        if end_date is None:
            end_date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        results: list[dict] = []
        current_dt = start_dt

        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            try:
                result = self.precompute_daily(date_str)
                results.append(result)
            except Exception as e:
                logging.getLogger("vibe-research").warning("[%s] 席位引擎回填失败: %s", date_str, e)

            current_dt += timedelta(days=1)
            time.sleep(0.5)  # 节流，避免请求过快

        return results

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_all_seat_types_summary(self) -> dict[str, list[str]]:
        """
        获取所有席位按类型的分组汇总。

        Returns:
            {seat_type: [seat_names]}
        """
        with self._lock:
            groups: dict[str, list[str]] = {}
            for name, profile in self._profiles.items():
                stype = profile.seat_type
                if stype not in groups:
                    groups[stype] = []
                groups[stype].append(name)

            # 按席位数量降序排列
            for stype in groups:
                groups[stype].sort()

        return groups

    def get_all_seat_profiles(self) -> dict[str, dict]:
        """
        获取所有席位画像（用于 API 返回）。
        
        Returns:
            {seat_name: profile_dict}
        """
        with self._lock:
            result = {}
            for name, profile in self._profiles.items():
                pd = profile.model_dump()
                pd.pop("_buy_appearances", None)
                pd.pop("_sell_appearances", None)
                pd.pop("_stocks_traded", None)
                pd.pop("_stock_buy_sell_pairs", None)
                result[name] = pd
            return result

    def refresh_all_profiles(self) -> dict[str, dict]:
        """
        完全重建所有席位画像（覆盖式更新）。

        Returns:
            同 build_seat_profiles
        """
        return self.build_seat_profiles()


# ===========================================================================
# 4. Singleton
# ===========================================================================

_engine_instance: SeatEngine | None = None


def get_engine() -> SeatEngine:
    """获取全局 SeatEngine 实例（单例）。"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SeatEngine()
    return _engine_instance
