"""
食安追溯引擎 — Food Safety Traceability Engine

台账录入、批次追溯、供应商管理、冷链温控、完整性检查。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def calculate_completeness_score(
    records: list[dict],
    suppliers: list[dict],
) -> dict:
    """计算追溯完整性评分。

    评分维度:
    - 台账覆盖: 所有进货是否都有台账记录
    - 供应商资质: 供应商是否都有有效资质
    返回 {"score": 0-100, "details": {...}}
    """
    if not records:
        return {"score": 0, "details": {"reason": "no_records"}}

    # 台账覆盖率
    total = len(records)
    with_batch = sum(1 for r in records if r.get("batch_no"))
    batch_rate = with_batch / total if total else 0

    # 供应商资质覆盖率
    supplier_ids_in_records = {r.get("supplier_id") for r in records if r.get("supplier_id")}
    registered_supplier_ids = {s.get("id") for s in suppliers if s.get("status") == "active"}
    if supplier_ids_in_records:
        cert_rate = len(supplier_ids_in_records & registered_supplier_ids) / len(supplier_ids_in_records)
    else:
        cert_rate = 0.0

    score = round(batch_rate * 50 + cert_rate * 50, 1)
    return {
        "score": score,
        "details": {
            "batch_coverage": round(batch_rate * 100, 1),
            "supplier_cert_coverage": round(cert_rate * 100, 1),
            "total_records": total,
            "with_batch": with_batch,
            "registered_suppliers": len(registered_supplier_ids),
            "referenced_suppliers": len(supplier_ids_in_records),
        },
    }


def check_expiry_risk(expiry_date: date | str | None, alert_days: int = 30) -> dict:
    """检查是否临近过期。

    返回 {"status": "valid"|"expiring_soon"|"expired", "days_remaining": int|None}
    """
    if expiry_date is None:
        return {"status": "unknown", "days_remaining": None}

    if isinstance(expiry_date, str):
        expiry_date = date.fromisoformat(expiry_date)

    today = date.today()
    delta = (expiry_date - today).days

    if delta < 0:
        status = "expired"
    elif delta <= alert_days:
        status = "expiring_soon"
    else:
        status = "valid"

    return {"status": status, "days_remaining": delta}


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------

async def record_inbound(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """录入进货台账。

    data 必须包含: item_name, quantity, unit, supplier_id, batch_no
    可选: production_date, expiry_date, storage_condition, inspector
    """
    record_id = str(uuid.uuid4())
    log = logger.bind(tenant_id=tenant_id, store_id=store_id, record_id=record_id)

    async with TenantSession(tenant_id) as db:
        # 检查供应商是否已登记
        supplier_row = await db.execute(
            text(
                "SELECT id, name, status FROM civic_suppliers "
                "WHERE tenant_id = :tenant_id AND id = :supplier_id"
            ),
            {"tenant_id": tenant_id, "supplier_id": data["supplier_id"]},
        )
        supplier = supplier_row.mappings().first()
        supplier_warning = None
        if not supplier:
            supplier_warning = f"供应商 {data['supplier_id']} 尚未登记资质，请尽快补录"
            log.warning("supplier_not_registered", supplier_id=data["supplier_id"])
        elif supplier["status"] != "active":
            supplier_warning = f"供应商 {supplier['name']} 状态为 {supplier['status']}，请核实"

        await db.execute(
            text(
                "INSERT INTO trace_inbound_records "
                "(id, tenant_id, store_id, item_name, quantity, unit, "
                " supplier_id, batch_no, production_date, expiry_date, "
                " storage_condition, inspector, recorded_at) "
                "VALUES (:id, :tenant_id, :store_id, :item_name, :quantity, :unit, "
                " :supplier_id, :batch_no, :production_date, :expiry_date, "
                " :storage_condition, :inspector, NOW())"
            ),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "item_name": data["item_name"],
                "quantity": data["quantity"],
                "unit": data.get("unit", "kg"),
                "supplier_id": data["supplier_id"],
                "batch_no": data["batch_no"],
                "production_date": data.get("production_date"),
                "expiry_date": data.get("expiry_date"),
                "storage_condition": data.get("storage_condition"),
                "inspector": data.get("inspector"),
            },
        )
        await db.commit()

    log.info("inbound_recorded", item=data["item_name"], batch=data["batch_no"])
    result = {"id": record_id, "status": "recorded", **data}
    if supplier_warning:
        result["supplier_warning"] = supplier_warning
    return result


async def get_inbound_records(
    tenant_id: str,
    store_id: str,
    date_from: str,
    date_to: str,
    page: int = 1,
    size: int = 20,
) -> dict:
    """查询进货台账（分页）。"""
    offset = (page - 1) * size

    async with TenantSession(tenant_id) as db:
        count_result = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM trace_inbound_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= :date_from AND recorded_at < :date_to"
            ),
            {"tenant_id": tenant_id, "store_id": store_id,
             "date_from": date_from, "date_to": date_to},
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                "SELECT id, item_name, quantity, unit, supplier_id, batch_no, "
                "  production_date, expiry_date, storage_condition, inspector, recorded_at "
                "FROM trace_inbound_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= :date_from AND recorded_at < :date_to "
                "ORDER BY recorded_at DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {"tenant_id": tenant_id, "store_id": store_id,
             "date_from": date_from, "date_to": date_to,
             "limit": size, "offset": offset},
        )
        items = [dict(r) for r in rows.mappings().all()]

    return {"total": total, "page": page, "size": size, "items": items}


async def get_batch_trace(tenant_id: str, batch_no: str) -> dict:
    """批次追溯 — 查找某批次的完整链路: 供应商→入库→冷链记录。"""
    log = logger.bind(tenant_id=tenant_id, batch_no=batch_no)

    async with TenantSession(tenant_id) as db:
        # 入库记录
        inbound_rows = await db.execute(
            text(
                "SELECT r.id, r.store_id, r.item_name, r.quantity, r.unit, "
                "  r.supplier_id, r.production_date, r.expiry_date, "
                "  r.storage_condition, r.inspector, r.recorded_at "
                "FROM trace_inbound_records r "
                "WHERE r.tenant_id = :tenant_id AND r.batch_no = :batch_no "
                "ORDER BY r.recorded_at"
            ),
            {"tenant_id": tenant_id, "batch_no": batch_no},
        )
        inbound = [dict(r) for r in inbound_rows.mappings().all()]

        if not inbound:
            log.info("batch_not_found")
            return {"batch_no": batch_no, "found": False}

        # 供应商信息
        supplier_ids = list({r["supplier_id"] for r in inbound if r.get("supplier_id")})
        suppliers = []
        if supplier_ids:
            placeholders = ", ".join(f":sid_{i}" for i in range(len(supplier_ids)))
            params: dict[str, Any] = {"tenant_id": tenant_id}
            for i, sid in enumerate(supplier_ids):
                params[f"sid_{i}"] = sid
            sup_rows = await db.execute(
                text(
                    f"SELECT id, name, contact, license_no, status "
                    f"FROM civic_suppliers "
                    f"WHERE tenant_id = :tenant_id AND id IN ({placeholders})"
                ),
                params,
            )
            suppliers = [dict(r) for r in sup_rows.mappings().all()]

        # 冷链记录
        coldchain_rows = await db.execute(
            text(
                "SELECT id, store_id, device_id, temperature, humidity, "
                "  recorded_at, location "
                "FROM trace_coldchain_records "
                "WHERE tenant_id = :tenant_id AND batch_no = :batch_no "
                "ORDER BY recorded_at"
            ),
            {"tenant_id": tenant_id, "batch_no": batch_no},
        )
        coldchain = [dict(r) for r in coldchain_rows.mappings().all()]

    log.info("batch_traced", inbound_count=len(inbound), coldchain_count=len(coldchain))
    return {
        "batch_no": batch_no,
        "found": True,
        "supplier": suppliers,
        "inbound_records": inbound,
        "coldchain_records": coldchain,
    }


async def register_supplier(tenant_id: str, data: dict[str, Any]) -> dict:
    """供应商资质登记。

    data: name, contact, license_no, license_expiry, address, category
    """
    supplier_id = str(uuid.uuid4())

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_suppliers "
                "(id, tenant_id, name, contact, license_no, license_expiry, "
                " address, category, status, created_at) "
                "VALUES (:id, :tenant_id, :name, :contact, :license_no, :license_expiry, "
                " :address, :category, 'active', NOW())"
            ),
            {
                "id": supplier_id,
                "tenant_id": tenant_id,
                "name": data["name"],
                "contact": data.get("contact"),
                "license_no": data.get("license_no"),
                "license_expiry": data.get("license_expiry"),
                "address": data.get("address"),
                "category": data.get("category"),
            },
        )
        await db.commit()

    logger.info("supplier_registered", tenant_id=tenant_id, supplier_id=supplier_id, name=data["name"])
    return {"id": supplier_id, "status": "active", **data}


async def get_suppliers(tenant_id: str, status_filter: str | None = None) -> list[dict]:
    """供应商列表。"""
    async with TenantSession(tenant_id) as db:
        if status_filter:
            rows = await db.execute(
                text(
                    "SELECT id, name, contact, license_no, license_expiry, "
                    "  address, category, status, created_at "
                    "FROM civic_suppliers "
                    "WHERE tenant_id = :tenant_id AND status = :status "
                    "ORDER BY created_at DESC"
                ),
                {"tenant_id": tenant_id, "status": status_filter},
            )
        else:
            rows = await db.execute(
                text(
                    "SELECT id, name, contact, license_no, license_expiry, "
                    "  address, category, status, created_at "
                    "FROM civic_suppliers "
                    "WHERE tenant_id = :tenant_id "
                    "ORDER BY created_at DESC"
                ),
                {"tenant_id": tenant_id},
            )
        return [dict(r) for r in rows.mappings().all()]


async def check_supplier_cert_expiry(tenant_id: str, alert_days: int = 30) -> list[dict]:
    """检查供应商资质到期情况，返回即将过期/已过期的供应商列表。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT id, name, contact, license_no, license_expiry, category, status "
                "FROM civic_suppliers "
                "WHERE tenant_id = :tenant_id AND status = 'active' "
                "  AND license_expiry IS NOT NULL "
                "  AND license_expiry <= CURRENT_DATE + :alert_days "
                "ORDER BY license_expiry"
            ),
            {"tenant_id": tenant_id, "alert_days": alert_days},
        )
        results = []
        for r in rows.mappings().all():
            row_dict = dict(r)
            risk = check_expiry_risk(row_dict.get("license_expiry"), alert_days)
            row_dict["expiry_status"] = risk["status"]
            row_dict["days_remaining"] = risk["days_remaining"]
            results.append(row_dict)

    logger.info("supplier_cert_expiry_checked", tenant_id=tenant_id, expiring_count=len(results))
    return results


