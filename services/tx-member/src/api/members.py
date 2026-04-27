"""会员管理 API — Golden ID + RFM + 旅程 + 企微 SCRM 绑定"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from services.repository import WecomRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    rfm_level: Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            conditions = ["tenant_id = :tid", "is_deleted = false"]
            params: dict = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}

            if rfm_level:
                conditions.append("rfm_level = :rfm_level")
                params["rfm_level"] = rfm_level

            if store_id:
                conditions.append("first_store_id = :store_id")
                params["store_id"] = store_id

            where_clause = " AND ".join(conditions)

            count_result = await db.execute(
                text(f"SELECT COUNT(*) FROM customers WHERE {where_clause}"),
                params,
            )
            total = count_result.scalar() or 0

            rows_result = await db.execute(
                text(
                    f"SELECT id, primary_phone, display_name, rfm_level, source, first_store_id, created_at"
                    f" FROM customers WHERE {where_clause}"
                    f" ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
            rows = rows_result.mappings().all()

        items = [
            {
                "customer_id": str(r["id"]),
                "phone": r["primary_phone"],
                "display_name": r["display_name"],
                "rfm_level": r["rfm_level"],
                "source": r["source"],
                "first_store_id": r["first_store_id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
        return {"ok": True, "data": {"items": items, "total": total}}

    except SQLAlchemyError as exc:
        logger.error("list_customers_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/customers")
async def create_customer(
    req: CreateMemberReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    log = logger.bind(phone=req.phone, tenant_id=x_tenant_id)

    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            # 幂等检查：phone 是否已存在
            existing = await db.execute(
                text(
                    "SELECT id FROM customers"
                    " WHERE primary_phone = :phone AND tenant_id = :tid AND is_deleted = false"
                    " LIMIT 1"
                ),
                {"phone": req.phone, "tid": x_tenant_id},
            )
            row = existing.first()
            if row:
                existing_id = str(row[0])
                log.info("create_customer_idempotent", customer_id=existing_id)
                return {"ok": True, "data": {"customer_id": existing_id}}

            # INSERT 新会员
            new_id = uuid4()
            now = datetime.now(tz=timezone.utc)
            await db.execute(
                text(
                    "INSERT INTO customers"
                    " (id, tenant_id, primary_phone, display_name, source, rfm_level, created_at, updated_at, is_deleted)"
                    " VALUES (:id, :tid, :phone, :display_name, :source, :rfm_level, :created_at, :updated_at, false)"
                ),
                {
                    "id": new_id,
                    "tid": x_tenant_id,
                    "phone": req.phone,
                    "display_name": req.display_name,
                    "source": req.source,
                    "rfm_level": "S3",
                    "created_at": now,
                    "updated_at": now,
                },
            )

        log.info("create_customer_ok", customer_id=str(new_id))

        # 发布会员注册事件（不阻塞响应）
        asyncio.create_task(
            emit_event(
                event_type=MemberEventType.REGISTERED,
                tenant_id=x_tenant_id,
                stream_id=str(new_id),
                payload={"phone": req.phone, "source": req.source},
                store_id=None,
                source_service="tx-member",
            )
        )

        return {"ok": True, "data": {"customer_id": str(new_id)}}

    except SQLAlchemyError as exc:
        log.error("create_customer_db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="db_error")


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """Golden ID 360 度画像"""
    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            result = await db.execute(
                text(
                    "SELECT id, primary_phone, display_name, rfm_level, source,"
                    " first_store_id, total_order_count, total_spend_fen, created_at, updated_at"
                    " FROM customers"
                    " WHERE id = :id AND tenant_id = :tid AND is_deleted = false"
                    " LIMIT 1"
                ),
                {"id": customer_id, "tid": x_tenant_id},
            )
            row = result.mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="customer_not_found")

        return {
            "ok": True,
            "data": {
                "customer_id": str(row["id"]),
                "phone": row["primary_phone"],
                "display_name": row["display_name"],
                "rfm_level": row["rfm_level"],
                "source": row["source"],
                "first_store_id": row["first_store_id"],
                "total_order_count": row["total_order_count"],
                "total_spend_fen": row["total_spend_fen"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("get_customer_db_error", error=str(exc), customer_id=customer_id)
        raise HTTPException(status_code=500, detail="db_error")


@router.get("/customers/{customer_id}/orders")
async def get_customer_orders(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = 1,
    size: int = 20,
):
    try:
        async with get_db_with_tenant(x_tenant_id) as db:
            count_result = await db.execute(
                text(
                    "SELECT COUNT(*) FROM orders WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false"
                ),
                {"cid": customer_id, "tid": x_tenant_id},
            )
            total = count_result.scalar() or 0

            rows_result = await db.execute(
                text(
                    "SELECT id, order_no, store_id, order_type, status,"
                    " total_amount_fen, final_amount_fen, order_time, created_at"
                    " FROM orders"
                    " WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false"
                    " ORDER BY created_at DESC"
                    " LIMIT :limit OFFSET :offset"
                ),
                {"cid": customer_id, "tid": x_tenant_id, "limit": size, "offset": (page - 1) * size},
            )
            rows = rows_result.mappings().all()

        items = [
            {
                "order_id": str(r["id"]),
                "order_no": r["order_no"],
                "store_id": str(r["store_id"]),
                "order_type": r["order_type"],
                "status": r["status"],
                "total_amount_fen": r["total_amount_fen"],
                "final_amount_fen": r["final_amount_fen"],
                "order_time": r["order_time"].isoformat() if r["order_time"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
        return {"ok": True, "data": {"items": items, "total": total}}

    except SQLAlchemyError as exc:
        logger.error("get_customer_orders_db_error", error=str(exc), customer_id=customer_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


# RFM 分析
@router.get("/rfm/segments")
async def get_rfm_segments(store_id: str):
    """RFM 分层分布：S1-S5"""
    return {"ok": True, "data": {"segments": {}}}


@router.get("/rfm/at-risk")
async def get_at_risk_customers(store_id: str, risk_threshold: float = 0.5):
    """流失风险客户列表"""
    return {"ok": True, "data": {"customers": []}}


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
    wecom_follow_at: str  # ISO 8601
    wecom_remark: str = ""
    mobile: str = ""  # 从企微客户联系 API 获取
    unionid: str = ""  # 微信 unionid（如已授权）
    name: str = ""  # 企微客户姓名（备用）
    state: str = ""  # 扫码来源（store_id）


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
