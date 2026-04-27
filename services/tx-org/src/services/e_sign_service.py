"""tx-org 电子签约模块服务。"""

from __future__ import annotations

import hashlib
import json
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee

logger = structlog.get_logger(__name__)

EMPLOYEES_TABLE = Employee.__tablename__
CONTRACTS_TABLE = "e_sign_contracts"

CONTRACT_TEMPLATES: dict[str, dict[str, Any]] = {
    "labor_standard": {
        "name": "标准劳动合同",
        "fields": [
            "employee_name",
            "id_card_no",
            "position",
            "salary_fen",
            "start_date",
            "end_date",
            "probation_months",
        ],
        "duration_months": 36,
    },
    "labor_probation": {
        "name": "试用期劳动合同",
        "fields": [
            "employee_name",
            "id_card_no",
            "position",
            "salary_fen",
            "start_date",
            "probation_end_date",
        ],
        "duration_months": 3,
    },
    "part_time": {
        "name": "非全日制用工协议",
        "fields": [
            "employee_name",
            "id_card_no",
            "position",
            "hourly_rate_fen",
            "start_date",
        ],
        "duration_months": 12,
    },
    "confidentiality": {
        "name": "保密协议",
        "fields": [
            "employee_name",
            "id_card_no",
            "position",
            "scope",
            "duration_years",
        ],
        "duration_months": 24,
    },
    "non_compete": {
        "name": "竞业限制协议",
        "fields": [
            "employee_name",
            "id_card_no",
            "position",
            "compensation_fen",
            "duration_months",
            "scope",
        ],
        "duration_months": 24,
    },
}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field} 不是合法 UUID") from e


def _tenant_str(tenant_id: str | uuid.UUID) -> str:
    return str(tenant_id) if isinstance(tenant_id, uuid.UUID) else tenant_id


def _parse_date_val(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    raise ValueError(f"无法解析日期: {v!r}")


def _add_months(d: date, months: int) -> date:
    m0 = d.month - 1 + months
    y = d.year + m0 // 12
    m = m0 % 12 + 1
    last = monthrange(y, m)[1]
    day = min(d.day, last)
    return date(y, m, day)


def _effective_end_date(template_code: str, field_values: Mapping[str, Any]) -> date | None:
    fv = dict(field_values)
    if fv.get("end_date") is not None:
        return _parse_date_val(fv["end_date"])
    if fv.get("probation_end_date") is not None:
        return _parse_date_val(fv["probation_end_date"])
    if fv.get("start_date") is not None and template_code in CONTRACT_TEMPLATES:
        start = _parse_date_val(fv["start_date"])
        if start is None:
            return None
        dm = int(CONTRACT_TEMPLATES[template_code]["duration_months"])
        return _add_months(start, dm)
    return None


def _validate_required_fields(template_code: str, field_values: dict[str, Any]) -> None:
    tpl = CONTRACT_TEMPLATES[template_code]
    for f in tpl["fields"]:
        if f not in field_values:
            raise ValueError(f"缺少必填字段: {f}")
        v = field_values[f]
        if v is None:
            raise ValueError(f"必填字段为空: {f}")
        if isinstance(v, str) and not v.strip():
            raise ValueError(f"必填字段为空: {f}")


def _serialize_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat()


def _row_to_contract_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "contract_id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "employee_id": str(row["employee_id"]),
        "template_code": row["template_code"],
        "field_values": row["field_values"],
        "status": row["status"],
        "sign_url": row.get("sign_url"),
        "signature_hash": row.get("signature_hash"),
        "signed_at": _serialize_dt(row.get("signed_at")),
        "expires_at": _serialize_dt(row.get("expires_at")),
        "terminated_at": _serialize_dt(row.get("terminated_at")),
        "termination_reason": row.get("termination_reason"),
        "created_at": _serialize_dt(row.get("created_at")),
        "updated_at": _serialize_dt(row.get("updated_at")),
    }
    if "emp_name" in row:
        out["emp_name"] = row["emp_name"]
    return out


