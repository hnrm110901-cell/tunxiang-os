"""tx-trade 内部 RBAC 依赖 — Sprint A4

用法：
    from src.security.rbac import require_role, require_mfa, UserContext

    @router.post("/refund")
    async def api_refund(
        body: RefundReq,
        request: Request,
        user: UserContext = Depends(require_role("store_manager", "admin")),
    ):
        ...

语义（与 gateway/src/middleware/rbac.py 对齐）：
    - 未认证（request.state.user_id 为空）→ 401 AUTH_MISSING
    - role 不在允许集合 → 403 ROLE_FORBIDDEN
    - require_mfa 且 request.state.mfa_verified 为 False → 403 MFA_REQUIRED

依赖链：
    gateway/AuthMiddleware 已将 JWT claims 注入 request.state（user_id /
    tenant_id / role / mfa_verified）。本装饰器直接读 state，不重复解 JWT，
    同一请求同一份用户上下文。

开发/测试模式：
    环境变量 TX_AUTH_ENABLED=false 时注入 mock UserContext（dev-user-mock /
    admin 角色），与 gateway AuthMiddleware 的 dev_bypass 行为保持一致。
    现有 tx-trade 单元测试通过该变量跳过 JWT 验证。

所有决策通过 structlog 记录 rbac_denied / rbac_mfa_required，后续接入 SIEM。
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Callable

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)


# RFC 4122 NIL UUID — 用于未认证请求的 audit tenant_id 兜底。
# 选择 NIL 而非任何真实租户 UUID 的理由：
#   1. PG 上 trade_audit_logs.tenant_id 是 UUID NOT NULL；空串 cast 失败 → 审计永久丢失。
#   2. 不能使用攻击者伪造的 X-Tenant-ID 作为 audit tenant_id —— 否则攻击者可往任意
#      受害租户的 audit 表注入污染行（破坏取证 + 误导 SIEM）。
#   3. NIL UUID 不与任何真实租户冲突（gen_random_uuid() 永远不返回 NIL）。
#   4. audit_admin 可单独 SELECT NIL 租户的 audit 表，盘查所有未认证扫描痕迹。
_NIL_TENANT_UUID: str = "00000000-0000-0000-0000-000000000000"


def _is_valid_uuid_str(value: str | None) -> bool:
    """检查字符串是否是合法 UUID（用于过滤 X-Tenant-ID header 防 log poisoning）。"""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _resolve_audit_for_unauthenticated(
    request: Request, ctx_tenant_id: str,
) -> tuple[str, str | None]:
    """为 deny 审计 resolve tenant_id + 取证后缀。

    决策规则（401 与 ctx 缺 tenant_id 的合并路径）：
      - ctx_tenant_id 非空（已认证或 gateway 注入了 state.tenant_id）→ 直接返回，不附加后缀
      - ctx_tenant_id 空：
          - 永远使用 NIL UUID 写入 audit（不让攻击者污染受害租户表）
          - 若 X-Tenant-ID header 是合法 UUID → 作为 probed_tenant 进 reason 取证
          - 若 X-Tenant-ID 非 UUID / 缺失 → 不附加后缀（防 log poisoning）

    Returns:
        (tenant_id_for_audit, reason_suffix_or_None)
    """
    if ctx_tenant_id:
        return ctx_tenant_id, None

    forged_tenant: str | None = None
    if hasattr(request, "headers"):
        candidate = (request.headers.get("X-Tenant-ID") or "").strip()
        if _is_valid_uuid_str(candidate):
            forged_tenant = candidate

    suffix = f"probed_tenant={forged_tenant}" if forged_tenant else None
    return _NIL_TENANT_UUID, suffix


@dataclass(frozen=True)
class UserContext:
    """从 request.state 提取的用户上下文快照。

    字段与 gateway AuthMiddleware 注入的 state 字段一一对应。
    client_ip 额外从 request.client.host 读取，供审计日志使用。
    """

    user_id: str
    tenant_id: str
    role: str
    mfa_verified: bool
    store_id: str | None
    client_ip: str | None


def extract_user_context(request: Request) -> UserContext:
    """从 request.state 提取 UserContext。

    gateway AuthMiddleware 在 JWT 验证通过后填充以下字段；
    未认证请求的 user_id 为 None / ""。
    """
    state = request.state
    client = getattr(request, "client", None)
    client_ip = getattr(client, "host", None) if client else None
    x_fwd = request.headers.get("X-Forwarded-For") if hasattr(request, "headers") else None
    if x_fwd:
        # X-Forwarded-For 取第一段（原始客户端）
        client_ip = x_fwd.split(",", 1)[0].strip() or client_ip

    return UserContext(
        user_id=getattr(state, "user_id", "") or "",
        tenant_id=getattr(state, "tenant_id", "") or "",
        role=getattr(state, "role", "") or "",
        mfa_verified=bool(getattr(state, "mfa_verified", False)),
        store_id=getattr(state, "store_id", None),
        client_ip=client_ip,
    )


def _dev_bypass() -> bool:
    """与 gateway AuthMiddleware 同语义：TX_AUTH_ENABLED=false 时跳过 RBAC。

    仅用于本地单元测试与开发环境，生产环境必须 true。
    """
    return os.getenv("TX_AUTH_ENABLED", "true").lower() == "false"


# 屯象 OS 项目环境约定（gitops/ + shared/feature_flags/flag_client.py 已采纳）：
#   TUNXIANG_ENV ∈ {dev (默认), test, uat, pilot, edge, prod}
# 仅 "prod" 视为生产环境；其他值（含未设置）允许 dev_bypass 以便单测 / staging。
_PRODUCTION_ENV_VALUES: frozenset[str] = frozenset({"prod"})


class DevBypassInProductionError(RuntimeError):
    """tx-trade 在生产环境（TUNXIANG_ENV=prod）启动时拒绝 TX_AUTH_ENABLED=false。

    §19 复审 R-A4-7：dev_bypass 短路会让所有 RBAC 检查失效**且不留任何
    deny 审计**。一次 ConfigMap 误写、helm values 误覆盖、migration 脚本
    临时设置忘恢复，整个 tx-trade 服务的权限闸门即静默失效——与
    R-补2-1 请求重放伪造同等级的安全风险。

    本异常在 lifespan startup 抛出，让 k8s readiness probe 失败 / 容器
    Crashloop，运维必须修复配置才能恢复服务。fail loud > fail silent。
    """


def assert_no_dev_bypass_in_production() -> None:
    """tx-trade 启动门禁：拒绝生产环境 TX_AUTH_ENABLED=false 配置漂移。

    在 lifespan 早期同步调用。识别 "生产" 用项目约定的 TUNXIANG_ENV=prod；
    其他环境 (dev/test/uat/pilot/edge) 仍允许 dev_bypass 以便单测 / staging
    调试。值匹配大小写无关。

    Raises:
        DevBypassInProductionError: 当 TUNXIANG_ENV=prod 且 TX_AUTH_ENABLED=false。
    """
    env_raw = os.getenv("TUNXIANG_ENV", "dev")
    env = (env_raw or "").strip().lower()
    if env not in _PRODUCTION_ENV_VALUES:
        return  # 非生产环境，不拦
    if not _dev_bypass():
        return  # TX_AUTH_ENABLED=true（或未设置），生产正常路径

    auth_raw = os.getenv("TX_AUTH_ENABLED")
    raise DevBypassInProductionError(
        "Refusing to start tx-trade in production with TX_AUTH_ENABLED=false. "
        "dev_bypass would silently disable all RBAC + deny audit. "
        f"Current: TUNXIANG_ENV={env_raw!r}, TX_AUTH_ENABLED={auth_raw!r}. "
        "If genuinely production, set TX_AUTH_ENABLED=true and use feature "
        "flags / per-route bypass — never disable the global RBAC switch."
    )


def _mock_user_context() -> UserContext:
    return UserContext(
        user_id="dev-user-mock",
        tenant_id="a0000000-0000-0000-0000-000000000001",
        role="admin",
        mfa_verified=True,
        store_id=None,
        client_ip="127.0.0.1",
    )


def require_role(*allowed_roles: str) -> Callable:
    """依赖工厂：要求当前用户角色在 allowed_roles 之内。

    401 AUTH_MISSING   — 无认证
    403 ROLE_FORBIDDEN — 角色不匹配
    """
    allowed = {r for r in allowed_roles if r}

    async def _dep(request: Request) -> UserContext:
        if _dev_bypass():
            return _mock_user_context()
        ctx = extract_user_context(request)
        if not ctx.user_id:
            logger.warning(
                "rbac_auth_missing",
                path=getattr(request.url, "path", ""),
                allowed=sorted(allowed),
            )
            raise HTTPException(status_code=401, detail="AUTH_MISSING")
        if ctx.role not in allowed:
            logger.warning(
                "rbac_denied",
                user_id=ctx.user_id,
                user_role=ctx.role,
                allowed=sorted(allowed),
                path=getattr(request.url, "path", ""),
            )
            raise HTTPException(status_code=403, detail="ROLE_FORBIDDEN")
        return ctx

    return _dep


def require_mfa(*allowed_roles: str) -> Callable:
    """依赖工厂：在 require_role 基础上叠加 MFA 校验。

    用于大额减免 / 退款等高风险写操作。
    未 MFA → 403 MFA_REQUIRED。
    """
    base = require_role(*allowed_roles)

    async def _dep(request: Request) -> UserContext:
        if _dev_bypass():
            return _mock_user_context()
        ctx = await base(request)
        if not ctx.mfa_verified:
            logger.warning(
                "rbac_mfa_required",
                user_id=ctx.user_id,
                user_role=ctx.role,
                path=getattr(request.url, "path", ""),
            )
            raise HTTPException(status_code=403, detail="MFA_REQUIRED")
        return ctx

    return _dep


# ──────────────────────────────────────────────────────────────────────────
#  Audit-aware 包装（Sprint A4 R-补1-1 / Tier1）
#  在拒绝路径（401/403）抛 HTTPException **之前** 写入 trade_audit_logs
#  result='deny' 行，关闭 §19 审查发现的"deny 审计缺失"阻塞。
# ──────────────────────────────────────────────────────────────────────────


# 延迟 import 避免循环：rbac.py 是底层模块，trade_audit_log 依赖 sqlalchemy
# 在生产 import 链路上是可用的；本模块仅在 wrapper 内部用到。
def _audit_deny_safe(
    *,
    db,
    tenant_id: str,
    store_id: str | None,
    user_id: str,
    user_role: str,
    action: str,
    reason: str,
    severity: str,
    client_ip: str | None,
    request_id: str | None,
):
    """同步触发 audit_deny。返回一个 awaitable；调用方决定是否 await。

    单独成函数便于单测 monkeypatch（避免直接 import 路径绑定）。
    """
    from ..services.trade_audit_log import audit_deny  # noqa: PLC0415

    return audit_deny(
        db,
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user_id,
        user_role=user_role,
        action=action,
        reason=reason,
        severity=severity,
        client_ip=client_ip,
        request_id=request_id,
    )


def _import_get_db() -> Callable:
    """懒加载 shared.ontology.src.database.get_db。

    rbac.py 不强依赖 ontology 模块（让单测更轻），仅在 audit-aware 装饰器
    实际被调用时 import；测试可通过参数注入 db_provider 替换。
    """
    from shared.ontology.src.database import get_db  # noqa: PLC0415
    return get_db


def require_role_audited(
    action: str,
    *allowed_roles: str,
    severity_on_deny: str = "warn",
    db_provider: Callable | None = None,
) -> Callable:
    """audit-aware 版 require_role：拒绝时写入 trade_audit_logs result='deny'。

    与 require_role 完全等价的成功语义；额外在 401/403 抛出 **之前** 写
    一条 audit 行，让"谁在哪个时间点对哪个 action 被拒"可追溯。

    Args:
        action: 业务动作标识（refund.apply / discount.apply / payment.create）
        allowed_roles: 允许的角色集合，转发给 require_role
        severity_on_deny: SIEM 严重级，默认 warn；高敏感场景（高额折扣 / 跨租户
            探测）调用方可传 error/critical
        db_provider: 测试用 — 不为 None 时跳过 shared.ontology import，直接用注入。
            生产保持 None，由 _import_get_db() 懒加载。

    Returns:
        FastAPI Dependency（接受 request + db）。
    """
    from fastapi import Depends  # noqa: PLC0415

    base = require_role(*allowed_roles)
    _get_db = db_provider if db_provider is not None else _import_get_db()

    async def _dep(request: Request, db=Depends(_get_db)) -> UserContext:
        try:
            return await base(request)
        except HTTPException as exc:
            # 拒绝路径：先写 deny 审计，再原样抛出（响应形状 / 状态码不变）
            ctx = extract_user_context(request)
            base_reason = (
                str(exc.detail) if isinstance(exc.detail, str) else exc.detail.__class__.__name__
            )
            # 401 / ctx 缺 tenant 路径：用 NIL UUID + 把伪造的 X-Tenant-ID 进 reason
            audit_tenant_id, reason_suffix = _resolve_audit_for_unauthenticated(
                request, ctx.tenant_id,
            )
            reason = (
                f"{base_reason} | {reason_suffix}" if reason_suffix else base_reason
            )
            try:
                await _audit_deny_safe(
                    db=db,
                    tenant_id=audit_tenant_id,
                    store_id=ctx.store_id,
                    user_id=ctx.user_id,
                    user_role=ctx.role,
                    action=action,
                    reason=reason,
                    severity=severity_on_deny,
                    client_ip=ctx.client_ip,
                    request_id=request.headers.get("X-Request-Id")
                    if hasattr(request, "headers")
                    else None,
                )
            except Exception:  # noqa: BLE001 — 审计失败绝不影响 403/401 响应
                logger.error(
                    "audit_deny_call_failed",
                    action=action,
                    user_id=ctx.user_id,
                    reason=reason,
                    exc_info=True,
                )
            raise

    return _dep


def require_mfa_audited(
    action: str,
    *allowed_roles: str,
    severity_on_deny: str = "error",
    db_provider: Callable | None = None,
) -> Callable:
    """audit-aware 版 require_mfa：MFA 缺失时写 deny 审计（severity 默认 error）。

    高额减免 / 退款 / 跨租户探测等高风险动作在被拒时应触发 SIEM 告警，
    severity_on_deny 默认 'error' 比 require_role_audited 高一档。
    """
    from fastapi import Depends  # noqa: PLC0415

    base = require_mfa(*allowed_roles)
    _get_db = db_provider if db_provider is not None else _import_get_db()

    async def _dep(request: Request, db=Depends(_get_db)) -> UserContext:
        try:
            return await base(request)
        except HTTPException as exc:
            ctx = extract_user_context(request)
            base_reason = (
                str(exc.detail) if isinstance(exc.detail, str) else exc.detail.__class__.__name__
            )
            # 401 / ctx 缺 tenant 路径：用 NIL UUID + 把伪造的 X-Tenant-ID 进 reason
            audit_tenant_id, reason_suffix = _resolve_audit_for_unauthenticated(
                request, ctx.tenant_id,
            )
            reason = (
                f"{base_reason} | {reason_suffix}" if reason_suffix else base_reason
            )
            try:
                await _audit_deny_safe(
                    db=db,
                    tenant_id=audit_tenant_id,
                    store_id=ctx.store_id,
                    user_id=ctx.user_id,
                    user_role=ctx.role,
                    action=action,
                    reason=reason,
                    severity=severity_on_deny,
                    client_ip=ctx.client_ip,
                    request_id=request.headers.get("X-Request-Id")
                    if hasattr(request, "headers")
                    else None,
                )
            except Exception:  # noqa: BLE001
                logger.error(
                    "audit_deny_call_failed",
                    action=action,
                    user_id=ctx.user_id,
                    reason=reason,
                    exc_info=True,
                )
            raise

    return _dep


# ──────────────────────────────────────────────────────────────────────────
#  PR-7 — 金额阈值动态 MFA 门禁（运行时检查，handler 内调用）
#
#  适用场景：banquet.deposit.create 这类大部分单据 < 阈值（cashier 友好），
#  少部分 ≥ 阈值（高敏感，需 MFA）的混合路由。FastAPI Dependency 装饰器层
#  无法看到 request body，所以放在 handler 里手动调。
#
#  与 require_mfa_audited 的区别：
#    - require_mfa_audited：装饰器层强制 MFA（每个调用都拦），UX 友好度低
#      但适合纯高敏感动作（refund / discount.rule.* 等）
#    - assert_mfa_for_high_value：handler 内按金额阈值动态拦，UX 友好度高
#      适合"主要是低额，少数高额"的混合路由（banquet 定金 / 大额企业团餐 等）
# ──────────────────────────────────────────────────────────────────────────


def _high_value_threshold_fen(action: str, default_fen: int) -> int:
    """读取 action 专属或全局阈值环境变量；非数字 / 缺失时用 default。

    优先级：
      TX_MFA_THRESHOLD_FEN__<action>  （e.g. TX_MFA_THRESHOLD_FEN__BANQUET_DEPOSIT_CREATE）
      TX_MFA_THRESHOLD_FEN_DEFAULT
      传入的 default_fen
    """
    action_key = (
        "TX_MFA_THRESHOLD_FEN__"
        + action.upper().replace(".", "_").replace("-", "_")
    )
    for var in (action_key, "TX_MFA_THRESHOLD_FEN_DEFAULT"):
        raw = os.getenv(var, "")
        if raw and raw.lstrip("-").isdigit():
            try:
                value = int(raw)
                if value > 0:
                    return value
            except ValueError:
                pass
    return default_fen


async def assert_mfa_for_high_value(
    user: UserContext,
    db,
    *,
    action: str,
    amount_fen: int,
    threshold_fen: int = 500_000,
    request_id: str | None = None,
) -> None:
    """金额阈值 MFA 门禁 — handler 内调用（require_role_audited 之外的运行时检查）。

    行为：
      - amount_fen < threshold → 直接放行（无 audit 写入）
      - amount_fen ≥ threshold + user 已 MFA → 放行
      - amount_fen ≥ threshold + user 未 MFA → 写 deny 审计 + 抛 403 MFA_REQUIRED

    阈值优先级：环境变量 TX_MFA_THRESHOLD_FEN__<ACTION> > TX_MFA_THRESHOLD_FEN_DEFAULT
    > 入参 threshold_fen（默认 ¥5000 = 500_000 fen）。

    Args:
        user: UserContext（来自 require_role_audited Depends 注入）
        db: SQLAlchemy AsyncSession
        action: 业务动作标识（与 audit 表 action 列对齐）
        amount_fen: 本次动作涉及的金额（分；金额来自 request body）
        threshold_fen: 默认阈值（分）；环境变量可覆盖
        request_id: 链路追踪 ID（可空）

    Raises:
        HTTPException(403, "MFA_REQUIRED"): 高额且未 MFA
    """
    effective_threshold = _high_value_threshold_fen(action, threshold_fen)
    if amount_fen < effective_threshold:
        return
    if user.mfa_verified:
        return

    # 写 deny 审计（与 require_mfa_audited 装饰器同 severity=error）
    try:
        from ..services.trade_audit_log import audit_deny  # noqa: PLC0415

        await audit_deny(
            db,
            tenant_id=user.tenant_id,
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action=action,
            amount_fen=amount_fen,
            client_ip=user.client_ip,
            reason=(
                f"MFA_REQUIRED_FOR_HIGH_VALUE "
                f"amount_fen={amount_fen} threshold_fen={effective_threshold}"
            ),
            severity="error",
            request_id=request_id,
        )
    except Exception:  # noqa: BLE001 — 审计失败不能阻塞 4xx 响应抛出
        logger.error(
            "high_value_mfa_audit_failed",
            action=action,
            user_id=user.user_id,
            amount_fen=amount_fen,
            exc_info=True,
        )

    raise HTTPException(status_code=403, detail="MFA_REQUIRED")
