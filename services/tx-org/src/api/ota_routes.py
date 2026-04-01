"""OTA 版本管理 API — 云端管理端点

POST /api/v1/org/ota/versions                    发布新版本
GET  /api/v1/org/ota/versions                    版本列表
GET  /api/v1/org/ota/versions/latest             各类型最新版本（设备轮询用）
PATCH /api/v1/org/ota/versions/{id}/deactivate   撤回版本
GET  /api/v1/org/ota/stats                       升级进度统计
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/org/ota", tags=["ota"])

VALID_TARGET_TYPES = {"android_pos", "mac_mini", "android_tablet", "ipad", "all"}


def _ok(data):
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"ok": False, "data": None, "error": msg})


def _get_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        _err("X-Tenant-ID header required", 401)
    return x_tenant_id


class CreateVersionRequest(BaseModel):
    target_type: str
    version_name: str = Field(..., max_length=50)
    version_code: int = Field(..., ge=1)
    min_version_code: int = Field(0, ge=0)
    download_url: str = Field(..., max_length=500, pattern=r'^https?://')
    file_sha256: Optional[str] = Field(None, max_length=64)
    file_size_bytes: Optional[int] = None
    release_notes: Optional[str] = None
    is_forced: bool = False
    rollout_pct: int = Field(100, ge=0, le=100)


@router.post("/versions")
async def create_version(
    req: CreateVersionRequest,
    tenant_id: str = Depends(_get_tenant),
    db: AsyncSession = Depends(get_db),
):
    if req.target_type not in VALID_TARGET_TYPES:
        _err(f"target_type 必须是 {VALID_TARGET_TYPES} 之一")

    version_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO app_versions
                    (id, tenant_id, target_type, version_name, version_code,
                     min_version_code, download_url, file_sha256, file_size_bytes,
                     release_notes, is_forced, rollout_pct, created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :target_type, :version_name, :version_code,
                     :min_version_code, :download_url, :file_sha256, :file_size_bytes,
                     :release_notes, :is_forced, :rollout_pct, NOW(), NOW())
            """),
            {
                "id": version_id, "tenant_id": tenant_id,
                "target_type": req.target_type, "version_name": req.version_name,
                "version_code": req.version_code, "min_version_code": req.min_version_code,
                "download_url": req.download_url, "file_sha256": req.file_sha256,
                "file_size_bytes": req.file_size_bytes, "release_notes": req.release_notes,
                "is_forced": req.is_forced, "rollout_pct": req.rollout_pct,
            },
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        _err(f"版本号 {req.version_code} 已存在 (target_type={req.target_type})", 409)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("ota_create_version_failed", error=str(exc))
        _err("数据库写入失败", 500)

    logger.info("ota_version_created", version_id=str(version_id), version_name=req.version_name)
    return _ok({"version_id": str(version_id), "version_name": req.version_name})


