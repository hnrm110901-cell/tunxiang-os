"""
演示前一键巡检 API 路由 — Week 3 P0 交付项

端点:
  GET  /api/v1/demo/health-check  — 对所有微服务、数据库及关键业务路径发起健康探测，
                                     返回 go/no-go 裁决 + 每服务状态 + 耗时 + 修复建议

用途:
  在每次对外演示前执行本接口，快速确认系统就绪度。
  设计为幂等轮询接口，可每日重复使用。

所有端点需要 X-Tenant-ID header（由 TenantMiddleware 注入）。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/demo", tags=["demo-healthcheck"])

# ────────────────────────────────────────────────────────────────────
# 常量：服务注册表
# ────────────────────────────────────────────────────────────────────

_SERVICES: list[dict] = [
    {"name": "gateway", "port": 8000, "health_path": "/health"},
    {"name": "tx-trade", "port": 8001, "health_path": "/health"},
    {"name": "tx-menu", "port": 8002, "health_path": "/health"},
    {"name": "tx-member", "port": 8003, "health_path": "/health"},
    {"name": "tx-growth", "port": 8004, "health_path": "/health"},
    {"name": "tx-ops", "port": 8005, "health_path": "/health"},
    {"name": "tx-supply", "port": 8006, "health_path": "/health"},
    {"name": "tx-finance", "port": 8007, "health_path": "/health"},
    {"name": "tx-agent", "port": 8008, "health_path": "/health"},
    {"name": "tx-analytics", "port": 8009, "health_path": "/health"},
    {"name": "tx-brain", "port": 8010, "health_path": "/health"},
    {"name": "tx-intel", "port": 8011, "health_path": "/health"},
    {"name": "tx-org", "port": 8012, "health_path": "/health"},
]

# HTTP 探测超时（秒）
_HTTP_TIMEOUT = 3.0

# 关键业务路径探测：(label, service_name, port, path, method)
_CRITICAL_PATHS: list[dict] = [
    {
        "label": "order_creation",
        "description": "收银下单链路",
        "service": "tx-trade",
        "port": 8001,
        "path": "/health",
        "method": "GET",
    },
    {
        "label": "kds_push",
        "description": "KDS出餐推送链路",
        "service": "tx-trade",
        "port": 8001,
        "path": "/health",
        "method": "GET",
    },
    {
        "label": "daily_settlement",
        "description": "日清日结链路",
        "service": "tx-ops",
        "port": 8005,
        "path": "/health",
        "method": "GET",
    },
]

# ────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ────────────────────────────────────────────────────────────────────


class ServiceCheckResult(BaseModel):
    name: str = Field(description="服务名称")
    port: int = Field(description="服务端口")
    status: str = Field(description="up / down / timeout")
    http_status_code: Optional[int] = Field(None, description="HTTP 状态码，探测失败时为 null")
    response_time_ms: float = Field(description="响应耗时（毫秒）")
    error: Optional[str] = Field(None, description="错误描述，正常时为 null")


class CriticalPathResult(BaseModel):
    label: str = Field(description="检查标识")
    description: str = Field(description="业务路径说明")
    service: str = Field(description="所属服务")
    status: str = Field(description="ok / fail")
    response_time_ms: float = Field(description="响应耗时（毫秒）")
    error: Optional[str] = Field(None, description="错误描述")


class DBCheckResult(BaseModel):
    status: str = Field(description="ok / fail")
    response_time_ms: float = Field(description="查询耗时（毫秒）")
    error: Optional[str] = Field(None, description="错误描述")


class DemoHealthCheckResponse(BaseModel):
    verdict: str = Field(description="go / no-go")
    checked_at: str = Field(description="检查时间 ISO8601")
    total_services: int = Field(description="探测的服务总数")
    services_up: int = Field(description="健康服务数")
    services_down: int = Field(description="异常服务数")
    services: list[ServiceCheckResult] = Field(description="每服务检查详情")
    db: DBCheckResult = Field(description="数据库连通性检查")
    critical_paths: list[CriticalPathResult] = Field(description="关键业务路径检查")
    recommendations: list[str] = Field(description="修复建议列表（为空表示系统就绪）")


# ────────────────────────────────────────────────────────────────────
# 内部探测函数
# ────────────────────────────────────────────────────────────────────


async def _probe_service(
    client: httpx.AsyncClient,
    name: str,
    port: int,
    health_path: str,
) -> ServiceCheckResult:
    """对单个服务发起 HTTP GET 健康探测，返回结构化结果。"""
    url = f"http://localhost:{port}{health_path}"
    start = time.monotonic()
    try:
        resp = await client.get(url, timeout=_HTTP_TIMEOUT)
        elapsed_ms = (time.monotonic() - start) * 1000
        status = "up" if resp.status_code < 500 else "down"
        return ServiceCheckResult(
            name=name,
            port=port,
            status=status,
            http_status_code=resp.status_code,
            response_time_ms=round(elapsed_ms, 2),
            error=None if status == "up" else f"HTTP {resp.status_code}",
        )
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.warning("demo_healthcheck.service_timeout", service=name, port=port)
        return ServiceCheckResult(
            name=name,
            port=port,
            status="timeout",
            http_status_code=None,
            response_time_ms=round(elapsed_ms, 2),
            error=f"连接超时（>{_HTTP_TIMEOUT}s）",
        )
    except httpx.ConnectError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.warning("demo_healthcheck.service_connect_error", service=name, port=port, error=str(exc))
        return ServiceCheckResult(
            name=name,
            port=port,
            status="down",
            http_status_code=None,
            response_time_ms=round(elapsed_ms, 2),
            error=f"连接失败: {exc}",
        )
    except httpx.RequestError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.warning("demo_healthcheck.service_request_error", service=name, port=port, error=str(exc))
        return ServiceCheckResult(
            name=name,
            port=port,
            status="down",
            http_status_code=None,
            response_time_ms=round(elapsed_ms, 2),
            error=f"请求错误: {exc}",
        )


async def _probe_critical_path(
    client: httpx.AsyncClient,
    label: str,
    description: str,
    service: str,
    port: int,
    path: str,
    method: str,
) -> CriticalPathResult:
    """对关键业务链路发起可达性探测。"""
    url = f"http://localhost:{port}{path}"
    start = time.monotonic()
    try:
        if method.upper() == "GET":
            resp = await client.get(url, timeout=_HTTP_TIMEOUT)
        else:
            resp = await client.request(method.upper(), url, timeout=_HTTP_TIMEOUT)
        elapsed_ms = (time.monotonic() - start) * 1000
        status = "ok" if resp.status_code < 500 else "fail"
        return CriticalPathResult(
            label=label,
            description=description,
            service=service,
            status=status,
            response_time_ms=round(elapsed_ms, 2),
            error=None if status == "ok" else f"HTTP {resp.status_code}",
        )
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CriticalPathResult(
            label=label,
            description=description,
            service=service,
            status="fail",
            response_time_ms=round(elapsed_ms, 2),
            error=f"连接超时（>{_HTTP_TIMEOUT}s）",
        )
    except httpx.ConnectError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CriticalPathResult(
            label=label,
            description=description,
            service=service,
            status="fail",
            response_time_ms=round(elapsed_ms, 2),
            error=f"连接失败: {exc}",
        )
    except httpx.RequestError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return CriticalPathResult(
            label=label,
            description=description,
            service=service,
            status="fail",
            response_time_ms=round(elapsed_ms, 2),
            error=f"请求错误: {exc}",
        )


async def _probe_db() -> DBCheckResult:
    """探测本地 PostgreSQL 连通性（通过 ORM session 执行 SELECT 1）。"""
    start = time.monotonic()
    try:
        from sqlalchemy import text

        from shared.ontology.src.database import async_session_factory

        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
        elapsed_ms = (time.monotonic() - start) * 1000
        return DBCheckResult(status="ok", response_time_ms=round(elapsed_ms, 2), error=None)
    except ImportError:
        elapsed_ms = (time.monotonic() - start) * 1000
        return DBCheckResult(
            status="fail",
            response_time_ms=round(elapsed_ms, 2),
            error="数据库模块未配置（ImportError）",
        )
    except OSError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error("demo_healthcheck.db_os_error", error=str(exc), exc_info=True)
        return DBCheckResult(
            status="fail",
            response_time_ms=round(elapsed_ms, 2),
            error=f"网络/IO 错误: {exc}",
        )
    except RuntimeError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error("demo_healthcheck.db_runtime_error", error=str(exc), exc_info=True)
        return DBCheckResult(
            status="fail",
            response_time_ms=round(elapsed_ms, 2),
            error=f"运行时错误: {exc}",
        )


def _build_recommendations(
    services: list[ServiceCheckResult],
    db: DBCheckResult,
    critical_paths: list[CriticalPathResult],
) -> list[str]:
    """根据探测结果生成人类可读的修复建议。"""
    recs: list[str] = []

    # 数据库
    if db.status != "ok":
        recs.append(f"[CRITICAL] 数据库不可达，请检查 PostgreSQL 服务状态。错误: {db.error}")

    # 关键路径
    for cp in critical_paths:
        if cp.status != "ok":
            recs.append(
                f"[CRITICAL] 关键链路 [{cp.description}] 不可用（{cp.service}），演示前必须恢复。错误: {cp.error}"
            )

    # 服务
    down_services = [s for s in services if s.status in ("down", "timeout")]
    for svc in down_services:
        recs.append(
            f"[WARNING] 服务 {svc.name}（:{svc.port}）{svc.status}，"
            f"请执行 `docker compose up {svc.name} -d` 或检查进程。错误: {svc.error}"
        )

    # 慢响应提示（>1000ms 视为警告）
    slow_services = [s for s in services if s.status == "up" and s.response_time_ms > 1000]
    for svc in slow_services:
        recs.append(
            f"[INFO] 服务 {svc.name} 响应较慢（{svc.response_time_ms:.0f}ms），演示时可能影响体验，建议重启服务预热。"
        )

    return recs


# ────────────────────────────────────────────────────────────────────
# 路由
# ────────────────────────────────────────────────────────────────────


@router.get(
    "/health-check",
    summary="演示前一键巡检",
    response_description="系统就绪度报告，含 go/no-go 裁决",
)
async def demo_health_check(request: Request) -> dict:
    """
    演示前一键巡检。

    并发探测所有 14 个微服务、数据库连通性及三条关键业务链路（下单/KDS推送/日结），
    返回整体 **go / no-go** 裁决 + 每项详情 + 修复建议。

    - 探测超时：单服务 3 秒
    - 所有探测并发执行，总体耗时约 = max(单项耗时)
    - 接口幂等，可每日演示前重复调用
    """
    tenant_id: str | None = getattr(request.state, "tenant_id", None)

    logger.info(
        "demo_healthcheck.started",
        tenant_id=str(tenant_id) if tenant_id else None,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )

    async with httpx.AsyncClient() as client:
        # 并发探测所有服务 + 关键路径 + DB
        service_tasks = [_probe_service(client, svc["name"], svc["port"], svc["health_path"]) for svc in _SERVICES]
        critical_tasks = [
            _probe_critical_path(
                client,
                cp["label"],
                cp["description"],
                cp["service"],
                cp["port"],
                cp["path"],
                cp["method"],
            )
            for cp in _CRITICAL_PATHS
        ]

        results = await asyncio.gather(
            *service_tasks,
            *critical_tasks,
            _probe_db(),
        )

    n_services = len(_SERVICES)
    n_critical = len(_CRITICAL_PATHS)

    service_results: list[ServiceCheckResult] = list(results[:n_services])  # type: ignore[arg-type]
    critical_results: list[CriticalPathResult] = list(results[n_services : n_services + n_critical])  # type: ignore[arg-type]
    db_result: DBCheckResult = results[-1]  # type: ignore[assignment]

    services_up = sum(1 for s in service_results if s.status == "up")
    services_down = len(service_results) - services_up

    recommendations = _build_recommendations(service_results, db_result, critical_results)

    # go = 数据库正常 + 所有关键路径正常 + 至少 P0 服务（trade/menu/member/ops/agent）在线
    p0_service_names = {"tx-trade", "tx-menu", "tx-member", "tx-ops", "tx-agent"}
    p0_up = all(s.status == "up" for s in service_results if s.name in p0_service_names)
    critical_all_ok = all(cp.status == "ok" for cp in critical_results)
    db_ok = db_result.status == "ok"

    verdict = "go" if (db_ok and p0_up and critical_all_ok) else "no-go"

    response_data = DemoHealthCheckResponse(
        verdict=verdict,
        checked_at=datetime.now(timezone.utc).isoformat(),
        total_services=len(service_results),
        services_up=services_up,
        services_down=services_down,
        services=service_results,
        db=db_result,
        critical_paths=critical_results,
        recommendations=recommendations,
    )

    logger.info(
        "demo_healthcheck.completed",
        verdict=verdict,
        services_up=services_up,
        services_down=services_down,
        db_status=db_result.status,
        tenant_id=str(tenant_id) if tenant_id else None,
    )

    return ok(response_data.model_dump())
