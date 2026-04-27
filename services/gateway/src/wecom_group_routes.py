"""企微群运营 API 路由

POST /api/v1/wecom/groups/configs        创建群运营配置
GET  /api/v1/wecom/groups/configs        配置列表
POST /api/v1/wecom/groups/{id}/create    执行建群
POST /api/v1/wecom/groups/{id}/send      手动发消息
POST /api/v1/wecom/groups/{id}/sop       执行指定 SOP
POST /api/v1/wecom/groups/{id}/sync      同步群成员
GET  /api/v1/wecom/groups/{id}/stats     群统计
GET  /api/v1/wecom/groups/{id}/history   消息历史
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .models.wecom_group import WecomGroupConfig, WecomGroupMessage
from .response import ok
from .wecom_group_service import WecomGroupService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/wecom/groups", tags=["wecom-group"])

# 模块级服务实例（FastAPI 生命周期内复用）
_service = WecomGroupService()


# ─────────────────────────────────────────────────────────────────
# 依赖：从 Header 解析 tenant_id
# ─────────────────────────────────────────────────────────────────


def _parse_tenant_id(x_tenant_id: str) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误") from exc


async def _get_db():  # type: ignore[return]
    """数据库会话依赖（代理到 gateway 的 database 模块）"""
    try:
        from .database import get_async_session  # type: ignore[import]

        async for session in get_async_session():
            yield session
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="数据库未配置，请检查 gateway database 模块",
        ) from exc


# ─────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────


class CreateConfigRequest(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=100, description="群名称")
    target_segment_id: str = Field(..., description="关联 tx-growth 分群 ID")
    target_store_ids: list[str] = Field(default_factory=list, description="目标门店 UUID 列表（空=全部）")
    max_members: int = Field(default=200, ge=3, le=500, description="最大群成员数")
    auto_invite: bool = Field(default=True, description="是否自动邀请符合条件的新会员")
    sop_calendar: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "SOP 日历条目列表，格式：\n"
            '  daily:   {"type":"daily","time":"09:00","content":"..."}\n'
            '  weekly:  {"type":"weekly","weekday":5,"time":"17:00","content":"..."}\n'
            '  holiday: {"type":"holiday","holiday":"spring_festival","content":"..."}\n'
            '  new_dish:{"type":"new_dish","content":"..."}'
        ),
    )


class SendMessageRequest(BaseModel):
    message_type: str = Field(..., description="text | image | news | miniapp")
    content: dict[str, Any] = Field(..., description='消息内容体，如 {"content": "xxx"}')
    sent_by: str = Field(default="system", description="发送者：system 或员工企微 userid")


class ExecuteSopRequest(BaseModel):
    sop_type: str = Field(..., description="daily | weekly | holiday | new_dish | manual")
    extra_vars: dict[str, str] | None = Field(default=None, description="额外模板变量（覆盖自动查询）")


# ─────────────────────────────────────────────────────────────────
# 路由：配置管理
# ─────────────────────────────────────────────────────────────────


@router.post("/configs")
async def create_group_config(
    req: CreateConfigRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建企微群运营配置"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        config = WecomGroupConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            group_name=req.group_name,
            group_chat_id=None,
            target_segment_id=req.target_segment_id,
            target_store_ids=req.target_store_ids,
            max_members=req.max_members,
            auto_invite=req.auto_invite,
            sop_calendar=req.sop_calendar,
            status="active",
        )
        db.add(config)
        try:
            await db.commit()
            await db.refresh(config)
        except Exception as exc:  # noqa: BLE001 — DB写入失败需要回滚，兜底捕获
            await db.rollback()
            logger.error("wecom_group_config_create_db_error", error=str(exc), exc_info=True)
            raise HTTPException(status_code=500, detail="数据库写入失败") from exc

        logger.info(
            "wecom_group_config_created",
            config_id=str(config.id),
            tenant_id=str(tenant_id),
            group_name=req.group_name,
        )
        return ok(
            {
                "config_id": str(config.id),
                "group_name": config.group_name,
                "status": config.status,
                "target_segment_id": config.target_segment_id,
                "max_members": config.max_members,
            }
        )


@router.get("/configs")
async def list_group_configs(
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """配置列表（分页）"""
    tenant_id = _parse_tenant_id(x_tenant_id)

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        stmt = (
            select(WecomGroupConfig)
            .where(WecomGroupConfig.tenant_id == tenant_id)
            .order_by(WecomGroupConfig.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        configs = result.scalars().all()

        # 总数查询
        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(WecomGroupConfig).where(WecomGroupConfig.tenant_id == tenant_id)
        total_result = await db.execute(count_stmt)
        total = total_result.scalar_one()

        items = [
            {
                "config_id": str(c.id),
                "group_name": c.group_name,
                "group_chat_id": c.group_chat_id,
                "target_segment_id": c.target_segment_id,
                "max_members": c.max_members,
                "status": c.status,
                "sop_calendar_count": len(c.sop_calendar or []),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in configs
        ]
        return ok({"items": items, "total": total, "page": page, "size": size})


# ─────────────────────────────────────────────────────────────────
# 路由：群操作
# ─────────────────────────────────────────────────────────────────


@router.post("/{config_id}/create")
async def create_group(
    config_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """执行建群（根据配置创建企微群并邀请分群成员）"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    try:
        cid = UUID(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="config_id 格式错误") from exc

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.create_group(cid, tenant_id, db)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "建群失败"))
        return ok(result)


