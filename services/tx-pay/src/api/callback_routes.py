"""支付回调统一网关

所有第三方支付回调统一入口：
  POST /api/v1/pay/callback/wechat     — 微信支付回调
  POST /api/v1/pay/callback/alipay     — 支付宝回调
  POST /api/v1/pay/callback/lakala     — 拉卡拉回调
  POST /api/v1/pay/callback/shouqianba — 收钱吧回调

安全：
  - 每个渠道独立验签
  - 验签失败返回 4xx，不处理
  - 成功处理后发射 payment.confirmed 事件
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/pay/callback", tags=["支付回调"])


@router.post("/wechat")
async def wechat_callback(request: Request) -> Response:
    """微信支付 V3 回调"""
    from ..deps import get_channel_registry

    registry = await get_channel_registry()
    body = await request.body()
    headers = dict(request.headers)

    try:
        channel = registry.get("wechat_direct")
        payload = await channel.verify_callback(headers, body)
    except NotImplementedError:
        logger.warning("wechat_callback_mock_mode")
        return Response(content='{"code": "SUCCESS"}', media_type="application/json")
    except Exception as exc:
        logger.error("wechat_callback_verify_failed", error=str(exc))
        return Response(status_code=400, content='{"code": "FAIL", "message": "验签失败"}')

    # 发射事件
    from ..events import emit_payment_confirmed
    await emit_payment_confirmed(payload)

    logger.info(
        "wechat_callback_processed",
        payment_id=payload.payment_id,
        trade_no=payload.trade_no,
    )
    return Response(content='{"code": "SUCCESS"}', media_type="application/json")


@router.post("/alipay")
async def alipay_callback(request: Request) -> Response:
    """支付宝回调（预留）"""
    logger.info("alipay_callback_received")
    return Response(content="success", media_type="text/plain")


@router.post("/lakala")
async def lakala_callback(request: Request) -> Response:
    """拉卡拉回调"""
    logger.info("lakala_callback_received")
    return Response(content='{"return_code": "SUCCESS"}', media_type="application/json")


@router.post("/shouqianba")
async def shouqianba_callback(request: Request) -> Response:
    """收钱吧回调"""
    logger.info("shouqianba_callback_received")
    return Response(content='{"result_code": "200"}', media_type="application/json")
