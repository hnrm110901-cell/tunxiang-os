"""认证服务 — 生产级 JWT + TOTP 双因素认证

等保三级合规：
  - 密码（第一因素）+ TOTP/备用码（第二因素）
  - access_token 15分钟，refresh_token 7天（可撤销）
  - 暴力破解保护：5次失败锁定15分钟
  - 所有认证事件写入 audit_log

两步登录流程：
  步骤1: POST /api/v1/auth/login
    - 验证密码 → 如已启用MFA则返回 session_token
    - 未启用MFA → 直接返回 access_token + refresh_token
  步骤2: POST /api/v1/auth/mfa/verify
    - 验证 session_token + TOTP码 → 返回 access_token + refresh_token

向后兼容：
  - DEMO_USERS 可在非生产环境用于演示（明文密码）；生产默认关闭，见环境变量 TX_ENABLE_DEMO_AUTH
  - GET /api/v1/auth/verify 兼容旧版内存 token（如现有服务依赖）
"""

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from shared.ontology.src.database import async_session_factory
from shared.tenant_registry import MERCHANT_CODE_TO_TENANT_UUID

from .response import err, ok
from .services.audit_log_service import AuditAction, AuditEntry, AuditLogService
from .services.jwt_service import JWTService
from .services.mfa_service import MFAService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ─────────────────────────────────────────────────────────────────
# Redis — MFA临时secret存储（5分钟TTL）
# ─────────────────────────────────────────────────────────────────
_mfa_redis = None


async def _get_mfa_redis():
    """获取Redis连接（单例，延迟初始化）"""
    global _mfa_redis
    if _mfa_redis is None:
        try:
            import redis.asyncio as aioredis

            _mfa_redis = await aioredis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except (ImportError, OSError) as exc:
            logger.warning("mfa_redis_unavailable", error=str(exc))
            return None
    return _mfa_redis


async def _store_mfa_temp_secret(user_id: str, encrypted_secret: str) -> None:
    """将MFA临时secret存入Redis，5分钟TTL"""
    r = await _get_mfa_redis()
    if r is not None:
        try:
            key = f"mfa:temp:{user_id}"
            await r.setex(key, 300, encrypted_secret)
            logger.debug("mfa_temp_secret_stored", user_id=user_id)
            return
        except OSError as exc:
            logger.warning("mfa_temp_secret_store_failed", user_id=user_id, error=str(exc))
    # fallback: Redis不可用时存入内存（仅限开发环境）
    _mfa_temp_fallback[user_id] = encrypted_secret
    logger.warning("mfa_temp_secret_stored_in_memory_fallback", user_id=user_id)


async def _get_mfa_temp_secret(user_id: str) -> Optional[str]:
    """从Redis读取MFA临时secret"""
    r = await _get_mfa_redis()
    if r is not None:
        try:
            key = f"mfa:temp:{user_id}"
            val = await r.get(key)
            if val:
                return val
        except OSError as exc:
            logger.warning("mfa_temp_secret_get_failed", user_id=user_id, error=str(exc))
    # fallback: 尝试内存
    return _mfa_temp_fallback.pop(user_id, None)


# 内存fallback（Redis不可用时的降级方案，仅限开发环境）
_mfa_temp_fallback: dict[str, str] = {}

# ─────────────────────────────────────────────────────────────────
# 服务实例（进程级单例）
# ─────────────────────────────────────────────────────────────────
_jwt_service = JWTService()
_mfa_service = MFAService()
_audit_log_service = AuditLogService()

# ─────────────────────────────────────────────────────────────────
# Demo 用户（向后兼容，明文密码仅供开发/演示环境）
# 生产环境默认关闭，见环境变量 TX_ENABLE_DEMO_AUTH；users 表查询已实现
# ─────────────────────────────────────────────────────────────────
DEMO_USERS: dict[str, dict] = {
    "admin": {
        "password": os.getenv("DEMO_ADMIN_PASSWORD", ""),
        "name": "系统管理员",
        "role": "admin",
        "tenant_id": "a0000000-0000-0000-0000-000000000001",
        "merchant": "屯象科技",
        "user_id": "u0000000-0000-0000-0000-000000000001",
        "mfa_enabled": False,
        "mfa_secret_enc": None,
        "mfa_backup_codes": [],
    },
    "changzaiyiqi": {
        "password": os.getenv("DEMO_CZQ_PASSWORD", ""),
        "name": "尝在一起管理员",
        "role": "merchant_admin",
        "tenant_id": MERCHANT_CODE_TO_TENANT_UUID["czyz"],
        "merchant": "尝在一起",
        "user_id": "u0000000-0000-0000-0000-000000000002",
        "mfa_enabled": False,
        "mfa_secret_enc": None,
        "mfa_backup_codes": [],
    },
    "zuiqianxian": {
        "password": os.getenv("DEMO_ZQX_PASSWORD", ""),
        "name": "最黔线管理员",
        "role": "merchant_admin",
        "tenant_id": MERCHANT_CODE_TO_TENANT_UUID["zqx"],
        "merchant": "最黔线",
        "user_id": "u0000000-0000-0000-0000-000000000003",
        "mfa_enabled": False,
        "mfa_secret_enc": None,
        "mfa_backup_codes": [],
    },
    "shanggongchu": {
        "password": os.getenv("DEMO_SGC_PASSWORD", ""),
        "name": "尚宫厨管理员",
        "role": "merchant_admin",
        "tenant_id": MERCHANT_CODE_TO_TENANT_UUID["sgc"],
        "merchant": "尚宫厨",
        "user_id": "u0000000-0000-0000-0000-000000000004",
        "mfa_enabled": False,
        "mfa_secret_enc": None,
        "mfa_backup_codes": [],
    },
    "xuji": {
        "password": os.getenv("DEMO_XJ_PASSWORD", ""),
        "name": "徐记海鲜管理员",
        "role": "merchant_admin",
        "tenant_id": "a0000000-0000-0000-0000-000000000005",
        "merchant": "徐记海鲜",
        "user_id": "u0000000-0000-0000-0000-000000000005",
        "mfa_enabled": False,
        "mfa_secret_enc": None,
        "mfa_backup_codes": [],
    },
}

