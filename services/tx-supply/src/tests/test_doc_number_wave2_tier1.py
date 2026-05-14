"""Tier 1 — doc_number wave2：调拨单/报废单/调整单写路径接入契约测试（PRD-03 / Wave2 方案 A）

测试场景基于真实餐厅操作（CLAUDE.md §20）：

  1. 调拨单：徐记 2026-05-14 长沙总店 → 岳麓店 五花肉调拨 → doc_number TR20260514-001
  2. 报废单：五花肉过期报废 → doc_number WS20260514-001（waste 分配，usage/transfer 不分配）
  3. 调整单：月末盘点盘盈/盘亏 → doc_number AJ20260514-001
  4. Graceful degradation：gen_doc_number raise DocNumberError → 业务继续 + doc_number=None + warning 记录
  5. Migration round-trip：v421→v422 upgrade/downgrade 幂等

mock 风格：参考 test_doc_number_wave1_tier1.py AsyncMock 模式（PR-03B）。
不依赖真 PG（沿用 PR-03A/03B 同约定；wave1 真 PG advisory_lock 已覆盖核心引擎）。
"""

from __future__ import annotations

import sys

# 本机 Python 3.9 跳过 — shared.ontology 用 PEP 604 `X | None` (requires 3.10+)
# CI Python 3.11 原生通过。与 test_auto_deduction_row_lock_tier1.py / wave1 同模式。
if sys.version_info < (3, 10):
    import pytest
    pytest.skip(
        "需 Python 3.10+ (shared.ontology PEP 604 union)；CI Python 3.11 跑通",
        allow_module_level=True,
    )

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 固定常量 ────────────────────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_STORE_CS = "33333333-cccc-cccc-cccc-333333333333"    # 长沙总店（调出）
_STORE_YL = "44444444-dddd-dddd-dddd-444444444444"    # 岳麓店（调入）
_INGREDIENT_ID = "66666666-ffff-ffff-ffff-666666666666"

_DOC_NUMBER_TR = "TR20260514-001"
_DOC_NUMBER_WS = "WS20260514-001"
_DOC_NUMBER_AJ = "AJ20260514-001"

_NOW = datetime(2026, 5, 14, 8, 0, tzinfo=timezone.utc)


# ─── mock 工厂 ───────────────────────────────────────────────────────────────


def _mk_ingredient_mock(qty: float = 200.0) -> MagicMock:
    ing = MagicMock()
    ing.current_quantity = qty
    ing.min_quantity = 50.0
    ing.unit_price_fen = 2800
    ing.status = "normal"
    ing.unit = "kg"
    return ing


def _make_execute_side_effect(
    doc_type: str,
    template: str,
    seq_scope: str,
    ingredient_mock: MagicMock,
    captured_updates: list[dict],
) -> AsyncMock:
    """构造 db.execute side_effect，捕获 doc_number UPDATE 调用。"""

    async def side_effect(query, params=None):
        sql = str(query)
        mock_result = MagicMock()

        if "set_config" in sql:
            return mock_result
        if "doc_number_rules" in sql and "SELECT" in sql.upper():
            mock_result.mappings.return_value.first.return_value = {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "doc_type": doc_type,
                "template": template,
                "seq_scope": seq_scope,
                "is_active": True,
            }
            return mock_result
        if "pg_advisory_xact_lock" in sql:
            return mock_result
        if "doc_number_sequences" in sql and "INSERT" in sql.upper():
            mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
            return mock_result
        if "transfer_orders" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
            captured_updates.append(dict(params) if params else {})
            return mock_result
        if "ingredient_transactions" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
            captured_updates.append(dict(params) if params else {})
            return mock_result
        # ORM select for ingredient
        mock_result.scalar_one_or_none.return_value = ingredient_mock
        return mock_result

    return side_effect


# ─── 1. 调拨单写路径 ─────────────────────────────────────────────────────────


