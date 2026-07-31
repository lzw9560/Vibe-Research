#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
financial_rigor.py — 金融数据程序化验算工具（项目内集成版）

源自 ~/tools/financial_rigor.py，集成进 backend/tools/ 供 S002 AC5 复算。
全部用 Decimal 精确十进制，禁止浮点心算。输出 JSON + 人类可读摘要。

子命令：
  verify-market-cap   手工验算 市值 = 股价 × 总股本，与报告市值对比（阈值 5%）
  cross-validate      多源交叉验证单一字段（≤1% ✅ / 1-5% ⚠️ / >5% ❌）
  verify-valuation    精确计算 PE / PB / FCF Yield / 股息率
  three-scenario      乐观/基准/悲观三情景估值
  verify-activity-tier  S002 AC5：独立重算活跃度分档，对照系统报告 tier
"""

import argparse
import json
import sys
from decimal import Decimal, getcontext, InvalidOperation

getcontext().prec = 28

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------- 工具函数 ----------

def to_decimal(x, name="value"):
    """安全转 Decimal，容忍千分位逗号与百分号。"""
    if x is None or x == "":
        return None
    s = str(x).strip().replace(",", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        print("错误: {} 无法解析为数值: {!r}".format(name, x), file=sys.stderr)
        sys.exit(2)


def pct_deviation(a, b):
    a, b = to_decimal(a), to_decimal(b)
    if a is None or a == 0:
        return None
    return abs(a - b) / abs(a) * Decimal(100)


def fmt(x, places=4):
    if x is None:
        return None
    q = Decimal(10) ** -places
    return str(x.quantize(q))


# ---------- 1. verify-market-cap ----------

def cmd_verify_market_cap(args):
    price = to_decimal(args.price, "price")
    reported = to_decimal(args.reported, "reported")
    shares_raw = to_decimal(args.shares, "shares")
    if args.shares_unit == "亿":
        shares_actual = shares_raw * Decimal(10) ** 8
        computed_mc_yi = price * shares_raw
    else:
        shares_actual = shares_raw
        computed_mc_yi = (price * shares_raw) / Decimal(10) ** 8
    reported_yi = reported if args.reported_unit == "亿" else reported / Decimal(10) ** 8
    dev = pct_deviation(computed_mc_yi, reported_yi)
    threshold = Decimal(args.threshold)
    verdict = "✅ 一致" if dev is not None and dev <= threshold else "❌ 偏差过大"
    out = {
        "command": "verify-market-cap", "currency": args.currency,
        "price": str(price),
        "shares": {"raw": str(shares_raw), "unit": args.shares_unit, "actual": str(shares_actual)},
        "computed_market_cap_yi": fmt(computed_mc_yi, 4),
        "reported_market_cap_yi": fmt(reported_yi, 4),
        "deviation_pct": fmt(dev, 4), "threshold_pct": str(threshold), "verdict": verdict,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- 2. cross-validate ----------

def cmd_cross_validate(args):
    values = json.loads(args.values)
    field = args.field
    unit = args.unit
    parsed = {s: to_decimal(v, s) for s, v in values.items()}
    items = [(s, v) for s, v in parsed.items() if v is not None]
    if len(items) < 2:
        print(json.dumps({"command": "cross-validate", "field": field,
                          "error": "至少需要 2 个有效数值"}, ensure_ascii=False, indent=2))
        sys.exit(2)
    base_src, base_val = items[0]
    deviations = []
    for src, val in items[1:]:
        dev = pct_deviation(base_val, val)
        deviations.append({"vs": src, "value": fmt(val, 6), "deviation_pct": fmt(dev, 4)})
    max_dev = max((Decimal(d["deviation_pct"]) for d in deviations if d["deviation_pct"] is not None),
                  default=Decimal(0))
    if max_dev <= Decimal(1):
        verdict = "✅ 一致（≤1%）"
    elif max_dev <= Decimal(5):
        verdict = "⚠️ 数据存在差异（1-5%）"
    else:
        verdict = "❌ 数据存在重大差异（>5%），须查原始财报"
    out = {
        "command": "cross-validate", "field": field, "unit": unit,
        "sources": {s: fmt(v, 6) for s, v in parsed.items()},
        "deviations": deviations, "max_deviation_pct": fmt(max_dev, 4),
        "adopted_value": fmt(base_val, 6), "verdict": verdict,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- 3. verify-valuation ----------

def cmd_verify_valuation(args):
    price = to_decimal(args.price, "price")
    eps = to_decimal(args.eps, "eps") if args.eps else None
    bvps = to_decimal(args.bvps, "bvps") if args.bvps else None
    fcfps = to_decimal(args.fcf_per_share, "fcf-per-share") if args.fcf_per_share else None
    div = to_decimal(args.dividend, "dividend") if args.dividend else None
    metrics = {}
    if eps:
        metrics["PE"] = fmt(price / eps, 4)
    if bvps:
        metrics["PB"] = fmt(price / bvps, 4)
    if fcfps:
        metrics["FCF_yield_pct"] = fmt(fcfps / price * Decimal(100), 4)
    if div:
        metrics["dividend_yield_pct"] = fmt(div / price * Decimal(100), 4)
    out = {"command": "verify-valuation", "currency": args.currency,
           "price": str(price),
           "inputs": {"eps": str(eps), "bvps": str(bvps),
                      "fcf_per_share": str(fcfps), "dividend": str(div)},
           "metrics": metrics}
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- 4. three-scenario ----------

def cmd_three_scenario(args):
    price = to_decimal(args.price, "price")
    eps = to_decimal(args.eps, "eps")
    shares_yi = to_decimal(args.shares, "shares(亿)")
    years = int(args.years)
    growths = [to_decimal(g, "growth") for g in args.growth]
    pes = [to_decimal(p, "pe") for p in args.pe]
    if len(growths) != 3 or len(pes) != 3:
        print("需要 3 个 growth 与 3 个 pe", file=sys.stderr)
        sys.exit(2)
    labels = ["乐观", "基准", "悲观"]
    discount = to_decimal(args.discount, "discount") if args.discount else None
    current_mc_yi = price * shares_yi
    scenarios = []
    for i in range(3):
        g, pe = growths[i], pes[i]
        factor = (Decimal(1) + g) ** years
        future_eps = eps * factor
        future_net_profit_yi = future_eps * shares_yi
        future_mc_yi = future_net_profit_yi * pe
        target_price = future_mc_yi / shares_yi
        ann_return = (target_price / price) ** (Decimal(1) / Decimal(years)) - Decimal(1)
        entry = {
            "label": labels[i], "growth_cagr_pct": fmt(g * 100, 2),
            "target_pe": str(pe), "future_eps": fmt(future_eps, 4),
            "future_net_profit_yi": fmt(future_net_profit_yi, 4),
            "future_market_cap_yi": fmt(future_mc_yi, 4),
            "target_price": fmt(target_price, 2),
            "implied_annual_return_pct": fmt(ann_return * 100, 2),
        }
        if discount is not None:
            disc_factor = (Decimal(1) + discount) ** years
            fair_value_now = future_mc_yi / disc_factor
            entry["discount_rate_pct"] = fmt(discount * 100, 2)
            entry["fair_value_now_yi"] = fmt(fair_value_now, 4)
            entry["fair_value_price_now"] = fmt(fair_value_now / shares_yi, 2)
        scenarios.append(entry)
    out = {"command": "three-scenario", "currency": args.currency,
           "price": str(price), "eps": str(eps), "shares_yi": str(shares_yi),
           "current_market_cap_yi": fmt(current_mc_yi, 4), "years": years,
           "scenarios": scenarios}
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------- 5. verify-activity-tier (S002 AC5) ----------

def verify_activity_tier(turnover, vol_ratio, amount_yi, amplitude,
                         turnover_cold, turnover_hot, vol_ratio_active,
                         amount_yi_min, amplitude_high, reported_tier):
    """独立重算活跃度分档（Decimal，spec §5.2 规则），对照系统报告 tier。

    规则：换手 >= hot → 热；>= cold → 活跃；< cold → 冷；缺失 → 冷。
    与 candidate_funnel.diagnosis.assess_activity 同规则、独立实现，便于复算。
    返回 dict：recomputed_tier / reported_tier / consistent / verdict / rules。
    """
    t = to_decimal(turnover, "turnover") if turnover is not None else None
    cold = to_decimal(turnover_cold, "turnover_cold")
    hot = to_decimal(turnover_hot, "turnover_hot")
    rules = []
    if t is None:
        recomputed = "冷"
        rules.append("换手未取得")
    elif t >= hot:
        recomputed = "热"
        rules.append("换手>={}%".format(turnover_hot))
    elif t >= cold:
        recomputed = "活跃"
        rules.append("换手>={}%".format(turnover_cold))
    else:
        recomputed = "冷"
        rules.append("换手<{}%".format(turnover_cold))

    vr = to_decimal(vol_ratio, "vol_ratio") if vol_ratio is not None else None
    amt = to_decimal(amount_yi, "amount_yi") if amount_yi is not None else None
    amp = to_decimal(amplitude, "amplitude") if amplitude is not None else None
    if vr is not None and vr >= to_decimal(vol_ratio_active):
        rules.append("量比>={}".format(vol_ratio_active))
    if amt is not None and amt >= to_decimal(amount_yi_min):
        rules.append("成交额>={}亿".format(amount_yi_min))
    if amp is not None and amp >= to_decimal(amplitude_high):
        rules.append("振幅>={}%".format(amplitude_high))

    consistent = (recomputed == reported_tier)
    return {
        "command": "verify-activity-tier",
        "inputs": {"turnover": str(t), "vol_ratio": str(vr),
                   "amount_yi": str(amt), "amplitude": str(amp)},
        "thresholds": {"turnover_cold": str(cold), "turnover_hot": str(hot),
                       "vol_ratio_active": str(vol_ratio_active),
                       "amount_yi_min": str(amount_yi_min),
                       "amplitude_high": str(amplitude_high)},
        "recomputed_tier": recomputed,
        "reported_tier": reported_tier,
        "rules": rules,
        "consistent": consistent,
        "verdict": "✅ 一致" if consistent else "❌ 不一致",
    }


def cmd_verify_activity_tier(args):
    r = verify_activity_tier(
        turnover=args.turnover, vol_ratio=args.vol_ratio,
        amount_yi=args.amount_yi, amplitude=args.amplitude,
        turnover_cold=args.turnover_cold, turnover_hot=args.turnover_hot,
        vol_ratio_active=args.vol_ratio_active,
        amount_yi_min=args.amount_yi_min, amplitude_high=args.amplitude_high,
        reported_tier=args.reported_tier,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("\n[活跃度复算] 重算 {} vs 报告 {} → {}".format(
        r["recomputed_tier"], r["reported_tier"], r["verdict"]))


# ---------- main ----------

def main():
    p = argparse.ArgumentParser(description="金融数据程序化验算工具")
    sub = p.add_subparsers(dest="cmd")

    pm = sub.add_parser("verify-market-cap")
    pm.add_argument("--price", required=True)
    pm.add_argument("--shares", required=True, help="总股本（默认单位亿）")
    pm.add_argument("--shares-unit", choices=["亿", "股"], default="亿")
    pm.add_argument("--reported", required=True, help="报告市值")
    pm.add_argument("--reported-unit", choices=["亿", "元"], default="亿")
    pm.add_argument("--currency", default="CNY")
    pm.add_argument("--threshold", default="5", help="市值验算阈值，默认5%")
    pm.set_defaults(func=cmd_verify_market_cap)

    pc = sub.add_parser("cross-validate")
    pc.add_argument("--field", required=True)
    pc.add_argument("--values", required=True, help='JSON: {"来源1":数值,"来源2":数值}')
    pc.add_argument("--unit", default="")
    pc.set_defaults(func=cmd_cross_validate)

    pv = sub.add_parser("verify-valuation")
    pv.add_argument("--price", required=True)
    pv.add_argument("--eps")
    pv.add_argument("--bvps")
    pv.add_argument("--fcf-per-share")
    pv.add_argument("--dividend")
    pv.add_argument("--currency", default="CNY")
    pv.set_defaults(func=cmd_verify_valuation)

    pt = sub.add_parser("three-scenario")
    pt.add_argument("--price", required=True)
    pt.add_argument("--eps", required=True)
    pt.add_argument("--shares", required=True, help="总股本(亿)")
    pt.add_argument("--growth", nargs=3, required=True, metavar=("乐观", "中性", "悲观"))
    pt.add_argument("--pe", nargs=3, required=True, metavar=("乐观PE", "中性PE", "悲观PE"))
    pt.add_argument("--years", default="3")
    pt.add_argument("--currency", default="CNY")
    pt.add_argument("--discount", help="可选折现率")
    pt.set_defaults(func=cmd_three_scenario)

    pa = sub.add_parser("verify-activity-tier")
    pa.add_argument("--turnover")
    pa.add_argument("--vol-ratio")
    pa.add_argument("--amount-yi")
    pa.add_argument("--amplitude")
    pa.add_argument("--turnover-cold", default="8")
    pa.add_argument("--turnover-hot", default="20")
    pa.add_argument("--vol-ratio-active", default="2")
    pa.add_argument("--amount-yi-min", default="10")
    pa.add_argument("--amplitude-high", default="8")
    pa.add_argument("--reported-tier", required=True, choices=["冷", "活跃", "热"])
    pa.set_defaults(func=cmd_verify_activity_tier)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
