"""Tier 1 — doc_number_service：业务单号引擎契约测试（PRD-03 / 审计+财务）

测试基于真实餐厅场景（CLAUDE.md §20）：

  - 晚高峰收银员同时结账 → 同租户同 doc_type 序号无重复（real PG 真并发用例
    在 Sprint H DEMO 验收，本测试覆盖单线程 happy path + DSL 守门）
  - 跨天 daily reset：5/13 晚上 11:59 vs 5/14 凌晨 00:01 序号互不影响
  - 跨门店 store_scope：长沙总店 STK-CS01 vs 株洲分店 STK-ZZ01 序号独立
  - 系统默认 fallback：新租户尝在一起未配置规则，仍能用 PO{yyyy}{MM}{dd}-{seq:03d}
  - 徐记定制覆盖：徐记 PO{yyyy}-{seq:04d} 覆盖系统默认
  - DSL 防御：坏模板 → DocNumberError 拒绝，不落数据库脏数据
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.tx_supply.src.services.doc_number_service import (
    DocNumberError,
    SYSTEM_TENANT_ID,
    _compute_lock_id,
    _render_template,
    _scope_key,
    _validate_template,
    generate,
    get_rule,
    upsert_rule,
)


_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"  # 徐记海鲜
_TENANT_CZYZ = "22222222-bbbb-bbbb-bbbb-222222222222"  # 尝在一起（新租户用系统默认）
_STORE_CS = "33333333-cccc-cccc-cccc-333333333333"     # 长沙总店
_STORE_ZZ = "44444444-dddd-dddd-dddd-444444444444"     # 株洲分店


# ─── 1. DSL 模板校验 ────────────────────────────────────────────────────────


class TestTemplateValidation:
    def test_empty_template_rejected(self):
        """空模板 — 财务配置 UI 没填 → 422 不落库。"""
        with pytest.raises(DocNumberError, match="template_empty"):
            _validate_template("")

    def test_template_without_seq_rejected(self):
        """模板缺 {seq} 占位符 → 拒绝，否则序号无落点导致单号永远相同。"""
        with pytest.raises(DocNumberError, match="template_missing_seq"):
            _validate_template("PO{yyyy}{MM}{dd}")

    def test_template_multiple_seq_rejected(self):
        """模板含多个 {seq} → 拒绝（语义不清），财务对账场景要求单一序号位置。"""
        with pytest.raises(DocNumberError, match="template_multiple_seq"):
            _validate_template("PO{seq:03d}-{seq:04d}")

    def test_template_unknown_placeholder_rejected(self):
        """模板含未知占位符 {garbage} → 拒绝。"""
        with pytest.raises(DocNumberError, match="template_invalid_placeholder"):
            _validate_template("PO{garbage}-{seq:03d}")

    def test_template_typo_in_format_spec_rejected(self):
        """模板里 seq 后接错误格式（如 {seq:3} 缺 d）→ 拒绝。"""
        with pytest.raises(DocNumberError, match="template_invalid_placeholder"):
            _validate_template("PO-{seq:3}")

    def test_valid_xuji_template_accepted(self):
        """徐记自定义模板 PO{yyyy}{MM}{dd}-{seq:03d} — 系统默认形态。"""
        _validate_template("PO{yyyy}{MM}{dd}-{seq:03d}")

    def test_valid_store_scoped_template_accepted(self):
        """连锁多店模板 STK-{store_code}-{yyyy}{MM}-{seq:04d}。"""
        _validate_template("STK-{store_code}-{yyyy}{MM}-{seq:04d}")


# ─── 2. 模板渲染 ────────────────────────────────────────────────────────────


class TestTemplateRendering:
    def test_purchase_order_xuji_evening(self):
        """徐记 2026-05-14 19:30 收单：PO20260514-001。"""
        now = datetime(2026, 5, 14, 19, 30, tzinfo=timezone.utc)
        result = _render_template("PO{yyyy}{MM}{dd}-{seq:03d}", now=now, seq=1)
        assert result == "PO20260514-001"

    def test_stocktake_with_store_code(self):
        """长沙总店 5 月盘点单 STK-CS01-202605-0042。"""
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        result = _render_template(
            "STK-{store_code}-{yyyy}{MM}-{seq:04d}",
            now=now,
            seq=42,
            store_code="CS01",
        )
        assert result == "STK-CS01-202605-0042"

    def test_store_code_required_but_missing_raises(self):
        """模板含 {store_code} 但 caller 未提供 → 拒绝（不静默替为空串）。"""
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        with pytest.raises(DocNumberError, match="store_code_required_but_missing"):
            _render_template(
                "STK-{store_code}-{yyyy}{MM}-{seq:04d}",
                now=now,
                seq=1,
            )

    def test_seq_no_width_renders_natural(self):
        """{seq} 不指定宽度 → 自然数字 1/2/.../1000。"""
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        result = _render_template("INV{seq}", now=now, seq=1000)
        assert result == "INV1000"

    def test_seq_overflow_padding_still_works(self):
        """seq:03d 但 seq=1234 → 1234（不截断，宽度只 zero-pad）。"""
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        result = _render_template("PO-{seq:03d}", now=now, seq=1234)
        assert result == "PO-1234"


# ─── 3. scope_key 计算（跨天/跨月/跨店）────────────────────────────────────


class TestScopeKey:
    def test_global_scope_constant_key(self):
        """global scope → 同一 scope_key 不论日期，序号永远累加。"""
        now1 = datetime(2026, 5, 14, tzinfo=timezone.utc)
        now2 = datetime(2027, 1, 1, tzinfo=timezone.utc)
        assert _scope_key("global", now=now1) == _scope_key("global", now=now2)
        assert _scope_key("global", now=now1) == "global"

    def test_daily_scope_resets_across_midnight(self):
        """跨天 daily reset：5/13 晚 11:59 vs 5/14 凌晨 00:01 → 不同 scope_key。

        徐记场景：每天凌晨自动 reset → PO20260513-099 → PO20260514-001。
        """
        late = datetime(2026, 5, 13, 23, 59, tzinfo=timezone.utc)
        early = datetime(2026, 5, 14, 0, 1, tzinfo=timezone.utc)
        assert _scope_key("daily", now=late) != _scope_key("daily", now=early)
        assert _scope_key("daily", now=late) == "2026-05-13"
        assert _scope_key("daily", now=early) == "2026-05-14"

    def test_monthly_scope_resets_across_month(self):
        """月度 reset：4/30 vs 5/1 → 不同 scope_key。盘点 STK-202604-0099 → STK-202605-0001。"""
        apr = datetime(2026, 4, 30, tzinfo=timezone.utc)
        may = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert _scope_key("monthly", now=apr) != _scope_key("monthly", now=may)

    def test_store_scope_independent_per_store(self):
        """跨门店 store scope：长沙总店 vs 株洲分店序号独立。"""
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        key_cs = _scope_key("store", now=now, store_id=_STORE_CS)
        key_zz = _scope_key("store", now=now, store_id=_STORE_ZZ)
        assert key_cs != key_zz
        assert key_cs == _STORE_CS
        assert key_zz == _STORE_ZZ

    def test_store_scope_requires_store_id(self):
        """store scope 但 caller 未传 store_id → 拒绝。"""
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        with pytest.raises(DocNumberError, match="store_id_required_for_store_scope"):
            _scope_key("store", now=now)

    def test_unknown_scope_rejected(self):
        with pytest.raises(DocNumberError, match="unknown_seq_scope"):
            _scope_key("yearly", now=datetime(2026, 5, 14, tzinfo=timezone.utc))


# ─── 4. advisory_lock id 计算（跨租户/跨 doc_type/跨 scope 不碰撞）────────


class TestLockId:
    def test_lock_id_deterministic(self):
        """相同输入 → 相同 lock_id（pg_advisory_xact_lock 串行的基础）。"""
        a = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-14")
        b = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-14")
        assert a == b

    def test_lock_id_in_bigint_range(self):
        """signed int64 范围 — PG advisory_xact_lock 接 BIGINT 不能溢出。"""
        lid = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-14")
        assert -(2**63) <= lid < 2**63

    def test_lock_id_differs_across_tenants(self):
        """徐记和尝在一起同 doc_type 同日期 → 不同 lock_id（不互相阻塞）。"""
        a = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-14")
        b = _compute_lock_id(_TENANT_CZYZ, "purchase_order", "2026-05-14")
        assert a != b

    def test_lock_id_differs_across_doc_types(self):
        """徐记 PO 序号锁 vs STK 盘点锁 → 不同 lock_id（不互相阻塞）。"""
        a = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-14")
        b = _compute_lock_id(_TENANT_XUJI, "stocktake", "2026-05-14")
        assert a != b

    def test_lock_id_differs_across_scope_keys(self):
        """同 doc_type 跨天 → 不同 lock_id（每天独立计数器，互不阻塞）。"""
        a = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-13")
        b = _compute_lock_id(_TENANT_XUJI, "purchase_order", "2026-05-14")
        assert a != b


# ─── 5. get_rule fallback（tenant 自定义 → 系统默认）────────────────────────


def _mk_db_for_rule_lookup(*, row=None) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return MagicMock()
        if "doc_number_rules" in sql and "SELECT" in sql:
            r = MagicMock()
            r.mappings.return_value.first.return_value = row
            return r
        if "doc_number_sequences" in sql and "INSERT" in sql:
            r = MagicMock()
            r.mappings.return_value.first.return_value = {"current_seq": 1}
            return r
        if "pg_advisory_xact_lock" in sql:
            return MagicMock()
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


class TestRuleFallback:
    @pytest.mark.asyncio
    async def test_tenant_custom_rule_wins_over_system_default(self):
        """徐记自定义 PO{yyyy}-{seq:04d} 优先于系统默认 PO{yyyy}{MM}{dd}-{seq:03d}。

        SQL 的 ORDER BY (tenant_id = :tid) DESC LIMIT 1 行为：
          - 若 tenant 自定义存在，按 SQL 排序应返回 tenant 行（不是 system）
        本测试 mock 返回 tenant 行验证 service 信任 SQL 排序。
        """
        db = _mk_db_for_rule_lookup(
            row={
                "tenant_id": _TENANT_XUJI,
                "doc_type": "purchase_order",
                "template": "PO{yyyy}-{seq:04d}",
                "seq_scope": "global",
                "is_active": True,
            }
        )
        rule = await get_rule(db, tenant_id=_TENANT_XUJI, doc_type="purchase_order")
        assert rule.template == "PO{yyyy}-{seq:04d}"
        assert rule.tenant_id == _TENANT_XUJI

    @pytest.mark.asyncio
    async def test_system_default_used_when_tenant_has_no_custom(self):
        """新租户尝在一起未配置规则 → 拿系统默认 fallback。"""
        db = _mk_db_for_rule_lookup(
            row={
                "tenant_id": SYSTEM_TENANT_ID,
                "doc_type": "purchase_order",
                "template": "PO{yyyy}{MM}{dd}-{seq:03d}",
                "seq_scope": "daily",
                "is_active": True,
            }
        )
        rule = await get_rule(db, tenant_id=_TENANT_CZYZ, doc_type="purchase_order")
        assert rule.template == "PO{yyyy}{MM}{dd}-{seq:03d}"
        assert rule.tenant_id == SYSTEM_TENANT_ID

    @pytest.mark.asyncio
    async def test_no_rule_anywhere_raises(self):
        """既无 tenant 又无系统默认 → 报错（运维介入而非静默生成 UUID）。"""
        db = _mk_db_for_rule_lookup(row=None)
        with pytest.raises(DocNumberError, match="no_active_rule"):
            await get_rule(db, tenant_id=_TENANT_XUJI, doc_type="nonexistent_type")


# ─── 6. generate() 集成（验证 advisory_lock + upsert 顺序）──────────────────


class TestGenerateIntegration:
    @pytest.mark.asyncio
    async def test_generate_purchase_order_xuji_evening(self):
        """徐记 2026-05-14 19:30 第 1 个采购单：PO20260514-001。

        集成验证：
          1. get_rule 返回 daily scope 模板
          2. _scope_key 算出 '2026-05-14'
          3. advisory_lock 被调用一次
          4. _next_seq UPSERT 返回 1
          5. 渲染输出符合财务可读格式
        """
        db = _mk_db_for_rule_lookup(
            row={
                "tenant_id": SYSTEM_TENANT_ID,
                "doc_type": "purchase_order",
                "template": "PO{yyyy}{MM}{dd}-{seq:03d}",
                "seq_scope": "daily",
                "is_active": True,
            }
        )
        now = datetime(2026, 5, 14, 19, 30, tzinfo=timezone.utc)
        result = await generate(
            db,
            tenant_id=_TENANT_XUJI,
            doc_type="purchase_order",
            now=now,
        )
        assert result == "PO20260514-001"

        # 验证 advisory_lock 被调用（并发安全）
        executed_sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("pg_advisory_xact_lock" in s for s in executed_sqls), (
            "并发安全要求 advisory_xact_lock 必须在 _next_seq 前持有"
        )
        # 验证 UPSERT 路径（ON CONFLICT DO UPDATE current_seq + 1）
        assert any(
            "ON CONFLICT" in s and "current_seq + 1" in s for s in executed_sqls
        ), "序号增量必须走 UPSERT，避免 SELECT-then-UPDATE 漏锁"

    @pytest.mark.asyncio
    async def test_generate_stocktake_requires_store_code_in_template(self):
        """盘点单 STK-{store_code}-{yyyy}{MM}-{seq:04d} 需 caller 传 store_code。"""
        db = _mk_db_for_rule_lookup(
            row={
                "tenant_id": _TENANT_XUJI,
                "doc_type": "stocktake",
                "template": "STK-{store_code}-{yyyy}{MM}-{seq:04d}",
                "seq_scope": "monthly",
                "is_active": True,
            }
        )
        now = datetime(2026, 5, 14, tzinfo=timezone.utc)
        # 没传 store_code → 抛错
        with pytest.raises(DocNumberError, match="store_code_required_but_missing"):
            await generate(
                db,
                tenant_id=_TENANT_XUJI,
                doc_type="stocktake",
                now=now,
            )

    @pytest.mark.asyncio
    async def test_generate_with_invalid_template_in_db_raises(self):
        """DB 里某行 template 被人工改坏 → generate 时 validate 阶段抛错，不写脏数据。"""
        db = _mk_db_for_rule_lookup(
            row={
                "tenant_id": _TENANT_XUJI,
                "doc_type": "purchase_order",
                "template": "PO{garbage}-{seq:03d}",  # 坏模板
                "seq_scope": "daily",
                "is_active": True,
            }
        )
        with pytest.raises(DocNumberError, match="template_invalid_placeholder"):
            await generate(db, tenant_id=_TENANT_XUJI, doc_type="purchase_order")

        # 关键：抛错时 advisory_lock 与 _next_seq 都不应被调用（防止脏序号）
        executed_sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert not any("pg_advisory_xact_lock" in s for s in executed_sqls), (
            "模板校验失败 → 不应已经 acquire lock，防止 seq 计数器被脏数据消耗"
        )
        assert not any(
            "INSERT INTO doc_number_sequences" in s for s in executed_sqls
        ), "模板校验失败 → 不应写入 sequences 表"


# ─── 7. upsert_rule 配置 ────────────────────────────────────────────────────


class TestUpsertRule:
    @pytest.mark.asyncio
    async def test_upsert_validates_template_before_db(self):
        """财务配置 UI 提交坏模板 → 校验阶段拒绝，DB 0 写入。"""
        db = AsyncMock()
        db.execute = AsyncMock()
        with pytest.raises(DocNumberError, match="template_missing_seq"):
            await upsert_rule(
                db,
                tenant_id=_TENANT_XUJI,
                doc_type="purchase_order",
                template="PO{yyyy}",  # 缺 seq
                seq_scope="daily",
            )
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_rejects_unknown_scope(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        with pytest.raises(DocNumberError, match="invalid_seq_scope"):
            await upsert_rule(
                db,
                tenant_id=_TENANT_XUJI,
                doc_type="purchase_order",
                template="PO{yyyy}-{seq:03d}",
                seq_scope="hourly",  # 非法 scope
            )

    @pytest.mark.asyncio
    async def test_upsert_writes_when_valid(self):
        """合法模板 → UPSERT 走完 set_config + INSERT ON CONFLICT。"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock())
        rule = await upsert_rule(
            db,
            tenant_id=_TENANT_XUJI,
            doc_type="purchase_order",
            template="PO{yyyy}{MM}{dd}-{seq:03d}",
            seq_scope="daily",
            description="徐记定制",
        )
        assert rule.template == "PO{yyyy}{MM}{dd}-{seq:03d}"

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("set_config" in s for s in sqls)
        assert any(
            "INSERT INTO doc_number_rules" in s and "ON CONFLICT" in s
            for s in sqls
        )


# ─── 8. 真 PG 并发用例（deferred 到 Sprint H DEMO 真 PG fixture）────────────


@pytest.mark.skip(
    reason=(
        "200 桌晚高峰真并发用例需 pytest-postgresql fixture，安排在 Sprint H DEMO "
        "阶段做（参考 services/tx-trade payment_saga PR-C 同模式）。本测试占位记录"
        "真并发用例描述，确保 reviewer 知道 advisory_lock 路径未跑真 PG。"
    )
)
def test_200_concurrent_settle_no_duplicate_po_number():
    """200 桌晚高峰收银员同时 settle → 200 个 PO 序号无重复、无空洞。

    GIVEN 徐记长沙总店 2026-05-14 19:30 晚高峰
    AND   200 桌同时 settle 触发 PO 生成
    WHEN  并发 200 reqs 调 generate(doc_type='purchase_order')
    THEN  返回 200 个不同 PO 序号
    AND   序号连续 PO20260514-001 ... PO20260514-200（无空洞）
    AND   PG advisory_xact_lock 自动串行化无 deadlock
    AND   P99 < 200ms（CLAUDE.md §17 Tier 1 验收标准）
    """
