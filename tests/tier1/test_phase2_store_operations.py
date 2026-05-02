"""Phase 2: 门店模板 + 监控 + 储值结算 — Tier 1 测试

验证：
  1. 门店模板路由文件存在且结构完整
  2. 门店健康监控路由存在
  3. tx-org main.py 注册了两个新路由
  4. 模板 CRUD 方法签名正确
  5. 监控维度完整
"""

import ast
from pathlib import Path

import pytest

# ── 文件路径 ──

TEMPLATE_ROUTES_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-org" / "src" / "api" / "store_template_routes.py"
)
HEALTH_ROUTES_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-org" / "src" / "api" / "store_health_routes.py"
)
TX_ORG_MAIN_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-org" / "src" / "main.py"
)


def _find_func_source(file_path, func_name):
    source = file_path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(source, node)
    return ""


# ═══════════════════════════════════════════════════════════════════════
# Task 2.3: 门店配置模板
# ═══════════════════════════════════════════════════════════════════════


class TestStoreTemplateRoutes:
    """门店配置模板 API"""

    def test_file_exists(self):
        """store_template_routes.py 文件存在"""
        assert TEMPLATE_ROUTES_PY.exists(), "store_template_routes.py 不存在"

    def test_router_prefix(self):
        """路由前缀为 /api/v1/store-templates"""
        source = TEMPLATE_ROUTES_PY.read_text()
        assert "/api/v1/store-templates" in source, "路由前缀错误"

    def test_create_template_endpoint(self):
        """POST / 创建模板端点"""
        source = TEMPLATE_ROUTES_PY.read_text()
        assert 'summary="从门店创建配置模板"' in source or "create_store_template" in source, (
            "缺少创建模板端点"
        )
        assert "store_config_templates" in source, (
            "模板数据未写入 store_config_templates 表"
        )

    def test_list_templates_endpoint(self):
        """GET / 模板列表"""
        source = TEMPLATE_ROUTES_PY.read_text()
        assert "list_store_templates" in source, "缺少模板列表端点"

    def test_get_template_endpoint(self):
        """GET /{template_id} 模板详情"""
        source = TEMPLATE_ROUTES_PY.read_text()
        assert "get_store_template" in source, "缺少模板详情端点"

    def test_delete_template_endpoint(self):
        """DELETE /{template_id} 删除模板"""
        source = TEMPLATE_ROUTES_PY.read_text()
        assert "delete_store_template" in source, "缺少删除模板端点"

    def test_apply_template_endpoint(self):
        """POST /{template_id}/apply 从模板创建门店"""
        source = TEMPLATE_ROUTES_PY.read_text()
        assert "apply_store_template" in source, "缺少应用模板端点"

    def test_7_config_domains_captured(self):
        """模板快照捕获 7 大配置域"""
        source = TEMPLATE_ROUTES_PY.read_text()
        domains = ["tables", "production_depts", "receipt_templates",
                   "attendance_rules", "shift_configs", "dispatch_rules",
                   "store_push_configs"]
        for domain in domains:
            assert domain in source, f"模板快照缺少 {domain} 配置域"

    def test_apply_creates_store_record(self):
        """应用模板创建 stores 记录"""
        source = _find_func_source(TEMPLATE_ROUTES_PY, "apply_store_template")
        assert source, "apply_store_template 函数未找到"
        assert "INSERT INTO stores" in source, (
            "apply_store_template 未创建门店记录"
        )
        assert "store_code" in source, "未生成门店编码"

    def test_template_wired_in_main_py(self):
        """tx-org main.py 注册了 store_template_router"""
        source = TX_ORG_MAIN_PY.read_text()
        assert "store_template_router" in source, (
            "main.py 未注册 store_template_router"
        )


# ═══════════════════════════════════════════════════════════════════════
# Task 2.4: 门店健康监控
# ═══════════════════════════════════════════════════════════════════════


