"""认证路由 — 登录/登出/会话验证

MVP直接内嵌简化auth，不依赖gateway的import路径。
"""
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...shared.response import err, ok

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Demo users — 与 gateway auth.py 保持一致
DEMO_USERS = {
    "admin": {
        "password": "admin123",
        "name": "系统管理员",
        "role": "admin",
        "tenant_id": "t-platform",
        "merchant": "屯象科技",
    },
    "changzaiyiqi": {
        "password": "czq2026",
        "name": "尝在一起管理员",
        "role": "merchant_admin",
        "tenant_id": "t-czq",
        "merchant": "尝在一起",
    },
    "zuiqianxian": {
        "password": "zqx2026",
        "name": "最黔线管理员",
        "role": "merchant_admin",
        "tenant_id": "t-zqx",
        "merchant": "最黔线",
    },
    "shanggongchu": {
        "password": "sgc2026",
        "name": "尚宫厨管理员",
        "role": "merchant_admin",
        "tenant_id": "t-sgc",
        "merchant": "尚宫厨",
    },
    "xuji": {
        "password": "xj2026",
        "name": "徐记海鲜管理员",
        "role": "merchant_admin",
        "tenant_id": "t-xuji",
        "merchant": "徐记海鲜",
    },
}

_token_store: dict[str, dict] = {}


class LoginBody(BaseModel):
    username: str
    password: str


def _user_info(username: str, user: dict) -> dict:
    return {
        "username": username,
        "name": user["name"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "merchant": user["merchant"],
    }


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


@router.post("/login")
async def login(body: LoginBody):
    user = DEMO_USERS.get(body.username)
    if not user or user["password"] != body.password:
        return err("用户名或密码错误", code="AUTH_FAILED", status_code=401)

    token = uuid.uuid4().hex
    info = _user_info(body.username, user)
    _token_store[token] = info
    return ok({"token": token, "user": info})


@router.post("/logout")
async def logout(request: Request):
    token = _extract_token(request)
    if token and token in _token_store:
        del _token_store[token]
    return ok({"message": "已登出"})


@router.get("/me")
async def me(request: Request):
    token = _extract_token(request)
    if not token or token not in _token_store:
        return err("未登录或 Token 已过期", code="UNAUTHORIZED", status_code=401)
    return ok(_token_store[token])
