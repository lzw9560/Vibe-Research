# -*- coding: utf-8 -*-
"""当前小盘熊段 regime 的历史恢复时间分布（2026-10-27）。

用户问"当前风险预计持续多久"——当前 breadth 21.2% + 小盘5d -1.33%（cap 口径 monitor）
gate=OFF。本脚本算 8 年历史类似极值的恢复时间分布。

口径（和 _audit_combo_gate_stratify 一致）：
- breadth = 全市场 >60MA 占比（不分组，cap/amount 口径一致）
- 小盘5d = amount-decile 最低 20% 组的 5d ret 均值（amount 代理，turn 2024前为0）
- viable = breadth>0.4 and sm5>0（FROZEN 阈值）

⚠️ 框定（重要）：
- 这是"历史类似极值的恢复时间分布"诊断，**不是预测精确持续天数**
- 命题B已证伪 market timing + A股 regime 跳变（政策/流动性催化可突然反转）
- 历史 ≠ 未来 + 极端区域样本量少（8年里 breadth≤21.2% 的次数可能不多，分布宽）
- 给分布（median/分位）不给单点预测
"""

from __future__ import annotations

import statistics
from importlib import util as _ilu
from pathlib import Path

# import 复用 _audit_combo_gate_stratify 的 build_by_date + gate_signal（同口径）
_mod_path = Path(__file__).resolve().parent / "_audit_combo_gate_stratify.py"
_spec = _ilu.spec_from_file_location("_audit_combo_gate_stratify", _mod_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_by_date = _mod.build_by_date
gate_signal = _mod.gate_signal

BREADTH_FLOOR = 0.4  # FROZEN（和 monitor/门分层一致）
SM5_FLOOR = 0.0


def _pct(data: list, q: float) -> float:
    """线性插值分位。"""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _dist_label(name: str, data: list) -> str:
    if not data:
        return f"{name}: (n=0)"
    return (
        f"{name}: n={len(data)} median={statistics.median(data):.0f}d "
        f"mean={statistics.mean(data):.0f}d p25={_pct(data, 0.25):.0f}d "
        f"p75={_pct(data, 0.75):.0f}d min={min(data)} max={max(data)}"
    )


def main() -> None:
    by_date = build_by_date()
    all_dates = sorted(by_date.keys())

    # 每日 breadth + sm5 + viable（amount 口径）
    series: list = []  # (date, breadth, sm5, viable)
    for d in all_dates:
        lst = by_date[d]
        if len(lst) < 200:
            continue
        b, sm5, viable = gate_signal(lst, "amt")
        if b == 0.0 and sm5 == 0.0 and not viable:
            continue
        series.append((d, b, sm5, viable))

    if not series:
        print("series 空")
        return

    all_b = [s[1] for s in series]
    all_sm5 = [s[2] for s in series]
    latest = series[-1]
    cur_b, cur_sm5, cur_viable = latest[1], latest[2], latest[3]
    latest_date = latest[0]

    # 用户给的 cap 口径当前值（monitor 10-26 跑出）作参考基准
    CAP_B = 0.212
    CAP_SM5 = -0.0133

    print(f"=== 当前 regime 历史恢复时间分布（amount-decile 口径，{series[0][0]}~{latest_date}，{len(series)} 日）===")
    print(f"数据日（最新）：{latest_date}")
    print(f"amount 口径当前值：breadth={cur_b * 100:.1f}%  小盘5d={cur_sm5 * 100:+.2f}%  viable={cur_viable}")
    print(f"cap 口径当前值（monitor 10-26 跑出，参考基准）：breadth={CAP_B * 100:.1f}%  小盘5d={CAP_SM5 * 100:+.2f}%")
    print()

    # 1. 历史分位
    b_pct_amt = sum(1 for b in all_b if b <= cur_b) / len(all_b)
    sm5_pct_amt = sum(1 for s in all_sm5 if s <= cur_sm5) / len(all_sm5)
    b_pct_cap = sum(1 for b in all_b if b <= CAP_B) / len(all_b)
    sm5_pct_cap = sum(1 for s in all_sm5 if s <= CAP_SM5) / len(all_sm5)
    print("【1】当前值的历史分位（越低=越极端=比现在更差的日子越少）")
    print(
        f"  breadth {cur_b * 100:.1f}%(amount口径): {b_pct_amt * 100:.1f}% 的日子比现在更差（即 {(1 - b_pct_amt) * 100:.1f}% 日子比现在好）"
    )
    print(f"  breadth {CAP_B * 100:.1f}%(cap口径基准): {b_pct_cap * 100:.1f}% 的日子比现在更差")
    print(f"  小盘5d {cur_sm5 * 100:+.2f}%(amount口径): {sm5_pct_amt * 100:.1f}% 的日子比现在更差")
    print(f"  小盘5d {CAP_SM5 * 100:+.2f}%(cap口径基准): {sm5_pct_cap * 100:.1f}% 的日子比现在更差")
    print()

    # 2. breadth≤当前 → 恢复 >0.4 的交易日数分布
    def recovery_time(cur_val: float, series_list, key_idx: int, recover_thr: float, label: str) -> list:
        rec = []
        for i, s in enumerate(series_list):
            if s[key_idx] <= cur_val:
                for j in range(i + 1, len(series_list)):
                    if series_list[j][key_idx] > recover_thr:
                        rec.append(j - i)
                        break
        print(f"【{label}】{series_list[i][0] if series_list else ''}≤基准 → 恢复>{recover_thr} 的交易日数分布")
        print(f"  {_dist_label('  ', rec)}")
        return rec

    # breadth 恢复（用 cap 口径基准 0.212，breadth 两口径一致）
    b_rec_cap = []
    for i, s in enumerate(series):
        if s[1] <= CAP_B:
            for j in range(i + 1, len(series)):
                if series[j][1] > BREADTH_FLOOR:
                    b_rec_cap.append(j - i)
                    break
    b_rec_amt = []
    for i, s in enumerate(series):
        if s[1] <= cur_b:
            for j in range(i + 1, len(series)):
                if series[j][1] > BREADTH_FLOOR:
                    b_rec_amt.append(j - i)
                    break
    print("【2】breadth≤当前 → 恢复>40% 的交易日数分布")
    print(f"  以 cap 基准 {CAP_B * 100:.1f}%: {_dist_label('', b_rec_cap)}")
    print(f"  以 amount 当前 {cur_b * 100:.1f}%: {_dist_label('', b_rec_amt)}")
    print()

    # 3. 小盘5d≤当前 → 转正 >0 的交易日数分布
    sm5_rec_cap = []
    for i, s in enumerate(series):
        if s[2] <= CAP_SM5:
            for j in range(i + 1, len(series)):
                if series[j][2] > SM5_FLOOR:
                    sm5_rec_cap.append(j - i)
                    break
    sm5_rec_amt = []
    for i, s in enumerate(series):
        if s[2] <= cur_sm5:
            for j in range(i + 1, len(series)):
                if series[j][2] > SM5_FLOOR:
                    sm5_rec_amt.append(j - i)
                    break
    print("【3】小盘5d≤当前 → 转正>0 的交易日数分布")
    print(f"  以 cap 基准 {CAP_SM5 * 100:+.2f}%: {_dist_label('', sm5_rec_cap)}")
    print(f"  以 amount 当前 {cur_sm5 * 100:+.2f}%: {_dist_label('', sm5_rec_amt)}")
    print()

    # 4. gate=OFF 连续段长度分布
    off_streaks = []
    cur_streak = 0
    for s in series:
        if not s[3]:
            cur_streak += 1
        else:
            if cur_streak > 0:
                off_streaks.append(cur_streak)
            cur_streak = 0
    if cur_streak > 0:
        off_streaks.append(cur_streak)  # 当前未结束 streak
    print("【4】gate=OFF 连续段长度分布（历史 OFF 段持续多久）")
    print(f"  {_dist_label('', off_streaks)}")
    # 当前已持续
    cur_off_days = 0
    for s in reversed(series):
        if not s[3]:
            cur_off_days += 1
        else:
            break
    print(f"  当前这轮 gate=OFF 已持续 {cur_off_days} 个交易日（从最近一次 viable=ON 翻 OFF 算起）")
    # 历史类似长度 OFF 段的后续恢复时间
    if off_streaks:
        longer = [x for x in off_streaks if x >= cur_off_days]
        print(f"  历史中 ≥{cur_off_days} 日的 OFF 段共 {len(longer)} 次，这些段的总长度分布: {_dist_label('', longer)}")
    print()

    # 5. 同时满足 breadth≤基准 AND sm5≤基准 的恢复（双极值同时触发 → 更接近当前状态）
    dual_rec = []
    for i, s in enumerate(series):
        if s[1] <= CAP_B and s[2] <= CAP_SM5:
            for j in range(i + 1, len(series)):
                if series[j][3]:  # viable 恢复（breadth>0.4 AND sm5>0）
                    dual_rec.append(j - i)
                    break
    print("【5】双极值同时触发（breadth≤21.2% AND 小盘5d≤-1.33%）→ gate 恢复 viable=ON 的交易日数")
    print(f"  {_dist_label('', dual_rec)}")
    print()

    # 6. 结论
    print("【6】结论（历史类似极值的恢复区间，非预测）")
    parts = []
    if b_rec_cap:
        parts.append(
            f"breadth≤21.2%→恢复>40% median {statistics.median(b_rec_cap):.0f} 交易日（p25-p75: {_pct(b_rec_cap, 0.25):.0f}-{_pct(b_rec_cap, 0.75):.0f}）"
        )
    if sm5_rec_cap:
        parts.append(
            f"小盘5d≤-1.33%→转正 median {statistics.median(sm5_rec_cap):.0f} 交易日（p25-p75: {_pct(sm5_rec_cap, 0.25):.0f}-{_pct(sm5_rec_cap, 0.75):.0f}）"
        )
    if dual_rec:
        parts.append(
            f"双极值→gate viable 恢复 median {statistics.median(dual_rec):.0f} 交易日（p25-p75: {_pct(dual_rec, 0.25):.0f}-{_pct(dual_rec, 0.75):.0f}）"
        )
    for p in parts:
        print(f"  {p}")
    print()
    print("⚠️ 框定：")
    print("  - 这是历史类似极值的恢复时间分布，不是预测精确持续天数")
    print("  - A股 regime 跳变（政策/流动性催化可突然反转）——历史恢复时间分布给的是'类似状态的典型持续'，")
    print("    不排除这次更长或更短（如 2024-09 政策催化 V 型反转 vs 2018 贸易战阴跌数月）")
    print("  - 极端区域样本量少（breadth≤21.2% 的次数有限），分布宽，median 仅供参照")
    print(
        "  - amount-decile 代理小盘（≠ cap-decile），cap 口径当前值（21.2%/-1.33%）在 amount 历史分布里找分位有口径差异"
    )
    print("  - 命题B已证伪 market timing——不给'X 天后转牛'的单点预测，给分布")


if __name__ == "__main__":
    main()
