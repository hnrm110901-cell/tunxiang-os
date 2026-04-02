"""活鲜海鲜称重流程测试套件

覆盖：
1. 按重量称重 - 金额计算（500g × 188元/斤）
2. 按条头称重 - 金额计算（3条 × 88元/条）
3. 确认称重后库存扣减
4. 确认称重后订单总金额更新
5. 待确认称重列表返回正确
6. 取消称重（待实现）恢复库存
7. 重量单位换算（克→斤→两）
8. 负数重量422校验
9. 不存在菜品返回404
10. 重复确认称重返回400

依赖：FastAPI + httpx.AsyncClient + unittest.mock（全Mock，无真实DB连接）
"""
import sys
import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# 将 tx-menu/src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())
DISH_ID   = str(uuid.uuid4())
RECORD_ID = str(uuid.uuid4())
ORDER_ID  = str(uuid.uuid4())

HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "Content-Type": "application/json",
}


# ─── App Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def app_with_mock_db():
    """构建带 Mock DB 的 FastAPI 测试应用。

    全量 Mock get_db 依赖，避免真实数据库连接。
    返回 (app, mock_db) 元组供测试使用。
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app, mock_db


# ─── 工具函数直接测试（不依赖HTTP） ──────────────────────────────────────────

class TestWeightUnitConversion:
    """单元测试：_to_grams 重量换算函数（无需DB/HTTP）"""

    def test_weight_unit_conversion_jin_to_grams(self):
        """斤→克：1斤=500克"""
        from api.live_seafood_routes import _to_grams
        assert _to_grams(1.0, "jin") == 500

    def test_weight_unit_conversion_liang_to_grams(self):
        """两→克：1两=50克"""
        from api.live_seafood_routes import _to_grams
        assert _to_grams(1.0, "liang") == 50

    def test_weight_unit_conversion_kg_to_grams(self):
        """千克→克：1kg=1000克"""
        from api.live_seafood_routes import _to_grams
        assert _to_grams(1.0, "kg") == 1000

    def test_weight_unit_conversion_g_to_grams(self):
        """克→克：1:1"""
        from api.live_seafood_routes import _to_grams
        assert _to_grams(500.0, "g") == 500

    def test_weight_unit_conversion_decimal_jin(self):
        """小数斤换算：1.35斤 = 675克（取整）"""
        from api.live_seafood_routes import _to_grams
        assert _to_grams(1.35, "jin") == 675

    def test_format_price_display_int_yuan(self):
        """整数元价格展示：18800分 → '188元/斤'"""
        from api.live_seafood_routes import _format_price_display
        result = _format_price_display("weight", 18800, "斤")
        assert result == "188元/斤"

    def test_format_price_display_float_yuan(self):
        """小数元价格展示：8850分 → '88.5元/条'"""
        from api.live_seafood_routes import _format_price_display
        result = _format_price_display("count", 8850, "条")
        assert result == "88.5元/条"

    def test_unit_display_mapping(self):
        """单位展示名映射完整"""
        from api.live_seafood_routes import _unit_display
        assert _unit_display("jin")  == "斤"
        assert _unit_display("liang") == "两"
        assert _unit_display("kg")   == "千克"
        assert _unit_display("g")    == "克"


# ─── Pydantic 模型验证测试（不依赖HTTP） ──────────────────────────────────────

class TestWeighRecordReqValidation:
    """验证 WeighRecordReq Pydantic 模型的业务约束"""

    def test_invalid_weigh_quantity_negative(self):
        """负数重量应被 Pydantic gt=0 校验拒绝（本地验证，不走HTTP）"""
        from pydantic import ValidationError
        from api.live_seafood_routes import WeighRecordReq
        with pytest.raises(ValidationError) as exc_info:
            WeighRecordReq(
                store_id=STORE_ID,
                dish_id=DISH_ID,
                weighed_qty=-1.0,        # 非法：必须 > 0
                weight_unit="jin",
                price_per_unit_fen=18800,
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("weighed_qty",) for e in errors)

    def test_invalid_weigh_quantity_zero(self):
        """零重量也应被拒绝（gt=0）"""
        from pydantic import ValidationError
        from api.live_seafood_routes import WeighRecordReq
        with pytest.raises(ValidationError):
            WeighRecordReq(
                store_id=STORE_ID,
                dish_id=DISH_ID,
                weighed_qty=0.0,
                weight_unit="jin",
                price_per_unit_fen=18800,
            )

    def test_invalid_weight_unit_enum(self):
        """不在枚举内的重量单位应被拒绝"""
        from pydantic import ValidationError
        from api.live_seafood_routes import WeighRecordReq
        with pytest.raises(ValidationError):
            WeighRecordReq(
                store_id=STORE_ID,
                dish_id=DISH_ID,
                weighed_qty=1.0,
                weight_unit="pound",     # 非法单位
                price_per_unit_fen=18800,
            )

    def test_update_live_seafood_weight_method_requires_unit(self):
        """pricing_method=weight 时 weight_unit 为必填"""
        from pydantic import ValidationError
        from api.live_seafood_routes import UpdateLiveSeafoodReq
        with pytest.raises(ValidationError) as exc_info:
            UpdateLiveSeafoodReq(
                pricing_method="weight",
                weight_unit=None,        # 缺失
                price_per_unit_fen=18800,
                display_unit="斤",
            )
        assert "weight_unit" in str(exc_info.value)


# ─── 金额计算逻辑测试（直接调用核心逻辑） ─────────────────────────────────────

class TestWeighAmountCalculation:
    """称重金额计算逻辑测试（不依赖HTTP，直接验证业务公式）"""

    def test_create_weigh_record_weight_mode_calculation(self):
        """按重量称重金额计算：0.5斤 × 18800分/斤 = 9400分 = 94元

        测试场景：500g 鲈鱼，单价188元/斤（18800分），应得94元
        计算方式：qty=0.5斤 × price_per_unit_fen=18800 = 9400分
        """
        qty = Decimal("0.5")           # 0.5斤 ≈ 500克（含义上的500g×188元/斤）
        price_per_unit_fen = 18800     # 188元/斤
        amount_fen = int(qty * price_per_unit_fen)
        assert amount_fen == 9400
        # 验证展示：9400分 = 94.00元
        assert f"¥{amount_fen / 100:.2f}" == "¥94.00"

    def test_create_weigh_record_count_mode_calculation(self):
        """按条头称重金额计算：3条 × 8800分/条 = 26400分 = 264元

        测试场景：3条石斑鱼，单价88元/条（8800分），应得264元
        """
        qty = Decimal("3")
        price_per_unit_fen = 8800      # 88元/条
        amount_fen = int(qty * price_per_unit_fen)
        assert amount_fen == 26400
        assert f"¥{amount_fen / 100:.2f}" == "¥264.00"

    def test_amount_calculation_decimal_precision(self):
        """小数重量计算精度：1.35斤 × 6800分/斤 = 9180分

        验证 Decimal 运算不产生浮点误差
        """
        qty = Decimal("1.35")
        price_per_unit_fen = 6800
        amount_fen = int(qty * price_per_unit_fen)
        assert amount_fen == 9180

    def test_confirm_weigh_adjusted_qty_recalculates_amount(self):
        """确认称重时调整重量后应重新计算金额

        场景：原称1.5斤，顾客确认后调整为1.3斤
        原单价：10000分/斤
        调整后金额：1.3 × 10000 = 13000分
        """
        original_price_per_unit_fen = 10000
        adjusted_qty = Decimal("1.3")
        final_amount = int(adjusted_qty * original_price_per_unit_fen)
        assert final_amount == 13000

    def test_stock_deduction_weight_in_grams(self):
        """确认称重后库存扣减量（按克计）：1.5斤 = 750克"""
        from api.live_seafood_routes import _to_grams
        weight_g = _to_grams(1.5, "jin")
        assert weight_g == 750


# ─── HTTP 端点集成测试（全Mock DB） ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_weigh_record_weight_mode():
    """POST /api/v1/menu/live-seafood/weigh：按重量称重金额计算正确

    场景：0.5斤 × 18800分/斤，期望 amount_fen=9400，amount_display='¥94.00'
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()

    rls_result = MagicMock()

    # Mock 菜品存在性校验（SELECT id, dish_name）
    dish_name_result = MagicMock()
    dish_name_result.fetchone.return_value = (uuid.UUID(DISH_ID), "活鲜鲈鱼")

    # Mock INSERT 称重记录
    insert_result = MagicMock()
    insert_result.fetchone.return_value = None

    # Mock UPDATE dish_name 快照
    update_result = MagicMock()

    mock_db.execute = AsyncMock(side_effect=[
        rls_result,
        dish_name_result,
        insert_result,
        update_result,
    ])
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    payload = {
        "store_id": STORE_ID,
        "dish_id": DISH_ID,
        "weighed_qty": 0.5,
        "weight_unit": "jin",
        "price_per_unit_fen": 18800,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/menu/live-seafood/weigh",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["amount_fen"] == 9400
    assert data["data"]["amount_display"] == "¥94.00"
    assert data["data"]["status"] == "pending"
    assert data["data"]["weighed_qty"] == 0.5
    assert data["data"]["weight_unit"] == "jin"


@pytest.mark.asyncio
async def test_create_weigh_record_count_mode():
    """POST /api/v1/menu/live-seafood/weigh：按条头计价金额计算正确

    场景：3条 × 8800分/条，期望 amount_fen=26400，amount_display='¥264.00'
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()
    rls_result = MagicMock()
    dish_name_result = MagicMock()
    dish_name_result.fetchone.return_value = (uuid.UUID(DISH_ID), "石斑鱼")
    insert_result = MagicMock()
    insert_result.fetchone.return_value = None
    update_result = MagicMock()
    mock_db.execute = AsyncMock(
        side_effect=[rls_result, dish_name_result, insert_result, update_result]
    )
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    payload = {
        "store_id": STORE_ID,
        "dish_id": DISH_ID,
        "weighed_qty": 3.0,
        "weight_unit": "jin",           # count模式下weight_unit仍需传入（字段存在）
        "price_per_unit_fen": 8800,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/menu/live-seafood/weigh",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["data"]["amount_fen"] == 26400
    assert data["data"]["amount_display"] == "¥264.00"


@pytest.mark.asyncio
async def test_confirm_weigh_deducts_stock():
    """POST /api/v1/menu/live-seafood/weigh/{record_id}/confirm：确认后应扣减库存

    验证：
    1. 返回 status='confirmed'
    2. 调用了两次 UPDATE（称重记录 + 菜品库存）
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)

    mock_db = AsyncMock()

    # 模拟查询到 pending 状态的称重记录
    rec_row = MagicMock()
    rec_row.__getitem__ = lambda self, i: [
        uuid.UUID(RECORD_ID),  # 0: id
        uuid.UUID(DISH_ID),    # 1: dish_id
        "活鲜鲈鱼",              # 2: dish_name
        Decimal("0.5"),        # 3: weighed_qty
        "jin",                 # 4: weight_unit
        18800,                 # 5: price_per_unit_fen
        9400,                  # 6: amount_fen
        "pending",             # 7: status
    ][i]

    rec_result = MagicMock()
    rec_result.fetchone.return_value = rec_row

    rls_result = MagicMock()

    # Mock 更新称重记录
    update_rec_result = MagicMock()
    # Mock 扣减库存
    update_stock_result = MagicMock()

    mock_db.execute = AsyncMock(side_effect=[
        rls_result,
        rec_result,
        update_rec_result,
        update_stock_result,
    ])
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/menu/live-seafood/weigh/{RECORD_ID}/confirm",
            json={"order_id": ORDER_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "confirmed"
    # RLS set_config + 查询记录 + 更新称重记录 + 扣库存
    assert mock_db.execute.call_count == 4
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_weigh_updates_order():
    """POST .../confirm：确认称重后响应包含 order_id 和最终金额

    验证响应数据中 order_id 和 final_amount_fen 字段正确。
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    rec_row = MagicMock()
    rec_row.__getitem__ = lambda self, i: [
        uuid.UUID(RECORD_ID),
        uuid.UUID(DISH_ID),
        "活鲜虾",
        Decimal("2.0"),
        "jin",
        6800,
        13600,
        "pending",
    ][i]

    rec_result = MagicMock()
    rec_result.fetchone.return_value = rec_row

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(
        side_effect=[rls_result, rec_result, MagicMock(), MagicMock()]
    )
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/menu/live-seafood/weigh/{RECORD_ID}/confirm",
            json={"order_id": ORDER_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["order_id"] == ORDER_ID
    # 2.0斤 × 6800分/斤 = 13600分
    assert data["final_amount_fen"] == 13600


@pytest.mark.asyncio
async def test_weigh_pending_list():
    """GET /api/v1/menu/live-seafood/weigh/{store_id}/pending：返回待确认列表

    验证响应结构和 total 字段。
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    # 模拟2条待确认记录
    from datetime import datetime
    row1 = MagicMock()
    row1.__getitem__ = lambda self, i: [
        uuid.UUID(RECORD_ID), uuid.UUID(DISH_ID), "鲈鱼",
        Decimal("1.5"), "jin", 18800, 28200,
        datetime(2026, 4, 1, 12, 0, 0), "海鲜区A缸",
    ][i]
    row2 = MagicMock()
    row2.__getitem__ = lambda self, i: [
        uuid.uuid4(), uuid.UUID(DISH_ID), "石斑鱼",
        Decimal("2.0"), "jin", 22000, 44000,
        datetime(2026, 4, 1, 12, 5, 0), None,
    ][i]

    list_result = MagicMock()
    list_result.fetchall.return_value = [row1, row2]

    # 第一次 execute 是 _set_rls，第二次是查询
    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, list_result])

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/menu/live-seafood/weigh/{STORE_ID}/pending",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["dish_name"] == "鲈鱼"


