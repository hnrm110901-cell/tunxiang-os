"""收银权限客户端 — tx-trade 调用 tx-org 权限校验

设计选择：
  直接复用 tx-org 的 PermissionService，而非走 HTTP 调用。
  原因：两个服务共享同一个 PostgreSQL 实例，复用 Service 层可避免网络开销和额外依赖。
  未来若拆分到独立部署，改为 httpx 调用 tx-org /api/v1/permissions/* 即可。

使用方：cashier_api.py（折扣/退单端点）
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

# 复用 tx-org 的 PermissionService
# 在同一 Python 进程内直接导入（monorepo 共享包策略）
try:
    from services.permission_service import (  # type: ignore[import]
        PermissionCheckResult,
        PermissionService,
    )
except ImportError:
    # 回退：通过 sys.path 查找（本地开发时路径可能不同）
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../tx-org/src"))
    from services.permission_service import (  # type: ignore[import]
        PermissionCheckResult,
        PermissionService,
    )

logger = structlog.get_logger(__name__)

_perm_svc = PermissionService()


class CashierPermissionClient:
    """收银操作权限检查封装

    所有方法均异步，与 cashier_api.py 的 async 端点兼容。
    Session 由调用方传入，复用同一事务。
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self._session = session
        try:
            self._tenant_id = UUID(tenant_id)
        except ValueError as exc:
            raise ValueError(f"tenant_id 格式无效: {tenant_id}") from exc

    async def check_discount(
        self,
        employee_id: UUID,
        discount_rate: float,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """折扣权限检查（percent_off 类型折扣）"""
        return await _perm_svc.check_discount_permission(
            employee_id=employee_id,
            discount_rate=discount_rate,
            tenant_id=self._tenant_id,
            session=self._session,
            store_id=store_id,
            order_id=order_id,
            request_ip=request_ip,
        )

    async def check_void_order(
        self,
        employee_id: UUID,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """退单权限检查（需 Level 7+）"""
        return await _perm_svc.check_void_order_permission(
            employee_id=employee_id,
            tenant_id=self._tenant_id,
            session=self._session,
            store_id=store_id,
            order_id=order_id,
            request_ip=request_ip,
        )

    async def check_wipeoff(
        self,
        employee_id: UUID,
        amount_fen: int,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """抹零权限检查"""
        return await _perm_svc.check_wipeoff_permission(
            employee_id=employee_id,
            amount_fen=amount_fen,
            tenant_id=self._tenant_id,
            session=self._session,
            store_id=store_id,
            order_id=order_id,
            request_ip=request_ip,
        )

    async def check_gift(
        self,
        employee_id: UUID,
        amount_fen: int,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """赠送权限检查"""
        return await _perm_svc.check_gift_permission(
            employee_id=employee_id,
            amount_fen=amount_fen,
            tenant_id=self._tenant_id,
            session=self._session,
            store_id=store_id,
            order_id=order_id,
            request_ip=request_ip,
        )

    async def check_modify_price(
        self,
        employee_id: UUID,
        store_id: Optional[UUID] = None,
        order_id: Optional[UUID] = None,
        request_ip: Optional[str] = None,
    ) -> PermissionCheckResult:
        """改价权限检查（需 Level 6+）"""
        return await _perm_svc.check_modify_price_permission(
            employee_id=employee_id,
            tenant_id=self._tenant_id,
            session=self._session,
            store_id=store_id,
            order_id=order_id,
            request_ip=request_ip,
        )
