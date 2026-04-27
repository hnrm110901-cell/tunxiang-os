"""最低消费/服务费规则引擎 API — 模块1.4（对标天财商龙）

端点:
  GET  /api/v1/billing-rules/{store_id}                   获取门店账单规则列表
  PUT  /api/v1/billing-rules/{store_id}                   配置门店账单规则（管理员）
  POST /api/v1/orders/{order_id}/apply-billing-rules      结账时应用账单规则

规则类型:
  - min_spend   : 最低消费（fixed=固定金额 / per_person=人均）
  - service_fee : 服务费（fixed=固定金额 / per_person=按人头 / percentage=按比例）

豁免机制:
  - exempt_member_tiers     : 豁免的会员等级列表（如 ["gold","platinum"]）
  - exempt_agreement_units  : 豁免的协议单位列表

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
金额全部用分（整数），不使用浮点。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["billing-rules"])

VALID_RULE_TYPES = {"min_spend", "service_fee"}
VALID_CALC_METHODS = {"fixed", "per_person", "percentage"}


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


def _jsonb(obj) -> str:
    """将 Python 对象序列化为 JSON 字符串，供 ::jsonb 参数使用。"""
    return json.dumps(obj, ensure_ascii=False)


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class BillingRuleItem(BaseModel):
    """单条账单规则配置"""

    rule_type: str = Field(..., description="规则类型: min_spend / service_fee")
    calc_method: str = Field(default="fixed", description="计算方式: fixed / per_person / percentage")
    threshold_fen: int = Field(default=0, ge=0, description="阈值金额（分）")
    service_fee_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="服务费费率(0~1)，percentage时有效")
    exempt_member_tiers: list[str] = Field(default_factory=list, description="豁免会员等级列表")
    exempt_agreement_units: list[str] = Field(default_factory=list, description="豁免协议单位列表")
    is_active: bool = Field(default=True, description="是否启用")

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        if v not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {sorted(VALID_RULE_TYPES)}")
        return v

    @field_validator("calc_method")
    @classmethod
    def validate_calc_method(cls, v: str) -> str:
        if v not in VALID_CALC_METHODS:
            raise ValueError(f"calc_method must be one of {sorted(VALID_CALC_METHODS)}")
        return v


class SetBillingRulesReq(BaseModel):
    """配置门店账单规则请求（替换现有所有规则）"""

    rules: list[BillingRuleItem] = Field(..., min_length=1, description="规则列表，替换该门店全部规则")


class ApplyBillingRulesReq(BaseModel):
    """结账时应用账单规则请求"""

    store_id: str = Field(..., description="门店ID")
    order_amount_fen: int = Field(..., ge=0, description="订单金额（分，折扣前）")
    guest_count: int = Field(default=1, ge=1, description="就餐人数")
    member_tier: Optional[str] = Field(default=None, description="会员等级，用于判断豁免")
    agreement_unit_id: Optional[str] = Field(default=None, description="协议单位ID，用于判断豁免")


# ─── GET /api/v1/billing-rules/{store_id} ────────────────────────────────────


@router.get("/billing-rules/{store_id}", summary="获取门店账单规则")
async def get_billing_rules(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """获取指定门店的所有启用账单规则（min_spend + service_fee）。无配置时返回空列表。"""
    tenant_id = _get_tenant_id(request)

    rows = (
        await db.execute(
            text("""
            SELECT id, store_id, rule_type, calc_method, threshold_fen,
                   service_fee_rate, exempt_member_tiers, exempt_agreement_units,
                   is_active, created_at, updated_at
            FROM billing_rules
            WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
            ORDER BY rule_type, created_at
        """),
            {"tid": tenant_id, "sid": store_id},
        )
    ).fetchall()

    items = [
        {
            "id": str(r.id),
            "store_id": str(r.store_id),
            "rule_type": r.rule_type,
            "calc_method": r.calc_method,
            "threshold_fen": r.threshold_fen,
            "service_fee_rate": float(r.service_fee_rate),
            "exempt_member_tiers": r.exempt_member_tiers or [],
            "exempt_agreement_units": r.exempt_agreement_units or [],
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]

    return _ok({"store_id": store_id, "rules": items, "total": len(items)})


# ─── PUT /api/v1/billing-rules/{store_id} ────────────────────────────────────


@router.put("/billing-rules/{store_id}", summary="配置门店账单规则（管理员）")
async def set_billing_rules(
    store_id: str,
    body: SetBillingRulesReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """
    替换门店全部账单规则（软删除旧规则，写入新规则）。
    管理员操作，需要 X-Tenant-ID header。

    规则约束：
    - min_spend/fixed: threshold_fen 为最低消费总额（分）
    - min_spend/per_person: threshold_fen 为人均最低消费（分）
    - service_fee/fixed: threshold_fen 为固定服务费（分）
    - service_fee/per_person: threshold_fen 为每人服务费（分）
    - service_fee/percentage: service_fee_rate 为费率（0~1），threshold_fen 可忽略
    """
    tenant_id = _get_tenant_id(request)

    # 业务校验
    for rule in body.rules:
        if rule.rule_type == "service_fee" and rule.calc_method == "percentage":
            if rule.service_fee_rate <= 0:
                _err("service_fee/percentage 规则必须设置 service_fee_rate > 0")
        elif rule.threshold_fen <= 0:
            _err(f"{rule.rule_type}/{rule.calc_method} 规则必须设置 threshold_fen > 0")

    # 软删除现有规则
    await db.execute(
        text("""
            UPDATE billing_rules
            SET is_deleted = true, updated_at = NOW()
            WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
        """),
        {"tid": tenant_id, "sid": store_id},
    )

    # 批量插入新规则
    inserted_ids: list[str] = []
    for rule in body.rules:
        new_id = str(uuid.uuid4())
        # 将 service_fee_rate float 转为 Decimal-safe string for Numeric column
        rate_str = f"{rule.service_fee_rate:.4f}"
        await db.execute(
            text("""
                INSERT INTO billing_rules
                    (id, tenant_id, store_id, rule_type, calc_method,
                     threshold_fen, service_fee_rate,
                     exempt_member_tiers, exempt_agreement_units, is_active)
                VALUES
                    (:id, :tid, :sid, :rtype, :method,
                     :threshold, :rate::numeric,
                     :exempt_tiers::jsonb, :exempt_units::jsonb, :active)
            """),
            {
                "id": new_id,
                "tid": tenant_id,
                "sid": store_id,
                "rtype": rule.rule_type,
                "method": rule.calc_method,
                "threshold": rule.threshold_fen,
                "rate": rate_str,
                "exempt_tiers": _jsonb(rule.exempt_member_tiers),
                "exempt_units": _jsonb(rule.exempt_agreement_units),
                "active": rule.is_active,
            },
        )
        inserted_ids.append(new_id)

    await db.commit()

    logger.info(
        "billing_rules_updated",
        store_id=store_id,
        rules_count=len(body.rules),
        inserted_ids=inserted_ids,
    )

    return _ok(
        {
            "store_id": store_id,
            "rules_count": len(body.rules),
            "ids": inserted_ids,
        }
    )


# ─── POST /api/v1/orders/{order_id}/apply-billing-rules ──────────────────────


@router.post("/orders/{order_id}/apply-billing-rules", summary="结账时应用账单规则")
async def apply_billing_rules(
    order_id: str,
    body: ApplyBillingRulesReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """
    结账时应用门店账单规则，返回：
    - service_fee_items  : 服务费明细列表（可能多条）
    - service_fee_fen    : 服务费总额（分）
    - min_spend_shortfall_fen : 最低消费差额（0表示已满足）
    - min_spend_required_fen  : 最低消费要求金额（分）
    - total_extra_fen    : 需额外收取总额（服务费 + 最低消费差额）
    - exempted           : 是否被豁免
    - exemption_reason   : 豁免原因

    完成后旁路写入事件 OrderEventType.BILLING_RULE_APPLIED。
    """
    tenant_id = _get_tenant_id(request)

    # 拉取该门店所有启用规则
    rows = (
        await db.execute(
            text("""
            SELECT id, rule_type, calc_method, threshold_fen, service_fee_rate,
                   exempt_member_tiers, exempt_agreement_units
            FROM billing_rules
            WHERE tenant_id = :tid AND store_id = :sid
              AND is_active = true AND is_deleted = false
            ORDER BY rule_type, id
        """),
            {"tid": tenant_id, "sid": body.store_id},
        )
    ).fetchall()

    if not rows:
        return _ok(
            {
                "service_fee_items": [],
                "service_fee_fen": 0,
                "min_spend_shortfall_fen": 0,
                "min_spend_required_fen": 0,
                "total_extra_fen": 0,
                "exempted": False,
                "exemption_reason": None,
                "message": "该门店未配置账单规则",
            }
        )

    # ── 豁免检查（任一规则命中豁免条件即全局豁免）──────────────────────────
    exempted = False
    exemption_reason: Optional[str] = None

    for row in rows:
        exempt_tiers: list[str] = row.exempt_member_tiers or []
        exempt_units: list[str] = row.exempt_agreement_units or []

        if body.member_tier and body.member_tier in exempt_tiers:
            exempted = True
            exemption_reason = f"会员等级 {body.member_tier} 享受豁免"
            break
        if body.agreement_unit_id and body.agreement_unit_id in exempt_units:
            exempted = True
            exemption_reason = f"协议单位 {body.agreement_unit_id} 享受豁免"
            break

    # ── 服务费计算 ──────────────────────────────────────────────────────────
    service_fee_items: list[dict] = []
    service_fee_fen = 0

    if not exempted:
        for row in rows:
            if row.rule_type != "service_fee":
                continue

            method = row.calc_method
            fee_fen = 0
            description = ""

            if method == "fixed":
                fee_fen = int(row.threshold_fen)
                description = f"服务费（固定）¥{fee_fen / 100:.2f}"
            elif method == "per_person":
                fee_fen = int(row.threshold_fen) * body.guest_count
                description = f"服务费（{body.guest_count}人 × ¥{row.threshold_fen / 100:.2f}）¥{fee_fen / 100:.2f}"
            elif method == "percentage":
                rate = float(row.service_fee_rate)
                fee_fen = round(body.order_amount_fen * rate)
                pct = rate * 100
                description = f"服务费（{pct:.0f}%）¥{fee_fen / 100:.2f}"

            if fee_fen > 0:
                service_fee_items.append(
                    {
                        "rule_id": str(row.id),
                        "calc_method": method,
                        "fee_fen": fee_fen,
                        "description": description,
                    }
                )
                service_fee_fen += fee_fen

    # ── 最低消费计算 ────────────────────────────────────────────────────────
    min_spend_required_fen = 0
    min_spend_shortfall_fen = 0

    if not exempted:
        for row in rows:
            if row.rule_type != "min_spend":
                continue

            method = row.calc_method
            if method == "fixed":
                required = int(row.threshold_fen)
            elif method == "per_person":
                required = int(row.threshold_fen) * body.guest_count
            else:
                required = int(row.threshold_fen)

            if required > min_spend_required_fen:
                min_spend_required_fen = required

        if min_spend_required_fen > 0:
            min_spend_shortfall_fen = max(0, min_spend_required_fen - body.order_amount_fen)

    total_extra_fen = service_fee_fen + min_spend_shortfall_fen

    # ── 旁路写入事件（create_task，不阻塞结账主流程）──────────────────────
    try:
        from shared.events.src.emitter import emit_event
        from shared.events.src.event_types import OrderEventType

        asyncio.create_task(
            emit_event(
                event_type=OrderEventType.BILLING_RULE_APPLIED,
                tenant_id=tenant_id,
                stream_id=order_id,
                payload={
                    "store_id": body.store_id,
                    "order_amount_fen": body.order_amount_fen,
                    "service_fee_fen": service_fee_fen,
                    "min_spend_required_fen": min_spend_required_fen,
                    "min_spend_shortfall_fen": min_spend_shortfall_fen,
                    "total_extra_fen": total_extra_fen,
                    "exempted": exempted,
                    "guest_count": body.guest_count,
                },
                store_id=body.store_id,
                source_service="tx-trade",
                metadata={
                    "member_tier": body.member_tier,
                    "agreement_unit_id": body.agreement_unit_id,
                },
            )
        )
    except ImportError:
        pass  # 事件总线不可用时降级，不影响结账主流程

    logger.info(
        "billing_rules_applied",
        order_id=order_id,
        store_id=body.store_id,
        service_fee_fen=service_fee_fen,
        min_spend_shortfall_fen=min_spend_shortfall_fen,
        exempted=exempted,
    )

    message_parts: list[str] = []
    if service_fee_fen > 0:
        message_parts.append(f"服务费 ¥{service_fee_fen / 100:.2f}")
    if min_spend_shortfall_fen > 0:
        actual_yuan = body.order_amount_fen / 100
        required_yuan = min_spend_required_fen / 100
        gap_yuan = min_spend_shortfall_fen / 100
        message_parts.append(f"本桌消费¥{actual_yuan:.2f}，最低消费¥{required_yuan:.2f}，差额¥{gap_yuan:.2f}")

    return _ok(
        {
            "service_fee_items": service_fee_items,
            "service_fee_fen": service_fee_fen,
            "min_spend_shortfall_fen": min_spend_shortfall_fen,
            "min_spend_required_fen": min_spend_required_fen,
            "total_extra_fen": total_extra_fen,
            "exempted": exempted,
            "exemption_reason": exemption_reason,
            "message": "、".join(message_parts) if message_parts else "无额外账单规则",
        }
    )
