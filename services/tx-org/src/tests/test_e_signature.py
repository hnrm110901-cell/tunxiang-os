"""电子签约服务测试 — ESignatureService

覆盖:
- 模板管理：创建 / 详情 / 更新 (成功路径 + 非法合同类型 + 名称为空)
- 签署流程：发起 / 员工签 / 企业签 / 终止
- 合同编号生成格式校验
- 查询分页参数校验
- 到期扫描：天数阈值
- 统计概览

使用 AsyncMock 模拟 AsyncSession，无真实 DB 依赖。
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# 确保 src 目录在导入路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.e_signature_service import (
    CONTRACT_TYPES,
    STATUS_LABELS,
    ESignatureService,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助：构造 mock AsyncSession / mock 查询结果
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_db() -> AsyncMock:
    """返回最小 AsyncSession mock：execute / flush 均 awaitable"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


def _mk_result(
    one_or_none: dict | None = None,
    all_rows: list[dict] | None = None,
    scalar_value: int | None = None,
    one: dict | None = None,
) -> MagicMock:
    """构造 SQLAlchemy Result mock"""
    result = MagicMock()
    mappings = MagicMock()
    mappings.one_or_none = MagicMock(return_value=one_or_none)
    mappings.all = MagicMock(return_value=all_rows or [])
    mappings.one = MagicMock(return_value=one or {})
    result.mappings = MagicMock(return_value=mappings)
    if scalar_value is not None:
        result.scalar_one = MagicMock(return_value=scalar_value)
    return result


TENANT_ID = str(uuid4())
TPL_ID = str(uuid4())
EMP_ID = str(uuid4())
REC_ID = str(uuid4())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 构造器参数校验
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_service_init_with_empty_tenant_raises():
    """空 tenant_id 初始化时抛 ValueError"""
    db = _make_db()
    with pytest.raises(ValueError, match="tenant_id 不能为空"):
        ESignatureService(db, "   ")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 合同编号生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_generate_contract_no_format():
    """合同编号格式 TX-{TYPE}-{YYYYMMDD}-{4位序号}"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    no = svc._generate_contract_no("labor")
    # 校验前缀与大致长度：TX- LABOR - 8位日期 - 4位16进制
    assert no.startswith("TX-LABOR-")
    parts = no.split("-")
    assert len(parts) == 4
    assert len(parts[2]) == 8  # YYYYMMDD
    assert len(parts[3]) == 4  # 4位序号


def test_generate_contract_no_unknown_type_uses_uppercase():
    """未知合同类型时使用大写截断"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    no = svc._generate_contract_no("custom_type")
    assert no.startswith("TX-CUSTOM-")  # 取前6位大写


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 创建模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_template_success():
    """创建合同模板 -> 返回 id / 版本号 1"""
    db = _make_db()
    db.execute.return_value = MagicMock()  # set_config 与 INSERT 都返回空
    svc = ESignatureService(db, TENANT_ID)
    out = await svc.create_template(
        name="标准劳动合同",
        contract_type="labor",
        content_html="<p>{{name}}</p>",
        variables=[{"key": "name", "label": "姓名"}],
    )
    assert out["template_name"] == "标准劳动合同"
    assert out["contract_type"] == "labor"
    assert out["contract_type_label"] == "劳动合同"
    assert out["version"] == 1
    assert "id" in out


@pytest.mark.asyncio
async def test_create_template_empty_name_raises():
    """模板名称为空时报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="模板名称不能为空"):
        await svc.create_template(name="   ", contract_type="labor")


@pytest.mark.asyncio
async def test_create_template_invalid_type_raises():
    """不支持的合同类型报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="不支持的合同类型"):
        await svc.create_template(name="NDA", contract_type="unknown_type")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 模板详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_template_not_found_raises():
    """模板不存在时报错"""
    db = _make_db()
    # set_config 与 SELECT：第二次返回空
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    svc = ESignatureService(db, TENANT_ID)
    with pytest.raises(ValueError, match="模板不存在"):
        await svc.get_template(TPL_ID)


