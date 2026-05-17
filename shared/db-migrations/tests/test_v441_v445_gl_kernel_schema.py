"""[GL 内核 W3 P0 #756] v441-v445 GL 4 表 + cost_center_dictionary 结构测试

round-1 §19 5 P0 + 5 P1 + 3 long-term P1 fix 的回归测试集。

覆盖范围：
  A. 静态扫描（不连 PG）：
     1. revision chain v440 → v441 → v442 → v443 → v444 → v445 单 head
     2. v441/v442/v443/v444/v445 RLS 四联 + NULLIF::uuid 模式（v139 对齐）
     3. v443 business_event 复合 FK 到 v147 events (event_id, occurred_at)
     4. v441 status / period_type 双向 CHECK 一致性
     5. v443 status 三态 + reverse_consistency CHECK
     6. v442 contra_asset / contra_revenue ENUM 扩展
     7. v442 parent_code != account_code 防自闭环
     8. v441 复合 UNIQUE (tenant_id, id)，v443 同
     9. v444 entry_id 改 composite FK (tenant_id, entry_id) → journal_entry
     10. v445 cost_center_dictionary 三分类 + parent 防自闭环

  B. 真 PG 反测（opt-in via INTEGRATION_PG_DSN）：
     - test_real_pg_apply_all_five_clean
     - test_real_pg_balanced_entry_double_zero_rejected
     - test_real_pg_balanced_entry_double_positive_rejected
     - test_real_pg_status_double_direction
     - test_real_pg_status_reversed_requires_reverse_of
     - test_real_pg_parent_code_no_self_loop_coa
     - test_real_pg_parent_code_no_self_loop_ccd
     - test_real_pg_cross_tenant_fk_je_posting_period
     - test_real_pg_cross_tenant_fk_je_reverse_of
     - test_real_pg_cross_tenant_fk_jl_entry
     - test_real_pg_business_event_fk_rejects_random_uuid
     - test_real_pg_pp_period_type_consistency
     - test_real_pg_rls_null_setlocal_returns_empty
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text


_VERSIONS_DIR = Path(__file__).parent.parent / "versions"


def _read(name: str) -> str:
    return (_VERSIONS_DIR / f"{name}.py").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - revision chain
# ─────────────────────────────────────────────────────────────────


def test_v441_revision_chain():
    src = _read("v441_posting_period")
    assert 'revision: str = "v441_posting_period"' in src
    assert 'down_revision: Union[str, Sequence[str], None] = "v440_certificate_types"' in src


def test_v442_revision_chain():
    src = _read("v442_chart_of_accounts")
    assert 'revision: str = "v442_chart_of_accounts"' in src
    assert 'down_revision: Union[str, Sequence[str], None] = "v441_posting_period"' in src


def test_v443_revision_chain():
    src = _read("v443_journal_entry")
    assert 'revision: str = "v443_journal_entry"' in src
    assert 'down_revision: Union[str, Sequence[str], None] = "v442_chart_of_accounts"' in src


def test_v444_revision_chain():
    src = _read("v444_journal_line")
    assert 'revision: str = "v444_journal_line"' in src
    assert 'down_revision: Union[str, Sequence[str], None] = "v443_journal_entry"' in src


def test_v445_revision_chain():
    src = _read("v445_cost_center_dictionary")
    assert 'revision: str = "v445_cost_center_dictionary"' in src
    assert 'down_revision: Union[str, Sequence[str], None] = "v444_journal_line"' in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - RLS 四联 + NULLIF::uuid 模式（round-1 §19 critic P1-1 / security P1-2）
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,table",
    [
        ("v441_posting_period", "posting_period"),
        ("v442_chart_of_accounts", "chart_of_accounts"),
        ("v443_journal_entry", "journal_entry"),
        ("v444_journal_line", "journal_line"),
        ("v445_cost_center_dictionary", "cost_center_dictionary"),
    ],
)
def test_rls_quad_enable_force_policy_with_check(name, table):
    src = _read(name)
    assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in src, (
        f"{name} 缺 ENABLE ROW LEVEL SECURITY"
    )
    assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in src, (
        f"{name} 缺 FORCE ROW LEVEL SECURITY"
    )
    assert "CREATE POLICY" in src, f"{name} 缺 CREATE POLICY"
    assert "WITH CHECK" in src, f"{name} 缺 WITH CHECK"


@pytest.mark.parametrize(
    "name",
    [
        "v441_posting_period",
        "v442_chart_of_accounts",
        "v443_journal_entry",
        "v444_journal_line",
        "v445_cost_center_dictionary",
    ],
)
def test_rls_uses_nullif_uuid_pattern(name):
    """v139 安全语义：NULLIF(...,'')::uuid 防未 SET 时返回 NULL=NULL 行为。"""
    src = _read(name)
    pattern = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    assert pattern in src, (
        f"{name} POLICY 应用 v139 NULLIF::uuid 模式，实际未见 `{pattern}`"
    )


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - v443 business_event 复合 FK 到 events
# ─────────────────────────────────────────────────────────────────


def test_v443_has_business_event_occurred_at_column():
    """round-1 §19 critic P0-3 Q1=A: business_event 复合 FK 必须配新列。"""
    src = _read("v443_journal_entry")
    assert "business_event_occurred_at  TIMESTAMPTZ" in src, (
        "v443 缺 business_event_occurred_at 列"
    )


def test_v443_business_event_fk_composite_to_events():
    """round-1 §19 critic P0-3 Q1=A: 复合 FK → events (event_id, occurred_at)
    DEFERRABLE INITIALLY DEFERRED 让 W4 同事务先 emit_event 再写 je。
    """
    src = _read("v443_journal_entry")
    assert "FOREIGN KEY (business_event_id, business_event_occurred_at)" in src
    assert "REFERENCES events (event_id, occurred_at)" in src
    assert "DEFERRABLE INITIALLY DEFERRED" in src


def test_v443_business_event_pair_check():
    """两列必须同时 NULL 或同时 NOT NULL（防一半数据）。"""
    src = _read("v443_journal_entry")
    assert "chk_je_business_event_pair" in src
    assert "business_event_id IS NULL AND business_event_occurred_at IS NULL" in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - v441 status / period_type 双向 CHECK 一致性
# ─────────────────────────────────────────────────────────────────


def test_v441_status_consistency_three_directions():
    """round-1 §19 P1-5: 双向 CHECK 防 status='open' AND closed_at=NOW() 反例。"""
    src = _read("v441_posting_period")
    assert "chk_pp_status_consistency" in src
    assert "status = 'open' AND closed_at IS NULL AND locked_at IS NULL" in src
    assert "status = 'closed' AND closed_at IS NOT NULL AND locked_at IS NULL" in src
    assert "status = 'locked' AND closed_at IS NOT NULL AND locked_at IS NOT NULL" in src


def test_v441_period_type_consistency():
    """round-1 §19 critic P1-3: monthly/daily/special 三态 + 与 period_date 一致性。"""
    src = _read("v441_posting_period")
    assert "chk_posting_period_period_type" in src
    assert "period_type IN ('monthly', 'daily', 'special')" in src
    assert "chk_pp_period_type_consistency" in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - v443 status 三态 + reverse_consistency
# ─────────────────────────────────────────────────────────────────


def test_v443_status_consistency_three_directions():
    src = _read("v443_journal_entry")
    assert "chk_je_status_consistency" in src
    assert "status = 'draft' AND posted_at IS NULL" in src
    assert "status = 'posted' AND posted_at IS NOT NULL" in src
    assert "status = 'reversed' AND posted_at IS NOT NULL" in src
    assert "reverse_of_entry_id IS NOT NULL" in src


def test_v443_reversed_implies_reverse_of():
    """round-1 §19 security #17: status='reversed' ⇔ reverse_of_entry_id NOT NULL。"""
    src = _read("v443_journal_entry")
    assert "chk_je_reverse_consistency" in src
    assert "status != 'reversed' OR reverse_of_entry_id IS NOT NULL" in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - v442 ENUM 扩展 + parent 自闭环
