"""
应用市场服务 — list/install/uninstall/change_tier/review/billing

职责：
  1. 应用市场列表（支持 category 过滤 + 关键字搜索）
  2. 安装/卸载（含试用期 trial_days 计算）
  3. 档位升降级
  4. 提交/读取评价
  5. 月度账单计算（租户维度汇总）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.app_marketplace import (
    AppBillingRecord,
    Application,
    AppInstallation,
    AppPricingTier,
    AppReview,
)

logger = structlog.get_logger()


class AppMarketplaceService:
    """应用市场核心服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ───────────────────── 应用列表 ─────────────────────
    async def list_apps(
        self,
        category: Optional[str] = None,
        search_query: Optional[str] = None,
        status: str = "published",
    ) -> List[Dict[str, Any]]:
        """应用广场列表：支持分类 + 关键字模糊搜索"""
        stmt = select(Application).where(Application.status == status)
        if category:
            stmt = stmt.where(Application.category == category)
        if search_query:
            kw = f"%{search_query}%"
            stmt = stmt.where(or_(
                Application.name.ilike(kw),
                Application.code.ilike(kw),
                Application.description.ilike(kw),
            ))
        res = await self.db.execute(stmt)
        apps = res.scalars().all()

        out: List[Dict[str, Any]] = []
        for a in apps:
            # 评分统计
            r = await self.db.execute(
                select(func.avg(AppReview.rating), func.count(AppReview.id))
                .where(AppReview.app_id == a.id, AppReview.status == "visible")
            )
            avg_rating, review_count = r.one()
            out.append({
                "id": str(a.id),
                "code": a.code,
                "name": a.name,
                "category": a.category,
                "description": a.description,
                "icon_url": a.icon_url,
                "provider": a.provider,
                "price_model": a.price_model,
                "price_fen": a.price_fen,
                "price_yuan": a.price_yuan,
                "version": a.version,
                "trial_days": a.trial_days,
                "avg_rating": float(avg_rating or 0),
                "review_count": int(review_count or 0),
                "feature_flags": a.feature_flags_json or {},
            })
        return out

    async def get_app_detail(self, app_id: str) -> Optional[Dict[str, Any]]:
        """单个应用详情：含定价档列表 + 最近评价"""
        app = await self.db.get(Application, uuid.UUID(app_id))
        if not app:
            return None
        tiers_res = await self.db.execute(
            select(AppPricingTier).where(AppPricingTier.app_id == app.id)
        )
        tiers = [{
            "id": str(t.id),
            "tier_name": t.tier_name,
            "monthly_fee_fen": t.monthly_fee_fen,
            "monthly_fee_yuan": t.monthly_fee_yuan,
            "usage_limits": t.usage_limits_json or {},
            "features": t.features_json or [],
        } for t in tiers_res.scalars().all()]

        reviews_res = await self.db.execute(
            select(AppReview)
            .where(AppReview.app_id == app.id, AppReview.status == "visible")
            .order_by(AppReview.created_at.desc())
            .limit(10)
        )
        reviews = [{
            "rating": r.rating,
            "review_text": r.review_text,
            "reviewed_by": r.reviewed_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in reviews_res.scalars().all()]

        return {
            "id": str(app.id),
            "code": app.code,
            "name": app.name,
            "category": app.category,
            "description": app.description,
            "icon_url": app.icon_url,
            "provider": app.provider,
            "price_model": app.price_model,
            "price_fen": app.price_fen,
            "price_yuan": app.price_yuan,
            "version": app.version,
            "trial_days": app.trial_days,
            "feature_flags": app.feature_flags_json or {},
            "supported_roles": app.supported_roles_json or [],
            "tiers": tiers,
            "reviews": reviews,
        }

    # ───────────────────── 安装 / 卸载 / 换档 ─────────────────────
    async def install_app(
        self,
        tenant_id: str,
        app_id: str,
        tier_name: Optional[str] = None,
        installed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """安装应用：自动计算试用期；重复安装会激活已 uninstalled 记录"""
        app = await self.db.get(Application, uuid.UUID(app_id))
        if not app:
            raise ValueError(f"application not found: {app_id}")
        if app.status != "published":
            raise ValueError(f"application not published: {app.code}")

        # 查是否已存在非 active 记录
        existing = await self.db.execute(
            select(AppInstallation).where(
                AppInstallation.tenant_id == tenant_id,
                AppInstallation.app_id == app.id,
            )
        )
        inst = existing.scalars().first()

        trial_ends_at = None
        if app.trial_days and app.trial_days > 0:
            trial_ends_at = datetime.utcnow() + timedelta(days=app.trial_days)

        if inst:
            inst.status = "active"
            inst.tier_name = tier_name or inst.tier_name or "basic"
            inst.installed_at = datetime.utcnow()
            inst.trial_ends_at = trial_ends_at
            inst.installed_by = installed_by or inst.installed_by
        else:
            inst = AppInstallation(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                app_id=app.id,
                tier_name=tier_name or "basic",
                installed_at=datetime.utcnow(),
                status="active",
                trial_ends_at=trial_ends_at,
                installed_by=installed_by,
            )
            self.db.add(inst)

        await self.db.flush()
        logger.info("app_installed",
                    tenant=tenant_id, app=app.code, tier=inst.tier_name)
        return {
            "installation_id": str(inst.id),
            "app_code": app.code,
            "tier_name": inst.tier_name,
            "status": inst.status,
            "trial_ends_at": inst.trial_ends_at.isoformat() if inst.trial_ends_at else None,
        }

    async def uninstall_app(self, installation_id: str) -> bool:
        inst = await self.db.get(AppInstallation, uuid.UUID(installation_id))
        if not inst:
            return False
        inst.status = "uninstalled"
        await self.db.flush()
        logger.info("app_uninstalled", installation=installation_id)
        return True

    async def update_tier(
        self, installation_id: str, new_tier: str,
    ) -> Dict[str, Any]:
        inst = await self.db.get(AppInstallation, uuid.UUID(installation_id))
        if not inst:
            raise ValueError("installation not found")
        if inst.status != "active":
            raise ValueError(f"installation not active: {inst.status}")
        # 校验该档位存在
        tier_res = await self.db.execute(
            select(AppPricingTier).where(
                AppPricingTier.app_id == inst.app_id,
                AppPricingTier.tier_name == new_tier,
            )
        )
        if not tier_res.scalars().first():
            raise ValueError(f"tier not found: {new_tier}")

        old = inst.tier_name
        inst.tier_name = new_tier
        await self.db.flush()
        logger.info("app_tier_changed",
                    installation=installation_id, old=old, new=new_tier)
        return {
            "installation_id": str(inst.id),
            "old_tier": old,
            "new_tier": new_tier,
        }

    async def get_my_installations(self, tenant_id: str) -> List[Dict[str, Any]]:
        """租户已装应用清单"""
        res = await self.db.execute(
            select(AppInstallation, Application)
            .join(Application, Application.id == AppInstallation.app_id)
            .where(
                AppInstallation.tenant_id == tenant_id,
                AppInstallation.status != "uninstalled",
            )
        )
        out = []
        for inst, app in res.all():
            out.append({
                "installation_id": str(inst.id),
                "app_id": str(app.id),
                "app_code": app.code,
                "app_name": app.name,
                "category": app.category,
                "tier_name": inst.tier_name,
                "status": inst.status,
                "installed_at": inst.installed_at.isoformat() if inst.installed_at else None,
                "trial_ends_at": inst.trial_ends_at.isoformat() if inst.trial_ends_at else None,
                "in_trial": bool(inst.trial_ends_at and inst.trial_ends_at > datetime.utcnow()),
            })
        return out

    # ───────────────────── 评价 ─────────────────────
    async def submit_review(
        self,
        app_id: str,
        tenant_id: str,
        rating: int,
        review_text: Optional[str] = None,
        reviewed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        if rating < 1 or rating > 5:
            raise ValueError("rating must be 1-5")
        review = AppReview(
            id=uuid.uuid4(),
            app_id=uuid.UUID(app_id),
            tenant_id=tenant_id,
            rating=rating,
            review_text=review_text,
            reviewed_by=reviewed_by,
            status="visible",
        )
        self.db.add(review)
        await self.db.flush()
        return {"review_id": str(review.id), "rating": rating}

    # ───────────────────── 月度账单 ─────────────────────
    async def compute_monthly_bill(
        self, tenant_id: str, billing_period: str,
    ) -> Dict[str, Any]:
        """按租户 × 账期汇总已产生的 billing record"""
        res = await self.db.execute(
            select(AppBillingRecord, AppInstallation, Application)
            .join(AppInstallation, AppInstallation.id == AppBillingRecord.installation_id)
            .join(Application, Application.id == AppInstallation.app_id)
            .where(
                AppInstallation.tenant_id == tenant_id,
                AppBillingRecord.billing_period == billing_period,
            )
        )
        items: List[Dict[str, Any]] = []
        total_fen = 0
        for rec, inst, app in res.all():
            total_fen += int(rec.amount_fen or 0)
            items.append({
                "app_code": app.code,
                "app_name": app.name,
                "tier": inst.tier_name,
                "amount_fen": rec.amount_fen,
                "amount_yuan": rec.amount_yuan,
                "usage": rec.usage_data_json or {},
                "paid_at": rec.paid_at.isoformat() if rec.paid_at else None,
                "invoice_id": rec.invoice_id,
            })
        return {
            "tenant_id": tenant_id,
            "billing_period": billing_period,
            "total_fen": total_fen,
            "total_yuan": round(total_fen / 100, 2),
            "line_items": items,
        }


def get_app_marketplace_service(db: AsyncSession) -> AppMarketplaceService:
    return AppMarketplaceService(db)