# ─────────────────────────────────────────────────────────────────
# 内存存储（开发/演示用）
# refresh_tokens 数据库表查询已实现（优先DB，_refresh_store保留为降级缓冲）
# ─────────────────────────────────────────────────────────────────

# 旧版内存 token（向后兼容 /api/v1/auth/verify）
_legacy_token_store: dict[str, dict] = {}

# 两步登录：session_token → {username, expires_at, failed_count}
# expires_at 单位为 Unix 时间戳（秒）
_mfa_sessions: dict[str, dict] = {}
_MFA_SESSION_TTL_SECONDS = 300  # 5分钟
_MFA_SESSION_MAX_FAILS = 3

# refresh_token 内存存储: jti → {user_id, expires_at, revoked}
# 故障降级缓冲：DB不可达时保证 token 操作不中断（正常路径走 refresh_tokens 表）
_refresh_store: dict[str, dict] = {}

# ─────────────────────────────────────────────────────────────────
# 暴力破解保护（DB主路径 users.failed_login_count/locked_until，内存作降级）
# ─────────────────────────────────────────────────────────────────
_MAX_LOGIN_FAILS = 5
_LOCKOUT_SECONDS = 900  # 15分钟
# username → {failed_count, locked_until}
_brute_force: dict[str, dict] = {}


class LoginBruteForceProtection:
    """DB-backed 暴力破解防护（查询 users.failed_login_count / users.locked_until）。

    所有方法均为 async。DB 操作失败时自动降级到内存字典，保证业务不中断。
    """

    async def is_locked(self, username: str) -> bool:
        """检查账户是否处于锁定状态。优先查 DB，失败降级到内存。"""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT locked_until, failed_login_count
                        FROM users
                        WHERE username = :username AND is_deleted = FALSE AND is_active = TRUE
                        LIMIT 1
                    """),
                    {"username": username},
                )
                row = result.mappings().first()
            if row is None:
                # 用户不在 DB 中（可能是 DEMO 用户），检查内存
                return self._mem_is_locked(username)
            locked_until = row.get("locked_until")
            if locked_until is None:
                return False
            # locked_until 是 TIMESTAMPTZ，可能带 tzinfo 也可能不带
            if hasattr(locked_until, "tzinfo") and locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) < locked_until
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning("brute_force_db_check_failed", username=username, error=str(exc))
            return self._mem_is_locked(username)

    async def record_failure(self, username: str) -> None:
        """记录一次登录失败；失败次数达到阈值时自动锁定账户。"""
        try:
            async with async_session_factory() as db:
                # 先递增计数
                await db.execute(
                    text("""
                        UPDATE users
                        SET failed_login_count = failed_login_count + 1,
                            updated_at = NOW()
                        WHERE username = :username AND is_deleted = FALSE
                    """),
                    {"username": username},
                )
                # 查询最新计数以决定是否锁定
                result = await db.execute(
                    text("""
                        SELECT failed_login_count FROM users
                        WHERE username = :username AND is_deleted = FALSE
                        LIMIT 1
                    """),
                    {"username": username},
                )
                row = result.mappings().first()
                if row and (row.get("failed_login_count") or 0) >= _MAX_LOGIN_FAILS:
                    await db.execute(
                        text("""
                            UPDATE users
                            SET locked_until = NOW() + INTERVAL '15 minutes',
                                updated_at = NOW()
                            WHERE username = :username AND is_deleted = FALSE
                        """),
                        {"username": username},
                    )
                    logger.warning(
                        "login_account_locked_db",
                        username=username,
                        locked_seconds=_LOCKOUT_SECONDS,
                    )
                await db.commit()
            # 同步内存（保持一致）
            self._mem_record_failure(username)
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning("brute_force_db_record_failed", username=username, error=str(exc))
            self._mem_record_failure(username)

    async def record_success(self, username: str) -> None:
        """登录成功后重置失败计数和锁定状态。"""
        try:
            async with async_session_factory() as db:
                await db.execute(
                    text("""
                        UPDATE users
                        SET failed_login_count = 0,
                            locked_until = NULL,
                            last_login_at = NOW(),
                            updated_at = NOW()
                        WHERE username = :username AND is_deleted = FALSE
                    """),
                    {"username": username},
                )
                await db.commit()
            # 清内存备份
            _brute_force.pop(username, None)
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning("brute_force_db_reset_failed", username=username, error=str(exc))
            _brute_force.pop(username, None)

    async def remaining_lockout(self, username: str) -> int:
        """返回锁定剩余秒数（0 表示未锁定）。优先查 DB，失败降级到内存。"""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT locked_until FROM users
                        WHERE username = :username AND is_deleted = FALSE AND is_active = TRUE
                        LIMIT 1
                    """),
                    {"username": username},
                )
                row = result.mappings().first()
            if row is None:
                return self._mem_remaining_lockout(username)
            locked_until = row.get("locked_until")
            if locked_until is None:
                return 0
            if hasattr(locked_until, "tzinfo") and locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            remaining = (locked_until - datetime.now(timezone.utc)).total_seconds()
            return max(0, int(remaining))
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning("brute_force_db_remaining_failed", username=username, error=str(exc))
            return self._mem_remaining_lockout(username)

    # ── 内存降级辅助方法 ──────────────────────────────────────────

    def _mem_is_locked(self, username: str) -> bool:
        state = _brute_force.get(username)
        if not state:
            return False
        locked_until = state.get("locked_until", 0)
        if locked_until and time.time() < locked_until:
            return True
        if locked_until and time.time() >= locked_until:
            _brute_force.pop(username, None)
        return False

    def _mem_record_failure(self, username: str) -> None:
        state = _brute_force.setdefault(username, {"failed_count": 0, "locked_until": 0})
        state["failed_count"] = state.get("failed_count", 0) + 1
        if state["failed_count"] >= _MAX_LOGIN_FAILS:
            state["locked_until"] = time.time() + _LOCKOUT_SECONDS
            logger.warning(
                "login_account_locked_mem",
                username=username,
                locked_seconds=_LOCKOUT_SECONDS,
            )

    def _mem_remaining_lockout(self, username: str) -> int:
        state = _brute_force.get(username)
        if not state:
            return 0
        locked_until = state.get("locked_until", 0)
        if locked_until:
            remaining = int(locked_until - time.time())
            return max(0, remaining)
        return 0


