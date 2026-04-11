"""
环保合规引擎 — Environmental Compliance Engine

油烟排放监控、餐厨垃圾台账、达标检查。
参考标准: HJ 1240-2021 (餐饮业油烟污染物排放标准)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# HJ 1240 标准阈值 (mg/m3)
# ---------------------------------------------------------------------------
EMISSION_LIMITS = {
    "oil_fume": 1.0,    # 油烟排放浓度上限 mg/m3
    "pm25": 0.075,      # PM2.5 日均浓度限值 mg/m3
    "nmhc": 10.0,       # 非甲烷总烃上限 mg/m3
}


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def is_emission_compliant(
    oil_fume: float | None = None,
    pm25: float | None = None,
    nmhc: float | None = None,
) -> dict:
    """判断排放是否达标（参考HJ 1240标准）。

    返回 {"compliant": bool, "violations": [...]}
    """
    violations = []

    if oil_fume is not None and oil_fume > EMISSION_LIMITS["oil_fume"]:
        violations.append({
            "metric": "oil_fume",
            "value": oil_fume,
            "limit": EMISSION_LIMITS["oil_fume"],
            "unit": "mg/m3",
        })

    if pm25 is not None and pm25 > EMISSION_LIMITS["pm25"]:
        violations.append({
            "metric": "pm25",
            "value": pm25,
            "limit": EMISSION_LIMITS["pm25"],
            "unit": "mg/m3",
        })

    if nmhc is not None and nmhc > EMISSION_LIMITS["nmhc"]:
        violations.append({
            "metric": "nmhc",
            "value": nmhc,
            "limit": EMISSION_LIMITS["nmhc"],
            "unit": "mg/m3",
        })

    return {"compliant": len(violations) == 0, "violations": violations}


def calculate_compliance_rate(records: list[dict]) -> float:
    """计算达标率（百分比）。

    每条记录需包含 oil_fume / pm25 / nmhc 中至少一项。
    """
    if not records:
        return 0.0
    compliant_count = 0
    for r in records:
        result = is_emission_compliant(
            oil_fume=r.get("oil_fume"),
            pm25=r.get("pm25"),
            nmhc=r.get("nmhc"),
        )
        if result["compliant"]:
            compliant_count += 1
    return round(compliant_count / len(records) * 100, 1)


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------

async def record_emission(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """油烟排放记录。

    data: oil_fume, pm25, nmhc, device_id, recorded_at(可选)
    """
    record_id = str(uuid.uuid4())
    compliance = is_emission_compliant(
        oil_fume=data.get("oil_fume"),
        pm25=data.get("pm25"),
        nmhc=data.get("nmhc"),
    )

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_emission_records "
                "(id, tenant_id, store_id, device_id, oil_fume, pm25, nmhc, "
                " compliant, recorded_at) "
                "VALUES (:id, :tenant_id, :store_id, :device_id, :oil_fume, "
                " :pm25, :nmhc, :compliant, COALESCE(:recorded_at, NOW()))"
            ),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "device_id": data.get("device_id"),
                "oil_fume": data.get("oil_fume"),
                "pm25": data.get("pm25"),
                "nmhc": data.get("nmhc"),
                "compliant": compliance["compliant"],
                "recorded_at": data.get("recorded_at"),
            },
        )
        await db.commit()

    log_level = "info" if compliance["compliant"] else "warning"
    getattr(logger, log_level)(
        "emission_recorded",
        tenant_id=tenant_id, store_id=store_id,
        compliant=compliance["compliant"], record_id=record_id,
    )
    return {"id": record_id, "compliant": compliance["compliant"], "violations": compliance["violations"]}


async def get_emission_trend(
    tenant_id: str,
    store_id: str,
    days: int = 30,
) -> dict:
    """排放趋势 — 最近N天每日均值。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT DATE(recorded_at) AS day, "
                "  AVG(oil_fume) AS avg_oil_fume, "
                "  AVG(pm25) AS avg_pm25, "
                "  AVG(nmhc) AS avg_nmhc, "
                "  COUNT(*) AS sample_count, "
                "  SUM(CASE WHEN compliant THEN 1 ELSE 0 END) AS compliant_count "
                "FROM civic_emission_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= CURRENT_DATE - :days "
                "GROUP BY DATE(recorded_at) "
                "ORDER BY day"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "days": days},
        )
        trend = []
        for r in rows.mappings().all():
            row = dict(r)
            row["compliance_rate"] = (
                round(row["compliant_count"] / row["sample_count"] * 100, 1)
                if row["sample_count"] else 0.0
            )
            trend.append(row)

    return {"store_id": store_id, "days": days, "trend": trend}


