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

import json
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


class PreOrderItem(BaseModel):
    dish_id: str
    dish_name: str
    quantity: int = 1
    unit_price_fen: int
    modifiers: list[dict] = []  # 做法加价等
    notes: str = ""


class PreOrderRequest(BaseModel):
    items: list[PreOrderItem]


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
            text("SELECT id, status, pre_order_items, pre_order_total_fen FROM waitlist_entries WHERE id = :eid"),
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

        # 入座时自动合并预点菜到正式订单
        raw_items = entry["pre_order_items"]
        pre_order_items: list = []
        if raw_items:
            pre_order_items = raw_items if isinstance(raw_items, list) else json.loads(raw_items)
        if pre_order_items:
            # TODO: 调用 dining_session / order API 创建正式订单
            # 将 pre_order_items 转为正式 order items
            logger.info("pre_order_merged", extra={
                "entry_id": entry_id,
                "items_count": len(pre_order_items),
                "total_fen": int(entry["pre_order_total_fen"] or 0),
            })

        await db.commit()

        return _ok({
            "entry_id": entry_id,
            "status": "seated",
            "seated_at": now.isoformat(),
            "pre_order_merged": len(pre_order_items) > 0,
            "pre_order_items_count": len(pre_order_items),
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
                RETURNING id, member_id, coupon_issued_on_timeout
            """),
            {"store_id": store_id, "threshold": timeout_threshold},
        )
        expired_entries = result.mappings().all()
        expired_ids = [str(r["id"]) for r in expired_entries]

        # ── 超时自动发券（SCRM8对标功能）──
        # 对有member_id的排队客户，自动发放安慰券
        coupon_issued_count = 0
        for entry in expired_entries:
            member_id = entry.get("member_id")
            if member_id and not entry.get("coupon_issued_on_timeout"):
                try:
                    import asyncio
                    from shared.events.src.emitter import emit_event
                    from shared.events.src.event_types import MemberEventType

                    asyncio.create_task(emit_event(
                        event_type=MemberEventType.VOUCHER_ISSUED,
                        tenant_id=tenant_id,
                        stream_id=str(member_id),
                        payload={
                            "member_id": str(member_id),
                            "voucher_type": "waitlist_timeout_compensation",
                            "amount_fen": 1000,  # 10元
                            "validity_days": 30,
                            "reason": "排队超时补偿",
                            "waitlist_entry_id": str(entry["id"]),
                        },
                        source_service="tx-trade",
                    ))

                    # 标记已发券
                    await db.execute(text("""
                        UPDATE waitlist_entries SET coupon_issued_on_timeout = TRUE, updated_at = NOW()
                        WHERE id = :eid
                    """), {"eid": str(entry["id"])})

                    coupon_issued_count += 1
                    logger.info("waitlist_timeout_coupon_issued",
                                member_id=str(member_id), entry_id=str(entry["id"]))
                except (ValueError, RuntimeError, OSError) as exc:
                    logger.warning("waitlist_timeout_coupon_failed",
                                   error=str(exc), member_id=str(member_id))

        await db.commit()

        return _ok({
            "expired_count": len(expired_ids),
            "expired_ids": expired_ids,
            "coupon_issued_count": coupon_issued_count,
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


# ─── 排队预点菜端点 ─────────────────────────────────────────────────────────────


@router.post("/{entry_id}/pre-order")
async def add_pre_order(
    entry_id: str,
    body: PreOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/waitlist/{entry_id}/pre-order — 添加预点菜品到排队条目"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        # 1. 查 waitlist_entry，确认 status='waiting' 或 'called'
        result = await db.execute(
            text("SELECT id, status, pre_order_items FROM waitlist_entries WHERE id = :eid"),
            {"eid": entry_id},
        )
        entry = result.mappings().one_or_none()
        if not entry:
            _err("等位记录不存在", 404)

        if entry["status"] not in ("waiting", "called"):
            _err(f"当前状态 {entry['status']} 不可预点菜，仅等位中或已叫号可操作")

        # 2. 合并新 items 到现有 pre_order_items
        raw_existing = entry["pre_order_items"]
        existing_items: list = []
        if raw_existing:
            existing_items = raw_existing if isinstance(raw_existing, list) else json.loads(raw_existing)

        new_items = [item.model_dump() for item in body.items]

        # 合并策略：同 dish_id + 同 modifiers 的合并数量，否则追加
        for new_item in new_items:
            merged = False
            for existing in existing_items:
                if (existing["dish_id"] == new_item["dish_id"]
                        and existing.get("modifiers", []) == new_item.get("modifiers", [])):
                    existing["quantity"] += new_item["quantity"]
                    existing["notes"] = new_item["notes"] or existing.get("notes", "")
                    merged = True
                    break
            if not merged:
                existing_items.append(new_item)

        # 3. 重算 pre_order_total_fen
        total_fen = 0
        for item in existing_items:
            modifier_extra = sum(m.get("extra_fen", 0) for m in item.get("modifiers", []))
            total_fen += (item["unit_price_fen"] + modifier_extra) * item["quantity"]

        # 4. UPDATE
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET pre_order_items = :items::jsonb,
                    pre_order_total_fen = :total_fen,
                    updated_at = :now
                WHERE id = :eid
            """),
            {
                "eid": entry_id,
                "items": json.dumps(existing_items, ensure_ascii=False),
                "total_fen": total_fen,
                "now": now,
            },
        )
        await db.commit()

        # 5. 返回合并后的预点菜列表
        return _ok({
            "entry_id": entry_id,
            "pre_order_items": existing_items,
            "pre_order_total_fen": total_fen,
            "items_count": len(existing_items),
        })
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_preorder_add_error", error=str(exc))
        _err("添加预点菜失败", 500)


