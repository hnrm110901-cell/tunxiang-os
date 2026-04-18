"""
电子签约模型 — Task 2

完整模块：
  - SignatureTemplate: 合同模板（含占位符）
  - SignatureSeal: 电子印章（主体、合同、财务章）
  - SignatureEnvelope: 一次签署任务（信封），承载 1 份最终合同 + 多个签署人
  - SignatureRecord: 单个签署人的签署记录（签名图、IP、设备）
  - SignatureAuditLog: 信封全生命周期审计日志（不可篡改链条）

状态机：
  draft → sent → partially_signed → completed
                     ↓                    ↑
                  rejected / expired    所有签署人 status=signed
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID

from .base import Base, TimestampMixin


class TemplateCategory(str, enum.Enum):
    """模板类别"""

    LABOR_CONTRACT = "labor_contract"  # 劳动合同
    PROBATION = "probation"  # 试用期协议
    TRANSFER = "transfer"  # 调岗协议
    RESIGNATION = "resignation"  # 离职确认
    NDA = "nda"  # 保密协议
    FRANCHISE_AGREEMENT = "franchise_agreement"  # 加盟协议
    SUPPLIER = "supplier"  # 供应商合同
    TRAINING_CONFIRM = "training_confirm"  # 培训完成确认
    OTHER = "other"


class SealType(str, enum.Enum):
    OFFICIAL = "official"  # 公章
    CONTRACT = "contract"  # 合同章
    FINANCE = "finance"  # 财务章
    LEGAL_REP = "legal_rep"  # 法人章


class EnvelopeStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PARTIALLY_SIGNED = "partially_signed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignerRole(str, enum.Enum):
    EMPLOYEE = "employee"
    HR = "hr"
    LEGAL_REP = "legal_rep"  # 法定代表人
    WITNESS = "witness"  # 见证人
    PARTY_A = "party_a"  # 甲方
    PARTY_B = "party_b"  # 乙方


class SignRecordStatus(str, enum.Enum):
    PENDING = "pending"
    SIGNED = "signed"
    REJECTED = "rejected"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    SEND = "send"
    VIEW = "view"
    SIGN = "sign"
    REJECT = "reject"
    EXPIRE = "expire"
    COMPLETE = "complete"
    VOID = "void"


class SignatureTemplate(Base, TimestampMixin):
    """合同模板"""

    __tablename__ = "signature_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(
        SAEnum(TemplateCategory, name="template_category_enum"),
        nullable=False,
        default=TemplateCategory.LABOR_CONTRACT,
    )

    content_template_url = Column(String(500), nullable=True)  # 模板文件 URL
    content_text = Column(Text, nullable=True)  # 或行内 Markdown/HTML
    placeholders_json = Column(JSON, nullable=True)  # [{"key": "employee_name", "label": "员工姓名"}]
    required_fields_json = Column(JSON, nullable=True)  # 必填字段校验

    legal_entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # 所属法人
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True, index=True)

    remark = Column(Text, nullable=True)


class SignatureSeal(Base, TimestampMixin):
    """电子印章"""

    __tablename__ = "signature_seals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    seal_name = Column(String(200), nullable=False)
    seal_type = Column(
        SAEnum(SealType, name="seal_type_enum"),
        nullable=False,
        default=SealType.CONTRACT,
    )
    seal_image_url = Column(String(500), nullable=True)  # 印章图（PNG，透明底）
    authorized_users_json = Column(JSON, nullable=True)  # 有权使用此章的用户ID列表

    is_active = Column(Boolean, default=True, index=True)
    expires_at = Column(DateTime, nullable=True)

    remark = Column(Text, nullable=True)


class SignatureEnvelope(Base, TimestampMixin):
    """签署信封（一次签署任务）"""

    __tablename__ = "signature_envelopes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envelope_no = Column(String(50), nullable=False, unique=True, index=True)

    template_id = Column(UUID(as_uuid=True), ForeignKey("signature_templates.id"), nullable=True)
    legal_entity_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    subject = Column(String(500), nullable=True)  # 信封主题/标题
    initiator_id = Column(String(50), nullable=True)  # 发起人（通常 HR）

    signer_info_json = Column(JSON, nullable=True)
    # [{"signer_id": "...", "role": "employee", "name": "张三", "phone": "..."}]
    placeholder_values_json = Column(JSON, nullable=True)  # 填充后占位符值
    document_url = Column(String(500), nullable=True)  # 生成的待签 PDF
    signed_document_url = Column(String(500), nullable=True)  # 完成后终稿 PDF

    envelope_status = Column(
        SAEnum(EnvelopeStatus, name="envelope_status_enum"),
        nullable=False,
        default=EnvelopeStatus.DRAFT,
        index=True,
    )

    sent_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # 业务关联（可选）—— 用于"合同到期→续签信封"回链
    related_contract_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    related_entity_type = Column(String(50), nullable=True)  # employee_contract / certificate / ...

    remark = Column(Text, nullable=True)


class SignatureRecord(Base, TimestampMixin):
    """单签署人记录"""

    __tablename__ = "signature_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(as_uuid=True), ForeignKey("signature_envelopes.id"), nullable=False, index=True)
    signer_id = Column(String(50), nullable=False, index=True)
    signer_name = Column(String(100), nullable=True)
    signer_role = Column(
        SAEnum(SignerRole, name="signer_role_enum"),
        nullable=False,
        default=SignerRole.EMPLOYEE,
    )
    sign_order = Column(Integer, default=1)  # 签署顺序

    status = Column(
        SAEnum(SignRecordStatus, name="sign_record_status_enum"),
        nullable=False,
        default=SignRecordStatus.PENDING,
        index=True,
    )

    signature_image_url = Column(String(500), nullable=True)  # 手写签名图 URL
    seal_id = Column(UUID(as_uuid=True), nullable=True)  # 若用印章签署
    signed_at = Column(DateTime, nullable=True)
    reject_reason = Column(Text, nullable=True)

    ip_address = Column(String(50), nullable=True)
    device_info = Column(String(200), nullable=True)


class SignatureAuditLog(Base, TimestampMixin):
    """审计日志（不可修改、不可删除 —— 应用层约束）"""

    __tablename__ = "signature_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(as_uuid=True), ForeignKey("signature_envelopes.id"), nullable=False, index=True)
    action = Column(
        SAEnum(AuditAction, name="signature_audit_action_enum"),
        nullable=False,
        index=True,
    )
    actor_id = Column(String(50), nullable=True)
    occurred_at = Column(DateTime, nullable=False, index=True)
    details_json = Column(JSON, nullable=True)
    ip_address = Column(String(50), nullable=True)
