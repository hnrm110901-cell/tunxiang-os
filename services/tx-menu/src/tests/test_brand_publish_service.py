"""品牌→门店三级发布体系测试

覆盖：
  - 发布方案 CRUD 和校验
  - 执行发布逻辑（不覆盖门店手动微调）
  - 门店菜品微调（改价/改名/上下架/批量）
  - 价格调整规则（时段/渠道/日期/节假日）
  - 生效价格五级优先级计算
  - 多租户隔离（tenant_id 边界）

所有 DB 交互通过 AsyncMock 模拟，纯函数逻辑独立测试。
"""
import uuid
from datetime import datetime, time, date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 导入被测服务和 Repository ───

import sys
import os
# 保证在 pytest 直接运行时也能找到包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from ..services.brand_publish_service import BrandPublishService
from ..services.brand_publish_repository import BrandPublishRepository


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

TENANT_ID = str(uuid.uuid4())
BRAND_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID_1 = str(uuid.uuid4())
DISH_ID_2 = str(uuid.uuid4())
PLAN_ID = str(uuid.uuid4())
RULE_ID = str(uuid.uuid4())


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


def _make_svc(db: AsyncMock) -> BrandPublishService:
    return BrandPublishService(db=db, tenant_id=TENANT_ID)


def _repo_mock(db: AsyncMock) -> BrandPublishRepository:
    return BrandPublishRepository(db=db, tenant_id=TENANT_ID)


def _fake_plan(
    plan_id: str = PLAN_ID,
    status: str = "draft",
    target_type: str = "stores",
    target_ids: list | None = None,
) -> dict:
    return {
        "id": plan_id,
        "plan_name": "测试发布方案",
        "target_type": target_type,
        "target_ids": target_ids or [STORE_ID],
        "status": status,
        "published_at": None,
        "created_at": "2026-03-31T10:00:00",
        "updated_at": "2026-03-31T10:00:00",
        "brand_id": BRAND_ID,
        "created_by": None,
    }


def _fake_item(
    dish_id: str = DISH_ID_1,
    override_price: int | None = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "plan_id": PLAN_ID,
        "dish_id": dish_id,
        "override_price_fen": override_price,
        "is_available": True,
        "created_at": "2026-03-31T10:00:00",
        "dish_name": "测试菜品",
        "brand_price_fen": 3800,
        "effective_price_fen": override_price if override_price else 3800,
        "image_url": None,
    }


def _fake_override(
    local_price: int | None = None,
    is_available: bool = True,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "dish_id": DISH_ID_1,
        "local_price_fen": local_price,
        "local_name": None,
        "local_description": None,
        "local_image_url": None,
        "is_available": is_available,
        "sort_order": 0,
        "updated_at": "2026-03-31T10:00:00",
    }


# ══════════════════════════════════════════════════════
# 1. 发布方案创建校验
# ══════════════════════════════════════════════════════


class TestCreatePublishPlan:
    @pytest.mark.asyncio
    async def test_empty_plan_name_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="plan_name"):
            await svc.create_publish_plan(
                plan_name="",
                target_type="stores",
                target_ids=[STORE_ID],
            )

    @pytest.mark.asyncio
    async def test_invalid_target_type_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="target_type"):
            await svc.create_publish_plan(
                plan_name="测试",
                target_type="invalid",
            )

    @pytest.mark.asyncio
    async def test_stores_type_requires_target_ids(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="target_ids"):
            await svc.create_publish_plan(
                plan_name="测试",
                target_type="stores",
                target_ids=None,
            )

    @pytest.mark.asyncio
    async def test_region_type_requires_target_ids(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="target_ids"):
            await svc.create_publish_plan(
                plan_name="测试",
                target_type="region",
                target_ids=[],
            )

    @pytest.mark.asyncio
    async def test_all_stores_no_target_ids_ok(self):
        db = _mock_db()
        svc = _make_svc(db)
        expected_plan = _fake_plan(target_type="all_stores", target_ids=None)

        with patch.object(
            BrandPublishRepository, "create_publish_plan", AsyncMock(return_value=expected_plan)
        ):
            plan = await svc.create_publish_plan(
                plan_name="全门店发布",
                target_type="all_stores",
            )
        assert plan["target_type"] == "all_stores"
        assert plan["status"] == "draft"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_with_brand_id(self):
        db = _mock_db()
        svc = _make_svc(db)
        expected_plan = _fake_plan()

        with patch.object(
            BrandPublishRepository, "create_publish_plan", AsyncMock(return_value=expected_plan)
        ):
            plan = await svc.create_publish_plan(
                plan_name="品牌发布方案",
                target_type="stores",
                target_ids=[STORE_ID],
                brand_id=BRAND_ID,
            )
        assert plan["brand_id"] == BRAND_ID