class TestTransferDocNumber:
    """调拨单创建时 doc_number 应由 doc_number_service 生成并写入 transfer_orders。"""

    @pytest.mark.asyncio
    async def test_create_transfer_order_generates_doc_number(self):
        """徐记 2026-05-14 长沙总店 → 岳麓店 五花肉调拨：doc_number 应为 TR20260514-001。

        GIVEN 徐记长沙总店库存充裕，岳麓店五花肉告急
        WHEN  仓管创建门店间调拨申请
        THEN  调拨单写入 DB 时同时写入 doc_number='TR20260514-001'
        AND   结果字典中包含 doc_number 字段
        """
        from services.tx_supply.src.services.transfer_service import create_transfer_order

        updated_rows: list[dict] = []

        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "transfer",
                    "template": "TR{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "transfer_orders" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                updated_rows.append(dict(params) if params else {})
                return mock_result
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "services.tx_supply.src.services.transfer_service.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_TR),
        ):
            result = await create_transfer_order(
                tenant_id=_TENANT_XUJI,
                from_store_id=_STORE_CS,
                to_store_id=_STORE_YL,
                items=[
                    {
                        "ingredient_id": _INGREDIENT_ID,
                        "ingredient_name": "五花肉",
                        "requested_quantity": 20,
                        "unit": "kg",
                    }
                ],
                db=db,
                transfer_reason="岳麓店应急补货",
            )

        assert result["doc_number"] == _DOC_NUMBER_TR, (
            f"调拨单结果应含 doc_number='{_DOC_NUMBER_TR}'，实际: {result}"
        )

    @pytest.mark.asyncio
    async def test_create_transfer_order_doc_number_written_to_db(self):
        """doc_number 必须通过 SQL UPDATE 写入 transfer_orders，不能仅在内存。

        GIVEN 调拨申请创建成功
        WHEN  create_transfer_order 完成
        THEN  UPDATE transfer_orders SET doc_number SQL 被执行，参数含 doc_number
        AND   财务稽查可按 TR 单号直接查库查表
        """
        from services.tx_supply.src.services.transfer_service import create_transfer_order

        updated_rows: list[dict] = []
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "transfer",
                    "template": "TR{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "transfer_orders" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                updated_rows.append(dict(params) if params else {})
                return mock_result
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "services.tx_supply.src.services.transfer_service.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_TR),
        ):
            await create_transfer_order(
                tenant_id=_TENANT_XUJI,
                from_store_id=_STORE_CS,
                to_store_id=_STORE_YL,
                items=[
                    {
                        "ingredient_id": _INGREDIENT_ID,
                        "ingredient_name": "五花肉",
                        "requested_quantity": 20,
                        "unit": "kg",
                    }
                ],
                db=db,
            )

        assert any(
            p.get("doc_number") == _DOC_NUMBER_TR for p in updated_rows
        ), "doc_number 必须通过 SQL UPDATE 写入 transfer_orders，不能只在返回字典"


# ─── 2. 报废单写路径 ─────────────────────────────────────────────────────────


