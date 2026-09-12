#!/usr/bin/env python3
"""批量给正式区实体加 confidence + source 字段。

规则（按 AGENTS.md 分级 + ontology-knowledge-graph skill）:
- stocks: 21 代表股(含 10 待入)→ high/manual+astock.tencent_quote 或 high/daily_report；
           有 indices 字段(沪深300/中证1000 灌入)→ high/akshare.index_stock_cons_csindex；
           无 indices 字段(涨停池灌入)→ high/astock.em_zt_topic_pool
- industries: 自由文本 source 已存在→保留并补 confidence=medium/source_label→astock+manual；
              无 source 字段→ high/manual(手工建)
- concepts: medium/astock.concept_blocks
- data-sources: high/ARCHITECTURE.md
- specs: DEC-* → high/specs/decision-log.md; *project* → high/README.md;
         archive/* → medium/scripts/extract_specs.py; 其余 → high/specs/README.md
- agents: high/trading-agents/README.md
- logic: high/ora-3_diagnosis
- actions: high/logic_rules
- events: high/astock.em_zt_topic_pool（保留现有 source）
- reports: high/astock.eastmoney_reports
- analysts: high/astock.eastmoney_reports.researcher
- metrics: 有真值(astock.financials)→ high/astock.financials；其余 medium/stock_frontmatter
- valuations: 有真值(astock.full_valuation)→ high/astock.full_valuation；其余 medium/stock_frontmatter
- dragon-tiger: high/astock.dragon_tiger_board（保留现有 source）
- indices: high/manual
- strategies: high/manual

幂等：已有 confidence 字段则跳过。
      已有 source 字段则保留现有 source，仅补 confidence（不覆盖）。
排除：templates/ inbox/ reviews/ index.md MOC.md README.md SUMMARY.md
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

VAULT = Path("/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing")

# 21 代表股（手工建+astock.tencent_quote 真值）
REP21 = {
    "600519", "000858", "300750", "688981", "002594", "002156", "002185",
    "002281", "600522", "600584", "601899", "003040", "600869", "002354",
    "601086", "600127", "688836", "300058", "600611", "605398", "605580",
}

# 10 待入灌入（从盘前/盘后报告提取，与 21 代表股重叠，优先匹配）
REP10_DAILY = {
    "600611", "605398", "605580", "003040", "600869",
    "002354", "601086", "600127", "688836", "300058",
}

# 排除文件名（不分目录）
EXCLUDE_NAMES = {"index.md", "MOC.md", "README.md", "SUMMARY.md"}

# 排除路径片段
EXCLUDE_PATH_FRAGMENTS = ("templates", "inbox", "reviews", ".codegraph")


def should_skip(rel: str, name: str) -> bool:
    if name in EXCLUDE_NAMES:
        return True
    low = rel.lower()
    return any(frag in low for frag in EXCLUDE_PATH_FRAGMENTS)


def has_field(content: str, field: str) -> bool:
    """检查 frontmatter 内是否已有某字段（行首）。"""
    return bool(re.search(rf"^{re.escape(field)}:\s*\S", content, re.MULTILINE))


def get_confidence_source(filepath: Path, content: str) -> tuple[str, str]:
    """根据文件路径+内容返回 (confidence, source)。

    若实体已有 source 字段（接口名或自由文本），调用方应跳过写入 source。
    本函数返回的 source 仅供"无 source 时"写入用。
    """
    rel = str(filepath.relative_to(VAULT))
    name = filepath.name

    # ---- stocks ----
    if rel.startswith("stocks/"):
        code = filepath.stem
        if code in REP10_DAILY:
            return ("high", "daily_report")
        if code in REP21:
            return ("high", "manual+astock.tencent_quote")
        # 有 indices 字段 → 指数成分股灌入
        if has_field(content, "indices"):
            return ("high", "akshare.index_stock_cons_csindex")
        # 无 indices → 涨停池灌入
        return ("high", "astock.em_zt_topic_pool")

    # ---- industries ----
    if rel.startswith("industries/"):
        # 已有自由文本 source（东财涨停池行业分类 / 东方财富EM2016行业分类 / 证监会行业分类）
        if has_field(content, "source"):
            return ("medium", "astock+manual")
        # 无 source → 手工建
        return ("high", "manual")

    # ---- concepts ----
    if rel.startswith("concepts/"):
        # 有手工补充描述的 → high/manual；其余 akshare 灌入 → medium
        # 启发式：concepts 无 source 字段统一标 medium/astock.concept_blocks
        # （手工建的概念在 frontmatter 里通常有 related_industry 等丰富字段，
        #  但与 akshare 灌入难区分；按表格 default medium/astock.concept_blocks）
        return ("medium", "astock.concept_blocks")

    # ---- data-sources ----
    if rel.startswith("data-sources/"):
        return ("high", "ARCHITECTURE.md")

    # ---- specs ----
    if rel.startswith("specs/"):
        if "DEC-" in name:
            return ("high", "specs/decision-log.md")
        if "project" in name:
            return ("high", "README.md")
        if "archive/" in rel:
            return ("medium", "scripts/extract_specs.py")
        return ("high", "specs/README.md")

    # ---- agents ----
    if rel.startswith("agents/"):
        return ("high", "trading-agents/README.md")

    # ---- logic ----
    if rel.startswith("logic/"):
        return ("high", "ora-3_diagnosis")

    # ---- actions ----
    if rel.startswith("actions/"):
        return ("high", "logic_rules")

    # ---- events ----
    if rel.startswith("events/"):
        # 已有 source（astock.em_zt_topic_pool 或 market_sentiment 文档）
        if has_field(content, "source"):
            return ("high", "")  # 保留现有 source
        return ("high", "astock.em_zt_topic_pool")

    # ---- reports ----
    if rel.startswith("reports/"):
        return ("high", "astock.eastmoney_reports")

    # ---- analysts ----
    if rel.startswith("analysts/"):
        return ("high", "astock.eastmoney_reports.researcher")

    # ---- metrics ----
    if rel.startswith("metrics/"):
        # 有 astock.financials 真值 source → high；其余 medium/stock_frontmatter
        if has_field(content, "source"):
            return ("high", "")  # 保留现有 source
        return ("medium", "stock_frontmatter")

    # ---- valuations ----
    if rel.startswith("valuations/"):
        if has_field(content, "source"):
            return ("high", "")
        return ("medium", "stock_frontmatter")

    # ---- dragon-tiger ----
    if rel.startswith("dragon-tiger/"):
        if has_field(content, "source"):
            return ("high", "")
        return ("high", "astock.dragon_tiger_board")

    # ---- indices ----
    if rel.startswith("indices/"):
        return ("high", "manual")

    # ---- strategies ----
    if rel.startswith("strategies/"):
        return ("high", "manual")

    return ("medium", "unknown")


def add_fields_to_file(filepath: Path) -> tuple[bool, str]:
    """给单个文件加 confidence + source。返回 (是否改动, 改动类型描述)。"""
    content = filepath.read_text(encoding="utf-8")

    # 幂等：已有 confidence 字段则跳过
    if has_field(content, "confidence"):
        return (False, "skip-existing")

    confidence, source = get_confidence_source(filepath, content)

    # 找 frontmatter（首行必须是 ---）
    # frontmatter: ^---\n...内容...\n---
    fm_match = re.match(r"^---\n(.*?)(\n---)", content, re.DOTALL)
    if not fm_match:
        return (False, "no-frontmatter")

    fm_body = fm_match.group(1)
    closing = fm_match.group(2)

    # 决定要插入的行
    insert_lines = [f"confidence: {confidence}"]
    add_source = False
    if source and not has_field(content, "source"):
        insert_lines.append(f"source: {source}")
        add_source = True

    insert_block = "\n".join(insert_lines)
    new_fm_body = fm_body + "\n" + insert_block
    new_content = content[: fm_match.start(1)] + new_fm_body + closing + content[fm_match.end():]

    filepath.write_text(new_content, encoding="utf-8")

    desc = f"confidence={confidence}"
    if add_source:
        desc += f"+source={source}"
    elif source == "" and not has_field(content, "source"):
        # source 为空字符串但实体本身无 source（events/metrics 无 source 的边缘情况）
        # 此情况 get_confidence_source 已返回非空 source 作为 default
        pass
    return (True, desc)


def main() -> int:
    if not VAULT.is_dir():
        print(f"ERROR: vault not found: {VAULT}", file=sys.stderr)
        return 1

    changed = 0
    skipped = 0
    no_fm = 0
    by_confidence: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    details: list[str] = []

    md_files = sorted(VAULT.rglob("*.md"))
    for f in md_files:
        try:
            rel = str(f.relative_to(VAULT))
        except ValueError:
            continue
        if should_skip(rel, f.name):
            continue

        ok, desc = add_fields_to_file(f)
        if ok:
            changed += 1
            # 解析 confidence/source 用于统计
            conf_m = re.search(r"confidence=(\S+)", desc)
            if conf_m:
                by_confidence[conf_m.group(1)] += 1
            src_m = re.search(r"\+source=(.+)$", desc)
            if src_m:
                by_source[src_m.group(1)] += 1
            # 按顶层目录统计
            top = rel.split("/", 1)[0] if "/" in rel else "root"
            by_type[top] += 1
            details.append(f"  + {rel}: {desc}")
        else:
            if desc == "skip-existing":
                skipped += 1
            elif desc == "no-frontmatter":
                no_fm += 1

    # 输出报告
    print("=" * 60)
    print("confidence + source 批量标注报告")
    print("=" * 60)
    print(f"vault: {VAULT}")
    print(f"总文件数: {len(md_files)}")
    print(f"本次新增字段: {changed}")
    print(f"已有跳过(幂等): {skipped}")
    print(f"无 frontmatter 跳过: {no_fm}")
    print()
    print("--- confidence 分布（本次新增）---")
    for k, v in by_confidence.most_common():
        print(f"  {k}: {v}")
    print()
    print("--- source 分布（本次新增）---")
    for k, v in by_source.most_common():
        print(f"  {k}: {v}")
    print()
    print("--- 实体类型分布（本次新增）---")
    for k, v in by_type.most_common():
        print(f"  {k}/: {v}")
    print()
    if details:
        print("--- 明细（前 50 条）---")
        for line in details[:50]:
            print(line)
        if len(details) > 50:
            print(f"  ... 另有 {len(details) - 50} 条省略")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
