"""优惠策略 API — prefix /api/v1/offers

端点（6个）:
1. POST /api/v1/offers                           创建优惠策略
2. GET  /api/v1/offers                           优惠策略列表
3. GET  /api/v1/offers/{offer_id}                优惠策略详情
4. POST /api/v1/offers/check-eligibility         检查用户是否可使用优惠
5. GET  /api/v1/offers/{offer_id}/analytics      优惠效果分析
6. GET  /api/v1/offers/recommend/{segment_id}    AI推荐优惠策略

v144 表：offers / offer_redemptions
RLS 通过 set_config('app.tenant_id') 激活
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/offers", tags=["growth-offers"])

# 优惠类型 → 默认参数映射
_TYPE_DEFAULTS: dict[str, dict] = {
    "new_customer_trial": {
        "description": "新客首单体验优惠",
        "typical_discount_pct": 15,
        "goal": "acquisition",
    },
    "first_addon": {
        "description": "首单加购优惠（满减/加价换购）",
        "typical_discount_pct": 10,
        "goal": "aov_lift",
    },
    "second_visit": {
        "description": "二次到店优惠券",
        "typical_discount_pct": 20,
        "goal": "retention",
    },
    "birthday_reward": {
        "description": "生日专属礼遇",
        "typical_discount_pct": 25,
        "goal": "loyalty",
    },
    "stored_value_bonus": {
        "description": "储值赠送额",
        "typical_discount_pct": 10,
        "goal": "lock_in",
    },
    "banquet_inquiry_gift": {
        "description": "宴会咨询到店礼",
        "typical_discount_pct": 5,
        "goal": "conversion",
    },
    "referral_reward": {
        "description": "老带新双向奖励",
        "typical_discount_pct": 15,
        "goal": "acquisition",
    },
    "new_dish_trial": {
        "description": "新品限时尝鲜价",
        "typical_discount_pct": 20,
        "goal": "trial",
    },
    "off_peak_traffic": {
        "description": "闲时到店优惠",
        "typical_discount_pct": 15,
        "goal": "traffic",
    },
}

_VALID_OFFER_TYPES = set(_TYPE_DEFAULTS.keys())

# 人群 → 推荐优惠类型映射
_SEGMENT_OFFER_MAP: dict[str, list[dict]] = {
    "new_customer": [
        {
            "offer_type": "new_customer_trial",
            "name": "新客首单立减20元",
            "discount_rules": {"type": "fixed_amount", "amount_fen": 2000},
            "reason": "降低新客首单门槛，提高转化率",
            "expected_roi": 3.5,
        },
    ],
    "first_no_repeat": [
        {
            "offer_type": "second_visit",
            "name": "二次到店享8折",
            "discount_rules": {"type": "percentage", "pct": 20},
            "reason": "首单未复购客户需要强激励驱动第二次消费",
            "expected_roi": 2.8,
        },
    ],
    "dormant": [
        {
            "offer_type": "second_visit",
            "name": "老客回归礼-满100减30",
            "discount_rules": {"type": "threshold", "threshold_fen": 10000, "reduce_fen": 3000},
            "reason": "沉睡客需要较大力度召回",
            "expected_roi": 2.2,
        },
    ],
    "high_frequency": [
        {
            "offer_type": "stored_value_bonus",
            "name": "充500送80",
            "discount_rules": {"type": "stored_value", "charge_fen": 50000, "bonus_fen": 8000},
            "reason": "高频客户适合用储值锁客，提高粘性",
            "expected_roi": 4.5,
        },
    ],
    "high_value_banquet": [
        {
            "offer_type": "banquet_inquiry_gift",
            "name": "宴会预订享专属管家服务",
            "discount_rules": {"type": "service_upgrade", "description": "专属管家+赠送果盘"},
            "reason": "高价值客户重服务不重折扣",
            "expected_roi": 6.0,
        },
    ],
}


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


def _row_to_offer(row) -> dict:
    def _j(v: Any) -> Any:
        if v is None:
            return None
        return v if isinstance(v, (dict, list)) else json.loads(v)

    return {
        "offer_id": str(row.id),
        "name": row.name,
        "offer_type": row.offer_type,
        "description": row.description,
        "goal": row.goal,
        "discount_rules": _j(row.discount_rules),
        "validity_days": row.validity_days,
        "target_segments": _j(row.target_segments) or [],
        "applicable_stores": _j(row.applicable_stores) or [],
        "time_slots": _j(row.time_slots) or [],
        "margin_floor": float(row.margin_floor),
        "max_per_user": row.max_per_user,
        "status": row.status,
        "stats": {
            "issued_count": row.issued_count,
            "redeemed_count": row.redeemed_count,
            "total_discount_fen": row.total_discount_fen,
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateOfferRequest(BaseModel):
    name: str
    offer_type: str
    discount_rules: dict
    validity_days: int = 30
    target_segments: list[str] = []
    stores: list[str] = []
    time_slots: list[dict] = []
    margin_floor: float = 0.45
    max_per_user: int = 1

    @field_validator("offer_type")
    @classmethod
    def validate_offer_type(cls, v: str) -> str:
        if v not in _VALID_OFFER_TYPES:
            raise ValueError(f"offer_type 须为 {_VALID_OFFER_TYPES} 之一")
        return v

    @field_validator("margin_floor")
    @classmethod
    def validate_margin(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("margin_floor 须在 [0, 1] 之间")
        return v

    @field_validator("validity_days")
    @classmethod
    def validate_days(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("validity_days 须大于 0")
        return v


class EligibilityRequest(BaseModel):
    user_id: str
    offer_id: str


class MarginCheckRequest(BaseModel):
    offer_id: str
    order_data: dict


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post("")
async def create_offer(
    req: CreateOfferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建优惠策略（毛利底线硬约束校验）

    基于业务目标设计利益结构：
    - 每个优惠有明确 goal（拉新/复购/提频/提客单价）
    - margin_floor 是毛利底线，三条硬约束之一
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        type_defaults = _TYPE_DEFAULTS.get(req.offer_type, {})
        now = datetime.now(timezone.utc)

        new_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO offers
                    (id, tenant_id, name, offer_type, description, goal,
                     discount_rules, validity_days, target_segments,
                     applicable_stores, time_slots, margin_floor, max_per_user,
                     status, issued_count, redeemed_count, total_discount_fen,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :name, :offer_type, :description, :goal,
                     :discount_rules::jsonb, :validity_days, :target_segments::jsonb,
                     :stores::jsonb, :time_slots::jsonb, :margin_floor, :max_per_user,
                     'active', 0, 0, 0,
                     :now, :now)
            """),
            {
                "id": new_id,
                "tid": tid,
                "name": req.name,
                "offer_type": req.offer_type,
                "description": type_defaults.get("description", ""),
                "goal": type_defaults.get("goal", "general"),
                "discount_rules": json.dumps(req.discount_rules),
                "validity_days": req.validity_days,
                "target_segments": json.dumps(req.target_segments),
                "stores": json.dumps(req.stores),
                "time_slots": json.dumps(req.time_slots),
                "margin_floor": req.margin_floor,
                "max_per_user": req.max_per_user,
                "now": now,
            },
        )
        await db.commit()

        logger.info(
            "offer.created",
            offer_id=str(new_id),
            offer_type=req.offer_type,
            tenant_id=x_tenant_id,
        )
        return ok_response(
            {
                "offer_id": str(new_id),
                "name": req.name,
                "offer_type": req.offer_type,
                "goal": type_defaults.get("goal", "general"),
                "status": "active",
                "margin_floor": req.margin_floor,
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠功能尚未初始化，请联系管理员")
        logger.error("offer.create_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "创建优惠失败")


@router.get("")
async def list_offers(
    offer_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """优惠策略列表（支持类型/状态过滤，分页）"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        offset = (page - 1) * size

        where_parts = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tid, "limit": size, "offset": offset}

        if offer_type:
            if offer_type not in _VALID_OFFER_TYPES:
                return error_response("INVALID_TYPE", f"offer_type 须为 {_VALID_OFFER_TYPES} 之一")
            where_parts.append("offer_type = :offer_type")
            params["offer_type"] = offer_type
        if status:
            where_parts.append("status = :status")
            params["status"] = status

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM offers WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text(f"""
                SELECT id, name, offer_type, description, goal,
                       discount_rules, validity_days, target_segments,
                       applicable_stores, time_slots, margin_floor, max_per_user,
                       status, issued_count, redeemed_count, total_discount_fen,
                       created_at, updated_at
                FROM offers
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()
        items = [_row_to_offer(r) for r in rows]
        return ok_response({"items": items, "total": total, "page": page, "size": size})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
        logger.error("offer.list_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询优惠列表失败")


@router.get("/recommend/{segment_id}")
async def recommend_offer(
    segment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI推荐：为特定人群推荐优惠策略

    优先从 offers 表查询该租户已配置的、包含此人群的活跃优惠；
    若 DB 中无匹配数据，则返回内置参考模板（标注 source=template，
    表示仅供参考，不对应任何真实优惠）。
    支持人群：new_customer / first_no_repeat / dormant / high_frequency / high_value_banquet
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)

        # 从 DB 查询包含该 segment 的活跃优惠（target_segments JSONB 包含 segment_id）
        result = await db.execute(
            text("""
                SELECT id, name, offer_type, description, goal,
                       discount_rules, validity_days, margin_floor,
                       issued_count, redeemed_count, total_discount_fen
                FROM offers
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND status = 'active'
                  AND (
                    target_segments = '[]'::jsonb
                    OR target_segments @> :segment_json::jsonb
                    OR target_segments IS NULL
                  )
                ORDER BY redeemed_count DESC, created_at DESC
                LIMIT 5
            """),
            {"tid": tid, "segment_json": json.dumps([segment_id])},
        )
        rows = result.fetchall()

        if rows:
            # 从真实 DB 数据构建推荐
            def _j(v: Any) -> Any:
                if v is None:
                    return {}
                return v if isinstance(v, (dict, list)) else json.loads(v)

            recommendations = [
                {
                    "offer_id": str(r.id),
                    "offer_type": r.offer_type,
                    "name": r.name,
                    "description": r.description or "",
                    "goal": r.goal,
                    "discount_rules": _j(r.discount_rules),
                    "validity_days": r.validity_days,
                    "margin_floor": float(r.margin_floor),
                    "stats": {
                        "issued_count": r.issued_count,
                        "redeemed_count": r.redeemed_count,
                        "total_discount_fen": r.total_discount_fen,
                    },
                    "source": "db",
                }
                for r in rows
            ]
            return ok_response(
                {
                    "segment_id": segment_id,
                    "recommendations": recommendations,
                    "total": len(recommendations),
                    "source": "db",
                }
            )

        # DB 无数据：返回内置参考模板（标注为 template，不影响真实数据）
        template_recommendations = _SEGMENT_OFFER_MAP.get(segment_id)
        if not template_recommendations:
            template_recommendations = [
                {
                    "offer_type": "new_dish_trial",
                    "name": "新品尝鲜券-满80减15（参考模板）",
                    "discount_rules": {"type": "threshold", "threshold_fen": 8000, "reduce_fen": 1500},
                    "reason": "新品试吃提升菜品覆盖面",
                    "expected_roi": 2.5,
                },
            ]
        fallback = [dict(item, source="template") for item in template_recommendations]
        return ok_response(
            {
                "segment_id": segment_id,
                "recommendations": fallback,
                "total": len(fallback),
                "source": "template",
                "_note": "当前租户尚未配置针对此人群的优惠，以下为参考模板，请先通过 POST /api/v1/offers 创建优惠",
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            # 表未就绪时降级返回模板推荐
            template_recommendations = _SEGMENT_OFFER_MAP.get(
                segment_id,
                [
                    {
                        "offer_type": "new_dish_trial",
                        "name": "新品尝鲜券-满80减15（参考模板）",
                        "discount_rules": {"type": "threshold", "threshold_fen": 8000, "reduce_fen": 1500},
                        "reason": "新品试吃提升菜品覆盖面",
                        "expected_roi": 2.5,
                    },
                ],
            )
            fallback = [dict(item, source="template") for item in template_recommendations]
            return ok_response(
                {
                    "segment_id": segment_id,
                    "recommendations": fallback,
                    "total": len(fallback),
                    "source": "template",
                    "_note": "TABLE_NOT_READY",
                }
            )
        logger.error("offer.recommend_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询推荐优惠失败")


@router.get("/{offer_id}")
async def get_offer_detail(
    offer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """优惠策略详情"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        oid = uuid.UUID(offer_id)

        result = await db.execute(
            text("""
                SELECT id, name, offer_type, description, goal,
                       discount_rules, validity_days, target_segments,
                       applicable_stores, time_slots, margin_floor, max_per_user,
                       status, issued_count, redeemed_count, total_discount_fen,
                       created_at, updated_at
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return error_response("NOT_FOUND", f"优惠不存在: {offer_id}")
        return ok_response(_row_to_offer(row))

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠功能尚未初始化")
        logger.error("offer.get_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询优惠失败")


@router.post("/check-eligibility")
async def check_eligibility(
    req: EligibilityRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """检查用户是否可以使用优惠

    校验：优惠状态、单用户使用次数上限
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        oid = uuid.UUID(req.offer_id)
        uid = req.user_id  # 可能是外部 user_id 或 customer_id

        # 查询优惠基础信息
        offer_result = await db.execute(
            text("""
                SELECT id, name, offer_type, status, discount_rules, validity_days, max_per_user
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        offer = offer_result.fetchone()
        if not offer:
            return ok_response({"eligible": False, "reason": f"优惠不存在: {req.offer_id}"})

        if offer.status != "active":
            return ok_response({"eligible": False, "reason": f"优惠已{offer.status}"})

        # 查询用户已领取/核销次数
        try:
            redemption_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM offer_redemptions
                    WHERE tenant_id = :tid AND offer_id = :oid
                      AND external_user_id = :uid AND is_deleted = false
                """),
                {"tid": tid, "oid": oid, "uid": uid},
            )
            user_redemption_count = redemption_result.scalar() or 0
        except SQLAlchemyError:
            # offer_redemptions 表不存在时降级：视为未使用过
            user_redemption_count = 0

        if user_redemption_count >= offer.max_per_user:
            return ok_response({"eligible": False, "reason": "已达使用上限"})

        return ok_response(
            {
                "eligible": True,
                "offer_id": req.offer_id,
                "user_id": uid,
                "discount_rules": offer.discount_rules
                if isinstance(offer.discount_rules, dict)
                else json.loads(offer.discount_rules or "{}"),
                "validity_days": offer.validity_days,
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return ok_response({"eligible": False, "reason": "TABLE_NOT_READY"})
        logger.error("offer.eligibility_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "资格检查失败")


@router.get("/{offer_id}/analytics")
async def get_offer_analytics(
    offer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """优惠效果分析

    返回：发放数、核销数、核销率、总优惠金额、归因收入、利润贡献
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        oid = uuid.UUID(offer_id)

        # 查询优惠基础信息
        offer_result = await db.execute(
            text("""
                SELECT id, name, offer_type, issued_count, redeemed_count, total_discount_fen
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        offer = offer_result.fetchone()
        if not offer:
            return error_response("NOT_FOUND", f"优惠不存在: {offer_id}")

        # 查询核销明细（来自 offer_redemptions 表）
        total_revenue_fen = 0
        actual_redeemed = 0
        actual_discount_fen = 0
        try:
            redemption_result = await db.execute(
                text("""
                    SELECT COUNT(*) AS cnt,
                           COALESCE(SUM(order_total_fen), 0) AS total_revenue,
                           COALESCE(SUM(discount_fen), 0) AS total_discount
                    FROM offer_redemptions
                    WHERE tenant_id = :tid AND offer_id = :oid AND is_deleted = false
                """),
                {"tid": tid, "oid": oid},
            )
            r = redemption_result.fetchone()
            if r:
                actual_redeemed = int(r.cnt)
                total_revenue_fen = int(r.total_revenue)
                actual_discount_fen = int(r.total_discount)
        except SQLAlchemyError:
            # offer_redemptions 表尚未就绪时，用 offers 表的统计字段降级
            actual_redeemed = offer.redeemed_count
            actual_discount_fen = offer.total_discount_fen

        issued = offer.issued_count
        redeemed = actual_redeemed or offer.redeemed_count
        redemption_rate = redeemed / max(1, issued)
        revenue_per_redemption = total_revenue_fen // max(1, redeemed) if total_revenue_fen else 0
        profit_contribution_fen = total_revenue_fen - actual_discount_fen

        return ok_response(
            {
                "offer_id": offer_id,
                "offer_name": offer.name,
                "offer_type": offer.offer_type,
                "issued_count": issued,
                "redeemed_count": redeemed,
                "redemption_rate": round(redemption_rate, 4),
                "total_discount_fen": actual_discount_fen or offer.total_discount_fen,
                "total_discount_yuan": round((actual_discount_fen or offer.total_discount_fen) / 100, 2),
                "total_revenue_fen": total_revenue_fen,
                "total_revenue_yuan": round(total_revenue_fen / 100, 2),
                "revenue_per_redemption_fen": revenue_per_redemption,
                "profit_contribution_fen": profit_contribution_fen,
                "profit_contribution_yuan": round(profit_contribution_fen / 100, 2),
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠功能尚未初始化")
        logger.error("offer.analytics_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询分析失败")


@router.get("/{offer_id}/cost")
async def calculate_offer_cost(
    offer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """计算优惠预估成本与 ROI

    基于优惠的 discount_rules 预估：单次优惠金额、总成本、增量收入、ROI。
    预估参数：100次核销、平均客单价120元（可在后续版本从历史数据计算）。
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        oid = uuid.UUID(offer_id)

        result = await db.execute(
            text("""
                SELECT id, name, discount_rules, validity_days, margin_floor
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return error_response("NOT_FOUND", f"优惠不存在: {offer_id}")

        import json as _json

        rules = row.discount_rules if isinstance(row.discount_rules, dict) else _json.loads(row.discount_rules or "{}")
        rule_type = rules.get("type", "")

        # 预估参数：可在后续版本从历史订单数据动态计算
        estimated_redemption_count = 100
        avg_order_fen = 12000  # 平均客单价 120元

        if rule_type == "fixed_amount":
            per_discount_fen = int(rules.get("amount_fen", 0))
        elif rule_type == "percentage":
            pct = rules.get("pct", 0)
            per_discount_fen = int(avg_order_fen * pct / 100)
        elif rule_type == "threshold":
            per_discount_fen = int(rules.get("reduce_fen", 0))
        else:
            per_discount_fen = 0

        projected_cost_fen = per_discount_fen * estimated_redemption_count
        # 假设每次核销带来增量收入为客单价的1.5倍（含复购效应）
        projected_revenue_lift_fen = int(avg_order_fen * 1.5 * estimated_redemption_count)
        projected_roi = (
            round(projected_revenue_lift_fen / max(1, projected_cost_fen), 2) if projected_cost_fen > 0 else 0.0
        )

        logger.info("offer.cost_calculated", offer_id=offer_id, tenant_id=x_tenant_id)
        return ok_response(
            {
                "offer_id": offer_id,
                "estimated_redemption_count": estimated_redemption_count,
                "per_discount_fen": per_discount_fen,
                "per_discount_yuan": round(per_discount_fen / 100, 2),
                "projected_cost_fen": projected_cost_fen,
                "projected_cost_yuan": round(projected_cost_fen / 100, 2),
                "projected_revenue_lift_fen": projected_revenue_lift_fen,
                "projected_revenue_lift_yuan": round(projected_revenue_lift_fen / 100, 2),
                "projected_roi": projected_roi,
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠功能尚未初始化")
        logger.error("offer.cost_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "计算优惠成本失败")


class MarginCheckRequest(BaseModel):
    offer_id: str
    order_data: dict  # {"total_fen": 15000, "cost_fen": 6000, "discount_fen": 2000}


@router.post("/check-margin")
async def check_margin_compliance(
    req: MarginCheckRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """毛利合规检查 — 三条硬约束之一

    确保优惠后的订单毛利不低于 margin_floor 设定底线。
    从 DB 读取该优惠的 margin_floor，纯计算不写 DB。
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        oid = uuid.UUID(req.offer_id)

        result = await db.execute(
            text("""
                SELECT id, margin_floor
                FROM offers
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"oid": oid, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return ok_response({"compliant": False, "reason": f"优惠不存在: {req.offer_id}"})

        margin_floor = float(row.margin_floor)
        total_fen = int(req.order_data.get("total_fen", 0))
        cost_fen = int(req.order_data.get("cost_fen", 0))
        discount_fen = int(req.order_data.get("discount_fen", 0))

        revenue_after_discount = total_fen - discount_fen
        if revenue_after_discount <= 0:
            return ok_response(
                {
                    "compliant": False,
                    "reason": "优惠后收入为零或负数",
                    "margin_rate": 0.0,
                    "margin_floor": margin_floor,
                }
            )

        margin_rate = (revenue_after_discount - cost_fen) / revenue_after_discount
        compliant = margin_rate >= margin_floor

        logger.info(
            "offer.margin_checked",
            offer_id=req.offer_id,
            compliant=compliant,
            margin_rate=round(margin_rate, 4),
            tenant_id=x_tenant_id,
        )
        return ok_response(
            {
                "compliant": compliant,
                "margin_rate": round(margin_rate, 4),
                "margin_floor": margin_floor,
                "revenue_after_discount_fen": revenue_after_discount,
                "cost_fen": cost_fen,
                "profit_fen": revenue_after_discount - cost_fen,
                "reason": "" if compliant else f"毛利率 {margin_rate:.1%} 低于底线 {margin_floor:.1%}",
            }
        )

    except (KeyError, TypeError) as exc:
        return error_response("INVALID_PARAM", f"order_data 格式错误: {exc}")
    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("offer.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠功能尚未初始化")
        logger.error("offer.margin_check_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "毛利检查失败")
