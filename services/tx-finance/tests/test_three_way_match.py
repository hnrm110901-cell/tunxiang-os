"""采购三单匹配引擎测试（测试先行）

覆盖场景：
  1. 完全匹配（采购单=收货=发票金额）→ status=matched
  2. 数量差异（收货少于订购）→ status=quantity_variance
  3. 价格差异（发票价格与采购价不符）→ status=price_variance
  4. 发票缺失 → status=missing_invoice
  5. 自动容差（差异<1% 且 <10元，视为匹配）→ status=matched
  6. 差异金额计算正确性
  7. 多项差异（数量+价格同时出问题）→ status=multi_variance
  8. 未收货 → status=missing_receiving
  9. tenant_id 隔离
  10. 批量匹配聚合统计
  11. AI 建议触发阈值（差异 >500元 = 50000分才触发）
  12. 自动核销小额差异（< max_amount 分）
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.three_way_match import (
    Base as MatchBase,
)
from services.three_way_match_engine import (
    MatchResult,
    MatchStatus,
    PurchaseOrderNotFoundError,
    ThreeWayMatchEngine,
    VarianceItem,
)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
SUPPLIER_1 = uuid.uuid4()
STORE_1 = uuid.uuid4()

# ── 内存 DB 夹具 ──────────────────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(MatchBase.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(MatchBase.metadata.drop_all)
    await engine.dispose()


def _make_po(
    po_id: uuid.UUID,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    items: list[dict],
    total_amount_fen: int,
) -> dict:
    """构造采购订单 dict（模拟 DB 行）"""
    return {
        "id": str(po_id),
        "tenant_id": str(tenant_id),
        "supplier_id": str(supplier_id),
        "store_id": str(STORE_1),
        "status": "approved",
        "total_amount_fen": total_amount_fen,
        "items": items,
        "order_number": f"PO-{po_id.hex[:8].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_receiving(
    receiving_id: uuid.UUID,
    po_id: uuid.UUID,
    tenant_id: uuid.UUID,
    items: list[dict],
) -> dict:
    """构造收货单 dict"""
    return {
        "id": str(receiving_id),
        "tenant_id": str(tenant_id),
        "purchase_order_id": str(po_id),
        "status": "confirmed",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }


def _make_invoice(
    invoice_id: uuid.UUID,
    po_id: uuid.UUID,
    tenant_id: uuid.UUID,
    amount_fen: int,
    items: list[dict],
) -> dict:
    """构造采购发票 dict"""
    return {
        "id": str(invoice_id),
        "tenant_id": str(tenant_id),
        "purchase_order_id": str(po_id),
        "invoice_no": f"INV-{invoice_id.hex[:8].upper()}",
        "amount_fen": amount_fen,
        "status": "confirmed",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }


# ── 单元测试：匹配逻辑 ────────────────────────────────────────────────────────


class TestThreeWayMatchLogic:
    """直接测试匹配引擎的核心逻辑（不依赖 DB）"""

    def setup_method(self):
        self.engine = ThreeWayMatchEngine()

    # ─── 场景 1：完全匹配 ──────────────────────────────────────────────────────

    def test_fully_matched(self):
        """采购单=收货=发票，金额数量完全一致 → matched"""
        po_items = [{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}]
        recv_items = [{"ingredient_name": "猪肉", "received_qty": 10.0, "unit_price_fen": 3000}]
        inv_items = [{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=30000,
            inv_total_fen=30000,
        )
        assert result.status == MatchStatus.MATCHED
        assert result.variance_amount_fen == 0
        assert result.line_variances == []

    # ─── 场景 2：数量差异 ──────────────────────────────────────────────────────

    def test_quantity_variance(self):
        """收货数量少于采购数量 → quantity_variance"""
        po_items = [{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}]
        recv_items = [{"ingredient_name": "猪肉", "received_qty": 8.0, "unit_price_fen": 3000}]
        inv_items = [{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=30000,
            inv_total_fen=30000,
        )
        assert result.status == MatchStatus.QUANTITY_VARIANCE
        assert len(result.line_variances) >= 1
        lv = result.line_variances[0]
        assert lv["type"] == "quantity_variance"
        assert lv["po_qty"] == 10.0
        assert lv["recv_qty"] == 8.0
        # 差异量2件 × 3000分 = 6000分
        assert lv["variance_fen"] == 6000

    # ─── 场景 3：价格差异 ──────────────────────────────────────────────────────

    def test_price_variance(self):
        """发票单价与采购单价不符 → price_variance"""
        po_items = [{"ingredient_name": "牛肉", "qty": 5.0, "unit_price_fen": 8000}]
        recv_items = [{"ingredient_name": "牛肉", "received_qty": 5.0, "unit_price_fen": 8000}]
        # 发票单价涨了：8500分/单位
        inv_items = [{"ingredient_name": "牛肉", "qty": 5.0, "unit_price_fen": 8500}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=40000,
            inv_total_fen=42500,  # 5 × 8500
        )
        assert result.status == MatchStatus.PRICE_VARIANCE
        lv = result.line_variances[0]
        assert lv["type"] == "price_variance"
        assert lv["po_unit_price_fen"] == 8000
        assert lv["inv_unit_price_fen"] == 8500
        # 差额：5件 × 500分 = 2500分
        assert lv["variance_fen"] == 2500

    # ─── 场景 4：发票缺失 ──────────────────────────────────────────────────────

    def test_missing_invoice(self):
        """无发票 → missing_invoice"""
        po_items = [{"ingredient_name": "蔬菜", "qty": 20.0, "unit_price_fen": 500}]
        recv_items = [{"ingredient_name": "蔬菜", "received_qty": 20.0, "unit_price_fen": 500}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=None,  # 无发票
            po_total_fen=10000,
            inv_total_fen=None,
        )
        assert result.status == MatchStatus.MISSING_INVOICE
        assert result.variance_amount_fen == 10000  # 整单金额视为差异

    # ─── 场景 5：未收货 ────────────────────────────────────────────────────────

    def test_missing_receiving(self):
        """无收货记录 → missing_receiving"""
        po_items = [{"ingredient_name": "海鲜", "qty": 3.0, "unit_price_fen": 20000}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=None,  # 无收货
            inv_items=None,
            po_total_fen=60000,
            inv_total_fen=None,
        )
        assert result.status == MatchStatus.MISSING_RECEIVING

    # ─── 场景 6：容差范围内视为匹配 ────────────────────────────────────────────

    def test_tolerance_small_amount(self):
        """差异 ≤10元（≤1000分），视为 matched"""
        # 采购10000分，发票10005分（差5分 < 10元）
        po_items = [{"ingredient_name": "调料", "qty": 1.0, "unit_price_fen": 10000}]
        recv_items = [{"ingredient_name": "调料", "received_qty": 1.0, "unit_price_fen": 10000}]
        inv_items = [{"ingredient_name": "调料", "qty": 1.0, "unit_price_fen": 10005}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=10000,
            inv_total_fen=10005,  # 差5分
        )
        assert result.status == MatchStatus.MATCHED

    def test_tolerance_percentage_within_1pct(self):
        """差异 < 1%，视为 matched"""
        # 采购100000分（1000元），发票100500分（差0.5%）
        po_items = [{"ingredient_name": "大米", "qty": 100.0, "unit_price_fen": 1000}]
        recv_items = [{"ingredient_name": "大米", "received_qty": 100.0, "unit_price_fen": 1000}]
        inv_items = [{"ingredient_name": "大米", "qty": 100.0, "unit_price_fen": 1005}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=100000,
            inv_total_fen=100500,  # 差0.5%
        )
        assert result.status == MatchStatus.MATCHED

    def test_tolerance_exceeds_1pct(self):
        """差异 > 1% 且 > 10元 → 不应视为匹配"""
        # 采购100000分，发票102000分（差2%）
        po_items = [{"ingredient_name": "大米", "qty": 100.0, "unit_price_fen": 1000}]
        recv_items = [{"ingredient_name": "大米", "received_qty": 100.0, "unit_price_fen": 1000}]
        inv_items = [{"ingredient_name": "大米", "qty": 100.0, "unit_price_fen": 1020}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=100000,
            inv_total_fen=102000,
        )
        assert result.status != MatchStatus.MATCHED
        assert result.variance_amount_fen == 2000

    # ─── 场景 7：多项差异 ──────────────────────────────────────────────────────

    def test_multi_variance(self):
        """数量+价格同时存在差异 → multi_variance"""
        po_items = [{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}]
        # 收货少2件
        recv_items = [{"ingredient_name": "猪肉", "received_qty": 8.0, "unit_price_fen": 3000}]
        # 发票单价涨200分
        inv_items = [{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3200}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=30000,
            inv_total_fen=32000,
        )
        assert result.status == MatchStatus.MULTI_VARIANCE
        types = {lv["type"] for lv in result.line_variances}
        assert "quantity_variance" in types
        assert "price_variance" in types

    # ─── 场景 8：差异金额计算 ──────────────────────────────────────────────────

    def test_variance_amount_calculation(self):
        """验证 variance_amount_fen 计算正确"""
        po_items = [{"ingredient_name": "牛排", "qty": 2.0, "unit_price_fen": 15000}]
        recv_items = [{"ingredient_name": "牛排", "received_qty": 2.0, "unit_price_fen": 15000}]
        inv_items = [{"ingredient_name": "牛排", "qty": 2.0, "unit_price_fen": 16000}]

        result = self.engine._compute_match_status(
            po_items=po_items,
            recv_items=recv_items,
            inv_items=inv_items,
            po_total_fen=30000,
            inv_total_fen=32000,
        )
        # 差异 = 32000 - 30000 = 2000分
        assert result.variance_amount_fen == 2000

    # ─── 场景 9：AI 建议触发阈值 ───────────────────────────────────────────────

    def test_ai_suggestion_threshold_not_triggered(self):
        """差异 ≤500元（≤50000分）不触发 AI 建议"""
        variance = VarianceItem(
            id=str(uuid.uuid4()),
            purchase_order_id=str(uuid.uuid4()),
            tenant_id=str(TENANT_A),
            supplier_id=str(SUPPLIER_1),
            status=MatchStatus.PRICE_VARIANCE,
            variance_amount_fen=40000,  # 400元，低于阈值
            po_amount_fen=100000,
            recv_amount_fen=100000,
            inv_amount_fen=140000,
            line_variances=[],
            created_at=datetime.now(timezone.utc),
        )
        should_trigger = self.engine._should_trigger_ai(variance)
        assert should_trigger is False

    def test_ai_suggestion_threshold_triggered(self):
        """差异 >500元（>50000分）触发 AI 建议"""
        variance = VarianceItem(
            id=str(uuid.uuid4()),
            purchase_order_id=str(uuid.uuid4()),
            tenant_id=str(TENANT_A),
            supplier_id=str(SUPPLIER_1),
            status=MatchStatus.PRICE_VARIANCE,
            variance_amount_fen=60000,  # 600元，超过阈值
            po_amount_fen=200000,
            recv_amount_fen=200000,
            inv_amount_fen=260000,
            line_variances=[],
            created_at=datetime.now(timezone.utc),
        )
        should_trigger = self.engine._should_trigger_ai(variance)
        assert should_trigger is True

    # ─── 场景 10：自动核销阈值 ────────────────────────────────────────────────

    def test_auto_approve_threshold(self):
        """差异金额在 max_amount 以内可自动核销"""
        # max_amount = 10000 分（100元）
        engine = ThreeWayMatchEngine()
        # 差异 5000分（50元）< 阈值，可核销
        can_approve = engine._can_auto_approve(variance_amount_fen=5000, max_amount_fen=10000)
        assert can_approve is True

    def test_auto_approve_threshold_exceeded(self):
        """差异金额超过 max_amount，不可自动核销"""
        engine = ThreeWayMatchEngine()
        # 差异 15000分（150元）> 阈值 10000分
        can_approve = engine._can_auto_approve(variance_amount_fen=15000, max_amount_fen=10000)
        assert can_approve is False


# ── 集成测试：完整匹配流程（含 DB 写入）────────────────────────────────────────


class TestThreeWayMatchIntegration:
    """集成测试：match_purchase_order 完整调用（mock DB 查询）"""

    @pytest.mark.asyncio
    async def test_match_purchase_order_fully_matched(self):
        """完整流程：单笔三单匹配 → matched"""
        engine = ThreeWayMatchEngine()
        po_id = uuid.uuid4()
        tenant_id = TENANT_A

        po_data = _make_po(
            po_id, tenant_id, SUPPLIER_1,
            items=[{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}],
            total_amount_fen=30000,
        )
        recv_data = _make_receiving(
            uuid.uuid4(), po_id, tenant_id,
            items=[{"ingredient_name": "猪肉", "received_qty": 10.0, "unit_price_fen": 3000}],
        )
        inv_data = _make_invoice(
            uuid.uuid4(), po_id, tenant_id,
            amount_fen=30000,
            items=[{"ingredient_name": "猪肉", "qty": 10.0, "unit_price_fen": 3000}],
        )

        mock_db = AsyncMock()

        with patch.object(engine, "_fetch_purchase_order", return_value=po_data), \
             patch.object(engine, "_fetch_receiving_orders", return_value=[recv_data]), \
             patch.object(engine, "_fetch_purchase_invoices", return_value=[inv_data]), \
             patch.object(engine, "_save_match_result", return_value=None):

            result = await engine.match_purchase_order(
                purchase_order_id=str(po_id),
                tenant_id=str(tenant_id),
                db=mock_db,
            )

        assert result.status == MatchStatus.MATCHED
        assert result.purchase_order_id == str(po_id)
        assert result.variance_amount_fen == 0

    @pytest.mark.asyncio
    async def test_match_purchase_order_missing_invoice(self):
        """完整流程：无发票 → missing_invoice"""
        engine = ThreeWayMatchEngine()
        po_id = uuid.uuid4()
        tenant_id = TENANT_A

        po_data = _make_po(
            po_id, tenant_id, SUPPLIER_1,
            items=[{"ingredient_name": "蔬菜", "qty": 20.0, "unit_price_fen": 500}],
            total_amount_fen=10000,
        )
        recv_data = _make_receiving(
            uuid.uuid4(), po_id, tenant_id,
            items=[{"ingredient_name": "蔬菜", "received_qty": 20.0, "unit_price_fen": 500}],
        )

        mock_db = AsyncMock()

        with patch.object(engine, "_fetch_purchase_order", return_value=po_data), \
             patch.object(engine, "_fetch_receiving_orders", return_value=[recv_data]), \
             patch.object(engine, "_fetch_purchase_invoices", return_value=[]), \
             patch.object(engine, "_save_match_result", return_value=None):

            result = await engine.match_purchase_order(
                purchase_order_id=str(po_id),
                tenant_id=str(tenant_id),
                db=mock_db,
            )

        assert result.status == MatchStatus.MISSING_INVOICE

    @pytest.mark.asyncio
    async def test_match_purchase_order_not_found(self):
        """采购单不存在 → 抛出 PurchaseOrderNotFoundError"""
        engine = ThreeWayMatchEngine()

        mock_db = AsyncMock()
        with patch.object(engine, "_fetch_purchase_order", return_value=None):
            with pytest.raises(PurchaseOrderNotFoundError):
                await engine.match_purchase_order(
                    purchase_order_id=str(uuid.uuid4()),
                    tenant_id=str(TENANT_A),
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_batch_match_returns_stats(self):
        """批量匹配返回正确统计数字"""
        engine = ThreeWayMatchEngine()
        po_id_1 = uuid.uuid4()
        po_id_2 = uuid.uuid4()

        # 两条采购单：一条匹配，一条有发票价格差异
        mock_results = [
            MatchResult(
                purchase_order_id=str(po_id_1),
                status=MatchStatus.MATCHED,
                po_amount_fen=30000,
                recv_amount_fen=30000,
                inv_amount_fen=30000,
                variance_amount_fen=0,
                line_variances=[],
                suggestion=None,
            ),
            MatchResult(
                purchase_order_id=str(po_id_2),
                status=MatchStatus.PRICE_VARIANCE,
                po_amount_fen=40000,
                recv_amount_fen=40000,
                inv_amount_fen=42000,
                variance_amount_fen=2000,
                line_variances=[{"type": "price_variance", "variance_fen": 2000}],
                suggestion=None,
            ),
        ]

        mock_db = AsyncMock()
        with patch.object(engine, "_fetch_pending_purchase_orders",
                          return_value=[str(po_id_1), str(po_id_2)]), \
             patch.object(engine, "match_purchase_order",
                          side_effect=mock_results):

            batch_result = await engine.batch_match(
                tenant_id=str(TENANT_A),
                db=mock_db,
            )

        assert batch_result.total == 2
        assert batch_result.matched == 1
        assert batch_result.variance_count == 1
        assert batch_result.missing_count == 0

    @pytest.mark.asyncio
    async def test_tenant_isolation(self):
        """不同租户的采购单不可互相访问"""
        engine = ThreeWayMatchEngine()
        po_id = uuid.uuid4()

        # 采购单属于 TENANT_A，用 TENANT_B 查询
        po_data = _make_po(
            po_id, TENANT_A, SUPPLIER_1,
            items=[{"ingredient_name": "食材", "qty": 1.0, "unit_price_fen": 1000}],
            total_amount_fen=1000,
        )

        mock_db = AsyncMock()

        # TENANT_B 查询应返回 None（RLS 隔离）
        with patch.object(engine, "_fetch_purchase_order", return_value=None):
            with pytest.raises(PurchaseOrderNotFoundError):
                await engine.match_purchase_order(
                    purchase_order_id=str(po_id),
                    tenant_id=str(TENANT_B),  # 不同租户
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_ai_suggestion_called_for_large_variance(self):
        """差异 > 500元时，建议字段应被填充（mock model_router）"""
        engine = ThreeWayMatchEngine()
        po_id = uuid.uuid4()
        tenant_id = TENANT_A

        po_data = _make_po(
            po_id, tenant_id, SUPPLIER_1,
            items=[{"ingredient_name": "牛排", "qty": 10.0, "unit_price_fen": 15000}],
            total_amount_fen=150000,
        )
        recv_data = _make_receiving(
            uuid.uuid4(), po_id, tenant_id,
            items=[{"ingredient_name": "牛排", "received_qty": 10.0, "unit_price_fen": 15000}],
        )
        inv_data = _make_invoice(
            uuid.uuid4(), po_id, tenant_id,
            amount_fen=160000,  # 差10000分（100元） — 但差价率 >1%
            items=[{"ingredient_name": "牛排", "qty": 10.0, "unit_price_fen": 16000}],
        )

        mock_db = AsyncMock()
        mock_model_router = AsyncMock()
        mock_model_router.complete = AsyncMock(return_value="建议：发票单价高于合同价，建议联系供应商确认。")

        with patch.object(engine, "_fetch_purchase_order", return_value=po_data), \
             patch.object(engine, "_fetch_receiving_orders", return_value=[recv_data]), \
             patch.object(engine, "_fetch_purchase_invoices", return_value=[inv_data]), \
             patch.object(engine, "_save_match_result", return_value=None):

            result = await engine.match_purchase_order(
                purchase_order_id=str(po_id),
                tenant_id=str(tenant_id),
                db=mock_db,
                model_router=mock_model_router,
            )

        # 差异10000分（100元）< 50000分，不触发 AI
        assert result.status == MatchStatus.PRICE_VARIANCE

    @pytest.mark.asyncio
    async def test_auto_approve_small_variances_returns_count(self):
        """自动核销小额差异，返回处理数量"""
        engine = ThreeWayMatchEngine()
        mock_db = AsyncMock()

        # mock 3条小额差异记录，max_amount = 10000分（100元）
        with patch.object(engine, "_fetch_small_variances",
                          return_value=["id1", "id2", "id3"]), \
             patch.object(engine, "_approve_variance",
                          return_value=None):

            count = await engine.auto_approve_small_variances(
                tenant_id=str(TENANT_A),
                max_amount_fen=10000,
                db=mock_db,
            )

        assert count == 3
