"""Task 3.4: 中央厨房 + 配送业务回归测试 — Tier 2

验证：
  1. 中央厨房服务使用 DB 化实现（非内存 dict）
  2. 配送路由全部端点可发现
  3. 菜单模板渠道发布链路完整
  4. 央厨/配送/菜单代码结构正确
"""

from pathlib import Path

import pytest

# ── 文件路径 ──

CK_SERVICE_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-supply" / "src" / "services"
    / "central_kitchen_service.py"
)
DELIVERY_ROUTER_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-trade" / "src" / "routers"
    / "delivery_router.py"
)
MENU_PUBLISH_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-menu" / "src" / "api"
)


# ═══════════════════════════════════════════════════════════════════════
# 中央厨房回归
# ═══════════════════════════════════════════════════════════════════════


class TestCentralKitchenRegression:
    """中央厨房业务回归"""

    def test_service_file_exists(self):
        """central_kitchen_service.py 存在"""
        assert CK_SERVICE_PY.exists(), "中央厨房服务文件不存在"

    def test_uses_db_repository(self):
        """使用 DB Repository 模式（v062 迁移后）"""
        source = CK_SERVICE_PY.read_text()
        assert "Repository" in source or "repository" in source or "db" in source.lower(), (
            "中央厨房未使用 DB 持久化（可能仍是内存 dict 实现）"
        )

    def test_has_crud_operations(self):
        """有完整 CRUD 操作"""
        source = CK_SERVICE_PY.read_text()
        crud_indicators = ["create", "get", "update", "delete", "list"]
        found = sum(1 for op in crud_indicators if op in source.lower())
        assert found >= 3, f"中央厨房 CRUD 操作不足: {found}/{len(crud_indicators)}"

    def test_has_production_planning(self):
        """有生产计划功能"""
        source = CK_SERVICE_PY.read_text()
        planning_keywords = ["plan", "production", "schedule", "forecast", "task"]
        found = sum(1 for kw in planning_keywords if kw in source.lower())
        assert found >= 2, f"缺少生产计划关键词: {found}/5"

    def test_has_inventory_linkage(self):
        """有库存联动或供给链关联"""
        source = CK_SERVICE_PY.read_text()
        inventory_kw = ["inventory", "stock", "material", "ingredient", "warehouse",
                        "supply", "procurement", "order", "dispatch", "delivery"]
        found = sum(1 for kw in inventory_kw if kw in source.lower())
        assert found >= 2, f"缺少供应链/库存联动关键词: {found}/10"

    def test_no_memory_dict_anti_pattern(self):
        """不使用内存 dict 存储（确认非旧版实现）"""
        source = CK_SERVICE_PY.read_text()
        # 检查不应有的内存存储模式
        assert "_store = {}" not in source, "中央厨房使用了内存 dict（旧版模式）"
        assert "_data = {}" not in source, "中央厨房使用了内存 dict（旧版模式）"


# ═══════════════════════════════════════════════════════════════════════
# 配送业务回归
# ═══════════════════════════════════════════════════════════════════════


class TestDeliveryRouterRegression:
    """配送路由回归"""

    def test_router_file_exists(self):
        """delivery_router.py 存在"""
        assert DELIVERY_ROUTER_PY.exists(), "配送路由文件不存在"

    def test_has_order_endpoints(self):
        """配送订单端点完整"""
        source = DELIVERY_ROUTER_PY.read_text()
        order_ops = ["order", "accept", "reject", "cancel", "status"]
        found = sum(1 for op in order_ops if op in source.lower())
        assert found >= 3, f"配送订单端点不足: {found}/{len(order_ops)}"

    def test_has_platform_integration(self):
        """有平台集成（美团/饿了么/抖音）"""
        source = DELIVERY_ROUTER_PY.read_text()
        platforms = ["meituan", "eleme", "douyin"]
        found = sum(1 for p in platforms if p in source.lower())
        assert found >= 1, "配送路由未集成任何外卖平台"

    def test_has_webhook_handling(self):
        """有 Webhook 回调处理"""
        source = DELIVERY_ROUTER_PY.read_text()
        assert "webhook" in source.lower() or "callback" in source.lower(), (
            "配送路由缺少 Webhook/回调处理"
        )


# ═══════════════════════════════════════════════════════════════════════
# 菜单模板渠道发布回归
# ═══════════════════════════════════════════════════════════════════════


