"""发票服务测试

覆盖场景：
1. 创建电子发票申请
2. 创建增值税专票（校验必填字段）
3. 增值税专票缺少字段报错
4. 提交到税控平台（mock成功）
5. 重复提交已开票发票报错
6. 查询发票状态
7. 查询不存在的发票报错
8. 生成开票二维码数据
9. 发票台账查询
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
import pytest


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()


@pytest.fixture(autouse=True)
def _clear_stores():
    from services.invoice_service import _invoices, _invoice_queue
    _invoices.clear()
    _invoice_queue.clear()


@pytest.mark.asyncio
async def test_create_electronic_invoice():
    """创建电子发票"""
    from services.invoice_service import create_invoice_request

    result = await create_invoice_request(
        order_id=_uid(),
        invoice_type="electronic",
        buyer_info={"name": "测试公司", "tax_no": "91110000ABCDEF"},
        tenant_id=TENANT_ID,
        amount_fen=15000,
    )
    assert result["status"] == "pending"
    assert result["invoice_type"] == "electronic"
    assert result["amount_fen"] == 15000
    assert result["invoice_no"].startswith("INV")


@pytest.mark.asyncio
async def test_create_vat_special_invoice():
    """创建增值税专票（完整信息）"""
    from services.invoice_service import create_invoice_request

    result = await create_invoice_request(
        order_id=_uid(),
        invoice_type="vat_special",
        buyer_info={
            "name": "测试公司",
            "tax_no": "91110000ABCDEF",
            "address": "北京市朝阳区",
            "phone": "010-12345678",
            "bank_name": "工商银行",
            "bank_account": "1234567890",
        },
        tenant_id=TENANT_ID,
        amount_fen=50000,
    )
    assert result["invoice_type"] == "vat_special"


@pytest.mark.asyncio
async def test_vat_special_missing_fields():
    """增值税专票缺少必填字段"""
    from services.invoice_service import create_invoice_request

    with pytest.raises(ValueError, match="VAT special invoice requires"):
        await create_invoice_request(
            order_id=_uid(),
            invoice_type="vat_special",
            buyer_info={"name": "测试公司"},
            tenant_id=TENANT_ID,
        )


@pytest.mark.asyncio
async def test_submit_to_tax_platform():
    """提交到税控平台（mock成功）"""
    from services.invoice_service import create_invoice_request, submit_to_tax_platform

    inv = await create_invoice_request(
        order_id=_uid(), invoice_type="electronic",
        buyer_info={"name": "测试", "tax_no": "123"},
        tenant_id=TENANT_ID, amount_fen=10000,
    )
    result = await submit_to_tax_platform(inv["id"], TENANT_ID)
    assert result["status"] == "issued"
    assert result["tax_platform_code"].startswith("TAX")
    assert result["pdf_url"] is not None


@pytest.mark.asyncio
async def test_submit_already_issued():
    """重复提交已开票发票"""
    from services.invoice_service import create_invoice_request, submit_to_tax_platform

    inv = await create_invoice_request(
        order_id=_uid(), invoice_type="electronic",
        buyer_info={"name": "测试", "tax_no": "123"},
        tenant_id=TENANT_ID,
    )
    await submit_to_tax_platform(inv["id"], TENANT_ID)

    with pytest.raises(ValueError, match="cannot be submitted"):
        await submit_to_tax_platform(inv["id"], TENANT_ID)


@pytest.mark.asyncio
async def test_get_invoice_status():
    """查询发票状态"""
    from services.invoice_service import create_invoice_request, get_invoice_status

    inv = await create_invoice_request(
        order_id=_uid(), invoice_type="paper",
        buyer_info={"name": "测试"},
        tenant_id=TENANT_ID, amount_fen=8800,
    )
    result = await get_invoice_status(inv["id"], TENANT_ID)
    assert result["status"] == "pending"
    assert result["amount_fen"] == 8800


@pytest.mark.asyncio
async def test_get_invoice_not_found():
    """查询不存在的发票"""
    from services.invoice_service import get_invoice_status

    with pytest.raises(ValueError, match="Invoice not found"):
        await get_invoice_status("nonexistent", TENANT_ID)


@pytest.mark.asyncio
async def test_generate_qrcode():
    """生成开票二维码数据"""
    from services.invoice_service import generate_qrcode_data

    result = await generate_qrcode_data(
        order_id=_uid(), tenant_id=TENANT_ID,
        amount_fen=20000, store_name="测试门店",
    )
    assert "url" in result
    assert "token" in result
    assert result["store_name"] == "测试门店"


@pytest.mark.asyncio
async def test_invoice_ledger():
    """发票台账查询"""
    from services.invoice_service import create_invoice_request, get_invoice_ledger

    # 创建几张发票
    for i in range(3):
        await create_invoice_request(
            order_id=_uid(), invoice_type="electronic",
            buyer_info={"name": f"公司{i}"},
            tenant_id=TENANT_ID, amount_fen=10000 * (i + 1),
        )

    result = await get_invoice_ledger(
        store_id=_uid(),
        date_range=("2020-01-01", "2030-12-31"),
        tenant_id=TENANT_ID,
    )
    assert result["total_count"] == 3
    assert result["total_amount_fen"] == 60000  # 10000+20000+30000
