"""Per-service alembic env.py.

读取 alembic.ini 的 `version_table` 让 stamp 表 service-specific，互不冲突。
DATABASE_URL env var 优先，fallback alembic.ini sqlalchemy.url。
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# upgrade/downgrade 不需要 ORM metadata；service-specific autogenerate 留给后续 PR
target_metadata = MetaData()

db_url = os.getenv(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url", "postgresql://tunxiang:changeme_dev@localhost/tunxiang_os"),
)
if db_url.startswith("postgresql+asyncpg://"):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

# 关键：从 alembic.ini 读 version_table；service-specific
# 必须显式声明 version_table — 无 fallback 避免静默回落到 alembic 全局默认表
# 与其他 service 或老 mono-repo 共享 PG 时撞 stamp
version_table = config.get_main_option('version_table')
if not version_table:
    raise RuntimeError(
        'alembic.ini 缺少 version_table 配置。per-service alembic 必须显式声明 '
        'version_table 防止多 alembic 共享 PG 时 stamp 冲突。'
    )


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table=version_table,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
            version_table=version_table,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
