"""
同步调度器测试 (sync_scheduler.py)

Round 64 Team D — 新增测试覆盖：
  - 三商户并行调度
  - 重试逻辑
  - sync_logs 写入
  - 环境变量配置
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# 路径注入 — gateway/src 含 sync_scheduler.py
_GATEWAY_SRC = os.path.join(
    os.path.dirname(__file__), "..", "services", "gateway", "src"
)
sys.path.insert(0, _GATEWAY_SRC)

# Mock 未安装的第三方依赖（apscheduler / structlog）
# 这样 sync_scheduler 可以在无完整依赖的 CI 环境中被导入
_mock_scheduler_instance = MagicMock()
_mock_scheduler_instance.get_jobs.return_value = []
_mock_scheduler_instance.running = False
_mock_scheduler_instance.timezone = MagicMock(__str__=lambda self: "Asia/Shanghai")

_mock_apscheduler = MagicMock()
_mock_apscheduler.schedulers.asyncio.AsyncIOScheduler.return_value = _mock_scheduler_instance

if "apscheduler" not in sys.modules:
    sys.modules["apscheduler"] = _mock_apscheduler
    sys.modules["apscheduler.schedulers"] = _mock_apscheduler.schedulers
    sys.modules["apscheduler.schedulers.asyncio"] = _mock_apscheduler.schedulers.asyncio

if "structlog" not in sys.modules:
    _mock_structlog = MagicMock()
    _mock_structlog.get_logger.return_value = MagicMock(
        bind=lambda **kw: MagicMock(
            info=MagicMock(), warning=MagicMock(), error=MagicMock()
        )
    )
    sys.modules["structlog"] = _mock_structlog


# ─── 辅助工厂 ───────────────────────────────────────────────────────────────

def _make_db_mock() -> AsyncMock:
    """构造符合 AsyncSession 接口的 mock 数据库会话"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()
    return db


# ─── 测试：常量与配置 ────────────────────────────────────────────────────────

class TestSyncSchedulerConstants:
    def test_merchants_list(self):
        """MERCHANTS 列表包含三商户代码"""
        from sync_scheduler import MERCHANTS
        assert set(MERCHANTS) == {"czyz", "zqx", "sgc"}
        assert len(MERCHANTS) == 3

    def test_retry_times_is_three(self):
        """RETRY_TIMES 默认值为 3"""
        from sync_scheduler import RETRY_TIMES
        assert RETRY_TIMES == 3

    def test_retry_delay_seconds(self):
        """RETRY_DELAY_SECONDS 为 300 秒（5分钟）"""
        from sync_scheduler import RETRY_DELAY_SECONDS
        assert RETRY_DELAY_SECONDS == 300

    def test_tenant_id_env_keys(self):
        """_TENANT_ID_ENVS 映射覆盖所有三商户"""
        from sync_scheduler import _TENANT_ID_ENVS
        assert "czyz" in _TENANT_ID_ENVS
        assert "zqx" in _TENANT_ID_ENVS
        assert "sgc" in _TENANT_ID_ENVS

    def test_get_tenant_id_from_env(self):
        """_get_tenant_id 从环境变量正确读取租户ID"""
        from sync_scheduler import _get_tenant_id
        test_uuid = str(uuid.uuid4())
        with patch.dict(os.environ, {"CZYZ_TENANT_ID": test_uuid}):
            assert _get_tenant_id("czyz") == test_uuid

    def test_get_tenant_id_missing_raises(self):
        """_get_tenant_id 当环境变量未设置时抛出 ValueError"""
        from sync_scheduler import _get_tenant_id
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ZQX_TENANT_ID", None)
            with pytest.raises(ValueError, match="ZQX_TENANT_ID"):
                _get_tenant_id("zqx")


# ─── 测试：sync_logs 写入 ────────────────────────────────────────────────────

