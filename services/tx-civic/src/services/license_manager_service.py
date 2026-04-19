"""
证照生命周期管理 — License Lifecycle Manager

证照登记、到期预警、健康证管理、覆盖率评估。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 不同业态必须持有的证照类型
# ---------------------------------------------------------------------------
REQUIRED_LICENSES: dict[str, list[str]] = {
    "正餐": [
        "营业执照",
        "食品经营许可证",
        "消防安全检查合格证",
        "排污许可证",
        "环境影响评价",
    ],
    "快餐": [
        "营业执照",
        "食品经营许可证",
        "消防安全检查合格证",
        "排污许可证",
    ],
    "饮品": [
        "营业执照",
        "食品经营许可证",
        "消防安全检查合格证",
    ],
    "烘焙": [
        "营业执照",
        "食品经营许可证",
        "食品生产许可证",
        "消防安全检查合格证",
    ],
    "default": [
        "营业执照",
        "食品经营许可证",
        "消防安全检查合格证",
    ],
}


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def classify_renewal_urgency(expiry_date: date | str, today: date | None = None) -> str:
    """续办紧急程度: valid / expiring_soon(30天内) / expired。"""
    if isinstance(expiry_date, str):
        expiry_date = date.fromisoformat(expiry_date)
    if today is None:
        today = date.today()

    delta = (expiry_date - today).days
    if delta < 0:
        return "expired"
    if delta <= 30:
        return "expiring_soon"
    return "valid"


def calculate_coverage_score(
    required: list[str],
    registered: list[str],
) -> dict:
    """证照覆盖率评分。

    返回 {"score": 0-100, "missing": [...], "covered": [...]}
    """
    if not required:
        return {"score": 100.0, "missing": [], "covered": []}

    registered_set = set(registered)
    required_set = set(required)
    covered = sorted(required_set & registered_set)
    missing = sorted(required_set - registered_set)

    score = round(len(covered) / len(required_set) * 100, 1)
    return {"score": score, "missing": missing, "covered": covered}


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------


async def register_license(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """登记证照。

    data: license_type, license_no, issued_by, issue_date, expiry_date, attachment_url
    """
    license_id = str(uuid.uuid4())
    urgency = classify_renewal_urgency(data["expiry_date"]) if data.get("expiry_date") else "valid"

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_licenses "
                "(id, tenant_id, store_id, license_type, license_no, issued_by, "
                " issue_date, expiry_date, attachment_url, renewal_status, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :license_type, :license_no, "
                " :issued_by, :issue_date, :expiry_date, :attachment_url, "
                " :renewal_status, NOW())"
            ),
            {
                "id": license_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "license_type": data["license_type"],
                "license_no": data.get("license_no"),
                "issued_by": data.get("issued_by"),
                "issue_date": data.get("issue_date"),
                "expiry_date": data.get("expiry_date"),
                "attachment_url": data.get("attachment_url"),
                "renewal_status": urgency if urgency != "valid" else "active",
            },
        )
        await db.commit()

    logger.info("license_registered", tenant_id=tenant_id, license_id=license_id, type=data["license_type"])
    return {"id": license_id, "renewal_urgency": urgency, **data}


async def get_licenses(
    tenant_id: str,
    store_id: str,
    license_type: str | None = None,
) -> list[dict]:
    """证照列表。"""
    async with TenantSession(tenant_id) as db:
        if license_type:
            rows = await db.execute(
                text(
                    "SELECT id, license_type, license_no, issued_by, issue_date, "
                    "  expiry_date, attachment_url, renewal_status, created_at "
                    "FROM civic_licenses "
                    "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                    "  AND license_type = :license_type "
                    "ORDER BY expiry_date"
                ),
                {"tenant_id": tenant_id, "store_id": store_id, "license_type": license_type},
            )
        else:
            rows = await db.execute(
                text(
                    "SELECT id, license_type, license_no, issued_by, issue_date, "
                    "  expiry_date, attachment_url, renewal_status, created_at "
                    "FROM civic_licenses "
                    "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                    "ORDER BY expiry_date"
                ),
                {"tenant_id": tenant_id, "store_id": store_id},
            )

        results = []
        for r in rows.mappings().all():
            row = dict(r)
            if row.get("expiry_date"):
                row["renewal_urgency"] = classify_renewal_urgency(row["expiry_date"])
            else:
                row["renewal_urgency"] = "valid"
            results.append(row)

    return results


async def get_expiring_licenses(tenant_id: str, days: int = 30) -> list[dict]:
    """即将到期证照（全品牌）。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT l.id, l.store_id, l.license_type, l.license_no, "
                "  l.expiry_date, l.renewal_status "
                "FROM civic_licenses l "
                "WHERE l.tenant_id = :tenant_id "
                "  AND l.expiry_date IS NOT NULL "
                "  AND l.expiry_date <= CURRENT_DATE + :days "
                "ORDER BY l.expiry_date"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        results = []
        for r in rows.mappings().all():
            row = dict(r)
            row["renewal_urgency"] = classify_renewal_urgency(row["expiry_date"])
            row["days_remaining"] = (
                (row["expiry_date"] - date.today()).days if isinstance(row["expiry_date"], date) else None
            )
            results.append(row)

    logger.info("expiring_licenses_checked", tenant_id=tenant_id, count=len(results))
    return results


