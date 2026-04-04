"""菜品规格管理 API — 真实 DB 接入
域B：规格组 CRUD（容量/份量/辣度/温度等维度）
接入 dish_spec_groups + dish_spec_options 表（v131 迁移创建）。
所有操作带 X-Tenant-ID 多租户隔离，RLS tenant context。
"""
import uuid
from typing import Optional, List

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/menu/specs", tags=["menu-specs"])


# ─── Pydantic 模型 ──────────────────────────────────────────────

class SpecOption(BaseModel):
    name: str
    price_delta_fen: int = 0
    is_default: bool = False
    sort_order: int = 0


class SpecGroupCreate(BaseModel):
    dish_id: str
    spec_group_name: str
    options: List[SpecOption]
    is_required: bool = False
    min_select: int = 0
    max_select: int = 1
    sort_order: int = 0


class SpecGroupUpdate(BaseModel):
    spec_group_name: Optional[str] = None
    options: Optional[List[SpecOption]] = None
    is_required: Optional[bool] = None
    min_select: Optional[int] = None
    max_select: Optional[int] = None
    sort_order: Optional[int] = None


# ─── 辅助 ───────────────────────────────────────────────────────

async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _get_group_with_options(db: AsyncSession, group_id: str, tenant_id: str) -> Optional[dict]:
    """按 group_id 查询规格组及其选项"""
    result = await db.execute(
        text("""
            SELECT g.id, g.dish_id, g.name AS group_name, g.is_required,
                   g.min_select, g.max_select, g.sort_order,
                   g.created_at, g.updated_at
            FROM dish_spec_groups g
            WHERE g.id = :gid::uuid
              AND g.tenant_id = :tid::uuid
              AND g.is_deleted = false
        """),
        {"gid": group_id, "tid": tenant_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        return None

    opts_result = await db.execute(
        text("""
            SELECT id, name, price_delta_fen, is_default, sort_order, stock_status
            FROM dish_spec_options
            WHERE group_id = :gid::uuid
              AND tenant_id = :tid::uuid
              AND is_deleted = false
            ORDER BY sort_order, id
        """),
        {"gid": group_id, "tid": tenant_id},
    )
    opts = [dict(o) for o in opts_result.mappings().all()]
    return {
        "id": str(row["id"]),
        "dish_id": str(row["dish_id"]),
        "spec_group_name": row["group_name"],
        "is_required": row["is_required"],
        "min_select": row["min_select"],
        "max_select": row["max_select"],
        "sort_order": row["sort_order"],
        "options": [
            {
                "id": str(o["id"]),
                "name": o["name"],
                "price_delta_fen": o["price_delta_fen"],
                "is_default": o["is_default"],
                "sort_order": o["sort_order"],
                "stock_status": o["stock_status"],
            }
            for o in opts
        ],
    }


# ─── 路由 ────────────────────────────────────────────────────────

@router.get("")
async def list_specs(
    dish_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取规格组列表，可按 dish_id 过滤"""
    try:
        await _set_rls(db, x_tenant_id)
        params: dict = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
        where_extra = ""
        if dish_id:
            where_extra = " AND g.dish_id = :dish_id::uuid"
            params["dish_id"] = dish_id

        count_result = await db.execute(
            text(f"""
                SELECT count(*) FROM dish_spec_groups g
                WHERE g.tenant_id = :tid::uuid AND g.is_deleted = false
                {where_extra}
            """),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text(f"""
                SELECT g.id, g.dish_id, g.name AS group_name, g.is_required,
                       g.min_select, g.max_select, g.sort_order
                FROM dish_spec_groups g
                WHERE g.tenant_id = :tid::uuid AND g.is_deleted = false
                {where_extra}
                ORDER BY g.sort_order, g.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        groups = result.mappings().all()

        # 批量拉选项
        items = []
        for g in groups:
            gid = str(g["id"])
            opts_result = await db.execute(
                text("""
                    SELECT id, name, price_delta_fen, is_default, sort_order, stock_status
                    FROM dish_spec_options
                    WHERE group_id = :gid::uuid AND tenant_id = :tid::uuid AND is_deleted = false
                    ORDER BY sort_order
                """),
                {"gid": gid, "tid": x_tenant_id},
            )
            opts = opts_result.mappings().all()
            items.append({
                "id": gid,
                "dish_id": str(g["dish_id"]),
                "spec_group_name": g["group_name"],
                "is_required": g["is_required"],
                "min_select": g["min_select"],
                "max_select": g["max_select"],
                "sort_order": g["sort_order"],
                "options": [
                    {
                        "id": str(o["id"]),
                        "name": o["name"],
                        "price_delta_fen": o["price_delta_fen"],
                        "is_default": o["is_default"],
                        "sort_order": o["sort_order"],
                        "stock_status": o["stock_status"],
                    }
                    for o in opts
                ],
            })
        log.info("list_specs", tenant_id=x_tenant_id, dish_id=dish_id, total=total)
        return {
            "ok": True,
            "data": {"items": items, "total": total, "page": page, "size": size},
        }
    except SQLAlchemyError as exc:
        log.error("specs.list_failed", error=str(exc), exc_info=True)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size, "_fallback": True}}


@router.post("")
async def create_spec(
    body: SpecGroupCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增规格组（含选项）"""
    try:
        await _set_rls(db, x_tenant_id)
        group_id = uuid.uuid4()
        tenant_uuid = x_tenant_id

        await db.execute(
            text("""
                INSERT INTO dish_spec_groups
                  (id, tenant_id, dish_id, name, is_required, min_select, max_select, sort_order)
                VALUES
                  (:id::uuid, :tid::uuid, :dish_id::uuid, :name, :is_required,
                   :min_select, :max_select, :sort_order)
            """),
            {
                "id": str(group_id),
                "tid": tenant_uuid,
                "dish_id": body.dish_id,
                "name": body.spec_group_name,
                "is_required": body.is_required,
                "min_select": body.min_select,
                "max_select": body.max_select,
                "sort_order": body.sort_order,
            },
        )
        for opt in body.options:
            await db.execute(
                text("""
                    INSERT INTO dish_spec_options
                      (id, tenant_id, group_id, name, price_delta_fen, is_default, sort_order)
                    VALUES
                      (gen_random_uuid(), :tid::uuid, :gid::uuid, :name, :delta, :is_default, :sort)
                """),
                {
                    "tid": tenant_uuid,
                    "gid": str(group_id),
                    "name": opt.name,
                    "delta": opt.price_delta_fen,
                    "is_default": opt.is_default,
                    "sort": opt.sort_order,
                },
            )
        await db.commit()
        data = await _get_group_with_options(db, str(group_id), x_tenant_id)
        log.info("create_spec", tenant_id=x_tenant_id, dish_id=body.dish_id, group_id=str(group_id))
        return {"ok": True, "data": data}
    except SQLAlchemyError as exc:
        log.error("specs.create_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")


@router.put("/{spec_id}")
async def update_spec(
    spec_id: str,
    body: SpecGroupCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全量更新规格组（含选项重建）"""
    try:
        await _set_rls(db, x_tenant_id)
        # 检查存在
        existing = await _get_group_with_options(db, spec_id, x_tenant_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"规格组不存在: {spec_id}")

        await db.execute(
            text("""
                UPDATE dish_spec_groups
                SET name = :name, is_required = :is_required,
                    min_select = :min_select, max_select = :max_select,
                    sort_order = :sort_order, updated_at = now()
                WHERE id = :id::uuid AND tenant_id = :tid::uuid AND is_deleted = false
            """),
            {
                "id": spec_id,
                "tid": x_tenant_id,
                "name": body.spec_group_name,
                "is_required": body.is_required,
                "min_select": body.min_select,
                "max_select": body.max_select,
                "sort_order": body.sort_order,
            },
        )
        # 软删除旧选项
        await db.execute(
            text("""
                UPDATE dish_spec_options SET is_deleted = true
                WHERE group_id = :gid::uuid AND tenant_id = :tid::uuid
            """),
            {"gid": spec_id, "tid": x_tenant_id},
        )
        # 重建选项
        for opt in body.options:
            await db.execute(
                text("""
                    INSERT INTO dish_spec_options
                      (id, tenant_id, group_id, name, price_delta_fen, is_default, sort_order)
                    VALUES
                      (gen_random_uuid(), :tid::uuid, :gid::uuid, :name, :delta, :is_default, :sort)
                """),
                {
                    "tid": x_tenant_id,
                    "gid": spec_id,
                    "name": opt.name,
                    "delta": opt.price_delta_fen,
                    "is_default": opt.is_default,
                    "sort": opt.sort_order,
                },
            )
        await db.commit()
        data = await _get_group_with_options(db, spec_id, x_tenant_id)
        log.info("update_spec", tenant_id=x_tenant_id, spec_id=spec_id)
        return {"ok": True, "data": data}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("specs.update_failed", spec_id=spec_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")


@router.delete("/{spec_id}")
async def delete_spec(
    spec_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除规格组（及其选项）"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("""
                UPDATE dish_spec_groups SET is_deleted = true, updated_at = now()
                WHERE id = :id::uuid AND tenant_id = :tid::uuid AND is_deleted = false
            """),
            {"id": spec_id, "tid": x_tenant_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"规格组不存在: {spec_id}")
        await db.execute(
            text("""
                UPDATE dish_spec_options SET is_deleted = true
                WHERE group_id = :gid::uuid AND tenant_id = :tid::uuid
            """),
            {"gid": spec_id, "tid": x_tenant_id},
        )
        await db.commit()
        log.info("delete_spec", tenant_id=x_tenant_id, spec_id=spec_id)
        return {"ok": True, "data": {"id": spec_id, "deleted": True}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("specs.delete_failed", spec_id=spec_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")


@router.patch("/{spec_id}")
async def patch_spec(
    spec_id: str,
    body: SpecGroupUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """部分更新规格组（字段级，选项可选重建）"""
    try:
        await _set_rls(db, x_tenant_id)
        existing = await _get_group_with_options(db, spec_id, x_tenant_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"规格组不存在: {spec_id}")

        set_clauses = []
        params: dict = {"id": spec_id, "tid": x_tenant_id}
        for field, col in [
            ("spec_group_name", "name"),
            ("is_required", "is_required"),
            ("min_select", "min_select"),
            ("max_select", "max_select"),
            ("sort_order", "sort_order"),
        ]:
            val = getattr(body, field, None)
            if val is not None:
                set_clauses.append(f"{col} = :{field}")
                params[field] = val

        if set_clauses:
            set_clauses.append("updated_at = now()")
            await db.execute(
                text(f"UPDATE dish_spec_groups SET {', '.join(set_clauses)} WHERE id = :id::uuid AND tenant_id = :tid::uuid AND is_deleted = false"),
                params,
            )

        if body.options is not None:
            await db.execute(
                text("UPDATE dish_spec_options SET is_deleted = true WHERE group_id = :gid::uuid AND tenant_id = :tid::uuid"),
                {"gid": spec_id, "tid": x_tenant_id},
            )
            for opt in body.options:
                await db.execute(
                    text("""
                        INSERT INTO dish_spec_options
                          (id, tenant_id, group_id, name, price_delta_fen, is_default, sort_order)
                        VALUES
                          (gen_random_uuid(), :tid::uuid, :gid::uuid, :name, :delta, :is_default, :sort)
                    """),
                    {
                        "tid": x_tenant_id,
                        "gid": spec_id,
                        "name": opt.name,
                        "delta": opt.price_delta_fen,
                        "is_default": opt.is_default,
                        "sort": opt.sort_order,
                    },
                )
        await db.commit()
        data = await _get_group_with_options(db, spec_id, x_tenant_id)
        log.info("patch_spec", tenant_id=x_tenant_id, spec_id=spec_id)
        return {"ok": True, "data": data}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("specs.patch_failed", spec_id=spec_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库暂时不可用，请稍后重试")
