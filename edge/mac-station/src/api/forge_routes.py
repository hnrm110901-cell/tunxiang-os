"""
ForgeNode API 路由 — mac-station 离线感知决策接口

端点列表：
  GET  /api/v1/forge/status          — ForgeNode 整体状态（连接状态 + 缓冲统计）
  GET  /api/v1/forge/skills          — 所有 Skill 离线状态汇总
  GET  /api/v1/forge/skills/{name}   — 单个 Skill 的离线决策（指定 action 查询）
  POST /api/v1/forge/buffer          — 手动写入离线缓冲
  GET  /api/v1/forge/buffer/stats    — 离线缓冲统计
  POST /api/v1/forge/sync            — 手动触发离线缓冲同步
  POST /api/v1/forge/reload          — 热重载所有 SKILL.yaml 配置
"""
from __future__ import annotations

import asyncio
from typing import Annotated

import structlog
from fastapi import APIRouter, Body, Query, Request

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/forge", tags=["forge-node"])


def _get_forge(request: Request):
    """从 app.state 获取 ForgeNode 单例"""
    forge = getattr(request.app.state, "forge_node", None)
    if forge is None:
        raise RuntimeError("ForgeNode 未初始化，请检查 lifespan 配置")
    return forge


# ─── 1. ForgeNode 整体状态 ────────────────────────────────────────────────────


@router.get("/status", summary="ForgeNode 整体状态")
async def get_forge_status(request: Request) -> dict:
    """
    返回 ForgeNode 当前状态：

    - `is_online`: 门店是否联网（上次检测结果）
    - `last_check_at`: 最后一次连接检测时间（ISO8601）
    - `cloud_url`: 正在 ping 的云端地址
    - `skills_loaded`: 已加载的 Skill 数量
    - `buffer_stats`: 离线缓冲队列统计
    """
    forge = _get_forge(request)
    status = await forge.get_status()
    return {"ok": True, "data": status.model_dump()}


# ─── 2. 所有 Skill 离线状态汇总 ───────────────────────────────────────────────


@router.get("/skills", summary="所有 Skill 离线状态汇总")
async def list_skill_offline_status(request: Request) -> dict:
    """
    返回所有已加载 Skill 的离线能力汇总，按 skill_name 排序。

    每条记录包含：
    - `can_operate`: 是否支持离线操作
    - `actions_available`: 离线可用的操作列表
    - `actions_disabled`: 离线禁用的操作列表
    - `max_offline_hours`: 最长离线支持时间
    """
    forge = _get_forge(request)
    statuses = forge.get_all_skill_status()
    return {
        "ok": True,
        "data": {
            "skills": [s.model_dump() for s in statuses],
            "total": len(statuses),
            "is_online": forge.is_online,
        },
    }


# ─── 3. 单个 Skill 离线决策 ───────────────────────────────────────────────────


@router.get("/skills/{skill_name}", summary="查询单个 Skill 的离线决策")
async def get_skill_offline_decision(
    request: Request,
    skill_name: str,
    action: str = Query(..., description="要查询的操作名称，如 store / retrieve / report"),
) -> dict:
    """
    针对指定 Skill + Action 组合，返回当前状态下的离线决策。

    结果字段：
    - `can_execute`: 是否允许执行
    - `mode`: full / limited / disabled
    - `requires_buffer`: 是否需要写入离线缓冲
    - `local_storage`: 本地存储类型（如 sqlite_wal）
    - `fallback_message`: 拒绝时的友好提示（展示给用户）
    - `reason`: 决策原因（调试用）
    """
    forge = _get_forge(request)
    decision = forge.can_execute(skill_name=skill_name, action=action)
    return {
        "ok": True,
        "data": decision.model_dump(),
    }


# ─── 4. 手动写入离线缓冲 ──────────────────────────────────────────────────────