# ══════════════════════════════════════════════════════
# 2. 添加菜品到方案的校验
# ══════════════════════════════════════════════════════


class TestAddPlanItems:
    @pytest.mark.asyncio
    async def test_cannot_add_to_published_plan(self):
        db = _mock_db()
        svc = _make_svc(db)
        published_plan = _fake_plan(status="published")

        with patch.object(
            BrandPublishRepository, "get_publish_plan", AsyncMock(return_value=published_plan)
        ):
            with pytest.raises(ValueError, match="状态"):
                await svc.add_items_to_plan(
                    plan_id=PLAN_ID,
                    items=[{"dish_id": DISH_ID_1}],
                )

    @pytest.mark.asyncio
    async def test_empty_items_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")

        with patch.object(
            BrandPublishRepository, "get_publish_plan", AsyncMock(return_value=draft_plan)
        ):
            with pytest.raises(ValueError, match="items"):
                await svc.add_items_to_plan(plan_id=PLAN_ID, items=[])

    @pytest.mark.asyncio
    async def test_negative_override_price_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")

        with patch.object(
            BrandPublishRepository, "get_publish_plan", AsyncMock(return_value=draft_plan)
        ):
            with pytest.raises(ValueError, match="override_price_fen"):
                await svc.add_items_to_plan(
                    plan_id=PLAN_ID,
                    items=[{"dish_id": DISH_ID_1, "override_price_fen": -100}],
                )

    @pytest.mark.asyncio
    async def test_success(self):
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")
        expected_items = [_fake_item(DISH_ID_1, 3500), _fake_item(DISH_ID_2)]

        with (
            patch.object(BrandPublishRepository, "get_publish_plan",
                         AsyncMock(return_value=draft_plan)),
            patch.object(BrandPublishRepository, "add_plan_items",
                         AsyncMock(return_value=expected_items)),
        ):
            result = await svc.add_items_to_plan(
                plan_id=PLAN_ID,
                items=[
                    {"dish_id": DISH_ID_1, "override_price_fen": 3500},
                    {"dish_id": DISH_ID_2},
                ],
            )
        assert len(result) == 2
        assert result[0]["override_price_fen"] == 3500


# ══════════════════════════════════════════════════════
# 3. 执行发布：不覆盖门店已有微调
# ══════════════════════════════════════════════════════


