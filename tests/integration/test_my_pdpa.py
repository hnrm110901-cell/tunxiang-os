"""PDPA 数据保护服务 + MY 支付网关集成测试"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_module(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 将项目根目录加入 sys.path，使 shared.* 等绝对导入可解析
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════════════════
# PDPA 数据保护服务
# ═══════════════════════════════════════════════════════════════════════════


class TestPDPAService:
    """马来西亚 PDPA 数据主体权利服务"""

    MOCK_TENANT = "a0000000-0000-0000-0000-000000000001"

    @pytest.fixture(autouse=True)
    def _mock_shared_security(self):
        """在加载 pdpa_service 之前 mock shared.security 依赖"""
        mock_modules = {
            "shared": MagicMock(),
            "shared.security": MagicMock(),
            "shared.security.src": MagicMock(),
            "shared.security.src.data_sovereignty": MagicMock(),
            "shared.security.src.field_encryption": MagicMock(),
            "shared.security.data_masking": MagicMock(),
        }
        mock_modules["shared.security.src.data_sovereignty"].DataSovereigntyRouter = MagicMock
        mock_modules["shared.security.src.field_encryption"].get_encryptor = MagicMock(
            return_value=MagicMock()
        )
        mock_modules["shared.security.src.field_encryption"].is_encrypted = MagicMock(
            return_value=False
        )
        mock_modules["shared.security.data_masking"].mask_value = MagicMock(
            return_value="***"
        )
        with patch.dict(sys.modules, mock_modules):
            yield

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def pdpa_service(self, mock_db):
        mod = _load_module(
            "pdpa_service",
            "services/tx-malaysia/src/services/pdpa_service.py",
        )
        return mod.PDPAService(db=mock_db, tenant_id=self.MOCK_TENANT)

    @pytest.mark.asyncio
    async def test_create_access_request(self, pdpa_service):
        """创建数据访问请求"""
        import uuid

        # create_access_request 内部会对 customer_id 做 uuid.UUID() 转换
        # 传字符串形式以避免 UUID 嵌套转换
        request = await pdpa_service.create_access_request(
            customer_id=str(uuid.uuid4()),
            requested_by="customer",
        )
        assert request["status"] == "pending"
        assert "id" in request

    @pytest.mark.asyncio
    async def test_create_correction_request(self, pdpa_service):
        """创建数据更正请求"""
        import uuid
        from types import SimpleNamespace

        cid = uuid.uuid4()
        rid = uuid.uuid4()
        fake_row = SimpleNamespace(
            id=rid,
            customer_id=cid,
            request_type="correction",
            status="pending",
            request_data=None,
            response_data=None,
            requested_by="customer",
            notes="号码变更",
            created_at=None,
            updated_at=None,
        )

        empty_result = MagicMock()
        empty_result.fetchone.return_value = None
        empty_result.fetchall.return_value = []

        row_result = MagicMock()
        row_result.fetchone.return_value = fake_row
        row_result.fetchall.return_value = []

        # handle_data_subject_request 调用链:
        #   1. _set_tenant → get_request → _set_tenant
        #   2. check existing → fetchone=None
        #   3. INSERT
        #   4. get_request → execute (need row)
        pdpa_service.db.execute = AsyncMock(side_effect=[
            empty_result,  # _set_tenant
            empty_result,  # check existing
            empty_result,  # INSERT
            empty_result,  # get_request._set_tenant
            row_result,    # get_request SELECT
        ])

        request = await pdpa_service.create_correction_request(
            customer_id=str(cid),
            field_name="phone",
            current_value="+60-12345678",
            new_value="+60-87654321",
            reason="号码变更",
        )
        assert request["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_request_status(self, pdpa_service):
        """查询请求状态"""
        import uuid
        from unittest.mock import MagicMock

        from types import SimpleNamespace

        request_id = uuid.uuid4()
        fake_row = SimpleNamespace(
            id=request_id,
            customer_id=uuid.uuid4(),
            request_type="access",
            status="completed",
            request_data=None,
            response_data=None,
            requested_by="customer",
            notes=None,
            created_at=None,
            updated_at=None,
        )
        pdpa_service.db.execute.return_value = MagicMock(
            fetchone=MagicMock(return_value=fake_row)
        )
        status = await pdpa_service.get_request_status(request_id=str(request_id))
        assert status is not None
        assert status["status"] == "completed"


# ═══════════════════════════════════════════════════════════════════════════
# MY 支付网关（代码静态分析验证，避免运行时依赖链）
# ═══════════════════════════════════════════════════════════════════════════

_MY_PAYMENT_METHODS = {"tng_ewallet", "grabpay", "boost"}


def _extract_payment_methods_from_source() -> dict[str, dict]:
    """从 payment_gateway.py 源码中提取 PAYMENT_METHODS dict（AST 静态分析）"""
    path = "services/tx-trade/src/services/payment_gateway.py"
    with open(path, encoding="utf-8") as f:
        source = f.read()

    # 查找 PAYMENT_METHODS = { ... } 赋值
    tree = ast.parse(source, filename=path)
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PAYMENT_METHODS":
                    # This is a class-level assignment, find it inside the class body
                    pass
        # Also check ClassDef assignments
        if isinstance(node, ast.ClassDef) and node.name == "PaymentGateway":
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "PAYMENT_METHODS":
                            # Found class-level PAYMENT_METHODS
                            if isinstance(item.value, ast.Dict):
                                for key, val in zip(item.value.keys, item.value.values):
                                    if isinstance(key, ast.Constant):
                                        method_name = key.value
                                        method_config = {}
                                        if isinstance(val, ast.Dict):
                                            for mk, mv in zip(val.keys, val.values):
                                                if isinstance(mk, ast.Constant):
                                                    if isinstance(mv, ast.Constant):
                                                        method_config[mk.value] = mv.value
                                                    elif isinstance(mv, ast.UnaryOp) and isinstance(mv.op, ast.USub) and isinstance(mv.operand, ast.Constant):
                                                        method_config[mk.value] = -mv.operand.value
                                        methods[method_name] = method_config
    return methods


class TestMyPaymentGateway:
    """马来西亚支付方式集成（源代码静态分析验证）"""

    def test_my_methods_configured(self):
        """MY 支付方式在 payment_gateway 中已配置"""
        methods = _extract_payment_methods_from_source()
        available_methods = set(methods.keys())
        missing = _MY_PAYMENT_METHODS - available_methods
        assert not missing, (
            f"payment_gateway.PaymentGateway.PAYMENT_METHODS "
            f"缺少马来西亚支付方式: {missing}"
        )

    def test_my_method_fee_rates(self):
        """MY 支付费率合理"""
        methods = _extract_payment_methods_from_source()

        for m in _MY_PAYMENT_METHODS:
            config = methods.get(m, {})
            fee = config.get("fee_rate_permil", 0)
            assert fee <= 20, f"{m} 费率不应超过 2%，当前: {fee / 10}%"

    def test_my_payment_notify_service_imports(self):
        """MY 支付回调通知服务可导入（AST 静态验证，避免运行时依赖链过长）"""
        notify_path = "services/tx-trade/src/services/my_payment_notify_service.py"
        assert os.path.exists(notify_path), f"文件不存在: {notify_path}"

        with open(notify_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=notify_path)

        func_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "handle_my_payment_callback" in func_names, (
            f"缺少 handle_my_payment_callback 函数; found: {func_names}"
        )
        assert "register_verifier" in func_names