class TestWriteSyncLog:
    @pytest.mark.asyncio
    async def test_write_sync_log_success(self):
        """_write_sync_log 正常路径：执行 set_config + INSERT + commit"""
        from sync_scheduler import _write_sync_log

        db = _make_db_mock()
        tenant_id = str(uuid.uuid4())
        started_at = datetime.utcnow()

        await _write_sync_log(
            db=db,
            tenant_id=tenant_id,
            merchant_code="czyz",
            sync_type="dishes",
            status="success",
            records_synced=42,
            error_msg=None,
            started_at=started_at,
        )

        # set_config 调用
        assert db.execute.call_count == 2
        first_call_sql = str(db.execute.call_args_list[0][0][0])
        assert "set_config" in first_call_sql

        # commit 被调用
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_sync_log_with_error_msg(self):
        """_write_sync_log 写入 failed 状态和 error_msg 不抛异常"""
        from sync_scheduler import _write_sync_log

        db = _make_db_mock()
        tenant_id = str(uuid.uuid4())

        await _write_sync_log(
            db=db,
            tenant_id=tenant_id,
            merchant_code="zqx",
            sync_type="employees",
            status="failed",
            records_synced=0,
            error_msg="Connection timeout",
            started_at=datetime.utcnow(),
        )

        # INSERT SQL 中含有 merchant_code 参数
        second_call_kwargs = db.execute.call_args_list[1][0][1]
        assert second_call_kwargs["merchant_code"] == "zqx"
        assert second_call_kwargs["status"] == "failed"
        assert second_call_kwargs["error_msg"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_write_sync_log_db_error_does_not_propagate(self):
        """_write_sync_log DB 异常时静默处理，不向上抛出"""
        from sync_scheduler import _write_sync_log

        db = _make_db_mock()
        db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        # 不应抛出异常
        await _write_sync_log(
            db=db,
            tenant_id=str(uuid.uuid4()),
            merchant_code="sgc",
            sync_type="tables",
            status="success",
            records_synced=10,
            error_msg=None,
            started_at=datetime.utcnow(),
        )


# ─── 测试：重试逻辑 ──────────────────────────────────────────────────────────

class TestWithRetry:
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self):
        """首次成功时直接返回，不重试"""
        from sync_scheduler import _with_retry

        success_result = {"status": "success", "records_synced": 5, "error_msg": None}
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return success_result

        result = await _with_retry(factory, sync_type="dishes", merchant_code="czyz")
        assert result["status"] == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_exhausts_all_attempts_on_failure(self):
        """持续失败时重试 RETRY_TIMES 次后返回 failed"""
        from sync_scheduler import _with_retry

        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return {"status": "failed", "records_synced": 0, "error_msg": "API error"}

        with patch("services.gateway.src.sync_scheduler.asyncio.sleep", new_callable=AsyncMock):
            result = await _with_retry(factory, sync_type="tables", merchant_code="zqx")

        assert result["status"] == "failed"
        assert call_count == 3  # RETRY_TIMES = 3

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """第一次失败，第二次成功时返回成功结果"""
        from sync_scheduler import _with_retry

        attempts = []

        async def factory():
            attempts.append(1)
            if len(attempts) == 1:
                return {"status": "failed", "records_synced": 0, "error_msg": "Temporary error"}
            return {"status": "success", "records_synced": 8, "error_msg": None}

        with patch("services.gateway.src.sync_scheduler.asyncio.sleep", new_callable=AsyncMock):
            result = await _with_retry(factory, sync_type="orders_incremental", merchant_code="sgc")

        assert result["status"] == "success"
        assert result["records_synced"] == 8
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_retry_handles_exception_from_factory(self):
        """factory 抛出异常时计入失败次数，最终返回 failed"""
        from sync_scheduler import _with_retry

        async def factory():
            raise RuntimeError("Network timeout")

        with patch("services.gateway.src.sync_scheduler.asyncio.sleep", new_callable=AsyncMock):
            result = await _with_retry(factory, sync_type="members_incremental", merchant_code="czyz")

        assert result["status"] == "failed"
        assert "Network timeout" in result["error_msg"]

    @pytest.mark.asyncio
    async def test_retry_sleep_between_attempts(self):
        """重试之间调用 asyncio.sleep(RETRY_DELAY_SECONDS)"""
        from sync_scheduler import _with_retry, RETRY_DELAY_SECONDS

        async def factory():
            return {"status": "failed", "records_synced": 0, "error_msg": "err"}

        with patch("services.gateway.src.sync_scheduler.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _with_retry(factory, sync_type="dishes", merchant_code="czyz")

        # 3次尝试，2次间隔 sleep
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(RETRY_DELAY_SECONDS)


# ─── 测试：调度器工厂 ────────────────────────────────────────────────────────

class TestCreateSyncScheduler:
    def test_scheduler_add_job_called_four_times(self):
        """create_sync_scheduler 调用 add_job 共 4 次（注册 4 个任务）"""
        from sync_scheduler import create_sync_scheduler
        # 重置 mock 调用计数
        _mock_scheduler_instance.reset_mock()
        create_sync_scheduler()
        assert _mock_scheduler_instance.add_job.call_count == 4

    def test_scheduler_daily_dishes_sync_job_id(self):
        """daily_dishes_sync 任务 ID 被传入 add_job"""
        from sync_scheduler import create_sync_scheduler
        _mock_scheduler_instance.reset_mock()
        create_sync_scheduler()
        job_ids = [
            call[1].get("id", "")
            for call in _mock_scheduler_instance.add_job.call_args_list
        ]
        assert "daily_dishes_sync" in job_ids

    def test_scheduler_hourly_orders_job_id(self):
        """hourly_orders_incremental_sync 任务 ID 被传入 add_job"""
        from sync_scheduler import create_sync_scheduler
        _mock_scheduler_instance.reset_mock()
        create_sync_scheduler()
        job_ids = [
            call[1].get("id", "")
            for call in _mock_scheduler_instance.add_job.call_args_list
        ]
        assert "hourly_orders_incremental_sync" in job_ids

    def test_scheduler_master_data_sync_job_id(self):
        """daily_master_data_sync 任务 ID 被传入 add_job"""
        from sync_scheduler import create_sync_scheduler
        _mock_scheduler_instance.reset_mock()
        create_sync_scheduler()
        job_ids = [
            call[1].get("id", "")
            for call in _mock_scheduler_instance.add_job.call_args_list
        ]
        assert "daily_master_data_sync" in job_ids

    def test_scheduler_source_code_timezone(self):
        """sync_scheduler.py 源码中包含 Asia/Shanghai 时区配置"""
        scheduler_path = os.path.join(_GATEWAY_SRC, "sync_scheduler.py")
        content = open(scheduler_path).read()
        assert "Asia/Shanghai" in content
