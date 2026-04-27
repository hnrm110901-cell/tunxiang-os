"""Tests for Forge Marketplace Service (U3.3)

覆盖：
- 开发者注册与管理
- 应用提交和审核工作流
- 安装和卸载
- API Key 管理
- 沙箱生命周期
- 收入计算（平台30%抽成）
- 搜索与过滤
- 市场分析
"""

import pytest
from forge_marketplace import (
    APP_CATEGORIES,
    PRICING_MODELS,
    ForgeMarketplaceService,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture
def svc() -> ForgeMarketplaceService:
    """带预置数据的服务实例"""
    return ForgeMarketplaceService(seed_data=True)


@pytest.fixture
def empty_svc() -> ForgeMarketplaceService:
    """空的服务实例（不带预置数据）"""
    return ForgeMarketplaceService(seed_data=False)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. Developer Registration & Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDeveloperManagement:
    def test_register_developer_individual(self, empty_svc: ForgeMarketplaceService) -> None:
        result = empty_svc.register_developer(
            name="张三",
            email="zhangsan@example.com",
            company="个人",
            dev_type="individual",
            description="独立餐饮SaaS开发者",
        )
        assert result["developer_id"].startswith("dev_")
        assert result["api_key"].startswith("txforge_")
        assert "sandbox_url" in result
        assert result["status"] == "active"

    def test_register_developer_company(self, empty_svc: ForgeMarketplaceService) -> None:
        result = empty_svc.register_developer(
            name="餐饮科技有限公司",
            email="dev@canyin.com",
            company="深圳餐饮科技有限公司",
            dev_type="company",
        )
        assert result["developer_id"].startswith("dev_")
        assert result["status"] == "active"

    def test_register_developer_isv(self, empty_svc: ForgeMarketplaceService) -> None:
        result = empty_svc.register_developer(
            name="云帐房ISV",
            email="isv@yunzhangfang.com",
            company="云帐房科技",
            dev_type="isv",
        )
        assert result["developer_id"].startswith("dev_")

    def test_register_developer_invalid_type(self, empty_svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="无效开发者类型"):
            empty_svc.register_developer(
                name="test",
                email="t@t.com",
                company="t",
                dev_type="invalid_type",
            )

    def test_get_developer_profile(self, svc: ForgeMarketplaceService) -> None:
        profile = svc.get_developer_profile("dev_meituan")
        assert profile["name"] == "美团外卖开放平台"
        assert profile["app_count"] >= 1
        assert profile["total_installs"] > 0

    def test_get_developer_profile_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.get_developer_profile("dev_nonexistent")

    def test_update_developer(self, svc: ForgeMarketplaceService) -> None:
        updated = svc.update_developer("dev_meituan", {"description": "更新后的描述"})
        assert updated["description"] == "更新后的描述"
        assert "updated_at" in updated

    def test_update_developer_ignores_forbidden_fields(self, svc: ForgeMarketplaceService) -> None:
        before = svc.get_developer_profile("dev_meituan")
        svc.update_developer("dev_meituan", {"developer_id": "hacked", "status": "hacked"})
        after = svc.get_developer_profile("dev_meituan")
        assert after["developer_id"] == before["developer_id"]
        assert after["status"] == before["status"]

    def test_list_developers(self, svc: ForgeMarketplaceService) -> None:
        all_devs = svc.list_developers()
        assert len(all_devs) >= 7  # 7 seed developers

    def test_list_developers_filter_status(self, svc: ForgeMarketplaceService) -> None:
        verified = svc.list_developers(status="verified")
        assert len(verified) >= 7
        for d in verified:
            assert d["status"] == "verified"

        active = svc.list_developers(status="active")
        assert len(active) == 0  # seed data uses "verified"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. App Submission & Review Workflow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAppLifecycle:
    def test_submit_app(self, svc: ForgeMarketplaceService) -> None:
        result = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="AR菜单",
            category="ai_addon",
            description="用AR技术展示菜品3D效果，提升点餐体验",
            version="1.0.0",
            icon_url="/icons/ar-menu.png",
            screenshots=["/screenshots/ar-1.png"],
            pricing_model="monthly",
            price_fen=19900,
            permissions=["menu.read", "ar.render"],
        )
        assert result["app_id"].startswith("app_")
        assert result["status"] == "pending_review"

    def test_submit_app_invalid_developer(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.submit_app(
                developer_id="dev_fake",
                app_name="test",
                category="ai_addon",
                description="test",
                version="1.0.0",
            )

    def test_submit_app_invalid_category(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="无效分类"):
            svc.submit_app(
                developer_id="dev_txlabs",
                app_name="test",
                category="nonexistent_category",
                description="test",
                version="1.0.0",
            )

    def test_submit_app_invalid_pricing(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="无效定价模式"):
            svc.submit_app(
                developer_id="dev_txlabs",
                app_name="test",
                category="ai_addon",
                description="test",
                version="1.0.0",
                pricing_model="super_premium",
            )

    def test_review_approve(self, svc: ForgeMarketplaceService) -> None:
        sub = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="测试应用",
            category="analytics",
            description="数据分析测试应用",
            version="0.1.0",
        )
        app_id = sub["app_id"]

        review = svc.review_app(app_id, "reviewer_001", "approved", "符合上架标准")
        assert review["decision"] == "approved"
        assert review["new_status"] == "published"

        detail = svc.get_app_detail(app_id)
        assert detail["status"] == "published"
        assert detail["published_at"] is not None

    def test_review_reject(self, svc: ForgeMarketplaceService) -> None:
        sub = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="违规应用",
            category="analytics",
            description="不符合规范",
            version="0.1.0",
        )
        app_id = sub["app_id"]

        review = svc.review_app(app_id, "reviewer_001", "rejected", "描述不清晰，功能不完整")
        assert review["decision"] == "rejected"
        assert review["new_status"] == "rejected"

    def test_review_needs_changes(self, svc: ForgeMarketplaceService) -> None:
        sub = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="待修改应用",
            category="analytics",
            description="需要补充截图",
            version="0.1.0",
        )
        app_id = sub["app_id"]

        review = svc.review_app(app_id, "reviewer_001", "needs_changes", "请补充截图和详细文档")
        assert review["new_status"] == "needs_changes"

    def test_review_invalid_decision(self, svc: ForgeMarketplaceService) -> None:
        sub = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="test",
            category="ai_addon",
            description="test",
            version="1.0.0",
        )
        with pytest.raises(ValueError, match="无效审核结果"):
            svc.review_app(sub["app_id"], "reviewer_001", "maybe")

    def test_get_pending_reviews(self, svc: ForgeMarketplaceService) -> None:
        svc.submit_app(
            developer_id="dev_txlabs",
            app_name="待审核1",
            category="ai_addon",
            description="desc1",
            version="1.0.0",
        )
        svc.submit_app(
            developer_id="dev_kingdee",
            app_name="待审核2",
            category="finance",
            description="desc2",
            version="1.0.0",
        )
        pending = svc.get_pending_reviews()
        assert len(pending) >= 2
        names = [p["app_name"] for p in pending]
        assert "待审核1" in names
        assert "待审核2" in names

    def test_get_review_history(self, svc: ForgeMarketplaceService) -> None:
        sub = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="多次审核",
            category="ai_addon",
            description="经历多次审核",
            version="1.0.0",
        )
        app_id = sub["app_id"]

        svc.review_app(app_id, "reviewer_001", "needs_changes", "请修改描述")
        svc.review_app(app_id, "reviewer_001", "approved", "修改后符合标准")

        history = svc.get_review_history(app_id)
        assert len(history) == 2
        # 倒序：最新在前
        assert history[0]["decision"] == "approved"
        assert history[1]["decision"] == "needs_changes"

    def test_update_app(self, svc: ForgeMarketplaceService) -> None:
        updated = svc.update_app("app_meituan_delivery", {"description": "新描述"})
        assert updated["description"] == "新描述"

    def test_update_app_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="应用不存在"):
            svc.update_app("app_nonexistent", {"description": "x"})

    def test_get_app_detail_enriched(self, svc: ForgeMarketplaceService) -> None:
        detail = svc.get_app_detail("app_meituan_delivery")
        assert detail["app_name"] == "美团外卖聚合"
        assert detail["developer_name"] == "美团外卖开放平台"
        assert detail["category_name"] == "外卖聚合"
        assert detail["pricing_model_name"] == "月订阅"
        assert detail["platform_fee_rate"] == 0.30

    def test_get_app_detail_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="应用不存在"):
            svc.get_app_detail("app_nope")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. Listing, Search, Filtering
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSearchAndFilter:
    def test_list_apps_all(self, svc: ForgeMarketplaceService) -> None:
        apps = svc.list_apps()
        assert len(apps) >= 7

    def test_list_apps_by_category(self, svc: ForgeMarketplaceService) -> None:
        delivery = svc.list_apps(category="delivery")
        assert len(delivery) >= 1
        for a in delivery:
            assert a["category"] == "delivery"

    def test_list_apps_by_status(self, svc: ForgeMarketplaceService) -> None:
        published = svc.list_apps(status="published")
        for a in published:
            assert a["status"] == "published"

    def test_list_apps_sort_by_popularity(self, svc: ForgeMarketplaceService) -> None:
        apps = svc.list_apps(sort_by="popularity")
        for i in range(len(apps) - 1):
            assert apps[i].get("install_count", 0) >= apps[i + 1].get("install_count", 0)

    def test_list_apps_sort_by_rating(self, svc: ForgeMarketplaceService) -> None:
        apps = svc.list_apps(sort_by="rating")
        for i in range(len(apps) - 1):
            assert apps[i].get("rating", 0) >= apps[i + 1].get("rating", 0)

    def test_list_apps_sort_by_price(self, svc: ForgeMarketplaceService) -> None:
        apps = svc.list_apps(sort_by="price")
        for i in range(len(apps) - 1):
            assert apps[i].get("price_fen", 0) <= apps[i + 1].get("price_fen", 0)

    def test_search_apps_by_name(self, svc: ForgeMarketplaceService) -> None:
        results = svc.search_apps("美团")
        assert len(results) >= 1
        assert any("美团" in a["app_name"] for a in results)

    def test_search_apps_by_description(self, svc: ForgeMarketplaceService) -> None:
        results = svc.search_apps("语音")
        assert len(results) >= 1

    def test_search_apps_by_category_name(self, svc: ForgeMarketplaceService) -> None:
        results = svc.search_apps("财务")
        assert len(results) >= 1

    def test_search_apps_empty_query_returns_published(self, svc: ForgeMarketplaceService) -> None:
        results = svc.search_apps("")
        assert len(results) >= 7

    def test_search_apps_no_match(self, svc: ForgeMarketplaceService) -> None:
        results = svc.search_apps("量子计算区块链元宇宙")
        assert len(results) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. Installation & Uninstallation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestInstallation:
    def test_install_app(self, svc: ForgeMarketplaceService) -> None:
        result = svc.install_app("tenant_001", "app_food_safety")
        assert result["install_id"].startswith("inst_")
        assert result["status"] == "active"
        assert result["tenant_id"] == "tenant_001"
        assert result["app_id"] == "app_food_safety"

    def test_install_app_with_specific_stores(self, svc: ForgeMarketplaceService) -> None:
        result = svc.install_app("tenant_002", "app_meituan_delivery", store_ids=["store_A", "store_B"])
        assert result["store_ids"] == ["store_A", "store_B"]

    def test_install_app_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="应用不存在"):
            svc.install_app("tenant_001", "app_fake")

    def test_install_unpublished_app(self, svc: ForgeMarketplaceService) -> None:
        sub = svc.submit_app(
            developer_id="dev_txlabs",
            app_name="未发布",
            category="ai_addon",
            description="desc",
            version="1.0.0",
        )
        with pytest.raises(ValueError, match="应用未发布"):
            svc.install_app("tenant_001", sub["app_id"])

    def test_install_app_duplicate(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_003", "app_food_safety")
        with pytest.raises(ValueError, match="应用已安装"):
            svc.install_app("tenant_003", "app_food_safety")

    def test_install_increments_count(self, svc: ForgeMarketplaceService) -> None:
        before = svc.get_app_detail("app_food_safety")["install_count"]
        svc.install_app("tenant_inc_test", "app_food_safety")
        after = svc.get_app_detail("app_food_safety")["install_count"]
        assert after == before + 1

    def test_uninstall_app(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_004", "app_voice_ordering")
        result = svc.uninstall_app("tenant_004", "app_voice_ordering")
        assert result["status"] == "uninstalled"

    def test_uninstall_app_not_installed(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="应用未安装"):
            svc.uninstall_app("tenant_999", "app_food_safety")

    def test_uninstall_decrements_count(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_dec_test", "app_food_safety")
        before = svc.get_app_detail("app_food_safety")["install_count"]
        svc.uninstall_app("tenant_dec_test", "app_food_safety")
        after = svc.get_app_detail("app_food_safety")["install_count"]
        assert after == before - 1

    def test_list_installed_apps(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_005", "app_food_safety")
        svc.install_app("tenant_005", "app_voice_ordering")
        installed = svc.list_installed_apps("tenant_005")
        assert len(installed) == 2
        names = {a["app_name"] for a in installed}
        assert "食安巡检助手" in names
        assert "智能语音点餐" in names

    def test_list_installed_apps_excludes_uninstalled(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_006", "app_food_safety")
        svc.install_app("tenant_006", "app_voice_ordering")
        svc.uninstall_app("tenant_006", "app_food_safety")
        installed = svc.list_installed_apps("tenant_006")
        assert len(installed) == 1
        assert installed[0]["app_name"] == "智能语音点餐"

    def test_get_installation_status_installed(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_007", "app_food_safety")
        status = svc.get_installation_status("tenant_007", "app_food_safety")
        assert status["installed"] is True
        assert status["status"] == "active"

    def test_get_installation_status_not_installed(self, svc: ForgeMarketplaceService) -> None:
        status = svc.get_installation_status("tenant_007", "app_meituan_delivery")
        assert status["installed"] is False
        assert status["status"] == "not_installed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. API Key Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAPIKeyManagement:
    def test_generate_api_key(self, svc: ForgeMarketplaceService) -> None:
        result = svc.generate_api_key(
            developer_id="dev_txlabs",
            key_name="生产密钥",
            permissions=["read", "write", "admin"],
        )
        assert result["key_id"].startswith("key_")
        assert result["api_key"].startswith("txforge_")
        assert result["permissions"] == ["read", "write", "admin"]

    def test_generate_api_key_developer_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.generate_api_key("dev_fake", "test", ["read"])

    def test_revoke_api_key(self, svc: ForgeMarketplaceService) -> None:
        key = svc.generate_api_key("dev_txlabs", "临时密钥", ["read"])
        result = svc.revoke_api_key(key["key_id"])
        assert result["status"] == "revoked"

    def test_revoke_api_key_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="密钥不存在"):
            svc.revoke_api_key("key_nonexistent")

    def test_list_api_keys(self, svc: ForgeMarketplaceService) -> None:
        svc.generate_api_key("dev_txlabs", "密钥A", ["read"])
        svc.generate_api_key("dev_txlabs", "密钥B", ["read", "write"])
        keys = svc.list_api_keys("dev_txlabs")
        assert len(keys) >= 2
        # 验证密钥被遮蔽
        for k in keys:
            assert "api_key_prefix" in k
            assert k["api_key_prefix"].endswith("...")

    def test_list_api_keys_developer_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.list_api_keys("dev_ghost")

    def test_get_api_usage(self, svc: ForgeMarketplaceService) -> None:
        usage = svc.get_api_usage("dev_txlabs")
        assert "total_calls" in usage
        assert "quota" in usage
        assert usage["quota"] == 100000  # company type

    def test_get_api_usage_individual_quota(self, empty_svc: ForgeMarketplaceService) -> None:
        reg = empty_svc.register_developer("个人开发者", "ind@test.com", "个人", "individual")
        dev_id = reg["developer_id"]
        usage = empty_svc.get_api_usage(dev_id)
        assert usage["quota"] == 10000  # individual


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. Sandbox Lifecycle
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSandbox:
    def test_create_sandbox(self, svc: ForgeMarketplaceService) -> None:
        result = svc.create_sandbox("dev_meituan", "app_meituan_delivery")
        assert result["sandbox_id"].startswith("sandbox_")
        assert result["test_tenant_id"].startswith("test_tenant_")
        assert result["test_api_key"].startswith("txforge_")
        assert "expires_at" in result
        assert result["test_data"]["menu_items"] == 56

    def test_create_sandbox_wrong_developer(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="只能为自己的应用创建沙箱"):
            svc.create_sandbox("dev_kingdee", "app_meituan_delivery")

    def test_create_sandbox_developer_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.create_sandbox("dev_fake", "app_meituan_delivery")

    def test_create_sandbox_app_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="应用不存在"):
            svc.create_sandbox("dev_meituan", "app_fake")

    def test_get_sandbox_status(self, svc: ForgeMarketplaceService) -> None:
        created = svc.create_sandbox("dev_meituan", "app_meituan_delivery")
        status = svc.get_sandbox_status(created["sandbox_id"])
        assert status["status"] == "running"
        assert "sandbox_url" in status

    def test_get_sandbox_status_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="沙箱不存在"):
            svc.get_sandbox_status("sandbox_fake")

    def test_delete_sandbox(self, svc: ForgeMarketplaceService) -> None:
        created = svc.create_sandbox("dev_meituan", "app_meituan_delivery")
        result = svc.delete_sandbox(created["sandbox_id"])
        assert result["status"] == "deleted"

        # 验证状态已更新
        status = svc.get_sandbox_status(created["sandbox_id"])
        assert status["status"] == "deleted"

    def test_delete_sandbox_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="沙箱不存在"):
            svc.delete_sandbox("sandbox_nope")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. Revenue & Settlement (30% Platform Fee)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRevenue:
    def test_install_paid_app_records_revenue(self, svc: ForgeMarketplaceService) -> None:
        """安装付费应用时应记录收入"""
        svc.install_app("tenant_rev_001", "app_meituan_delivery")
        revenue = svc.get_app_revenue("app_meituan_delivery")
        assert revenue["transaction_count"] >= 1
        assert revenue["total_revenue_fen"] > 0

    def test_install_free_app_no_revenue(self, svc: ForgeMarketplaceService) -> None:
        """安装免费应用不应产生收入"""
        svc.install_app("tenant_rev_002", "app_food_safety")
        revenue = svc.get_app_revenue("app_food_safety")
        assert revenue["transaction_count"] == 0

    def test_platform_fee_30_percent(self, svc: ForgeMarketplaceService) -> None:
        """平台抽成30%验证"""
        svc.install_app("tenant_rev_003", "app_kingdee_voucher")
        revenue = svc.get_app_revenue("app_kingdee_voucher")

        # 金蝶月订阅 19900分 = 199元, 平台抽成30% = 5970分
        entries = svc._app_revenue_log.get("app_kingdee_voucher", [])
        latest = [e for e in entries if e["tenant_id"] == "tenant_rev_003"]
        assert len(latest) == 1

        entry = latest[0]
        assert entry["amount_fen"] == 19900
        assert entry["platform_fee_fen"] == int(19900 * 0.30)  # 5970
        assert entry["developer_payout_fen"] == 19900 - int(19900 * 0.30)  # 13930
        assert entry["fee_rate"] == 0.30

    def test_usage_based_fee_20_percent(self, svc: ForgeMarketplaceService) -> None:
        """按用量定价平台抽成20%验证"""
        svc.install_app("tenant_rev_004", "app_voice_ordering")
        entries = svc._app_revenue_log.get("app_voice_ordering", [])
        latest = [e for e in entries if e["tenant_id"] == "tenant_rev_004"]
        assert len(latest) == 1
        entry = latest[0]
        assert entry["fee_rate"] == 0.20  # usage_based: 20%
        assert entry["platform_fee_fen"] == int(10 * 0.20)  # 2 fen

    def test_get_developer_revenue(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_rev_005", "app_meituan_delivery")
        revenue = svc.get_developer_revenue("dev_meituan")
        assert revenue["total_revenue_fen"] > 0
        assert revenue["platform_fee_fen"] > 0
        assert revenue["developer_payout_fen"] > 0
        assert revenue["platform_fee_rate"] == 0.30
        assert len(revenue["app_breakdown"]) >= 1

    def test_get_developer_revenue_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.get_developer_revenue("dev_fake")

    def test_get_app_revenue(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_rev_006", "app_douyin_marketing")
        revenue = svc.get_app_revenue("app_douyin_marketing")
        assert revenue["app_name"] == "抖音营销"
        assert revenue["pricing_model"] == "monthly"
        assert revenue["platform_fee_rate"] == 0.30
        assert revenue["total_revenue_fen"] > 0

    def test_get_app_revenue_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="应用不存在"):
            svc.get_app_revenue("app_ghost")

    def test_request_payout(self, svc: ForgeMarketplaceService) -> None:
        # 先产生收入
        svc.install_app("tenant_pay_001", "app_meituan_delivery")
        revenue = svc.get_developer_revenue("dev_meituan")
        payout_amount = revenue["developer_payout_fen"]

        result = svc.request_payout("dev_meituan", payout_amount, "招商银行 6214 **** **** 1234")
        assert result["payout_id"].startswith("payout_")
        assert result["amount_fen"] == payout_amount
        assert result["status"] == "pending"

    def test_request_payout_insufficient_balance(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="余额不足"):
            svc.request_payout("dev_safecheck", 100000000, "bank_account")

    def test_request_payout_negative_amount(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="提现金额必须大于0"):
            svc.request_payout("dev_meituan", -100, "bank_account")

    def test_request_payout_developer_not_found(self, svc: ForgeMarketplaceService) -> None:
        with pytest.raises(ValueError, match="开发者不存在"):
            svc.request_payout("dev_fake", 100, "bank")

    def test_get_payout_history(self, svc: ForgeMarketplaceService) -> None:
        svc.install_app("tenant_pay_002", "app_meituan_delivery")
        revenue = svc.get_developer_revenue("dev_meituan")
        amount = min(revenue["developer_payout_fen"], 1000)
        if amount > 0:
            svc.request_payout("dev_meituan", amount, "工商银行 6222 **** 5678")

        history = svc.get_payout_history("dev_meituan")
        assert isinstance(history, list)
        if amount > 0:
            assert len(history) >= 1

    def test_double_payout_exceeds_balance(self, svc: ForgeMarketplaceService) -> None:
        """不能重复提现超过余额"""
        svc.install_app("tenant_pay_003", "app_meituan_delivery")
        revenue = svc.get_developer_revenue("dev_meituan")
        total = revenue["developer_payout_fen"]

        if total > 0:
            svc.request_payout("dev_meituan", total, "bank_1")
            with pytest.raises(ValueError, match="余额不足"):
                svc.request_payout("dev_meituan", 1, "bank_1")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. Marketplace Analytics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMarketplaceAnalytics:
    def test_get_marketplace_stats(self, svc: ForgeMarketplaceService) -> None:
        stats = svc.get_marketplace_stats()
        assert stats["total_apps"] >= 7
        assert stats["published_apps"] >= 7
        assert stats["total_developers"] >= 7
        assert stats["total_installs"] > 0
        assert stats["total_revenue_fen"] > 0
        assert "category_distribution" in stats
        assert stats["avg_rating"] > 0

    def test_get_trending_apps(self, svc: ForgeMarketplaceService) -> None:
        trending = svc.get_trending_apps(period="week", limit=5)
        assert len(trending) == 5
        assert trending[0]["rank"] == 1
        # 应该按综合分排序
        for i in range(len(trending) - 1):
            assert trending[i]["trend_score"] >= trending[i + 1]["trend_score"]

    def test_get_trending_apps_limit(self, svc: ForgeMarketplaceService) -> None:
        trending = svc.get_trending_apps(limit=3)
        assert len(trending) == 3

    def test_get_trending_apps_has_required_fields(self, svc: ForgeMarketplaceService) -> None:
        trending = svc.get_trending_apps(limit=1)
        app = trending[0]
        required_fields = {
            "rank",
            "app_id",
            "app_name",
            "developer_name",
            "category",
            "category_name",
            "rating",
            "install_count",
            "price_display",
            "trend_score",
        }
        assert required_fields.issubset(set(app.keys()))

    def test_get_category_stats(self, svc: ForgeMarketplaceService) -> None:
        stats = svc.get_category_stats()
        assert len(stats) == len(APP_CATEGORIES)

        # 验证有数据的分类
        cats_with_apps = [s for s in stats if s["app_count"] > 0]
        assert len(cats_with_apps) >= 5  # 至少5个分类有应用

        for s in stats:
            assert "category" in s
            assert "category_name" in s
            assert "app_count" in s
            assert "total_installs" in s
            assert "avg_rating" in s

    def test_get_category_stats_sorted_by_app_count(self, svc: ForgeMarketplaceService) -> None:
        stats = svc.get_category_stats()
        for i in range(len(stats) - 1):
            assert stats[i]["app_count"] >= stats[i + 1]["app_count"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. Full Workflow Integration Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestIntegration:
    def test_full_developer_to_payout_workflow(self, empty_svc: ForgeMarketplaceService) -> None:
        """完整工作流：注册 → 提交应用 → 审核 → 发布 → 安装 → 收入 → 提现"""
        svc = empty_svc

        # 1. 注册开发者
        reg = svc.register_developer(
            name="湘菜智能",
            email="dev@xiangcai-ai.com",
            company="长沙湘菜智能科技有限公司",
            dev_type="company",
            description="专注湘菜餐饮数字化",
        )
        dev_id = reg["developer_id"]

        # 2. 提交应用
        sub = svc.submit_app(
            developer_id=dev_id,
            app_name="湘菜智能配料",
            category="ai_addon",
            description="湘菜标准化配料系统，AI分析菜品口味，自动推荐配料方案",
            version="1.0.0",
            pricing_model="monthly",
            price_fen=29900,
            permissions=["menu.read", "recipe.read", "recipe.write"],
        )
        app_id = sub["app_id"]
        assert sub["status"] == "pending_review"

        # 3. 审核通过
        review = svc.review_app(app_id, "admin_001", "approved", "湘菜特色应用，批准上架")
        assert review["new_status"] == "published"

        # 4. 租户安装
        install = svc.install_app("tenant_xiangcai_001", app_id)
        assert install["status"] == "active"

        # 5. 验证收入
        revenue = svc.get_developer_revenue(dev_id)
        assert revenue["total_revenue_fen"] == 29900
        assert revenue["platform_fee_fen"] == int(29900 * 0.30)  # 8970
        assert revenue["developer_payout_fen"] == 29900 - int(29900 * 0.30)  # 20930

        # 6. 提现
        payout = svc.request_payout(dev_id, revenue["developer_payout_fen"], "长沙银行 1234")
        assert payout["status"] == "pending"
        assert payout["amount_fen"] == 20930

        # 7. 验证提现历史
        history = svc.get_payout_history(dev_id)
        assert len(history) == 1

    def test_app_rejected_then_resubmit_and_approve(self, empty_svc: ForgeMarketplaceService) -> None:
        """被拒后重新提交审核通过"""
        svc = empty_svc

        reg = svc.register_developer("测试开发者", "t@t.com", "测试公司", "individual")
        dev_id = reg["developer_id"]

        sub = svc.submit_app(
            developer_id=dev_id,
            app_name="待完善应用",
            category="analytics",
            description="初版描述",
            version="0.1.0",
        )
        app_id = sub["app_id"]

        # 第一次审核：需要修改
        svc.review_app(app_id, "admin_001", "needs_changes", "请补充截图")

        # 开发者更新应用
        svc.update_app(
            app_id,
            {
                "description": "完善后的描述，补充了截图",
                "screenshots": ["/s1.png", "/s2.png"],
                "version": "0.2.0",
            },
        )

        # 第二次审核：通过
        review = svc.review_app(app_id, "admin_001", "approved", "OK")
        assert review["new_status"] == "published"

        # 审核历史有2条记录
        history = svc.get_review_history(app_id)
        assert len(history) == 2

    def test_sandbox_lifecycle(self, empty_svc: ForgeMarketplaceService) -> None:
        """沙箱完整生命周期"""
        svc = empty_svc

        reg = svc.register_developer("沙箱测试", "sb@t.com", "沙箱公司", "company")
        dev_id = reg["developer_id"]

        sub = svc.submit_app(
            developer_id=dev_id,
            app_name="沙箱测试应用",
            category="iot",
            description="IoT沙箱测试",
            version="1.0.0",
        )
        app_id = sub["app_id"]

        # 创建沙箱
        sandbox = svc.create_sandbox(dev_id, app_id)
        sandbox_id = sandbox["sandbox_id"]

        # 检查状态
        status = svc.get_sandbox_status(sandbox_id)
        assert status["status"] == "running"

        # 删除沙箱
        deleted = svc.delete_sandbox(sandbox_id)
        assert deleted["status"] == "deleted"

        # 确认已删除
        status = svc.get_sandbox_status(sandbox_id)
        assert status["status"] == "deleted"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. Seed Data Validation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSeedData:
    def test_seed_developers_count(self, svc: ForgeMarketplaceService) -> None:
        assert len(svc._developers) == 7

    def test_seed_apps_count(self, svc: ForgeMarketplaceService) -> None:
        assert len(svc._apps) == 7

    def test_seed_apps_all_published(self, svc: ForgeMarketplaceService) -> None:
        for app in svc._apps.values():
            assert app["status"] == "published"

    def test_seed_apps_have_valid_categories(self, svc: ForgeMarketplaceService) -> None:
        for app in svc._apps.values():
            assert app["category"] in APP_CATEGORIES

    def test_seed_apps_have_valid_pricing(self, svc: ForgeMarketplaceService) -> None:
        for app in svc._apps.values():
            assert app["pricing_model"] in PRICING_MODELS

    def test_seed_apps_developers_exist(self, svc: ForgeMarketplaceService) -> None:
        for app in svc._apps.values():
            assert app["developer_id"] in svc._developers

    def test_seed_food_safety_is_free(self, svc: ForgeMarketplaceService) -> None:
        app = svc.get_app_detail("app_food_safety")
        assert app["pricing_model"] == "free"
        assert app["price_fen"] == 0

    def test_seed_voice_ordering_is_usage_based(self, svc: ForgeMarketplaceService) -> None:
        app = svc.get_app_detail("app_voice_ordering")
        assert app["pricing_model"] == "usage_based"
        assert app["price_fen"] == 10  # 0.1元/次

    def test_seed_supplier_direct_is_freemium(self, svc: ForgeMarketplaceService) -> None:
        app = svc.get_app_detail("app_supplier_direct")
        assert app["pricing_model"] == "freemium"

    def test_pricing_models_complete(self) -> None:
        assert "free" in PRICING_MODELS
        assert "one_time" in PRICING_MODELS
        assert "monthly" in PRICING_MODELS
        assert "per_store" in PRICING_MODELS
        assert "usage_based" in PRICING_MODELS
        assert "freemium" in PRICING_MODELS
        assert PRICING_MODELS["free"]["platform_fee_rate"] == 0.0
        assert PRICING_MODELS["monthly"]["platform_fee_rate"] == 0.30
        assert PRICING_MODELS["usage_based"]["platform_fee_rate"] == 0.20

    def test_app_categories_complete(self) -> None:
        expected_keys = {
            "supply_chain",
            "delivery",
            "finance",
            "ai_addon",
            "iot",
            "analytics",
            "marketing",
            "hr",
            "payment",
            "compliance",
        }
        assert set(APP_CATEGORIES.keys()) == expected_keys
        for cat in APP_CATEGORIES.values():
            assert "name" in cat
            assert "icon" in cat
            assert "description" in cat

    def test_no_seed_data_mode(self, empty_svc: ForgeMarketplaceService) -> None:
        assert len(empty_svc._developers) == 0
        assert len(empty_svc._apps) == 0
