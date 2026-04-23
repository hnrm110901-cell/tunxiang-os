"""菜品口味做法 API — 3个端点

- GET  /api/v1/menu/dishes/{dish_id}/practices   列出做法
- POST /api/v1/menu/dishes/{dish_id}/practices   批量保存做法
- DELETE /api/v1/menu/practices/{practice_id}     删除单条做法
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..models.dish_practice import DishPractice

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/menu", tags=["practice"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class PracticeItem(BaseModel):
    practice_name: str
    practice_group: str = "default"
    additional_price_fen: int = Field(default=0, ge=0)
    is_default: bool = False
    sort_order: int = 0


class BatchSavePracticesReq(BaseModel):
    practices: list[PracticeItem]


# ─── 端点 ───


@router.get("/dishes/{dish_id}/practices")
async def list_practices(
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出菜品的全部做法，按 practice_group + sort_order 排序"""
    tenant_id = _get_tenant_id(request)
    dish_uuid = uuid.UUID(dish_id)

    result = await db.execute(
        select(DishPractice)
        .where(
            DishPractice.dish_id == dish_uuid,
            DishPractice.tenant_id == uuid.UUID(tenant_id),
            DishPractice.is_deleted == False,  # noqa: E712
        )
        .order_by(DishPractice.practice_group, DishPractice.sort_order)
    )
    practices = result.scalars().all()

    items = [
        {
            "id": str(p.id),
            "dish_id": str(p.dish_id),
            "practice_name": p.practice_name,
            "practice_group": p.practice_group,
            "additional_price_fen": p.additional_price_fen,
            "is_default": p.is_default,
            "sort_order": p.sort_order,
        }
        for p in practices
    ]

    # 按 group 分组返回
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(item["practice_group"], []).append(item)

    return _ok({"items": items, "groups": groups, "total": len(items)})


@router.post("/dishes/{dish_id}/practices")
async def batch_save_practices(
    dish_id: str,
    req: BatchSavePracticesReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量保存做法 — 先删除该菜品所有做法，再批量插入（全量替换策略）"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)

    # 软删除旧做法
    await db.execute(
        delete(DishPractice).where(
            DishPractice.dish_id == dish_uuid,
            DishPractice.tenant_id == tenant_uuid,
        )
    )

    created = []
    for p in req.practices:
        practice = DishPractice(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            dish_id=dish_uuid,
            practice_name=p.practice_name,
            practice_group=p.practice_group,
            additional_price_fen=p.additional_price_fen,
            is_default=p.is_default,
            sort_order=p.sort_order,
        )
        db.add(practice)
        created.append(
            {
                "id": str(practice.id),
                "practice_name": p.practice_name,
                "practice_group": p.practice_group,
                "additional_price_fen": p.additional_price_fen,
            }
        )

    await db.commit()
    logger.info("practices_saved", dish_id=dish_id, count=len(created))

    return _ok({"dish_id": dish_id, "saved": len(created), "items": created})


@router.delete("/practices/{practice_id}")
async def delete_practice(
    practice_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除单条做法"""
    tenant_id = _get_tenant_id(request)
    practice_uuid = uuid.UUID(practice_id)

    result = await db.execute(
        select(DishPractice).where(
            DishPractice.id == practice_uuid,
            DishPractice.tenant_id == uuid.UUID(tenant_id),
        )
    )
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="做法不存在")

    await db.delete(practice)
    await db.commit()
    logger.info("practice_deleted", practice_id=practice_id)

    return _ok({"deleted": True, "practice_id": practice_id})
