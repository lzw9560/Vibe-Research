"""报告 → 知识图谱关联段注入器（独立脚本）。

ora-3 §1.1：盘前/盘后报告每天自动生成，但与图谱 0 双链。
本脚本读 daily 报告 → 扫 6 位股票代码 → 查 vault 实体 →
补"图谱关联"+"待入图谱"两段。

用法：
    python scripts/inject_kg_to_report.py                    # 扫全部 daily 报告
    python scripts/inject_kg_to_report.py path/to/report.md  # 单份报告
    python scripts/inject_kg_to_report.py --dry-run          # 只打印不写
    VR_KG_VAULT_PATH=/path/to/vault python scripts/inject_kg_to_report.py

设计纪律（对齐 AGENTS.md + ora-3 §1.1 + §2.5）：
- 只读 vault 客观数据，不改 frontmatter，不臆造数据
- 命中已有实体 → 输出 [[stocks/600519|贵州茅台]] 双链
- 未命中 → 在"待入图谱"段列出，作为 inbox stub 的输入清单
- 报告已含"图谱关联"段 → 跳过（幂等，不重复注入）
- 正则排除日期（2026-09-05）/百分比/版本号等干扰
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# vault 路径（与 backend/ai/tools/kg_tools.py 同口径，可被环境变量覆盖）
_VAULT_ROOT = Path(
    os.environ.get(
        "VR_KG_VAULT_PATH",
        "/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing",
    )
)
_VAULT_INVESTING = _VAULT_ROOT  # 上面默认值已指向 investing 子区

# 报告目录候选（daily/ 与 market_sentiment/daily/ 两处）
_REPORT_DIRS = [
    Path("/Users/lizhiwei/Documents/Obsidian Vault/daily"),
    Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/market_sentiment/daily"),
]

# 6 位 A 股代码正则（沪深主板/创业板/科创板/北交所前缀）
# 排除日期（2026-09-05 在报告头部会被命中的话用 \b 边界 + 上下文排除）
_CODE_RE = re.compile(r"(?<![\d-])((?:00|30|60|68|688|8)\d{4})(?!\d)")

# 排除日期模式：YYYY-MM-DD
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 已注入标记（幂等检查）
_INJECTED_MARKER = "<!-- kg-inject:done -->"
_INJECTED_HEADER = "## 图谱关联"


def _extract_codes(text: str) -> list[str]:
    """从报告正文提取 6 位 A 股代码，去重保序，排除日期内的数字。"""
    # 先把日期遮蔽，避免 YYYY-MM-DD 里的 MM-DD 被误判（2026-09-05 → 09-05 不像代码，但稳妥起见）
    masked = _DATE_RE.sub("DATE", text)
    seen: set[str] = set()
    codes: list[str] = []
    for m in _CODE_RE.finditer(masked):
        code = m.group(1)
        # 688 开头是 6 位科创板，但正则里 688\d{3} 已是 6 位，与 \d{4} 合并会重复匹配——
        # 用 (?<![\d-]) 前视 + (?!\d) 后视保证不嵌套
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def _stock_entity(code: str) -> dict | None:
    """查 vault 是否有该股票实体。命中返回 frontmatter（含 name），否则 None。"""
    p = _VAULT_INVESTING / "stocks" / f"{code}.md"
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return None
    # 手写 frontmatter 解析（与 kg_tools.py 同口径，不依赖 PyYAML）
    m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
    if not m:
        return {"code": code, "name": code, "path": str(p.relative_to(_VAULT_INVESTING))}
    fm: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip("'\"")
        val = re.sub(r"<%.*?%>", "", val).strip()
        if val:
            fm[key.strip()] = val
    fm["code"] = code
    fm["path"] = str(p.relative_to(_VAULT_INVESTING))
    fm.setdefault("name", code)
    return fm


def _has_injected(text: str) -> bool:
    """报告是否已含图谱关联段（幂等）。"""
    return _INJECTED_MARKER in text or _INJECTED_HEADER in text


def _build_injection(codes: list[str]) -> str:
    """构建图谱关联 + 待入图谱两段 markdown。"""
    linked: list[str] = []
    missing: list[dict] = []
    for code in codes:
        ent = _stock_entity(code)
        if ent:
            name = ent.get("name", code)
            # 用全路径双链，确保从 daily/ 报告能跳到 investing/stocks/
            linked.append(f"- [[10_Reference/investing/stocks/{code}|{name}]] — ✅ 已入图谱")
        else:
            missing.append({"code": code})

    parts: list[str] = []
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(_INJECTED_HEADER)
    parts.append("")
    parts.append(
        "> 本段由 `scripts/inject_kg_to_report.py` 注入（规则："
        "[[10_Reference/investing/logic/报告图谱关联]]）。"
        "扫描报告 6 位股票代码，链接到投研知识图谱实体。"
    )
    parts.append("")

    if linked:
        parts.append("**本报告涉及个股（已入图谱）：**")
        parts.append("")
        parts.extend(linked)
        parts.append("")
    else:
        parts.append("> 本报告出现的股票代码均未入图谱。")
        parts.append("")

    parts.append("## 待入图谱")
    parts.append("")
    if missing:
        parts.append(
            "以下代码在图谱 [[10_Reference/investing/stocks/]] 中无对应实体，"
            "建议按 [[10_Reference/investing/logic/LLM抽取质量门]] 走 inbox stub 流程灌入："
        )
        parts.append("")
        parts.append("| 代码 | 出现位置 | 建议优先级 |")
        parts.append("|---|---|---|")
        for item in missing:
            parts.append(f"| {item['code']} | 龙虎榜/热榜 | medium |")
        parts.append("")
        parts.append(
            "> ⚠️ ora-3 诊断硬事实 1：图谱个股与盘前报告 Top 榜的重叠靠本段驱动。"
            "被 ≥2 份不同日期报告命中的代码才建档（[[10_Reference/investing/logic/inbox-promotion]]）。"
        )
    else:
        parts.append("> 无缺失——本报告所有代码均已入图谱。")
    parts.append("")
    parts.append(_INJECTED_MARKER)
    return "\n".join(parts)


def inject_report(path: Path, dry_run: bool = False) -> dict:
    """对单份报告执行注入。返回 {file, codes, linked, missing, injected, skipped}。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {"file": str(path), "error": str(e)}

    if _has_injected(text):
        return {
            "file": str(path),
            "skipped": True,
            "reason": "已含图谱关联段（幂等）",
        }

    codes = _extract_codes(text)
    linked_count = sum(1 for c in codes if _stock_entity(c))
    missing_count = len(codes) - linked_count

    if not codes:
        return {
            "file": str(path),
            "skipped": True,
            "reason": "未发现 6 位股票代码",
        }

    injection = _build_injection(codes)
    new_text = text.rstrip() + "\n" + injection

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")

    return {
        "file": str(path),
        "codes": codes,
        "linked": linked_count,
        "missing": missing_count,
        "injected": not dry_run,
        "dry_run": dry_run,
    }