# ─────────────────────────────────────────────────────────────────


def test_v442_account_type_has_contra():
    """round-1 §19 critic P1-4: ENUM 扩展 contra_asset / contra_revenue。"""
    src = _read("v442_chart_of_accounts")
    assert "'contra_asset'" in src
    assert "'contra_revenue'" in src
    # 原 5 类不退化
    for t in ("'asset'", "'liability'", "'equity'", "'revenue'", "'expense'"):
        assert t in src, f"v442 account_type 缺 {t}"


def test_v442_parent_code_no_self_loop():
    """round-1 §19 security P1-4 部分: parent_code != account_code。"""
    src = _read("v442_chart_of_accounts")
    assert "chk_coa_no_self_parent" in src
    assert "parent_code IS NULL OR parent_code != account_code" in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - 复合 UNIQUE 让 composite FK 成立
# ─────────────────────────────────────────────────────────────────


def test_v441_has_composite_unique_tenant_id():
    """round-1 §19 security P0-1: UNIQUE (tenant_id, id) 让 je composite FK 成立。"""
    src = _read("v441_posting_period")
    assert "uq_posting_period_tenant_id" in src
    assert "UNIQUE (tenant_id, id)" in src


def test_v443_has_composite_unique_tenant_id():
    """round-1 §19 security P0-2 + P1-1: UNIQUE (tenant_id, id) 让 reverse_of + jl FK 成立。"""
    src = _read("v443_journal_entry")
    assert "uq_journal_entry_tenant_id" in src
    assert "UNIQUE (tenant_id, id)" in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - 跨 PR FK 全 composite
