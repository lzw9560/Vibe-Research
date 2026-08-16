#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spec→plan/tasks 一致性 lint——查 plan.md/tasks.md 是否裸引用 spec 已收回的 stale 事实。

spec 经多轮 grill 更新（rebound 收回→等权 placeholder、§13.0 绝对 60、§44 lift bar、
039 label-only）；plan/tasks 若仍 bare 引用旧事实则不一致。本 lint 标记 bare stale
（含 ~~ 划掉 / §44 注解 / "已废止"/"收回" 的视为已处置，跳过）。

用法：python tools/spec_plan_stale_lint.py [plan.md tasks.md ...]
退出码：0=clean，1=有 bare stale（CI 友好）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# spec 已收回/改的事实 → 不应 bare 出现在 plan/tasks
STALE: list[tuple[str, str]] = [
    (r"seal_rate 60%|seal 60%", "暴风暴 seal 60% 已废止→等权 placeholder（§4.3）"),
    (r"freq 反向 40%|freq反向40%", "暴风暴 freq 反向 40% 已废止→等权"),
    (r"premium\(反向\)|freq\(反向\)", "涨停类 premium/freq 反向权重已废止→等权 placeholder（§4.1）"),
    (r"rebound[_ ]rate.*主因子|升主因子", "rebound_rate 升主因子已二轮验证收回（日级伪信号）"),
    (r"n=6537(?!\s*条|样本)", "0b n=6537 单组已废止→双轨分层 kline3760/eastmoney2836"),
    (r"板块阶段 ?-> ?策略分修饰系数接入|修饰系数接入策略分|修饰系数接入", "039 修饰接入策略分已 §5.4 Q2 改纯 LABEL（不接策略分）"),
    (r"胜率 ?>= ?回测 ?x ?0\.8|胜率.*回测.*0\.8", "Phase 0e pass ×0.8(=48) 弱 bar ≠ §13.0 绝对60 + 无随机基准（§44 不合规）"),
]


def lint(path: str) -> list[tuple[str, int, str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    hits: list[tuple[str, int, str, str]] = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        # 已划掉 / §44 注解 / 标注已废止/收回 的视为处置，跳过
        if "~~" in line or "§44" in line or "已废止" in line or "收回" in line or "placeholder" in line.lower():
            continue
        for pat, why in STALE:
            if re.search(pat, line):
                hits.append((str(p), i, why, line.strip()))
    return hits


def main() -> int:
    files = sys.argv[1:] or [
        "specs/S066-策略特定漏斗架构重构/plan.md",
        "specs/S066-策略特定漏斗架构重构/tasks.md",
    ]
    all_hits: list[tuple[str, int, str, str]] = []
    for f in files:
        all_hits.extend(lint(f))
    if not all_hits:
        print("✓ plan/tasks 无 bare stale 标记（spec 已收回事实未裸引用）")
        return 0
    print(f"✗ 发现 {len(all_hits)} 处 bare stale（spec 已收回但 plan/tasks 仍裸引用）：")
    for path, line, why, txt in all_hits:
        print(f"  {path}:{line} [{why}]")
        print(f"    > {txt}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
