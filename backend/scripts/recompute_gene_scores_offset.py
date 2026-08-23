"""S098 Fix C：重算 gene_scores 表的历史行日期错位（2026-08-17 ~ 08-21）。

根因
----
gene_scores 表历史行存在系统性错位：写入时刻在 T 日晚，用"盘中口径"的东财
池值算了 T+1 的基因（标 T+1），导致每行偏移一个交易日。已用 code 集合相等
验证：

    gene_scores 08-18(106) = zt_history 08-17 的池  ← 错位
    gene_scores 08-19(79)  = zt_history 08-18 的池  ← 错位
    gene_scores 08-20(36)  = zt_history 08-19 的池  ← 错位
    gene_scores 08-21(54)  = 正确（今晚已用显式日期重算过）

08-17 及更早一并重算。

本脚本（一次性，不进 git）
--------------------------
对 ``['2026-08-17','2026-08-18','2026-08-19','2026-08-20','2026-08-21']`` 五日逐日：

  1. DELETE FROM gene_scores WHERE date=? —— 清旧行（INSERT OR REPLACE 不删多余 code，
     若重算前后 code 集合不同会残留旧 code，故先 DELETE）
  2. 清 ``_CACHE`` 对应 ``limitup_screener_{YYYYMMDD}`` 键 + ``_RESOLVED_DATE_CACHE``
     ——独立进程 import 后本为空，防御性清除（成本零）
  3. ``await precompute_daily_async(date)`` 显式传日期 —— 绕 ``_resolve_date`` 缓存；
      传历史交易日，``is_trading_day`` 守卫不拦（08-13/08-14 均为周三/周四非节假日）
  4. 每日之间 ``time.sleep(2)`` —— em_get 防封纪律
  5. 内置验证：行数对照 + code 集合对照（gs(d) == zh(d)）+ updated_at

用法
----
    cd backend && ../.venv/bin/python -m scripts.recompute_gene_scores_offset           # dry-run
    cd backend && ../.venv/bin/python -m scripts.recompute_gene_scores_offset --apply   # 实跑

注意：不改任何运行时代码，只写 ``.vibe-research/gene_scores.db``（私有数据）。

2026-08-23 追加重算
-------------------
fix-18 上轮重算 08-17~08-21 后，发现 08-13/08-14 仍偏移一天：
    gene_scores 08-13(92) = zt_history 08-12 的池  ← 错位
    gene_scores 08-14(59) = zt_history 08-13 的池  ← 错位
本次把 ``TARGET_DATES`` 改为 ``['2026-08-13','2026-08-14']`` 重算对齐。
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GENE_SCORES_DB_PATH  # noqa: E402
from vr_paths import is_trading_day  # noqa: E402

# 重算目标日（2026-08-23 追加：08-13/08-14 偏移一天，需对齐 zt_history 同日）
TARGET_DATES = ["2026-08-13", "2026-08-14"]

# 东财历史交易日池稳定后的最终行数（与 zt_history 最终表 is_final=1 对照一致）
EXPECTED_ROWS = {
    "2026-08-13": 59,
    "2026-08-14": 63,
}

# zt_history.db 路径（与 gene_scores.db 同目录）
ZT_HISTORY_DB_PATH = Path(GENE_SCORES_DB_PATH).parent / "zt_history.db"

# 每日之间 sleep（秒）—— em_get 防封
SLEEP_BETWEEN_DATES = 2.0


def _gs_codes(d: str, conn: sqlite3.Connection) -> set[str]:
    """gene_scores 某日 code 集合。"""
    rows = conn.execute(
        "SELECT code FROM gene_scores WHERE date = ?", (d,)
    ).fetchall()
    return {r[0] for r in rows}


def _zh_codes(d: str, conn: sqlite3.Connection) -> set[str]:
    """zt_history 某日 code 集合（最终稳定池）。"""
    rows = conn.execute(
        "SELECT code FROM zt_history WHERE date = ?", (d,)
    ).fetchall()
    return {r[0] for r in rows}


def _gs_count(d: str, conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM gene_scores WHERE date = ?", (d,)
    ).fetchone()[0]


def _print_before_state(conn: sqlite3.Connection) -> dict[str, int]:
    """打印重算前各日行数，返回 {date: count}。"""
    print("=== 重算前 gene_scores 行数 ===")
    before = {}
    for d in TARGET_DATES:
        cnt = _gs_count(d, conn)
        before[d] = cnt
        exp = EXPECTED_ROWS.get(d)
        flag = "" if cnt == exp else f"  <- 期望 {exp}（错位或未对齐）"
        print(f"  {d}: {cnt}{flag}")
    print()
    return before


async def _recompute_one(d: str) -> int:
    """重算单日，返回新生成的基因得分条数。"""
    from limitup_screener.service import (
        _CACHE,
        _RESOLVED_DATE_CACHE,
        precompute_daily_async,
    )

    # 1. 清 DB 旧行（INSERT OR REPLACE 不删多余 code，必须先 DELETE）
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        cur = conn.execute("DELETE FROM gene_scores WHERE date = ?", (d,))
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    print(f"  [DELETE] {d} 删除旧行 {deleted} 行")

    # 2. 清 _CACHE 对应键（独立进程本为空，防御性）
    date_compact = d.replace("-", "")
    cache_key = f"limitup_screener_{date_compact}"
    _CACHE.pop(cache_key, None)
    _RESOLVED_DATE_CACHE.pop("latest_trading_day", None)

    # 3. is_trading_day 守卫确认（历史交易日应返回 True）
    d_obj = date.fromisoformat(d)
    if not is_trading_day(d_obj):
        print(f"  [SKIP] {d} 非交易日，跳过（守卫拦截）", file=sys.stderr)
        return -1

    # 4. 显式传日期 → precompute_daily_async
    print(f"  [COMPUTE] {d} 开始重算（拉东财池 + 250 天历史 + 算分）...")
    t0 = time.time()
    result = await precompute_daily_async(d)
    elapsed = time.time() - t0

    # 空 ScreenerResult（非交易日守卫返回的）→ 跳过
    n = len(result.gene_scores) if result and result.gene_scores else 0
    print(f"  [COMPUTE] {d} 完成：{n} 条基因得分，耗时 {elapsed:.1f}s")
    return n


async def _run_apply() -> int:
    """实跑：逐日重算。返回退出码（0=成功）。"""
    # 打印重算前状态
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    conn.row_factory = sqlite3.Row
    before = _print_before_state(conn)
    conn.close()

    print("=== 开始重算 ===")
    for i, d in enumerate(TARGET_DATES):
        print(f"[{i+1}/{len(TARGET_DATES)}] {d}")
        try:
            n = await _recompute_one(d)
        except Exception as e:
            print(f"  [ERROR] {d} 重算失败: {e}", file=sys.stderr)
            # 继续下一日，最后统一验证会暴露
        if i < len(TARGET_DATES) - 1:
            print(f"  ...sleep {SLEEP_BETWEEN_DATES}s（em_get 防封）")
            await asyncio.sleep(SLEEP_BETWEEN_DATES)
    print()

    # 验证
    rc = _verify()
    return rc


def _verify() -> int:
    """重算后验证：行数 + code 集合 + updated_at。返回退出码（0=成功，1=有不等）。"""
    print("=== 重算后验证 ===")
    gs_conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    zh_conn = sqlite3.connect(ZT_HISTORY_DB_PATH)

    all_ok = True
    today = date.today().isoformat()

    # a. 行数对照
    print("--- a. 行数对照（gene_scores vs 期望）---")
    for d in TARGET_DATES:
        got = _gs_count(d, gs_conn)
        exp = EXPECTED_ROWS.get(d)
        ok = "OK" if got == exp else "FAIL"
        if got != exp:
            all_ok = False
        print(f"  {d}: {got} （期望 {exp}）[{ok}]")
    print()

    # b. 集合对照（最强校验）
    print("--- b. code 集合对照（gene_scores == zt_history 同日）---")
    for d in TARGET_DATES:
        gs_set = _gs_codes(d, gs_conn)
        zh_set = _zh_codes(d, zh_conn)
        only_gs = gs_set - zh_set
        only_zh = zh_set - gs_set
        if gs_set == zh_set:
            print(f"  {d}: 相等 ({len(gs_set)} == {len(zh_set)}) [OK]")
        else:
            all_ok = False
            print(
                f"  {d}: 不等 [FAIL] gs={len(gs_set)} zh={len(zh_set)} "
                f"only_gs={sorted(only_gs)[:5]}{'...' if len(only_gs)>5 else ''} "
                f"only_zh={sorted(only_zh)[:5]}{'...' if len(only_zh)>5 else ''}"
            )
    print()

    # c. updated_at 应为今天（重算时间戳）
    # SQLite CURRENT_TIMESTAMP 默认 UTC，北京时间凌晨会落在前一 UTC 日。
    # 误差 ±1 日视为通过（重算动作发生在今天才是关注点，非时区精确性）。
    from datetime import date as _date, timedelta as _td
    today_d = _date.today()
    ok_dates = {today_d.isoformat(), (today_d - _td(days=1)).isoformat()}
    print("--- c. updated_at 应为今天（重算时间戳，±1日/UTC）---")
    for d in TARGET_DATES:
        row = gs_conn.execute(
            "SELECT MAX(updated_at) AS ua FROM gene_scores WHERE date = ?", (d,)
        ).fetchone()
        ua = row[0] if row else None
        # updated_at 格式 "YYYY-MM-DD HH:MM:SS"，取前 10 字符比对日期
        ua_date = str(ua)[:10] if ua else ""
        ok = "OK" if ua_date in ok_dates else "FAIL"
        if ua_date not in ok_dates:
            all_ok = False
        print(f"  {d}: updated_at={ua} （日期 {ua_date}，期望 {today_d.isoformat()}±1日/UTC）[{ok}]")

    gs_conn.close()
    zh_conn.close()

    print()
    if all_ok:
        print("[OK] 全部验证通过")
        return 0
    else:
        print("[FAIL] 存在不等项，见上表", file=sys.stderr)
        return 1


def _dry_run() -> int:
    """dry-run：只打印重算前状态 + 计划，不执行。"""
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    conn.row_factory = sqlite3.Row
    _print_before_state(conn)

    # zt_history 对照（基准）
    print("=== zt_history 最终池行数（基准）===")
    zh_conn = sqlite3.connect(ZT_HISTORY_DB_PATH)
    for d in TARGET_DATES:
        cnt = zh_conn.execute(
            "SELECT COUNT(*) FROM zt_history WHERE date = ?", (d,)
        ).fetchone()[0]
        print(f"  {d}: {cnt}")
    zh_conn.close()

    print()
    print("=== 重算计划 ===")
    for d in TARGET_DATES:
        d_obj = date.fromisoformat(d)
        td = is_trading_day(d_obj)
        print(f"  {d}: is_trading_day={td} 期望={EXPECTED_ROWS[d]}")
    print()
    print("[DRY-RUN] 如要实跑，加 --apply")
    print("[注意] 每日 1-3 分钟，五日串行约 5-15 分钟；每日间 sleep 2s 防封")
    conn.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="重算 gene_scores 表历史行日期错位（08-13/08-14）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行重算（默认 dry-run 只打印）",
    )
    args = parser.parse_args()

    db_path = Path(GENE_SCORES_DB_PATH)
    if not db_path.exists():
        print(f"[ERROR] db 不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"db: {db_path}")
    print(f"zt_history: {ZT_HISTORY_DB_PATH}")
    print(f"模式: {'APPLY（实跑）' if args.apply else 'DRY-RUN（只打印）'}")
    print()

    if args.apply:
        rc = asyncio.run(_run_apply())
    else:
        rc = _dry_run()
    sys.exit(rc)


if __name__ == "__main__":
    main()