class TestWasteDocNumber:
    """报废出库时 doc_number 应由 doc_number_service 生成并写入 ingredient_transactions。"""

    @pytest.mark.asyncio
    async def test_waste_issue_generates_doc_number(self):
        """五花肉过期报废 5kg：ingredient_transactions.doc_number='WS20260514-001'。

        GIVEN 一批五花肉临期报废
        WHEN  仓管执行报废出库（reason='waste'）
        THEN  ingredient_transactions 流水 doc_number='WS20260514-001'
        AND   食药监稽查可按 WS 单号追溯报废原因
        """
        from services.tx_supply.src.services.inventory_io import issue_stock

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        updated_rows: list[dict] = []

        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "waste",
                    "template": "WS{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "ingredient_transactions" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                updated_rows.append(dict(params) if params else {})
                return mock_result
            # FIFO batch query
            mock_result.all.return_value = []
            # ORM ingredient select
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        # mock FIFO batches so there's stock to deduct
        with patch(
            "services.tx_supply.src.services.inventory_io._get_batch_remaining",
            new=AsyncMock(
                return_value=[
                    {
                        "batch_no": "BATCH-001",
                        "remaining": 100.0,
                        "unit_cost_fen": 2800,
                        "expiry_date": None,
                        "created_at": _NOW,
                    }
                ]
            ),
        ), patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_WS),
        ):
            result = await issue_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=5.0,
                reason="waste",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") == _DOC_NUMBER_WS, (
            f"报废出库结果应含 doc_number='{_DOC_NUMBER_WS}'，实际: {result}"
        )
        assert any(
            p.get("doc_number") == _DOC_NUMBER_WS for p in updated_rows
        ), "doc_number 必须通过 SQL UPDATE 写入 ingredient_transactions"

    @pytest.mark.asyncio
    async def test_waste_issue_multi_batch_all_get_doc_number(self):
        """报废出库跨多 batch FIFO：ANY(:ids::uuid[]) 单条 SQL 写入全部 batch 流水。

        GIVEN 五花肉有两个 FIFO batch（batch-A remaining=3.0, batch-B remaining=10.0）
        WHEN  报废 8.0kg（跨两个 batch：扣尽 batch-A 3.0 + 从 batch-B 扣 5.0）
        THEN  UPDATE ingredient_transactions 只执行 1 条 SQL（ANY(:ids::uuid[]) 批量）
        AND   该 SQL 的 ids 参数含 2 个事务 ID，doc_number == _DOC_NUMBER_WS
        （不应退化为 per-batch 逐条 UPDATE — P1#1 修法 invariant）
        """
        from services.tx_supply.src.services.inventory_io import issue_stock

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        updated_rows: list[dict] = []

        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "waste",
                    "template": "WS{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "ingredient_transactions" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                captured_params = dict(params) if params else {}
                updated_rows.append(captured_params)
                return mock_result
            # FIFO batch query
            mock_result.all.return_value = []
            # ORM ingredient select
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        # 两个 FIFO batch：batch-A remaining=3.0, batch-B remaining=10.0
        # quantity=8.0 → FIFO 扣 3.0（batch-A 耗尽）+ 5.0（batch-B 部分）= 2 条 ingredient_transactions
        with patch(
            "services.tx_supply.src.services.inventory_io._get_batch_remaining",
            new=AsyncMock(
                return_value=[
                    {
                        "batch_no": "BATCH-A",
                        "remaining": 3.0,
                        "unit_cost_fen": 2800,
                        "expiry_date": None,
                        "created_at": _NOW,
                    },
                    {
                        "batch_no": "BATCH-B",
                        "remaining": 10.0,
                        "unit_cost_fen": 2900,
                        "expiry_date": None,
                        "created_at": _NOW,
                    },
                ]
            ),
        ), patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_WS),
        ):
            result = await issue_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=8.0,
                reason="waste",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") == _DOC_NUMBER_WS, (
            f"多 batch 报废结果应含 doc_number='{_DOC_NUMBER_WS}'，实际: {result}"
        )
        # P1#1 核心 invariant：ANY(:ids::uuid[]) — 只有 1 条 UPDATE SQL
        assert len(updated_rows) == 1, (
            f"ANY(:ids::uuid[]) 修法应只执行 1 条 UPDATE SQL，实际执行了 {len(updated_rows)} 条"
            "（如果 >1 说明退化为 per-batch loop，P1#1 修法未生效）"
        )
        # 该单条 SQL 的 ids 参数应含 2 个事务 ID（2 个 batch 各生成 1 条 ingredient_transaction）
        ids_param = updated_rows[0].get("ids", [])
        assert len(ids_param) == 2, (
            f"ANY(:ids::uuid[]) 的 ids 参数应含 2 个事务 ID（对应 2 个 batch），实际: {ids_param}"
        )
        assert updated_rows[0].get("doc_number") == _DOC_NUMBER_WS, (
            f"UPDATE SQL 的 doc_number 参数应为 '{_DOC_NUMBER_WS}'，实际: {updated_rows[0]}"
        )

    @pytest.mark.asyncio
    async def test_usage_issue_no_doc_number(self):
        """BOM 扣料（reason='usage'）不分配报废单号 — doc_number 应为 None。

        GIVEN 出餐 BOM 自动扣料（后厨日常操作）
        WHEN  issue_stock(reason='usage') 执行
        THEN  doc_number=None（usage 无需单号，不浪费序号）
        AND   gen_doc_number 不被调用（reason 门控）
        """
        from services.tx_supply.src.services.inventory_io import issue_stock

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            mock_result.all.return_value = []
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        gen_mock = AsyncMock(return_value=_DOC_NUMBER_WS)
        with patch(
            "services.tx_supply.src.services.inventory_io._get_batch_remaining",
            new=AsyncMock(
                return_value=[
                    {
                        "batch_no": "BATCH-001",
                        "remaining": 100.0,
                        "unit_cost_fen": 2800,
                        "expiry_date": None,
                        "created_at": _NOW,
                    }
                ]
            ),
        ), patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=gen_mock,
        ):
            result = await issue_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=5.0,
                reason="usage",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") is None, (
            "usage 出库不应分配单号，doc_number 应为 None"
        )
        gen_mock.assert_not_called(), "usage 出库不应调用 gen_doc_number"

    @pytest.mark.asyncio
    async def test_transfer_issue_no_doc_number(self):
        """调拨出库（reason='transfer'）不分配报废单号 — doc_number 应为 None。

        GIVEN transfer_service.ship_transfer_order 触发子流水出库
        WHEN  issue_stock(reason='transfer') 执行
        THEN  doc_number=None（调拨主单号在 transfer_orders 表，子流水不重复分配）
        """
        from services.tx_supply.src.services.inventory_io import issue_stock

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            mock_result.all.return_value = []
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        gen_mock = AsyncMock(return_value=_DOC_NUMBER_WS)
        with patch(
            "services.tx_supply.src.services.inventory_io._get_batch_remaining",
            new=AsyncMock(
                return_value=[
                    {
                        "batch_no": "BATCH-001",
                        "remaining": 100.0,
                        "unit_cost_fen": 2800,
                        "expiry_date": None,
                        "created_at": _NOW,
                    }
                ]
            ),
        ), patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=gen_mock,
        ):
            result = await issue_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=5.0,
                reason="transfer",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") is None, (
            "transfer 出库子流水不应分配单号，doc_number 应为 None"
        )
        gen_mock.assert_not_called(), "transfer 出库不应调用 gen_doc_number"


