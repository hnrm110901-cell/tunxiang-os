"""客户生命周期 FSM API — 3 个路由

  GET  /api/v1/customer-lifecycle/{customer_id}              查询单客户当前状态
  POST /api/v1/customer-lifecycle/{customer_id}/recompute    手动触发重算
  GET  /api/v1/customer-lifecycle/summary                    4 象限计数 + 4 类流量

统一响应：{"ok": bool, "data": {}, "error": {}}
X-Tenant-ID header 必填。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

try:
    from repositories.customer_lifecycle_repo import CustomerLifecycleRepository
    from services.customer_lifecycle_fsm import CustomerLifecycleFSM
except ImportError:  # pragma: no cover
    from ..repositories.customer_lifecycle_repo import (  # type: ignore[no-redef]
        CustomerLifecycleRepository,
    )
    from ..services.customer_lifecycle_fsm import (  # type: ignore[no-redef]
        CustomerLifecycleFSM,
    )

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/customer-lifecycle",
    tags=["customer-lifecycle"],
)


# ──────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str) -> uuid.UUID:
    """解析并校验 X-Tenant-ID header。"""
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=400,
            detail="X-Tenant-ID header is required",
        )
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"X-Tenant-ID must be a valid UUID, got: {x_tenant_id!r}",
        ) from exc


def _parse_customer_id(customer_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(customer_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"customer_id must be a valid UUID, got: {customer_id!r}",
        ) from exc


async def _set_rls(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ──────────────────────────────────────────────────────────────────
# 1. GET /customer-lifecycle/{customer_id}
# ──────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_lifecycle_summary(
    flow_window_days: int = Query(
        30, ge=1, le=365, description="流量窗口天数（默认近 30 天）"
    ),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按租户返回 4 象限计数 + 4 类流量。

    Returns:
        {
          ok: True,
          data: {
            counts: {no_order, active, dormant, churned},
            flows:  {new_active, new_dormant, recalled, recovered},
            as_of:  ISO8601,
          },
          error: {}
        }
    """
    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    repo = CustomerLifecycleRepository(db, tenant_id)

    try:
        counts = await repo.count_by_state()
        flows = await repo.count_flows(window_days=flow_window_days)
    except (RuntimeError, ValueError) as exc:
        logger.error(
            "lifecycle_summary_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
            exc_info=True,
        )
        return {
            "ok": False,
            "data": {},
            "error": {"code": "LIFECYCLE_SUMMARY_FAILED", "message": str(exc)},
        }

    return {
        "ok": True,
        "data": {
            "counts": counts,
            "flows": flows,
            "flow_window_days": flow_window_days,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
        "error": {},
    }


@router.get("/{customer_id}")
async def get_lifecycle_for_customer(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询指定客户当前的生命周期状态。"""
    tenant_id = _parse_tenant(x_tenant_id)
    cid = _parse_customer_id(customer_id)
    await _set_rls(db, tenant_id)

    repo = CustomerLifecycleRepository(db, tenant_id)
    record = await repo.get_current_state(cid)
    if record is None:
        return {
            "ok": False,
            "data": {},
            "error": {
                "code": "LIFECYCLE_NOT_FOUND",
                "message": f"customer {customer_id} has no lifecycle record yet",
            },
        }

    return {
        "ok": True,
        "data": {
            "customer_id": str(record.customer_id),
            "tenant_id": str(record.tenant_id),
            "state": record.state.value,
            "previous_state": (
                record.previous_state.value if record.previous_state else None
            ),
            "since_ts": record.since_ts.isoformat(),
            "transition_count": record.transition_count,
            "last_transition_event_id": (
                str(record.last_transition_event_id)
                if record.last_transition_event_id
                else None
            ),
            "updated_at": record.updated_at.isoformat(),
        },
        "error": {},
    }


# ──────────────────────────────────────────────────────────────────
# 2. POST /customer-lifecycle/{customer_id}/recompute
# ──────────────────────────────────────────────────────────────────


@router.post("/{customer_id}/recompute")
async def recompute_lifecycle(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动触发单客户状态重算（从 customers 表读 last_order_at/total_order_count）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    cid = _parse_customer_id(customer_id)
    await _set_rls(db, tenant_id)

    row = (
        await db.execute(
            text(
                """
                SELECT last_order_at, total_order_count
                FROM customers
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = FALSE
                """
            ),
            {"tid": str(tenant_id), "cid": str(cid)},
        )
    ).fetchone()
    if row is None:
        return {
            "ok": False,
            "data": {},
            "error": {
                "code": "CUSTOMER_NOT_FOUND",
                "message": f"customer {customer_id} does not exist",
            },
        }

    last_order_at = row[0]
    order_count = int(row[1] or 0)

    fsm = CustomerLifecycleFSM(db, tenant_id)
    record = await fsm.recompute_one(
        customer_id=cid,
        now=datetime.now(timezone.utc),
        last_order_at=last_order_at,
        order_count=order_count,
    )

    logger.info(
        "lifecycle_recompute_done",
        tenant_id=str(tenant_id),
        customer_id=str(cid),
        state=record.state.value,
    )

    return {
        "ok": True,
        "data": {
            "customer_id": str(record.customer_id),
            "state": record.state.value,
            "previous_state": (
                record.previous_state.value if record.previous_state else None
            ),
            "transition_count": record.transition_count,
            "since_ts": record.since_ts.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        },
        "error": {},
    }
