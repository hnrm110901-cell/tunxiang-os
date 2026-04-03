"""菜单版本管理 + 集团模板下发测试

覆盖：
  1. 创建版本（菜品快照）
  2. 发布版本到指定门店（全量/部分）
  3. 灰度发布（5% 门店先试验，再全量推送）
  4. 门店微调（增菜/停菜/改价，叠加基础版本）
  5. 版本回滚（回到上一个已发布版本）
  6. 下发记录（版本下发进度追踪）
  7. 租户隔离（不同 tenant_id 数据互不可见）
"""
import uuid

import pytest

from ..services.menu_dispatch_service import MenuDispatchService
from ..services.menu_version_service import (
    MenuVersionService,
    _clear_all,
)

# ─── 常量 ───

TENANT = str(uuid.uuid4())
BRAND = str(uuid.uuid4())

# 模拟 20 家门店
ALL_STORES = [str(uuid.uuid4()) for _ in range(20)]
STORE_A = ALL_STORES[0]
STORE_B = ALL_STORES[1]

SNAPSHOT = [
    {"dish_id": "d1", "dish_name": "剁椒鱼头", "price_fen": 8800, "status": "active"},
    {"dish_id": "d2", "dish_name": "小炒肉", "price_fen": 4200, "status": "active"},
    {"dish_id": "d3", "dish_name": "米饭", "price_fen": 300, "status": "active"},
]


# ─── Fixture ───


@pytest.fixture(autouse=True)
def _clean():
    """每个测试前清空内存存储"""
    _clear_all()
    yield
    _clear_all()


# ═══════════════════════════════════════════
# 1. 创建版本（菜品快照）
# ═══════════════════════════════════════════