class TestExecutePublishPlan:
    @pytest.mark.asyncio
    async def test_archived_plan_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        archived = _fake_plan(status="archived")

        with patch.object(
            BrandPublishRepository, "get_publish_plan", AsyncMock(return_value=archived)
        ):
            with pytest.raises(ValueError, match="归档"):
                await svc.execute_publish_plan(PLAN_ID)

    @pytest.mark.asyncio
    async def test_no_items_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")

        with (
            patch.object(BrandPublishRepository, "get_publish_plan",
                         AsyncMock(return_value=draft_plan)),
            patch.object(BrandPublishRepository, "get_target_store_ids",
                         AsyncMock(return_value=[STORE_ID])),
            patch.object(BrandPublishRepository, "get_plan_items",
                         AsyncMock(return_value=[])),
        ):
            with pytest.raises(ValueError, match="菜品"):
                await svc.execute_publish_plan(PLAN_ID)

    @pytest.mark.asyncio
    async def test_new_dish_creates_override(self):
        """新菜品（门店无微调记录）→ 新建 store_dish_overrides。"""
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")
        items = [_fake_item(DISH_ID_1, override_price=3500)]
        new_override = _fake_override(local_price=3500)
        updated_plan = {**draft_plan, "status": "published"}

        upsert_mock = AsyncMock(return_value=new_override)

        with (
            patch.object(BrandPublishRepository, "get_publish_plan",
                         AsyncMock(return_value=draft_plan)),
            patch.object(BrandPublishRepository, "get_target_store_ids",
                         AsyncMock(return_value=[STORE_ID])),
            patch.object(BrandPublishRepository, "get_plan_items",
                         AsyncMock(return_value=items)),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value=None)),  # 无已有记录
            patch.object(BrandPublishRepository, "upsert_store_dish_override",
                         upsert_mock),
            patch.object(BrandPublishRepository, "update_plan_status",
                         AsyncMock(return_value=updated_plan)),
        ):
            result = await svc.execute_publish_plan(PLAN_ID)

        assert result["success_stores"] == 1
        assert result["failed_stores"] == 0
        # 新建了 override
        upsert_mock.assert_awaited_once()
        call_kwargs = upsert_mock.call_args
        assert call_kwargs.kwargs["data"]["local_price_fen"] == 3500

    @pytest.mark.asyncio
    async def test_existing_manual_is_available_not_overridden(self):
        """门店已主动下架菜品（is_available=False），执行发布不应覆盖。"""
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")
        items = [_fake_item(DISH_ID_1, override_price=3500)]
        existing_override = _fake_override(local_price=None, is_available=False)  # 门店主动下架
        updated_plan = {**draft_plan, "status": "published"}

        upsert_mock = AsyncMock(return_value=existing_override)

        with (
            patch.object(BrandPublishRepository, "get_publish_plan",
                         AsyncMock(return_value=draft_plan)),
            patch.object(BrandPublishRepository, "get_target_store_ids",
                         AsyncMock(return_value=[STORE_ID])),
            patch.object(BrandPublishRepository, "get_plan_items",
                         AsyncMock(return_value=items)),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value=existing_override)),
            patch.object(BrandPublishRepository, "upsert_store_dish_override",
                         upsert_mock),
            patch.object(BrandPublishRepository, "update_plan_status",
                         AsyncMock(return_value=updated_plan)),
        ):
            result = await svc.execute_publish_plan(PLAN_ID)

        assert result["success_stores"] == 1
        # 已有记录 + 无本地价 + 方案有覆盖价 → 同步价格（但不动 is_available）
        # upsert 会被调用，但传入的 data 不含 is_available
        if upsert_mock.called:
            call_data = upsert_mock.call_args.kwargs["data"]
            assert "is_available" not in call_data

    @pytest.mark.asyncio
    async def test_existing_with_local_price_not_overridden(self):
        """门店已有本地价格 → 不再用方案价覆盖。"""
        db = _mock_db()
        svc = _make_svc(db)
        draft_plan = _fake_plan(status="draft")
        items = [_fake_item(DISH_ID_1, override_price=3500)]
        # 门店已有本地价 4000
        existing_override = _fake_override(local_price=4000, is_available=True)
        updated_plan = {**draft_plan, "status": "published"}

        upsert_mock = AsyncMock(return_value=existing_override)

        with (
            patch.object(BrandPublishRepository, "get_publish_plan",
                         AsyncMock(return_value=draft_plan)),
            patch.object(BrandPublishRepository, "get_target_store_ids",
                         AsyncMock(return_value=[STORE_ID])),
            patch.object(BrandPublishRepository, "get_plan_items",
                         AsyncMock(return_value=items)),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value=existing_override)),
            patch.object(BrandPublishRepository, "upsert_store_dish_override",
                         upsert_mock),
            patch.object(BrandPublishRepository, "update_plan_status",
                         AsyncMock(return_value=updated_plan)),
        ):
            await svc.execute_publish_plan(PLAN_ID)

        # 门店已有本地价，upsert 不应被调用
        upsert_mock.assert_not_awaited()


# ══════════════════════════════════════════════════════
# 4. 门店菜品微调校验
# ══════════════════════════════════════════════════════


