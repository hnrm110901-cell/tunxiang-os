"""
GDPR 合规服务

- 同意管理：grant / revoke
- SAR：create_access_request / export / delete / anonymize
- 删除原则：假名化 + 保留法定必须字段（工资/税务/劳动合同等）
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.employee import Employee
from src.models.gdpr import DataAccessRequest, DataConsentRecord

logger = logging.getLogger(__name__)

# 法定必须保留字段（删除时仅假名化，不物理删除）
LEGAL_RETAINED_FIELDS = {
    "id",  # 员工 ID 本身
    "store_id",
    "hire_date",
    "first_work_date",
    "regular_date",
    "seniority_months",
    "employment_type",
    "employment_status",
    "daily_wage_standard_fen",
    "created_at",
    "updated_at",
    # 工资/税务/合同数据通过外键表保留（审计 7 年）
}


class GDPRService:
    """GDPR 合规操作服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── 同意管理 ────────────────────────────────
    async def grant_consent(
        self,
        employee_id: str,
        consent_type: str,
        legal_basis: str = "consent",
        notes: Optional[str] = None,
    ) -> DataConsentRecord:
        record = DataConsentRecord(
            employee_id=employee_id,
            consent_type=consent_type,
            granted=True,
            granted_at=datetime.utcnow(),
            legal_basis=legal_basis,
            notes=notes,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def revoke_consent(
        self, employee_id: str, consent_type: str, reason: Optional[str] = None
    ) -> DataConsentRecord:
        record = DataConsentRecord(
            employee_id=employee_id,
            consent_type=consent_type,
            granted=False,
            revoked_at=datetime.utcnow(),
            legal_basis="consent",
            notes=reason,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_my_consents(self, employee_id: str) -> list[DataConsentRecord]:
        stmt = (
            select(DataConsentRecord)
            .where(DataConsentRecord.employee_id == employee_id)
            .order_by(DataConsentRecord.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ── SAR 请求 ───────────────────────────────
    async def create_access_request(
        self, employee_id: str, request_type: str
    ) -> DataAccessRequest:
        if request_type not in {"access", "export", "delete", "correct"}:
            raise ValueError(f"Invalid request_type: {request_type}")
        req = DataAccessRequest(
            employee_id=employee_id,
            request_type=request_type,
            status="pending",
            requested_at=datetime.utcnow(),
        )
        self.session.add(req)
        await self.session.flush()
        return req

    # ── 数据导出 ────────────────────────────────
    async def export_personal_data(self, employee_id: str) -> bytes:
        """
        导出员工全部个人数据为 ZIP（含 CSV 基础信息 + JSON 完整快照）。
        返回 ZIP 的 bytes，调用方负责上传 OSS 并更新 export_file_url。
        """
        emp = await self.session.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"Employee {employee_id} not found")

        emp_dict = {
            c.name: _safe_serialize(getattr(emp, c.name))
            for c in emp.__table__.columns
        }

        # 同意记录
        consents = await self.get_my_consents(employee_id)
        consents_list = [
            {c.name: _safe_serialize(getattr(r, c.name)) for c in r.__table__.columns}
            for r in consents
        ]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # CSV 基础信息
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow(["field", "value"])
            for k, v in emp_dict.items():
                writer.writerow([k, v])
            zf.writestr("employee_basic.csv", csv_buf.getvalue())

            # JSON 完整快照
            zf.writestr(
                "employee_full.json",
                json.dumps(
                    {"employee": emp_dict, "consents": consents_list},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            zf.writestr(
                "README.txt",
                f"个人数据导出 for employee_id={employee_id}\n"
                f"生成时间: {datetime.utcnow().isoformat()}Z\n"
                f"依据: GDPR Art.15 / Art.20 数据可携带权\n",
            )

        return buf.getvalue()

    # ── 数据删除（假名化） ───────────────────────
    async def delete_personal_data(
        self, employee_id: str, retain_legal_required: bool = True
    ) -> dict:
        """
        GDPR Art.17 被遗忘权。
        我们做假名化而非物理删除，以保留法定审计数据（工资/税务 7 年）。
        """
        emp = await self.session.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"Employee {employee_id} not found")

        pseudonym = hashlib.sha256(
            f"{employee_id}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16]

        anonymized_fields: list[str] = []
        for col in emp.__table__.columns:
            name = col.name
            if retain_legal_required and name in LEGAL_RETAINED_FIELDS:
                continue
            # PII 字段 → 假名化
            if name in {
                "name",
                "phone",
                "email",
                "id_card_no",
                "bank_account",
                "bank_branch",
                "emergency_contact",
                "emergency_phone",
                "hukou_location",
                "wechat_userid",
                "dingtalk_userid",
                "health_cert_attachment",
            }:
                setattr(emp, name, f"ANON-{pseudonym}" if col.type.python_type is str else None)
                anonymized_fields.append(name)

        emp.is_active = False
        await self.session.flush()

        return {
            "employee_id": employee_id,
            "pseudonym": pseudonym,
            "anonymized_fields": anonymized_fields,
            "retained_legal_fields": sorted(LEGAL_RETAINED_FIELDS),
            "deleted_at": datetime.utcnow().isoformat() + "Z",
        }

    async def anonymize_historical_data(self, employee_id: str) -> dict:
        """历史数据假名化（与 delete 同义的简化入口）"""
        return await self.delete_personal_data(employee_id, retain_legal_required=True)


def _safe_serialize(v):
    if isinstance(v, datetime):
        return v.isoformat() + "Z"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    return str(v)
