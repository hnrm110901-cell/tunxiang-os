"""
CivicTraceSubmissionService — 湘食通食品安全追溯上报服务

湖南省湘食通平台的上报数据管理。
当前为最简接口骨架（湘食通外部账号需采购，先 mock 接口）。

上报类型:
  ingredient_batch   — 食材批次信息上报
  waste_disposal     — 废弃物处理上报
  inspection_report  — 检测报告上报

罚款风险：食安法第126条 5-10 万元。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SubmissionResult:
    """上报结果。"""
    ok: bool
    id: str
    status: str
    submission_id: str | None
    message: str | None


SUBMISSION_TYPES = frozenset({
    "ingredient_batch",
    "waste_disposal",
    "inspection_report",
})


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# 核心服务函数
# ---------------------------------------------------------------------------


async def submit_traceability(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    submission_type: str,
    payload: dict[str, Any],
) -> SubmissionResult:
    """提交数据到湘食通平台（模拟接口）。

    实际对接湘食通平台后，此函数应:
    1. 调用湘食通 HTTP API
    2. 接收平台返回的 submission_id
    3. 更新记录状态（submitted / acknowledged / rejected）

    Args:
        submission_type: 上报类型，参见 SUBMISSION_TYPES
        payload: 上报数据（根据类型不同结构不同）

    Returns:
        SubmissionResult
    """
    await _set_tenant(db, tenant_id)

    # 校验上报类型
    if submission_type not in SUBMISSION_TYPES:
        return SubmissionResult(
            ok=False,
            id="",
            status="rejected",
            submission_id=None,
            message=f"不支持的上报类型: {submission_type}",
        )

    record_id = str(uuid4())
    # 模拟湘食通平台返回的 submission_id
    mock_submission_id = f"XST-{uuid4().hex[:12].upper()}"

    try:
        await db.execute(
            text("""
                INSERT INTO civic_traceability_submissions
                    (id, tenant_id, store_id, submission_type, payload,
                     status, submission_id, created_at)
                VALUES
                    (:id, :tenant_id, :store_id, :submission_type, :payload,
                     'submitted', :submission_id, NOW())
            """),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "submission_type": submission_type,
                "payload": json.dumps(payload),
                "submission_id": mock_submission_id,
            },
        )
        await db.commit()

        logger.info(
            "traceability_submitted",
            record_id=record_id,
            submission_type=submission_type,
            submission_id=mock_submission_id,
        )

        return SubmissionResult(
            ok=True,
            id=record_id,
            status="submitted",
            submission_id=mock_submission_id,
            message="已提交（模拟湘食通接口）",
        )

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "traceability_submit_failed",
            submission_type=submission_type,
            error=str(exc),
            exc_info=True,
        )
        return SubmissionResult(
            ok=False,
            id="",
            status="failed",
            submission_id=None,
            message=str(exc),
        )


async def query_submission_status(
    db: AsyncSession,
    tenant_id: str,
    submission_id: str,
) -> dict[str, Any] | None:
    """查询湘食通上报状态。

    Args:
        submission_id: 湘食通平台返回的 submission_id (XST-xxxx)

    Returns:
        上报记录 dict，或 None（记录不存在）
    """
    await _set_tenant(db, tenant_id)

    try:
        row = await db.execute(
            text("""
                SELECT id, tenant_id, store_id, submission_type,
                       payload, status, submission_id,
                       acknowledged_at, error_message, created_at
                FROM civic_traceability_submissions
                WHERE tenant_id = :tenant_id
                  AND submission_id = :submission_id
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "submission_id": submission_id},
        )
        record = row.mappings().first()
        if not record:
            return None

        result = dict(record)
        # JSON 序列化处理
        for key in ("created_at", "acknowledged_at"):
            if isinstance(result.get(key), datetime):
                result[key] = result[key].isoformat()
        if isinstance(result.get("payload"), dict):
            result["payload"] = json.dumps(result["payload"])

        return result

    except SQLAlchemyError as exc:
        logger.error(
            "query_submission_status_failed",
            submission_id=submission_id,
            error=str(exc),
            exc_info=True,
        )
        return None


async def get_pending_submissions(
    db: AsyncSession,
    tenant_id: str,
    store_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询待处理的湘食通上报记录（draft 或 submitted 状态）。

    Args:
        store_id: 可选，按门店筛选
        limit: 返回条数上限

    Returns:
        上报记录列表
    """
    await _set_tenant(db, tenant_id)

    conditions = [
        "tenant_id = :tenant_id",
        "status IN ('draft', 'submitted')",
        "is_deleted = FALSE",
    ]
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    try:
        rows = await db.execute(
            text(f"""
                SELECT id, store_id, submission_type, payload, status,
                       submission_id, error_message, created_at
                FROM civic_traceability_submissions
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            params,
        )
        items = []
        for r in rows.mappings():
            item = dict(r)
            if isinstance(item.get("created_at"), datetime):
                item["created_at"] = item["created_at"].isoformat()
            items.append(item)

        return items

    except SQLAlchemyError as exc:
        logger.error(
            "get_pending_submissions_failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return []
