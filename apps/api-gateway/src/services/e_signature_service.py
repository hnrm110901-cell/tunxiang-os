"""
电子签约服务（Task 2）

状态机：
    draft ──send──▶ sent ──首个签署──▶ partially_signed ──末签署──▶ completed
                      │                          │
                      └──reject─▶ rejected ◀─────┘
                      └──expire─▶ expired

关键不变量：
  - 每个状态变更都必须写 audit log（即使业务失败也要写）
  - signature_records.status = signed 的数量 == 签署人总数 → envelope.status = completed
  - rejected 一次即终止，信封置 rejected
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.e_signature import (
    AuditAction,
    EnvelopeStatus,
    SignatureAuditLog,
    SignatureEnvelope,
    SignatureRecord,
    SignatureSeal,
    SignatureTemplate,
    SignerRole,
    SignRecordStatus,
    TemplateCategory,
)

logger = structlog.get_logger()


class ESignatureService:
    """电子签约核心服务"""

    # ---------------- 审计 ----------------
    @staticmethod
    async def _write_audit(
        session: AsyncSession,
        envelope_id: uuid.UUID,
        action: AuditAction,
        actor_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """统一写审计日志。失败仅记日志，不抛。"""
        try:
            log = SignatureAuditLog(
                id=uuid.uuid4(),
                envelope_id=envelope_id,
                action=action,
                actor_id=actor_id,
                occurred_at=datetime.utcnow(),
                details_json=details or {},
                ip_address=ip_address,
            )
            session.add(log)
            await session.flush()
        except Exception as exc:  # pragma: no cover
            logger.error("e_signature.audit_failed", envelope_id=str(envelope_id), error=str(exc))

    # ---------------- 模板 ----------------
    @staticmethod
    async def create_template(
        session: AsyncSession,
        *,
        code: str,
        name: str,
        category: str,
        content_text: Optional[str] = None,
        content_template_url: Optional[str] = None,
        placeholders: Optional[List[Dict[str, Any]]] = None,
        required_fields: Optional[List[str]] = None,
        legal_entity_id: Optional[uuid.UUID] = None,
    ) -> SignatureTemplate:
        tpl = SignatureTemplate(
            id=uuid.uuid4(),
            code=code,
            name=name,
            category=TemplateCategory(category),
            content_text=content_text,
            content_template_url=content_template_url,
            placeholders_json=placeholders or [],
            required_fields_json=required_fields or [],
            legal_entity_id=legal_entity_id,
        )
        session.add(tpl)
        await session.flush()
        return tpl

    # ---------------- 信封 ----------------
    @staticmethod
    async def prepare_envelope(
        session: AsyncSession,
        *,
        template_id: Optional[uuid.UUID],
        signer_list: List[Dict[str, Any]],
        placeholder_values: Optional[Dict[str, Any]] = None,
        subject: Optional[str] = None,
        initiator_id: Optional[str] = None,
        legal_entity_id: Optional[uuid.UUID] = None,
        expires_in_days: int = 14,
        related_contract_id: Optional[uuid.UUID] = None,
        related_entity_type: Optional[str] = None,
    ) -> SignatureEnvelope:
        """生成信封 + 每个签署人一条 pending 记录，占位符填充后返回。"""
        if not signer_list:
            raise ValueError("signer_list 不能为空")

        envelope_no = f"ENV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        envelope = SignatureEnvelope(
            id=uuid.uuid4(),
            envelope_no=envelope_no,
            template_id=template_id,
            legal_entity_id=legal_entity_id,
            subject=subject,
            initiator_id=initiator_id,
            signer_info_json=signer_list,
            placeholder_values_json=placeholder_values or {},
            envelope_status=EnvelopeStatus.DRAFT,
            expires_at=datetime.utcnow() + timedelta(days=expires_in_days),
            related_contract_id=related_contract_id,
            related_entity_type=related_entity_type,
        )
        session.add(envelope)
        await session.flush()

        # 签署记录
        for idx, s in enumerate(signer_list, start=1):
            rec = SignatureRecord(
                id=uuid.uuid4(),
                envelope_id=envelope.id,
                signer_id=str(s.get("signer_id") or ""),
                signer_name=s.get("name"),
                signer_role=SignerRole(s.get("role", "employee")),
                sign_order=int(s.get("order", idx)),
                status=SignRecordStatus.PENDING,
            )
            session.add(rec)

        await ESignatureService._write_audit(
            session,
            envelope.id,
            AuditAction.CREATE,
            actor_id=initiator_id,
            details={"signer_count": len(signer_list), "envelope_no": envelope_no},
        )
        return envelope

    @staticmethod
    async def send_envelope(
        session: AsyncSession,
        envelope_id: uuid.UUID,
        actor_id: Optional[str] = None,
    ) -> SignatureEnvelope:
        env = await ESignatureService._get_envelope(session, envelope_id)
        if env.envelope_status != EnvelopeStatus.DRAFT:
            await ESignatureService._write_audit(
                session, envelope_id, AuditAction.SEND, actor_id=actor_id,
                details={"ok": False, "reason": f"status={env.envelope_status.value}"},
            )
            raise ValueError(f"只有 draft 状态可发送，当前 {env.envelope_status.value}")
        env.envelope_status = EnvelopeStatus.SENT
        env.sent_at = datetime.utcnow()
        await session.flush()
        await ESignatureService._write_audit(session, envelope_id, AuditAction.SEND, actor_id=actor_id)
        return env

    @staticmethod
    async def sign(
        session: AsyncSession,
        *,
        envelope_id: uuid.UUID,
        signer_id: str,
        signature_image_url: Optional[str] = None,
        signature_image_base64: Optional[str] = None,
        seal_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        device_info: Optional[str] = None,
    ) -> Dict[str, Any]:
        """单签署人签字。返回当前进度 + 是否触发 completed。"""
        env = await ESignatureService._get_envelope(session, envelope_id)
        if env.envelope_status not in (EnvelopeStatus.SENT, EnvelopeStatus.PARTIALLY_SIGNED):
            await ESignatureService._write_audit(
                session, envelope_id, AuditAction.SIGN, actor_id=signer_id,
                details={"ok": False, "reason": f"status={env.envelope_status.value}"},
                ip_address=ip_address,
            )
            raise ValueError(f"信封状态不允许签署：{env.envelope_status.value}")

        # 定位 pending 记录
        rec_res = await session.execute(
            select(SignatureRecord).where(
                and_(
                    SignatureRecord.envelope_id == envelope_id,
                    SignatureRecord.signer_id == signer_id,
                    SignatureRecord.status == SignRecordStatus.PENDING,
                )
            )
        )
        rec = rec_res.scalar_one_or_none()
        if not rec:
            await ESignatureService._write_audit(
                session, envelope_id, AuditAction.SIGN, actor_id=signer_id,
                details={"ok": False, "reason": "no_pending_record"},
                ip_address=ip_address,
            )
            raise ValueError("签署人无待签署记录")

        # 签名图：base64 占位，生产接 OSS
        if signature_image_base64 and not signature_image_url:
            signature_image_url = f"oss://placeholder/signature/{uuid.uuid4().hex}.png"

        rec.status = SignRecordStatus.SIGNED
        rec.signature_image_url = signature_image_url
        rec.seal_id = seal_id
        rec.signed_at = datetime.utcnow()
        rec.ip_address = ip_address
        rec.device_info = device_info
        await session.flush()

        await ESignatureService._write_audit(
            session, envelope_id, AuditAction.SIGN, actor_id=signer_id,
            details={"ok": True, "record_id": str(rec.id)},
            ip_address=ip_address,
        )

        # 检查信封完成
        completed = await ESignatureService.check_envelope_completed(session, envelope_id)

        # 未完成则置 partially_signed
        if not completed and env.envelope_status == EnvelopeStatus.SENT:
            env.envelope_status = EnvelopeStatus.PARTIALLY_SIGNED
            await session.flush()

        return {
            "envelope_id": str(envelope_id),
            "signer_id": signer_id,
            "envelope_status": env.envelope_status.value,
            "completed": completed,
        }

    @staticmethod
    async def check_envelope_completed(
        session: AsyncSession,
        envelope_id: uuid.UUID,
    ) -> bool:
        """若所有签署人 signed 则置 completed。"""
        env = await ESignatureService._get_envelope(session, envelope_id)
        total_q = await session.execute(
            select(func.count(SignatureRecord.id)).where(SignatureRecord.envelope_id == envelope_id)
        )
        signed_q = await session.execute(
            select(func.count(SignatureRecord.id)).where(
                and_(
                    SignatureRecord.envelope_id == envelope_id,
                    SignatureRecord.status == SignRecordStatus.SIGNED,
                )
            )
        )
        total = total_q.scalar_one() or 0
        signed = signed_q.scalar_one() or 0
        if total > 0 and signed == total and env.envelope_status != EnvelopeStatus.COMPLETED:
            env.envelope_status = EnvelopeStatus.COMPLETED
            env.completed_at = datetime.utcnow()
            # 生成终稿 PDF（懒加载避免循环依赖）
            try:
                from src.services.e_signature_pdf_service import ESignaturePdfService

                pdf_url = await ESignaturePdfService.render_signed_pdf(session, envelope_id)
                env.signed_document_url = pdf_url
            except Exception as exc:
                logger.warning("e_signature.pdf_render_failed", envelope_id=str(envelope_id), error=str(exc))
            await session.flush()
            await ESignatureService._write_audit(session, envelope_id, AuditAction.COMPLETE)
            return True
        return signed == total and total > 0

    @staticmethod
    async def reject(
        session: AsyncSession,
        *,
        envelope_id: uuid.UUID,
        signer_id: str,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> SignatureEnvelope:
        env = await ESignatureService._get_envelope(session, envelope_id)
        rec_res = await session.execute(
            select(SignatureRecord).where(
                and_(
                    SignatureRecord.envelope_id == envelope_id,
                    SignatureRecord.signer_id == signer_id,
                    SignatureRecord.status == SignRecordStatus.PENDING,
                )
            )
        )
        rec = rec_res.scalar_one_or_none()
        if rec:
            rec.status = SignRecordStatus.REJECTED
            rec.reject_reason = reason
            rec.ip_address = ip_address

        env.envelope_status = EnvelopeStatus.REJECTED
        await session.flush()
        await ESignatureService._write_audit(
            session, envelope_id, AuditAction.REJECT,
            actor_id=signer_id, details={"reason": reason}, ip_address=ip_address,
        )
        return env

    @staticmethod
    async def list_pending_for_user(
        session: AsyncSession,
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """查用户待签清单（信封状态 sent / partially_signed 且记录 pending）"""
        q = select(SignatureRecord, SignatureEnvelope).join(
            SignatureEnvelope, SignatureEnvelope.id == SignatureRecord.envelope_id
        ).where(
            and_(
                SignatureRecord.signer_id == user_id,
                SignatureRecord.status == SignRecordStatus.PENDING,
                SignatureEnvelope.envelope_status.in_(
                    [EnvelopeStatus.SENT, EnvelopeStatus.PARTIALLY_SIGNED]
                ),
            )
        ).order_by(SignatureEnvelope.sent_at.desc())
        res = await session.execute(q)
        out = []
        for rec, env in res.all():
            out.append({
                "envelope_id": str(env.id),
                "envelope_no": env.envelope_no,
                "subject": env.subject,
                "status": env.envelope_status.value,
                "sent_at": env.sent_at.isoformat() if env.sent_at else None,
                "expires_at": env.expires_at.isoformat() if env.expires_at else None,
                "my_role": rec.signer_role.value,
                "sign_order": rec.sign_order,
            })
        return out

    @staticmethod
    async def list_envelopes(
        session: AsyncSession,
        *,
        role: str = "initiator",
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """我的信封（发起 or 参与签署）"""
        if role == "initiator":
            q = select(SignatureEnvelope).where(SignatureEnvelope.initiator_id == user_id)
            if status:
                q = q.where(SignatureEnvelope.envelope_status == EnvelopeStatus(status))
            q = q.order_by(SignatureEnvelope.created_at.desc()).limit(limit)
            res = await session.execute(q)
            return [ESignatureService._envelope_to_dict(e) for e in res.scalars().all()]
        else:  # signer
            q = select(SignatureEnvelope).join(
                SignatureRecord, SignatureRecord.envelope_id == SignatureEnvelope.id
            ).where(SignatureRecord.signer_id == user_id)
            if status:
                q = q.where(SignatureEnvelope.envelope_status == EnvelopeStatus(status))
            q = q.order_by(SignatureEnvelope.created_at.desc()).limit(limit)
            res = await session.execute(q)
            seen = set()
            out = []
            for e in res.scalars().all():
                if e.id in seen:
                    continue
                seen.add(e.id)
                out.append(ESignatureService._envelope_to_dict(e))
            return out

    @staticmethod
    async def get_audit_trail(
        session: AsyncSession,
        envelope_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        """完整审计链（按时间正序）"""
        q = select(SignatureAuditLog).where(
            SignatureAuditLog.envelope_id == envelope_id
        ).order_by(SignatureAuditLog.occurred_at.asc())
        res = await session.execute(q)
        return [
            {
                "id": str(x.id),
                "action": x.action.value,
                "actor_id": x.actor_id,
                "occurred_at": x.occurred_at.isoformat() if x.occurred_at else None,
                "details": x.details_json or {},
                "ip_address": x.ip_address,
            }
            for x in res.scalars().all()
        ]

    @staticmethod
    async def get_envelope_detail(
        session: AsyncSession,
        envelope_id: uuid.UUID,
    ) -> Dict[str, Any]:
        env = await ESignatureService._get_envelope(session, envelope_id)
        rec_res = await session.execute(
            select(SignatureRecord).where(SignatureRecord.envelope_id == envelope_id)
            .order_by(SignatureRecord.sign_order.asc())
        )
        records = [
            {
                "id": str(r.id),
                "signer_id": r.signer_id,
                "signer_name": r.signer_name,
                "signer_role": r.signer_role.value,
                "sign_order": r.sign_order,
                "status": r.status.value,
                "signed_at": r.signed_at.isoformat() if r.signed_at else None,
                "signature_image_url": r.signature_image_url,
                "reject_reason": r.reject_reason,
            }
            for r in rec_res.scalars().all()
        ]
        data = ESignatureService._envelope_to_dict(env)
        data["records"] = records
        return data

    # ---------------- 印章 ----------------
    @staticmethod
    async def create_seal(
        session: AsyncSession,
        *,
        legal_entity_id: uuid.UUID,
        seal_name: str,
        seal_type: str = "contract",
        seal_image_url: Optional[str] = None,
        authorized_users: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
    ) -> SignatureSeal:
        seal = SignatureSeal(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            seal_name=seal_name,
            seal_type=seal_type,
            seal_image_url=seal_image_url,
            authorized_users_json=authorized_users or [],
            expires_at=expires_at,
        )
        session.add(seal)
        await session.flush()
        return seal

    # ---------------- 私有 ----------------
    @staticmethod
    async def _get_envelope(session: AsyncSession, envelope_id: uuid.UUID) -> SignatureEnvelope:
        res = await session.execute(
            select(SignatureEnvelope).where(SignatureEnvelope.id == envelope_id)
        )
        env = res.scalar_one_or_none()
        if not env:
            raise ValueError(f"信封不存在：{envelope_id}")
        return env

    @staticmethod
    def _envelope_to_dict(e: SignatureEnvelope) -> Dict[str, Any]:
        return {
            "id": str(e.id),
            "envelope_no": e.envelope_no,
            "subject": e.subject,
            "template_id": str(e.template_id) if e.template_id else None,
            "legal_entity_id": str(e.legal_entity_id) if e.legal_entity_id else None,
            "initiator_id": e.initiator_id,
            "envelope_status": e.envelope_status.value if e.envelope_status else None,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            "expires_at": e.expires_at.isoformat() if e.expires_at else None,
            "document_url": e.document_url,
            "signed_document_url": e.signed_document_url,
            "related_contract_id": str(e.related_contract_id) if e.related_contract_id else None,
            "related_entity_type": e.related_entity_type,
        }
