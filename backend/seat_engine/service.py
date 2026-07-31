# -*- coding: utf-8 -*-
"""seat_engine 服务层 —— SeatEngine 核心逻辑。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import astock

from data.mappers import billboard_detail_from_dict
from seat_engine.models import (
    SeatProfile,
    ConsensusSignal,
    SEAT_DISCLAIMER,
    SEAT_LOOKBACK_DAYS,
    SEAT_QUANT_THRESHOLD,
    SEAT_ACTIVE_MIN,
    SEAT_LARGE_POS,
    SEAT_SMALL_POS,
)
from seat_engine.data import load_profiles_from_disk, save_profiles_to_disk

BEIJING_TZ = datetime.now().astimezone().tzinfo

_engine_instance: SeatEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> SeatEngine:
    """返回 SeatEngine 单例。"""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = SeatEngine()
    return _engine_instance


class SeatEngine:
    """龙虎榜席位智能引擎。"""

    def __init__(self):
        self._profiles: dict[str, SeatProfile] = {}
        self._lock = threading.Lock()

        raw = load_profiles_from_disk()
        if raw:
            for name, data in raw.items():
                try:
                    profile = SeatProfile(**data)
                    self._profiles[name] = profile
                except Exception:
                    continue

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
            if page > 20:
                break
        return all_data

    def _classify_seat_type(self, profile: SeatProfile) -> str:
        """根据统计特征对席位进行分类。"""
        if profile.total_appearances == 0:
            return "inactive"

        if profile.seat_name == "机构专用":
            return "机构专用"

        is_quant = (
            profile.total_appearances >= SEAT_QUANT_THRESHOLD
            and len(profile._stock_buy_sell_pairs) > 0
            and profile.avg_buy_amt < SEAT_LARGE_POS
        )
        if is_quant:
            return "量化席位"

        is_active_youzi = (
            SEAT_ACTIVE_MIN <= profile.total_appearances < SEAT_QUANT_THRESHOLD
            and profile.net_amt > 0
            and profile.avg_buy_amt >= SEAT_LARGE_POS
        )
        if is_active_youzi:
            return "活跃游资"

        is_follower = (
            profile.total_appearances >= SEAT_ACTIVE_MIN
            and profile.avg_buy_amt < SEAT_SMALL_POS
        )
        if is_follower:
            return "跟风席位"

        return "inactive"

    def _merge_record_into_profile(self, record: dict, profile: SeatProfile,
                                    side: str) -> None:
        """将一条龙虎榜明细记录合并到席位画像中。"""
        rec = billboard_detail_from_dict(record)
        buy_amt = rec.buy or 0
        sell_amt = rec.sell or 0
        net_amt = rec.net or 0
        stock_code = rec.security_code or ""
        trade_date = rec.trade_date or ""

        profile.total_appearances += 1
        profile.total_buy_amt += buy_amt
        profile.total_sell_amt += sell_amt
        profile.net_amt += net_amt

        if side == "buy":
            profile._buy_appearances += 1
        else:
            profile._sell_appearances += 1

        profile._stocks_traded.add(stock_code)

        if buy_amt > 0 and sell_amt > 0:
            profile._stock_buy_sell_pairs.add((stock_code, profile.seat_name))

        if trade_date and (not profile.last_seen or trade_date > profile.last_seen):
            profile.last_seen = trade_date

    def build_seat_profiles(self, lookback_days: int | None = None) -> dict[str, dict]:
        """冷启动：批量拉取历史龙虎榜数据，构建所有席位画像。"""
        if lookback_days is None:
            lookback_days = SEAT_LOOKBACK_DAYS

        end_date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        start_dt = datetime.now(BEIJING_TZ) - timedelta(days=lookback_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        filter_str = f'(TRADE_DATE>=\'{start_date}\')(TRADE_DATE<=\'{end_date}\')'

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

        profiles: dict[str, SeatProfile] = {}

        for record in buy_data:
            seat_name = billboard_detail_from_dict(record).operate_dept_name or ""
            if not seat_name:
                continue
            if seat_name not in profiles:
                profiles[seat_name] = SeatProfile(seat_name=seat_name)
            self._merge_record_into_profile(record, profiles[seat_name], side="buy")

        for record in sell_data:
            seat_name = billboard_detail_from_dict(record).operate_dept_name or ""
            if not seat_name:
                continue
            if seat_name not in profiles:
                profiles[seat_name] = SeatProfile(seat_name=seat_name)
            self._merge_record_into_profile(record, profiles[seat_name], side="sell")

        result: dict[str, dict] = {}
        for seat_name, profile in profiles.items():
            buy_count = profile._buy_appearances
            sell_count = profile._sell_appearances

            profile.avg_buy_amt = round(profile.total_buy_amt / max(buy_count, 1), 1)
            profile.avg_sell_amt = round(profile.total_sell_amt / max(sell_count, 1), 1)
            profile.stock_cooldown = len(profile._stocks_traded)
            profile.seat_type = self._classify_seat_type(profile)

            profile_dict = profile.model_dump()
            profile_dict.pop("_buy_appearances", None)
            profile_dict.pop("_sell_appearances", None)
            profile_dict.pop("_stocks_traded", None)
            profile_dict.pop("_stock_buy_sell_pairs", None)
            result[seat_name] = profile_dict

        with self._lock:
            self._profiles = profiles
            save_dict = {}
            for name, p in profiles.items():
                pd = p.model_dump()
                pd.pop("_buy_appearances", None)
                pd.pop("_sell_appearances", None)
                pd.pop("_stocks_traded", None)
                pd.pop("_stock_buy_sell_pairs", None)
                save_dict[name] = pd
            save_profiles_to_disk(save_dict)

        return result

    def get_seat_profile(self, seat_name: str) -> dict[str, Any] | None:
        """获取指定席位的缓存画像。"""
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

    def compute_consensus_signal(self, trade_date: str, stock_code: str) -> dict[str, Any] | None:
        """计算某只股票在特定日期的多席位共识/分歧信号。"""
        filter_str = f"(TRADE_DATE='{trade_date}')(SECURITY_CODE='{stock_code}')"
        records = self._pull_records(
            report_name="RPT_DAILYBILLBOARD_DETAILSNEW",
            columns="ALL",
            filter_str=filter_str,
        )
        if not records:
            return None

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

        buy_seats: list[dict[str, Any]] = []
        buy_seat_types: set[str] = set()
        total_buy_amount = 0.0
        institution_buy_amt = 0.0

        for rec in buy_details:
            rec_m = billboard_detail_from_dict(rec)
            seat_name = rec_m.operate_dept_name or ""
            if not seat_name:
                continue
            buy_amt = rec_m.buy or 0
            sell_amt = rec_m.sell or 0
            net = rec_m.net or 0
            total_buy_amount += buy_amt

            profile = self.get_seat_profile(seat_name)
            if profile:
                seat_type = profile.get("seat_type", "inactive")
                buy_seat_types.add(seat_type)
            else:
                code_val = rec_m.operate_dept_code or ""
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

        sell_seats: list[dict[str, Any]] = []
        sell_seat_types: set[str] = set()
        institution_sell_amt = 0.0

        for rec in sell_details:
            rec_m = billboard_detail_from_dict(rec)
            seat_name = rec_m.operate_dept_name or ""
            if not seat_name:
                continue
            buy_amt = rec_m.buy or 0
            sell_amt = rec_m.sell or 0
            net = rec_m.net or 0

            profile = self.get_seat_profile(seat_name)
            if profile:
                seat_type = profile.get("seat_type", "inactive")
                sell_seat_types.add(seat_type)
            else:
                code_val = rec_m.operate_dept_code or ""
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
        """根据席位类型分布判定共识/分歧信号。"""
        youzi_types = {"活跃游资", "跟风席位", "量化席位"}
        has_institution_buy = "机构专用" in buy_seat_types
        has_institution_sell = "机构专用" in sell_seat_types
        has_youzi_buy = bool(buy_seat_types & youzi_types)
        has_quant_or_inst_sell = bool(sell_seat_types & {"量化席位", "机构专用"})

        if has_institution_buy and total_buy_amount > 0:
            inst_ratio = institution_buy_amt / total_buy_amount
            if inst_ratio > 0.5:
                return "机构主导"

        net_buying_types = set()
        for seat in buy_seats:
            if seat["net"] > 0:
                net_buying_types.add(seat["seat_type"])
        meaningful_types = {t for t in net_buying_types if t != "未知席位"}
        if len(meaningful_types) >= 2:
            return "多资金共识"

        if has_youzi_buy and has_quant_or_inst_sell:
            return "分歧信号"

        if has_youzi_buy and not has_institution_buy:
            return "游资主导"

        if has_institution_buy and not has_youzi_buy:
            return "机构主导"

        return None

    def precompute_daily(self, date: str) -> dict[str, Any]:
        """每日 T+1 增量更新：拉取指定日期的龙虎榜数据，更新席位画像。"""
        filter_str = f"(TRADE_DATE='{date}')"

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
                seat_name = billboard_detail_from_dict(record).operate_dept_name or ""
                if not seat_name:
                    continue
                if seat_name not in self._profiles:
                    self._profiles[seat_name] = SeatProfile(seat_name=seat_name)
                self._merge_record_into_profile(record, self._profiles[seat_name], side="buy")
                updated_seats.add(seat_name)

            for record in sell_data:
                seat_name = billboard_detail_from_dict(record).operate_dept_name or ""
                if not seat_name:
                    continue
                if seat_name not in self._profiles:
                    self._profiles[seat_name] = SeatProfile(seat_name=seat_name)
                self._merge_record_into_profile(record, self._profiles[seat_name], side="sell")
                updated_seats.add(seat_name)

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

            save_dict = {}
            for name, p in self._profiles.items():
                pd = p.model_dump()
                pd.pop("_buy_appearances", None)
                pd.pop("_sell_appearances", None)
                pd.pop("_stocks_traded", None)
                pd.pop("_stock_buy_sell_pairs", None)
                save_dict[name] = pd
            save_profiles_to_disk(save_dict)

        return {
            "date": date,
            "updated_seats": sorted(updated_seats),
            "total_seats": len(self._profiles),
            "buy_records": len(buy_data),
            "sell_records": len(sell_data),
        }

    def backfill(self, start_date: str, end_date: str | None = None) -> list[dict]:
        """历史回填：逐日拉取龙虎榜数据，构建完整席位画像。"""
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
            time.sleep(0.5)

        return results

    def get_all_seat_types_summary(self) -> dict[str, list[str]]:
        """获取所有席位按类型的分组汇总。"""
        with self._lock:
            groups: dict[str, list[str]] = {}
            for name, profile in self._profiles.items():
                stype = profile.seat_type
                if stype not in groups:
                    groups[stype] = []
                groups[stype].append(name)

            for stype in groups:
                groups[stype].sort()

        return groups

    def get_all_seat_profiles(self) -> dict[str, dict]:
        """获取所有席位画像（用于 API 返回）。"""
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
        """完全重建所有席位画像（覆盖式更新）。"""
        return self.build_seat_profiles()