_brute_force_guard = LoginBruteForceProtection()


# ─────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _user_info_from_demo(username: str, user: dict) -> dict:
    """构建去除敏感字段的用户信息字典。"""
    return {
        "user_id": user["user_id"],
        "username": username,
        "name": user["name"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "merchant": user["merchant"],
        "mfa_enabled": user["mfa_enabled"],
    }


def _demo_auth_enabled() -> bool:
    """是否允许回退到 DEMO_USERS（开发/演示账号）。

    - 显式设置 TX_ENABLE_DEMO_AUTH：1/true/yes/on 为启用，否则关闭。
    - 未设置时：ENVIRONMENT/ENV 为 production 或 prod 则关闭，其余环境默认启用。
    """
    explicit = os.getenv("TX_ENABLE_DEMO_AUTH")
    if explicit is not None:
        return explicit.strip().lower() in ("1", "true", "yes", "on")
    env = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").strip().lower()
    return env not in ("production", "prod")


async def _load_user_dict_by_username(username: str) -> Optional[dict]:
    """从 users 表加载活跃用户（与 login 成功路径字段一致，供 MFA 等使用）。"""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT id, tenant_id, username, name, role,
                           mfa_enabled, mfa_secret_enc, mfa_backup_codes
                    FROM users
                    WHERE username = :username AND is_deleted = FALSE AND is_active = TRUE
                    LIMIT 1
                """),
                {"username": username},
            )
            row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("user_db_lookup_failed", username=username, error=str(exc))
        return None
    if row is None:
        return None
    backup_codes_raw = row.get("mfa_backup_codes")
    if isinstance(backup_codes_raw, str):
        try:
            backup_codes_raw = json.loads(backup_codes_raw)
        except (ValueError, TypeError):
            backup_codes_raw = []
    return {
        "user_id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "username": row["username"],
        "name": row.get("name") or username,
        "role": row.get("role", "staff"),
        "merchant": "",
        "mfa_enabled": bool(row.get("mfa_enabled")),
        "mfa_secret_enc": row.get("mfa_secret_enc"),
        "mfa_backup_codes": backup_codes_raw or [],
    }


async def _load_user_dict_by_id(user_id: str) -> Optional[dict]:
    """按用户主键从 users 表加载（供 MFA 设置、JWT 兼容校验等）。"""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT id, tenant_id, username, name, role,
                           mfa_enabled, mfa_secret_enc, mfa_backup_codes
                    FROM users
                    WHERE id = :user_id AND is_deleted = FALSE AND is_active = TRUE
                    LIMIT 1
                """),
                {"user_id": user_id},
            )
            row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("user_db_lookup_failed", user_id=user_id, error=str(exc))
        return None
    if row is None:
        return None
    uname = row["username"]
    backup_codes_raw = row.get("mfa_backup_codes")
    if isinstance(backup_codes_raw, str):
        try:
            backup_codes_raw = json.loads(backup_codes_raw)
        except (ValueError, TypeError):
            backup_codes_raw = []
    return {
        "user_id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "username": uname,
        "name": row.get("name") or uname,
        "role": row.get("role", "staff"),
        "merchant": "",
        "mfa_enabled": bool(row.get("mfa_enabled")),
        "mfa_secret_enc": row.get("mfa_secret_enc"),
        "mfa_backup_codes": backup_codes_raw or [],
    }


