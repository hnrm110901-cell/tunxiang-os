"""
法人主体服务 — 单元测试

覆盖：
  1) create_entity 成功
  2) bind_to_store：新绑定
  3) bind_to_store is_primary：旧主绑定会被 end_date 回填
  4) get_active_entity_for_store：有 / 无生效绑定
"""

import sys
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.legal_entity_service import LegalEntityService  # noqa: E402


def _mk_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_entity_defaults():
    db = _mk_db()
    entity = await LegalEntityService.create_entity(
        db,
        code="E001",
        name="屯象科技（长沙）有限公司",
    )
    assert entity.code == "E001"
    assert entity.entity_type.value == "direct_operated"
    db.add.assert_called_once()
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_bind_to_store_no_existing():
    db = _mk_db()

    class EmptyScalars:
        def scalars(self):
            class _S:
                def all(self_inner):
                    return []
            return _S()

    db.execute = AsyncMock(return_value=EmptyScalars())
    entity_id = uuid.uuid4()
    link = await LegalEntityService.bind_to_store(
        db,
        entity_id=entity_id,
        store_id="S001",
        start_date=date.today(),
    )
    assert link.store_id == "S001"
    assert link.legal_entity_id == entity_id
    assert link.is_primary is True


@pytest.mark.asyncio
async def test_bind_to_store_closes_previous_primary():
    db = _mk_db()

    # 模拟旧主绑定存在
    prev_link = MagicMock(end_date=None)

    class HasOld:
        def scalars(self):
            class _S:
                def all(self_inner):
                    return [prev_link]
            return _S()

    db.execute = AsyncMock(return_value=HasOld())

    start = date.today()
    await LegalEntityService.bind_to_store(
        db,
        entity_id=uuid.uuid4(),
        store_id="S001",
        start_date=start,
        is_primary=True,
    )
    # 旧绑定应被回填 end_date = start - 1
    assert prev_link.end_date == start - timedelta(days=1)


@pytest.mark.asyncio
async def test_get_active_entity_none():
    db = _mk_db()

    class NoRow:
        def first(self):
            return None

    db.execute = AsyncMock(return_value=NoRow())
    result = await LegalEntityService.get_active_entity_for_store(db, "S999")
    assert result is None
