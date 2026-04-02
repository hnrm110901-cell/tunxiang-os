"""服务铃 Service"""
import os
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.service_bell_call import ServiceBellCall

logger = structlog.get_logger()

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")


async def create_call(
    store_id: str,
    table_no: str,
    call_type: str,
    call_type_label: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> ServiceBellCall:
    now = datetime.now(timezone.utc)
    call = ServiceBellCall(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        table_no=table_no,
        call_type=call_type,
        call_type_label=call_type_label,
        status="pending",
        called_at=now,
    )
    db.add(call)
    await db.flush()
    await db.commit()
    await db.refresh(call)

    logger.info(
        "service_bell.call.created",
        call_id=str(call.id),
        store_id=store_id,
        table_no=table_no,
        call_type=call_type,
    )

    await _broadcast_call(call, tenant_id)
    return call


async def respond_call(
    call_id: str,
    operator_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> ServiceBellCall:
    result = await db.execute(
        select(ServiceBellCall).where(
            ServiceBellCall.id == uuid.UUID(call_id),
            ServiceBellCall.tenant_id == uuid.UUID(tenant_id),
            ServiceBellCall.is_deleted.is_(False),
        )
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise LookupError(f"service_bell_call {call_id} not found")

    now = datetime.now(timezone.utc)
    await db.execute(
        update(ServiceBellCall)
        .where(ServiceBellCall.id == call.id)
        .values(
            status="responded",
            operator_id=uuid.UUID(operator_id),
            responded_at=now,
        )
    )
    await db.commit()
    await db.refresh(call)

    logger.info(
        "service_bell.call.responded",
        call_id=call_id,
        operator_id=operator_id,
    )
    return call


async def get_pending_calls(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[ServiceBellCall]:
    result = await db.execute(
        select(ServiceBellCall)
        .where(
            ServiceBellCall.tenant_id == uuid.UUID(tenant_id),
            ServiceBellCall.store_id == uuid.UUID(store_id),
            ServiceBellCall.status == "pending",
            ServiceBellCall.is_deleted.is_(False),
        )
        .order_by(ServiceBellCall.called_at.asc())
    )
    return list(result.scalars().all())


async def get_call_history(
    store_id: str,
    query_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> list[ServiceBellCall]:
    from sqlalchemy import Date, cast

    result = await db.execute(
        select(ServiceBellCall)
        .where(
            ServiceBellCall.tenant_id == uuid.UUID(tenant_id),
            ServiceBellCall.store_id == uuid.UUID(store_id),
            cast(ServiceBellCall.called_at, Date) == query_date,
            ServiceBellCall.is_deleted.is_(False),
        )
        .order_by(ServiceBellCall.called_at.desc())
    )
    return list(result.scalars().all())


async def _broadcast_call(call: ServiceBellCall, tenant_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{MAC_STATION_URL}/api/kds/broadcast",
                json={
                    "event": "service_bell_called",
                    "store_id": str(call.store_id),
                    "data": {
                        "call_id": str(call.id),
                        "table_no": call.table_no,
                        "call_type": call.call_type,
                        "call_type_label": call.call_type_label,
                        "called_at": call.called_at.isoformat(),
                    },
                },
                headers={"X-Tenant-ID": tenant_id},
            )
    except httpx.RequestError as e:
        logger.warning("service_bell.broadcast.failed", error=str(e))
