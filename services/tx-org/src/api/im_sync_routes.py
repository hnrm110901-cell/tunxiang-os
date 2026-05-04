from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from services.im_sync_service import IMSyncConfig, push_alert_to_im
from services.im_webhook_handler import (
    handle_dingtalk_callback,
    handle_wecom_callback,
)

router = APIRouter(prefix="/api/v1/org/im-sync", tags=["im-sync"])

# ─── 辅助 ────────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(msg: str, code: str = "IM_ERROR") -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": msg}}


def _get_tenant_id(request: Request) -> str:
    """从请求头提取 tenant_id（X-Tenant-ID）。"""
    return request.headers.get("X-Tenant-ID", "")


# ─── 请求/响应模型 ───────────────────────────────────────────────────────────


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


class IMPushAlertRequest(BaseModel):
    provider: str
    corp_id: str
    corp_secret: str
    agent_id: str = ""
    user_ids: list[str]
    alert: dict[str, Any]


class IMConfigStatusData(BaseModel):
    wecom_configured: bool
    dingtalk_configured: bool
    wecom_corp_id: str
    dingtalk_app_key: str


# ─── 原有端点 ────────────────────────────────────────────────────────────────


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


# ─── 新增端点：Webhook 回调 ──────────────────────────────────────────────────


@router.post("/webhook/wecom")
async def post_wecom_webhook(request: Request):
    """企微事件回调接口。

    企微服务器会将通讯录变更等事件推送到此端点。
    生产环境需先完成 URL 验证（GET 请求回显 echostr）。
    """
    try:
        body = await request.json()
    except ValueError:
        return _err("请求体不是有效 JSON", "INVALID_BODY")

    result = await handle_wecom_callback(body)
    return _ok(result)


@router.get("/webhook/wecom")
async def get_wecom_webhook_verify(request: Request):
    """企微回调 URL 验证（回显 echostr）。"""
    echostr = request.query_params.get("echostr", "")
    return echostr


@router.post("/webhook/dingtalk")
async def post_dingtalk_webhook(request: Request):
    """钉钉事件回调接口。

    钉钉服务器会将通讯录变更等事件推送到此端点。
    """
    try:
        body = await request.json()
    except ValueError:
        return _err("请求体不是有效 JSON", "INVALID_BODY")

    result = await handle_dingtalk_callback(body)
    return _ok(result)


# ─── 新增端点：预警推送 ──────────────────────────────────────────────────────


@router.post("/push-alert")
async def post_push_alert(body: IMPushAlertRequest):
    """手动推送预警到 IM 平台。

    用于后台管理员手动触发预警通知到企微/钉钉。
    """
    if not body.user_ids:
        return _err("user_ids 不可为空", "EMPTY_USER_IDS")

    config = IMSyncConfig(
        provider=body.provider,
        corp_id=body.corp_id,
        corp_secret=body.corp_secret,
        agent_id=body.agent_id,
    )

    result = await push_alert_to_im(config, body.user_ids, body.alert)
    return _ok(result)


# ─── 新增端点：IM 配置状态 ───────────────────────────────────────────────────


@router.get("/config")
async def get_im_config():
    """获取 IM 集成配置状态。

    返回企微/钉钉是否已配置（仅返回脱敏信息）。
    当前为 Mock 实现 -- 正式版本从租户配置表读取。
    """
    import os

    wecom_corp_id = os.getenv("WECOM_CORP_ID", "")
    dingtalk_app_key = os.getenv("DINGTALK_APP_KEY", "")

    data = IMConfigStatusData(
        wecom_configured=bool(wecom_corp_id),
        dingtalk_configured=bool(dingtalk_app_key),
        wecom_corp_id=wecom_corp_id[:4] + "***" if len(wecom_corp_id) > 4 else "",
        dingtalk_app_key=dingtalk_app_key[:4] + "***" if len(dingtalk_app_key) > 4 else "",
    )
    return _ok(data.model_dump())
