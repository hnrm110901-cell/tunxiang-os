from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/org/im-sync", tags=["im-sync"])


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


class IMSyncRequest(BaseModel):
    provider: str
    corp_id: str
    corp_secret: str
    agent_id: str = ""


class IMApplyRequest(BaseModel):
    provider: str
    auto_create: bool = False
    diff_id: str


class IMMessageRequest(BaseModel):
    provider: str
    user_ids: list[str]
    message: dict[str, Any]


class IMSyncStatusData(BaseModel):
    total_employees: int
    wecom_bound: int
    dingtalk_bound: int
    unbound: int


class IMPreviewEntry(BaseModel):
    im_userid: str
    name: str
    employee_id: str | None = None


class IMSyncPreviewData(BaseModel):
    to_bind: list[IMPreviewEntry]
    to_create: list[IMPreviewEntry]
    to_deactivate: list[IMPreviewEntry]
    unchanged: int


class IMSyncApplyResult(BaseModel):
    bound: int
    created: int
    deactivated: int
    errors: list[str]


class IMSendMessageResult(BaseModel):
    sent: int
    failed: int


@router.get("/status")
async def get_im_sync_status():
    """获取 IM 绑定状态概览（Mock）。"""
    data = IMSyncStatusData(
        total_employees=45,
        wecom_bound=30,
        dingtalk_bound=10,
        unbound=5,
    )
    return _ok(data.model_dump())


@router.post("/preview")
async def post_im_sync_preview(body: IMSyncRequest):
    """拉取 IM 用户并对比差异，返回预览且不执行写入（Mock）。"""
    preview = IMSyncPreviewData(
        to_bind=[
            IMPreviewEntry(im_userid="wx-001", name="张三", employee_id="emp-01"),
            IMPreviewEntry(im_userid="wx-002", name="李四", employee_id="emp-02"),
            IMPreviewEntry(im_userid="wx-003", name="王五", employee_id=None),
        ],
        to_create=[
            IMPreviewEntry(im_userid="wx-101", name="赵六", employee_id=None),
            IMPreviewEntry(im_userid="wx-102", name="钱七", employee_id=None),
        ],
        to_deactivate=[
            IMPreviewEntry(im_userid="wx-201", name="已离职用户", employee_id="emp-99"),
        ],
        unchanged=39,
    )
    return _ok(preview.model_dump())


@router.post("/apply")
async def post_im_sync_apply(body: IMApplyRequest):
    """根据 diff 应用 IM 同步结果（Mock）。"""
    result = IMSyncApplyResult(
        bound=3,
        created=0,
        deactivated=0,
        errors=[],
    )
    return _ok(result.model_dump())


@router.post("/send-message")
async def post_im_sync_send_message(body: IMMessageRequest):
    """向指定用户发送 IM 消息（Mock）。"""
    n = len(body.user_ids)
    result = IMSendMessageResult(sent=n, failed=0)
    return _ok(result.model_dump())
