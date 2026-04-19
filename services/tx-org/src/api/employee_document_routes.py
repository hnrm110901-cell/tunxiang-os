"""员工证照管理 API 路由

端点列表：
  GET  /api/v1/employee-documents/expiring              即将到期证照（30/15/7天分级）
  GET  /api/v1/employee-documents/statistics             证照统计（有效/即将到期/已过期）
  GET  /api/v1/employee-documents/{employee_id}          某员工所有证照信息
  PUT  /api/v1/employee-documents/{employee_id}          更新证照信息
  POST /api/v1/employee-documents/scan-expiry            手动触发到期扫描

数据源：employees 表的证照字段 + compliance_alerts 表

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/employee-documents", tags=["employee-documents"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _classify_severity(days_remaining: int) -> str:
    """根据剩余天数分级"""
    if days_remaining < 0:
        return "critical"  # 已过期
    elif days_remaining <= 7:
        return "high"
    elif days_remaining <= 15:
        return "medium"
    elif days_remaining <= 30:
        return "low"
    return "normal"


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class UpdateDocumentReq(BaseModel):
    health_cert_number: Optional[str] = Field(None, description="健康证编号")
    health_cert_expiry: Optional[date] = Field(None, description="健康证到期日")
    food_safety_cert: Optional[str] = Field(None, description="食品安全证编号")
    food_safety_cert_expiry: Optional[date] = Field(None, description="食品安全证到期日")
    contract_start_date: Optional[date] = Field(None, description="合同开始日期")
    contract_end_date: Optional[date] = Field(None, description="合同结束日期")


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/expiring")
async def get_expiring_documents(
    request: Request,
    threshold_days: int = Query(30, ge=1, le=365, description="距到期天数阈值"),
    store_id: Optional[str] = Query(None, description="门店筛选"),
    severity: Optional[str] = Query(None, description="严重度筛选: critical/high/medium/low"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """即将到期证照（30/15/7天分级）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND e.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {"threshold": threshold_days}
    if store_id:
        params["store_id"] = store_id

    # 查询健康证和食品安全证到期情况
    sql = text(f"""
        WITH cert_records AS (
            -- 健康证
            SELECT
                e.id::text AS employee_id,
                e.emp_name,
                e.store_id::text,
                e.department_id::text,
                'health_cert' AS cert_type,
                '健康证' AS cert_type_name,
                e.health_cert_number AS cert_number,
                e.health_cert_expiry AS expiry_date,
                (e.health_cert_expiry - CURRENT_DATE) AS days_remaining
            FROM employees e
            WHERE e.is_deleted = FALSE
              AND e.health_cert_expiry IS NOT NULL
              AND e.health_cert_expiry <= CURRENT_DATE + :threshold * INTERVAL '1 day'
              {store_filter}

            UNION ALL

            -- 食品安全证
            SELECT
                e.id::text AS employee_id,
                e.emp_name,
                e.store_id::text,
                e.department_id::text,
                'food_safety_cert' AS cert_type,
                '食品安全证' AS cert_type_name,
                e.food_safety_cert AS cert_number,
                e.food_safety_cert_expiry AS expiry_date,
                (e.food_safety_cert_expiry - CURRENT_DATE) AS days_remaining
            FROM employees e
            WHERE e.is_deleted = FALSE
              AND e.food_safety_cert_expiry IS NOT NULL
              AND e.food_safety_cert_expiry <= CURRENT_DATE + :threshold * INTERVAL '1 day'
              {store_filter}

            UNION ALL

            -- 合同到期
            SELECT
                e.id::text AS employee_id,
                e.emp_name,
                e.store_id::text,
                e.department_id::text,
                'contract' AS cert_type,
                '劳动合同' AS cert_type_name,
                NULL AS cert_number,
                e.contract_end_date AS expiry_date,
                (e.contract_end_date - CURRENT_DATE) AS days_remaining
            FROM employees e
            WHERE e.is_deleted = FALSE
              AND e.contract_end_date IS NOT NULL
              AND e.contract_end_date <= CURRENT_DATE + :threshold * INTERVAL '1 day'
              {store_filter}
        )
        SELECT * FROM cert_records
        ORDER BY days_remaining ASC
    """)

    result = await db.execute(sql, params)
    all_items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        days = int(d["days_remaining"]) if d["days_remaining"] is not None else 0
        d["days_remaining"] = days
        d["severity"] = _classify_severity(days)
        d["expiry_date"] = str(d["expiry_date"]) if d.get("expiry_date") else None
        all_items.append(d)

    # 严重度筛选
    if severity:
        all_items = [item for item in all_items if item["severity"] == severity]

    total = len(all_items)
    offset = (page - 1) * size
    paged_items = all_items[offset : offset + size]

    # 分级统计
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in all_items:
        sev = item.get("severity", "low")
        if sev in severity_counts:
            severity_counts[sev] += 1

    log.info("get_expiring_documents", tenant_id=tenant_id, total=total, threshold=threshold_days)
    return _ok(
        {
            "items": paged_items,
            "total": total,
            "page": page,
            "size": size,
            "severity_counts": severity_counts,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.get("/statistics")
async def get_document_statistics(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选"),
    db: AsyncSession = Depends(get_db),
):
    """证照统计（有效/即将到期/已过期）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND e.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id

    sql = text(f"""
        SELECT
            -- 健康证统计
            COUNT(*) FILTER (WHERE e.health_cert_expiry IS NOT NULL) AS health_cert_total,
            COUNT(*) FILTER (WHERE e.health_cert_expiry IS NOT NULL AND e.health_cert_expiry > CURRENT_DATE + INTERVAL '30 days') AS health_cert_valid,
            COUNT(*) FILTER (WHERE e.health_cert_expiry IS NOT NULL AND e.health_cert_expiry > CURRENT_DATE AND e.health_cert_expiry <= CURRENT_DATE + INTERVAL '30 days') AS health_cert_expiring,
            COUNT(*) FILTER (WHERE e.health_cert_expiry IS NOT NULL AND e.health_cert_expiry <= CURRENT_DATE) AS health_cert_expired,
            -- 食品安全证统计
            COUNT(*) FILTER (WHERE e.food_safety_cert_expiry IS NOT NULL) AS food_cert_total,
            COUNT(*) FILTER (WHERE e.food_safety_cert_expiry IS NOT NULL AND e.food_safety_cert_expiry > CURRENT_DATE + INTERVAL '30 days') AS food_cert_valid,
            COUNT(*) FILTER (WHERE e.food_safety_cert_expiry IS NOT NULL AND e.food_safety_cert_expiry > CURRENT_DATE AND e.food_safety_cert_expiry <= CURRENT_DATE + INTERVAL '30 days') AS food_cert_expiring,
            COUNT(*) FILTER (WHERE e.food_safety_cert_expiry IS NOT NULL AND e.food_safety_cert_expiry <= CURRENT_DATE) AS food_cert_expired,
            -- 合同统计
            COUNT(*) FILTER (WHERE e.contract_end_date IS NOT NULL) AS contract_total,
            COUNT(*) FILTER (WHERE e.contract_end_date IS NOT NULL AND e.contract_end_date > CURRENT_DATE + INTERVAL '30 days') AS contract_valid,
            COUNT(*) FILTER (WHERE e.contract_end_date IS NOT NULL AND e.contract_end_date > CURRENT_DATE AND e.contract_end_date <= CURRENT_DATE + INTERVAL '30 days') AS contract_expiring,
            COUNT(*) FILTER (WHERE e.contract_end_date IS NOT NULL AND e.contract_end_date <= CURRENT_DATE) AS contract_expired,
            -- 无证照员工
            COUNT(*) FILTER (WHERE e.health_cert_number IS NULL) AS no_health_cert,
            COUNT(*) FILTER (WHERE e.food_safety_cert IS NULL) AS no_food_cert
        FROM employees e
        WHERE e.is_deleted = FALSE AND e.status = 'active' {store_filter}
    """)

    result = await db.execute(sql, params)
    row = dict(result.fetchone()._mapping)

    # 将所有值转int
    for key in row:
        row[key] = int(row[key] or 0)

    log.info("document_statistics", tenant_id=tenant_id)
    return _ok(
        {
            "health_cert": {
                "total": row["health_cert_total"],
                "valid": row["health_cert_valid"],
                "expiring_30d": row["health_cert_expiring"],
                "expired": row["health_cert_expired"],
            },
            "food_safety_cert": {
                "total": row["food_cert_total"],
                "valid": row["food_cert_valid"],
                "expiring_30d": row["food_cert_expiring"],
                "expired": row["food_cert_expired"],
            },
            "contract": {
                "total": row["contract_total"],
                "valid": row["contract_valid"],
                "expiring_30d": row["contract_expiring"],
                "expired": row["contract_expired"],
            },
            "missing": {
                "no_health_cert": row["no_health_cert"],
                "no_food_safety_cert": row["no_food_cert"],
            },
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.get("/{employee_id}")
async def get_employee_documents(
    request: Request,
    employee_id: str,
    db: AsyncSession = Depends(get_db),
):
    """某员工所有证照信息"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            e.id::text AS employee_id,
            e.emp_name,
            e.store_id::text,
            e.department_id::text,
            e.health_cert_number,
            e.health_cert_expiry,
            e.food_safety_cert,
            e.food_safety_cert_expiry,
            e.contract_start_date,
            e.contract_end_date
        FROM employees e
        WHERE e.id = :eid AND e.is_deleted = FALSE
    """)
    result = await db.execute(sql, {"eid": employee_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="员工不存在")

    data = dict(row._mapping)

    # 构建证照列表
    today = date.today()
    documents = []

    if data.get("health_cert_number") or data.get("health_cert_expiry"):
        days_remaining = (data["health_cert_expiry"] - today).days if data.get("health_cert_expiry") else None
        documents.append(
            {
                "cert_type": "health_cert",
                "cert_type_name": "健康证",
                "cert_number": data.get("health_cert_number"),
                "expiry_date": str(data["health_cert_expiry"]) if data.get("health_cert_expiry") else None,
                "days_remaining": days_remaining,
                "severity": _classify_severity(days_remaining) if days_remaining is not None else "unknown",
                "status": "expired"
                if days_remaining is not None and days_remaining < 0
                else "valid"
                if days_remaining and days_remaining > 0
                else "unknown",
            }
        )

    if data.get("food_safety_cert") or data.get("food_safety_cert_expiry"):
        days_remaining = (data["food_safety_cert_expiry"] - today).days if data.get("food_safety_cert_expiry") else None
        documents.append(
            {
                "cert_type": "food_safety_cert",
                "cert_type_name": "食品安全证",
                "cert_number": data.get("food_safety_cert"),
                "expiry_date": str(data["food_safety_cert_expiry"]) if data.get("food_safety_cert_expiry") else None,
                "days_remaining": days_remaining,
                "severity": _classify_severity(days_remaining) if days_remaining is not None else "unknown",
                "status": "expired"
                if days_remaining is not None and days_remaining < 0
                else "valid"
                if days_remaining and days_remaining > 0
                else "unknown",
            }
        )

    if data.get("contract_start_date") or data.get("contract_end_date"):
        days_remaining = (data["contract_end_date"] - today).days if data.get("contract_end_date") else None
        documents.append(
            {
                "cert_type": "contract",
                "cert_type_name": "劳动合同",
                "cert_number": None,
                "start_date": str(data["contract_start_date"]) if data.get("contract_start_date") else None,
                "expiry_date": str(data["contract_end_date"]) if data.get("contract_end_date") else None,
                "days_remaining": days_remaining,
                "severity": _classify_severity(days_remaining) if days_remaining is not None else "unknown",
                "status": "expired"
                if days_remaining is not None and days_remaining < 0
                else "valid"
                if days_remaining and days_remaining > 0
                else "unknown",
            }
        )

    log.info("get_employee_documents", tenant_id=tenant_id, employee_id=employee_id, doc_count=len(documents))
    return _ok(
        {
            "employee_id": data["employee_id"],
            "emp_name": data["emp_name"],
            "documents": documents,
        }
    )


@router.put("/{employee_id}")
async def update_employee_documents(
    request: Request,
    employee_id: str,
    req: UpdateDocumentReq,
    db: AsyncSession = Depends(get_db),
):
    """更新证照信息"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id FROM employees WHERE id = :eid AND is_deleted = FALSE"),
        {"eid": employee_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="员工不存在")

    update_fields: list[str] = []
    params: dict[str, Any] = {"eid": employee_id, "now": datetime.now(timezone.utc)}

    field_map = {
        "health_cert_number": req.health_cert_number,
        "health_cert_expiry": req.health_cert_expiry,
        "food_safety_cert": req.food_safety_cert,
        "food_safety_cert_expiry": req.food_safety_cert_expiry,
        "contract_start_date": req.contract_start_date,
        "contract_end_date": req.contract_end_date,
    }

    for field_name, value in field_map.items():
        if value is not None:
            update_fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_fields.append("updated_at = :now")
    set_clause = ", ".join(update_fields)

    sql = text(f"UPDATE employees SET {set_clause} WHERE id = :eid AND is_deleted = FALSE")
    await db.execute(sql, params)
    await db.commit()

    log.info("update_employee_documents", tenant_id=tenant_id, employee_id=employee_id)
    return _ok({"employee_id": employee_id, "updated": True})


@router.post("/scan-expiry")
async def scan_expiry(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选（空=全部）"),
    db: AsyncSession = Depends(get_db),
):
    """手动触发到期扫描，生成compliance_alerts"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    store_filter = "AND e.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {"tenant_id": tenant_id, "now": now}
    if store_id:
        params["store_id"] = store_id

    # 查询所有即将到期或已过期的证照
    scan_sql = text(f"""
        WITH expiring_certs AS (
            -- 健康证
            SELECT
                e.id AS employee_id,
                e.store_id,
                'health_cert_expiry' AS alert_type,
                '健康证' AS doc_name,
                e.health_cert_expiry AS expiry_date,
                (e.health_cert_expiry - CURRENT_DATE) AS days_remaining
            FROM employees e
            WHERE e.is_deleted = FALSE AND e.status = 'active'
              AND e.health_cert_expiry IS NOT NULL
              AND e.health_cert_expiry <= CURRENT_DATE + INTERVAL '30 days'
              {store_filter}

            UNION ALL

            -- 食品安全证
            SELECT
                e.id AS employee_id,
                e.store_id,
                'food_safety_cert_expiry' AS alert_type,
                '食品安全证' AS doc_name,
                e.food_safety_cert_expiry AS expiry_date,
                (e.food_safety_cert_expiry - CURRENT_DATE) AS days_remaining
            FROM employees e
            WHERE e.is_deleted = FALSE AND e.status = 'active'
              AND e.food_safety_cert_expiry IS NOT NULL
              AND e.food_safety_cert_expiry <= CURRENT_DATE + INTERVAL '30 days'
              {store_filter}

            UNION ALL

            -- 合同到期
            SELECT
                e.id AS employee_id,
                e.store_id,
                'contract_expiry' AS alert_type,
                '劳动合同' AS doc_name,
                e.contract_end_date AS expiry_date,
                (e.contract_end_date - CURRENT_DATE) AS days_remaining
            FROM employees e
            WHERE e.is_deleted = FALSE AND e.status = 'active'
              AND e.contract_end_date IS NOT NULL
              AND e.contract_end_date <= CURRENT_DATE + INTERVAL '30 days'
              {store_filter}
        )
        SELECT * FROM expiring_certs ORDER BY days_remaining ASC
    """)

    result = await db.execute(scan_sql, params)
    rows = result.fetchall()

    created_alerts = 0
    skipped_alerts = 0

    for r in rows:
        d = dict(r._mapping)
        days = int(d["days_remaining"]) if d["days_remaining"] is not None else 0
        severity = _classify_severity(days)

        # 检查是否已有未解决的同类预警
        existing = await db.execute(
            text("""
                SELECT id FROM compliance_alerts
                WHERE employee_id = :emp_id
                  AND alert_type = :alert_type
                  AND status IN ('pending', 'acknowledged')
                LIMIT 1
            """),
            {"emp_id": str(d["employee_id"]), "alert_type": d["alert_type"]},
        )
        if existing.fetchone():
            skipped_alerts += 1
            continue

        # 创建预警
        alert_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO compliance_alerts (
                    id, tenant_id, employee_id, store_id, alert_type, severity,
                    title, description, status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :employee_id, :store_id, :alert_type, :severity,
                    :title, :description, 'pending', :now, :now
                )
            """),
            {
                "id": alert_id,
                "tenant_id": tenant_id,
                "employee_id": str(d["employee_id"]),
                "store_id": str(d["store_id"]) if d.get("store_id") else None,
                "alert_type": d["alert_type"],
                "severity": severity,
                "title": f"{d['doc_name']}{'已过期' if days < 0 else f'将在{days}天后到期'}",
                "description": f"到期日期: {d['expiry_date']}, 剩余天数: {days}",
                "now": now,
            },
        )
        created_alerts += 1

    await db.commit()

    log.info(
        "scan_expiry",
        tenant_id=tenant_id,
        scanned=len(rows),
        created=created_alerts,
        skipped=skipped_alerts,
    )
    return _ok(
        {
            "scanned_records": len(rows),
            "created_alerts": created_alerts,
            "skipped_existing": skipped_alerts,
            "scanned_at": now.isoformat(),
        }
    )
