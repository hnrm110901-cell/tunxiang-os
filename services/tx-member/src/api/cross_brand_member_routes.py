"""跨品牌会员智能 API — 统一画像 + 会员合并 + 积分互通

端点列表：
  GET    /api/v1/member/cross-brand/{golden_id}         跨品牌统一画像
  POST   /api/v1/member/cross-brand/merge               跨品牌会员合并（手机号匹配）
  GET    /api/v1/member/cross-brand/stats                跨品牌会员统计
  POST   /api/v1/member/cross-brand/points-transfer      跨品牌积分互通

对标：Olo Guest Intelligence（统一客户智能+交叉推荐） + 海底捞 2 亿会员中台
"""

import hashlib
import os
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/cross-brand", tags=["cross-brand-member"])

_PHONE_HASH_SALT: str = os.environ.get("PHONE_HASH_SALT", "tx-member-phone-salt-v1")


# ── 工具函数 ─────────────────────────────────────────────────────────────────


def _hash_phone(phone: str) -> str:
    """sha256(phone + salt)，隐私保护"""
    raw = f"{phone}{_PHONE_HASH_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _set_tenant(db, tenant_id: str) -> None:
    """设置 RLS app.tenant_id"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────


class CrossBrandMergeReq(BaseModel):
    phone: str = Field(description="手机号（用于匹配跨品牌账户）")
    source_brand_id: str = Field(description="源品牌ID")
    target_brand_id: str = Field(description="目标品牌ID")
    operator_id: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if len(v) < 7 or len(v) > 20:
            raise ValueError("手机号长度不合法")
        return v


class PointsTransferReq(BaseModel):
    golden_id: str = Field(description="Golden ID（跨品牌唯一标识）")
    from_brand_id: str = Field(description="转出品牌ID")
    to_brand_id: str = Field(description="转入品牌ID")
    points: int = Field(gt=0, description="转移积分数（正整数）")
    exchange_rate: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="兑换比例（from_brand 积分 × rate = to_brand 积分）",
    )
    reason: str = Field(default="manual_transfer", description="转移原因")

    @field_validator("golden_id", "from_brand_id", "to_brand_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as e:
            raise ValueError(f"UUID 格式错误: {v}") from e
        return v


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/{golden_id}")
async def get_cross_brand_profile(
    golden_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """跨品牌统一画像：聚合所有品牌的消费记录+积分+储值+偏好

    返回该 Golden ID 在所有品牌下的会员信息聚合视图。
    """
    try:
        uuid.UUID(x_tenant_id)
        uuid.UUID(golden_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 查询该 golden_id 关联的所有品牌会员链接
            links_result = await db.execute(
                text("""
                    SELECT cbl.brand_id, cbl.brand_member_id,
                           cbl.created_at AS link_created_at
                    FROM cross_brand_member_links cbl
                    WHERE cbl.golden_id = :golden_id
                      AND cbl.tenant_id = :tenant_id
                      AND cbl.is_deleted = FALSE
                    ORDER BY cbl.created_at
                """),
                {"golden_id": golden_id, "tenant_id": x_tenant_id},
            )
            links = links_result.fetchall()

            if not links:
                raise HTTPException(
                    status_code=404,
                    detail=f"Golden ID {golden_id} 未找到跨品牌关联",
                )

            brand_profiles: list[dict] = []
            total_points = 0
            total_stored_value_fen = 0
            total_order_count = 0
            total_spend_fen = 0
            all_preferences: list[str] = []

            for link in links:
                brand_id = str(link.brand_id)
                brand_member_id = str(link.brand_member_id)

                # 积分汇总
                points_result = await db.execute(
                    text("""
                        SELECT COALESCE(SUM(balance), 0) AS total_points
                        FROM member_points
                        WHERE tenant_id = :tenant_id
                          AND customer_id = :member_id
                    """),
                    {"tenant_id": x_tenant_id, "member_id": brand_member_id},
                )
                brand_points = points_result.scalar() or 0
                total_points += brand_points

                # 储值余额
                sv_result = await db.execute(
                    text("""
                        SELECT COALESCE(SUM(balance_fen), 0) AS sv_balance
                        FROM stored_value_cards
                        WHERE tenant_id = :tenant_id
                          AND customer_id = :member_id
                          AND status = 'active'
                    """),
                    {"tenant_id": x_tenant_id, "member_id": brand_member_id},
                )
                brand_sv = sv_result.scalar() or 0
                total_stored_value_fen += brand_sv

                # 消费统计
                order_result = await db.execute(
                    text("""
                        SELECT COUNT(*) AS order_count,
                               COALESCE(SUM(total_fen), 0) AS spend_fen
                        FROM orders
                        WHERE tenant_id = :tenant_id
                          AND customer_id = :member_id
                          AND status = 'paid'
                    """),
                    {"tenant_id": x_tenant_id, "member_id": brand_member_id},
                )
                order_row = order_result.fetchone()
                brand_order_count = order_row.order_count if order_row else 0
                brand_spend = order_row.spend_fen if order_row else 0
                total_order_count += brand_order_count
                total_spend_fen += brand_spend

                # 偏好标签
                pref_result = await db.execute(
                    text("""
                        SELECT DISTINCT tag
                        FROM member_preference_tags
                        WHERE tenant_id = :tenant_id
                          AND customer_id = :member_id
                        LIMIT 10
                    """),
                    {"tenant_id": x_tenant_id, "member_id": brand_member_id},
                )
                brand_prefs = [r.tag for r in pref_result.fetchall()]
                all_preferences.extend(brand_prefs)

                brand_profiles.append(
                    {
                        "brand_id": brand_id,
                        "brand_member_id": brand_member_id,
                        "points": brand_points,
                        "stored_value_fen": brand_sv,
                        "order_count": brand_order_count,
                        "total_spend_fen": brand_spend,
                        "preferences": brand_prefs,
                        "linked_at": link.link_created_at.isoformat() if link.link_created_at else None,
                    }
                )

            # 去重偏好标签
            unique_preferences = list(dict.fromkeys(all_preferences))

            return {
                "ok": True,
                "data": {
                    "golden_id": golden_id,
                    "brand_count": len(brand_profiles),
                    "brands": brand_profiles,
                    "aggregated": {
                        "total_points": total_points,
                        "total_stored_value_fen": total_stored_value_fen,
                        "total_order_count": total_order_count,
                        "total_spend_fen": total_spend_fen,
                        "preferences": unique_preferences[:20],
                    },
                },
                "error": {},
            }

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logger.error("cross_brand_profile_error", golden_id=golden_id, error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="跨品牌画像查询失败") from e


@router.post("/merge")
async def merge_cross_brand_member(
    req: CrossBrandMergeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """跨品牌会员合并：通过手机号匹配同一自然人在不同品牌下的会员账户

    流程：
    1. 用 phone_hash 在两个品牌中分别查找会员
    2. 若两个品牌都有会员，创建 cross_brand_member_links 关联到同一 golden_id
    3. 若 golden_id 已存在则复用，否则新建
    """
    try:
        uuid.UUID(x_tenant_id)
        uuid.UUID(req.source_brand_id)
        uuid.UUID(req.target_brand_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    if req.source_brand_id == req.target_brand_id:
        raise HTTPException(status_code=400, detail="源品牌与目标品牌不能相同")

    phone_hash = _hash_phone(req.phone)

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 查找源品牌会员（通过 phone_hash）
            source_member = await db.execute(
                text("""
                    SELECT customer_id
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                      AND phone_hash = :phone_hash
                      AND binding_status = 'active'
                    LIMIT 1
                """),
                {"tenant_id": x_tenant_id, "phone_hash": phone_hash},
            )
            source_row = source_member.fetchone()
            if not source_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"源品牌 {req.source_brand_id} 中未找到该手机号会员",
                )

            # 查找目标品牌会员
            target_member = await db.execute(
                text("""
                    SELECT customer_id
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                      AND phone_hash = :phone_hash
                      AND binding_status = 'active'
                    LIMIT 1
                """),
                {"tenant_id": x_tenant_id, "phone_hash": phone_hash},
            )
            target_row = target_member.fetchone()
            if not target_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"目标品牌 {req.target_brand_id} 中未找到该手机号会员",
                )

            source_customer_id = str(source_row.customer_id)
            target_customer_id = str(target_row.customer_id)

            # 检查是否已有 golden_id
            existing_link = await db.execute(
                text("""
                    SELECT golden_id
                    FROM cross_brand_member_links
                    WHERE tenant_id = :tenant_id
                      AND brand_member_id = :member_id
                      AND is_deleted = FALSE
                    LIMIT 1
                """),
                {"tenant_id": x_tenant_id, "member_id": source_customer_id},
            )
            existing_row = existing_link.fetchone()
            golden_id = str(existing_row.golden_id) if existing_row else str(uuid.uuid4())

            # 插入/更新源品牌链接
            await db.execute(
                text("""
                    INSERT INTO cross_brand_member_links
                        (id, tenant_id, golden_id, brand_id, brand_member_id, phone_hash)
                    VALUES
                        (:id, :tenant_id, :golden_id, :brand_id, :member_id, :phone_hash)
                    ON CONFLICT (tenant_id, brand_id, brand_member_id)
                        WHERE is_deleted = FALSE
                    DO UPDATE SET golden_id = :golden_id, updated_at = NOW()
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": x_tenant_id,
                    "golden_id": golden_id,
                    "brand_id": req.source_brand_id,
                    "member_id": source_customer_id,
                    "phone_hash": phone_hash,
                },
            )

            # 插入/更新目标品牌链接
            await db.execute(
                text("""
                    INSERT INTO cross_brand_member_links
                        (id, tenant_id, golden_id, brand_id, brand_member_id, phone_hash)
                    VALUES
                        (:id, :tenant_id, :golden_id, :brand_id, :member_id, :phone_hash)
                    ON CONFLICT (tenant_id, brand_id, brand_member_id)
                        WHERE is_deleted = FALSE
                    DO UPDATE SET golden_id = :golden_id, updated_at = NOW()
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": x_tenant_id,
                    "golden_id": golden_id,
                    "brand_id": req.target_brand_id,
                    "member_id": target_customer_id,
                    "phone_hash": phone_hash,
                },
            )

            await db.commit()

            logger.info(
                "cross_brand_merged",
                tenant_id=x_tenant_id,
                golden_id=golden_id,
                source_brand=req.source_brand_id,
                target_brand=req.target_brand_id,
            )
            return {
                "ok": True,
                "data": {
                    "golden_id": golden_id,
                    "source_brand_id": req.source_brand_id,
                    "source_member_id": source_customer_id,
                    "target_brand_id": req.target_brand_id,
                    "target_member_id": target_customer_id,
                },
                "error": {},
            }

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("cross_brand_merge_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="跨品牌合并失败") from e


@router.get("/stats")
async def get_cross_brand_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """跨品牌会员统计：总会员/共享会员/品牌独占/跨品牌转化率"""
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 总会员数（distinct golden_id）
            total_result = await db.execute(
                text("""
                    SELECT COUNT(DISTINCT golden_id) AS total_members
                    FROM cross_brand_member_links
                    WHERE tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {"tenant_id": x_tenant_id},
            )
            total_members = total_result.scalar() or 0

            # 共享会员（消费 2+ 品牌的 golden_id 数）
            shared_result = await db.execute(
                text("""
                    SELECT COUNT(*) AS shared_members
                    FROM (
                        SELECT golden_id
                        FROM cross_brand_member_links
                        WHERE tenant_id = :tenant_id
                          AND is_deleted = FALSE
                        GROUP BY golden_id
                        HAVING COUNT(DISTINCT brand_id) >= 2
                    ) sub
                """),
                {"tenant_id": x_tenant_id},
            )
            shared_members = shared_result.scalar() or 0

            # 品牌独占会员（仅在 1 个品牌的 golden_id 数）
            exclusive_members = total_members - shared_members

            # 跨品牌转化率
            cross_brand_rate = round(shared_members / total_members * 100, 2) if total_members > 0 else 0.0

            # 各品牌会员数
            brand_stats_result = await db.execute(
                text("""
                    SELECT brand_id,
                           COUNT(DISTINCT golden_id) AS member_count,
                           COUNT(DISTINCT brand_member_id) AS account_count
                    FROM cross_brand_member_links
                    WHERE tenant_id = :tenant_id
                      AND is_deleted = FALSE
                    GROUP BY brand_id
                    ORDER BY member_count DESC
                """),
                {"tenant_id": x_tenant_id},
            )
            brand_stats = [
                {
                    "brand_id": str(r.brand_id),
                    "member_count": r.member_count,
                    "account_count": r.account_count,
                }
                for r in brand_stats_result.fetchall()
            ]

            return {
                "ok": True,
                "data": {
                    "total_members": total_members,
                    "shared_members": shared_members,
                    "exclusive_members": exclusive_members,
                    "cross_brand_rate_pct": cross_brand_rate,
                    "brand_stats": brand_stats,
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            logger.error("cross_brand_stats_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="跨品牌统计查询失败") from e


@router.post("/points-transfer")
async def transfer_points_cross_brand(
    req: PointsTransferReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """跨品牌积分互通：从一个品牌转移积分到另一个品牌

    流程：
    1. 验证 golden_id 在两个品牌都有关联
    2. 检查源品牌积分余额是否充足
    3. 扣减源品牌积分
    4. 按兑换比例增加目标品牌积分
    5. 写入转移日志
    """
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {e}") from e

    if req.from_brand_id == req.to_brand_id:
        raise HTTPException(status_code=400, detail="转出和转入品牌不能相同")

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 查找两个品牌的会员链接
            from_link = await db.execute(
                text("""
                    SELECT brand_member_id
                    FROM cross_brand_member_links
                    WHERE tenant_id = :tenant_id
                      AND golden_id = :golden_id
                      AND brand_id = :brand_id
                      AND is_deleted = FALSE
                """),
                {
                    "tenant_id": x_tenant_id,
                    "golden_id": req.golden_id,
                    "brand_id": req.from_brand_id,
                },
            )
            from_row = from_link.fetchone()
            if not from_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Golden ID {req.golden_id} 在转出品牌 {req.from_brand_id} 中无关联",
                )

            to_link = await db.execute(
                text("""
                    SELECT brand_member_id
                    FROM cross_brand_member_links
                    WHERE tenant_id = :tenant_id
                      AND golden_id = :golden_id
                      AND brand_id = :brand_id
                      AND is_deleted = FALSE
                """),
                {
                    "tenant_id": x_tenant_id,
                    "golden_id": req.golden_id,
                    "brand_id": req.to_brand_id,
                },
            )
            to_row = to_link.fetchone()
            if not to_row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Golden ID {req.golden_id} 在转入品牌 {req.to_brand_id} 中无关联",
                )

            from_member_id = str(from_row.brand_member_id)
            to_member_id = str(to_row.brand_member_id)

            # 检查源品牌积分余额
            balance_result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(balance), 0) AS available_points
                    FROM member_points
                    WHERE tenant_id = :tenant_id
                      AND customer_id = :member_id
                """),
                {"tenant_id": x_tenant_id, "member_id": from_member_id},
            )
            available = balance_result.scalar() or 0
            if available < req.points:
                raise HTTPException(
                    status_code=400,
                    detail=f"源品牌积分不足: 可用 {available}，需转 {req.points}",
                )

            # 计算转入积分
            transferred_points = int(req.points * req.exchange_rate)

            # 扣减源品牌积分
            await db.execute(
                text("""
                    INSERT INTO member_points
                        (id, tenant_id, customer_id, balance, change_amount,
                         change_type, change_reason, created_at)
                    VALUES
                        (:id, :tenant_id, :member_id, -:points, -:points,
                         'cross_brand_transfer_out', :reason, NOW())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": x_tenant_id,
                    "member_id": from_member_id,
                    "points": req.points,
                    "reason": f"跨品牌转出至 {req.to_brand_id}",
                },
            )

            # 增加目标品牌积分
            await db.execute(
                text("""
                    INSERT INTO member_points
                        (id, tenant_id, customer_id, balance, change_amount,
                         change_type, change_reason, created_at)
                    VALUES
                        (:id, :tenant_id, :member_id, :points, :points,
                         'cross_brand_transfer_in', :reason, NOW())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": x_tenant_id,
                    "member_id": to_member_id,
                    "points": transferred_points,
                    "reason": f"跨品牌转入来自 {req.from_brand_id}",
                },
            )

            await db.commit()

            logger.info(
                "cross_brand_points_transferred",
                tenant_id=x_tenant_id,
                golden_id=req.golden_id,
                from_brand=req.from_brand_id,
                to_brand=req.to_brand_id,
                points_out=req.points,
                points_in=transferred_points,
                exchange_rate=req.exchange_rate,
            )
            return {
                "ok": True,
                "data": {
                    "golden_id": req.golden_id,
                    "from_brand_id": req.from_brand_id,
                    "to_brand_id": req.to_brand_id,
                    "points_deducted": req.points,
                    "points_credited": transferred_points,
                    "exchange_rate": req.exchange_rate,
                },
                "error": {},
            }

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("cross_brand_points_transfer_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="跨品牌积分转移失败") from e