@router.get("/versions")
async def list_versions(
    target_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_get_tenant),
    db: AsyncSession = Depends(get_db),
):
    where = ["(tenant_id = :tenant_id OR tenant_id IS NULL)"]
    params: dict = {"tenant_id": tenant_id, "offset": (page - 1) * size, "limit": size}

    if target_type:
        where.append("target_type = :target_type")
        params["target_type"] = target_type
    if active_only:
        where.append("is_active = TRUE")

    where_sql = " AND ".join(where)
    rows = await db.execute(
        text(f"""
            SELECT id, target_type, version_name, version_code, min_version_code,
                   is_forced, is_active, rollout_pct, release_notes, created_at
            FROM app_versions
            WHERE {where_sql}
            ORDER BY version_code DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r) for r in rows.mappings()]
    for item in items:
        item["id"] = str(item["id"])
        if item.get("created_at"):
            item["created_at"] = item["created_at"].isoformat()

    return _ok({"items": items, "page": page, "size": size})


@router.get("/versions/latest")
async def get_latest_version(
    device_type: str = Query(...),
    current_version_code: int = Query(0, ge=0),
    tenant_id: str = Depends(_get_tenant),
    db: AsyncSession = Depends(get_db),
):
    """设备轮询接口 — 检查是否有更新"""
    row = await db.execute(
        text("""
            SELECT id, version_name, version_code, min_version_code,
                   download_url, file_sha256, file_size_bytes,
                   release_notes, is_forced, rollout_pct
            FROM app_versions
            WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
              AND target_type IN (:device_type, 'all')
              AND is_active = TRUE
            ORDER BY version_code DESC
            LIMIT 1
        """),
        {"tenant_id": tenant_id, "device_type": device_type},
    )
    latest = row.mappings().first()

    if not latest or latest["version_code"] <= current_version_code:
        return _ok({"has_update": False, "current_version_code": current_version_code})

    is_forced = latest["is_forced"] or (current_version_code < latest["min_version_code"])

    return _ok({
        "has_update": True,
        "is_forced": is_forced,
        "version_name": latest["version_name"],
        "version_code": latest["version_code"],
        "download_url": latest["download_url"],
        "file_sha256": latest["file_sha256"],
        "file_size_bytes": latest["file_size_bytes"],
        "release_notes": latest["release_notes"],
    })


@router.patch("/versions/{version_id}/deactivate")
async def deactivate_version(
    version_id: str,
    tenant_id: str = Depends(_get_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        vid = uuid.UUID(version_id)
    except ValueError:
        _err("version_id 格式非法")

    result = await db.execute(
        text("""
            UPDATE app_versions SET is_active = FALSE, updated_at = NOW()
            WHERE id = :id AND (tenant_id = :tenant_id OR tenant_id IS NULL)
        """),
        {"id": vid, "tenant_id": tenant_id},
    )
    await db.commit()
    if result.rowcount == 0:
        _err("版本不存在或无权操作", 404)

    return _ok({"version_id": version_id, "is_active": False})


@router.get("/stats")
async def ota_stats(
    target_type: Optional[str] = Query(None),
    tenant_id: str = Depends(_get_tenant),
    db: AsyncSession = Depends(get_db),
):
    """升级进度统计 — 按设备类型聚合"""
    # 先查各类型最新版本号
    latest_rows = await db.execute(
        text("""
            SELECT DISTINCT ON (target_type) target_type, version_name, version_code
            FROM app_versions
            WHERE (tenant_id = :tenant_id OR tenant_id IS NULL) AND is_active = TRUE
            ORDER BY target_type, version_code DESC
        """),
        {"tenant_id": tenant_id},
    )
    latest_map = {r["target_type"]: r for r in latest_rows.mappings()}

    # 设备统计
    where = "dr.tenant_id = :tenant_id"
    params: dict = {"tenant_id": tenant_id}
    if target_type:
        where += " AND dr.device_type = :device_type"
        params["device_type"] = target_type

    device_rows = await db.execute(
        text(f"""
            SELECT dr.device_type,
                   COUNT(*) as total,
                   SUM(CASE WHEN dr.status = 'online' THEN 1 ELSE 0 END) as online_count,
                   dr.app_version
            FROM device_registry dr
            WHERE {where}
            GROUP BY dr.device_type, dr.app_version
        """),
        params,
    )

    stats: dict = {}
    for row in device_rows.mappings():
        dtype = row["device_type"]
        if dtype not in stats:
            latest = latest_map.get(dtype) or latest_map.get("all")
            stats[dtype] = {
                "device_type": dtype,
                "total": 0,
                "online": 0,
                "latest_version": latest["version_name"] if latest else None,
                "latest_code": latest["version_code"] if latest else None,
                "updated_count": 0,
            }
        stats[dtype]["total"] += row["total"]
        stats[dtype]["online"] += row["online_count"]
        latest_code = stats[dtype]["latest_code"]
        if latest_code and row["app_version"]:
            try:
                # app_version 格式 "3.1.0" → 与 version_code 31000 比较
                parts = row["app_version"].split(".")
                code = int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2]) if len(parts) == 3 else 0
                if code >= latest_code:
                    stats[dtype]["updated_count"] += row["total"]
            except (ValueError, IndexError):
                pass

    result = []
    for s in stats.values():
        total = s["total"]
        s["update_pct"] = round(100 * s["updated_count"] / total, 1) if total else 0
        result.append(s)

    return _ok({"stats": result})