@router.post("/buffer", summary="手动写入离线缓冲")
async def write_to_buffer(
    request: Request,
    body: Annotated[
        dict,
        Body(
            example={
                "skill_name": "wine-storage",
                "action": "store",
                "tenant_id": "tenant-uuid-here",
                "payload": {
                    "customer_id": "cust-001",
                    "wine_name": "茅台飞天 2022",
                    "quantity": 2,
                    "deposit_fen": 299800,
                },
            }
        ),
    ],
) -> dict:
    """
    手动将操作写入离线缓冲队列。

    通常由 Skill 业务逻辑在确认 `can_execute` 后自动调用，
    此接口供紧急手动补录或测试使用。

    请求体字段：
    - `skill_name`: Skill 名称（必填）
    - `action`: 操作名称（必填）
    - `tenant_id`: 租户 ID（必填，RLS 隔离）
    - `payload`: 操作数据（必填，金额字段单位：分）
    """
    skill_name = body.get("skill_name", "").strip()
    action = body.get("action", "").strip()
    tenant_id = body.get("tenant_id", "").strip()
    payload = body.get("payload")

    if not skill_name:
        return {"ok": False, "error": {"code": "MISSING_FIELD", "message": "skill_name 不能为空"}}
    if not action:
        return {"ok": False, "error": {"code": "MISSING_FIELD", "message": "action 不能为空"}}
    if not tenant_id:
        return {"ok": False, "error": {"code": "MISSING_FIELD", "message": "tenant_id 不能为空"}}
    if not isinstance(payload, dict):
        return {"ok": False, "error": {"code": "INVALID_PAYLOAD", "message": "payload 必须是对象"}}

    forge = _get_forge(request)
    buffer_id = await forge.buffer_operation(
        skill_name=skill_name,
        action=action,
        payload=payload,
        tenant_id=tenant_id,
    )

    logger.info(
        "forge_routes_manual_buffer_write",
        buffer_id=buffer_id,
        skill_name=skill_name,
        action=action,
        tenant_id=tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "buffer_id": buffer_id,
            "skill_name": skill_name,
            "action": action,
            "status": "pending",
            "message": "操作已写入离线缓冲，联网后将自动同步",
        },
    }


# ─── 5. 离线缓冲统计 ──────────────────────────────────────────────────────────


@router.get("/buffer/stats", summary="离线缓冲队列统计")
async def get_buffer_stats(request: Request) -> dict:
    """
    返回当前离线缓冲队列的统计信息：

    - `pending_count`: 待同步数量
    - `syncing_count`: 同步中数量
    - `failed_count`: 失败数量
    - `total_count`: 总记录数
    - `oldest_entry`: 最早未同步记录时间
    - `newest_entry`: 最新未同步记录时间
    - `size_bytes`: SQLite 文件大小（字节）
    """
    forge = _get_forge(request)
    stats = await forge._buffer.get_stats()
    return {"ok": True, "data": stats.model_dump()}


# ─── 6. 手动触发同步 ──────────────────────────────────────────────────────────


@router.post("/sync", summary="手动触发离线缓冲同步")
async def trigger_sync(request: Request) -> dict:
    """
    立即触发离线缓冲队列同步（不等待下次自动检测）。

    - 如果当前离线，同步将失败并返回错误
    - 同步过程在后台异步执行，立即返回任务已提交的响应
    - 查看结果请轮询 `/api/v1/forge/buffer/stats`
    """
    forge = _get_forge(request)

    if not forge.is_online:
        return {
            "ok": False,
            "error": {
                "code": "FORGE_OFFLINE",
                "message": "当前门店处于离线状态，无法同步到云端",
            },
        }

    # 后台执行，不阻塞本次请求
    asyncio.create_task(forge.sync_on_reconnect())

    logger.info("forge_routes_manual_sync_triggered")
    return {
        "ok": True,
        "data": {
            "message": "同步任务已提交，后台异步执行",
            "hint": "请查询 /api/v1/forge/buffer/stats 确认同步进度",
        },
    }


# ─── 7. 热重载 SKILL.yaml 配置 ────────────────────────────────────────────────


@router.post("/reload", summary="热重载所有 SKILL.yaml 配置")
async def reload_skills(request: Request) -> dict:
    """
    重新扫描 services/*/skills/*/SKILL.yaml 并更新 Skill 配置缓存。

    在以下场景使用：
    - 部署新 Skill 或更新 SKILL.yaml 后，无需重启 mac-station
    - 排查离线决策异常时，强制刷新配置
    """
    forge = _get_forge(request)

    loop = asyncio.get_event_loop()
    count = await loop.run_in_executor(None, forge.reload_skills)

    logger.info("forge_routes_skills_reloaded", skills_loaded=count)
    return {
        "ok": True,
        "data": {
            "skills_loaded": count,
            "message": f"已重新加载 {count} 个 Skill 配置",
        },
    }
