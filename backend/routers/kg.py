"""知识图谱 router（S216 P1 Cognition /api/kg/*）。

复用 ai.tools.kg_tools 读 Obsidian Vault markdown，返图谱客观数据（实体元数据/
关系链接）。三 endpoint：entities（列实体）/ inbox（M7 待审队列）/ flow（关系流）。

合规（CLAUDE.md §1.2 工程底线）：
- 不臆造：缺数据返空 + data_status='empty'，不伪造假数据
- 私有数据隔离：只返图谱客观数据（实体 frontmatter/关系链接），持仓/研报/API key 不进 endpoint
- 不碰选股分（scoring.py）/§44v2（lift_for_arm）——只读图谱客观数据
"""
from __future__ import annotations

import importlib
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["kg"])


def _kg():
    """import kg_tools（按 package 方式，参考 stock_data.py:363 模式）。

    ai 包用相对导入（from .registry import），须 import_module 非 importlib。
    """
    try:
        return importlib.import_module("ai.tools.kg_tools")
    except ModuleNotFoundError as e:
        raise HTTPException(501, f"kg_tools 不可用: {e}") from e


@router.get("/api/kg/entities")
def kg_entities(
    entity_type: str = Query(
        "stock",
        description="实体类型: stock/industry/concept/strategy/data_source/spec/event/inbox 等",
    ),
    filter_field: str = Query("", description="可选过滤字段，如 industry/code/edge_family"),
    filter_value: str = Query("", description="可选过滤值"),
) -> Dict[str, Any]:
    """列某类型实体 frontmatter（跳过 index.md）。

    复用 kg_tools.query_kg_entities。entity_type=inbox 返 M7 LLM 注入待审队列。
    缺数据返空 list + data_status='empty'，不臆造。
    """
    try:
        kg = _kg()
        entities = kg.query_kg_entities(entity_type, filter_field, filter_value)
        return {
            "data": {
                "entity_type": entity_type,
                "entities": entities,
                "count": len(entities),
                "data_status": "ok" if entities else "empty",
            }
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"kg entities 查询异常: {e}") from e


@router.get("/api/kg/inbox")
def kg_inbox() -> Dict[str, Any]:
    """M7 LLM 注入的待审队列（图谱 inbox/ 目录）。

    M7 = DeepSeek 公告→JSON→图谱 inbox 待审，审过进正式区。客观数据（实体
    frontmatter），无私有数据。缺数据返空 + data_status='empty' 不臆造。
    """
    try:
        kg = _kg()
        entities = kg.query_kg_entities("inbox")
        return {
            "data": {
                "entities": entities,
                "count": len(entities),
                "data_status": "ok" if entities else "empty",
                "note": "M7 LLM 注入的待审公告 JSON，审过进正式区（图谱 inbox/ 目录）",
            }
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"kg inbox 查询异常: {e}") from e


@router.get("/api/kg/flow")
def kg_flow(
    entity_code: str = Query(..., description="实体代码或文件名，如 600519 或 dragon_head"),
    entity_type: str = Query("stock", description="实体类型（定位文件夹）"),
) -> Dict[str, Any]:
    """实体关系流（[[]] 链接列表）。

    复用 kg_tools.query_kg_relations。返 {entity, entity_type, path, relations, total}。
    实体不存在返 404，不臆造关系。
    """
    try:
        kg = _kg()
        result = kg.query_kg_relations(entity_code, entity_type)
        if result.get("error"):
            raise HTTPException(404, result["error"])
        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"kg flow 查询异常: {e}") from e


__all__ = ["router"]
