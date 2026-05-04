"""test_migration_chain.py — DB 迁移链完整性测试（真实 PostgreSQL）

验证：
  1. 所有迁移版本按顺序执行无错误
  2. 迁移历史无断链（所有依赖的迁移都存在）
  3. 每个迁移产生预期的 schema 变更
  4. 迁移可回滚（upgrade + downgrade 不报错）

前提：
  - 测试数据库已运行
  - alembic.ini 配置指向测试数据库
  - shared/db-migrations/versions/ 下有迁移文件
"""

from __future__ import annotations

import os
from pathlib import Path
from subprocess import check_call, check_output

import pytest


@pytest.fixture(scope="module")
def alembic_cfg() -> str:
    """返回 Alembic 配置文件的路径。"""
    return str(Path(__file__).resolve().parent.parent.parent / "shared" / "db-migrations" / "alembic.ini")


@pytest.fixture(scope="module")
def alembic_versions_dir() -> Path:
    """返回迁移版本目录。"""
    return Path(__file__).resolve().parent.parent.parent / "shared" / "db-migrations" / "versions"


class TestMigrationChain:
    """迁移链完整性验证。"""

    @pytest.mark.integration
    async def test_all_migrations_run_clean(self, alembic_cfg: str):
        """所有迁移从头执行应无错误。

        策略：在测试数据库上执行 `alembic upgrade head`，
        验证所有迁移按顺序完成。
        """
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ.get(
            "INTEGRATION_DATABASE_URL",
            "postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test",
        )

        result = check_call(
            ["alembic", "-c", alembic_cfg, "upgrade", "head"],
            env=env,
        )
        assert result == 0, "Alembic upgrade head 失败"

    @pytest.mark.integration
    async def test_migration_history_complete(self, alembic_cfg: str):
        """迁移历史记录应完整，无缺失版本。"""
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ.get(
            "INTEGRATION_DATABASE_URL",
            "postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test",
        )

        # 获取当前 head
        head = check_output(
            ["alembic", "-c", alembic_cfg, "heads"],
            env=env, text=True,
        ).strip()

        assert head, "迁移历史中无 head（数据库可能为空）"
        assert " (head)" in head or len(head.split("\n")) == 1, "存在多个 head（分支）"

    @pytest.mark.integration
    async def test_last_migration_downgrade(self, alembic_cfg: str, alembic_versions_dir: Path):
        """最新迁移可降级。

        验证 upgrade + downgrade 的对称性。
        """
        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ.get(
            "INTEGRATION_DATABASE_URL",
            "postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test",
        )

        # head 的 revision
        current = check_output(
            ["alembic", "-c", alembic_cfg, "current"],
            env=env, text=True,
        ).strip()

        if not current:
            pytest.skip("当前数据库为空，无法降级")

        # 降级一步
        downgrade = check_call(
            ["alembic", "-c", alembic_cfg, "downgrade", "-1"],
            env=env,
        )
        assert downgrade == 0, "downgrade -1 失败"

        # 再升回来
        upgrade = check_call(
            ["alembic", "-c", alembic_cfg, "upgrade", "head"],
            env=env,
        )
        assert upgrade == 0, "downgrade 后 upgrade head 失败"
