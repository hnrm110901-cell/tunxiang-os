"""FastAPI 依赖：自动从请求中提取 store_id 并校验跨店权限。

用法:
    @router.get("/vouchers/{store_id}", dependencies=[Depends(require_store_access("finance"))])
    async def list_vouchers(store_id: str, ...): ...

    # 或者拿到 user 对象
    @router.post("/ar/{store_id}")
    async def create_ar(
        store_id: str,
        user: User = Depends(require_store_access("finance_write")),
    ): ...

store_id 提取顺序：
    1) FastAPI Path 参数 `store_id`
    2) Query 参数 `store_id`
    3) 请求体中的 `store_id` 字段（需要 Body 已经解析；本依赖不负责此情形）
"""

from typing import Callable

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user import User
from ..services.store_access_service import store_access_service
from .database import get_db
from .dependencies import get_current_active_user


def require_store_access(resource: str = "read") -> Callable:
    """生成一个校验 store_id 权限的依赖。"""

    async def _dep(
        request: Request,
        store_id_q: str | None = Query(default=None, alias="store_id"),
        user: User = Depends(get_current_active_user),
        session: AsyncSession = Depends(get_db),
    ) -> User:
        # 路径参数优先
        path_store = (request.path_params or {}).get("store_id")
        store_id = path_store or store_id_q
        if not store_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少 store_id 参数，无法进行门店权限校验",
            )

        ok = await store_access_service.check_store_access(
            session=session, user=user, store_id=str(store_id), resource_type=resource
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"无权访问门店 {store_id} 的 {resource} 资源",
            )
        return user

    return _dep