# ─────────────────────────────────────────────────────────────────


def test_v443_fk_posting_period_composite():
    """round-1 §19 security P0-1: posting_period FK 改 composite。"""
    src = _read("v443_journal_entry")
    assert "FOREIGN KEY (tenant_id, posting_period_id)" in src
    assert "REFERENCES posting_period (tenant_id, id)" in src


def test_v443_fk_reverse_of_composite():
    """round-1 §19 security P0-2: reverse_of_entry_id 自引用 FK 改 composite。"""
    src = _read("v443_journal_entry")
    assert "FOREIGN KEY (tenant_id, reverse_of_entry_id)" in src
    assert "REFERENCES journal_entry (tenant_id, id)" in src


def test_v444_fk_entry_composite():
    """round-1 §19 security P1-1: journal_line.entry_id FK 改 composite。"""
    src = _read("v444_journal_line")
    assert "FOREIGN KEY (tenant_id, entry_id)" in src
    assert "REFERENCES journal_entry (tenant_id, id)" in src


# ─────────────────────────────────────────────────────────────────
# A. 静态扫描 - v445 cost_center_dictionary
# ─────────────────────────────────────────────────────────────────


def test_v445_three_types():
    src = _read("v445_cost_center_dictionary")
    assert "chk_ccd_cost_center_type" in src
    assert "'line_of_business'" in src
    assert "'store'" in src
    assert "'department'" in src


def test_v445_parent_no_self_loop():
    src = _read("v445_cost_center_dictionary")
    assert "chk_ccd_no_self_parent" in src
    assert "parent_code IS NULL OR parent_code != cost_center_code" in src


