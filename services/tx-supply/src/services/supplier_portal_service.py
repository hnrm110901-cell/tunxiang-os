"""供应链深度管理 — 从进销存到供应链协同网络 (U2.4)

核心能力：
- 供应商管理（注册/评分/排名）
- 自动比价（RFQ → 报价对比 → 推荐）
- 合同管理（创建/到期预警/合规评估）
- 价格情报（趋势/异常/预测）
- 供应商评分（五维度加权）
- 供应链风险评估与缓解建议

金额单位统一为"分"（fen），与 V2.x 保持一致。

存储层：PostgreSQL（通过 SQLAlchemy async ORM）
持久化层：
- supplier_profiles 表 — 供应商主档（register_supplier / update_supplier / get_supplier）
- 若 v064 迁移未运行（表不存在），自动降级到内存模式并记录 WARNING
- 评分计算仍在内存完成（AI 评分由 Phase 1-D 接管）
"""

from __future__ import annotations

import math
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

log = structlog.get_logger(__name__)

import structlog
from sqlalchemy import select, update, func, text, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.supplier_portal import (
    SupplierAccount,
    SupplierQuotation,
    SupplierReconciliation,
)

logger = structlog.get_logger()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SUPPLIER_CATEGORIES = {"seafood", "meat", "vegetable", "seasoning", "frozen", "dry_goods", "beverage", "other"}
SUPPLIER_STATUSES = {"active", "inactive", "suspended", "blacklisted"}

