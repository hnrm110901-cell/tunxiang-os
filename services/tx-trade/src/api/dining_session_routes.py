"""堂食会话 API — 桌台中心化架构核心路由 (v149)

负责 dining_sessions 的完整生命周期管理：
  开台 / 查询 / 桌台大板 / 状态迁移 / 转台 / 并台 / 买单 / 结账 / 清台 / VIP识别

v186新增：开台时自动关联当前营业市别（market_session_id）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.dining_session_service import DiningSessionService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/dining-sessions", tags=["dining-sessions"])


# ─── 通用工具 ─────────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> HTTPException:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


def _svc(db: AsyncSession, tenant_id: str) -> DiningSessionService:
    return DiningSessionService(db, tenant_id)


# ─── 请求 / 响应 Pydantic 模型 ────────────────────────────────────────────────

class OpenTableReq(BaseModel):
    """开台请求"""
    store_id:         uuid.UUID
    table_id:         uuid.UUID
    guest_count:      int        = Field(ge=1, le=100, description="就餐人数")
    lead_waiter_id:   uuid.UUID  = Field(description="责任服务员ID")
    zone_id:          Optional[uuid.UUID] = None
    booking_id:       Optional[uuid.UUID] = None
    vip_customer_id:  Optional[uuid.UUID] = None
    session_type:     str        = Field(
        default="dine_in",
        description="类型：dine_in/banquet/vip_room/self_order/hotpot",
    )

    @field_validator("session_type")
    @classmethod
    def _valid_session_type(cls, v: str) -> str:
        allowed = {"dine_in", "banquet", "vip_room", "self_order", "hotpot"}
        if v not in allowed:
            raise ValueError(f"session_type 必须是 {allowed} 之一")
        return v


class TransferTableReq(BaseModel):
    """转台请求"""
    target_table_id: uuid.UUID
    reason:          str = Field(max_length=200, description="转台原因")
    operator_id:     uuid.UUID


class MergeSessionsReq(BaseModel):
    """并台请求"""
    secondary_session_ids: list[uuid.UUID] = Field(
        min_length=1, description="要合并进来的副会话ID列表（至少1个）"
    )
    operator_id: uuid.UUID


class RequestBillReq(BaseModel):
    """买单请求"""
    operator_id: Optional[uuid.UUID] = None


class CompletePaymentReq(BaseModel):
    """结账完成（由支付服务回调）"""
    final_amount_fen:    int = Field(ge=0, description="实付金额（分）")
    discount_amount_fen: int = Field(default=0, ge=0, description="折扣金额（分）")


class ClearTableReq(BaseModel):
    """清台请求"""
    cleaner_id: uuid.UUID = Field(description="清台操作员工ID")


class IdentifyVipReq(BaseModel):
    """VIP识别请求"""
    customer_id:    uuid.UUID
    identified_by:  str = Field(
        default="scan",
        description="识别方式：scan/phone/face/manual",
    )


class UpdateGuestCountReq(BaseModel):
    """修改就餐人数"""
    guest_count: int = Field(ge=1, le=100)
    operator_id: Optional[uuid.UUID] = None


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.post("", summary="开台")
async def open_table(
    body: OpenTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    开台：创建堂食会话，锁定桌台状态为 occupied。

    - 同一桌台同一时刻只能有一个活跃会话
    - 若桌台已有活跃会话返回 409
    - 可从预订（booking_id）进来，自动关联预订单
    """
    tid = _get_tenant_id(request)
    svc = _svc(db, tid)
    try:
        session = await svc.open_table(
            store_id=body.store_id,
            table_id=body.table_id,
            guest_count=body.guest_count,
            lead_waiter_id=body.lead_waiter_id,
            zone_id=body.zone_id,
            booking_id=body.booking_id,
            vip_customer_id=body.vip_customer_id,
            session_type=body.session_type,
        )
    except ValueError as exc:
        _err(str(exc), code=409 if "已有活跃会话" in str(exc) else 400)

    # v186：开台后自动关联当前营业市别（后台异步，不阻塞开台响应）
    session_id_for_market = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
    if session_id_for_market:
        asyncio.create_task(
            _bind_market_session(db, tid, str(body.store_id), str(session_id_for_market))
        )

    return _ok(session)