async def create_contract(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    template_code: str,
    employee_id: str,
    field_values: dict[str, Any],
) -> dict[str, Any]:
    """创建电子合同。"""
    if template_code not in CONTRACT_TEMPLATES:
        raise ValueError(f"未知模板编码: {template_code}")
    _validate_required_fields(template_code, field_values)
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    eid = _parse_uuid(employee_id, "employee_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    chk = await db.execute(
        text(
            f"""
            SELECT 1 FROM {EMPLOYEES_TABLE}
            WHERE id = :eid AND tenant_id = :tid AND is_deleted = FALSE
            """
        ),
        {"eid": eid, "tid": tid},
    )
    if chk.first() is None:
        raise ValueError("员工不存在或不属于当前租户")
    cid = uuid.uuid4()
    fv_json = json.dumps(field_values, ensure_ascii=False)
    await db.execute(
        text(
            f"""
            INSERT INTO {CONTRACTS_TABLE} (
                id, tenant_id, employee_id, template_code, field_values,
                status, created_at, updated_at
            ) VALUES (
                :id, :tid, :eid, :tcode, CAST(:fv AS jsonb),
                'draft', NOW(), NOW()
            )
            """
        ),
        {
            "id": cid,
            "tid": tid,
            "eid": eid,
            "tcode": template_code,
            "fv": fv_json,
        },
    )
    await db.flush()
    tpl_name = str(CONTRACT_TEMPLATES[template_code]["name"])
    logger.info(
        "e_sign.contract_created",
        tenant_id=ts,
        contract_id=str(cid),
        template_code=template_code,
    )
    return {
        "contract_id": str(cid),
        "template_name": tpl_name,
        "status": "draft",
    }


