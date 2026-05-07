"""tx-pay — 屯象OS 支付中枢微服务

端口: 8016（统一规划：8015=tx-expense / 8016=tx-pay / 8017=tx-devforge）
职责: 统一收款/退款/对账/渠道管理/Agent支付协议

启动: uvicorn services.tx-pay.src.main:app --port 8016
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """初始化渠道注册表和路由引擎"""
    from .channels.alipay import AlipayChannel
    from .channels.cash import CashChannel
    from .channels.credit_account import CreditAccountChannel
    from .channels.lakala import LakalaChannel
    from .channels.registry import ChannelRegistry
    from .channels.shouqianba import ShouqianbaChannel
    from .channels.stored_value import StoredValueChannel
    from .channels.wechat import WechatPayChannel
    from .deps import init_globals
    from .routing.engine import PaymentRoutingEngine

    # 1. 注册所有渠道
    registry = ChannelRegistry()

    # 微信直连
    notify_base = os.getenv("PAY_NOTIFY_BASE_URL", "https://api.tunxiang.com")
    registry.register(WechatPayChannel(notify_url=f"{notify_base}/api/v1/pay/callback/wechat"))

    # 支付宝（Mock 骨架）
    registry.register(AlipayChannel())

    # 聚合支付（拉卡拉 + 收钱吧）
    registry.register(LakalaChannel())
    registry.register(ShouqianbaChannel())

    # 内部渠道
    registry.register(CashChannel())
    registry.register(StoredValueChannel())
    registry.register(CreditAccountChannel())

    # 2. 初始化路由引擎
    routing = PaymentRoutingEngine(registry)

    # 3. 注入全局依赖
    init_globals(registry, routing)

    logger.info(
        "tx_pay_started",
        channels=registry.channel_names,
        port=8016,
    )

    yield

    logger.info("tx_pay_shutdown")


app = FastAPI(
    title="TunxiangOS Payment Nexus",
    version="0.1.0",
    description="支付中枢 — 统一收款/退款/对账/渠道管理/Agent支付协议",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 审计 S-02 闭环：校验 gateway 注入的 X-Internal-JWT，把受信 claims 写入
# request.state；env TX_INTERNAL_JWT_SECRET 未配时 skip 不破坏现状。
# 必须在 CORSMiddleware 之后 add（FastAPI 后 add 的在内层；CORS preflight
# OPTIONS 走外层 CORS 直接返 200，不经 JWT 校验）。
# 详见 docs/security/internal-jwt-rollout.md
from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware

app.add_middleware(InternalJwtMiddleware)
# 路由注册
from .api.admin_routes import router as admin_router
from .api.agent_routes import router as agent_router
from .api.callback_routes import router as callback_router
from .api.payment_routes import router as payment_router

app.include_router(payment_router)
app.include_router(callback_router)
app.include_router(admin_router)
app.include_router(agent_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-pay", "version": "0.1.0"}}
