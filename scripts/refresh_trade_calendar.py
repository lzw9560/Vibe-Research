# -*- coding: utf-8 -*-
"""刷新 A 股交易日历缓存（holidays.json）。

数据源：akshare ``tool_trade_date_hist_sina()``（新浪财经交易日历）。
产出：更新 ``backend/data/holidays.json`` 的 ``non_trading_days`` 字段
（工作日但休市的日期，即法定节假日落在工作日的部分），并刷新 ``_meta.updated``。

向后兼容：保留 ``calendar_factor.py`` 依赖的 ``holidays_2026`` /
``pre_holiday_last_trading_day`` / ``post_holiday_first_trading_day`` 字段不动。

用法：
    python3 scripts/refresh_trade_calendar.py           # 拉取并更新
    python3 scripts/refresh_trade_calendar.py --dry-run # 只预览不写

退出码：0 成功；1 akshare 拉取失败；2 文件写失败。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

#: holidays.json 路径（与 vr_paths._HOLIDAYS_JSON_PATH 一致）
HOLIDAYS_JSON = Path(__file__).resolve().parent.parent / "backend" / "data" / "holidays.json"

#: 缓存近 N 年的非交易日（工作日休市日）。akshare 数据范围决定上限。
#: 存近 2 年足够覆盖 is_trading_day 的近期查询（今天/前后交易日）。
CACHE_YEARS = 2


def fetch_trade_days() -> list[date]:
    """用 akshare 拉取 A 股交易日历，返回 date 对象列表。

    akshare 失败时抛异常，由调用方处理。
    """
    import akshare as ak  # 延迟导入，避免模块加载时触发网络

    df = ak.tool_trade_date_hist_sina()
    # trade_date 列是 datetime.date 对象（已验证）
    return list(df["trade_date"])


def derive_non_trading_days(trade_days: list[date]) -> list[str]:
    """从交易日列表反推"工作日但休市"的日期（法定节假日落在工作日的部分）。

    - 周末（周六/周日）不列入（is_trading_day 已由 weekday >= 5 排除）。
    - 调休补班日（周末但交易）不在 trade_days 的补班判断范围内——
      本函数只产 non_trading_days，补班日处理留扩展位。
    - 只取最近 CACHE_YEARS 年的数据，避免文件膨胀。

    返回排序后的 YYYY-MM-DD 字符串列表。
    """
    trade_set = set(trade_days)
    if not trade_set:
        return []
    max_year = max(d.year for d in trade_days)
    # 取有数据的最近 CACHE_YEARS 年（避免对无数据年份臆造非交易日）
    years_with_data = sorted({d.year for d in trade_days})
    target_years = years_with_data[-CACHE_YEARS:]
    non_trading: list[str] = []
    for y in target_years:
        cur = date(y, 1, 1)
        end = date(y, 12, 31)
        while cur <= end:
            # 工作日（周一至周五）且不在交易日列表 → 法定节假日休市
            if cur.weekday() < 5 and cur not in trade_set:
                non_trading.append(cur.isoformat())
            cur += timedelta(days=1)
    return non_trading


def update_holidays_json(non_trading: list[str], dry_run: bool = False) -> dict:
    """更新 holidays.json：保留原有字段，写入 non_trading_days + 刷新 _meta。

    返回更新后的 dict（供调用方打印摘要）。
    """
    # 读取现有内容（保留 calendar_factor 依赖的字段）
    if HOLIDAYS_JSON.exists():
        data = json.loads(HOLIDAYS_JSON.read_text(encoding="utf-8"))
    else:
        data = {}

    today_str = date.today().isoformat()
    # 溯源 akshare
    data.setdefault("_meta", {})
    data["_meta"]["updated"] = today_str
    data["_meta"]["source"] = "akshare tool_trade_date_hist_sina + 国务院放假安排"
    # 新增交易日历范围元信息
    if non_trading:
        years = sorted({d[:4] for d in non_trading})
        data["_meta"]["trade_calendar_range"] = f"{years[0]}-{years[-1]}"
    data["_meta"]["non_trading_days_note"] = (
        "工作日但休市的日期（法定节假日落在周一至周五的部分）。"
        "周末由 is_trading_day 的 weekday 判断覆盖，不重复列。"
        "由 scripts/refresh_trade_calendar.py 从 akshare 交易日历反推生成。"
    )

    data["non_trading_days"] = non_trading

    if not dry_run:
        HOLIDAYS_JSON.parent.mkdir(parents=True, exist_ok=True)
        HOLIDAYS_JSON.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新 A 股交易日历缓存")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写文件")
    args = parser.parse_args()

    print("[refresh] 拉取 akshare 交易日历 ...")
    try:
        trade_days = fetch_trade_days()
    except Exception as e:
        print(f"[refresh] akshare 拉取失败: {e}", file=sys.stderr)
        print("[refresh] 提示：vr_paths 会 fallback 到硬编码 _A_SHARE_HOLIDAYS", file=sys.stderr)
        return 1

    print(f"[refresh] akshare 返回 {len(trade_days)} 个交易日")
    print(f"[refresh] 数据范围: {min(trade_days)} ~ {max(trade_days)}")

    non_trading = derive_non_trading_days(trade_days)
    print(f"[refresh] 推导出 {len(non_trading)} 个工作日休市日（近 {CACHE_YEARS} 年）")

    data = update_holidays_json(non_trading, dry_run=args.dry_run)

    # 摘要
    meta = data.get("_meta", {})
    print("\n========== holidays.json 摘要 ==========")
    print(f"updated:           {meta.get('updated')}")
    print(f"source:            {meta.get('source')}")
    print(f"calendar_range:    {meta.get('trade_calendar_range', 'N/A')}")
    print(f"non_trading_days:  {len(non_trading)} 条")
    if non_trading:
        years = {}
        for d in non_trading:
            y = d[:4]
            years[y] = years.get(y, 0) + 1
        for y in sorted(years):
            print(f"  {y} 年: {years[y]} 个工作日休市日")
        print(f"  示例（前 10）: {non_trading[:10]}")
    if args.dry_run:
        print("\n[dry-run] 未写入文件。去掉 --dry-run 实际更新。")
    else:
        print(f"\n[refresh] 已写入 {HOLIDAYS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
