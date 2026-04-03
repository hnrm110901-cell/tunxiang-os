"""KDS任务DB持久化测试

覆盖场景：
1. 创建任务后能从DB查询到
2. 状态变更后DB记录更新
3. Mac mini重启场景：从DB恢复pending/cooking任务
4. tenant_id隔离：不同租户看不到彼此的任务
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_A = _uid()
TENANT_B = _uid()
DEPT_ID = _uid()
ORDER_ITEM_ID = _uid()


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


# ─── 场景1: 创建任务后能从DB查询到 ───

class TestTaskCreation:

    @pytest.mark.asyncio
    async def test_start_cooking_writes_db(self):
        """开始制作时同步写入kds_tasks表"""
        from services.kds_actions import start_cooking

        task_id = _uid()
        operator_id = _uid()
        db = _fake_db()

        # 模拟DB中已有pending记录
        fake_task_row = MagicMock()
        fake_task_row.status = "pending"
        fake_task_row.id = uuid.UUID(task_id)
        fake_task_row.tenant_id = uuid.UUID(TENANT_A)
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task_row))

        with patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await start_cooking(task_id, operator_id, db, tenant_id=TENANT_A)

        assert result["ok"] is True
        # 应调用DB execute（查询）和commit（更新）
        assert db.execute.called
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_finish_cooking_updates_db(self):
        """完成出品时更新DB记录状态为done"""
        from services.kds_actions import finish_cooking

        task_id = _uid()
        operator_id = _uid()
        db = _fake_db()

        fake_task_row = MagicMock()
        fake_task_row.status = "cooking"
        fake_task_row.started_at = datetime.now(timezone.utc)
        fake_task_row.id = uuid.UUID(task_id)
        fake_task_row.dept_id = None
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task_row))

        with patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await finish_cooking(task_id, operator_id, db, tenant_id=TENANT_A)

        assert result["ok"] is True
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_task_not_found_returns_error(self):
        """任务不存在时返回明确错误"""
        from services.kds_actions import start_cooking

        task_id = _uid()
        db = _fake_db()
        db.execute = AsyncMock(return_value=FakeResult(scalar=None))

        result = await start_cooking(task_id, "op1", db, tenant_id=TENANT_A)

        assert result["ok"] is False
        assert "不存在" in result["error"] or "not found" in result["error"].lower()


# ─── 场景2: 状态变更后DB记录更新 ───

class TestStateTransition:

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self):
        """非法状态流转被拒绝（done -> cooking）"""
        from services.kds_actions import start_cooking

        task_id = _uid()
        db = _fake_db()

        fake_task_row = MagicMock()
        fake_task_row.status = "done"  # 已完成，不能再开始
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task_row))

        result = await start_cooking(task_id, "op1", db, tenant_id=TENANT_A)

        assert result["ok"] is False
        # 状态非法时不应提交
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_finish_cooking_records_duration(self):
        """完成出品时记录制作耗时"""
        from datetime import timedelta

        from services.kds_actions import finish_cooking

        task_id = _uid()
        db = _fake_db()

        started = datetime.now(timezone.utc) - timedelta(minutes=5)
        fake_task_row = MagicMock()
        fake_task_row.status = "cooking"
        fake_task_row.started_at = started
        fake_task_row.dept_id = None
        db.execute = AsyncMock(return_value=FakeResult(scalar=fake_task_row))

        with patch("services.kds_actions._push_to_kds_station", return_value=True):
            result = await finish_cooking(task_id, "op1", db, tenant_id=TENANT_A)

        assert result["ok"] is True
        duration = result["data"].get("duration_sec", 0)
        # 5分钟 ≈ 300秒，允许±10秒误差
        assert 290 <= duration <= 310


# ─── 场景3: Mac mini重启恢复 ───

class TestRecoveryOnRestart:

    @pytest.mark.asyncio
    async def test_recover_active_tasks_from_db(self):
        """从DB恢复pending/cooking任务（模拟重启后内存为空）"""
        from services.kds_actions import recover_active_tasks

        db = _fake_db()
        tenant_id = TENANT_A

        t1 = MagicMock()
        t1.id = uuid.UUID(_uid())
        t1.status = "pending"
        t1.dept_id = uuid.UUID(DEPT_ID)
        t1.priority = "normal"
        t1.rush_count = 0
        t1.remake_count = 0
        t1.started_at = None
        t1.promised_at = None

        t2 = MagicMock()
        t2.id = uuid.UUID(_uid())
        t2.status = "cooking"
        t2.dept_id = uuid.UUID(DEPT_ID)
        t2.priority = "rush"
        t2.rush_count = 1
        t2.remake_count = 0
        t2.started_at = datetime.now(timezone.utc)
        t2.promised_at = None

        db.execute = AsyncMock(return_value=FakeResult(rows=[t1, t2]))

        result = await recover_active_tasks(tenant_id, db)

        assert result["ok"] is True
        assert result["data"]["recovered"] == 2

    @pytest.mark.asyncio
    async def test_recovery_excludes_done_tasks(self):
        """恢复时不加载已完成/取消的任务"""
        from services.kds_actions import recover_active_tasks

        db = _fake_db()
        # DB只返回active任务（SQL WHERE status IN (pending, cooking)）
        db.execute = AsyncMock(return_value=FakeResult(rows=[]))

        result = await recover_active_tasks(TENANT_A, db)

        assert result["ok"] is True
        assert result["data"]["recovered"] == 0


# ─── 场景4: tenant_id隔离 ───

class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_access_tenant_b_task(self):
        """租户A无法访问租户B的任务"""
        from services.kds_actions import start_cooking

        task_id_b = _uid()
        db = _fake_db()

        # 模拟DB查询带tenant_id过滤后返回None（RLS隔离）
        db.execute = AsyncMock(return_value=FakeResult(scalar=None))

        result = await start_cooking(task_id_b, "op_a", db, tenant_id=TENANT_A)

        # 应返回错误，而非修改成功
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_query_includes_tenant_filter(self):
        """DB查询必须包含tenant_id过滤条件"""
        from services.kds_actions import start_cooking

        task_id = _uid()
        db = _fake_db()
        db.execute = AsyncMock(return_value=FakeResult(scalar=None))

        await start_cooking(task_id, "op1", db, tenant_id=TENANT_A)

        # 验证execute被调用（查询带了tenant条件）
        assert db.execute.called
        # 获取第一次调用的参数（SELECT查询）
        call_args = db.execute.call_args_list[0]
        stmt = call_args[0][0]
        # SQLAlchemy语句的字符串化应包含tenant_id
        stmt_str = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "tenant_id" in stmt_str