# ─── 3. 调整单写路径 ─────────────────────────────────────────────────────────


class TestAdjustmentDocNumber:
    """盘点调整时 doc_number 应由 doc_number_service 生成并写入 ingredient_transactions。"""

    @pytest.mark.asyncio
    async def test_adjust_stock_surplus_generates_doc_number(self):
        """月末盘点盘盈 +5kg：ingredient_transactions.doc_number='AJ20260514-001'。

        GIVEN 徐记长沙总店 5/14 月末盘点，五花肉实际比账面多 5kg
        WHEN  仓管执行盘盈调整（quantity=+5）
        THEN  ingredient_transactions 流水 doc_number='AJ20260514-001'
        AND   财务对账可按 AJ 单号找到盘盈原因
        """
        from services.tx_supply.src.services.inventory_io import adjust_stock

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        updated_rows: list[dict] = []
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "adjustment",
                    "template": "AJ{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "ingredient_transactions" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                updated_rows.append(dict(params) if params else {})
                return mock_result
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_AJ),
        ):
            result = await adjust_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=5.0,
                reason="盘盈：月末盘点",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") == _DOC_NUMBER_AJ, (
            f"盘盈调整结果应含 doc_number='{_DOC_NUMBER_AJ}'，实际: {result}"
        )
        assert any(
            p.get("doc_number") == _DOC_NUMBER_AJ for p in updated_rows
        ), "doc_number 必须通过 SQL UPDATE 写入 ingredient_transactions"

    @pytest.mark.asyncio
    async def test_adjust_stock_shortage_generates_doc_number(self):
        """月末盘点盘亏 -3kg：doc_number 同样应生成（盘亏也需审计单号）。

        GIVEN 长沙总店 5/14 月末盘点，葱实际比账面少 3kg
        WHEN  仓管执行盘亏调整（quantity=-3）
        THEN  ingredient_transactions 流水 doc_number='AJ20260514-001'
        AND   盘盈盘亏均纳入调整单审计体系
        """
        from services.tx_supply.src.services.inventory_io import adjust_stock

        mock_ingredient = _mk_ingredient_mock(qty=50.0)
        updated_rows: list[dict] = []
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "adjustment",
                    "template": "AJ{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "ingredient_transactions" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                updated_rows.append(dict(params) if params else {})
                return mock_result
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_AJ),
        ):
            result = await adjust_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=-3.0,
                reason="盘亏：月末盘点",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") == _DOC_NUMBER_AJ, (
            f"盘亏调整结果应含 doc_number='{_DOC_NUMBER_AJ}'，实际: {result}"
        )
        assert any(
            p.get("doc_number") == _DOC_NUMBER_AJ for p in updated_rows
        ), "doc_number 必须通过 SQL UPDATE 写入 ingredient_transactions（盘亏同盘盈均需）"


