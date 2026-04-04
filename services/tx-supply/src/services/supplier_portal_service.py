"""供应商门户服务 — 纯 ORM 实现

涵盖：
  - 供应商账户管理（注册/更新/查询/列表/详情）
  - 询价管理（发起RFQ / 提交报价 / 比价 / 接受）
  - 交付记录与评分更新
  - 供应链风险评估

所有方法无状态，db session 由调用方注入。
金额单位：分（整数）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from ..models.supplier_portal import (
    SupplierAccount,
    SupplierQuotation,
    SupplierReconciliation,
)

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_rfq_id() -> str:
    """生成询价单号，格式: RFQ-YYYYMMDD-6位随机大写"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"RFQ-{today}-{suffix}"


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """激活 RLS 租户隔离"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _supplier_to_dict(s: SupplierAccount) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "category": s.category,
        "contact": s.contact,
        "certifications": s.certifications,
        "payment_terms": s.payment_terms,
        "status": s.status,
        "overall_score": s.overall_score,
        "order_count": s.order_count,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _quotation_to_dict(q: SupplierQuotation) -> dict:
    return {
        "id": str(q.id),
        "supplier_id": str(q.supplier_id),
        "rfq_id": q.rfq_id,
        "item_name": q.item_name,
        "quantity": float(q.quantity),
        "delivery_date": q.delivery_date.isoformat() if q.delivery_date else None,
        "unit_price_fen": q.unit_price_fen,
        "total_price_fen": q.total_price_fen,
        "delivery_days": q.delivery_days,
        "notes": q.notes,
        "status": q.status,
        "composite_score": q.composite_score,
        "score_detail": q.score_detail,
        "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 供应商管理
# ──────────────────────────────────────────────────────────────────────────────


async def register_supplier(
    name: str,
    category: str,
    contact: dict,
    certifications: list,
    payment_terms: str = "net30",
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """注册新供应商，返回创建后的供应商信息"""
    await _set_tenant(db, tenant_id)

    supplier = SupplierAccount(
        tenant_id=uuid.UUID(tenant_id),
        name=name,
        category=category,
        contact=contact,
        certifications=certifications,
        payment_terms=payment_terms,
        status="active",
        overall_score=0.0,
        order_count=0,
    )
    db.add(supplier)
    await db.flush()
    await db.refresh(supplier)

    logger.info(
        "supplier_registered",
        supplier_id=str(supplier.id),
        name=name,
        category=category,
        tenant_id=tenant_id,
    )
    return _supplier_to_dict(supplier)


async def update_supplier(
    supplier_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
    status: Optional[str] = None,
    overall_score: Optional[float] = None,
) -> dict:
    """更新供应商状态或评分"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.id == uuid.UUID(supplier_id),
            SupplierAccount.is_deleted.is_(False),
        )
    )
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise ValueError(f"供应商不存在: {supplier_id}")

    if status is not None:
        supplier.status = status
    if overall_score is not None:
        supplier.overall_score = overall_score
    supplier.updated_at = _now()

    await db.flush()
    await db.refresh(supplier)

    logger.info(
        "supplier_updated",
        supplier_id=supplier_id,
        status=status,
        overall_score=overall_score,
        tenant_id=tenant_id,
    )
    return _supplier_to_dict(supplier)


