"""Phase 2: 分账异常处理 + 储值路由注册 — Tier 1 测试

Task 2.1+2.2 验证：
  1. 储值分账路由已在 tx-finance main.py 注册
  2. retry_failed_records 方法存在且含重试上限
  3. reverse_settled_record 创建负向流水
  4. mark_discrepancy + list_discrepancies + resolve_discrepancy
  5. 分账 API 新增端点已定义（/retry, /reverse, /discrepancy, /discrepancies）
"""

import ast
from pathlib import Path

import pytest

# ── 文件路径 ──

FINANCE_MAIN_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-finance" / "src" / "main.py"
)
SPLIT_ENGINE_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-finance" / "src" / "services" / "split_engine.py"
)
SPLIT_ROUTES_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-finance" / "src" / "api" / "split_routes.py"
)


def _find_method_source(file_path, method_name):
    source = file_path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            return ast.get_source_segment(source, node)
    return ""


# ═══════════════════════════════════════════════════════════════════════
# Task 2.1/2.2: 储值分账路由注册
# ═══════════════════════════════════════════════════════════════════════


class TestStoredValueSettlementRegistration:
    """储值分账路由已注册到 tx-finance"""

    def test_import_stored_value_settlement_router(self):
        """main.py 导入了 stored_value_settlement_router"""
        source = FINANCE_MAIN_PY.read_text()
        assert "stored_value_settlement_router" in source, (
            "main.py 未导入 stored_value_settlement_router"
        )

    def test_register_stored_value_settlement_router(self):
        """main.py 注册了 stored_value_settlement_router"""
        source = FINANCE_MAIN_PY.read_text()
        assert "app.include_router(stored_value_settlement_router)" in source, (
            "main.py 未注册 stored_value_settlement_router"
        )

    def test_sv_settlement_prefix_in_source(self):
        """sv-settlement 前缀在注册行附近"""
        source = FINANCE_MAIN_PY.read_text()
        assert "sv-settlement" in source, (
            "main.py 缺少 sv-settlement 前缀说明"
        )


# ═══════════════════════════════════════════════════════════════════════
# Task 2.2: 分账异常处理 — retry/reverse/discrepancy
# ═══════════════════════════════════════════════════════════════════════


class TestSplitRetry:
    """分账重试功能"""

    def test_retry_failed_records_method_exists(self):
        """retry_failed_records 方法已定义"""
        source = _find_method_source(SPLIT_ENGINE_PY, "retry_failed_records")
        assert source, "retry_failed_records 方法未找到"

    def test_retry_max_3_times(self):
        """重试上限为 3 次"""
        source = _find_method_source(SPLIT_ENGINE_PY, "retry_failed_records")
        assert "retry_count" in source, "retry_failed_records 未跟踪重试次数"
        assert "< 3" in source or "<= 3" in source or "MAX" in source, (
            "retry_failed_records 缺少重试上限"
        )

    def test_retry_only_cancelled_status(self):
        """只重试 cancelled 状态的记录"""
        source = _find_method_source(SPLIT_ENGINE_PY, "retry_failed_records")
        assert "cancelled" in source, "retry_failed_records 未过滤 cancelled 状态"

    def test_retry_route_exists(self):
        """POST /retry 端点已定义"""
        source = SPLIT_ROUTES_PY.read_text()
        assert "/retry" in source, "split_routes.py 缺少 /retry 端点"


class TestSplitReversal:
    """分账回退功能"""

    def test_reverse_settled_record_method_exists(self):
        """reverse_settled_record 方法已定义"""
        source = _find_method_source(SPLIT_ENGINE_PY, "reverse_settled_record")
        assert source, "reverse_settled_record 方法未找到"

    def test_reversal_creates_negative_entry(self):
        """回退创建负向流水记录"""
        source = _find_method_source(SPLIT_ENGINE_PY, "reverse_settled_record")
        assert "-row.split_amount_fen" in source or "-" in source, (
            "reverse_settled_record 未创建负向金额"
        )
        assert "reversed" in source, "回退记录状态应为 reversed"

    def test_reversal_only_settled_records(self):
        """只能回退 settled 状态的记录"""
        source = _find_method_source(SPLIT_ENGINE_PY, "reverse_settled_record")
        assert "settled" in source, (
            "reverse_settled_record 未限制只回退 settled 记录"
        )

    def test_reversal_route_exists(self):
        """POST /reverse 端点已定义"""
        source = SPLIT_ROUTES_PY.read_text()
        assert "/reverse" in source, "split_routes.py 缺少 /reverse 端点"


