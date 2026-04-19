"""最低消费规则引擎 API — 配置/计算/报表 (v212)

端点:
  GET  /api/v1/minimum-consumption/config/{store_id}  获取门店最低消费规则
  PUT  /api/v1/minimum-consumption/config/{store_id}  设置规则
  POST /api/v1/minimum-consumption/calculate           计算是否满足最低消费
  GET  /api/v1/minimum-consumption/report              最低消费补齐统计报表

规则类型:
  - room        : 包间类型最低消费（大包/小包）
  - per_person  : 人均最低消费（可限制市别）
  - time_based  : 按市别最低消费（午市/晚市）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/minimum-consumption", tags=["minimum-consumption"])


# ─── 通用工具 ─────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


async def _get_tenant_db(request: Request):
    tid = _get_tenant_id(request)
    async for session in get_db_with_tenant(tid):
        yield session


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400):
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 请求 / 响应 Pydantic 模型 ────────────────────────────────────────────────


class RuleItem(BaseModel):
    """单条最低消费规则"""

    type: str = Field(..., description="规则类型: room / per_person / time_based")
    room_type: Optional[str] = Field(None, description="包间类型（type=room 时必填）")
    min_amount_fen: Optional[int] = Field(None, ge=0, description="最低消费金额（分）")
    min_per_person_fen: Optional[int] = Field(None, ge=0, description="人均最低消费（分，type=per_person）")
    surcharge_mode: Optional[str] = Field("补齐", description="不足处理方式: 补齐 / 拒单")
    applies_to: Optional[list[str]] = Field(None, description="适用市别列表")
    market_session: Optional[str] = Field(None, description="市别名称（type=time_based）")


class WaiveConditions(BaseModel):
    """豁免条件"""

    vip_level_gte: Optional[int] = Field(None, ge=0, description="VIP等级>=此值可豁免")
    group_size_gte: Optional[int] = Field(None, ge=1, description="人数>=此值可豁免")


class SetConfigReq(BaseModel):
    """设置最低消费规则"""

    rules: list[RuleItem] = Field(..., min_length=1, description="规则列表")
    waive_conditions: Optional[WaiveConditions] = Field(default=None, description="豁免条件")


class CalculateReq(BaseModel):
    """计算最低消费请求"""

    store_id: str = Field(..., description="门店ID")
    dining_session_id: str = Field(..., description="堂食会话ID")
    order_amount_fen: int = Field(..., ge=0, description="当前订单金额（分）")
    guest_count: int = Field(default=1, ge=1, description="就餐人数")
    room_type: Optional[str] = Field(None, description="包间类型")
    market_session: Optional[str] = Field(None, description="当前市别: lunch/dinner")
    vip_level: Optional[int] = Field(default=0, ge=0, description="顾客VIP等级")


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/config/{store_id}", summary="获取门店最低消费规则")
async def get_config(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """获取指定门店的最低消费规则配置。无配置时返回空默认值。"""
    tenant_id = _get_tenant_id(request)
    row = (
        await db.execute(
            text("""
            SELECT id, store_id, rules, waive_conditions, is_active,
                   created_at, updated_at
            FROM minimum_consumption_configs
            WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
        """),
            {"tid": tenant_id, "sid": store_id},
        )
    ).fetchone()

    if row is None:
        return _ok(
            {
                "store_id": store_id,
                "rules": [],
                "waive_conditions": {},
                "is_active": False,
            }
        )

    return _ok(
        {
            "id": str(row.id),
            "store_id": str(row.store_id),
            "rules": row.rules,
            "waive_conditions": row.waive_conditions,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    )


@router.put("/config/{store_id}", summary="设置门店最低消费规则")
async def set_config(
    store_id: str,
    body: SetConfigReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """
    设置门店最低消费规则（UPSERT）。

    规则类型：
    - room: 包间类型最低消费
    - per_person: 人均最低消费
    - time_based: 按市别最低消费
    """
    tenant_id = _get_tenant_id(request)

    # 校验规则合法性
    for rule in body.rules:
        if rule.type == "room" and not rule.room_type:
            _err("room 类型规则必须指定 room_type")
        if rule.type == "room" and rule.min_amount_fen is None:
            _err("room 类型规则必须指定 min_amount_fen")
        if rule.type == "per_person" and rule.min_per_person_fen is None:
            _err("per_person 类型规则必须指定 min_per_person_fen")
        if rule.type == "time_based" and (rule.market_session is None or rule.min_amount_fen is None):
            _err("time_based 类型规则必须指定 market_session 和 min_amount_fen")
        if rule.type not in ("room", "per_person", "time_based"):
            _err(f"不支持的规则类型: {rule.type}，仅支持 room/per_person/time_based")

    rules_json = [r.model_dump(exclude_none=True) for r in body.rules]
    waive_json = body.waive_conditions.model_dump(exclude_none=True) if body.waive_conditions else {}

    # UPSERT: 利用唯一索引 (tenant_id, store_id)
    existing = (
        await db.execute(
            text("""
            SELECT id FROM minimum_consumption_configs
            WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
        """),
            {"tid": tenant_id, "sid": store_id},
        )
    ).fetchone()

    if existing:
        await db.execute(
            text("""
                UPDATE minimum_consumption_configs
                SET rules = :rules::jsonb,
                    waive_conditions = :waive::jsonb,
                    is_active = true,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"rules": _jsonb(rules_json), "waive": _jsonb(waive_json), "id": existing.id},
        )
        config_id = str(existing.id)
    else:
        new_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO minimum_consumption_configs
                    (id, tenant_id, store_id, rules, waive_conditions, is_active)
                VALUES (:id, :tid, :sid, :rules::jsonb, :waive::jsonb, true)
            """),
            {
                "id": new_id,
                "tid": tenant_id,
                "sid": store_id,
                "rules": _jsonb(rules_json),
                "waive": _jsonb(waive_json),
            },
        )
        config_id = new_id

    await db.commit()

    logger.info(
        "minimum_consumption_config_saved",
        store_id=store_id,
        rules_count=len(body.rules),
    )

    return _ok(
        {
            "id": config_id,
            "store_id": store_id,
            "rules": rules_json,
            "waive_conditions": waive_json,
            "is_active": True,
        }
    )


@router.post("/calculate", summary="计算是否满足最低消费")
async def calculate(
    body: CalculateReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """
    根据当前订单上下文计算是否满足最低消费。

    返回:
    - satisfied: 是否满足
    - shortfall_fen: 差额（分）
    - matched_rule: 命中的规则
    - waived: 是否被豁免
    - surcharge_fen: 需要补齐的金额（分）
    """
    tenant_id = _get_tenant_id(request)

    # 获取门店规则配置
    config_row = (
        await db.execute(
            text("""
            SELECT rules, waive_conditions
            FROM minimum_consumption_configs
            WHERE tenant_id = :tid AND store_id = :sid
              AND is_active = true AND is_deleted = false
        """),
            {"tid": tenant_id, "sid": body.store_id},
        )
    ).fetchone()

    if config_row is None:
        return _ok(
            {
                "satisfied": True,
                "shortfall_fen": 0,
                "matched_rule": None,
                "waived": False,
                "surcharge_fen": 0,
                "message": "该门店未配置最低消费规则",
            }
        )

    rules: list[dict] = config_row.rules or []
    waive_conditions: dict = config_row.waive_conditions or {}

    # 1. 检查豁免条件
    waived = False
    waive_reason = None

    vip_gte = waive_conditions.get("vip_level_gte")
    if vip_gte is not None and body.vip_level >= vip_gte:
        waived = True
        waive_reason = f"VIP等级{body.vip_level} >= 豁免阈值{vip_gte}"

    group_gte = waive_conditions.get("group_size_gte")
    if group_gte is not None and body.guest_count >= group_gte:
        waived = True
        waive_reason = f"就餐人数{body.guest_count} >= 豁免阈值{group_gte}"

    # 2. 按优先级匹配规则: room > per_person > time_based
    matched_rule = None
    min_required_fen = 0

    for rule in rules:
        rtype = rule.get("type")
        if rtype == "room" and body.room_type and rule.get("room_type") == body.room_type:
            matched_rule = rule
            min_required_fen = rule.get("min_amount_fen", 0)
            break
        if rtype == "per_person":
            applies = rule.get("applies_to")
            if applies is None or body.market_session in applies:
                per_person_min = rule.get("min_per_person_fen", 0)
                min_required_fen = per_person_min * body.guest_count
                matched_rule = rule
                break
        if rtype == "time_based" and rule.get("market_session") == body.market_session:
            matched_rule = rule
            min_required_fen = rule.get("min_amount_fen", 0)
            break

    if matched_rule is None:
        return _ok(
            {
                "satisfied": True,
                "shortfall_fen": 0,
                "matched_rule": None,
                "waived": False,
                "surcharge_fen": 0,
                "message": "未命中任何最低消费规则",
            }
        )

    shortfall_fen = max(0, min_required_fen - body.order_amount_fen)
    satisfied = shortfall_fen == 0 or waived

    surcharge_mode = matched_rule.get("surcharge_mode", "补齐")
    surcharge_fen = shortfall_fen if surcharge_mode == "补齐" and not waived else 0

    # 3. 记录补齐记录（仅当有差额且未豁免时）
    if shortfall_fen > 0:
        await db.execute(
            text("""
                INSERT INTO minimum_consumption_surcharges
                    (tenant_id, store_id, dining_session_id, rule_type,
                     min_amount_fen, actual_amount_fen, surcharge_fen,
                     waived, waive_reason)
                VALUES (:tid, :sid, :dsid, :rtype,
                        :min_fen, :actual_fen, :surcharge_fen,
                        :waived, :waive_reason)
            """),
            {
                "tid": tenant_id,
                "sid": body.store_id,
                "dsid": body.dining_session_id,
                "rtype": matched_rule.get("type"),
                "min_fen": min_required_fen,
                "actual_fen": body.order_amount_fen,
                "surcharge_fen": surcharge_fen,
                "waived": waived,
                "waive_reason": waive_reason,
            },
        )
        await db.commit()

    return _ok(
        {
            "satisfied": satisfied,
            "shortfall_fen": shortfall_fen,
            "matched_rule": matched_rule,
            "waived": waived,
            "waive_reason": waive_reason,
            "surcharge_fen": surcharge_fen,
            "min_required_fen": min_required_fen,
            "order_amount_fen": body.order_amount_fen,
            "message": ("已满足最低消费" if satisfied else f"未达最低消费，差额 {shortfall_fen / 100:.2f} 元"),
        }
    )


@router.get("/report", summary="最低消费补齐统计报表")
async def surcharge_report(
    store_id: str = Query(..., description="门店ID"),
    start_date: date = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: date = Query(..., description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    request: Request = ...,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """
    统计指定门店在时间范围内的最低消费补齐记录。

    返回:
    - items: 补齐记录列表
    - summary: 汇总统计（总补齐金额、总次数、豁免次数）
    - total: 总记录数
    """
    tenant_id = _get_tenant_id(request)

    # 汇总统计
    summary_row = (
        await db.execute(
            text("""
            SELECT
                COUNT(*)                                       AS total_count,
                COALESCE(SUM(surcharge_fen), 0)                AS total_surcharge_fen,
                COUNT(*) FILTER (WHERE waived = true)          AS waived_count,
                COUNT(*) FILTER (WHERE waived = false AND surcharge_fen > 0) AS charged_count,
                COALESCE(SUM(surcharge_fen) FILTER (WHERE waived = false), 0) AS effective_surcharge_fen
            FROM minimum_consumption_surcharges
            WHERE tenant_id = :tid AND store_id = :sid
              AND created_at >= :start AND created_at < :end::date + 1
              AND is_deleted = false
        """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
        )
    ).fetchone()

    total_count = summary_row.total_count if summary_row else 0

    # 分页明细
    offset = (page - 1) * size
    rows = (
        await db.execute(
            text("""
            SELECT s.id, s.dining_session_id, s.rule_type,
                   s.min_amount_fen, s.actual_amount_fen, s.surcharge_fen,
                   s.waived, s.waive_reason, s.created_at
            FROM minimum_consumption_surcharges s
            WHERE s.tenant_id = :tid AND s.store_id = :sid
              AND s.created_at >= :start AND s.created_at < :end::date + 1
              AND s.is_deleted = false
            ORDER BY s.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "limit": size,
                "offset": offset,
            },
        )
    ).fetchall()

    items = [
        {
            "id": str(r.id),
            "dining_session_id": str(r.dining_session_id),
            "rule_type": r.rule_type,
            "min_amount_fen": r.min_amount_fen,
            "actual_amount_fen": r.actual_amount_fen,
            "surcharge_fen": r.surcharge_fen,
            "waived": r.waived,
            "waive_reason": r.waive_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    return _ok(
        {
            "items": items,
            "total": total_count,
            "page": page,
            "size": size,
            "summary": {
                "total_count": summary_row.total_count if summary_row else 0,
                "total_surcharge_fen": summary_row.total_surcharge_fen if summary_row else 0,
                "effective_surcharge_fen": summary_row.effective_surcharge_fen if summary_row else 0,
                "waived_count": summary_row.waived_count if summary_row else 0,
                "charged_count": summary_row.charged_count if summary_row else 0,
            },
        }
    )


# ─── 内部工具 ─────────────────────────────────────────────────────────────────


def _jsonb(obj) -> str:
    """将 Python 对象序列化为 JSON 字符串，供 ::jsonb 参数使用。"""
    import json

    return json.dumps(obj, ensure_ascii=False)
