# -*- coding: utf-8 -*-
"""baostock query_stock_basic 生成 stock_basic_type1.json（含 outDate 退市，供 R13 survivorship）。

scan_long_value_cache.py Layer0.5 委托 baostock_src.fetch_stock_basic，
但 stock_basic_type1.json 不存在（须生成）。
本脚本直接 baostock query_stock_basic() 全表 → code 前缀过滤 A 股 → 存 .vibe-research。
fields: code, code_name, ipoDate, outDate, type, status（query_stock_basic 返 6 字段，非 query_all_stock 的 3 字段）。
anonymous login（baostock 免费）。
"""

import json
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
OUT = DATA / "stock_basic_type1.json"


def is_a_share(code: str) -> bool:
    """A 股 code 前缀过滤（sh.6/sz.0/sz.3/bj.4/bj.8 主板/创业板/北交所）。"""
    c = code.replace("sh.", "").replace("sz.", "").replace("bj.", "")
    if len(c) != 6:
        return False
    return c[0] in ("6", "0", "3", "4", "8")


def main() -> None:
    import baostock as bs  # noqa: PLC0415

    lg = bs.login()
    print(f"login: {lg.error_code} {lg.error_msg}")
    if lg.error_code != "0":
        print(f"login 失败: {lg.error_msg}")
        return

    rs = bs.query_stock_basic()
    print(f"query_stock_basic: {rs.error_code} {rs.error_msg}")
    fields = rs.fields
    print(f"fields: {fields}")

    stock_basic: dict = {}
    while rs.next():
        row = rs.get_row_data()
        code = row[0] if len(row) > 0 else ""
        if not is_a_share(code):
            continue
        # 字段顺序按 rs.fields
        info = {}
        for i, f in enumerate(fields):
            info[f] = row[i] if i < len(row) else ""
        stock_basic[code] = info

    bs.logout()

    delisted = sum(1 for v in stock_basic.values() if v.get("outDate"))
    print(f"A 股总数: {len(stock_basic)}, 退市(outDate非空): {delisted}")
    OUT.write_text(json.dumps(stock_basic, ensure_ascii=False))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
