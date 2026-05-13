"""Tier 1 行锁测试：tx-finance wine_storage_routes 2 mutation 路径必须含 FOR UPDATE

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.2 (tx-finance wine_storage 独立模块)
  - docs/security/tier1-row-lock-audit-2026-05.md §6.1 (wine_storage 双轨架构债)
  - PR #538 (audit), Issue #532 (parent), #535 (架构 follow-up)
  - PR-A of 6-PR fix roadmap

业务影响（audit doc §4.2）：
  - retrieve_wine (P0)：并发取酒读相同 quantity → 各扣 → 负库存（客户押金/物权）
  - extend_storage (P1)：并发续存读相同 expires_at → 重复收 fee + 日期错乱

⚠️ 此文件验证的是 tx-finance/src/api/wine_storage_routes.py（biz_wine_storage 表），
   与 tx-trade/src/api/wine_storage_routes.py（wine_storage_records 表）双轨并存.
   tx-trade 端 4 路由已加锁（PR #272 §19 修完），本 PR 修 tx-finance 端 2 路由.
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.elements import TextClause

# ── 路径 ───────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FINANCE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, FINANCE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── sys.modules stub 注入（与 services/tx-finance/src/tests/test_wine_storage.py 对齐）
# 原因：shared/events/src/event_base.py 用 @dataclass(slots=True) (Python 3.10+ 语法)，
# 本地 Python 3.9 仅可通过 stub 跑测；CI 3.11 不需要 stub 但兼容这套 stub。
def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db_with_tenant"):

    async def _placeholder_get_db_with_tenant(tenant_id: str):
        yield None

    _db_mod.get_db_with_tenant = _placeholder_get_db_with_tenant

_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")
if not hasattr(_ev_types, "WineStorageEventType"):

    class _FakeWineStorageEventType:
        STORED = "wine.stored"
        RETRIEVED = "wine.retrieved"
        EXTENDED = "wine.extended"
        EXPIRED = "wine.expired"

    _ev_types.WineStorageEventType = _FakeWineStorageEventType

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _sl

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.ModuleType("asyncpg")


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORAGE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OPERATOR_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CUSTOMER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
STORE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _text_sql(stmt) -> str:
    """从 SQLAlchemy TextClause 取出 SQL 字符串。"""
    if isinstance(stmt, TextClause):
        return stmt.text
    return str(stmt)


def _build_db_with_select_returning(select_row, update_row):
    """构造 AsyncSession mock，capture 所有 execute SQL，第一个 SELECT 返回 select_row，
    后续 UPDATE/INSERT 返回 update_row。"""
    captured_sqls = []

    async def mock_execute(stmt, params=None):
        sql = _text_sql(stmt)
        captured_sqls.append(sql)
        result = MagicMock()
        sql_upper = sql.upper().strip()
        if sql_upper.startswith("SELECT") or "SELECT " in sql_upper[:20]:
            mappings_obj = MagicMock()
            mappings_obj.first = MagicMock(return_value=select_row)
            result.mappings = MagicMock(return_value=mappings_obj)
        else:
            mappings_obj = MagicMock()
            mappings_obj.first = MagicMock(return_value=update_row)
            result.mappings = MagicMock(return_value=mappings_obj)
        return result

    db = AsyncMock()
    db.execute = mock_execute
    db.commit = AsyncMock()
    return db, captured_sqls


class TestWineStorageRowLockTier1:
    """tx-finance wine_storage_routes 2 mutation 路径必须含 FOR UPDATE.

    与 tx-trade 端 take_wine/extend/transfer/write_off 4 路由模式对齐
    （PR #272 §19 reviewer 已修完 tx-trade 端）.
    """

    @pytest.mark.asyncio
    async def test_retrieve_wine_select_contains_for_update(self):
        """retrieve_wine 内 SELECT biz_wine_storage 必须 FOR UPDATE.

        Race 场景（audit doc §4.2 P0）：
          两路并发取酒读相同 quantity=5, body.quantity=3, 各自通过校验
          → 各 UPDATE quantity=2 → 最终库存 = -1（客户押金/物权风险）.
        """
        from services.tx_finance.src.api.wine_storage_routes import (
            WineRetrieveRequest,
            retrieve_wine,
        )

        select_row = {
            "id": STORAGE_ID,
            "quantity": 5.0,
            "status": "stored",
            "customer_id": CUSTOMER_ID,
            "wine_name": "茅台",
            "store_id": str(STORE_ID),
        }
        update_row = {"id": STORAGE_ID, "quantity": 2.0, "status": "partially_retrieved"}
        db, captured = _build_db_with_select_returning(select_row, update_row)

        body = WineRetrieveRequest(quantity=3.0, related_order_id=None, remark="test 取酒")

        await retrieve_wine(
            storage_id=str(STORAGE_ID),
            body=body,
            x_tenant_id=str(TENANT_ID),
            x_operator_id=str(OPERATOR_ID),
            db=db,
        )

        # 第一条必须是 SELECT biz_wine_storage
        assert captured, "retrieve_wine 必须 execute 至少一条 SQL"
        first_sql = captured[0]
        assert "SELECT" in first_sql.upper() and "biz_wine_storage" in first_sql.lower(), (
            f"第一条必须是 SELECT biz_wine_storage，got: {first_sql[:200]}"
        )
        assert "FOR UPDATE" in first_sql.upper(), (
            f"retrieve_wine SELECT 必须含 FOR UPDATE — "
            f"audit doc §4.2 P0 客户押金/物权风险（并发超取）。SQL:\n{first_sql}"
        )

    @pytest.mark.asyncio
    async def test_extend_storage_select_contains_for_update(self):
        """extend_storage 内 SELECT biz_wine_storage 必须 FOR UPDATE.

        Race 场景（audit doc §4.2 P1）：
          两路并发续存读相同 old expires_at → 各算 new_expires = old + delta
          → 都写相同 new_expires → 少续一次（应该叠加）+ fee 重复收取.
        """
        from services.tx_finance.src.api.wine_storage_routes import (
            WineExtendRequest,
            extend_storage,
        )

        select_row = {
            "id": STORAGE_ID,
            "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
            "status": "stored",
        }
        update_row = {
            "id": STORAGE_ID,
            "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc) + timedelta(days=30),
            "status": "stored",
        }
        db, captured = _build_db_with_select_returning(select_row, update_row)

        body = WineExtendRequest(extend_days=30, remark="续存 30 天")

        await extend_storage(
            storage_id=str(STORAGE_ID),
            body=body,
            x_tenant_id=str(TENANT_ID),
            x_operator_id=str(OPERATOR_ID),
            db=db,
        )

        assert captured, "extend_storage 必须 execute 至少一条 SQL"
        first_sql = captured[0]
        assert "SELECT" in first_sql.upper() and "biz_wine_storage" in first_sql.lower(), (
            f"第一条必须是 SELECT biz_wine_storage，got: {first_sql[:200]}"
        )
        assert "FOR UPDATE" in first_sql.upper(), (
            f"extend_storage SELECT 必须含 FOR UPDATE — "
            f"audit doc §4.2 P1 押金 race（重复续存 fee）。SQL:\n{first_sql}"
        )
