"""Tier 1 — doc_number wave1：4 类高频单据写路径接入契约测试（PRD-03 / 审计+财务）

§19 round-1 P0#1 之后：申购单移出 wave1，留 PRD-07（Phase 2）一并做建表 + 持久化。

测试场景基于真实餐厅操作（CLAUDE.md §20）：

  1. 采购单：徐记 2026-05-14 早晨第 1 个采购单 → doc_number 形如 PO20260514-001
  2. 盘点单：长沙总店 5 月月末盘点 → doc_number 形如 STK-202605-0001
  3. 收货单：供应商送货 → doc_number 形如 RV20260514-001
  4. 出入库流水：BOM 扣料 / 盘点调整 → doc_number 形如 IO20260514-0001

mock 风格：参考 test_doc_number_tier1.py AsyncMock 模式（PR-03A）。
不需要真 PG fixture（沿用 PR-03A 同约定）。
"""

from __future__ import annotations

import sys

# 本机 Python 3.9 跳过 — shared.ontology 用 PEP 604 `X | None` (requires 3.10+)
# CI Python 3.11 原生通过。与 test_auto_deduction_row_lock_tier1.py 同模式。
if sys.version_info < (3, 10):
    import pytest
    pytest.skip(
        "需 Python 3.10+ (shared.ontology PEP 604 union)；CI Python 3.11 跑通",
        allow_module_level=True,
    )

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 租户/门店固定 UUID ────────────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"  # 徐记海鲜
_STORE_CS = "33333333-cccc-cccc-cccc-333333333333"      # 长沙总店
_SUPPLIER_ID = "55555555-eeee-eeee-eeee-555555555555"   # 供应商
_INGREDIENT_ID = "66666666-ffff-ffff-ffff-666666666666"  # 食材

_DOC_NUMBER_PO = "PO20260514-001"
_DOC_NUMBER_RQ = "RQ20260514-001"
_DOC_NUMBER_STK = "STK-202605-0001"
_DOC_NUMBER_RV = "RV20260514-001"
_DOC_NUMBER_IO = "IO20260514-0001"

_NOW = datetime(2026, 5, 14, 8, 0, tzinfo=timezone.utc)


# ─── mock 工厂（仿照 test_doc_number_tier1.py）──────────────────────────────


def _mk_db_with_po_insert(doc_number: str) -> AsyncMock:
    """mock db.execute that captures calls; doc_number injected by mock."""
    db = AsyncMock()
    exec_results: list[MagicMock] = []

    async def execute_side_effect(query, params=None):
        sql = str(query)
        mock_result = MagicMock()
        # set_config call
        if "set_config" in sql:
            return mock_result
        # doc_number_rules lookup
        if "doc_number_rules" in sql and "SELECT" in sql.upper():
            mock_result.mappings.return_value.first.return_value = {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "doc_type": "purchase_order",
                "template": "PO{yyyy}{MM}{dd}-{seq:03d}",
                "seq_scope": "daily",
                "is_active": True,
            }
            return mock_result
        # advisory lock
        if "pg_advisory_xact_lock" in sql:
            return mock_result
        # sequence upsert
        if "doc_number_sequences" in sql and "INSERT" in sql.upper():
            mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
            return mock_result
        # purchase_orders INSERT
        if "purchase_orders" in sql and "INSERT" in sql.upper():
            exec_results.append(mock_result)
            return mock_result
        # purchase_order_items INSERT
        if "purchase_order_items" in sql and "INSERT" in sql.upper():
            return mock_result
        return mock_result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ─── 1. 采购单写路径 ──────────────────────────────────────────────────────────


