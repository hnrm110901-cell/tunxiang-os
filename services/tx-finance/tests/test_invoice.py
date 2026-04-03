"""电子发票集成测试

覆盖场景：
  1. 订单完成后触发发票申请 → 写入 invoices 表（pending 状态）
  2. 调用诺诺 API 成功 → 状态更新为 issued，存储发票号
  3. 诺诺 API 失败 → 状态为 failed，记录错误，可重试
  4. 查询发票状态（pending/issued/failed/cancelled）
  5. 重打发票（已 issued 的发票重新发送）
  6. 发票金额与订单金额校验（防止异常）
  7. tenant_id 隔离
"""
import os

# ── 路径适配（CI 环境下直接 import service 层）────────────────────────────────
import sys
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.cost_snapshot import Base
from models.invoice import Invoice
from services.invoice_service import (
    InvoiceAmountMismatchError,
    InvoiceNotFoundError,
    InvoiceService,
    InvoiceStatusError,
)

from shared.adapters.nuonuo.src.invoice_client import NuonuoInvoiceClient, NuonuoResponse

# ── 夹具：内存 SQLite DB（仅测试用，生产使用 PostgreSQL）────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _make_nuonuo_client(
    apply_success: bool = True,
    query_status: str = "1",  # "1"=成功 "2"=失败
    apply_data: dict | None = None,
    apply_error: str = "诺诺服务不可用",
    get_pdf_success: bool = True,
    red_flush_success: bool = True,
) -> NuonuoInvoiceClient:
    """构建 Mock NuonuoInvoiceClient。"""
    client = MagicMock(spec=NuonuoInvoiceClient)

    if apply_success:
        client.apply_invoice = AsyncMock(
            return_value=NuonuoResponse(
                success=True,
                data=apply_data or {"serialNo": "SN-TEST-001"},
            )
        )
    else:
        client.apply_invoice = AsyncMock(
            return_value=NuonuoResponse(success=False, error_msg=apply_error)
        )

    # query_invoice 返回模拟状态
    client.query_invoice = AsyncMock(
        return_value=NuonuoResponse(
            success=True,
            data={
                "invoiceQueryResultList": [
                    {
                        "status": query_status,
                        "invoiceNo": "24440000" if query_status == "1" else "",
                        "invoiceCode": "144031909110",
                        "pdfUrl": "https://example.com/invoice.pdf",
                        "failCause": "" if query_status == "1" else "开票信息有误",
                    }
                ]
            },
        )
    )

    if get_pdf_success:
        client.get_pdf_url = AsyncMock(
            return_value=NuonuoResponse(
                success=True,
                data={"pdf_url": "https://example.com/invoice_new.pdf"},
            )
        )
    else:
        client.get_pdf_url = AsyncMock(
            return_value=NuonuoResponse(success=False, error_msg="PDF 获取失败")
        )

    if red_flush_success:
        client.red_flush_invoice = AsyncMock(
            return_value=NuonuoResponse(success=True, data={"serialNo": "SN-RED-001"})
        )
    else:
        client.red_flush_invoice = AsyncMock(
            return_value=NuonuoResponse(success=False, error_msg="红冲失败")
        )

    return client


TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ORDER_ID = uuid.uuid4()


def _base_invoice_info(**overrides) -> dict[str, Any]:
    base = {
        "order_id": ORDER_ID,
        "invoice_type": "electronic",
        "invoice_title": "测试餐饮有限公司",
        "tax_number": "91430100MA4L12345X",
        "amount": Decimal("128.00"),
        "tax_amount": Decimal("7.28"),
    }
    base.update(overrides)
    return base


# ── 测试用例 ──────────────────────────────────────────────────────────────────

class TestRequestInvoice:
    """场景1：订单完成触发发票申请 → 写入 invoices 表"""

    @pytest.mark.asyncio
    async def test_creates_invoice_in_pending_state(self, db_session: AsyncSession):
        """申请发票后 invoices 表应存在 pending 状态记录。"""
        client = _make_nuonuo_client(apply_success=True)
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )

        assert invoice.id is not None
        assert invoice.order_id == ORDER_ID
        assert invoice.tenant_id == TENANT_A
        assert invoice.amount == Decimal("128.00")
        # 申请受理后仍为 pending（诺诺异步开票）
        assert invoice.status == "pending"
        assert invoice.platform_request_id is not None
        client.apply_invoice.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_platform_request_id_updated_after_acceptance(self, db_session: AsyncSession):
        """诺诺返回 serialNo 后 platform_request_id 应更新为 serialNo。"""
        client = _make_nuonuo_client(apply_data={"serialNo": "SN-ABC-999"})
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )

        assert invoice.platform_request_id == "SN-ABC-999"


