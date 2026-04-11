"""定时上报 Worker — 处理 pending/retry 状态的上报任务

职责:
- 检查 pending 状态的 submissions
- 检查 retry 状态且 next_retry_at 已到的 submissions
- 执行上报（调用城市适配器）
- 更新状态（accepted/rejected/retry/failed）
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.civic_enums import SubmissionStatus
from ..models.civic_events import CivicEventType

logger = structlog.get_logger(__name__)

# 最大重试次数
MAX_RETRY_COUNT = 3
# 重试间隔（分钟）— 指数退避基数
RETRY_BASE_MINUTES = 5
# 每批处理数量
BATCH_SIZE = 50


class ScheduledSubmissionWorker:
    """定时上报处理器

    外部调用入口:
        worker = ScheduledSubmissionWorker()
        await worker.run(db)
    """

    async def _fetch_tenant_ids(self, db: AsyncSession) -> list[str]:
        """获取所有租户 ID 列表。"""
        result = await db.execute(
            text("SELECT DISTINCT tenant_id FROM civic_submissions WHERE is_deleted = FALSE AND status IN ('pending', 'retry')")
        )
        return [str(row[0]) for row in result.all()]

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        """设置当前会话的租户上下文，以通过 RLS。"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    async def run(self, db: AsyncSession) -> dict[str, Any]:
        """执行一轮上报处理。

        Args:
            db: 数据库异步会话

        Returns:
            {processed, succeeded, failed, retried}
        """
        started_at = datetime.now(timezone.utc)
        logger.info("scheduled_submission_worker_started")

        # 获取所有租户，逐租户处理（RLS 要求）
        tenant_ids = await self._fetch_tenant_ids(db)

        all_pending: list[dict[str, Any]] = []
        all_retry: list[dict[str, Any]] = []

        for tid in tenant_ids:
            await self._set_tenant(db, tid)
            pending_items = await self._fetch_pending(db)
            retry_items = await self._fetch_retryable(db)
            all_pending.extend(pending_items)
            all_retry.extend(retry_items)

        pending_items = all_pending
        retry_items = all_retry

        all_items = pending_items + retry_items
        if not all_items:
            logger.info("scheduled_submission_worker_no_items")
            return {"processed": 0, "succeeded": 0, "failed": 0, "retried": 0}

        succeeded = 0
        failed = 0
        retried = 0

        for item in all_items:
            await self._set_tenant(db, str(item["tenant_id"]))
            result = await self._process_submission(item, db)
            if result == "accepted":
                succeeded += 1
            elif result == "failed":
                failed += 1
            elif result == "retry":
                retried += 1

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        logger.info(
            "scheduled_submission_worker_completed",
            processed=len(all_items),
            succeeded=succeeded,
            failed=failed,
            retried=retried,
            elapsed_seconds=round(elapsed, 2),
        )

        return {
            "processed": len(all_items),
            "succeeded": succeeded,
            "failed": failed,
            "retried": retried,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def _fetch_pending(self, db: AsyncSession) -> list[dict[str, Any]]:
        """获取 pending 状态的 submissions。

        Args:
            db: 数据库异步会话

        Returns:
            submissions 列表
        """
        sql = text("""
            SELECT id, tenant_id, store_id, city_code, domain,
                   submission_type, payload, retry_count
            FROM civic_submissions
            WHERE is_deleted = FALSE
              AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT :limit
        """)

        try:
            result = await db.execute(sql, {"limit": BATCH_SIZE})
            rows = result.all()
        except SQLAlchemyError as exc:
            logger.error("fetch_pending_failed", error=str(exc), exc_info=True)
            return []

        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "store_id": row[2],
                "city_code": row[3],
                "domain": row[4],
                "submission_type": row[5],
                "payload": row[6],
                "retry_count": row[7] or 0,
            }
            for row in rows
        ]

    async def _fetch_retryable(self, db: AsyncSession) -> list[dict[str, Any]]:
        """获取可重试的 submissions（retry 状态且 next_retry_at 已到）。

        Args:
            db: 数据库异步会话

        Returns:
            submissions 列表
        """
        now = datetime.now(timezone.utc)

        sql = text("""
            SELECT id, tenant_id, store_id, city_code, domain,
                   submission_type, payload, retry_count
            FROM civic_submissions
            WHERE is_deleted = FALSE
              AND status = 'retry'
              AND (next_retry_at IS NULL OR next_retry_at <= :now)
              AND retry_count < :max_retry
            ORDER BY next_retry_at ASC
            LIMIT :limit
        """)

        try:
            result = await db.execute(
                sql, {"now": now, "max_retry": MAX_RETRY_COUNT, "limit": BATCH_SIZE}
            )
            rows = result.all()
        except SQLAlchemyError as exc:
            logger.error("fetch_retryable_failed", error=str(exc), exc_info=True)
            return []

        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "store_id": row[2],
                "city_code": row[3],
                "domain": row[4],
                "submission_type": row[5],
                "payload": row[6],
                "retry_count": row[7] or 0,
            }
            for row in rows
        ]

    async def _process_submission(
        self,
        item: dict[str, Any],
        db: AsyncSession,
    ) -> str:
        """处理单条上报。

        调用城市适配器执行上报，根据结果更新状态。

        Args:
            item: submission 数据
            db: 数据库异步会话

        Returns:
            最终状态: "accepted" / "retry" / "failed"
        """
        submission_id = item["id"]
        city_code = item["city_code"]
        domain = item["domain"]
        retry_count = item["retry_count"]

        logger.info(
            "processing_submission",
            submission_id=str(submission_id),
            city_code=city_code,
            domain=domain,
            retry_count=retry_count,
        )

        # 标记为 submitting
        await self._update_status(
            db, submission_id, SubmissionStatus.submitting, retry_count
        )

        try:
            # 获取城市适配器并执行上报
            from ..adapters.registry import CityAdapterRegistry

            adapter = CityAdapterRegistry.get_adapter(city_code, domain)
            if adapter is None:
                logger.error(
                    "no_adapter_found",
                    city_code=city_code,
                    domain=domain,
                    submission_id=str(submission_id),
                )
                await self._update_status(
                    db, submission_id, SubmissionStatus.failed, retry_count,
                    error_message=f"No adapter for city={city_code} domain={domain}",
                )
                await self._emit_event(item, SubmissionStatus.failed)
                return "failed"

            # 执行上报
            submit_result = await adapter.submit(item["payload"])

            if submit_result.get("accepted"):
                await self._update_status(
                    db, submission_id, SubmissionStatus.accepted, retry_count,
                    response_data=submit_result,
                )
                await self._emit_event(item, SubmissionStatus.accepted)
                return "accepted"

            if submit_result.get("rejected"):
                await self._update_status(
                    db, submission_id, SubmissionStatus.rejected, retry_count,
                    error_message=submit_result.get("reason", "rejected by platform"),
                    response_data=submit_result,
                )
                await self._emit_event(item, SubmissionStatus.failed)
                return "failed"

            # 可重试的失败
            raise ConnectionError(submit_result.get("error", "unknown submission error"))

        except (ConnectionError, TimeoutError, OSError) as exc:
            # 网络类错误，可以重试
            new_retry_count = retry_count + 1
            if new_retry_count >= MAX_RETRY_COUNT:
                await self._update_status(
                    db, submission_id, SubmissionStatus.failed, new_retry_count,
                    error_message=f"Max retries exceeded: {exc}",
                )
                await self._emit_event(item, SubmissionStatus.failed)
                logger.error(
                    "submission_max_retries_exceeded",
                    submission_id=str(submission_id),
                    error=str(exc),
                )
                return "failed"

            # 指数退避计算下次重试时间
            backoff_minutes = RETRY_BASE_MINUTES * (2 ** retry_count)
            next_retry = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)

            await self._update_status(
                db, submission_id, SubmissionStatus.retry, new_retry_count,
                next_retry_at=next_retry,
                error_message=str(exc),
            )
            logger.warning(
                "submission_will_retry",
                submission_id=str(submission_id),
                retry_count=new_retry_count,
                next_retry_at=next_retry.isoformat(),
                error=str(exc),
            )
            return "retry"

        except (ValueError, KeyError, RuntimeError) as exc:
            # 不可重试的错误
            await self._update_status(
                db, submission_id, SubmissionStatus.failed, retry_count,
                error_message=str(exc),
            )
            await self._emit_event(item, SubmissionStatus.failed)
            logger.error(
                "submission_failed_non_retryable",
                submission_id=str(submission_id),
                error=str(exc),
                exc_info=True,
            )
            return "failed"

    async def _update_status(
        self,
        db: AsyncSession,
        submission_id: uuid.UUID,
        status: SubmissionStatus,
        retry_count: int,
        next_retry_at: datetime | None = None,
        error_message: str | None = None,
        response_data: dict | None = None,
    ) -> None:
        """更新 submission 状态。

        Args:
            db: 数据库异步会话
            submission_id: submission ID
            status: 新状态
            retry_count: 重试次数
            next_retry_at: 下次重试时间
            error_message: 错误信息
            response_data: 平台响应数据
        """
        sql = text("""
            UPDATE civic_submissions
            SET status = :status,
                retry_count = :retry_count,
                next_retry_at = :next_retry_at,
                last_error = :error_message,
                response_data = :response_data,
                submitted_at = CASE WHEN :status IN ('accepted', 'rejected') THEN NOW() ELSE submitted_at END,
                updated_at = NOW()
            WHERE id = :id
        """)

        import json
        await db.execute(sql, {
            "id": submission_id,
            "status": status.value,
            "retry_count": retry_count,
            "next_retry_at": next_retry_at,
            "error_message": error_message,
            "response_data": json.dumps(response_data) if response_data else None,
        })
        await db.commit()

    async def _emit_event(
        self,
        item: dict[str, Any],
        status: SubmissionStatus,
    ) -> None:
        """发射上报结果事件。

        Args:
            item: submission 数据
            status: 最终状态
        """
        try:
            from shared.events.src.emitter import emit_event

            event_type = (
                CivicEventType.SUBMISSION_SUCCESS.value
                if status == SubmissionStatus.accepted
                else CivicEventType.SUBMISSION_FAILED.value
            )

            asyncio.create_task(emit_event(
                event_type=event_type,
                tenant_id=item["tenant_id"],
                stream_id=str(item["id"]),
                payload={
                    "store_id": str(item["store_id"]),
                    "city_code": item["city_code"],
                    "domain": item["domain"],
                    "status": status.value,
                },
                source_service="tx-civic",
            ))
        except ImportError:
            logger.warning("event_emitter_not_available", hint="shared.events not installed")