# ─────────────────────────────────────────────────────────────────
# B. 真 PG 反测（opt-in via INTEGRATION_PG_DSN，fixture 见 conftest.py）
# ─────────────────────────────────────────────────────────────────
#
# 共用 fixture：
#   - integration_pg_session  事务隔离 session（teardown 自动 rollback）
#   - set_tenant_guc          设 app.tenant_id GUC（事务级）
#
# 未配置 DSN 时 fixture 自身 pytest.skip — 不污染 default 测试套件。
#
# 注意：integration_pg_session fixture 仅 GRANT channel-aggregation 三表。
# 本测试集需要 GL 5 表的 GRANT；conftest fixture 不支持，故下方测试改用
# session-level engine 直连（不走 RLS_TEST_ROLE，仅做约束/CHECK/FK 验证）。
# RLS 隔离测试用 SET LOCAL app.tenant_id GUC 即可（FORCE ROW LEVEL SECURITY
# 让 superuser 也受策略约束）。


# 真 PG 反测专用 fixture — 不复用 channel-aggregation 三表 GRANT 模式
import os
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


_DSN = os.getenv("INTEGRATION_PG_DSN")
_RUN_REAL_PG = bool(_DSN)


def _to_async_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


@pytest_asyncio.fixture
async def gl_pg_session():
    """真 PG session — 每 test 独立事务 rollback 隔离。

    不 GRANT 给 RLS_TEST_ROLE（superuser 仍受 FORCE ROW LEVEL SECURITY 约束）。
    """
    if not _DSN:
        pytest.skip("INTEGRATION_PG_DSN 未配置")
    engine = create_async_engine(_to_async_dsn(_DSN), pool_pre_ping=True, pool_size=1)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                await trans.rollback()
    finally:
        await engine.dispose()


async def _set_tenant(session, tenant_id):
    await session.execute(
        text(f"SET LOCAL app.tenant_id = '{tenant_id}'")
    )


async def _insert_posting_period(session, tenant_id, year_month="2026-05", period_type="monthly", period_date=None):
    """返回新建 posting_period.id"""
    result = await session.execute(
        text("""
            INSERT INTO posting_period (tenant_id, year_month, period_type, period_date)
            VALUES (:tid, :ym, :pt, :pd)
            RETURNING id
        """),
        {"tid": str(tenant_id), "ym": year_month, "pt": period_type, "pd": period_date},
    )
    return result.scalar_one()


async def _insert_coa(session, tenant_id, code="1001", name="现金", account_type="asset"):
    result = await session.execute(
        text("""
            INSERT INTO chart_of_accounts (tenant_id, account_code, account_name, account_type)
            VALUES (:tid, :code, :name, :at)
            RETURNING id
        """),
        {"tid": str(tenant_id), "code": code, "name": name, "at": account_type},
    )
    return result.scalar_one()


async def _insert_je(session, tenant_id, pp_id, entry_no="JE-001", source_service="test", **extra):
    cols = ["tenant_id", "posting_period_id", "entry_no", "source_service"]
    vals = {"tid": str(tenant_id), "pp_id": str(pp_id), "en": entry_no, "ss": source_service}
    placeholders = [":tid", ":pp_id", ":en", ":ss"]
    for k, v in extra.items():
        cols.append(k)
        placeholders.append(f":{k}")
        vals[k] = v
    sql = f"""
        INSERT INTO journal_entry ({', '.join(cols)})
        VALUES ({', '.join(placeholders)})
        RETURNING id
    """
    result = await session.execute(text(sql), vals)
    return result.scalar_one()


# ----- 真 PG 反测 -----


async def test_real_pg_apply_all_five_clean(gl_pg_session):
    """5 张表 + 索引都已 apply（前提：本 fixture 连的 DB 已 upgrade）。"""
    session = gl_pg_session
    result = await session.execute(text(
        "SELECT relname FROM pg_class "
        "WHERE relname IN ('posting_period','chart_of_accounts','journal_entry',"
        "'journal_line','cost_center_dictionary') ORDER BY relname"
    ))
    rows = [r[0] for r in result.fetchall()]
    assert rows == [
        "chart_of_accounts", "cost_center_dictionary",
        "journal_entry", "journal_line", "posting_period",
    ], f"5 张表应全部存在，实际：{rows}"


