"""get_db_no_rls 单一模式 Tier 1 测试

审计 S-05 阶段 5 cutover 完成后：双模式已删，强制 SET LOCAL ROLE tx_system_role。
要求 DBA 已撤 app role 的 BYPASSRLS（详见 docs/security/cutover-cleanup-plan.md §3.2）。

本测试用 mock AsyncSession 验证 SQL 字符串生成正确，不连真 PG。
真 PG 行为（BYPASSRLS 撤销后 RLS 是否生效）由 staging dry-run 验证。

CLAUDE.md §17 Tier 1：S-05 RLS 隔离是零容忍域，本切换涉及生产路径，必须
TDD 覆盖 SQL 字符串 + finally 清理逻辑。
"""

from __future__ import annotations

import importlib.util
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


class TestSingleModeSetRole:
    """cutover 完成后的单一模式：SET LOCAL ROLE tx_system_role + RESET ROLE in finally。"""

    @pytest.mark.asyncio
    async def test_uses_set_local_role_tx_system_role(self, mock_session_factory):
        """第一条 SQL 必须是 SET LOCAL ROLE tx_system_role（不再有 row_security 路径）。"""
        agen = get_db_no_rls()
        session = await agen.__anext__()
        assert "SET LOCAL ROLE tx_system_role" in session.executed_sqls[0]
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass

    @pytest.mark.asyncio
    async def test_does_not_set_row_security(self, mock_session_factory):
        """绝不能再调 SET LOCAL row_security = off（cutover 后 app role 已 NOBYPASSRLS，
        即便调了也 silent 无效但语义混淆）。"""
        agen = get_db_no_rls()
        session = await agen.__anext__()
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass
        sql_blob = " ".join(session.executed_sqls)
        assert "row_security" not in sql_blob

    @pytest.mark.asyncio
    async def test_finally_resets_role(self, mock_session_factory):
        """finally 必须 RESET ROLE 释放 tx_system_role（恢复到 app role）。"""
        agen = get_db_no_rls()
        session = await agen.__anext__()
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass
        sql_blob = " ".join(session.executed_sqls)
        assert "RESET ROLE" in sql_blob

    @pytest.mark.asyncio
    async def test_no_more_app_tenant_id_clear(self, mock_session_factory):
        """cutover 后不再清 app.tenant_id GUC（SET ROLE 模式不依赖该 GUC）。"""
        agen = get_db_no_rls()
        session = await agen.__anext__()
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass
        sql_blob = " ".join(session.executed_sqls)
        assert "set_config('app.tenant_id'" not in sql_blob

    @pytest.mark.asyncio
    async def test_commits_on_normal_path(self, mock_session_factory):
        """正常路径必须 commit。"""
        agen = get_db_no_rls()
        session = await agen.__anext__()
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass
        assert session.committed is True
        assert session.rolled_back is False


class TestExceptionHandling:
    """异常处理：rollback + finally 仍 RESET ROLE。"""

    @pytest.mark.asyncio
    async def test_exception_rollbacks(self, mock_session_factory):
        agen = get_db_no_rls()
        session = await agen.__anext__()
        try:
            await agen.athrow(RuntimeError("boom"))
        except RuntimeError:
            pass
        assert session.rolled_back, "异常路径必须 rollback"

    @pytest.mark.asyncio
    async def test_exception_still_resets_role(self, mock_session_factory):
        """异常路径 finally 仍必须 RESET ROLE（防止 session 被复用时持有 BYPASSRLS）。"""
        agen = get_db_no_rls()
        session = await agen.__anext__()
        try:
            await agen.athrow(RuntimeError("boom"))
        except RuntimeError:
            pass
        sql_blob = " ".join(session.executed_sqls)
        assert "RESET ROLE" in sql_blob


class TestNoEnvDependency:
    """cutover 完成后行为不依赖 env（不再有 RLS_USE_TX_SYSTEM_ROLE 切换）。"""

    @pytest.mark.asyncio
    async def test_behavior_independent_of_legacy_env(self, mock_session_factory):
        """即便 env 设了 RLS_USE_TX_SYSTEM_ROLE=false 也不应回退（env 已废弃）。"""
        import os

        with mock.patch.dict(
            os.environ, {"RLS_USE_TX_SYSTEM_ROLE": "false"}, clear=False
        ):
            agen = get_db_no_rls()
            session = await agen.__anext__()
            assert "SET LOCAL ROLE tx_system_role" in session.executed_sqls[0]
            try:
                await agen.__anext__()
            except StopAsyncIteration:
                pass


class TestSqlScriptsExist:
    """部署脚本存在性 + 关键 SQL 内容（确保 cutover 仍可重放）。"""

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
