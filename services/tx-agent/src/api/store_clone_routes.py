"""store_clone_routes — 门店快速开店克隆 API

端点：
  POST   /api/v1/store-clone           启动克隆任务
  GET    /api/v1/store-clone/{task_id}/progress  查询进度
  GET    /api/v1/store-clone/history   克隆历史
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

router = APIRouter(prefix="/api/v1/store-clone", tags=["store-clone"])


# ── 依赖注入 ───────────────────────────────────────────────────────────────────

async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_tenant_id(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> str:
    return x_tenant_id


# ── Pydantic 模型 ───────────────────────────────────────────────────────────────

class CloneRequest(BaseModel):
    source_store_id: UUID
    target_store_id: UUID
    items: list[str]  # CloneItemType values
    operator_id: UUID


class CloneResponse(BaseModel):
    task_id: str
    message: str


# ── 端点 ───────────────────────────────────────────────────────────────────────

@router.post("", response_model=CloneResponse)
async def start_clone(
    req: CloneRequest,
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant_id),
) -> CloneResponse:
    """启动门店配置克隆任务（异步执行，立即返回 task_id）"""
    from ..services.store_clone_service import CloneItemType, StoreCloneService

    try:
        items = [CloneItemType(i) for i in req.items]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"无效的克隆项: {exc}") from exc

    task_id = await StoreCloneService.start_clone(
        db=db,
        tenant_id=UUID(tenant_id),
        source_store_id=req.source_store_id,
        target_store_id=req.target_store_id,
        items=items,
        operator_id=req.operator_id,
    )
    return CloneResponse(task_id=task_id, message="克隆任务已启动")


@router.get("/history")
async def list_clone_history(
    db: AsyncSession = Depends(_get_db),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict:
    """查询克隆历史（最近50条，按创建时间降序）"""
    result = await db.execute(
        text("""
            SELECT id, source_store_id, target_store_id, selected_items,
                   status, progress, created_by, created_at, updated_at,
                   error_message, result_summary
            FROM store_clone_tasks
            WHERE tenant_id = :tenant_id
              AND is_deleted = FALSE
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"tenant_id": tenant_id},
    )
    rows = result.fetchall()
    return {"ok": True, "data": {"items": [dict(r._mapping) for r in rows]}}


@router.get("/{task_id}/progress")
async def get_clone_progress(task_id: str) -> dict:
    """查询克隆进度（从内存缓存读取，实时更新）"""
    from ..services.store_clone_service import StoreCloneService

    progress = await StoreCloneService.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "ok": True,
        "data": {
            "task_id": progress.task_id,
            "status": progress.status,
            "progress_pct": progress.progress_pct,
            "completed_items": progress.completed_items,
            "total_items": progress.total_items,
            "current_step": progress.current_step,
            "errors": progress.errors,
            "started_at": progress.started_at,
            "completed_at": progress.completed_at,
        },
    }