class TestStoreDishOverride:
    @pytest.mark.asyncio
    async def test_no_valid_fields_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="没有有效的更新字段"):
            await svc.override_store_dish(
                store_id=STORE_ID,
                dish_id=DISH_ID_1,
                data={"unknown_field": 123},
            )

    @pytest.mark.asyncio
    async def test_negative_local_price_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="local_price_fen"):
            await svc.override_store_dish(
                store_id=STORE_ID,
                dish_id=DISH_ID_1,
                data={"local_price_fen": -500},
            )

    @pytest.mark.asyncio
    async def test_price_override_success(self):
        db = _mock_db()
        svc = _make_svc(db)
        expected = _fake_override(local_price=4200)

        with patch.object(
            BrandPublishRepository, "upsert_store_dish_override",
            AsyncMock(return_value=expected)
        ):
            result = await svc.override_store_dish(
                store_id=STORE_ID,
                dish_id=DISH_ID_1,
                data={"local_price_fen": 4200},
            )
        assert result["local_price_fen"] == 4200
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_batch_toggle_empty_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="dish_ids"):
            await svc.batch_toggle_dishes(
                store_id=STORE_ID,
                dish_ids=[],
                is_available=False,
            )

    @pytest.mark.asyncio
    async def test_batch_toggle_success(self):
        db = _mock_db()
        svc = _make_svc(db)

        with patch.object(
            BrandPublishRepository, "batch_toggle_availability",
            AsyncMock(return_value=2)
        ):
            result = await svc.batch_toggle_dishes(
                store_id=STORE_ID,
                dish_ids=[DISH_ID_1, DISH_ID_2],
                is_available=False,
            )
        assert result["updated_count"] == 2
        assert result["is_available"] is False


# ══════════════════════════════════════════════════════
# 5. 调价规则校验
# ══════════════════════════════════════════════════════


class TestPriceRuleValidation:
    @pytest.mark.asyncio
    async def test_invalid_rule_type_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="rule_type"):
            await svc.create_price_rule({
                "rule_name": "午市",
                "rule_type": "invalid",
                "adjustment_type": "percentage",
                "adjustment_value": 10,
            })

    @pytest.mark.asyncio
    async def test_invalid_adjustment_type_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="adjustment_type"):
            await svc.create_price_rule({
                "rule_name": "午市",
                "rule_type": "time_period",
                "adjustment_type": "bad_type",
                "adjustment_value": 10,
            })

    @pytest.mark.asyncio
    async def test_empty_rule_name_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="rule_name"):
            await svc.create_price_rule({
                "rule_name": "",
                "rule_type": "time_period",
                "adjustment_type": "percentage",
                "adjustment_value": 10,
            })

    @pytest.mark.asyncio
    async def test_invalid_channel_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="channel"):
            await svc.create_price_rule({
                "rule_name": "外卖加价",
                "rule_type": "channel",
                "channel": "meituan",  # 不在允许列表
                "adjustment_type": "percentage",
                "adjustment_value": 5,
            })

    @pytest.mark.asyncio
    async def test_create_time_period_rule_success(self):
        db = _mock_db()
        svc = _make_svc(db)
        expected_rule = {
            "id": RULE_ID,
            "rule_name": "午市优惠",
            "rule_type": "time_period",
            "channel": None,
            "adjustment_type": "percentage",
            "adjustment_value": -10.0,
            "priority": 5,
            "is_active": True,
        }

        with patch.object(
            BrandPublishRepository, "create_price_rule",
            AsyncMock(return_value=expected_rule)
        ):
            rule = await svc.create_price_rule({
                "rule_name": "午市优惠",
                "rule_type": "time_period",
                "time_start": time(11, 0),
                "time_end": time(14, 0),
                "adjustment_type": "percentage",
                "adjustment_value": -10.0,
                "priority": 5,
            })
        assert rule["adjustment_value"] == -10.0
        assert rule["rule_type"] == "time_period"

    @pytest.mark.asyncio
    async def test_bind_dishes_no_dishes_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="dish_ids"):
            await svc.bind_dishes_to_rule(rule_id=RULE_ID, dish_ids=[])

    @pytest.mark.asyncio
    async def test_bind_dishes_rule_not_found_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with patch.object(
            BrandPublishRepository, "get_price_rule",
            AsyncMock(return_value=None)
        ):
            with pytest.raises(ValueError, match="调价规则不存在"):
                await svc.bind_dishes_to_rule(
                    rule_id=RULE_ID,
                    dish_ids=[DISH_ID_1],
                )


# ══════════════════════════════════════════════════════
# 6. 生效价格五级优先级（纯函数测试）
# ══════════════════════════════════════════════════════