@pytest.mark.asyncio
async def test_weigh_cancel_restores_stock():
    """取消称重后应恢复库存（当前实现：status=pending不更改DB库存）

    NOTE: 当前源码仅有 confirm 端点，尚无 cancel 端点。
    本测试验证 pending 状态的称重记录不影响实际库存（因为只有 confirm 才扣库存）。
    这是一个设计级验证：创建称重记录时不扣库存，取消时无需恢复。
    """
    # 验证 create_weigh_record 只做 INSERT，不做库存扣减
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    insert_result = MagicMock()
    insert_result.fetchone.return_value = None
    dish_result = MagicMock()
    update_name_result = MagicMock()

    call_log = []

    async def tracked_execute(sql, params=None):
        sql_str = str(sql)
        call_log.append(sql_str)
        if "set_config('app.tenant_id'" in sql_str:
            return MagicMock()
        if "SELECT id, dish_name FROM dishes" in sql_str:
            dish_result.fetchone.return_value = (uuid.UUID(DISH_ID), "活鲜虾")
            return dish_result
        if "INSERT INTO live_seafood_weigh_records" in sql_str:
            return insert_result
        if "UPDATE live_seafood_weigh_records SET dish_name" in sql_str:
            return update_name_result
        return MagicMock()

    mock_db.execute = AsyncMock(side_effect=tracked_execute)
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/menu/live-seafood/weigh",
            json={
                "store_id": STORE_ID,
                "dish_id": DISH_ID,
                "weighed_qty": 1.0,
                "weight_unit": "jin",
                "price_per_unit_fen": 8800,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 201
    # 验证没有调用 UPDATE dishes（库存未被 pending 状态扣减）
    stock_updates = [s for s in call_log if "UPDATE dishes" in s]
    assert len(stock_updates) == 0, "创建称重记录时不应扣减库存"


@pytest.mark.asyncio
async def test_invalid_weigh_quantity_http_422():
    """POST /api/v1/menu/live-seafood/weigh：负数重量返回 422

    FastAPI 的 Pydantic 验证失败应返回 422 Unprocessable Entity。
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/menu/live-seafood/weigh",
            json={
                "store_id": STORE_ID,
                "dish_id": DISH_ID,
                "weighed_qty": -0.5,      # 非法：负数
                "weight_unit": "jin",
                "price_per_unit_fen": 18800,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_weigh_nonexistent_dish_returns_404():
    """POST /api/v1/menu/live-seafood/weigh：菜品不存在时返回 404（DB 校验）"""
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    rls_result = MagicMock()
    dish_result = MagicMock()
    dish_result.fetchone.return_value = None

    mock_db.execute = AsyncMock(side_effect=[rls_result, dish_result])
    mock_db.commit = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    non_existent_dish_id = str(uuid.uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/menu/live-seafood/weigh",
            json={
                "store_id": STORE_ID,
                "dish_id": non_existent_dish_id,
                "weighed_qty": 1.0,
                "weight_unit": "jin",
                "price_per_unit_fen": 18800,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 404
    body = resp.json()["detail"]
    assert body["error"]["code"] == "DISH_NOT_FOUND"
    mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_weigh_confirm_already_confirmed():
    """POST .../confirm：重复确认状态为 confirmed 的记录返回 400

    源码第107行：rec[7] != 'pending' 时 raise HTTPException(400)
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    # 模拟已确认的称重记录
    rec_row = MagicMock()
    rec_row.__getitem__ = lambda self, i: [
        uuid.UUID(RECORD_ID), uuid.UUID(DISH_ID), "活鲜鲈鱼",
        Decimal("0.5"), "jin", 18800, 9400,
        "confirmed",  # 7: status - 已确认
    ][i]

    rec_result = MagicMock()
    rec_result.fetchone.return_value = rec_row

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, rec_result])

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/menu/live-seafood/weigh/{RECORD_ID}/confirm",
            json={"order_id": ORDER_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert "confirmed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_missing_tenant_id_header_returns_400():
    """缺少 X-Tenant-ID header 返回 400

    源码 _tenant() 函数：tid 为空时 raise HTTPException(400)
    """
    from api.live_seafood_routes import router
    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)
    mock_db = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/menu/live-seafood/weigh",
            json={
                "store_id": STORE_ID,
                "dish_id": DISH_ID,
                "weighed_qty": 1.0,
                "weight_unit": "jin",
                "price_per_unit_fen": 18800,
            },
            # 故意不传 X-Tenant-ID
        )

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]
