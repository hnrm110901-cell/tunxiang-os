"""打印重试队列测试套件

覆盖：
1. 打印失败 → 任务进入重试队列
2. 重连后队列自动消费，补打所有积压任务
3. 重试超过5次的任务标记为死信，不再重试
4. 重试有指数退避（1s, 2s, 4s, 8s, 16s）
"""
import os

# 将 edge/mac-mini 加入测试路径
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../edge/mac-mini"))

from print_queue import JobStatus, PrintJob, PrintQueue

# ─── 测试夹具 ───

@pytest.fixture
def tmp_db(tmp_path):
    """使用临时目录的 SQLite 数据库"""
    db_path = str(tmp_path / "test_print_queue.db")
    os.environ["PRINT_QUEUE_DB"] = db_path
    yield db_path
    # 清理
    if "PRINT_QUEUE_DB" in os.environ:
        del os.environ["PRINT_QUEUE_DB"]


@pytest.fixture
async def queue(tmp_db):
    """初始化好的 PrintQueue 实例"""
    q = PrintQueue(db_path=tmp_db)
    await q.init_db()
    return q


def _make_job(printer_address: str = "192.168.1.100:9100") -> PrintJob:
    return PrintJob(
        payload_base64="AQIDBA==",
        printer_address=printer_address,
        printer_id=None,
    )


# ─── Test 1: 打印失败 → 任务进入重试队列 ───

@pytest.mark.asyncio
async def test_failed_print_enqueues_job(queue):
    """send_to_printer 失败时任务应入队，状态为 pending"""
    job = _make_job()
    job_id = await queue.enqueue(job)
    assert job_id is not None

    jobs = await queue.get_pending_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["status"] == JobStatus.PENDING
    assert jobs[0]["retry_count"] == 0


@pytest.mark.asyncio
async def test_enqueue_stores_payload(queue):
    """入队的任务应保留完整 payload"""
    job = _make_job(printer_address="10.0.0.50:9100")
    job_id = await queue.enqueue(job)

    jobs = await queue.get_pending_jobs()
    assert jobs[0]["printer_address"] == "10.0.0.50:9100"
    assert jobs[0]["payload_base64"] == "AQIDBA=="


# ─── Test 2: 重连后队列自动消费，补打所有积压任务 ───

@pytest.mark.asyncio
async def test_process_pending_success(queue):
    """process_pending 成功时任务状态改为 done"""
    job = _make_job()
    job_id = await queue.enqueue(job)

    # 模拟打印成功
    async def mock_send(payload_base64, printer_address, printer_id):
        return True

    await queue.process_pending(send_fn=mock_send)

    # 任务应标记为 done
    done_jobs = await queue.get_jobs_by_status(JobStatus.DONE)
    assert len(done_jobs) == 1
    assert done_jobs[0]["id"] == job_id

    # pending 队列应为空
    pending = await queue.get_pending_jobs()
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_process_pending_multiple_jobs(queue):
    """process_pending 应消费所有积压任务"""
    for i in range(3):
        await queue.enqueue(_make_job(printer_address=f"192.168.1.{100+i}:9100"))

    call_count = 0

    async def mock_send(payload_base64, printer_address, printer_id):
        nonlocal call_count
        call_count += 1
        return True

    await queue.process_pending(send_fn=mock_send)

    assert call_count == 3
    done_jobs = await queue.get_jobs_by_status(JobStatus.DONE)
    assert len(done_jobs) == 3


@pytest.mark.asyncio
async def test_process_pending_skips_future_retry(queue):
    """next_retry_at 在未来的任务不应被处理"""
    job = _make_job()
    job_id = await queue.enqueue(job)

    # 手动将 next_retry_at 设置到未来
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    await queue._update_retry(job_id, retry_count=1, next_retry_at=future_time, error=None)

    call_count = 0

    async def mock_send(payload_base64, printer_address, printer_id):
        nonlocal call_count
        call_count += 1
        return True

    await queue.process_pending(send_fn=mock_send)
    assert call_count == 0


# ─── Test 3: 重试超过5次 → 死信 ───

