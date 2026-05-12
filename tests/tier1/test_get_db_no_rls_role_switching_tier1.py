"""get_db_no_rls 双模式 Tier 1 测试

审计 S-05 阶段 4：get_db_no_rls 改造为 env-driven 双模式：
  - 默认（RLS_USE_TX_SYSTEM_ROLE 未设/false）→ 模式 A: SET LOCAL row_security = off
  - RLS_USE_TX_SYSTEM_ROLE=true → 模式 B: SET LOCAL ROLE tx_system_role

本测试用 mock AsyncSession 验证 SQL 字符串生成正确，不连真 PG。
真 PG 行为（BYPASSRLS 撤销后 RLS 是否生效）由 staging dry-run 验证。

CLAUDE.md §17 Tier 1：S-05 RLS 隔离是零容忍域，本切换涉及生产路径，必须
TDD 覆盖 SQL 字符串 + finally 清理逻辑 + env 切换。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# database.py 用 PEP 604 union（type | None），需要 Python 3.10+
# 本地 macOS system Python 3.9 跳过；CI 用 setup-python@v6 with 3.11 会跑
if sys.version_info < (3, 10):
    pytest.skip(
        "Requires Python 3.10+ (database.py uses PEP 604 union)",
        allow_module_level=True,
    )

# 仓库根加 sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_database_module():
    """直接 import shared/ontology/src/database.py 单文件，绕过 package
    __init__ 触发的 entities 导入（entities.py 用 PEP 604 union 在 3.9 报错；
    CI 3.11+ 不会，但本地 3.9 跑测要绕过）。"""
    src_path = _REPO_ROOT / "shared" / "ontology" / "src" / "database.py"
    spec = importlib.util.spec_from_file_location(
        "shared_ontology_src_database_test", src_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 测试期间替代 import 入口
_db_module = _load_database_module()
get_db_no_rls = _db_module.get_db_no_rls


class _CapturingSession:
    """模拟 AsyncSession，记录所有 .execute(text(...)) 的 SQL 字符串。"""

    def __init__(self, *, raise_in_yield: Exception | None = None) -> None:
        self.executed_sqls: list[str] = []
        self.committed: bool = False
        self.rolled_back: bool = False
        self._raise_in_yield = raise_in_yield

    async def execute(self, sql_obj, *_args, **_kwargs):
        # sql_obj 是 sqlalchemy text() 包装；str() 取出 SQL 字符串
        self.executed_sqls.append(str(sql_obj))
        return mock.MagicMock()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def mock_session_factory():
    """patch async_session_factory 让 get_db_no_rls 用 _CapturingSession。"""
    sessions: list[_CapturingSession] = []

    class _Ctx:
        def __init__(self, session: _CapturingSession) -> None:
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False  # 不吞异常

    def _factory_call():
        s = _CapturingSession()
        sessions.append(s)
        return _Ctx(s)

    with mock.patch.object(
        _db_module,
        "async_session_factory",
        side_effect=_factory_call,
    ):
        yield sessions


class TestModeA_LegacyRowSecurity:
    """默认模式（无 env）→ SET LOCAL row_security = off"""

    @pytest.mark.asyncio
    async def test_default_uses_row_security_off(self, mock_session_factory):
        with mock.patch.dict(os.environ, {}, clear=True):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            # 第一条 SQL 应是 SET LOCAL row_security = off
            assert "SET LOCAL row_security = off" in session.executed_sqls[0]
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_rls_use_role_false_uses_legacy(self, mock_session_factory):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "false"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            assert "SET LOCAL row_security = off" in session.executed_sqls[0]
            assert "SET LOCAL ROLE" not in session.executed_sqls[0]
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_legacy_finally_clears_tenant_id(self, mock_session_factory):
        with mock.patch.dict(os.environ, {}, clear=True):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass
            # finally 应执行 set_config('app.tenant_id', '', true)
            sql_blob = " ".join(session.executed_sqls)
            assert "set_config('app.tenant_id', '', true)" in sql_blob
            assert "RESET ROLE" not in sql_blob


class TestModeB_TxSystemRole:
    """RLS_USE_TX_SYSTEM_ROLE=true → SET LOCAL ROLE tx_system_role"""

    @pytest.mark.asyncio
    async def test_env_true_uses_set_role(self, mock_session_factory):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "true"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            assert "SET LOCAL ROLE tx_system_role" in session.executed_sqls[0]
            assert "row_security" not in session.executed_sqls[0]
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_env_1_uses_set_role(self, mock_session_factory):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "1"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            assert "SET LOCAL ROLE tx_system_role" in session.executed_sqls[0]
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_env_yes_uses_set_role(self, mock_session_factory):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "yes"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            assert "SET LOCAL ROLE tx_system_role" in session.executed_sqls[0]
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_role_mode_finally_resets_role(self, mock_session_factory):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "true"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass
            sql_blob = " ".join(session.executed_sqls)
            assert "RESET ROLE" in sql_blob
            assert "set_config('app.tenant_id', '', true)" not in sql_blob

    @pytest.mark.asyncio
    async def test_role_mode_does_not_set_row_security(self, mock_session_factory):
        """模式 B 必须不调 SET LOCAL row_security = off
        （因为 cutover 后 app role 没 BYPASSRLS，调了会 silent 无效但语义混淆）"""
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "true"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass
            sql_blob = " ".join(session.executed_sqls)
            assert "row_security = off" not in sql_blob


class TestEnvParsingEdgeCases:
    """env 值解析的边界 case"""

    @pytest.mark.parametrize(
        "env_value,expected_role_mode",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("YES", True),
            ("on", True),
            ("ON", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("", False),
            ("anything-else", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_env_value_parsing(
        self, mock_session_factory, env_value, expected_role_mode
    ):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": env_value}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass

            sql_blob = " ".join(session.executed_sqls)
            if expected_role_mode:
                assert "SET LOCAL ROLE tx_system_role" in sql_blob, (
                    f"env={env_value!r} 应启用 role 模式但未生效"
                )
            else:
                assert "SET LOCAL row_security = off" in sql_blob, (
                    f"env={env_value!r} 应保持 legacy 模式但被解析为 role 模式"
                )


class TestExceptionHandling:
    """异常处理：rollback + finally 仍执行清理"""

    @pytest.mark.asyncio
    async def test_legacy_mode_exception_rollbacks(self, mock_session_factory):
        with mock.patch.dict(os.environ, {}, clear=True):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            # 模拟 yield 期间业务代码抛异常
            try:
                await agen.athrow(RuntimeError("boom"))
            except RuntimeError:
                pass
            assert session.rolled_back, "异常路径必须 rollback"
            sql_blob = " ".join(session.executed_sqls)
            assert "set_config('app.tenant_id', '', true)" in sql_blob, (
                "legacy 模式 finally 必须清 tenant_id GUC"
            )

    @pytest.mark.asyncio
    async def test_role_mode_exception_resets_role(self, mock_session_factory):
        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "true"}, clear=True
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            try:
                await agen.athrow(RuntimeError("boom"))
            except RuntimeError:
                pass
            assert session.rolled_back, "异常路径必须 rollback"
            sql_blob = " ".join(session.executed_sqls)
            assert "RESET ROLE" in sql_blob, "role 模式 finally 必须 RESET ROLE"


class TestSqlScriptsExist:
    """部署脚本存在性 + 关键 SQL 内容"""

    def test_create_role_script_exists(self):
        path = _REPO_ROOT / "scripts" / "db" / "create_tx_system_role.sql"
        assert path.exists(), "scripts/db/create_tx_system_role.sql 必须存在"
        content = path.read_text(encoding="utf-8")
        assert "CREATE ROLE tx_system_role" in content
        assert "BYPASSRLS" in content
        assert "GRANT tx_system_role TO tunxiang" in content
        assert "NOLOGIN" in content, "tx_system_role 必须 NOLOGIN（防止登录帐号）"
        assert "NOINHERIT" in content, "tx_system_role 必须 NOINHERIT（强制 SET ROLE）"

    def test_revoke_script_exists(self):
        path = _REPO_ROOT / "scripts" / "db" / "revoke_tunxiang_bypassrls.sql"
        assert path.exists(), "scripts/db/revoke_tunxiang_bypassrls.sql 必须存在"
        content = path.read_text(encoding="utf-8")
        assert "ALTER ROLE tunxiang NOBYPASSRLS" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
