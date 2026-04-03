"""集团视角跨品牌分析服务

技术方案：应用层聚合（不破坏 RLS）
  - 每个品牌单独设置 app.tenant_id，单独查询 customers 表
  - asyncio.gather 并发多品牌查询，降低延迟
  - 不使用超级租户绕过 RLS，避免数据安全风险

金额单位：分（fen）。
"""
from __future__ import annotations

import asyncio
import uuid
from collections import Counter, defaultdict
from typing import Any

import structlog
from fastapi import HTTPException
from models.group_config import BrandGroup
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer

logger = structlog.get_logger(__name__)

# RFM 等级优先级排序（S1 最高价值）
_RFM_PRIORITY: dict[str, int] = {
    "S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5,
}

CHURN_HIGH_RISK_DAYS = 60
CHURN_MEDIUM_RISK_DAYS = 30


def _to_uuid(val: str | uuid.UUID) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    return uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文（线程安全：每次调用覆盖当前事务配置）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _fetch_brand_group(
    group_id: uuid.UUID,
    group_tenant_id: str,
    db: AsyncSession,
) -> BrandGroup:
    """按 group_id 查询品牌组配置，不存在则抛 404"""
    await _set_tenant(db, group_tenant_id)
    result = await db.execute(
        select(BrandGroup)
        .where(BrandGroup.id == group_id)
        .where(BrandGroup.tenant_id == _to_uuid(group_tenant_id))
        .where(BrandGroup.is_deleted == False)  # noqa: E712
        .where(BrandGroup.status == "active")
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="brand_group_not_found")
    return group


async def _query_brand_customers(
    tenant_id: str,
    brand_name: str,
    db: AsyncSession,
) -> list[Customer]:
    """在单品牌 RLS 上下文内查询全量 Customer（不含已删除/已合并）"""
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    result = await db.execute(
        select(Customer)
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
    )
    return list(result.scalars().all())


async def _query_customer_by_phone(
    phone: str,
    tenant_id: str,
    db: AsyncSession,
) -> Customer | None:
    """在单品牌 RLS 上下文内按手机号查询 Customer"""
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    result = await db.execute(
        select(Customer)
        .where(Customer.primary_phone == phone)
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
    )
    return result.scalar_one_or_none()