class TestCreateVersion:
    @pytest.mark.asyncio
    async def test_create_version_basic(self):
        """创建版本成功，返回 draft 状态"""
        v = await MenuVersionService.create_version(
            brand_id=BRAND,
            version_name="春季新菜单",
            tenant_id=TENANT,
            dishes_snapshot=SNAPSHOT,
        )
        assert v["status"] == "draft"
        assert v["version_name"] == "春季新菜单"
        assert v["brand_id"] == BRAND
        assert v["tenant_id"] == TENANT
        assert len(v["dishes_snapshot"]) == 3
        assert v["published_at"] is None

    @pytest.mark.asyncio
    async def test_version_no_auto_generated(self):
        """版本号自动生成，格式 YYYY.QN.vN"""
        v = await MenuVersionService.create_version(
            brand_id=BRAND,
            tenant_id=TENANT,
            dishes_snapshot=SNAPSHOT,
        )
        assert "." in v["version_no"]
        assert v["version_no"].startswith("202")

    @pytest.mark.asyncio
    async def test_version_no_increments(self):
        """同品牌同季度版本号递增"""
        v1 = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        v2 = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        assert v1["version_no"] != v2["version_no"]
        # v2 序号比 v1 大
        seq1 = int(v1["version_no"].split("v")[-1])
        seq2 = int(v2["version_no"].split("v")[-1])
        assert seq2 > seq1

    @pytest.mark.asyncio
    async def test_empty_snapshot_allowed(self):
        """空快照合法（草稿阶段可以先建版本再填充）"""
        v = await MenuVersionService.create_version(
            brand_id=BRAND,
            tenant_id=TENANT,
        )
        assert v["dishes_snapshot"] == []

    @pytest.mark.asyncio
    async def test_empty_tenant_raises(self):
        """空 tenant_id 抛出异常"""
        with pytest.raises(ValueError, match="tenant_id"):
            await MenuVersionService.create_version(brand_id=BRAND, tenant_id="", dishes_snapshot=SNAPSHOT)

    @pytest.mark.asyncio
    async def test_empty_brand_raises(self):
        """空 brand_id 抛出异常"""
        with pytest.raises(ValueError, match="brand_id"):
            await MenuVersionService.create_version(brand_id="", tenant_id=TENANT, dishes_snapshot=SNAPSHOT)

    @pytest.mark.asyncio
    async def test_get_version(self):
        """可以按 ID 获取版本"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        fetched = await MenuVersionService.get_version(v["id"], TENANT)
        assert fetched is not None
        assert fetched["id"] == v["id"]

    @pytest.mark.asyncio
    async def test_list_versions_pagination(self):
        """版本列表支持分页"""
        for i in range(5):
            await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        result = await MenuVersionService.list_versions(tenant_id=TENANT, brand_id=BRAND, page=1, size=3)
        assert result["total"] == 5
        assert len(result["items"]) == 3


# ═══════════════════════════════════════════
# 2. 发布版本到指定门店（全量/部分门店）
# ═══════════════════════════════════════════


class TestPublishToStores:
    @pytest.mark.asyncio
    async def test_publish_to_single_store(self):
        """下发版本到单个门店"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        records = await MenuVersionService.publish_to_stores(
            version_id=v["id"],
            store_ids=[STORE_A],
            tenant_id=TENANT,
        )
        assert len(records) == 1
        assert records[0]["store_id"] == STORE_A
        assert records[0]["status"] == "pending"
        assert records[0]["dispatch_type"] == "full"

    @pytest.mark.asyncio
    async def test_publish_to_multiple_stores(self):
        """下发版本到多个门店，每个门店各一条记录"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        records = await MenuVersionService.publish_to_stores(
            version_id=v["id"],
            store_ids=[STORE_A, STORE_B],
            tenant_id=TENANT,
        )
        assert len(records) == 2
        store_ids_in_records = {r["store_id"] for r in records}
        assert STORE_A in store_ids_in_records
        assert STORE_B in store_ids_in_records

    @pytest.mark.asyncio
    async def test_publish_updates_version_status(self):
        """首次下发后，版本状态从 draft 变 published"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        assert v["status"] == "draft"
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        updated = await MenuVersionService.get_version(v["id"], TENANT)
        assert updated["status"] == "published"
        assert updated["published_at"] is not None

    @pytest.mark.asyncio
    async def test_publish_nonexistent_version_raises(self):
        """下发不存在的版本抛出异常"""
        with pytest.raises(ValueError, match="版本不存在"):
            await MenuVersionService.publish_to_stores(
                version_id=str(uuid.uuid4()),
                store_ids=[STORE_A],
                tenant_id=TENANT,
            )

    @pytest.mark.asyncio
    async def test_publish_empty_stores_raises(self):
        """空门店列表抛出异常"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        with pytest.raises(ValueError, match="store_ids"):
            await MenuVersionService.publish_to_stores(
                version_id=v["id"], store_ids=[], tenant_id=TENANT
            )

    @pytest.mark.asyncio
    async def test_confirm_applied(self):
        """门店确认应用后，record status 变 applied"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        records = await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        record_id = records[0]["id"]
        applied = await MenuVersionService.confirm_applied(record_id=record_id, tenant_id=TENANT)
        assert applied["status"] == "applied"
        assert applied["applied_at"] is not None


# ═══════════════════════════════════════════
# 3. 灰度发布
# ═══════════════════════════════════════════


