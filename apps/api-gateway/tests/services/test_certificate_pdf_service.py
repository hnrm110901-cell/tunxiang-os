"""
D11 证书 PDF 生成服务测试
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_generate_certificate_pdf_returns_bytes():
    """生成 PDF 成功：返回非空 bytes 且包含 PDF 头。"""
    from src.services.certificate_pdf_service import generate_certificate_pdf

    # 伪造 cert / course / employee
    cert = MagicMock()
    cert.id = uuid.uuid4()
    cert.cert_no = "TEST20260401001"
    cert.issued_at = datetime(2026, 4, 1, 10, 0, 0)
    cert.expire_at = datetime(2027, 4, 1, 10, 0, 0)
    cert.status = "active"
    cert.employee_id = "E001"
    cert.course_id = uuid.uuid4()

    course = MagicMock()
    course.title = "食品安全培训"

    emp = MagicMock()
    emp.name = "张三"

    # mock session.execute 按调用顺序返回 cert / course / employee
    session = MagicMock()

    results = [cert, course, emp]

    async def mock_execute(*args, **kwargs):
        m = MagicMock()
        m.scalar_one_or_none.return_value = results.pop(0) if results else None
        return m

    session.execute = AsyncMock(side_effect=mock_execute)
    session.flush = AsyncMock()

    pdf_bytes = await generate_certificate_pdf(session, str(cert.id), write_pdf_url=True)

    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 500, "PDF 内容太小，生成异常"
    assert pdf_bytes[:4] == b"%PDF", "缺少 PDF 头标识"


@pytest.mark.asyncio
async def test_generate_certificate_pdf_not_found_returns_empty():
    """证书不存在：返回空 bytes，不抛异常。"""
    from src.services.certificate_pdf_service import generate_certificate_pdf

    session = MagicMock()

    async def mock_execute(*args, **kwargs):
        m = MagicMock()
        m.scalar_one_or_none.return_value = None
        return m

    session.execute = AsyncMock(side_effect=mock_execute)
    session.flush = AsyncMock()

    pdf_bytes = await generate_certificate_pdf(session, str(uuid.uuid4()))
    assert pdf_bytes == b""


def test_mask_holder_name():
    """姓名脱敏规则：2 位保留首字，3+ 位首尾保留、中间 *。"""
    from src.services.certificate_pdf_service import mask_holder_name

    assert mask_holder_name("张") == "张"
    assert mask_holder_name("张三") == "张*"
    assert mask_holder_name("张小三") == "张*三"
    assert mask_holder_name("欧阳修明") == "欧*明"
    assert mask_holder_name("") == "*"
