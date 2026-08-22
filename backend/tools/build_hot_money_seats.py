"""S073 §9 游资画像构建——60 日龙虎榜聚合 → seat_profiles.db 宽表（B 字段）。

datacenter direct fetch（绕 em_get，spec §8.1）；60 日 × 2 report/日（buy+sell）。
跑：.venv/bin/python tools/build_hot_money_seats.py
画像建成 → compute_seat_risk_factor modifier 真扣分（§9.4）；不可达 → 降级 modifier 1.0。
周更为主（spec §9.3），行为突变检测 5 日增量。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.hot_money_seats import (
    fetch_billboard_dates,
    fetch_billboard_for_date,
    build_seat_profiles,
    merge_with_presets,
    save_aggregate_profiles,
)


def main() -> None:
    print("=== 游资画像构建（60 日龙虎榜聚合）===")
    dates = fetch_billboard_dates(60)
    if not dates:
        print("❌ datacenter 不可达或无数据；画像未建（compute_seat_risk_factor 降级 modifier 1.0，用 preset）")
        return

    print(f"获取 {len(dates)} 个龙虎榜交易日（{dates[0]} ~ {dates[-1]}）")
    all_data: list[dict] = []
    for i, d in enumerate(dates):
        rows = fetch_billboard_for_date(d)
        all_data.extend(rows)
        print(f"  [{i + 1}/{len(dates)}] {d}: {len(rows)} 明细")
        if (i + 1) % 10 == 0:
            print(f"  累计 {len(all_data)} 条")

    print(f"合并 {len(all_data)} 条买卖明细")
    if not all_data:
        print("❌ 无明细数据；画像未建")
        return

    profiles = build_seat_profiles(all_data)
    merged = merge_with_presets(profiles)
    save_aggregate_profiles(merged)
    print(f"✅ 画像构建：{len(merged)} 席位 → seat_profiles.db")

    by_type: dict[str, int] = {}
    for p in merged:
        by_type[p.seat_type] = by_type.get(p.seat_type, 0) + 1
    print(f"分类：{by_type}")
    print(f"source 分布：data={sum(1 for p in merged if p.source == 'data')}, preset={sum(1 for p in merged if p.source == 'preset')}")


if __name__ == "__main__":
    main()