async def test_real_pg_all_tables_rls_forced(gl_pg_session):
    """全部 5 表 RLS ENABLED + FORCED。"""
    session = gl_pg_session
    result = await session.execute(text(
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname IN ('posting_period','chart_of_accounts','journal_entry',"
        "'journal_line','cost_center_dictionary') ORDER BY relname"
    ))
    for relname, rls, force in result.fetchall():
        assert rls is True, f"{relname} 未 ENABLE RLS"
        assert force is True, f"{relname} 未 FORCE RLS（feedback_rls_force.md）"


async def test_real_pg_balanced_entry_double_zero_rejected(gl_pg_session):
    """journal_line debit=0 credit=0 必须被 CHECK 拒绝（双零空行）。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    pp_id = await _insert_posting_period(session, tenant)
    await _insert_coa(session, tenant)
    je_id = await _insert_je(session, tenant, pp_id)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO journal_line (tenant_id, entry_id, line_no, account_code, debit_fen, credit_fen)
            VALUES (:tid, :eid, 1, '1001', 0, 0)
        """), {"tid": str(tenant), "eid": str(je_id)})
    assert "chk_jl_amounts_exclusive" in str(exc.value).lower() or "check" in str(exc.value).lower()


async def test_real_pg_balanced_entry_double_positive_rejected(gl_pg_session):
    """journal_line debit=100 credit=100 必须被 CHECK 拒绝（不允许双边）。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    pp_id = await _insert_posting_period(session, tenant)
    await _insert_coa(session, tenant)
    je_id = await _insert_je(session, tenant, pp_id)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO journal_line (tenant_id, entry_id, line_no, account_code, debit_fen, credit_fen)
            VALUES (:tid, :eid, 1, '1001', 100, 100)
        """), {"tid": str(tenant), "eid": str(je_id)})
    assert "check" in str(exc.value).lower()


async def test_real_pg_status_double_direction_open_with_closed_at(gl_pg_session):
    """round-1 §19 P1-5: UPDATE status='open' AND closed_at=NOW() → CHECK reject。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    pp_id = await _insert_posting_period(session, tenant)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            UPDATE posting_period
            SET status = 'open', closed_at = NOW()
            WHERE id = :pp_id
        """), {"pp_id": str(pp_id)})
    assert "chk_pp_status_consistency" in str(exc.value).lower() or "check" in str(exc.value).lower()


async def test_real_pg_status_reversed_requires_reverse_of(gl_pg_session):
    """round-1 §19 security #17: status='reversed' AND reverse_of_entry_id=NULL → CHECK reject。"""
    from datetime import datetime, timezone
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    pp_id = await _insert_posting_period(session, tenant)
    posted_at = datetime.now(timezone.utc)
    with pytest.raises(Exception) as exc:
        await _insert_je(
            session, tenant, pp_id,
            entry_no="JE-R", status="reversed", posted_at=posted_at,
        )
    msg = str(exc.value).lower()
    assert "chk_je_reverse_consistency" in msg or "chk_je_status_consistency" in msg or "check" in msg


async def test_real_pg_coa_parent_no_self_loop(gl_pg_session):
    """round-1 §19 security P1-4 部分: chart_of_accounts parent_code = account_code 拒绝。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO chart_of_accounts (tenant_id, account_code, account_name, parent_code, account_type)
            VALUES (:tid, '1001', '现金', '1001', 'asset')
        """), {"tid": str(tenant)})
    assert "chk_coa_no_self_parent" in str(exc.value).lower() or "check" in str(exc.value).lower()


async def test_real_pg_ccd_parent_no_self_loop(gl_pg_session):
    """v445 cost_center_dictionary parent_code = cost_center_code 拒绝。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO cost_center_dictionary
                (tenant_id, cost_center_code, cost_center_name, cost_center_type, parent_code)
            VALUES (:tid, 'STORE-001', '门店一', 'store', 'STORE-001')
        """), {"tid": str(tenant)})
    assert "chk_ccd_no_self_parent" in str(exc.value).lower() or "check" in str(exc.value).lower()


