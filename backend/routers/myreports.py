"""
MyReports router.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any, Dict

import myreports as mr

router = APIRouter(tags=["myreports"])


class ReportIn(BaseModel):
    name: str
    content_b64: str


@router.get("/api/myreports")
def myreports_list() -> Dict[str, Any]:
    return {"data": mr.list_reports()}


@router.post("/api/myreports")
def myreports_upload(r: ReportIn) -> Dict[str, Any]:
    """上传一份研报（base64）→ 存本地 + 按文件名自动打行业标签。"""
    try:
        return {"data": mr.save_report(r.name, r.content_b64)}
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/myreports/file/{rid}")
def myreports_file(rid: str):
    """下载/预览某份研报原文件。"""
    hit = mr.report_path(rid)
    if not hit:
        raise HTTPException(404, "研报不存在")
    path, name = hit
    return FileResponse(str(path), filename=name)


@router.delete("/api/myreports/{rid}")
def myreports_delete(rid: str) -> Dict[str, Any]:
    return {"data": {"ok": mr.delete_report(rid)}}


__all__ = ["router"]
