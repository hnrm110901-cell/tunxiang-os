"""Sprint E3 — 小红书 OAuth 2.0 token 管理

职责：
  1. 处理授权回调：用 authorization_code 换 access_token + refresh_token
  2. token 到期前刷新
  3. 连续 401 错误时标记 binding 过期

注：
  · 真实的 HTTP 调用通过可注入的 token_exchanger 实现，测试用 stub
  · token 写入 DB 前应用 KMS 加密（本模块不做加密 — 由上层 repository 负责）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# 默认 access_token 有效期 2 小时（小红书 2025 版）
DEFAULT_ACCESS_TOKEN_TTL = timedelta(hours=2)
# 默认 refresh_token 有效期 30 天
DEFAULT_REFRESH_TOKEN_TTL = timedelta(days=30)

# 刷新提前量：到期前 10 分钟刷新
REFRESH_BUFFER = timedelta(minutes=10)

# 连续 401 失败 > AUTH_ERROR_THRESHOLD 次 → 标记 expired，要求重新授权
AUTH_ERROR_THRESHOLD = 3


# ─────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────


@dataclass
class TokenPair:
    """access_token + refresh_token + metadata"""

    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: Optional[str] = None

    @property
    def needs_refresh(self) -> bool:
        """是否需要刷新（到期前 REFRESH_BUFFER 内）"""
        return datetime.now(tz=timezone.utc) >= (self.expires_at - REFRESH_BUFFER)

    @property
    def is_expired(self) -> bool:
        return datetime.now(tz=timezone.utc) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "scope": self.scope,
        }


# TokenExchanger 协议：async (grant: dict) → raw response
# grant 类型：
#   {"grant_type": "authorization_code", "code": "..."}
#   {"grant_type": "refresh_token", "refresh_token": "..."}
TokenExchanger = Callable[[dict], Awaitable[dict]]


# ─────────────────────────────────────────────────────────────
# OAuth Token Service
# ─────────────────────────────────────────────────────────────


class XhsOAuthTokenService:
    """小红书 OAuth 2.0 token 管理器

    构造时注入 exchanger 函数（真实是 HTTP 调用小红书 API，测试用 stub）。
    服务内部不碰 DB — token repository 由上层提供（或 caller 直接用 SQL）。
    """

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        token_exchanger: Optional[TokenExchanger] = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._exchanger = token_exchanger or _default_stub_exchanger

    async def exchange_code_for_token(
        self, *, code: str, redirect_uri: Optional[str] = None
    ) -> TokenPair:
        """授权回调：authorization_code → TokenPair"""
        grant = {
            "grant_type": "authorization_code",
            "app_id": self._app_id,
            "app_secret": self._app_secret,
            "code": code,
        }
        if redirect_uri:
            grant["redirect_uri"] = redirect_uri

        response = await self._exchanger(grant)
        return self._parse_token_response(response)

    async def refresh_access_token(self, *, refresh_token: str) -> TokenPair:
        """用 refresh_token 换新的 access_token"""
        grant = {
            "grant_type": "refresh_token",
            "app_id": self._app_id,
            "app_secret": self._app_secret,
            "refresh_token": refresh_token,
        }
        response = await self._exchanger(grant)
        return self._parse_token_response(response)

    async def ensure_fresh_token(self, pair: TokenPair) -> TokenPair:
        """若 pair 快到期则刷新，否则原样返回"""
        if not pair.needs_refresh:
            return pair
        logger.info(
            "xhs_token_refresh", extra={"expires_at": pair.expires_at.isoformat()}
        )
        return await self.refresh_access_token(refresh_token=pair.refresh_token)

    def _parse_token_response(self, response: dict[str, Any]) -> TokenPair:
        """从平台响应解析 TokenPair

        2025 版小红书响应（标准 OAuth 2.0）：
            {
              "access_token": "...",
              "refresh_token": "...",
              "expires_in": 7200,  // 秒
              "scope": "read write",
              "token_type": "Bearer"
            }

        错误响应：
            {
              "error": "invalid_grant",
              "error_description": "..."
            }
        """
        if error := response.get("error"):
            raise XhsOAuthError(
                f"OAuth 错误: {error} — "
                f"{response.get('error_description', '(no description)')}"
            )

        access = response.get("access_token")
        refresh = response.get("refresh_token")
        if not access or not refresh:
            raise XhsOAuthError(
                f"响应缺少 access_token / refresh_token: {response}"
            )

        expires_in = int(response.get("expires_in") or DEFAULT_ACCESS_TOKEN_TTL.total_seconds())
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)

        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
            scope=response.get("scope"),
        )


# ─────────────────────────────────────────────────────────────
# 异常
# ─────────────────────────────────────────────────────────────


class XhsOAuthError(Exception):
    """OAuth 交互失败（错误响应 / 网络异常）"""


# ─────────────────────────────────────────────────────────────
# 默认 stub exchanger（测试 + 本地开发用）
# ─────────────────────────────────────────────────────────────


async def _default_stub_exchanger(grant: dict) -> dict:
    """不调真实平台，返回 deterministic fake token

    用于：
      · 本地开发（不配置 app_id/app_secret）
      · 单元测试（确定性结果）
      · CI 环境（不走外网）
    """
    grant_type = grant.get("grant_type")
    if grant_type == "authorization_code":
        code = grant.get("code", "")
        return {
            "access_token": f"stub_access_{code}",
            "refresh_token": f"stub_refresh_{code}",
            "expires_in": int(DEFAULT_ACCESS_TOKEN_TTL.total_seconds()),
            "scope": "read write",
            "token_type": "Bearer",
        }
    if grant_type == "refresh_token":
        old_refresh = grant.get("refresh_token", "")
        return {
            "access_token": f"stub_access_refreshed_{old_refresh[-8:]}",
            "refresh_token": old_refresh,  # 有些平台复用，有些换新，此处保守
            "expires_in": int(DEFAULT_ACCESS_TOKEN_TTL.total_seconds()),
            "scope": "read write",
            "token_type": "Bearer",
        }
    return {"error": "unsupported_grant_type", "error_description": grant_type}
