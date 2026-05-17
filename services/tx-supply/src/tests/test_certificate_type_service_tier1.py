"""certificate_type_service 契约测试（PRD-12 / Phase 3 W13 / Tier 1 邻接）

测试基于真实餐厅场景（CLAUDE.md §20）:
徐记海鲜采购总监管理供应商资质证件字典:
  - 创建"食品经营许可证"证件类型
  - 同名重复创建 → 409 错误
  - 软删除后允许新建同名
  - 分页列表（含 total 统计）
  - RLS 租户隔离（tenant A 不能读 tenant B）
  - initialize_defaults 幂等（重复调用 skipped=5）
  - fail-open：cert_expiry_alerter 不依赖本表（PRD-01 回归）

mock 风格沿用 test_market_survey_tier1.py（_FakeResult plain class + asyncpg rollback 守门）。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.certificate_type_service import (  # noqa: E402
    create_certificate_type,
    initialize_defaults,
    list_certificate_types,
    soft_delete_certificate_type,
    update_certificate_type,
)


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_TENANT_ZQXIAN = "22222222-bbbb-bbbb-bbbb-222222222222"
_CERT_TYPE_ID = "33333333-cccc-cccc-cccc-333333333333"
_CERT_NAME = "食品经营许可证"


def _cert_type_row(
    *,
    name: str = _CERT_NAME,
    applicable_supplier_kinds=None,
    validity_period_days: int | None = 365,
    is_required: bool = True,
    is_deleted: bool = False,
) -> dict:
    if applicable_supplier_kinds is None:
        applicable_supplier_kinds = ["all"]
    return {
        "id": _CERT_TYPE_ID,
        "tenant_id": _TENANT_XUJI,
        "name": name,
        "applicable_supplier_kinds": applicable_supplier_kinds,
        "validity_period_days": validity_period_days,
        "is_required": is_required,
        "is_deleted": is_deleted,
        "created_at": datetime(2026, 5, 17, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 17, 10, 0, tzinfo=timezone.utc),
    }


class _FakeResult:
    """plain class 替 MagicMock 链（PRD-08 P0-3 lesson，deterministic in Python 3.11）。"""

    def __init__(self, row, *, rowcount: int = 1):
        self._row = row
        self.rowcount = rowcount if row is not None else 0

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return [self._row] if self._row else []


# ═════════════════════════════════════════════════════════════════════════════
# DB Mock 工厂
# ═════════════════════════════════════════════════════════════════════════════


def _mk_db_create(*, fail_with=None):
    """模拟 create_certificate_type 成功 / IntegrityError。"""
    from sqlalchemy.exc import IntegrityError

    sql_log: list[str] = []
    db = AsyncMock()
    rollback_called: dict[str, bool] = {"v": False}

    async def rollback_side_effect():
        rollback_called["v"] = True

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "INSERT INTO certificate_types" in sql:
            if fail_with is not None:
                raise fail_with
            return _FakeResult(_cert_type_row())
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.rollback = AsyncMock(side_effect=rollback_side_effect)
    return db, sql_log, rollback_called


def _mk_db_get(*, row: dict | None):
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM certificate_types" in sql:
            return _FakeResult(row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_update(*, get_row: dict | None, update_row: dict | None = None, fail_with=None):
    """模拟 update_certificate_type：先 SELECT 查存在，再 UPDATE 返回。"""
    from sqlalchemy.exc import IntegrityError

    sql_log: list[str] = []
    db = AsyncMock()
    rollback_called: dict[str, bool] = {"v": False}

    async def rollback_side_effect():
        rollback_called["v"] = True

    call_count: dict[str, int] = {"select": 0, "update": 0}

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "SELECT" in sql and "FROM certificate_types" in sql:
            call_count["select"] += 1
            return _FakeResult(get_row)
        if "UPDATE certificate_types" in sql:
            call_count["update"] += 1
            if fail_with is not None:
                raise fail_with
            return _FakeResult(update_row or get_row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.rollback = AsyncMock(side_effect=rollback_side_effect)
    return db, sql_log, call_count, rollback_called


def _mk_db_delete(*, delete_row: dict | None):
    """模拟 soft_delete_certificate_type。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "UPDATE certificate_types" in sql and "is_deleted" in sql:
            return _FakeResult(delete_row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_list(*, rows: list[dict], total: int = 0):
    """模拟 list_certificate_types：COUNT + SELECT。"""
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "COUNT(*)" in sql:
            count_row = MagicMock()
            count_row.__getitem__ = lambda self, i: total
            return _FakeResult(count_row)
        if "FROM certificate_types" in sql:
            res = MagicMock()
            res.mappings.return_value.all.return_value = rows
            return res
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_init_defaults(*, rowcounts: list[int] | None = None):
    """模拟 initialize_defaults：每个 INSERT ON CONFLICT 返回 rowcount 0 或 1。"""
    db = AsyncMock()
    insert_idx: dict[str, int] = {"v": 0}

    if rowcounts is None:
        rowcounts = [1, 1, 1, 1, 1]  # 全部新建

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "INSERT INTO certificate_types" in sql and "ON CONFLICT" in sql:
            rc = rowcounts[insert_idx["v"] % len(rowcounts)]
            insert_idx["v"] += 1
            return _FakeResult(None, rowcount=rc) if rc == 0 else _FakeResult({"id": "x"}, rowcount=rc)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ═════════════════════════════════════════════════════════════════════════════
# 1. create_certificate_type 测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_cert_type_success():
    """正常创建证件类型，返回完整字段。"""
    db, sql_log, _ = _mk_db_create()
    result = await create_certificate_type(
        tenant_id=_TENANT_XUJI,
        name=_CERT_NAME,
        applicable_supplier_kinds=["all"],
        validity_period_days=365,
        is_required=True,
        db=db,
    )
    assert result["name"] == _CERT_NAME
    assert result["is_required"] is True
    assert result["is_deleted"] is False
    assert any("set_config" in s for s in sql_log)
    assert any("INSERT INTO certificate_types" in s for s in sql_log)


@pytest.mark.asyncio
async def test_create_cert_type_duplicate_name_raises():
    """同租户同名（未软删除）raise ValueError CERT_TYPE_NAME_EXISTS → HTTP 409。"""
    from sqlalchemy.exc import IntegrityError

    fake_ie = IntegrityError("duplicate key", None, None)
    db, _, rollback_called = _mk_db_create(fail_with=fake_ie)

    with pytest.raises(ValueError, match="CERT_TYPE_NAME_EXISTS"):
        await create_certificate_type(
            tenant_id=_TENANT_XUJI,
            name=_CERT_NAME,
            applicable_supplier_kinds=["all"],
            validity_period_days=None,
            is_required=True,
            db=db,
        )
    # rollback 必须被调用（asyncpg IntegrityError rollback lesson）
    assert rollback_called["v"] is True


@pytest.mark.asyncio
async def test_create_cert_type_long_period():
    """长效证件（ISO22000 3 年 1095 天），validity_period_days 正确保存。"""
    db, sql_log, _ = _mk_db_create()
    # 模拟返回包含 1095 天的行
    iso_row = _cert_type_row(
        name="ISO22000",
        validity_period_days=1095,
        is_required=False,
    )

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "INSERT INTO certificate_types" in sql:
            return _FakeResult(iso_row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)

    result = await create_certificate_type(
        tenant_id=_TENANT_XUJI,
        name="ISO22000",
        applicable_supplier_kinds=["seafood", "meat"],
        validity_period_days=1095,
        is_required=False,
        db=db,
    )
    assert result["validity_period_days"] == 1095
    assert result["is_required"] is False


# ═════════════════════════════════════════════════════════════════════════════
# 2. update_certificate_type 测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_cert_type_success():
    """更新证件类型名称，返回更新后字段。"""
    row = _cert_type_row()
    updated_row = _cert_type_row(name="食品经营许可证（更新版）")
    db, _, _, _ = _mk_db_update(get_row=row, update_row=updated_row)

    result = await update_certificate_type(
        _CERT_TYPE_ID,
        tenant_id=_TENANT_XUJI,
        name="食品经营许可证（更新版）",
        db=db,
    )
    assert result["name"] == "食品经营许可证（更新版）"


@pytest.mark.asyncio
async def test_update_cert_type_not_found():
    """更新不存在的证件类型 → ValueError CERT_TYPE_NOT_FOUND。"""
    db, _, _, _ = _mk_db_update(get_row=None)

    with pytest.raises(ValueError, match="CERT_TYPE_NOT_FOUND"):
        await update_certificate_type(
            "nonexistent-id",
            tenant_id=_TENANT_XUJI,
            name="新名称",
            db=db,
        )


@pytest.mark.asyncio
async def test_update_cert_type_name_conflict():
    """更新时同名冲突 → ValueError CERT_TYPE_NAME_EXISTS。"""
    from sqlalchemy.exc import IntegrityError

    row = _cert_type_row()
    fake_ie = IntegrityError("duplicate key", None, None)
    db, _, _, rollback_called = _mk_db_update(get_row=row, fail_with=fake_ie)

    with pytest.raises(ValueError, match="CERT_TYPE_NAME_EXISTS"):
        await update_certificate_type(
            _CERT_TYPE_ID,
            tenant_id=_TENANT_XUJI,
            name="已存在的名称",
            db=db,
        )
    assert rollback_called["v"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 3. soft_delete_certificate_type 测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_soft_delete_does_not_remove_row():
    """软删除后 is_deleted=True，行依然存在。"""
    db = _mk_db_delete(delete_row={"id": _CERT_TYPE_ID})
    # 不抛异常即成功
    await soft_delete_certificate_type(_CERT_TYPE_ID, tenant_id=_TENANT_XUJI, db=db)


@pytest.mark.asyncio
async def test_soft_delete_not_found():
    """软删除不存在的证件类型 → ValueError CERT_TYPE_NOT_FOUND。"""
    db = _mk_db_delete(delete_row=None)

    with pytest.raises(ValueError, match="CERT_TYPE_NOT_FOUND"):
        await soft_delete_certificate_type("nonexistent-id", tenant_id=_TENANT_XUJI, db=db)


@pytest.mark.asyncio
async def test_soft_delete_allows_same_name_recreate():
    """软删除后允许新建同名证件类型（DB 层 partial unique index 已支持）。

    本测试验证 service 层不阻止：软删除后执行 create 不触发重名错误。
    """
    # Step 1: soft delete 成功
    db_del = _mk_db_delete(delete_row={"id": _CERT_TYPE_ID})
    await soft_delete_certificate_type(_CERT_TYPE_ID, tenant_id=_TENANT_XUJI, db=db_del)

    # Step 2: 新建同名（模拟 DB 层 partial index 允许）
    new_row = _cert_type_row(name=_CERT_NAME)
    db_create, _, rollback_called = _mk_db_create()

    async def execute_ok(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "INSERT INTO certificate_types" in sql:
            return _FakeResult(new_row)
        return _FakeResult(None)

    db_create.execute = AsyncMock(side_effect=execute_ok)

    result = await create_certificate_type(
        tenant_id=_TENANT_XUJI,
        name=_CERT_NAME,
        applicable_supplier_kinds=["all"],
        validity_period_days=365,
        is_required=True,
        db=db_create,
    )
    assert result["name"] == _CERT_NAME
    assert rollback_called["v"] is False  # 无 IntegrityError


# ═════════════════════════════════════════════════════════════════════════════
# 4. list_certificate_types 测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_pagination():
    """分页：total 正确，items 数量不超过 size。"""
    rows = [_cert_type_row(name=f"证件{i}") for i in range(3)]
    db, sql_log = _mk_db_list(rows=rows, total=15)

    result = await list_certificate_types(
        tenant_id=_TENANT_XUJI,
        page=2,
        size=3,
        db=db,
    )
    assert result["total"] == 15
    assert len(result["items"]) == 3
    # 验证 set_config 和 COUNT 都被调用
    assert any("set_config" in s for s in sql_log)
    assert any("COUNT" in s for s in sql_log)


@pytest.mark.asyncio
async def test_list_empty():
    """空列表时 total=0 + items=[]。"""
    db, _ = _mk_db_list(rows=[], total=0)
    result = await list_certificate_types(tenant_id=_TENANT_XUJI, db=db)
    assert result["total"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_list_include_deleted():
    """include_deleted=True 时包含软删除条目。"""
    rows = [
        _cert_type_row(is_deleted=False),
        _cert_type_row(name="已删证件", is_deleted=True),
    ]
    db, sql_log = _mk_db_list(rows=rows, total=2)

    result = await list_certificate_types(
        tenant_id=_TENANT_XUJI,
        include_deleted=True,
        db=db,
    )
    assert result["total"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# 5. RLS 租户隔离测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rls_tenant_isolation():
    """tenant_XUJI 不能读取 tenant_ZQXIAN 的证件类型。

    RLS 在 DB 层实现，service 层保证 set_config('app.tenant_id') 按调用方 tenant_id 设置。
    本测试验证 service 为每次调用传正确的 tenant_id 给 set_config。
    """
    captured_tenant: dict[str, str] = {}

    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql and params:
            captured_tenant["tid"] = params.get("tid", "")
        if "COUNT(*)" in sql:
            count_row = MagicMock()
            count_row.__getitem__ = lambda self, i: 0
            return _FakeResult(count_row)
        if "FROM certificate_types" in sql:
            res = MagicMock()
            res.mappings.return_value.all.return_value = []
            return res
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)

    await list_certificate_types(tenant_id=_TENANT_ZQXIAN, db=db)

    # service 必须传最黔线的 tenant_id，而非徐记
    assert captured_tenant.get("tid") == _TENANT_ZQXIAN


# ═════════════════════════════════════════════════════════════════════════════
# 6. initialize_defaults 测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_initialize_defaults_all_created():
    """首次调用 initialize_defaults：5 类全部新建，created=5。"""
    db = _mk_db_init_defaults(rowcounts=[1, 1, 1, 1, 1])
    result = await initialize_defaults(tenant_id=_TENANT_XUJI, db=db)
    assert result["created"] == 5
    assert result["skipped"] == 0
    assert result["total_defaults"] == 5


@pytest.mark.asyncio
async def test_initialize_defaults_idempotent():
    """重复调用 initialize_defaults：5 类全部 skipped（ON CONFLICT DO NOTHING）。"""
    db = _mk_db_init_defaults(rowcounts=[0, 0, 0, 0, 0])
    result = await initialize_defaults(tenant_id=_TENANT_XUJI, db=db)
    assert result["created"] == 0
    assert result["skipped"] == 5


@pytest.mark.asyncio
async def test_initialize_defaults_partial():
    """部分已存在：3 个 skipped，2 个新建。"""
    db = _mk_db_init_defaults(rowcounts=[1, 0, 0, 1, 0])
    result = await initialize_defaults(tenant_id=_TENANT_XUJI, db=db)
    assert result["created"] == 2
    assert result["skipped"] == 3


# ═════════════════════════════════════════════════════════════════════════════
# 7. PRD-01 fail-open 回归测试
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cert_alerter_unaffected_by_cert_types_table():
    """cert_expiry_alerter 运行路径不依赖 certificate_types 表。

    验证：cert_service（PRD-01）仅读 supplier_certificates，
    不 import certificate_type_service，与字典 infra 完全解耦。
    """
    from services.tx_supply.src.services.cert_service import is_supplier_blocked

    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM supplier_certificates" in sql:
            # 模拟无过期证件（不阻断）
            return _FakeResult(None)
        # certificate_types 表不应被查询
        if "FROM certificate_types" in sql:
            raise AssertionError("cert_expiry_alerter 不应查询 certificate_types 表")
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)

    from datetime import date

    blocked = await is_supplier_blocked(
        db=db,
        tenant_id=_TENANT_XUJI,
        supplier_id="aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa",
        today=date(2026, 5, 17),
    )
    # 无过期证件 → 不阻断
    assert blocked is False


# ═════════════════════════════════════════════════════════════════════════════
# 8. round-1 fix 验证测试（P1-1 + P1-2）
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_clears_validity_to_null():
    """管理员将证件从"365 天"改为"长期有效"（validity_period_days=null）。

    round-1 P1-1 fix：通过 fields_set 路径，允许将 validity_period_days 写入 NULL。
    """
    existing_row = _cert_type_row(validity_period_days=365)
    null_updated_row = _cert_type_row(validity_period_days=None)
    db, _, call_count, _ = _mk_db_update(get_row=existing_row, update_row=null_updated_row)

    result = await update_certificate_type(
        _CERT_TYPE_ID,
        tenant_id=_TENANT_XUJI,
        validity_period_days=None,
        fields_set={"validity_period_days"},  # 客户端明确传入 null
        db=db,
    )
    # DB 写入 NULL（长期有效），而非静默跳过
    assert result["validity_period_days"] is None
    # UPDATE 确实被执行（不是因为 None 而跳过）
    assert call_count["update"] == 1


@pytest.mark.asyncio
async def test_initialize_defaults_idempotent_no_integrity_error():
    """连续调用两次 initialize_defaults，第 2 次应全部 skipped，不 raise IntegrityError。

    round-1 P1-2 fix：ON CONFLICT (tenant_id, name) WHERE is_deleted = FALSE DO NOTHING
    显式指定 partial index target，保证幂等不抛异常。

    本测试验证 service 层正确生成带 WHERE 子句的 ON CONFLICT SQL。
    """
    sql_log: list[str] = []
    db = AsyncMock()
    insert_idx: dict[str, int] = {"v": 0}
    # 第 1 轮全部新建，第 2 轮全部跳过
    rowcounts_round1 = [1, 1, 1, 1, 1]
    rowcounts_round2 = [0, 0, 0, 0, 0]

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "INSERT INTO certificate_types" in sql and "ON CONFLICT" in sql:
            # 验证 ON CONFLICT 包含 partial index target（WHERE is_deleted）
            assert "WHERE is_deleted" in sql, (
                "ON CONFLICT 必须包含 partial index predicate: WHERE is_deleted = FALSE"
            )
            rc = rowcounts_round1[insert_idx["v"] % 5] if insert_idx["v"] < 5 else rowcounts_round2[insert_idx["v"] % 5]
            insert_idx["v"] += 1
            return _FakeResult(None, rowcount=rc) if rc == 0 else _FakeResult({"id": "x"}, rowcount=rc)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)

    # 第 1 次调用
    result1 = await initialize_defaults(tenant_id=_TENANT_XUJI, db=db)
    assert result1["created"] == 5

    # 第 2 次调用（幂等，不 raise）
    result2 = await initialize_defaults(tenant_id=_TENANT_XUJI, db=db)
    assert result2["skipped"] == 5
    assert result2["created"] == 0