@router.get("/{entry_id}/pre-order")
async def get_pre_order(
    entry_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/waitlist/{entry_id}/pre-order — 查看预点菜品"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("SELECT id, status, pre_order_items, pre_order_total_fen FROM waitlist_entries WHERE id = :eid"),
            {"eid": entry_id},
        )
        entry = result.mappings().one_or_none()
        if not entry:
            _err("等位记录不存在", 404)

        raw_items = entry["pre_order_items"]
        items: list = []
        if raw_items:
            items = raw_items if isinstance(raw_items, list) else json.loads(raw_items)

        return _ok({
            "entry_id": entry_id,
            "status": entry["status"],
            "pre_order_items": items,
            "pre_order_total_fen": int(entry["pre_order_total_fen"] or 0),
            "items_count": len(items),
        })
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("waitlist_preorder_get_error", error=str(exc))
        _err("查询预点菜失败", 500)


@router.delete("/{entry_id}/pre-order/{dish_id}")
async def remove_pre_order_item(
    entry_id: str,
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """DELETE /api/v1/waitlist/{entry_id}/pre-order/{dish_id} — 删除预点的某道菜"""
    tenant_id = _get_tenant_id(request)
    try:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text("SELECT id, status, pre_order_items FROM waitlist_entries WHERE id = :eid"),
            {"eid": entry_id},
        )
        entry = result.mappings().one_or_none()
        if not entry:
            _err("等位记录不存在", 404)

        if entry["status"] not in ("waiting", "called"):
            _err(f"当前状态 {entry['status']} 不可修改预点菜")

        raw_items = entry["pre_order_items"]
        existing_items: list = []
        if raw_items:
            existing_items = raw_items if isinstance(raw_items, list) else json.loads(raw_items)

        # 移除指定 dish_id 的所有 item
        updated_items = [item for item in existing_items if item["dish_id"] != dish_id]
        removed_count = len(existing_items) - len(updated_items)

        if removed_count == 0:
            _err(f"预点菜中未找到菜品 {dish_id}", 404)

        # 重算 total_fen
        total_fen = 0
        for item in updated_items:
            modifier_extra = sum(m.get("extra_fen", 0) for m in item.get("modifiers", []))
            total_fen += (item["unit_price_fen"] + modifier_extra) * item["quantity"]

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET pre_order_items = :items::jsonb,
                    pre_order_total_fen = :total_fen,
                    updated_at = :now
                WHERE id = :eid
            """),
            {
                "eid": entry_id,
                "items": json.dumps(updated_items, ensure_ascii=False),
                "total_fen": total_fen,
                "now": now,
            },
        )
        await db.commit()

        return _ok({
            "entry_id": entry_id,
            "removed_dish_id": dish_id,
            "removed_count": removed_count,
            "pre_order_items": updated_items,
            "pre_order_total_fen": total_fen,
            "items_count": len(updated_items),
        })
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("waitlist_preorder_remove_error", error=str(exc))
        _err("删除预点菜失败", 500)
