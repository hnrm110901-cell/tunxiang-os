"""打印任务持久化重试队列 — Mac mini 端

使用 SQLite（WAL 模式）持久化存储打印任务，支持：
- 指数退避重试（1s, 2s, 4s, 8s, 16s）
- 超过 5 次失败标记为死信（dead_letter）
- 断电/重启后任务不丢失
- 管理员可查询死信任务并手动重触发

SQLite 文件路径通过环境变量 PRINT_QUEUE_DB 配置。
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, List, Optional

import aiosqlite
import structlog

logger = structlog.get_logger()

# 最大重试次数（超过此次数转为死信）
MAX_RETRY_COUNT = 5

# 默认 SQLite 数据库路径（通过环境变量覆盖）
DEFAULT_DB_PATH = os.getenv("PRINT_QUEUE_DB", "/var/lib/tunxiang/print_queue.db")


class JobStatus:
    PENDING = "pending"
    DONE = "done"
    DEAD_LETTER = "dead_letter"


@dataclass
class PrintJob:
    """打印任务数据对象"""
    payload_base64: str           # ESC/POS 字节流的 base64 编码
    printer_address: Optional[str] = None   # 打印机网络地址 host:port
    printer_id: Optional[str] = None        # 打印机标识名


# 发送函数类型：(payload_base64, printer_address, printer_id) -> bool
SendFn = Callable[[str, Optional[str], Optional[str]], Awaitable[bool]]


class PrintQueue:
    """SQLite 持久化打印重试队列"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        # 确保目录存在
        os.makedirs(os.path.dirname(self._db_path) if os.path.dirname(self._db_path) else ".", exist_ok=True)

    @staticmethod
    def backoff_seconds(attempt: int) -> int:
        """计算指数退避秒数：第 0 次=1s, 1次=2s, 2次=4s, 3次=8s, 4次=16s"""
        return 2 ** attempt

    async def init_db(self) -> None:
        """初始化 SQLite 数据库，启用 WAL 模式"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS print_jobs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_base64 TEXT    NOT NULL,
                    printer_address TEXT,
                    printer_id     TEXT,
                    status         TEXT    NOT NULL DEFAULT 'pending',
                    retry_count    INTEGER NOT NULL DEFAULT 0,
                    next_retry_at  TEXT    NOT NULL,
                    created_at     TEXT    NOT NULL,
                    error          TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_print_jobs_status_retry ON print_jobs(status, next_retry_at)"
            )
            await db.commit()
        logger.info("print_queue.db_initialized", db_path=self._db_path)

    async def enqueue(self, job: PrintJob) -> int:
        """将打印任务入队，返回任务 ID"""
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO print_jobs (payload_base64, printer_address, printer_id,
                                        status, retry_count, next_retry_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.payload_base64,
                    job.printer_address,
                    job.printer_id,
                    JobStatus.PENDING,
                    0,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            await db.commit()
            job_id = cursor.lastrowid
        logger.info("print_queue.enqueued", job_id=job_id, printer_address=job.printer_address)
        return job_id

    async def process_pending(self, send_fn: SendFn) -> None:
        """处理待打印任务（定时调用）

        取出 status=pending 且 next_retry_at <= now 的任务：
        - 发送成功 → status=done
        - 发送失败且 retry_count < MAX_RETRY_COUNT → 指数退避更新 next_retry_at
        - 发送失败且 retry_count >= MAX_RETRY_COUNT → status=dead_letter
        """
        now = datetime.now(timezone.utc)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, payload_base64, printer_address, printer_id, retry_count
                FROM print_jobs
                WHERE status = ? AND next_retry_at <= ?
                ORDER BY created_at ASC
                """,
                (JobStatus.PENDING, now.isoformat()),
            )
            rows = await cursor.fetchall()

        for row in rows:
            job_id = row["id"]
            retry_count = row["retry_count"]
            log = logger.bind(job_id=job_id, retry_count=retry_count)

            try:
                success = await send_fn(
                    row["payload_base64"],
                    row["printer_address"],
                    row["printer_id"],
                )
            except Exception as exc:
                log.error("print_queue.send_exception", error=str(exc), exc_info=True)
                success = False

            if success:
                await self._mark_done(job_id)
                log.info("print_queue.job_done")
            elif retry_count >= MAX_RETRY_COUNT:
                await self._mark_dead_letter(job_id, error=f"超过最大重试次数 {MAX_RETRY_COUNT}")
                log.warning("print_queue.dead_letter", job_id=job_id)
            else:
                delay = self.backoff_seconds(retry_count)
                next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                await self._update_retry(
                    job_id,
                    retry_count=retry_count + 1,
                    next_retry_at=next_retry_at,
                    error=f"第 {retry_count + 1} 次重试失败",
                )
                log.warning("print_queue.retry_scheduled", delay_seconds=delay, next_retry_at=next_retry_at.isoformat())

    async def get_pending_jobs(self) -> List[dict]:
        """查询所有待处理任务（不限 next_retry_at）"""
        return await self.get_jobs_by_status(JobStatus.PENDING)

    async def get_jobs_by_status(self, status: str) -> List[dict]:
        """按状态查询任务列表"""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM print_jobs WHERE status = ? ORDER BY created_at ASC",
                (status,),
            )
            rows = await cursor.fetchall()

        result = []
        for row in rows:
            item = dict(row)
            # 将 next_retry_at 字符串转为 datetime
            if item.get("next_retry_at"):
                item["next_retry_at"] = datetime.fromisoformat(item["next_retry_at"])
            result.append(item)
        return result

    async def get_dead_letters(self) -> List[dict]:
        """查询死信任务，用于管理员查看/手动重试"""
        return await self.get_jobs_by_status(JobStatus.DEAD_LETTER)

    async def requeue_dead_letter(self, job_id: int) -> bool:
        """管理员手动重新入队死信任务"""
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE print_jobs
                SET status = ?, retry_count = 0, next_retry_at = ?, error = NULL
                WHERE id = ? AND status = ?
                """,
                (JobStatus.PENDING, now.isoformat(), job_id, JobStatus.DEAD_LETTER),
            )
            await db.commit()
        logger.info("print_queue.dead_letter_requeued", job_id=job_id)
        return True

    # ─── 内部辅助方法 ───

    async def _mark_done(self, job_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE print_jobs SET status = ? WHERE id = ?",
                (JobStatus.DONE, job_id),
            )
            await db.commit()

    async def _mark_dead_letter(self, job_id: int, error: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE print_jobs SET status = ?, error = ? WHERE id = ?",
                (JobStatus.DEAD_LETTER, error, job_id),
            )
            await db.commit()

    async def _update_retry(
        self,
        job_id: int,
        retry_count: int,
        next_retry_at: datetime,
        error: Optional[str],
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE print_jobs
                SET retry_count = ?, next_retry_at = ?, error = ?
                WHERE id = ?
                """,
                (retry_count, next_retry_at.isoformat(), error, job_id),
            )
            await db.commit()
