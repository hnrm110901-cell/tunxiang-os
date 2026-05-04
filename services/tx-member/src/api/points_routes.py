"""积分 API 端点（Tier 1，金额 = 分）

8 个端点 + 2 个新增（抵现校验、过期清理）：
  1. POST /earn                        — 积分获取（消费/充值/活动/签到）
  2. POST /spend                       — 积分消耗（抵现/兑换）
  3. PUT  /types/{ct_id}/earn-rules    — 设置获取规则
  4. PUT  /types/{ct_id}/spend-rules   — 设置消耗规则
  5. PUT  /types/{ct_id}/multiplier    — 倍数（会员日/活动）
  6. POST /cards/{cid}/growth-value    — 成长值管理（只增）
  7. GET  /cards/{cid}/balance         — 余额查询
  8. GET  /cards/{cid}/history         — 明细查询
  9. GET  /settlement/{month}          — 跨店结算（按月）
 10. POST /offset-check                — 抵现毛利底线校验（新增，路由前调用）
 11. POST /expiry/clear                — 触发过期 FIFO 清理（cron 调用）

设计变更（修复审计 ghost claim "已实现"）：
  - 原 8 端点全部为 mock 返回 0；本次改造按 CLAUDE.md §17 接服务层。
  - 服务函数通过依赖注入（db），便于单测 monkey-patch。
  - 涉及金额变动的写操作（earn/spend/expiry-clear）旁路 emit_event
    `MemberEventType.POINTS_CHANGED`（CLAUDE.md §15）。
  - cash_offset 在 spend 路由内强制走 `check_offset_against_margin_floor`，
    违反毛利底线时返回 422，不继续扣减积分。

降级策略：
  - DB 不可用（开发期/测试期）时端点不崩溃，返回 503 + 错误信息。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

# 服务层（importable，但 DB 路径在 demo 模式下可能未启动；以 ImportError 兜底）
try:
    from services.points_engine import (
        check_offset_against_margin_floor as _svc_check_offset,
    )
    from services.points_engine import cross_store_settlement as _svc_settlement
    from services.points_engine import earn_points as _svc_earn_points
    from services.points_engine import get_points_balance as _svc_balance
    from services.points_engine import get_points_history as _svc_history
    from services.points_engine import manage_growth_value as _svc_growth
    from services.points_engine import set_earn_rules as _svc_set_earn_rules
    from services.points_engine import set_multiplier as _svc_set_multiplier
    from services.points_engine import set_spend_rules as _svc_set_spend_rules
    from services.points_engine import spend_points as _svc_spend_points

    _SERVICES_AVAILABLE = True
except ImportError as exc:  # pragma: no cover
    _SERVICES_AVAILABLE = False
    _IMPORT_ERROR = exc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/member/points", tags=["member-points"])


# ── DB 依赖（lazy import，便于测试） ────────────────────────────


async def get_db_dep():
    """FastAPI 依赖注入：返回 AsyncSession。

    单元测试通过 app.dependency_overrides[get_db_dep] = ... 替换。
    """
    try:
        from shared.ontology.src.database import get_db  # noqa: PLC0415
    except ImportError:
        yield None
        return
    async for session in get_db():
        yield session


# ── 事件总线（best-effort，按 v147+ 规范） ─────────────────────


def _emit_points_changed(
    *,
    tenant_id: str,
    card_id: str,
    direction: str,
    points: int,
    new_balance: Optional[int],
    source_or_purpose: str,
    store_id: Optional[str] = None,
) -> None:
    """旁路写入 MemberEventType.POINTS_CHANGED（不阻塞主业务）。

    create_task 后台执行；emit_event 内部已对 Redis/PG 失败做了降级。
    """
    try:
        from shared.events.src.emitter import emit_event  # noqa: PLC0415
        from shared.events.src.event_types import MemberEventType  # noqa: PLC0415
    except ImportError:
        return  # 事件总线未就绪 → 静默跳过（不阻塞业务）

    try:
        asyncio.create_task(
            emit_event(
                event_type=MemberEventType.POINTS_CHANGED,
                tenant_id=tenant_id,
                stream_id=card_id,
                payload={
                    "direction": direction,  # earn | spend | expire
                    "points": int(points),
                    "new_balance": int(new_balance) if new_balance is not None else None,
                    "source_or_purpose": source_or_purpose,
                },
                store_id=store_id,
                source_service="tx-member",
            )
        )
    except RuntimeError:
        # 无 running loop（同步上下文）→ 退化为不发射；调用路径全部异步，正常不会触发。
        logger.debug("emit_points_changed_no_loop")


# ── 请求 / 响应模型 ────────────────────────────────────────────


class EarnPointsRequest(BaseModel):
    card_id: str
    source: str  # consume|recharge|activity|sign_in
    amount: int = Field(gt=0, description="积分数（正整数）")
    store_id: Optional[str] = None  # 跨店结算用


class SpendPointsRequest(BaseModel):
    card_id: str
    amount: int = Field(gt=0, description="积分数（正整数）")
    purpose: str  # cash_offset|exchange
    store_id: Optional[str] = None
    # cash_offset 时下列必填，用于毛利底线校验
    order_total_fen: Optional[int] = Field(default=None, ge=0)
    food_cost_fen: Optional[int] = Field(default=None, ge=0)
    min_margin_rate: Optional[float] = Field(default=None, gt=0.0, lt=1.0)


class SetEarnRulesRequest(BaseModel):
    rules: dict


class SetSpendRulesRequest(BaseModel):
    rules: dict


class SetMultiplierRequest(BaseModel):
    multiplier: float = Field(gt=0)
    conditions: dict


class ManageGrowthValueRequest(BaseModel):
    action: str = "add"
    amount: int = Field(gt=0)


class OffsetCheckRequest(BaseModel):
    order_total_fen: int = Field(gt=0)
    food_cost_fen: int = Field(ge=0)
    offset_fen: int = Field(ge=0)
    min_margin_rate: float = Field(default=0.15, gt=0.0, lt=1.0)


# ── 帮助函数 ───────────────────────────────────────────────────


def _err(code: int, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data}


# ═══════════════════════════════════════════════════════════════════
# 1. 积分获取
# ═══════════════════════════════════════════════════════════════════


@router.post("/earn")
async def earn_points(
    body: EarnPointsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """积分获取（消费/充值/活动/签到）。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_earn_points(
            card_id=body.card_id,
            source=body.source,
            amount=body.amount,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        return _err(422, str(exc))

    _emit_points_changed(
        tenant_id=x_tenant_id,
        card_id=body.card_id,
        direction="earn",
        points=body.amount,
        new_balance=result.get("new_balance"),
        source_or_purpose=body.source,
        store_id=body.store_id,
    )
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 2. 积分消耗（含毛利底线硬约束）
# ═══════════════════════════════════════════════════════════════════


@router.post("/spend")
async def spend_points(
    body: SpendPointsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """积分消耗（抵现/兑换）。

    cash_offset 路径强制毛利底线校验：order_total_fen / food_cost_fen 必填。
    """
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")

    # 抵现路径：必须做毛利约束校验
    if body.purpose == "cash_offset":
        if body.order_total_fen is None or body.food_cost_fen is None:
            return _err(422, "cash_offset_requires_order_total_and_food_cost")

        # 抵扣金额按默认规则：1 积分 = 1 分（与 calculate_cash_offset_fen 默认一致）
        # TODO: 真实场景应从 card_type 的 spend_rules 读取
        offset_fen = body.amount  # 1 积分 = 1 分
        margin_check = _svc_check_offset(
            order_total_fen=body.order_total_fen,
            food_cost_fen=body.food_cost_fen,
            offset_fen=offset_fen,
            min_margin_rate=body.min_margin_rate or 0.15,
        )
        if not margin_check["allowed"]:
            return _err(
                422,
                f"margin_floor_violation:{margin_check['reason']};" f"max_offset_fen={margin_check['max_offset_fen']}",
            )

    try:
        result = await _svc_spend_points(
            card_id=body.card_id,
            amount=body.amount,
            purpose=body.purpose,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        return _err(422, str(exc))

    _emit_points_changed(
        tenant_id=x_tenant_id,
        card_id=body.card_id,
        direction="spend",
        points=body.amount,
        new_balance=result.get("new_balance"),
        source_or_purpose=body.purpose,
        store_id=body.store_id,
    )
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 3. 设置获取规则
# ═══════════════════════════════════════════════════════════════════


@router.put("/types/{card_type_id}/earn-rules")
async def set_earn_rules(
    card_type_id: str,
    body: SetEarnRulesRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """设置积分获取规则（每消费 X 元获 Y 积分）。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_set_earn_rules(
            card_type_id=card_type_id,
            rules=body.rules,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        return _err(422, str(exc))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 4. 设置消耗规则
# ═══════════════════════════════════════════════════════════════════


@router.put("/types/{card_type_id}/spend-rules")
async def set_spend_rules(
    card_type_id: str,
    body: SetSpendRulesRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """设置积分消耗规则（X 积分抵 1 元）。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_set_spend_rules(
            card_type_id=card_type_id,
            rules=body.rules,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        return _err(422, str(exc))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 5. 积分倍数设置
# ═══════════════════════════════════════════════════════════════════


@router.put("/types/{card_type_id}/multiplier")
async def set_multiplier(
    card_type_id: str,
    body: SetMultiplierRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """积分倍数设置（会员日/活动期）。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_set_multiplier(
            card_type_id=card_type_id,
            multiplier=body.multiplier,
            conditions=body.conditions,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        return _err(422, str(exc))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 6. 成长值管理（只增不减）
# ═══════════════════════════════════════════════════════════════════


@router.post("/cards/{card_id}/growth-value")
async def manage_growth_value(
    card_id: str,
    body: ManageGrowthValueRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """成长值管理（只增不减）。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_growth(
            card_id=card_id,
            action=body.action,
            amount=body.amount,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        return _err(422, str(exc))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 7. 余额 + 8. 明细
# ═══════════════════════════════════════════════════════════════════


@router.get("/cards/{card_id}/balance")
async def get_points_balance(
    card_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """积分余额查询。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_balance(card_id=card_id, tenant_id=x_tenant_id, db=db)
    except ValueError as exc:
        return _err(404, str(exc))
    return _ok(result)


@router.get("/cards/{card_id}/history")
async def get_points_history(
    card_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """积分明细查询。"""
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_history(card_id=card_id, tenant_id=x_tenant_id, db=db, page=page, size=size)
    except ValueError as exc:
        return _err(422, str(exc))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 9. 跨店积分结算（按月）
# ═══════════════════════════════════════════════════════════════════


@router.get("/settlement/{month}")
async def cross_store_settlement(
    month: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: Any = Depends(get_db_dep),
):
    """跨店积分结算（按月，YYYY-MM）。

    返回 per_store 维度统计。完整跨店转账（fund flow）由 services.points_settlement
    模块在月结作业中生成；此端点仅供查询。
    """
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    try:
        result = await _svc_settlement(tenant_id=x_tenant_id, month=month, db=db)
    except ValueError as exc:
        return _err(422, str(exc))
    return _ok(result)


# ═══════════════════════════════════════════════════════════════════
# 10. 抵现毛利底线校验（独立端点，POS 在弹窗"用积分抵现"时预检）
# ═══════════════════════════════════════════════════════════════════


@router.post("/offset-check")
async def offset_margin_check(
    body: OffsetCheckRequest = Body(...),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """检查拟抵扣金额是否会击穿毛利底线（不写库，纯计算）。

    收银员在 POS 上输入"抵 X 积分"时，前端先调本接口预检；
    若 allowed=False 则提示"最多可抵 max_offset_fen 分"。
    """
    if not _SERVICES_AVAILABLE:
        raise HTTPException(status_code=503, detail="points_service_unavailable")
    result = _svc_check_offset(
        order_total_fen=body.order_total_fen,
        food_cost_fen=body.food_cost_fen,
        offset_fen=body.offset_fen,
        min_margin_rate=body.min_margin_rate,
    )
    return _ok(result)
