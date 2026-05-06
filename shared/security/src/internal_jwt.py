"""服务间内部 JWT — 短期 HS256，由 gateway 签发，下游服务校验

审计 S-02（P0）跟进：每个 service 都直接信任 X-Tenant-ID header → 任何能到 pod 的
请求都能伪造租户绕 RLS。本模块提供"由 gateway 签、下游验"的最小化内部 JWT，
搭配 NetworkPolicy 后构成纵深防御。

⚠️ 独立 review P1-4：当前 InternalJwtMiddleware **尚未部署到任何下游服务**。
   gateway 已开始 mint X-Internal-JWT，但下游 24 服务仍读 X-Tenant-ID header — 即
   "只签不验"，S-02 完成度 50%。完整闭环 follow-up（约 2-3 天）：
     1. 在每个 services/*/src/main.py 加 app.add_middleware(InternalJwtMiddleware)
     2. 路由 _get_tenant_id() 改读 request.state.tenant_id（middleware 写入）
        而非 request.headers.get("X-Tenant-ID", "")
     3. k8s NetworkPolicy 限只有 gateway namespace 可达 tx-* pod 的端口
   爆炸半径提示：HS256 共享密钥模型下单 pod 内存被 dump 即获密钥可签任意租户；
   生产应配 Vault / Sealed Secret 限制 secret 投放范围；可考虑升级 RS256 非对称
   （gateway 持私钥签，下游持公钥验，私钥可单独保护）。

设计取舍：
  - 算法 HS256（共享密钥），不引 RSA 复杂度；密钥经 K8s Secret 注入
  - 有效期 60s（可配），只够穿过 gateway → 下游一跳；防止 token 外泄久留
  - claims 仅包含 tenant_id / user_id / role / iss / exp / iat —— 不携带敏感数据
  - issuer = "tx-gateway"；audience 默认 "tx-internal"
  - 环境变量 TX_INTERNAL_JWT_SECRET 缺失：
      * 生产（TX_ENV in {production, prod, gray}）→ raise，禁止启动
      * 其他 → 返回 None，gateway 不附加 header（向后兼容期）

使用方式：
  - gateway proxy 调 mint_internal_jwt(...)，把返回值放 X-Internal-JWT
  - 下游 FastAPI 服务挂 InternalJwtMiddleware (follow-up)：校验后写
    request.state.{tenant_id, user_id, role}，路由优先读这套 trusted 值
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 配置 ────────────────────────────────────────────────────────────────────

_DEFAULT_TTL_SECONDS = 60
_DEFAULT_ISSUER = "tx-gateway"
_DEFAULT_AUDIENCE = "tx-internal"
_PRODUCTION_ENVS = ("production", "prod", "gray")


def _get_secret() -> str:
    """读取共享密钥；生产环境无密钥即抛错（fail-closed）。

    Returns:
        非空字符串 = 密钥可用；空字符串 = 非生产环境且未配置（向后兼容）。
    """
    secret = os.environ.get("TX_INTERNAL_JWT_SECRET", "").strip()
    if secret:
        return secret
    env = (os.environ.get("TX_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    if env in _PRODUCTION_ENVS:
        raise RuntimeError(
            "TX_INTERNAL_JWT_SECRET 未配置；生产环境拒绝启动 "
            "（审计 S-02：服务间 token 必须签名，不能信任客户端 X-Tenant-ID）"
        )
    logger.debug("internal_jwt_secret_missing_dev_mode")
    return ""


def _get_ttl() -> int:
    raw = os.environ.get("TX_INTERNAL_JWT_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS))
    try:
        v = int(raw)
        return max(5, min(v, 300))  # clamp 5..300s
    except ValueError:
        return _DEFAULT_TTL_SECONDS


# ─── 签发 ────────────────────────────────────────────────────────────────────


def mint_internal_jwt(
    *,
    tenant_id: str,
    user_id: str = "",
    role: str = "",
    extra_claims: Optional[dict] = None,
) -> Optional[str]:
    """为下游服务签发一次性内部 JWT。

    Returns:
        JWT 字符串；密钥未配置（仅 dev/test）时返回 None。
    """
    secret = _get_secret()
    if not secret:
        return None
    if not tenant_id:
        # 没有 tenant 不签发 — 防止"匿名 + 受信"陷阱
        return None
    try:
        import jwt  # PyJWT
    except ImportError:
        logger.warning("internal_jwt_pyjwt_missing")
        return None
    now = int(time.time())
    payload = {
        "iss": _DEFAULT_ISSUER,
        "aud": _DEFAULT_AUDIENCE,
        "iat": now,
        "exp": now + _get_ttl(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, secret, algorithm="HS256")
    return token if isinstance(token, str) else token.decode("utf-8")


# ─── 校验 ────────────────────────────────────────────────────────────────────


class InternalJwtError(ValueError):
    """内部 JWT 校验失败 — 调用方应回 401。"""


def verify_internal_jwt(token: str) -> dict:
    """校验下游收到的 X-Internal-JWT，返回 claims；任何错误均抛 InternalJwtError。"""
    if not token:
        raise InternalJwtError("missing token")
    secret = _get_secret()
    if not secret:
        # 非生产无密钥 → 不强制校验（dev 兼容）；调用方需配合按 env 判断是否要求
        raise InternalJwtError("internal jwt secret not configured")
    try:
        import jwt  # PyJWT
    except ImportError as exc:
        raise InternalJwtError("pyjwt not installed") from exc
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_DEFAULT_AUDIENCE,
            issuer=_DEFAULT_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise InternalJwtError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InternalJwtError(f"invalid token: {exc}") from exc
    if not claims.get("tenant_id"):
        raise InternalJwtError("tenant_id claim missing")
    return claims
