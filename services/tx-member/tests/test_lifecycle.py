"""会员生命周期自动化测试

覆盖：
1. 新客分类：首次消费 ≤7 天
2. 活跃分类：过去 30 天有消费
3. 沉睡分类：30-90 天无消费
4. 流失分类：90 天以上无消费
5. 批量重分类：扫描全体会员更新 lifecycle_stage
6. 触发营销：沉睡会员自动发挽回券（调用 coupon_engine）
7. 流失会员推送企微消息（调用 social_routes）
8. 生命周期事件记录（分类变更历史）
9. tenant_id 隔离
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# 将 src 加入路径（适配 tunxiang-os 项目结构）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 被测模块
from services.lifecycle_service import (  # noqa: E402
    LifecycleService,
    LifecycleStage,
)


# ── 工具 ──────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


def _make_customer(
    *,
    first_order_at: datetime,
    last_order_at: datetime,
    lifecycle_stage: str = "new",
    customer_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": customer_id or str(uuid.uuid4()),
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "lifecycle_stage": lifecycle_stage,
        "first_order_at": first_order_at,
        "last_order_at": last_order_at,
    }


# ── Fixture ───────────────────────────────────────────────────

@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def other_tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def service() -> LifecycleService:
    return LifecycleService()


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ── 1. 新客分类 ───────────────────────────────────────────────


class TestClassifyNew:
    @pytest.mark.asyncio
    async def test_new_member_first_order_today(self, service, tenant_id):
        """首次消费当天 → new"""
        customer = _make_customer(
            first_order_at=_days_ago(0),
            last_order_at=_days_ago(0),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.NEW

    @pytest.mark.asyncio
    async def test_new_member_within_7_days(self, service, tenant_id):
        """首次消费后第 6 天 → new"""
        customer = _make_customer(
            first_order_at=_days_ago(6),
            last_order_at=_days_ago(6),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.NEW

    @pytest.mark.asyncio
    async def test_new_member_exactly_7_days(self, service, tenant_id):
        """首次消费恰好第 7 天 → new（边界值，含 7 天）"""
        customer = _make_customer(
            first_order_at=_days_ago(7),
            last_order_at=_days_ago(7),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.NEW

    @pytest.mark.asyncio
    async def test_not_new_after_8_days(self, service, tenant_id):
        """首次消费 8 天后，且最近有消费 → active"""
        customer = _make_customer(
            first_order_at=_days_ago(8),
            last_order_at=_days_ago(2),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.ACTIVE


# ── 2. 活跃分类 ───────────────────────────────────────────────


class TestClassifyActive:
    @pytest.mark.asyncio
    async def test_active_last_purchase_today(self, service, tenant_id):
        """今天消费 → active"""
        customer = _make_customer(
            first_order_at=_days_ago(60),
            last_order_at=_days_ago(0),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.ACTIVE

    @pytest.mark.asyncio
    async def test_active_within_30_days(self, service, tenant_id):
        """29 天前消费 → active"""
        customer = _make_customer(
            first_order_at=_days_ago(90),
            last_order_at=_days_ago(29),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.ACTIVE

    @pytest.mark.asyncio
    async def test_active_exactly_30_days(self, service, tenant_id):
        """恰好 30 天前消费 → active（含 30 天边界）"""
        customer = _make_customer(
            first_order_at=_days_ago(90),
            last_order_at=_days_ago(30),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.ACTIVE


# ── 3. 沉睡分类 ───────────────────────────────────────────────


class TestClassifyDormant:
    @pytest.mark.asyncio
    async def test_dormant_31_days(self, service, tenant_id):
        """31 天前消费 → dormant"""
        customer = _make_customer(
            first_order_at=_days_ago(120),
            last_order_at=_days_ago(31),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.DORMANT

    @pytest.mark.asyncio
    async def test_dormant_60_days(self, service, tenant_id):
        """60 天前消费 → dormant"""
        customer = _make_customer(
            first_order_at=_days_ago(180),
            last_order_at=_days_ago(60),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.DORMANT

    @pytest.mark.asyncio
    async def test_dormant_exactly_90_days(self, service, tenant_id):
        """恰好 90 天前消费 → dormant（90 天含在沉睡区间）"""
        customer = _make_customer(
            first_order_at=_days_ago(180),
            last_order_at=_days_ago(90),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.DORMANT


# ── 4. 流失分类 ───────────────────────────────────────────────


class TestClassifyChurned:
    @pytest.mark.asyncio
    async def test_churned_91_days(self, service, tenant_id):
        """91 天前消费 → churned"""
        customer = _make_customer(
            first_order_at=_days_ago(200),
            last_order_at=_days_ago(91),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.CHURNED

    @pytest.mark.asyncio
    async def test_churned_1_year(self, service, tenant_id):
        """365 天前消费 → churned"""
        customer = _make_customer(
            first_order_at=_days_ago(400),
            last_order_at=_days_ago(365),
            tenant_id=tenant_id,
        )
        stage = service._compute_stage(customer)
        assert stage == LifecycleStage.CHURNED


# ── 5. 批量重分类 ─────────────────────────────────────────────


class TestBatchReclassify:
    @pytest.mark.asyncio
    async def test_batch_reclassify_returns_summary(self, service, tenant_id, mock_db):
        """批量重分类返回含各阶段统计的字典"""
        customers = [
            _make_customer(
                first_order_at=_days_ago(3),
                last_order_at=_days_ago(3),
                lifecycle_stage="new",
                tenant_id=tenant_id,
            ),
            _make_customer(
                first_order_at=_days_ago(60),
                last_order_at=_days_ago(10),
                lifecycle_stage="active",
                tenant_id=tenant_id,
            ),
            _make_customer(
                first_order_at=_days_ago(120),
                last_order_at=_days_ago(45),
                lifecycle_stage="active",  # 应变为 dormant
                tenant_id=tenant_id,
            ),
            _make_customer(
                first_order_at=_days_ago(200),
                last_order_at=_days_ago(100),
                lifecycle_stage="dormant",  # 应变为 churned
                tenant_id=tenant_id,
            ),
        ]

        with patch.object(service, "_fetch_all_members", return_value=customers), \
             patch.object(service, "_update_member_stage", new_callable=AsyncMock), \
             patch.object(service, "_record_event", new_callable=AsyncMock), \
             patch.object(service, "trigger_intervention", new_callable=AsyncMock):
            result = await service.batch_reclassify(tenant_id, mock_db)

        assert "new" in result
        assert "active" in result
        assert "dormant" in result
        assert "churned" in result
        assert "changed" in result
        assert result["new"] == 1
        assert result["active"] == 1
        assert result["dormant"] == 1
        assert result["churned"] == 1
        assert result["changed"] == 2  # dormant 和 churned 发生了变更

    @pytest.mark.asyncio
    async def test_batch_reclassify_records_events_for_changed(
        self, service, tenant_id, mock_db
    ):
        """批量重分类：只对阶段变更的会员记录事件"""
        cid = str(uuid.uuid4())
        customers = [
            _make_customer(
                first_order_at=_days_ago(120),
                last_order_at=_days_ago(45),
                lifecycle_stage="active",  # active → dormant，有变更
                customer_id=cid,
                tenant_id=tenant_id,
            ),
        ]

        record_event_mock = AsyncMock()
        trigger_mock = AsyncMock()

        with patch.object(service, "_fetch_all_members", return_value=customers), \
             patch.object(service, "_update_member_stage", new_callable=AsyncMock), \
             patch.object(service, "_record_event", record_event_mock), \
             patch.object(service, "trigger_intervention", trigger_mock):
            await service.batch_reclassify(tenant_id, mock_db)

        record_event_mock.assert_called_once()
        call_kwargs = record_event_mock.call_args
        assert call_kwargs.kwargs["from_stage"] == "active"
        assert call_kwargs.kwargs["to_stage"] == LifecycleStage.DORMANT


# ── 6. 沉睡会员触发挽回券 ─────────────────────────────────────


class TestTriggerIntervention:
    @pytest.mark.asyncio
    async def test_dormant_triggers_coupon(self, service, tenant_id, mock_db):
        """沉睡会员 → 自动发挽回优惠券"""
        member_id = str(uuid.uuid4())
        config = {
            "stage": "dormant",
            "auto_action": "coupon",
            "coupon_template_id": str(uuid.uuid4()),
            "message_template": None,
            "is_active": True,
        }

        with patch.object(service, "_get_lifecycle_config", return_value=config), \
             patch.object(
                 service, "_issue_coupon_to_member", new_callable=AsyncMock
             ) as mock_issue, \
             patch.object(
                 service, "_send_wecom_message", new_callable=AsyncMock
             ) as mock_wecom:
            result = await service.trigger_intervention(
                member_id=member_id,
                new_stage=LifecycleStage.DORMANT,
                tenant_id=tenant_id,
                db=mock_db,
            )

        mock_issue.assert_called_once()
        mock_wecom.assert_not_called()
        assert result["action_taken"] == "coupon_sent"

    @pytest.mark.asyncio
    async def test_intervention_failure_does_not_block(
        self, service, tenant_id, mock_db
    ):
        """营销触发失败不阻塞分类流程"""
        member_id = str(uuid.uuid4())
        config = {
            "stage": "dormant",
            "auto_action": "coupon",
            "coupon_template_id": str(uuid.uuid4()),
            "message_template": None,
            "is_active": True,
        }

        with patch.object(service, "_get_lifecycle_config", return_value=config), \
             patch.object(
                 service,
                 "_issue_coupon_to_member",
                 side_effect=RuntimeError("coupon API down"),
             ):
            # 不抛出异常
            result = await service.trigger_intervention(
                member_id=member_id,
                new_stage=LifecycleStage.DORMANT,
                tenant_id=tenant_id,
                db=mock_db,
            )

        assert result["action_taken"] == "none"
        assert "error" in result


# ── 7. 流失会员推送企微 ────────────────────────────────────────


class TestChurnedWecom:
    @pytest.mark.asyncio
    async def test_churned_triggers_wecom_and_large_coupon(
        self, service, tenant_id, mock_db
    ):
        """流失会员 → 企微消息 + 大额复活券"""
        member_id = str(uuid.uuid4())
        config = {
            "stage": "churned",
            "auto_action": "wecom_message",
            "coupon_template_id": str(uuid.uuid4()),
            "message_template": "亲，好久不见，送您一张大额券！",
            "is_active": True,
        }

        with patch.object(service, "_get_lifecycle_config", return_value=config), \
             patch.object(
                 service, "_send_wecom_message", new_callable=AsyncMock
             ) as mock_wecom, \
             patch.object(
                 service, "_issue_coupon_to_member", new_callable=AsyncMock
             ) as mock_issue:
            result = await service.trigger_intervention(
                member_id=member_id,
                new_stage=LifecycleStage.CHURNED,
                tenant_id=tenant_id,
                db=mock_db,
            )

        mock_wecom.assert_called_once()
        mock_issue.assert_called_once()
        assert "wecom" in result["action_taken"]

    @pytest.mark.asyncio
    async def test_wecom_failure_does_not_block(self, service, tenant_id, mock_db):
        """企微推送失败记录日志但不阻塞"""
        member_id = str(uuid.uuid4())
        config = {
            "stage": "churned",
            "auto_action": "wecom_message",
            "coupon_template_id": None,
            "message_template": "我们想你了",
            "is_active": True,
        }

        with patch.object(service, "_get_lifecycle_config", return_value=config), \
             patch.object(
                 service,
                 "_send_wecom_message",
                 side_effect=RuntimeError("企微 API 超时"),
             ):
            result = await service.trigger_intervention(
                member_id=member_id,
                new_stage=LifecycleStage.CHURNED,
                tenant_id=tenant_id,
                db=mock_db,
            )

        assert result["action_taken"] == "none"
        assert "error" in result


# ── 8. 生命周期事件记录 ────────────────────────────────────────


class TestLifecycleEventRecording:
    @pytest.mark.asyncio
    async def test_record_event_stores_stage_change(
        self, service, tenant_id, mock_db
    ):
        """阶段变更时记录 lifecycle_events"""
        member_id = str(uuid.uuid4())

        with patch.object(
            service, "_insert_lifecycle_event", new_callable=AsyncMock
        ) as mock_insert:
            await service._record_event(
                member_id=member_id,
                tenant_id=tenant_id,
                from_stage="active",
                to_stage=LifecycleStage.DORMANT,
                trigger_reason="days_since_last_visit=45",
                action_taken="coupon_sent",
                db=mock_db,
            )

        mock_insert.assert_called_once()
        call_kwargs = mock_insert.call_args.kwargs
        assert call_kwargs["from_stage"] == "active"
        assert call_kwargs["to_stage"] == LifecycleStage.DORMANT
        assert "days_since_last_visit" in call_kwargs["trigger_reason"]

    @pytest.mark.asyncio
    async def test_reactivated_stage_recorded(self, service, tenant_id, mock_db):
        """流失→再次消费 → reactivated 阶段记录"""
        member_id = str(uuid.uuid4())

        with patch.object(
            service, "_insert_lifecycle_event", new_callable=AsyncMock
        ) as mock_insert:
            await service._record_event(
                member_id=member_id,
                tenant_id=tenant_id,
                from_stage="churned",
                to_stage=LifecycleStage.REACTIVATED,
                trigger_reason="new_order_detected",
                action_taken="welcome_gift_sent",
                db=mock_db,
            )

        call_kwargs = mock_insert.call_args.kwargs
        assert call_kwargs["to_stage"] == LifecycleStage.REACTIVATED


# ── 9. tenant_id 隔离 ─────────────────────────────────────────


class TestTenantIsolation:
    def test_compute_stage_is_pure_no_db(self, service):
        """_compute_stage 是纯函数，不依赖 DB"""
        t1 = str(uuid.uuid4())
        t2 = str(uuid.uuid4())
        c1 = _make_customer(
            first_order_at=_days_ago(5),
            last_order_at=_days_ago(5),
            tenant_id=t1,
        )
        c2 = _make_customer(
            first_order_at=_days_ago(100),
            last_order_at=_days_ago(100),
            tenant_id=t2,
        )
        assert service._compute_stage(c1) == LifecycleStage.NEW
        assert service._compute_stage(c2) == LifecycleStage.CHURNED

    @pytest.mark.asyncio
    async def test_batch_reclassify_filters_by_tenant(
        self, service, tenant_id, other_tenant_id, mock_db
    ):
        """批量重分类只处理指定 tenant 的会员"""
        own_customer = _make_customer(
            first_order_at=_days_ago(60),
            last_order_at=_days_ago(45),
            lifecycle_stage="active",
            tenant_id=tenant_id,
        )

        with patch.object(
            service, "_fetch_all_members", return_value=[own_customer]
        ) as mock_fetch, \
             patch.object(service, "_update_member_stage", new_callable=AsyncMock), \
             patch.object(service, "_record_event", new_callable=AsyncMock), \
             patch.object(service, "trigger_intervention", new_callable=AsyncMock):
            await service.batch_reclassify(tenant_id, mock_db)

        # _fetch_all_members 应使用 tenant_id 参数过滤
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args.kwargs.get("tenant_id") == tenant_id or \
               call_args.args[0] == tenant_id

    @pytest.mark.asyncio
    async def test_get_lifecycle_stats_scoped_to_tenant(
        self, service, tenant_id, mock_db
    ):
        """get_lifecycle_stats 返回的统计数据范围限定在指定 tenant"""
        mock_result = {
            "new": 5,
            "active": 20,
            "dormant": 8,
            "churned": 3,
            "reactivated": 2,
            "total": 38,
        }

        with patch.object(
            service, "_query_stage_counts", new_callable=AsyncMock,
            return_value=mock_result
        ):
            stats = await service.get_lifecycle_stats(
                tenant_id=tenant_id, db=mock_db
            )

        assert stats["total"] == 38
        assert stats["new"] == 5


# ── 补充：get_lifecycle_stats 占比计算 ────────────────────────


class TestLifecycleStats:
    @pytest.mark.asyncio
    async def test_stats_includes_ratios(self, service, tenant_id, mock_db):
        """统计结果包含各阶段占比"""
        mock_result = {
            "new": 10,
            "active": 40,
            "dormant": 30,
            "churned": 20,
            "reactivated": 0,
            "total": 100,
        }

        with patch.object(
            service, "_query_stage_counts", new_callable=AsyncMock,
            return_value=mock_result
        ):
            stats = await service.get_lifecycle_stats(
                tenant_id=tenant_id, db=mock_db
            )

        assert "ratios" in stats
        assert abs(stats["ratios"]["active"] - 0.4) < 0.001

    @pytest.mark.asyncio
    async def test_stats_with_store_filter(self, service, tenant_id, mock_db):
        """传入 store_id 时统计限定到门店维度"""
        store_id = str(uuid.uuid4())
        mock_result = {
            "new": 2, "active": 8, "dormant": 3,
            "churned": 1, "reactivated": 0, "total": 14,
        }

        with patch.object(
            service, "_query_stage_counts", new_callable=AsyncMock,
            return_value=mock_result
        ) as mock_query:
            await service.get_lifecycle_stats(
                tenant_id=tenant_id, store_id=store_id, db=mock_db
            )

        call_kwargs = mock_query.call_args.kwargs
        assert call_kwargs.get("store_id") == store_id
