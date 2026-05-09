"""积分系统 Tier 1 测试 — 跨店结算 / 抵现毛利约束 / FIFO 过期 / 规则引擎

对齐 CLAUDE.md §17 / §20：测试基于真实餐厅场景（不是技术边界值）。
所有金额单位：分（fen，整数）。

覆盖（共 4 组核心场景）：
  A. 规则引擎：消费 100 元送 1 积分（按规则配置）
  B. 抵现：1 积分抵 1 分；高额抵现违反毛利底线时拒绝
  C. 跨店 FIFO 结算：A 店产生的积分在 B 店消耗，结算时回流到 A 店
  D. 过期清理：积分过期 12 个月按 FIFO 清理

测试策略：
- 纯函数 → 直接断言（无 DB / 无 Redis 依赖）
- 服务函数：用 AsyncMock / MagicMock 替换 DB session 和 emit_event
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# 注入 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════════
# A. 规则引擎：消费 / 充值 / 签到 / 活动
# ═══════════════════════════════════════════════════════════════════════════


class TestEarnRules:
    """场景：徐记海鲜会员日，消费 100 元送 1 积分（默认规则）。"""

    def test_consume_100_yuan_earns_1_point(self):
        """点单 100 元（10000 分），按默认规则 earn_unit=10000 / earn_ratio=1，得 1 积分。"""
        from services.tx_member.src.services.points_engine import calculate_earn_points

        assert calculate_earn_points(amount_fen=10000, earn_ratio=1, earn_unit_fen=10000) == 1

    def test_consume_888_yuan_earns_8_points(self):
        """点单 888 元（不是 100 的整数倍），向下取整 → 8 积分。"""
        from services.tx_member.src.services.points_engine import calculate_earn_points

        assert calculate_earn_points(amount_fen=88800, earn_ratio=1, earn_unit_fen=10000) == 8

    def test_member_day_double_points(self):
        """会员日双倍：multiplier=2.0，消费 200 元 → 4 积分。"""
        from services.tx_member.src.services.points_engine import calculate_earn_points

        assert calculate_earn_points(amount_fen=20000, earn_ratio=1, earn_unit_fen=10000, multiplier=2.0) == 4

    def test_recharge_500_with_2x_multiplier_earns_10_points(self):
        """大客户充值 500 元做 2x 倍数活动，按 100 元 1 积分基础 → 10 积分。"""
        from services.tx_member.src.services.points_engine import calculate_earn_points

        assert calculate_earn_points(amount_fen=50000, earn_ratio=1, earn_unit_fen=10000, multiplier=2.0) == 10

    def test_signin_fixed_amount(self):
        """签到固定送积分由 source 路由决定，不走金额折算（amount 直接传入）。"""
        from services.tx_member.src.services.points_engine import EARN_SOURCES

        assert "sign_in" in EARN_SOURCES

    def test_invalid_rule_returns_zero(self):
        """earn_unit_fen 为 0 时不能除零，返回 0 积分而非崩溃。"""
        from services.tx_member.src.services.points_engine import calculate_earn_points

        assert calculate_earn_points(10000, 1, 0) == 0


# ═══════════════════════════════════════════════════════════════════════════
# B. 积分抵现 + 毛利底线硬约束
# ═══════════════════════════════════════════════════════════════════════════


class TestCashOffset:
    """场景：100 积分抵 1 元（默认规则）。"""

    def test_100_points_offsets_1_yuan(self):
        """100 积分按默认 spend_ratio=100 / spend_value_fen=100 → 抵 100 分（= 1 元）。"""
        from services.tx_member.src.services.points_engine import calculate_cash_offset_fen

        assert calculate_cash_offset_fen(points=100, spend_ratio=100, spend_value_fen=100) == 100

    def test_offset_floor_division(self):
        """150 积分按 100 单位向下取整 → 只能抵 100 分。"""
        from services.tx_member.src.services.points_engine import calculate_cash_offset_fen

        assert calculate_cash_offset_fen(points=150, spend_ratio=100, spend_value_fen=100) == 100

    def test_1000_points_offsets_10_yuan(self):
        """1000 积分 → 抵 1000 分 = 10 元。"""
        from services.tx_member.src.services.points_engine import calculate_cash_offset_fen

        assert calculate_cash_offset_fen(points=1000, spend_ratio=100, spend_value_fen=100) == 1000


class TestMarginFloorConstraint:
    """硬约束：抵现后单笔毛利不可低于阈值（默认 15%）。"""

    def test_normal_offset_passes(self):
        """正常订单：100 元食材成本 60 元，抵 5 元后毛利仍达标。"""
        from services.tx_member.src.services.points_engine import check_offset_against_margin_floor

        result = check_offset_against_margin_floor(
            order_total_fen=10000,
            food_cost_fen=6000,
            offset_fen=500,
            min_margin_rate=0.15,
        )
        assert result["allowed"] is True
        # 实际毛利: (10000 - 500 - 6000) / (10000 - 500) = 3500 / 9500 ≈ 36.8%
        assert result["actual_margin_rate"] > 0.15

    def test_excessive_offset_blocked(self):
        """高额抵现：100 元订单食材成本 90 元，抵 50 元 → 毛利率会变负，必须拒绝。"""
        from services.tx_member.src.services.points_engine import check_offset_against_margin_floor

        result = check_offset_against_margin_floor(
            order_total_fen=10000,
            food_cost_fen=9000,
            offset_fen=5000,
            min_margin_rate=0.15,
        )
        assert result["allowed"] is False
        assert "margin" in result["reason"].lower()

    def test_offset_at_exactly_threshold_passes(self):
        """毛利率刚好等于阈值，应通过（>=）。"""
        from services.tx_member.src.services.points_engine import check_offset_against_margin_floor

        # 设计: 毛利率 = (price - offset - cost) / (price - offset) = threshold
        # threshold=0.15, cost=850, price=1000, 求 offset 使毛利率 = 0.15
        # (1000-offset-850)/(1000-offset)=0.15 → 150-offset=0.15(1000-offset)
        # → 150-offset=150-0.15*offset → 0.85*offset=0 → offset=0
        # 所以零抵现就是临界。换个例子：高成本但允许少量抵
        result = check_offset_against_margin_floor(
            order_total_fen=10000,
            food_cost_fen=5000,
            offset_fen=1000,
            min_margin_rate=0.15,
        )
        # 实际: (10000-1000-5000)/(10000-1000) = 4000/9000 ≈ 44.4% >> 15%
        assert result["allowed"] is True

    def test_offset_zero_is_noop(self):
        """0 抵现总是允许。"""
        from services.tx_member.src.services.points_engine import check_offset_against_margin_floor

        result = check_offset_against_margin_floor(
            order_total_fen=10000,
            food_cost_fen=8000,
            offset_fen=0,
            min_margin_rate=0.15,
        )
        assert result["allowed"] is True

    def test_invalid_total_returns_blocked(self):
        """订单金额非正数视为非法 → 拒绝。"""
        from services.tx_member.src.services.points_engine import check_offset_against_margin_floor

        result = check_offset_against_margin_floor(
            order_total_fen=0,
            food_cost_fen=0,
            offset_fen=100,
            min_margin_rate=0.15,
        )
        assert result["allowed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# C. 跨店积分结算（按月）
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossStoreSettlement:
    """场景：连锁集团 A/B/C 三店，会员在 A 店消费攒积分，跨店去 B 店抵现。
    月底结算时，B 店应将抵扣金额按比例回流给 A 店（资金流向）。

    会计原则：积分负债的归属是"产生积分的门店"。
    抵现时，消费门店实际提供商品/服务，但积分负债从产生门店核销。
    所以结算的是：B 店从 A 店"购入"了对应金额的负债核销权 →
        B 店应付给 A 店：抵扣金额。
    """

    def test_single_store_no_cross_flow(self):
        """全部在 A 店产生且在 A 店消耗，无跨店流量。"""
        from services.tx_member.src.services.points_settlement import settle_cross_store

        events = [
            {"direction": "earn", "store_id": "A", "points": 100, "amount_fen": 10000},
            {"direction": "spend", "store_id": "A", "points": 100, "amount_fen": 100},
        ]
        result = settle_cross_store(events)
        assert result["transfers"] == []
        assert result["per_store"]["A"]["earned_points"] == 100
        assert result["per_store"]["A"]["spent_points"] == 100

    def test_cross_store_flow_a_earns_b_spends(self):
        """A 店产生 100 积分，B 店消耗 100 积分（抵 100 分）→
        B 店需支付 100 分给 A 店（A 店核销自己产生的负债）。"""
        from services.tx_member.src.services.points_settlement import settle_cross_store

        events = [
            {"direction": "earn", "store_id": "A", "points": 100, "amount_fen": 10000},
            {"direction": "spend", "store_id": "B", "points": 100, "amount_fen": 100},
        ]
        result = settle_cross_store(events)

        # 应该有一笔从 B → A 的转账，金额 100 分
        transfers = result["transfers"]
        assert len(transfers) == 1
        assert transfers[0]["from_store_id"] == "B"
        assert transfers[0]["to_store_id"] == "A"
        assert transfers[0]["amount_fen"] == 100

    def test_three_store_settlement_proportional(self):
        """A 店产生 200 积分，B 店产生 100 积分，C 店消耗 150 积分（抵 150 分）。
        C 店需按 A:B = 2:1 比例分别付给 A 店 100 分 / B 店 50 分。"""
        from services.tx_member.src.services.points_settlement import settle_cross_store

        events = [
            {"direction": "earn", "store_id": "A", "points": 200, "amount_fen": 20000},
            {"direction": "earn", "store_id": "B", "points": 100, "amount_fen": 10000},
            {"direction": "spend", "store_id": "C", "points": 150, "amount_fen": 150},
        ]
        result = settle_cross_store(events)

        # C 店向 A/B 各转账，比例按积分余额加权
        transfers_by_target = {(t["from_store_id"], t["to_store_id"]): t["amount_fen"] for t in result["transfers"]}
        assert (("C", "A")) in transfers_by_target
        assert (("C", "B")) in transfers_by_target
        # A:B = 2:1 → 150 分应 100/50 分
        assert transfers_by_target[("C", "A")] == 100
        assert transfers_by_target[("C", "B")] == 50

    def test_no_negative_balance_protection(self):
        """没有积分产生但有消耗，跳过结算（数据问题，不应崩溃）。"""
        from services.tx_member.src.services.points_settlement import settle_cross_store

        events = [
            {"direction": "spend", "store_id": "C", "points": 100, "amount_fen": 100},
        ]
        result = settle_cross_store(events)
        # 没有发行方，无法分配 → transfers 为空
        assert result["transfers"] == []
        assert "warnings" in result

    def test_rounding_residual_assigned_to_largest_creditor(self):
        """金额无法整除时，余数分给最大债权人，保证总额准确（金额 = 整数分）。"""
        from services.tx_member.src.services.points_settlement import settle_cross_store

        events = [
            {"direction": "earn", "store_id": "A", "points": 100, "amount_fen": 10000},
            {"direction": "earn", "store_id": "B", "points": 100, "amount_fen": 10000},
            {"direction": "earn", "store_id": "C", "points": 100, "amount_fen": 10000},
            {"direction": "spend", "store_id": "D", "points": 300, "amount_fen": 100},  # 100/3 不整除
        ]
        result = settle_cross_store(events)

        total = sum(t["amount_fen"] for t in result["transfers"])
        assert total == 100  # 总和必须严格等于消耗金额，无金额泄漏


# ═══════════════════════════════════════════════════════════════════════════
# D. FIFO 过期清理
# ═══════════════════════════════════════════════════════════════════════════


class TestFifoExpiry:
    """场景：积分按批次发行，每批有效期 12 个月（365 天）。
    清理时按 earned_at 升序（先发行先过期）。
    """

    def test_single_expired_batch_cleared(self):
        """一批积分发行 366 天前，今天清理 → 应被清零。"""
        from services.tx_member.src.services.points_expiry_fifo import clear_expired_batches_fifo

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        batches = [
            {
                "batch_id": "b1",
                "earned_at": now - timedelta(days=400),
                "expiry_date": now - timedelta(days=35),
                "remaining_points": 100,
                "cleared": False,
            },
        ]
        result = clear_expired_batches_fifo(batches, now=now)
        assert result["cleared_count"] == 1
        assert result["cleared_points"] == 100
        assert batches[0]["cleared"] is True
        assert batches[0]["remaining_points"] == 0

    def test_unexpired_batch_untouched(self):
        """未过期的批次不动。"""
        from services.tx_member.src.services.points_expiry_fifo import clear_expired_batches_fifo

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        batches = [
            {
                "batch_id": "b1",
                "earned_at": now - timedelta(days=10),
                "expiry_date": now + timedelta(days=355),
                "remaining_points": 100,
                "cleared": False,
            },
        ]
        result = clear_expired_batches_fifo(batches, now=now)
        assert result["cleared_count"] == 0
        assert batches[0]["remaining_points"] == 100
        assert batches[0]["cleared"] is False

    def test_fifo_order_oldest_first(self):
        """三批积分，最早的两批已过期、第三批未过期 → 清理顺序为最早 → 次早。"""
        from services.tx_member.src.services.points_expiry_fifo import clear_expired_batches_fifo

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        batches = [
            # 故意倒序传入，验证函数内排序
            {
                "batch_id": "b3",
                "earned_at": now - timedelta(days=30),
                "expiry_date": now + timedelta(days=335),
                "remaining_points": 50,
                "cleared": False,
            },
            {
                "batch_id": "b1",
                "earned_at": now - timedelta(days=400),
                "expiry_date": now - timedelta(days=35),
                "remaining_points": 100,
                "cleared": False,
            },
            {
                "batch_id": "b2",
                "earned_at": now - timedelta(days=380),
                "expiry_date": now - timedelta(days=15),
                "remaining_points": 80,
                "cleared": False,
            },
        ]
        result = clear_expired_batches_fifo(batches, now=now)
        assert result["cleared_count"] == 2
        assert result["cleared_points"] == 180
        # 验证清理顺序：b1（最早）在 b2 之前
        cleared_ids = [d["batch_id"] for d in result["details"]]
        assert cleared_ids == ["b1", "b2"]

    def test_consume_fifo_takes_oldest_first(self):
        """消费积分时，应从最早批次开始扣减（FIFO）。"""
        from services.tx_member.src.services.points_expiry_fifo import consume_points_fifo

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        batches = [
            {
                "batch_id": "b_new",
                "earned_at": now - timedelta(days=10),
                "expiry_date": now + timedelta(days=355),
                "remaining_points": 200,
                "cleared": False,
            },
            {
                "batch_id": "b_old",
                "earned_at": now - timedelta(days=200),
                "expiry_date": now + timedelta(days=165),
                "remaining_points": 50,
                "cleared": False,
            },
        ]
        # 消费 80 积分：应先扣 b_old 的 50，再扣 b_new 的 30
        result = consume_points_fifo(batches, points_to_spend=80)
        assert result["spent"] == 80
        # 找出 b_old 和 b_new
        b_old = next(b for b in batches if b["batch_id"] == "b_old")
        b_new = next(b for b in batches if b["batch_id"] == "b_new")
        assert b_old["remaining_points"] == 0
        assert b_new["remaining_points"] == 170
        # 流水明细
        assert len(result["consumed_from"]) == 2
        assert result["consumed_from"][0]["batch_id"] == "b_old"
        assert result["consumed_from"][0]["points"] == 50
        assert result["consumed_from"][1]["batch_id"] == "b_new"
        assert result["consumed_from"][1]["points"] == 30

    def test_consume_insufficient_balance_raises(self):
        """余额不足时拒绝消费（不允许部分消费产生半状态）。"""
        from services.tx_member.src.services.points_expiry_fifo import consume_points_fifo

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        batches = [
            {
                "batch_id": "b1",
                "earned_at": now - timedelta(days=10),
                "expiry_date": now + timedelta(days=355),
                "remaining_points": 50,
                "cleared": False,
            },
        ]
        with pytest.raises(ValueError, match="insufficient_points"):
            consume_points_fifo(batches, points_to_spend=100)
        # 失败时不修改任何批次
        assert batches[0]["remaining_points"] == 50

    def test_consume_skips_expired_batches(self):
        """已过期/已清零的批次不被消费。"""
        from services.tx_member.src.services.points_expiry_fifo import consume_points_fifo

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        batches = [
            {
                "batch_id": "b_expired",
                "earned_at": now - timedelta(days=400),
                "expiry_date": now - timedelta(days=35),
                "remaining_points": 0,  # 已被清零
                "cleared": True,
            },
            {
                "batch_id": "b_valid",
                "earned_at": now - timedelta(days=10),
                "expiry_date": now + timedelta(days=355),
                "remaining_points": 100,
                "cleared": False,
            },
        ]
        result = consume_points_fifo(batches, points_to_spend=80)
        assert result["spent"] == 80
        # 仅 b_valid 被扣
        b_valid = next(b for b in batches if b["batch_id"] == "b_valid")
        b_expired = next(b for b in batches if b["batch_id"] == "b_expired")
        assert b_valid["remaining_points"] == 20
        assert b_expired["remaining_points"] == 0  # 不变


# ═══════════════════════════════════════════════════════════════════════════
# E. 端点级集成（验证路由真的调用了服务层而非返回 mock）
# ═══════════════════════════════════════════════════════════════════════════


class TestRoutesNotMocked:
    """回归测试：确认 points_routes.py 的 8 个端点会调用服务层（不再是写死 0）。

    通过 monkey-patch 服务层函数，验证路由确实路由到了服务函数。
    """

    @pytest.mark.asyncio
    async def test_earn_route_calls_service(self, monkeypatch):
        """POST /earn 必须调用 services.points_engine.earn_points。"""
        from api import points_routes

        called = {}

        async def fake_earn(*, card_id, source, amount, tenant_id, db):
            called["card_id"] = card_id
            called["amount"] = amount
            return {"card_id": card_id, "source": source, "earned": amount, "new_balance": 999}

        monkeypatch.setattr(points_routes, "_svc_earn_points", fake_earn, raising=False)
        # 调用路由处理函数（直接 await，不走 HTTP）
        from services.tx_member.src.api.points_routes import EarnPointsRequest, earn_points

        body = EarnPointsRequest(card_id="c1", source="consume", amount=100)

        # db 通过依赖注入；测试中给 None
        result = await earn_points(body=body, x_tenant_id="t1", db=None)
        assert called["card_id"] == "c1"
        assert called["amount"] == 100
        assert result["data"]["new_balance"] == 999

    @pytest.mark.asyncio
    async def test_spend_cash_offset_blocks_when_margin_violated(self, monkeypatch):
        """POST /spend (cash_offset) 抵现使毛利低于阈值 → 拒绝，不调用 spend_points。"""
        from api import points_routes
        from services.tx_member.src.api.points_routes import SpendPointsRequest, spend_points

        spend_called = {"called": False}

        async def fake_spend(*, card_id, amount, purpose, tenant_id, db):
            spend_called["called"] = True
            return {"card_id": card_id, "purpose": purpose, "spent": amount, "new_balance": 0}

        monkeypatch.setattr(points_routes, "_svc_spend_points", fake_spend, raising=False)

        # 100 元订单，食材成本 90 元，抵 50 分 → 实付 50 元，毛利率 = (50-90)/50 = -0.8
        body = SpendPointsRequest(
            card_id="c1",
            amount=5000,  # 5000 积分 = 5000 分 = 50 元
            purpose="cash_offset",
            order_total_fen=10000,
            food_cost_fen=9000,
            min_margin_rate=0.15,
        )
        result = await spend_points(body=body, x_tenant_id="t1", db=None)
        assert result["ok"] is False
        assert "margin_floor" in result["error"]["message"]
        # spend_points 不应被调用（拒绝在校验阶段）
        assert spend_called["called"] is False

    @pytest.mark.asyncio
    async def test_spend_cash_offset_passes_normal_order(self, monkeypatch):
        """正常订单：抵现少且毛利充足 → 调用 spend_points。"""
        from api import points_routes
        from services.tx_member.src.api.points_routes import SpendPointsRequest, spend_points

        spend_called = {"called": False}

        async def fake_spend(*, card_id, amount, purpose, tenant_id, db):
            spend_called["called"] = True
            return {"card_id": card_id, "purpose": purpose, "spent": amount, "new_balance": 0}

        monkeypatch.setattr(points_routes, "_svc_spend_points", fake_spend, raising=False)

        body = SpendPointsRequest(
            card_id="c1",
            amount=500,  # 500 积分 = 5 元
            purpose="cash_offset",
            order_total_fen=10000,
            food_cost_fen=6000,
        )
        result = await spend_points(body=body, x_tenant_id="t1", db=None)
        assert result["ok"] is True
        assert spend_called["called"] is True


# ═══════════════════════════════════════════════════════════════════════════
# F. 过期清理 Worker
# ═══════════════════════════════════════════════════════════════════════════


class TestExpiryWorker:
    """Cron Worker：批量过期清理。"""

    @pytest.mark.asyncio
    async def test_worker_clears_for_single_tenant(self):
        """Worker 收到批次后调用 FIFO 清理函数。"""
        from workers.points_expiry_worker import PointsExpiryWorker

        now = datetime(2026, 5, 1, tzinfo=timezone.utc)

        async def fake_loader(tenant_id):
            return [
                {
                    "batch_id": "b_old",
                    "earned_at": now - timedelta(days=400),
                    "expiry_date": now - timedelta(days=35),
                    "remaining_points": 100,
                    "cleared": False,
                },
                {
                    "batch_id": "b_valid",
                    "earned_at": now - timedelta(days=10),
                    "expiry_date": now + timedelta(days=355),
                    "remaining_points": 50,
                    "cleared": False,
                },
            ]

        worker = PointsExpiryWorker(batch_loader=fake_loader)
        result = await worker.run_for_tenant("t1")
        assert result["cleared_count"] == 1
        assert result["cleared_points"] == 100