@router.post("/{config_id}/send")
async def send_group_message(
    config_id: str,
    req: SendMessageRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """手动向群发消息"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    try:
        cid = UUID(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="config_id 格式错误") from exc

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        # 查 chatid
        stmt = select(WecomGroupConfig).where(
            WecomGroupConfig.id == cid,
            WecomGroupConfig.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if config is None:
            raise HTTPException(status_code=404, detail="群配置不存在")
        if not config.group_chat_id:
            raise HTTPException(status_code=400, detail="群尚未建立（group_chat_id 为空）")

        send_result = await _service.send_group_message(
            group_chat_id=config.group_chat_id,
            message_type=req.message_type,
            content=req.content,
            tenant_id=tenant_id,
            sop_type="manual",
            db=db,
            config_id=cid,
            sent_by=req.sent_by,
        )
        return ok(send_result)


@router.post("/{config_id}/sop")
async def execute_sop(
    config_id: str,
    req: ExecuteSopRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """执行指定 SOP 类型的内容发送"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    try:
        cid = UUID(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="config_id 格式错误") from exc

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.execute_sop(
            config_id=cid,
            sop_type=req.sop_type,
            tenant_id=tenant_id,
            db=db,
            extra_vars=req.extra_vars,
        )
        if not result.get("success") and not result.get("skipped"):
            raise HTTPException(status_code=400, detail=result.get("error", "SOP 执行失败"))
        return ok(result)


@router.post("/{config_id}/sync")
async def sync_group_members(
    config_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """同步群成员（对比分群人员，返回待邀请名单）"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    try:
        cid = UUID(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="config_id 格式错误") from exc

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.sync_group_members(cid, tenant_id, db)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "同步失败"))
        return ok(result)


@router.get("/{config_id}/stats")
async def get_group_stats(
    config_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """群运营统计（消息数/成功率/成员数）"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    try:
        cid = UUID(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="config_id 格式错误") from exc

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        result = await _service.get_group_stats(cid, tenant_id, db)
        if not result.get("success", True) and result.get("error") == "config not found":
            raise HTTPException(status_code=404, detail="群配置不存在")
        return ok(result)


@router.get("/{config_id}/history")
async def get_message_history(
    config_id: str,
    page: int = 1,
    size: int = 20,
    sop_type: str | None = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """消息发送历史（分页，支持按 sop_type 过滤）"""
    tenant_id = _parse_tenant_id(x_tenant_id)
    try:
        cid = UUID(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="config_id 格式错误") from exc

    from .database import get_async_session  # type: ignore[import]

    async for db in get_async_session():
        conditions = [
            WecomGroupMessage.group_config_id == cid,
            WecomGroupMessage.tenant_id == tenant_id,
        ]
        if sop_type:
            conditions.append(WecomGroupMessage.sop_type == sop_type)

        stmt = (
            select(WecomGroupMessage)
            .where(*conditions)
            .order_by(WecomGroupMessage.sent_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        messages = result.scalars().all()

        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(WecomGroupMessage).where(*conditions)
        total_result = await db.execute(count_stmt)
        total = total_result.scalar_one()

        items = [
            {
                "message_id": str(m.id),
                "message_type": m.message_type,
                "sop_type": m.sop_type,
                "status": m.status,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "sent_by": m.sent_by,
                "error_msg": m.error_msg,
            }
            for m in messages
        ]
        return ok({"items": items, "total": total, "page": page, "size": size})
