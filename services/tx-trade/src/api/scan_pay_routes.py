"""扫码付款码收款 API — 顾客出示微信/支付宝/银联付款码，收银员扫码收款

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/payments", tags=["scan-pay"])

# ─── 内存存储（生产环境应写入 DB） ───

_payments: dict[str, dict] = {}


# ─── 工具 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _detect_channel(auth_code: str) -> Literal["wechat", "alipay", "unionpay"]:
    """根据付款码前缀识别支付渠道。

    微信：10/11/12/13/14/15 开头
    支付宝：25/26/27/28/29/30 开头
    其他：银联云闪付
    """
    if len(auth_code) < 2:
        return "unionpay"
    prefix2 = auth_code[:2]
    wechat_prefixes = {"10", "11", "12", "13", "14", "15"}
    alipay_prefixes = {"25", "26", "27", "28", "29", "30"}
    if prefix2 in wechat_prefixes:
        return "wechat"
    if prefix2 in alipay_prefixes:
        return "alipay"
    return "unionpay"


# ─── 请求/响应模型 ───


class ScanPayRequest(BaseModel):
    order_id: str = Field(..., description="订单ID")
    auth_code: str = Field(..., min_length=6, description="付款码原始内容（通常18位数字）")
    amount_fen: int = Field(..., gt=0, description="收款金额（分）")
    operator_id: str = Field(default="", description="操作员ID")
    store_id: str = Field(default="", description="门店ID")


class ScanPayResponse(BaseModel):
    payment_id: str
    status: Literal["success", "pending", "failed"]
    pay_channel: Literal["wechat", "alipay", "unionpay"]
    transaction_id: str
    amount_fen: int
    order_id: str
    created_at: str
    channel_label: str  # "微信支付" / "支付宝" / "银联云闪付"


# ─── 路由 ───


@router.post("/scan-pay")
async def scan_pay(body: ScanPayRequest, request: Request):
    """付款码聚合收款 — 自动识别微信/支付宝/银联，mock成功响应。

    生产接入：需在商户后台配置 mchid、apikey、appid 后替换 mock 逻辑。
    """
    _get_tenant_id(request)

    channel = _detect_channel(body.auth_code)
    channel_label_map: dict[str, str] = {
        "wechat": "微信支付",
        "alipay": "支付宝",
        "unionpay": "银联云闪付",
    }

    payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    transaction_id = f"txn_{uuid.uuid4().hex[:20]}"
    now = datetime.now(timezone.utc).isoformat()

    payment_record = {
        "payment_id": payment_id,
        "order_id": body.order_id,
        "auth_code": body.auth_code,
        "amount_fen": body.amount_fen,
        "operator_id": body.operator_id,
        "store_id": body.store_id,
        "pay_channel": channel,
        "channel_label": channel_label_map[channel],
        "status": "pending",
        "transaction_id": transaction_id,
        "created_at": now,
        "error_message": None,
    }
    _payments[payment_id] = payment_record

    # mock：模拟支付网关延迟 1.5 秒
    await asyncio.sleep(1.5)

    # mock：直接成功（生产环境替换为真实支付网关调用）
    payment_record["status"] = "success"

    return _ok(
        ScanPayResponse(
            payment_id=payment_id,
            status="success",
            pay_channel=channel,
            transaction_id=transaction_id,
            amount_fen=body.amount_fen,
            order_id=body.order_id,
            created_at=now,
            channel_label=channel_label_map[channel],
        ).model_dump()
    )


@router.get("/scan-pay/{payment_id}/status")
async def get_payment_status(payment_id: str, request: Request):
    """轮询支付状态 — 前端在"支付中"状态每2秒调用一次。"""
    _get_tenant_id(request)

    record = _payments.get(payment_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")

    channel_label_map: dict[str, str] = {
        "wechat": "微信支付",
        "alipay": "支付宝",
        "unionpay": "银联云闪付",
    }

    return _ok(
        {
            "payment_id": payment_id,
            "status": record["status"],
            "pay_channel": record["pay_channel"],
            "channel_label": channel_label_map.get(record["pay_channel"], record["pay_channel"]),
            "transaction_id": record["transaction_id"],
            "amount_fen": record["amount_fen"],
            "order_id": record["order_id"],
            "error_message": record.get("error_message"),
        }
    )


@router.post("/scan-pay/{payment_id}/cancel")
async def cancel_payment(payment_id: str, request: Request):
    """取消支付 — 超时或顾客操作失误时由前端调用。"""
    _get_tenant_id(request)

    record = _payments.get(payment_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")

    if record["status"] == "success":
        raise HTTPException(status_code=409, detail="支付已成功，不可取消")

    record["status"] = "failed"
    record["error_message"] = "已取消"

    return _ok({"payment_id": payment_id, "status": "failed", "message": "已取消"})
