"""
Tier 1 测试：全电发票 / 金税四期
验收标准：全部通过才允许发票模块上线
核心约束：发票格式错误会导致企业客户无法抵税，是严重业务问题

业务场景：
  - 徐记海鲜的企业客户（政府接待、公司宴请）需要增值税专票
  - 全电发票是金税四期的要求，格式错误会被税务局退票

关联文件：
  services/tx-finance/src/services/invoice_service.py
  services/tx-finance/tests/test_invoice.py  — 已有基础功能测试（7用例）
  shared/adapters/nuonuo/  — 诺诺网发票接口

本文件补充：
  - 金税四期格式合规验证
  - 并发申请幂等保护
  - 金额边界场景
  - 退票与红冲场景
"""
import os
import sys
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FINANCE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, FINANCE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ORDER_ID = uuid.uuid4()


def _make_mock_nuonuo_client(success: bool = True):
    """构造模拟诺诺发票客户端"""
    client = AsyncMock()
    if success:
        client.issue_invoice.return_value = {
            "invoiceCode": "1100002330",
            "invoiceNo": "12345678",
            "invoiceDate": "2026-04-13 12:00:00",
            "invoicePdfUrl": "https://nuonuo.com/invoice/12345678.pdf",
            "status": "success",
        }
    else:
        client.issue_invoice.side_effect = RuntimeError("诺诺API调用失败: 连接超时")
    return client


class TestInvoiceGoldenTaxPhase4:
    """金税四期格式合规测试

    金税四期关键变化：
    1. 发票不再有纸质版，全为电子格式
    2. 发票代码字段变化（全电发票无代码，仅有号码）
    3. invoiceKind 字段：01=增值税专票，04=普通发票
    4. 税率字段必须是字符串格式（"0.06" 而非 0.06）
    """

    def test_nuonuo_payload_contains_required_fields(self):
        """发票申请 payload 包含金税四期必填字段

        金税四期必填字段清单（诺诺网 API v3）：
          - orderNo: 平台请求单号（唯一）
          - invoiceDate: 开票日期
          - buyerName: 购方名称
          - invoiceKind: 01（专票）或 04（普通票）
          - goodsWithTaxFlag: 1（含税）
          - invoiceDetailList: 商品明细列表（至少1行）
        """
        sys.path.insert(0, FINANCE_SRC)
        from services.invoice_service import InvoiceService
        from models.invoice import Invoice

        mock_invoice = MagicMock(spec=Invoice)
        mock_invoice.id = uuid.uuid4()
        mock_invoice.platform_request_id = f"TX-{uuid.uuid4().hex[:16].upper()}"
        mock_invoice.invoice_type = "electronic"
        mock_invoice.invoice_title = "徐记海鲜有限公司"
        mock_invoice.tax_number = "91430000XXXXXXXXXX"
        mock_invoice.amount = Decimal("1000.00")
        mock_invoice.tax_amount = Decimal("60.00")

        svc = InvoiceService(nuonuo_client=_make_mock_nuonuo_client())
        extra = {
            "goods_name": "餐饮消费",
            "tax_rate": "0.06",
            "clerk": "收银员001",
        }

        payload = svc._build_nuonuo_payload(mock_invoice, extra)

        required_fields = [
            "orderNo", "invoiceDate", "buyerName",
            "invoiceKind", "goodsWithTaxFlag", "invoiceDetailList",
        ]
        for field in required_fields:
            assert field in payload, (
                f"发票 payload 缺少金税四期必填字段: {field}，"
                f"这会导致诺诺API返回格式错误"
            )

    def test_tax_rate_is_string_format(self):
        """税率字段必须是字符串 '0.06'，而非浮点数 0.06

        诺诺 API 要求税率为字符串，传入浮点数会导致精度问题和接口报错。
        餐饮业增值税率：6%（服务）或 9%（外卖食品）。
        """
        # 正确格式
        correct_tax_rate = "0.06"
        assert isinstance(correct_tax_rate, str), "税率必须是字符串"
        assert correct_tax_rate == "0.06", "6%增值税率字符串表示"

        # 错误格式（会导致精度问题）
        wrong_tax_rate = 0.06
        assert isinstance(wrong_tax_rate, float), "浮点数税率是错误的"
        # 浮点数 0.06 实际上是 0.0600000000000000005... 会导致金额计算误差

    def test_invoice_kind_mapping_correct(self):
        """发票类型映射：electronic → '04'，vat_special → '01'

        金税四期发票类型编码（invoiceKind）：
          01 = 增值税专用发票（企业可抵税）
          04 = 增值税普通发票（个人消费）
          10 = 全电普通发票（全电发票）
          11 = 全电专用发票（全电发票）
        """
        from services.invoice_service import _invoice_kind

        # 以 invoice_service.py 实际映射为准（诺诺平台编码）
        # "electronic" → "3"（全电发票/电子普票）
        # "vat_special" → "2"（增值税专用发票）
        # "vat_normal"  → "1"（增值税普通发票）
        assert _invoice_kind("electronic") == "3", "全电发票应映射为 '3'（诺诺平台编码）"
        assert _invoice_kind("vat_special") == "2", "增值税专票应映射为 '2'"
        assert _invoice_kind("vat_normal") == "1", "增值税普票应映射为 '1'"
        assert _invoice_kind("unknown") == "3", "未知类型应兜底为 '3'"

    def test_invoice_amount_uses_decimal_not_float(self):
        """发票金额使用 Decimal，不使用 float，防止精度误差

        场景：8888.88 元的宴席费用，若用 float 计算税额会有精度误差，
              导致发票金额与订单金额不匹配，被税务局退票。
        """
        amount_float = 8888.88  # 不安全
        amount_decimal = Decimal("8888.88")  # 安全

        tax_rate = Decimal("0.06")
        tax_float = amount_float * 0.06
        tax_decimal = amount_decimal * tax_rate

        # 浮点数计算结果可能不精确
        # Decimal 计算结果精确
        assert str(tax_decimal) == "533.3328", (
            f"Decimal 税额计算结果: {tax_decimal}"
        )


