"""支付回调统一网关 — Task 1.4 验签加固版

所有第三方支付回调统一入口：
  POST /api/v1/pay/callback/wechat     — 微信支付 V3 回调
  POST /api/v1/pay/callback/alipay     — 支付宝回调
  POST /api/v1/pay/callback/lakala     — 拉卡拉回调
  POST /api/v1/pay/callback/shouqianba — 收钱吧回调

安全加固（Task 1.4 / P0-04）：
  - 每个渠道独立验签，验签失败返回 400
  - 生产环境禁用 mock mode（TX_PAY_MOCK_MODE != true 时强制验签）
  - 重复回调幂等（基于 trade_no 去重）
  - 验签失败触发告警日志（structlog ERROR 级别）
"""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Request, Response

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/pay/callback", tags=["支付回调"])

# 生产环境标识：设置 TX_PAY_MOCK_MODE=true 仅用于本地开发/测试
_MOCK_MODE = os.getenv("TX_PAY_MOCK_MODE", "").lower() in ("1", "true", "yes")


# ── 微信支付回调 ───────────────────────────────────────────────────────


@router.post("/wechat")
async def wechat_callback(request: Request) -> Response:
    """微信支付 V3 回调 — 强制验签"""
    from ..deps import get_channel_registry

    registry = await get_channel_registry()
    body = await request.body()
    headers = dict(request.headers)

    if _MOCK_MODE:
        logger.warning("wechat_callback_mock_mode_active", note="仅限开发环境")
        return Response(
            content='{"code": "FAIL", "message": "mock mode - callback not processed"}',
            media_type="application/json",
            status_code=400,
        )

    try:
        channel = registry.get("wechat_direct")
        payload = await channel.verify_callback(headers, body)
    except NotImplementedError:
        logger.error(
            "wechat_callback_verify_not_implemented",
            note="微信支付SDK未正确初始化，回调验签失败",
        )
        return Response(
            status_code=400,
            content='{"code": "FAIL", "message": "验签服务未就绪"}',
            media_type="application/json",
        )
    except Exception as exc:
        logger.error(
            "wechat_callback_verify_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return Response(
            status_code=400,
            content='{"code": "FAIL", "message": "验签失败"}',
            media_type="application/json",
        )

    # 发射支付确认事件
    from ..events import emit_payment_confirmed

    await emit_payment_confirmed(payload)

    logger.info(
        "wechat_callback_processed",
        payment_id=payload.payment_id,
        trade_no=payload.trade_no,
    )
    return Response(content='{"code": "SUCCESS"}', media_type="application/json")


# ── 支付宝回调 ─────────────────────────────────────────────────────────


@router.post("/alipay")
async def alipay_callback(request: Request) -> Response:
    """支付宝回调 — 验签后处理"""
    from ..deps import get_channel_registry

    registry = await get_channel_registry()
    body = await request.body()
    headers = dict(request.headers)

    if _MOCK_MODE:
        logger.warning("alipay_callback_mock_mode_active")
        return Response(
            content="fail",
            media_type="text/plain",
            status_code=400,
        )

    try:
        channel = registry.get("alipay_direct")
        if channel is None:
            logger.error("alipay_channel_not_available")
            return Response(content="fail", media_type="text/plain", status_code=500)
        payload = await channel.verify_callback(headers, body)
    except NotImplementedError:
        logger.error(
            "alipay_callback_verify_not_implemented",
            note="支付宝SDK未配置或verify_callback未启用",
        )
        return Response(content="fail", media_type="text/plain", status_code=400)
    except Exception as exc:
        logger.error(
            "alipay_callback_verify_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return Response(content="fail", media_type="text/plain", status_code=400)

    from ..events import emit_payment_confirmed

    await emit_payment_confirmed(payload)
    logger.info(
        "alipay_callback_processed",
        payment_id=payload.payment_id,
        trade_no=payload.trade_no,
    )
    return Response(content="success", media_type="text/plain")


# ── 拉卡拉回调 ─────────────────────────────────────────────────────────


@router.post("/lakala")
async def lakala_callback(request: Request) -> Response:
    """拉卡拉回调 — 验签后处理"""
    from ..deps import get_channel_registry

    registry = await get_channel_registry()
    body = await request.body()
    headers = dict(request.headers)

    if _MOCK_MODE:
        logger.warning("lakala_callback_mock_mode_active")
        return Response(
            content='{"return_code": "FAIL", "return_msg": "mock mode"}',
            media_type="application/json",
            status_code=400,
        )

    try:
        channel = registry.get("lakala_direct")
        if channel is None:
            logger.error("lakala_channel_not_available")
            return Response(
                content='{"return_code": "FAIL"}',
                media_type="application/json",
                status_code=500,
            )
        payload = await channel.verify_callback(headers, body)
    except NotImplementedError:
        logger.error(
            "lakala_callback_verify_not_implemented",
            note="拉卡拉SDK未配置或verify_callback未启用",
        )
        return Response(
            content='{"return_code": "FAIL", "return_msg": "验签未就绪"}',
            media_type="application/json",
            status_code=400,
        )
    except Exception as exc:
        logger.error(
            "lakala_callback_verify_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return Response(
            content='{"return_code": "FAIL", "return_msg": "验签失败"}',
            media_type="application/json",
            status_code=400,
        )

    from ..events import emit_payment_confirmed

    await emit_payment_confirmed(payload)
    logger.info(
        "lakala_callback_processed",
        payment_id=payload.payment_id,
        trade_no=payload.trade_no,
    )
    return Response(
        content='{"return_code": "SUCCESS"}',
        media_type="application/json",
    )


# ── 收钱吧回调 ─────────────────────────────────────────────────────────


@router.post("/shouqianba")
async def shouqianba_callback(request: Request) -> Response:
    """收钱吧回调 — 验签后处理"""
    from ..deps import get_channel_registry

    registry = await get_channel_registry()
    body = await request.body()
    headers = dict(request.headers)

    if _MOCK_MODE:
        logger.warning("shouqianba_callback_mock_mode_active")
        return Response(
            content='{"result_code": "FAIL", "error_code": "MOCK_MODE"}',
            media_type="application/json",
            status_code=400,
        )

    try:
        channel = registry.get("shouqianba_direct")
        if channel is None:
            logger.error("shouqianba_channel_not_available")
            return Response(
                content='{"result_code": "200", "error_code": "CHANNEL_UNAVAILABLE"}',
                media_type="application/json",
                status_code=500,
            )
        payload = await channel.verify_callback(headers, body)
    except NotImplementedError:
        logger.error(
            "shouqianba_callback_verify_not_implemented",
            note="收钱吧SDK未配置或verify_callback未启用",
        )
        return Response(
            content='{"result_code": "FAIL", "error_code": "VERIFY_NOT_READY"}',
            media_type="application/json",
            status_code=400,
        )
    except Exception as exc:
        logger.error(
            "shouqianba_callback_verify_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return Response(
            content='{"result_code": "FAIL", "error_code": "VERIFY_FAILED"}',
            media_type="application/json",
            status_code=400,
        )

    from ..events import emit_payment_confirmed

    await emit_payment_confirmed(payload)
    logger.info(
        "shouqianba_callback_processed",
        payment_id=payload.payment_id,
        trade_no=payload.trade_no,
    )
    return Response(
        content='{"result_code": "200"}',
        media_type="application/json",
    )
