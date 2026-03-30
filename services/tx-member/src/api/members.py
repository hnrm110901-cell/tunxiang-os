"""会员管理 API — Golden ID + RFM + 旅程 + 企微 SCRM 绑定"""
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/member", tags=["member"])


class CreateMemberReq(BaseModel):
    phone: str
    display_name: Optional[str] = None
    source: str = "manual"


# Golden ID 会员
@router.get("/customers")
async def list_customers(store_id: str, rfm_level: Optional[str] = None, page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}

@router.post("/customers")
async def create_customer(req: CreateMemberReq):
    return {"ok": True, "data": {"customer_id": "new"}}

@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Golden ID 360 度画像"""
    return {"ok": True, "data": None}

@router.get("/customers/{customer_id}/orders")
async def get_customer_orders(customer_id: str, page: int = 1, size: int = 20):
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
async def get_customer_wecom_binding(customer_id: str) -> dict:
    """查询某会员的企微绑定状态"""
    # TODO: 从数据库查询 Customer.wecom_external_userid / wecom_follow_user / wecom_follow_at
    logger.info("get_customer_wecom_binding", customer_id=customer_id)
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "wecom_external_userid": None,
            "wecom_follow_user": None,
            "wecom_follow_at": None,
            "wecom_remark": None,
        },
    }


@router.patch("/customers/{customer_id}/wecom")
async def update_customer_wecom(
    customer_id: str,
    req: WecomBindingUpdate,
) -> dict:
    """更新会员的企微绑定信息（支持部分更新）

    幂等：重复调用相同参数不产生副作用。
    """
    log = logger.bind(customer_id=customer_id, external_userid=req.wecom_external_userid)
    log.info("update_customer_wecom")

    # TODO: 查询 Customer by customer_id；若不存在则 raise 404
    # TODO: UPDATE customers SET
    #         wecom_external_userid = :wecom_external_userid,
    #         wecom_follow_user = :wecom_follow_user,
    #         wecom_follow_at = :wecom_follow_at,
    #         wecom_remark = :wecom_remark,
    #         updated_at = NOW()
    #       WHERE id = :customer_id AND tenant_id = current_setting('app.tenant_id')::uuid

    log.info("update_customer_wecom_ok")
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "wecom_external_userid": req.wecom_external_userid,
            "wecom_follow_user": req.wecom_follow_user,
        },
    }


@router.post("/customers/wecom/bind_by_external_id")
async def bind_customer_by_external_id(req: WecomBindByExternalIdReq) -> dict:
    """通过企微 customer_add 事件绑定或创建 Customer

    处理逻辑（幂等）：
    1. 先查 wecom_external_userid —— 若已存在则更新 follow_at/follow_user（同一客户重加）
    2. 若无：用 mobile 或 unionid 查找已有 Customer，找到则绑定
    3. 若无：创建临时档案（source="wecom_only"），等待会员注册后通过手机号/unionid 合并
    """
    log = logger.bind(
        external_userid=req.wecom_external_userid,
        follow_user=req.wecom_follow_user,
        mobile=req.mobile,
    )
    log.info("bind_customer_by_external_id")

    # ── Step 1: 查 wecom_external_userid 是否已存在 ──────────────
    # TODO: SELECT id FROM customers
    #       WHERE wecom_external_userid = :external_userid
    #         AND tenant_id = current_setting('app.tenant_id')::uuid
    #         AND is_deleted = false
    existing_by_external = None  # placeholder

    if existing_by_external:
        # 已绑定 — 更新跟进信息（幂等）
        # TODO: UPDATE customers SET wecom_follow_user=..., wecom_follow_at=..., updated_at=NOW()
        log.info("bind_customer_by_external_id_updated", customer_id=str(existing_by_external))
        return {"ok": True, "data": {"customer_id": str(existing_by_external), "created": False}}

    # ── Step 2: 用 mobile 或 unionid 查找已有 Customer ───────────
    existing_by_identity = None  # placeholder
    if req.mobile:
        # TODO: SELECT id FROM customers WHERE primary_phone = :mobile AND ...
        pass
    if not existing_by_identity and req.unionid:
        # TODO: SELECT id FROM customers WHERE wechat_unionid = :unionid AND ...
        pass

    if existing_by_identity:
        # 找到已有 Customer — 绑定企微信息
        # TODO: UPDATE customers SET wecom_external_userid=..., wecom_follow_user=..., ...
        log.info("bind_customer_by_external_id_linked", customer_id=str(existing_by_identity))
        return {"ok": True, "data": {"customer_id": str(existing_by_identity), "created": False}}

    # ── Step 3: 创建临时档案 ──────────────────────────────────────
    # TODO: INSERT INTO customers (tenant_id, primary_phone, display_name, source,
    #           wecom_external_userid, wecom_follow_user, wecom_follow_at, wecom_remark, ...)
    #       VALUES (current_setting('app.tenant_id')::uuid, :mobile_or_placeholder, :name,
    #           'wecom_only', :external_userid, :follow_user, :follow_at, '', ...)
    #       RETURNING id
    temp_customer_id = "temp_placeholder"
    log.info("bind_customer_by_external_id_created_temp", customer_id=temp_customer_id)
    return {"ok": True, "data": {"customer_id": temp_customer_id, "created": True}}


@router.post("/customers/wecom/unbind_by_external_id")
async def unbind_customer_by_external_id(req: WecomUnbindReq) -> dict:
    """处理 customer_del 事件：清空企微绑定，并打"已删除好友"标签

    幂等：如已清空则无副作用。
    """
    log = logger.bind(external_userid=req.wecom_external_userid)
    log.info("unbind_customer_by_external_id")

    # TODO: UPDATE customers
    #       SET wecom_external_userid = NULL,
    #           wecom_follow_user = NULL,
    #           tags = array_append(COALESCE(tags, '[]'::jsonb), '"已删除好友"'),
    #           updated_at = NOW()
    #       WHERE wecom_external_userid = :external_userid
    #         AND tenant_id = current_setting('app.tenant_id')::uuid
    #         AND is_deleted = false

    log.info("unbind_customer_by_external_id_ok")
    return {"ok": True, "data": {"wecom_external_userid": req.wecom_external_userid, "unbound": True}}


@router.post("/customers/wecom/batch_by_external_ids")
async def batch_get_customers_by_external_ids(req: BatchByExternalIdsReq) -> dict:
    """批量查询企微外部联系人 ID 对应的会员信息（用于导购客户列表）"""
    log = logger.bind(count=len(req.external_userids))
    log.info("batch_get_customers_by_external_ids")

    # TODO: SELECT id, display_name, primary_phone, wechat_nickname,
    #              rfm_level, last_order_at, total_order_amount_fen,
    #              wecom_external_userid, wecom_follow_user, wecom_follow_at, wecom_remark
    #       FROM customers
    #       WHERE wecom_external_userid = ANY(:external_userids)
    #         AND tenant_id = current_setting('app.tenant_id')::uuid
    #         AND is_deleted = false

    return {
        "ok": True,
        "data": {
            "items": [],
            "total": 0,
        },
    }
