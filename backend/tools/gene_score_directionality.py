# -*- coding: utf-8 -*-
# ⚠️ §44 v2 窗口caveat（2026-09-06）：top-gene"劣于随机"基于 forward path-winrate（D+1-开盘→D+4，隔夜正之后的反转负段），非绝对无 edge——是"对窗口无 selection edge"。gap_window_lift.py 证 gene_score 也不预测隔夜 gap（lift 0.942x, pearson -0.075）——对窗口也验证无选股力，真非 bug。见 S159 + memory s44-quant-validation-loop。
"""§44 后续研究：gene total_score 是否方向性预测 forward path-winrate？

动机（2026-09-03，S145 收尾后）：
  §44 verdict 已 robust：breakout 选股 path_lift<1（0.87-0.97，5 组 params），top-gene picks
  劣于随机。敏感性显示"越松出场越接近 1"——暗示 top-gene picks 波动更大，可能反向预测
  （高分=追涨=过度乐观=均值回归伤它）。若低分 bucket 反而 winrate 更高，则 score 方向性
  是真信号，且解释了"top-gene 坏"。

设计（§44-consistent，read-only，不碰 pipeline）：
  substrate = universe_returns（全体涨停股，完整 score 分布；picks 仅窄顶片不适合测方向）。
  - WHERE return_path IS NOT NULL AND is_unbuyable=0 AND is_win_path IS NOT NULL（§44 口径）
  - JOIN gene_scores ON date=signal_date, code → total_score
  - **rank-within-date** decile（NTILE(10) OVER PARTITION BY signal_date ORDER BY total_score）
    decile 10 = 最高分。rank-within-date 消"某日整体分偏高"跨日混淆。
  - 缺 total_score 的行（gene_scores 数据缺口，非系统性弱股）排除，缺口率报出。
  每 decile：n / wins / path_winrate / Wilson 95% CI。
  单调性：Spearman rho（decile 序 vs path_winrate）。
  Confounder 报出：
    - 每 decile 的 unbuyable 率（高分若更易一字板封死→"更差"是 survivorship 假象）

用法：python tools/gene_score_directionality.py
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from config import GENE_SCORES_DB_PATH
from strategies.forward_test import _ensure_table, _wilson

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gene_directionality")

N_DECILES = 10


def _wilson_pct(wins: int, n: int) -> tuple[float, float]:
    """Wilson 95% CI，返百分点 [lo, hi]（_wilson 返分数，×100）。n=0 返 (0,0)。"""
    lo, hi = _wilson(wins, n)
    return lo * 100, hi * 100


def _spearman_rho(xs: list[float], ys: list[float]) -> float:
    """Spearman = Pearson on ranks。decile 序已 1..N，winrate 取秩。
    手算避 numpy/scipy 依赖。-1 反向单调，+1 正向，0 无单调。"""
    if len(xs) < 3 or len(set(ys)) < 2:
        return 0.0

    def ranks(vals: list[float]) -> list[float]:
        idx = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(vals):
            j = i
            while j + 1 < len(vals) and vals[idx[j + 1]] == vals[idx[i]]:
                j += 1
            avg = (i + j) / 2 + 1  # 1-indexed 平均秩
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    return num / dx / dy if dx and dy else 0.0


def main() -> int:
    _ensure_table()
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        # 全部 joined universe 行（含 unbuyable，per-date 统一分位）
        # 注意：unbuyable 行 return_path=NULL（不可买不模拟），故查询**不**滤 return_path，
        # 否则 unbuyable confounder 永远为 0（之前 bug：unbuyable% 全 0 即此）。
        # is_unbuyable → confounder；is_win_path → 主 winrate（仅 buyable+settled）
        rows = conn.execute("""
            SELECT u.signal_date, u.code, g.total_score,
                   u.is_unbuyable, u.is_win_path
            FROM universe_returns u
            JOIN gene_scores g ON g.date = u.signal_date AND g.code = u.code
            WHERE g.total_score IS NOT NULL
            ORDER BY u.signal_date, g.total_score
        """).fetchall()
    finally:
        conn.close()

    from collections import defaultdict
    by_date: dict[str, list[tuple]] = defaultdict(list)
    for d, code, score, unb, won in rows:
        by_date[d].append((code, score, 1 if unb else 0, won))
    # per-date decile（1=低分..10=高分），rank-within-date 消跨日 score 偏移
    # 含 unbuyable 一起分位 → 高分若更易封死，高 decile unbuyable 率高（survivorship 信号）
    dec_rows: list[tuple[str, int, int, int]] = []  # date, decile, is_unbuyable, is_win_path(-1=unsettled/None)
    for d, items in by_date.items():
        items.sort(key=lambda x: x[1])  # 升序（低→高）
        n = len(items)
        for i, (code, _score, unb, won) in enumerate(items):
            dec = min(N_DECILES, (i * N_DECILES) // n + 1)  # 1..10
            dec_rows.append((d, dec, unb, -1 if won is None else (1 if won else 0)))
    # 每 decile 聚合
    # n_total = 全体分位行（buyable+unbuyable+unsettled）；n_unb = 不可买；n_buy_settled = 可买且有 path
    stats: dict[int, dict] = {d: {"n_buy": 0, "wins": 0, "n_total": 0, "n_unb": 0}
                               for d in range(1, N_DECILES + 1)}
    for _d, dec, unb, won in dec_rows:
        stats[dec]["n_total"] += 1
        if unb:
            stats[dec]["n_unb"] += 1
        elif won != -1:  # buyable + settled（is_win_path NOT NULL）
            stats[dec]["n_buy"] += 1
            if won == 1:
                stats[dec]["wins"] += 1

    # ---- 输出 ----
    total_n = sum(s["n_buy"] for s in stats.values())
    total_wins = sum(s["wins"] for s in stats.values())
    overall_wr = total_wins / total_n * 100 if total_n else 0.0
    decile_nums = list(range(1, N_DECILES + 1))
    winrates = [stats[d]["wins"] / stats[d]["n_buy"] * 100 if stats[d]["n_buy"] else 0.0
                for d in decile_nums]

    print("\n" + "=" * 92)
    print("gene total_score 方向性分析：universe 按 rank-within-date decile 分桶")
    print(f"substrate = universe_returns（全体涨停，§44 口径：buyable + path-settled）")
    print(f"n_dates={len(by_date)} | buyable_joined={total_n} | overall_path_winrate={overall_wr:.2f}%")
    print("=" * 92)
    print(f"{'decile':<8}{'score_band':<10}{'n_buy':<8}{'wins':<8}{'winrate%':<11}{'95% CI':<20}{'unbuy%':<8}")
    print("-" * 92)
    for d in decile_nums:
        s = stats[d]
        wr = s["wins"] / s["n_buy"] * 100 if s["n_buy"] else 0.0
        lo, hi = _wilson_pct(s["wins"], s["n_buy"])
        band = "lowest" if d == 1 else ("highest" if d == N_DECILES else "")
        unb_rate = f"{s['n_unb'] / s['n_total'] * 100:.1f}" if s["n_total"] else "0.0"
        print(f"{d:<8}{band:<10}{s['n_buy']:<8}{s['wins']:<8}{wr:<11.2f}"
              f"[{lo:.1f},{hi:.1f}]{'':<6}{unb_rate:<8}")
    print("-" * 92)

    rho = _spearman_rho([float(d) for d in decile_nums], winrates)
    d10, d1 = winrates[-1], winrates[0]
    print(f"\nSpearman rho（decile 序 vs path_winrate）= {rho:+.3f}")
    print(f"  rho < 0 → score 反向预测（高分 winrate 更低）；rho > 0 → 正向；|rho|<0.3 弱。")
    print(f"decile10(高) winrate={d10:.2f}%  vs  decile1(低) winrate={d1:.2f}%  →  Δ={d10-d1:+.2f}pp")
    print(f"  Δ<0 → 高分更差（反向）；Δ>0 → 高分更好（正向，与 §44 top-gene 劣于随机一致）")

    # 数据缺口 caveat
    print("\n--- 数据缺口 caveat ---")
    conn = sqlite3.connect(GENE_SCORES_DB_PATH)
    try:
        gap = conn.execute("""
            SELECT COUNT(*) FROM universe_returns u
            WHERE u.return_path IS NOT NULL AND u.is_unbuyable = 0
              AND NOT EXISTS (SELECT 1 FROM gene_scores g
                              WHERE g.date=u.signal_date AND g.code=u.code
                                AND g.total_score IS NOT NULL)
        """).fetchone()[0]
        denom = conn.execute("""
            SELECT COUNT(*) FROM universe_returns
            WHERE return_path IS NOT NULL AND is_unbuyable=0
        """).fetchone()[0]
    finally:
        conn.close()
    pct = gap / denom * 100 if denom else 0
    print(f"  缺 score（universe path 行无法分位）= {gap}/{denom} ({pct:.1f}%)")
    print(f"  → gene_scores 数据缺口（近期未刷新），非系统性弱股未评分；分位基于 {total_n} joined 行。")

    # 结论框架（诚实，不软化）
    print("\n--- 判读 ---")
    if rho < -0.3 and d1 > d10:
        print(f"  rho={rho:+.3f}<0 且低分>高分 → **score 反向预测**：低分反而 winrate 更高。")
        print(f"  解释 top-gene 劣于随机：高分=追涨过度乐观=均值回归。低分/多空或值得研究。")
        print(f"  ⚠️ 须先排 unbuyable survivorship（高 decile 若高 unbuyable→'更差'是剔强股假象）。")
    elif rho > 0.3 and d10 > d1:
        print(f"  rho={rho:+.3f}>0 且高分>低分 → **score 正向预测**（与 top-gene picks 劣于随机看似矛盾）。")
        print(f"  可能：score 正向但 picks=最高分=最追涨，max-decile 反转（看 d10 vs d8/d9）。")
    else:
        print(f"  rho={rho:+.3f}（弱/无单调）→ gene_score 无方向性：分位与 winrate 不系统相关。")
        print(f"  top-gene 劣于随机非 score 方向性所致，是 picks 高分位的局部反转/波动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
