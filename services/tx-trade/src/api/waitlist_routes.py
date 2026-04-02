"""等位调度引擎 API — 叫号队列管理

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
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["waitlist"])

# ─── 优先级映射 ──────────────────────────────────────────────────────────────

_MEMBER_LEVEL_PRIORITY: dict[str, int] = {
    "normal":   10,
    "silver":   20,
    "gold":     30,
    "black":    40,
    # 中文别名
    "普通会员": 10,
    "银卡":     20,
    "金卡":     30,
    "黑金":     40,
}

# 平均翻台时间（分钟）和估算公式分母（可用桌台数默认值）
_AVG_TURNOVER_MIN = 30
_DEFAULT_TABLE_COUNT = 5

# 过号超时阈值（分钟）
_EXPIRE_TIMEOUT_MIN = 15

# ─── 内存存储（生产替换为真实 DB 查询） ────────────────────────────────────
# 结构: { store_id: [entry_dict, ...] }
# 叫号日志: { entry_id: [log_dict, ...] }
_store: dict[str, list[dict]] = {}
_call_logs: dict[str, list[dict]] = {}


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entries_for_store(store_id: str) -> list[dict]:
    return _store.setdefault(store_id, [])


def _find_entry(store_id: str, entry_id: str) -> Optional[dict]:
    for e in _entries_for_store(store_id):
        if e["id"] == entry_id:
            return e
    return None


def _next_queue_no(store_id: str) -> int:
    """当日从101起递增（跨日重置）。"""
    today = datetime.now(timezone.utc).date().isoformat()
    entries = _entries_for_store(store_id)
    today_entries = [e for e in entries if e.get("date") == today]
    if not today_entries:
        return 101
    return max(e["queue_no"] for e in today_entries) + 1


def _estimate_wait(store_id: str) -> int:
    """估算等待分钟：当前waiting人数 × 30 / 5（简化公式）。"""
    waiting = sum(
        1 for e in _entries_for_store(store_id) if e["status"] == "waiting"
    )
    return max(0, (waiting * _AVG_TURNOVER_MIN) // _DEFAULT_TABLE_COUNT)


def _entry_to_dict(e: dict) -> dict:
    """返回API响应字段子集。"""
    return {
        "id":                e["id"],
        "queue_no":          e["queue_no"],
        "name":              e["name"],
        "phone":             e.get("phone"),
        "party_size":        e["party_size"],
        "table_type":        e.get("table_type"),
        "priority":          e["priority"],
        "status":            e["status"],
        "call_count":        e["call_count"],
        "estimated_wait_min": e.get("estimated_wait_min"),
        "called_at":         e.get("called_at"),
        "seated_at":         e.get("seated_at"),
        "expired_at":        e.get("expired_at"),
        "created_at":        e["created_at"],
    }


# ─── Pydantic 请求模型 ────────────────────────────────────────────────────────

class WaitlistCreateBody(BaseModel):
    store_id:   str
    name:       str
    phone:      Optional[str] = None
    party_size: int
    table_type: Optional[str] = None
    member_id:  Optional[str] = None

    @field_validator("party_size")
    @classmethod
    def party_size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("party_size must be >= 1")
        return v


class CallBody(BaseModel):
    operator_id: str
    channel:     str = "screen"


class SeatBody(BaseModel):
    table_no:    str
    operator_id: str


class CancelBody(BaseModel):
    reason:  Optional[str] = None
    expired: bool = False


# ─── 端点 ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_waitlist(
    request: Request,
    store_id: str = Query(...),
    status: Optional[str] = Query(None),
) -> dict:
    """GET /api/v1/waitlist?store_id=&status=waiting

    返回等位队列，按 priority DESC, created_at ASC 排序。
    """
    _get_tenant_id(request)
    entries = _entries_for_store(store_id)

    if status:
        entries = [e for e in entries if e["status"] == status]

    # 排序：priority 降序 → created_at 升序
    entries = sorted(entries, key=lambda e: (-e["priority"], e["created_at"]))

    return _ok({
        "items": [_entry_to_dict(e) for e in entries],
        "total": len(entries),
    })


@router.post("")
async def create_waitlist_entry(body: WaitlistCreateBody, request: Request) -> dict:
    """POST /api/v1/waitlist

    登记等位：自动分配队列号、推算优先级和预估等待时间。
    """
    tenant_id = _get_tenant_id(request)

    # 推算优先级（若有 member_id 查询等级，此处简化：member_id 存在=普通会员10）
    priority = 0
    if body.member_id:
        priority = _MEMBER_LEVEL_PRIORITY.get("normal", 10)

    today = datetime.now(timezone.utc).date().isoformat()
    queue_no = _next_queue_no(body.store_id)
    estimated_wait = _estimate_wait(body.store_id)

    entry: dict = {
        "id":                str(uuid4()),
        "tenant_id":         tenant_id,
        "store_id":          body.store_id,
        "date":              today,
        "queue_no":          queue_no,
        "name":              body.name,
        "phone":             body.phone,
        "party_size":        body.party_size,
        "table_type":        body.table_type,
        "member_id":         body.member_id,
        "priority":          priority,
        "status":            "waiting",
        "called_at":         None,
        "call_count":        0,
        "seated_at":         None,
        "expired_at":        None,
        "estimated_wait_min": estimated_wait,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }

    _entries_for_store(body.store_id).append(entry)
    logger.info("waitlist_entry_created store=%s queue_no=%s name=%s", body.store_id, queue_no, body.name)

    return _ok(_entry_to_dict(entry))


@router.post("/{entry_id}/call")
async def call_entry(entry_id: str, body: CallBody, request: Request) -> dict:
    """POST /api/v1/waitlist/{entry_id}/call

    叫号：更新状态为 called，记录叫号流水。
    若 channel=sms 且有手机号，记录 mock 日志（真实短信需配置服务商）。
    """
    tenant_id = _get_tenant_id(request)

    # 在所有门店中查找（store_id 未在路径中）
    entry = None
    for store_entries in _store.values():
        for e in store_entries:
            if e["id"] == entry_id and e["tenant_id"] == tenant_id:
                entry = e
                break
        if entry:
            break

    if not entry:
        _err(f"entry {entry_id} not found", 404)

    now = _now_iso()
    entry["status"] = "called"
    entry["called_at"] = now
    entry["call_count"] = entry.get("call_count", 0) + 1
    entry["updated_at"] = now

    # 写叫号日志
    log: dict = {
        "id":        str(uuid4()),
        "tenant_id": tenant_id,
        "entry_id":  entry_id,
        "channel":   body.channel,
        "called_by": body.operator_id,
        "created_at": now,
    }
    _call_logs.setdefault(entry_id, []).append(log)

    # SMS mock
    if body.channel == "sms" and entry.get("phone"):
        logger.info(
            "waitlist_sms_mock entry_id=%s phone=%s queue_no=%s name=%s [短信待接入真实服务商]",
            entry_id, entry["phone"], entry["queue_no"], entry["name"],
        )

    logger.info(
        "waitlist_called entry_id=%s queue_no=%s call_count=%s channel=%s operator=%s",
        entry_id, entry["queue_no"], entry["call_count"], body.channel, body.operator_id,
    )
    return _ok(_entry_to_dict(entry))


@router.post("/{entry_id}/seat")
async def seat_entry(entry_id: str, body: SeatBody, request: Request) -> dict:
    """POST /api/v1/waitlist/{entry_id}/seat

    入座：更新状态为 seated，记录入座时间。
    """
    tenant_id = _get_tenant_id(request)

    entry = None
    for store_entries in _store.values():
        for e in store_entries:
            if e["id"] == entry_id and e["tenant_id"] == tenant_id:
                entry = e
                break
        if entry:
            break

    if not entry:
        _err(f"entry {entry_id} not found", 404)

    now = _now_iso()
    entry["status"] = "seated"
    entry["seated_at"] = now
    entry["updated_at"] = now

    logger.info(
        "waitlist_seated entry_id=%s queue_no=%s table_no=%s operator=%s",
        entry_id, entry["queue_no"], body.table_no, body.operator_id,
    )
    return _ok(_entry_to_dict(entry))


@router.post("/{entry_id}/cancel")
async def cancel_entry(entry_id: str, body: CancelBody, request: Request) -> dict:
    """POST /api/v1/waitlist/{entry_id}/cancel

    取消或标记为过号（expired）。
    """
    tenant_id = _get_tenant_id(request)

    entry = None
    for store_entries in _store.values():
        for e in store_entries:
            if e["id"] == entry_id and e["tenant_id"] == tenant_id:
                entry = e
                break
        if entry:
            break

    if not entry:
        _err(f"entry {entry_id} not found", 404)

    now = _now_iso()
    new_status = "expired" if body.expired else "cancelled"
    entry["status"] = new_status
    entry["updated_at"] = now
    if body.expired:
        entry["expired_at"] = now

    logger.info(
        "waitlist_cancelled entry_id=%s queue_no=%s status=%s reason=%s",
        entry_id, entry["queue_no"], new_status, body.reason,
    )
    return _ok(_entry_to_dict(entry))


@router.post("/expire-overdue")
async def expire_overdue(request: Request, store_id: str = Query(...)) -> dict:
    """POST /api/v1/waitlist/expire-overdue?store_id=

    批量过号降级：called 超过15分钟的 entry → 状态重置为 waiting，priority=-10，
    记录 expired_at 时间戳。供前端定时轮询或 cron 调用。
    """
    _get_tenant_id(request)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_EXPIRE_TIMEOUT_MIN)
    now = _now_iso()
    expired_ids: list[str] = []

    for e in _entries_for_store(store_id):
        if e["status"] != "called" or not e.get("called_at"):
            continue
        called_dt = datetime.fromisoformat(e["called_at"])
        if called_dt.tzinfo is None:
            called_dt = called_dt.replace(tzinfo=timezone.utc)
        if called_dt < cutoff:
            e["status"] = "waiting"
            e["priority"] = -10
            e["expired_at"] = now
            e["updated_at"] = now
            expired_ids.append(e["id"])
            logger.info(
                "waitlist_expired entry_id=%s queue_no=%s name=%s",
                e["id"], e["queue_no"], e["name"],
            )

    return _ok({"expired_count": len(expired_ids), "expired_ids": expired_ids})


@router.get("/stats")
async def get_stats(request: Request, store_id: str = Query(...)) -> dict:
    """GET /api/v1/waitlist/stats?store_id=

    返回统计摘要：等待桌数、已叫号桌数、平均等待分钟、当前最大队列号。
    """
    _get_tenant_id(request)
    entries = _entries_for_store(store_id)

    waiting = [e for e in entries if e["status"] == "waiting"]
    called  = [e for e in entries if e["status"] == "called"]

    avg_wait = _estimate_wait(store_id)

    today = datetime.now(timezone.utc).date().isoformat()
    today_entries = [e for e in entries if e.get("date") == today]
    current_queue_no = max((e["queue_no"] for e in today_entries), default=100)

    return _ok({
        "waiting_count":    len(waiting),
        "called_count":     len(called),
        "avg_wait_min":     avg_wait,
        "current_queue_no": current_queue_no,
    })