SCORE_WEIGHTS = {
    "quality": 0.30,
    "delivery": 0.25,
    "price": 0.20,
    "service": 0.15,
    "compliance": 0.10,
}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  供应链深度服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SupplierPortalService:
    """供应链深度管理 — DB 持久化版"""
    """供应链深度管理 — 从进销存到供应链协同网络"""

    def __init__(self) -> None:
        self._suppliers: Dict[str, dict] = {}
        self._rfqs: Dict[str, dict] = {}
        self._contracts: Dict[str, dict] = {}
        self._price_history: Dict[str, list] = {}  # {ingredient: [{date, supplier_id, price_fen}]}
        self._delivery_records: Dict[str, list] = {}  # {supplier_id: [{on_time, quality, date}]}
        self._store_suppliers: Dict[str, list] = {}  # {store_id: [supplier_id]}
        self._last_risk_assessment: Dict[str, dict] = {}  # cache: {store_id: assessment}
        self._db_mode: Optional[bool] = None  # None=未检测, True=DB, False=内存降级

    # ──────────────────────────────────────────────────────
    #  DB 模式检测（supplier_profiles 表是否存在）
    # ──────────────────────────────────────────────────────

    async def _check_db_mode(self, db: Any) -> bool:
        """检测 supplier_profiles 表是否存在（v064 迁移是否已运行）"""
        if self._db_mode is not None:
            return self._db_mode
        try:
            await db.execute(text("SELECT 1 FROM supplier_profiles LIMIT 1"))
            self._db_mode = True
            log.info("supplier_portal.mode", mode="db")
        except (ProgrammingError, OperationalError):
            self._db_mode = False
            log.warning(
                "supplier_portal.fallback_to_memory",
                reason="supplier_profiles table not found — run v064_wms_persistence migration",
            )
        return self._db_mode

    async def _set_tenant(self, db: Any, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ──────────────────────────────────────────────────────
    #  1. Supplier Management（供应商管理）
    # ──────────────────────────────────────────────────────

    async def register_supplier(
        self,
        name: str,
        category: str,
        contact: dict,
        certifications: list[str],
        payment_terms: str = "net30",
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """注册供应商"""
        if category not in SUPPLIER_CATEGORIES:
            raise ValueError(f"无效供应商类别: {category}，可选: {SUPPLIER_CATEGORIES}")

        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)

        account = SupplierAccount(
            id=_uuid.uuid4(),
            tenant_id=tid,
            name=name,
            category=category,
            contact=contact,
            certifications=certifications,
            payment_terms=payment_terms,
            status="active",
            overall_score=0.0,
            order_count=0,
        )
        db.add(account)
        await db.flush()

        logger.info("supplier_registered", supplier_id=str(account.id), name=name)
        return {
            "supplier_id": str(account.id),
        tenant_id: str = "",
        db: Any = None,
    ) -> dict:
        """注册供应商，持久化到 supplier_profiles 表（v064 已运行时）。

        Args:
            name: 供应商名称
            category: 供应商类别 (seafood/meat/vegetable/seasoning/frozen/dry_goods/beverage/other)
            contact: 联系信息 {"person": "张三", "phone": "138xxx", "address": "长沙市xxx"}
            certifications: 资质认证列表 ["食品经营许可证", "ISO22000", ...]
            payment_terms: 付款条件 (net30/net60/cod)
            tenant_id: 租户 ID（DB 模式必填）
            db: 数据库会话（DB 模式必填）

        Returns:
            供应商字典
        """
        if category not in SUPPLIER_CATEGORIES:
            raise ValueError(f"无效供应商类别: {category}，可选: {SUPPLIER_CATEGORIES}")

        supplier_id = f"sup_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        import json as _json
        supplier = {
            "supplier_id": supplier_id,
            "name": name,
            "category": category,
            "contact": contact,
            "certifications": certifications,
            "payment_terms": payment_terms,
            "status": "active",
            "overall_score": 0.0,
            "order_count": 0,
            "registered_at": account.created_at.isoformat() if account.created_at else datetime.now(timezone.utc).isoformat(),
        }
            "registered_at": now_iso,
        }

        use_db = db is not None and tenant_id and await self._check_db_mode(db)

        if use_db:
            await self._set_tenant(db, tenant_id)
            # v064 schema: supplier_name, contact_name, contact_phone, address, categories JSONB
            await db.execute(
                text("""
                    INSERT INTO supplier_profiles
                        (id, tenant_id, supplier_name,
                         contact_name, contact_phone, address,
                         categories,
                         status,
                         created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :tenant_id::uuid, :name,
                         :contact_name, :contact_phone, :address,
                         :categories::jsonb,
                         'active',
                         :now, :now)
                    RETURNING id
                """),
                {
                    "tenant_id": tenant_id,
                    "name": name,
                    "contact_name": contact.get("person", ""),
                    "contact_phone": contact.get("phone", ""),
                    "address": contact.get("address", ""),
                    # categories JSONB: 存单个 category 作为 array
                    "categories": _json.dumps([category], ensure_ascii=False),
                    "now": now,
                },
            )
            await db.flush()

        # 同步写入内存（保证计算逻辑可用）
        self._suppliers[supplier_id] = supplier

        log.info(
            "supplier.registered",
            supplier_id=supplier_id,
            name=name,
            category=category,
            mode="db" if use_db else "memory",
        )
        return supplier

    async def update_supplier(
        self,
        supplier_id: str,
        tenant_id: str,
        db: Any,
        *,
        status: Optional[str] = None,
        overall_score: Optional[float] = None,
        order_count: Optional[int] = None,
    ) -> dict:
        """更新供应商信息（持久化版本）。

        Args:
            supplier_id: 供应商 ID
            tenant_id: 租户 ID
            db: 数据库会话
            status: 新状态（可选）
            overall_score: 新综合评分（可选）
            order_count: 新订单数（可选）

        Returns:
            更新后的供应商字典
        """
        use_db = await self._check_db_mode(db)

        if use_db:
            await self._set_tenant(db, tenant_id)

            # v064: supplier_profiles 无 overall_score / order_count 列
            set_clauses = ["updated_at = :now"]
            params: Dict[str, Any] = {
                "id": supplier_id,
                "tenant_id": tenant_id,
                "now": datetime.now(timezone.utc),
            }
            if status is not None:
                set_clauses.append("status = :status")
                params["status"] = status

            result = await db.execute(
                text(f"""
                    UPDATE supplier_profiles
                    SET {', '.join(set_clauses)}
                    WHERE id = :id::uuid AND tenant_id = :tenant_id::uuid
                    RETURNING id
                """),
                params,
            )
            if not result.scalar_one_or_none():
                raise ValueError(f"供应商不存在（DB）: {supplier_id}")

            await db.flush()

        # 同步更新内存缓存
        supplier = self._suppliers.get(supplier_id)
        if supplier:
            if status is not None:
                supplier["status"] = status
            if overall_score is not None:
                supplier["overall_score"] = overall_score
            if order_count is not None:
                supplier["order_count"] = order_count
        elif not use_db:
            raise ValueError(f"供应商不存在: {supplier_id}")

        log.info(
            "supplier.updated",
            supplier_id=supplier_id,
            mode="db" if use_db else "memory",
        )
        return self._suppliers.get(supplier_id, {"supplier_id": supplier_id})

    async def get_supplier(
        self,
        supplier_id: str,
        tenant_id: str,
        db: Any,
    ) -> dict:
        """从 DB 查询供应商（DB 模式），或从内存读取（降级模式）。

        Args:
            supplier_id: 供应商 ID
            tenant_id: 租户 ID
            db: 数据库会话

        Returns:
            供应商字典
        """
        use_db = await self._check_db_mode(db)

        if use_db:
            await self._set_tenant(db, tenant_id)

            import json as _json
            # v064 schema: supplier_name, contact_name, contact_phone, address, categories JSONB
            row = await db.execute(
                text("""
                    SELECT id, supplier_name, categories,
                           contact_name, contact_phone, address,
                           status, created_at
                    FROM supplier_profiles
                    WHERE id = :id::uuid AND tenant_id = :tenant_id::uuid
                      AND is_deleted = FALSE
                """),
                {"id": supplier_id, "tenant_id": tenant_id},
            )
            r = row.mappings().one_or_none()
            if not r:
                raise ValueError(f"供应商不存在: {supplier_id}")

            cats_raw = r["categories"]
            try:
                cats = _json.loads(cats_raw) if isinstance(cats_raw, str) else (cats_raw or [])
            except ValueError:
                cats = []
            # categories[0] 作为主类别，兼容旧内存模式 category 字段
            main_category = cats[0] if cats else "other"

            supplier = {
                "supplier_id": str(r["id"]),
                "name": r["supplier_name"],
                "category": main_category,
                "contact": {
                    "person": r["contact_name"] or "",
                    "phone": r["contact_phone"] or "",
                    "address": r["address"] or "",
                },
                "certifications": [],  # v064 无 certifications 列，保留字段兼容
                "payment_terms": "net30",  # v064 无 payment_terms 列
                "status": r["status"],
                "overall_score": 0.0,
                "order_count": 0,
                "registered_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            # 同步到内存缓存（供评分计算使用）
            self._suppliers[supplier_id] = supplier
            return supplier

        # 内存降级
        supplier = self._suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"供应商不存在: {supplier_id}")
        return supplier

    async def list_suppliers(
        self,
        *,
        tenant_id: str,
        db: AsyncSession,
        category: Optional[str] = None,
        rating_min: Optional[float] = None,
    ) -> list[dict]:
        """列出供应商"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        """列出供应商（从内存缓存读取；调用前请确保 get_supplier 或 register_supplier 已同步缓存）。

        Args:
            category: 筛选类别
            rating_min: 最低评分筛选

        Returns:
            供应商列表
        """
        result = list(self._suppliers.values())

        conditions = [SupplierAccount.tenant_id == tid, SupplierAccount.is_deleted == False]  # noqa: E712
        if category:
            conditions.append(SupplierAccount.category == category)
        if rating_min is not None:
            conditions.append(SupplierAccount.overall_score >= rating_min)

        result = await db.execute(
            select(SupplierAccount).where(and_(*conditions)).order_by(SupplierAccount.overall_score.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "supplier_id": str(r.id),
                "name": r.name,
                "category": r.category,
                "contact": r.contact,
                "certifications": r.certifications,
                "payment_terms": r.payment_terms,
                "status": r.status,
                "overall_score": r.overall_score,
                "order_count": r.order_count,
            }
            for r in rows
        ]

    async def get_supplier_profile(self, supplier_id: str, *, tenant_id: str, db: AsyncSession) -> dict:
        """获取供应商详情"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        result = await db.execute(
            select(SupplierAccount).where(
                SupplierAccount.id == sid, SupplierAccount.tenant_id == tid, SupplierAccount.is_deleted == False  # noqa: E712
            )
        )
        supplier = result.scalar_one_or_none()
    def get_supplier_profile(self, supplier_id: str) -> dict:
        """获取供应商详情（含交付统计，从内存缓存读取）"""
        supplier = self._suppliers.get(supplier_id)
        if not supplier:
            raise ValueError(f"供应商不存在: {supplier_id}")

        # 交付记录统计
        delivery_result = await db.execute(
            select(
                func.count().label("total"),
                func.count().filter(SupplierReconciliation.on_time == True).label("on_time"),  # noqa: E712
                func.count().filter(SupplierReconciliation.quality_result == "pass").label("quality_pass"),
            ).where(
                SupplierReconciliation.supplier_id == sid,
                SupplierReconciliation.tenant_id == tid,
                SupplierReconciliation.record_type == "delivery",
                SupplierReconciliation.is_deleted == False,  # noqa: E712
            )
        )
        dr = delivery_result.one()
        total_deliveries = dr.total or 0
        on_time = dr.on_time or 0
        quality_pass = dr.quality_pass or 0

        # 活跃合同数
        contract_result = await db.execute(
            select(func.count()).where(
                SupplierReconciliation.supplier_id == sid,
                SupplierReconciliation.tenant_id == tid,
                SupplierReconciliation.record_type == "contract",
                SupplierReconciliation.is_deleted == False,  # noqa: E712
            )
        )
        active_contracts = contract_result.scalar() or 0

        return {
            "supplier_id": str(supplier.id),
            "name": supplier.name,
            "category": supplier.category,
            "contact": supplier.contact,
            "certifications": supplier.certifications,
            "payment_terms": supplier.payment_terms,
            "status": supplier.status,
            "overall_score": supplier.overall_score,
            "order_count": supplier.order_count,
            "total_deliveries": total_deliveries,
            "on_time_rate": round(on_time / total_deliveries, 4) if total_deliveries else 0.0,
            "quality_pass_rate": round(quality_pass / total_deliveries, 4) if total_deliveries else 0.0,
            "active_contracts": active_contracts,
        }

    # ──────────────────────────────────────────────────────
    #  2. Auto Bidding（自动比价）
    # ──────────────────────────────────────────────────────

    async def request_quotes(
        self,
        item_name: str,
        quantity: float,
        delivery_date: str,
        supplier_ids: Optional[list[str]] = None,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """发起询价 (RFQ)"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        rfq_id = f"rfq_{_uuid.uuid4().hex[:8]}"

        if supplier_ids is None:
            result = await db.execute(
                select(SupplierAccount.id).where(
                    SupplierAccount.tenant_id == tid,
                    SupplierAccount.status == "active",
                    SupplierAccount.is_deleted == False,  # noqa: E712
                )
            )
            supplier_ids = [str(r) for r in result.scalars().all()]

        d_date = date.fromisoformat(delivery_date) if delivery_date else None

        for sid in supplier_ids:
            quotation = SupplierQuotation(
                id=_uuid.uuid4(),
                tenant_id=tid,
                supplier_id=_uuid.UUID(sid),
                rfq_id=rfq_id,
                item_name=item_name,
                quantity=quantity,
                delivery_date=d_date,
                status="open",
            )
            db.add(quotation)

        await db.flush()
        logger.info("rfq_created", rfq_id=rfq_id, item=item_name, suppliers=len(supplier_ids))

        return {
            "rfq_id": rfq_id,
            "item_name": item_name,
            "quantity": quantity,
            "delivery_date": delivery_date,
            "supplier_ids": supplier_ids,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def submit_quote(
        self,
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
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        result = await db.execute(
            select(SupplierQuotation).where(
                SupplierQuotation.rfq_id == rfq_id,
                SupplierQuotation.supplier_id == sid,
                SupplierQuotation.tenant_id == tid,
                SupplierQuotation.is_deleted == False,  # noqa: E712
            )
        )
        quotation = result.scalar_one_or_none()
        if not quotation:
            raise ValueError(f"RFQ {rfq_id} 中不存在供应商 {supplier_id}")

        quotation.unit_price_fen = unit_price_fen
        quotation.total_price_fen = int(unit_price_fen * float(quotation.quantity))
        quotation.delivery_days = delivery_days
        quotation.notes = notes
        quotation.status = "quoted"
        quotation.submitted_at = datetime.now(timezone.utc)
        await db.flush()

    async def compare_quotes(self, rfq_id: str, *, tenant_id: str, db: AsyncSession) -> dict:
        """对比报价并推荐最佳供应商"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)

        result = await db.execute(
            select(SupplierQuotation).where(
                SupplierQuotation.rfq_id == rfq_id,
                SupplierQuotation.tenant_id == tid,
                SupplierQuotation.status == "quoted",
                SupplierQuotation.is_deleted == False,  # noqa: E712
            )
        )
        quotes = result.scalars().all()

        if not quotes:
            return {"rfq_id": rfq_id, "quotes": [], "recommended": None, "reason": "无供应商报价"}

        # 获取供应商名称
        supplier_ids = [q.supplier_id for q in quotes]
        sup_result = await db.execute(
            select(SupplierAccount.id, SupplierAccount.name).where(SupplierAccount.id.in_(supplier_ids))
        )
        name_map = {r[0]: r[1] for r in sup_result.all()}

        prices = [q.unit_price_fen for q in quotes]
        min_price, max_price = min(prices), max(prices)
        price_range = max_price - min_price if max_price > min_price else 1

        days_list = [q.delivery_days for q in quotes]
        min_days, max_days = min(days_list), max(days_list)
        days_range = max_days - min_days if max_days > min_days else 1

        scored = []
        for q in quotes:
            price_score = 100 * (max_price - q.unit_price_fen) / price_range if price_range > 0 else 100
            delivery_score = 100 * (max_days - q.delivery_days) / days_range if days_range > 0 else 100

            # 历史可靠性
            dr = await db.execute(
                select(
                    func.count().label("total"),
                    func.count().filter(SupplierReconciliation.on_time == True).label("on_time"),  # noqa: E712
                    func.count().filter(SupplierReconciliation.quality_result == "pass").label("qp"),
                ).where(
                    SupplierReconciliation.supplier_id == q.supplier_id,
                    SupplierReconciliation.tenant_id == tid,
                    SupplierReconciliation.record_type == "delivery",
                    SupplierReconciliation.is_deleted == False,  # noqa: E712
                )
            )
            row = dr.one()
            if row.total and row.total > 0:
                reliability_score = ((row.on_time or 0) / row.total * 50 + (row.qp or 0) / row.total * 50)
            else:
                reliability_score = 50

            composite = price_score * 0.4 + delivery_score * 0.3 + reliability_score * 0.3

            scored.append({
                "supplier_id": str(q.supplier_id),
                "supplier_name": name_map.get(q.supplier_id, ""),
                "unit_price_fen": q.unit_price_fen,
                "total_price_fen": q.total_price_fen,
                "delivery_days": q.delivery_days,
                "notes": q.notes or "",
                "price_score": round(price_score, 1),
                "delivery_score": round(delivery_score, 1),
                "reliability_score": round(reliability_score, 1),
                "composite_score": round(composite, 1),
            })

            q.composite_score = round(composite, 1)
            q.score_detail = {"price": round(price_score, 1), "delivery": round(delivery_score, 1), "reliability": round(reliability_score, 1)}

        await db.flush()
        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        best = scored[0]

        reasons = []
        if best["price_score"] >= 80:
            reasons.append("价格最优")
        if best["delivery_score"] >= 80:
            reasons.append("交付最快")
        if best["reliability_score"] >= 80:
            reasons.append("历史可靠性高")

        return {
            "rfq_id": rfq_id,
            "item_name": quotes[0].item_name,
            "quantity": float(quotes[0].quantity),
            "quotes": scored,
            "recommended": {
                "supplier_id": best["supplier_id"],
                "supplier_name": best["supplier_name"],
                "unit_price_fen": best["unit_price_fen"],
                "composite_score": best["composite_score"],
            },
            "reason": "、".join(reasons) if reasons else "综合评分最高",
        }

    async def accept_quote(self, rfq_id: str, supplier_id: str, *, tenant_id: str, db: AsyncSession) -> dict:
        """接受报价"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        result = await db.execute(
            select(SupplierQuotation).where(
                SupplierQuotation.rfq_id == rfq_id,
                SupplierQuotation.supplier_id == sid,
                SupplierQuotation.tenant_id == tid,
                SupplierQuotation.is_deleted == False,  # noqa: E712
            )
        )
        quote = result.scalar_one_or_none()
        if not quote:
            raise ValueError(f"供应商 {supplier_id} 未在 RFQ {rfq_id} 中报价")

        quote.status = "accepted"

        # 其他报价标为 rejected
        await db.execute(
            update(SupplierQuotation).where(
                SupplierQuotation.rfq_id == rfq_id,
                SupplierQuotation.tenant_id == tid,
                SupplierQuotation.supplier_id != sid,
            ).values(status="rejected")
        )
        await db.flush()

        sup_result = await db.execute(select(SupplierAccount.name).where(SupplierAccount.id == sid))
        sup_name = sup_result.scalar() or ""

        return {
            "rfq_id": rfq_id,
            "status": "accepted",
            "supplier_id": supplier_id,
            "supplier_name": sup_name,
            "unit_price_fen": quote.unit_price_fen,
            "total_price_fen": quote.total_price_fen,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────
    #  3. Contract Management（合同管理）
    # ──────────────────────────────────────────────────────

    async def create_contract(
        self,
        supplier_id: str,
        items: list[dict],
        start_date: str,
        end_date: str,
        pricing_terms: str,
        payment_terms: str,
        penalties: dict,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """创建采购合同（存为 reconciliation record_type=contract）"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        # 验证供应商
        sup_result = await db.execute(
            select(SupplierAccount).where(SupplierAccount.id == sid, SupplierAccount.tenant_id == tid)
        )
        supplier = sup_result.scalar_one_or_none()
        if not supplier:
            raise ValueError(f"供应商不存在: {supplier_id}")

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end <= start:
            raise ValueError("合同结束日期必须晚于开始日期")

        contract_id = f"ct_{_uuid.uuid4().hex[:8]}"

        record = SupplierReconciliation(
            id=_uuid.uuid4(),
            tenant_id=tid,
            supplier_id=sid,
            record_type="contract",
            reference_id=contract_id,
            record_date=start,
            contract_data={
                "items": items,
                "item_count": len(items),
                "start_date": start_date,
                "end_date": end_date,
                "duration_days": (end - start).days,
                "pricing_terms": pricing_terms,
                "payment_terms": payment_terms,
                "penalties": penalties,
                "status": "active",
            },
        )
        db.add(record)
        await db.flush()

        return {
            "contract_id": contract_id,
            "supplier_id": supplier_id,
            "supplier_name": supplier.name,
            "items": items,
            "item_count": len(items),
            "start_date": start_date,
            "end_date": end_date,
            "duration_days": (end - start).days,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def check_contract_expiry(self, days_ahead: int = 30, *, tenant_id: str, db: AsyncSession) -> list[dict]:
        """检查即将到期的合同"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)

        result = await db.execute(
            select(SupplierReconciliation).where(
                SupplierReconciliation.tenant_id == tid,
                SupplierReconciliation.record_type == "contract",
                SupplierReconciliation.is_deleted == False,  # noqa: E712
            )
        )
        contracts = result.scalars().all()

        today = date.today()
        deadline = today + timedelta(days=days_ahead)
        expiring = []

        for c in contracts:
            data = c.contract_data or {}
            if data.get("status") != "active":
                continue
            end_str = data.get("end_date", "")
            if not end_str:
                continue
            end = date.fromisoformat(end_str)
            if today <= end <= deadline:
                days_remaining = (end - today).days
                sup_result = await db.execute(select(SupplierAccount.name).where(SupplierAccount.id == c.supplier_id))
                sup_name = sup_result.scalar() or ""
                expiring.append({
                    "contract_id": c.reference_id,
                    "supplier_id": str(c.supplier_id),
                    "supplier_name": sup_name,
                    "end_date": end_str,
                    "days_remaining": days_remaining,
                    "item_count": data.get("item_count", 0),
                    "urgency": "critical" if days_remaining <= 7 else "warning",
                })

        expiring.sort(key=lambda x: x["days_remaining"])
        return expiring

    # ──────────────────────────────────────────────────────
    #  4. Supplier Scoring（供应商评分）
    # ──────────────────────────────────────────────────────

    async def calculate_supplier_score(self, supplier_id: str, *, tenant_id: str, db: AsyncSession) -> dict:
        """计算供应商综合评分（五维度加权）"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        sup_result = await db.execute(
            select(SupplierAccount).where(SupplierAccount.id == sid, SupplierAccount.tenant_id == tid)
        )
        supplier = sup_result.scalar_one_or_none()
        if not supplier:
            raise ValueError(f"供应商不存在: {supplier_id}")

        # 交付记录
        dr = await db.execute(
            select(SupplierReconciliation).where(
                SupplierReconciliation.supplier_id == sid,
                SupplierReconciliation.tenant_id == tid,
                SupplierReconciliation.record_type == "delivery",
                SupplierReconciliation.is_deleted == False,  # noqa: E712
            ).order_by(SupplierReconciliation.created_at)
        )
        records = dr.scalars().all()
        total = len(records)

        if not records:
            return {
                "supplier_id": supplier_id,
                "supplier_name": supplier.name,
                "overall_score": 0.0,
                "quality_score": 0.0,
                "delivery_score": 0.0,
                "price_score": 0.0,
                "service_score": 0.0,
                "compliance_score": 0.0,
                "trend": "no_data",
                "recommendation": "approved",
                "record_count": 0,
            }

        quality_pass = sum(1 for r in records if r.quality_result == "pass")
        quality_score = round(quality_pass / total * 100, 1)

        on_time = sum(1 for r in records if r.on_time)
        delivery_score = round(on_time / total * 100, 1)

        price_scores = [r.price_competitiveness or 70 for r in records]
        price_score = round(sum(price_scores) / len(price_scores), 1)

        service_scores = [r.service_rating or 70 for r in records]
        service_score = round(sum(service_scores) / len(service_scores), 1)

        certs = supplier.certifications or []
        compliance_score = min(100.0, len(certs) * 25.0)

        overall = round(
            quality_score * SCORE_WEIGHTS["quality"]
            + delivery_score * SCORE_WEIGHTS["delivery"]
            + price_score * SCORE_WEIGHTS["price"]
            + service_score * SCORE_WEIGHTS["service"]
            + compliance_score * SCORE_WEIGHTS["compliance"],
            1,
        )

        supplier.overall_score = overall
        await db.flush()

        # 趋势
        if total >= 6:
            mid = total // 2
            early_ot = sum(1 for r in records[:mid] if r.on_time) / mid
            late_ot = sum(1 for r in records[mid:] if r.on_time) / (total - mid)
            trend = "improving" if late_ot > early_ot + 0.1 else ("declining" if late_ot < early_ot - 0.1 else "stable")
        else:
            trend = "insufficient_data"

        recommendation = "preferred" if overall >= 85 else ("approved" if overall >= 60 else ("probation" if overall >= 40 else "blacklist"))

        return {
            "supplier_id": supplier_id,
            "supplier_name": supplier.name,
            "overall_score": overall,
            "quality_score": quality_score,
            "delivery_score": delivery_score,
            "price_score": price_score,
            "service_score": service_score,
            "compliance_score": compliance_score,
            "trend": trend,
            "recommendation": recommendation,
            "record_count": total,
        }

    async def get_supplier_ranking(self, category: str, *, tenant_id: str, db: AsyncSession) -> list[dict]:
        """获取品类下供应商排名"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)

        result = await db.execute(
            select(SupplierAccount).where(
                SupplierAccount.tenant_id == tid,
                SupplierAccount.category == category,
                SupplierAccount.is_deleted == False,  # noqa: E712
            ).order_by(SupplierAccount.overall_score.desc())
        )
        suppliers = result.scalars().all()

        ranked = []
        for i, s in enumerate(suppliers):
            score_data = await self.calculate_supplier_score(str(s.id), tenant_id=tenant_id, db=db)
            ranked.append({
                "rank": i + 1,
                "supplier_id": str(s.id),
                "name": s.name,
                "overall_score": score_data["overall_score"],
                "recommendation": score_data["recommendation"],
                "trend": score_data["trend"],
            })

        ranked.sort(key=lambda x: x["overall_score"], reverse=True)
        for i, item in enumerate(ranked):
            item["rank"] = i + 1
        return ranked

    # ──────────────────────────────────────────────────────
    #  5. 交付记录管理
    # ──────────────────────────────────────────────────────

    async def add_delivery_record(
        self,
        supplier_id: str,
        record: dict,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """添加交付记录"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        rec = SupplierReconciliation(
            id=_uuid.uuid4(),
            tenant_id=tid,
            supplier_id=sid,
            record_type="delivery",
            store_id=_uuid.UUID(record["store_id"]) if record.get("store_id") else None,
            ingredient_name=record.get("ingredient"),
            on_time=record.get("on_time", False),
            quality_result=record.get("quality", "pass"),
            price_adherence=record.get("price_adherence", True),
            price_competitiveness=record.get("price_competitiveness"),
            service_rating=record.get("service_rating"),
            price_fen=record.get("price_fen"),
            total_fen=record.get("total_fen"),
            record_date=date.fromisoformat(record["date"]) if record.get("date") else date.today(),
        )
        db.add(rec)
        await db.flush()

    async def add_price_history(
        self,
        ingredient: str,
        supplier_id: str,
        price_fen: int,
        *,
        tenant_id: str,
        db: AsyncSession,
        record_date: Optional[date] = None,
    ) -> None:
        """添加价格历史"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        sid = _uuid.UUID(supplier_id)

        rec = SupplierReconciliation(
            id=_uuid.uuid4(),
            tenant_id=tid,
            supplier_id=sid,
            record_type="price_history",
            ingredient_name=ingredient,
            price_fen=price_fen,
            record_date=record_date or date.today(),
        )
        db.add(rec)
        await db.flush()

    async def get_price_trend(self, ingredient: str, days: int = 180, *, tenant_id: str, db: AsyncSession) -> dict:
        """获取食材价格趋势"""
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        cutoff = date.today() - timedelta(days=days)

        result = await db.execute(
            select(SupplierReconciliation).where(
                SupplierReconciliation.tenant_id == tid,
                SupplierReconciliation.record_type == "price_history",
                SupplierReconciliation.ingredient_name == ingredient,
                SupplierReconciliation.record_date >= cutoff,
                SupplierReconciliation.is_deleted == False,  # noqa: E712
            ).order_by(SupplierReconciliation.record_date)
        )
        rows = result.scalars().all()

        if not rows:
            return {"ingredient": ingredient, "days": days, "data_points": 0, "trend": "no_data", "prices": []}

        prices = [r.price_fen for r in rows if r.price_fen]
        if not prices:
            return {"ingredient": ingredient, "days": days, "data_points": 0, "trend": "no_data", "prices": []}

        avg_price = round(sum(prices) / len(prices))
        latest, earliest = prices[-1], prices[0]

        if len(prices) >= 2:
            change_pct = (latest - earliest) / earliest * 100 if earliest > 0 else 0
            trend = "rising" if change_pct > 10 else ("falling" if change_pct < -10 else "stable")
        else:
            trend, change_pct = "insufficient_data", 0

        return {
            "ingredient": ingredient,
            "days": days,
            "data_points": len(prices),
            "avg_price_fen": avg_price,
            "min_price_fen": min(prices),
            "max_price_fen": max(prices),
            "latest_price_fen": latest,
            "change_pct": round(change_pct, 1),
            "trend": trend,
            "volatility": round((max(prices) - min(prices)) / avg_price * 100, 1) if avg_price > 0 else 0,
        }

    async def detect_price_anomaly(
        self, supplier_id: str, item: str, proposed_price: int, *, tenant_id: str, db: AsyncSession,
    ) -> dict:
        """检测价格异常"""
        trend = await self.get_price_trend(item, days=180, tenant_id=tenant_id, db=db)
        avg = trend.get("avg_price_fen", 0)

        if trend["data_points"] == 0:
            return {
                "supplier_id": supplier_id, "item": item, "proposed_price_fen": proposed_price,
                "is_anomaly": False, "reason": "无历史价格数据", "confidence": 0.0,
            }

        # 从 DB 获取最近价格计算标准差
        await _set_tenant(db, tenant_id)
        tid = _uuid.UUID(tenant_id)
        result = await db.execute(
            select(SupplierReconciliation.price_fen).where(
                SupplierReconciliation.tenant_id == tid,
                SupplierReconciliation.record_type == "price_history",
                SupplierReconciliation.ingredient_name == item,
                SupplierReconciliation.price_fen.isnot(None),
                SupplierReconciliation.is_deleted == False,  # noqa: E712
            ).order_by(SupplierReconciliation.record_date.desc()).limit(30)
        )
        recent_prices = [r[0] for r in result.all()]

        if not recent_prices:
            return {
                "supplier_id": supplier_id, "item": item, "proposed_price_fen": proposed_price,
                "is_anomaly": False, "reason": "无历史价格数据", "confidence": 0.0,
            }

        avg_r = sum(recent_prices) / len(recent_prices)
        variance = sum((p - avg_r) ** 2 for p in recent_prices) / len(recent_prices)
        std_dev = math.sqrt(variance) if variance > 0 else 0
        threshold = avg_r + 2 * std_dev if std_dev > 0 else avg_r * 1.3
        deviation_pct = (proposed_price - avg_r) / avg_r * 100 if avg_r > 0 else 0
        is_anomaly = proposed_price > threshold

        return {
            "supplier_id": supplier_id,
            "item": item,
            "proposed_price_fen": proposed_price,
            "market_avg_fen": round(avg_r),
            "threshold_fen": round(threshold),
            "deviation_pct": round(deviation_pct, 1),
            "is_anomaly": is_anomaly,
            "reason": f"报价高于均价 {round(deviation_pct, 1)}%" if is_anomaly else "报价在合理范围内",
            "confidence": round(min(0.95, 0.5 + deviation_pct / 100), 2) if is_anomaly else round(min(0.9, 0.3 + len(recent_prices) * 0.03), 2),
        }
