#!/usr/bin/env python3
"""S128 CI grep-lint：flag consumer 反吞 NEVER_ZERO 字段 None→0（防 S121 反吞复发）。

扫 backend/**/*.py，flag `.(NEVER_ZERO 字段) or 0` 模式（model.price or 0 / quote.open or 0 等）。
mappers.py 已对这些字段 `or None`（"0 永不合法"，S121/S125 契约），consumer 不该再 or 0
反吞 None→0——S127 抓到 bidding_monitor:114-118 反吞 S121 致 open_premium=0→"缩量平开"
假交易信号 + market_cap=0→错 tier。本 lint 防未来 consumer 反吞复发。

跑：python scripts/check_or_zero_contract.py
违例返非零退出码（CI 红门）。白名单：mappers.py 自身（或 None 是契约源头）、test 文件。

NEVER_ZERO 集合保持与 backend/data/mappers.py 同步（手动 sync，避免 runtime import 重依赖）。
"""
import re
import sys
from pathlib import Path

NEVER_ZERO = {
    "market_cap", "price", "pe_ttm", "pb", "limit_up_price", "limit_down_price",
    "last_close", "open", "high", "low", "pe_static", "ps_ttm", "pcf_ttm",
    "forward_pe", "mcap_yi", "float_market_cap",
}

# \.(field)\s+or\s+0(\.0)? 后跟边界（$, [,),]},空格,;）——匹配 attribute access `model.price or 0`
PATTERN = re.compile(
    r"\.(" + "|".join(re.escape(f) for f in NEVER_ZERO) + r")\s+or\s+0(?:\.0)?(?:\s|$|[,)\];}])"
)

BACKEND = Path(__file__).resolve().parent.parent / "backend"
ALLOWLIST = {"data/mappers.py"}  # 契约源头（或 None 是契约本身，非反吞）


def scan() -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    if not BACKEND.is_dir():
        return violations
    for py in BACKEND.rglob("*.py"):
        if "__pycache__" in py.parts or "tests" in py.parts:
            continue
        rel = py.relative_to(BACKEND).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                violations.append((rel, i, line.strip()))
    return violations


def main() -> int:
    vs = scan()
    if not vs:
        print("✅ check_or_zero_contract: 0 违例（无 consumer 反吞 NEVER_ZERO 字段）")
        return 0
    print(f"❌ check_or_zero_contract: {len(vs)} 违例（consumer 反吞 NEVER_ZERO 字段 None→0）：")
    for rel, i, line in vs:
        print(f"  {rel}:{i}: {line}")
    print("\n修复：不 `model.X or 0`，保 None + data_status=degraded/skip 信号（对齐 S125 portfolio / S128 bidding_monitor 范式）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
