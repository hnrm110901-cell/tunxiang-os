"""Sprint E2 — publisher 框架测试

覆盖：
  · DishPublishSpec 合法性（价非负 / name 非空 / stock 非负 / override_for）
  · PublishResult success/failure 工厂 + to_dict 契约
  · DeliveryPublisher ABC：默认 pause/resume/update_full 合成
  · Registry：register/get/unknown/list
  · 5 平台 stub：publish 成功 + 失败模拟（FAIL_ 前缀） + update_price/stock/unpublish
  · publish_to_platform 便捷函数各 operation 分支
  · v286 迁移静态断言

不测试：
  · Orchestrator（需要 DB，留 integration test）
  · 真实 SDK 调用（需要真 API credentials）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.adapters.delivery_publish import (  # noqa: E402
    DeliveryPublisher,
    DishPublishSpec,
    PublishOperation,
    PublishResult,
    PublishStatus,
    get_publisher,
    list_registered_publishers,
    publish_to_platform,
    register_publisher,
)
from shared.adapters.delivery_publish.base import PublishError  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
DISH = "00000000-0000-0000-0000-000000000099"
SHOP = "poi_xxx_001"


def _run(coro):
    return asyncio.run(coro)


def _spec(**overrides) -> DishPublishSpec:
    base = {
        "dish_id": DISH,
        "name": "鱼香肉丝",
        "category": "川菜/热菜",
        "price_fen": 2800,
        "stock": 100,
    }
    base.update(overrides)
    return DishPublishSpec(**base)


# ─────────────────────────────────────────────────────────────
# 1. DishPublishSpec
# ─────────────────────────────────────────────────────────────


class TestDishPublishSpec:
    def test_happy_path(self):
        s = _spec()
        assert s.price_fen == 2800
        assert s.stock == 100

    def test_rejects_negative_price(self):
        with pytest.raises(PublishError, match="price_fen"):
            _spec(price_fen=-1)

    def test_rejects_empty_name(self):
        with pytest.raises(PublishError, match="name"):
            _spec(name="  ")

    def test_rejects_empty_dish_id(self):
        with pytest.raises(PublishError, match="dish_id"):
            _spec(dish_id="")

    def test_rejects_negative_stock(self):
        with pytest.raises(PublishError, match="stock"):
            _spec(stock=-5)

    def test_allows_none_stock(self):
        """stock=None 表示不限库存，合法"""
        s = _spec(stock=None)
        assert s.stock is None

    def test_override_for_platform(self):
        s = _spec(
            platform_overrides={
                "meituan": {"specId": "M123"},
                "eleme": {"categoryChainId": "E456"},
            }
        )
        assert s.override_for("meituan") == {"specId": "M123"}
        assert s.override_for("douyin") == {}

    def test_to_dict_contract(self):
        s = _spec()
        d = s.to_dict()
        for key in (
            "dish_id", "name", "category", "price_fen", "stock",
            "image_urls", "tags", "platform_overrides",
        ):
            assert key in d


# ─────────────────────────────────────────────────────────────
# 2. PublishResult
# ─────────────────────────────────────────────────────────────


class TestPublishResult:
    def test_success_factory(self):
        r = PublishResult.success(
            platform="meituan",
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED,
            platform_sku_id="x",
            published_price_fen=2800,
        )
        assert r.ok is True
        assert r.platform_sku_id == "x"
        assert r.error_message is None

    def test_failure_factory(self):
        r = PublishResult.failure(
            platform="eleme",
            operation=PublishOperation.PUBLISH,
            error_message="token expired",
            error_code="AUTH_FAILED",
        )
        assert r.ok is False
        assert r.status == PublishStatus.ERROR
        assert r.error_code == "AUTH_FAILED"

    def test_to_dict_contract(self):
        d = PublishResult.success(
            platform="meituan",
            operation=PublishOperation.PUBLISH,
            status=PublishStatus.PUBLISHED,
            platform_sku_id="x",
        ).to_dict()
        for key in (
            "platform", "operation", "status", "ok", "platform_sku_id",
            "published_price_fen", "published_stock", "error_message",
        ):
            assert key in d
        assert d["operation"] == "publish"


# ─────────────────────────────────────────────────────────────
# 3. Registry
# ─────────────────────────────────────────────────────────────


class TestRegistry:
    def test_list_has_5_platforms(self):
        registered = list_registered_publishers()
        for p in ("meituan", "eleme", "douyin", "xiaohongshu", "wechat"):
            assert p in registered

    def test_get_unknown_raises(self):
        with pytest.raises(PublishError, match="找不到"):
            get_publisher("not_a_platform")

    def test_register_rejects_bad_platform(self):
        class BadPublisher(DeliveryPublisher):
            platform = "invalid_platform"

            async def publish(self, **kw): ...
            async def update_price(self, **kw): ...
            async def update_stock(self, **kw): ...
            async def unpublish(self, **kw): ...

        with pytest.raises(ValueError, match="ALLOWED_PLATFORMS"):
            register_publisher(BadPublisher())


# ─────────────────────────────────────────────────────────────
# 4. 5 平台 Stub Publisher
# ─────────────────────────────────────────────────────────────


class TestStubPublishers:
    @pytest.mark.parametrize(
        "platform",
        ["meituan", "eleme", "douyin", "xiaohongshu", "wechat"],
    )
    def test_publish_success_returns_sku(self, platform):
        publisher = get_publisher(platform)
        result = _run(
            publisher.publish(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(),
            )
        )
        assert result.ok is True
        assert result.status == PublishStatus.PUBLISHED
        assert result.platform_sku_id
        assert result.published_price_fen == 2800

    @pytest.mark.parametrize(
        "platform",
        ["meituan", "eleme", "douyin", "xiaohongshu", "wechat"],
    )
    def test_publish_failure_with_fail_prefix(self, platform):
        publisher = get_publisher(platform)
        result = _run(
            publisher.publish(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(dish_id="FAIL_test_001"),
            )
        )
        assert result.ok is False
        assert result.status == PublishStatus.ERROR
        assert result.error_message
        assert result.error_code

    @pytest.mark.parametrize(
        "platform",
        ["meituan", "eleme", "douyin"],
    )
    def test_update_price(self, platform):
        publisher = get_publisher(platform)
        result = _run(
            publisher.update_price(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                platform_sku_id="sku_x",
                price_fen=3300,
                original_price_fen=4000,
            )
        )
        assert result.ok is True
        assert result.published_price_fen == 3300
        assert result.operation == PublishOperation.UPDATE_PRICE

    def test_update_stock_sold_out(self):
        publisher = get_publisher("meituan")
        result = _run(
            publisher.update_stock(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                platform_sku_id="sku_x",
                stock=0,
            )
        )
        assert result.ok is True
        assert result.status == PublishStatus.SOLD_OUT
        assert result.published_stock == 0

    def test_update_stock_unlimited(self):
        publisher = get_publisher("eleme")
        result = _run(
            publisher.update_stock(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                platform_sku_id="sku_x",
                stock=None,
            )
        )
        assert result.ok is True
        assert result.published_stock == 9999  # stub convention

    def test_unpublish(self):
        publisher = get_publisher("douyin")
        result = _run(
            publisher.unpublish(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                platform_sku_id="sku_x",
            )
        )
        assert result.ok is True
        assert result.status == PublishStatus.UNPUBLISHED

    def test_default_pause_calls_update_stock_zero(self):
        """ABC 默认 pause() 实现：调 update_stock(0)"""
        publisher = get_publisher("meituan")
        result = _run(
            publisher.pause(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                platform_sku_id="sku_x",
            )
        )
        assert result.ok is True
        assert result.status == PublishStatus.SOLD_OUT
        assert result.published_stock == 0

    def test_default_update_full_composes_price_and_stock(self):
        publisher = get_publisher("meituan")
        result = _run(
            publisher.update_full(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                platform_sku_id="sku_x",
                spec=_spec(price_fen=5000, stock=50),
            )
        )
        assert result.ok is True
        assert result.operation == PublishOperation.UPDATE_FULL
        assert result.published_price_fen == 5000
        assert result.published_stock == 50

    def test_wechat_sku_equals_dish_id(self):
        """微信自营 SKU = internal dish_id"""
        publisher = get_publisher("wechat")
        result = _run(
            publisher.publish(
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(),
            )
        )
        assert result.platform_sku_id == DISH


# ─────────────────────────────────────────────────────────────
# 5. publish_to_platform 便捷函数
# ─────────────────────────────────────────────────────────────


class TestPublishToPlatform:
    def test_publish_operation_no_sku_needed(self):
        result = _run(
            publish_to_platform(
                platform="meituan",
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(),
                operation=PublishOperation.PUBLISH,
            )
        )
        assert result.ok is True

    def test_update_price_requires_sku(self):
        with pytest.raises(PublishError, match="platform_sku_id"):
            _run(
                publish_to_platform(
                    platform="meituan",
                    tenant_id=TENANT,
                    platform_shop_id=SHOP,
                    spec=_spec(),
                    operation=PublishOperation.UPDATE_PRICE,
                    platform_sku_id=None,
                )
            )

    def test_update_stock_with_sku(self):
        result = _run(
            publish_to_platform(
                platform="eleme",
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(stock=10),
                operation=PublishOperation.UPDATE_STOCK,
                platform_sku_id="sku_existing",
            )
        )
        assert result.ok is True
        assert result.published_stock == 10

    def test_update_full_requires_sku(self):
        with pytest.raises(PublishError):
            _run(
                publish_to_platform(
                    platform="meituan",
                    tenant_id=TENANT,
                    platform_shop_id=SHOP,
                    spec=_spec(),
                    operation=PublishOperation.UPDATE_FULL,
                    platform_sku_id=None,
                )
            )

    def test_pause_with_sku(self):
        result = _run(
            publish_to_platform(
                platform="douyin",
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(),
                operation=PublishOperation.PAUSE,
                platform_sku_id="sku_x",
            )
        )
        assert result.ok is True
        assert result.status == PublishStatus.SOLD_OUT

    def test_resume_with_stock(self):
        result = _run(
            publish_to_platform(
                platform="douyin",
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(stock=50),
                operation=PublishOperation.RESUME,
                platform_sku_id="sku_x",
            )
        )
        assert result.ok is True
        assert result.published_stock == 50

    def test_unpublish(self):
        result = _run(
            publish_to_platform(
                platform="xiaohongshu",
                tenant_id=TENANT,
                platform_shop_id=SHOP,
                spec=_spec(),
                operation=PublishOperation.UNPUBLISH,
                platform_sku_id="sku_x",
            )
        )
        assert result.ok is True
        assert result.status == PublishStatus.UNPUBLISHED


# ─────────────────────────────────────────────────────────────
# 6. Custom Publisher 覆盖 stub
# ─────────────────────────────────────────────────────────────


class TestCustomPublisher:
    def test_register_custom_meituan_overrides_stub(self):
        """允许测试 / 灰度环境用自定义 publisher 覆盖默认 stub"""

        class CustomMeituanPublisher(DeliveryPublisher):
            platform = "meituan"

            async def publish(self, **kw):
                return PublishResult.success(
                    platform=self.platform,
                    operation=PublishOperation.PUBLISH,
                    status=PublishStatus.PUBLISHED,
                    platform_sku_id="CUSTOM_SKU",
                    published_price_fen=kw["spec"].price_fen,
                )

            async def update_price(self, **kw):
                return PublishResult.success(
                    platform=self.platform,
                    operation=PublishOperation.UPDATE_PRICE,
                    status=PublishStatus.PUBLISHED,
                )

            async def update_stock(self, **kw):
                return PublishResult.success(
                    platform=self.platform,
                    operation=PublishOperation.UPDATE_STOCK,
                    status=PublishStatus.PUBLISHED,
                )

            async def unpublish(self, **kw):
                return PublishResult.success(
                    platform=self.platform,
                    operation=PublishOperation.UNPUBLISH,
                    status=PublishStatus.UNPUBLISHED,
                )

        # 保存原 stub 以便测试后恢复
        from shared.adapters.delivery_publish.publishers import MeituanPublisher

        try:
            register_publisher(CustomMeituanPublisher())
            result = _run(
                get_publisher("meituan").publish(
                    tenant_id=TENANT, platform_shop_id=SHOP, spec=_spec()
                )
            )
            assert result.platform_sku_id == "CUSTOM_SKU"
        finally:
            # 还原
            register_publisher(MeituanPublisher())


# ─────────────────────────────────────────────────────────────
# 7. v286 迁移静态断言
# ─────────────────────────────────────────────────────────────


class TestV286Migration:
    @pytest.fixture
    def migration_source(self) -> str:
        path = (
            ROOT
            / "shared"
            / "db-migrations"
            / "versions"
            / "v286_dish_publish_registry.py"
        )
        return path.read_text(encoding="utf-8")

    def test_revision_chain(self, migration_source):
        assert 'revision = "v286_dish_publish"' in migration_source
        assert 'down_revision = "v285_canonical_delivery"' in migration_source

    def test_table_names(self, migration_source):
        assert "dish_publish_registry" in migration_source
        assert "dish_publish_tasks" in migration_source

    def test_all_7_registry_statuses(self, migration_source):
        for s in (
            "pending",
            "publishing",
            "published",
            "paused",
            "sold_out",
            "unpublished",
            "error",
        ):
            assert f"'{s}'" in migration_source

    def test_all_7_operations(self, migration_source):
        for op in (
            "publish",
            "update_price",
            "update_stock",
            "update_full",
            "pause",
            "resume",
            "unpublish",
        ):
            assert f"'{op}'" in migration_source

    def test_5_platforms_in_check(self, migration_source):
        for p in ("meituan", "eleme", "douyin", "xiaohongshu", "wechat"):
            assert f"'{p}'" in migration_source

    def test_consecutive_error_count_field(self, migration_source):
        assert "consecutive_error_count" in migration_source

    def test_unique_idempotent_index(self, migration_source):
        assert "ux_dish_publish_registry_unique" in migration_source

    def test_rls_on_both_tables(self, migration_source):
        assert (
            "ALTER TABLE dish_publish_registry ENABLE ROW LEVEL SECURITY"
            in migration_source
        )
        assert (
            "ALTER TABLE dish_publish_tasks ENABLE ROW LEVEL SECURITY"
            in migration_source
        )

    def test_task_queue_index(self, migration_source):
        """Worker 拉队列的索引必须存在"""
        assert "idx_dish_publish_tasks_queue" in migration_source
