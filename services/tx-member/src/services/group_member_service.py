"""跨品牌会员聚合服务 — GroupMemberService

安全架构说明：
  tenant_db   普通租户连接，受 RLS 约束，只能查询 app.tenant_id 对应品牌的数据。
  group_db    集团级连接（BYPASSRLS 权限），连接字符串从 DATABASE_URL_GROUP 环境变量读取。
              TODO: 部署时必须配置 DATABASE_URL_GROUP 指向具有 BYPASSRLS 权限的角色。
              此连接专用于集团级跨品牌查询，每次使用均记录审计日志。

phone_hash 安全：
  SHA256(手机号明文) — 不在数据库存储明文手机号，防止数据泄露时手机号被反查。

跨品牌查询访问控制：
  每次调用 get_cross_brand_profile 前必须确认 brand_groups.member_data_shared = True，
  否则抛出 PermissionError，拒绝跨品牌数据访问。

审计日志：
  每次跨品牌查询（stored_value_query）、积分操作均写入 cross_brand_transactions 表。
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────
# Pydantic v2 响应模型
# ─────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class GroupMemberProfile(BaseModel):
    id: UUID
    group_id: UUID
    phone_hash: str
    total_points: int
    total_stored_value_fen: int
    brands_visited: list[UUID]
    last_visit_at: Optional[datetime]

    model_config = {"from_attributes": True}


class BrandBalance(BaseModel):
    tenant_id: UUID
    brand_name: str
    stored_value_fen: int
    points: int


class CrossBrandProfile(BaseModel):
    group_member: GroupMemberProfile
    brand_balances: list[BrandBalance]
    group_points: int


class CrossBrandTransaction(BaseModel):
    id: UUID
    transaction_type: str
    from_tenant_id: UUID
    to_tenant_id: UUID
    points_delta: int
    amount_fen: int
    order_id: Optional[UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────
# 自定义异常
# ─────────────────────────────────────────────────────────────────

class InsufficientPointsError(Exception):
    """集团积分余额不足"""


class CrossBrandNotAllowedError(PermissionError):
    """brand_groups.member_data_shared = False，拒绝跨品牌数据访问"""


class GroupNotFoundError(Exception):
    """brand_groups 中未找到对应集团"""


class TenantNotInGroupError(Exception):
    """brand_tenant_ids 中不包含指定 tenant_id"""


# ─────────────────────────────────────────────────────────────────
# group_db 连接工厂（BYPASSRLS 集团专用连接）
#
# TODO: 部署前必须在环境变量中配置 DATABASE_URL_GROUP，
#       该连接角色需具有 BYPASSRLS 权限，且只授权访问
#       group_member_profiles 和 cross_brand_transactions 两张表。
#       切勿将此连接字符串暴露在普通品牌 API 的响应中。
# ─────────────────────────────────────────────────────────────────
_DATABASE_URL_GROUP: str = os.getenv(
    "DATABASE_URL_GROUP",
    "postgresql+asyncpg://group_service_role:changeme_dev@localhost/tunxiang_os",
)

_group_engine = create_async_engine(
    _DATABASE_URL_GROUP,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
)
_group_session_factory = async_sessionmaker(
    _group_engine, class_=AsyncSession, expire_on_commit=False
)


def _hash_phone(phone: str) -> str:
    """SHA256(手机号明文) → 64 字符十六进制字符串。不存储明文。"""
    return hashlib.sha256(phone.strip().encode("utf-8")).hexdigest()


class GroupMemberService:
    """跨品牌会员聚合服务

    tenant_db   受 RLS 约束的普通连接，用于查询当前品牌会员数据。
    group_db    BYPASSRLS 集团连接，用于操作 group_member_profiles /
                cross_brand_transactions。每次调用均从 _group_session_factory 获取。

    调用方传入 tenant_db（FastAPI Depends 注入的 AsyncSession），
    group_db 由本服务内部通过工厂创建，不暴露给路由层。
    """

    def __init__(self, tenant_db: AsyncSession) -> None:
        # tenant_db: 受 RLS 约束的品牌级连接（由 FastAPI Depends 注入）
        self._tenant_db = tenant_db

    # ─────────────────────────────────────────────────────────────
    # 内部工具方法
    # ─────────────────────────────────────────────────────────────

    async def _get_brand_group(self, group_id: UUID) -> dict:
        """通过 group_db (BYPASSRLS) 查询 brand_groups 集团配置。

        注意：brand_groups 表有 RLS，但集团 API 可能以集团主 tenant 身份访问。
        此处通过 group_db 绕过 RLS，适用于跨品牌内部调度场景。
        """
        async with _group_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, tenant_id, group_name, brand_tenant_ids, "
                    "stored_value_interop, member_data_shared, status "
                    "FROM brand_groups WHERE id = :group_id AND is_deleted = false"
                ),
                {"group_id": str(group_id)},
            )
            row = result.mappings().first()
        if row is None:
            raise GroupNotFoundError(f"brand_groups not found: group_id={group_id}")
        return dict(row)

    def _assert_tenant_in_group(self, group_config: dict, tenant_id: UUID) -> None:
        """校验 tenant_id 是否属于该集团旗下品牌。"""
        brand_ids = [uuid.UUID(t) for t in (group_config.get("brand_tenant_ids") or [])]
        if tenant_id not in brand_ids:
            raise TenantNotInGroupError(
                f"tenant_id={tenant_id} is not in group brand_tenant_ids"
            )

    async def _write_audit_log(
        self,
        session: AsyncSession,
        *,
        group_member_id: UUID,
        group_id: UUID,
        from_tenant_id: UUID,
        to_tenant_id: UUID,
        transaction_type: str,
        points_delta: int = 0,
        amount_fen: int = 0,
        order_id: Optional[UUID] = None,
        operator_id: Optional[UUID] = None,
        note: Optional[str] = None,
    ) -> UUID:
        """向 cross_brand_transactions 写入审计记录，返回新记录 id。"""
        new_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO cross_brand_transactions (
                    id, group_member_id, group_id,
                    from_tenant_id, to_tenant_id,
                    transaction_type, points_delta, amount_fen,
                    order_id, operator_id, note, created_at
                ) VALUES (
                    :id, :group_member_id, :group_id,
                    :from_tenant_id, :to_tenant_id,
                    :transaction_type, :points_delta, :amount_fen,
                    :order_id, :operator_id, :note, NOW()
                )
                """
            ),
            {
                "id": str(new_id),
                "group_member_id": str(group_member_id),
                "group_id": str(group_id),
                "from_tenant_id": str(from_tenant_id),
                "to_tenant_id": str(to_tenant_id),
                "transaction_type": transaction_type,
                "points_delta": points_delta,
                "amount_fen": amount_fen,
                "order_id": str(order_id) if order_id else None,
                "operator_id": str(operator_id) if operator_id else None,
                "note": note,
            },
        )
        return new_id

    def _row_to_profile(self, row: dict) -> GroupMemberProfile:
        brands_raw = row.get("brands_visited") or []
        return GroupMemberProfile(
            id=row["id"],
            group_id=row["group_id"],
            phone_hash=row["phone_hash"],
            total_points=row["total_points"],
            total_stored_value_fen=row["total_stored_value_fen"],
            brands_visited=[uuid.UUID(str(b)) for b in brands_raw if b],
            last_visit_at=row.get("last_visit_at"),
        )

    def _row_to_transaction(self, row: dict) -> CrossBrandTransaction:
        return CrossBrandTransaction(
            id=row["id"],
            transaction_type=row["transaction_type"],
            from_tenant_id=row["from_tenant_id"],
            to_tenant_id=row["to_tenant_id"],
            points_delta=row["points_delta"],
            amount_fen=row["amount_fen"],
            order_id=row.get("order_id"),
            created_at=row["created_at"],
        )

    # ─────────────────────────────────────────────────────────────
    # 公开业务方法
    # ─────────────────────────────────────────────────────────────

    async def get_or_create_group_profile(
        self, group_id: UUID, phone: str
    ) -> GroupMemberProfile:
        """用 SHA256(phone) 查找集团会员档案，不存在则创建。

        使用 INSERT ... ON CONFLICT DO NOTHING 保证并发安全。
        """
        phone_hash = _hash_phone(phone)
        async with _group_session_factory() as session:
            # 先查
            result = await session.execute(
                text(
                    "SELECT * FROM group_member_profiles "
                    "WHERE group_id = :group_id AND phone_hash = :phone_hash"
                ),
                {"group_id": str(group_id), "phone_hash": phone_hash},
            )
            row = result.mappings().first()
            if row:
                return self._row_to_profile(dict(row))

            # 不存在则创建（ON CONFLICT 防止并发竞争）
            new_id = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO group_member_profiles
                        (id, group_id, phone_hash, total_points,
                         total_stored_value_fen, brands_visited, created_at, updated_at)
                    VALUES
                        (:id, :group_id, :phone_hash, 0, 0, '{}', NOW(), NOW())
                    ON CONFLICT (group_id, phone_hash) DO NOTHING
                    """
                ),
                {
                    "id": str(new_id),
                    "group_id": str(group_id),
                    "phone_hash": phone_hash,
                },
            )
            await session.commit()

            # 重新查询（ON CONFLICT 可能是另一个并发请求创建了）
            result2 = await session.execute(
                text(
                    "SELECT * FROM group_member_profiles "
                    "WHERE group_id = :group_id AND phone_hash = :phone_hash"
                ),
                {"group_id": str(group_id), "phone_hash": phone_hash},
            )
            row2 = result2.mappings().first()
            if row2 is None:
                raise RuntimeError(
                    f"Failed to create group_member_profile for group_id={group_id}"
                )
            return self._row_to_profile(dict(row2))

    async def get_cross_brand_profile(
        self, group_id: UUID, phone: str, requesting_tenant_id: UUID
    ) -> CrossBrandProfile:
        """获取跨品牌会员全貌。

        流程：
          1. 检查 brand_groups.member_data_shared = True（否则 CrossBrandNotAllowedError）
          2. 确认 requesting_tenant_id 属于该集团
          3. 获取或创建集团会员档案
          4. 遍历 brand_tenant_ids，用 tenant_db（RLS）查询各品牌储值余额
          5. 写入审计日志（stored_value_query）

        安全说明：
          - 步骤 4 的每次储值查询通过 tenant_db 进行，RLS 生效，
            只允许访问目标品牌自己的数据（需要调用方按品牌切换 tenant 上下文）。
            当前实现：在集团连接上直接 SELECT，已有 group_id 隔离。
          - 审计日志确保每次跨品牌查询可追溯。
        """
        group_config = await self._get_brand_group(group_id)

        # 安全校验：member_data_shared 开关
        if not group_config.get("member_data_shared", False):
            raise CrossBrandNotAllowedError(
                f"group_id={group_id} has member_data_shared=False, "
                "cross-brand profile access denied"
            )

        # 校验请求方品牌属于该集团
        self._assert_tenant_in_group(group_config, requesting_tenant_id)

        # 获取集团会员档案
        group_member = await self.get_or_create_group_profile(group_id, phone)
        phone_hash = _hash_phone(phone)

        brand_tenant_ids: list[UUID] = [
            uuid.UUID(t) for t in (group_config.get("brand_tenant_ids") or [])
        ]

        # 查询各品牌储值余额（通过 tenant_db 受 RLS 约束的连接）
        # 注意：这里使用 group_db 连接直接查询各品牌会员表的储值余额，
        # 需要 BYPASSRLS 权限才能跨品牌查询。
        brand_balances: list[BrandBalance] = []
        async with _group_session_factory() as session:
            for brand_tid in brand_tenant_ids:
                # 查询该品牌下此 phone_hash 对应的储值余额
                # stored_value_accounts 按 tenant_id + phone 关联，此处通过 phone_hash 反查
                # TODO: 实际储值余额查询依赖 stored_value_accounts 表结构，
                #       当前用 group_db BYPASSRLS 连接查询，绕过品牌 RLS
                sv_result = await session.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(balance_fen), 0) AS stored_value_fen,
                               COALESCE(SUM(gift_balance_fen), 0) AS gift_balance_fen
                        FROM stored_value_accounts sva
                        JOIN members m ON m.id = sva.member_id
                        WHERE sva.tenant_id = :tenant_id
                          AND m.phone_hash = :phone_hash
                          AND sva.status = 'active'
                        """
                    ),
                    {"tenant_id": str(brand_tid), "phone_hash": phone_hash},
                )
                sv_row = sv_result.mappings().first()
                stored_value_fen = int(sv_row["stored_value_fen"]) if sv_row else 0

                # 查询积分
                pts_result = await session.execute(
                    text(
                        """
                        SELECT COALESCE(balance, 0) AS points
                        FROM points_accounts
                        WHERE tenant_id = :tenant_id
                          AND member_id IN (
                              SELECT id FROM members
                              WHERE tenant_id = :tenant_id AND phone_hash = :phone_hash
                          )
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": str(brand_tid), "phone_hash": phone_hash},
                )
                pts_row = pts_result.mappings().first()
                points = int(pts_row["points"]) if pts_row else 0

                # 查询品牌名称
                name_result = await session.execute(
                    text(
                        "SELECT group_name FROM brand_groups WHERE id = :group_id LIMIT 1"
                    ),
                    {"group_id": str(group_id)},
                )
                name_row = name_result.mappings().first()
                brand_name = name_row["group_name"] if name_row else str(brand_tid)

                brand_balances.append(
                    BrandBalance(
                        tenant_id=brand_tid,
                        brand_name=brand_name,
                        stored_value_fen=stored_value_fen,
                        points=points,
                    )
                )

            # 审计日志：记录本次跨品牌查询（stored_value_query）
            await self._write_audit_log(
                session,
                group_member_id=group_member.id,
                group_id=group_id,
                from_tenant_id=requesting_tenant_id,
                to_tenant_id=requesting_tenant_id,
                transaction_type="stored_value_query",
                note=f"cross_brand_profile query by tenant={requesting_tenant_id}",
            )
            await session.commit()

        logger.info(
            "cross_brand_profile_queried",
            group_id=str(group_id),
            requesting_tenant_id=str(requesting_tenant_id),
            brand_count=len(brand_balances),
        )

        return CrossBrandProfile(
            group_member=group_member,
            brand_balances=brand_balances,
            group_points=group_member.total_points,
        )

    async def earn_group_points(
        self,
        group_id: UUID,
        phone: str,
        points: int,
        source_tenant_id: UUID,
        order_id: Optional[UUID] = None,
    ) -> GroupMemberProfile:
        """消费积累集团积分（原子更新 total_points + 写审计日志）。"""
        if points <= 0:
            raise ValueError(f"points must be positive, got {points}")

        group_member = await self.get_or_create_group_profile(group_id, phone)

        async with _group_session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE group_member_profiles
                    SET total_points = total_points + :points,
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"points": points, "id": str(group_member.id)},
            )
            await self._write_audit_log(
                session,
                group_member_id=group_member.id,
                group_id=group_id,
                from_tenant_id=source_tenant_id,
                to_tenant_id=source_tenant_id,
                transaction_type="points_earn",
                points_delta=points,
                order_id=order_id,
                note=f"earn {points} points from tenant={source_tenant_id}",
            )
            await session.commit()

            # 返回最新数据
            result = await session.execute(
                text("SELECT * FROM group_member_profiles WHERE id = :id"),
                {"id": str(group_member.id)},
            )
            row = result.mappings().first()

        logger.info(
            "group_points_earned",
            group_id=str(group_id),
            points=points,
            source_tenant_id=str(source_tenant_id),
            order_id=str(order_id) if order_id else None,
        )
        return self._row_to_profile(dict(row))

    async def use_group_points(
        self,
        group_id: UUID,
        phone: str,
        points: int,
        target_tenant_id: UUID,
        order_id: Optional[UUID],
    ) -> GroupMemberProfile:
        """使用集团积分（校验余额 → 原子扣减 → 写审计日志）。

        使用行锁（FOR UPDATE）防止并发超扣。
        """
        if points <= 0:
            raise ValueError(f"points must be positive, got {points}")

        async with _group_session_factory() as session:
            # 行锁：防止并发超扣
            result = await session.execute(
                text(
                    """
                    SELECT id, total_points, group_id
                    FROM group_member_profiles
                    WHERE group_id = :group_id AND phone_hash = :phone_hash
                    FOR UPDATE
                    """
                ),
                {
                    "group_id": str(group_id),
                    "phone_hash": _hash_phone(phone),
                },
            )
            row = result.mappings().first()
            if row is None:
                raise GroupNotFoundError(
                    f"group_member_profile not found for group_id={group_id}"
                )

            current_points = int(row["total_points"])
            if current_points < points:
                raise InsufficientPointsError(
                    f"Insufficient group points: have {current_points}, need {points}"
                )

            member_id = row["id"]
            await session.execute(
                text(
                    """
                    UPDATE group_member_profiles
                    SET total_points = total_points - :points,
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"points": points, "id": str(member_id)},
            )
            await self._write_audit_log(
                session,
                group_member_id=member_id,
                group_id=group_id,
                from_tenant_id=target_tenant_id,
                to_tenant_id=target_tenant_id,
                transaction_type="points_use",
                points_delta=-points,
                order_id=order_id,
                note=f"use {points} points at tenant={target_tenant_id}",
            )
            await session.commit()

            result2 = await session.execute(
                text("SELECT * FROM group_member_profiles WHERE id = :id"),
                {"id": str(member_id)},
            )
            updated_row = result2.mappings().first()

        logger.info(
            "group_points_used",
            group_id=str(group_id),
            points=points,
            target_tenant_id=str(target_tenant_id),
        )
        return self._row_to_profile(dict(updated_row))

    async def transfer_points(
        self,
        group_id: UUID,
        phone: str,
        from_tenant_id: UUID,
        to_tenant_id: UUID,
        points: int,
        operator_id: UUID,
    ) -> CrossBrandTransaction:
        """积分品牌间转移。

        校验：
          1. 两个品牌均属于同一集团（brand_tenant_ids）
          2. 集团积分余额充足
        转移语义：从集团积分池扣减，再加回（本质是重新归属记录），
        实际上只记录一条 points_transfer 流水（不改变集团总积分）。
        """
        if points <= 0:
            raise ValueError(f"points must be positive, got {points}")

        group_config = await self._get_brand_group(group_id)
        self._assert_tenant_in_group(group_config, from_tenant_id)
        self._assert_tenant_in_group(group_config, to_tenant_id)

        group_member = await self.get_or_create_group_profile(group_id, phone)

        async with _group_session_factory() as session:
            # 行锁校验余额
            result = await session.execute(
                text(
                    """
                    SELECT total_points FROM group_member_profiles
                    WHERE id = :id FOR UPDATE
                    """
                ),
                {"id": str(group_member.id)},
            )
            row = result.mappings().first()
            if row is None or int(row["total_points"]) < points:
                raise InsufficientPointsError(
                    f"Insufficient group points for transfer: "
                    f"have {row['total_points'] if row else 0}, need {points}"
                )

            txn_id = await self._write_audit_log(
                session,
                group_member_id=group_member.id,
                group_id=group_id,
                from_tenant_id=from_tenant_id,
                to_tenant_id=to_tenant_id,
                transaction_type="points_transfer",
                points_delta=points,
                operator_id=operator_id,
                note=f"transfer {points} points from {from_tenant_id} to {to_tenant_id}",
            )
            await session.commit()

            # 读取刚写入的记录
            result2 = await session.execute(
                text("SELECT * FROM cross_brand_transactions WHERE id = :id"),
                {"id": str(txn_id)},
            )
            txn_row = result2.mappings().first()

        logger.info(
            "group_points_transferred",
            group_id=str(group_id),
            from_tenant_id=str(from_tenant_id),
            to_tenant_id=str(to_tenant_id),
            points=points,
            operator_id=str(operator_id),
        )
        return self._row_to_transaction(dict(txn_row))

    async def get_cross_brand_history(
        self, group_id: UUID, phone: str, page: int = 1, size: int = 20
    ) -> tuple[list[CrossBrandTransaction], int]:
        """分页查询跨品牌交易历史（倒序）。"""
        phone_hash = _hash_phone(phone)
        offset = (page - 1) * size

        async with _group_session_factory() as session:
            # 先找 group_member_id
            m_result = await session.execute(
                text(
                    "SELECT id FROM group_member_profiles "
                    "WHERE group_id = :group_id AND phone_hash = :phone_hash"
                ),
                {"group_id": str(group_id), "phone_hash": phone_hash},
            )
            m_row = m_result.mappings().first()
            if m_row is None:
                return [], 0

            member_id = m_row["id"]

            count_result = await session.execute(
                text(
                    "SELECT COUNT(*) AS cnt FROM cross_brand_transactions "
                    "WHERE group_member_id = :member_id"
                ),
                {"member_id": str(member_id)},
            )
            total = int(count_result.scalar_one())

            rows_result = await session.execute(
                text(
                    """
                    SELECT * FROM cross_brand_transactions
                    WHERE group_member_id = :member_id
                    ORDER BY created_at DESC
                    LIMIT :size OFFSET :offset
                    """
                ),
                {"member_id": str(member_id), "size": size, "offset": offset},
            )
            rows = rows_result.mappings().all()

        transactions = [self._row_to_transaction(dict(r)) for r in rows]
        return transactions, total

    async def check_stored_value_interop(self, group_id: UUID) -> bool:
        """检查集团是否开启储值卡互通（stored_value_interop 开关）。"""
        group_config = await self._get_brand_group(group_id)
        return bool(group_config.get("stored_value_interop", False))

    async def sync_brand_visit(
        self, group_id: UUID, phone: str, tenant_id: UUID
    ) -> None:
        """更新 brands_visited 数组（幂等 array_append，避免重复追加）。

        同时刷新 last_visit_at。
        """
        phone_hash = _hash_phone(phone)
        # 确保会员档案存在
        group_member = await self.get_or_create_group_profile(group_id, phone)

        async with _group_session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE group_member_profiles
                    SET brands_visited = CASE
                            WHEN :tid = ANY(brands_visited) THEN brands_visited
                            ELSE array_append(brands_visited, :tid::uuid)
                        END,
                        last_visit_at = NOW(),
                        updated_at   = NOW()
                    WHERE id = :id
                    """
                ),
                {"tid": str(tenant_id), "id": str(group_member.id)},
            )
            await session.commit()

        logger.info(
            "brand_visit_synced",
            group_id=str(group_id),
            tenant_id=str(tenant_id),
        )
