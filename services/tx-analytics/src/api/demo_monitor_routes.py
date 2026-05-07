"""演示环境监控面板 API — Gap C-04

提供三商户（czyz/zqx/sgc）演示环境的健康度检查和服务状态。

端点：
  GET /api/v1/analytics/demo-monitor/health   — 三商户健康度检查
  GET /api/v1/analytics/demo-monitor/services  — 所有微服务端口列表
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["demo-monitor"])

_DEMO_MERCHANTS: dict[str, str] = {
    code: str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{code}-demo-tenant")) for code in ("czyz", "zqx", "sgc")
}

_MERCHANT_NAMES = {
    "czyz": "尝在一起",
    "zqx": "最黔线",
    "sgc": "尚宫厨",
}

_SERVICES: list[dict] = [
    {"name": "gateway", "port": 8000, "status": "unknown", "note": "API 网关"},
    {"name": "tx-trade", "port": 8001, "status": "unknown", "note": "交易履约"},
    {"name": "tx-menu", "port": 8002, "status": "unknown", "note": "菜品菜单"},
    {"name": "tx-member", "port": 8003, "status": "unknown", "note": "会员 CDP"},
    {"name": "tx-growth", "port": 8004, "status": "unknown", "note": "增长营销"},
    {"name": "tx-ops", "port": 8005, "status": "unknown", "note": "运营流程"},
    {"name": "tx-supply", "port": 8006, "status": "unknown", "note": "供应链"},
    {"name": "tx-finance", "port": 8007, "status": "unknown", "note": "财务结算"},
    {"name": "tx-agent", "port": 8008, "status": "unknown", "note": "Agent OS"},
    {"name": "tx-analytics", "port": 8009, "status": "unknown", "note": "经营分析（当前服务）"},
    {"name": "tx-brain", "port": 8010, "status": "unknown", "note": "AI 智能决策"},
    {"name": "tx-intel", "port": 8011, "status": "unknown", "note": "商业智能"},
    {"name": "tx-org", "port": 8012, "status": "unknown", "note": "组织人事"},
    {"name": "tx-civic", "port": 8014, "status": "unknown", "note": "城市监管"},
]


async def _check_merchant_health(merchant_code: str, tenant_id: str) -> dict:
    """对单个商户执行数据库健康检查和数据计数。"""
    checks: list[dict] = []
    overall_ok = True

    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # stores
        try:
            row = await session.execute(
                text("SELECT COUNT(*) AS cnt FROM stores WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            cnt = row.scalar() or 0
            checks.append({"name": "stores", "count": cnt, "ok": cnt >= 1})
        except SQLAlchemyError as exc:
            logger.warning("demo_monitor_query_failed", merchant=merchant_code, table="stores", error=str(exc))
            checks.append({"name": "stores", "count": 0, "ok": False})
            overall_ok = False

        # dishes
        try:
            row = await session.execute(
                text("SELECT COUNT(*) AS cnt FROM dishes WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            cnt = row.scalar() or 0
            checks.append({"name": "dishes", "count": cnt, "ok": cnt >= 10})
        except SQLAlchemyError as exc:
            logger.warning("demo_monitor_query_failed", merchant=merchant_code, table="dishes", error=str(exc))
            checks.append({"name": "dishes", "count": 0, "ok": False})
            overall_ok = False

        # members
        try:
            row = await session.execute(
                text("SELECT COUNT(*) AS cnt FROM members WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            cnt = row.scalar() or 0
            checks.append({"name": "members", "count": cnt, "ok": cnt >= 5})
        except SQLAlchemyError as exc:
            logger.warning("demo_monitor_query_failed", merchant=merchant_code, table="members", error=str(exc))
            checks.append({"name": "members", "count": 0, "ok": False})
            overall_ok = False

        # orders (90 days)
        try:
            row = await session.execute(
                text("""
                    SELECT COUNT(*) AS cnt FROM orders
                    WHERE tenant_id = :tid
                      AND is_deleted = FALSE
                      AND created_at >= NOW() - (:days * INTERVAL '1 day')
                """),
                {"tid": tenant_id, "days": 90},
            )
            cnt = row.scalar() or 0
            checks.append({"name": "orders_90d", "count": cnt, "ok": cnt >= 20})
        except SQLAlchemyError as exc:
            logger.warning("demo_monitor_query_failed", merchant=merchant_code, table="orders", error=str(exc))
            checks.append({"name": "orders_90d", "count": 0, "ok": False})
            overall_ok = False

        # tables
        try:
            row = await session.execute(
                text("SELECT COUNT(*) AS cnt FROM tables WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            cnt = row.scalar() or 0
            checks.append({"name": "tables", "count": cnt, "ok": cnt >= 5})
        except SQLAlchemyError as exc:
            logger.warning("demo_monitor_query_failed", merchant=merchant_code, table="tables", error=str(exc))
            checks.append({"name": "tables", "count": 0, "ok": False})
            overall_ok = False

    # 简化数据质量评分：5项检查，各20分（仅已知 check 名称参与评分；未知 check 不得分，避免静默"白送"）
    _MIN_COUNTS = {"stores": 1, "dishes": 10, "members": 5, "orders_90d": 20, "tables": 5}
    quality_score = sum(20 for c in checks if c["name"] in _MIN_COUNTS and c["count"] >= _MIN_COUNTS[c["name"]])

    status = "error" if all(not c["ok"] for c in checks) else ("degraded" if not overall_ok else "healthy")

    return {
        "merchant_code": merchant_code,
        "merchant_name": _MERCHANT_NAMES.get(merchant_code, merchant_code),
        "service": "tx-analytics",
        "status": status,
        "db_connected": overall_ok,
        "data_quality_score": quality_score,
        "grade": _grade(quality_score),
        "last_seed_at": None,
        "checks": checks,
    }


def _grade(score: float) -> str:
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 85:
        return "B+"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C+"
    if score >= 60:
        return "C"
    return "D"


@router.get("/demo-monitor/health", summary="演示环境三商户健康度检查")
async def get_demo_monitor_health() -> dict:
    """返回三个演示商户（czyz/zqx/sgc）的数据库健康度和数据概览。"""
    results: list[dict] = []
    for code, tid in _DEMO_MERCHANTS.items():
        try:
            result = await _check_merchant_health(code, tid)
        except SQLAlchemyError as exc:
            logger.error("demo_monitor_health_failed", merchant_code=code, error=str(exc))
            result = {
                "merchant_code": code,
                "merchant_name": _MERCHANT_NAMES.get(code, code),
                "service": "tx-analytics",
                "status": "error",
                "db_connected": False,
                "data_quality_score": 0,
                "grade": "D",
                "last_seed_at": None,
                "checks": [],
            }
        results.append(result)

    return {"ok": True, "data": results}


@router.get("/demo-monitor/services", summary="演示环境微服务列表")
async def get_demo_monitor_services() -> dict:
    """返回全部微服务端口列表（用于监控面板展示）。"""
    return {
        "ok": True,
        "data": {
            "services": _SERVICES,
            "analytics_quality_url": "/api/v1/analytics/data-quality",
            "demo_monitor_health_url": "/api/v1/analytics/demo-monitor/health",
        },
    }