class GroupAnalyticsService:
    """集团视角跨品牌分析服务

    所有方法采用「应用层聚合」模式：
      1. 从 brand_groups 表获取旗下 brand_tenant_ids
      2. asyncio.gather 并发对每个 tenant_id 执行单品牌查询
      3. 在应用层汇总、去重、排序

    调用方须提供 group_tenant_id（集团主租户 ID）用于 RLS 校验。
    """

    async def get_group_member_profile(
        self,
        phone: str,
        group_id: uuid.UUID,
        group_tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询某手机号在集团所有品牌的会员信息（跨品牌全貌）

        并发查询各品牌，汇总跨品牌消费数据。

        Returns:
            {
                phone, group_total_amount_fen, group_total_orders,
                brands: [{tenant_id, brand_name, member_level,
                          total_amount_fen, total_orders, last_order_at, rfm_level}]
            }
        """
        log = logger.bind(group_id=str(group_id), phone=phone[-4:] + "****")

        group = await _fetch_brand_group(group_id, group_tenant_id, db)
        brand_tenant_ids: list[str] = [str(t) for t in group.brand_tenant_ids]

        if not brand_tenant_ids:
            log.info("group_member_profile_no_brands")
            return {
                "phone": phone,
                "group_total_amount_fen": 0,
                "group_total_orders": 0,
                "brands": [],
            }

        # 并发查询各品牌
        tasks = [
            _query_customer_by_phone(phone, tid, db)
            for tid in brand_tenant_ids
        ]
        results: list[Customer | None] = await asyncio.gather(*tasks)

        brand_profiles: list[dict] = []
        for tenant_id, customer in zip(brand_tenant_ids, results):
            if customer is None:
                continue

            last_order_str: str | None = None
            if customer.last_order_at is not None:
                last_order_str = customer.last_order_at.isoformat()

            brand_profiles.append({
                "tenant_id": tenant_id,
                "brand_name": None,          # 品牌名称由上层调用方填充（或接入 tx-org 获取）
                "member_level": customer.rfm_level,
                "total_amount_fen": customer.total_order_amount_fen,
                "total_orders": customer.total_order_count,
                "last_order_at": last_order_str,
                "rfm_level": customer.rfm_level,
                "r_score": customer.r_score,
                "f_score": customer.f_score,
                "m_score": customer.m_score,
                "tags": customer.tags or [],
            })

        group_total_amount_fen = sum(b["total_amount_fen"] for b in brand_profiles)
        group_total_orders = sum(b["total_orders"] for b in brand_profiles)

        log.info(
            "group_member_profile_fetched",
            brand_count=len(brand_profiles),
            group_total_orders=group_total_orders,
        )

        return {
            "phone": phone,
            "group_total_amount_fen": group_total_amount_fen,
            "group_total_orders": group_total_orders,
            "brands": brand_profiles,
        }

    async def get_group_rfm_dashboard(
        self,
        group_id: uuid.UUID,
        group_tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """集团 RFM 总览（跨品牌汇总）

        去重逻辑：同一手机号在多品牌出现时，按最高 RFM 等级（S1 最高）计入总分布。

        Returns:
            {
                group_total_members（去重 by 手机号），
                brands: [{brand_name, tenant_id, total_members, s1_count ... s5_count}],
                cross_brand_members,
                group_rfm_distribution: {S1:N, ...}
            }
        """
        log = logger.bind(group_id=str(group_id))

        group = await _fetch_brand_group(group_id, group_tenant_id, db)
        brand_tenant_ids: list[str] = [str(t) for t in group.brand_tenant_ids]

        if not brand_tenant_ids:
            log.info("group_rfm_dashboard_no_brands")
            return {
                "group_total_members": 0,
                "brands": [],
                "cross_brand_members": 0,
                "group_rfm_distribution": {f"S{i}": 0 for i in range(1, 6)},
            }

        # 并发查询各品牌所有客户
        tasks = [
            _query_brand_customers(tid, brand_name="", db=db)
            for tid in brand_tenant_ids
        ]
        brand_customers_lists: list[list[Customer]] = await asyncio.gather(*tasks)

        brands_summary: list[dict] = []
        # phone -> 该手机号在各品牌的 rfm_level 列表
        phone_rfm_map: dict[str, list[str]] = defaultdict(list)
        # phone -> 出现品牌数
        phone_brand_count: Counter[str] = Counter()

        for tenant_id, customers in zip(brand_tenant_ids, brand_customers_lists):
            rfm_counts: dict[str, int] = {f"S{i}": 0 for i in range(1, 6)}
            for c in customers:
                lvl = c.rfm_level or "S3"
                if lvl in rfm_counts:
                    rfm_counts[lvl] += 1
                if c.primary_phone:
                    phone_rfm_map[c.primary_phone].append(lvl)
                    phone_brand_count[c.primary_phone] += 1

            brands_summary.append({
                "tenant_id": tenant_id,
                "brand_name": None,          # 调用方从 tx-org 填充品牌名
                "total_members": len(customers),
                **rfm_counts,
            })

        # 去重总会员数
        group_total_members = len(phone_rfm_map)

        # 跨品牌消费人数（在 2 个以上品牌出现）
        cross_brand_members = sum(
            1 for cnt in phone_brand_count.values() if cnt >= 2
        )

        # 集团 RFM 分布：每个手机号取最高等级（S1 最优先）
        group_rfm_dist: dict[str, int] = {f"S{i}": 0 for i in range(1, 6)}
        for levels in phone_rfm_map.values():
            best = min(levels, key=lambda lvl: _RFM_PRIORITY.get(lvl, 99))
            if best in group_rfm_dist:
                group_rfm_dist[best] += 1

        log.info(
            "group_rfm_dashboard_done",
            group_total_members=group_total_members,
            cross_brand_members=cross_brand_members,
        )

        return {
            "group_total_members": group_total_members,
            "brands": brands_summary,
            "cross_brand_members": cross_brand_members,
            "group_rfm_distribution": group_rfm_dist,
        }

    async def get_group_churn_risk(
        self,
        group_id: uuid.UUID,
        group_tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """集团流失风险汇总

        规则（与单品牌一致）：
          >60 天未消费 → 高风险
          30-60 天未消费 → 中风险

        Returns:
            {
                high_risk_count（跨品牌去重），
                brands: [{brand_name, tenant_id, high_risk_count, medium_risk_count}],
                top_at_risk: 最有价值的高风险客户（最多 20 条，按 total_order_amount_fen 降序）
            }
        """
        from datetime import datetime, timezone

        log = logger.bind(group_id=str(group_id))
        now = datetime.now(timezone.utc)

        group = await _fetch_brand_group(group_id, group_tenant_id, db)
        brand_tenant_ids: list[str] = [str(t) for t in group.brand_tenant_ids]

        tasks = [
            _query_brand_customers(tid, brand_name="", db=db)
            for tid in brand_tenant_ids
        ]
        brand_customers_lists: list[list[Customer]] = await asyncio.gather(*tasks)

        brands_risk: list[dict] = []
        # 跨品牌高风险客户（手机号去重），取最高风险品牌数据
        high_risk_phones: dict[str, dict] = {}

        for tenant_id, customers in zip(brand_tenant_ids, brand_customers_lists):
            high_cnt = 0
            med_cnt = 0

            for c in customers:
                if c.last_order_at is None:
                    continue
                last = c.last_order_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)

                days_since = (now - last).days
                if days_since > CHURN_HIGH_RISK_DAYS:
                    high_cnt += 1
                    # 去重：手机号相同时保留消费金额更高的记录
                    phone = c.primary_phone
                    if phone not in high_risk_phones or (
                        c.total_order_amount_fen
                        > high_risk_phones[phone]["total_order_amount_fen"]
                    ):
                        high_risk_phones[phone] = {
                            "customer_id": str(c.id),
                            "phone": phone,
                            "display_name": c.display_name,
                            "tenant_id": tenant_id,
                            "days_since_last_order": days_since,
                            "rfm_level": c.rfm_level,
                            "total_order_amount_fen": c.total_order_amount_fen,
                            "total_order_count": c.total_order_count,
                        }
                elif days_since > CHURN_MEDIUM_RISK_DAYS:
                    med_cnt += 1

            brands_risk.append({
                "tenant_id": tenant_id,
                "brand_name": None,
                "high_risk_count": high_cnt,
                "medium_risk_count": med_cnt,
            })

        # TOP 20 最有价值高风险客户（按历史消费金额降序）
        top_at_risk = sorted(
            high_risk_phones.values(),
            key=lambda x: x["total_order_amount_fen"],
            reverse=True,
        )[:20]

        log.info(
            "group_churn_risk_done",
            high_risk_unique_phones=len(high_risk_phones),
            brand_count=len(brands_risk),
        )

        return {
            "high_risk_count": len(high_risk_phones),
            "brands": brands_risk,
            "top_at_risk": top_at_risk,
        }

    async def configure_stored_value_interop(
        self,
        group_id: uuid.UUID,
        interop: bool,
        operator_id: uuid.UUID,
        group_tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """配置储值卡跨品牌互通开关

        开启互通后，各品牌的 StoredValueCard.scope_type 应设为 'group'。
        通知逻辑说明（注释）：
          - 实际互通生效需在 tx-member 储值服务中，按 brand_tenant_ids 逐一更新
            stored_value_cards 的 scope_type，本方法仅更新集团配置开关。
          - 业务上建议通过消息队列（Redis Stream）异步通知各品牌储值服务更新，
            避免在单次 HTTP 请求中跨多个 tenant 事务，防止部分失败难以回滚。
        """
        log = logger.bind(group_id=str(group_id), interop=interop)

        group = await _fetch_brand_group(group_id, group_tenant_id, db)
        group.stored_value_interop = interop
        group.updated_by = operator_id
        await db.flush()

        log.info(
            "stored_value_interop_configured",
            brand_count=len(group.brand_tenant_ids),
        )

        return {
            "group_id": str(group_id),
            "stored_value_interop": interop,
            "brand_count": len(group.brand_tenant_ids),
            "note": (
                "集团配置已更新。各品牌储值卡 scope_type 需通过异步任务同步，"
                "请确认 Redis Stream 事件已发送。"
            ),
        }

    async def find_cross_brand_customers(
        self,
        group_id: uuid.UUID,
        group_tenant_id: str,
        min_brands: int = 2,
        db: AsyncSession = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """找出在 N 个以上品牌消费过的客户（集团最核心的高价值客户）

        实现：
          1. 并发查询各品牌所有客户手机号
          2. Counter 统计手机号出现次数
          3. 返回出现次数 >= min_brands 的客户（附各品牌消费详情）

        Returns:
            {
                total_cross_brand,
                min_brands,
                customers: [
                    {
                        phone, brand_count, group_total_amount_fen,
                        group_total_orders,
                        brands: [{tenant_id, total_amount_fen, total_orders,
                                  rfm_level, last_order_at}]
                    }
                ]
            }
        """
        log = logger.bind(group_id=str(group_id), min_brands=min_brands)

        group = await _fetch_brand_group(group_id, group_tenant_id, db)
        brand_tenant_ids: list[str] = [str(t) for t in group.brand_tenant_ids]

        tasks = [
            _query_brand_customers(tid, brand_name="", db=db)
            for tid in brand_tenant_ids
        ]
        brand_customers_lists: list[list[Customer]] = await asyncio.gather(*tasks)

        # phone -> [{tenant_id, customer}]
        phone_brand_map: dict[str, list[dict]] = defaultdict(list)

        for tenant_id, customers in zip(brand_tenant_ids, brand_customers_lists):
            for c in customers:
                if c.primary_phone:
                    last_order_str: str | None = None
                    if c.last_order_at is not None:
                        last_order_str = c.last_order_at.isoformat()

                    phone_brand_map[c.primary_phone].append({
                        "tenant_id": tenant_id,
                        "customer_id": str(c.id),
                        "total_amount_fen": c.total_order_amount_fen,
                        "total_orders": c.total_order_count,
                        "rfm_level": c.rfm_level,
                        "last_order_at": last_order_str,
                    })

        # 筛选出现 >= min_brands 的客户
        cross_brand_customers: list[dict] = []
        for phone, brand_entries in phone_brand_map.items():
            if len(brand_entries) < min_brands:
                continue

            group_total_amount = sum(b["total_amount_fen"] for b in brand_entries)
            group_total_orders = sum(b["total_orders"] for b in brand_entries)

            cross_brand_customers.append({
                "phone": phone,
                "brand_count": len(brand_entries),
                "group_total_amount_fen": group_total_amount,
                "group_total_orders": group_total_orders,
                "brands": brand_entries,
            })

        # 按集团总消费金额降序
        cross_brand_customers.sort(
            key=lambda x: x["group_total_amount_fen"],
            reverse=True,
        )

        log.info(
            "cross_brand_customers_found",
            total_cross_brand=len(cross_brand_customers),
            min_brands=min_brands,
        )

        return {
            "total_cross_brand": len(cross_brand_customers),
            "min_brands": min_brands,
            "customers": cross_brand_customers,
        }
