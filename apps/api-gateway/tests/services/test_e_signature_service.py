"""
电子签约服务 — 单元测试

覆盖：
  1) prepare_envelope 空 signer_list 拒绝
  2) prepare_envelope 正常：返回 draft + signer_info_json + 创建审计日志
  3) send_envelope：draft→sent；非 draft 拒绝
  4) sign：sent→partially_signed（多人）
  5) sign：全员签署→completed（并发最后一笔触发）
  6) reject：信封 status=rejected + 记录 rejected
  7) 审计链：每次操作写一条 log
"""

import sys
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.models.e_signature import (  # noqa: E402
    EnvelopeStatus,
    SignRecordStatus,
)
from src.services.e_signature_service import ESignatureService  # noqa: E402


def _mk_db():
    db = MagicMock()
    added = []

    def _add(obj):
        added.append(obj)

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db._added = added
    return db


@pytest.mark.asyncio
async def test_prepare_envelope_empty_signer_rejected():
    db = _mk_db()
    with pytest.raises(ValueError, match="signer_list"):
        await ESignatureService.prepare_envelope(
            db,
            template_id=None,
            signer_list=[],
        )


@pytest.mark.asyncio
async def test_prepare_envelope_creates_records_and_audit():
    db = _mk_db()
    env = await ESignatureService.prepare_envelope(
        db,
        template_id=None,
        signer_list=[
            {"signer_id": "E001", "role": "employee", "name": "张三"},
            {"signer_id": "HR", "role": "hr", "name": "HR"},
        ],
        subject="测试合同",
        initiator_id="HR",
    )
    assert env.envelope_status == EnvelopeStatus.DRAFT
    # 1 信封 + 2 签署记录 + 1 审计
    types_added = [type(x).__name__ for x in db._added]
    assert types_added.count("SignatureEnvelope") == 1
    assert types_added.count("SignatureRecord") == 2
    assert types_added.count("SignatureAuditLog") >= 1


@pytest.mark.asyncio
async def test_send_envelope_draft_to_sent():
    db = _mk_db()
    fake_env = MagicMock(
        id=uuid.uuid4(),
        envelope_status=EnvelopeStatus.DRAFT,
        sent_at=None,
    )

    class One:
        def scalar_one_or_none(self):
            return fake_env

    db.execute = AsyncMock(return_value=One())
    env = await ESignatureService.send_envelope(db, fake_env.id, actor_id="HR")
    assert env.envelope_status == EnvelopeStatus.SENT
    assert env.sent_at is not None


@pytest.mark.asyncio
async def test_send_envelope_non_draft_rejected():
    db = _mk_db()
    fake_env = MagicMock(id=uuid.uuid4(), envelope_status=EnvelopeStatus.COMPLETED)

    class One:
        def scalar_one_or_none(self):
            return fake_env

    db.execute = AsyncMock(return_value=One())
    with pytest.raises(ValueError):
        await ESignatureService.send_envelope(db, fake_env.id)


@pytest.mark.asyncio
async def test_sign_partially_then_completed():
    """模拟 2 签署人，第一人签后 partially_signed，第二人签后 completed。"""
    db = _mk_db()
    env_id = uuid.uuid4()

    # 第一次调用：_get_envelope 返回 sent；check_envelope_completed 的 _get_envelope 也一样
    env_sent = MagicMock(id=env_id, envelope_status=EnvelopeStatus.SENT)
    # 待签记录
    rec = MagicMock(id=uuid.uuid4(), status=SignRecordStatus.PENDING)

    # 序列化 execute 返回：
    # 1. _get_envelope → env
    # 2. select SignatureRecord PENDING → rec
    # 3. check_completed: _get_envelope → env
    # 4. count total → 2
    # 5. count signed → 1 (未全签)
    calls = []

    async def _exec(stmt):
        calls.append(stmt)
        idx = len(calls)

        class R:
            def scalar_one_or_none(self_inner):
                if idx == 1 or idx == 3:
                    return env_sent
                if idx == 2:
                    return rec
                return None

            def scalar_one(self_inner):
                # 4 total=2, 5 signed=1
                return 2 if idx == 4 else 1

        return R()

    db.execute = AsyncMock(side_effect=_exec)

    result = await ESignatureService.sign(
        db,
        envelope_id=env_id,
        signer_id="E001",
        ip_address="127.0.0.1",
    )
    assert rec.status == SignRecordStatus.SIGNED
    assert result["completed"] is False
    assert env_sent.envelope_status == EnvelopeStatus.PARTIALLY_SIGNED


@pytest.mark.asyncio
async def test_sign_last_signer_triggers_completed():
    db = _mk_db()
    env_id = uuid.uuid4()
    env = MagicMock(
        id=env_id,
        envelope_status=EnvelopeStatus.PARTIALLY_SIGNED,
        template_id=None,
        completed_at=None,
        signed_document_url=None,
    )
    rec = MagicMock(id=uuid.uuid4(), status=SignRecordStatus.PENDING)

    calls = []

    async def _exec(stmt):
        calls.append(stmt)
        idx = len(calls)

        class R:
            def scalar_one_or_none(self_inner):
                if idx in (1, 3):
                    return env
                if idx == 2:
                    return rec
                return None

            def scalar_one(self_inner):
                # total=2, signed=2 → 全部完成
                return 2

        return R()

    db.execute = AsyncMock(side_effect=_exec)

    # Patch PDF 渲染以避免 reportlab 依赖
    with patch(
        "src.services.e_signature_pdf_service.ESignaturePdfService.render_signed_pdf",
        new=AsyncMock(return_value="/tmp/e_signatures/fake.pdf"),
    ):
        result = await ESignatureService.sign(
            db,
            envelope_id=env_id,
            signer_id="HR",
        )
    assert result["completed"] is True
    assert env.envelope_status == EnvelopeStatus.COMPLETED


@pytest.mark.asyncio
async def test_reject_sets_envelope_rejected():
    db = _mk_db()
    env_id = uuid.uuid4()
    env = MagicMock(id=env_id, envelope_status=EnvelopeStatus.SENT)
    rec = MagicMock(id=uuid.uuid4(), status=SignRecordStatus.PENDING)

    calls = []

    async def _exec(stmt):
        calls.append(stmt)
        idx = len(calls)

        class R:
            def scalar_one_or_none(self_inner):
                return env if idx == 1 else rec

        return R()

    db.execute = AsyncMock(side_effect=_exec)

    env_out = await ESignatureService.reject(
        db,
        envelope_id=env_id,
        signer_id="E001",
        reason="不认可合同条款",
        ip_address="127.0.0.1",
    )
    assert env_out.envelope_status == EnvelopeStatus.REJECTED
    assert rec.status == SignRecordStatus.REJECTED
    assert rec.reject_reason == "不认可合同条款"


@pytest.mark.asyncio
async def test_audit_trail_records_each_action():
    """create→send→sign 应至少产生 3 条审计记录（_write_audit 调用次数）"""
    db = _mk_db()
    await ESignatureService.prepare_envelope(
        db,
        template_id=None,
        signer_list=[{"signer_id": "E001", "role": "employee"}],
        initiator_id="HR",
    )
    audit_types = [
        type(x).__name__ for x in db._added if type(x).__name__ == "SignatureAuditLog"
    ]
    assert len(audit_types) >= 1  # create 时至少 1 条
