# -*- coding: utf-8 -*-
"""S171 R1 数据采集 scan_long_value_cache.py——Layer0.5-4 baostock/akshare 多年 cache。

spec: specs/S171-长线价值/spec.md（R1）。plan: plan.md（§4）。tasks: tasks.md（T2-T7）。

Layer 依赖序（非任意序——Layer1 需 stock_list 先就绪）：
  Layer0.5 query_stock_basic code 前缀过滤 A 股 → stock_basic_type1.json（T2，供 Layer1/2 迭代）
  Layer0   akshare stock_value_em pre-check（可选，PIT 待验 + falsified spot-check，T3）
  Layer1   baostock kline 多年（adjustflag=2 前复权 return 用 + adjustflag=3 不复权 PE 用，bug 1，T4）
  Layer2   baostock profit_data 多年（T5）
  Layer3   query_all_stock 月末 PIT active 集 + type=1 交集 + outDate 二义 + 0bars + 停牌过滤（T6）
  Layer4   benchmark HS300+ZZ500（T7）

cache 存 .vibe-research/（VR_DATA_DIR，.gitignore，不 in git）。atomic write（tmp+os.replace）。
checkpoint per-batch-50 sidecar（tmp+os.replace，防 kill 损坏）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from vr_paths import resolve_data_dir  # noqa: E402

DATA_DIR = resolve_data_dir()  # .vibe-research/
SCRATCH = DATA_DIR / "s171_long_value"
SCRATCH.mkdir(parents=True, exist_ok=True)

# A 股 code 前缀（baostock code 格式 sh.6XXXXXX / sz.000XXX / sz.002XXX / sz.30XXXX / sh.688XXX / bj.XXXXXX）
# 非 type=1 参数（baostock query_stock_basic 签名 (code='', code_name='')——无 type 参数，bug 2 fix）
_A_PREFIXES = ("sh.60", "sh.68", "sz.000", "sz.001", "sz.002", "sz.003", "sh.688", "bj.")


def _atomic_write_json(path: Path, data) -> None:
    """atomic write（tmp+os.replace，POSIX 原子 inode swap）——防 kill 时 truncated JSON（plan §4）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _is_a_share(code: str) -> bool:
    """code 前缀过滤 A 股股票（剔除指数/债券/ETF——query_stock_basic 返所有证券，bug 2）。"""
    return code.startswith(_A_PREFIXES)


def scan_stock_basic() -> dict:
    """Layer0.5：baostock query_stock_basic() 全表 → code 前缀过滤 A 股 → stock_basic_type1.json。

    baostock query_stock_basic(code='', code_name='') 返所有证券（含指数/债券/ETF），
    无 type 参数（spec 原 'type=1 过滤' 无效，bug 2 fix：用 code 前缀）。
    存 {code: {code_name, ipoDate, outDate, type, status}} 供 Layer1/2 迭代 + Layer3 退市元数据。
    退市股数（outDate!=""）须 vs 已知 A 股退市股总数（~300+）交叉验（bug 3 漏标率）。
    """
    import baostock as bs

    cache_path = SCRATCH / "stock_basic_type1.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_bytes())
        print(f"[S171 Layer0.5] cache hit: {len(data)} A 股")
        return data

    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        print(f"[S171 Layer0.5] baostock login fail: {lg.error_code} {lg.error_msg}")
        return {}

    rs = bs.query_stock_basic(code="")
    if rs.error_code != "0":
        print(f"[S171 Layer0.5] query_stock_basic fail: {rs.error_code} {rs.error_msg}")
        bs.logout()
        return {}

    # fields: code, code_name, ipoDate, outDate, type, status
    all_securities = []
    while rs.error_code == "0" and rs.next():
        all_securities.append(rs.get_row_data())

    a_shares = {}
    n_delisted = 0
    for row in all_securities:
        code = row[0]
        if not _is_a_share(code):
            continue
        out_date = row[3] if len(row) > 3 else ""
        if out_date:
            n_delisted += 1
        a_shares[code] = {
            "code_name": row[1],
            "ipoDate": row[2],
            "outDate": out_date,
            "type": row[4] if len(row) > 4 else "",
            "status": row[5] if len(row) > 5 else "",
        }

    _atomic_write_json(cache_path, a_shares)
    bs.logout()
    print(f"[S171 Layer0.5] {len(all_securities)} 证券 → {len(a_shares)} A 股 "
          f"（{n_delisted} 退市 outDate!=''）→ {cache_path}")
    print(f"[S171 Layer0.5] 退市股数 {n_delisted} vs 已知~300+（bug 3 漏标率交叉验）")
    return a_shares


def scan_kline_long() -> dict:
    """Layer1：baostock kline 多年（两套 adjustflag=2+3，bug 1 前复权 PE 致命 fix）。T4。"""
    raise NotImplementedError("T4 待实现：baostock query_history_k_data_plus 全股×2016-2026 两套 adjustflag")


def scan_profit_multiyear() -> dict:
    """Layer2：baostock profit_data 多年（2016-2026×4Q）。T5。"""
    raise NotImplementedError("T5 待实现：baostock query_profit_data 全股×4Q")


def scan_universe_monthly() -> dict:
    """Layer3：query_all_stock 月末 PIT active 集 + type=1 交集 + 退市审计 + 停牌过滤。T6。"""
    raise NotImplementedError("T6 待实现：query_all_stock 月末 PIT + 交集 + outDate 二义 + 0bars + 停牌")


def scan_benchmark() -> dict:
    """Layer4：HS300+ZZ500 2016-2026 日K pctChg。T7。"""
    raise NotImplementedError("T7 待实现：baostock sh.000300+sh.000905 日K")


if __name__ == "__main__":
    # 默认跑 Layer0.5（T2.1，快无依赖）。Layer1-4 通过参数指定（T4-7）。
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--layer", default="0.5", help="0.5 stock_basic / 0 akshare pre-check / 1 kline / 2 profit / 3 universe / 4 benchmark / all")
    args = p.parse_args()

    if args.layer in ("0.5", "all"):
        scan_stock_basic()
    if args.layer in ("1", "all"):
        scan_kline_long()
    if args.layer in ("2", "all"):
        scan_profit_multiyear()
    if args.layer in ("3", "all"):
        scan_universe_monthly()
    if args.layer in ("4", "all"):
        scan_benchmark()