async def get_supplier(supplier_id: str, *, tenant_id: str, db: AsyncSession) -> dict:
    """获取单个供应商基本信息"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.id == uuid.UUID(supplier_id),
            SupplierAccount.is_deleted.is_(False),
        )
    )
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise ValueError(f"供应商不存在: {supplier_id}")

    return _supplier_to_dict(supplier)


async def list_suppliers(
    *,
    tenant_id: str,
    db: AsyncSession,
    category: Optional[str] = None,
    rating_min: Optional[float] = None,
) -> list[dict]:
    """列出供应商，可按品类和最低评分过滤"""
    await _set_tenant(db, tenant_id)

    stmt = select(SupplierAccount).where(
        SupplierAccount.is_deleted.is_(False),
    )
    if category:
        stmt = stmt.where(SupplierAccount.category == category)
    if rating_min is not None:
        stmt = stmt.where(SupplierAccount.overall_score >= rating_min)
    stmt = stmt.order_by(SupplierAccount.overall_score.desc())

    result = await db.execute(stmt)
    suppliers = result.scalars().all()
    return [_supplier_to_dict(s) for s in suppliers]


async def get_supplier_profile(
    supplier_id: str, *, tenant_id: str, db: AsyncSession
) -> dict:
    """获取供应商完整档案（含交付统计、最近报价）"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.id == uuid.UUID(supplier_id),
            SupplierAccount.is_deleted.is_(False),
        )
    )
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise ValueError(f"供应商不存在: {supplier_id}")

    # 交付统计（delivery 类型的对账记录）
    recon_result = await db.execute(
        select(SupplierReconciliation).where(
            SupplierReconciliation.supplier_id == uuid.UUID(supplier_id),
            SupplierReconciliation.record_type == "delivery",
            SupplierReconciliation.is_deleted.is_(False),
        )
    )
    deliveries = recon_result.scalars().all()

    total_deliveries = len(deliveries)
    on_time_count = sum(1 for d in deliveries if d.on_time is True)
    quality_pass_count = sum(1 for d in deliveries if d.quality_result == "pass")

    on_time_rate = (on_time_count / total_deliveries) if total_deliveries > 0 else 0.0
    quality_pass_rate = (quality_pass_count / total_deliveries) if total_deliveries > 0 else 0.0

    # 最近5条报价记录
    quotes_result = await db.execute(
        select(SupplierQuotation)
        .where(
            SupplierQuotation.supplier_id == uuid.UUID(supplier_id),
            SupplierQuotation.is_deleted.is_(False),
        )
        .order_by(SupplierQuotation.created_at.desc())
        .limit(5)
    )
    recent_quotes = quotes_result.scalars().all()

    profile = _supplier_to_dict(supplier)
    profile["delivery_stats"] = {
        "total_deliveries": total_deliveries,
        "on_time_count": on_time_count,
        "on_time_rate": round(on_time_rate, 4),
        "quality_pass_count": quality_pass_count,
        "quality_pass_rate": round(quality_pass_rate, 4),
    }
    profile["recent_quotes"] = [_quotation_to_dict(q) for q in recent_quotes]
    return profile


# ──────────────────────────────────────────────────────────────────────────────
# 询价管理
# ──────────────────────────────────────────────────────────────────────────────


