"""跨品牌会员权益穿越 API 路由

安全说明：
  - 所有路由要求 X-Group-ID header（标识操作的集团 ID）
  - POST 写操作额外要求 X-Tenant-ID header（标识操作品牌，用于审计）
  - member_data_shared=False 时 GET /members/{phone}/profile 返回 403
  - 每次跨品牌查询均写入 cross_brand_transactions 审计日志

响应格式统一：{ "ok": bool, "data": {}, "error": {} }
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from services.group_member_service import (
    CrossBrandNotAllowedError,
    CrossBrandProfile,
    CrossBrandTransaction,
    GroupMemberProfile,
    GroupMemberService,
    GroupNotFoundError,
    InsufficientPointsError,
    TenantNotInGroupError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/group", tags=["group-member"])


# ─────────────────────────────────────────────────────────────────
# 请求体模型
# ─────────────────────────────────────────────────────────────────


class EarnPointsBody(BaseModel):
    group_id: UUID = Field(..., description="集团 ID")
    points: int = Field(..., gt=0, description="积分数量（正整数）")
    source_tenant_id: UUID = Field(..., description="来源品牌 tenant_id")
    order_id: Optional[UUID] = Field(None, description="关联订单（可选）")


class UsePointsBody(BaseModel):
    group_id: UUID = Field(..., description="集团 ID")
    points: int = Field(..., gt=0, description="积分数量（正整数）")
    target_tenant_id: UUID = Field(..., description="使用积分的品牌 tenant_id")
    order_id: Optional[UUID] = Field(None, description="关联订单（可选）")


class TransferPointsBody(BaseModel):
    group_id: UUID = Field(..., description="集团 ID")
    from_tenant_id: UUID = Field(..., description="来源品牌 tenant_id")
    to_tenant_id: UUID = Field(..., description="目标品牌 tenant_id")
    points: int = Field(..., gt=0, description="转移积分数量（正整数）")


# ─────────────────────────────────────────────────────────────────
# 依赖项：解析 X-Group-ID / X-Tenant-ID header
# ─────────────────────────────────────────────────────────────────


def _require_group_id(
    x_group_id: str = Header(..., alias="X-Group-ID"),
) -> UUID:
    """从 X-Group-ID header 解析集团 UUID。"""
    try:
        return UUID(x_group_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid X-Group-ID: {x_group_id}") from e


def _require_tenant_id(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> UUID:
    """从 X-Tenant-ID header 解析品牌 UUID（写操作必须）。"""
    try:
        return UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid X-Tenant-ID: {x_tenant_id}") from e


def _optional_operator_id(
    x_operator_id: str = Header(default="", alias="X-Operator-ID"),
) -> Optional[UUID]:
    """从 X-Operator-ID header 解析操作员 UUID（可选）。"""
    if not x_operator_id:
        return None
    try:
        return UUID(x_operator_id)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────
# 统一响应包装 & 异常处理
# ─────────────────────────────────────────────────────────────────


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


def _handle_service_error(exc: Exception) -> None:
    """将服务层异常映射到 HTTP 错误码。"""
    if isinstance(exc, CrossBrandNotAllowedError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, InsufficientPointsError):
        raise HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, GroupNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TenantNotInGroupError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


# ─────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────


@router.get(
    "/members/{phone}/profile",
    summary="集团会员档案（跨品牌全貌）",
    description=(
        "返回会员在该集团下的聚合档案：集团积分池 + 各品牌储值余额。\n\n"
        "**安全要求**：brand_groups.member_data_shared 必须为 True，否则返回 403。\n"
        "**审计**：每次调用均写入 cross_brand_transactions（type=stored_value_query）。"
    ),
)
async def get_group_member_profile(
    phone: str,
    group_id: UUID = Depends(_require_group_id),
    requesting_tenant_id: UUID = Depends(_require_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = GroupMemberService(tenant_db=db)
    try:
        profile: CrossBrandProfile = await svc.get_cross_brand_profile(
            group_id=group_id,
            phone=phone,
            requesting_tenant_id=requesting_tenant_id,
        )
    except (
        CrossBrandNotAllowedError,
        GroupNotFoundError,
        TenantNotInGroupError,
        InsufficientPointsError,
        ValueError,
    ) as exc:
        _handle_service_error(exc)

    return _ok(profile.model_dump())


@router.get(
    "/members/{phone}/cross-brand-history",
    summary="跨品牌消费记录（分页）",
)
async def get_cross_brand_history(
    phone: str,
    group_id: UUID = Depends(_require_group_id),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = GroupMemberService(tenant_db=db)
    try:
        transactions, total = await svc.get_cross_brand_history(
            group_id=group_id,
            phone=phone,
            page=page,
            size=size,
        )
    except (GroupNotFoundError, ValueError) as exc:
        _handle_service_error(exc)

    return _ok(
        {
            "items": [t.model_dump() for t in transactions],
            "total": total,
            "page": page,
            "size": size,
        }
    )


@router.post(
    "/members/{phone}/points/earn",
    summary="积累集团积分",
    description="消费后积累集团积分池。写入 cross_brand_transactions（type=points_earn）。",
)
async def earn_group_points(
    phone: str,
    body: EarnPointsBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = GroupMemberService(tenant_db=db)
    try:
        updated: GroupMemberProfile = await svc.earn_group_points(
            group_id=body.group_id,
            phone=phone,
            points=body.points,
            source_tenant_id=body.source_tenant_id,
            order_id=body.order_id,
        )
    except (GroupNotFoundError, TenantNotInGroupError, ValueError) as exc:
        _handle_service_error(exc)

    return _ok(updated.model_dump())


@router.post(
    "/members/{phone}/points/use",
    summary="使用集团积分",
    description=("在指定品牌消费集团积分。使用行锁防止并发超扣。\n写入 cross_brand_transactions（type=points_use）。"),
)
async def use_group_points(
    phone: str,
    body: UsePointsBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = GroupMemberService(tenant_db=db)
    try:
        updated: GroupMemberProfile = await svc.use_group_points(
            group_id=body.group_id,
            phone=phone,
            points=body.points,
            target_tenant_id=body.target_tenant_id,
            order_id=body.order_id,
        )
    except (
        InsufficientPointsError,
        GroupNotFoundError,
        TenantNotInGroupError,
        ValueError,
    ) as exc:
        _handle_service_error(exc)

    return _ok(updated.model_dump())


@router.post(
    "/members/{phone}/points/transfer",
    summary="积分品牌间转移",
    description=(
        "将集团积分从一个品牌归属转移到另一个品牌（两个品牌必须属于同一集团）。\n"
        "写入 cross_brand_transactions（type=points_transfer）。"
    ),
)
async def transfer_points(
    phone: str,
    body: TransferPointsBody,
    operator_id: Optional[UUID] = Depends(_optional_operator_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if operator_id is None:
        # 转移操作需要操作员身份，未提供时使用 from_tenant_id 作为默认标识
        operator_id = body.from_tenant_id

    svc = GroupMemberService(tenant_db=db)
    try:
        txn: CrossBrandTransaction = await svc.transfer_points(
            group_id=body.group_id,
            phone=phone,
            from_tenant_id=body.from_tenant_id,
            to_tenant_id=body.to_tenant_id,
            points=body.points,
            operator_id=operator_id,
        )
    except (
        InsufficientPointsError,
        GroupNotFoundError,
        TenantNotInGroupError,
        ValueError,
    ) as exc:
        _handle_service_error(exc)

    return _ok(txn.model_dump())


@router.get(
    "/config/{group_id}/interop",
    summary="查询集团互通配置",
    description="返回集团是否开启储值卡互通（stored_value_interop）。",
)
async def get_interop_config(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = GroupMemberService(tenant_db=db)
    try:
        interop_enabled = await svc.check_stored_value_interop(group_id=group_id)
    except GroupNotFoundError as exc:
        _handle_service_error(exc)

    return _ok(
        {
            "group_id": str(group_id),
            "stored_value_interop": interop_enabled,
        }
    )