class TestPurchaseOrderDocNumber:
    """采购单创建时 doc_number 应由 doc_number_service 生成并写入 purchase_orders"""

    @pytest.mark.asyncio
    async def test_create_po_generates_doc_number(self):
        """徐记 2026-05-14 早晨第 1 个采购单：doc_number 应为 PO20260514-001。

        GIVEN 徐记长沙总店早班开店 08:00
        WHEN  采购员创建当天第 1 个采购单（五花肉 50kg）
        THEN  采购单写入 DB 时同时写入 doc_number='PO20260514-001'
        AND   原有 po_number 字段保留（双轨兼容期）
        """
        from services.tx_supply.src.api.purchase_order_routes import create_purchase_order

        # mock doc_number_service.generate
        with patch(
            "services.tx_supply.src.api.purchase_order_routes.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_PO),
        ):
            db = _mk_db_with_po_insert(_DOC_NUMBER_PO)

            # 模拟 FastAPI 请求体
            from services.tx_supply.src.api.purchase_order_routes import (
                CreatePurchaseOrderRequest,
                POItemIn,
            )
            from decimal import Decimal

            body = CreatePurchaseOrderRequest(
                store_id=_STORE_CS,
                supplier_id=_SUPPLIER_ID,
                items=[
                    POItemIn(
                        ingredient_id=_INGREDIENT_ID,
                        ingredient_name="五花肉",
                        quantity=Decimal("50"),
                        unit="kg",
                        unit_price_fen=2800,
                    )
                ],
            )

            result = await create_purchase_order(
                body=body,
                x_tenant_id=_TENANT_XUJI,
                db=db,
            )

        assert result["ok"] is True
        assert result["data"]["doc_number"] == _DOC_NUMBER_PO
        # po_number 仍存在（双轨兼容）
        assert "po_id" in result["data"]

    @pytest.mark.asyncio
    async def test_create_po_doc_number_written_to_db(self):
        """doc_number 必须写入 purchase_orders INSERT 语句，不能仅返回但不落库。

        验证 SQL INSERT 包含 doc_number 参数（防止仅在返回字典加而未持久化）。
        """
        from services.tx_supply.src.api.purchase_order_routes import create_purchase_order, CreatePurchaseOrderRequest, POItemIn
        from decimal import Decimal

        written_params: list[dict] = []

        db = AsyncMock()

        async def capture_execute(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if params and "doc_number" in (params or {}):
                written_params.append(dict(params))
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "purchase_order",
                    "template": "PO{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            return mock_result

        db.execute = AsyncMock(side_effect=capture_execute)
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch(
            "services.tx_supply.src.api.purchase_order_routes.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_PO),
        ):
            body = CreatePurchaseOrderRequest(
                store_id=_STORE_CS,
                items=[
                    POItemIn(
                        ingredient_id=_INGREDIENT_ID,
                        ingredient_name="五花肉",
                        quantity=Decimal("50"),
                        unit="kg",
                        unit_price_fen=2800,
                    )
                ],
            )
            await create_purchase_order(body=body, x_tenant_id=_TENANT_XUJI, db=db)

        # doc_number 必须作为 SQL 参数被写入（不只是字典键）
        assert any(
            "doc_number" in p for p in written_params
        ), "doc_number 必须作为 SQL 参数写入 purchase_orders，不能只在返回字典里"


# ─── 2. 申购单写路径 ──────────────────────────────────────────────────────────


# ─── 2. 申购单（已移除 — §19 P0#2）────────────────────────────────────────────
# 申购单接入 doc_number 移交 PRD-07 申购模板系统（Phase 2 W9-W12）一并做：
#   - 仓库内无 CREATE TABLE requisitions migration（现有 service 是纯内存字典）
#   - 建表 + service 持久化是 PRD-07 自然范围
# 本 PR (PR-03B Wave1) 范围降为 4 类：PO / stocktake / receiving / inventory_io


# ─── 3. 盘点单写路径 ──────────────────────────────────────────────────────────


class TestStocktakeDocNumber:
    """盘点单创建时 doc_number 应由 doc_number_service 生成并写入 stocktakes"""

    @pytest.mark.asyncio
    async def test_create_stocktake_generates_doc_number(self):
        """长沙总店 5 月末月度盘点：doc_number='STK-202605-0001'。

        GIVEN 徐记长沙总店 2026-05-31 月末全盘
        WHEN  仓管创建盘点单
        THEN  盘点单写入 stocktakes 表，doc_number='STK-202605-0001'
        AND   doc_number 写入 DB INSERT 参数（不只在内存）
        """
        from services.tx_supply.src.services.stocktake_service import create_stocktake

        written_params: list[dict] = []

        # 模拟 db_mode = True（DB 模式）
        db = AsyncMock()

        async def capture_execute(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if params:
                params_dict = dict(params) if params else {}
                if "doc_number" in params_dict:
                    written_params.append(params_dict)
            # set_config
            if "set_config" in sql:
                return mock_result
            # doc_number_rules
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "stocktake",
                    "template": "STK-{yyyy}{MM}-{seq:04d}",
                    "seq_scope": "monthly",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            # stocktake check (SELECT 1 FROM stocktakes LIMIT 1)
            if "stocktakes" in sql and "LIMIT 1" in sql.upper():
                return mock_result
            # ingredient query
            if "ingredients" in sql or "Ingredient" in sql:
                mock_result.scalars.return_value.all.return_value = []
                return mock_result
            # stocktakes INSERT
            if "stocktakes" in sql and "INSERT" in sql.upper():
                return mock_result
            return mock_result

        db.execute = AsyncMock(side_effect=capture_execute)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with patch(
            "services.tx_supply.src.services.stocktake_service.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_STK),
        ), patch(
            "services.tx_supply.src.services.stocktake_service._db_mode",
            True,
        ):
            result = await create_stocktake(
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
                now=_NOW,
            )

        assert result.get("doc_number") == _DOC_NUMBER_STK, (
            f"盘点单结果应含 doc_number='{_DOC_NUMBER_STK}'，实际: {result}"
        )
        # doc_number 必须在 DB INSERT 参数中
        assert any(
            "doc_number" in p for p in written_params
        ), "doc_number 必须写入 stocktakes INSERT 参数，不能只在返回字典"


# ─── 4. 收货单写路径 ──────────────────────────────────────────────────────────


class TestReceivingOrderDocNumber:
    """收货单创建时 doc_number 应由 doc_number_service 生成并写入 receiving_orders"""

    @pytest.mark.asyncio
    async def test_create_receiving_order_generates_doc_number(self):
        """供应商 5/14 早晨送货：收货单 doc_number='RV20260514-001'。

        GIVEN 供应商 08:00 到徐记长沙总店送货
        WHEN  仓管扫供应商送货单创建收货单
        THEN  doc_number='RV20260514-001' 写入 receiving_orders 表
        AND   supply chain 财务稽查可按 RV20260514-001 查单
        """
        from services.tx_supply.src.services.receiving_v2_service import create_receiving_order

        db = AsyncMock()
        updated_rows: list[dict] = []

        async def capture_execute(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "receiving",
                    "template": "RV{yyyy}{MM}{dd}-{seq:03d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql:
                return mock_result
            if "doc_number_sequences" in sql and "INSERT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "receiving_orders" in sql and "UPDATE" in sql.upper() and "doc_number" in sql:
                updated_rows.append(dict(params) if params else {})
                return mock_result
            return mock_result

        db.execute = AsyncMock(side_effect=capture_execute)

        # Mock ORM add/flush
        db.add = MagicMock()
        db.flush = AsyncMock()

        # simulate order object returned by ORM
        mock_order = MagicMock()
        mock_order.id = "aaaaaaaa-1111-2222-3333-444444444444"
        mock_order.status = "draft"
        mock_order.total_items = 1
        mock_order.created_at = datetime(2026, 5, 14, 8, 0, tzinfo=timezone.utc)

        with patch(
            "services.tx_supply.src.services.receiving_v2_service.ReceivingOrder",
            return_value=mock_order,
        ), patch(
            "services.tx_supply.src.services.receiving_v2_service.ReceivingOrderItem",
            return_value=MagicMock(),
        ), patch(
            "services.tx_supply.src.services.receiving_v2_service.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_RV),
        ):
            result = await create_receiving_order(
                tenant_id=_TENANT_XUJI,
                store_id=_STORE_CS,
                supplier_id=_SUPPLIER_ID,
                delivery_note_no="DN-20260514-001",
                receiver_id="77777777-aaaa-bbbb-cccc-777777777777",
                items=[
                    {
                        "ingredient_id": _INGREDIENT_ID,
                        "ingredient_name": "五花肉",
                        "expected_quantity": "50",
                        "expected_unit": "kg",
                    }
                ],
                db=db,
                now=_NOW,
            )

        assert result.get("doc_number") == _DOC_NUMBER_RV, (
            f"收货单结果应含 doc_number='{_DOC_NUMBER_RV}'，实际: {result}"
        )
        # doc_number 必须通过 UPDATE SQL 写入 DB（ORM 实体冻结，不能直接加列）
        assert any(
            p.get("doc_number") == _DOC_NUMBER_RV for p in updated_rows
        ), "doc_number 必须通过 SQL UPDATE 写入 receiving_orders 表"


# ─── 5. 出入库流水写路径 ──────────────────────────────────────────────────────


class TestInventoryIoDocNumber:
    """出入库流水创建时 doc_number 应由 doc_number_service 生成并写入 ingredient_transactions"""

    @pytest.mark.asyncio
    async def test_receive_stock_generates_doc_number(self):
        """采购入库：五花肉 50kg 入库流水 doc_number='IO20260514-0001'。

        GIVEN 供应商 5/14 08:00 送货验收完成
        WHEN  仓管执行入库操作（receive_stock）
        THEN  ingredient_transactions 流水 doc_number='IO20260514-0001'
        AND   财务 / 食药监可按 IO 单号追溯批次来源
        """
        from services.tx_supply.src.services.inventory_io import receive_stock

        db = AsyncMock()
        updated_rows: list[dict] = []

        # mock ingredient ORM object with FOR UPDATE lock
        mock_ingredient = MagicMock()
        mock_ingredient.current_quantity = 200.0
        mock_ingredient.min_quantity = 50.0
        mock_ingredient.unit_price_fen = 2800
        mock_ingredient.status = "normal"

        mock_select_result = MagicMock()
        mock_select_result.scalar_one_or_none.return_value = mock_ingredient

        async def capture_execute(query, params=None):
            sql = str(query)
            mock_result = MagicMock()
            if "set_config" in sql:
                return mock_result
            if "doc_number_rules" in sql and "SELECT" in sql.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "inventory_io",
                    "template": "IO{yyyy}{MM}{dd}-{seq:04d}",
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
            return mock_result

        db.execute = AsyncMock(side_effect=capture_execute)
        db.execute.return_value = mock_select_result  # default for ORM select

        # Patch the select execution to return mock ingredient
        async def smart_execute(query, params=None):
            sql_text = str(query)
            mock_result = MagicMock()

            if "set_config" in sql_text:
                return mock_result
            if "doc_number_rules" in sql_text and "SELECT" in sql_text.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "inventory_io",
                    "template": "IO{yyyy}{MM}{dd}-{seq:04d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql_text:
                return mock_result
            if "doc_number_sequences" in sql_text and "INSERT" in sql_text.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            if "ingredient_transactions" in sql_text and "UPDATE" in sql_text.upper():
                updated_rows.append(dict(params) if params else {})
                return mock_result
            # ORM select for ingredient
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=smart_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_IO),
        ):
            result = await receive_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=50.0,
                unit_cost_fen=2800,
                batch_no="BATCH-20260514-001",
                expiry_date=None,
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
                now=_NOW,
            )

        assert "transaction_id" in result, "入库应返回 transaction_id"
        # doc_number 应通过 UPDATE SQL 写入 ingredient_transactions
        assert any(
            p.get("doc_number") == _DOC_NUMBER_IO for p in updated_rows
        ), "doc_number 必须通过 SQL UPDATE 写入 ingredient_transactions 表"

    @pytest.mark.asyncio
    async def test_inventory_io_doc_number_in_result(self):
        """入库操作结果含 doc_number 字段（供调用方展示和记录）。

        GIVEN 供应商送货后仓管执行入库
        WHEN  receive_stock 成功
        THEN  返回结果包含 doc_number 字段，值符合 IO 格式
        AND   调用方（收货路由）可将 doc_number 返回给前端展示
        """
        from services.tx_supply.src.services.inventory_io import receive_stock

        mock_ingredient = MagicMock()
        mock_ingredient.current_quantity = 200.0
        mock_ingredient.min_quantity = 50.0
        mock_ingredient.unit_price_fen = 2800
        mock_ingredient.status = "normal"

        db = AsyncMock()

        async def smart_execute(query, params=None):
            sql_text = str(query)
            mock_result = MagicMock()
            if "set_config" in sql_text:
                return mock_result
            if "doc_number_rules" in sql_text and "SELECT" in sql_text.upper():
                mock_result.mappings.return_value.first.return_value = {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "doc_type": "inventory_io",
                    "template": "IO{yyyy}{MM}{dd}-{seq:04d}",
                    "seq_scope": "daily",
                    "is_active": True,
                }
                return mock_result
            if "pg_advisory_xact_lock" in sql_text:
                return mock_result
            if "doc_number_sequences" in sql_text and "INSERT" in sql_text.upper():
                mock_result.mappings.return_value.first.return_value = {"current_seq": 1}
                return mock_result
            mock_result.scalar_one_or_none.return_value = mock_ingredient
            return mock_result

        db.execute = AsyncMock(side_effect=smart_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "services.tx_supply.src.services.inventory_io.gen_doc_number",
            new=AsyncMock(return_value=_DOC_NUMBER_IO),
        ):
            result = await receive_stock(
                ingredient_id=_INGREDIENT_ID,
                quantity=50.0,
                unit_cost_fen=2800,
                batch_no="BATCH-20260514-001",
                expiry_date=None,
                store_id=_STORE_CS,
                tenant_id=_TENANT_XUJI,
                db=db,
                now=_NOW,
            )

        assert result.get("doc_number") == _DOC_NUMBER_IO, (
            f"入库结果应含 doc_number='{_DOC_NUMBER_IO}'，实际: {result}"
        )