class TestStoreHealthRoutes:
    """门店健康监控 API"""

    def test_file_exists(self):
        """store_health_routes.py 文件存在"""
        assert HEALTH_ROUTES_PY.exists(), "store_health_routes.py 不存在"

    def test_router_prefix(self):
        """路由前缀为 /api/v1/store-health"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "/api/v1/store-health" in source, "路由前缀错误"

    def test_overview_endpoint(self):
        """GET /overview/{store_id} 健康总览"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "store_health_overview" in source, "缺少健康总览端点"

    def test_alerts_endpoint(self):
        """GET /alerts 告警列表"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "store_alerts" in source, "缺少告警列表端点"

    def test_5_dimensions_monitored(self):
        """覆盖 5 大监控维度"""
        source = HEALTH_ROUTES_PY.read_text()
        dimensions = ["devices", "printers", "kds_backlog", "daily_settlement", "sync"]
        for dim in dimensions:
            assert dim in source, f"监控维度缺少 {dim}"

    def test_device_health_query(self):
        """设备健康查询存在"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "_get_device_health" in source, "缺少 _get_device_health"

    def test_printer_health_query(self):
        """打印机健康查询存在"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "_get_printer_health" in source, "缺少 _get_printer_health"

    def test_kds_backlog_query(self):
        """KDS 积压查询存在"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "_get_kds_backlog" in source, "缺少 _get_kds_backlog"

    def test_settlement_status_query(self):
        """日结状态查询存在"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "_get_daily_settlement_status" in source, "缺少日结状态查询"

    def test_sync_status_query(self):
        """同步状态查询存在"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "_get_sync_status" in source, "缺少同步状态查询"

    def test_health_score_calculation(self):
        """健康分计算（0-100）"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "health_score" in source, "缺少 health_score 计算"
        assert "healthy" in source, "缺少 healthy 状态判定"
        assert "degraded" in source, "缺少 degraded 状态判定"

    def test_alert_conditions(self):
        """告警条件定义存在"""
        source = HEALTH_ROUTES_PY.read_text()
        assert "alert" in source, "缺少告警条件"

    def test_wired_in_main_py(self):
        """tx-org main.py 注册了 store_health_router"""
        source = TX_ORG_MAIN_PY.read_text()
        assert "store_health_router" in source, (
            "main.py 未注册 store_health_router"
        )


# ═══════════════════════════════════════════════════════════════════════
# Task 2.5/2.6: 储值结算 + 央厨/配送验证
# ═══════════════════════════════════════════════════════════════════════


class TestStoredValueSettlementReady:
    """储值分账结算就绪验证"""

    def test_stored_value_settlement_routes_exist(self):
        """stored_value_settlement_routes.py 文件存在"""
        sv_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-finance" / "src" / "api"
            / "stored_value_settlement_routes.py"
        )
        assert sv_path.exists(), "stored_value_settlement_routes.py 不存在"

    def test_sv_batch_endpoints_defined(self):
        """储值批量结算端点已定义"""
        sv_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-finance" / "src" / "api"
            / "stored_value_settlement_routes.py"
        )
        source = sv_path.read_text()
        assert "run-daily" in source, "缺少 run-daily 端点"
        assert "confirm" in source, "缺少 confirm 端点"
        assert "settle" in source, "缺少 settle 端点"
        assert "dashboard" in source, "缺少 dashboard 端点"


class TestCentralKitchenReady:
    """中央厨房/配送代码验证"""

    def test_central_kitchen_service_exists(self):
        """中央厨房服务文件存在"""
        ck_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-supply" / "src" / "services"
            / "central_kitchen_service.py"
        )
        assert ck_path.exists(), "central_kitchen_service.py 不存在"

    def test_central_kitchen_uses_db_repository(self):
        """中央厨房使用 DB Repository（非内存 dict）"""
        ck_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-supply" / "src" / "services"
            / "central_kitchen_service.py"
        )
        source = ck_path.read_text()
        assert "Repository" in source or "repository" in source, (
            "中央厨房服务未使用 Repository 模式（可能仍是内存实现）"
        )

    def test_delivery_router_exists(self):
        """配送路由文件存在"""
        del_path = (
            Path(__file__).parent.parent.parent
            / "services" / "tx-trade" / "src" / "routers"
            / "delivery_router.py"
        )
        assert del_path.exists(), "delivery_router.py 不存在"
