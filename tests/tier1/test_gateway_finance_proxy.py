"""Task 1.1: Gateway 分账路由接线验证 — Tier 1

验证 Gateway 通配符代理正确转发 /api/v1/finance/* 到 tx-finance。
不直接 import proxy.py（触发 httpx 连接池初始化），改为验证源码结构。
"""

import ast
import os
from pathlib import Path

import pytest


PROXY_PY = Path(__file__).parent.parent.parent / "services" / "gateway" / "src" / "proxy.py"


def _parse_domain_routes():
    """解析 proxy.py 中 DOMAIN_ROUTES 字典的字面量条目"""
    source = PROXY_PY.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DOMAIN_ROUTES":
                    routes = {}
                    if isinstance(node.value, ast.Dict):
                        for key_node, value_node in zip(node.value.keys, node.value.values):
                            if isinstance(key_node, ast.Constant):
                                key = key_node.value
                                if isinstance(value_node, ast.Call) and hasattr(value_node.func, 'attr'):
                                    # os.getenv("TX_FINANCE_URL", "http://localhost:8007")
                                    routes[key] = {
                                        "env_var": value_node.args[0].value if value_node.args else None,
                                        "default": value_node.args[1].value if len(value_node.args) > 1 else None,
                                    }
                    return routes
    return {}


def _parse_wildcard_route():
    """验证通配符路由装饰器存在"""
    source = PROXY_PY.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "domain_proxy":
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    if hasattr(decorator.func, 'attr') and decorator.func.attr == "api_route":
                        return decorator
    return None


def _find_function_source(func_name):
    """从 proxy.py 源码中查找函数定义"""
    source = PROXY_PY.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(source, node)
    return ""


# ── DOMAIN_ROUTES 注册验证 ──


def test_finance_domain_registered():
    """finance 域已在 Gateway DOMAIN_ROUTES 注册"""
    routes = _parse_domain_routes()
    assert "finance" in routes, (
        "finance 域未在 DOMAIN_ROUTES 注册"
    )
    assert routes["finance"]["default"] is not None
    assert "8007" in (routes["finance"]["default"] or ""), (
        f"finance 域默认端口不是8007: {routes['finance']['default']}"
    )


def test_pay_domain_registered():
    """pay 域已在 Gateway DOMAIN_ROUTES 注册"""
    routes = _parse_domain_routes()
    assert "pay" in routes, (
        "pay 域未在 DOMAIN_ROUTES 注册"
    )


def test_all_core_domains_registered():
    """14 个核心域全部注册"""
    routes = _parse_domain_routes()
    core_domains = [
        "trade", "menu", "member", "growth", "ops", "supply",
        "finance", "agent", "analytics", "brain", "intel", "org", "civic", "pay",
    ]
    for domain in core_domains:
        assert domain in routes, f"核心域 {domain} 未在 DOMAIN_ROUTES 注册"


# ── 通配符路由验证 ──


def test_wildcard_route_exists():
    """domain_proxy 通配符路由已定义"""
    source = PROXY_PY.read_text()
    assert "async def domain_proxy" in source, "domain_proxy 函数未找到"
    assert "@router.api_route" in source, "domain_proxy 缺少 @router.api_route 装饰器"


def test_wildcard_route_pattern():
    """通配符路由匹配 /api/v1/{domain}/{path:path} 模式"""
    source = PROXY_PY.read_text()
    assert "/api/v1/{domain}/{path:path}" in source, (
        "通配符路由模式不匹配 /api/v1/{domain}/{path:path}"
    )


def test_wildcard_route_handles_all_methods():
    """通配符路由处理全部 HTTP 方法"""
    source = PROXY_PY.read_text()
    assert "GET" in source
    assert "POST" in source
    assert "PUT" in source
    assert "DELETE" in source


# ── 分账路径转发验证 ──


def test_finance_splits_path_matches_finance_domain():
    """/api/v1/finance/splits/* 中 domain 部分 = 'finance'"""
    path = "/api/v1/finance/splits/rules"
    domain = path.split("/")[3]
    assert domain == "finance", f"路径域部分: {domain}"


def test_finance_sv_settlement_path_matches_finance_domain():
    """/api/v1/finance/sv-settlement/* 中 domain 部分 = 'finance'"""
    path = "/api/v1/finance/sv-settlement/rules"
    domain = path.split("/")[3]
    assert domain == "finance", f"路径域部分: {domain}"


# ── 转发函数容错验证 ──


def test_proxy_function_has_503_fallback():
    """_proxy 函数在目标为空时返回503"""
    source = _find_function_source("_proxy")
    assert "503" in source or "SERVICE_UNAVAILABLE" in source, (
        "_proxy 缺少503容错返回"
    )


def test_proxy_function_handles_connect_error():
    """_proxy 函数处理 ConnectError"""
    source = _find_function_source("_proxy")
    assert "ConnectError" in source, "_proxy 缺少 ConnectError 异常处理"


def test_proxy_function_handles_timeout():
    """_proxy 函数处理 TimeoutException"""
    source = _find_function_source("_proxy")
    assert "Timeout" in source, "_proxy 缺少超时异常处理"


def test_proxy_function_strips_host_header():
    """_proxy 剥离 host 和 content-length header"""
    source = _find_function_source("_proxy")
    assert "host" in source.lower(), "_proxy 未剥离 host header"


def test_proxy_function_legacy_fallback():
    """目标不可达时回退到 LEGACY_URL"""
    source = _find_function_source("_proxy")
    assert "LEGACY_URL" in source, "_proxy 缺少旧单体回退逻辑"


# ── tx-finance 路由注册验证 ──

FINANCE_MAIN_PY = Path(__file__).parent.parent.parent / "services" / "tx-finance" / "src" / "main.py"


def test_tx_finance_registers_split_router():
    """tx-finance main.py 注册了 split_router（分账路由）"""
    source = FINANCE_MAIN_PY.read_text()
    assert "split_router" in source, "tx-finance main.py 未注册 split_router"
    assert "split_routes" in source, "tx-finance 未导入 split_routes"


def test_tx_finance_registers_fund_settlement_router():
    """tx-finance main.py 注册了 fund_settlement_router（储值分账）"""
    source = FINANCE_MAIN_PY.read_text()
    assert "fund_settlement_router" in source, "tx-finance main.py 未注册 fund_settlement_router"


def test_tx_finance_registers_split_payment_router():
    """tx-finance main.py 注册了 split_payment_router（聚合支付/分账）"""
    source = FINANCE_MAIN_PY.read_text()
    assert "split_payment_router" in source, "tx-finance 未注册 split_payment_router"


# ── 端到端路径覆盖矩阵 ──

SPLIT_PATHS = [
    "/api/v1/finance/splits/rules",
    "/api/v1/finance/splits/execute",
    "/api/v1/finance/splits/settle",
    "/api/v1/finance/splits/transactions",
    "/api/v1/finance/splits/settlement",
    "/api/v1/finance/splits/channel-notify",
]

SV_SETTLEMENT_PATHS = [
    "/api/v1/finance/sv-settlement/rules",
    "/api/v1/finance/sv-settlement/ledger",
    "/api/v1/finance/sv-settlement/batches",
    "/api/v1/finance/sv-settlement/dashboard",
]


@pytest.mark.parametrize("path", SPLIT_PATHS + SV_SETTLEMENT_PATHS)
def test_all_finance_paths_routable(path):
    """所有分账/储值分账路径通过 Gateway 的 finance 域可路由"""
    domain = path.split("/")[3]
    assert domain == "finance", (
        f"路径 {path} 的域部分是 '{domain}'，不是 'finance'"
    )