async def send_for_signing(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    contract_id: str,
) -> dict[str, Any]:
    """发起签署。"""
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    cid = _parse_uuid(contract_id, "contract_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=7)
    sign_url = f"https://esign.mock.tunxiang.local/sign/{contract_id}?token=mock"
    result = await db.execute(
        text(
            f"""
            UPDATE {CONTRACTS_TABLE}
            SET status = 'pending_sign',
                sign_url = :url,
                expires_at = :exp,
                updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid AND status = 'draft'
            RETURNING id
            """
        ),
        {"url": sign_url, "exp": exp, "cid": cid, "tid": tid},
    )
    row = result.first()
    if row is None:
        raise ValueError("合同不存在、不属于当前租户或状态不是草稿")
    await db.flush()
    logger.info(
        "e_sign.send_for_signing",
        tenant_id=ts,
        contract_id=contract_id,
    )
    return {
        "contract_id": contract_id,
        "sign_url": sign_url,
        "expires_at": exp.isoformat(),
    }


async def sign_contract(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    contract_id: str,
    signature_data: str,
) -> dict[str, Any]:
    """员工签署合同。"""
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    cid = _parse_uuid(contract_id, "contract_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    sig_hash = hashlib.sha256(signature_data.encode("utf-8")).hexdigest()
    result = await db.execute(
        text(
            f"""
            UPDATE {CONTRACTS_TABLE}
            SET status = 'signed',
                signed_at = NOW(),
                signature_hash = :sh,
                updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid AND status = 'pending_sign'
            RETURNING signed_at
            """
        ),
        {"sh": sig_hash, "cid": cid, "tid": tid},
    )
    r = result.first()
    if r is None:
        raise ValueError("合同不存在、不属于当前租户或状态不是待签署")
    signed_at = r[0]
    if not isinstance(signed_at, datetime):
        raise TypeError("signed_at 类型异常")
    await db.flush()
    logger.info(
        "e_sign.contract_signed",
        tenant_id=ts,
        contract_id=contract_id,
    )
    return {
        "contract_id": contract_id,
        "status": "signed",
        "signed_at": _serialize_dt(signed_at) or "",
    }


async def get_contracts(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    employee_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """查询合同列表。"""
    if page < 1:
        raise ValueError("page 须 >= 1")
    if size < 1:
        raise ValueError("size 须 >= 1")
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    conditions = ["c.tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tid}
    if employee_id is not None:
        conditions.append("c.employee_id = :eid")
        params["eid"] = _parse_uuid(employee_id, "employee_id")
    if status is not None:
        conditions.append("c.status = :st")
        params["st"] = status
    where_sql = " AND ".join(conditions)
    count_r = await db.execute(
        text(
            f"""
            SELECT COUNT(*) AS n
            FROM {CONTRACTS_TABLE} c
            INNER JOIN {EMPLOYEES_TABLE} e
              ON e.id = c.employee_id AND e.tenant_id = c.tenant_id
            WHERE {where_sql}
            """
        ),
        params,
    )
    total = int(count_r.scalar_one())
    offset = (page - 1) * size
    params_list = {**params, "lim": size, "off": offset}
    list_r = await db.execute(
        text(
            f"""
            SELECT
              c.id, c.tenant_id, c.employee_id, c.template_code, c.field_values,
              c.status, c.sign_url, c.signature_hash, c.signed_at, c.expires_at,
              c.terminated_at, c.termination_reason, c.created_at, c.updated_at,
              e.emp_name
            FROM {CONTRACTS_TABLE} c
            INNER JOIN {EMPLOYEES_TABLE} e
              ON e.id = c.employee_id AND e.tenant_id = c.tenant_id
            WHERE {where_sql}
            ORDER BY c.created_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        params_list,
    )
    items = [_row_to_contract_dict(m) for m in list_r.mappings().all()]
    return {"items": items, "total": total}


async def get_contract_detail(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    contract_id: str,
) -> dict[str, Any]:
    """查询合同详情。"""
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    cid = _parse_uuid(contract_id, "contract_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    result = await db.execute(
        text(
            f"""
            SELECT
              c.id, c.tenant_id, c.employee_id, c.template_code, c.field_values,
              c.status, c.sign_url, c.signature_hash, c.signed_at, c.expires_at,
              c.terminated_at, c.termination_reason, c.created_at, c.updated_at,
              e.emp_name
            FROM {CONTRACTS_TABLE} c
            INNER JOIN {EMPLOYEES_TABLE} e
              ON e.id = c.employee_id AND e.tenant_id = c.tenant_id
            WHERE c.id = :cid AND c.tenant_id = :tid
            """
        ),
        {"cid": cid, "tid": tid},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ValueError("合同不存在或不属于当前租户")
    d = _row_to_contract_dict(row)
    tc = row["template_code"]
    if tc in CONTRACT_TEMPLATES:
        d["template_name"] = str(CONTRACT_TEMPLATES[tc]["name"])
    return d


async def terminate_contract(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    contract_id: str,
    reason: str,
) -> dict[str, Any]:
    """终止/解除合同。"""
    if not reason.strip():
        raise ValueError("终止原因不能为空")
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    cid = _parse_uuid(contract_id, "contract_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    result = await db.execute(
        text(
            f"""
            UPDATE {CONTRACTS_TABLE}
            SET status = 'terminated',
                terminated_at = NOW(),
                termination_reason = :reason,
                updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid AND status <> 'terminated'
            RETURNING id
            """
        ),
        {"reason": reason.strip(), "cid": cid, "tid": tid},
    )
    if result.first() is None:
        raise ValueError("合同不存在、不属于当前租户或已解除")
    await db.flush()
    logger.info(
        "e_sign.contract_terminated",
        tenant_id=ts,
        contract_id=contract_id,
    )
    return {
        "contract_id": contract_id,
        "status": "terminated",
    }


async def get_expiring_contracts(
    db: AsyncSession,
    tenant_id: str | uuid.UUID,
    days_ahead: int = 60,
) -> list[dict[str, Any]]:
    """查询即将到期的合同。"""
    if days_ahead < 0:
        raise ValueError("days_ahead 须 >= 0")
    tid = _parse_uuid(_tenant_str(tenant_id), "tenant_id")
    ts = _tenant_str(tenant_id)
    await _set_tenant(db, ts)
    result = await db.execute(
        text(
            f"""
            SELECT
              c.id, c.employee_id, c.template_code, c.field_values, e.emp_name
            FROM {CONTRACTS_TABLE} c
            INNER JOIN {EMPLOYEES_TABLE} e
              ON e.id = c.employee_id AND e.tenant_id = c.tenant_id
            WHERE c.tenant_id = :tid
              AND c.status IN ('signed', 'pending_sign')
            """
        ),
        {"tid": tid},
    )
    today = datetime.now(timezone.utc).date()
    end_upper = today + timedelta(days=days_ahead)
    out: list[dict[str, Any]] = []
    for m in result.mappings().all():
        tc = m["template_code"]
        fv = m["field_values"]
        if not isinstance(fv, dict):
            continue
        try:
            end_d = _effective_end_date(str(tc), fv)
        except ValueError:
            logger.warning(
                "e_sign.skip_invalid_end_date",
                contract_id=str(m["id"]),
                template_code=tc,
            )
            continue
        if end_d is None:
            continue
        days_remaining = (end_d - today).days
        if 0 <= days_remaining <= days_ahead:
            tpl_name = str(CONTRACT_TEMPLATES.get(tc, {}).get("name", tc))
            out.append(
                {
                    "contract_id": str(m["id"]),
                    "employee_id": str(m["employee_id"]),
                    "emp_name": m["emp_name"],
                    "template_name": tpl_name,
                    "end_date": end_d.isoformat(),
                    "days_remaining": days_remaining,
                }
            )
    out.sort(key=lambda x: x["days_remaining"])
    return out
