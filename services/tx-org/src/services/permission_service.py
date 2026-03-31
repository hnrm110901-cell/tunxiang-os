"""权限校验服务 — 10级角色体系

职责：
  - 查询员工当前角色配置（含10级限制字段）
  - 按操作类型校验是否在权限范围内
  - 超限时判断是否可走审批流
  - 写入权限检查日志（合规留痕）

架构：PermissionService → PermissionRepository → DB
金额全部以「分」为单位，折扣率以「百分比」表示（如 85.0 = 85折 = 打八五折）。

注意：
  - max_discount_rate = 0.0 表示管理员无限制（level=10）
  - 折扣 discount_rate < role.max_discount_rate 表示「想打更低的折扣」= 超权限
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据类
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass(frozen=True)
class RoleSnapshot:
    """员工当前有效角色的权限快照（只读）"""
    role_config_id: UUID
    role_name: str
    level: int
    max_discount_rate: float       # 最低折扣率(%) — 低于此值需审批/拒绝
    max_wipeoff_fen: int           # 抹零上限(分)
    max_gift_fen: int              # 赠送上限(分)
    data_query_days: int           # 可查询历史天数
    can_void_order: bool
    can_modify_price: bool
    can_override_discount: bool    # 可申请审批突破折扣下限


@dataclass(frozen=True)
class PermissionCheckResult:
    """权限检查结果"""
    allowed: bool
    require_approval: bool = False
    approver_min_level: int = 0    # 需要最低几级审批人，0=无需审批
    message: str = ""

    @classmethod
    def permit(cls) -> "PermissionCheckResult":
        return cls(allowed=True, message="允许")

    @classmethod
    def deny(cls, reason: str) -> "PermissionCheckResult":
        return cls(allowed=False, require_approval=False, message=reason)

    @classmethod
    def need_approval(cls, approver_min_level: int, reason: str) -> "PermissionCheckResult":
        return cls(
            allowed=False,
            require_approval=True,
            approver_min_level=approver_min_level,
            message=reason,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Repository（DB访问层）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PermissionRepository:
    """权限相关DB操作"""

    async def get_employee_role_snapshot(
        self,
        employee_id: UUID,
        tenant_id: UUID,
        store_id: Optional[UUID],
        session: AsyncSession,
    ) -> Optional[RoleSnapshot]:
        """查询员工当前生效的角色快照。

        查询优先级：门店级角色 > 全品牌角色（store_id IS NULL）。
        若两个都有，取 store_id 精确匹配的。
        """
        # 先精确匹配门店，再回退到全品牌
        sql = text("""
            SELECT
                rc.id                   AS role_config_id,
                rc.role_name,
                rc.level,
                rc.max_discount_rate,
                rc.max_wipeoff_fen,
                rc.max_gift_fen_v2      AS max_gift_fen,
                rc.data_query_days,
                rc.can_void_order,
                rc.can_modify_price,
                rc.can_override_discount
            FROM employee_role_assignments era
            JOIN role_configs rc
                ON rc.id = era.role_config_id
               AND rc.is_deleted = FALSE
            WHERE era.tenant_id    = :tenant_id
              AND era.employee_id  = :employee_id
              AND era.is_active    = TRUE
              AND (era.expires_at IS NULL OR era.expires_at > NOW())
              AND (
                  era.store_id = :store_id
                  OR era.store_id IS NULL
              )
            ORDER BY
                CASE WHEN era.store_id = :store_id THEN 0 ELSE 1 END ASC
            LIMIT 1
        """)
        result = await session.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "employee_id": str(employee_id),
                "store_id": str(store_id) if store_id else None,
            },
        )
        row = result.mappings().first()
        if row is None:
            return None

        return RoleSnapshot(
            role_config_id=UUID(str(row["role_config_id"])),
            role_name=row["role_name"],
            level=row["level"],
            max_discount_rate=float(row["max_discount_rate"]),
            max_wipeoff_fen=int(row["max_wipeoff_fen"]),
            max_gift_fen=int(row["max_gift_fen"]),
            data_query_days=int(row["data_query_days"]),
            can_void_order=bool(row["can_void_order"]),
            can_modify_price=bool(row["can_modify_price"]),
            can_override_discount=bool(row["can_override_discount"]),
        )

    async def write_check_log(
        self,
        *,
        tenant_id: UUID,
        employee_id: UUID,
        store_id: Optional[UUID],
        operation: str,
        amount_fen: Optional[int],
        role_level: Optional[int],
        result: PermissionCheckResult,
        order_id: Optional[UUID],
        request_ip: Optional[str],
        session: AsyncSession,
    ) -> None:
        """写入权限检查日志（不阻断主流程，失败仅警告）"""
        sql = text("""
            INSERT INTO permission_check_logs
                (id, tenant_id, employee_id, store_id, operation, amount_fen,
                 role_level, allowed, require_approval, approver_min_level,
                 deny_reason, order_id, request_ip)
            VALUES
                (:id, :tenant_id, :employee_id, :store_id, :operation, :amount_fen,
                 :role_level, :allowed, :require_approval, :approver_min_level,
                 :deny_reason, :order_id, :request_ip)
        """)
        await session.execute(sql, {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "employee_id": str(employee_id),
            "store_id": str(store_id) if store_id else None,
            "operation": operation,
            "amount_fen": amount_fen,
            "role_level": role_level,
            "allowed": result.allowed,
            "require_approval": result.require_approval,
            "approver_min_level": result.approver_min_level if result.approver_min_level else None,
            "deny_reason": result.message if not result.allowed else None,
            "order_id": str(order_id) if order_id else None,
            "request_ip": request_ip,
        })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Service（业务逻辑层）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PermissionService:
    """10级角色权限校验服务

    所有 check_* 方法：
      1. 查询员工角色快照
      2. 执行业务规则判断
      3. 写入审计日志
      4. 返回 PermissionCheckResult

    调用方负责根据 result.allowed 决定是否继续。
    """

    def __init__(self) -> None:
        self._repo = PermissionRepository()

    async def _get_role_or_deny(
        self,
        employee_id: UUID,
        tenant_id: UUID,
        store_id: Optional[UUID],
        session: AsyncSession,
    ) -> tuple[Optional[RoleSnapshot], Optional[PermissionCheckResult]]:
        """查询角色快照，找不到时返回拒绝结果"""
        role = await self._repo.get_employee_role_snapshot(
            employee_id, tenant_id, store_id, session
        )
        if role is None:
            result = PermissionCheckResult.deny("员工未分配角色，操作被拒绝")
            return None, result
        return role, None

    async def check_discount_permission(
        self,
        employee_id: UUID,
        discount_rate: float,       # 0-100，如 85.0 = 打85折
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """检查员工是否有权执行该折扣率。

        规则：
          - level=10（管理员）且 max_discount_rate=0.0 → 无限制，直接允许
          - discount_rate >= role.max_discount_rate → 允许（折扣不超权）
          - discount_rate < role.max_discount_rate  → 超权
            - can_override_discount=True → 需审批（approver_min_level = role.level + 2）
            - can_override_discount=False → 直接拒绝
        """
        role, early_deny = await self._get_role_or_deny(
            employee_id, tenant_id, store_id, session
        )
        if early_deny is not None:
            await self._log(
                tenant_id, employee_id, store_id, "discount",
                int(discount_rate * 100), None, early_deny, order_id, request_ip, session,
            )
            return early_deny

        # 管理员无限制
        if role.level >= 10 or role.max_discount_rate == 0.0:
            result = PermissionCheckResult.permit()
        elif discount_rate >= role.max_discount_rate:
            result = PermissionCheckResult.permit()
        elif role.can_override_discount:
            approver_level = min(role.level + 2, 10)
            result = PermissionCheckResult.need_approval(
                approver_min_level=approver_level,
                reason=f"折扣率 {discount_rate}% 低于本角色最低权限 {role.max_discount_rate}%，需 Level {approver_level}+ 审批",
            )
        else:
            result = PermissionCheckResult.deny(
                f"折扣率 {discount_rate}% 低于本角色权限下限 {role.max_discount_rate}%，且无超额申请权限"
            )

        await self._log(
            tenant_id, employee_id, store_id, "discount",
            int(discount_rate * 100), role.level, result, order_id, request_ip, session,
        )
        logger.info(
            "permission_check_discount",
            employee_id=str(employee_id),
            discount_rate=discount_rate,
            role_level=role.level,
            allowed=result.allowed,
            require_approval=result.require_approval,
        )
        return result

    async def check_wipeoff_permission(
        self,
        employee_id: UUID,
        amount_fen: int,
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """检查抹零权限。

        规则：amount_fen <= role.max_wipeoff_fen → 允许
        """
        role, early_deny = await self._get_role_or_deny(
            employee_id, tenant_id, store_id, session
        )
        if early_deny is not None:
            await self._log(
                tenant_id, employee_id, store_id, "wipeoff",
                amount_fen, None, early_deny, order_id, request_ip, session,
            )
            return early_deny

        if role.level >= 10:
            result = PermissionCheckResult.permit()
        elif amount_fen <= role.max_wipeoff_fen:
            result = PermissionCheckResult.permit()
        else:
            result = PermissionCheckResult.deny(
                f"抹零金额 {amount_fen} 分超过本角色上限 {role.max_wipeoff_fen} 分"
            )

        await self._log(
            tenant_id, employee_id, store_id, "wipeoff",
            amount_fen, role.level, result, order_id, request_ip, session,
        )
        logger.info(
            "permission_check_wipeoff",
            employee_id=str(employee_id),
            amount_fen=amount_fen,
            role_level=role.level,
            allowed=result.allowed,
        )
        return result

    async def check_gift_permission(
        self,
        employee_id: UUID,
        amount_fen: int,
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """检查赠送权限。

        规则：amount_fen <= role.max_gift_fen → 允许
        """
        role, early_deny = await self._get_role_or_deny(
            employee_id, tenant_id, store_id, session
        )
        if early_deny is not None:
            await self._log(
                tenant_id, employee_id, store_id, "gift",
                amount_fen, None, early_deny, order_id, request_ip, session,
            )
            return early_deny

        if role.level >= 10:
            result = PermissionCheckResult.permit()
        elif role.max_gift_fen == 0:
            result = PermissionCheckResult.deny("本角色无赠送权限")
        elif amount_fen <= role.max_gift_fen:
            result = PermissionCheckResult.permit()
        else:
            result = PermissionCheckResult.deny(
                f"赠送金额 {amount_fen} 分超过本角色上限 {role.max_gift_fen} 分"
            )

        await self._log(
            tenant_id, employee_id, store_id, "gift",
            amount_fen, role.level, result, order_id, request_ip, session,
        )
        logger.info(
            "permission_check_gift",
            employee_id=str(employee_id),
            amount_fen=amount_fen,
            role_level=role.level,
            allowed=result.allowed,
        )
        return result

    async def check_void_order_permission(
        self,
        employee_id: UUID,
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """检查退单权限"""
        role, early_deny = await self._get_role_or_deny(
            employee_id, tenant_id, store_id, session
        )
        if early_deny is not None:
            await self._log(
                tenant_id, employee_id, store_id, "void_order",
                None, None, early_deny, order_id, request_ip, session,
            )
            return early_deny

        if role.can_void_order:
            result = PermissionCheckResult.permit()
        else:
            result = PermissionCheckResult.deny(
                f"本角色（Level {role.level}）无退单权限，需 Level 7+ 操作"
            )

        await self._log(
            tenant_id, employee_id, store_id, "void_order",
            None, role.level, result, order_id, request_ip, session,
        )
        logger.info(
            "permission_check_void_order",
            employee_id=str(employee_id),
            role_level=role.level,
            allowed=result.allowed,
        )
        return result

    async def check_modify_price_permission(
        self,
        employee_id: UUID,
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """检查改价权限"""
        role, early_deny = await self._get_role_or_deny(
            employee_id, tenant_id, store_id, session
        )
        if early_deny is not None:
            await self._log(
                tenant_id, employee_id, store_id, "modify_price",
                None, None, early_deny, order_id, request_ip, session,
            )
            return early_deny

        if role.can_modify_price:
            result = PermissionCheckResult.permit()
        else:
            result = PermissionCheckResult.deny(
                f"本角色（Level {role.level}）无改价权限，需 Level 6+ 操作"
            )

        await self._log(
            tenant_id, employee_id, store_id, "modify_price",
            None, role.level, result, order_id, request_ip, session,
        )
        logger.info(
            "permission_check_modify_price",
            employee_id=str(employee_id),
            role_level=role.level,
            allowed=result.allowed,
        )
        return result

    async def check_data_query_permission(
        self,
        employee_id: UUID,
        query_days: int,
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """检查数据查询天数权限"""
        role, early_deny = await self._get_role_or_deny(
            employee_id, tenant_id, store_id, session
        )
        if early_deny is not None:
            return early_deny

        if role.level >= 10 or role.data_query_days >= 9999:
            result = PermissionCheckResult.permit()
        elif query_days <= role.data_query_days:
            result = PermissionCheckResult.permit()
        else:
            result = PermissionCheckResult.deny(
                f"查询范围 {query_days} 天超过本角色权限上限 {role.data_query_days} 天"
            )

        logger.info(
            "permission_check_data_query",
            employee_id=str(employee_id),
            query_days=query_days,
            role_level=role.level,
            allowed=result.allowed,
        )
        return result

    async def get_employee_role_snapshot(
        self,
        employee_id: UUID,
        tenant_id: UUID,
        session: AsyncSession,
        store_id: Optional[UUID] = None,
    ) -> Optional[RoleSnapshot]:
        """暴露给外部调用的角色查询（供API层直接使用）"""
        return await self._repo.get_employee_role_snapshot(
            employee_id, tenant_id, store_id, session
        )

    async def _log(
        self,
        tenant_id: UUID,
        employee_id: UUID,
        store_id: Optional[UUID],
        operation: str,
        amount_fen: Optional[int],
        role_level: Optional[int],
        result: PermissionCheckResult,
        order_id: Optional[UUID],
        request_ip: Optional[str],
        session: AsyncSession,
    ) -> None:
        """写审计日志，失败仅记录警告，不中断主流程"""
        try:
            await self._repo.write_check_log(
                tenant_id=tenant_id,
                employee_id=employee_id,
                store_id=store_id,
                operation=operation,
                amount_fen=amount_fen,
                role_level=role_level,
                result=result,
                order_id=order_id,
                request_ip=request_ip,
                session=session,
            )
        except OSError as exc:
            logger.warning("permission_log_write_failed", error=str(exc))
        except RuntimeError as exc:
            logger.warning("permission_log_write_failed", error=str(exc))