async def request_quotes(
    item_name: str,
    quantity: float,
    delivery_date: Optional[date],
    supplier_ids: Optional[list[str]] = None,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """发起询价（RFQ），向指定或全部活跃供应商创建 open 状态报价单"""
    await _set_tenant(db, tenant_id)

    rfq_id = _new_rfq_id()

    # 确定目标供应商
    if supplier_ids:
        stmt = select(SupplierAccount).where(
            SupplierAccount.id.in_([uuid.UUID(sid) for sid in supplier_ids]),
            SupplierAccount.status == "active",
            SupplierAccount.is_deleted.is_(False),
        )
    else:
        stmt = select(SupplierAccount).where(
            SupplierAccount.status == "active",
            SupplierAccount.is_deleted.is_(False),
        )

    result = await db.execute(stmt)
    suppliers = result.scalars().all()

    if not suppliers:
        raise ValueError("没有找到符合条件的活跃供应商")

    # 为每个供应商创建一条询价记录
    created_count = 0
    for supplier in suppliers:
        quotation = SupplierQuotation(
            tenant_id=uuid.UUID(tenant_id),
            supplier_id=supplier.id,
            rfq_id=rfq_id,
            item_name=item_name,
            quantity=quantity,
            delivery_date=delivery_date,
            unit_price_fen=0,
            total_price_fen=0,
            delivery_days=0,
            status="open",
            composite_score=0.0,
        )
        db.add(quotation)
        created_count += 1

    await db.flush()

    logger.info(
        "rfq_created",
        rfq_id=rfq_id,
        item_name=item_name,
        quantity=quantity,
        supplier_count=created_count,
        tenant_id=tenant_id,
    )
    return {
        "rfq_id": rfq_id,
        "item_name": item_name,
        "quantity": quantity,
        "delivery_date": delivery_date.isoformat() if delivery_date else None,
        "supplier_count": created_count,
        "status": "open",
    }


async def submit_quote(
    rfq_id: str,
    supplier_id: str,
    unit_price_fen: int,
    delivery_days: int,
    notes: str = "",
    *,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """供应商提交报价"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(SupplierQuotation).where(
            SupplierQuotation.rfq_id == rfq_id,
            SupplierQuotation.supplier_id == uuid.UUID(supplier_id),
            SupplierQuotation.status == "open",
            SupplierQuotation.is_deleted.is_(False),
        )
    )
    quotation = result.scalar_one_or_none()
    if quotation is None:
        raise ValueError(f"询价单不存在或已关闭: rfq_id={rfq_id}, supplier_id={supplier_id}")

    total_price_fen = int(float(quotation.quantity) * unit_price_fen)

    quotation.unit_price_fen = unit_price_fen
    quotation.total_price_fen = total_price_fen
    quotation.delivery_days = delivery_days
    quotation.notes = notes
    quotation.status = "quoted"
    quotation.submitted_at = _now()
    quotation.updated_at = _now()

    await db.flush()

    logger.info(
        "quote_submitted",
        rfq_id=rfq_id,
        supplier_id=supplier_id,
        unit_price_fen=unit_price_fen,
        total_price_fen=total_price_fen,
        delivery_days=delivery_days,
        tenant_id=tenant_id,
    )


async def compare_quotes(rfq_id: str, *, tenant_id: str, db: AsyncSession) -> dict:
    """比价分析：对所有已报价供应商计算综合评分

    综合评分公式（满分100）：
      - 价格分（50分）：最低价得满分，其余按比例递减
      - 交付天数分（30分）：最短交期得满分
      - 可靠度分（20分）：基于供应商 overall_score
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(SupplierQuotation).where(
            SupplierQuotation.rfq_id == rfq_id,
            SupplierQuotation.status == "quoted",
            SupplierQuotation.is_deleted.is_(False),
        )
    )
    quotes = result.scalars().all()

    if not quotes:
        raise ValueError(f"询价单暂无报价: {rfq_id}")

    # 获取关联供应商评分
    supplier_ids = [q.supplier_id for q in quotes]
    sup_result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.id.in_(supplier_ids),
            SupplierAccount.is_deleted.is_(False),
        )
    )
    supplier_map: dict[uuid.UUID, SupplierAccount] = {
        s.id: s for s in sup_result.scalars().all()
    }

    # 计算评分基准值
    min_price = min(q.unit_price_fen for q in quotes)
    min_delivery = min((q.delivery_days for q in quotes if q.delivery_days > 0), default=1)

    scored: list[dict] = []
    for q in quotes:
        # 价格分（50分）：最低价满分
        price_score = 50.0 * (min_price / q.unit_price_fen) if q.unit_price_fen > 0 else 0.0

        # 交付分（30分）：最短交期满分
        if q.delivery_days > 0:
            delivery_score = 30.0 * (min_delivery / q.delivery_days)
        else:
            delivery_score = 0.0

        # 可靠度分（20分）：基于 overall_score（0~100 映射到 0~20）
        supplier = supplier_map.get(q.supplier_id)
        reliability_raw = supplier.overall_score if supplier else 0.0
        reliability_score = 20.0 * (reliability_raw / 100.0) if reliability_raw > 0 else 0.0

        composite = round(price_score + delivery_score + reliability_score, 2)
        score_detail = {
            "price_score": round(price_score, 2),
            "delivery_score": round(delivery_score, 2),
            "reliability_score": round(reliability_score, 2),
        }

        # 持久化评分
        q.composite_score = composite
        q.score_detail = score_detail
        q.updated_at = _now()

        scored.append({
            **_quotation_to_dict(q),
            "supplier_name": supplier.name if supplier else None,
        })

    await db.flush()

    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    logger.info(
        "quotes_compared",
        rfq_id=rfq_id,
        quote_count=len(scored),
        tenant_id=tenant_id,
    )
    return {
        "rfq_id": rfq_id,
        "quotes": scored,
        "recommended_supplier_id": scored[0]["supplier_id"] if scored else None,
    }


