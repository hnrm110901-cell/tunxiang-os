"""ApplicationRepository — Application 表的 CRUD 封装。

约束：
- RLS 已由 session 层注入 ``app.tenant_id``，本层 SQL 仍显式带 tenant_id 作为防御性写法。
- 所有方法使用具体异常（``SQLAlchemyError`` / ``IntegrityError``），禁止 broad except。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.application import Application

logger = structlog.get_logger(__name__)


class ApplicationAlreadyExists(Exception):
    """同租户内 ``code`` 重复。"""


class ApplicationRepository:
    """Application 表 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tenant_id: UUID, payload: dict[str, Any]) -> Application:
        application = Application(tenant_id=tenant_id, **payload)
        self._session.add(application)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            logger.warning(
                "devforge_application_create_conflict",
                tenant_id=str(tenant_id),
                code=payload.get("code"),
            )
            raise ApplicationAlreadyExists(
                f"application with code={payload.get('code')!r} already exists"
            ) from exc
        return application

    async def get_by_id(self, tenant_id: UUID, application_id: UUID) -> Application | None:
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .where(Application.tenant_id == tenant_id)
            .where(Application.is_deleted.is_(False))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        resource_type: str | None = None,
        code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[Application], int]:
        if page < 1:
            page = 1
        if size < 1:
            size = 1
        if size > 200:
            size = 200

        base = (
            select(Application)
            .where(Application.tenant_id == tenant_id)
            .where(Application.is_deleted.is_(False))
        )
        count_stmt = (
            select(func.count())
            .select_from(Application)
            .where(Application.tenant_id == tenant_id)
            .where(Application.is_deleted.is_(False))
        )
        if resource_type is not None:
            base = base.where(Application.resource_type == resource_type)
            count_stmt = count_stmt.where(Application.resource_type == resource_type)
        if code is not None:
            base = base.where(Application.code == code)
            count_stmt = count_stmt.where(Application.code == code)

        offset = (page - 1) * size
        stmt = base.order_by(Application.created_at.desc()).offset(offset).limit(size)

        try:
            rows = (await self._session.execute(stmt)).scalars().all()
            total_value = (await self._session.execute(count_stmt)).scalar_one()
        except SQLAlchemyError:
            logger.exception(
                "devforge_application_list_failed",
                tenant_id=str(tenant_id),
                resource_type=resource_type,
                code=code,
            )
            raise

        total = int(total_value or 0)
        return list(rows), total

    async def update(
        self,
        tenant_id: UUID,
        application_id: UUID,
        patch: dict[str, Any],
    ) -> Application | None:
        if not patch:
            return await self.get_by_id(tenant_id, application_id)

        stmt = (
            update(Application)
            .where(Application.id == application_id)
            .where(Application.tenant_id == tenant_id)
            .where(Application.is_deleted.is_(False))
            .values(**patch)
            .returning(Application)
        )
        try:
            result = await self._session.execute(stmt)
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApplicationAlreadyExists(str(exc.orig)) from exc
        await self._session.flush()
        return result.scalar_one_or_none()

    async def soft_delete(self, tenant_id: UUID, application_id: UUID) -> bool:
        stmt = (
            update(Application)
            .where(Application.id == application_id)
            .where(Application.tenant_id == tenant_id)
            .where(Application.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return (result.rowcount or 0) > 0
