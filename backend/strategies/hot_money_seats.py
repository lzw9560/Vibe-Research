# -*- coding: utf-8 -*-
"""S066 §9 游资席位分析——60 日龙虎榜聚合画像 + 行为突变检测 + 策略分接入。

spec §9 设计：
- 席位分三类：一日游（T 买 T+1 卖）/ 接力型（持仓 2-5 日）/ 机构
- 60 日龙虎榜聚合 → next_day_sell_rate + appearance_count → 分类
- 周更为主 + 行为突变检测（5 日增量 vs 60 日均值，偏差 > 30% 标注）
- 预设画像覆盖已知席位（hot_money_seats_preset.json），实际数据积累后修正

数据源：东财 datacenter RPT_BILLBOARD_DAILYDETAILSBUY/SELL
- S079 AC6 处置（2026-08-18）：原 spec §8.1 注释"datacenter API 可直接 urllib 调用"
  经核实 datacenter-web.eastmoney.com 与 push2ex 同属东财域名，限流策略可能同源（同 IP 池）。
  风险：原 urllib 直调无限流无熔断，有 IP 封禁风险。
  处置：改用 astock.em_get（复用既有防封底线：0.3s 限流 + circuit_breaker 熔断 + 代理探测），
  不臆造新限流。em_get 对所有东财域名统一防护，datacenter 与 push2ex 共享 breaker("eastmoney")。
- 不输出个体席位名（S018 R11：个体席位标签 alpha 已衰减，只用聚合分类）

输出：
- hot_money_seats.json：60 日聚合画像（周更）
- hot_money_seat_risk 因子 → 策略分修饰（一日游占比高 → ×0.7 扣分）
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import astock
from vr_paths import resolve_data_dir

_DATA_DIR = resolve_data_dir()
_PRESET_PATH = Path(__file__).resolve().parent.parent / "data" / "hot_money_seats_preset.json"
_AGGREGATE_PATH = _DATA_DIR / "hot_money_seats.json"

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

# 分类阈值（spec §9.3）
DAY_TRIP_SELL_RATE_MIN = 0.7    # 一日游：next_day_sell_rate >= 0.7
RELAY_SELL_RATE_MAX = 0.3       # 接力型：next_day_sell_rate <= 0.3
APPEARANCE_MIN = 3              # 最少上榜次数才分类
MUTATION_THRESHOLD = 0.30       # 行为突变：偏差 > 30%


@dataclass(frozen=True)
class SeatProfile:
    """单个席位画像。"""
    seat_name: str
    seat_type: str               # 一日游 / 接力型 / 机构 / 混合型 / 样本不足
    next_day_sell_rate: float    # T 买入后 T+1 在卖方榜出现的比例
    appearance_count: int       # 60 日上榜总次数
    confidence: str             # high / medium / low
    source: str                  # data / preset
    note: str = ""


@dataclass(frozen=True)
class SeatRiskFactor:
    """个股游资席位风险因子（spec §9.4）。"""
    day_trip_ratio: float       # 一日游席位净买入额 / 总净买入额
    relay_ratio: float          # 接力型席位净买入额 / 总净买入额
    institution_ratio: float    # 机构席位净买入额 / 总净买入额
    score_modifier: float        # 策略分修饰系数（一日游高 → ×0.7）
    risk_label: str             # 高风险 / 中风险 / 低风险 / 无数据
    mutation_alert: bool        # 行为突变标注
    mutation_note: str = ""


# ===========================================================================
# 60 日龙虎榜聚合（周更，spec §9.3）
# ===========================================================================

def fetch_billboard_dates(days: int = 60) -> list[str]:
    """获取最近 N 个有龙虎榜数据的交易日日期列表。

    S079 AC6：走 astock.em_get 限流 + 熔断（原 urllib 直调已废弃，见模块 docstring）。
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days + 15)).strftime("%Y-%m-%d")  # 多取 15 日防周末
    url = (
        f"{_DATACENTER_URL}?reportName=RPT_DAILYBILLBOARD_DETAILSNEW"
        f"&columns=TRADE_DATE&filter=(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')"
        f"&pageNumber=1&pageSize=500&sortColumns=TRADE_DATE&sortTypes=-1&source=WEB&client=WEB"
    )
    try:
        resp = astock.em_get(url, headers=_UA, timeout=15)
        data = resp.json() if hasattr(resp, "json") else json.loads(resp.read())
        rows = data.get("result", {}).get("data", []) or []
        dates = sorted(set(str(r.get("TRADE_DATE", ""))[:10] for r in rows if r.get("TRADE_DATE")))
        return dates[-days:] if len(dates) > days else dates
    except Exception:
        return []


