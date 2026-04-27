"""菜品口味做法 API — 6个端点（v345 DB重构版）

- GET    /api/v1/menu/dishes/{dish_id}/practices      列出做法
- POST   /api/v1/menu/dishes/{dish_id}/practices      批量保存做法
- POST   /api/v1/menu/dishes/{dish_id}/practices/temp  创建临时做法
- DELETE /api/v1/menu/practices/{practice_id}          删除单条做法
- GET    /api/v1/menu/practice-templates               获取做法模板
- POST   /api/v1/menu/practice-templates/seed          初始化默认模板
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
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


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 请求模型 ───


class PracticeItem(BaseModel):
    practice_name: str
    practice_group: str = "default"
    additional_price_fen: int = Field(default=0, ge=0)
    is_default: bool = False
    sort_order: int = 0
    practice_type: str = "standard"
    max_quantity: int = Field(default=1, ge=1)


class BatchSavePracticesReq(BaseModel):
    practices: list[PracticeItem]


class TempPracticeReq(BaseModel):
    practice_name: str
    additional_price_fen: int = Field(ge=0)
    practice_group: str = "临时做法"
    max_quantity: int = Field(default=1, ge=1)


# ─── 端点 ───


@router.get("/dishes/{dish_id}/practices")
async def list_practices(
    dish_id: str,
    request: Request,
    include_temporary: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出菜品的全部做法，按 practice_group + sort_order 排序"""
    tenant_id = _get_tenant_id(request)
    dish_uuid = uuid.UUID(dish_id)
    await _set_rls(db, tenant_id)

    conditions = [
        DishPractice.dish_id == dish_uuid,
        DishPractice.tenant_id == uuid.UUID(tenant_id),
        DishPractice.is_deleted == False,  # noqa: E712
    ]
    if not include_temporary:
        conditions.append(DishPractice.is_temporary == False)  # noqa: E712

    result = await db.execute(
        select(DishPractice).where(*conditions).order_by(DishPractice.practice_group, DishPractice.sort_order)
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
            "is_temporary": p.is_temporary,
            "practice_type": p.practice_type,
            "max_quantity": p.max_quantity,
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
    """批量保存做法 -- 先删除该菜品所有非临时做法，再批量插入（全量替换策略）

    注意：临时做法不受批量保存影响，需要单独通过 DELETE 端点删除。
    """
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    await _set_rls(db, tenant_id)

    # 软删除旧的非临时做法（保留临时做法）
    await db.execute(
        delete(DishPractice).where(
            DishPractice.dish_id == dish_uuid,
            DishPractice.tenant_id == tenant_uuid,
            DishPractice.is_temporary == False,  # noqa: E712
        )
    )

    created = []
    for p in req.practices:
        is_temporary = p.practice_type == "temporary"
        practice = DishPractice(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            dish_id=dish_uuid,
            practice_name=p.practice_name,
            practice_group=p.practice_group,
            additional_price_fen=p.additional_price_fen,
            is_default=p.is_default,
            sort_order=p.sort_order,
            is_temporary=is_temporary,
            practice_type=p.practice_type,
            max_quantity=p.max_quantity,
        )
        db.add(practice)
        created.append(
            {
                "id": str(practice.id),
                "practice_name": p.practice_name,
                "practice_group": p.practice_group,
                "additional_price_fen": p.additional_price_fen,
                "practice_type": p.practice_type,
                "max_quantity": p.max_quantity,
            }
        )

    await db.commit()
    logger.info("practices_saved", dish_id=dish_id, count=len(created))

    return _ok({"dish_id": dish_id, "saved": len(created), "items": created})


@router.post("/dishes/{dish_id}/practices/temp")
async def create_temp_practice(
    dish_id: str,
    req: TempPracticeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建临时做法（有价做法）-- 顾客下单时自定义"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    await _set_rls(db, tenant_id)

    practice = DishPractice(
        id=uuid.uuid4(),
        tenant_id=tenant_uuid,
        dish_id=dish_uuid,
        practice_name=req.practice_name,
        practice_group=req.practice_group,
        additional_price_fen=req.additional_price_fen,
        is_default=False,
        sort_order=99,
        is_temporary=True,
        practice_type="temporary",
        max_quantity=req.max_quantity,
    )
    db.add(practice)
    await db.commit()

    logger.info("temp_practice_created", dish_id=dish_id, name=req.practice_name, price_fen=req.additional_price_fen)

    return _ok(
        {
            "id": str(practice.id),
            "dish_id": dish_id,
            "practice_name": req.practice_name,
            "practice_group": req.practice_group,
            "additional_price_fen": req.additional_price_fen,
            "is_temporary": True,
            "practice_type": "temporary",
            "max_quantity": req.max_quantity,
        }
    )


@router.delete("/practices/{practice_id}")
async def delete_practice(
    practice_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除单条做法"""
    tenant_id = _get_tenant_id(request)
    practice_uuid = uuid.UUID(practice_id)
    await _set_rls(db, tenant_id)

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


@router.get("/practice-templates")
async def list_practice_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取通用做法模板（按 practice_group 分组）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 使用 service 层获取模板
    # 直接查询 DB 中的模板（全零 dish_id）
    template_dish_id = "00000000-0000-0000-0000-000000000000"
    result = await db.execute(
        select(DishPractice)
        .where(
            DishPractice.tenant_id == uuid.UUID(tenant_id),
            DishPractice.dish_id == uuid.UUID(template_dish_id),
            DishPractice.is_deleted == False,  # noqa: E712
        )
        .order_by(DishPractice.practice_group, DishPractice.sort_order)
    )
    rows = result.scalars().all()

    if rows:
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(r.practice_group, []).append(
                {
                    "id": str(r.id),
                    "practice_name": r.practice_name,
                    "practice_group": r.practice_group,
                    "additional_price_fen": r.additional_price_fen,
                    "is_default": r.is_default,
                    "practice_type": r.practice_type,
                    "max_quantity": r.max_quantity,
                }
            )
        return _ok({"groups": groups, "total": len(rows)})

    # 未 seed，返回内存默认模板
    _DEFAULT_TEMPLATES = [
        {
            "practice_name": "不辣",
            "practice_group": "辣度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "微辣",
            "practice_group": "辣度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "中辣",
            "practice_group": "辣度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "特辣",
            "practice_group": "辣度",
            "additional_price_fen": 200,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "不加糖",
            "practice_group": "甜度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "半糖",
            "practice_group": "甜度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "全糖",
            "practice_group": "甜度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "不要香菜",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "不要葱",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "不要蒜",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "不加味精",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "max_quantity": 1,
        },
        {
            "practice_name": "加蛋",
            "practice_group": "加料",
            "additional_price_fen": 200,
            "practice_type": "addon",
            "max_quantity": 3,
        },
        {
            "practice_name": "加芝士",
            "practice_group": "加料",
            "additional_price_fen": 300,
            "practice_type": "addon",
            "max_quantity": 2,
        },
    ]

    groups = {}
    for tpl in _DEFAULT_TEMPLATES:
        groups.setdefault(tpl["practice_group"], []).append(tpl)
    return _ok({"groups": groups, "total": len(_DEFAULT_TEMPLATES), "_fallback": True})


@router.post("/practice-templates/seed")
async def seed_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """初始化默认做法模板到 DB（幂等操作）"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)
    template_dish_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    await _set_rls(db, tenant_id)

    # 检查是否已初始化
    existing = await db.execute(
        select(DishPractice).where(
            DishPractice.tenant_id == tenant_uuid,
            DishPractice.dish_id == template_dish_id,
            DishPractice.is_deleted == False,  # noqa: E712
        )
    )
    if existing.scalars().first():
        return _ok({"seeded": 0, "message": "模板已存在，跳过初始化"})

    _SEED_TEMPLATES = [
        {
            "practice_name": "不辣",
            "practice_group": "辣度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": True,
            "sort_order": 0,
            "max_quantity": 1,
        },
        {
            "practice_name": "微辣",
            "practice_group": "辣度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 1,
            "max_quantity": 1,
        },
        {
            "practice_name": "中辣",
            "practice_group": "辣度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 2,
            "max_quantity": 1,
        },
        {
            "practice_name": "特辣",
            "practice_group": "辣度",
            "additional_price_fen": 200,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 3,
            "max_quantity": 1,
        },
        {
            "practice_name": "不加糖",
            "practice_group": "甜度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": True,
            "sort_order": 0,
            "max_quantity": 1,
        },
        {
            "practice_name": "半糖",
            "practice_group": "甜度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 1,
            "max_quantity": 1,
        },
        {
            "practice_name": "全糖",
            "practice_group": "甜度",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 2,
            "max_quantity": 1,
        },
        {
            "practice_name": "不要香菜",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 0,
            "max_quantity": 1,
        },
        {
            "practice_name": "不要葱",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 1,
            "max_quantity": 1,
        },
        {
            "practice_name": "不要蒜",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 2,
            "max_quantity": 1,
        },
        {
            "practice_name": "不加味精",
            "practice_group": "忌口",
            "additional_price_fen": 0,
            "practice_type": "standard",
            "is_default": False,
            "sort_order": 3,
            "max_quantity": 1,
        },
        {
            "practice_name": "加蛋",
            "practice_group": "加料",
            "additional_price_fen": 200,
            "practice_type": "addon",
            "is_default": False,
            "sort_order": 0,
            "max_quantity": 3,
        },
        {
            "practice_name": "加芝士",
            "practice_group": "加料",
            "additional_price_fen": 300,
            "practice_type": "addon",
            "is_default": False,
            "sort_order": 1,
            "max_quantity": 2,
        },
    ]

    inserted = 0
    for tpl in _SEED_TEMPLATES:
        is_temporary = tpl.get("practice_type") == "temporary"
        practice = DishPractice(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            dish_id=template_dish_id,
            practice_name=tpl["practice_name"],
            practice_group=tpl["practice_group"],
            additional_price_fen=tpl["additional_price_fen"],
            is_default=tpl.get("is_default", False),
            sort_order=tpl.get("sort_order", 0),
            is_temporary=is_temporary,
            practice_type=tpl.get("practice_type", "standard"),
            max_quantity=tpl.get("max_quantity", 1),
        )
        db.add(practice)
        inserted += 1

    await db.commit()
    logger.info("practice_templates_seeded", tenant_id=tenant_id, count=inserted)

    return _ok({"seeded": inserted, "message": f"成功初始化 {inserted} 个做法模板"})