async def record_waste_disposal(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """餐厨垃圾台账。

    data: waste_type(kitchen_waste/oil_waste/other), weight_kg, collector,
          collector_license, disposal_method, recorded_date
    """
    record_id = str(uuid.uuid4())

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_waste_records "
                "(id, tenant_id, store_id, waste_type, weight_kg, collector, "
                " collector_license, disposal_method, recorded_date, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :waste_type, :weight_kg, "
                " :collector, :collector_license, :disposal_method, "
                " COALESCE(:recorded_date, CURRENT_DATE), NOW())"
            ),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "waste_type": data["waste_type"],
                "weight_kg": data["weight_kg"],
                "collector": data.get("collector"),
                "collector_license": data.get("collector_license"),
                "disposal_method": data.get("disposal_method"),
                "recorded_date": data.get("recorded_date"),
            },
        )
        await db.commit()

    logger.info("waste_disposal_recorded", tenant_id=tenant_id, store_id=store_id, record_id=record_id)
    return {"id": record_id, "status": "recorded", **data}


async def get_waste_summary(
    tenant_id: str,
    store_id: str,
    date_from: str,
    date_to: str,
) -> dict:
    """垃圾处置汇总。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT waste_type, "
                "  COUNT(*) AS record_count, "
                "  SUM(weight_kg) AS total_weight_kg, "
                "  AVG(weight_kg) AS avg_weight_kg "
                "FROM civic_waste_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_date >= :date_from AND recorded_date <= :date_to "
                "GROUP BY waste_type"
            ),
            {"tenant_id": tenant_id, "store_id": store_id,
             "date_from": date_from, "date_to": date_to},
        )
        by_type = [dict(r) for r in rows.mappings().all()]

        total_row = await db.execute(
            text(
                "SELECT COUNT(*) AS record_count, SUM(weight_kg) AS total_weight_kg "
                "FROM civic_waste_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_date >= :date_from AND recorded_date <= :date_to"
            ),
            {"tenant_id": tenant_id, "store_id": store_id,
             "date_from": date_from, "date_to": date_to},
        )
        totals = dict(total_row.mappings().first() or {})

    return {
        "store_id": store_id,
        "date_from": date_from,
        "date_to": date_to,
        "total_records": totals.get("record_count", 0),
        "total_weight_kg": totals.get("total_weight_kg", 0),
        "by_type": by_type,
    }


async def check_emission_compliance(tenant_id: str, store_id: str) -> dict:
    """排放达标检查 — 最近7天整体达标情况。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT id, oil_fume, pm25, nmhc, compliant, recorded_at "
                "FROM civic_emission_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_at >= CURRENT_DATE - 7 "
                "ORDER BY recorded_at DESC"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        records = [dict(r) for r in rows.mappings().all()]

    if not records:
        return {
            "store_id": store_id,
            "status": "no_data",
            "compliance_rate": 0.0,
            "sample_count": 0,
            "recent_violations": [],
        }

    rate = calculate_compliance_rate(records)
    violations = []
    for r in records:
        check = is_emission_compliant(
            oil_fume=r.get("oil_fume"),
            pm25=r.get("pm25"),
            nmhc=r.get("nmhc"),
        )
        if not check["compliant"]:
            violations.append({
                "record_id": r["id"],
                "recorded_at": r["recorded_at"],
                "violations": check["violations"],
            })

    status = "compliant" if rate >= 90.0 else ("warning" if rate >= 70.0 else "non_compliant")

    return {
        "store_id": store_id,
        "status": status,
        "compliance_rate": rate,
        "sample_count": len(records),
        "recent_violations": violations[:10],
        "limits": EMISSION_LIMITS,
    }
