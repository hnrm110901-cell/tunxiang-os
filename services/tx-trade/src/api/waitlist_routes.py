"""等位调度引擎 API — 叫号队列管理（DB版，v109）

路由注册（在 main.py 中添加）:
    from .api.waitlist_routes import router as waitlist_router
    app.include_router(waitlist_router, prefix="/api/v1/waitlist")

所有接口需 X-Tenant-ID header。
统一响应格式: {"ok": bool, "data": {}, "error": {}}

优先级规则:
  0  = 普通散客
  10 = 普通会员
  20 = 银卡会员
  30 = 金卡会员
  40 = 黑金会员
  -10 = 过号降级
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["waitlist"])

# ─── 优先级映射 ──────────────────────────────────────────────────────────────

_MEMBER_LEVEL_PRIORITY: dict[str, int] = {
    "normal":   10,
    "silver":   20,
    "gold":     30,
    "black":    40,
    "普通会员": 10,
    "银卡":     20,
    "金卡":     30,
    "黑金":     40,
}

_AVG_TURNOVER_MIN = 30
_DEFAULT_TABLE_COUNT = 5
_EXPIRE_TIMEOUT_MIN = 15

# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", "")


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "error": {"message": msg}})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── Request/Response Models ─────────────────────────────────────────────────


class WaitlistCreateBody(BaseModel):
    store_id: str
    name: str
    phone: Optional[str] = None
    party_size: int
    table_type: Optional[str] = None
    member_id: Optional[str] = None
    member_level: Optional[str] = None

    @field_validator("party_size")
    @classmethod
    def party_size_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("party_size 必须大于0")
        return v


class CallBody(BaseModel):
    channel: str = "screen"  # screen / sms / wechat
    called_by: Optional[str] = None


class SeatBody(BaseModel):
    table_id: Optional[str] = None


class CancelBody(BaseModel):
    reason: Optional[str] = ""


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("")
async def list_waitlist(
    request: Request,
    store_id: str = Query(...),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/waitlist?store_id=<id>&status=<status>

    返回门店等位列表，按优先级 DESC + 创建时间 ASC 排序。
    """
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)
        params: dict = {"store_id": store_id}
        status_clause = ""
        if status:
            status_clause = "AND status = :status"
            params["status"] = status

        result = await db.execute(
            text(f"""
                SELECT id, queue_no, name, phone, party_size, table_type,
                       member_id, priority, status, called_at, call_count,
                       seated_at, expired_at, estimated_wait_min, created_at
                FROM waitlist_entries
                WHERE store_id = :store_id {status_clause}
                ORDER BY priority DESC, created_at ASC
            """),
            params,
        )
        rows = result.mappings().all()
        waiting_count = sum(1 for r in rows if r["status"] == "waiting")
        # 估算等待时间（简化：waiting人数 × 翻台时间 / 可用桌台数）
        est_wait = (waiting_count * _AVG_TURNOVER_MIN) // max(_DEFAULT_TABLE_COUNT, 1)

        items = []
        for r in rows:
            item = dict(r._mapping)
            for k, v in item.items():
                if hasattr(v, 'isoformat'):
                    item[k] = v.isoformat()
                elif v is not None:
                    item[k] = str(v) if not isinstance(v, (int, float, bool, str)) else v
            items.append(item)

        return _ok({
            "items": items,
            "total": len(items),
            "waiting_count": waiting_count,
            "estimated_wait_min": est_wait,
        })
    except SQLAlchemyError as exc:
        logger.error("waitlist_list_error", error=str(exc))
        _err("查询等位列表失败", 500)