async def _issue_tokens(
    user_id: str,
    tenant_id: str,
    role: str,
    mfa_verified: bool,
    ip_address: str = "",
    user_agent: str = "",
) -> dict:
    """签发 access_token + refresh_token，写入 refresh_tokens 数据库表。"""
    access_token = _jwt_service.create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        mfa_verified=mfa_verified,
    )
    refresh_token, jti = _jwt_service.create_refresh_token(user_id=user_id)

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    # 写入 refresh_tokens 数据库表，同时保留内存备份（向后兼容）
    try:
        async with async_session_factory() as db:
            await db.execute(
                text("""
                    INSERT INTO refresh_tokens (jti, user_id, tenant_id, issued_at, expires_at, ip_address, user_agent)
                    VALUES (:jti, :user_id, :tenant_id, NOW(), :expires_at, :ip_address, :user_agent)
                    ON CONFLICT (jti) DO NOTHING
                """),
                {
                    "jti": jti,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "expires_at": expires_at,
                    "ip_address": ip_address or None,
                    "user_agent": user_agent or None,
                },
            )
            await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:  # DB写入失败时回退到内存存储，保证业务不中断
        logger.warning("refresh_token_db_write_failed", jti=jti, error=str(exc))

    _refresh_store[jti] = {
        "user_id": user_id,
        "expires_at": time.time() + 7 * 86400,
        "revoked": False,
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 15 * 60,  # seconds
    }


# ─────────────────────────────────────────────────────────────────
# Request / Response 模型
# ─────────────────────────────────────────────────────────────────


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class MFAVerifyBody(BaseModel):
    session_token: str = Field(..., min_length=32)
    code: str = Field(..., min_length=6, max_length=8)  # 6位TOTP或8位备用码


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class MFASetupEnableBody(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="用于确认的TOTP验证码")


# ─────────────────────────────────────────────────────────────────
# 步骤1：登录（密码验证）
# ─────────────────────────────────────────────────────────────────