def fetch_billboard_for_date(trade_date: str) -> list[dict]:
    """取指定日期所有龙虎榜买卖明细（buy + sell 合并）。

    S079 AC6：走 astock.em_get 限流 + 熔断（原 urllib 直调已废弃，见模块 docstring）。
    返回 [{SECURITY_CODE, OPERATEDEPT_NAME, BUY, SELL, NET, TRADE_DATE, side}]。
    """
    results: list[dict] = []
    for side, report in (("buy", "RPT_BILLBOARD_DAILYDETAILSBUY"),
                         ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL")):
        url = (
            f"{_DATACENTER_URL}?reportName={report}&columns=ALL"
            f"&filter=(TRADE_DATE='{trade_date}')"
            f"&pageNumber=1&pageSize=500&sortColumns=TRADE_DATE&sortTypes=-1&source=WEB&client=WEB"
        )
        try:
            resp = astock.em_get(url, headers=_UA, timeout=15)
            data = resp.json() if hasattr(resp, "json") else json.loads(resp.read())
            rows = data.get("result", {}).get("data", []) or []
            for r in rows:
                r["side"] = side
                results.append(r)
        except Exception:
            continue
    return results


def _classify_seat(next_day_sell_rate: float, appearance_count: int) -> tuple[str, str]:
    """席位分类（spec §9.3）。返回 (seat_type, confidence)。"""
    if appearance_count < APPEARANCE_MIN:
        return "样本不足", "low"
    if next_day_sell_rate >= DAY_TRIP_SELL_RATE_MIN:
        return "一日游", "medium"
    if next_day_sell_rate <= RELAY_SELL_RATE_MAX:
        return "接力型", "medium"
    return "混合型", "low"


def build_seat_profiles(billboard_data: list[dict]) -> list[SeatProfile]:
    """从 60 日龙虎榜数据构建席位画像。

    billboard_data: 所有日期的买卖明细合并列表。
    对每个 OPERATEDEPT_NAME 计算 next_day_sell_rate + appearance_count → 分类。
    """
    # 按席位名聚合
    seat_stats: dict[str, dict] = {}
    for r in billboard_data:
        name = r.get("OPERATEDEPT_NAME", "")
        if not name:
            continue
        if name not in seat_stats:
            seat_stats[name] = {
                "buy_dates": set(),
                "sell_dates": set(),
                "appearance_count": 0,
            }
        trade_date = str(r.get("TRADE_DATE", ""))[:10]
        seat_stats[name]["appearance_count"] += 1
        if r.get("side") == "buy":
            seat_stats[name]["buy_dates"].add(trade_date)
        else:
            seat_stats[name]["sell_dates"].add(trade_date)

    profiles: list[SeatProfile] = []
    for name, stats in seat_stats.items():
        # next_day_sell_rate: T 买入后 T+1 在卖方榜出现的比例
        buy_dates = sorted(stats["buy_dates"])
        if not buy_dates:
            # 只有卖方记录的席位，无法算 next_day_sell_rate
            seat_type, conf = "样本不足", "low"
            profiles.append(SeatProfile(
                seat_name=name, seat_type=seat_type,
                next_day_sell_rate=0.0, appearance_count=stats["appearance_count"],
                confidence=conf, source="data", note="无买入记录",
            ))
            continue

        # 简化：检查买入日次日是否在卖方榜（需跨日匹配，这里用 buy_dates 和 sell_dates 交集近似）
        next_day_sell_count = 0
        for bd in buy_dates:
            # 次日 = bd + 1 交易日（简化：检查 bd 后 3 日内是否出现在卖方榜）
            bd_dt = datetime.strptime(bd, "%Y-%m-%d")
            for offset in range(1, 4):
                next_dt = bd_dt + timedelta(days=offset)
                next_str = next_dt.strftime("%Y-%m-%d")
                if next_str in stats["sell_dates"]:
                    next_day_sell_count += 1
                    break

        next_day_sell_rate = next_day_sell_count / len(buy_dates) if buy_dates else 0.0
        seat_type, conf = _classify_seat(next_day_sell_rate, stats["appearance_count"])

        profiles.append(SeatProfile(
            seat_name=name, seat_type=seat_type,
            next_day_sell_rate=round(next_day_sell_rate, 4),
            appearance_count=stats["appearance_count"],
            confidence=conf, source="data",
        ))

    return profiles


def merge_with_presets(data_profiles: list[SeatProfile]) -> list[SeatProfile]:
    """合并预设画像（spec §9.3.1）。

    1. 数据画像覆盖预设（数据为准）
    2. 预设中有但数据中没有的席位 → 保留预设标签
    3. 数据画像与预设冲突 → 以数据为准，标注"预设标签已被数据修正"
    """
    try:
        preset_data = json.loads(_PRESET_PATH.read_text(encoding="utf-8"))
    except Exception:
        preset_data = {}

    seat_groups = preset_data.get("seat_groups", {})
    data_names = {p.seat_name for p in data_profiles}
    merged = list(data_profiles)

    # 预设中有但数据中没有的席位
    for group_name, group_info in seat_groups.items():
        for seat_name in group_info.get("seats", []):
            if seat_name not in data_names:
                merged.append(SeatProfile(
                    seat_name=seat_name,
                    seat_type=group_info.get("default_type", "混合型"),
                    next_day_sell_rate=0.0,
                    appearance_count=0,
                    confidence=group_info.get("confidence", "low"),
                    source="preset",
                    note=group_info.get("note", ""),
                ))

    return merged


def save_aggregate_profiles(profiles: list[SeatProfile]) -> None:
    """保存聚合画像到 hot_money_seats.json（周更）。"""
    data = {
        "_meta": {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "60d_billboard_aggregate",
            "total_seats": len(profiles),
        },
        "profiles": [
            {
                "seat_name": p.seat_name,
                "seat_type": p.seat_type,
                "next_day_sell_rate": p.next_day_sell_rate,
                "appearance_count": p.appearance_count,
                "confidence": p.confidence,
                "source": p.source,
                "note": p.note,
            }
            for p in profiles
        ],
    }
    _AGGREGATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def load_aggregate_profiles() -> list[SeatProfile]:
    """加载已保存的聚合画像。文件不存在返空列表。"""
    if not _AGGREGATE_PATH.exists():
        return []
    try:
        data = json.loads(_AGGREGATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [
        SeatProfile(
            seat_name=p["seat_name"],
            seat_type=p["seat_type"],
            next_day_sell_rate=p.get("next_day_sell_rate", 0.0),
            appearance_count=p.get("appearance_count", 0),
            confidence=p.get("confidence", "low"),
            source=p.get("source", "data"),
            note=p.get("note", ""),
        )
        for p in data.get("profiles", [])
    ]


# ===========================================================================
# 行为突变检测（spec §9.3）
# ===========================================================================

def detect_behavior_mutation(
    recent_5d_profiles: list[SeatProfile],
    baseline_60d_profiles: list[SeatProfile],
) -> dict[str, dict]:
    """行为突变检测：5 日增量 vs 60 日均值，偏差 > 30% 标注。

    返回 {seat_name: {baseline_rate, recent_rate, deviation, alert}}。
    """
    baseline_map = {p.seat_name: p for p in baseline_60d_profiles}
    mutations: dict[str, dict] = {}

    for recent_p in recent_5d_profiles:
        base_p = baseline_map.get(recent_p.seat_name)
        if not base_p or base_p.appearance_count < APPEARANCE_MIN:
            continue

        base_rate = base_p.next_day_sell_rate
        recent_rate = recent_p.next_day_sell_rate
        if base_rate == 0:
            continue

        deviation = abs(recent_rate - base_rate) / base_rate
        if deviation > MUTATION_THRESHOLD:
            mutations[recent_p.seat_name] = {
                "baseline_rate": round(base_rate, 4),
                "recent_rate": round(recent_rate, 4),
                "deviation": round(deviation, 4),
                "alert": True,
                "note": f"行为变化：60日 next_day_sell_rate={base_rate:.2f} → 5日={recent_rate:.2f}",
            }

    return mutations


# ===========================================================================
# 策略分接入（spec §9.4）
# ===========================================================================

def compute_seat_risk_factor(
    code: str,
    trade_date: str,
    profiles: list[SeatProfile] | None = None,
    mutations: dict[str, dict] | None = None,
    billboard: list[dict] | None = None,
) -> SeatRiskFactor:
    """计算个股游资席位风险因子（spec §9.4）。

    billboard 参数支持外部 batch 传入（score_candidates 取一次供所有 cand 复用，避免 per-cand 重复 fetch）；
    不传则内部 fetch_billboard_for_date。
    画像未建（load_aggregate_profiles 返空/preset）→ 席位"样本不足" → modifier 1.0 降级标注。

    day_trip_ratio > 0.5 → 策略分 ×0.7（高风险）
    day_trip_ratio 0.2-0.5 → 策略分 ×0.9（中风险）
    day_trip_ratio < 0.2 → 不扣分
    接力型净买入 > 总净买入 30% → 策略分 +5（接力支撑）
    """
    profiles = profiles if profiles is not None else load_aggregate_profiles()
    profile_map = {p.seat_name: p for p in profiles}
    mutations = mutations or {}

    # 当日龙虎榜明细（batch：外部传入；否则内部 fetch）
    if billboard is None:
        billboard = fetch_billboard_for_date(trade_date)
    code_billboard = [r for r in billboard if r.get("SECURITY_CODE") == code]

    if not code_billboard:
        return SeatRiskFactor(
            day_trip_ratio=0.0, relay_ratio=0.0, institution_ratio=0.0,
            score_modifier=1.0, risk_label="无数据", mutation_alert=False,
        )

    # 按席位类型聚合净买入额
    type_net: dict[str, float] = {"一日游": 0.0, "接力型": 0.0, "机构": 0.0, "混合型": 0.0, "样本不足": 0.0}
    total_net = 0.0
    mutation_found = False

    for r in code_billboard:
        seat_name = r.get("OPERATEDEPT_NAME", "")
        net = float(r.get("NET") or 0)
        total_net += net

        profile = profile_map.get(seat_name)
        if not profile:
            # 未在画像中的席位 → 标"样本不足"
            type_net["样本不足"] += net
            continue

        if profile.seat_type in type_net:
            type_net[profile.seat_type] += net
        else:
            type_net["混合型"] += net

        if seat_name in mutations:
            mutation_found = True

    # 计算占比
    if total_net > 0:
        day_trip_ratio = type_net["一日游"] / total_net
        relay_ratio = type_net["接力型"] / total_net
        institution_ratio = type_net["机构"] / total_net
    else:
        day_trip_ratio = relay_ratio = institution_ratio = 0.0

    # 策略分修饰（spec §9.4）
    modifier = 1.0
    if day_trip_ratio > 0.5:
        modifier = 0.7
        risk_label = "高风险"
    elif day_trip_ratio > 0.2:
        modifier = 0.9
        risk_label = "中风险"
    else:
        risk_label = "低风险"

    # 接力型支撑 +5（spec §9.4）
    if relay_ratio > 0.3:
        modifier = min(modifier + 0.05, 1.05)  # 不超过 1.05
        risk_label = f"{risk_label}+接力支撑"

    return SeatRiskFactor(
        day_trip_ratio=round(day_trip_ratio, 4),
        relay_ratio=round(relay_ratio, 4),
        institution_ratio=round(institution_ratio, 4),
        score_modifier=round(modifier, 4),
        risk_label=risk_label,
        mutation_alert=mutation_found,
        mutation_note="; ".join(mutations.get(s, {}).get("note", "") for s in mutations) if mutation_found else "",
    )


# ===========================================================================
# 周更入口
# ===========================================================================

def update_hot_money_seats(days: int = 60) -> int:
    """周更入口：拉 60 日龙虎榜 → 聚合画像 → 保存。

    约 18 次 API 调用（60 日 / 3.5 日均一次，每页 500 条）。
    返回画像席位数。
    """
    dates = fetch_billboard_dates(days)
    if not dates:
        return 0

    all_data: list[dict] = []
    for d in dates:
        rows = fetch_billboard_for_date(d)
        all_data.extend(rows)

    profiles = build_seat_profiles(all_data)
    merged = merge_with_presets(profiles)
    save_aggregate_profiles(merged)
    return len(merged)