# ─── 4. Graceful Degradation 验证 ────────────────────────────────────────────


class TestDocNumberGracefulDegradation:
    """doc_number 生成失败时，3 个 callsite 业务继续，返回 doc_number=None，记录 warning。

    参考 feedback_graceful_degradation_pattern.md — 辅助标识 infra 失败 fail-open 静默 fallback NULL。
    """

    @pytest.mark.asyncio
    async def test_transfer_order_degradation_on_doc_number_error(self):
        """调拨单：gen_doc_number raise DocNumberError → 调拨单创建仍成功，doc_number=None。

        GIVEN doc_number_rules 表未配置 transfer 规则（rule_missing）
        WHEN  create_transfer_order 调用
        THEN  调拨单创建成功（不抛出异常）
        AND   result['doc_number'] 为 None
        AND   logger.warning('doc_number_generate_skipped') 被调用
        """
        from services.tx_supply.src.services import transfer_service
        from services.tx_supply.src.services.doc_number_service import DocNumberError

        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch.object(
            transfer_service,
            "gen_doc_number",
            new=AsyncMock(side_effect=DocNumberError("rule_missing:transfer")),
        ), patch.object(
            transfer_service.logger,
            "warning",
        ) as mock_warn:
            result = await transfer_service.create_transfer_order(
                tenant_id=_TENANT_XUJI,
                from_store_id=_STORE_CS,
                to_store_id=_STORE_YL,
                items=[
                    {
                        "ingredient_id": _INGREDIENT_ID,
                        "ingredient_name": "五花肉",
                        "requested_quantity": 20,
                        "unit": "kg",
                    }
                ],
                db=db,
            )

        assert result.get("doc_number") is None, (
            "DocNumberError 时调拨单仍应创建成功，doc_number=None"
        )
        assert mock_warn.called, "应记录 doc_number_generate_skipped warning"

    @pytest.mark.asyncio
    async def test_waste_issue_degradation_on_doc_number_error(self):
        """报废出库：gen_doc_number raise DocNumberError → 出库仍成功，doc_number=None。

        GIVEN doc_number_rules 表未配置 waste 规则
        WHEN  issue_stock(reason='waste') 调用
        THEN  出库操作成功（不抛出异常，不影响食安 Tier 1）
        AND   result['doc_number'] 为 None
        AND   logger.warning 被调用
        """
        from services.tx_supply.src.services import inventory_io
        from services.tx_supply.src.services.doc_number_service import DocNumberError

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch.object(
            inventory_io,
            "gen_doc_number",
            new=AsyncMock(side_effect=DocNumberError("rule_missing:waste")),
        ), patch(
            "services.tx_supply.src.services.inventory_io._get_batch_remaining",
            new=AsyncMock(
                return_value=[
                    {
                        "batch_no": "BATCH-001",
                        "remaining": 100.0,
                        "unit_cost_fen": 2800,
                        "expiry_date": None,
                        "created_at": _NOW,
                    }
                ]
            ),
        ), patch.object(
            inventory_io.logger,
            "warning",
        ) as mock_warn:
            result = await inventory_io.issue_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=5.0,
                reason="waste",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") is None, (
            "DocNumberError 时报废出库仍应成功，doc_number=None"
        )
        assert mock_warn.called, "应记录 doc_number_generate_skipped warning"

    @pytest.mark.asyncio
    async def test_adjust_stock_degradation_on_doc_number_error(self):
        """盘点调整：gen_doc_number raise DocNumberError → 调整仍成功，doc_number=None。

        GIVEN doc_number_rules 表未配置 adjustment 规则
        WHEN  adjust_stock 调用
        THEN  调整操作成功（不抛出异常）
        AND   result['doc_number'] 为 None
        AND   logger.warning 被调用
        """
        from services.tx_supply.src.services import inventory_io
        from services.tx_supply.src.services.doc_number_service import DocNumberError

        mock_ingredient = _mk_ingredient_mock(qty=200.0)
        db = AsyncMock()

        async def execute_side(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=execute_side)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch.object(
            inventory_io,
            "gen_doc_number",
            new=AsyncMock(side_effect=DocNumberError("rule_missing:adjustment")),
        ), patch.object(
            inventory_io.logger,
            "warning",
        ) as mock_warn:
            result = await inventory_io.adjust_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=5.0,
                reason="盘盈",
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result.get("doc_number") is None, (
            "DocNumberError 时盘点调整仍应成功，doc_number=None"
        )
        assert mock_warn.called, "应记录 doc_number_generate_skipped warning"


