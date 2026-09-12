#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inbox 去重：同 (entity_type + code|name) 只保留一份，合并 confidence 取高值。

用法: python3 scripts/llm_extract_dedup.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

INBOX = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/inbox")

_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _parse_frontmatter(text: str) -> dict:
    """简易 YAML frontmatter 解析（只取顶层 key: value）。"""
    fm: dict[str, str] = {}
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return fm
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def _entity_key(fm: dict) -> str:
    """去重键：stock 用 code，其余用 name。"""
    t = fm.get("entity_type", "")
    if t == "stock":
        return f"stock:{fm.get('code', '')}"
    return f"{t}:{fm.get('name', '')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告不删除")
    args = ap.parse_args()

    files = [f for f in INBOX.glob("*.md") if f.name != "index.md"]
    if not files:
        print("[INFO] inbox 无待审文件")
        return 0

    # key -> list[(conf_rank, quality_score, filepath)]
    groups: dict[str, list[tuple[int, int, Path]]] = {}
    for f in files:
        fm = _parse_frontmatter(f.read_text(encoding="utf-8"))
        key = _entity_key(fm)
        conf = fm.get("confidence", "low")
        qs = int(fm.get("quality_score", "20") or 20)
        groups.setdefault(key, []).append((_CONF_RANK.get(conf, 1), qs, f))

    total = len(files)
    dup_keys = {k for k, v in groups.items() if len(v) > 1}
    to_delete: list[Path] = []
    merged_counts: dict[str, int] = {}

    for key, items in groups.items():
        if len(items) == 1:
            continue
        # 保留 confidence 最高（并列时 quality_score 最高，再并列取最早文件名）
        items.sort(key=lambda x: (-x[0], -x[1], x[2].name))
        keep = items[0]
        for it in items[1:]:
            to_delete.append(it[2])
        merged_counts[key] = len(items)

    print(f"[STAT] 总文件 {total}，唯一实体键 {len(groups)}，重复键 {len(dup_keys)}，待删 {len(to_delete)}")
    if dup_keys:
        print("\n重复明细（key -> 重复数）：")
        for k in sorted(dup_keys):
            print(f"  {k}: {merged_counts[k]}")

    if args.dry_run:
        print("\n[DRY-RUN] 未删除，加 --no-dry-run 或去掉 --dry-run 执行删除")
        return 0

    for f in to_delete:
        f.unlink()
    print(f"\n[DONE] 删除 {len(to_delete)} 个重复文件，保留 {total - len(to_delete)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
