# -*- coding: utf-8 -*-
"""质量标准检查——check_quality_standards / passes_hard_standards。"""
from __future__ import annotations

from typing import Any

from strategies.funnel.registry import get_strategy_config


def check_quality_standards(
    candidate: dict,
    strategy_code: str,
    market_data: dict | None = None,
) -> list[dict]:
    """检查策略特定质量标准（spec §7）。

    返回 [{name, passed, required, description}]。
    missing 数据标 "数据不足"（不作为硬标准，spec §7.1）。

    market_data: {seal_time, open_count, seal_amount, float_market_cap, ...}
    缺字段 → 该标准标 missing=True 不通过硬过滤。
    """
    cfg = get_strategy_config(strategy_code)
    if not cfg:
        return []

    results = []
    md = market_data or {}
    for std in cfg.quality_standards:
        passed = False
        missing = False
        detail = ""

        if std.name == "开板次数" or std.name == "开板次数≥1":
            oc = md.get("open_count")
            if oc is None:
                missing = True
            elif strategy_code == "break_reseal" or std.name == "开板次数≥1":
                passed = oc >= 1  # 炸板回封需要至少一次开板
            else:
                passed = oc <= 1
            detail = f"开板次数={oc}" if oc is not None else "数据不足"

        elif std.name == "封板时间≤10:30":
            st = md.get("seal_time")
            if st is None:
                missing = True
            else:
                passed = st <= "10:30"
            detail = f"封板时间={st}" if st else "数据不足"

        elif std.name == "封板时间>14:30":
            st = md.get("seal_time")
            if st is None:
                missing = True
            else:
                passed = st > "14:30"
            detail = f"封板时间={st}" if st else "数据不足"

        elif std.name == "连板数≥2":
            lb = md.get("consecutive_boards")
            if lb is None:
                missing = True
            else:
                passed = lb >= 2
            detail = f"连板数={lb}" if lb is not None else "数据不足"

        elif std.name == "封板率≥80%":
            sr = md.get("seal_rate")
            if sr is None:
                missing = True
            else:
                passed = sr >= 80
            detail = f"封板率={sr}" if sr is not None else "数据不足"

        elif std.name == "封板率≥60%":
            sr = md.get("seal_rate")
            if sr is None:
                missing = True
            else:
                passed = sr >= 60
            detail = f"封板率={sr}" if sr is not None else "数据不足"

        elif std.name == "量比>2":
            vr = md.get("vol_ratio")
            if vr is None:
                missing = True
            else:
                passed = vr > 2
            detail = f"量比={vr}" if vr is not None else "数据不足"

        elif std.name == "T-1未涨停":
            t1_zt = md.get("t1_limit_up")
            if t1_zt is None:
                missing = True
            else:
                passed = not t1_zt
            detail = "T-1涨停" if t1_zt else "T-1未涨停"

        elif std.name == "成交额>15亿":
            amt = md.get("amount_yi")
            if amt is None:
                missing = True
            else:
                passed = amt > 15
            detail = f"成交额={amt}亿" if amt is not None else "数据不足"

        elif std.name == "均线多头":
            ma5 = md.get("ma5")
            ma10 = md.get("ma10")
            ma20 = md.get("ma20")
            if None in (ma5, ma10, ma20):
                missing = True
            else:
                passed = ma5 > ma10 > ma20
            detail = f"MA5={ma5}/MA10={ma10}/MA20={ma20}"

        elif std.name == "横盘≥5日":
            consolidation = md.get("consolidation_days")
            if consolidation is None:
                missing = True
            else:
                passed = consolidation >= 5
            detail = f"横盘{consolidation}日" if consolidation is not None else "数据不足"

        elif std.name == "成交额放大2倍":
            vol_breakout = md.get("vol_breakout_ratio")
            if vol_breakout is None:
                missing = True
            else:
                passed = vol_breakout >= 2
            detail = f"量比放大{vol_breakout}倍" if vol_breakout is not None else "数据不足"

        elif std.name == "板块领涨":
            sector_rank = md.get("sector_rank")
            if sector_rank is None:
                missing = True
            else:
                passed = sector_rank <= 3  # TOP-3 板块
            detail = f"板块排名={sector_rank}" if sector_rank is not None else "数据不足"

        elif std.name == "换手>5%":
            turnover = md.get("turnover_rate")
            if turnover is None:
                missing = True
            else:
                passed = turnover > 5
            detail = f"换手={turnover}%" if turnover is not None else "数据不足"

        elif std.name == "回调至MA5":
            ma5 = md.get("ma5")
            close = md.get("close")
            if None in (ma5, close):
                missing = True
            else:
                passed = abs(close - ma5) / ma5 * 100 < 3  # 接近 MA5
            detail = f"close={close}/MA5={ma5}"

        elif std.name == "2日内涨停":
            recent_zt = md.get("recent_zt_days", 0)
            if recent_zt is None:
                missing = True
            else:
                passed = recent_zt >= 1
            detail = f"近{recent_zt}日涨停"

        else:
            missing = True
            detail = "未实现检查逻辑"

        results.append({
            "name": std.name,
            "passed": passed,
            "required": std.required,
            "missing": missing,
            "description": std.description,
            "detail": detail,
        })

    return results


def passes_hard_standards(quality_results: list[dict]) -> bool:
    """是否通过所有硬标准（required=True 且无 missing）。

    spec §7.1：missing 率 > 50% 的标准标注"数据不足，不作为硬标准"。
    本函数对 missing 的标准不阻断（不作为硬标准）。
    """
    for r in quality_results:
        if r["required"] and not r["missing"] and not r["passed"]:
            return False
    return True