async def update_renewal_status(
    tenant_id: str,
    license_id: str,
    status: str,
) -> dict:
    """更新续办状态。

    status: active / renewing / renewed / expired
    """
    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "UPDATE civic_licenses "
                "SET renewal_status = :status, updated_at = NOW() "
                "WHERE tenant_id = :tenant_id AND id = :license_id"
            ),
            {"tenant_id": tenant_id, "license_id": license_id, "status": status},
        )
        await db.commit()

    logger.info("license_renewal_updated", license_id=license_id, status=status)
    return {"license_id": license_id, "renewal_status": status}


async def register_health_cert(
    tenant_id: str,
    store_id: str,
    employee_id: str,
    data: dict[str, Any],
) -> dict:
    """登记员工健康证。

    data: employee_name, cert_no, issue_date, expiry_date, attachment_url
    """
    cert_id = str(uuid.uuid4())

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_health_certs "
                "(id, tenant_id, store_id, employee_id, employee_name, cert_no, "
                " issue_date, expiry_date, attachment_url, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :employee_id, :employee_name, "
                " :cert_no, :issue_date, :expiry_date, :attachment_url, NOW())"
            ),
            {
                "id": cert_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "employee_name": data.get("employee_name"),
                "cert_no": data.get("cert_no"),
                "issue_date": data.get("issue_date"),
                "expiry_date": data.get("expiry_date"),
                "attachment_url": data.get("attachment_url"),
            },
        )
        await db.commit()

    logger.info("health_cert_registered", tenant_id=tenant_id, cert_id=cert_id, employee_id=employee_id)
    return {"id": cert_id, "employee_id": employee_id, **data}


async def get_expiring_health_certs(tenant_id: str, days: int = 30) -> list[dict]:
    """即将到期健康证。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT id, store_id, employee_id, employee_name, cert_no, "
                "  expiry_date "
                "FROM civic_health_certs "
                "WHERE tenant_id = :tenant_id "
                "  AND expiry_date IS NOT NULL "
                "  AND expiry_date <= CURRENT_DATE + :days "
                "ORDER BY expiry_date"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        results = []
        for r in rows.mappings().all():
            row = dict(r)
            row["renewal_urgency"] = classify_renewal_urgency(row["expiry_date"])
            row["days_remaining"] = (
                (row["expiry_date"] - date.today()).days if isinstance(row["expiry_date"], date) else None
            )
            results.append(row)

    logger.info("expiring_health_certs_checked", tenant_id=tenant_id, count=len(results))
    return results


async def get_license_coverage(tenant_id: str, store_id: str) -> dict:
    """证照覆盖率 — 该门店应有证照 vs 已登记证照。"""
    async with TenantSession(tenant_id) as db:
        # 获取门店业态
        store_row = await db.execute(
            text("SELECT business_type FROM stores WHERE tenant_id = :tenant_id AND id = :store_id"),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        store = store_row.mappings().first()
        business_type = store["business_type"] if store else "default"

        # 已登记的证照类型（有效期内或无到期日的）
        lic_rows = await db.execute(
            text(
                "SELECT DISTINCT license_type "
                "FROM civic_licenses "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND (expiry_date IS NULL OR expiry_date > CURRENT_DATE)"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        registered = [r["license_type"] for r in lic_rows.mappings().all()]

    required = REQUIRED_LICENSES.get(business_type, REQUIRED_LICENSES["default"])
    coverage = calculate_coverage_score(required, registered)

    return {
        "store_id": store_id,
        "business_type": business_type,
        "required_licenses": required,
        "registered_licenses": registered,
        **coverage,
    }
