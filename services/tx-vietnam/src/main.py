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