async def test_real_pg_cross_tenant_fk_je_posting_period(gl_pg_session):
    """round-1 §19 security P0-1: tenant_A je 引用 tenant_B 的 posting_period → FK reject。"""
    session = gl_pg_session
    tenant_a, tenant_b = uuid4(), uuid4()
    # tenant_b 写一个 posting_period
    await _set_tenant(session, tenant_b)
    pp_b = await _insert_posting_period(session, tenant_b, year_month="2026-05")
    # tenant_a 试图引用 pp_b — 应当被 composite FK 拒绝
    await _set_tenant(session, tenant_a)
    # 注意：RLS 让 tenant_a 看不到 pp_b，但即便 tenant_a 显式指 pp_b.id，composite FK
    # (tenant_a, pp_b) 找不到匹配（因为 pp_b 在 tenant_b 名下）
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO journal_entry
                (tenant_id, posting_period_id, entry_no, source_service)
            VALUES (:tid, :pp, 'JE-1', 'test')
        """), {"tid": str(tenant_a), "pp": str(pp_b)})
    assert "fk_je_posting_period" in str(exc.value).lower() or "foreign key" in str(exc.value).lower()


async def test_real_pg_cross_tenant_fk_je_reverse_of(gl_pg_session):
    """round-1 §19 security P0-2: tenant_A je.reverse_of 指 tenant_B 的 je → FK reject。"""
    session = gl_pg_session
    tenant_a, tenant_b = uuid4(), uuid4()
    # tenant_b 建 pp + je
    await _set_tenant(session, tenant_b)
    pp_b = await _insert_posting_period(session, tenant_b)
    je_b = await _insert_je(session, tenant_b, pp_b, entry_no="JE-B")
    # tenant_a 建 pp + je 同时设 reverse_of 指 je_b
    await _set_tenant(session, tenant_a)
    pp_a = await _insert_posting_period(session, tenant_a)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO journal_entry
                (tenant_id, posting_period_id, entry_no, source_service,
                 status, posted_at, reverse_of_entry_id)
            VALUES (:tid, :pp, 'JE-A', 'test', 'reversed', NOW(), :rev)
        """), {"tid": str(tenant_a), "pp": str(pp_a), "rev": str(je_b)})
    assert "fk_je_reverse_of" in str(exc.value).lower() or "foreign key" in str(exc.value).lower()


async def test_real_pg_cross_tenant_fk_jl_entry(gl_pg_session):
    """round-1 §19 security P1-1: tenant_A jl 挂 tenant_B 的 je → FK reject。"""
    session = gl_pg_session
    tenant_a, tenant_b = uuid4(), uuid4()
    # tenant_b 建完整 je + coa
    await _set_tenant(session, tenant_b)
    pp_b = await _insert_posting_period(session, tenant_b)
    je_b = await _insert_je(session, tenant_b, pp_b, entry_no="JE-B")
    # tenant_a 建 coa（必须有，否则会先撞 coa fk）
    await _set_tenant(session, tenant_a)
    await _insert_coa(session, tenant_a)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO journal_line
                (tenant_id, entry_id, line_no, account_code, debit_fen, credit_fen)
            VALUES (:tid, :eid, 1, '1001', 100, 0)
        """), {"tid": str(tenant_a), "eid": str(je_b)})
    assert "fk_jl_entry" in str(exc.value).lower() or "foreign key" in str(exc.value).lower()


async def test_real_pg_business_event_fk_rejects_random_uuid(gl_pg_session):
    """round-1 §19 critic P0-3 Q1=A: business_event_id 指随机 UUID + 当前时间 → FK reject。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    pp = await _insert_posting_period(session, tenant)
    # 用 IMMEDIATE 约束模式触发 FK 检查
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            SET CONSTRAINTS ALL IMMEDIATE
        """))
        await session.execute(text("""
            INSERT INTO journal_entry
                (tenant_id, posting_period_id, entry_no, source_service,
                 business_event_id, business_event_occurred_at)
            VALUES (:tid, :pp, 'JE-BE', 'test', :bid, NOW())
        """), {"tid": str(tenant), "pp": str(pp), "bid": str(uuid4())})
    assert "fk_je_business_event" in str(exc.value).lower() or "foreign key" in str(exc.value).lower()


async def test_real_pg_pp_period_type_consistency_daily_requires_date(gl_pg_session):
    """round-1 §19 critic P1-3: period_type='daily' AND period_date IS NULL → CHECK reject。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    with pytest.raises(Exception) as exc:
        await session.execute(text("""
            INSERT INTO posting_period (tenant_id, year_month, period_type, period_date)
            VALUES (:tid, '2026-05', 'daily', NULL)
        """), {"tid": str(tenant)})
    assert "chk_pp_period_type_consistency" in str(exc.value).lower() or "check" in str(exc.value).lower()


