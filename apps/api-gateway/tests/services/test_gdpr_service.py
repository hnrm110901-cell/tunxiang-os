"""
GDPR service 单元测试
覆盖：
  1) grant/revoke consent 记录状态
  2) 非法 request_type 抛错
  3) 数据导出 ZIP 结构（含 CSV/JSON/README）
  4) 删除：PII 字段假名化，法定字段保留
"""

import io
import sys
import zipfile
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.gdpr_service import LEGAL_RETAINED_FIELDS, GDPRService  # noqa: E402


def _mk_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_access_request_invalid_type():
    svc = GDPRService(_mk_db())
    with pytest.raises(ValueError):
        await svc.create_access_request("EMP001", "hacker")


@pytest.mark.asyncio
async def test_grant_consent_records_granted_true():
    svc = GDPRService(_mk_db())
    r = await svc.grant_consent("EMP001", "data_processing", "contract")
    assert r.granted is True
    assert r.legal_basis == "contract"
    assert r.granted_at is not None


@pytest.mark.asyncio
async def test_revoke_consent_marks_revoked():
    svc = GDPRService(_mk_db())
    r = await svc.revoke_consent("EMP001", "marketing", reason="不想接收推送")
    assert r.granted is False
    assert r.revoked_at is not None


@pytest.mark.asyncio
async def test_export_personal_data_zip_structure():
    # 构造最小 employee mock
    emp = MagicMock()
    emp.__table__ = MagicMock()
    col_id = MagicMock()
    col_id.name = "id"
    col_name = MagicMock()
    col_name.name = "name"
    col_phone = MagicMock()
    col_phone.name = "phone"
    emp.__table__.columns = [col_id, col_name, col_phone]
    emp.id = "EMP001"
    emp.name = "张三"
    emp.phone = "13800000000"

    db = _mk_db()
    db.get = AsyncMock(return_value=emp)
    # get_my_consents → 空
    exec_result = MagicMock()
    exec_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(return_value=exec_result)

    svc = GDPRService(db)
    zip_bytes = await svc.export_personal_data("EMP001")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        assert "employee_basic.csv" in names
        assert "employee_full.json" in names
        assert "README.txt" in names


@pytest.mark.asyncio
async def test_delete_personal_data_anonymizes_pii_retains_legal():
    # 构造 employee 含 PII + 法定字段
    emp = MagicMock()

    col_defs = [
        ("id", str),
        ("name", str),
        ("phone", str),
        ("email", str),
        ("hire_date", str),  # 法定保留
        ("daily_wage_standard_fen", int),
    ]
    cols = []
    for nm, pytype in col_defs:
        c = MagicMock()
        c.name = nm
        c.type.python_type = pytype
        cols.append(c)
    emp.__table__ = MagicMock()
    emp.__table__.columns = cols
    emp.id = "EMP001"
    emp.name = "张三"
    emp.phone = "13800000000"
    emp.email = "a@a.com"
    emp.hire_date = "2020-01-01"
    emp.daily_wage_standard_fen = 20000
    emp.is_active = True

    db = _mk_db()
    db.get = AsyncMock(return_value=emp)

    svc = GDPRService(db)
    result = await svc.delete_personal_data("EMP001")

    assert "name" in result["anonymized_fields"]
    assert "phone" in result["anonymized_fields"]
    # 法定字段不在 anonymized 列表
    assert "hire_date" not in result["anonymized_fields"]
    assert "hire_date" in set(result["retained_legal_fields"])
    # is_active 标记软删除
    assert emp.is_active is False
    # name/phone 被替换为 ANON-*
    assert str(emp.name).startswith("ANON-")
    assert str(emp.phone).startswith("ANON-")
    # hire_date 不变
    assert emp.hire_date == "2020-01-01"