async def _get_current_market_session_id(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
) -> Optional[str]:
    """查询当前时间所在的营业市别ID（优先门店配置，无则查集团模板）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, TRUE)"), {"tid": tenant_id}
    )
    now_time = datetime.now().time()

    def _in_session(start: time, end: time) -> bool:
        if start <= end:
            return start <= now_time < end
        return now_time >= start or now_time < end

    # 1. 门店自定义配置
    store_rows = (await db.execute(
        text("""
            SELECT id, start_time, end_time
            FROM store_market_sessions
            WHERE tenant_id = :tid AND store_id = :sid AND is_active = TRUE
        """),
        {"tid": tenant_id, "sid": store_id},
    )).fetchall()

    for row in store_rows:
        st = row.start_time if isinstance(row.start_time, time) else datetime.strptime(str(row.start_time), "%H:%M:%S").time()
        et = row.end_time if isinstance(row.end_time, time) else datetime.strptime(str(row.end_time), "%H:%M:%S").time()
        if _in_session(st, et):
            return str(row.id)

    # 2. 集团模板
    tmpl_rows = (await db.execute(
        text("""
            SELECT id, start_time, end_time
            FROM market_session_templates
            WHERE tenant_id = :tid AND is_active = TRUE
            ORDER BY display_order, start_time
        """),
        {"tid": tenant_id},
    )).fetchall()

    for row in tmpl_rows:
        st = row.start_time if isinstance(row.start_time, time) else datetime.strptime(str(row.start_time), "%H:%M:%S").time()
        et = row.end_time if isinstance(row.end_time, time) else datetime.strptime(str(row.end_time), "%H:%M:%S").time()
        if _in_session(st, et):
            return str(row.id)

    return None


async def _bind_market_session(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    session_id: str,
) -> None:
    """开台后台任务：查询当前市别并写入 dining_sessions.market_session_id"""
    try:
        market_session_id = await _get_current_market_session_id(db, tenant_id, store_id)
        if market_session_id:
            await db.execute(
                text("UPDATE dining_sessions SET market_session_id = :msid WHERE id = :sid"),
                {"msid": market_session_id, "sid": session_id},
            )
            await db.commit()
            logger.info(
                "market_session_bound",
                dining_session_id=session_id,
                market_session_id=market_session_id,
            )
    except Exception as exc:  # noqa: BLE001 - 市别关联失败不影响已完成的开台
        logger.warning("market_session_bind_failed", error=str(exc), dining_session_id=session_id)


@router.get("/board", summary="桌台大板")
async def get_store_board(
    store_id: uuid.UUID = Query(..., description="门店ID"),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    获取门店所有活跃会话的桌台大板（实时快照）。

    返回字段含：桌台信息、区域、服务员、用餐时长、待处理呼叫数、金额等。
    用于 POS 主界面桌台看板展示。
    """
    tid = _get_tenant_id(request)
    board = await _svc(db, tid).get_store_board(store_id)
    return _ok(board)


@router.get("/{session_id}", summary="获取会话详情")
async def get_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取单个堂食会话的完整详情（含关联桌台、服务员信息）"""
    tid = _get_tenant_id(request)
    session = await _svc(db, tid).get_session(session_id)
    if session is None:
        _err("会话不存在", code=404)
    return _ok(session)


@router.get("/by-table/{table_id}", summary="查桌台当前活跃会话")
async def get_active_by_table(
    table_id: uuid.UUID,
    store_id: uuid.UUID = Query(...),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取指定桌台的当前活跃会话。无活跃会话时返回 data: null。"""
    tid = _get_tenant_id(request)
    session = await _svc(db, tid).get_active_session_by_table(store_id, table_id)
    return _ok(session)


