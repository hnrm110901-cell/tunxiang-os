"""test_discount_engine.py — 多优惠叠加规则引擎测试

覆盖范围：
  GET  /api/v1/discount/rules         — 查询规则列表
  POST /api/v1/discount/rules         — 新建规则
  POST /api/v1/discount/calculate     — 多优惠叠加计算
  PUT  /api/v1/discount/rules/{id}    — 更新规则

核心内部函数单元测试（无 DB 依赖）：
  _apply_single_discount              — 单个优惠应用
  _calc_combination                   — 组合优惠计算
  _resolve_conflicts                  — 互斥冲突解决
  _build_steps                        — 步骤详情构建

DB 层通过 app.dependency_overrides[get_db] 注入 AsyncMock。
折扣计算的核心逻辑全在内存中运行（_resolve_conflicts / _build_steps），
DB 只用于读 discount_rules 和写 checkout_discount_log。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
)

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.api.discount_engine_routes import (
    DiscountInput,
    _apply_single_discount,
    _build_steps,
    _calc_combination,
    _resolve_conflicts,
)
from src.api.discount_engine_routes import (
    router as discount_engine_router,
)

from shared.ontology.src.database import get_db

# ─── 测试 app ─────────────────────────────────────────────────────────────────

_app = FastAPI(title="discount-engine-test")
_app.include_router(discount_engine_router)

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}

# 固定的合法 UUID（作为 store_id / order_id 等）
STORE_UUID = "00000000-0000-0000-0000-000000000099"
ORDER_UUID = "00000000-0000-0000-0000-000000000088"


# ─── Mock DB 工厂 ─────────────────────────────────────────────────────────────


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


def _db_returns_no_rules(db: AsyncMock) -> None:
    """配置 mock DB：discount_rules 查询返回空列表，log 写入正常。"""
    empty_result = MagicMock()
    empty_mapping = MagicMock()
    empty_mapping.all = MagicMock(return_value=[])
    empty_result.mappings = MagicMock(return_value=empty_mapping)

    db.execute.return_value = empty_result


def _db_returns_rules(db: AsyncMock, rules: list[dict]) -> None:
    """配置 mock DB：discount_rules 查询返回指定规则列表。"""
    rows = []
    for r in rules:
        row = MagicMock()
        for k, v in r.items():
            setattr(row, k, v)
        row.__getitem__ = lambda self, key, r=r: r[key]
        rows.append(row)

    result = MagicMock()
    mapping = MagicMock()
    mapping.all = MagicMock(return_value=rows)
    result.mappings = MagicMock(return_value=mapping)

    db.execute.return_value = result


# ─── DB override 上下文 ───────────────────────────────────────────────────────


class _DBOverride:
    def __init__(self, mock_db: AsyncMock):
        self._mock_db = mock_db

    def __enter__(self):
        async def _override():
            yield self._mock_db
        _app.dependency_overrides[get_db] = _override
        return self._mock_db

    def __exit__(self, *args):
        _app.dependency_overrides.pop(get_db, None)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 1：纯函数单元测试（无 HTTP/DB 依赖）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestApplySingleDiscount:
    """_apply_single_discount — 单个优惠应用"""

    def _d(self, **kwargs) -> DiscountInput:
        base = {"type": "member_discount"}
        base.update(kwargs)
        return DiscountInput(**base)

    def test_member_discount_90_percent(self):
        """会员 9 折：10_000 × 0.9 = 9_000。"""
        d = self._d(type="member_discount", rate=0.9)
        assert _apply_single_discount(10_000, d) == 9_000

    def test_member_discount_85_percent(self):
        """会员 8.5 折：10_000 × 0.85 = 8_500。"""
        d = self._d(type="member_discount", rate=0.85)
        assert _apply_single_discount(10_000, d) == 8_500

    def test_platform_coupon_deduct(self):
        """平台券直减 2_000：10_000 - 2_000 = 8_000。"""
        d = self._d(type="platform_coupon", deduct_fen=2_000)
        assert _apply_single_discount(10_000, d) == 8_000

    def test_manual_discount_rate(self):
        """手动折扣 0.8 折：10_000 × 0.8 = 8_000。"""
        d = self._d(type="manual_discount", rate=0.8)
        assert _apply_single_discount(10_000, d) == 8_000

    def test_manual_discount_fixed(self):
        """手动直减 1_500：10_000 - 1_500 = 8_500。"""
        d = self._d(type="manual_discount", deduct_fen=1_500)
        assert _apply_single_discount(10_000, d) == 8_500

    def test_full_reduction_triggered(self):
        """满 100 减 20（10_000 分满足条件）：10_000 - 2_000 = 8_000。"""
        d = self._d(type="full_reduction", condition_fen=10_000, deduct_fen=2_000)
        assert _apply_single_discount(10_000, d) == 8_000

    def test_full_reduction_not_triggered(self):
        """满 200 减 20（10_000 分不满足 20_000 条件）：不触发，返回原金额。"""
        d = self._d(type="full_reduction", condition_fen=20_000, deduct_fen=2_000)
        assert _apply_single_discount(10_000, d) == 10_000

    def test_result_never_negative(self):
        """直减金额超过原价时，最低返回 0。"""
        d = self._d(type="platform_coupon", deduct_fen=99_999)
        assert _apply_single_discount(1_000, d) == 0


class TestCalcCombination:
    """_calc_combination — 组合优惠总节省"""

    def test_single_discount(self):
        """单个 9 折：10_000 → 9_000，saved=1_000。"""
        d = DiscountInput(type="member_discount", rate=0.9)
        final, saved = _calc_combination(10_000, [d])
        assert final == 9_000
        assert saved == 1_000

    def test_two_discounts_stacked(self):
        """9 折 + 减 500：10_000 → 9_000 → 8_500，saved=1_500。"""
        d1 = DiscountInput(type="member_discount", rate=0.9)
        d2 = DiscountInput(type="platform_coupon", deduct_fen=500)
        final, saved = _calc_combination(10_000, [d1, d2])
        assert final == 8_500
        assert saved == 1_500

    def test_empty_combo(self):
        """空组合 → 原价，saved=0。"""
        final, saved = _calc_combination(10_000, [])
        assert final == 10_000
        assert saved == 0


class TestResolveConflicts:
    """_resolve_conflicts — 互斥冲突解决，选对顾客最优组合"""

    def test_no_conflict_returns_all(self):
        """规则均允许叠加 → 返回全部 discount，无 conflicts。"""
        rule_map = {
            "member_discount": {"can_stack_with": ["platform_coupon"], "apply_order": 10},
            "platform_coupon": {"can_stack_with": ["member_discount"], "apply_order": 20},
        }
        d1 = DiscountInput(type="member_discount", rate=0.9)
        d2 = DiscountInput(type="platform_coupon", deduct_fen=500)
        chosen, conflicts = _resolve_conflicts(10_000, [d1, d2], rule_map)
        assert len(conflicts) == 0
        assert len(chosen) == 2

    def test_conflict_picks_best(self):
        """两个互斥优惠：选 saved 最大的一个。"""
        # member_discount 不允许与 manual_discount 叠加（can_stack_with=[]）
        rule_map = {
            "member_discount": {"can_stack_with": [], "apply_order": 10},
            "manual_discount": {"can_stack_with": [], "apply_order": 10},
        }
        # member_discount 9折：10_000→9_000，saved=1_000
        d1 = DiscountInput(type="member_discount", rate=0.9)
        # manual_discount 直减 2_000：10_000→8_000，saved=2_000（更优）
        d2 = DiscountInput(type="manual_discount", deduct_fen=2_000)

        chosen, conflicts = _resolve_conflicts(10_000, [d1, d2], rule_map)
        assert len(conflicts) > 0
        assert len(chosen) == 1
        assert chosen[0].type == "manual_discount"  # saved=2_000 > 1_000

    def test_conflict_favors_member_when_larger(self):
        """当会员折扣比手动优惠更优时，选会员折扣。"""
        rule_map = {
            "member_discount": {"can_stack_with": [], "apply_order": 10},
            "manual_discount": {"can_stack_with": [], "apply_order": 10},
        }
        # 1折（0.1）：10_000→1_000，saved=9_000（极大）
        d1 = DiscountInput(type="member_discount", rate=0.1)
        # 手动直减 500：saved=500
        d2 = DiscountInput(type="manual_discount", deduct_fen=500)

        chosen, conflicts = _resolve_conflicts(10_000, [d1, d2], rule_map)
        assert chosen[0].type == "member_discount"

    def test_empty_discounts_returns_empty(self):
        """空 discounts 列表 → 返回空。"""
        chosen, conflicts = _resolve_conflicts(10_000, [], {})
        assert chosen == []
        assert conflicts == []


class TestBuildSteps:
    """_build_steps — 按 apply_order 构建折扣步骤"""

    def test_steps_order(self):
        """apply_order 小的先执行。"""
        rule_map = {
            "member_discount": {"can_stack_with": [], "apply_order": 10},
            "platform_coupon": {"can_stack_with": [], "apply_order": 5},
        }
        d1 = DiscountInput(type="member_discount", rate=0.9)
        d2 = DiscountInput(type="platform_coupon", deduct_fen=500)
        steps = _build_steps(10_000, [d1, d2], rule_map)

        assert len(steps) == 2
        assert steps[0]["type"] == "platform_coupon"   # apply_order=5，先执行
        assert steps[1]["type"] == "member_discount"   # apply_order=10，后执行

    def test_steps_before_after_saved(self):
        """每步 before / after / saved 计算正确。"""
        rule_map = {
            "member_discount": {"can_stack_with": [], "apply_order": 10},
        }
        d = DiscountInput(type="member_discount", rate=0.9)
        steps = _build_steps(10_000, [d], rule_map)

        assert steps[0]["before"] == 10_000
        assert steps[0]["after"] == 9_000
        assert steps[0]["saved"] == 1_000

    def test_steps_empty(self):
        """无优惠 → 空步骤列表。"""
        steps = _build_steps(10_000, [], {})
        assert steps == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 2：HTTP 路由集成测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGetRules:
    @pytest.mark.asyncio
    async def test_get_rules_empty(self, client: AsyncClient):
        """无规则时返回空列表，total=0。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        with _DBOverride(mock_db):
            resp = await client.get(
                "/api/v1/discount/rules",
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["rules"] == []
        assert data["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_get_rules_missing_tenant(self, client: AsyncClient):
        """不带 X-Tenant-ID → HTTP 400。"""
        resp = await client.get("/api/v1/discount/rules")
        assert resp.status_code == 400


class TestCreateRule:
    @pytest.mark.asyncio
    async def test_create_rule_success(self, client: AsyncClient):
        """POST 创建折扣规则 → 返回 rule_id。"""
        mock_db = _make_db()

        body = {
            "name": "会员9折",
            "type": "member_discount",
            "priority": 100,
            "can_stack_with": ["platform_coupon"],
            "apply_order": 10,
            "description": "会员专属9折优惠",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/rules",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "rule_id" in data["data"]
        assert data["data"]["rule_id"]   # 非空

    @pytest.mark.asyncio
    async def test_create_rule_invalid_type(self, client: AsyncClient):
        """无效的 type → HTTP 400（业务逻辑校验，非 Pydantic）。"""
        mock_db = _make_db()

        body = {
            "name": "测试规则",
            "type": "invalid_discount_type",
            "priority": 100,
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/rules",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_rule_invalid_can_stack_with(self, client: AsyncClient):
        """can_stack_with 含无效类型 → HTTP 400。"""
        mock_db = _make_db()

        body = {
            "name": "测试规则",
            "type": "member_discount",
            "can_stack_with": ["unknown_type"],
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/rules",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 400


class TestCalculateDiscount:
    """POST /api/v1/discount/calculate 集成测试"""

    def _calc_body(self, discounts: list[dict], base: int = 10_000) -> dict:
        return {
            "order_id": ORDER_UUID,
            "base_amount_fen": base,
            "discounts": discounts,
            "store_id": None,
        }

    @pytest.mark.asyncio
    async def test_calculate_discount_no_rules(self, client: AsyncClient):
        """无规则 + 1 个 member_discount → 正常计算，total_saved 正确。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        body = self._calc_body([
            {"type": "member_discount", "rate": 0.9, "member_id": "member-001"},
        ])
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        result = data["data"]
        # 9折：10_000 → 9_000，saved=1_000
        assert result["total_saved_fen"] == 1_000
        assert result["final_amount_fen"] == 9_000
        assert len(result["applied_steps"]) == 1

    @pytest.mark.asyncio
    async def test_calculate_discount_percentage(self, client: AsyncClient):
        """单一 9折（rate=0.9）规则：100元 → 90元。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        body = self._calc_body(
            [{"type": "member_discount", "rate": 0.9}],
            base=10_000,
        )
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["final_amount_fen"] == 9_000    # 10_000 × 0.9
        assert data["total_saved_fen"] == 1_000

    @pytest.mark.asyncio
    async def test_calculate_discount_fixed(self, client: AsyncClient):
        """满100减20（满减）：10_000 分满足 10_000 条件 → 减 2_000 → 8_000。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        body = self._calc_body(
            [{
                "type": "full_reduction",
                "condition_fen": 10_000,
                "deduct_fen": 2_000,
            }],
            base=10_000,
        )
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["final_amount_fen"] == 8_000
        assert data["total_saved_fen"] == 2_000

    @pytest.mark.asyncio
    async def test_calculate_discount_conflict_picks_best(self, client: AsyncClient):
        """两个互斥规则冲突时，引擎自动选对顾客最优方案。

        rule_map 中两个类型都设为 can_stack_with=[]（互斥），
        manual_discount（减 3_000）比 member_discount（9折=减 1_000）更优，
        应选 manual_discount。
        """
        mock_db = _make_db()

        # 配置 DB 返回两条互斥规则
        rules = [
            {
                "id": str(uuid.uuid4()),
                "store_id": None,
                "name": "会员9折",
                "priority": 100,
                "type": "member_discount",
                "can_stack_with": [],
                "apply_order": 10,
                "is_active": True,
                "description": None,
            },
            {
                "id": str(uuid.uuid4()),
                "store_id": None,
                "name": "手动折扣",
                "priority": 200,
                "type": "manual_discount",
                "can_stack_with": [],
                "apply_order": 10,
                "is_active": True,
                "description": None,
            },
        ]
        _db_returns_rules(mock_db, rules)

        body = self._calc_body(
            [
                {"type": "member_discount", "rate": 0.9},       # saved=1_000
                {"type": "manual_discount", "deduct_fen": 3_000},  # saved=3_000（更优）
            ],
            base=10_000,
        )
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        # 应选 manual_discount（saved=3_000）
        assert data["total_saved_fen"] == 3_000
        assert data["final_amount_fen"] == 7_000
        assert len(data["conflicts"]) > 0   # 有冲突记录

    @pytest.mark.asyncio
    async def test_calculate_discount_invalid_type(self, client: AsyncClient):
        """无效 discount.type → HTTP 400。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        body = self._calc_body(
            [{"type": "invalid_type", "rate": 0.9}],
        )
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_calculate_stacked_discounts(self, client: AsyncClient):
        """两个可叠加优惠：9折 + 直减 500。"""
        mock_db = _make_db()

        # 规则允许叠加
        rules = [
            {
                "id": str(uuid.uuid4()),
                "store_id": None,
                "name": "会员9折",
                "priority": 100,
                "type": "member_discount",
                "can_stack_with": ["platform_coupon"],
                "apply_order": 10,
                "is_active": True,
                "description": None,
            },
            {
                "id": str(uuid.uuid4()),
                "store_id": None,
                "name": "平台券",
                "priority": 200,
                "type": "platform_coupon",
                "can_stack_with": ["member_discount"],
                "apply_order": 20,
                "is_active": True,
                "description": None,
            },
        ]
        _db_returns_rules(mock_db, rules)

        body = self._calc_body(
            [
                {"type": "member_discount", "rate": 0.9},        # 10_000→9_000
                {"type": "platform_coupon", "deduct_fen": 500},  # 9_000→8_500
            ],
            base=10_000,
        )
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["final_amount_fen"] == 8_500
        assert data["total_saved_fen"] == 1_500
        assert len(data["applied_steps"]) == 2
        assert data["conflicts"] == []   # 无冲突


class TestHardConstraintGrossMargin:
    """毛利底线约束测试

    当前 discount_engine_routes.py 的折扣引擎本身不感知毛利阈值
    （毛利校验由上游 Agent / 折扣守护 Agent 执行），
    但折扣计算结果应提供足够信息让调用方判断是否违反约束。

    本测试验证：
    1. 极大折扣（如 1折）时，final_amount_fen 极低，由调用方判断 constraint_violated。
    2. 接口本身不因毛利问题返回错误（底层引擎只负责数学计算）。
    """

    @pytest.mark.asyncio
    async def test_extreme_discount_returns_low_final(self, client: AsyncClient):
        """0.1折（10%）折扣：10_000 → 1_000，引擎照常计算，调用方自行判断约束。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        body = {
            "order_id": ORDER_UUID,
            "base_amount_fen": 10_000,
            "discounts": [{"type": "member_discount", "rate": 0.1}],
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["final_amount_fen"] == 1_000
        assert data["total_saved_fen"] == 9_000
        # 引擎本身不返回 constraint_violated 字段（毛利校验在 Agent 层）
        # 但调用方可通过 final_amount_fen < gross_margin_threshold 判断
        assert "final_amount_fen" in data

    @pytest.mark.asyncio
    async def test_discount_reduces_to_zero(self, client: AsyncClient):
        """直减超过原价时，final_amount_fen=0，不出现负数。"""
        mock_db = _make_db()
        _db_returns_no_rules(mock_db)

        body = {
            "order_id": ORDER_UUID,
            "base_amount_fen": 5_000,
            "discounts": [{"type": "platform_coupon", "deduct_fen": 99_999}],
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                "/api/v1/discount/calculate",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["final_amount_fen"] == 0
        assert data["total_saved_fen"] == 5_000


class TestUpdateRule:
    @pytest.mark.asyncio
    async def test_update_rule_success(self, client: AsyncClient):
        """PUT 更新规则 → 返回 rule_id 和成功消息。"""
        mock_db = _make_db()
        rule_id = str(uuid.uuid4())

        # 模拟 UPDATE ... RETURNING id
        returning_result = MagicMock()
        returning_result.fetchone = MagicMock(return_value=(rule_id,))
        mock_db.execute.return_value = returning_result

        body = {"name": "更新后的会员折扣", "is_active": True}
        with _DBOverride(mock_db):
            resp = await client.put(
                f"/api/v1/discount/rules/{rule_id}",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["rule_id"] == rule_id

    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, client: AsyncClient):
        """更新不存在的规则 → HTTP 404。"""
        mock_db = _make_db()
        rule_id = str(uuid.uuid4())

        # RETURNING 返回 None（未找到）
        returning_result = MagicMock()
        returning_result.fetchone = MagicMock(return_value=None)
        mock_db.execute.return_value = returning_result

        body = {"name": "不存在的规则"}
        with _DBOverride(mock_db):
            resp = await client.put(
                f"/api/v1/discount/rules/{rule_id}",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 404
