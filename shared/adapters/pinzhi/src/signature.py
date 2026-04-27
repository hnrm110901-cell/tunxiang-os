"""
品智收银系统签名认证工具
支持 MD5 签名和 HMAC-SHA256 签名
"""

import hashlib
import hmac
import time
from collections import OrderedDict
from typing import Any, Dict


def generate_sign(token: str, params: Dict[str, Any]) -> str:
    """
    生成品智API签名（MD5方式）

    签名算法:
    1. 将所有请求参数（除sign外）按参数名ASCII码升序排列
    2. 排除pageIndex和pageSize参数
    3. 拼接成key1=value1&key2=value2&...&token=xxx格式
    4. 对拼接后的字符串进行MD5加密得到签名值

    Args:
        token: API Token
        params: 请求参数字典

    Returns:
        MD5签名字符串（32位小写）

    Example:
        >>> params = {"ognid": "12345", "beginDate": "2024-01-01"}
        >>> sign = generate_sign("your_token", params)
        >>> print(sign)
        'a1b2c3d4e5f6...'
    """
    # 1. 过滤掉sign、pageIndex、pageSize参数
    filtered_params = {k: v for k, v in params.items() if k not in ["sign", "pageIndex", "pageSize"] and v is not None}

    # 2. 按key排序
    ordered_params = OrderedDict(sorted(filtered_params.items()))

    # 3. 构建参数字符串
    param_list = [f"{k}={v}" for k, v in ordered_params.items()]
    param_str = "&".join(param_list)

    # 4. 添加token
    param_str += f"&token={token}"

    # 5. MD5加密（小写，实测品智服务器只接受小写）
    sign = hashlib.md5(param_str.encode("utf-8")).hexdigest()

    return sign


def verify_sign(token: str, params: Dict[str, Any], expected_sign: str) -> bool:
    """
    验证品智API签名

    Args:
        token: API Token
        params: 请求参数字典
        expected_sign: 期望的签名值

    Returns:
        签名是否正确
    """
    calculated_sign = generate_sign(token, params)
    return calculated_sign == expected_sign


def pinzhi_sign(params: dict, secret: str) -> str:
    """
    通用签名函数，支持 MD5 和 HMAC-SHA256 两种模式。

    当 secret 长度 <= 32 时使用 MD5（兼容品智原有 token 签名），
    否则使用 HMAC-SHA256（适用于新版 API 密钥较长的场景）。

    Args:
        params: 请求参数字典（sign 字段自动排除）
        secret: 密钥（品智 token 或 HMAC secret）

    Returns:
        签名字符串（32位小写十六进制）
    """
    # 过滤并排序参数
    filtered = {k: v for k, v in params.items() if k not in ("sign", "pageIndex", "pageSize") and v is not None}
    ordered = OrderedDict(sorted(filtered.items()))
    param_str = "&".join(f"{k}={v}" for k, v in ordered.items())

    if len(secret) <= 32:
        # MD5 模式：与 generate_sign 保持一致
        raw = f"{param_str}&token={secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()
    else:
        # HMAC-SHA256 模式
        return hmac.new(
            secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]


def build_auth_headers(api_key: str, secret: str, timestamp: int | None = None) -> dict:
    """
    构建品智 API 认证请求头。

    Args:
        api_key: API Key（品智分配的 appId / api_key）
        secret: API Secret（品智分配的 token / secret）
        timestamp: Unix 时间戳（秒），不传则自动取当前时间

    Returns:
        包含认证信息的请求头字典，可直接传入 httpx 请求
    """
    if timestamp is None:
        timestamp = int(time.time())

    sign_params = {
        "api_key": api_key,
        "timestamp": str(timestamp),
    }
    sign_value = pinzhi_sign(sign_params, secret)

    return {
        "X-Api-Key": api_key,
        "X-Timestamp": str(timestamp),
        "X-Sign": sign_value,
        "Content-Type": "application/x-www-form-urlencoded",
    }
