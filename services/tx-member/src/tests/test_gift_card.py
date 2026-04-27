"""礼品卡服务测试 — 制卡/激活/售卖/使用/余额/线上配置"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.gift_card import (
    _CardStore,
    _CardTypeStore,
    _OnlineConfigStore,
    activate_cards,
    batch_create_cards,
    create_gift_card_type,
    get_card_balance,
    online_purchase_config,
    sell_card,
    use_card,
)

TENANT = "t-test-001"


@pytest.fixture(autouse=True)
def _clear_stores():
    _CardTypeStore.clear()
    _CardStore.clear()
    _OnlineConfigStore.clear()
    yield
    _CardTypeStore.clear()
    _CardStore.clear()
    _OnlineConfigStore.clear()


# ---------------------------------------------------------------------------
# 1. 创建礼品卡类型
# ---------------------------------------------------------------------------


class TestCreateType:
    @pytest.mark.asyncio
    async def test_create_type(self):
        result = await create_gift_card_type("生日卡", 20000, TENANT)
        assert result["name"] == "生日卡"
        assert result["face_value_fen"] == 20000
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_create_type_zero_value(self):
        with pytest.raises(ValueError, match="面值必须大于0"):
            await create_gift_card_type("空卡", 0, TENANT)


# ---------------------------------------------------------------------------
# 2. 批量制卡
# ---------------------------------------------------------------------------


class TestBatchCreate:
    @pytest.mark.asyncio
    async def test_batch_create(self):
        ct = await create_gift_card_type("节日卡", 10000, TENANT)
        result = await batch_create_cards(ct["type_id"], 5, TENANT)
        assert result["created_count"] == 5
        assert len(result["cards"]) == 5
        for card in result["cards"]:
            assert len(card["card_no"]) == 16
            assert len(card["password"]) == 6
            assert card["password"].isdigit()

    @pytest.mark.asyncio
    async def test_batch_create_unique_nos(self):
        ct = await create_gift_card_type("VIP卡", 50000, TENANT)
        result = await batch_create_cards(ct["type_id"], 100, TENANT)
        nos = [c["card_no"] for c in result["cards"]]
        assert len(set(nos)) == 100  # 全部唯一

    @pytest.mark.asyncio
    async def test_batch_create_wrong_tenant(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        with pytest.raises(ValueError, match="租户不匹配"):
            await batch_create_cards(ct["type_id"], 1, "other")

    @pytest.mark.asyncio
    async def test_batch_create_too_many(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        with pytest.raises(ValueError, match="不能超过10000"):
            await batch_create_cards(ct["type_id"], 10001, TENANT)


# ---------------------------------------------------------------------------
# 3. 批量激活
# ---------------------------------------------------------------------------


class TestActivate:
    @pytest.mark.asyncio
    async def test_activate_success(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        created = await batch_create_cards(ct["type_id"], 3, TENANT)
        card_ids = [c["card_id"] for c in created["cards"]]
        result = await activate_cards(card_ids, TENANT)
        assert result["activated_count"] == 3
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_activate_wrong_status(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        created = await batch_create_cards(ct["type_id"], 1, TENANT)
        card_id = created["cards"][0]["card_id"]
        await activate_cards([card_id], TENANT)
        # 重复激活
        result = await activate_cards([card_id], TENANT)
        assert result["activated_count"] == 0
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# 4. 售卖
# ---------------------------------------------------------------------------


class TestSellCard:
    @pytest.mark.asyncio
    async def test_sell_success(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        created = await batch_create_cards(ct["type_id"], 1, TENANT)
        card_id = created["cards"][0]["card_id"]
        await activate_cards([card_id], TENANT)
        result = await sell_card(card_id, {"name": "张三", "phone": "13800138000"}, TENANT)
        assert result["face_value_fen"] == 10000
        assert result["buyer_info"]["name"] == "张三"

    @pytest.mark.asyncio
    async def test_sell_not_activated(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        created = await batch_create_cards(ct["type_id"], 1, TENANT)
        card_id = created["cards"][0]["card_id"]
        with pytest.raises(ValueError, match="需先激活"):
            await sell_card(card_id, {"name": "test"}, TENANT)


# ---------------------------------------------------------------------------
# 5. 使用礼品卡
# ---------------------------------------------------------------------------


class TestUseCard:
    async def _prepare_sold_card(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        created = await batch_create_cards(ct["type_id"], 1, TENANT)
        card_info = created["cards"][0]
        await activate_cards([card_info["card_id"]], TENANT)
        await sell_card(card_info["card_id"], {"name": "买家"}, TENANT)
        return card_info

    @pytest.mark.asyncio
    async def test_use_full_balance(self):
        card = await self._prepare_sold_card()
        result = await use_card(card["card_no"], card["password"], "order_001", 10000, TENANT)
        assert result["balance_fen"] == 0
        assert result["status"] == "exhausted"

    @pytest.mark.asyncio
    async def test_use_partial(self):
        card = await self._prepare_sold_card()
        result = await use_card(card["card_no"], card["password"], "order_001", 3000, TENANT)
        assert result["balance_fen"] == 7000
        assert result["status"] == "sold"

    @pytest.mark.asyncio
    async def test_use_wrong_password(self):
        card = await self._prepare_sold_card()
        with pytest.raises(ValueError, match="密码错误"):
            await use_card(card["card_no"], "000000", "order_001", 1000, TENANT)

    @pytest.mark.asyncio
    async def test_use_insufficient_balance(self):
        card = await self._prepare_sold_card()
        with pytest.raises(ValueError, match="余额不足"):
            await use_card(card["card_no"], card["password"], "order_001", 99999, TENANT)

    @pytest.mark.asyncio
    async def test_use_multiple_times(self):
        card = await self._prepare_sold_card()
        await use_card(card["card_no"], card["password"], "o1", 3000, TENANT)
        await use_card(card["card_no"], card["password"], "o2", 4000, TENANT)
        result = await use_card(card["card_no"], card["password"], "o3", 3000, TENANT)
        assert result["balance_fen"] == 0
        assert result["status"] == "exhausted"


# ---------------------------------------------------------------------------
# 6. 查余额
# ---------------------------------------------------------------------------


class TestBalance:
    @pytest.mark.asyncio
    async def test_balance_query(self):
        ct = await create_gift_card_type("卡", 10000, TENANT)
        created = await batch_create_cards(ct["type_id"], 1, TENANT)
        card = created["cards"][0]
        await activate_cards([card["card_id"]], TENANT)
        await sell_card(card["card_id"], {"name": "买家"}, TENANT)
        await use_card(card["card_no"], card["password"], "o1", 2500, TENANT)
        result = await get_card_balance(card["card_no"], TENANT)
        assert result["balance_fen"] == 7500
        assert len(result["transactions"]) == 1

    @pytest.mark.asyncio
    async def test_balance_not_found(self):
        with pytest.raises(ValueError, match="不存在"):
            await get_card_balance("9999999999999999", TENANT)


# ---------------------------------------------------------------------------
# 7. 线上售卖配置
# ---------------------------------------------------------------------------


class TestOnlineConfig:
    @pytest.mark.asyncio
    async def test_set_config(self):
        ct = await create_gift_card_type("新年卡", 20000, TENANT)
        result = await online_purchase_config(
            ct["type_id"],
            {"title": "新年快乐", "cover_image": "https://example.com/cover.jpg"},
            TENANT,
        )
        assert result["theme"]["title"] == "新年快乐"
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_config_wrong_type(self):
        with pytest.raises(ValueError, match="不存在"):
            await online_purchase_config("fake-id", {}, TENANT)
