# -*- coding: utf-8 -*-
"""S188 B · 变动量 Multi-Level OFI CSV 验证脚本。

读用户下载的 A 股五档快照 CSV（bid_p1..5/ask_p1..5/bid_v1..5/ask_v1..5）→
跑 compute_multi_level_ofi（Cont 2014 变动量，跳档判断）→ 输出 per-level OFI + total。

剔除集合竞价（09:15-09:25 / 14:57-15:00），只算连续竞价段。

用法：
  python tools/multi_ofi_csv_validate.py /Users/lizhiwei/Downloads/as_market_test_data.csv
  python tools/multi_ofi_csv_validate.py <csv> --output result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
from engine.intraday_ofi import compute_multi_level_ofi, is_auction_period  # noqa: E402


def _extract_levels(row: pd.Series, side: str, kind: str, levels: int = 5) -> list[float]:
    """从 row 取 bid_p1..5 / ask_v1..5 等。side=bid|ask, kind=p|v。"""
    out = []
    for i in range(1, levels + 1):
        col = f"{side}_{kind}{i}"
        v = row.get(col)
        try:
            out.append(float(v) if v is not None else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def validate_csv(csv_path: str, levels: int = 5) -> dict:
    """读 CSV → 逐行算变动量 OFI → 返结果。"""
    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns:
        return {"error": "CSV 缺 timestamp 列"}

    # 剔除集合竞价
    mask = df["timestamp"].apply(lambda ts: not is_auction_period(str(ts)))
    auction_dropped = len(df) - mask.sum()
    df = df[mask].reset_index(drop=True)

    records = []
    for i in range(1, len(df)):
        prev, curr = df.iloc[i - 1], df.iloc[i]
        per_level, total = compute_multi_level_ofi(
            _extract_levels(prev, "bid", "p", levels),
            _extract_levels(prev, "bid", "v", levels),
            _extract_levels(prev, "ask", "p", levels),
            _extract_levels(prev, "ask", "v", levels),
            _extract_levels(curr, "bid", "p", levels),
            _extract_levels(curr, "bid", "v", levels),
            _extract_levels(curr, "ask", "p", levels),
            _extract_levels(curr, "ask", "v", levels),
            levels=levels,
        )
        records.append({
            "timestamp": str(curr["timestamp"]),
            "ofi_levels": [round(x, 1) for x in per_level],
            "total_ofi": round(total, 1),
            "buy_pressure": int(sum(_extract_levels(curr, "bid", "v", levels))),
            "sell_pressure": int(sum(_extract_levels(curr, "ask", "v", levels))),
        })

    # 统计
    totals = [r["total_ofi"] for r in records]
    positive_ticks = sum(1 for t in totals if t > 0)
    negative_ticks = sum(1 for t in totals if t < 0)
    zero_ticks = sum(1 for t in totals if t == 0)
    return {
        "csv": csv_path,
        "total_ticks": len(records),
        "auction_dropped": int(auction_dropped),
        "ofi_positive_ticks": positive_ticks,
        "ofi_negative_ticks": negative_ticks,
        "ofi_zero_ticks": zero_ticks,
        "mean_total_ofi": round(sum(totals) / len(totals), 1) if totals else 0,
        "max_total_ofi": round(max(totals), 1) if totals else 0,
        "min_total_ofi": round(min(totals), 1) if totals else 0,
        "per_tick": records[:10],  # 前 10 tick 展示
    }


def main() -> None:
    p = argparse.ArgumentParser(description="S188 B · Multi-Level OFI CSV 验证")
    p.add_argument("csv", help="五档快照 CSV 路径")
    p.add_argument("--output", default=None, help="结果落盘 JSON 路径（默认只 print）")
    args = p.parse_args()

    result = validate_csv(args.csv)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n落盘: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
