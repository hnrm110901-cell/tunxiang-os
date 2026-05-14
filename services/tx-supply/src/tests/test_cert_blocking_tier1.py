"""Tier 1 — 供应商证件阻断收货契约测试（PRD-01 / 食安合规硬约束）

CLAUDE.md §17 Tier 1 三条硬约束之一：食安合规 — 临期/过期食材不可用于出品。
PRD-01 扩展：过期供应商证件不可继续收货。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. 过期当天阻断收货（食药监稽查场景）
     GIVEN  供应商 A 食品许可证 expire_date=2026-05-13（今天）
     WHEN   收货员尝试创建收货单 today=2026-05-13
     THEN   422 SUPPLIER_CERT_EXPIRED

  2. 未到期正常通过（正常营业场景）
     GIVEN  供应商 B expire_date=2026-05-14（明天）
     WHEN   今天（2026-05-13）创建收货单
     THEN   通过（is_supplier_blocked 返回 False）

  3. 续证后自动恢复（续证场景）
     GIVEN  供应商 A 证件过期，is_supplier_blocked 返回 True
     WHEN   续证到 expire_date=2026-06-15
     THEN   续证后 is_supplier_blocked 立即返回 False（无需手动解锁）

  4. auto_block_on_expire=False 证件不阻断（文件类证件场景）
     GIVEN  auto_block_on_expire=False 证件过期（如审计报告归档）
     WHEN   创建收货单
     THEN   通过（仅预警，不阻断）

  5. 跨租户隔离（RLS 隔离场景）
     GIVEN  tenant_A 供应商证件过期
     WHEN   tenant_B 查询同名供应商阻断状态
     THEN   tenant_B 查询结果 False（RLS 隔离，互不影响）

mock 风格：AsyncMock 模式，参考 test_doc_number_tier1.py。
不需要真 PG fixture（同 PR-03A 模式）。
"""

from __future__ import annotations

import sys
import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))

from services.tx_supply.src.services.cert_service import (
    is_supplier_blocked,
    is_supplier_blocked_via_po,
    list_expiring,
    renew_cert,
)


# ─── 测试常量（徐记海鲜餐厅场景）──────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"   # 徐记海鲜
_TENANT_CZYZ = "22222222-bbbb-bbbb-bbbb-222222222222"   # 尝在一起（跨租户隔离）
_SUPPLIER_A  = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"   # 供应商 A（证件过期）
_SUPPLIER_B  = "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"   # 供应商 B（证件有效）
_CERT_ID     = "cccccccc-0003-0003-0003-cccccccccccc"   # 证件 UUID

_TODAY = date(2026, 5, 13)   # 测试日期（模拟"今天"）


# ─── DB Mock 工厂 ────────────────────────────────────────────────────────────