@router.post("/{session_id}/transfer", summary="转台")
async def transfer_table(
    session_id: uuid.UUID,
    body: TransferTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    转台：将当前桌台的会话迁移到目标桌台。

    - 旧桌台状态 → free
    - 新桌台状态 → occupied
    - 会话中所有订单自动跟随迁移
    - 若目标桌台已有活跃会话返回 409
    """
    tid = _get_tenant_id(request)
    try:
        session = await _svc(db, tid).transfer_table(
            session_id=session_id,
            target_table_id=body.target_table_id,
            reason=body.reason,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        _err(str(exc), code=409 if "已有活跃会话" in str(exc) else 400)
    return _ok(session)


@router.post("/{session_id}/merge", summary="并台")
async def merge_sessions(
    session_id: uuid.UUID,
    body: MergeSessionsReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    并台：将多个副会话合并到当前主会话。

    - 副会话的所有订单关联到主会话
    - 副会话桌台状态 → free
    - 副会话逻辑删除（保留历史审计）
    - 主会话金额重新汇总
    """
    tid = _get_tenant_id(request)
    try:
        session = await _svc(db, tid).merge_sessions(
            primary_session_id=session_id,
            secondary_session_ids=body.secondary_session_ids,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        _err(str(exc))
    return _ok(session)


@router.post("/{session_id}/request-bill", summary="买单")
async def request_bill(
    session_id: uuid.UUID,
    body: RequestBillReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    买单：状态迁移到 billing，记录买单时间。

    触发 TABLE.BILL_REQUESTED 事件。
    """
    tid = _get_tenant_id(request)
    try:
        session = await _svc(db, tid).request_bill(
            session_id=session_id,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        _err(str(exc))
    return _ok(session)


@router.post("/{session_id}/complete-payment", summary="结账完成")
async def complete_payment(
    session_id: uuid.UUID,
    body: CompletePaymentReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    结账完成回调（由 payment_service 在支付成功后调用）。

    - 更新实付金额、折扣、人均消费
    - 状态迁移到 paid
    - 触发 TABLE.PAID 事件（供 Agent 分析翻台率）
    """
    tid = _get_tenant_id(request)
    try:
        session = await _svc(db, tid).complete_payment(
            session_id=session_id,
            final_amount_fen=body.final_amount_fen,
            discount_amount_fen=body.discount_amount_fen,
        )
    except ValueError as exc:
        _err(str(exc))
    return _ok(session)


@router.post("/{session_id}/clear", summary="清台")
async def clear_table(
    session_id: uuid.UUID,
    body: ClearTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    清台：服务员确认桌面清理完毕。

    - 会话状态 → clearing（终态）
    - 桌台状态 → free（可供下一批客人开台）
    - 触发 TABLE.CLEARED 事件
    """
    tid = _get_tenant_id(request)
    try:
        await _svc(db, tid).clear_table(
            session_id=session_id,
            cleaner_id=body.cleaner_id,
        )
    except ValueError as exc:
        _err(str(exc))
    return _ok({"cleared": True})


@router.post("/{session_id}/identify-vip", summary="识别VIP")
async def identify_vip(
    session_id: uuid.UUID,
    body: IdentifyVipReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    中途识别VIP顾客（扫码/手机号/人脸）。

    触发 TABLE.VIP_IDENTIFIED 事件，会员洞察 Agent 订阅后
    自动推送个性化服务建议到服务员端。
    """
    tid = _get_tenant_id(request)
    try:
        session = await _svc(db, tid).identify_vip(
            session_id=session_id,
            customer_id=body.customer_id,
            identified_by=body.identified_by,
        )
    except ValueError as exc:
        _err(str(exc))
    return _ok(session)


@router.patch("/{session_id}/guest-count", summary="修改就餐人数")
async def update_guest_count(
    session_id: uuid.UUID,
    body: UpdateGuestCountReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """修改就餐人数（如追加客人入座）。同步更新人均消费。"""
    tid = _get_tenant_id(request)
    svc = _svc(db, tid)
    session = await svc.get_session(session_id)
    if session is None:
        _err("会话不存在", code=404)

    from sqlalchemy import text
    await db.execute(
        text("""
            UPDATE dining_sessions
            SET guest_count  = :guest_count,
                per_capita_fen = CASE
                    WHEN :guest_count > 0 AND final_amount_fen > 0
                    THEN final_amount_fen / :guest_count
                    ELSE per_capita_fen
                END,
                updated_at = NOW()
            WHERE id = :session_id
              AND tenant_id = :tenant_id
        """),
        {
            "guest_count": body.guest_count,
            "session_id": session_id,
            "tenant_id": str(tid),
        },
    )

    updated = await svc.get_session(session_id)
    return _ok(updated)


# ─── 低消豁免 ────────────────────────────────────────────────────────────────


class OverrideMinSpendReq(BaseModel):
    approver_id: uuid.UUID = Field(..., description="审批人（管理员）ID")


@router.post("/{session_id}/override-min-spend", summary="管理员豁免包间低消")
async def override_min_spend(
    session_id: uuid.UUID,
    body: OverrideMinSpendReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """管理员审批后豁免低消限制，允许未达低消桌台买单。

    需配合 approval_logs 表记录审批意图（前端负责写审批记录）。
    设置后 request_bill() 不再检查 min_spend_fen。
    """
    tid = _get_tenant_id(request)
    svc = _svc(db, tid)
    try:
        result = await svc.override_min_spend(session_id, body.approver_id)
        await db.commit()
        return _ok(result)
    except ValueError as exc:
        _err(str(exc))


# ─── 宴席场次关联 ────────────────────────────────────────────────────────────


class LinkBanquetSessionReq(BaseModel):
    banquet_session_id: uuid.UUID = Field(..., description="宴席场次ID")


@router.post("/{session_id}/link-banquet", summary="关联宴席场次")
async def link_banquet_session(
    session_id: uuid.UUID,
    body: LinkBanquetSessionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将堂食会话关联到宴席场次，用于宴席多桌统一调度和结账。"""
    tid = _get_tenant_id(request)
    from sqlalchemy import text
    session_result = await db.execute(
        text("SELECT id FROM dining_sessions WHERE id = :sid AND tenant_id = :tid AND is_deleted = false"),
        {"sid": session_id, "tid": str(tid)},
    )
    if session_result.one_or_none() is None:
        _err("会话不存在", code=404)

    await db.execute(
        text("""
            UPDATE dining_sessions
            SET banquet_session_id = :banquet_session_id, updated_at = NOW()
            WHERE id = :session_id AND tenant_id = :tenant_id
        """),
        {
            "banquet_session_id": body.banquet_session_id,
            "session_id": session_id,
            "tenant_id": str(tid),
        },
    )
    await db.commit()

    svc = _svc(db, tid)
    updated = await svc.get_session(session_id)
    return _ok(updated)