def _gather_reports(explicit: list[str]) -> list[Path]:
    """收集要处理的报告文件。显式参数优先，否则扫 _REPORT_DIRS。"""
    if explicit:
        return [Path(p) for p in explicit if Path(p).exists()]

    reports: list[Path] = []
    for d in _REPORT_DIRS:
        if not d.exists():
            continue
        # daily 报告命名：YYYY-MM-DD_<phase>_<title>.md
        for p in sorted(d.glob("*.md")):
            if p.name in ("index.md", "README.md"):
                continue
            reports.append(p)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="盘前/盘后报告注入知识图谱关联段（ora-3 §1.1）"
    )
    parser.add_argument("reports", nargs="*", help="显式指定报告路径（默认扫 daily 两处）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    parser.add_argument("--vault", help="覆盖 vault 路径（默认读 VR_KG_VAULT_PATH 或内置路径）")
    args = parser.parse_args(argv)

    if args.vault:
        global _VAULT_INVESTING
        _VAULT_INVESTING = Path(args.vault)

    reports = _gather_reports(args.reports)
    if not reports:
        print("未找到报告文件", file=sys.stderr)
        return 1

    print(f"扫描 {len(reports)} 份报告（dry_run={args.dry_run}）")
    print(f"vault 路径：{_VAULT_INVESTING}")
    print("-" * 60)

    summary = {"total": 0, "injected": 0, "skipped": 0, "linked": 0, "missing": 0}
    for p in reports:
        r = inject_report(p, dry_run=args.dry_run)
        summary["total"] += 1

        if r.get("skipped"):
            summary["skipped"] += 1
            print(f"[跳过] {r['file']} — {r['reason']}")
            continue

        summary["linked"] += r["linked"]
        summary["missing"] += r["missing"]
        if r.get("injected") or (args.dry_run and r.get("codes")):
            summary["injected"] += 1
            action = "[dry-run]" if args.dry_run else "[注入]"
            print(
                f"{action} {r['file']}\n"
                f"    代码 {len(r['codes'])} 个，已入图谱 {r['linked']}，"
                f"待入图谱 {r['missing']}"
            )

    print("-" * 60)
    print(
        f"汇总：{summary['total']} 份，注入 {summary['injected']}，"
        f"跳过 {summary['skipped']}，已链接 {summary['linked']}，"
        f"待入图谱 {summary['missing']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
