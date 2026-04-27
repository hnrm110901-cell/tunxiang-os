"""人群包引擎 API — 人群包CRUD/刷新/预览/预设/成员/趋势

12个端点：
  CRUD (5):
    POST   /                        创建人群包
    GET    /                        人群包列表（分页）
    GET    /{id}                    人群包详情
    PUT    /{id}                    更新人群包
    DELETE /{id}                    删除人群包

  Refresh (1):
    POST   /{id}/refresh            刷新动态人群包

  Preview (1):
    POST   /preview                 预览规则匹配人数

  Presets (2):
    GET    /presets                  预设列表
    POST   /from-preset             从预设创建人群包

  Members (2):
    GET    /{id}/members            成员列表（分页）
    GET    /{id}/members/export     导出全部成员

  Trend (1):
    GET    /{id}/trend              成员趋势（按日）
"""

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel
from services.audience_pack_service import AudiencePackError, AudiencePackService

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/audience-packs", tags=["audience-packs"])

_svc = AudiencePackService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreatePackRequest(BaseModel):
    pack_name: str
    pack_type: str = "dynamic"
    rules: dict = {}
    description: Optional[str] = None
    refresh_interval_hours: int = 24
    store_id: Optional[str] = None
    created_by: str


class UpdatePackRequest(BaseModel):
    pack_name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[dict] = None
    refresh_interval_hours: Optional[int] = None
    store_id: Optional[str] = None


class PreviewRulesRequest(BaseModel):
    rules: dict
    store_id: Optional[str] = None


class CreateFromPresetRequest(BaseModel):
    preset_id: str
    created_by: str
    pack_name: Optional[str] = None
    store_id: Optional[str] = None


# ---------------------------------------------------------------------------
# CRUD 端点
# ---------------------------------------------------------------------------


@router.post("")
async def create_pack(
    req: CreatePackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建人群包"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_pack(
                tenant_id=uuid.UUID(x_tenant_id),
                pack_name=req.pack_name,
                pack_type=req.pack_type,
                rules=req.rules,
                created_by=uuid.UUID(req.created_by),
                db=db,
                description=req.description,
                refresh_interval_hours=req.refresh_interval_hours,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
            )
            await db.commit()
            return ok_response(result)
        except AudiencePackError as exc:
            return error_response(exc.message, exc.code)


@router.get("")
async def list_packs(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    pack_type: Optional[str] = None,
    status: Optional[str] = None,
    store_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """人群包列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_packs(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            pack_type=pack_type,
            status=status,
            store_id=uuid.UUID(store_id) if store_id else None,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/presets")
async def list_presets(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    category: Optional[str] = None,
) -> dict:
    """预设列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_presets(
            uuid.UUID(x_tenant_id),
            db,
            category=category,
        )
        return ok_response(result)


@router.post("/preview")
async def preview_rules(
    req: PreviewRulesRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """预览规则匹配人数"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.preview_rules(
            tenant_id=uuid.UUID(x_tenant_id),
            rules=req.rules,
            db=db,
            store_id=uuid.UUID(req.store_id) if req.store_id else None,
        )
        return ok_response(result)


@router.post("/from-preset")
async def create_from_preset(
    req: CreateFromPresetRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """从预设创建人群包"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_from_preset(
                tenant_id=uuid.UUID(x_tenant_id),
                preset_id=uuid.UUID(req.preset_id),
                created_by=uuid.UUID(req.created_by),
                db=db,
                pack_name=req.pack_name,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
            )
            await db.commit()
            return ok_response(result)
        except AudiencePackError as exc:
            return error_response(exc.message, exc.code)


@router.get("/{pack_id}")
async def get_pack(
    pack_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """人群包详情"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.get_pack(uuid.UUID(x_tenant_id), uuid.UUID(pack_id), db)
            return ok_response(result)
        except AudiencePackError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{pack_id}")
async def update_pack(
    pack_id: str,
    req: UpdatePackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新人群包"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            updates = req.model_dump(exclude_none=True)
            result = await _svc.update_pack(uuid.UUID(x_tenant_id), uuid.UUID(pack_id), updates, db)
            await db.commit()
            return ok_response(result)
        except AudiencePackError as exc:
            return error_response(exc.message, exc.code)


@router.delete("/{pack_id}")
async def delete_pack(
    pack_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除人群包"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.delete_pack(uuid.UUID(x_tenant_id), uuid.UUID(pack_id), db)
            await db.commit()
            return ok_response(result)
        except AudiencePackError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Refresh 端点
# ---------------------------------------------------------------------------


@router.post("/{pack_id}/refresh")
async def refresh_pack(
    pack_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """刷新动态人群包"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.refresh_pack(uuid.UUID(x_tenant_id), uuid.UUID(pack_id), db)
            await db.commit()
            return ok_response(result)
        except AudiencePackError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Members 端点
# ---------------------------------------------------------------------------


@router.get("/{pack_id}/members")
async def list_pack_members(
    pack_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    is_active: Optional[bool] = True,
    page: int = 1,
    size: int = 20,
) -> dict:
    """成员列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_pack_members(
            uuid.UUID(x_tenant_id),
            uuid.UUID(pack_id),
            db,
            is_active=is_active,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/{pack_id}/members/export")
async def export_pack_members(
    pack_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """导出全部成员"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.export_pack_members(
            uuid.UUID(x_tenant_id),
            uuid.UUID(pack_id),
            db,
        )
        return ok_response({"members": result, "total": len(result)})


# ---------------------------------------------------------------------------
# Trend 端点
# ---------------------------------------------------------------------------


@router.get("/{pack_id}/trend")
async def get_pack_trend(
    pack_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    days: int = 30,
) -> dict:
    """成员趋势"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_pack_trend(
            uuid.UUID(x_tenant_id),
            uuid.UUID(pack_id),
            db,
            days=days,
        )
        return ok_response(result)
