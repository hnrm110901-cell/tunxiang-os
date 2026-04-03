"""设备心跳注册表路由 — Mac Station 门店级

端点列表：
  POST  /api/v1/devices/register                 设备首次注册（UPSERT）
  POST  /api/v1/devices/{device_id}/heartbeat    上报心跳
  GET   /api/v1/devices                          列出门店所有设备
  GET   /api/v1/devices/alerts                   获取离线告警（>5分钟无心跳）
  GET   /api/v1/devices/{device_id}              查询单台设备详情
  PATCH /api/v1/devices/{device_id}/status       手动设置设备状态（维护模式）

业务规则：
  - register：按 (tenant_id, mac_address) UPSERT，返回 device_id
  - heartbeat：更新 last_heartbeat_at + status='online'，写入 device_heartbeats 日志
               CPU > 90% 或内存 > 90% 时在 extra 中写入 warnings 字段
  - alerts：last_heartbeat_at < NOW()-5min AND status='online' 视为疑似离线

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID 和 X-Store-ID header。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["device-heartbeat"])

# MAC地址格式正则
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

# 心跳超时阈值：5分钟
_HEARTBEAT_TIMEOUT_SECONDS = 5 * 60

# 资源告警阈值
_CPU_WARN_PCT = 90.0
_MEM_WARN_PCT = 90.0

VALID_DEVICE_TYPES = {
    "android_pos",
    "mac_mini",
    "android_tablet",
    "ipad",
    "printer",
    "kds",
}
VALID_STATUSES = {"online", "offline", "maintenance"}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise _err("MISSING_TENANT_ID", "X-Tenant-ID header required")
    return x_tenant_id


def _require_store(x_store_id: str | None) -> str:
    if not x_store_id:
        raise _err("MISSING_STORE_ID", "X-Store-ID header required")
    return x_store_id


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── 内存存储（替代真实 DB，待接入本地 PostgreSQL） ───────────────────────────
# 格式: { "tenant_id:mac_address" -> device_dict }
_device_registry: dict[str, dict] = {}
# 格式: { "device_id" -> [heartbeat_dict, ...] }
_heartbeat_log: dict[str, list[dict]] = {}


def _upsert_device(
    tenant_id: str,
    store_id: str,
    device_type: str,
    device_name: str,
    mac_address: str,
    hardware_model: str | None,
    app_version: str | None,
    os_version: str | None,
    ip_address: str | None,
) -> dict:
    """按 (tenant_id, mac_address) UPSERT 设备记录，返回设备 dict。"""
    import uuid

    key = f"{tenant_id}:{mac_address}"
    existing = _device_registry.get(key)

    if existing:
        # 更新可变字段
        existing["store_id"] = store_id
        existing["device_name"] = device_name
        existing["hardware_model"] = hardware_model or existing.get("hardware_model")
        existing["app_version"] = app_version or existing.get("app_version")
        existing["os_version"] = os_version or existing.get("os_version")
        existing["ip_address"] = ip_address or existing.get("ip_address")
        existing["updated_at"] = _now_utc().isoformat()
        log.info(
            "device_registry_updated",
            device_id=existing["device_id"],
            mac=mac_address,
        )
        return existing

    device_id = str(uuid.uuid4())
    now = _now_utc().isoformat()
    record = {
        "device_id": device_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "device_type": device_type,
        "device_name": device_name,
        "hardware_model": hardware_model,
        "mac_address": mac_address,
        "ip_address": ip_address,
        "app_version": app_version,
        "os_version": os_version,
        "status": "offline",
        "last_heartbeat_at": None,
        "registered_at": now,
        "created_at": now,
        "updated_at": now,
    }
    _device_registry[key] = record
    _heartbeat_log[device_id] = []
    log.info("device_registry_created", device_id=device_id, mac=mac_address, type=device_type)
    return record


def _find_device_by_id(tenant_id: str, device_id: str) -> dict | None:
    """按 device_id 查找设备（校验 tenant_id 隔离）。"""
    for record in _device_registry.values():
        if record["device_id"] == device_id and record["tenant_id"] == tenant_id:
            return record
    return None


def _list_devices_for_store(tenant_id: str, store_id: str) -> list[dict]:
    return [
        r for r in _device_registry.values()
        if r["tenant_id"] == tenant_id and r["store_id"] == store_id
    ]


def _list_devices_for_tenant(tenant_id: str) -> list[dict]:
    return [r for r in _device_registry.values() if r["tenant_id"] == tenant_id]


def _is_stale(device: dict) -> bool:
    """判断设备是否疑似离线（status=online 但超过5分钟无心跳）。"""
    if device.get("status") != "online":
        return False
    last_hb = device.get("last_heartbeat_at")
    if not last_hb:
        return True
    last_dt = datetime.fromisoformat(last_hb)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    elapsed = (_now_utc() - last_dt).total_seconds()
    return elapsed > _HEARTBEAT_TIMEOUT_SECONDS


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────


class DeviceRegisterRequest(BaseModel):
    device_type: str = Field(..., description="android_pos/mac_mini/android_tablet/ipad/printer/kds")
    device_name: str = Field(..., min_length=1, max_length=100, description="可读设备名称，如'1号收银台'")
    hardware_model: Optional[str] = Field(None, max_length=100, description="硬件型号，如'商米T2'")
    mac_address: str = Field(..., description="MAC地址，格式 XX:XX:XX:XX:XX:XX")
    app_version: Optional[str] = Field(None, max_length=50)
    os_version: Optional[str] = Field(None, max_length=100)
    ip_address: Optional[str] = Field(None, max_length=45)

    @field_validator("mac_address")
    @classmethod
    def validate_mac(cls, v: str) -> str:
        if not _MAC_RE.match(v):
            raise ValueError("MAC地址格式无效，需为 XX:XX:XX:XX:XX:XX（十六进制，冒号分隔）")
        return v.upper()

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        if v not in VALID_DEVICE_TYPES:
            raise ValueError(f"device_type 必须为 {sorted(VALID_DEVICE_TYPES)} 之一")
        return v


class HeartbeatRequest(BaseModel):
    cpu_usage_pct: Optional[float] = Field(None, ge=0, le=100, description="CPU使用率 0-100")
    memory_usage_pct: Optional[float] = Field(None, ge=0, le=100, description="内存使用率 0-100")
    disk_usage_pct: Optional[float] = Field(None, ge=0, le=100, description="磁盘使用率 0-100")
    network_latency_ms: Optional[int] = Field(None, ge=0, description="到服务器延迟（毫秒）")
    app_version: Optional[str] = Field(None, max_length=50)
    extra: Optional[dict] = Field(None, description="额外指标，如打印机状态")


class DeviceStatusPatchRequest(BaseModel):
    status: str = Field(..., description="online/offline/maintenance")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status 必须为 {sorted(VALID_STATUSES)} 之一")
        return v


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.post("/api/v1/devices/register")
async def register_device(
    req: DeviceRegisterRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_store_id: str | None = Header(None, alias="X-Store-ID"),
) -> dict:
    """POST /api/v1/devices/register — 设备首次注册（UPSERT）

    按 (tenant_id, mac_address) 去重，设备重启或重装 App 后调用此接口更新信息。
    返回 device_id，后续心跳上报使用此 ID。
    """
    tenant_id = _require_tenant(x_tenant_id)
    store_id = _require_store(x_store_id)

    try:
        device = _upsert_device(
            tenant_id=tenant_id,
            store_id=store_id,
            device_type=req.device_type,
            device_name=req.device_name,
            mac_address=req.mac_address,
            hardware_model=req.hardware_model,
            app_version=req.app_version,
            os_version=req.os_version,
            ip_address=req.ip_address,
        )
    except (KeyError, TypeError) as exc:
        log.error("device_register_error", error=str(exc))
        raise _err("REGISTER_FAILED", f"设备注册失败: {exc}", 500) from exc

    return _ok({
        "device_id": device["device_id"],
        "registered_at": device["registered_at"],
        "status": device["status"],
    })


@router.post("/api/v1/devices/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: str,
    req: HeartbeatRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """POST /api/v1/devices/{device_id}/heartbeat — 上报心跳

    更新 last_heartbeat_at 和 status='online'。
    将心跳指标写入 device_heartbeats 日志。
    CPU > 90% 或内存 > 90% 时在 extra.warnings 中附加告警标记。
    """
    tenant_id = _require_tenant(x_tenant_id)

    device = _find_device_by_id(tenant_id, device_id)
    if device is None:
        raise _err("DEVICE_NOT_FOUND", f"设备 {device_id} 不存在或无权限访问", 404)

    now_str = _now_utc().isoformat()

    # 构建 extra 字段，附加资源告警
    extra: dict = dict(req.extra or {})
    warnings: list[str] = []
    if req.cpu_usage_pct is not None and req.cpu_usage_pct > _CPU_WARN_PCT:
        warnings.append(f"CPU使用率过高: {req.cpu_usage_pct:.1f}%")
    if req.memory_usage_pct is not None and req.memory_usage_pct > _MEM_WARN_PCT:
        warnings.append(f"内存使用率过高: {req.memory_usage_pct:.1f}%")
    if warnings:
        extra["warnings"] = warnings
        log.warning(
            "device_resource_warning",
            device_id=device_id,
            warnings=warnings,
        )

    # 更新注册表状态
    device["status"] = "online"
    device["last_heartbeat_at"] = now_str
    device["updated_at"] = now_str
    if req.app_version:
        device["app_version"] = req.app_version

    # 写入心跳日志
    hb_record = {
        "device_id": device_id,
        "tenant_id": tenant_id,
        "cpu_usage_pct": req.cpu_usage_pct,
        "memory_usage_pct": req.memory_usage_pct,
        "disk_usage_pct": req.disk_usage_pct,
        "network_latency_ms": req.network_latency_ms,
        "app_version": req.app_version or device.get("app_version"),
        "extra": extra,
        "created_at": now_str,
    }
    log_list = _heartbeat_log.setdefault(device_id, [])
    log_list.append(hb_record)
    # 内存中只保留最近 200 条（生产环境由 DB 7天清理策略处理）
    if len(log_list) > 200:
        _heartbeat_log[device_id] = log_list[-200:]

    log.debug("device_heartbeat_received", device_id=device_id, has_warnings=bool(warnings))

    return _ok({
        "device_id": device_id,
        "status": "online",
        "last_heartbeat_at": now_str,
        "warnings": warnings,
    })


@router.get("/api/v1/devices/alerts")
async def get_device_alerts(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_store_id: str | None = Header(None, alias="X-Store-ID"),
) -> dict:
    """GET /api/v1/devices/alerts — 获取疑似离线设备告警

    查询条件：last_heartbeat_at < NOW() - 5分钟 AND status = 'online'
    这些设备心跳丢失，运维需介入排查。

    注意：路由必须在 /{device_id} 前注册，避免 'alerts' 被解析为 device_id。
    """
    tenant_id = _require_tenant(x_tenant_id)
    store_id = x_store_id  # 可选，不提供则查租户全部门店

    if store_id:
        candidates = _list_devices_for_store(tenant_id, store_id)
    else:
        candidates = _list_devices_for_tenant(tenant_id)

    stale_devices = [d for d in candidates if _is_stale(d)]

    alerts = [
        {
            "device_id": d["device_id"],
            "device_name": d["device_name"],
            "device_type": d["device_type"],
            "store_id": d["store_id"],
            "hardware_model": d.get("hardware_model"),
            "last_heartbeat_at": d.get("last_heartbeat_at"),
            "status": d["status"],
        }
        for d in stale_devices
    ]

    log.info(
        "device_alerts_queried",
        tenant_id=tenant_id,
        store_id=store_id,
        alert_count=len(alerts),
    )

    return _ok({"items": alerts, "total": len(alerts)})


@router.get("/api/v1/devices")
async def list_devices(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_store_id: str | None = Header(None, alias="X-Store-ID"),
    status: str | None = Query(None, description="按状态过滤: online/offline/maintenance"),
    device_type: str | None = Query(None, description="按设备类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """GET /api/v1/devices — 列出门店所有设备"""
    tenant_id = _require_tenant(x_tenant_id)
    store_id = _require_store(x_store_id)

    devices = _list_devices_for_store(tenant_id, store_id)

    if status:
        devices = [d for d in devices if d["status"] == status]
    if device_type:
        devices = [d for d in devices if d["device_type"] == device_type]

    total = len(devices)
    offset = (page - 1) * size
    paged = devices[offset: offset + size]

    return _ok({"items": paged, "total": total, "page": page, "size": size})


@router.get("/api/v1/devices/{device_id}")
async def get_device(
    device_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """GET /api/v1/devices/{device_id} — 查询单台设备详情"""
    tenant_id = _require_tenant(x_tenant_id)

    device = _find_device_by_id(tenant_id, device_id)
    if device is None:
        raise _err("DEVICE_NOT_FOUND", f"设备 {device_id} 不存在或无权限访问", 404)

    # 附加最近一次心跳数据
    recent_hb = None
    hb_list = _heartbeat_log.get(device_id, [])
    if hb_list:
        recent_hb = hb_list[-1]

    return _ok({**device, "recent_heartbeat": recent_hb})


@router.patch("/api/v1/devices/{device_id}/status")
async def update_device_status(
    device_id: str,
    req: DeviceStatusPatchRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """PATCH /api/v1/devices/{device_id}/status — 手动设置设备状态

    主要用于将设备置为 'maintenance'（计划维护）或人工标记 'offline'。
    """
    tenant_id = _require_tenant(x_tenant_id)

    device = _find_device_by_id(tenant_id, device_id)
    if device is None:
        raise _err("DEVICE_NOT_FOUND", f"设备 {device_id} 不存在或无权限访问", 404)

    old_status = device["status"]
    device["status"] = req.status
    device["updated_at"] = _now_utc().isoformat()

    log.info(
        "device_status_changed",
        device_id=device_id,
        old_status=old_status,
        new_status=req.status,
    )

    return _ok({
        "device_id": device_id,
        "status": req.status,
        "updated_at": device["updated_at"],
    })
