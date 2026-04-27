"""电子签约模块服务 — 合同模板管理 + 签署流程 + 到期提醒 + 统计

表：contract_templates / contract_signing_records (v252 迁移)
合同编号格式：TX-{TYPE}-{YYYYMMDD}-{4位序号}  如 TX-LABOR-20260413-0001
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

TEMPLATES_TABLE = "contract_templates"
SIGNING_TABLE = "contract_signing_records"

CONTRACT_TYPES = {
    "labor": "劳动合同",
    "confidentiality": "保密协议",
    "non_compete": "竞业限制协议",
    "internship": "实习协议",
    "part_time": "非全日制用工协议",
}

STATUS_LABELS = {
    "draft": "草稿",
    "pending_sign": "待签署",
    "employee_signed": "员工已签",
    "company_signed": "企业已签",
    "completed": "已完成",
    "expired": "已过期",
    "terminated": "已终止",
}

# 合同类型编号映射
_TYPE_CODE = {
    "labor": "LABOR",
    "confidentiality": "CONF",
    "non_compete": "NCA",
    "internship": "INTERN",
    "part_time": "PT",
}


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} 不是合法 UUID") from exc


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_dt(v: datetime | date | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    return v.isoformat()


class ESignatureService:
    """电子签约服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id.strip()
        if not self.tenant_id:
            raise ValueError("tenant_id 不能为空")

    async def _ensure_tenant(self) -> None:
        await _set_tenant(self.db, self.tenant_id)

    # ────────────────────── 模板管理 ──────────────────────

    async def create_template(
        self,
        name: str,
        contract_type: str,
        content_html: str = "",
        variables: list[dict[str, Any]] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """创建合同模板"""
        await self._ensure_tenant()
        name = name.strip()
        contract_type = contract_type.strip()
        if not name:
            raise ValueError("模板名称不能为空")
        if contract_type not in CONTRACT_TYPES:
            raise ValueError(f"不支持的合同类型: {contract_type}")

        tid = _parse_uuid(self.tenant_id, "tenant_id")
        tpl_id = uuid.uuid4()
        variables_json = json.dumps(variables or [], ensure_ascii=False)
        cb = _parse_uuid(created_by, "created_by") if created_by else None

        await self.db.execute(
            text(f"""
                INSERT INTO {TEMPLATES_TABLE}
                    (id, tenant_id, template_name, contract_type, content_html,
                     variables, is_active, version, created_by)
                VALUES
                    (:id, :tid, :name, :ctype, :html,
                     CAST(:vars AS jsonb), TRUE, 1, :created_by)
            """),
            {
                "id": tpl_id,
                "tid": tid,
                "name": name,
                "ctype": contract_type,
                "html": content_html,
                "vars": variables_json,
                "created_by": cb,
            },
        )
        await self.db.flush()
        logger.info("e_signature.template_created", tenant_id=self.tenant_id, template_id=str(tpl_id))
        return {
            "id": str(tpl_id),
            "template_name": name,
            "contract_type": contract_type,
            "contract_type_label": CONTRACT_TYPES[contract_type],
            "version": 1,
        }

    async def list_templates(
        self,
        contract_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """列出合同模板（分页）"""
        await self._ensure_tenant()
        if page < 1:
            raise ValueError("page 须 >= 1")
        if size < 1 or size > 100:
            raise ValueError("size 须在 1-100 之间")
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tid": tid}
        if contract_type:
            conditions.append("contract_type = :ctype")
            params["ctype"] = contract_type
        where = " AND ".join(conditions)

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM {TEMPLATES_TABLE} WHERE {where}"),
            params,
        )
        total = int(count_result.scalar_one())

        offset = (page - 1) * size
        params_list = {**params, "lim": size, "off": offset}
        result = await self.db.execute(
            text(f"""
                SELECT id, template_name, contract_type, content_html,
                       variables, is_active, version, created_by,
                       created_at, updated_at
                FROM {TEMPLATES_TABLE}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :lim OFFSET :off
            """),
            params_list,
        )
        items = []
        for row in result.mappings().all():
            items.append(
                {
                    "id": str(row["id"]),
                    "template_name": row["template_name"],
                    "contract_type": row["contract_type"],
                    "contract_type_label": CONTRACT_TYPES.get(row["contract_type"], row["contract_type"]),
                    "content_html": row["content_html"],
                    "variables": row["variables"],
                    "is_active": row["is_active"],
                    "version": row["version"],
                    "created_by": str(row["created_by"]) if row["created_by"] else None,
                    "created_at": _serialize_dt(row["created_at"]),
                    "updated_at": _serialize_dt(row["updated_at"]),
                }
            )
        return {"items": items, "total": total}

    async def get_template(self, template_id: str) -> dict[str, Any]:
        """获取模板详情"""
        await self._ensure_tenant()
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        tpl_id = _parse_uuid(template_id, "template_id")
        result = await self.db.execute(
            text(f"""
                SELECT id, template_name, contract_type, content_html,
                       variables, is_active, version, created_by,
                       created_at, updated_at
                FROM {TEMPLATES_TABLE}
                WHERE id = :tpl_id AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"tpl_id": tpl_id, "tid": tid},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("模板不存在或不属于当前租户")
        return {
            "id": str(row["id"]),
            "template_name": row["template_name"],
            "contract_type": row["contract_type"],
            "contract_type_label": CONTRACT_TYPES.get(row["contract_type"], row["contract_type"]),
            "content_html": row["content_html"],
            "variables": row["variables"],
            "is_active": row["is_active"],
            "version": row["version"],
            "created_by": str(row["created_by"]) if row["created_by"] else None,
            "created_at": _serialize_dt(row["created_at"]),
            "updated_at": _serialize_dt(row["updated_at"]),
        }

    async def update_template(self, template_id: str, **kwargs: Any) -> dict[str, Any]:
        """更新合同模板"""
        await self._ensure_tenant()
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        tpl_id = _parse_uuid(template_id, "template_id")

        set_clauses: list[str] = ["updated_at = NOW()", "version = version + 1"]
        params: dict[str, Any] = {"tpl_id": tpl_id, "tid": tid}

        if "template_name" in kwargs:
            set_clauses.append("template_name = :name")
            params["name"] = kwargs["template_name"]
        if "contract_type" in kwargs:
            if kwargs["contract_type"] not in CONTRACT_TYPES:
                raise ValueError(f"不支持的合同类型: {kwargs['contract_type']}")
            set_clauses.append("contract_type = :ctype")
            params["ctype"] = kwargs["contract_type"]
        if "content_html" in kwargs:
            set_clauses.append("content_html = :html")
            params["html"] = kwargs["content_html"]
        if "variables" in kwargs:
            set_clauses.append("variables = CAST(:vars AS jsonb)")
            params["vars"] = json.dumps(kwargs["variables"], ensure_ascii=False)
        if "is_active" in kwargs:
            set_clauses.append("is_active = :active")
            params["active"] = kwargs["is_active"]

        set_sql = ", ".join(set_clauses)
        result = await self.db.execute(
            text(f"""
                UPDATE {TEMPLATES_TABLE}
                SET {set_sql}
                WHERE id = :tpl_id AND tenant_id = :tid AND is_deleted = FALSE
                RETURNING id, template_name, contract_type, version
            """),
            params,
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("模板不存在或不属于当前租户")
        await self.db.flush()
        logger.info("e_signature.template_updated", tenant_id=self.tenant_id, template_id=template_id)
        return {
            "id": str(row["id"]),
            "template_name": row["template_name"],
            "contract_type": row["contract_type"],
            "version": row["version"],
        }

    # ────────────────────── 签署流程 ──────────────────────

    def _generate_contract_no(self, contract_type: str) -> str:
        """格式: TX-{TYPE}-{YYYYMMDD}-{4位序号}"""
        now = datetime.now(timezone.utc)
        type_code = _TYPE_CODE.get(contract_type, contract_type.upper()[:6])
        date_str = now.strftime("%Y%m%d")
        # 用uuid尾部4位做序号，保证唯一
        seq = uuid.uuid4().hex[-4:].upper()
        return f"TX-{type_code}-{date_str}-{seq}"

    async def initiate_signing(
        self,
        template_id: str,
        employee_id: str,
        start_date: str,
        end_date: str,
        variables_filled: dict[str, Any] | None = None,
        store_id: str | None = None,
    ) -> dict[str, Any]:
        """发起签署，创建签署记录，状态=pending_sign"""
        await self._ensure_tenant()

        # 日期校验
        from datetime import date as _date

        parsed_start = _date.fromisoformat(start_date)
        parsed_end = _date.fromisoformat(end_date)
        if parsed_end < parsed_start:
            raise ValueError("合同结束日期不能早于开始日期")

        tid = _parse_uuid(self.tenant_id, "tenant_id")
        tpl_id = _parse_uuid(template_id, "template_id")
        eid = _parse_uuid(employee_id, "employee_id")
        sid = _parse_uuid(store_id, "store_id") if store_id else None

        # 获取模板
        tpl_result = await self.db.execute(
            text(f"""
                SELECT template_name, contract_type, content_html, variables
                FROM {TEMPLATES_TABLE}
                WHERE id = :tpl_id AND tenant_id = :tid AND is_deleted = FALSE AND is_active = TRUE
            """),
            {"tpl_id": tpl_id, "tid": tid},
        )
        tpl = tpl_result.mappings().one_or_none()
        if tpl is None:
            raise ValueError("模板不存在、已停用或不属于当前租户")

        # 查员工姓名
        emp_result = await self.db.execute(
            text("""
                SELECT emp_name FROM employees
                WHERE id = :eid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"eid": eid, "tid": tid},
        )
        emp_row = emp_result.mappings().one_or_none()
        employee_name = emp_row["emp_name"] if emp_row else ""

        # 生成合同编号
        contract_no = self._generate_contract_no(tpl["contract_type"])

        # 渲染合同内容快照
        variables_filled = variables_filled or {}
        content_snapshot = tpl["content_html"] or ""
        for key, val in variables_filled.items():
            content_snapshot = content_snapshot.replace(f"{{{{{key}}}}}", str(val))

        record_id = uuid.uuid4()
        await self.db.execute(
            text(f"""
                INSERT INTO {SIGNING_TABLE}
                    (id, tenant_id, template_id, contract_type, employee_id,
                     employee_name, store_id, contract_no, start_date, end_date,
                     status, content_snapshot, variables_filled)
                VALUES
                    (:id, :tid, :tpl_id, :ctype, :eid,
                     :emp_name, :sid, :cno, :sd, :ed,
                     'pending_sign', :snapshot, CAST(:vars AS jsonb))
            """),
            {
                "id": record_id,
                "tid": tid,
                "tpl_id": tpl_id,
                "ctype": tpl["contract_type"],
                "eid": eid,
                "emp_name": employee_name,
                "sid": sid,
                "cno": contract_no,
                "sd": start_date,
                "ed": end_date,
                "snapshot": content_snapshot,
                "vars": json.dumps(variables_filled, ensure_ascii=False),
            },
        )
        await self.db.flush()
        logger.info(
            "e_signature.signing_initiated",
            tenant_id=self.tenant_id,
            record_id=str(record_id),
            contract_no=contract_no,
        )
        return {
            "id": str(record_id),
            "contract_no": contract_no,
            "status": "pending_sign",
            "employee_name": employee_name,
        }

    async def employee_sign(self, record_id: str) -> dict[str, Any]:
        """员工签署，状态→employee_signed"""
        await self._ensure_tenant()
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        rid = _parse_uuid(record_id, "record_id")
        result = await self.db.execute(
            text(f"""
                UPDATE {SIGNING_TABLE}
                SET status = 'employee_signed',
                    signed_at = NOW(),
                    updated_at = NOW()
                WHERE id = :rid AND tenant_id = :tid
                  AND status = 'pending_sign' AND is_deleted = FALSE
                RETURNING id, contract_no, signed_at
            """),
            {"rid": rid, "tid": tid},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("签署记录不存在、状态不正确或不属于当前租户")
        await self.db.flush()
        logger.info("e_signature.employee_signed", tenant_id=self.tenant_id, record_id=record_id)
        return {
            "id": str(row["id"]),
            "contract_no": row["contract_no"],
            "status": "employee_signed",
            "signed_at": _serialize_dt(row["signed_at"]),
        }

    async def company_sign(self, record_id: str, signer_id: str) -> dict[str, Any]:
        """企业盖章，状态→completed"""
        await self._ensure_tenant()
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        rid = _parse_uuid(record_id, "record_id")
        suid = _parse_uuid(signer_id, "signer_id")
        result = await self.db.execute(
            text(f"""
                UPDATE {SIGNING_TABLE}
                SET status = 'completed',
                    company_signed_at = NOW(),
                    company_signer_id = :suid,
                    updated_at = NOW()
                WHERE id = :rid AND tenant_id = :tid
                  AND status = 'employee_signed' AND is_deleted = FALSE
                RETURNING id, contract_no, company_signed_at
            """),
            {"rid": rid, "tid": tid, "suid": suid},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("签署记录不存在、状态不正确或不属于当前租户")
        await self.db.flush()
        logger.info("e_signature.company_signed", tenant_id=self.tenant_id, record_id=record_id)
        return {
            "id": str(row["id"]),
            "contract_no": row["contract_no"],
            "status": "completed",
            "company_signed_at": _serialize_dt(row["company_signed_at"]),
        }

    async def terminate_contract(self, record_id: str, reason: str) -> dict[str, Any]:
        """终止合同"""
        await self._ensure_tenant()
        reason = reason.strip()
        if not reason:
            raise ValueError("终止原因不能为空")
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        rid = _parse_uuid(record_id, "record_id")
        reason_json = json.dumps(reason, ensure_ascii=False)
        result = await self.db.execute(
            text(f"""
                UPDATE {SIGNING_TABLE}
                SET status = 'terminated',
                    metadata = jsonb_set(COALESCE(metadata, '{{}}'), '{{terminate_reason}}', :reason_json::jsonb),
                    updated_at = NOW()
                WHERE id = :rid AND tenant_id = :tid
                  AND status IN ('pending_sign', 'employee_signed', 'completed')
                  AND is_deleted = FALSE
                RETURNING id, contract_no
            """),
            {"rid": rid, "tid": tid, "reason_json": reason_json},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("签署记录不存在、状态不允许终止或不属于当前租户")
        await self.db.flush()
        logger.info("e_signature.contract_terminated", tenant_id=self.tenant_id, record_id=record_id)
        return {
            "id": str(row["id"]),
            "contract_no": row["contract_no"],
            "status": "terminated",
        }

    # ────────────────────── 查询 ──────────────────────────

    async def list_signing_records(
        self,
        employee_id: str | None = None,
        status: str | None = None,
        contract_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """签署记录列表"""
        await self._ensure_tenant()
        if page < 1:
            raise ValueError("page 须 >= 1")
        if size < 1 or size > 100:
            raise ValueError("size 须在 1-100 之间")
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tid": tid}
        if employee_id:
            conditions.append("employee_id = :eid")
            params["eid"] = _parse_uuid(employee_id, "employee_id")
        if status:
            conditions.append("status = :st")
            params["st"] = status
        if contract_type:
            conditions.append("contract_type = :ctype")
            params["ctype"] = contract_type
        where = " AND ".join(conditions)

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM {SIGNING_TABLE} WHERE {where}"),
            params,
        )
        total = int(count_result.scalar_one())

        offset = (page - 1) * size
        params_list = {**params, "lim": size, "off": offset}
        result = await self.db.execute(
            text(f"""
                SELECT id, template_id, contract_type, employee_id, employee_name,
                       store_id, contract_no, start_date, end_date, status,
                       signed_at, company_signed_at, company_signer_id,
                       expire_remind_days, created_at, updated_at
                FROM {SIGNING_TABLE}
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params_list,
        )
        items = []
        for row in result.mappings().all():
            items.append(self._map_signing_record(row))
        return {"items": items, "total": total}

    async def get_signing_detail(self, record_id: str) -> dict[str, Any]:
        """签署记录详情"""
        await self._ensure_tenant()
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        rid = _parse_uuid(record_id, "record_id")
        result = await self.db.execute(
            text(f"""
                SELECT id, template_id, contract_type, employee_id, employee_name,
                       store_id, contract_no, start_date, end_date, status,
                       signed_at, company_signed_at, company_signer_id,
                       content_snapshot, variables_filled, e_sign_doc_id,
                       metadata, expire_remind_days, created_at, updated_at
                FROM {SIGNING_TABLE}
                WHERE id = :rid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"rid": rid, "tid": tid},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise ValueError("签署记录不存在或不属于当前租户")
        record = self._map_signing_record(row)
        record["content_snapshot"] = row.get("content_snapshot")
        record["variables_filled"] = row.get("variables_filled")
        record["e_sign_doc_id"] = row.get("e_sign_doc_id")
        record["metadata"] = row.get("metadata")
        return record

    # ────────────────────── 到期预警 ──────────────────────

    async def scan_expiring_contracts(self, days_threshold: int = 30) -> list[dict[str, Any]]:
        """扫描即将到期的合同"""
        await self._ensure_tenant()
        if days_threshold < 0:
            raise ValueError("days_threshold 须 >= 0")
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        today = date.today()
        deadline = today + timedelta(days=days_threshold)
        result = await self.db.execute(
            text(f"""
                SELECT id, employee_id, employee_name, contract_no,
                       contract_type, store_id, start_date, end_date,
                       expire_remind_days
                FROM {SIGNING_TABLE}
                WHERE tenant_id = :tid
                  AND status = 'completed'
                  AND is_deleted = FALSE
                  AND end_date IS NOT NULL
                  AND end_date >= :today
                  AND end_date <= :deadline
                ORDER BY end_date ASC
            """),
            {"tid": tid, "today": today, "deadline": deadline},
        )
        items = []
        for row in result.mappings().all():
            end_d = row["end_date"]
            days_remaining = (end_d - today).days if isinstance(end_d, date) else 0
            items.append(
                {
                    "id": str(row["id"]),
                    "employee_id": str(row["employee_id"]),
                    "employee_name": row["employee_name"],
                    "contract_no": row["contract_no"],
                    "contract_type": row["contract_type"],
                    "contract_type_label": CONTRACT_TYPES.get(row["contract_type"], row["contract_type"]),
                    "store_id": str(row["store_id"]) if row["store_id"] else None,
                    "start_date": _serialize_dt(row["start_date"]),
                    "end_date": _serialize_dt(end_d),
                    "days_remaining": days_remaining,
                }
            )
        return items

    # ────────────────────── 统计 ──────────────────────────

    async def get_contract_stats(self) -> dict[str, Any]:
        """合同统计概览"""
        await self._ensure_tenant()
        tid = _parse_uuid(self.tenant_id, "tenant_id")
        result = await self.db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status IN ('draft', 'pending_sign', 'employee_signed')) AS pending,
                    COUNT(*) FILTER (WHERE status = 'terminated') AS terminated,
                    COUNT(*) FILTER (WHERE status = 'expired') AS expired,
                    COUNT(*) FILTER (
                        WHERE status = 'completed'
                          AND end_date IS NOT NULL
                          AND end_date <= CURRENT_DATE + INTERVAL '30 days'
                          AND end_date >= CURRENT_DATE
                    ) AS expiring_30d
                FROM {SIGNING_TABLE}
                WHERE tenant_id = :tid AND is_deleted = FALSE
            """),
            {"tid": tid},
        )
        row = result.mappings().one()
        return {
            "total": int(row["total"]),
            "completed": int(row["completed"]),
            "pending": int(row["pending"]),
            "terminated": int(row["terminated"]),
            "expired": int(row["expired"]),
            "expiring_30d": int(row["expiring_30d"]),
        }

    # ────────────────────── 内部方法 ──────────────────────

    @staticmethod
    def _map_signing_record(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "template_id": str(row["template_id"]),
            "employee_id": str(row["employee_id"]),
            "employee_name": row["employee_name"],
            "store_id": str(row["store_id"]) if row.get("store_id") else None,
            "contract_no": row["contract_no"],
            "contract_type": row["contract_type"],
            "contract_type_label": CONTRACT_TYPES.get(row["contract_type"], row["contract_type"]),
            "status": row["status"],
            "status_label": STATUS_LABELS.get(row["status"], row["status"]),
            "signed_at": _serialize_dt(row.get("signed_at")),
            "company_signed_at": _serialize_dt(row.get("company_signed_at")),
            "company_signer_id": str(row["company_signer_id"]) if row.get("company_signer_id") else None,
            "start_date": _serialize_dt(row.get("start_date")),
            "end_date": _serialize_dt(row.get("end_date")),
            "expire_remind_days": row.get("expire_remind_days", 30),
            "created_at": _serialize_dt(row.get("created_at")),
            "updated_at": _serialize_dt(row.get("updated_at")),
        }
