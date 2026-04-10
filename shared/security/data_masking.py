"""
数据脱敏工具 — PII 字段自动遮掩

用途：日志输出、API 响应、数据导出时自动脱敏敏感字段
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


# PII 字段名列表（忽略大小写，支持下划线/驼峰）
_PII_FIELD_NAMES = frozenset([
    "phone", "mobile", "telephone", "cellphone",
    "email", "email_address",
    "id_card", "id_number", "national_id",
    "bank_card", "card_number", "account_number",
    "address", "home_address",
    "name", "full_name", "real_name",
    "password", "passwd", "secret", "token",
    "openid", "union_id",
])


def mask_phone(phone: str) -> str:
    """138****8888"""
    if len(phone) < 7:
        return "***"
    return phone[:3] + "****" + phone[-4:]


def mask_email(email: str) -> str:
    """te***@example.com"""
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[:2] + "***"
    return f"{masked_local}@{domain}"


def mask_id_card(id_card: str) -> str:
    """110***********1234"""
    if len(id_card) < 8:
        return "***"
    return id_card[:3] + "*" * (len(id_card) - 7) + id_card[-4:]


def mask_bank_card(card: str) -> str:
    """**** **** **** 1234"""
    digits = re.sub(r"\D", "", card)
    if len(digits) < 4:
        return "****"
    return "*" * (len(digits) - 4) + digits[-4:]


def mask_name(name: str) -> str:
    """张*"""
    if not name:
        return "***"
    return name[0] + "*" * (len(name) - 1)


def hash_pii(value: str, salt: str = "txos_pii_salt_v1") -> str:
    """SHA256 哈希，用于日志去标识化但保留关联性"""
    return hashlib.sha256(f"{salt}{value}".encode()).hexdigest()[:16]


def mask_value(field_name: str, value: Any) -> Any:
    """根据字段名自动选择脱敏策略"""
    if value is None or not isinstance(value, str):
        return value

    lower_name = field_name.lower().replace("-", "_")

    if any(k in lower_name for k in ("phone", "mobile", "cellphone", "telephone")):
        return mask_phone(value)
    if "email" in lower_name:
        return mask_email(value)
    if any(k in lower_name for k in ("id_card", "national_id", "id_number")):
        return mask_id_card(value)
    if any(k in lower_name for k in ("bank_card", "card_number", "account")):
        return mask_bank_card(value)
    if any(k in lower_name for k in ("password", "passwd", "secret", "token")):
        return "***REDACTED***"
    if lower_name in ("name", "full_name", "real_name"):
        return mask_name(value)
    if any(k in lower_name for k in ("openid", "union_id")):
        return value[:4] + "***" + value[-4:] if len(value) > 8 else "***"
    if "address" in lower_name:
        return value[:6] + "***" if len(value) > 6 else "***"

    return value


def mask_dict(data: dict[str, Any], deep: bool = True) -> dict[str, Any]:
    """递归脱敏字典中的 PII 字段"""
    result = {}
    for key, value in data.items():
        if isinstance(value, dict) and deep:
            result[key] = mask_dict(value, deep=True)
        elif isinstance(value, list) and deep:
            result[key] = [
                mask_dict(item, deep=True) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = mask_value(key, value)
    return result
