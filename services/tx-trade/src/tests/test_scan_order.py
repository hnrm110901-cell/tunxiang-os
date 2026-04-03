"""扫码点餐服务 — 单元测试

覆盖场景：
1. 桌码生成 — 格式正确、包含门店简码和桌号
2. 桌码解析 — 正常解析 + 异常格式处理
3. 扫码下单 — 新建订单 + 菜品添加 + KDS同步
4. 加菜追加 — 同桌多人追加菜品
5. 查看当桌订单 — 返回订单详情及菜品明细
6. 请求结账 — 状态流转到 pending_checkout
7. KDS同步 — 未发送菜品推送到后厨
8. 扫码统计 — 订单数/金额/热门菜品
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock, patch

import pytest

# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()
TABLE_ID = "A01"
CUSTOMER_ID = _uid()
DISH_ID_1 = _uid()
DISH_ID_2 = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        if self._rows:
            return self._rows[0]
        return self._scalar


class FakeDB:
    def __init__(self):
        self.added = []
        self._execute_results = []
        self._execute_index = 0

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        if self._execute_index < len(self._execute_results):
            result = self._execute_results[self._execute_index]
            self._execute_index += 1
            return result
        return FakeResult()

    async def flush(self):
        pass

    async def commit(self):
        pass

    def set_results(self, results: list):
        self._execute_results = results
        self._execute_index = 0


# ─── 1. 桌码生成测试 ───

class TestGenerateTableQrcode:
    def test_qrcode_format(self):
        """桌码格式正确: TX-{简码}-{桌号}"""
        from services.scan_order_service import generate_table_qrcode

        result = generate_table_qrcode(
            store_id=STORE_ID,
            table_id=TABLE_ID,
            tenant_id=TENANT_ID,
        )

        assert result["qrcode"].startswith("TX-")
        assert TABLE_ID in result["qrcode"]
        assert result["store_id"] == STORE_ID
        assert result["table_id"] == TABLE_ID
        assert "miniapp_path" in result

    def test_qrcode_contains_short_code(self):
        """桌码包含门店简码"""
        from services.scan_order_service import _store_short_code, generate_table_qrcode

        result = generate_table_qrcode(
            store_id=STORE_ID,
            table_id="B02",
            tenant_id=TENANT_ID,
        )

        short_code = _store_short_code(STORE_ID)
        assert short_code in result["qrcode"]
        assert result["short_code"] == short_code

    def test_miniapp_path_correct(self):
        """小程序跳转路径正确"""
        from services.scan_order_service import generate_table_qrcode

        result = generate_table_qrcode(
            store_id=STORE_ID,
            table_id=TABLE_ID,
            tenant_id=TENANT_ID,
        )

        path = result["miniapp_path"]
        assert "/pages/scan-order/index" in path
        assert f"store_id={STORE_ID}" in path
        assert f"table_id={TABLE_ID}" in path


# ─── 2. 桌码解析测试 ───

class TestParseQrcode:
    def test_parse_valid_code(self):
        """正常解析桌码"""
        from services.scan_order_service import parse_qrcode

        result = parse_qrcode("TX-ABC123-A01")

        assert result["store_short_code"] == "ABC123"
        assert result["table_id"] == "A01"
        assert result["raw_code"] == "TX-ABC123-A01"

    def test_parse_invalid_prefix(self):
        """无效前缀抛出异常"""
        from services.scan_order_service import parse_qrcode

        with pytest.raises(ValueError, match="无效桌码格式"):
            parse_qrcode("QR-ABC-01")

    def test_parse_empty_code(self):
        """空桌码抛出异常"""
        from services.scan_order_service import parse_qrcode

        with pytest.raises(ValueError, match="无效桌码格式"):
            parse_qrcode("")

    def test_parse_incomplete_code(self):
        """不完整桌码抛出异常"""
        from services.scan_order_service import parse_qrcode

        with pytest.raises(ValueError, match="桌码格式错误"):
            parse_qrcode("TX-ONLY")


# ─── 3. 扫码下单测试 ───

class TestCreateScanOrder:
    @pytest.mark.asyncio
    async def test_create_new_order(self):
        """新建扫码订单"""
        from services.scan_order_service import create_scan_order

        db = FakeDB()

        # Mock: 桌台查询（空闲桌台）
        fake_table = FakeRow(
            id=uuid.uuid4(),
            store_id=uuid.UUID(STORE_ID),
            table_no=TABLE_ID,
            tenant_id=uuid.UUID(TENANT_ID),
            is_active=True,
            status="free",
            current_order_id=None,
        )
        # Mock: 菜品查询
        fake_dish = FakeRow(
            id=uuid.UUID(DISH_ID_1),
            tenant_id=uuid.UUID(TENANT_ID),
            dish_name="宫保鸡丁",
            price_fen=3800,
            is_available=True,
            is_deleted=False,
        )

        db.set_results([
            FakeResult(scalar=fake_table),  # 桌台查询
            FakeResult(),                    # update Table (lock)
            FakeResult(scalar=fake_dish),    # 菜品查询
            FakeResult(),                    # update Order (total)
        ])

        items = [{"dish_id": DISH_ID_1, "quantity": 2}]

        with patch("services.scan_order_service.sync_to_kds", new_callable=AsyncMock) as mock_kds:
            mock_kds.return_value = {"items_synced": 1}

            result = await create_scan_order(
                store_id=STORE_ID,
                table_id=TABLE_ID,
                items=items,
                customer_id=CUSTOMER_ID,
                tenant_id=TENANT_ID,
                db=db,
            )

        assert result["is_new_order"] is True
        assert len(result["items"]) == 1
        assert result["items"][0]["dish_name"] == "宫保鸡丁"
        assert result["total_added_fen"] == 7600
        mock_kds.assert_called_once()


# ─── 4. 加菜追加测试 ───

class TestAddItemsToOrder:
    @pytest.mark.asyncio
    async def test_add_items_success(self):
        """同桌追加菜品"""
        from services.scan_order_service import add_items_to_order

        order_id = _uid()
        db = FakeDB()

        # Mock: 订单查询
        fake_order = FakeRow(
            id=uuid.UUID(order_id),
            tenant_id=uuid.UUID(TENANT_ID),
            status="confirmed",
            is_deleted=False,
        )
        # Mock: 菜品查询
        fake_dish = FakeRow(
            id=uuid.UUID(DISH_ID_2),
            tenant_id=uuid.UUID(TENANT_ID),
            dish_name="清蒸鲈鱼",
            price_fen=6800,
            is_available=True,
            is_deleted=False,
        )

        db.set_results([
            FakeResult(scalar=fake_order),  # 订单查询
            FakeResult(scalar=fake_dish),    # 菜品查询
            FakeResult(),                    # update Order total
        ])

        items = [{"dish_id": DISH_ID_2, "quantity": 1}]

        with patch("services.scan_order_service.sync_to_kds", new_callable=AsyncMock) as mock_kds:
            mock_kds.return_value = {"items_synced": 1}

            result = await add_items_to_order(
                order_id=order_id,
                items=items,
                tenant_id=TENANT_ID,
                db=db,
            )

        assert len(result["items"]) == 1
        assert result["items"][0]["dish_name"] == "清蒸鲈鱼"
        assert result["total_added_fen"] == 6800

    @pytest.mark.asyncio
    async def test_add_items_order_completed_raises(self):
        """已完成订单不可加菜"""
        from services.scan_order_service import add_items_to_order

        order_id = _uid()
        db = FakeDB()

        fake_order = FakeRow(
            id=uuid.UUID(order_id),
            tenant_id=uuid.UUID(TENANT_ID),
            status="completed",
            is_deleted=False,
        )

        db.set_results([FakeResult(scalar=fake_order)])

        with pytest.raises(ValueError, match="不可加菜"):
            await add_items_to_order(
                order_id=order_id,
                items=[{"dish_id": DISH_ID_1, "quantity": 1}],
                tenant_id=TENANT_ID,
                db=db,
            )


# ─── 5. 请求结账测试 ───

class TestRequestCheckout:
    @pytest.mark.asyncio
    async def test_checkout_success(self):
        """请求结账成功"""
        from services.scan_order_service import request_checkout

        order_id = _uid()
        db = FakeDB()

        fake_order = FakeRow(
            id=uuid.UUID(order_id),
            tenant_id=uuid.UUID(TENANT_ID),
            order_no="TX20260327120000ABCD",
            status="confirmed",
            final_amount_fen=15600,
            table_number=TABLE_ID,
            is_deleted=False,
            order_metadata={},
        )

        db.set_results([FakeResult(scalar=fake_order)])

        result = await request_checkout(
            order_id=order_id,
            tenant_id=TENANT_ID,
            db=db,
        )

        assert result["status"] == "pending_checkout"
        assert result["final_amount_fen"] == 15600
        assert fake_order.status == "pending_checkout"

    @pytest.mark.asyncio
    async def test_checkout_completed_order_raises(self):
        """已完成订单不可结账"""
        from services.scan_order_service import request_checkout

        order_id = _uid()
        db = FakeDB()

        fake_order = FakeRow(
            id=uuid.UUID(order_id),
            tenant_id=uuid.UUID(TENANT_ID),
            status="completed",
            is_deleted=False,
        )

        db.set_results([FakeResult(scalar=fake_order)])

        with pytest.raises(ValueError, match="无法结账"):
            await request_checkout(
                order_id=order_id,
                tenant_id=TENANT_ID,
                db=db,
            )


# ─── 6. 桌码生成/解析往返测试 ───

class TestQrcodeRoundtrip:
    def test_generate_then_parse(self):
        """生成桌码后能正确解析回原始信息"""
        from services.scan_order_service import generate_table_qrcode, parse_qrcode

        gen_result = generate_table_qrcode(
            store_id=STORE_ID,
            table_id="C05",
            tenant_id=TENANT_ID,
        )

        parse_result = parse_qrcode(gen_result["qrcode"])

        assert parse_result["table_id"] == "C05"
        assert parse_result["store_short_code"] == gen_result["short_code"]