async def test_real_pg_rls_null_setlocal_returns_empty(gl_pg_session):
    """v139 NULLIF::uuid 模式：未 SET LOCAL app.tenant_id → SELECT 返 0 行（fail-closed）。

    本测试需要 non-superuser role（superuser 即便 FORCE ROW LEVEL SECURITY 也 bypass）。
    内联 GRANT + SET LOCAL ROLE — 不依赖 conftest fixture（fixture 只 GRANT
    channel-aggregation 三表，不含 GL 5 表）。
    """
    session = gl_pg_session
    # 内联 GRANT GL 5 表给 RLS test role（事务级 GRANT 走当前 superuser）
    rls_role = "tunxiang_rls_app"
    # 确保 role 存在（conftest fixture 创建过；这里 idempotent）
    await session.execute(text(f"""
        DO $do$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rls_role}') THEN
                CREATE ROLE {rls_role} NOINHERIT NOLOGIN;
            END IF;
        END $do$
    """))
    for tbl in ("posting_period", "chart_of_accounts", "journal_entry", "journal_line", "cost_center_dictionary"):
        await session.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO {rls_role}"))

    # 先以 superuser 写一行（绕 RLS）— 这一步是 fixture setup
    tenant_a = uuid4()
    await _set_tenant(session, tenant_a)
    pp_id = await _insert_posting_period(session, tenant_a)
    assert pp_id is not None

    # 切到 non-superuser role + 重置 app.tenant_id 到空串 → RLS 应返 0 行
    await session.execute(text(f"SET LOCAL ROLE {rls_role}"))
    await session.execute(text("SET LOCAL app.tenant_id = ''"))
    result = await session.execute(text("SELECT COUNT(*) FROM posting_period"))
    cnt = result.scalar_one()
    assert cnt == 0, f"未 SET LOCAL 时应 fail-closed 返 0 行，实际 {cnt}"

    # 再 SET 为 tenant_a，应见 1 行
    await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_a}'"))
    result = await session.execute(text("SELECT COUNT(*) FROM posting_period"))
    cnt = result.scalar_one()
    assert cnt == 1, f"SET tenant_a 时应见 1 行，实际 {cnt}"


async def test_real_pg_account_type_contra_accepted(gl_pg_session):
    """round-1 §19 critic P1-4: contra_asset / contra_revenue 必须可入。"""
    session = gl_pg_session
    tenant = uuid4()
    await _set_tenant(session, tenant)
    # accumulated_depreciation 累计折旧（contra_asset）
    await _insert_coa(session, tenant, code="1601-DEP", name="累计折旧", account_type="contra_asset")
    # sales_returns 销售退回（contra_revenue）
    await _insert_coa(session, tenant, code="6001-RET", name="销售退回", account_type="contra_revenue")
    # 验证两行确实写入
    result = await session.execute(text(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE account_type LIKE 'contra%'"
    ))
    assert result.scalar_one() == 2
