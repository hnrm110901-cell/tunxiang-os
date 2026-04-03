"""
库存智能补货聚合接口

GET  /api/v1/inventory/dashboard      — 库存总览（缺货/临期/正常数量）
POST /api/v1/inventory/restock-plan   — 生成 AI 补货计划（调用 inventory_alert agent）
GET  /api/v1/inventory/restock-plan   — 获取最新补货计划（从 DB 缓存）
"""
import structlog
from fastapi import APIRouter, Depends, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/dashboard")
async def get_inventory_dashboard(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
):
    """库存总览：缺货/临界/低库存/正常/即将临期/已过期 数量 + 低库存食材列表（前50条）"""
    try:
        summary_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'out_of_stock')                          AS out_of_stock,
                    COUNT(*) FILTER (WHERE status = 'critical')                              AS critical,
                    COUNT(*) FILTER (WHERE status = 'low')                                   AS low_stock,
                    COUNT(*) FILTER (WHERE status = 'normal')                                AS normal,
                    COUNT(*) FILTER (
                        WHERE expiry_date <= CURRENT_DATE + INTERVAL '3 days'
                          AND expiry_date >= CURRENT_DATE
                    )                                                                        AS expiring_soon,
                    COUNT(*) FILTER (WHERE expiry_date < CURRENT_DATE)                       AS expired
                FROM ingredient_stocks
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND is_deleted = FALSE
            """),
            {"tenant_id": x_tenant_id, "store_id": store_id},
        )
        row = summary_result.fetchone()

        low_result = await db.execute(
            text("""
                SELECT
                    i.id::text                              AS id,
                    i.name                                  AS name,
                    s.current_qty                           AS current_qty,
                    s.unit                                  AS unit,
                    s.safety_stock_qty                      AS safety_stock_qty,
                    s.status                                AS status,
                    s.expiry_date                           AS expiry_date,
                    COALESCE(sp.name, '未设置')             AS preferred_supplier,
                    COALESCE(sp.last_price_fen, 0)          AS last_price_fen
                FROM ingredient_stocks s
                JOIN ingredients       i  ON i.id  = s.ingredient_id
                LEFT JOIN suppliers    sp ON sp.id = i.preferred_supplier_id
                WHERE s.tenant_id  = :tenant_id
                  AND s.store_id   = :store_id
                  AND s.is_deleted = FALSE
                  AND s.status IN ('out_of_stock', 'critical', 'low')
                ORDER BY
                    CASE s.status
                        WHEN 'out_of_stock' THEN 1
                        WHEN 'critical'     THEN 2
                        WHEN 'low'          THEN 3
                    END,
                    i.name
                LIMIT 50
            """),
            {"tenant_id": x_tenant_id, "store_id": store_id},
        )
        low_items = low_result.fetchall()

        return {
            "ok": True,
            "data": {
                "summary": {
                    "out_of_stock":  row.out_of_stock  if row else 0,
                    "critical":      row.critical      if row else 0,
                    "low_stock":     row.low_stock     if row else 0,
                    "normal":        row.normal        if row else 0,
                    "expiring_soon": row.expiring_soon if row else 0,
                    "expired":       row.expired       if row else 0,
                },
                "low_items": [
                    {
                        "id":                 r.id,
                        "name":               r.name,
                        "current_qty":        float(r.current_qty),
                        "unit":               r.unit,
                        "safety_stock_qty":   float(r.safety_stock_qty) if r.safety_stock_qty else 0.0,
                        "status":             r.status,
                        "expiry_date":        r.expiry_date.isoformat() if r.expiry_date else None,
                        "preferred_supplier": r.preferred_supplier,
                        "last_price_fen":     int(r.last_price_fen),
                    }
                    for r in low_items
                ],
            },
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "inventory_dashboard_failed",
            store_id=store_id,
            tenant_id=x_tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return {"ok": True, "data": {"summary": {}, "low_items": []}}


@router.post("/restock-plan")
async def generate_restock_plan(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
):
    """
    触发 AI 补货计划生成。

    内部通过 MasterAgent → InventoryAlertAgent 执行 generate_restock_alerts + assess_shortage_severity。
    结果持久化到 agent_restock_plans 表（如果存在），同时直接返回给调用方。
    """
    from ..agents.master import MasterAgent
    from ..agents.skills import ALL_SKILL_AGENTS
    from ..services.model_router import ModelRouter

    try:
        model_router = ModelRouter()
    except ValueError:
        model_router = None

    master = MasterAgent(tenant_id=x_tenant_id)
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id=x_tenant_id, db=db, model_router=model_router))

    try:
        alert_result = await master.dispatch(
            "inventory_alert",
            "generate_restock_alerts",
            {"store_id": store_id},
        )
        severity_result = await master.dispatch(
            "inventory_alert",
            "assess_shortage_severity",
            {"store_id": store_id},
        )

        return {
            "ok": True,
            "data": {
                "restock_alerts":  alert_result.data    if alert_result.success    else [],
                "severity":        severity_result.data if severity_result.success else {},
                "ai_reasoning":    alert_result.reasoning,
                "confidence":      alert_result.confidence,
                "constraints_ok":  alert_result.constraints_passed,
                "execution_ms":    alert_result.execution_ms,
            },
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "restock_plan_generation_failed",
            store_id=store_id,
            tenant_id=x_tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return {"ok": False, "data": {}, "error": {"message": str(exc)}}


@router.get("/restock-plan")
async def get_latest_restock_plan(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
):
    """获取最新一条 AI 补货计划（从 agent_decision_logs 查询，按时间倒序取第一条）"""
    try:
        result = await db.execute(
            text("""
                SELECT
                    id::text          AS id,
                    output_action     AS output_action,
                    reasoning         AS reasoning,
                    confidence        AS confidence,
                    created_at        AS created_at
                FROM agent_decision_logs
                WHERE tenant_id   = :tenant_id
                  AND agent_id    = 'inventory_alert'
                  AND decision_type IN ('generate_restock_alerts', 'restock_plan')
                  AND (input_context->>'store_id') = :store_id
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"tenant_id": x_tenant_id, "store_id": store_id},
        )
        row = result.fetchone()

        if not row:
            return {"ok": True, "data": None}

        return {
            "ok": True,
            "data": {
                "plan_id":      row.id,
                "plan":         row.output_action,
                "reasoning":    row.reasoning,
                "confidence":   float(row.confidence) if row.confidence else 0.0,
                "generated_at": row.created_at.isoformat() if row.created_at else None,
            },
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "get_latest_restock_plan_failed",
            store_id=store_id,
            tenant_id=x_tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return {"ok": True, "data": None}
