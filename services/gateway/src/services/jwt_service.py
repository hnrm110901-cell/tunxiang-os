"""JWT令牌服务 — 等保三级合规实现

access_token:  15分钟，包含 sub/tenant_id/role/mfa_verified
refresh_token: 7天，jti 需存入 refresh_tokens 表（可撤销）

密钥来自环境变量 TX_JWT_SECRET_KEY（min 32字节）
算法：HS256

安全约束（2026-05 A1 加固）：
  - 生产环境缺少 TX_JWT_SECRET_KEY → RuntimeError（不复位默认值）
  - verify_access_token 校验 type/iss/aud
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import structlog
from jwt.exceptions import ExpiredSignatureError
from jwt.exceptions import InvalidTokenError as JWTError

logger = structlog.get_logger(__name__)

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"


class JWTService:
    """JWT令牌的签发与验证。

    实例化时从环境变量读取密钥。
    建议以单例方式注入（FastAPI Depends）。
    """

    def __init__(self) -> None:
        env = os.environ.get("TX_ENV", "development")
        secret = os.environ.get("TX_JWT_SECRET_KEY", "")

        if not secret:
            if env == "production":
                logger.error("jwt_secret_missing_production")
                raise RuntimeError(
                    "TX_JWT_SECRET_KEY is required in production environment"
                )
            logger.warning(
                "jwt_secret_not_set",
                message="TX_JWT_SECRET_KEY未设置，使用不安全的默认值，仅限开发环境",
            )
            secret = "INSECURE_DEV_KEY_CHANGE_IN_PRODUCTION_32b"
        elif len(secret) < 32:
            logger.warning(
                "jwt_secret_too_short",
                length=len(secret),
                message="TX_JWT_SECRET_KEY长度不足32字节，存在安全风险",
            )

        self._secret = secret
        self._expected_issuer = os.environ.get("TX_JWT_ISSUER")
        self._expected_audience = os.environ.get("TX_JWT_AUDIENCE")

    # ─────────────────────────────────────────────────────────────────
    # 签发
    # ─────────────────────────────────────────────────────────────────

    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        role: str,
        mfa_verified: bool = False,
    ) -> str:
        """签发 access token（15分钟有效）。"""
        now = datetime.now(timezone.utc)
        payload: dict = {
            "type": "access",
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "mfa_verified": mfa_verified,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        }
        if self._expected_issuer:
            payload["iss"] = self._expected_issuer
        if self._expected_audience:
            payload["aud"] = self._expected_audience
        token: str = jwt.encode(payload, self._secret, algorithm=ALGORITHM)
        logger.info(
            "access_token_issued",
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            mfa_verified=mfa_verified,
        )
        return token

    def create_refresh_token(self, user_id: str) -> tuple[str, str]:
        """签发 refresh token（7天有效）。

        Returns:
            (token_string, jti) — jti 必须由调用方存入 refresh_tokens 表。
        """
        jti = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        payload: dict = {
            "sub": user_id,
            "jti": jti,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        }
        token: str = jwt.encode(payload, self._secret, algorithm=ALGORITHM)
        logger.info("refresh_token_issued", user_id=user_id, jti=jti)
        return token, jti

    # ─────────────────────────────────────────────────────────────────
    # 验证 / 解码
    # ─────────────────────────────────────────────────────────────────

    def verify_access_token(self, token: str) -> Optional[dict]:
        """验证并解码 access token。

        校验项：
          - 签名正确且未过期
          - type 声明必须为 "access"（拒绝 refresh token 被误用）
          - iss 声明必须匹配 TX_JWT_ISSUER（如果配置了该环境变量）
          - aud 声明必须匹配 TX_JWT_AUDIENCE（如果配置了该环境变量）

        Returns:
            payload 字典；校验失败时返回 None。
        """
        try:
            payload: dict = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                options={"verify_aud": False, "verify_iss": False},
            )
        except ExpiredSignatureError:
            logger.info("jwt_expired")
            return None
        except JWTError as exc:
            logger.warning("jwt_invalid", error=str(exc))
            return None

        # 校验 type — 拒绝 refresh token 当 access token 使用
        if payload.get("type") is not None and payload.get("type") != "access":
            logger.warning("jwt_type_mismatch", type_field=payload.get("type"))
            return None

        # 校验 iss
        if self._expected_issuer and payload.get("iss") != self._expected_issuer:
            logger.warning(
                "jwt_issuer_mismatch",
                expected=self._expected_issuer,
                got=payload.get("iss"),
            )
            return None

        # 校验 aud
        if self._expected_audience and payload.get("aud") != self._expected_audience:
            logger.warning(
                "jwt_audience_mismatch",
                expected=self._expected_audience,
                got=payload.get("aud"),
            )
            return None

        return payload

    def decode_refresh_token(self, token: str) -> Optional[dict]:
        """解码 refresh token（不验证撤销状态，调用方负责 DB 查询）。

        Returns:
            payload 字典；type 不为 'refresh' 或签名无效时返回 None。
        """
        try:
            payload: dict = jwt.decode(token, self._secret, algorithms=[ALGORITHM])
            if payload.get("type") != "refresh":
                logger.warning("jwt_refresh_type_mismatch", type_field=payload.get("type"))
                return None
            return payload
        except ExpiredSignatureError:
            logger.info("refresh_token_expired")
            return None
        except JWTError as exc:
            logger.warning("refresh_token_invalid", error=str(exc))
            return None
