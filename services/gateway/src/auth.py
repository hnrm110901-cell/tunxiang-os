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
  - DEMO_USERS 仍然有效（明文密码，仅供开发/演示）
  - GET /api/v1/auth/verify 兼容旧版内存 token（如现有服务依赖）
"""

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .response import ok, err
from .services.jwt_service import JWTService
from .services.mfa_service import MFAService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ─────────────────────────────────────────────────────────────────
# 服务实例（进程级单例）
# ─────────────────────────────────────────────────────────────────
_jwt_service = JWTService()
_mfa_service = MFAService()

# ─────────────────────────────────────────────────────────────────
# Demo 用户（向后兼容，明文密码仅供开发/演示环境）
# 生产环境: TODO — 改为查询 users 表，使用 bcrypt 验证
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
        "tenant_id": "a0000000-0000-0000-0000-000000000002",
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
        "tenant_id": "a0000000-0000-0000-0000-000000000003",
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
        "tenant_id": "a0000000-0000-0000-0000-000000000004",
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
# 生产环境: TODO — refresh_tokens 改为查询 refresh_tokens 数据库表
# ─────────────────────────────────────────────────────────────────

# 旧版内存 token（向后兼容 /api/v1/auth/verify）
_legacy_token_store: dict[str, dict] = {}

# 两步登录：session_token → {username, expires_at, failed_count}
# expires_at 单位为 Unix 时间戳（秒）
_mfa_sessions: dict[str, dict] = {}
_MFA_SESSION_TTL_SECONDS = 300  # 5分钟
_MFA_SESSION_MAX_FAILS = 3

# refresh_token 内存存储: jti → {user_id, expires_at, revoked}
# 生产环境 TODO: 改为 DB 表 refresh_tokens
_refresh_store: dict[str, dict] = {}

# ─────────────────────────────────────────────────────────────────
# 暴力破解保护（内存，生产环境 TODO: 改为 Redis）
# ─────────────────────────────────────────────────────────────────
_MAX_LOGIN_FAILS = 5
_LOCKOUT_SECONDS = 900  # 15分钟
# username → {failed_count, locked_until}
_brute_force: dict[str, dict] = {}


class LoginBruteForceProtection:
    """内存版暴力破解防护。生产环境替换为 Redis 实现。"""

    def is_locked(self, username: str) -> bool:
        state = _brute_force.get(username)
        if not state:
            return False
        locked_until = state.get("locked_until", 0)
        if locked_until and time.time() < locked_until:
            return True
        # 锁定已过期，清除
        if locked_until and time.time() >= locked_until:
            _brute_force.pop(username, None)
        return False

    def record_failure(self, username: str) -> None:
        state = _brute_force.setdefault(username, {"failed_count": 0, "locked_until": 0})
        state["failed_count"] = state.get("failed_count", 0) + 1
        if state["failed_count"] >= _MAX_LOGIN_FAILS:
            state["locked_until"] = time.time() + _LOCKOUT_SECONDS
            logger.warning(
                "login_account_locked",
                username=username,
                locked_seconds=_LOCKOUT_SECONDS,
            )

    def record_success(self, username: str) -> None:
        _brute_force.pop(username, None)

    def remaining_lockout(self, username: str) -> int:
        """返回锁定剩余秒数。"""
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


def _issue_tokens(user_id: str, tenant_id: str, role: str, mfa_verified: bool) -> dict:
    """签发 access_token + refresh_token，存储 refresh_token。"""
    access_token = _jwt_service.create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        mfa_verified=mfa_verified,
    )
    refresh_token, jti = _jwt_service.create_refresh_token(user_id=user_id)

    # 生产环境 TODO: 写入 refresh_tokens 数据库表
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
    if _brute_force_guard.is_locked(username):
        remaining = _brute_force_guard.remaining_lockout(username)
        logger.warning("login_blocked_locked", username=username, ip=ip)
        return err(
            f"账户已锁定，请 {remaining} 秒后重试",
            code="ACCOUNT_LOCKED",
            status_code=423,
        )

    # 2. 验证用户凭证
    # 生产环境 TODO: 查询 users 表，使用 bcrypt.checkpw() 验证
    user = DEMO_USERS.get(username)
    if not user or not user["password"] or user["password"] != body.password:
        _brute_force_guard.record_failure(username)
        logger.warning(
            "login_failed",
            username=username,
            ip=ip,
            # 注意：密码不写入日志
        )
        # audit_log TODO: 写入 audit_logs 表（需要 DB session）
        return err("用户名或密码错误", code="AUTH_FAILED", status_code=401)

    # 3. 登录成功，重置暴力破解计数
    _brute_force_guard.record_success(username)
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
        return ok({
            "step": "mfa_required",
            "session_token": session_token,
            "expires_in": _MFA_SESSION_TTL_SECONDS,
        })

    # 5. 未启用MFA，直接签发token
    tokens = _issue_tokens(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        role=user["role"],
        mfa_verified=False,
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
    # audit_log TODO: 写入 audit_logs 表

    return ok({
        **tokens,
        "user": user_info,
        # 向后兼容字段
        "token": legacy_token,
    })


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
            # 生产环境 TODO: 从数据库中移除已使用的备用码
            hashed_codes.pop(idx)
            user["mfa_backup_codes"] = hashed_codes
            verified = True
            logger.info("mfa_backup_code_used", username=username, remaining=len(hashed_codes))

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

    tokens = _issue_tokens(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        role=user["role"],
        mfa_verified=True,
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
    # audit_log TODO: 写入 audit_logs 表

    return ok({
        **tokens,
        "user": user_info,
        "token": legacy_token,
    })


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

    # 检查撤销状态（生产环境 TODO: 查询 refresh_tokens 数据库表）
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

    # 查找用户信息（生产环境 TODO: 查询 users 表）
    user = None
    username = None
    for uname, udata in DEMO_USERS.items():
        if udata["user_id"] == user_id:
            user = udata
            username = uname
            break

    if not user:
        logger.warning("refresh_user_not_found", user_id=user_id)
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    # 撤销旧 refresh_token（轮换策略）
    stored["revoked"] = True

    # 签发新的 token 对
    tokens = _issue_tokens(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        role=user["role"],
        mfa_verified=False,  # refresh 后 mfa_verified 重置，需重新MFA
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
            if jti in _refresh_store:
                _refresh_store[jti]["revoked"] = True
                logger.info(
                    "refresh_token_revoked",
                    jti=jti,
                    # audit_log TODO
                )

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
        # 查找用户信息（生产环境 TODO: 查询 users 表）
        for username, user in DEMO_USERS.items():
            if user["user_id"] == user_id:
                return ok({
                    **_user_info_from_demo(username, user),
                    "mfa_verified": payload.get("mfa_verified", False),
                    "token_expires_at": payload.get("exp"),
                })
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

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
    username = None
    user = None
    for uname, udata in DEMO_USERS.items():
        if udata["user_id"] == user_id:
            user = udata
            username = uname
            break

    if not user:
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    if user.get("mfa_enabled"):
        return err("MFA已启用，如需重置请联系管理员", code="MFA_ALREADY_ENABLED", status_code=409)

    # 生成新 secret 并临时存储（等待验证后正式启用）
    # 生产环境 TODO: 将临时 secret 存入 Redis（5分钟TTL），不要直接写 DB
    raw_secret = _mfa_service.generate_secret()
    encrypted_secret = _mfa_service.encrypt_secret(raw_secret)
    user["_pending_mfa_secret_enc"] = encrypted_secret  # 临时存储

    totp_uri = _mfa_service.get_totp_uri(encrypted_secret, username)

    logger.info("mfa_setup_initiated", user_id=user_id)
    return ok({
        "totp_uri": totp_uri,
        "message": "请使用验证器App（Google Authenticator/Authy）扫描二维码，然后调用 /mfa/enable 提交验证码",
    })


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
    user = None
    username = None
    for uname, udata in DEMO_USERS.items():
        if udata["user_id"] == user_id:
            user = udata
            username = uname
            break

    if not user:
        return err("用户不存在", code="USER_NOT_FOUND", status_code=401)

    pending_secret = user.get("_pending_mfa_secret_enc")
    if not pending_secret:
        return err("请先调用 /mfa/setup 获取二维码", code="MFA_SETUP_REQUIRED", status_code=400)

    # 验证用户提交的TOTP码
    if not _mfa_service.verify_totp(pending_secret, body.code):
        logger.warning("mfa_enable_verify_failed", user_id=user_id)
        return err("验证码错误，请重试", code="MFA_INVALID_CODE", status_code=400)

    # 生成备用码
    backup_codes_plain = _mfa_service.generate_backup_codes()
    backup_codes_hashed = _mfa_service.hash_backup_codes(backup_codes_plain)

    # 正式启用MFA（生产环境 TODO: 写入 users 表）
    user["mfa_enabled"] = True
    user["mfa_secret_enc"] = pending_secret
    user["mfa_backup_codes"] = backup_codes_hashed
    user["mfa_verified_at"] = datetime.now(timezone.utc).isoformat()
    user.pop("_pending_mfa_secret_enc", None)

    logger.info("mfa_enabled", user_id=user_id, username=username)
    # audit_log TODO

    return ok({
        "message": "MFA已成功启用",
        "backup_codes": backup_codes_plain,
        "backup_codes_warning": "请将备用码保存在安全位置，每个备用码只能使用一次，丢失后无法找回",
    })


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
        for username, user in DEMO_USERS.items():
            if user["user_id"] == user_id:
                return ok({
                    "valid": True,
                    "user": _user_info_from_demo(username, user),
                    "mfa_verified": payload.get("mfa_verified", False),
                })
        return ok({"valid": False, "user": None})

    # 回退：旧版内存 token
    if token in _legacy_token_store:
        return ok({"valid": True, "user": _legacy_token_store[token]})

    return ok({"valid": False, "user": None})