@router.post("/login")
async def login(body: LoginBody, request: Request):
    """步骤1：用户名+密码登录。

    - 已启用MFA → 返回 {step: "mfa_required", session_token}
    - 未启用MFA → 返回 access_token + refresh_token
    """
    username = body.username
    ip = _client_ip(request)
    ua = request.headers.get("User-Agent", "")

    # 1. 账户锁定检查
    if await _brute_force_guard.is_locked(username):
        remaining = await _brute_force_guard.remaining_lockout(username)
        logger.warning("login_blocked_locked", username=username, ip=ip)
        return err(
            f"账户已锁定，请 {remaining} 秒后重试",
            code="ACCOUNT_LOCKED",
            status_code=423,
        )

    # 2. 验证用户凭证 — 优先查询 users 表（bcrypt），回退到 DEMO_USERS（开发/演示）
    user = None
    db_user_row = None
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT id, tenant_id, username, name, role,
                           password_hash, mfa_enabled, mfa_secret_enc, mfa_backup_codes
                    FROM users
                    WHERE username = :username AND is_deleted = FALSE AND is_active = TRUE
                    LIMIT 1
                """),
                {"username": username},
            )
            db_user_row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("login_db_lookup_failed", username=username, error=str(exc))

    password_ok = False
    if db_user_row is not None:
        ph: Optional[str] = db_user_row.get("password_hash")
        if ph:
            try:
                password_ok = bcrypt.checkpw(body.password.encode(), ph.encode())
            except (ValueError, TypeError):
                password_ok = False
        if password_ok:
            # 从 DB 行构建 user dict，兼容后续逻辑
            backup_codes_raw = db_user_row.get("mfa_backup_codes")
            if isinstance(backup_codes_raw, str):
                try:
                    backup_codes_raw = json.loads(backup_codes_raw)
                except (ValueError, TypeError):
                    backup_codes_raw = []
            user = {
                "user_id": str(db_user_row["id"]),
                "tenant_id": str(db_user_row["tenant_id"]),
                "username": db_user_row["username"],
                "name": db_user_row.get("name") or username,
                "role": db_user_row.get("role", "staff"),
                "merchant": "",  # 从 stores 表可进一步关联，此处留空
                "mfa_enabled": bool(db_user_row.get("mfa_enabled")),
                "mfa_secret_enc": db_user_row.get("mfa_secret_enc"),
                "mfa_backup_codes": backup_codes_raw or [],
            }
    if user is None and _demo_auth_enabled():
        # 回退到 DEMO_USERS（仅开发/演示；生产默认关闭）
        demo = DEMO_USERS.get(username)
        if demo and demo.get("password") and demo["password"] == body.password:
            password_ok = True
            user = dict(demo)

    if not password_ok or user is None:
        await _brute_force_guard.record_failure(username)
        logger.warning(
            "login_failed",
            username=username,
            ip=ip,
            # 注意：密码不写入日志
        )
        # 写入登录失败审计日志
        try:
            async with async_session_factory() as db:
                await _audit_log_service.log(
                    AuditEntry(
                        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                        action=AuditAction.LOGIN_FAILED,
                        actor_id=username,
                        actor_type="user",
                        resource_type="auth",
                        ip_address=ip,
                        user_agent=ua,
                        severity="warning",
                    ),
                    db,
                )
                await db.commit()
        except (OperationalError, SQLAlchemyError) as audit_exc:
            logger.warning("audit_log_write_failed", error=str(audit_exc))
        return err("用户名或密码错误", code="AUTH_FAILED", status_code=401)

    # 3. 登录成功，重置暴力破解计数
    await _brute_force_guard.record_success(username)
    user_info = _user_info_from_demo(username, user)

    # 4. 检查是否启用MFA
    if user.get("mfa_enabled") and user.get("mfa_secret_enc"):
        # 生成临时 session_token（5分钟有效）
        session_token = uuid.uuid4().hex + uuid.uuid4().hex  # 64字符
        _mfa_sessions[session_token] = {
            "username": username,
            "expires_at": time.time() + _MFA_SESSION_TTL_SECONDS,
            "failed_count": 0,
        }
        logger.info("login_mfa_required", username=username, ip=ip)
        return ok(
            {
                "step": "mfa_required",
                "session_token": session_token,
                "expires_in": _MFA_SESSION_TTL_SECONDS,
            }
        )

    # 5. 未启用MFA，直接签发token
    tokens = await _issue_tokens(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        role=user["role"],
        mfa_verified=False,
        ip_address=ip,
        user_agent=ua,
    )

    # 向后兼容: 同时写入旧版内存 token store
    legacy_token = uuid.uuid4().hex
    _legacy_token_store[legacy_token] = user_info

    logger.info(
        "login_success",
        username=username,
        tenant_id=user["tenant_id"],
        ip=ip,
        mfa_enabled=False,
    )
    # 写入登录成功审计日志
    try:
        async with async_session_factory() as db:
            await _audit_log_service.log(
                AuditEntry(
                    tenant_id=uuid.UUID(user["tenant_id"]),
                    action=AuditAction.LOGIN,
                    actor_id=user["user_id"],
                    actor_type="user",
                    resource_type="auth",
                    ip_address=ip,
                    user_agent=ua,
                ),
                db,
            )
            await db.commit()
    except (OperationalError, SQLAlchemyError) as audit_exc:
        logger.warning("audit_log_write_failed", error=str(audit_exc))

    return ok(
        {
            **tokens,
            "user": user_info,
            # 向后兼容字段
            "token": legacy_token,
        }
    )


# ─────────────────────────────────────────────────────────────────
# 步骤2：MFA验证
# ─────────────────────────────────────────────────────────────────


@router.post("/mfa/verify")
async def mfa_verify(body: MFAVerifyBody, request: Request):
    """步骤2：验证TOTP码或备用码，完成登录，签发token。"""
    ip = _client_ip(request)

    # 1. 验证 session_token 有效性
    session = _mfa_sessions.get(body.session_token)
    if not session:
        logger.warning("mfa_session_not_found", ip=ip)
        return err("session_token无效或已过期，请重新登录", code="MFA_SESSION_INVALID", status_code=401)

    if time.time() > session["expires_at"]:
        _mfa_sessions.pop(body.session_token, None)
        logger.info("mfa_session_expired", ip=ip)
        return err("验证码已超时，请重新登录", code="MFA_SESSION_EXPIRED", status_code=401)

    username = session["username"]
    user = await _load_user_dict_by_username(username)
    if user is None and _demo_auth_enabled():
        user = DEMO_USERS.get(username)
    if not user:
        _mfa_sessions.pop(body.session_token, None)
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    # 2. 验证 TOTP 码或备用码
    code = body.code.strip()
    verified = False

    if len(code) == 6 and code.isdigit():
        # TOTP 验证
        encrypted_secret = user.get("mfa_secret_enc")
        if encrypted_secret:
            verified = _mfa_service.verify_totp(encrypted_secret, code)
    elif len(code) == 8:
        # 备用码验证
        hashed_codes: list[str] = user.get("mfa_backup_codes", [])
        idx = _mfa_service.verify_backup_code(hashed_codes, code)
        if idx is not None:
            # 从内存中移除已使用的备用码
            hashed_codes.pop(idx)
            user["mfa_backup_codes"] = hashed_codes
            verified = True
            logger.info("mfa_backup_code_used", username=username, remaining=len(hashed_codes))
            # 同步更新 users 数据库表中的备用码列表
            try:
                async with async_session_factory() as db:
                    await db.execute(
                        text("SELECT set_config('app.tenant_id', :tid, true)"),
                        {"tid": user.get("tenant_id", "")},
                    )
                    await db.execute(
                        text("""
                            UPDATE users
                            SET mfa_backup_codes = :codes::jsonb, updated_at = NOW()
                            WHERE username = :username AND is_deleted = FALSE
                        """),
                        {
                            "codes": json.dumps(hashed_codes, ensure_ascii=False),
                            "username": username,
                        },
                    )
                    await db.commit()
            except (OperationalError, SQLAlchemyError) as exc:
                logger.warning("mfa_backup_code_db_update_failed", username=username, error=str(exc))

    if not verified:
        session["failed_count"] = session.get("failed_count", 0) + 1
        logger.warning(
            "mfa_verify_failed",
            username=username,
            attempt=session["failed_count"],
            ip=ip,
        )
        if session["failed_count"] >= _MFA_SESSION_MAX_FAILS:
            _mfa_sessions.pop(body.session_token, None)
            return err(
                "验证失败次数过多，session已失效，请重新登录",
                code="MFA_MAX_RETRIES",
                status_code=401,
            )
        remaining_attempts = _MFA_SESSION_MAX_FAILS - session["failed_count"]
        return err(
            f"验证码错误，还剩 {remaining_attempts} 次机会",
            code="MFA_INVALID_CODE",
            status_code=401,
        )

    # 3. 验证通过，清除 session，签发 token
    _mfa_sessions.pop(body.session_token, None)
    user_info = _user_info_from_demo(username, user)

    ua = request.headers.get("User-Agent", "")
    tokens = await _issue_tokens(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        role=user["role"],
        mfa_verified=True,
        ip_address=ip,
        user_agent=ua,
    )

    # 向后兼容
    legacy_token = uuid.uuid4().hex
    _legacy_token_store[legacy_token] = user_info

    logger.info(
        "mfa_verify_success",
        username=username,
        tenant_id=user["tenant_id"],
        ip=ip,
    )
    # 写入 MFA 验证成功审计日志
    try:
        async with async_session_factory() as db:
            await _audit_log_service.log(
                AuditEntry(
                    tenant_id=uuid.UUID(user["tenant_id"]),
                    action=AuditAction.LOGIN,
                    actor_id=user["user_id"],
                    actor_type="user",
                    resource_type="auth",
                    ip_address=ip,
                    user_agent=ua,
                    extra={"mfa_verified": True},
                ),
                db,
            )
            await db.commit()
    except (OperationalError, SQLAlchemyError) as audit_exc:
        logger.warning("audit_log_write_failed", error=str(audit_exc))

    return ok(
        {
            **tokens,
            "user": user_info,
            "token": legacy_token,
        }
    )


# ─────────────────────────────────────────────────────────────────
# Refresh Token
# ─────────────────────────────────────────────────────────────────


@router.post("/refresh")
async def refresh_token(body: RefreshBody, request: Request):
    """刷新 access_token。

    验证 refresh_token 签名和撤销状态，签发新的 access_token。
    """
    payload = _jwt_service.decode_refresh_token(body.refresh_token)
    if not payload:
        return err("refresh_token无效或已过期", code="REFRESH_TOKEN_INVALID", status_code=401)

    jti = payload.get("jti", "")
    user_id = payload.get("sub", "")

    # 检查撤销状态 — 优先查询 refresh_tokens 数据库表，回退到内存 _refresh_store
    db_token_row = None
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT jti, user_id, tenant_id, expires_at, revoked_at
                    FROM refresh_tokens
                    WHERE jti = :jti
                    LIMIT 1
                """),
                {"jti": jti},
            )
            db_token_row = result.mappings().first()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("refresh_token_db_lookup_failed", jti=jti, error=str(exc))

    if db_token_row is not None:
        if db_token_row.get("revoked_at") is not None:
            logger.warning("refresh_token_already_revoked", jti=jti)
            return err("refresh_token已撤销，请重新登录", code="REFRESH_TOKEN_REVOKED", status_code=401)
        expires_at_dt = db_token_row.get("expires_at")
        if expires_at_dt and datetime.now(timezone.utc) > expires_at_dt:
            return err("refresh_token已过期，请重新登录", code="REFRESH_TOKEN_EXPIRED", status_code=401)
    else:
        # 回退到内存存储
        stored = _refresh_store.get(jti)
        if not stored:
            logger.warning("refresh_token_not_found", jti=jti)
            return err("refresh_token不存在或已撤销", code="REFRESH_TOKEN_REVOKED", status_code=401)
        if stored.get("revoked"):
            logger.warning("refresh_token_already_revoked", jti=jti)
            return err("refresh_token已撤销，请重新登录", code="REFRESH_TOKEN_REVOKED", status_code=401)
        if time.time() > stored.get("expires_at", 0):
            _refresh_store.pop(jti, None)
            return err("refresh_token已过期，请重新登录", code="REFRESH_TOKEN_EXPIRED", status_code=401)

    # 查找用户信息 — 优先查询 users 表，回退到 DEMO_USERS
    user = None
    username = None
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text("""
                    SELECT id, tenant_id, username, name, role, mfa_enabled
                    FROM users
                    WHERE id = :user_id AND is_deleted = FALSE AND is_active = TRUE
                    LIMIT 1
                """),
                {"user_id": user_id},
            )
            row = result.mappings().first()
            if row is not None:
                user = {
                    "user_id": str(row["id"]),
                    "tenant_id": str(row["tenant_id"]),
                    "username": row["username"],
                    "name": row.get("name") or row["username"],
                    "role": row.get("role", "staff"),
                    "merchant": "",
                    "mfa_enabled": bool(row.get("mfa_enabled")),
                }
                username = row["username"]
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("refresh_user_db_lookup_failed", user_id=user_id, error=str(exc))

    if user is None and _demo_auth_enabled():
        # 回退到 DEMO_USERS
        for uname, udata in DEMO_USERS.items():
            if udata["user_id"] == user_id:
                user = udata
                username = uname
                break

    if not user:
        logger.warning("refresh_user_not_found", user_id=user_id)
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    # 撤销旧 refresh_token（轮换策略）— 更新 DB 和内存
    try:
        async with async_session_factory() as db:
            await db.execute(
                text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE jti = :jti"),
                {"jti": jti},
            )
            await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("refresh_token_revoke_db_failed", jti=jti, error=str(exc))
    if jti in _refresh_store:
        _refresh_store[jti]["revoked"] = True

    ip = _client_ip(request)
    ua = request.headers.get("User-Agent", "")

    # 签发新的 token 对
    tokens = await _issue_tokens(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        role=user["role"],
        mfa_verified=False,  # refresh 后 mfa_verified 重置，需重新MFA
        ip_address=ip,
        user_agent=ua,
    )

    logger.info("token_refreshed", user_id=user_id)
    return ok(tokens)


