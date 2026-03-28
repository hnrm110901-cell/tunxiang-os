"""Alembic env.py — 支持 asyncpg 运行时 + psycopg2 迁移"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from shared.ontology.src.base import TenantBase

# Import all models so TenantBase.metadata discovers them for autogenerate
from shared.ontology.src.entities import *  # noqa: F401, F403

# tx-trade domain models (also inherit TenantBase, must be imported for autogenerate)
# Directory is "tx-trade" (hyphen), so we add it to sys.path for import resolution.
import sys as _sys
from pathlib import Path as _Path

_tx_trade_src = str(_Path(__file__).resolve().parent.parent.parent / "services" / "tx-trade" / "src")
if _tx_trade_src not in _sys.path:
    _sys.path.insert(0, _tx_trade_src)

try:
    from models.reservation import Reservation, NoShowRecord  # noqa: F401
    from models.queue import QueueEntry, QueueCounter  # noqa: F401
    from models.delivery_order import DeliveryOrder  # noqa: F401
    from models.production_dept import ProductionDept, DishDeptMapping  # noqa: F401
    from models.payment import Payment, Refund  # noqa: F401
    from models.tables import Table  # noqa: F401
    from models.settlement import Settlement, ShiftHandover  # noqa: F401
    from models.receipt import ReceiptTemplate, ReceiptLog  # noqa: F401
except ImportError:
    pass  # Models not available; autogenerate will miss tx-trade tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = TenantBase.metadata

# 运行时用 asyncpg，迁移用 psycopg2（同步）
db_url = os.getenv(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url", "postgresql://tunxiang:changeme_dev@localhost/tunxiang_os"),
)
if db_url.startswith("postgresql+asyncpg://"):
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def run_migrations_offline() -> None:
    context.configure(url=db_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