# ─── 5. Migration Round-trip 验证 ────────────────────────────────────────────


class TestV422MigrationRoundTrip:
    """v422 migration upgrade/downgrade/idempotency 验证。

    使用 inspector-and-skip 模式验证幂等性（参考 v296/v418/v419 模式）。
    """

    def test_v422_upgrade_adds_doc_number_column(self):
        """v422 upgrade 后 transfer_orders 应含 doc_number 列。

        GIVEN alembic 已运行至 v421
        WHEN  upgrade 至 v422
        THEN  transfer_orders.doc_number 列存在（VARCHAR(64) NULL）
        AND   现有行回填为 'LEGACY-' + id 前 8 位
        """
        from shared.db_migrations.versions.v422_doc_number_wave2_backfill import upgrade, downgrade, _has_column

        # 模拟 inspector — 表存在，列不存在
        bind = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["transfer_orders"]
        inspector.get_columns.return_value = []  # 无 doc_number 列

        executed_sql: list[str] = []

        with patch(
            "shared.db_migrations.versions.v422_doc_number_wave2_backfill.op"
        ) as mock_op, patch(
            "shared.db_migrations.versions.v422_doc_number_wave2_backfill.sa.inspect",
            return_value=inspector,
        ):
            mock_op.get_bind.return_value = bind
            mock_op.execute.side_effect = lambda sql: executed_sql.append(str(sql))

            upgrade()

        assert any("ADD COLUMN" in s and "doc_number" in s for s in executed_sql), (
            "upgrade 应执行 ADD COLUMN doc_number"
        )
        assert any("LEGACY-" in s and "UPDATE" in s for s in executed_sql), (
            "upgrade 应执行历史行回填"
        )

    def test_v422_downgrade_drops_doc_number_column(self):
        """v422 downgrade 后 transfer_orders.doc_number 列应被移除。

        GIVEN alembic 已运行至 v422
        WHEN  downgrade 至 v421
        THEN  transfer_orders.doc_number 列被 DROP
        """
        from shared.db_migrations.versions.v422_doc_number_wave2_backfill import downgrade

        bind = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["transfer_orders"]
        inspector.get_columns.return_value = [{"name": "doc_number"}]  # 列已存在

        executed_sql: list[str] = []

        with patch(
            "shared.db_migrations.versions.v422_doc_number_wave2_backfill.op"
        ) as mock_op, patch(
            "shared.db_migrations.versions.v422_doc_number_wave2_backfill.sa.inspect",
            return_value=inspector,
        ):
            mock_op.get_bind.return_value = bind
            mock_op.execute.side_effect = lambda sql: executed_sql.append(str(sql))

            downgrade()

        assert any("DROP COLUMN" in s and "doc_number" in s for s in executed_sql), (
            "downgrade 应执行 DROP COLUMN doc_number"
        )

    def test_v422_upgrade_idempotent(self):
        """v422 upgrade 重复运行不抛错（inspector-and-skip 模式）。

        GIVEN v422 已经运行过（doc_number 列已存在）
        WHEN  upgrade 再次执行
        THEN  不执行 ALTER TABLE，不抛错
        AND   幂等性保证部署回滚/重试安全
        """
        from shared.db_migrations.versions.v422_doc_number_wave2_backfill import upgrade

        bind = MagicMock()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["transfer_orders"]
        inspector.get_columns.return_value = [{"name": "doc_number"}]  # 列已存在

        executed_sql: list[str] = []

        with patch(
            "shared.db_migrations.versions.v422_doc_number_wave2_backfill.op"
        ) as mock_op, patch(
            "shared.db_migrations.versions.v422_doc_number_wave2_backfill.sa.inspect",
            return_value=inspector,
        ):
            mock_op.get_bind.return_value = bind
            mock_op.execute.side_effect = lambda sql: executed_sql.append(str(sql))

            upgrade()  # 不抛错即通过

        assert not any("ADD COLUMN" in s for s in executed_sql), (
            "inspector-and-skip：列已存在时 upgrade 不应再执行 ADD COLUMN"
        )