# ─────────────────────────────────────────────────────────────────
# 登出
# ─────────────────────────────────────────────────────────────────


@router.post("/logout")
async def logout(request: Request, body: Optional[RefreshBody] = None):
    """撤销 refresh_token，使会话失效。

    同时清理旧版内存 token（向后兼容）。
    """
    # 撤销 JWT refresh_token
    if body and body.refresh_token:
        payload = _jwt_service.decode_refresh_token(body.refresh_token)
        if payload:
            jti = payload.get("jti", "")
            user_id_logout = payload.get("sub", "")
            # 更新 refresh_tokens 数据库表
            try:
                async with async_session_factory() as db:
                    await db.execute(
                        text("UPDATE refresh_tokens SET revoked_at = NOW() WHERE jti = :jti"),
                        {"jti": jti},
                    )
                    await db.commit()
            except (OperationalError, SQLAlchemyError) as exc:
                logger.warning("logout_db_revoke_failed", jti=jti, error=str(exc))
            # 同时更新内存存储
            if jti in _refresh_store:
                _refresh_store[jti]["revoked"] = True
            logger.info("refresh_token_revoked", jti=jti)
            # 写入登出审计日志
            try:
                async with async_session_factory() as db:
                    await _audit_log_service.log(
                        AuditEntry(
                            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                            action=AuditAction.LOGOUT,
                            actor_id=user_id_logout or "unknown",
                            actor_type="user",
                            resource_type="auth",
                            ip_address=_client_ip(request),
                            user_agent=request.headers.get("User-Agent", ""),
                            extra={"jti": jti},
                        ),
                        db,
                    )
                    await db.commit()
            except (OperationalError, SQLAlchemyError) as audit_exc:
                logger.warning("audit_log_write_failed", error=str(audit_exc))

    # 清理旧版内存 token（向后兼容）
    legacy_token = _extract_token(request)
    if legacy_token and legacy_token in _legacy_token_store:
        del _legacy_token_store[legacy_token]

    return ok({"message": "已登出"})