class TestNuonuoApiSuccess:
    """场景2：调用诺诺 API 成功后状态更新为 issued + 存储发票号"""

    @pytest.mark.asyncio
    async def test_query_updates_status_to_issued(self, db_session: AsyncSession):
        """pending 发票查询时，诺诺返回 status=1 → 本地更新为 issued。"""
        client = _make_nuonuo_client(query_status="1")
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        assert invoice.status == "pending"

        result = await service.get_invoice_status(invoice.id, TENANT_A, db_session)

        assert result["status"] == "issued"
        assert result["invoice_no"] == "24440000"
        assert result["invoice_code"] == "144031909110"
        assert result["pdf_url"] == "https://example.com/invoice.pdf"
        assert result["issued_at"] is not None


class TestNuonuoApiFailure:
    """场景3：诺诺 API 失败 → status=failed，记录错误，可重试"""

    @pytest.mark.asyncio
    async def test_failed_status_on_api_error(self, db_session: AsyncSession):
        """诺诺申请失败 → invoice.status == 'failed'，failed_reason 有内容。"""
        client = _make_nuonuo_client(apply_success=False, apply_error="税号不存在")
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )

        assert invoice.status == "failed"
        assert "税号不存在" in invoice.failed_reason

    @pytest.mark.asyncio
    async def test_retry_failed_invoice(self, db_session: AsyncSession):
        """failed 发票可重试，重试成功后变为 pending。"""
        # 第一次：失败
        client = _make_nuonuo_client(apply_success=False, apply_error="网络超时")
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        assert invoice.status == "failed"

        # 第二次：成功
        client.apply_invoice = AsyncMock(
            return_value=NuonuoResponse(success=True, data={"serialNo": "SN-RETRY-001"})
        )
        retried = await service.retry_failed(invoice.id, TENANT_A, db_session)

        assert retried.status == "pending"
        assert retried.failed_reason is None
        assert retried.platform_request_id == "SN-RETRY-001"

    @pytest.mark.asyncio
    async def test_retry_non_failed_invoice_raises(self, db_session: AsyncSession):
        """非 failed 状态的发票重试应抛出 InvoiceStatusError。"""
        # 先造一个 pending 发票
        client = _make_nuonuo_client(apply_success=True)
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        assert invoice.status == "pending"

        with pytest.raises(InvoiceStatusError):
            await service.retry_failed(invoice.id, TENANT_A, db_session)


class TestInvoiceStatusQuery:
    """场景4：查询发票状态（pending/issued/failed/cancelled）"""

    @pytest.mark.asyncio
    async def test_query_pending_triggers_nuonuo_call(self, db_session: AsyncSession):
        """pending 状态时，get_invoice_status 应调用诺诺实时查询。"""
        client = _make_nuonuo_client(query_status="0")  # 0=开票中
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        result = await service.get_invoice_status(invoice.id, TENANT_A, db_session)

        assert result["status"] == "pending"
        client.query_invoice.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_issued_no_nuonuo_call(self, db_session: AsyncSession):
        """issued 状态时，不再调用诺诺接口。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        # 手动造 issued 发票
        inv = Invoice(
            tenant_id=TENANT_A,
            order_id=ORDER_ID,
            invoice_type="electronic",
            amount=Decimal("100.00"),
            status="issued",
            invoice_no="INV-001",
            invoice_code="CODE-001",
            platform_request_id="SN-ISSUED-001",
        )
        db_session.add(inv)
        await db_session.commit()
        await db_session.refresh(inv)

        result = await service.get_invoice_status(inv.id, TENANT_A, db_session)

        assert result["status"] == "issued"
        client.query_invoice.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_query_failed_status(self, db_session: AsyncSession):
        """诺诺返回 status=2 时本地更新为 failed 并记录 failCause。"""
        client = _make_nuonuo_client(query_status="2")
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        result = await service.get_invoice_status(invoice.id, TENANT_A, db_session)

        assert result["status"] == "failed"
        assert result["failed_reason"] is not None


class TestReprint:
    """场景5：重打发票（已 issued 的发票重新发送）"""

    @pytest.mark.asyncio
    async def test_reprint_updates_pdf_url(self, db_session: AsyncSession):
        """重打成功后 pdf_url 应更新。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        inv = Invoice(
            tenant_id=TENANT_A,
            order_id=ORDER_ID,
            invoice_type="electronic",
            amount=Decimal("100.00"),
            status="issued",
            invoice_no="INV-REPRINT-001",
            invoice_code="CODE-REPRINT",
            pdf_url="https://example.com/old.pdf",
            platform_request_id="SN-OLD",
        )
        db_session.add(inv)
        await db_session.commit()
        await db_session.refresh(inv)

        result = await service.reprint(inv.id, TENANT_A, db_session)

        assert result["pdf_url"] == "https://example.com/invoice_new.pdf"
        client.get_pdf_url.assert_awaited_once_with("CODE-REPRINT", "INV-REPRINT-001")

    @pytest.mark.asyncio
    async def test_reprint_non_issued_raises(self, db_session: AsyncSession):
        """非 issued 状态的发票重打应抛出 InvoiceStatusError。"""
        client = _make_nuonuo_client(apply_success=False, apply_error="err")
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        assert invoice.status == "failed"

        with pytest.raises(InvoiceStatusError):
            await service.reprint(invoice.id, TENANT_A, db_session)


