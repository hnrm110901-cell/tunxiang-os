"""WA-1 微信 AI 智能体 SDK 测试

测试：6 个 Function Calling 的 Mock 模式行为、FUNCTIONS Schema 完整性。
"""

import pytest

from ..external_sdk import ExternalSDKManager, WechatAIAgentSDK


@pytest.fixture
def sdk() -> WechatAIAgentSDK:
    return WechatAIAgentSDK()


@pytest.fixture
def manager() -> ExternalSDKManager:
    return ExternalSDKManager()


class TestFunctionsSchema:
    """6 个函数的 OpenAPI Schema 定义"""

    def test_all_6_functions_defined(self):
        assert len(WechatAIAgentSDK.FUNCTIONS) == 6

    def test_each_function_has_name_and_description(self):
        for fn in WechatAIAgentSDK.FUNCTIONS:
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_each_function_has_parameters_schema(self):
        for fn in WechatAIAgentSDK.FUNCTIONS:
            params = fn["parameters"]
            assert params["type"] == "object"
            assert "properties" in params

    def test_function_names_are_unique(self):
        names = [fn["name"] for fn in WechatAIAgentSDK.FUNCTIONS]
        assert len(names) == len(set(names))

    def test_function_names_match_expected(self):
        names = {fn["name"] for fn in WechatAIAgentSDK.FUNCTIONS}
        expected = {"query_menu", "create_order", "query_order",
                    "query_member", "query_coupons", "book_table"}
        assert names == expected

    def test_required_fields_present(self):
        fn_map = {fn["name"]: fn for fn in WechatAIAgentSDK.FUNCTIONS}
        assert "store_id" in fn_map["query_menu"]["parameters"]["required"]
        assert "store_id" in fn_map["create_order"]["parameters"]["required"]
        assert "dishes" in fn_map["create_order"]["parameters"]["required"]
        assert "order_id" in fn_map["query_order"]["parameters"]["required"]
        assert "openid" in fn_map["query_member"]["parameters"]["required"]
        assert "openid" in fn_map["query_coupons"]["parameters"]["required"]
        assert "store_id" in fn_map["book_table"]["parameters"]["required"]
        assert "time" in fn_map["book_table"]["parameters"]["required"]
        assert "guests" in fn_map["book_table"]["parameters"]["required"]


class TestQueryMenu:
    async def test_returns_ok(self, sdk):
        result = await sdk.query_menu("store_001")
        assert result["ok"] is True
        assert "dishes" in result["data"]
        assert result["data"]["store_id"] == "store_001"

    async def test_filter_by_category(self, sdk):
        result = await sdk.query_menu("store_001", category="招牌")
        assert all(d["category"] == "招牌" for d in result["data"]["dishes"])

    async def test_search_by_dish_name(self, sdk):
        result = await sdk.query_menu("store_001", dish_name="鱼")
        assert all("鱼" in d["name"] for d in result["data"]["dishes"])

    async def test_all_category_returns_all(self, sdk):
        result = await sdk.query_menu("store_001", category="全部")
        full = await sdk.query_menu("store_001")
        assert len(result["data"]["dishes"]) == len(full["data"]["dishes"])

    async def test_no_match_returns_empty(self, sdk):
        result = await sdk.query_menu("store_001", dish_name="不存在的菜")
        assert len(result["data"]["dishes"]) == 0


class TestCreateOrder:
    async def test_creates_order(self, sdk):
        result = await sdk.create_order(
            "store_001",
            dishes=[{"dish_name": "水煮鱼", "quantity": 1}],
        )
        assert result["ok"] is True
        assert result["data"]["status"] == "pending_payment"
        assert result["data"]["store_id"] == "store_001"

    async def test_calculates_total_correctly(self, sdk):
        result = await sdk.create_order(
            "store_001",
            dishes=[
                {"dish_name": "水煮鱼", "quantity": 2},
                {"dish_name": "米饭", "quantity": 3},
            ],
        )
        assert result["data"]["total_fen"] == 2 * 8800 + 3 * 300

    async def test_includes_preference(self, sdk):
        result = await sdk.create_order(
            "store_001",
            dishes=[{"dish_name": "水煮鱼", "quantity": 1}],
            preference="少油少盐",
        )
        assert result["data"]["preference"] == "少油少盐"


class TestQueryOrder:
    async def test_returns_order_status(self, sdk):
        result = await sdk.query_order("order_001")
        assert result["ok"] is True
        assert "status" in result["data"]
        assert "estimated_wait_minutes" in result["data"]


class TestQueryMember:
    async def test_returns_member_info(self, sdk):
        result = await sdk.query_member("openid_001")
        assert result["ok"] is True
        assert result["data"]["openid"] == "openid_001"
        assert "level" in result["data"]
        assert "current_points" in result["data"]


class TestQueryCoupons:
    async def test_returns_available_coupons(self, sdk):
        result = await sdk.query_coupons("openid_001")
        assert result["ok"] is True
        assert len(result["data"]["coupons"]) == 2
        assert all(c["status"] == "available" for c in result["data"]["coupons"])

    async def test_filter_by_store(self, sdk):
        result = await sdk.query_coupons("openid_001", store_id="store_001")
        assert result["data"]["store_id"] == "store_001"


class TestBookTable:
    async def test_books_table(self, sdk):
        result = await sdk.book_table(
            "store_001",
            time="2026-06-01T18:30:00+08:00",
            guests=4,
        )
        assert result["ok"] is True
        assert result["data"]["status"] == "confirmed"
        assert result["data"]["guests"] == 4
        assert "table_no" in result["data"]
        assert "booking_id" in result["data"]

    async def test_with_note(self, sdk):
        result = await sdk.book_table(
            "store_001",
            time="2026-06-01T18:30:00+08:00",
            guests=6,
            note="靠窗包厢",
        )
        assert result["data"]["note"] == "靠窗包厢"


class TestManagerIntegration:
    """ExternalSDKManager 集成"""

    def test_ai_agent_accessible_via_manager(self, manager):
        assert hasattr(manager, "ai_agent")
        assert isinstance(manager.ai_agent, WechatAIAgentSDK)

    def test_manager_ai_agent_has_all_methods(self, manager):
        agent = manager.ai_agent
        assert hasattr(agent, "query_menu")
        assert hasattr(agent, "create_order")
        assert hasattr(agent, "query_order")
        assert hasattr(agent, "query_member")
        assert hasattr(agent, "query_coupons")
        assert hasattr(agent, "book_table")
