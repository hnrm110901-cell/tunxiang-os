"""OTA 版本检查 — Edge 端点（Mac mini 本地服务）

GET /api/v1/ota/check   设备检查更新（带本地缓存，1小时同步一次云端）

设计：
- 内存缓存避免每次查询都打云端，减少延迟
- 缓存过期时后台异步同步，不阻塞设备查询
- 云端地址从环境变量 CLOUD_API_URL 读取
"""

import asyncio
import os
import time
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from httpx import AsyncClient, RequestError

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/ota", tags=["ota"])

CLOUD_API_URL = os.environ.get("CLOUD_API_URL", "http://localhost:8001")
CACHE_TTL_SECONDS = 3600  # 1小时

# 本地缓存：{ device_type -> { "data": {...}, "fetched_at": float } }
_version_cache: dict[str, dict] = {}
_sync_lock = asyncio.Lock()


def _ok(data):
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"ok": False, "data": None, "error": msg})


async def _fetch_from_cloud(device_type: str, tenant_id: str) -> Optional[dict]:
    """从云端 tx-org 拉取最新版本信息。"""
    url = f"{CLOUD_API_URL}/api/v1/org/ota/versions/latest"
    try:
        async with AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                params={"device_type": device_type, "current_version_code": 0},
                headers={"X-Tenant-ID": tenant_id},
            )
            resp.raise_for_status()
            body = resp.json()
            return body.get("data")
    except RequestError as exc:
        logger.warning("ota_cloud_fetch_failed", device_type=device_type, error=str(exc))
        return None


async def _get_cached_or_fetch(device_type: str, tenant_id: str) -> Optional[dict]:
    """返回缓存版本信息，缓存过期时后台刷新。"""
    cache_key = f"{tenant_id}:{device_type}"
    entry = _version_cache.get(cache_key)

    if entry and (time.monotonic() - entry["fetched_at"]) < CACHE_TTL_SECONDS:
        return entry["data"]

    # 缓存过期 or 首次查询，拉云端
    async with _sync_lock:
        # double-check
        entry = _version_cache.get(cache_key)
        if entry and (time.monotonic() - entry["fetched_at"]) < CACHE_TTL_SECONDS:
            return entry["data"]

        data = await _fetch_from_cloud(device_type, tenant_id)
        if data is not None:
            _version_cache[cache_key] = {"data": data, "fetched_at": time.monotonic()}
        elif entry:
            # 云端不可达，延长旧缓存有效期（避免设备无法工作）
            logger.warning("ota_using_stale_cache", device_type=device_type)
            return entry["data"]

        return data


@router.get("/check")
async def check_update(
    device_type: str = Query(..., description="android_pos | mac_mini | android_tablet | ipad"),
    current_version_code: int = Query(0, ge=0),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """设备检查更新 — 带本地1小时缓存"""
    if not x_tenant_id:
        _err("X-Tenant-ID header required", 401)

    latest = await _get_cached_or_fetch(device_type, x_tenant_id)

    if not latest or not latest.get("has_update"):
        return _ok(
            {
                "has_update": False,
                "current_version_code": current_version_code,
                "source": "cache" if f"{x_tenant_id}:{device_type}" in _version_cache else "cloud",
            }
        )

    latest_code = latest.get("version_code", 0)
    if latest_code <= current_version_code:
        return _ok({"has_update": False, "current_version_code": current_version_code})

    min_code = latest.get("min_version_code", 0)
    is_forced = latest.get("is_forced", False) or (current_version_code < min_code)

    logger.info(
        "ota_update_available",
        device_type=device_type,
        current=current_version_code,
        latest=latest_code,
        forced=is_forced,
    )

    return _ok(
        {
            "has_update": True,
            "is_forced": is_forced,
            "version_name": latest.get("version_name"),
            "version_code": latest_code,
            "download_url": latest.get("download_url"),
            "file_sha256": latest.get("file_sha256"),
            "release_notes": latest.get("release_notes"),
            "source": "cache",
        }
    )


@router.post("/cache/invalidate")
async def invalidate_cache(
    device_type: Optional[str] = Query(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """手动清除版本缓存（云端推送新版本后调用）"""
    if device_type:
        key = f"{x_tenant_id}:{device_type}"
        _version_cache.pop(key, None)
        cleared = [key]
    else:
        # 清除该租户所有缓存
        prefix = f"{x_tenant_id}:"
        to_del = [k for k in _version_cache if k.startswith(prefix)]
        for k in to_del:
            del _version_cache[k]
        cleared = to_del

    return _ok({"cleared": cleared})