# ─────────────────────────────────────────────────────────────────
# 当前用户信息
# ─────────────────────────────────────────────────────────────────


@router.get("/me")
async def me(request: Request):
    """返回当前用户信息。

    优先验证 JWT access_token，回退到旧版内存 token（向后兼容）。
    """
    token = _extract_token(request)
    if not token:
        return err("未提供认证令牌", code="UNAUTHORIZED", status_code=401)

    # 尝试 JWT 验证
    payload = _jwt_service.verify_access_token(token)
    if payload:
        user_id = payload.get("sub", "")
        # 查询 users 表，回退到 DEMO_USERS
        user_info_result = None
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT id, tenant_id, username, name, role, mfa_enabled
                        FROM users
                        WHERE id = :user_id AND is_deleted = FALSE AND is_active = TRUE
                        LIMIT 1
                    """),
                    {"user_id": user_id},
                )
                row = result.mappings().first()
                if row is not None:
                    user_info_result = {
                        "user_id": str(row["id"]),
                        "username": row["username"],
                        "name": row.get("name") or row["username"],
                        "role": row.get("role", "staff"),
                        "tenant_id": str(row["tenant_id"]),
                        "merchant": "",
                        "mfa_enabled": bool(row.get("mfa_enabled")),
                        "mfa_verified": payload.get("mfa_verified", False),
                        "token_expires_at": payload.get("exp"),
                    }
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning("me_db_lookup_failed", user_id=user_id, error=str(exc))

        if user_info_result is None and _demo_auth_enabled():
            # 回退到 DEMO_USERS
            for uname, udata in DEMO_USERS.items():
                if udata["user_id"] == user_id:
                    user_info_result = {
                        **_user_info_from_demo(uname, udata),
                        "mfa_verified": payload.get("mfa_verified", False),
                        "token_expires_at": payload.get("exp"),
                    }
                    break

        if user_info_result is None:
            return err("用户不存在", code="USER_NOT_FOUND", status_code=401)
        return ok(user_info_result)

    # 回退：旧版内存 token
    if token in _legacy_token_store:
        return ok(_legacy_token_store[token])

    return err("Token无效或已过期，请重新登录", code="UNAUTHORIZED", status_code=401)


# ─────────────────────────────────────────────────────────────────
# MFA 设置端点
# ─────────────────────────────────────────────────────────────────


@router.post("/mfa/setup")
async def mfa_setup(request: Request):
    """返回 TOTP setup URI（用于前端生成二维码）。

    需要已登录（JWT access_token）。
    生成新的 secret 并临时存储，等待 /mfa/enable 确认后正式启用。
    """
    token = _extract_token(request)
    if not token:
        return err("未登录", code="UNAUTHORIZED", status_code=401)

    payload = _jwt_service.verify_access_token(token)
    if not payload:
        return err("Token无效或已过期", code="UNAUTHORIZED", status_code=401)

    user_id = payload.get("sub", "")
    user = await _load_user_dict_by_id(user_id)
    username = None
    if user:
        username = user["username"]
    elif _demo_auth_enabled():
        for uname, udata in DEMO_USERS.items():
            if udata["user_id"] == user_id:
                user = udata
                username = uname
                break

    if not user:
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    if user.get("mfa_enabled"):
        return err("MFA已启用，如需重置请联系管理员", code="MFA_ALREADY_ENABLED", status_code=409)

    # 生成新 secret 并临时存储到Redis（5分钟TTL）
    raw_secret = _mfa_service.generate_secret()
    encrypted_secret = _mfa_service.encrypt_secret(raw_secret)
    await _store_mfa_temp_secret(user_id, encrypted_secret)

    totp_uri = _mfa_service.get_totp_uri(encrypted_secret, username or "")

    logger.info("mfa_setup_initiated", user_id=user_id)
    return ok(
        {
            "totp_uri": totp_uri,
            "message": "请使用验证器App（Google Authenticator/Authy）扫描二维码，然后调用 /mfa/enable 提交验证码",
        }
    )


@router.post("/mfa/enable")
async def mfa_enable(body: MFASetupEnableBody, request: Request):
    """用户首次设置MFA：验证TOTP码后正式启用，同时生成备用码。

    需要已登录（JWT access_token）。
    """
    token = _extract_token(request)
    if not token:
        return err("未登录", code="UNAUTHORIZED", status_code=401)

    payload = _jwt_service.verify_access_token(token)
    if not payload:
        return err("Token无效或已过期", code="UNAUTHORIZED", status_code=401)

    user_id = payload.get("sub", "")
    user = await _load_user_dict_by_id(user_id)
    username = None
    if user:
        username = user["username"]
    elif _demo_auth_enabled():
        for uname, udata in DEMO_USERS.items():
            if udata["user_id"] == user_id:
                user = udata
                username = uname
                break

    if not user:
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    pending_secret = await _get_mfa_temp_secret(user_id)
    if not pending_secret:
        return err("请先调用 /mfa/setup 获取二维码（临时密钥已过期或未生成）", code="MFA_SETUP_REQUIRED", status_code=400)

    # 验证用户提交的TOTP码
    if not _mfa_service.verify_totp(pending_secret, body.code):
        logger.warning("mfa_enable_verify_failed", user_id=user_id)
        return err("验证码错误，请重试", code="MFA_INVALID_CODE", status_code=400)

    # 生成备用码
    backup_codes_plain = _mfa_service.generate_backup_codes()
    backup_codes_hashed = _mfa_service.hash_backup_codes(backup_codes_plain)

    now_utc = datetime.now(timezone.utc)

    # 正式启用MFA — 写入 users 数据库表，同时更新内存 DEMO_USERS（向后兼容）
    try:
        async with async_session_factory() as db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": user.get("tenant_id", "")},
            )
            await db.execute(
                text("""
                    UPDATE users
                    SET mfa_enabled = TRUE,
                        mfa_secret_enc = :mfa_secret_enc,
                        mfa_backup_codes = :mfa_backup_codes::jsonb,
                        mfa_verified_at = :mfa_verified_at,
                        updated_at = NOW()
                    WHERE id = :user_id AND is_deleted = FALSE
                """),
                {
                    "mfa_secret_enc": pending_secret,
                    "mfa_backup_codes": json.dumps(backup_codes_hashed, ensure_ascii=False),
                    "mfa_verified_at": now_utc,
                    "user_id": user_id,
                },
            )
            await db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        logger.warning("mfa_enable_db_write_failed", user_id=user_id, error=str(exc))

    user["mfa_enabled"] = True
    user["mfa_secret_enc"] = pending_secret
    user["mfa_backup_codes"] = backup_codes_hashed
    user["mfa_verified_at"] = now_utc.isoformat()
    user.pop("_pending_mfa_secret_enc", None)

    logger.info("mfa_enabled", user_id=user_id, username=username)
    # 写入 MFA 启用审计日志
    try:
        async with async_session_factory() as db:
            await _audit_log_service.log(
                AuditEntry(
                    tenant_id=uuid.UUID(user.get("tenant_id", "00000000-0000-0000-0000-000000000000")),
                    action=AuditAction.CONFIG_CHANGE,
                    actor_id=user_id,
                    actor_type="user",
                    resource_type="user_mfa",
                    resource_id=user_id,
                    after_state={"mfa_enabled": True},
                    severity="info",
                ),
                db,
            )
            await db.commit()
    except (OperationalError, SQLAlchemyError) as audit_exc:
        logger.warning("audit_log_write_failed", error=str(audit_exc))

    return ok(
        {
            "message": "MFA已成功启用",
            "backup_codes": backup_codes_plain,
            "backup_codes_warning": "请将备用码保存在安全位置，每个备用码只能使用一次，丢失后无法找回",
        }
    )


# ─────────────────────────────────────────────────────────────────
# 向后兼容端点（旧版 verify）
# ─────────────────────────────────────────────────────────────────


@router.get("/verify")
async def verify_token(request: Request):
    """向后兼容的 token 验证端点（现有其他服务可能依赖）。

    优先验证 JWT access_token，回退到旧版内存 token。
    返回格式与旧版一致：{valid: bool, user: {...}}
    """
    token = _extract_token(request)
    if not token:
        return ok({"valid": False, "user": None})

    # 尝试 JWT 验证
    payload = _jwt_service.verify_access_token(token)
    if payload:
        user_id = payload.get("sub", "")
        db_user = await _load_user_dict_by_id(user_id)
        if db_user:
            uname = db_user["username"]
            return ok(
                {
                    "valid": True,
                    "user": _user_info_from_demo(uname, db_user),
                    "mfa_verified": payload.get("mfa_verified", False),
                }
            )
        if _demo_auth_enabled():
            for username, user in DEMO_USERS.items():
                if user["user_id"] == user_id:
                    return ok(
                        {
                            "valid": True,
                            "user": _user_info_from_demo(username, user),
                            "mfa_verified": payload.get("mfa_verified", False),
                        }
                    )
        return ok({"valid": False, "user": None})

    # 回退：旧版内存 token
    if token in _legacy_token_store:
        return ok({"valid": True, "user": _legacy_token_store[token]})

    return ok({"valid": False, "user": None})