class TestPilotDispatch:
    @pytest.mark.asyncio
    async def test_pilot_selects_correct_ratio(self):
        """灰度 5% — 20 家门店选 1 家（至少 1 家）"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        result = await MenuDispatchService.pilot_dispatch(
            version_id=v["id"],
            all_store_ids=ALL_STORES,
            tenant_id=TENANT,
            pilot_ratio=0.05,
        )
        assert len(result["pilot_stores"]) >= 1
        assert len(result["pilot_stores"]) + len(result["remaining_stores"]) == len(ALL_STORES)

    @pytest.mark.asyncio
    async def test_pilot_10_percent(self):
        """灰度 10% — 20 家门店选 2 家"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        result = await MenuDispatchService.pilot_dispatch(
            version_id=v["id"],
            all_store_ids=ALL_STORES,
            tenant_id=TENANT,
            pilot_ratio=0.10,
        )
        assert len(result["pilot_stores"]) == 2
        assert len(result["remaining_stores"]) == 18

    @pytest.mark.asyncio
    async def test_pilot_records_are_pilot_type(self):
        """灰度下发记录 dispatch_type=pilot"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        result = await MenuDispatchService.pilot_dispatch(
            version_id=v["id"],
            all_store_ids=ALL_STORES,
            tenant_id=TENANT,
        )
        for r in result["records"]:
            assert r["dispatch_type"] == "pilot"

    @pytest.mark.asyncio
    async def test_promote_pilot_to_full(self):
        """灰度确认 OK 后，全量推送剩余门店"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        pilot_result = await MenuDispatchService.pilot_dispatch(
            version_id=v["id"],
            all_store_ids=ALL_STORES,
            tenant_id=TENANT,
            pilot_ratio=0.05,
        )
        remaining = pilot_result["remaining_stores"]
        promote_result = await MenuDispatchService.promote_pilot_to_full(
            version_id=v["id"],
            remaining_store_ids=remaining,
            tenant_id=TENANT,
        )
        assert promote_result["promoted_count"] == len(remaining)
        assert len(promote_result["records"]) == len(remaining)

    @pytest.mark.asyncio
    async def test_pilot_invalid_ratio_raises(self):
        """灰度比例超出 (0, 1] 范围抛出异常"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        with pytest.raises(ValueError, match="pilot_ratio"):
            await MenuDispatchService.pilot_dispatch(
                version_id=v["id"],
                all_store_ids=ALL_STORES,
                tenant_id=TENANT,
                pilot_ratio=0.0,
            )


# ═══════════════════════════════════════════
# 4. 门店微调
# ═══════════════════════════════════════════


class TestStoreOverride:
    @pytest.mark.asyncio
    async def test_add_dishes_override(self):
        """门店新增本店独有菜品"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        record = await MenuVersionService.apply_store_override(
            store_id=STORE_A,
            overrides={
                "add_dishes": [{"dish_id": "local-1", "dish_name": "本店特色", "price_fen": 5000}],
            },
            tenant_id=TENANT,
        )
        assert len(record["store_overrides"]["add_dishes"]) == 1
        assert record["store_overrides"]["add_dishes"][0]["dish_id"] == "local-1"

    @pytest.mark.asyncio
    async def test_remove_dishes_override(self):
        """门店停售菜品"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        record = await MenuVersionService.apply_store_override(
            store_id=STORE_A,
            overrides={"remove_dishes": ["d2", "d3"]},
            tenant_id=TENANT,
        )
        assert "d2" in record["store_overrides"]["remove_dishes"]
        assert "d3" in record["store_overrides"]["remove_dishes"]

    @pytest.mark.asyncio
    async def test_price_override(self):
        """门店价格覆盖"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        record = await MenuVersionService.apply_store_override(
            store_id=STORE_A,
            overrides={"price_overrides": {"d1": 9800}},
            tenant_id=TENANT,
        )
        assert record["store_overrides"]["price_overrides"]["d1"] == 9800

    @pytest.mark.asyncio
    async def test_override_merges_price(self):
        """多次微调价格覆盖：新的优先"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        await MenuVersionService.apply_store_override(
            store_id=STORE_A,
            overrides={"price_overrides": {"d1": 9800, "d2": 4500}},
            tenant_id=TENANT,
        )
        record = await MenuVersionService.apply_store_override(
            store_id=STORE_A,
            overrides={"price_overrides": {"d1": 10000}},  # 只更新 d1
            tenant_id=TENANT,
        )
        # d1 更新为 10000，d2 保留 4500
        assert record["store_overrides"]["price_overrides"]["d1"] == 10000
        assert record["store_overrides"]["price_overrides"]["d2"] == 4500

    @pytest.mark.asyncio
    async def test_override_no_dispatch_record_raises(self):
        """门店没有下发记录时，微调抛出异常"""
        with pytest.raises(ValueError, match="下发记录"):
            await MenuVersionService.apply_store_override(
                store_id=str(uuid.uuid4()),
                overrides={"remove_dishes": ["d1"]},
                tenant_id=TENANT,
            )

    @pytest.mark.asyncio
    async def test_override_does_not_modify_version(self):
        """微调不改变版本快照本身"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        original_snapshot = list(v["dishes_snapshot"])
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        await MenuVersionService.apply_store_override(
            store_id=STORE_A,
            overrides={"price_overrides": {"d1": 99999}},
            tenant_id=TENANT,
        )
        v_after = await MenuVersionService.get_version(v["id"], TENANT)
        assert v_after["dishes_snapshot"] == original_snapshot


