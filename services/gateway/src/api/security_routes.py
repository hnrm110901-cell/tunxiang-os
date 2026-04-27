"""
安全合规 API 路由 — Phase 4-B

端点:
  GET  /api/v1/security/audit-logs          — 查询审计日志（分页+过滤）
  GET  /api/v1/security/alerts              — 安全告警（最近24h）
  GET  /api/v1/security/compliance          — 合规状态检查
  GET  /api/v1/security/report/weekly       — 周度安全报告
  POST /api/v1/security/audit-logs/export   — 导出审计日志（触发 DATA_EXPORT 审计）

所有端点需要 X-Tenant-ID header（由 TenantMiddleware 校验）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.roles import PlatformRole, TenantRole

from ..middleware.rbac import UserContext, require_roles
from ..services.audit_log_service import AuditAction, AuditEntry, AuditLogService
from ..services.security_report_service import SecurityReportService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/security", tags=["security"])

# ────────────────────────────────────────────────────────────────────
# 依赖注入
# ────────────────────────────────────────────────────────────────────

_audit_service = AuditLogService()
_report_service = SecurityReportService()


def _get_audit_service() -> AuditLogService:
    return _audit_service


def _get_report_service() -> SecurityReportService:
    return _report_service


async def _get_db(request: Request) -> AsyncSession:
    """从 request.state 获取数据库会话（由 TenantMiddleware 注入）。"""
    db: AsyncSession | None = getattr(request.state, "db", None)
    if db is None:
        raise HTTPException(status_code=500, detail="数据库会话未初始化")
    return db


def _get_tenant_id(request: Request) -> UUID:
    """从 request.state 获取租户 UUID（由 TenantMiddleware 注入）。"""
    tenant_id_str: str | None = getattr(request.state, "tenant_id", None)
    if not tenant_id_str:
        raise HTTPException(status_code=403, detail="缺少 X-Tenant-ID")
    try:
        return UUID(tenant_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的 X-Tenant-ID 格式") from exc


# ────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ────────────────────────────────────────────────────────────────────


class AuditLogExportRequest(BaseModel):
    actor_id: str | None = Field(None, description="按操作人过滤")
    action: str | None = Field(None, description="按操作类型过滤")
    resource_type: str | None = Field(None, description="按资源类型过滤")
    severity: str | None = Field(None, description="按严重级别过滤: info/warning/critical")
    start_time: datetime | None = Field(None, description="起始时间（含）")
    end_time: datetime | None = Field(None, description="截止时间（含）")
    format: str = Field("json", description="导出格式: json / csv")


# ────────────────────────────────────────────────────────────────────
# 路由
# ────────────────────────────────────────────────────────────────────


@router.get("/audit-logs", summary="查询审计日志")
async def list_audit_logs(
    request: Request,
    actor_id: str | None = Query(None, description="按操作人 ID 过滤"),
    action: str | None = Query(None, description="按操作类型过滤，如 auth.login"),
    resource_type: str | None = Query(None, description="按资源类型过滤"),
    severity: str | None = Query(None, description="按严重级别过滤: info/warning/critical"),
    start_time: datetime | None = Query(None, description="起始时间，ISO8601"),
    end_time: datetime | None = Query(None, description="截止时间，ISO8601"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    size: int = Query(20, ge=1, le=200, description="每页条数，最大200"),
    db: AsyncSession = Depends(_get_db),
    audit_svc: AuditLogService = Depends(_get_audit_service),
    # 三权分立：只有 audit_admin（平台）或 auditor（租户内）可查看审计日志
    # system_admin 被明确排除（权限矩阵中无 AUDIT_LOGS 权限）
    _user: UserContext = Depends(require_roles(PlatformRole.AUDIT_ADMIN, TenantRole.AUDITOR)),
) -> JSONResponse:
    """
    分页查询审计日志，支持多维度过滤。
    返回 { ok, data: { items, total, page, size } }
    """
    tenant_id = _get_tenant_id(request)

    result = await audit_svc.query_logs(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
        page=page,
        size=size,
        db=db,
    )
    return JSONResponse({"ok": True, "data": result})


@router.get("/alerts", summary="安全告警")
async def get_security_alerts(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="查询过去 N 小时，最大168（7天）"),
    db: AsyncSession = Depends(_get_db),
    audit_svc: AuditLogService = Depends(_get_audit_service),
    # 安全告警属于审计域，需要 audit_admin 或 security_admin
    _user: UserContext = Depends(
        require_roles(PlatformRole.AUDIT_ADMIN, PlatformRole.SECURITY_ADMIN, TenantRole.AUDITOR)
    ),
) -> JSONResponse:
    """
    返回最近 N 小时内的安全告警，包括：
    - 同一 actor 登录失败 > 5次/小时
    - 任意 CONSTRAINT_OVERRIDE 事件
    - 同一 actor 数据导出 > 3次/小时
    - 凌晨 2-5 点（Asia/Shanghai）的登录事件
    """
    tenant_id = _get_tenant_id(request)

    alerts = await audit_svc.get_security_alerts(
        tenant_id=tenant_id,
        hours=hours,
        db=db,
    )
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "alerts": alerts,
                "total": len(alerts),
                "hours_checked": hours,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )


@router.get("/compliance", summary="合规状态检查")
async def get_compliance_status(
    request: Request,
    db: AsyncSession = Depends(_get_db),
    report_svc: SecurityReportService = Depends(_get_report_service),
) -> JSONResponse:
    """
    实时合规检查清单，包括：
    - RLS 是否启用
    - 过期 token 检测
    - 30天未使用的 app 检测
    - 健康证即将过期的员工数
    - 综合合规分（0-100）
    """
    tenant_id = _get_tenant_id(request)

    compliance = await report_svc.check_compliance_status(
        tenant_id=tenant_id,
        db=db,
    )
    return JSONResponse({"ok": True, "data": compliance})


@router.get("/report/weekly", summary="周度安全报告")
async def get_weekly_report(
    request: Request,
    week_start: date = Query(..., description="周开始日期，格式 YYYY-MM-DD"),
    db: AsyncSession = Depends(_get_db),
    report_svc: SecurityReportService = Depends(_get_report_service),
) -> JSONResponse:
    """
    生成指定周的安全报告汇总，包括：
    - 登录失败次数（按 actor 分组）
    - API 调用量（按 app 分组）
    - 数据导出次数
    - critical 级别事件列表
    - 合规检查项状态
    """
    tenant_id = _get_tenant_id(request)

    report = await report_svc.generate_weekly_report(
        tenant_id=tenant_id,
        week_start=week_start,
        db=db,
    )
    return JSONResponse({"ok": True, "data": report})


@router.post("/audit-logs/export", summary="导出审计日志")
async def export_audit_logs(
    request: Request,
    body: AuditLogExportRequest,
    db: AsyncSession = Depends(_get_db),
    audit_svc: AuditLogService = Depends(_get_audit_service),
    # 导出审计日志是高风险操作，仅允许 audit_admin（三权分立：system_admin 不可导出）
    _user: UserContext = Depends(require_roles(PlatformRole.AUDIT_ADMIN)),
) -> JSONResponse:
    """
    导出审计日志（JSON 格式）。
    导出操作本身会触发 DATA_EXPORT 审计记录。

    注意: 当前返回 JSON，后续可扩展为 CSV 流式下载。
    """
    tenant_id = _get_tenant_id(request)
    actor_id: str = getattr(request.state, "user_id", "unknown")
    ip_address: str | None = request.client.host if request.client else None
    user_agent: str | None = request.headers.get("User-Agent")

    # 查询日志数据（最多导出10000条）
    result = await audit_svc.query_logs(
        tenant_id=tenant_id,
        actor_id=body.actor_id,
        action=body.action,
        resource_type=body.resource_type,
        severity=body.severity,
        start_time=body.start_time,
        end_time=body.end_time,
        page=1,
        size=10000,
        db=db,
    )

    # 记录本次导出操作的审计日志（DATA_EXPORT）
    export_entry = AuditEntry(
        tenant_id=tenant_id,
        action=AuditAction.DATA_EXPORT,
        actor_id=actor_id,
        actor_type="user",
        resource_type="audit_logs",
        resource_id=None,
        severity="warning",
        ip_address=ip_address,
        user_agent=user_agent,
        extra={
            "export_filters": {
                "actor_id": body.actor_id,
                "action": body.action,
                "resource_type": body.resource_type,
                "severity": body.severity,
                "start_time": body.start_time.isoformat() if body.start_time else None,
                "end_time": body.end_time.isoformat() if body.end_time else None,
            },
            "exported_count": result["total"],
            "format": body.format,
        },
    )
    await audit_svc.log(export_entry, db)

    logger.info(
        "audit_logs.exported",
        tenant_id=str(tenant_id),
        actor_id=actor_id,
        exported_count=result["total"],
    )

    return JSONResponse(
        {
            "ok": True,
            "data": {
                "items": result["items"],
                "total": result["total"],
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "format": body.format,
            },
        }
    )
