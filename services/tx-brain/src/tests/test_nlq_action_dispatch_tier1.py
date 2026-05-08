"""Tier 1 — S4-03 NLQ → 三类操作 dispatcher 测试

覆盖 (CLAUDE.md §20 真实餐厅场景):
  - actionId 白名单 firewall（4 合法 + 非法）
  - dispatch_dry_run 各 actionId 跑 stub handler
  - Pydantic 类型 schema 校验
  - 三条硬约束守门 stub（毛利底线 / 食安合规 / 客户体验）
  - confirmation_token 生成（同 req+diff 同 token）

技术约束 (PR1):
  - 不连真 DB / 不连 tx-menu / tx-supply / tx-org（4 stub handler 已 hardcode 占位）
  - 不测 execute_action（PR2 才落）
  - 测试条数 ≥13（issue #290 整体 ≥18，分摊到 PR1）

S4-03 Issue #290 / Tier 1
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from ..services.nlq_action_dispatcher import (
    ActionPayloadError,
    dispatch_dry_run,
    gen_confirmation_token,
)
from ..services.nlq_action_registry import (
    ALLOWED_ACTIONS,
    UnknownActionError,
    assert_action_id_allowed,
)
from ..services.nlq_action_types import (
    ActionRequest,
    DryRunDiff,
)

TENANT = str(uuid.uuid4())
STORE = str(uuid.uuid4())
OPERATOR = str(uuid.uuid4())


def _req(action_id, payload, **kw):
    return ActionRequest(
        action_id=action_id,
        tenant_id=TENANT,
        store_id=STORE,
        operator_id=OPERATOR,
        natural_query=kw.get("natural_query", "测试"),
        payload=payload,
    )


# ─── 白名单 firewall ───


class TestActionIdWhitelistTier1:
    """actionId 白名单 — 任何非白名单值一律拒，零容忍。"""

    def test_allowed_actions_set_has_exactly_four(self):
        """S4-03 issue 锁定 4 个 actionId — 白名单必须正好 4 个，多了少了都是漂移。"""
        assert ALLOWED_ACTIONS == frozenset({
            "menu.toggle_availability",
            "menu.update_price",
            "inventory.86",
            "roster.update",
        })

    def test_menu_update_price_is_allowed(self):
        """店长说"把酸菜鱼涨到 99 块" → menu.update_price 放行。"""
        assert_action_id_allowed("menu.update_price")

    def test_inventory_86_is_allowed(self):
        """厨师长说"鲈鱼 86" → inventory.86 放行。"""
        assert_action_id_allowed("inventory.86")

    def test_unknown_menu_delete_is_rejected(self):
        """LLM 误生成 menu.delete → 必须拒。删菜应该走下架（toggle_availability=off）。"""
        with pytest.raises(UnknownActionError, match="menu.delete"):
            assert_action_id_allowed("menu.delete")

    def test_payload_tampered_arbitrary_is_rejected(self):
        """前端被劫持注入 'evil.do_anything' → 必须拒。"""
        with pytest.raises(UnknownActionError, match="evil"):
            assert_action_id_allowed("evil.do_anything")


# ─── dispatch_dry_run ───


class TestDispatchDryRunTier1:
    """dispatch_dry_run 流程 — 4 个 actionId 各跑通 stub handler。"""

    @pytest.mark.asyncio
    async def test_menu_update_price_returns_diff_with_price_field(self):
        """店长把"酸菜鱼"改到 ¥99 → DryRunDiff.fields.price_fen.after = 9900。"""
        req = _req("menu.update_price", {"new_price_fen": 9900})
        diff = await dispatch_dry_run(req)
        assert isinstance(diff, DryRunDiff)
        assert diff.fields["price_fen"]["after"] == 9900
        assert diff.affected_count == 1

    @pytest.mark.asyncio
    async def test_menu_toggle_availability_off_returns_diff(self):
        """店长把"酸菜鱼"下架 → DryRunDiff.fields.availability.after = 'off'。"""
        req = _req("menu.toggle_availability", {"toggle_to": "off"})
        diff = await dispatch_dry_run(req)
        assert diff.fields["availability"]["after"] == "off"

    @pytest.mark.asyncio
    async def test_inventory_86_returns_diff(self):
        """厨师长 86 鲈鱼 → DryRunDiff.fields.qty_remaining.after = 0。"""
        req = _req("inventory.86", {"ingredient_id": "ing-luyu-001"})
        diff = await dispatch_dry_run(req)
        assert diff.fields["qty_remaining"]["after"] == 0

    @pytest.mark.asyncio
    async def test_roster_update_returns_diff(self):
        """店长调整员工排班 → DryRunDiff.fields.shift.after = 'evening'。"""
        req = _req(
            "roster.update",
            {"employee_id": "emp-zhang-san", "new_shift": "evening"},
        )
        diff = await dispatch_dry_run(req)
        assert diff.fields["shift"]["after"] == "evening"

    @pytest.mark.asyncio
    async def test_handler_validation_error_propagates(self):
        """改价 payload 缺 new_price_fen → handler 抛 ActionPayloadError 透出（不被沙箱吞）。"""
        req = _req("menu.update_price", {})
        with pytest.raises(ActionPayloadError, match="new_price_fen"):
            await dispatch_dry_run(req)

    def test_action_payload_error_is_value_error_subclass(self):
        """ActionPayloadError 必须是 ValueError 子类（向后兼容既有 except ValueError）。"""
        assert issubclass(ActionPayloadError, ValueError)

    @pytest.mark.asyncio
    async def test_each_handler_payload_error_uses_action_payload_error(self):
        """4 个 stub handler payload 字段错 → 必须抛具体 ActionPayloadError，
        而非裸 ValueError，否则 PR2 路由层 except 无法精准映射 400。"""
        bad_cases = [
            ("menu.update_price", {}),  # 缺 new_price_fen
            ("menu.toggle_availability", {"toggle_to": "evil"}),  # 非 on/off
            ("inventory.86", {}),  # 缺 ingredient_id
            ("roster.update", {"employee_id": "emp-1"}),  # 缺 new_shift
        ]
        for action_id, payload in bad_cases:
            req = _req(action_id, payload)
            with pytest.raises(ActionPayloadError):
                await dispatch_dry_run(req)


# ─── Pydantic schema 校验 ───


class TestActionRequestSchemaTier1:
    """ActionRequest schema — Pydantic 拦截非法输入。"""

    def test_missing_action_id_is_rejected(self):
        """缺 action_id → ValidationError。"""
        with pytest.raises(ValidationError):
            ActionRequest(
                tenant_id=TENANT,
                operator_id=OPERATOR,
                natural_query="测试",
                payload={},
            )  # type: ignore[call-arg]

    def test_unknown_action_id_in_schema_is_rejected(self):
        """action_id='evil' → Pydantic Literal 校验拒（甚至不到 firewall 就拒）。"""
        with pytest.raises(ValidationError):
            ActionRequest(
                action_id="evil",  # type: ignore[arg-type]
                tenant_id=TENANT,
                operator_id=OPERATOR,
                natural_query="测试",
                payload={},
            )

    def test_payload_default_empty_dict(self):
        """payload 不传 → default {} 不报错。"""
        req = ActionRequest(
            action_id="menu.toggle_availability",
            tenant_id=TENANT,
            operator_id=OPERATOR,
            natural_query="测试",
        )
        assert req.payload == {}


# ─── 三条硬约束 stub ───


class TestHardConstraintsStubTier1:
    """硬约束守门 stub — PR1 简单逻辑（PR2 接 tx-agent constraints）。"""

    @pytest.mark.asyncio
    async def test_normal_price_update_no_block(self):
        """正常改价（new_price > cost）→ 不阻断、无 risk_warnings。"""
        req = _req(
            "menu.update_price",
            {"new_price_fen": 9900, "cost_fen": 5000},
        )
        diff = await dispatch_dry_run(req)
        assert diff.constraint_block is None
        assert diff.risk_warnings == []

    @pytest.mark.asyncio
    async def test_price_below_cost_triggers_gross_margin_block(self):
        """改价跌破成本 → 毛利底线触发，constraint_block.name='gross_margin'。"""
        req = _req(
            "menu.update_price",
            {"new_price_fen": 3000, "cost_fen": 5000},  # 30 < 50（成本）
        )
        diff = await dispatch_dry_run(req)
        assert diff.constraint_block is not None
        assert diff.constraint_block["name"] == "gross_margin"
        assert any("毛利底线" in w for w in diff.risk_warnings)

    @pytest.mark.asyncio
    async def test_inventory_86_expired_batch_triggers_food_safety_block(self):
        """86 跨过期批次 → 食安合规触发，constraint_block.name='food_safety'。"""
        req = _req(
            "inventory.86",
            {"ingredient_id": "ing-luyu-001", "has_expired_batch": True},
        )
        diff = await dispatch_dry_run(req)
        assert diff.constraint_block is not None
        assert diff.constraint_block["name"] == "food_safety"

    @pytest.mark.asyncio
    async def test_toggle_off_with_unfinished_orders_triggers_cx_block(self):
        """下架前有未结订单 → 客户体验触发，constraint_block.name='customer_experience'。"""
        req = _req(
            "menu.toggle_availability",
            {"toggle_to": "off", "unfinished_orders": 3},
        )
        diff = await dispatch_dry_run(req)
        assert diff.constraint_block is not None
        assert diff.constraint_block["name"] == "customer_experience"

    @pytest.mark.asyncio
    async def test_inventory_86_with_unfinished_orders_triggers_cx_block(self):
        """86 食材但仍被 N 单未完成订单引用 → 客户体验触发（与 toggle_availability 对称）。

        徐记海鲜场景：服务员收银时已下"清蒸鲈鱼" 5 单未出菜，厨师长此时 86 鲈鱼
        会让那 5 桌客人收到"无法上菜"通知，必须在 dispatcher 层提前拦截。
        """
        req = _req(
            "inventory.86",
            {"ingredient_id": "ing-luyu-001", "unfinished_orders": 5},
        )
        diff = await dispatch_dry_run(req)
        assert diff.constraint_block is not None
        assert diff.constraint_block["name"] == "customer_experience"
        assert any("客户体验" in w for w in diff.risk_warnings)

    @pytest.mark.asyncio
    async def test_inventory_86_food_safety_takes_priority_over_cx(self):
        """同时含过期批次 + 未结订单 → 食安合规优先（更严重的约束在前）。"""
        req = _req(
            "inventory.86",
            {
                "ingredient_id": "ing-luyu-001",
                "has_expired_batch": True,
                "unfinished_orders": 5,
            },
        )
        diff = await dispatch_dry_run(req)
        assert diff.constraint_block is not None
        # 食安合规先于客户体验返回（短路）— 过期食材是绝对不能用的
        assert diff.constraint_block["name"] == "food_safety"


# ─── confirmation_token ───


class TestConfirmationTokenTier1:
    """confirmation_token 生成 — nonce 一次性（PR2 持久化 nonce 表防重放）。"""

    @pytest.mark.asyncio
    async def test_same_request_yields_different_tokens_due_to_nonce(self):
        """同 req 多次调用 → 不同 token（nonce 强制）。

        Code review (#301) 反转语义：原 deterministic hash 让同 token 可被 PR2 多次
        confirm（双花）；现在每次 nonce 不同，PR2 持久化 token 表后单次性使用。
        """
        req = _req("menu.update_price", {"new_price_fen": 9900, "cost_fen": 5000})
        diff1 = await dispatch_dry_run(req)
        diff2 = await dispatch_dry_run(req)
        token1 = gen_confirmation_token(req, diff1)
        token2 = gen_confirmation_token(req, diff2)
        assert token1 != token2, "nonce 必须让同 req 多次生成的 token 不同（防双花）"

    @pytest.mark.asyncio
    async def test_different_action_yields_different_token(self):
        """不同 actionId → 不同 token（防 token 跨 actionId 重用）。"""
        req_price = _req("menu.update_price", {"new_price_fen": 9900})
        req_toggle = _req("menu.toggle_availability", {"toggle_to": "off"})
        diff_price = await dispatch_dry_run(req_price)
        diff_toggle = await dispatch_dry_run(req_toggle)
        assert gen_confirmation_token(req_price, diff_price) != gen_confirmation_token(
            req_toggle, diff_toggle
        )

    @pytest.mark.asyncio
    async def test_token_format_is_32_char_hex(self):
        """token 必须是 32 字符十六进制（SHA256 截断），稳定 schema 给 PR2 nonce 表用。"""
        req = _req("menu.update_price", {"new_price_fen": 9900})
        diff = await dispatch_dry_run(req)
        token = gen_confirmation_token(req, diff)
        assert len(token) == 32
        assert all(c in "0123456789abcdef" for c in token)
