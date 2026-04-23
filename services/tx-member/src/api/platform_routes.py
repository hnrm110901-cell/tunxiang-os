"""外卖平台会员绑定 API 路由

端点：
  POST /api/v1/member/platform/meituan/order     美团订单绑定（适配器调用）
  POST /api/v1/member/platform/douyin/order      抖音订单绑定
  POST /api/v1/member/platform/bind              通用平台绑定
  GET  /api/v1/member/platform/stats             平台绑定统计
  POST /api/v1/member/platform/merge-duplicates  合并重复会员（管理端）

所有端点通过 X-Tenant-ID header 传入租户 ID。
"""

import uuid
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator
from services.platform_binding_service import PlatformBindingService
from sqlalchemy.exc import IntegrityError

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/member/platform", tags=["platform-binding"])

_binding_service = PlatformBindingService()


# ─────────────────────────────────────────────────────────────────
# Request Models
# ─────────────────────────────────────────────────────────────────


class MeituanOrderReq(BaseModel):
    """美团订单绑定请求体"""

    order_no: str
    amount_fen: int  # 消费金额（分）
    store_id: str
    items: list[dict[str, Any]] = []
    phone: Optional[str] = None  # 顾客手机号
    meituan_user_id: Optional[str] = None
    meituan_openid: Optional[str] = None

    @field_validator("amount_fen")
    @classmethod
    def amount_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amount_fen 不能为负数")
        return v


class DouyinOrderReq(BaseModel):
    """抖音订单绑定请求体"""

    order_no: str
    amount_fen: int
    store_id: str
    items: list[dict[str, Any]] = []
    phone: Optional[str] = None
    douyin_openid: Optional[str] = None

    @field_validator("amount_fen")
    @classmethod
    def amount_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("amount_fen 不能为负数")
        return v


class PlatformBindReq(BaseModel):
    """通用平台绑定请求体"""

    platform: Literal["meituan", "douyin", "eleme"]
    platform_user_id: str
    phone: Optional[str] = None
    extra_data: dict[str, Any] = {}


# ─────────────────────────────────────────────────────────────────
# 端点实现
# ─────────────────────────────────────────────────────────────────


@router.post("/meituan/order")
async def bind_meituan_order(
    req: MeituanOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """美团外卖订单核销绑定

    适配器在核销事件时调用此端点，完成 Golden ID 匹配/创建。
    同一 order_no 重复调用幂等。
    """
    log = logger.bind(order_no=req.order_no, tenant_id=x_tenant_id)
    log.info("bind_meituan_order_api")

    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_tenant_id")

    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            result = await _binding_service.bind_meituan_order(
                order_data=req.model_dump(),
                tenant_id=tenant_id,
                db=db,
            )
    except IntegrityError as exc:
        log.error("bind_meituan_order_integrity_error", error=str(exc.orig))
        raise HTTPException(status_code=409, detail="constraint_violation")

    return {"ok": True, "data": result}


@router.post("/douyin/order")
async def bind_douyin_order(
    req: DouyinOrderReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """抖音团购核销绑定

    适配器在核销事件时调用此端点，完成 Golden ID 匹配/创建。
    同一 order_no 重复调用幂等。
    """
    log = logger.bind(order_no=req.order_no, tenant_id=x_tenant_id)
    log.info("bind_douyin_order_api")

    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_tenant_id")

    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            result = await _binding_service.bind_douyin_order(
                order_data=req.model_dump(),
                tenant_id=tenant_id,
                db=db,
            )
    except IntegrityError as exc:
        log.error("bind_douyin_order_integrity_error", error=str(exc.orig))
        raise HTTPException(status_code=409, detail="constraint_violation")

    return {"ok": True, "data": result}


@router.post("/bind")
async def bind_platform_user(
    req: PlatformBindReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """通用平台用户绑定

    支持 meituan / douyin / eleme 三个平台。
    可以不传 extra_data 中的 order_no / amount_fen（则不更新消费统计）。
    """
    log = logger.bind(platform=req.platform, tenant_id=x_tenant_id)
    log.info("bind_platform_user_api")

    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_tenant_id")

    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            result = await _binding_service.bind_platform_user(
                platform=req.platform,
                platform_user_id=req.platform_user_id,
                phone=req.phone,
                extra_data=req.extra_data,
                tenant_id=tenant_id,
                db=db,
            )
    except IntegrityError as exc:
        log.error("bind_platform_user_integrity_error", error=str(exc.orig))
        raise HTTPException(status_code=409, detail="constraint_violation")

    return {"ok": True, "data": result}


@router.get("/stats")
async def get_platform_binding_stats(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """各平台绑定情况统计

    返回：
      meituan/douyin/eleme 各自的 total_bound / new_today / conversion_rate
      total_cross_platform: 同时在两个以上平台消费的会员数
    """
    log = logger.bind(tenant_id=x_tenant_id)
    log.info("get_platform_stats_api")

    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_tenant_id")

    async with get_db_with_tenant(x_tenant_id) as db:
        stats = await _binding_service.get_platform_binding_stats(
            tenant_id=tenant_id,
            db=db,
        )

    return {"ok": True, "data": stats}


@router.post("/merge-duplicates")
async def merge_platform_duplicates(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """合并平台重复会员（管理端操作）

    以 primary_phone 为 key 查找同手机号的重复档案，
    将消费数据合并到最早创建的主档案，标记重复档案 is_merged=True。

    此操作不可逆，建议先在测试环境验证。
    """
    log = logger.bind(tenant_id=x_tenant_id)
    log.info("merge_platform_duplicates_api")

    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_tenant_id")

    async with get_db_with_tenant(x_tenant_id) as db:
        result = await _binding_service.merge_platform_duplicates(
            tenant_id=tenant_id,
            db=db,
        )

    return {"ok": True, "data": result}
