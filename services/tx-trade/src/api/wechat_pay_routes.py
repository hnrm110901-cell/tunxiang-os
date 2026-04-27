"""微信支付路由 — 预支付 / 回调 / 查询 / 退款

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有业务接口需 X-Tenant-ID header，回调接口除外（微信服务器调用）。
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from shared.integrations.wechat_pay import get_wechat_pay_service

from ..services.wechat_pay_notify_service import apply_wechat_pay_notify_success

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/trade/payment/wechat",
    tags=["wechat-pay"],
)


# ─── 工具 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(message: str, code: str = "PAYMENT_ERROR") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


# ─── 请求模型 ───


class PrepayRequest(BaseModel):
    """创建预支付请求"""

    order_id: str = Field(..., description="商户订单号")
    total_fen: int = Field(..., gt=0, description="支付金额（分）")
    description: str = Field(default="屯象OS订单", description="商品描述")
    openid: str = Field(..., description="用户 OpenID")
    notify_url: Optional[str] = Field(
        default=None,
        description="支付结果回调地址，默认使用系统配置",
    )


class RefundRequest(BaseModel):
    """退款请求"""

    order_id: str = Field(..., description="原商户订单号")
    refund_no: Optional[str] = Field(default=None, description="退款单号，不传则自动生成")
    total_fen: int = Field(..., gt=0, description="原订单金额（分）")
    refund_fen: int = Field(..., gt=0, description="退款金额（分）")
    reason: str = Field(default="", description="退款原因")


# ─── 路由 ───


@router.post("/prepay")
async def create_prepay(req: PrepayRequest, request: Request):
    """创建微信支付预支付订单

    返回小程序调用 wx.requestPayment 所需的全部参数。
    """
    tenant_id = _get_tenant_id(request)
    logger.info(
        "create_prepay: tenant=%s order=%s amount=%d openid=%s",
        tenant_id,
        req.order_id,
        req.total_fen,
        req.openid[:8] + "***",
    )

    svc = get_wechat_pay_service()

    # 默认回调地址（生产环境应从配置读取）
    notify_url = req.notify_url or "https://api.tunxiang.com/api/v1/trade/payment/wechat/callback"

    try:
        result = await svc.create_prepay(
            out_trade_no=req.order_id,
            total_fen=req.total_fen,
            description=req.description,
            openid=req.openid,
            notify_url=notify_url,
        )
        return _ok(result)
    except ValueError as exc:
        logger.error("create_prepay failed: %s", exc)
        return _err(str(exc))


@router.post("/callback")
async def wechat_pay_callback(request: Request):
    """微信支付结果回调（微信服务器 → 我们）

    注意：此接口不需要 X-Tenant-ID，由微信服务器主动调用。
    返回格式遵循微信要求：成功返回 {"code": "SUCCESS", "message": "成功"}
    """
    body = await request.body()
    headers = dict(request.headers)

    logger.info("wechat_pay_callback: received notification")

    svc = get_wechat_pay_service()

    try:
        result = await svc.verify_callback(headers, body)
        trade_state = result.get("trade_state", "")
        out_trade_no = result.get("out_trade_no", "")
        transaction_id = result.get("transaction_id", "")

        logger.info(
            "wechat_pay_callback: order=%s state=%s txn=%s",
            out_trade_no,
            trade_state,
            transaction_id,
        )

        if trade_state == "SUCCESS":
            try:
                notify_result = await apply_wechat_pay_notify_success(result)
                logger.info(
                    "wechat_pay_callback: notify_result=%s",
                    notify_result,
                )
                if not notify_result.get("ok", True):
                    return {
                        "code": "FAIL",
                        "message": notify_result.get("message", "notify_failed"),
                    }
            except SQLAlchemyError as exc:
                logger.error(
                    "wechat_pay_callback: 落库失败 order=%s err=%s",
                    out_trade_no,
                    exc,
                    exc_info=True,
                )
                return {"code": "FAIL", "message": "database_error"}
        else:
            logger.warning(
                "wechat_pay_callback: 订单 %s 状态为 %s",
                out_trade_no,
                trade_state,
            )

        # 微信要求的成功响应格式
        return {"code": "SUCCESS", "message": "成功"}

    except ValueError as exc:
        logger.error("wechat_pay_callback: 签名验证失败: %s", exc)
        return {"code": "FAIL", "message": str(exc)}


@router.get("/query/{order_no}")
async def query_order(order_no: str, request: Request):
    """主动查询订单支付状态"""
    tenant_id = _get_tenant_id(request)
    logger.info("query_order: tenant=%s order=%s", tenant_id, order_no)

    svc = get_wechat_pay_service()

    try:
        result = await svc.query_order(order_no)
        return _ok(result)
    except ValueError as exc:
        logger.error("query_order failed: %s", exc)
        return _err(str(exc))


@router.post("/refund")
async def apply_refund(req: RefundRequest, request: Request):
    """申请微信支付退款"""
    tenant_id = _get_tenant_id(request)
    refund_no = req.refund_no or f"RF_{uuid.uuid4().hex[:16]}"

    if req.refund_fen > req.total_fen:
        raise HTTPException(status_code=400, detail="退款金额不能超过订单金额")

    logger.info(
        "apply_refund: tenant=%s order=%s refund_no=%s amount=%d/%d reason=%s",
        tenant_id,
        req.order_id,
        refund_no,
        req.refund_fen,
        req.total_fen,
        req.reason,
    )

    svc = get_wechat_pay_service()

    try:
        result = await svc.refund(
            out_trade_no=req.order_id,
            refund_no=refund_no,
            total_fen=req.total_fen,
            refund_fen=req.refund_fen,
            reason=req.reason,
        )
        return _ok(result)
    except ValueError as exc:
        logger.error("apply_refund failed: %s", exc)
        return _err(str(exc))
