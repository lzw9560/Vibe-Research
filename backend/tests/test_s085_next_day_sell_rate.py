# -*- coding: utf-8 -*-
"""S085 C3 — next_day_sell_rate 真实交易日单测。

bug：build_seat_profiles:175-185 用 1-3 自然日 offset（bd+timedelta(days=offset)）找
sell_dates——长假（春节/国庆 7 天）买入，真实下一交易日 = 长假后第 1 日，但 +1..3 自然日
够不着（长假后第 4+ 日才是真实下一交易日）→ MISSED → next_day_sell_rate 系统性偏低
→ 偏向接力型 → 少计一日游风险扣分（score_modifier 0.7/0.9 少触发）→ 选股分偏高。
修复：从 billboard_data 提取 sorted 真实交易日，用 index+1..3 真实下一交易日替代自然日
（保留 1-3 宽泛语义，只修长假 catch）。

承重：next_day_sell_rate → seat_type → score_modifier → strategy_funnel_registry:460 选股分。
改 score_modifier → 选股分漂移（CORRECTING bias，当前偏高是 bug）。
回溯：hot_money_seats.json 持久化旧 modifier，需重算历史画像统一（todo，需数据积累后重跑）。
"""
from __future__ import annotations

from strategies.hot_money_seats import build_seat_profiles


def _row(name, date, side):
    return {"OPERATEDEPT_NAME": name, "TRADE_DATE": date, "side": side,
            "SECURITY_CODE": "X", "BUY": 0, "SELL": 0, "NET": 0}


def test_long_holiday_next_day_sell_caught():
    """春节长假（02-13 买入→02-19 真实下一交易日卖出）修复后 catch，原自然日漏判。"""
    # 02-13（节前最后交易日）买入，02-19（节后第一交易日）卖出
    # 自然日 +1..3 = 02-14/15/16（春节，非交易日）→ 漏；真实交易日 index+1 = 02-19 → catch
    billboard = [
        _row("席位A", "2026-02-13", "buy"),
        _row("席位A", "2026-02-19", "sell"),
    ]
    profiles = build_seat_profiles(billboard)
    p = next(p for p in profiles if p.seat_name == "席位A")
    assert p.next_day_sell_rate == 1.0, (
        f"长假买入→真实下一交易日卖出应 catch（rate=1.0），实得 {p.next_day_sell_rate}（自然日漏判?）"
    )


def test_weekend_next_day_sell_still_caught():
    """周末（周五买→周一卖）修复后仍 catch（非长假日不回归）。"""
    billboard = [
        _row("席位B", "2026-08-14", "buy"),  # 周五
        _row("席位B", "2026-08-17", "sell"),  # 周一（真实下一交易日）
    ]
    profiles = build_seat_profiles(billboard)
    p = next(p for p in profiles if p.seat_name == "席位B")
    assert p.next_day_sell_rate == 1.0


def test_no_next_day_sell_zero_rate():
    """买入但下一交易日未卖（sell 在 index+4+，超出 1-3 宽泛窗口）→ rate=0.0。"""
    billboard = [
        _row("席位C", "2026-08-14", "buy"),
        _row("X", "2026-08-15", "buy"),   # 中间交易日让 08-21 超出 08-14 的 index+1..3
        _row("X", "2026-08-18", "buy"),
        _row("X", "2026-08-19", "buy"),
        _row("席位C", "2026-08-21", "sell"),  # index 4，超出 08-14 的 +1..3（index 1-3）
    ]
    profiles = build_seat_profiles(billboard)
    p = next(p for p in profiles if p.seat_name == "席位C")
    assert p.next_day_sell_rate == 0.0


def test_within_3_real_trade_days_caught():
    """T+2/T+3 真实交易日卖出仍算 next_day_sell（保留 1-3 宽泛语义）。"""
    # 08-14 买，08-16 卖（真实交易日 index+2）
    billboard = [
        _row("席位D", "2026-08-14", "buy"),
        _row("席位D", "2026-08-15", "buy"),  # 连续两日买
        _row("席位D", "2026-08-16", "sell"),
    ]
    profiles = build_seat_profiles(billboard)
    p = next(p for p in profiles if p.seat_name == "席位D")
    # 2 个 buy_date，08-16 在 08-14 的 index+2（catch）+ 08-15 的 index+1（catch）→ 2/2 = 1.0
    assert p.next_day_sell_rate == 1.0


def test_buy_on_last_trade_day_no_next():
    """买入日在最后一交易日（无下一交易日）→ 不算 next_day_sell（不臆造）。"""
    billboard = [
        _row("席位E", "2026-08-21", "buy"),  # 数据中最后一日
    ]
    profiles = build_seat_profiles(billboard)
    p = next(p for p in profiles if p.seat_name == "席位E")
    assert p.next_day_sell_rate == 0.0