async def record_coldchain(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """冷链温控记录。

    data: device_id, temperature, humidity, batch_no, location
    """
    record_id = str(uuid.uuid4())

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO trace_coldchain_records "
                "(id, tenant_id, store_id, device_id, temperature, humidity, "
                " batch_no, location, recorded_at) "
                "VALUES (:id, :tenant_id, :store_id, :device_id, :temperature, "
                " :humidity, :batch_no, :location, NOW())"
            ),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "device_id": data.get("device_id"),
                "temperature": data["temperature"],
                "humidity": data.get("humidity"),
                "batch_no": data.get("batch_no"),
                "location": data.get("location"),
            },
        )
        await db.commit()

    logger.info(
        "coldchain_recorded",
        tenant_id=tenant_id, store_id=store_id,
        temp=data["temperature"], record_id=record_id,
    )
    return {"id": record_id, "status": "recorded", **data}


async def check_completeness(
    tenant_id: str,
    store_id: str,
    check_date: str,
) -> dict:
    """追溯完整性检查。

    检查指定日期:
    - 所有进货是否都录入了台账
    - 是否有缺失的供应商资质
    返回完整性评分和缺失项。
    """
    next_day = (date.fromisoformat(check_date) + timedelta(days=1)).isoformat()

    async with TenantSession(tenant_id) as db:
        # 当天进货台账
        rec_rows = await db.execute(
            text(
                "SELECT id, item_name, supplier_id, batch_no "
                "FROM trace_inbound_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= :date_from AND recorded_at < :date_to"
            ),
            {"tenant_id": tenant_id, "store_id": store_id,
             "date_from": check_date, "date_to": next_day},
        )
        records = [dict(r) for r in rec_rows.mappings().all()]

        # 所有活跃供应商
        sup_rows = await db.execute(
            text(
                "SELECT id, name, license_no, license_expiry, status "
                "FROM civic_suppliers "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        )
        suppliers = [dict(r) for r in sup_rows.mappings().all()]

    score_data = calculate_completeness_score(records, suppliers)

    # 找出缺失项
    missing_items = []
    missing_batch = [r for r in records if not r.get("batch_no")]
    if missing_batch:
        missing_items.append({
            "type": "missing_batch_no",
            "count": len(missing_batch),
            "items": [r["item_name"] for r in missing_batch],
        })

    supplier_ids_in_records = {r["supplier_id"] for r in records if r.get("supplier_id")}
    registered_ids = {s["id"] for s in suppliers if s.get("status") == "active"}
    unregistered = supplier_ids_in_records - registered_ids
    if unregistered:
        missing_items.append({
            "type": "unregistered_supplier",
            "count": len(unregistered),
            "supplier_ids": list(unregistered),
        })

    return {
        "date": check_date,
        "store_id": store_id,
        "score": score_data["score"],
        "details": score_data["details"],
        "missing_items": missing_items,
        "record_count": len(records),
    }


async def get_trace_stats(tenant_id: str, store_id: str) -> dict:
    """追溯统计: 录入率、合格率、供应商数等。"""
    async with TenantSession(tenant_id) as db:
        # 最近30天台账数
        rec_count = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM trace_inbound_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= CURRENT_DATE - 30"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        record_count_30d = rec_count.scalar() or 0

        # 有批次号的占比
        with_batch = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM trace_inbound_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= CURRENT_DATE - 30 "
                "  AND batch_no IS NOT NULL AND batch_no != ''"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        batch_count = with_batch.scalar() or 0

        # 供应商统计
        sup_count = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_suppliers "
                "WHERE tenant_id = :tenant_id AND status = 'active'"
            ),
            {"tenant_id": tenant_id},
        )
        active_suppliers = sup_count.scalar() or 0

        # 冷链记录数
        cc_count = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM trace_coldchain_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= CURRENT_DATE - 30"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        coldchain_count_30d = cc_count.scalar() or 0

    batch_rate = round(batch_count / record_count_30d * 100, 1) if record_count_30d else 0.0

    return {
        "store_id": store_id,
        "period": "last_30_days",
        "inbound_records": record_count_30d,
        "batch_coverage_rate": batch_rate,
        "active_suppliers": active_suppliers,
        "coldchain_records": coldchain_count_30d,
    }
