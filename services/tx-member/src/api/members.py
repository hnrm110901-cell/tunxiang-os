"""会员管理 API — Golden ID + RFM + 旅程 + 企微 SCRM 绑定"""
import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from services.repository import CustomerRepository, WecomRepository
from sqlalchemy.exc import IntegrityError

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import MemberEventType
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member", tags=["member"])


class CreateMemberReq(BaseModel):
    phone: str
    display_name: Optional[str] = None
    source: str = "manual"


# Golden ID 会员
@router.get("/customers")
async def list_customers(
    store_id: str,
    rfm_level: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    log = logger.bind(tenant_id=x_tenant_id, store_id=store_id, rfm_level=rfm_level)
    log.info("list_customers_start", page=page, size=size)

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = CustomerRepository(db, x_tenant_id)
        result = await repo.list_customers(
            store_id=store_id,
            rfm_level=rfm_level,
            page=page,
            size=size,
        )

    log.info("list_customers_ok", total=result["total"])
    return {"ok": True, "data": result}

@router.post("/customers")
async def create_customer(
    req: CreateMemberReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    log = logger.bind(tenant_id=x_tenant_id, phone=req.phone)
    log.info("create_customer_start")

    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            repo = CustomerRepository(db, x_tenant_id)
            customer = await repo.create_customer({
                "phone": req.phone,
                "display_name": req.display_name,
                "source": req.source,
            })
    except IntegrityError:
        log.warning("create_customer_duplicate_phone", phone=req.phone)
        raise HTTPException(status_code=409, detail="duplicate_phone")

    customer_id = customer["id"]
    log.info("create_customer_ok", customer_id=customer_id)

    # 发布会员注册事件（不阻塞响应）
    asyncio.create_task(emit_event(
        event_type=MemberEventType.REGISTERED,
        tenant_id=x_tenant_id,
        stream_id=customer_id,
        payload={"phone": req.phone, "source": req.source},
        source_service="tx-member",
    ))

    return {"ok": True, "data": {"customer_id": customer_id}}

@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """Golden ID 360 度画像"""
    log = logger.bind(tenant_id=x_tenant_id, customer_id=customer_id)
    log.info("get_customer_start")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = CustomerRepository(db, x_tenant_id)
        customer = await repo.get_customer(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    log.info("get_customer_ok")
    return {"ok": True, "data": customer}

@router.get("/customers/{customer_id}/orders")
async def get_customer_orders(
    customer_id: str,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    log = logger.bind(tenant_id=x_tenant_id, customer_id=customer_id)
    log.info("get_customer_orders_start", page=page, size=size)

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = CustomerRepository(db, x_tenant_id)
        # Verify customer exists first
        customer = await repo.get_customer(customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="customer_not_found")
        result = await repo.get_customer_orders(customer_id, page=page, size=size)

    log.info("get_customer_orders_ok", total=result["total"])
    return {"ok": True, "data": result}

# RFM 分析
@router.get("/rfm/segments")
async def get_rfm_segments(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """RFM 分层分布：S1-S5"""
    log = logger.bind(tenant_id=x_tenant_id, store_id=store_id)
    log.info("get_rfm_segments_start")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = CustomerRepository(db, x_tenant_id)
        result = await repo.get_rfm_segments(store_id)

    log.info("get_rfm_segments_ok", total=result["total"])
    return {"ok": True, "data": result}

@router.get("/rfm/at-risk")
async def get_at_risk_customers(
    store_id: str,
    risk_threshold: float = 0.5,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """流失风险客户列表"""
    log = logger.bind(tenant_id=x_tenant_id, store_id=store_id, risk_threshold=risk_threshold)
    log.info("get_at_risk_customers_start")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = CustomerRepository(db, x_tenant_id)
        customers = await repo.get_at_risk(store_id, threshold=risk_threshold)

    log.info("get_at_risk_customers_ok", count=len(customers))
    return {"ok": True, "data": {"customers": customers}}

# 营销活动
@router.get("/campaigns")
async def list_campaigns(store_id: str):
    return {"ok": True, "data": {"campaigns": []}}

@router.post("/campaigns")
async def create_campaign(data: dict):
    return {"ok": True, "data": {"campaign_id": "new"}}

@router.post("/campaigns/{campaign_id}/trigger")
async def trigger_campaign(campaign_id: str):
    return {"ok": True, "data": {"triggered": True}}

# 用户旅程
@router.get("/journeys")
async def list_journeys(store_id: str, status: Optional[str] = None):
    return {"ok": True, "data": {"journeys": []}}

@router.post("/journeys/trigger")
async def trigger_journey(customer_id: str, journey_type: str):
    return {"ok": True, "data": {"journey_id": "new"}}

# 身份合并
@router.post("/customers/merge")
async def merge_customers(primary_id: str, secondary_id: str):
    """Golden ID 合并"""
    return {"ok": True, "data": {"merged_into": primary_id}}


# ─────────────────────────────────────────────────────────────────
# 企微 SCRM 绑定
# ─────────────────────────────────────────────────────────────────

class WecomBindingUpdate(BaseModel):
    wecom_external_userid: Optional[str] = None
    wecom_follow_user: Optional[str] = None
    wecom_follow_at: Optional[datetime] = None
    wecom_remark: Optional[str] = None


class WecomBindByExternalIdReq(BaseModel):
    """通过企微事件回调传入的信息，找到或创建 Customer 并绑定"""
    wecom_external_userid: str
    wecom_follow_user: str
    wecom_follow_at: str            # ISO 8601
    wecom_remark: str = ""
    mobile: str = ""                # 从企微客户联系 API 获取
    unionid: str = ""               # 微信 unionid（如已授权）
    name: str = ""                  # 企微客户姓名（备用）
    state: str = ""                 # 扫码来源（store_id）


class WecomUnbindReq(BaseModel):
    wecom_external_userid: str
    follow_user: str = ""


class BatchByExternalIdsReq(BaseModel):
    external_userids: list[str]


@router.get("/customers/{customer_id}/wecom")
async def get_customer_wecom_binding(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """查询某会员的企微绑定状态"""
    log = logger.bind(customer_id=customer_id, tenant_id=x_tenant_id)
    log.info("get_customer_wecom_binding")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = WecomRepository(db, x_tenant_id)
        binding = await repo.get_wecom_binding(customer_id)

    if binding is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    return {"ok": True, "data": binding}


@router.patch("/customers/{customer_id}/wecom")
async def update_customer_wecom(
    customer_id: str,
    req: WecomBindingUpdate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """更新会员的企微绑定信息（支持部分更新）

    只允许更新 wecom_follow_user 和 wecom_remark。
    幂等：重复调用相同参数不产生副作用。
    """
    log = logger.bind(customer_id=customer_id, tenant_id=x_tenant_id)
    log.info("update_customer_wecom")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = WecomRepository(db, x_tenant_id)
        updated = await repo.update_wecom_binding(
            customer_id=customer_id,
            follow_user=req.wecom_follow_user,
            remark=req.wecom_remark,
        )

    if updated is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    log.info("update_customer_wecom_ok")
    return {"ok": True, "data": updated}


@router.post("/customers/wecom/bind_by_external_id")
async def bind_customer_by_external_id(
    req: WecomBindByExternalIdReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """通过企微 customer_add 事件绑定或创建 Customer

    处理逻辑（幂等）：
    1. 先查 wecom_external_userid —— 若已存在则更新 follow_at/follow_user（同一客户重加）
    2. 若无：优先用 unionid 查找已有 Customer，找到则绑定
    3. 若无：用 mobile 查找已有 Customer，找到则绑定
    4. 若无：创建临时档案（source="wecom_only"）
    """
    log = logger.bind(
        external_userid=req.wecom_external_userid,
        follow_user=req.wecom_follow_user,
        mobile=req.mobile,
        tenant_id=x_tenant_id,
    )
    log.info("bind_customer_by_external_id")

    try:
        follow_at = datetime.fromisoformat(req.wecom_follow_at)
    except ValueError:
        follow_at = datetime.utcnow()

    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            repo = WecomRepository(db, x_tenant_id)
            result = await repo.bind_by_external_id(
                external_userid=req.wecom_external_userid,
                follow_user=req.wecom_follow_user,
                follow_at=follow_at,
                remark=req.wecom_remark,
                mobile=req.mobile or None,
                unionid=req.unionid or None,
                name=req.name or None,
            )
    except IntegrityError as exc:
        log.error("bind_customer_integrity_error", error=str(exc.orig))
        raise HTTPException(status_code=409, detail="duplicate_phone_or_constraint_violation")

    log.info("bind_customer_by_external_id_done", **result)
    return {"ok": True, "data": result}


@router.post("/customers/wecom/unbind_by_external_id")
async def unbind_customer_by_external_id(
    req: WecomUnbindReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """处理 customer_del 事件：清空企微绑定，并打"已删除好友"标签

    幂等：如已清空则无副作用，返回 action="not_found"。
    """
    log = logger.bind(external_userid=req.wecom_external_userid, tenant_id=x_tenant_id)
    log.info("unbind_customer_by_external_id")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = WecomRepository(db, x_tenant_id)
        result = await repo.unbind_by_external_id(req.wecom_external_userid)

    log.info("unbind_customer_by_external_id_ok", action=result["action"])
    return {"ok": True, "data": result}


@router.post("/customers/wecom/batch_by_external_ids")
async def batch_get_customers_by_external_ids(
    req: BatchByExternalIdsReq,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """批量查询企微外部联系人 ID 对应的会员信息（用于导购客户列表）

    最多 100 个 external_userid；未找到的记录在结果中标记 found=False。
    """
    log = logger.bind(count=len(req.external_userids), tenant_id=x_tenant_id)
    log.info("batch_get_customers_by_external_ids")

    async with get_db_with_tenant(x_tenant_id) as db:
        repo = WecomRepository(db, x_tenant_id)
        items = await repo.batch_by_external_ids(req.external_userids)

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
        },
    }