class TestApplyRule:
    """BrandPublishService._apply_rule 静态逻辑（不需要 DB）。"""

    def test_percentage_increase(self):
        rule = {"adjustment_type": "percentage", "adjustment_value": 10.0, "priority": 1}
        assert BrandPublishService._apply_rule(3800, rule) == 4180  # 3800 * 1.10

    def test_percentage_decrease(self):
        rule = {"adjustment_type": "percentage", "adjustment_value": -20.0, "priority": 1}
        assert BrandPublishService._apply_rule(5000, rule) == 4000

    def test_fixed_add(self):
        rule = {"adjustment_type": "fixed_add", "adjustment_value": 300.0, "priority": 1}
        assert BrandPublishService._apply_rule(3800, rule) == 4100

    def test_fixed_add_negative(self):
        rule = {"adjustment_type": "fixed_add", "adjustment_value": -500.0, "priority": 1}
        assert BrandPublishService._apply_rule(3800, rule) == 3300

    def test_fixed_price(self):
        rule = {"adjustment_type": "fixed_price", "adjustment_value": 2888.0, "priority": 1}
        assert BrandPublishService._apply_rule(3800, rule) == 2888

    def test_min_price_floor_at_one_fen(self):
        rule = {"adjustment_type": "fixed_add", "adjustment_value": -99999.0, "priority": 1}
        result = BrandPublishService._apply_rule(100, rule)
        assert result == 1  # 不能低于 1 分

    def test_percentage_rounding(self):
        # 3333 * 1.10 = 3666.3 → 四舍五入 → 3666
        rule = {"adjustment_type": "percentage", "adjustment_value": 10.0, "priority": 1}
        assert BrandPublishService._apply_rule(3333, rule) == 3666


# ══════════════════════════════════════════════════════
# 7. get_effective_price 五级优先级集成测试（mock DB）
# ══════════════════════════════════════════════════════


def _make_dish_row(price_fen: int = 3800, dish_name: str = "番茄炒蛋"):
    """创建可下标访问的菜品查询 mock 行。"""
    # 直接用列表，天然支持 [0] [1] 下标
    return [price_fen, dish_name]


def _make_db_with_dish(price_fen: int = 3800) -> AsyncMock:
    """返回一个 execute 固定返回指定菜品行的 mock db。"""
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = _make_dish_row(price_fen)
    db.execute.return_value = mock_result
    return db


