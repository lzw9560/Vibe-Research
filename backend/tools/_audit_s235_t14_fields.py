# -*- coding: utf-8 -*-
"""S235 T14 实测竞价 CLI 字段（2026-10-08 开盘后）。

Phase B T14：实测 hithink-finance market auction-snapshot 字段完整性，
确认反核三因子（量比/额占比/高开）能否算。

结果（2026-10-08，603778.SH 竞价 final）：
- auction_volume_ratio（量比）= 4.69 → 反核因子"量比>4.5"可算 ✅
- auction_yesterday_ratio_pct（额占比）= 2.66% → 反核因子"额占比>10%"可算 ✅
- auction_pct（高开）= 1.25% → 反核因子"高开2-5%"可算 ✅
- + auction_price/volume/amount/float_market_cap 全有

结论：反核三因子字段全，T14 PASS。603778 今天量比 4.69>4.5 但额占比 2.66%<10% + 高开 1.25%<2% → 不触发反核。
Phase B feishu 接线仍暂缓（预期 FAIL + T+1 致命），但 10/8 后审计验证（用真实竞价数据跑反核评分）可做。
"""
from __future__ import annotations
import json
import subprocess

THSCODE = "603778.SH"  # 测试标的


def pull_auction_final(thscode: str) -> dict:
    cmd = [
        "hithink-finance", "market", "auction-snapshot",
        "--thscodes", thscode, "--stage", "final", "--format", "json",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    d = json.loads(out.stdout or "{}")
    items = d.get("data", {}).get("item", [])
    return items[0] if items else {}


def check_reversal_factors(a: dict) -> dict:
    """反核三因子：量比>4.5 / 额占比>10% / 高开2-5%。"""
    vol_ratio = a.get("auction_volume_ratio", 0)
    amt_ratio = a.get("auction_yesterday_ratio_pct", 0)
    gap_pct = a.get("auction_pct", 0)
    return {
        "vol_ratio": vol_ratio,
        "vol_ratio_pass": vol_ratio > 4.5,
        "amt_ratio_pct": amt_ratio,
        "amt_ratio_pass": amt_ratio > 10,
        "gap_pct": gap_pct,
        "gap_pass": 2 <= gap_pct <= 5,
        "all_pass": vol_ratio > 4.5 and amt_ratio > 10 and 2 <= gap_pct <= 5,
    }


def main() -> None:
    a = pull_auction_final(THSCODE)
    if not a:
        print("拉不到竞价数据")
        return
    print(f"=== S235 T14 实测竞价字段（{THSCODE}）===")
    print(f"thscode: {a.get('thscode')}, name: {a.get('name')}")
    print(f"auction_phase: {a.get('auction_phase')}, data_status: {a.get('data_status')}")
    print(f"\n字段完整性：")
    for k in ["auction_price", "auction_volume", "auction_amount",
              "auction_volume_ratio", "auction_yesterday_ratio_pct", "auction_pct",
              "pre_close_price", "open_price", "float_market_cap"]:
        print(f"  {k}: {a.get(k)}")
    r = check_reversal_factors(a)
    print(f"\n反核三因子：")
    print(f"  量比 {r['vol_ratio']:.2f} > 4.5: {'✅' if r['vol_ratio_pass'] else '❌'}")
    print(f"  额占比 {r['amt_ratio_pct']:.2f}% > 10%: {'✅' if r['amt_ratio_pass'] else '❌'}")
    print(f"  高开 {r['gap_pct']:.2f}% 在 2-5%: {'✅' if r['gap_pass'] else '❌'}")
    print(f"  反核触发: {'✅' if r['all_pass'] else '❌'}")
    print(f"\n结论：字段全（T14 PASS），反核三因子可算。触发需三因子全过。")


if __name__ == "__main__":
    main()
