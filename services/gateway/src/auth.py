"""认证服务 — JWT 令牌签发/验证 + bcrypt 密码哈希"""
import os
from datetime import datetime, timedelta, timezone

import jwt
import structlog
from fastapi import APIRouter, Request
from passlib.context import CryptContext
from pydantic import BaseModel

from .response import ok, err

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

JWT_SECRET = os.environ.get("JWT_SECRET", "tunxiang-dev-secret-key-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEMO_USERS: dict[str, dict] = {
    # 尝在一起（品智czyq.pinzhikeji.net, 3家门店: 文化城/浏小鲜/永安）
    "czyz_admin": {"tenant_id": "10000000-0000-0000-0000-000000000001", "merchant": "尝在一起", "name": "尝在一起管理员", "role": "merchant_admin", "password_hash": pwd_context.hash("czyz@2026")},
    # 最黔线（品智ljcg.pinzhikeji.net, 6家门店: 马家湾/东欣万象/合众路/广州路/昆明路/仁怀）
    "zqx_admin": {"tenant_id": "10000000-0000-0000-0000-000000000002", "merchant": "最黔线", "name": "最黔线管理员", "role": "merchant_admin", "password_hash": pwd_context.hash("zqx@2026")},
    # 尚宫厨（品智xcsgc.pinzhikeji.net, 5家门店: 采霞街/湘江水岸/乐城/啫匠亲城/酃湖雅院）
    "sgc_admin": {"tenant_id": "10000000-0000-0000-0000-000000000003", "merchant": "尚宫厨", "name": "尚宫厨管理员", "role": "merchant_admin", "password_hash": pwd_context.hash("sgc@2026")},
    # 屯象科技超管（可切换查看任意商户）
    "tx_superadmin": {"tenant_id": "platform", "merchant": "屯象科技", "name": "屯象超级管理员", "role": "superadmin", "password_hash": pwd_context.hash("tunxiang2024!")},
}


def create_jwt_token(user_id: str, tenant_id: str, role: str, merchant_name: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"user_id": user_id, "tenant_id": tenant_id, "role": role, "merchant_name": merchant_name, "iat": now, "exp": now + timedelta(hours=JWT_EXPIRE_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginBody):
    user = DEMO_USERS.get(body.username)
    if not user or not pwd_context.verify(body.password, user["password_hash"]):
        logger.warning("login_failed", username=body.username)
        return err("用户名或密码错误", code="AUTH_FAILED", status_code=401)
    token = create_jwt_token(user_id=body.username, tenant_id=user["tenant_id"], role=user["role"], merchant_name=user["merchant"])
    user_info = {"username": body.username, "name": user["name"], "role": user["role"], "tenant_id": user["tenant_id"], "merchant": user["merchant"]}
    logger.info("login_success", username=body.username, tenant_id=user["tenant_id"])
    return ok({"token": token, "user": user_info})


@router.post("/logout")
async def logout(request: Request):
    logger.info("logout", user_id=getattr(request.state, "user_id", None))
    return ok({"message": "已登出"})


@router.get("/me")
async def me(request: Request):
    token = _extract_token(request)
    if not token:
        return err("未登录或 Token 已过期", code="UNAUTHORIZED", status_code=401)
    try:
        payload = decode_jwt_token(token)
    except jwt.ExpiredSignatureError:
        return err("Token 已过期", code="TOKEN_EXPIRED", status_code=401)
    except jwt.InvalidTokenError:
        return err("Token 无效", code="INVALID_TOKEN", status_code=401)
    return ok({"username": payload["user_id"], "name": DEMO_USERS.get(payload["user_id"], {}).get("name", payload["user_id"]), "role": payload["role"], "tenant_id": payload["tenant_id"], "merchant": payload["merchant_name"]})