async def accept_quote(
    rfq_id: str,
    supplier_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """接受指定供应商的报价，其余报价标记为 rejected"""
    await _set_tenant(db, tenant_id)

    # 找到被接受的报价
    result = await db.execute(
        select(SupplierQuotation).where(
            SupplierQuotation.rfq_id == rfq_id,
            SupplierQuotation.supplier_id == uuid.UUID(supplier_id),
            SupplierQuotation.is_deleted.is_(False),
        )
    )
    accepted_quote = result.scalar_one_or_none()
    if accepted_quote is None:
        raise ValueError(f"报价不存在: rfq_id={rfq_id}, supplier_id={supplier_id}")
    if accepted_quote.status not in ("quoted", "open"):
        raise ValueError(f"该报价当前状态 '{accepted_quote.status}' 不可接受")

    accepted_quote.status = "accepted"
    accepted_quote.updated_at = _now()

    # 其余同 rfq_id 的报价标记为 rejected
    all_result = await db.execute(
        select(SupplierQuotation).where(
            SupplierQuotation.rfq_id == rfq_id,
            SupplierQuotation.supplier_id != uuid.UUID(supplier_id),
            SupplierQuotation.status.in_(["open", "quoted"]),
            SupplierQuotation.is_deleted.is_(False),
        )
    )
    for q in all_result.scalars().all():
        q.status = "rejected"
        q.updated_at = _now()

    # 更新供应商订单计数
    sup_result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.id == uuid.UUID(supplier_id),
            SupplierAccount.is_deleted.is_(False),
        )
    )
    supplier = sup_result.scalar_one_or_none()
    if supplier:
        supplier.order_count = (supplier.order_count or 0) + 1
        supplier.updated_at = _now()

    await db.flush()

    logger.info(
        "quote_accepted",
        rfq_id=rfq_id,
        supplier_id=supplier_id,
        unit_price_fen=accepted_quote.unit_price_fen,
        tenant_id=tenant_id,
    )
    return {
        "rfq_id": rfq_id,
        "accepted_supplier_id": supplier_id,
        "unit_price_fen": accepted_quote.unit_price_fen,
        "total_price_fen": accepted_quote.total_price_fen,
        "delivery_days": accepted_quote.delivery_days,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 交付记录与风险评估
# ──────────────────────────────────────────────────────────────────────────────


async def record_delivery(
    supplier_id: str,
    on_time: bool,
    quality_result: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """记录一次交付结果，并重新计算供应商综合评分

    评分算法（0~100）：
      - 基础分（20分）：固定
      - 准时率（40分）：近20次交付的准时比例
      - 质检通过率（40分）：近20次的通过比例
    """
    await _set_tenant(db, tenant_id)

    # 校验供应商存在
    sup_result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.id == uuid.UUID(supplier_id),
            SupplierAccount.is_deleted.is_(False),
        )
    )
    supplier = sup_result.scalar_one_or_none()
    if supplier is None:
        raise ValueError(f"供应商不存在: {supplier_id}")

    # 写入交付记录
    record = SupplierReconciliation(
        tenant_id=uuid.UUID(tenant_id),
        supplier_id=uuid.UUID(supplier_id),
        record_type="delivery",
        on_time=on_time,
        quality_result=quality_result,
        record_date=_now().date(),
    )
    db.add(record)
    await db.flush()

    # 重新计算综合评分（基于近20次交付）
    recon_result = await db.execute(
        select(SupplierReconciliation)
        .where(
            SupplierReconciliation.supplier_id == uuid.UUID(supplier_id),
            SupplierReconciliation.record_type == "delivery",
            SupplierReconciliation.is_deleted.is_(False),
        )
        .order_by(SupplierReconciliation.created_at.desc())
        .limit(20)
    )
    recent = recon_result.scalars().all()
    total = len(recent)

    if total > 0:
        on_time_rate = sum(1 for r in recent if r.on_time is True) / total
        quality_rate = sum(1 for r in recent if r.quality_result == "pass") / total
        new_score = round(20.0 + on_time_rate * 40.0 + quality_rate * 40.0, 2)
    else:
        new_score = 0.0

    supplier.overall_score = new_score
    supplier.updated_at = _now()
    await db.flush()

    logger.info(
        "delivery_recorded",
        supplier_id=supplier_id,
        on_time=on_time,
        quality_result=quality_result,
        new_score=new_score,
        tenant_id=tenant_id,
    )
    return {
        "supplier_id": supplier_id,
        "on_time": on_time,
        "quality_result": quality_result,
        "new_overall_score": new_score,
        "sample_size": total,
    }