@pytest.mark.asyncio
async def test_exceed_max_retries_becomes_dead_letter(queue):
    """重试 5 次失败后任务状态应变为 dead_letter"""
    job = _make_job()
    job_id = await queue.enqueue(job)

    # 模拟打印一直失败，设置 retry_count 已经等于 5（下一次失败触发死信）
    past_time = datetime.now(timezone.utc) - timedelta(seconds=1)
    await queue._update_retry(job_id, retry_count=5, next_retry_at=past_time, error="连接超时")

    async def mock_send(payload_base64, printer_address, printer_id):
        return False

    await queue.process_pending(send_fn=mock_send)

    dead_letters = await queue.get_dead_letters()
    assert len(dead_letters) == 1
    assert dead_letters[0]["id"] == job_id
    assert dead_letters[0]["status"] == JobStatus.DEAD_LETTER
    assert dead_letters[0]["error"] is not None

    # 死信任务不应出现在 pending 中
    pending = await queue.get_pending_jobs()
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_dead_letter_not_retried_again(queue):
    """死信任务不应再次被 process_pending 处理"""
    job = _make_job()
    job_id = await queue.enqueue(job)

    # 直接设置为死信
    await queue._mark_dead_letter(job_id, error="已超过最大重试次数")

    call_count = 0

    async def mock_send(payload_base64, printer_address, printer_id):
        nonlocal call_count
        call_count += 1
        return True

    await queue.process_pending(send_fn=mock_send)
    assert call_count == 0


# ─── Test 4: 指数退避 ───

@pytest.mark.asyncio
async def test_exponential_backoff_on_failure(queue):
    """每次失败后 next_retry_at 应按指数退避增长"""
    job = _make_job()
    job_id = await queue.enqueue(job)

    async def mock_send_fail(payload_base64, printer_address, printer_id):
        return False

    # 第1次失败：next_retry_at 应该约为 1 秒后
    now_before = datetime.now(timezone.utc)
    await queue.process_pending(send_fn=mock_send_fail)
    now_after = datetime.now(timezone.utc)

    jobs = await queue.get_jobs_by_status(JobStatus.PENDING)
    assert len(jobs) == 1
    assert jobs[0]["retry_count"] == 1
    # next_retry_at 应在 [now+0.5s, now+2s] 范围内（容错0.5s）
    expected_delta = timedelta(seconds=1)
    actual_next = jobs[0]["next_retry_at"]
    assert now_before + expected_delta - timedelta(seconds=0.5) <= actual_next <= now_after + expected_delta + timedelta(seconds=0.5)


@pytest.mark.asyncio
async def test_backoff_delays_are_exponential(queue):
    """验证指数退避时间序列：1s, 2s, 4s, 8s, 16s"""
    expected_delays = [1, 2, 4, 8, 16]

    for attempt, expected_delay in enumerate(expected_delays):
        delay = PrintQueue.backoff_seconds(attempt)
        assert delay == expected_delay, (
            f"第 {attempt+1} 次重试期望退避 {expected_delay}s，实际为 {delay}s"
        )


@pytest.mark.asyncio
async def test_retry_count_increments_on_failure(queue):
    """每次失败后 retry_count 应递增"""
    job = _make_job()
    job_id = await queue.enqueue(job)

    async def mock_send_fail(payload_base64, printer_address, printer_id):
        return False

    # 手动推进：将 next_retry_at 设为过去以允许重试
    for expected_retry_count in range(1, 4):
        past_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        # 更新为可立即重试状态（只有 retry_count < 5 时）
        current_jobs = await queue.get_pending_jobs()
        if not current_jobs:
            break
        current_job = current_jobs[0]
        await queue._update_retry(
            current_job["id"],
            retry_count=current_job["retry_count"],
            next_retry_at=past_time,
            error=None,
        )
        await queue.process_pending(send_fn=mock_send_fail)

        jobs = await queue.get_jobs_by_status(JobStatus.PENDING)
        if jobs:
            assert jobs[0]["retry_count"] == expected_retry_count


# ─── 辅助：get_dead_letters 查询 ───

@pytest.mark.asyncio
async def test_get_dead_letters_returns_all_dead(queue):
    """get_dead_letters 应返回所有死信任务"""
    for _ in range(3):
        job_id = await queue.enqueue(_make_job())
        await queue._mark_dead_letter(job_id, error="测试错误")

    # 另有一个正常 pending 任务
    await queue.enqueue(_make_job())

    dead = await queue.get_dead_letters()
    assert len(dead) == 3
    assert all(d["status"] == JobStatus.DEAD_LETTER for d in dead)