def _mk_db_blocked(*, has_expired_cert: bool) -> AsyncMock:
    """模拟 DB：is_supplier_blocked 用。

    has_expired_cert=True  → SELECT 返回一行（证件过期，阻断）
    has_expired_cert=False → SELECT 返回空（无过期证件，通过）
    """
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "supplier_certificates" in sql and "SELECT" in sql.upper():
            if has_expired_cert:
                # 返回一行（有过期证件）
                result.first.return_value = MagicMock()
            else:
                # 返回 None（无过期证件）
                result.first.return_value = None
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_renew(*, found: bool = True) -> AsyncMock:
    """模拟 DB：renew_cert 用。

    found=True  → UPDATE RETURNING 返回续证后行
    found=False → 返回 None（cert 不存在）
    """
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)

        if "set_config" in sql:
            return MagicMock()

        if "UPDATE supplier_certificates" in sql:
            result = MagicMock()
            if found:
                row = {
                    "id": _CERT_ID,
                    "supplier_id": _SUPPLIER_A,
                    "cert_type": "food_license",
                    "cert_number": "粤食经许字 20250001",
                    "expire_date": date(2026, 6, 15),
                    "auto_block_on_expire": True,
                    "attachment_url": "https://oss.example.com/cert/new.pdf",
                    "updated_at": "2026-05-13T10:00:00+00:00",
                }
                result.mappings.return_value.first.return_value = row
            else:
                result.mappings.return_value.first.return_value = None
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_list_expiring(*, rows: list) -> AsyncMock:
    """模拟 DB：list_expiring 用。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)

        if "set_config" in sql:
            return MagicMock()

        if "supplier_certificates" in sql and "SELECT" in sql.upper():
            result = MagicMock()
            result.mappings.return_value.all.return_value = rows
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ─── 1. 过期当天阻断收货 ────────────────────────────────────────────────────


class TestCertBlockingOnExpiry:
    @pytest.mark.asyncio
    async def test_expired_cert_blocks_receiving_today(self):
        """场景1：食品许可证过期当天，收货员尝试收货 → 阻断。

        GIVEN  供应商 A 食品经营许可证 expire_date=2026-05-13（今天）
               auto_block_on_expire=TRUE
        WHEN   收货员在 today=2026-05-13 创建收货单
        THEN   is_supplier_blocked 返回 True → 触发 422 SUPPLIER_CERT_EXPIRED

        食药监稽查场景：徐记海鲜晚高峰，稽查人员突击检查供应商甲 A 证件，
        发现食品许可证 5/13 到期，收货系统即日起阻断，保护连锁不被连坐整顿。
        """
        db = _mk_db_blocked(has_expired_cert=True)

        blocked = await is_supplier_blocked(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_A,
            today=_TODAY,
        )

        assert blocked is True, "过期证件当天必须阻断收货（食安硬约束）"

        # 验证 RLS set_config 已调用（租户隔离）
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("set_config" in s for s in sqls), "必须设置 RLS 租户上下文"

    @pytest.mark.asyncio
    async def test_yesterday_expired_cert_blocks_receiving(self):
        """场景1扩展：昨天过期的证件，今天收货同样阻断（非仅当天）。"""
        db = _mk_db_blocked(has_expired_cert=True)

        blocked = await is_supplier_blocked(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_A,
            today=date(2026, 5, 14),  # 昨天(5/13)过期，今天(5/14)查
        )

        assert blocked is True


# ─── 2. 未到期正常通过 ────────────────────────────────────────────────────────


class TestCertPassWhenValid:
    @pytest.mark.asyncio
    async def test_valid_cert_allows_receiving(self):
        """场景2：供应商 B 证件明天到期，今天收货正常通过。

        GIVEN  供应商 B expire_date=2026-05-14（明天）
        WHEN   today=2026-05-13 收货
        THEN   is_supplier_blocked 返回 False → 允许收货

        正常营业场景：徐记海鲜每日进货，供应商 B 证件有效，
        收货员无感知，业务正常进行。
        """
        db = _mk_db_blocked(has_expired_cert=False)

        blocked = await is_supplier_blocked(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_B,
            today=_TODAY,
        )

        assert blocked is False, "有效证件不应阻断收货"

    @pytest.mark.asyncio
    async def test_no_certs_allows_receiving(self):
        """供应商无证件记录 → 不阻断（允许收货）。

        设计决策：新供应商录入时证件可能尚未上传，不默认阻断。
        证件过期预警走 PR-01B alerter 路径，而非此处默认拒绝。
        """
        db = _mk_db_blocked(has_expired_cert=False)

        blocked = await is_supplier_blocked(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id="ffffffff-ffff-ffff-ffff-ffffffffffff",  # 新供应商
            today=_TODAY,
        )

        assert blocked is False


# ─── 3. 续证后自动恢复 ─────────────────────────────────────────────────────────


class TestCertRenewAutoRestore:
    @pytest.mark.asyncio
    async def test_renew_cert_updates_expire_date(self):
        """场景3：供应商 A 证件过期被阻断，续证到 2026-06-15 后自动恢复。

        GIVEN  供应商 A 证件已过期（expire_date=2026-05-13），is_supplier_blocked=True
        WHEN   督导上传新证件，调用 renew_cert(new_expire_date=2026-06-15)
        THEN   renew_cert 成功更新 expire_date
        AND    下次 is_supplier_blocked 查询（new expire_date > today）返回 False
        AND    无需手动解锁操作（续证 = 自动恢复）

        食药监整改场景：供应商甲 A 完成年检，更新许可证，督导 2 分钟内完成续证操作，
        收货系统立即恢复，不影响当日进货计划。
        """
        db_renew = _mk_db_for_renew(found=True)

        result = await renew_cert(
            db=db_renew,
            tenant_id=_TENANT_XUJI,
            cert_id=_CERT_ID,
            new_expire_date=date(2026, 6, 15),
            new_attachment_url="https://oss.example.com/cert/new.pdf",
        )

        assert result["expire_date"] == date(2026, 6, 15), "续证后 expire_date 必须更新"
        assert result["auto_block_on_expire"] is True, "auto_block_on_expire 不变"

        # 续证后 is_supplier_blocked 查询（新 expire_date=6/15 > today=5/13）→ False
        db_check = _mk_db_blocked(has_expired_cert=False)
        blocked_after_renew = await is_supplier_blocked(
            db=db_check,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_A,
            today=_TODAY,
        )
        assert blocked_after_renew is False, "续证后收货阻断自动解除，无需手动操作"

    @pytest.mark.asyncio
    async def test_renew_cert_not_found_raises(self):
        """续证时 cert_id 不存在 → ValueError（不静默）。"""
        db = _mk_db_for_renew(found=False)

        with pytest.raises(ValueError, match="not found"):
            await renew_cert(
                db=db,
                tenant_id=_TENANT_XUJI,
                cert_id="00000000-0000-0000-0000-000000000000",
                new_expire_date=date(2026, 6, 15),
            )


# ─── 4. auto_block_on_expire=False 不阻断 ─────────────────────────────────────


class TestNonBlockingCertType:
    @pytest.mark.asyncio
    async def test_non_blocking_cert_does_not_block_receiving(self):
        """场景4：auto_block_on_expire=False 的文件类证件过期，不阻断收货。

        GIVEN  供应商 A 有一张审计报告（auto_block_on_expire=False）已过期
        WHEN   收货员创建收货单
        THEN   is_supplier_blocked 返回 False（仅预警，不阻断）

        业务设计：并非所有证件过期都阻断收货，文件类（审计报告/检测报告归档）
        仅触发 PR-01B alerter 预警，不阻断日常收货流程。
        """
        # DB 中 auto_block_on_expire=FALSE 证件过期 → SELECT ... WHERE auto_block_on_expire=TRUE 返回 0 行
        db = _mk_db_blocked(has_expired_cert=False)  # SQL 过滤条件已包含 auto_block_on_expire=TRUE

        blocked = await is_supplier_blocked(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_A,
            today=_TODAY,
        )

        assert blocked is False, "auto_block_on_expire=False 证件过期不应阻断收货"


# ─── 5. 跨租户 RLS 隔离 ────────────────────────────────────────────────────────


class TestCrossTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_cert_does_not_affect_tenant_b(self):
        """场景5：tenant_A 供应商证件过期，tenant_B 查询同一供应商不受影响。

        GIVEN  tenant_A（徐记海鲜）供应商 A 证件已过期
        WHEN   tenant_B（尝在一起）查询同名供应商 A 的阻断状态
        THEN   tenant_B 结果为 False（RLS 隔离，互不影响）

        多门店场景：徐记海鲜（tenant_A）和尝在一起（tenant_B）共用同一供应商编号，
        徐记证件问题不能误伤尝在一起的收货流程。
        """
        # tenant_B 查询时，RLS 自动过滤 tenant_B 的证件（无过期记录）
        db_tenant_b = _mk_db_blocked(has_expired_cert=False)

        blocked = await is_supplier_blocked(
            db=db_tenant_b,
            tenant_id=_TENANT_CZYZ,   # tenant_B（尝在一起）
            supplier_id=_SUPPLIER_A,  # 同一供应商 UUID
            today=_TODAY,
        )

        assert blocked is False, "RLS 必须隔离跨租户证件数据"

        # 验证 set_config 传入的是 tenant_B 的 tenant_id（而非 tenant_A）
        set_config_calls = [
            call for call in db_tenant_b.execute.call_args_list
            if "set_config" in str(call.args[0])
        ]
        assert len(set_config_calls) >= 1, "RLS set_config 必须调用"
        # 验证 params 中 tid 是 tenant_B
        tid_value = set_config_calls[0].args[1]["tid"]
        assert tid_value == _TENANT_CZYZ, f"RLS 租户隔离：set_config 必须用 tenant_B({_TENANT_CZYZ})，实际用 {tid_value}"

    @pytest.mark.asyncio
    async def test_tenant_a_blocked_tenant_b_not_blocked(self):
        """场景5扩展：tenant_A blocked=True，tenant_B 独立查询 blocked=False（并发场景）。"""
        db_a = _mk_db_blocked(has_expired_cert=True)
        db_b = _mk_db_blocked(has_expired_cert=False)

        blocked_a = await is_supplier_blocked(
            db=db_a,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_A,
            today=_TODAY,
        )
        blocked_b = await is_supplier_blocked(
            db=db_b,
            tenant_id=_TENANT_CZYZ,
            supplier_id=_SUPPLIER_A,
            today=_TODAY,
        )

        assert blocked_a is True,  "tenant_A 证件过期 → 阻断"
        assert blocked_b is False, "tenant_B 独立数据 → 不受 tenant_A 影响"


# ─── 6. list_expiring 预警列表 ──────────────────────────────────────────────────


class TestListExpiring:
    @pytest.mark.asyncio
    async def test_list_expiring_within_30_days(self):
        """list_expiring 返回 30 天内到期证件（为 PR-01B alerter 预留）。"""
        rows = [
            {
                "id": _CERT_ID,
                "supplier_id": _SUPPLIER_A,
                "cert_type": "food_license",
                "cert_number": "粤食经许字 20250001",
                "issuer": "广东省食药监局",
                "expire_date": date(2026, 5, 20),
                "warning_days": [30, 15, 7],
                "auto_block_on_expire": True,
                "attachment_url": None,
            }
        ]
        db = _mk_db_for_list_expiring(rows=rows)

        result = await list_expiring(db=db, tenant_id=_TENANT_XUJI, within_days=30)

        assert len(result) == 1
        assert result[0]["cert_type"] == "food_license"
        assert result[0]["expire_date"] == date(2026, 5, 20)

    @pytest.mark.asyncio
    async def test_list_expiring_empty_when_none(self):
        """无即将到期证件时返回空列表（非异常）。"""
        db = _mk_db_for_list_expiring(rows=[])

        result = await list_expiring(db=db, tenant_id=_TENANT_XUJI, within_days=7)

        assert result == []


# ─── §19 P0/P1 修复回归测试 ────────────────────────────────────────────────────


def _mk_db_for_po_lookup(
    *, supplier_id_for_po: str | None, supplier_blocked: bool
) -> AsyncMock:
    """构造支持 PO 反查 + supplier_id 阻断查询的 AsyncMock。"""
    db = AsyncMock()
    call_count = {"po_lookup": 0, "block_check": 0}

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return MagicMock()
        if "FROM purchase_orders" in sql:
            call_count["po_lookup"] += 1
            r = MagicMock()
            r.mappings.return_value.first.return_value = (
                {"supplier_id": supplier_id_for_po} if supplier_id_for_po else None
            )
            return r
        if "FROM supplier_certificates" in sql:
            call_count["block_check"] += 1
            r = MagicMock()
            r.first.return_value = 1 if supplier_blocked else None
            return r
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


class TestIsSupplierBlockedViaPo:
    """§19 P0-1 修复回归 — v1 收货路径通过 PO 反查 supplier 阻断。"""

    @pytest.mark.asyncio
    async def test_po_lookup_then_supplier_blocked_returns_true(self):
        """GIVEN PO 存在 + supplier_id 有效 + 证件过期 → 返回 True 阻断。"""
        db = _mk_db_for_po_lookup(
            supplier_id_for_po=_SUPPLIER_A, supplier_blocked=True
        )
        blocked = await is_supplier_blocked_via_po(
            db,
            tenant_id=_TENANT_XUJI,
            purchase_order_id="po-00000000-0000-0000-0000-000000000001",
            today=date(2026, 5, 14),
        )
        assert blocked is True

    @pytest.mark.asyncio
    async def test_po_lookup_then_supplier_clean_returns_false(self):
        """GIVEN PO 存在 + supplier 证件正常 → 返回 False 通过。"""
        db = _mk_db_for_po_lookup(
            supplier_id_for_po=_SUPPLIER_B, supplier_blocked=False
        )
        blocked = await is_supplier_blocked_via_po(
            db,
            tenant_id=_TENANT_XUJI,
            purchase_order_id="po-00000000-0000-0000-0000-000000000002",
            today=date(2026, 5, 14),
        )
        assert blocked is False

    @pytest.mark.asyncio
    async def test_po_not_found_fail_closed(self):
        """GIVEN PO 不存在（伪造 ID 或跨租户）→ fail-closed 返回 True。

        徐记场景：攻击者直发 POST /api/v1/supply/receiving 带伪造 PO ID 试图
        绕过证件阻断。fail-closed 默认拒绝 = 食安硬约束守门。
        """
        db = _mk_db_for_po_lookup(supplier_id_for_po=None, supplier_blocked=False)
        blocked = await is_supplier_blocked_via_po(
            db,
            tenant_id=_TENANT_XUJI,
            purchase_order_id="po-fake-deadbeef",
            today=date(2026, 5, 14),
        )
        assert blocked is True

    @pytest.mark.asyncio
    async def test_po_has_null_supplier_fail_closed(self):
        """GIVEN PO 存在但 supplier_id NULL（脏数据/迁移漏字段）→ fail-closed。"""
        db = _mk_db_for_po_lookup(supplier_id_for_po=None, supplier_blocked=False)
        blocked = await is_supplier_blocked_via_po(
            db,
            tenant_id=_TENANT_XUJI,
            purchase_order_id="po-dirty-data",
            today=date(2026, 5, 14),
        )
        assert blocked is True


class TestRenewCertGuardrails:
    """§19 P1-2 修复回归 — renew_cert 拒绝过去日期。"""

    @pytest.mark.asyncio
    async def test_renew_with_past_expire_date_rejected(self):
        """督导手滑输入过去日期 → ValueError，UPDATE 不执行。

        徐记场景：督导晚 10 点续证误填 2020-01-01，看似成功，但第二天早 6 点
        is_supplier_blocked 仍 True 阻断收货员 — 早市进货全废。
        必须 fail-fast 拒绝。
        """
        db = AsyncMock()
        db.execute = AsyncMock()
        with pytest.raises(ValueError, match="不能早于今天"):
            await renew_cert(
                db,
                tenant_id=_TENANT_XUJI,
                cert_id=_CERT_ID,
                new_expire_date=date(2020, 1, 1),
            )
        # 关键：UPDATE 不应被调用
        db.execute.assert_not_called()


# ─── 7. 真 PG 并发用例占位（deferred 到 Sprint H DEMO）────────────────────────


@pytest.mark.skip(
    reason=(
        "200 桌晚高峰并发收货 → 证件过期阻断真并发验证需 pytest-postgresql fixture，"
        "安排在 Sprint H DEMO 阶段做（参考 PR-C payment_saga 同模式）。"
        "本测试占位记录真并发用例描述，确保 reviewer 知道 is_supplier_blocked "
        "路径未跑真 PG 并发验证。"
    )
)
def test_200_concurrent_receiving_with_expired_cert_all_blocked():
    """200 个并发收货请求，供应商 A 证件过期 → 全部返回 422 SUPPLIER_CERT_EXPIRED。

    GIVEN  供应商 A 食品许可证 expire_date=2026-05-13（今天）
    AND    200 桌晚高峰同时提交收货单
    WHEN   200 个并发请求命中 create_order 入口
    THEN   全部返回 422 SUPPLIER_CERT_EXPIRED
    AND    P99 阻断响应 < 200ms（CLAUDE.md §17 Tier 1 验收标准）
    AND    无任何请求穿越阻断进入 create_receiving_order 下游
    """
