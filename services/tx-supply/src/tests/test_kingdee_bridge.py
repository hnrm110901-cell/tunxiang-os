"""金蝶ERP桥接层测试

测试覆盖:
1. 采购入库凭证生成（借贷平衡、科目正确）
2. 成本结转凭证生成
3. 调拨出入库凭证生成（含调出+调入）
4. 工资计提凭证生成
5. 收营日报凭证（多支付方式分录）
6. 销售出库凭证生成
7. 导出历史查询
8. 重试失败导出（状态校验）
9. 凭证金额单位为分
10. 导出记录结构完整性
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.kingdee_bridge import (
    ACCOUNT_ADMIN_EXPENSE,
    ACCOUNT_AP,
    ACCOUNT_INVENTORY_GOODS,
    ACCOUNT_MAIN_BIZ_COST,
    ACCOUNT_MAIN_BIZ_REVENUE,
    ACCOUNT_RAW_MATERIAL,
    ACCOUNT_SALARY_PAYABLE,
    EXPORT_STATUS_COMPLETED,
    _make_voucher_entry,
    export_cost_transfer,
    export_daily_revenue,
    export_purchase_receipt,
    export_salary_accrual,
    export_sales_delivery,
    export_transfer_in_out,
    get_export_history,
    retry_failed_export,
)

# ─── Mock 工具 ───


def _make_mock_db(rows=None, scalar_value=None, mappings_first=None):
    """构建 mock AsyncSession"""
    mock_db = AsyncMock()
    mock_result = MagicMock()

    if mappings_first is not None:
        mock_result.mappings.return_value.first.return_value = mappings_first
    elif rows:
        mock_result.mappings.return_value.first.return_value = rows[0] if rows else None
        mock_result.mappings.return_value.all.return_value = rows
    else:
        mock_result.mappings.return_value.first.return_value = None
        mock_result.mappings.return_value.all.return_value = []

    mock_result.scalar.return_value = scalar_value
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ─── 测试 ───


class TestVoucherEntry:
    def test_make_entry_debit(self):
        entry = _make_voucher_entry("1403", debit_fen=50000, summary="采购")
        assert entry["account"] == "1403"
        assert entry["debit_fen"] == 50000
        assert entry["credit_fen"] == 0

    def test_make_entry_credit(self):
        entry = _make_voucher_entry("2202", credit_fen=50000, summary="应付")
        assert entry["credit_fen"] == 50000
        assert entry["debit_fen"] == 0


class TestPurchaseReceipt:
    @pytest.mark.asyncio
    async def test_purchase_receipt_voucher(self):
        db = _make_mock_db(mappings_first={"total_cost_fen": 1500000, "tx_count": 30})
        result = await export_purchase_receipt("store1", "2026-03", "t1", db)

        assert result["export_type"] == "purchase_receipt"
        assert result["status"] == EXPORT_STATUS_COMPLETED
        voucher = result["voucher"]
        assert voucher["voucher_type"] == "记"
        assert len(voucher["entries"]) == 2
        # 借贷平衡
        assert voucher["total_debit_fen"] == voucher["total_credit_fen"]
        assert voucher["total_debit_fen"] == 1500000
        # 科目检查
        assert voucher["entries"][0]["account"] == ACCOUNT_RAW_MATERIAL
        assert voucher["entries"][1]["account"] == ACCOUNT_AP

    @pytest.mark.asyncio
    async def test_purchase_receipt_zero(self):
        db = _make_mock_db(mappings_first={"total_cost_fen": 0, "tx_count": 0})
        result = await export_purchase_receipt("store1", "2026-03", "t1", db)
        assert result["voucher"]["total_debit_fen"] == 0


class TestCostTransfer:
    @pytest.mark.asyncio
    async def test_cost_transfer_voucher(self):
        db = _make_mock_db(mappings_first={"total_cost_fen": 800000, "tx_count": 200})
        result = await export_cost_transfer("store1", "2026-03", "t1", db)

        voucher = result["voucher"]
        assert voucher["voucher_type"] == "转"
        assert voucher["entries"][0]["account"] == ACCOUNT_MAIN_BIZ_COST
        assert voucher["entries"][0]["debit_fen"] == 800000
        assert voucher["entries"][1]["account"] == ACCOUNT_RAW_MATERIAL
        assert voucher["entries"][1]["credit_fen"] == 800000


class TestTransferInOut:
    @pytest.mark.asyncio
    async def test_transfer_both_directions(self):
        """调出+调入同时存在"""
        mock_db = AsyncMock()
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # 调出
                mock_result.mappings.return_value.first.return_value = {"total_fen": 300000, "cnt": 5}
            else:
                # 调入
                mock_result.mappings.return_value.first.return_value = {"total_fen": 200000, "cnt": 3}
            return mock_result

        mock_db.execute = AsyncMock(side_effect=side_effect)
        result = await export_transfer_in_out("store1", "2026-03", "t1", mock_db)

        voucher = result["voucher"]
        assert len(voucher["entries"]) == 4  # 调出2条 + 调入2条
        assert voucher["total_debit_fen"] == 500000
        assert voucher["total_credit_fen"] == 500000


class TestSalaryAccrual:
    @pytest.mark.asyncio
    async def test_salary_accrual_voucher(self):
        db = _make_mock_db(mappings_first={"total_salary_fen": 2000000, "employee_count": 15})
        result = await export_salary_accrual("store1", "2026-03", "t1", db)

        voucher = result["voucher"]
        assert voucher["entries"][0]["account"] == ACCOUNT_ADMIN_EXPENSE
        assert voucher["entries"][0]["debit_fen"] == 2000000
        assert voucher["entries"][1]["account"] == ACCOUNT_SALARY_PAYABLE
        assert voucher["entries"][1]["credit_fen"] == 2000000


class TestDailyRevenue:
    @pytest.mark.asyncio
    async def test_daily_revenue_multi_payment(self):
        """多支付方式生成多条借方分录"""
        rows = [
            {"pay_method": "wechat", "amount_fen": 500000, "pay_count": 80},
            {"pay_method": "alipay", "amount_fen": 300000, "pay_count": 50},
            {"pay_method": "cash", "amount_fen": 100000, "pay_count": 10},
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await export_daily_revenue("store1", "2026-03-15", "t1", mock_db)
        voucher = result["voucher"]
        assert voucher["voucher_type"] == "收"
        # 3个借方 + 1个贷方(收入)
        assert len(voucher["entries"]) == 4
        assert voucher["total_debit_fen"] == 900000
        assert voucher["entries"][-1]["account"] == ACCOUNT_MAIN_BIZ_REVENUE
        assert voucher["entries"][-1]["credit_fen"] == 900000


class TestSalesDelivery:
    @pytest.mark.asyncio
    async def test_sales_delivery_voucher(self):
        db = _make_mock_db(mappings_first={"total_cost_fen": 600000, "order_count": 150})
        result = await export_sales_delivery("store1", "2026-03", "t1", db)

        voucher = result["voucher"]
        assert voucher["entries"][0]["account"] == ACCOUNT_MAIN_BIZ_COST
        assert voucher["entries"][1]["account"] == ACCOUNT_INVENTORY_GOODS
        assert voucher["total_debit_fen"] == voucher["total_credit_fen"]


class TestExportHistory:
    @pytest.mark.asyncio
    async def test_get_history(self):
        rows = [{"export_id": "abc", "export_type": "purchase_receipt", "status": "completed"}]
        mock_db = AsyncMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar.return_value = 1
            else:
                mock_result.mappings.return_value.all.return_value = rows
            return mock_result

        mock_db.execute = AsyncMock(side_effect=side_effect)
        result = await get_export_history("t1", mock_db)

        assert result["total"] == 1
        assert result["page"] == 1
        assert len(result["items"]) == 1


class TestRetryExport:
    @pytest.mark.asyncio
    async def test_retry_non_failed_raises(self):
        """只有 failed 状态可重试"""
        db = _make_mock_db(
            mappings_first={
                "id": "abc",
                "export_type": "purchase_receipt",
                "store_id": "s1",
                "period": "2026-03",
                "status": "completed",
            }
        )
        with pytest.raises(ValueError, match="Only failed exports"):
            await retry_failed_export("abc", "t1", db)

    @pytest.mark.asyncio
    async def test_retry_not_found_raises(self):
        db = _make_mock_db(mappings_first=None)
        with pytest.raises(ValueError, match="Export record not found"):
            await retry_failed_export("nonexist", "t1", db)


class TestExportRecordStructure:
    @pytest.mark.asyncio
    async def test_record_has_required_fields(self):
        db = _make_mock_db(mappings_first={"total_cost_fen": 100000, "tx_count": 5})
        result = await export_purchase_receipt("store1", "2026-03", "t1", db)

        required_fields = [
            "export_id",
            "export_type",
            "store_id",
            "period",
            "tenant_id",
            "status",
            "voucher",
            "created_at",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"
        assert result["tenant_id"] == "t1"
        assert result["store_id"] == "store1"
