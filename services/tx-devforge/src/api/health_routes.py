"""tx-devforge 健康/就绪检查路由。"""

from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..db import check_db_connectivity

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    """liveness 探针：进程存活即 200。"""

    settings = get_settings()
    return {
        "ok": True,
        "data": {
            "service": settings.service_name,
            "version": settings.service_version,
        },
        "error": {},
    }


@router.get("/readiness")
async def readiness() -> dict[str, object]:
    """readiness 探针：DB 可连通才视为就绪。"""

    settings = get_settings()
    db_ok = await check_db_connectivity()
    return {
        "ok": db_ok,
        "data": {
            "service": settings.service_name,
            "version": settings.service_version,
            "db": "ok" if db_ok else "unreachable",
        },
        "error": {} if db_ok else {"code": "db_unreachable", "message": "database not reachable"},
    }