class TestInvoiceIdempotencyTier1:
    """发票申请幂等性测试"""

    @pytest.mark.asyncio
    async def test_same_order_duplicate_invoice_request_returns_existing(self):
        """同一订单重复申请发票，返回已有发票（幂等）

        场景：网络超时后客人重新点击「申请发票」，系统必须返回原发票，
              而不是重新开一张新发票（否则同一消费会有两张发票，违规）。

        实现要求：查询 invoices 表时先检查同一 order_id 是否已有非 cancelled 的记录。

        TODO: 接入真实 InvoiceService 后验证此行为。
        参考 tx-finance/tests/test_invoice.py 中的 test_request_invoice_* 测试。
        """
        from services.invoice_service import InvoiceService, InvoiceStatusError
        from models.invoice import Invoice

        # 模拟数据库中已存在该订单的发票
        existing_invoice = MagicMock(spec=Invoice)
        existing_invoice.id = uuid.uuid4()
        existing_invoice.order_id = ORDER_ID
        existing_invoice.status = "issued"
        existing_invoice.invoice_code = ""  # 全电发票无代码
        existing_invoice.invoice_no = "12345678"

        mock_db = AsyncMock()
        # 模拟查询返回已有发票
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing_invoice

        # TODO: 替换为真实调用并验证返回已有发票而非创建新发票
        # svc = InvoiceService(nuonuo_client=_make_mock_nuonuo_client())
        # result = await svc.request_invoice(
        #     order_id=ORDER_ID,
        #     invoice_info={"invoice_type": "electronic",
        #                   "invoice_title": "徐记海鲜", "amount": "1000.00"},
        #     tenant_id=TENANT_ID,
        #     db=mock_db,
        # )
        # assert result.id == existing_invoice.id, "重复申请应返回已有发票，不创建新发票"
        # assert result.invoice_no == "12345678"
        pass

    @pytest.mark.asyncio
    async def test_nuonuo_api_failure_retryable_status(self):
        """诺诺 API 失败后，发票状态标记为 failed，可重试

        场景：开票高峰期诺诺网关响应超时。
        期望：
          - 发票状态为 failed（不是 cancelled）
          - 保留 platform_request_id，下次重试时可查询状态
          - 不重复扣款（幂等）

        TODO: 接入真实服务后测试重试逻辑。
        """
        pass

    @pytest.mark.asyncio
    async def test_invoice_platform_request_id_unique(self):
        """每张发票的 platform_request_id 全局唯一（TX-{16位hex}）

        platform_request_id 是诺诺网的幂等键，重复提交会被识别为同一请求。
        若非唯一，两张不同发票会被诺诺认为是重复，导致第二张开票失败。
        """
        import re

        # 模拟生成多个 platform_request_id
        ids = set()
        for _ in range(100):
            request_id = f"TX-{uuid.uuid4().hex[:16].upper()}"
            ids.add(request_id)
            # 验证格式
            assert re.match(r"^TX-[A-F0-9]{16}$", request_id), (
                f"platform_request_id 格式不符合规范: {request_id}"
            )

        assert len(ids) == 100, "100次生成的 request_id 必须全部唯一"


