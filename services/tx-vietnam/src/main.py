"""
tx-vietnam — Vietnam Market Service

Vietnam-specific tax (VAT) and compliance service for Tunxiang OS.
Handles VAT calculation, e-invoice references, and tax ID validation.

All monetary amounts are in VND (integer). VND has no decimal subunit.
VAT is price-inclusive per Vietnamese practice.

Run:
    uvicorn tx_vietnam.src.main:app --reload --port 8200
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tx_vietnam.src.api.vat_routes import router as vat_router

app = FastAPI(
    title="Tunxiang OS — Vietnam Market Service",
    version="0.1.0",
    description="Vietnam VAT, e-invoice, and market-specific compliance",
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
# Register routers
app.include_router(vat_router)


@app.get("/health")
async def health_check() -> dict:
    """Service health check."""
    return {
        "ok": True,
        "service": "tx-vietnam",
        "version": "0.1.0",
        "market": "vietnam",
    }
