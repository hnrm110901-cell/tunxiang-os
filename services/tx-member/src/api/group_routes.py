"""集团视角跨品牌 API 路由

权限说明：
  集团 API 需要「集团管理员」角色才能访问。
  当前采用简单 Header `X-Group-Admin: true` 标识（临时方案），
  后续接入完整权限系统（RBAC + JWT role claims）时替换 _require_group_admin 依赖项。

响应格式统一：{ "ok": bool, "data": {}, "error": {} }
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from models.group_config import BrandGroup
from pydantic import BaseModel, Field
from services.group_analytics import GroupAnalyticsService
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/groups", tags=["group"])

_analytics_service = GroupAnalyticsService()


# ─────────────────────────────────────────────────────────────────
# 依赖项：集团管理员鉴权（临时 Header 方案）
# ─────────────────────────────────────────────────────────────────

def _require_group_admin(
    x_group_admin: str = Header(default="false", alias="X-Group-Admin"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
) -> str:
    """校验集团管理员身份，返回 group_tenant_id。

    临时方案：Header X-Group-Admin: true + X-Tenant-ID = 集团主租户 ID。
    后续接入 JWT role claims 时，替换此依赖项即可，路由无需修改。
    """
    if x_group_admin.lower() != "true":
        raise HTTPException(
            status_code=403,
            detail="group_admin_required: X-Group-Admin: true header missing",
        )
    if not x_tenant_id:
        raise HTTPException(
            status_code=400,
            detail="x_tenant_id_required: X-Tenant-ID header missing",
        )
    return x_tenant_id


# ─────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────

class CreateBrandGroupReq(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=100, description="集团名称")
    group_code: str = Field(..., min_length=1, max_length=50, description="集团唯一标识码")
    brand_tenant_ids: list[str] = Field(
        default_factory=list, description="旗下品牌 tenant_id 列表（UUID 字符串）"
    )
    stored_value_interop: bool = Field(default=False, description="储值卡是否跨品牌互通")
    member_data_shared: bool = Field(default=False, description="会员数据是否集团共享")
    operator_id: Optional[str] = Field(default=None, description="操作人 UUID")


class UpdateBrandListReq(BaseModel):
    brand_tenant_ids: list[str] = Field(..., description="新的品牌 tenant_id 完整列表")
    operator_id: Optional[str] = Field(default=None, description="操作人 UUID")


class StoredValueInteropReq(BaseModel):
    interop: bool = Field(..., description="True=开启跨品牌互通，False=关闭")
    operator_id: str = Field(..., description="操作人 UUID（必填，用于审计）")


# ─────────────────────────────────────────────────────────────────
# A. 创建品牌组
# ─────────────────────────────────────────────────────────────────

@router.post("", summary="创建品牌组（集团管理员）")
async def create_brand_group(
    req: CreateBrandGroupReq,
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """创建品牌组配置。

    - group_code 全局唯一（数据库 UNIQUE 约束兜底）
    - tenant_id 为集团主租户 ID（来自 X-Tenant-ID header）
    """
    log = logger.bind(group_code=req.group_code, tenant=group_tenant_id[-8:])

    # 校验 brand_tenant_ids 格式
    try:
        brand_uuids = [str(uuid.UUID(tid)) for tid in req.brand_tenant_ids]
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid brand_tenant_id format: {exc}"
        ) from exc

    operator_id: uuid.UUID | None = None
    if req.operator_id:
        try:
            operator_id = uuid.UUID(req.operator_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid operator_id: {exc}"
            ) from exc

    group = BrandGroup(
        tenant_id=uuid.UUID(group_tenant_id),
        group_name=req.group_name,
        group_code=req.group_code,
        brand_tenant_ids=brand_uuids,
        stored_value_interop=req.stored_value_interop,
        member_data_shared=req.member_data_shared,
        status="active",
        created_by=operator_id,
        updated_by=operator_id,
    )
    db.add(group)
    await db.flush()
    await db.commit()

    log.info("brand_group_created", group_id=str(group.id))

    return {
        "ok": True,
        "data": {
            "group_id": str(group.id),
            "group_code": group.group_code,
            "group_name": group.group_name,
            "brand_count": len(brand_uuids),
        },
    }


# ─────────────────────────────────────────────────────────────────
# B. 集团配置详情
# ─────────────────────────────────────────────────────────────────

@router.get("/{group_id}", summary="集团配置详情")
async def get_brand_group(
    group_id: uuid.UUID,
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """查询品牌组配置详情（含旗下品牌列表和策略开关）。"""
    from sqlalchemy import select, text

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": group_tenant_id},
    )
    result = await db.execute(
        select(BrandGroup)
        .where(BrandGroup.id == group_id)
        .where(BrandGroup.tenant_id == uuid.UUID(group_tenant_id))
        .where(BrandGroup.is_deleted == False)  # noqa: E712
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="brand_group_not_found")

    return {
        "ok": True,
        "data": {
            "group_id": str(group.id),
            "group_name": group.group_name,
            "group_code": group.group_code,
            "brand_tenant_ids": group.brand_tenant_ids,
            "brand_count": len(group.brand_tenant_ids),
            "stored_value_interop": group.stored_value_interop,
            "member_data_shared": group.member_data_shared,
            "status": group.status,
            "created_at": group.created_at.isoformat(),
            "updated_at": group.updated_at.isoformat(),
        },
    }


# ─────────────────────────────────────────────────────────────────
# C. 更新旗下品牌列表
# ─────────────────────────────────────────────────────────────────

@router.put("/{group_id}/brands", summary="更新旗下品牌列表")
async def update_brand_list(
    group_id: uuid.UUID,
    req: UpdateBrandListReq,
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """替换品牌组旗下的品牌 tenant_id 完整列表（全量替换语义）。"""
    from sqlalchemy import select, text

    try:
        brand_uuids = [str(uuid.UUID(tid)) for tid in req.brand_tenant_ids]
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid brand_tenant_id format: {exc}"
        ) from exc

    operator_id: uuid.UUID | None = None
    if req.operator_id:
        try:
            operator_id = uuid.UUID(req.operator_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid operator_id: {exc}"
            ) from exc

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": group_tenant_id},
    )
    result = await db.execute(
        select(BrandGroup)
        .where(BrandGroup.id == group_id)
        .where(BrandGroup.tenant_id == uuid.UUID(group_tenant_id))
        .where(BrandGroup.is_deleted == False)  # noqa: E712
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="brand_group_not_found")

    old_count = len(group.brand_tenant_ids)
    group.brand_tenant_ids = brand_uuids
    group.updated_by = operator_id
    await db.flush()
    await db.commit()

    logger.info(
        "brand_list_updated",
        group_id=str(group_id),
        old_count=old_count,
        new_count=len(brand_uuids),
    )

    return {
        "ok": True,
        "data": {
            "group_id": str(group_id),
            "brand_count": len(brand_uuids),
            "brand_tenant_ids": brand_uuids,
        },
    }


# ─────────────────────────────────────────────────────────────────
# D. 集团 RFM 总览
# ─────────────────────────────────────────────────────────────────

@router.get("/{group_id}/dashboard", summary="集团 RFM 总览")
async def get_group_dashboard(
    group_id: uuid.UUID,
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """集团 RFM 总览（跨品牌汇总，手机号去重）。

    - group_total_members：按手机号去重的会员总数
    - cross_brand_members：在 2 个以上品牌消费过的人数
    - group_rfm_distribution：每人取最高 RFM 等级后的分布
    """
    data = await _analytics_service.get_group_rfm_dashboard(
        group_id=group_id,
        group_tenant_id=group_tenant_id,
        db=db,
    )
    return {"ok": True, "data": data}


# ─────────────────────────────────────────────────────────────────
# E. 跨品牌会员全貌（by phone）
# ─────────────────────────────────────────────────────────────────

@router.get("/{group_id}/member-profile", summary="跨品牌会员全貌（by phone）")
async def get_group_member_profile(
    group_id: uuid.UUID,
    phone: str = Query(..., description="手机号（精确匹配）"),
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """查询某手机号在集团所有品牌的会员信息（跨品牌全貌）。

    并发查询各品牌，汇总消费金额和订单数。
    """
    data = await _analytics_service.get_group_member_profile(
        phone=phone,
        group_id=group_id,
        group_tenant_id=group_tenant_id,
        db=db,
    )
    return {"ok": True, "data": data}


# ─────────────────────────────────────────────────────────────────
# F. 集团流失风险
# ─────────────────────────────────────────────────────────────────

@router.get("/{group_id}/churn-risk", summary="集团流失风险汇总")
async def get_group_churn_risk(
    group_id: uuid.UUID,
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """集团维度流失风险汇总。

    - high_risk_count：跨品牌去重的高风险人数（>60 天未消费）
    - top_at_risk：最有价值的高风险客户（TOP 20，按历史消费金额降序）
    """
    data = await _analytics_service.get_group_churn_risk(
        group_id=group_id,
        group_tenant_id=group_tenant_id,
        db=db,
    )
    return {"ok": True, "data": data}


# ─────────────────────────────────────────────────────────────────
# G. 跨品牌消费客户
# ─────────────────────────────────────────────────────────────────

@router.get("/{group_id}/cross-brand", summary="跨品牌消费客户列表")
async def get_cross_brand_customers(
    group_id: uuid.UUID,
    min_brands: int = Query(default=2, ge=2, le=20, description="最少出现品牌数"),
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """找出在 N 个以上品牌消费过的客户（集团最核心的高价值客户）。

    结果按跨品牌总消费金额降序排列。
    """
    data = await _analytics_service.find_cross_brand_customers(
        group_id=group_id,
        group_tenant_id=group_tenant_id,
        min_brands=min_brands,
        db=db,
    )
    return {"ok": True, "data": data}


# ─────────────────────────────────────────────────────────────────
# H. 储值互通配置
# ─────────────────────────────────────────────────────────────────

@router.post("/{group_id}/stored-value-interop", summary="储值卡跨品牌互通配置")
async def configure_stored_value_interop(
    group_id: uuid.UUID,
    req: StoredValueInteropReq,
    group_tenant_id: str = Depends(_require_group_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """开启或关闭储值卡跨品牌互通。

    注意：本接口仅更新集团配置开关。
    各品牌 StoredValueCard.scope_type 的实际同步由异步任务完成（Redis Stream 事件驱动）。
    开启后需等待异步任务执行完毕，各品牌储值卡才真正生效互通。
    """
    try:
        operator_uuid = uuid.UUID(req.operator_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid operator_id: {exc}"
        ) from exc

    data = await _analytics_service.configure_stored_value_interop(
        group_id=group_id,
        interop=req.interop,
        operator_id=operator_uuid,
        group_tenant_id=group_tenant_id,
        db=db,
    )
    return {"ok": True, "data": data}