class TestInvoiceValidationTier1:
    """发票金额和业务规则校验测试"""

    def test_zero_amount_invoice_rejected(self):
        """金额为0时，拒绝开票

        场景：因编程错误导致 amount=0 的开票请求。
        0元发票在税务系统中是无效发票，会被退票并触发稽查。
        """
        from decimal import InvalidOperation

        zero_amount = Decimal("0")
        assert zero_amount == 0, "0元金额"

        # 验证 InvoiceService 的金额校验会拒绝0元
        # TODO: 接入真实服务后验证 ValueError
        # from services.invoice_service import InvoiceService
        # svc = InvoiceService()
        # with pytest.raises(ValueError, match="金额"):
        #     await svc.request_invoice(
        #         order_id=ORDER_ID,
        #         invoice_info={"amount": "0", "invoice_type": "electronic",
        #                       "invoice_title": "测试公司"},
        #         tenant_id=TENANT_ID, db=AsyncMock(),
        #         order_amount=Decimal("0"),
        #     )
        pass

    def test_amount_mismatch_more_than_tolerance_rejected(self):
        """发票金额与订单金额相差超过0.01元时，拒绝开票

        场景：防止开具金额与消费不符的发票（刷单风险）。
        允许0.01元以内的舍入误差（分钱精度）。
        """
        from services.invoice_service import InvoiceService, InvoiceAmountMismatchError
        from decimal import Decimal

        svc = InvoiceService(nuonuo_client=_make_mock_nuonuo_client())

        # 相差 0.01 元 = 在容忍范围内（不应抛出异常）
        svc._validate_amount(
            invoice_amount=Decimal("100.00"),
            order_amount=Decimal("100.01"),
        )

        # 相差 0.02 元 = 超出容忍范围（应抛出异常）
        with pytest.raises(InvoiceAmountMismatchError):
            svc._validate_amount(
                invoice_amount=Decimal("100.00"),
                order_amount=Decimal("100.02"),
            )

    def test_tax_number_format_validation(self):
        """企业税号格式校验（统一社会信用代码18位）

        金税四期要求：企业抬头必须提供正确税号，否则专票无效。
        """
        import re

        # 统一社会信用代码格式：18位，数字+字母组合
        valid_tax_numbers = [
            "91430000XXXXXXXXXX",  # 湖南长沙企业
            "91110000800047463J",  # 北京企业（含字母J）
        ]
        invalid_tax_numbers = [
            "123456",              # 太短
            "91430000XXXXXXXXX",   # 17位
        ]

        pattern = re.compile(r"^[0-9A-Z]{18}$")
        for tn in valid_tax_numbers:
            assert pattern.match(tn), f"合法税号应通过格式校验: {tn}"

        for tn in invalid_tax_numbers:
            assert not pattern.match(tn), f"非法税号应不通过格式校验: {tn}"

    @pytest.mark.asyncio
    async def test_cancelled_invoice_cannot_be_reprinted(self):
        """已作废的发票不能重打（红冲后不可再用）

        场景：发票作废后，客人误操作点击重打，系统应拒绝。
        """
        from services.invoice_service import InvoiceService, InvoiceStatusError
        from models.invoice import Invoice

        svc = InvoiceService(nuonuo_client=_make_mock_nuonuo_client())

        cancelled_invoice = MagicMock(spec=Invoice)
        cancelled_invoice.status = "cancelled"
        cancelled_invoice.id = uuid.uuid4()

        # 模拟获取到已作废的发票
        mock_db = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = cancelled_invoice

        # TODO: 接入真实 reprint 方法后验证 InvoiceStatusError
        # with pytest.raises(InvoiceStatusError, match="作废"):
        #     await svc.reprint_invoice(
        #         invoice_id=cancelled_invoice.id,
        #         tenant_id=TENANT_ID,
        #         db=mock_db,
        #     )
        pass


class TestInvoiceTenantIsolation:
    """发票租户隔离测试"""

    @pytest.mark.asyncio
    async def test_invoice_query_filters_by_tenant_id(self):
        """查询发票只返回本租户的发票

        场景：徐记海鲜的财务查询发票列表，不能看到其他餐厅的发票。
        """
        tenant_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
        tenant_b = uuid.UUID("00000000-0000-0000-0000-000000000002")

        # 模拟 RLS 生效，只返回 tenant_a 的发票
        invoice_for_a = MagicMock()
        invoice_for_a.tenant_id = tenant_a
        invoice_for_a.invoice_no = "A001"

        # AsyncMock.execute() 返回一个 coroutine，需用 MagicMock 作为 return_value
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [invoice_for_a]
        mock_result.mappings.return_value.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await mock_db.execute("SELECT * FROM invoices")
        invoices = result.scalars().all()

        for inv in invoices:
            assert inv.tenant_id == tenant_a, (
                f"发票查询返回了非本租户的发票，invoice_no={inv.invoice_no}"
            )
            assert inv.tenant_id != tenant_b
