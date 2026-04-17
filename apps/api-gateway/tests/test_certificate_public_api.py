"""
D11 证书公开验证端点测试
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_cert(status: str = "active", expired: bool = False, revoked: bool = False):
    cert = MagicMock()
    cert.id = uuid.uuid4()
    cert.cert_no = "PUB20260401001"
    cert.status = "revoked" if revoked else status
    cert.issued_at = datetime(2026, 1, 1)
    cert.expire_at = (
        datetime.utcnow() - timedelta(days=1)
        if expired
        else datetime.utcnow() + timedelta(days=180)
    )
    cert.employee_id = "E001"
    cert.course_id = uuid.uuid4()
    return cert


async def _fake_session(cert, course_title: str = "消防安全培训", emp_name: str = "张小三"):
    course = MagicMock()
    course.title = course_title
    emp = MagicMock()
    emp.name = emp_name

    results = [cert, course, emp]
    session = MagicMock()

    async def mock_execute(*args, **kwargs):
        m = MagicMock()
        m.scalar_one_or_none.return_value = results.pop(0) if results else None
        return m

    session.execute = AsyncMock(side_effect=mock_execute)
    return session


@pytest.mark.asyncio
async def test_public_verify_valid_certificate():
    """有效证书返回 valid=True 且姓名脱敏。"""
    from src.api.certificate_public import public_verify_certificate

    cert = _make_cert()
    session = await _fake_session(cert)

    resp = await public_verify_certificate(cert.cert_no, db=session)

    assert resp["valid"] is True
    assert resp["cert_no"] == cert.cert_no
    assert resp["holder_name_masked"] == "张*三"
    assert resp["course_name"] == "消防安全培训"
    assert resp["reason"] is None


@pytest.mark.asyncio
async def test_public_verify_expired_certificate():
    """过期证书返回 valid=False, reason=expired。"""
    from src.api.certificate_public import public_verify_certificate

    cert = _make_cert(expired=True)
    session = await _fake_session(cert)

    resp = await public_verify_certificate(cert.cert_no, db=session)
    assert resp["valid"] is False
    assert resp["reason"] == "expired"


@pytest.mark.asyncio
async def test_public_verify_not_found():
    """不存在证书返回 valid=False, reason=not_found。"""
    from src.api.certificate_public import public_verify_certificate

    session = MagicMock()

    async def mock_execute(*args, **kwargs):
        m = MagicMock()
        m.scalar_one_or_none.return_value = None
        return m

    session.execute = AsyncMock(side_effect=mock_execute)

    resp = await public_verify_certificate("NOTEXIST", db=session)
    assert resp["valid"] is False
    assert resp["reason"] == "not_found"