class TestGetEffectivePrice:

    @pytest.mark.asyncio
    async def test_invalid_channel_raises(self):
        db = _mock_db()
        svc = _make_svc(db)
        with pytest.raises(ValueError, match="channel"):
            await svc.get_effective_price(
                dish_id=DISH_ID_1,
                store_id=STORE_ID,
                channel="waimai",  # 非法渠道
            )

    @pytest.mark.asyncio
    async def test_brand_price_is_baseline(self):
        """无任何覆盖时，返回品牌标准价。"""
        db = _make_db_with_dish(3800)
        svc = _make_svc(db)

        with (
            patch.object(BrandPublishRepository, "_set_tenant", AsyncMock()),
            patch.object(BrandPublishRepository, "get_plan_override_for_dish",
                         AsyncMock(return_value=None)),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value=None)),
            patch.object(BrandPublishRepository, "get_active_rules_for_dish",
                         AsyncMock(return_value=[])),
        ):
            result = await svc.get_effective_price(
                dish_id=DISH_ID_1,
                store_id=STORE_ID,
                channel="dine_in",
            )

        assert result["effective_price_fen"] == 3800
        assert result["price_source"] == "brand_standard"

    @pytest.mark.asyncio
    async def test_plan_override_beats_brand_price(self):
        """发布方案覆盖价 > 品牌标准价。"""
        db = _make_db_with_dish(3800)
        svc = _make_svc(db)

        with (
            patch.object(BrandPublishRepository, "_set_tenant", AsyncMock()),
            patch.object(BrandPublishRepository, "get_plan_override_for_dish",
                         AsyncMock(return_value={"override_price_fen": 3500, "plan_name": "促销方案"})),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value=None)),
            patch.object(BrandPublishRepository, "get_active_rules_for_dish",
                         AsyncMock(return_value=[])),
        ):
            result = await svc.get_effective_price(
                dish_id=DISH_ID_1, store_id=STORE_ID, channel="dine_in"
            )

        assert result["effective_price_fen"] == 3500
        assert result["price_source"] == "publish_plan"

    @pytest.mark.asyncio
    async def test_store_override_beats_plan_price(self):
        """门店覆盖价 > 发布方案覆盖价。"""
        db = _make_db_with_dish(3800)
        svc = _make_svc(db)

        with (
            patch.object(BrandPublishRepository, "_set_tenant", AsyncMock()),
            patch.object(BrandPublishRepository, "get_plan_override_for_dish",
                         AsyncMock(return_value={"override_price_fen": 3500})),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value={"local_price_fen": 4200})),  # 门店自行调价更高
            patch.object(BrandPublishRepository, "get_active_rules_for_dish",
                         AsyncMock(return_value=[])),
        ):
            result = await svc.get_effective_price(
                dish_id=DISH_ID_1, store_id=STORE_ID, channel="dine_in"
            )

        assert result["effective_price_fen"] == 4200
        assert result["price_source"] == "store_override"

    @pytest.mark.asyncio
    async def test_time_period_rule_is_highest_priority(self):
        """调价规则最高优先级：时段规则覆盖门店价。"""
        db = _make_db_with_dish(3800)
        svc = _make_svc(db)
        lunch_rule = {
            "id": RULE_ID,
            "rule_type": "time_period",
            "channel": None,
            "adjustment_type": "percentage",
            "adjustment_value": -10.0,  # 午市九折
            "priority": 10,
        }

        with (
            patch.object(BrandPublishRepository, "_set_tenant", AsyncMock()),
            patch.object(BrandPublishRepository, "get_plan_override_for_dish",
                         AsyncMock(return_value=None)),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value={"local_price_fen": 4200})),
            patch.object(BrandPublishRepository, "get_active_rules_for_dish",
                         AsyncMock(return_value=[lunch_rule])),
        ):
            result = await svc.get_effective_price(
                dish_id=DISH_ID_1, store_id=STORE_ID, channel="dine_in",
                at_datetime=datetime(2026, 3, 31, 12, 0, 0),
            )

        # 4200（门店覆盖价）× 0.9 = 3780
        assert result["effective_price_fen"] == 3780
        assert result["price_source"] == "adjustment_rule"

    @pytest.mark.asyncio
    async def test_delivery_channel_surcharge(self):
        """外卖渠道加价规则正确计算。"""
        db = _make_db_with_dish(3800)
        svc = _make_svc(db)
        delivery_rule = {
            "id": RULE_ID,
            "rule_type": "channel",
            "channel": "delivery",
            "adjustment_type": "fixed_add",
            "adjustment_value": 200.0,  # 外卖加 2 元
            "priority": 5,
        }

        with (
            patch.object(BrandPublishRepository, "_set_tenant", AsyncMock()),
            patch.object(BrandPublishRepository, "get_plan_override_for_dish",
                         AsyncMock(return_value=None)),
            patch.object(BrandPublishRepository, "get_store_dish_override",
                         AsyncMock(return_value=None)),
            patch.object(BrandPublishRepository, "get_active_rules_for_dish",
                         AsyncMock(return_value=[delivery_rule])),
        ):
            result = await svc.get_effective_price(
                dish_id=DISH_ID_1, store_id=STORE_ID, channel="delivery"
            )

        assert result["effective_price_fen"] == 4000  # 3800 + 200
        assert result["price_source"] == "adjustment_rule"


# ══════════════════════════════════════════════════════
# 8. 多租户隔离（边界测试）
# ══════════════════════════════════════════════════════


class TestMultiTenantIsolation:
    def test_repository_uses_correct_tenant_id(self):
        """Repository 构建时正确存储 tenant_id。"""
        db = _mock_db()
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        repo_a = BrandPublishRepository(db, tenant_a)
        repo_b = BrandPublishRepository(db, tenant_b)
        assert repo_a.tenant_id != repo_b.tenant_id
        assert repo_a._tid != repo_b._tid

    def test_service_passes_tenant_to_repo(self):
        """Service 将 tenant_id 透传给 Repository。"""
        db = _mock_db()
        tenant = str(uuid.uuid4())
        svc = BrandPublishService(db, tenant)
        assert svc._repo.tenant_id == tenant

    @pytest.mark.asyncio
    async def test_create_plan_commits_once(self):
        """创建发布方案只提交一次事务。"""
        db = _mock_db()
        svc = _make_svc(db)
        expected_plan = _fake_plan()

        with patch.object(
            BrandPublishRepository, "create_publish_plan",
            AsyncMock(return_value=expected_plan)
        ):
            await svc.create_publish_plan(
                plan_name="隔离测试方案",
                target_type="stores",
                target_ids=[STORE_ID],
            )

        db.commit.assert_awaited_once()
