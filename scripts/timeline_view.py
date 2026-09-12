#!/usr/bin/env python3
"""知识图谱时间线视图——按时间排列事件实体。

扫描 vault markdown frontmatter 中的 date 字段（含 publish_date/created/audit_date），
按时间升序输出，生成 markdown 时间线报告。
"""
import re
import sys
from pathlib import Path
from datetime import datetime

VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")
REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "timeline-report.md"

# 跳过模板与 index
SKIP_NAMES = {"index.md"}
SKIP_SUBSTR = ("templates",)

DATE_FIELDS = ["date", "publish_date", "created", "audit_date"]
# frontmatter 单行字段：field: value
FIELD_RE = re.compile(r"^(\w[\w-]*)\s*:\s*(.+?)\s*$", re.MULTILINE)
# frontmatter 起止
FM_START_RE = re.compile(r"^---\s*$", re.MULTILINE)


def _skip_file(f: Path) -> bool:
    if f.name in SKIP_NAMES:
        return True
    if any(s in str(f) for s in SKIP_SUBSTR):
        return True
    return False


def _parse_date(s: str):
    """尝试多种格式解析日期，成功返回 datetime，失败返回 None。"""
    s = s.strip().strip('"').strip("'")
    # 截断到前 10 位（YYYY-MM-DD）
    candidate = s[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    # 尝试完整日期时间
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _strip_frontmatter(content: str):
    """返回 (frontmatter_text, body_text)。无 frontmatter 返回 ("", content)。"""
    if not content.startswith("---"):
        return "", content
    # 找第二个 ---
    m = FM_START_RE.search(content, 4)  # 跳过第一个 ---
    if not m:
        return "", content
    fm = content[4 : m.start()].strip()
    body = content[m.end() :].lstrip("\n")
    return fm, body


def collect_timeline():
    """收集所有有 date 字段的实体，按时间升序排列。"""
    events = []
    skipped_no_date = 0
    for f in VAULT.rglob("*.md"):
        if _skip_file(f):
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue

        fm, body = _strip_frontmatter(content)
        if not fm:
            skipped_no_date += 1
            continue

        # 字段字典
        fields = dict(FIELD_RE.findall(fm))

        dt = None
        used_field = None
        date_str_raw = None
        for field in DATE_FIELDS:
            if field in fields:
                date_str_raw = fields[field]
                dt = _parse_date(date_str_raw)
                if dt:
                    used_field = field
                    break

        if not dt:
            skipped_no_date += 1
            continue

        # 提取 type 与其他有用字段
        etype = fields.get("type", "unknown")
        title = fields.get("name") or fields.get("title") or f.stem
        code = fields.get("code", "")
        summary = fields.get("summary", "")

        rel = str(f.relative_to(VAULT)).replace(".md", "")
        events.append({
            "date": dt,
            "type": etype,
            "file": rel,
            "title": title,
            "code": code,
            "summary": summary,
            "used_field": used_field,
            "date_str": dt.strftime("%Y-%m-%d"),
        })

    events.sort(key=lambda x: x["date"])
    return events, skipped_no_date


def build_report(events, skipped):
    """生成 markdown 时间线报告。"""
    lines = []
    lines.append("# 知识图谱时间线视图")
    lines.append("")
    lines.append(f"> 自动生成于 `timeline_view.py`。数据源：`{VAULT}`")
    lines.append("")
    lines.append(f"- 有日期字段的实体数：**{len(events)}**")
    lines.append(f"- 无/无法解析日期的实体数：{skipped}")
    if events:
        lines.append(f"- 时间范围：`{events[0]['date_str']}` ~ `{events[-1]['date_str']}`")
    lines.append("")

    if not events:
        lines.append("> 无带日期的实体，报告为空。")
        return "\n".join(lines)

    # 按年-月分组
    from collections import defaultdict
    by_month = defaultdict(list)
    for e in events:
        key = e["date"].strftime("%Y-%m")
        by_month[key].append(e)

    lines.append("## 时间线（按月分组）")
    lines.append("")
    for month in sorted(by_month.keys()):
        items = by_month[month]
        lines.append(f"### {month}（{len(items)} 条）")
        lines.append("")
        lines.append("| 日期 | 类型 | 实体 | 代码/标题 | 摘要 |")
        lines.append("|---|---|---|---|---|")
        for e in items:
            label = e["title"] or e["file"]
            code_part = f"`{e['code']}`" if e["code"] else label
            summary = (e["summary"] or "").replace("|", "\\|")
            if len(summary) > 60:
                summary = summary[:57] + "..."
            lines.append(
                f"| {e['date_str']} | {e['type']} | `[[{e['file']}]]` | {code_part} | {summary} |"
            )
        lines.append("")

    # 按类型聚合的速览
    lines.append("## 按类型速览")
    lines.append("")
    type_count = defaultdict(int)
    for e in events:
        type_count[e["type"]] += 1
    lines.append("| 类型 | 数量 |")
    lines.append("|---|---|")
    for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
        lines.append(f"| {t} | {c} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 方法说明")
    lines.append("")
    lines.append("- 扫描 vault 内所有 `.md`（排除 templates/index），解析 frontmatter。")
    lines.append(f"- 日期字段优先级：`{' > '.join(DATE_FIELDS)}`，第一个能解析的生效。")
    lines.append("- 支持格式：`YYYY-MM-DD` / `YYYY/MM/DD` / `YYYY.MM.DD` 及完整日期时间。")
    lines.append("- 无 frontmatter 或字段无法解析的实体计入 `skipped`。")
    lines.append("")

    return "\n".join(lines)


def main():
    if not VAULT.exists():
        print(f"ERROR: vault not found: {VAULT}", file=sys.stderr)
        sys.exit(1)

    print(f"Collecting timeline from {VAULT} ...")
    events, skipped = collect_timeline()
    print(f"  events={len(events)} skipped(no_date)={skipped}")
    if events:
        print(f"  range={events[0]['date_str']} ~ {events[-1]['date_str']}")

    print("Building report ...")
    report = build_report(events, skipped)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"  report -> {REPORT_PATH}")

    # 摘要
    print("\n=== Summary ===")
    print(f"dated entities: {len(events)}")
    print(f"skipped (no date): {skipped}")
    if events:
        print(f"earliest: {events[0]['date_str']} ({events[0]['file']})")
        print(f"latest:   {events[-1]['date_str']} ({events[-1]['file']})")


if __name__ == "__main__":
    main()