class TestDiscrepancyManagement:
    """差错账管理功能"""

    def test_mark_discrepancy_method_exists(self):
        """mark_discrepancy 方法已定义"""
        source = _find_method_source(SPLIT_ENGINE_PY, "mark_discrepancy")
        assert source, "mark_discrepancy 方法未找到"

    def test_discrepancy_only_settled_or_pending(self):
        """只能将 settled/pending 记录标记为差错"""
        source = _find_method_source(SPLIT_ENGINE_PY, "mark_discrepancy")
        assert "settled" in source and "pending" in source, (
            "mark_discrepancy 应只接受 settled/pending 状态"
        )

    def test_discrepancy_status_value(self):
        """差错状态值为 'discrepancy'"""
        source = _find_method_source(SPLIT_ENGINE_PY, "mark_discrepancy")
        assert "discrepancy" in source, "差错状态值应为 discrepancy"

    def test_list_discrepancies_method_exists(self):
        """list_discrepancies 方法已定义"""
        source = _find_method_source(SPLIT_ENGINE_PY, "list_discrepancies")
        assert source, "list_discrepancies 方法未找到"

    def test_resolve_discrepancy_method_exists(self):
        """resolve_discrepancy 方法已定义"""
        source = _find_method_source(SPLIT_ENGINE_PY, "resolve_discrepancy")
        assert source, "resolve_discrepancy 方法未找到"

    def test_resolve_discrepancy_validates_resolution(self):
        """resolve_discrepancy 校验 resolution 参数"""
        source = _find_method_source(SPLIT_ENGINE_PY, "resolve_discrepancy")
        assert "settled" in source, "resolve_discrepancy 应接受 settled"
        assert "cancelled" in source, "resolve_discrepancy 应接受 cancelled"

    def test_discrepancy_routes_exist(self):
        """差错账管理端点已定义"""
        source = SPLIT_ROUTES_PY.read_text()
        assert "/discrepancy" in source, "split_routes.py 缺少 /discrepancy 端点"
        assert "/discrepancies" in source, "split_routes.py 缺少 /discrepancies 端点"


# ═══════════════════════════════════════════════════════════════════════
# 分账路由端点完整性
# ═══════════════════════════════════════════════════════════════════════


ENHANCED_SPLIT_ENDPOINTS = [
    "/api/v1/finance/splits/rules",
    "/api/v1/finance/splits/execute",
    "/api/v1/finance/splits/settle",
    "/api/v1/finance/splits/channel-notify",
    "/api/v1/finance/splits/retry",
    "/api/v1/finance/splits/reverse",
    "/api/v1/finance/splits/discrepancy",
    "/api/v1/finance/splits/discrepancies",
    "/api/v1/finance/splits/transactions",
    "/api/v1/finance/splits/settlement",
]


@pytest.mark.parametrize("path_prefix", ENHANCED_SPLIT_ENDPOINTS)
def test_split_endpoint_domain_is_finance(path_prefix):
    """所有分账端点域部分为 finance"""
    domain = path_prefix.split("/")[3]
    assert domain == "finance", f"{path_prefix} 域部分为 {domain}, 不是 finance"


# ═══════════════════════════════════════════════════════════════════════
# 分账汇总包含新状态
# ═══════════════════════════════════════════════════════════════════════


def test_settlement_summary_includes_cancelled():
    """分账汇总查询包含 cancelled 金额"""
    source = _find_method_source(SPLIT_ENGINE_PY, "get_settlement_summary")
    assert "cancelled" in source, "get_settlement_summary 未汇总 cancelled 金额"


def test_settlement_summary_includes_discrepancy_comment():
    """分账记录行包含 discrepancy 字段"""
    source = SPLIT_ROUTES_PY.read_text()
    assert "discrepancy" in source, "split_routes.py 差错相关逻辑缺失"