async def assess_risk(*, tenant_id: str, db: AsyncSession) -> dict:
    """评估供应链整体风险

    风险维度：
      - 高风险供应商（评分 < 40 或 status=suspended/blacklisted）
      - 单一供应商品类（仅1个活跃供应商的品类）
      - 近期交付异常（近30条记录中 on_time=False 或 quality=fail 的比例）
    """
    await _set_tenant(db, tenant_id)

    # 1. 高风险供应商
    risky_result = await db.execute(
        select(SupplierAccount).where(
            SupplierAccount.is_deleted.is_(False),
            (
                (SupplierAccount.overall_score < 40.0)
                | SupplierAccount.status.in_(["suspended", "blacklisted"])
            ),
        )
    )
    risky_suppliers = risky_result.scalars().all()

    # 2. 品类覆盖度（找出只有1家活跃供应商的品类）
    all_active_result = await db.execute(
        select(SupplierAccount.category, func.count(SupplierAccount.id).label("cnt"))
        .where(
            SupplierAccount.status == "active",
            SupplierAccount.is_deleted.is_(False),
        )
        .group_by(SupplierAccount.category)
    )
    category_counts = {row.category: row.cnt for row in all_active_result}
    single_source_categories = [cat for cat, cnt in category_counts.items() if cnt == 1]

    # 3. 近期交付异常率
    recent_recon_result = await db.execute(
        select(SupplierReconciliation)
        .where(
            SupplierReconciliation.record_type == "delivery",
            SupplierReconciliation.is_deleted.is_(False),
        )
        .order_by(SupplierReconciliation.created_at.desc())
        .limit(30)
    )
    recent_deliveries = recent_recon_result.scalars().all()
    total_recent = len(recent_deliveries)

    if total_recent > 0:
        anomaly_count = sum(
            1 for r in recent_deliveries
            if r.on_time is False or r.quality_result == "fail"
        )
        anomaly_rate = round(anomaly_count / total_recent, 4)
    else:
        anomaly_count = 0
        anomaly_rate = 0.0

    # 整体风险等级
    if risky_suppliers or anomaly_rate > 0.3:
        risk_level = "high"
    elif single_source_categories or anomaly_rate > 0.1:
        risk_level = "medium"
    else:
        risk_level = "low"

    logger.info(
        "risk_assessed",
        risk_level=risk_level,
        risky_supplier_count=len(risky_suppliers),
        single_source_categories=single_source_categories,
        anomaly_rate=anomaly_rate,
        tenant_id=tenant_id,
    )
    return {
        "risk_level": risk_level,
        "risky_suppliers": [
            {
                "id": str(s.id),
                "name": s.name,
                "status": s.status,
                "overall_score": s.overall_score,
            }
            for s in risky_suppliers
        ],
        "single_source_categories": single_source_categories,
        "recent_delivery_stats": {
            "sample_size": total_recent,
            "anomaly_count": anomaly_count,
            "anomaly_rate": anomaly_rate,
        },
        "category_coverage": category_counts,
    }
