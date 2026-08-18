# -*- coding: utf-8 -*-
"""投研记录笔记 API——全局可见，跨设备同步。

旧前端 Note.ts 用 localStorage（vr-notes key，"数据只存本地不上传"）。
本 router 切换为后端 SQLite 落盘（notes_repo），笔记全局可见、跨设备同步。

端点：
- GET    /api/notes           列出全部笔记（按 ts 降序）
- POST   /api/notes           新增笔记
- DELETE /api/notes/{note_id} 删除单条笔记
- DELETE /api/notes           清空全部笔记
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["notes"])


class NoteCreate(BaseModel):
    """新增笔记请求体。"""
    kind: str
    title: str
    content: str


@router.get("/api/notes")
def list_notes(limit: int = 200) -> Dict[str, Any]:
    """列出全部笔记（按 ts 降序，默认 200 条）。"""
    from notes_repo import list_notes as _list

    return {"data": _list(limit)}


@router.post("/api/notes")
def create_note(note: NoteCreate) -> Dict[str, Any]:
    """新增笔记。返新笔记 dict（含生成的 id 和 ts）。"""
    from notes_repo import add_note

    return {"data": add_note(note.kind, note.title, note.content)}


@router.delete("/api/notes/{note_id}")
def delete_note(note_id: str) -> Dict[str, Any]:
    """删除单条笔记。不存在返 404。"""
    from notes_repo import delete_note as _delete

    ok = _delete(note_id)
    if not ok:
        raise HTTPException(404, f"笔记不存在: {note_id}")
    return {"data": {"deleted": True}}


@router.delete("/api/notes")
def clear_notes() -> Dict[str, Any]:
    """清空全部笔记。返删除条数。"""
    from notes_repo import clear_notes as _clear

    count = _clear()
    return {"data": {"cleared": count}}
