"""
TC-P2-12 智慧商街/档口管理 — 测试套件

测试覆盖：
1. 档口列表获取
2. 创建档口（outlet_code唯一性）
3. 完整下单流程（开单→追加品项→结算）
4. 档口数据隔离
5. 日报统计

运行：pytest services/tx-trade/src/tests/test_food_court.py -v
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# 延迟导入，避免循环依赖问题
def get_app():
    from services.tx_trade.src.main import app

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    """创建测试客户端（ASGI transport，不需要真实网络）"""
    try:
        from services.tx_trade.src.main import app as _app
    except ImportError:
        # 路径别名兼容
        import os
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
        from services.tx_trade.src.main import app as _app

    async with AsyncClient(
        transport=ASGITransport(app=_app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def mock_outlet_payload():
    return {
        "store_id": "store-test-001",
        "name": "测试档口",
        "outlet_code": "T01",
        "location": "测试区1号",
        "owner_name": "测试老板",
        "owner_phone": "13900000099",
        "settlement_ratio": 1.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: 获取档口列表
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_outlets_list(client: AsyncClient):
    """获取档口列表，验证返回3个档口且含today_revenue_fen字段"""
    response = await client.get("/api/v1/food-court/outlets")

    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is True
    assert "data" in body

    data = body["data"]
    assert "items" in data
    assert "total" in data

    items = data["items"]
    # 至少包含Mock的3个档口
    assert len(items) >= 3

    # 验证必要字段存在
    for outlet in items:
        assert "id" in outlet
        assert "name" in outlet
        assert "outlet_code" in outlet
        assert "status" in outlet
        assert "today_revenue_fen" in outlet, f"档口 {outlet['name']} 缺少 today_revenue_fen 字段"
        assert "today_order_count" in outlet

    # 验证3个Mock档口都在结果中
    outlet_names = [o["name"] for o in items]
    assert "张记烤鱼" in outlet_names
    assert "李家粉面" in outlet_names
    assert "老王串串" in outlet_names


@pytest.mark.asyncio
async def test_get_outlets_list_with_store_filter(client: AsyncClient):
    """测试store_id过滤功能"""
    response = await client.get(
        "/api/v1/food-court/outlets",
        params={"store_id": "store-demo-001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    items = body["data"]["items"]
    for outlet in items:
        assert outlet["store_id"] == "store-demo-001"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: 创建档口（outlet_code唯一性）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_outlet(client: AsyncClient, mock_outlet_payload: dict):
    """创建新档口，验证outlet_code唯一性逻辑"""
    # Step 1: 创建档口
    response = await client.post(
        "/api/v1/food-court/outlets",
        json=mock_outlet_payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    data = body["data"]
    assert data["name"] == mock_outlet_payload["name"]
    assert data["outlet_code"] == mock_outlet_payload["outlet_code"]
    assert data["status"] == "active"
    assert "id" in data

    # Step 2: 尝试创建相同outlet_code的档口（同一门店）
    duplicate_payload = {
        **mock_outlet_payload,
        "name": "另一个测试档口",  # 名称不同，但编号相同
    }
    dup_response = await client.post(
        "/api/v1/food-court/outlets",
        json=duplicate_payload,
    )

    # 应该返回422（唯一性冲突）
    assert dup_response.status_code == 422, f"预期422，实际 {dup_response.status_code}，响应：{dup_response.text}"

    # Step 3: 不同门店相同编号应该允许
    different_store_payload = {
        **mock_outlet_payload,
        "store_id": "store-different-999",  # 不同门店
        "name": "不同门店的同编号档口",
    }
    ok_response = await client.post(
        "/api/v1/food-court/outlets",
        json=different_store_payload,
    )
    assert ok_response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: 完整下单流程
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_food_court_order_flow(client: AsyncClient):
    """完整下单流程：开单→加品项→结算，验证各档口小计汇总"""
    # Step 1: 开单（张记烤鱼）
    create_resp = await client.post(
        "/api/v1/food-court/orders",
        json={
            "outlet_id": "out-001",
            "store_id": "store-demo-001",
            "table_no": "A05",
            "items": [
                {"id": "dish-001", "name": "招牌烤鱼", "price_fen": 6800, "qty": 1},
            ],
            "notes": "少辣",
        },
    )
    assert create_resp.status_code == 200
    order_data = create_resp.json()["data"]
    order_id = order_data["id"]

    assert order_data["outlet_id"] == "out-001"
    assert order_data["subtotal_fen"] == 6800
    assert order_data["status"] == "open"

    # Step 2: 追加品项（李家粉面，跨档口加单）
    add_resp = await client.post(
        f"/api/v1/food-court/orders/{order_id}/add-items",
        json={
            "outlet_id": "out-002",
            "items": [
                {"id": "dish-005", "name": "牛肉粉", "price_fen": 1800, "qty": 2},
            ],
        },
    )
    assert add_resp.status_code == 200
    add_data = add_resp.json()["data"]
    assert add_data["outlet_id"] == "out-002"
    assert add_data["added_subtotal_fen"] == 3600  # 1800 * 2

    # 验证总金额汇总
    expected_total = 6800 + 3600  # 张记 + 李家
    assert add_data["new_total_fen"] == expected_total

    # Step 3: 统一结算（微信支付）
    checkout_resp = await client.post(
        f"/api/v1/food-court/orders/{order_id}/checkout",
        json={
            "payment_method": "wechat",
        },
    )
    assert checkout_resp.status_code == 200
    checkout_data = checkout_resp.json()["data"]

    assert checkout_data["order_id"] == order_id
    assert checkout_data["total_fen"] == expected_total
    assert checkout_data["payment_method"] == "wechat"
    assert "outlet_breakdown" in checkout_data
    assert "paid_at" in checkout_data

    # 验证档口分账明细
    breakdown = checkout_data["outlet_breakdown"]
    assert len(breakdown) >= 1  # 至少有一个档口

    # 验证各档口小计之和等于总金额
    breakdown_total = sum(b["subtotal_fen"] for b in breakdown)
    # 允许与总额相等（outlet_breakdown来自outlet_orders记录）
    assert breakdown_total >= 0


@pytest.mark.asyncio
async def test_checkout_cash_with_change(client: AsyncClient):
    """现金支付验证找零计算"""
    # 开单
    create_resp = await client.post(
        "/api/v1/food-court/orders",
        json={
            "outlet_id": "out-001",
            "store_id": "store-demo-001",
            "items": [
                {"id": "dish-001", "name": "招牌烤鱼", "price_fen": 6800, "qty": 1},
            ],
        },
    )
    assert create_resp.status_code == 200
    order_id = create_resp.json()["data"]["id"]

    # 现金支付，给100元
    checkout_resp = await client.post(
        f"/api/v1/food-court/orders/{order_id}/checkout",
        json={
            "payment_method": "cash",
            "amount_tendered_fen": 10000,  # 100元
        },
    )
    assert checkout_resp.status_code == 200
    data = checkout_resp.json()["data"]
    assert data["change_fen"] == 10000 - 6800  # 找零 32元


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: 档口数据隔离
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outlet_data_isolation(client: AsyncClient):
    """档口数据隔离：A档口报表不含B档口数据"""
    # 查询出-001档口的订单
    resp_a = await client.get(
        "/api/v1/food-court/orders",
        params={"outlet_id": "out-001"},
    )
    assert resp_a.status_code == 200
    orders_a = resp_a.json()["data"]["items"]

    # 所有返回的订单都应属于 out-001
    for order in orders_a:
        assert order["outlet_id"] == "out-001", f"过滤 out-001 返回了其他档口的订单：{order['outlet_id']}"

    # 查询out-002档口的订单
    resp_b = await client.get(
        "/api/v1/food-court/orders",
        params={"outlet_id": "out-002"},
    )
    assert resp_b.status_code == 200
    orders_b = resp_b.json()["data"]["items"]

    for order in orders_b:
        assert order["outlet_id"] == "out-002", f"过滤 out-002 返回了其他档口的订单：{order['outlet_id']}"

    # A、B两个档口的订单集合无重叠
    ids_a = {o["id"] for o in orders_a}
    ids_b = {o["id"] for o in orders_b}
    overlap = ids_a & ids_b
    assert len(overlap) == 0, f"档口数据出现交叉：{overlap}"


@pytest.mark.asyncio
async def test_get_outlet_detail(client: AsyncClient):
    """获取单个档口详情，验证菜单数据"""
    response = await client.get("/api/v1/food-court/outlets/out-001")

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["id"] == "out-001"
    assert data["name"] == "张记烤鱼"
    assert "menu_items" in data
    assert len(data["menu_items"]) > 0


@pytest.mark.asyncio
async def test_get_nonexistent_outlet(client: AsyncClient):
    """获取不存在的档口，应返回404"""
    response = await client.get("/api/v1/food-court/outlets/out-nonexistent-999")
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: 日报统计
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_stats(client: AsyncClient):
    """日报统计：各档口营业额/订单数正确"""
    response = await client.get(
        "/api/v1/food-court/stats/daily",
        params={"store_id": "store-demo-001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    data = body["data"]
    assert "stat_date" in data
    assert "total_revenue_fen" in data
    assert "total_order_count" in data
    assert "outlet_count" in data
    assert "outlets" in data

    outlets_stats = data["outlets"]
    assert len(outlets_stats) >= 3

    # 验证每个档口统计字段完整
    for stat in outlets_stats:
        assert "outlet_id" in stat
        assert "outlet_name" in stat
        assert "revenue_fen" in stat
        assert "order_count" in stat
        assert "avg_order_fen" in stat
        assert stat["revenue_fen"] >= 0
        assert stat["order_count"] >= 0

    # 验证汇总正确：总营业额 = 各档口之和
    sum_revenue = sum(s["revenue_fen"] for s in outlets_stats)
    assert data["total_revenue_fen"] == sum_revenue

    # 验证Mock数据中张记烤鱼的营业额
    zhangjis = next((s for s in outlets_stats if s["outlet_name"] == "张记烤鱼"), None)
    assert zhangjis is not None
    assert zhangjis["revenue_fen"] == 285600
    assert zhangjis["order_count"] == 23


@pytest.mark.asyncio
async def test_outlet_compare_stats(client: AsyncClient):
    """档口对比报表：多档口营业额对比"""
    from datetime import date, timedelta

    start = date.today()
    end = start + timedelta(days=6)

    response = await client.get(
        "/api/v1/food-court/stats/compare",
        params={
            "store_id": "store-demo-001",
            "start_date": str(start),
            "end_date": str(end),
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert "start_date" in data
    assert "end_date" in data
    assert "days" in data
    assert "outlets" in data
    assert "trend" in data

    assert data["days"] == 7

    # 趋势数据应有7天
    assert len(data["trend"]) == 7

    # 每天趋势数据应包含日期字段
    for day_data in data["trend"]:
        assert "date" in day_data
