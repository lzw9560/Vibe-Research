"""知识图谱查询工具（S010 工具注册表扩展）。

直接读 vault markdown，不依赖 Obsidian 运行或 MCP。
用标准库 + pathlib，不引新依赖。frontmatter 解析用手写正则
（和 scripts/vault_audit.py 同策略，不依赖 PyYAML）。

合规（CLAUDE.md §1 弱合规）：工具只返回图谱客观数据（实体元数据/关系链接），
方向性研判由 LLM 在 SYSTEM_PROMPT 约束下给出，工具不越权。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .registry import register_tool

# vault 路径（可被环境变量 VR_KG_VAULT_PATH 覆盖）
_VAULT_INVESTING = Path(
    os.environ.get(
        "VR_KG_VAULT_PATH",
        "/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing",
    )
)

# 实体类型 → 文件夹映射（query_kg_entities / query_kg_relations 共用）
_FOLDER_MAP: dict[str, str] = {
    "stock": "stocks",
    "industry": "industries",
    "concept": "concepts",
    "strategy": "strategies",
    "data_source": "data-sources",
    "spec": "specs",
    "event": "events",
    "report": "reports",
    "analyst": "analysts",
    "metric": "metrics",
    "valuation": "valuations",
    "dragon_tiger": "dragon-tiger",
    "logic": "logic",
    "action": "actions",
}


def _parse_frontmatter(content: str) -> dict:
    """手写 YAML frontmatter 解析（不依赖 PyYAML）。

    解析 `---\n<yaml>\n---` 块，逐行 `key: value`。值去引号、去 Templater
    占位符 `<% ... %>`。多行 list（`- item`）与嵌套不解析——知识图谱实体
    frontmatter 是扁平 k:v，够用且和 scripts/vault_audit.py 同口径。
    """
    m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
    if not m:
        return {}
    fm: dict[str, Any] = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip("'\"")
        # 去掉 Templater 占位符 <% tp.date.now("YYYY-MM-DD") %>
        val = re.sub(r"<%.*?%>", "", val).strip()
        if val:
            fm[key.strip()] = val
    return fm


def _list_entities(
    folder: str, filter_field: str = "", filter_value: str = ""
) -> list[dict]:
    """列某文件夹下所有实体的 frontmatter（跳过 index.md）。

    filter_field + filter_value 命中时按字段精确匹配过滤（字符串化比对，
    因 frontmatter 值已解析为字符串）。
    """
    dir_path = _VAULT_INVESTING / folder
    if not dir_path.exists():
        return []
    results: list[dict] = []
    for f in sorted(dir_path.glob("*.md")):
        if f.name == "index.md":
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(content)
        if filter_field and filter_value:
            if str(fm.get(filter_field, "")) != filter_value:
                continue
        fm["_path"] = str(f.relative_to(_VAULT_INVESTING))
        fm["_filename"] = f.stem
        results.append(fm)
    return results


@register_tool(
    "query_kg_entities",
    "查知识图谱实体。可按类型/行业/代码过滤。"
    "如「查白酒行业所有股票」「查所有数据源」「查所有战法」。",
    params={
        "entity_type": {
            "description": "实体类型",
            "enum": [
                "stock",
                "industry",
                "concept",
                "strategy",
                "data_source",
                "spec",
                "event",
                "report",
                "analyst",
                "metric",
                "valuation",
                "dragon_tiger",
                "logic",
                "action",
            ],
        },
        "filter_field": {
            "description": "可选过滤字段，如 industry/code/edge_family/type",
            "default": "",
        },
        "filter_value": {
            "description": "可选过滤值",
            "default": "",
        },
    },
)
def query_kg_entities(
    entity_type: str, filter_field: str = "", filter_value: str = ""
) -> list[dict]:
    folder = _FOLDER_MAP.get(entity_type, entity_type + "s")
    return _list_entities(folder, filter_field, filter_value)


@register_tool(
    "query_kg_relations",
    "查实体关系。扫描实体的 [[]] 链接，返回关联实体列表。"
    "如「600519 关联哪些战法」「国产芯片概念有哪些股票」。",
    params={
        "entity_code": {
            "description": "实体代码或文件名，如 '600519' 或 'dragon_head'",
        },
        "entity_type": {
            "description": "实体类型（定位文件夹）",
            "enum": ["stock", "industry", "concept", "strategy", "data_source", "spec"],
            "default": "stock",
        },
    },
)
def query_kg_relations(entity_code: str, entity_type: str = "stock") -> dict:
    folder = _FOLDER_MAP.get(entity_type, entity_type + "s")
    # 找文件：试 .md 后缀 + 裸名 + 全路径
    candidates = [
        _VAULT_INVESTING / folder / f"{entity_code}.md",
        _VAULT_INVESTING / folder / entity_code,
        _VAULT_INVESTING / entity_code,
    ]
    filepath = next((p for p in candidates if p.exists() and p.is_file()), None)
    if not filepath:
        return {"error": f"实体 {entity_code} 不存在（folder={folder}）"}
    content = filepath.read_text(encoding="utf-8")
    # 提取 [[]] 链接（去别名 |xxx，去 #锚点）
    links = re.findall(r"\[\[([^\]]+)\]\]", content)
    seen: set[str] = set()
    relations: list[dict] = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        target = link.split("|")[0].split("#")[0].strip()
        if not target:
            continue
        relations.append({"target": target, "link": f"[[{link}]]"})
    return {
        "entity": entity_code,
        "entity_type": entity_type,
        "path": str(filepath.relative_to(_VAULT_INVESTING)),
        "relations": relations,
        "total": len(relations),
    }


@register_tool(
    "kg_audit",
    "知识图谱健康检查。返回各类型实体数、总实体数。",
    params={},
)
def kg_audit() -> dict:
    summary: dict[str, int] = {}
    total = 0
    for folder in _FOLDER_MAP.values():
        dir_path = _VAULT_INVESTING / folder
        if dir_path.exists():
            count = len(
                [x for x in dir_path.glob("*.md") if x.name != "index.md"]
            )
            summary[folder] = count
            total += count
        else:
            summary[folder] = 0
    return {
        "vault_path": str(_VAULT_INVESTING),
        "total_entities": total,
        "by_type": summary,
    }
