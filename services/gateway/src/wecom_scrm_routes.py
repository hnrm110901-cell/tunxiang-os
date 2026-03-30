"""企微 SCRM 管理 API

GET  /api/v1/wecom/contacts/{customer_id}      查询某会员的企微绑定状态
POST /api/v1/wecom/contacts/bind               手动绑定企微 ID 与会员 ID
POST /api/v1/wecom/contacts/qrcode             生成门店企微活码（导购专属）
GET  /api/v1/wecom/contacts/staff/{user_id}    获取某导购的所有客户列表
"""
from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from .wecom_contact import WecomAPIError, wecom_contact_sdk

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/wecom/contacts", tags=["wecom-scrm"])

_MEMBER_SERVICE_URL: str = __import__("os").getenv("TX_MEMBER_URL", "http://tx-member:8004")


# ─────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────

class BindWecomRequest(BaseModel):
    customer_id: str
    wecom_external_userid: str
    wecom_follow_user: str | None = None
    wecom_remark: str | None = None


class QrcodeRequest(BaseModel):
    store_id: str                     # 作为 state 传递，回调时可识别来源
    user_id: str | None = None        # 导购专属时指定企微 userid
    remark: str = "门店扫码"


# ─────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────

@router.get("/{customer_id}")
async def get_wecom_binding(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询某会员的企微绑定状态"""
    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.get(
                f"{_MEMBER_SERVICE_URL}/api/v1/member/customers/{customer_id}/wecom",
                headers={"X-Tenant-ID": x_tenant_id},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="customer not found") from exc
            logger.error(
                "wecom_scrm_get_binding_http_error",
                customer_id=customer_id,
                status=exc.response.status_code,
            )
            raise HTTPException(status_code=502, detail="member service error") from exc
        except httpx.ConnectError as exc:
            logger.error("wecom_scrm_get_binding_connect_error", error=str(exc))
            raise HTTPException(status_code=503, detail="member service unavailable") from exc
        except httpx.TimeoutException as exc:
            logger.error("wecom_scrm_get_binding_timeout", error=str(exc))
            raise HTTPException(status_code=504, detail="member service timeout") from exc

    return resp.json()


@router.post("/bind")
async def bind_wecom_contact(
    req: BindWecomRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """手动绑定企微外部联系人 ID 与会员 ID

    幂等：重复绑定同一对 (customer_id, external_userid) 不报错。
    """
    log = logger.bind(
        customer_id=req.customer_id,
        external_userid=req.wecom_external_userid,
    )
    log.info("wecom_scrm_manual_bind")

    payload = {
        "wecom_external_userid": req.wecom_external_userid,
        "wecom_follow_user": req.wecom_follow_user,
        "wecom_remark": req.wecom_remark,
    }

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.patch(
                f"{_MEMBER_SERVICE_URL}/api/v1/member/customers/{req.customer_id}/wecom",
                json=payload,
                headers={"X-Tenant-ID": x_tenant_id},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="customer not found") from exc
            log.error("wecom_scrm_bind_http_error", status=exc.response.status_code)
            raise HTTPException(status_code=502, detail="member service error") from exc
        except httpx.ConnectError as exc:
            log.error("wecom_scrm_bind_connect_error", error=str(exc))
            raise HTTPException(status_code=503, detail="member service unavailable") from exc
        except httpx.TimeoutException as exc:
            log.error("wecom_scrm_bind_timeout", error=str(exc))
            raise HTTPException(status_code=504, detail="member service timeout") from exc

    log.info("wecom_scrm_manual_bind_ok")
    return resp.json()


@router.post("/qrcode")
async def create_contact_qrcode(
    req: QrcodeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """生成门店企微活码（导购专属二维码）

    state 传入 store_id，企微回调 customer_add 事件中可通过 State 字段识别来源。
    """
    log = logger.bind(store_id=req.store_id, user_id=req.user_id)
    log.info("wecom_scrm_create_qrcode")

    try:
        result = await wecom_contact_sdk.add_contact_way(
            state=req.store_id,
            remark=req.remark,
        )
    except WecomAPIError as exc:
        log.error("wecom_scrm_qrcode_api_error", errcode=exc.errcode, errmsg=exc.errmsg)
        raise HTTPException(
            status_code=502,
            detail=f"wecom api error {exc.errcode}: {exc.errmsg}",
        ) from exc
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.error("wecom_scrm_qrcode_network_error", error=str(exc))
        raise HTTPException(status_code=503, detail="wecom api unavailable") from exc

    log.info("wecom_scrm_qrcode_ok", config_id=result.get("config_id"))
    return {"ok": True, "data": result}


@router.get("/staff/{user_id}")
async def get_staff_contacts(
    user_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取某导购（企微 userid）的所有客户外部联系人列表

    先从企微获取 external_userid 列表，再批量查询 tx-member 获得会员信息。
    """
    log = logger.bind(user_id=user_id)
    log.info("wecom_scrm_get_staff_contacts")

    # 1. 从企微获取该导购的所有客户 ID 列表
    try:
        external_ids = await wecom_contact_sdk.batch_get_external_contact(user_id)
    except WecomAPIError as exc:
        log.error(
            "wecom_scrm_staff_contacts_api_error",
            errcode=exc.errcode,
            errmsg=exc.errmsg,
        )
        raise HTTPException(
            status_code=502,
            detail=f"wecom api error {exc.errcode}: {exc.errmsg}",
        ) from exc
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.error("wecom_scrm_staff_contacts_network_error", error=str(exc))
        raise HTTPException(status_code=503, detail="wecom api unavailable") from exc

    if not external_ids:
        log.info("wecom_scrm_staff_contacts_empty", user_id=user_id)
        return {"ok": True, "data": {"items": [], "total": 0}}

    # 2. 批量查询 tx-member 获取会员绑定信息
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                f"{_MEMBER_SERVICE_URL}/api/v1/member/customers/wecom/batch_by_external_ids",
                json={"external_userids": external_ids},
                headers={"X-Tenant-ID": x_tenant_id},
            )
            resp.raise_for_status()
            member_data = resp.json()
        except httpx.HTTPStatusError as exc:
            log.error("wecom_scrm_staff_member_http_error", status=exc.response.status_code)
            # 降级：返回仅含企微 ID 的列表
            member_data = {
                "ok": True,
                "data": {
                    "items": [{"wecom_external_userid": eid} for eid in external_ids],
                    "total": len(external_ids),
                },
            }
        except httpx.ConnectError as exc:
            log.error("wecom_scrm_staff_member_connect_error", error=str(exc))
            raise HTTPException(status_code=503, detail="member service unavailable") from exc
        except httpx.TimeoutException as exc:
            log.error("wecom_scrm_staff_member_timeout", error=str(exc))
            raise HTTPException(status_code=504, detail="member service timeout") from exc

    log.info(
        "wecom_scrm_get_staff_contacts_ok",
        user_id=user_id,
        total=len(external_ids),
    )
    return member_data