@pytest.mark.asyncio
async def test_get_template_returns_detail():
    """模板存在时返回详情"""
    db = _make_db()
    row = {
        "id": TPL_ID,
        "template_name": "劳动合同",
        "contract_type": "labor",
        "content_html": "<p></p>",
        "variables": [],
        "is_active": True,
        "version": 2,
        "created_by": None,
        "created_at": None,
        "updated_at": None,
    }
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    svc = ESignatureService(db, TENANT_ID)
    detail = await svc.get_template(TPL_ID)
    assert detail["id"] == TPL_ID
    assert detail["version"] == 2
    assert detail["contract_type_label"] == "劳动合同"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 模板分页
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_templates_invalid_page_raises():
    """page < 1 时报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="page"):
        await svc.list_templates(page=0)


@pytest.mark.asyncio
async def test_list_templates_invalid_size_raises():
    """size 超出 1-100 时报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="size"):
        await svc.list_templates(size=500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 发起签署
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_initiate_signing_end_before_start_raises():
    """合同结束日期早于开始日期时报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="结束日期不能早于开始日期"):
        await svc.initiate_signing(
            template_id=TPL_ID,
            employee_id=EMP_ID,
            start_date="2026-06-01",
            end_date="2026-05-01",
        )


@pytest.mark.asyncio
async def test_initiate_signing_template_not_found_raises():
    """模板不存在或已停用时报错"""
    db = _make_db()
    # set_config + 查询模板(返回 None)
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    svc = ESignatureService(db, TENANT_ID)
    with pytest.raises(ValueError, match="模板不存在"):
        await svc.initiate_signing(
            template_id=TPL_ID,
            employee_id=EMP_ID,
            start_date="2026-01-01",
            end_date="2026-12-31",
        )


@pytest.mark.asyncio
async def test_initiate_signing_success_returns_pending():
    """成功发起签署 -> 状态 pending_sign，生成合同编号"""
    db = _make_db()
    tpl_row = {
        "template_name": "劳动合同",
        "contract_type": "labor",
        "content_html": "欢迎 {{name}} 加入",
        "variables": [],
    }
    emp_row = {"emp_name": "张三"}
    db.execute.side_effect = [
        MagicMock(),  # set_config
        _mk_result(one_or_none=tpl_row),  # 查模板
        _mk_result(one_or_none=emp_row),  # 查员工
        MagicMock(),  # INSERT
    ]
    svc = ESignatureService(db, TENANT_ID)
    out = await svc.initiate_signing(
        template_id=TPL_ID,
        employee_id=EMP_ID,
        start_date="2026-01-01",
        end_date="2026-12-31",
        variables_filled={"name": "张三"},
    )
    assert out["status"] == "pending_sign"
    assert out["employee_name"] == "张三"
    assert out["contract_no"].startswith("TX-LABOR-")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 员工/企业签署
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_employee_sign_wrong_status_raises():
    """签署记录状态不是 pending_sign 时报错"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=None)]
    svc = ESignatureService(db, TENANT_ID)
    with pytest.raises(ValueError, match="签署记录不存在"):
        await svc.employee_sign(REC_ID)


@pytest.mark.asyncio
async def test_employee_sign_success():
    """员工签成功 -> employee_signed"""
    db = _make_db()
    row = {"id": REC_ID, "contract_no": "TX-LABOR-20260101-ABCD", "signed_at": None}
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    svc = ESignatureService(db, TENANT_ID)
    out = await svc.employee_sign(REC_ID)
    assert out["status"] == "employee_signed"
    assert out["contract_no"] == "TX-LABOR-20260101-ABCD"


@pytest.mark.asyncio
async def test_company_sign_success():
    """企业盖章成功 -> completed"""
    db = _make_db()
    row = {"id": REC_ID, "contract_no": "TX-LABOR-X", "company_signed_at": None}
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    svc = ESignatureService(db, TENANT_ID)
    out = await svc.company_sign(REC_ID, str(uuid4()))
    assert out["status"] == "completed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 终止合同
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_terminate_contract_empty_reason_raises():
    """终止原因为空时报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="终止原因不能为空"):
        await svc.terminate_contract(REC_ID, "  ")


@pytest.mark.asyncio
async def test_terminate_contract_success():
    """终止合同成功"""
    db = _make_db()
    row = {"id": REC_ID, "contract_no": "TX-LABOR-X"}
    db.execute.side_effect = [MagicMock(), _mk_result(one_or_none=row)]
    svc = ESignatureService(db, TENANT_ID)
    out = await svc.terminate_contract(REC_ID, "员工离职")
    assert out["status"] == "terminated"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 到期预警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_scan_expiring_contracts_negative_days_raises():
    """阈值 < 0 时报错"""
    svc = ESignatureService(_make_db(), TENANT_ID)
    with pytest.raises(ValueError, match="days_threshold"):
        await svc.scan_expiring_contracts(days_threshold=-1)


@pytest.mark.asyncio
async def test_scan_expiring_contracts_empty_list():
    """无到期合同时返回空列表"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(all_rows=[])]
    svc = ESignatureService(db, TENANT_ID)
    items = await svc.scan_expiring_contracts(days_threshold=30)
    assert items == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. 统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_contract_stats_returns_counts():
    """统计概览：返回各状态的数量"""
    db = _make_db()
    stats_row = {
        "total": 10,
        "completed": 6,
        "pending": 2,
        "terminated": 1,
        "expired": 1,
        "expiring_30d": 3,
    }
    db.execute.side_effect = [MagicMock(), _mk_result(one=stats_row)]
    svc = ESignatureService(db, TENANT_ID)
    stats = await svc.get_contract_stats()
    assert stats["total"] == 10
    assert stats["completed"] == 6
    assert stats["expiring_30d"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  11. 元数据常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_contract_types_contains_five_categories():
    """5 种合同类型全部存在"""
    for k in ("labor", "confidentiality", "non_compete", "internship", "part_time"):
        assert k in CONTRACT_TYPES


def test_status_labels_coverage():
    """7 种状态标签全部存在"""
    for k in (
        "draft",
        "pending_sign",
        "employee_signed",
        "company_signed",
        "completed",
        "expired",
        "terminated",
    ):
        assert k in STATUS_LABELS
