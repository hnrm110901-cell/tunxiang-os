"""会员 Repository — 真实 DB 查询层

封装 Customer 的 CRUD + RFM 分析查询 + 企微 SCRM 绑定操作。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update, func, case, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer, Order

logger = structlog.get_logger()


class CustomerRepository:
    """会员 Repository — 封装真实 DB 查询"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 会员 CRUD ───

    async def list_customers(
        self,
        store_id: str,
        rfm_level: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询会员列表，可按 RFM 等级筛选"""
        await self._set_tenant()

        base = (
            select(Customer)
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
        )
        count_base = (
            select(func.count(Customer.id))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
        )

        if rfm_level:
            base = base.where(Customer.rfm_level == rfm_level)
            count_base = count_base.where(Customer.rfm_level == rfm_level)

        total_result = await self.db.execute(count_base)
        total = total_result.scalar() or 0

        offset = (page - 1) * size
        query = base.order_by(Customer.last_order_at.desc().nullslast()).offset(offset).limit(size)
        result = await self.db.execute(query)
        rows = result.scalars().all()

        items = [self._customer_to_dict(c) for c in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_customer(self, customer_id: str) -> Optional[dict]:
        """查询单个会员 360 度画像"""
        await self._set_tenant()

        result = await self.db.execute(
            select(Customer)
            .where(Customer.id == uuid.UUID(customer_id))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return None
        return self._customer_to_dict(customer)

    async def create_customer(self, data: dict) -> dict:
        """创建会员"""
        await self._set_tenant()

        customer = Customer(
            id=uuid.uuid4(),
            tenant_id=self._tenant_uuid,
            primary_phone=data["phone"],
            display_name=data.get("display_name"),
            gender=data.get("gender"),
            source=data.get("source", "manual"),
            tags=data.get("tags", []),
            rfm_level="S3",  # 新会员默认 S3
        )
        self.db.add(customer)
        await self.db.flush()
        return self._customer_to_dict(customer)

    # ─── RFM 分析 ───

    async def get_rfm_segments(self, store_id: str) -> dict:
        """获取 RFM 分层分布统计"""
        await self._set_tenant()

        result = await self.db.execute(
            select(
                Customer.rfm_level,
                func.count(Customer.id).label("count"),
            )
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
            .group_by(Customer.rfm_level)
        )
        rows = result.all()

        segments = {}
        total = 0
        for row in rows:
            level = row[0] or "S3"
            count = row[1]
            segments[level] = count
            total += count

        return {
            "segments": segments,
            "total": total,
        }

    async def get_at_risk(self, store_id: str, threshold: float = 0.5) -> list:
        """获取流失风险客户列表

        筛选条件：RFM level >= S4（低活跃），且最近消费距今天数超过 threshold 对应的天数。
        threshold=0.5 对应 rfm_recency_days >= 60。
        """
        await self._set_tenant()

        recency_threshold = int(threshold * 120)  # 0.5 -> 60 天

        result = await self.db.execute(
            select(Customer)
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
            .where(Customer.rfm_recency_days >= recency_threshold)
            .order_by(Customer.rfm_recency_days.desc())
            .limit(50)
        )
        rows = result.scalars().all()

        return [
            {
                "id": str(c.id),
                "display_name": c.display_name,
                "primary_phone": c.primary_phone,
                "rfm_level": c.rfm_level,
                "rfm_recency_days": c.rfm_recency_days,
                "last_order_at": c.last_order_at.isoformat() if c.last_order_at else None,
                "total_order_count": c.total_order_count,
                "total_order_amount_fen": c.total_order_amount_fen,
            }
            for c in rows
        ]

    # ─── 内部工具 ───

    @staticmethod
    def _to_isoformat(val: object) -> Optional[str]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.isoformat()
        return str(val)

    @staticmethod
    def _customer_to_dict(c: Customer) -> dict:
        return {
            "id": str(c.id),
            "primary_phone": c.primary_phone,
            "display_name": c.display_name,
            "gender": c.gender,
            "source": c.source,
            "rfm_level": c.rfm_level,
            "rfm_recency_days": c.rfm_recency_days,
            "rfm_frequency": c.rfm_frequency,
            "rfm_monetary_fen": c.rfm_monetary_fen,
            "total_order_count": c.total_order_count,
            "total_order_amount_fen": c.total_order_amount_fen,
            "first_order_at": c.first_order_at.isoformat() if c.first_order_at else None,
            "last_order_at": c.last_order_at.isoformat() if c.last_order_at else None,
            "tags": c.tags,
            "wechat_nickname": c.wechat_nickname,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }


# ─────────────────────────────────────────────────────────────────
# 企微 SCRM 绑定 Repository
# ─────────────────────────────────────────────────────────────────

class WecomRepository:
    """企微客户联系绑定操作 — 封装 wecom_* 字段的读写"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── bind_by_external_id ────────────────────────────────────

    async def bind_by_external_id(
        self,
        external_userid: str,
        follow_user: str,
        follow_at: datetime,
        remark: str = "",
        mobile: Optional[str] = None,
        unionid: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict:
        """绑定或创建 Customer（幂等）。

        优先级：
        1. wecom_external_userid 已存在 → 更新跟进信息，返回 action="bound_existing"
        2. unionid 查已有会员 → 绑定，返回 action="bound"
        3. mobile 查已有会员 → 绑定，返回 action="bound"
        4. 均未找到 → 创建临时档案，返回 action="created"
        """
        log = logger.bind(
            external_userid=external_userid,
            follow_user=follow_user,
            tenant_id=self.tenant_id,
        )
        await self._set_tenant()
        now = datetime.now(tz=timezone.utc)

        # Step 1：幂等检查 — external_userid 是否已绑定
        result = await self.db.execute(
            select(Customer)
            .where(Customer.wecom_external_userid == external_userid)
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        existing_by_external: Optional[Customer] = result.scalar_one_or_none()

        if existing_by_external:
            # 已绑定同一客户：更新跟进信息（幂等）
            existing_by_external.wecom_follow_user = follow_user
            existing_by_external.wecom_follow_at = follow_at
            existing_by_external.wecom_remark = remark
            existing_by_external.updated_at = now
            await self.db.flush()
            log.info("wecom_bind_updated_existing", customer_id=str(existing_by_external.id))
            return {
                "action": "bound_existing",
                "customer_id": str(existing_by_external.id),
                "is_new": False,
            }

        # Step 2：用 unionid 查已有会员
        existing: Optional[Customer] = None
        if unionid:
            r = await self.db.execute(
                select(Customer)
                .where(Customer.wechat_unionid == unionid)
                .where(Customer.tenant_id == self._tenant_uuid)
                .where(Customer.is_deleted == False)  # noqa: E712
                .where(Customer.is_merged == False)  # noqa: E712
            )
            existing = r.scalar_one_or_none()

        # Step 3：退而用 mobile 查
        if existing is None and mobile:
            r = await self.db.execute(
                select(Customer)
                .where(Customer.primary_phone == mobile)
                .where(Customer.tenant_id == self._tenant_uuid)
                .where(Customer.is_deleted == False)  # noqa: E712
                .where(Customer.is_merged == False)  # noqa: E712
            )
            existing = r.scalar_one_or_none()

        if existing is not None:
            # 找到已有会员 — 绑定企微信息
            existing.wecom_external_userid = external_userid
            existing.wecom_follow_user = follow_user
            existing.wecom_follow_at = follow_at
            existing.wecom_remark = remark
            existing.updated_at = now
            await self.db.flush()
            log.info("wecom_bind_linked", customer_id=str(existing.id))
            return {
                "action": "bound",
                "customer_id": str(existing.id),
                "is_new": False,
            }

        # Step 4：创建临时档案（source="wecom_only"）
        # primary_phone 字段有 NOT NULL 约束；无手机号时用 external_userid 占位（格式可识别）
        placeholder_phone = mobile if mobile else f"wecom_{external_userid}"
        new_customer = Customer(
            id=uuid.uuid4(),
            tenant_id=self._tenant_uuid,
            primary_phone=placeholder_phone,
            display_name=name if name else None,
            wechat_unionid=unionid if unionid else None,
            wecom_external_userid=external_userid,
            wecom_follow_user=follow_user,
            wecom_follow_at=follow_at,
            wecom_remark=remark,
            source="wecom_only",
            tags=[],
            rfm_level="S3",
        )
        self.db.add(new_customer)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            log.warning(
                "wecom_bind_create_integrity_error",
                error=str(exc.orig),
                external_userid=external_userid,
            )
            raise

        log.info("wecom_bind_created_temp", customer_id=str(new_customer.id))
        return {
            "action": "created",
            "customer_id": str(new_customer.id),
            "is_new": True,
        }

    # ─── unbind_by_external_id ──────────────────────────────────

    async def unbind_by_external_id(self, external_userid: str) -> dict:
        """清空企微绑定，追加"已删除好友"标签（幂等）。

        若已解绑（找不到该 external_userid），直接返回 not_found。
        """
        log = logger.bind(external_userid=external_userid, tenant_id=self.tenant_id)
        await self._set_tenant()
        now = datetime.now(tz=timezone.utc)

        result = await self.db.execute(
            select(Customer)
            .where(Customer.wecom_external_userid == external_userid)
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        customer: Optional[Customer] = result.scalar_one_or_none()

        if customer is None:
            log.info("wecom_unbind_not_found")
            return {"action": "not_found", "customer_id": None}

        # 清空企微绑定字段
        customer.wecom_external_userid = None
        customer.wecom_follow_user = None
        customer.wecom_follow_at = None
        customer.updated_at = now

        # 追加"已删除好友"标签（Python 层处理 JSONB，避免方言差异）
        tags: list = list(customer.tags) if customer.tags else []
        deleted_tag = "已删除好友"
        if deleted_tag not in tags:
            tags.append(deleted_tag)
        customer.tags = tags

        await self.db.flush()
        log.info("wecom_unbound_ok", customer_id=str(customer.id))
        return {"action": "unbound", "customer_id": str(customer.id)}

    # ─── batch_by_external_ids ──────────────────────────────────

    async def batch_by_external_ids(self, external_userids: list[str]) -> list[dict]:
        """批量查询 external_userid 对应的会员摘要（最多 100 个）。

        结果列表与输入顺序对齐；未找到的 external_userid 标记 found=False。
        """
        log = logger.bind(count=len(external_userids), tenant_id=self.tenant_id)
        await self._set_tenant()

        if not external_userids:
            return []

        # 限制最大 100 个，防止超大查询
        query_ids = external_userids[:100]

        result = await self.db.execute(
            select(
                Customer.id,
                Customer.wecom_external_userid,
                Customer.display_name,
                Customer.rfm_level,
                Customer.last_order_at,
                Customer.total_order_amount_fen,
                Customer.risk_score,
            )
            .where(Customer.wecom_external_userid.in_(query_ids))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        rows = result.all()

        # 构建 external_userid → row 的映射
        found_map: dict[str, object] = {
            row.wecom_external_userid: row for row in rows
        }

        items: list[dict] = []
        for eid in query_ids:
            row = found_map.get(eid)
            if row is None:
                items.append({"external_userid": eid, "found": False})
            else:
                items.append({
                    "external_userid": eid,
                    "found": True,
                    "customer_id": str(row.id),
                    "display_name": row.display_name,
                    "rfm_level": row.rfm_level,
                    "total_order_amount_fen": row.total_order_amount_fen,
                    "last_order_at": (
                        row.last_order_at.isoformat() if row.last_order_at else None
                    ),
                    "risk_score": row.risk_score,
                })

        log.info("wecom_batch_query_ok", found=len(found_map), total=len(query_ids))
        return items

    # ─── get_wecom_binding ──────────────────────────────────────

    async def get_wecom_binding(self, customer_id: str) -> Optional[dict]:
        """查询单个会员的企微绑定状态。

        返回 None 表示 customer 不存在。
        """
        await self._set_tenant()

        result = await self.db.execute(
            select(
                Customer.id,
                Customer.wecom_external_userid,
                Customer.wecom_follow_user,
                Customer.wecom_follow_at,
                Customer.wecom_remark,
            )
            .where(Customer.id == uuid.UUID(customer_id))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        row = result.one_or_none()
        if row is None:
            return None

        return {
            "customer_id": customer_id,
            "is_bound": row.wecom_external_userid is not None,
            "external_userid": row.wecom_external_userid,
            "follow_user": row.wecom_follow_user,
            "follow_at": (
                row.wecom_follow_at.isoformat() if row.wecom_follow_at else None
            ),
            "remark": row.wecom_remark,
        }

    # ─── update_wecom_binding ───────────────────────────────────

    async def update_wecom_binding(
        self,
        customer_id: str,
        follow_user: Optional[str],
        remark: Optional[str],
    ) -> Optional[dict]:
        """部分更新会员的企微绑定信息（只允许更新 follow_user / remark）。

        返回 None 表示 customer 不存在。
        """
        log = logger.bind(customer_id=customer_id, tenant_id=self.tenant_id)
        await self._set_tenant()
        now = datetime.now(tz=timezone.utc)

        # 先查，确认存在且属于该租户
        result = await self.db.execute(
            select(Customer)
            .where(Customer.id == uuid.UUID(customer_id))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        customer: Optional[Customer] = result.scalar_one_or_none()
        if customer is None:
            return None

        # 只更新非 None 的字段（支持 PATCH 语义）
        if follow_user is not None:
            customer.wecom_follow_user = follow_user
        if remark is not None:
            customer.wecom_remark = remark
        customer.updated_at = now

        await self.db.flush()
        log.info("wecom_binding_updated")
        return {
            "customer_id": customer_id,
            "wecom_follow_user": customer.wecom_follow_user,
            "wecom_remark": customer.wecom_remark,
            "updated_at": now.isoformat(),
        }