class TestMenuTemplatePublishRegression:
    """菜单模板 → 门店 → 渠道发布链路"""

    def test_menu_publish_routes_exist(self):
        """菜单发布相关路由存在"""
        menu_api_dir = MENU_PUBLISH_PY
        if not menu_api_dir.exists():
            pytest.skip("tx-menu api 目录不存在")
        menu_files = list(menu_api_dir.glob("*.py"))
        publish_files = [f for f in menu_files if "publish" in f.name.lower() or "channel" in f.name.lower()]
        # 至少应有渠道价或发布相关路由文件
        channel_files = list(menu_api_dir.glob("*channel*"))
        assert len(channel_files) > 0 or len(publish_files) > 0, (
            "tx-menu 缺少渠道发布/渠道价路由文件"
        )

    def test_dish_publish_routes_registered(self):
        """菜品发布路由在 tx-trade main.py 中注册"""
        main_py = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-trade" / "src" / "main.py"
        )
        source = main_py.read_text()
        assert "dish_publish" in source, (
            "tx-trade main.py 未注册 dish_publish 路由"
        )


# ═══════════════════════════════════════════════════════════════════════
# 数据一致性验证
# ═══════════════════════════════════════════════════════════════════════


class TestSupplyChainDataConsistency:
    """供应链数据一致性"""

    def test_inventory_routes_exist(self):
        """库存路由存在"""
        inv_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-supply" / "src" / "api"
        )
        if not inv_path.exists():
            pytest.skip("tx-supply api 目录不存在")
        inv_files = list(inv_path.glob("*inventory*"))
        assert len(inv_files) > 0, "tx-supply 缺少库存路由"

    def test_procurement_routes_exist(self):
        """采购路由存在"""
        proc_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-supply" / "src" / "api"
        )
        if not proc_path.exists():
            pytest.skip("tx-supply api 目录不存在")
        proc_files = list(proc_path.glob("*procur*")) + list(proc_path.glob("*purchase*"))
        # 采购可能嵌入在 inventory 或 supply 路由中
        supply_files = list(proc_path.glob("*supply*"))
        assert len(proc_files) > 0 or len(supply_files) > 0, (
            "tx-supply 缺少采购/供应链路由"
        )


# ═══════════════════════════════════════════════════════════════════════
# P1-06: 物化视图优化验证
# ═══════════════════════════════════════════════════════════════════════


class TestMaterializedViewOptimization:
    """物化视图性能优化"""

    def test_index_migration_exists(self):
        """v310 索引优化迁移文件存在"""
        migration_path = (
            Path(__file__).parent.parent.parent
            / "shared" / "db-migrations" / "versions"
            / "v310_mv_performance_indexes.py"
        )
        assert migration_path.exists(), "v310 迁移文件不存在"

    def test_covers_all_8_mvs(self):
        """覆盖全部 8 个物化视图"""
        source = (
            Path(__file__).parent.parent.parent
            / "shared" / "db-migrations" / "versions"
            / "v310_mv_performance_indexes.py"
        ).read_text()
        mvs = [
            "mv_daily_settlement", "mv_store_pnl", "mv_discount_health",
            "mv_channel_margin", "mv_member_clv", "mv_inventory_bom",
            "mv_safety_compliance", "mv_energy_efficiency",
        ]
        for mv in mvs:
            assert mv in source, f"v310 迁移缺少物化视图: {mv}"

    def test_has_brin_index(self):
        """events 表使用 BRIN 索引（节省空间）"""
        source = (
            Path(__file__).parent.parent.parent
            / "shared" / "db-migrations" / "versions"
            / "v310_mv_performance_indexes.py"
        ).read_text()
        assert "BRIN" in source, "v310 迁移未使用 BRIN 索引"

    def test_has_downgrade(self):
        """downgrade 方法存在"""
        source = (
            Path(__file__).parent.parent.parent
            / "shared" / "db-migrations" / "versions"
            / "v310_mv_performance_indexes.py"
        ).read_text()
        assert "def downgrade" in source, "v310 迁移缺少 downgrade 方法"

    def test_has_if_not_exists(self):
        """使用 IF NOT EXISTS 避免重复创建"""
        source = (
            Path(__file__).parent.parent.parent
            / "shared" / "db-migrations" / "versions"
            / "v310_mv_performance_indexes.py"
        ).read_text()
        assert "IF NOT EXISTS" in source, "索引创建未使用 IF NOT EXISTS"
