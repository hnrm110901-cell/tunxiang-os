"""POS 遥测路由 — 前端崩溃上报

端点:
  POST /api/v1/telemetry/pos-crash   接收 apps/web-pos ErrorBoundary 上报

限流维度 (tenant_id, device_id)：每 60 秒最多 1 条。理由是崩溃后 ErrorBoundary 常在同一渲染
循环内重复触发，若不节流会瞬间淹没入库链路，真实高价值样本反被稀释。
A1 安全修复：限流键含 tenant_id，避免调试机一日内切多个 tenant 登录因共享 device_id
误伤限流（tenant_A 和 tenant_B 同一物理设备各自独立计窗）。

§XIV 审计约束：
  - 禁 broad except，统一捕获 SQLAlchemyError / ValueError / KeyError。
  - RLS 通过 set_config('app.tenant_id', ..., true) 隔离租户。

A1 安全修复（2026-04-25）—— 跨租户 crash 写入漏洞拦截：
  - X-Tenant-ID Header 必须等于 JWT 解析出的 user.tenant_id（UUID 字符串归一化比较）
  - body 若携带 tenant_id 字段，亦必须等于 user.tenant_id
  - 不一致 → 403 TENANT_MISMATCH，并 asyncio.create_task 写一条审计 deny 事件

统一响应: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审计钩子（Sprint A1 — 非阻塞）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 约定：_audit_hook 是一个可选的 async 可调用对象，签名为 (**kwargs) -> Awaitable[None]。
# 在 report_pos_crash 路由中通过 asyncio.create_task 调度，绝不阻塞主业务。
# 生产接线点：app 启动时注入 tx-trade.write_audit 或 SIEM 客户端；测试可 monkeypatch。
_audit_hook: Optional[Callable[..., Awaitable[None]]] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  JWT 用户上下文依赖（A1 安全修复）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 与 services/tx-trade/src/security/rbac.py 同语义：
#   - gateway/AuthMiddleware 已在 request.state 注入 user_id / tenant_id / role
#   - 本服务直接读 state，不重复解 JWT
#   - TX_AUTH_ENABLED=false 时返回 mock context（与 dev_bypass 对齐），允许单测/本地跳过
#
# 测试可通过 app.dependency_overrides[get_current_user] 注入自定义上下文。

_DEV_TENANT_ID = "a0000000-0000-0000-0000-000000000001"


def _normalize_uuid(value: str) -> str:
    """归一化 UUID 字符串：去空白、转小写、保留连字符；非法则原样返回（由调用方再判定）。"""
    s = (value or "").strip().lower()
    try:
        return str(uuid.UUID(s))
    except (ValueError, AttributeError, TypeError):
        return s


async def get_current_user(request: Request) -> Dict[str, Any]:
    """从 request.state 提取当前 JWT 用户上下文。

    Returns:
        dict: {"user_id": str, "tenant_id": str, "role": str}
              tenant_id 已做 UUID 归一化（小写）。

    Raises:
        HTTPException 401: 未通过 gateway 认证（user_id 为空）。
    """
    if os.getenv("TX_AUTH_ENABLED", "true").lower() == "false":
        # dev/test 环境：与 tx-trade.rbac._dev_bypass 对齐
        return {
            "user_id": "dev-user-mock",
            "tenant_id": _DEV_TENANT_ID,
            "role": "admin",
        }
    state = request.state
    user_id = getattr(state, "user_id", "") or ""
    tenant_id = getattr(state, "tenant_id", "") or ""
    if not user_id or not tenant_id:
        log.warning(
            "telemetry_auth_missing",
            path=getattr(request.url, "path", ""),
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_MISSING", "message": "缺少认证凭据"},
        )
    return {
        "user_id": str(user_id),
        "tenant_id": _normalize_uuid(str(tenant_id)),
        "role": str(getattr(state, "role", "") or ""),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  限流：per-device_id 进程内 TTL 字典
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 进程级去重足够，因为 POS 主机数量有限、单实例即可覆盖；跨实例重复 <1% 可接受。
# 若未来切 Redis，仅替换 _rate_limit_check 实现即可，调用点保持不变。

_RATE_LIMIT_WINDOW_SEC = 60
# A1 安全修复：限流键由纯 device_id 改为 "tenant_id:device_id"。
# 多租户调试机一日内切换登录不会因共享 device_id 误伤限流。
_rate_limit_cache: Dict[str, float] = {}


def _rate_limit_key(tenant_id: str, device_id: str) -> str:
    return f"{tenant_id}:{device_id}"


def _rate_limit_check(tenant_id: str, device_id: str) -> bool:
    """返回 True 表示通过，False 表示被限流。副作用：写入时间戳。

    限流键含 tenant_id：tenant_A 与 tenant_B 同一物理设备各自独立计窗。
    """
    now = time.monotonic()
    key = _rate_limit_key(tenant_id, device_id)
    last = _rate_limit_cache.get(key)
    if last is not None and (now - last) < _RATE_LIMIT_WINDOW_SEC:
        return False
    _rate_limit_cache[key] = now
    # 粗略 GC：当缓存超过 10k 条时丢弃过期项，避免长期内存膨胀
    if len(_rate_limit_cache) > 10000:
        cutoff = now - _RATE_LIMIT_WINDOW_SEC
        stale = [k for k, v in _rate_limit_cache.items() if v < cutoff]
        for k in stale:
            _rate_limit_cache.pop(k, None)
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MAX_STACK_LEN = 8192  # 防止日志炸库；超长前端已截断，后端再兜一层
_MAX_FIELD_LEN = 512


class PosCrashReport(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=_MAX_FIELD_LEN, description="POS 设备指纹或商米 SN")
    route: Optional[str] = Field(None, max_length=_MAX_FIELD_LEN, description="崩溃时前端路由")
    error_stack: Optional[str] = Field(None, max_length=_MAX_STACK_LEN, description="前端捕获的错误堆栈")
    user_action: Optional[str] = Field(None, max_length=_MAX_FIELD_LEN, description="崩溃前最后用户动作摘要")
    store_id: Optional[str] = Field(None, max_length=64, description="门店 UUID（登录前可空）")
    # ── Sprint A1 扩字段（v268），全部 Optional，向前兼容 ───────────────────
    timeout_reason: Optional[str] = Field(
        None, max_length=32,
        description="超时原因：fetch_timeout/saga_timeout/gateway_timeout/rls_deny/disk_io_error/unknown",
    )
    recovery_action: Optional[str] = Field(
        None, max_length=32,
        description="恢复动作：reset/redirect_tables/retry/abort",
    )
    saga_id: Optional[str] = Field(None, max_length=64, description="关联 payment_sagas.saga_id")
    order_no: Optional[str] = Field(None, max_length=64, description="订单号（软关联）")
    severity: Optional[str] = Field(None, max_length=16, description="严重级：fatal/warn/info")
    boundary_level: Optional[str] = Field(
        None, max_length=16, description="ErrorBoundary 层级：root/cashier/unknown"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _schedule_tenant_mismatch_audit(
    *,
    user_tenant_id: str,
    header_tenant_id: str,
    body_tenant_id: Optional[str],
    user_id: str,
    user_role: str,
    device_id: str,
    route_path: str,
    client_ip: Optional[str],
) -> None:
    """跨租户拦截后异步写一条审计 deny 事件（_audit_hook 接 SIEM）。

    约束（§9 + §禁止：审计同步阻塞主业务）：
      - asyncio.create_task 即发即忘
      - hook 失败仅 log.error，不向上抛
    """
    hook = _audit_hook
    if hook is None:
        log.warning(
            "telemetry_tenant_mismatch_no_audit_hook",
            user_tenant_id=user_tenant_id,
            header_tenant_id=header_tenant_id,
            body_tenant_id=body_tenant_id,
            user_id=user_id,
        )
        return

    async def _run() -> None:
        try:
            await hook(
                action="pos_crash_report.deny.tenant_mismatch",
                tenant_id=user_tenant_id,
                user_id=user_id,
                user_role=user_role,
                device_id=device_id,
                route=route_path,
                header_tenant_id=header_tenant_id,
                body_tenant_id=body_tenant_id,
                client_ip=client_ip,
                outcome="deny",
            )
        except (SQLAlchemyError, ValueError, KeyError, RuntimeError) as exc:
            log.error(
                "telemetry_tenant_mismatch_audit_failed",
                error=str(exc),
                user_id=user_id,
            )

    try:
        asyncio.create_task(_run())
    except RuntimeError as exc:
        # 无运行中事件循环（极少出现） — 退化为同步跳过
        log.warning("telemetry_audit_schedule_failed", error=str(exc))


@router.post("/pos-crash")
async def report_pos_crash(
    body: PosCrashReport,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """接收 POS 前端崩溃上报。

    A1 安全修复（2026-04-25）— 跨租户 crash 写入漏洞拦截：
      1. JWT user.tenant_id 必须等于 X-Tenant-ID Header（UUID 归一化比较）
      2. body 若携带 tenant_id（向前兼容字段），亦必须等于 user.tenant_id
      3. 任一不一致 → 403 TENANT_MISMATCH，并 asyncio.create_task 写审计 deny 事件
      4. RLS set_config 一律使用 user.tenant_id（不信任 Header），防御深度

    出于 §XIV 审计合规，500 场景仅返回通用提示，不把 SQLAlchemy 错误原文回显。
    """
    user_tenant_id = _normalize_uuid(user.get("tenant_id", "") or "")
    header_tenant_id_norm = _normalize_uuid(x_tenant_id)

    # body.tenant_id 是向前兼容字段：当前 PosCrashReport schema 未声明，
    # 但若客户端附带（如 dict 形式直传），从原始 JSON 中检出并校验。
    body_tenant_id_raw: Optional[str] = None
    try:
        # FastAPI 已消费 body 流；这里仅在需要时再解析（非阻塞主路径，
        # 失败则跳过并视为无 body tenant_id）。
        raw_json = await request.json()
        if isinstance(raw_json, dict) and "tenant_id" in raw_json:
            val = raw_json.get("tenant_id")
            if isinstance(val, str) and val.strip():
                body_tenant_id_raw = val
    except (ValueError, TypeError, RuntimeError):
        body_tenant_id_raw = None
    body_tenant_id_norm = _normalize_uuid(body_tenant_id_raw) if body_tenant_id_raw else None

    client_ip: Optional[str] = None
    client = getattr(request, "client", None)
    if client is not None:
        client_ip = getattr(client, "host", None)
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        client_ip = fwd.split(",", 1)[0].strip() or client_ip

    # ── 跨租户校验（防 XSS / 恶意员工伪造 X-Tenant-ID 跨租户写入） ──
    header_mismatch = header_tenant_id_norm != user_tenant_id
    body_mismatch = body_tenant_id_norm is not None and body_tenant_id_norm != user_tenant_id
    if header_mismatch or body_mismatch:
        _schedule_tenant_mismatch_audit(
            user_tenant_id=user_tenant_id,
            header_tenant_id=header_tenant_id_norm,
            body_tenant_id=body_tenant_id_norm,
            user_id=str(user.get("user_id", "")),
            user_role=str(user.get("role", "")),
            device_id=body.device_id.strip(),
            route_path=getattr(request.url, "path", ""),
            client_ip=client_ip,
        )
        log.warning(
            "telemetry_tenant_mismatch",
            user_tenant_id=user_tenant_id,
            header_tenant_id=header_tenant_id_norm,
            body_tenant_id=body_tenant_id_norm,
            user_id=user.get("user_id"),
            header_mismatch=header_mismatch,
            body_mismatch=body_mismatch,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "TENANT_MISMATCH",
                "message": "Header/body tenant_id 与认证身份不一致",
            },
        )

    device_id = body.device_id.strip()
    if not device_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "device_id 不能为空"},
        )

    if not _rate_limit_check(user_tenant_id, device_id):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "RATE_LIMITED",
                "message": f"同设备 {_RATE_LIMIT_WINDOW_SEC}s 内仅允许 1 次上报",
            },
        )

    # store_id 合法性：前端若传了必须是 UUID，否则落库会报 22P02
    store_uuid: Optional[str] = None
    if body.store_id:
        try:
            store_uuid = str(uuid.UUID(body.store_id))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PAYLOAD", "message": "store_id 必须是合法 UUID"},
            )

    # saga_id 合法性（可空）
    saga_uuid: Optional[str] = None
    if body.saga_id:
        try:
            saga_uuid = str(uuid.UUID(body.saga_id))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PAYLOAD", "message": "saga_id 必须是合法 UUID"},
            )

    # severity / boundary_level / timeout_reason / recovery_action 枚举白名单校验
    if body.severity is not None and body.severity not in {"fatal", "warn", "info"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "severity 必须是 fatal/warn/info"},
        )
    if body.boundary_level is not None and body.boundary_level not in {
        "root", "cashier", "unknown",
    }:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "boundary_level 必须是 root/cashier/unknown"},
        )
    if body.timeout_reason is not None and body.timeout_reason not in {
        "fetch_timeout", "saga_timeout", "gateway_timeout",
        "rls_deny", "disk_io_error", "unknown",
    }:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "timeout_reason 枚举不合法"},
        )
    if body.recovery_action is not None and body.recovery_action not in {
        "reset", "redirect_tables", "retry", "abort",
    }:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "recovery_action 枚举不合法"},
        )

    # tenant_id 合法性：A1 安全修复后以 JWT user.tenant_id 为唯一可信源。
    # Header 已在跨租户校验中等同性比对过；此处再校验 UUID 合法性以兜底 RLS ::uuid 转换。
    try:
        uuid.UUID(user_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "tenant_id 必须是合法 UUID"},
        )

    report_id = str(uuid.uuid4())

    try:
        await _set_rls(db, user_tenant_id)
        await db.execute(
            text(
                """
                INSERT INTO pos_crash_reports
                    (report_id, tenant_id, store_id, device_id, route,
                     error_stack, user_action,
                     timeout_reason, recovery_action, saga_id, order_no,
                     severity, boundary_level)
                VALUES
                    (:rid::uuid, :tid::uuid, :sid::uuid, :did, :route,
                     :stack, :action,
                     :timeout_reason, :recovery_action, :saga_id::uuid, :order_no,
                     :severity, :boundary_level)
                """
            ),
            {
                "rid": report_id,
                "tid": user_tenant_id,
                "sid": store_uuid,
                "did": device_id,
                "route": body.route,
                "stack": body.error_stack,
                "action": body.user_action,
                "timeout_reason": body.timeout_reason,
                "recovery_action": body.recovery_action,
                "saga_id": saga_uuid,
                "order_no": body.order_no,
                "severity": body.severity,
                "boundary_level": body.boundary_level,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error(
            "pos_crash_report_db_error",
            error=str(exc),
            tenant_id=user_tenant_id,
            device_id=device_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "上报暂时不可用，请稍后重试"},
        )

    # Sprint A1：非阻塞审计钩子（§9 Agent 决策留痕 + CLAUDE.md §禁止 审计同步阻塞主业务）
    # 审计钩子失败绝不影响 POS 主业务：create_task 即发即忘 + 内层 try/except
    hook = _audit_hook
    if hook is not None:
        async def _run_audit_hook() -> None:
            try:
                await hook(
                    action="pos_crash_report",
                    tenant_id=user_tenant_id,
                    user_id=str(user.get("user_id", "")),
                    user_role=str(user.get("role", "")),
                    report_id=report_id,
                    device_id=device_id,
                    route=body.route,
                    saga_id=saga_uuid,
                    order_no=body.order_no,
                    severity=body.severity,
                    boundary_level=body.boundary_level,
                    timeout_reason=body.timeout_reason,
                    recovery_action=body.recovery_action,
                )
            except (SQLAlchemyError, ValueError, KeyError, RuntimeError) as exc:
                log.error(
                    "pos_crash_audit_hook_failed",
                    error=str(exc),
                    report_id=report_id,
                    tenant_id=user_tenant_id,
                )
        try:
            asyncio.create_task(_run_audit_hook())
        except RuntimeError as exc:
            # 无运行中事件循环（极少出现，TestClient 已处理）— 退化为同步跳过
            log.warning("pos_crash_audit_hook_schedule_failed", error=str(exc))

    log.info(
        "pos_crash_reported",
        report_id=report_id,
        tenant_id=user_tenant_id,
        user_id=user.get("user_id"),
        device_id=device_id,
        route=body.route,
        severity=body.severity,
        boundary_level=body.boundary_level,
        saga_id=saga_uuid,
        order_no=body.order_no,
    )
    return {"ok": True, "data": {"report_id": report_id}}
