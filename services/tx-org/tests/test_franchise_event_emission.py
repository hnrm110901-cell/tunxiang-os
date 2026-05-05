"""加盟管理域 v147+ 事件总线接入验证测试 [Tier2]

验证 7 个 Tier 1 写入点在业务操作完成后正确触发 emit_event：

routes 层（franchise_v5_routes.py）：
  1. POST /api/v1/franchise/franchisees                 → franchise.franchisee_applied
  2. PUT  /api/v1/franchise/franchisees/{id}            → franchisee_activated/suspended/terminated/signing

routes 层（franchise_fee_routes.py）：
  3. POST /api/v1/franchise/fee-bills                   → franchise.fee_billed (+ fee_overdue 当首次写入即过期)
  4. POST /api/v1/franchise/fee-bills/{id}/record-payment → franchise.fee_paid
  5. GET  /api/v1/franchise/fee-bills/overdue 自动标记   → franchise.fee_overdue（每条新标记账单独立事件）

service 层：
  6. royalty_calculator.generate_monthly_bills          → franchise.royalty_calculated
  7. franchise_settlement_service.generate_monthly_settlement → franchise.settlement_generated

策略：unittest.mock.patch 拦截各模块本地的 emit_event，
不依赖任何数据库连接 / Redis 实例。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# 公共测试常量与工具
# ─────────────────────────────────────────────────────────────────────────────

TENANT_UUID = uuid4()
TENANT_ID = str(TENANT_UUID)
FRANCHISEE_ID = str(uuid4())
BILL_ID = str(uuid4())


def _patched_create_task(coro):
    """让 asyncio.create_task 同步推进协程，避免事件循环竞争。

    在 Python 测试中，emit_event 通常被 mock 成 AsyncMock；
    我们仍需 close 协程对象避免 RuntimeWarning。
    """
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


# ═════════════════════════════════════════════════════════════════════════════
# Routes 层：franchise_v5_routes.py
# ═════════════════════════════════════════════════════════════════════════════


class TestFranchiseV5RoutesEvents:
    """加盟商档案路由 → APPLIED / ACTIVATED / SUSPENDED / TERMINATED 事件"""

    @pytest.mark.asyncio
    async def test_create_franchisee_emits_applied(self):
        """POST /franchisees 成功 → emit FranchiseEventType.APPLIED"""
        from services.tx_org.src.api.franchise_v5_routes import (
            FranchiseeCreateV5,
            create_franchisee_v5,
        )

        body = FranchiseeCreateV5(
            name="测试加盟商",
            company_name="测试公司",
            contact_phone="13800000001",
            region="湖南/长沙",
            store_name="测试门店",
            store_address="长沙市XX路1号",
            franchise_type="standard",
        )

        db = AsyncMock()
        db.execute.return_value = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "services.tx_org.src.api.franchise_v5_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_v5_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            result = await create_franchisee_v5(body=body, x_tenant_id=TENANT_ID, db=db)

        assert result["ok"] is True
        # 由于 create_task 被同步替换，emit_event 被同步调用一次
        assert mock_emit.call_count == 1
        kw = mock_emit.call_args.kwargs
        assert kw["event_type"].value == "franchise.franchisee_applied"
        assert kw["tenant_id"] == TENANT_ID
        assert kw["source_service"] == "tx-org"
        assert "franchisee_id" in kw["payload"]
        assert kw["payload"]["name"] == "测试加盟商"
        assert kw["payload"]["franchise_type"] == "standard"
        assert kw["stream_id"] == kw["payload"]["franchisee_id"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status_value,expected_event",
        [
            ("active", "franchise.franchisee_activated"),
            ("operating", "franchise.franchisee_activated"),
            ("signing", "franchise.franchisee_signing"),
            ("suspended", "franchise.franchisee_suspended"),
            ("terminated", "franchise.franchisee_terminated"),
        ],
    )
    async def test_update_franchisee_status_emits_lifecycle_event(self, status_value, expected_event):
        """PUT /franchisees/{id} 含 status 字段 → emit 对应生命周期事件"""
        from services.tx_org.src.api.franchise_v5_routes import (
            FranchiseeUpdateV5,
            update_franchisee_v5,
        )

        db = AsyncMock()
        db.execute.return_value = MagicMock()
        db.commit = AsyncMock()

        body = FranchiseeUpdateV5(status=status_value)

        with patch(
            "services.tx_org.src.api.franchise_v5_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_v5_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            await update_franchisee_v5(
                franchisee_id=FRANCHISEE_ID,
                body=body,
                x_tenant_id=TENANT_ID,
                db=db,
            )

        assert mock_emit.call_count == 1
        kw = mock_emit.call_args.kwargs
        assert kw["event_type"].value == expected_event
        assert kw["tenant_id"] == TENANT_ID
        assert kw["stream_id"] == FRANCHISEE_ID
        assert kw["payload"]["new_status"] == status_value
        assert kw["source_service"] == "tx-org"

    @pytest.mark.asyncio
    async def test_update_franchisee_no_status_no_event(self):
        """PUT /franchisees/{id} 仅修改档案字段（无 status） → 不发射事件"""
        from services.tx_org.src.api.franchise_v5_routes import (
            FranchiseeUpdateV5,
            update_franchisee_v5,
        )

        db = AsyncMock()
        db.execute.return_value = MagicMock()
        db.commit = AsyncMock()

        body = FranchiseeUpdateV5(name="新名称", contact_phone="13900000000")

        with patch(
            "services.tx_org.src.api.franchise_v5_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_v5_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            await update_franchisee_v5(
                franchisee_id=FRANCHISEE_ID,
                body=body,
                x_tenant_id=TENANT_ID,
                db=db,
            )

        # 状态未变更：不应发射任何事件
        mock_emit.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# Routes 层：franchise_fee_routes.py — 账单生成 / 收款 / 逾期
# ═════════════════════════════════════════════════════════════════════════════


class TestFranchiseFeeRoutesEvents:
    """加盟费账单路由 → FEE_BILLED / FEE_PAID / FEE_OVERDUE 事件"""

    @pytest.mark.asyncio
    async def test_create_fee_bill_future_due_emits_billed_only(self):
        """create_fee_bill 到期日在未来 → 仅发射 FEE_BILLED"""
        from services.tx_org.src.api.franchise_fee_routes import (
            CreateFeeBillReq,
            create_fee_bill,
        )

        # 模拟 _set_rls 返回 UUID + 加盟商存在
        db = AsyncMock()

        # _set_rls 内 db.execute；接着 fran_res = SELECT id, name FROM franchisees ...
        # 然后 INSERT。我们让 db.execute 返回 MagicMock，但 fetchone 返回真实加盟商
        franchisee_row = MagicMock()
        franchisee_row.__getitem__ = lambda self, idx: {
            0: uuid.UUID(FRANCHISEE_ID),
            1: "测试加盟商",
        }[idx]

        fran_res = MagicMock()
        fran_res.fetchone.return_value = franchisee_row

        # 第 1 次 execute = set_config（_set_rls）
        # 第 2 次 = 校验加盟商存在
        # 第 3 次 = INSERT
        db.execute.side_effect = [MagicMock(), fran_res, MagicMock()]
        db.commit = AsyncMock()

        req = CreateFeeBillReq(
            franchise_id=FRANCHISEE_ID,
            bill_type="royalty",
            amount_fen=500_000,  # 5000 元
            due_date="2099-12-31",  # 远期到期日，确保不会标记 overdue
            billing_period="2026-04",
        )

        with patch(
            "services.tx_org.src.api.franchise_fee_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_fee_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            result = await create_fee_bill(
                req=req,
                x_tenant_id=TENANT_ID,
                x_operator="test_op",
                db=db,
            )

        assert result["ok"] is True
        assert result["data"]["status"] == "pending"
        # 期望仅 1 个事件（FEE_BILLED）
        assert mock_emit.call_count == 1
        kw = mock_emit.call_args.kwargs
        assert kw["event_type"].value == "franchise.fee_billed"
        assert kw["payload"]["amount_fen"] == 500_000
        assert kw["payload"]["bill_type"] == "royalty"
        assert kw["payload"]["franchise_id"] == FRANCHISEE_ID
        assert kw["payload"]["initial_status"] == "pending"
        assert kw["metadata"]["operator_id"] == "test_op"

    @pytest.mark.asyncio
    async def test_create_fee_bill_past_due_emits_billed_and_overdue(self):
        """create_fee_bill 到期日已过去 → 发射 FEE_BILLED + FEE_OVERDUE"""
        from services.tx_org.src.api.franchise_fee_routes import (
            CreateFeeBillReq,
            create_fee_bill,
        )

        db = AsyncMock()
        franchisee_row = MagicMock()
        franchisee_row.__getitem__ = lambda self, idx: {
            0: uuid.UUID(FRANCHISEE_ID),
            1: "测试加盟商",
        }[idx]
        fran_res = MagicMock()
        fran_res.fetchone.return_value = franchisee_row
        db.execute.side_effect = [MagicMock(), fran_res, MagicMock()]
        db.commit = AsyncMock()

        req = CreateFeeBillReq(
            franchise_id=FRANCHISEE_ID,
            bill_type="ad_fee",
            amount_fen=100_000,
            due_date="2020-01-01",  # 已过期
            billing_period="2020-01",
        )

        with patch(
            "services.tx_org.src.api.franchise_fee_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_fee_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            await create_fee_bill(
                req=req,
                x_tenant_id=TENANT_ID,
                x_operator=None,
                db=db,
            )

        assert mock_emit.call_count == 2
        events = [c.kwargs["event_type"].value for c in mock_emit.call_args_list]
        assert "franchise.fee_billed" in events
        assert "franchise.fee_overdue" in events

        overdue_call = [c for c in mock_emit.call_args_list if c.kwargs["event_type"].value == "franchise.fee_overdue"][
            0
        ]
        assert overdue_call.kwargs["payload"]["unpaid_fen"] == 100_000
        assert overdue_call.kwargs["payload"]["reason"] == "due_date_in_past_at_creation"

    @pytest.mark.asyncio
    async def test_record_payment_emits_fee_paid(self):
        """POST /fee-bills/{id}/record-payment 成功 → emit FEE_PAID"""
        from services.tx_org.src.api.franchise_fee_routes import (
            RecordPaymentReq,
            record_payment,
        )

        db = AsyncMock()
        # _set_rls -> execute；_fetch_bill 内 db.execute -> fetchone
        bill_row_values = (
            uuid.UUID(BILL_ID),  # id
            uuid.UUID(FRANCHISEE_ID),  # franchise_id
            "测试加盟商",  # franchise_name
            "royalty",  # bill_type
            500_000,  # amount_fen
            0,  # paid_fen
            "pending",  # status
            date(2099, 12, 31),  # due_date
            "2026-04",  # billing_period
            None,
            None,  # created_at, updated_at
        )
        bill_row = MagicMock()
        bill_row.__getitem__ = lambda self, idx: bill_row_values[idx]
        bill_res = MagicMock()
        bill_res.fetchone.return_value = bill_row

        # 顺序：_set_rls / _fetch_bill / INSERT payment / UPDATE bill
        db.execute.side_effect = [
            MagicMock(),  # set_config
            bill_res,  # SELECT bill detail
            MagicMock(),  # INSERT payment
            MagicMock(),  # UPDATE bill
        ]
        db.commit = AsyncMock()

        req = RecordPaymentReq(
            paid_amount_fen=500_000,  # 全额支付
            payment_method="transfer",
            payment_date="2026-04-15",
            receipt_no="RC-001",
        )

        with patch(
            "services.tx_org.src.api.franchise_fee_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_fee_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            result = await record_payment(
                req=req,
                bill_id=BILL_ID,
                x_tenant_id=TENANT_ID,
                x_operator="cashier_001",
                db=db,
            )

        assert result["ok"] is True
        assert result["data"]["bill_status"] == "paid"
        assert mock_emit.call_count == 1
        kw = mock_emit.call_args.kwargs
        assert kw["event_type"].value == "franchise.fee_paid"
        assert kw["stream_id"] == BILL_ID
        assert kw["payload"]["paid_amount_fen"] == 500_000
        assert kw["payload"]["fully_paid"] is True
        assert kw["payload"]["bill_status"] == "paid"
        assert kw["payload"]["payment_method"] == "transfer"
        assert kw["metadata"]["receipt_no"] == "RC-001"
        assert kw["metadata"]["operator_id"] == "cashier_001"

    @pytest.mark.asyncio
    async def test_record_payment_partial_emits_fee_paid_with_partial_status(self):
        """部分付款 → 仍 emit FEE_PAID，但 fully_paid=False / bill_status=partial"""
        from services.tx_org.src.api.franchise_fee_routes import (
            RecordPaymentReq,
            record_payment,
        )

        db = AsyncMock()
        bill_row_values = (
            uuid.UUID(BILL_ID),
            uuid.UUID(FRANCHISEE_ID),
            "测试加盟商",
            "royalty",
            500_000,
            0,
            "pending",
            date(2099, 12, 31),
            "2026-04",
            None,
            None,
        )
        bill_row = MagicMock()
        bill_row.__getitem__ = lambda self, idx: bill_row_values[idx]
        bill_res = MagicMock()
        bill_res.fetchone.return_value = bill_row
        db.execute.side_effect = [MagicMock(), bill_res, MagicMock(), MagicMock()]
        db.commit = AsyncMock()

        req = RecordPaymentReq(paid_amount_fen=200_000)  # 部分支付

        with patch(
            "services.tx_org.src.api.franchise_fee_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_fee_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            await record_payment(
                req=req,
                bill_id=BILL_ID,
                x_tenant_id=TENANT_ID,
                x_operator=None,
                db=db,
            )

        kw = mock_emit.call_args.kwargs
        assert kw["payload"]["fully_paid"] is False
        assert kw["payload"]["bill_status"] == "partial"
        assert kw["payload"]["remaining_fen"] == 300_000

    @pytest.mark.asyncio
    async def test_list_overdue_bills_auto_mark_emits_per_bill(self):
        """GET /fee-bills/overdue 自动标记 → 每条新标记账单独立 emit FEE_OVERDUE"""
        from services.tx_org.src.api.franchise_fee_routes import list_overdue_bills

        db = AsyncMock()
        # 模拟 UPDATE ... RETURNING 返回 2 条新标记行
        marked_rows = []
        for i in range(2):
            row = MagicMock()
            row._mapping = {
                "id": uuid.uuid4(),
                "franchise_id": uuid.UUID(FRANCHISEE_ID),
                "bill_type": "royalty",
                "amount_fen": 200_000,
                "paid_fen": 0,
                "due_date": date(2025, 1, 1),
            }
            marked_rows.append(row)

        marked_res = MagicMock()
        marked_res.fetchall.return_value = marked_rows

        # COUNT(*) result
        count_res = MagicMock()
        count_res.scalar.return_value = 0  # 列表查询不重要

        # SELECT items result
        rows_res = MagicMock()
        rows_res.fetchall.return_value = []

        # 顺序：set_config / UPDATE ... RETURNING / COUNT / SELECT
        db.execute.side_effect = [MagicMock(), marked_res, count_res, rows_res]
        db.commit = AsyncMock()

        with patch(
            "services.tx_org.src.api.franchise_fee_routes.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.api.franchise_fee_routes.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            result = await list_overdue_bills(
                franchise_id=None,
                bill_type=None,
                page=1,
                size=20,
                x_tenant_id=TENANT_ID,
                db=db,
            )

        assert result["ok"] is True
        # 2 条新标记 → 2 个 FEE_OVERDUE 事件
        assert mock_emit.call_count == 2
        for call in mock_emit.call_args_list:
            assert call.kwargs["event_type"].value == "franchise.fee_overdue"
            assert call.kwargs["payload"]["reason"] == "auto_mark_pending_past_due"
            assert call.kwargs["payload"]["unpaid_fen"] == 200_000


# ═════════════════════════════════════════════════════════════════════════════
# Service 层：royalty_calculator + franchise_settlement_service
# ═════════════════════════════════════════════════════════════════════════════


class TestRoyaltyCalculatorEvents:
    """月度分润账单批处理 → ROYALTY_CALCULATED 事件"""

    @pytest.mark.asyncio
    async def test_generate_monthly_bills_emits_royalty_calculated_per_bill(self):
        """generate_monthly_bills 每写入 1 个 royalty_bill → emit 1 个 ROYALTY_CALCULATED"""
        from services.tx_org.src.models.franchise import (
            Franchisee,
            FranchiseeStatus,
        )
        from services.tx_org.src.services.royalty_calculator import RoyaltyCalculator

        franchisee = Franchisee(
            tenant_id=TENANT_UUID,
            franchisee_name="测试加盟商A",
            contact_name="老板",
            contact_phone="13800000000",
            contract_start=date(2024, 1, 1),
            contract_end=date(2026, 12, 31),
            royalty_rate=0.05,
            royalty_tiers=[],
            status=FranchiseeStatus.ACTIVE,
        )
        object.__setattr__(franchisee, "management_fee_fen", 200_000)

        db = AsyncMock()

        with patch.object(
            RoyaltyCalculator,
            "_fetch_active_franchisees",
            return_value=[franchisee],
        ), patch.object(
            RoyaltyCalculator,
            "_fetch_franchisee_store_ids",
            return_value=[uuid4()],
        ), patch.object(
            RoyaltyCalculator,
            "_sum_store_revenue_fen",
            return_value=10_000_000,  # 10 万元营业额（分）
        ), patch.object(
            RoyaltyCalculator,
            "_find_existing_bill",
            return_value=None,  # 无已有账单
        ), patch.object(
            RoyaltyCalculator,
            "_insert_royalty_bill",
            return_value=None,
        ), patch(
            "services.tx_org.src.services.royalty_calculator.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.services.royalty_calculator.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            bills = await RoyaltyCalculator.generate_monthly_bills(
                tenant_id=TENANT_UUID,
                bill_month="2026-04",
                db=db,
            )

        assert len(bills) == 1
        # 每个账单应有 1 个 ROYALTY_CALCULATED 事件
        assert mock_emit.call_count == 1
        kw = mock_emit.call_args.kwargs
        assert kw["event_type"].value == "franchise.royalty_calculated"
        assert kw["tenant_id"] == TENANT_ID
        assert kw["source_service"] == "tx-org"
        assert kw["payload"]["bill_month"] == "2026-04"
        assert kw["payload"]["revenue_fen"] == 10_000_000
        # royalty_amount = 10万 * 5% = 5000 元 = 500_000 分
        assert kw["payload"]["royalty_amount_fen"] == 500_000
        assert kw["payload"]["management_fee_fen"] == 200_000
        assert kw["payload"]["total_due_fen"] == 700_000

    @pytest.mark.asyncio
    async def test_generate_monthly_bills_skips_event_when_existing_bill(self):
        """已存在当期账单时跳过写入 → 不发射事件"""
        from services.tx_org.src.models.franchise import (
            Franchisee,
            FranchiseeStatus,
        )
        from services.tx_org.src.services.royalty_calculator import RoyaltyCalculator

        franchisee = Franchisee(
            tenant_id=TENANT_UUID,
            franchisee_name="测试加盟商A",
            contact_name="老板",
            contact_phone="13800000000",
            contract_start=date(2024, 1, 1),
            contract_end=date(2026, 12, 31),
            royalty_rate=0.05,
            royalty_tiers=[],
            status=FranchiseeStatus.ACTIVE,
        )
        object.__setattr__(franchisee, "management_fee_fen", 200_000)

        db = AsyncMock()
        existing_id = uuid4()
        with patch.object(
            RoyaltyCalculator,
            "_fetch_active_franchisees",
            return_value=[franchisee],
        ), patch.object(
            RoyaltyCalculator,
            "_fetch_franchisee_store_ids",
            return_value=[uuid4()],
        ), patch.object(
            RoyaltyCalculator,
            "_sum_store_revenue_fen",
            return_value=10_000_000,
        ), patch.object(
            RoyaltyCalculator,
            "_find_existing_bill",
            return_value=existing_id,  # 命中已有账单
        ), patch(
            "services.tx_org.src.services.royalty_calculator.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.services.royalty_calculator.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            bills = await RoyaltyCalculator.generate_monthly_bills(
                tenant_id=TENANT_UUID,
                bill_month="2026-04",
                db=db,
            )

        assert bills == []
        mock_emit.assert_not_called()


class TestFranchiseSettlementServiceEvents:
    """月结算单生成 → SETTLEMENT_GENERATED 事件"""

    @pytest.mark.asyncio
    async def test_generate_monthly_settlement_emits_event(self):
        """generate_monthly_settlement 写入 franchise_settlements 后 → emit SETTLEMENT_GENERATED"""
        from services.tx_org.src.models.franchise import (
            Franchisee,
            FranchiseeStatus,
        )
        from services.tx_org.src.services.franchise_settlement_service import (
            FranchiseSettlementService,
            SettlementStatus,
        )

        franchisee = Franchisee(
            tenant_id=TENANT_UUID,
            franchisee_name="测试加盟商B",
            contact_name="老板",
            contact_phone="13800000001",
            contract_start=date(2024, 1, 1),
            contract_end=date(2026, 12, 31),
            royalty_rate=0.05,
            royalty_tiers=[],
            status=FranchiseeStatus.ACTIVE,
        )
        object.__setattr__(franchisee, "management_fee_fen", 200_000)

        service = FranchiseSettlementService()

        db = AsyncMock()
        # _find_existing_settlement → None（无已有记录）
        # _sum_store_revenue_fen → 100 万分
        db.fetch_one.side_effect = [
            None,
            {"total_fen": 100_000_000},
        ]
        db.fetch_all.return_value = [{"store_id": str(uuid4())}]
        db.execute.return_value = MagicMock()

        with patch.object(
            service,
            "_fetch_franchisee",
            return_value=franchisee,
        ), patch(
            "services.tx_org.src.services.franchise_settlement_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.services.franchise_settlement_service.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            settlement = await service.generate_monthly_settlement(
                franchisee_id=FRANCHISEE_ID,
                year=2026,
                month=4,
                tenant_id=TENANT_ID,
                db=db,
            )

        assert settlement.status == SettlementStatus.DRAFT
        assert mock_emit.call_count == 1
        kw = mock_emit.call_args.kwargs
        assert kw["event_type"].value == "franchise.settlement_generated"
        assert kw["tenant_id"] == TENANT_ID
        assert kw["stream_id"] == str(settlement.id)
        assert kw["payload"]["franchisee_id"] == FRANCHISEE_ID
        assert kw["payload"]["year"] == 2026
        assert kw["payload"]["month"] == 4
        assert kw["payload"]["revenue_fen"] == 100_000_000
        # royalty = 100 万元 × 5% = 5 万元 = 5_000_000 分
        assert kw["payload"]["royalty_amount_fen"] == 5_000_000
        assert kw["payload"]["mgmt_fee_fen"] == 200_000
        assert kw["payload"]["total_amount_fen"] == 5_200_000
        assert kw["payload"]["status"] == "draft"

    @pytest.mark.asyncio
    async def test_generate_monthly_settlement_idempotent_no_event(self):
        """已存在当月结算单 → 不发射事件"""
        from services.tx_org.src.services.franchise_settlement_service import (
            FranchiseSettlementService,
        )

        service = FranchiseSettlementService()
        existing_id = uuid4()
        db = AsyncMock()
        db.fetch_one.side_effect = [
            {
                "id": str(existing_id),
                "tenant_id": TENANT_ID,
                "franchisee_id": FRANCHISEE_ID,
                "year": 2026,
                "month": 4,
                "revenue_fen": 100_000_000,
                "royalty_amount_fen": 5_000_000,
                "mgmt_fee_fen": 200_000,
                "total_amount_fen": 5_200_000,
                "status": "draft",
                "due_date": date(2026, 5, 15),
                "paid_at": None,
                "payment_ref": None,
            },
        ]

        with patch(
            "services.tx_org.src.services.franchise_settlement_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "services.tx_org.src.services.franchise_settlement_service.asyncio.create_task",
            side_effect=_patched_create_task,
        ):
            settlement = await service.generate_monthly_settlement(
                franchisee_id=FRANCHISEE_ID,
                year=2026,
                month=4,
                tenant_id=TENANT_ID,
                db=db,
            )

        assert str(settlement.id) == str(existing_id)
        mock_emit.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# 枚举完整性
# ═════════════════════════════════════════════════════════════════════════════


class TestFranchiseEventTypeRegistry:
    """FranchiseEventType 注册完整性 — 防止漂移"""

    def test_franchise_event_type_has_11_members(self):
        from shared.events.src.event_types import FranchiseEventType

        assert len(list(FranchiseEventType)) == 11

    def test_franchise_event_type_in_all_event_enums(self):
        from shared.events.src.event_types import (
            ALL_EVENT_ENUMS,
            FranchiseEventType,
        )

        assert FranchiseEventType in ALL_EVENT_ENUMS

    def test_franchise_domain_in_stream_maps(self):
        from shared.events.src.event_types import (
            DOMAIN_STREAM_MAP,
            DOMAIN_STREAM_TYPE_MAP,
            resolve_stream_key,
            resolve_stream_type,
        )

        assert DOMAIN_STREAM_MAP["franchise"] == "tx_franchise_events"
        assert DOMAIN_STREAM_TYPE_MAP["franchise"] == "franchise"
        assert resolve_stream_key("franchise.fee_paid") == "tx_franchise_events"
        assert resolve_stream_type("franchise.fee_paid") == "franchise"
