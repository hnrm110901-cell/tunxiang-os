"""催菜SLA闭环测试

覆盖场景：
1. 厨师确认催菜并设置承诺时间
2. 承诺时间同步到web-crew
3. 同一菜品30分钟内催菜超2次被限流
4. 承诺时间到期未完成触发升级告警
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
DEPT_ID = _uid()
ORDER_ID = _uid()
DISH_ID = _uid()


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


def _fake_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult())
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_task(status="cooking", rush_count=0, last_rush_at=None):
    task = MagicMock()
    task.id = uuid.UUID(_uid())
    task.status = status
    task.rush_count = rush_count
    task.last_rush_at = last_rush_at
    task.promised_at = None
    task.dept_id = uuid.UUID(DEPT_ID)
    task.order_item_id = uuid.UUID(_uid())
    task.priority = "normal"
    return task


# ─── 场景1: 厨师确认催菜并设置承诺时间 ───

class TestConfirmRush:

    @pytest.mark.asyncio
    async def test_confirm_rush_sets_promised_at(self):
        """厨师确认催菜后，promised_at被设置为当前时间+承诺分钟数"""
        from services.kds_actions import confirm_rush

        task_id = _uid()
        db = _fake_db()
        fake_task = _make_task(status="cooking")
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task))

        with patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await confirm_rush(task_id, promised_minutes=10, operator_id="chef_1",
                                        db=db, tenant_id=TENANT_ID)

        assert result["ok"] is True
        assert result["data"]["promised_minutes"] == 10
        # promised_at应被设置
        assert fake_task.promised_at is not None
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_confirm_rush_on_done_task_fails(self):
        """已完成的任务无法确认催菜"""
        from services.kds_actions import confirm_rush

        task_id = _uid()
        db = _fake_db()
        fake_task = _make_task(status="done")
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task))

        result = await confirm_rush(task_id, promised_minutes=5, operator_id="chef_1",
                                    db=db, tenant_id=TENANT_ID)

        assert result["ok"] is False
        assert "done" in result["error"] or "完成" in result["error"]
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_rush_task_not_found(self):
        """任务不存在时返回错误"""
        from services.kds_actions import confirm_rush

        db = _fake_db()
        db.execute = AsyncMock(return_value=FakeResult(scalar=None))

        result = await confirm_rush(_uid(), promised_minutes=5, operator_id="chef_1",
                                    db=db, tenant_id=TENANT_ID)

        assert result["ok"] is False


# ─── 场景2: 承诺时间同步到web-crew ───

class TestRushSLAPush:

    @pytest.mark.asyncio
    async def test_confirm_rush_pushes_to_web_crew(self):
        """确认催菜后推送promised_at到web-crew（通过KDS推送）"""
        from services.kds_actions import confirm_rush

        task_id = _uid()
        db = _fake_db()
        fake_task = _make_task(status="cooking")
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task))

        push_calls = []

        async def mock_push(station_id, message):
            push_calls.append({"station_id": station_id, "message": message})
            return True

        with patch("services.kds_actions._push_to_kds_station", side_effect=mock_push):
            result = await confirm_rush(task_id, promised_minutes=8, operator_id="chef_1",
                                        db=db, tenant_id=TENANT_ID)

        assert result["ok"] is True
        # 至少有一次推送
        assert len(push_calls) >= 1
        # 推送消息中应包含承诺时间信息
        push_msg = push_calls[0]["message"]
        assert push_msg.get("type") == "rush_confirmed"
        assert "promised_at" in push_msg or "promised_minutes" in push_msg

    @pytest.mark.asyncio
    async def test_push_failure_does_not_block_confirm(self):
        """KDS推送失败不阻塞承诺时间写入DB"""
        from services.kds_actions import confirm_rush

        task_id = _uid()
        db = _fake_db()
        fake_task = _make_task(status="cooking")
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task))

        with patch("services.kds_actions._push_to_kds_station", return_value=False):
            result = await confirm_rush(task_id, promised_minutes=5, operator_id="chef_1",
                                        db=db, tenant_id=TENANT_ID)

        # 即使推送失败，DB写入应成功
        assert result["ok"] is True
        assert db.commit.called


# ─── 场景3: 30分钟内催菜超2次限流 ───

class TestRushRateLimit:

    @pytest.mark.asyncio
    async def test_rush_allowed_when_count_is_zero(self):
        """首次催菜正常通过"""
        from services.kds_actions import request_rush

        db = _fake_db()
        fake_task = _make_task(rush_count=0, last_rush_at=None)

        # 模拟查找到匹配任务
        order_id = ORDER_ID
        dish_id = DISH_ID

        # request_rush查找内存+DB中的任务
        with patch("services.kds_actions._find_active_tasks_for_dish",
                   return_value=[fake_task]), \
             patch("services.kds_actions._resolve_task_context",
                   return_value={
                       "dept_id": DEPT_ID, "dept_name": "热菜间",
                       "printer_address": None, "table_number": "8",
                       "order_no": "T001", "dish_name": "宫保鸡丁", "quantity": 1
                   }), \
             patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await request_rush(order_id, dish_id, db, tenant_id=TENANT_ID)

        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_rush_allowed_at_second_time(self):
        """第2次催菜（30分钟内）正常通过"""
        from services.kds_actions import request_rush

        db = _fake_db()
        last_rush = datetime.now(timezone.utc) - timedelta(minutes=10)
        fake_task = _make_task(rush_count=1, last_rush_at=last_rush)

        with patch("services.kds_actions._find_active_tasks_for_dish",
                   return_value=[fake_task]), \
             patch("services.kds_actions._resolve_task_context",
                   return_value={
                       "dept_id": DEPT_ID, "dept_name": "热菜间",
                       "printer_address": None, "table_number": "8",
                       "order_no": "T001", "dish_name": "宫保鸡丁", "quantity": 1
                   }), \
             patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await request_rush(ORDER_ID, DISH_ID, db, tenant_id=TENANT_ID)

        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_rush_blocked_at_third_time_within_30min(self):
        """第3次催菜在30分钟内被限流拦截"""
        from services.kds_actions import request_rush

        db = _fake_db()
        last_rush = datetime.now(timezone.utc) - timedelta(minutes=5)
        fake_task = _make_task(rush_count=2, last_rush_at=last_rush)

        with patch("services.kds_actions._find_active_tasks_for_dish",
                   return_value=[fake_task]), \
             patch("services.kds_actions._resolve_task_context",
                   return_value={
                       "dept_id": DEPT_ID, "dept_name": "热菜间",
                       "printer_address": None, "table_number": "8",
                       "order_no": "T001", "dish_name": "宫保鸡丁", "quantity": 1
                   }):
            result = await request_rush(ORDER_ID, DISH_ID, db, tenant_id=TENANT_ID)

        assert result["ok"] is False
        assert "限流" in result["error"] or "rate_limit" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_rush_resets_after_30min(self):
        """30分钟后限流重置，可以再次催菜"""
        from services.kds_actions import request_rush

        db = _fake_db()
        # last_rush在35分钟前，超过30分钟窗口，rush_count=2
        last_rush = datetime.now(timezone.utc) - timedelta(minutes=35)
        fake_task = _make_task(rush_count=2, last_rush_at=last_rush)

        with patch("services.kds_actions._find_active_tasks_for_dish",
                   return_value=[fake_task]), \
             patch("services.kds_actions._resolve_task_context",
                   return_value={
                       "dept_id": DEPT_ID, "dept_name": "热菜间",
                       "printer_address": None, "table_number": "8",
                       "order_no": "T001", "dish_name": "宫保鸡丁", "quantity": 1
                   }), \
             patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await request_rush(ORDER_ID, DISH_ID, db, tenant_id=TENANT_ID)

        assert result["ok"] is True


# ─── 场景4: 承诺时间到期触发升级告警 ───

class TestRushOverdue:

    @pytest.mark.asyncio
    async def test_check_overdue_finds_expired_promise(self):
        """承诺时间已过但任务未完成，触发升级告警"""
        from services.kds_actions import check_rush_overdue

        db = _fake_db()
        now = datetime.now(timezone.utc)

        overdue_task = MagicMock()
        overdue_task.id = uuid.UUID(_uid())
        overdue_task.status = "cooking"
        overdue_task.promised_at = now - timedelta(minutes=5)  # 5分钟前到期
        overdue_task.dept_id = uuid.UUID(DEPT_ID)
        overdue_task.rush_count = 1
        overdue_task.tenant_id = uuid.UUID(TENANT_ID)

        db.execute = AsyncMock(return_value=FakeResult(rows=[overdue_task]))

        push_calls = []

        async def mock_push(station_id, message):
            push_calls.append(message)
            return True

        with patch("services.kds_actions._push_to_kds_station", side_effect=mock_push):
            result = await check_rush_overdue(TENANT_ID, db)

        assert result["ok"] is True
        assert result["data"]["overdue_count"] >= 1
        # 应有升级告警推送
        assert len(push_calls) >= 1
        alert_types = [m.get("type") for m in push_calls]
        assert "rush_overdue_alert" in alert_types

    @pytest.mark.asyncio
    async def test_check_overdue_ignores_on_time_tasks(self):
        """承诺时间未到的任务不触发告警"""
        from services.kds_actions import check_rush_overdue

        db = _fake_db()
        now = datetime.now(timezone.utc)

        on_time_task = MagicMock()
        on_time_task.id = uuid.UUID(_uid())
        on_time_task.status = "cooking"
        on_time_task.promised_at = now + timedelta(minutes=5)  # 还有5分钟
        on_time_task.dept_id = uuid.UUID(DEPT_ID)
        on_time_task.rush_count = 1
        on_time_task.tenant_id = uuid.UUID(TENANT_ID)

        # check_rush_overdue只查promised_at < NOW()的任务
        db.execute = AsyncMock(return_value=FakeResult(rows=[]))

        with patch("services.kds_actions._push_to_kds_station", return_value=True) as mock_push:
            result = await check_rush_overdue(TENANT_ID, db)

        assert result["ok"] is True
        assert result["data"]["overdue_count"] == 0

    @pytest.mark.asyncio
    async def test_check_overdue_no_promised_at_skipped(self):
        """没有承诺时间的任务不参与超时检查"""
        from services.kds_actions import check_rush_overdue

        db = _fake_db()
        # 没有promised_at的任务不会出现在查询结果中（SQL: promised_at IS NOT NULL）
        db.execute = AsyncMock(return_value=FakeResult(rows=[]))

        result = await check_rush_overdue(TENANT_ID, db)

        assert result["ok"] is True
        assert result["data"]["overdue_count"] == 0
