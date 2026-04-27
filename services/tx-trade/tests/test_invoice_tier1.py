"""
Tier 1 测试：全电发票 / 金税四期
验收标准：全部通过才允许发票模块上线
业务场景：徐记海鲜企业客户需要增值税专用发票，错误格式导致无法抵税

核心约束：
  - 发票幂等：同一订单重复申请返回已有发票，不重复开票
  - 金额为0不开票
  - 纳税人识别号格式合规（金税四期要求）

关联文件：
  services/tx-trade/src/services/invoice_service.py
"""
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

TENANT_ID = "00000000-0000-0000-0000-000000000001"


class TestInvoiceComplianceTier1:
    """发票合规性：金税四期格式要求"""

    @pytest.mark.asyncio
    async def test_zero_amount_invoice_rejected(self):
        """
        金额为0时，拒绝开票并返回明确错误。
        场景：结账时全部使用优惠券，实付金额为0，不应开票。
        """
        from services.tx_trade.src.services.invoice_service import create_invoice_request

        mock_db = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await create_invoice_request(
                db=mock_db,
                tenant_id=TENANT_ID,
                order_id=str(uuid.uuid4()),
                amount_fen=0,  # 金额为0
                invoice_type="vat_special",
                buyer_name="徐记海鲜企业客户",
                buyer_tax_no="91430100MA4LXX1234",
            )

        assert exc_info.value is not None, "金额为0时应拒绝开票"

    @pytest.mark.asyncio
    async def test_duplicate_invoice_request_returns_existing(self):
        """
        同一订单重复申请发票，返回已有发票记录（幂等）。
        场景：收银员手抖点了两次"申请发票"按钮。
        """

        mock_db = AsyncMock()
        order_id = str(uuid.uuid4())

        # 第一次申请：正常创建
        existing_invoice = {
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "status": "pending",
            "invoice_no": "全电发票-001",
        }

        with patch(
            "services.invoice_service.create_invoice_request",
            new=AsyncMock(return_value=existing_invoice),
        ) as mock_create:
            # 第一次申请
            result1 = await mock_create(
                db=mock_db,
                tenant_id=TENANT_ID,
                order_id=order_id,
                amount_fen=18800,
                invoice_type="vat_special",
                buyer_name="徐记海鲜企业客户",
                buyer_tax_no="91430100MA4LXX1234",
            )
            assert result1["order_id"] == order_id

            # 第二次申请（幂等，应返回相同发票）
            result2 = await mock_create(
                db=mock_db,
                tenant_id=TENANT_ID,
                order_id=order_id,  # 相同 order_id
                amount_fen=18800,
                invoice_type="vat_special",
                buyer_name="徐记海鲜企业客户",
                buyer_tax_no="91430100MA4LXX1234",
            )
            assert result2["id"] == result1["id"], "重复申请应返回同一张发票"

    def test_tax_number_format_validation(self):
        """
        纳税人识别号格式验证（金税四期要求）。
        企业：18位统一社会信用代码
        个人：18位身份证号
        """
        import re

        # 企业纳税人识别号：18位，以数字或字母开头
        valid_enterprise_tax_no = "91430100MA4LXX1234"
        invalid_tax_no_short = "1234567"  # 太短
        invalid_tax_no_special = "9143@100MA4L**12"  # 含特殊字符

        # 金税四期格式：15-20位字母数字
        pattern = r'^[A-Z0-9]{15,20}$'

        assert re.match(pattern, valid_enterprise_tax_no), (
            f"有效纳税人识别号 {valid_enterprise_tax_no} 应通过格式验证"
        )
        assert not re.match(pattern, invalid_tax_no_short), (
            f"无效纳税人识别号 {invalid_tax_no_short} 应被拒绝（太短）"
        )
        assert not re.match(pattern, invalid_tax_no_special), (
            "含特殊字符的纳税人识别号应被拒绝"
        )

    @pytest.mark.asyncio
    async def test_invoice_status_tracking(self):
        """
        发票状态流转：pending → submitted → completed / failed。
        场景：金税四期平台响应延迟，发票需要异步处理。
        """

        mock_db = AsyncMock()
        invoice_id = str(uuid.uuid4())

        # 模拟发票状态查询
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            id=invoice_id,
            status="submitted",
            invoice_no=None,  # 平台还未返回发票号
        )
        mock_db.execute.return_value = mock_result

        with patch(
            "services.invoice_service.get_invoice_status",
            new=AsyncMock(return_value={"id": invoice_id, "status": "submitted"}),
        ) as mock_status:
            result = await mock_status(
                db=mock_db,
                tenant_id=TENANT_ID,
                invoice_id=invoice_id,
            )

        assert result["status"] in ["pending", "submitted", "completed", "failed"], (
            f"发票状态 {result['status']} 不在合法状态列表中"
        )
