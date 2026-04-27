"""远程管理 API 路由 — 设备管理 + OTA + 远程命令

端点列表：
  GET   /api/v1/mgmt/device-info    设备详情
  GET   /api/v1/mgmt/system-stats   系统资源（CPU/内存/磁盘/网络）
  POST  /api/v1/mgmt/command        执行远程命令
  GET   /api/v1/mgmt/ota/check      检查更新
  POST  /api/v1/mgmt/ota/update     触发 OTA 更新
  GET   /api/v1/mgmt/ota/status     OTA 当前状态
  GET   /api/v1/mgmt/ota/history    更新历史
  POST  /api/v1/mgmt/ota/rollback   手动回滚
  GET   /api/v1/mgmt/logs           获取最近日志

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/mgmt", tags=["remote-management"])


# ── 辅助 ──


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"ok": False, "data": None, "error": {"code": code, "message": message}},
    )


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise _err("MISSING_TENANT_ID", "X-Tenant-ID header required", 401)
    return x_tenant_id


# ── 请求模型 ──


class RemoteCommandRequest(BaseModel):
    """远程命令请求体。"""

    command_type: str = Field(
        ...,
        description="命令类型: restart_service | clear_cache | sync_now | collect_logs | update_config | health_check",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="命令参数",
    )
    timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description="命令超时（秒）",
    )


class OTAUpdateRequest(BaseModel):
    """OTA 更新触发请求体。"""

    force: bool = Field(
        default=False,
        description="是否强制更新（跳过版本比较）",
    )


# ── 设备信息 ──


@router.get("/device-info")
async def get_device_info(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """GET /api/v1/mgmt/device-info -- 设备详情

    返回设备注册信息、心跳状态、版本号等。
    """
    _require_tenant(x_tenant_id)

    from services.device_registry import get_device_registry

    registry = get_device_registry()
    status = registry.get_status()

    from services.ota_manager import get_ota_manager

    ota = get_ota_manager()

    return _ok(
        {
            **status,
            "ota": {
                "current_version": ota.current_version,
                "current_version_code": ota.current_version_code,
                "state": ota.state.value,
            },
        }
    )


# ── 系统资源 ──


@router.get("/system-stats")
async def get_system_stats(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """GET /api/v1/mgmt/system-stats -- 系统资源指标

    返回 CPU、内存、磁盘、网络、负载等实时指标。
    """
    _require_tenant(x_tenant_id)

    from services.device_registry import _collect_system_stats

    stats = _collect_system_stats()

    return _ok(
        {
            "cpu_usage_pct": stats.cpu_usage_pct,
            "memory": {
                "usage_pct": stats.memory_usage_pct,
                "total_mb": stats.memory_total_mb,
                "used_mb": stats.memory_used_mb,
            },
            "disk": {
                "usage_pct": stats.disk_usage_pct,
                "total_gb": stats.disk_total_gb,
                "used_gb": stats.disk_used_gb,
            },
            "network": {
                "bytes_sent": stats.network_bytes_sent,
                "bytes_recv": stats.network_bytes_recv,
            },
            "load_avg": {
                "1m": stats.load_avg_1m,
                "5m": stats.load_avg_5m,
                "15m": stats.load_avg_15m,
            },
            "uptime_seconds": stats.uptime_seconds,
        }
    )


# ── 远程命令 ──


@router.post("/command")
async def execute_remote_command(
    req: RemoteCommandRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """POST /api/v1/mgmt/command -- 执行远程命令

    仅接受白名单中的命令类型。
    """
    _require_tenant(x_tenant_id)

    from services.remote_command import (
        CommandRequest,
        RemoteCommandService,
        get_remote_command_service,
    )

    service = get_remote_command_service()

    # 白名单检查
    if req.command_type not in RemoteCommandService.ALLOWED_COMMANDS:
        raise _err(
            "COMMAND_NOT_ALLOWED",
            f"Command type '{req.command_type}' is not in whitelist. "
            f"Allowed: {sorted(RemoteCommandService.ALLOWED_COMMANDS)}",
            403,
        )

    import uuid

    cmd_request = CommandRequest(
        command_id=str(uuid.uuid4()),
        command_type=req.command_type,
        params=req.params,
        issued_at=time.time(),
        timeout_seconds=req.timeout_seconds,
    )

    result = await service.execute_command(cmd_request)

    return _ok(
        {
            "command_id": result.command_id,
            "command_type": result.command_type,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "duration_ms": round((result.finished_at - result.started_at) * 1000, 1),
        }
    )


# ── OTA 更新 ──


@router.get("/ota/check")
async def ota_check_update(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """GET /api/v1/mgmt/ota/check -- 检查更新

    对比本地版本与云端最新版本。
    """
    _require_tenant(x_tenant_id)

    from services.ota_manager import get_ota_manager

    ota = get_ota_manager()
    update = await ota.check_update()

    if update is None:
        return _ok(
            {
                "has_update": False,
                "current_version": ota.current_version,
                "current_version_code": ota.current_version_code,
            }
        )

    return _ok(
        {
            "has_update": True,
            "current_version": ota.current_version,
            "current_version_code": ota.current_version_code,
            "available_update": {
                "version_name": update.version_name,
                "version_code": update.version_code,
                "release_notes": update.release_notes,
                "is_forced": update.is_forced,
                "file_size_bytes": update.file_size_bytes,
            },
        }
    )


@router.post("/ota/update")
async def ota_trigger_update(
    req: OTAUpdateRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """POST /api/v1/mgmt/ota/update -- 触发 OTA 更新

    执行完整的更新流程：检查 -> 下载 -> 校验 -> 备份 -> 应用 -> 重启。
    """
    _require_tenant(x_tenant_id)

    from services.ota_manager import OTAState, get_ota_manager

    ota = get_ota_manager()

    # 检查是否正在更新
    if ota.state not in (OTAState.IDLE, OTAState.SUCCESS, OTAState.FAILED):
        raise _err(
            "OTA_IN_PROGRESS",
            f"OTA update is in progress (state: {ota.state.value})",
            409,
        )

    result = await ota.perform_update()
    return _ok(result)


@router.get("/ota/status")
async def ota_get_status(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """GET /api/v1/mgmt/ota/status -- OTA 当前状态

    返回下载进度、当前版本等。
    """
    _require_tenant(x_tenant_id)

    from services.ota_manager import get_ota_manager

    ota = get_ota_manager()
    return _ok(ota.get_status())


@router.get("/ota/history")
async def ota_get_history(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
) -> dict:
    """GET /api/v1/mgmt/ota/history -- 更新历史"""
    _require_tenant(x_tenant_id)

    from services.ota_manager import get_ota_manager

    ota = get_ota_manager()
    return _ok(
        {
            "items": ota.get_history(limit),
            "current_version": ota.current_version,
        }
    )


@router.post("/ota/rollback")
async def ota_rollback(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """POST /api/v1/mgmt/ota/rollback -- 手动回滚到上一版本"""
    _require_tenant(x_tenant_id)

    from services.ota_manager import get_ota_manager

    ota = get_ota_manager()
    success = ota.rollback()

    if not success:
        raise _err("ROLLBACK_FAILED", "Rollback failed, no backup available", 500)

    return _ok({"rolled_back": True, "version": ota.current_version})


# ── 日志 ──


@router.get("/logs")
async def get_recent_logs(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    lines: int = Query(200, ge=10, le=5000, description="返回行数"),
    log_file: str = Query("mac-station.log", description="日志文件名"),
) -> dict:
    """GET /api/v1/mgmt/logs -- 获取最近日志

    从日志目录读取指定日志文件的最近 N 行。
    """
    _require_tenant(x_tenant_id)

    log_dir = Path(os.getenv("LOG_DIR", "/var/log/tunxiang"))

    # 安全检查：防止路径遍历
    safe_name = Path(log_file).name
    log_path = log_dir / safe_name

    if not str(log_path.resolve()).startswith(str(log_dir.resolve())):
        raise _err("INVALID_LOG_FILE", "Invalid log file path", 400)

    if not log_path.exists():
        return _ok(
            {
                "file": safe_name,
                "lines": [],
                "total_lines": 0,
                "note": "Log file not found",
            }
        )

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        recent = all_lines[-lines:]
        return _ok(
            {
                "file": safe_name,
                "lines": [line.rstrip("\n") for line in recent],
                "total_lines": len(all_lines),
                "returned_lines": len(recent),
            }
        )
    except OSError as exc:
        raise _err("LOG_READ_ERROR", f"Failed to read log file: {exc}", 500) from exc


# ── 命令执行历史 ──


@router.get("/commands/history")
async def get_command_history(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
) -> dict:
    """GET /api/v1/mgmt/commands/history -- 远程命令执行历史"""
    _require_tenant(x_tenant_id)

    from services.remote_command import get_remote_command_service

    service = get_remote_command_service()
    return _ok(
        {
            "items": service.get_history(limit),
        }
    )


# ── 心跳历史 ──


@router.get("/heartbeat/history")
async def get_heartbeat_history(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
) -> dict:
    """GET /api/v1/mgmt/heartbeat/history -- 心跳上报历史"""
    _require_tenant(x_tenant_id)

    from services.device_registry import get_device_registry

    registry = get_device_registry()
    return _ok(
        {
            "items": registry.get_heartbeat_history(limit),
        }
    )