@router.post("")
async def create_waitlist_entry(
    body: WaitlistCreateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/waitlist — 新建等位记录"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        # 获取下一个队列号
        result = await db.execute(
            text("""
                SELECT COALESCE(MAX(queue_no), 100) + 1 AS next_no
                FROM waitlist_entries
                WHERE store_id = :store_id
                  AND DATE(created_at) = CURRENT_DATE
            """),
            {"store_id": body.store_id},
        )
        row = result.mappings().one_or_none()
        queue_no = int(row["next_no"]) if row else 101

        # 等待人数
        count_result = await db.execute(
            text("SELECT COUNT(*) AS cnt FROM waitlist_entries WHERE store_id = :sid AND status = 'waiting'"),
            {"sid": body.store_id},
        )
        waiting_count = int(count_result.scalar() or 0)
        estimated_wait = (waiting_count * _AVG_TURNOVER_MIN) // max(_DEFAULT_TABLE_COUNT, 1)

        priority = _MEMBER_LEVEL_PRIORITY.get(body.member_level or "", 0) if body.member_level else 0

        insert_result = await db.execute(
            text("""
                INSERT INTO waitlist_entries
                    (tenant_id, store_id, queue_no, name, phone, party_size,
                     table_type, member_id, priority, status, estimated_wait_min)
                VALUES (:tenant_id, :store_id, :queue_no, :name, :phone, :party_size,
                        :table_type, :member_id, :priority, 'waiting', :estimated_wait_min)
                RETURNING id, queue_no, estimated_wait_min, created_at
            """),
            {
                "tenant_id": tenant_id,
                "store_id": body.store_id,
                "queue_no": queue_no,
                "name": body.name,
                "phone": body.phone,
                "party_size": body.party_size,
                "table_type": body.table_type,
                "member_id": body.member_id,
                "priority": priority,
                "estimated_wait_min": estimated_wait,
            },
        )
        new_row = insert_result.mappings().one()
        await db.commit()

        return _ok({
            "entry_id": str(new_row["id"]),
            "queue_no": new_row["queue_no"],
            "estimated_wait_min": new_row["estimated_wait_min"],
            "status": "waiting",
            "created_at": new_row["created_at"].isoformat() if new_row["created_at"] else _now_iso(),
        })
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_create_error", error=str(exc))
        _err("创建等位记录失败", 500)


@router.post("/{entry_id}/call")
async def call_entry(
    entry_id: str,
    body: CallBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/waitlist/{entry_id}/call — 叫号"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        # 查找记录
        result = await db.execute(
            text("SELECT id, status, call_count FROM waitlist_entries WHERE id = :eid"),
            {"eid": entry_id},
        )
        entry = result.mappings().one_or_none()
        if not entry:
            _err("等位记录不存在", 404)

        if entry["status"] not in ("waiting",):
            _err(f"当前状态 {entry['status']} 不可叫号")

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'called', called_at = :now,
                    call_count = call_count + 1, updated_at = :now
                WHERE id = :eid
            """),
            {"eid": entry_id, "now": now},
        )

        # 写叫号日志
        await db.execute(
            text("""
                INSERT INTO waitlist_call_logs (tenant_id, entry_id, channel, called_by)
                VALUES (:tid, :eid, :channel, :called_by)
            """),
            {
                "tid": tenant_id,
                "eid": entry_id,
                "channel": body.channel,
                "called_by": body.called_by,
            },
        )
        await db.commit()

        return _ok({
            "entry_id": entry_id,
            "status": "called",
            "call_count": int(entry["call_count"]) + 1,
            "called_at": now.isoformat(),
        })
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_call_error", error=str(exc))
        _err("叫号操作失败", 500)


@router.post("/{entry_id}/seat")
async def seat_entry(
    entry_id: str,
    body: SeatBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/waitlist/{entry_id}/seat — 入座确认"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("SELECT id, status FROM waitlist_entries WHERE id = :eid"),
            {"eid": entry_id},
        )
        entry = result.mappings().one_or_none()
        if not entry:
            _err("等位记录不存在", 404)

        if entry["status"] not in ("called", "waiting"):
            _err(f"当前状态 {entry['status']} 不可入座")

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'seated', seated_at = :now, updated_at = :now
                WHERE id = :eid
            """),
            {"eid": entry_id, "now": now},
        )
        await db.commit()

        return _ok({
            "entry_id": entry_id,
            "status": "seated",
            "seated_at": now.isoformat(),
        })
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_seat_error", error=str(exc))
        _err("入座操作失败", 500)


@router.post("/{entry_id}/cancel")
async def cancel_entry(
    entry_id: str,
    body: CancelBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/waitlist/{entry_id}/cancel — 取消等位"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("SELECT id, status FROM waitlist_entries WHERE id = :eid"),
            {"eid": entry_id},
        )
        entry = result.mappings().one_or_none()
        if not entry:
            _err("等位记录不存在", 404)

        if entry["status"] in ("seated", "cancelled", "expired"):
            _err(f"当前状态 {entry['status']} 不可取消")

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'cancelled', updated_at = :now
                WHERE id = :eid
            """),
            {"eid": entry_id, "now": now},
        )
        await db.commit()

        return _ok({"entry_id": entry_id, "status": "cancelled"})
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_cancel_error", error=str(exc))
        _err("取消等位失败", 500)


@router.post("/expire-overdue")
async def expire_overdue(
    request: Request,
    store_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/waitlist/expire-overdue — 批量过期超时未到场的叫号记录"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=_EXPIRE_TIMEOUT_MIN)
        result = await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'expired', expired_at = NOW(),
                    priority = GREATEST(-10, priority - 10),
                    updated_at = NOW()
                WHERE store_id = :store_id
                  AND status = 'called'
                  AND called_at < :threshold
                RETURNING id
            """),
            {"store_id": store_id, "threshold": timeout_threshold},
        )
        expired_ids = [str(r["id"]) for r in result.mappings().all()]
        await db.commit()

        return _ok({
            "expired_count": len(expired_ids),
            "expired_ids": expired_ids,
        })
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_expire_error", error=str(exc))
        _err("批量过期操作失败", 500)


@router.get("/stats")
async def get_stats(
    request: Request,
    store_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/waitlist/stats — 等位统计（今日）"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'waiting')  AS waiting_count,
                    COUNT(*) FILTER (WHERE status = 'called')   AS called_count,
                    COUNT(*) FILTER (WHERE status = 'seated')   AS seated_count,
                    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                    COUNT(*) FILTER (WHERE status = 'expired')  AS expired_count,
                    COUNT(*) AS total_today
                FROM waitlist_entries
                WHERE store_id = :store_id
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
            """),
            {"store_id": store_id},
        )
        row = result.mappings().one_or_none()
        stats = {k: int(v or 0) for k, v in dict(row._mapping).items()} if row else {}

        waiting = stats.get("waiting_count", 0)
        estimated_wait = (waiting * _AVG_TURNOVER_MIN) // max(_DEFAULT_TABLE_COUNT, 1)

        return _ok({**stats, "estimated_wait_min": estimated_wait})
    except SQLAlchemyError as exc:
        logger.error("waitlist_stats_error", error=str(exc))
        _err("获取统计失败", 500)