class TestAmountValidation:
    """场景6：发票金额与订单金额校验"""

    @pytest.mark.asyncio
    async def test_amount_mismatch_raises(self, db_session: AsyncSession):
        """发票金额超出订单金额容差时应抛出 InvoiceAmountMismatchError。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        with pytest.raises(InvoiceAmountMismatchError):
            await service.request_invoice(
                order_id=ORDER_ID,
                invoice_info=_base_invoice_info(amount=Decimal("200.00")),
                tenant_id=TENANT_A,
                db=db_session,
                order_amount=Decimal("128.00"),  # 差额 72 >> 0.01
            )

    @pytest.mark.asyncio
    async def test_amount_within_tolerance_ok(self, db_session: AsyncSession):
        """发票金额在容差范围内（≤0.01）应正常申请。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(amount=Decimal("128.00")),
            tenant_id=TENANT_A,
            db=db_session,
            order_amount=Decimal("128.00"),
        )
        assert invoice is not None

    @pytest.mark.asyncio
    async def test_no_order_amount_skips_validation(self, db_session: AsyncSession):
        """不传 order_amount 时跳过金额校验。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(amount=Decimal("999.00")),
            tenant_id=TENANT_A,
            db=db_session,
            order_amount=None,  # 不校验
        )
        assert invoice is not None


class TestTenantIsolation:
    """场景7：tenant_id 隔离"""

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_access_tenant_a_invoice(self, db_session: AsyncSession):
        """租户 B 无法查询租户 A 的发票，应抛出 InvoiceNotFoundError。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )

        with pytest.raises(InvoiceNotFoundError):
            await service.get_invoice_status(invoice.id, TENANT_B, db_session)

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_retry_tenant_a_invoice(self, db_session: AsyncSession):
        """租户 B 不能重试租户 A 的失败发票。"""
        client = _make_nuonuo_client(apply_success=False, apply_error="err")
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )
        assert invoice.status == "failed"

        with pytest.raises(InvoiceNotFoundError):
            await service.retry_failed(invoice.id, TENANT_B, db_session)

    @pytest.mark.asyncio
    async def test_each_tenant_gets_own_invoices(self, db_session: AsyncSession):
        """两个租户分别申请发票，互不可见。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        inv_a = await service.request_invoice(
            order_id=uuid.uuid4(),
            invoice_info=_base_invoice_info(invoice_title="租户A公司"),
            tenant_id=TENANT_A,
            db=db_session,
        )
        inv_b = await service.request_invoice(
            order_id=uuid.uuid4(),
            invoice_info=_base_invoice_info(invoice_title="租户B公司"),
            tenant_id=TENANT_B,
            db=db_session,
        )

        # A 能查自己
        result_a = await service.get_invoice_status(inv_a.id, TENANT_A, db_session)
        assert result_a["invoice_title"] == "租户A公司"

        # A 不能查 B
        with pytest.raises(InvoiceNotFoundError):
            await service.get_invoice_status(inv_b.id, TENANT_A, db_session)


class TestCancelInvoice:
    """补充：红冲作废场景"""

    @pytest.mark.asyncio
    async def test_cancel_issued_invoice(self, db_session: AsyncSession):
        """issued 发票红冲成功 → status 变为 cancelled。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        inv = Invoice(
            tenant_id=TENANT_A,
            order_id=ORDER_ID,
            invoice_type="electronic",
            amount=Decimal("100.00"),
            status="issued",
            invoice_no="INV-CANCEL-001",
            invoice_code="CODE-CANCEL",
            platform_request_id="SN-CANCEL",
        )
        db_session.add(inv)
        await db_session.commit()
        await db_session.refresh(inv)

        cancelled = await service.cancel_invoice(inv.id, TENANT_A, db_session)
        assert cancelled.status == "cancelled"
        client.red_flush_invoice.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_pending_invoice_raises(self, db_session: AsyncSession):
        """pending 发票不可红冲。"""
        client = _make_nuonuo_client()
        service = InvoiceService(nuonuo_client=client)

        invoice = await service.request_invoice(
            order_id=ORDER_ID,
            invoice_info=_base_invoice_info(),
            tenant_id=TENANT_A,
            db=db_session,
        )

        with pytest.raises(InvoiceStatusError):
            await service.cancel_invoice(invoice.id, TENANT_A, db_session)