# ═══════════════════════════════════════════
# 5. 版本回滚
# ═══════════════════════════════════════════


class TestVersionRollback:
    @pytest.mark.asyncio
    async def test_rollback_to_previous_version(self):
        """回滚门店到上一个已发布版本"""
        v1 = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v1["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        # 发布新版本
        v2 = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v2["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        # 回滚到 v1
        rollback_record = await MenuVersionService.rollback_store(
            store_id=STORE_A,
            version_id=v1["id"],
            tenant_id=TENANT,
        )
        assert rollback_record["version_id"] == v1["id"]
        assert rollback_record["store_id"] == STORE_A
        assert rollback_record["status"] == "pending"
        assert rollback_record["dispatch_type"] == "rollback"

    @pytest.mark.asyncio
    async def test_rollback_to_draft_version_raises(self):
        """不能回滚到 draft 版本"""
        v_draft = await MenuVersionService.create_version(
            brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT
        )
        with pytest.raises(ValueError, match="已发布版本"):
            await MenuVersionService.rollback_store(
                store_id=STORE_A,
                version_id=v_draft["id"],
                tenant_id=TENANT,
            )

    @pytest.mark.asyncio
    async def test_rollback_nonexistent_version_raises(self):
        """回滚到不存在的版本抛出异常"""
        with pytest.raises(ValueError, match="版本不存在"):
            await MenuVersionService.rollback_store(
                store_id=STORE_A,
                version_id=str(uuid.uuid4()),
                tenant_id=TENANT,
            )


# ═══════════════════════════════════════════
# 6. 下发记录与进度追踪
# ═══════════════════════════════════════════


class TestDispatchStatus:
    @pytest.mark.asyncio
    async def test_dispatch_status_all_pending(self):
        """下发后全部 pending"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=ALL_STORES[:5], tenant_id=TENANT
        )
        status = await MenuDispatchService.get_dispatch_status(
            version_id=v["id"], tenant_id=TENANT
        )
        assert status["total"] == 5
        assert status["pending"] == 5
        assert status["applied"] == 0
        assert status["failed"] == 0
        assert status["apply_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_dispatch_status_partial_applied(self):
        """部分门店应用后，进度正确"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        records = await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=ALL_STORES[:4], tenant_id=TENANT
        )
        # 确认前 2 家已应用
        await MenuVersionService.confirm_applied(record_id=records[0]["id"], tenant_id=TENANT)
        await MenuVersionService.confirm_applied(record_id=records[1]["id"], tenant_id=TENANT)

        status = await MenuDispatchService.get_dispatch_status(
            version_id=v["id"], tenant_id=TENANT
        )
        assert status["total"] == 4
        assert status["applied"] == 2
        assert status["pending"] == 2
        assert status["apply_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_mark_dispatch_failed(self):
        """标记下发失败"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        records = await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        record_id = records[0]["id"]
        failed = await MenuDispatchService.mark_dispatch_failed(
            record_id=record_id, tenant_id=TENANT, reason="门店网络超时"
        )
        assert failed["status"] == "failed"
        assert failed["fail_reason"] == "门店网络超时"

    @pytest.mark.asyncio
    async def test_get_store_current_version(self):
        """查询门店当前版本"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        records = await MenuVersionService.publish_to_stores(
            version_id=v["id"], store_ids=[STORE_A], tenant_id=TENANT
        )
        await MenuVersionService.confirm_applied(record_id=records[0]["id"], tenant_id=TENANT)

        result = await MenuVersionService.get_store_current_version(
            store_id=STORE_A, tenant_id=TENANT
        )
        assert result is not None
        assert result["version"]["id"] == v["id"]
        assert result["dispatch_record"]["status"] == "applied"

    @pytest.mark.asyncio
    async def test_full_dispatch_service(self):
        """MenuDispatchService.full_dispatch 全量下发"""
        v = await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        result = await MenuDispatchService.full_dispatch(
            version_id=v["id"],
            all_store_ids=ALL_STORES,
            tenant_id=TENANT,
        )
        assert result["store_count"] == len(ALL_STORES)
        assert len(result["records"]) == len(ALL_STORES)


# ═══════════════════════════════════════════
# 7. 租户隔离
# ═══════════════════════════════════════════


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_version_invisible_to_other_tenant(self):
        """不同租户的版本互不可见"""
        other_tenant = str(uuid.uuid4())
        other_brand = str(uuid.uuid4())

        v_mine = await MenuVersionService.create_version(
            brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT
        )
        await MenuVersionService.create_version(
            brand_id=other_brand, tenant_id=other_tenant, dishes_snapshot=SNAPSHOT
        )

        # 用 other_tenant 查不到 v_mine
        result = await MenuVersionService.get_version(v_mine["id"], other_tenant)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_versions_tenant_isolated(self):
        """版本列表按租户隔离"""
        other_tenant = str(uuid.uuid4())
        other_brand = str(uuid.uuid4())

        await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.create_version(brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT)
        await MenuVersionService.create_version(
            brand_id=other_brand, tenant_id=other_tenant, dishes_snapshot=SNAPSHOT
        )

        mine = await MenuVersionService.list_versions(tenant_id=TENANT)
        theirs = await MenuVersionService.list_versions(tenant_id=other_tenant)
        assert mine["total"] == 2
        assert theirs["total"] == 1

    @pytest.mark.asyncio
    async def test_publish_cross_tenant_raises(self):
        """跨租户下发版本抛出异常"""
        other_tenant = str(uuid.uuid4())
        v = await MenuVersionService.create_version(
            brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT
        )
        with pytest.raises(ValueError, match="版本不存在"):
            await MenuVersionService.publish_to_stores(
                version_id=v["id"],
                store_ids=[STORE_A],
                tenant_id=other_tenant,  # 使用不同租户
            )

    @pytest.mark.asyncio
    async def test_dispatch_status_tenant_isolated(self):
        """下发进度按租户隔离"""
        other_tenant = str(uuid.uuid4())
        other_brand = str(uuid.uuid4())

        v_mine = await MenuVersionService.create_version(
            brand_id=BRAND, tenant_id=TENANT, dishes_snapshot=SNAPSHOT
        )
        await MenuVersionService.publish_to_stores(
            version_id=v_mine["id"], store_ids=ALL_STORES[:3], tenant_id=TENANT
        )

        # 其他租户查询同一 version_id，看不到记录
        status = await MenuDispatchService.get_dispatch_status(
            version_id=v_mine["id"], tenant_id=other_tenant
        )
        assert status["total"] == 0

    @pytest.mark.asyncio
    async def test_empty_tenant_raises(self):
        """空 tenant_id 各方法均抛出异常"""
        with pytest.raises(ValueError, match="tenant_id"):
            await MenuVersionService.create_version(brand_id=BRAND, tenant_id="", dishes_snapshot=SNAPSHOT)

        with pytest.raises(ValueError, match="tenant_id"):
            await MenuVersionService.list_versions(tenant_id="")

        with pytest.raises(ValueError, match="tenant_id"):
            await MenuDispatchService.get_dispatch_status(
                version_id=str(uuid.uuid4()), tenant_id=""
            )
