"""
数据脱敏工具 — 用于API响应、日志、导出
合规场景: GDPR/个人信息保护法

使用方式:
    from shared.utils.data_masker import DataMasker

    DataMasker.mask_phone("13812348888")              # "138****8888"
    DataMasker.mask_id_card("110101199001011234")      # "110***********1234"
    DataMasker.mask_email("user@example.com")          # "u***@example.com"
    DataMasker.mask_bank_account("6225880112346789")   # "****6789"
    DataMasker.mask_dict({"phone": "13812348888", "name": "张三"})
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable


def _mask_phone(phone: str | None) -> str | None:
    """
    手机号脱敏: 保留前3位和后4位，中间替换为 ****。
    示例: "13812348888" → "138****8888"
    支持带国际区号或分隔符的号码，提取纯数字后脱敏。
    """
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return "*" * len(phone)
    if len(digits) == 11:
        return digits[:3] + "****" + digits[7:]
    return digits[:3] + "****" + digits[-4:]


def _mask_id_card(id_card: str | None) -> str | None:
    """
    身份证号脱敏: 前3位 + 中间全遮盖 + 后4位明文。
    示例: "110101199001011234" → "110***********1234"
    """
    if id_card is None:
        return None
    s = id_card.strip()
    if len(s) <= 7:
        return "*" * len(s)
    prefix = s[:3]
    suffix = s[-4:]
    stars = "*" * (len(s) - 7)
    return prefix + stars + suffix


def _mask_email(email: str | None) -> str | None:
    """
    邮箱脱敏: 用户名保留首字符，其余替换为 ***，域名明文。
    示例: "user@example.com" → "u***@example.com"
    """
    if email is None:
        return None
    at_pos = email.find("@")
    if at_pos < 0:
        return "***"
    local = email[:at_pos]
    domain = email[at_pos:]  # 含 @
    if not local:
        return "***" + domain
    return local[0] + "***" + domain


def _mask_bank_account(account: str | None) -> str | None:
    """
    银行卡/账号脱敏: 仅保留后4位，前面全部遮盖为 ****。
    示例: "6225880112346789" → "****6789"
    """
    if account is None:
        return None
    digits = re.sub(r"\D", "", account)
    if len(digits) <= 4:
        return "*" * len(account)
    return "****" + digits[-4:]


# 模块级默认敏感字段 → 脱敏函数映射
_DEFAULT_SENSITIVE: dict[str, Callable[[Any], Any]] = {
    "phone": _mask_phone,
    "mobile": _mask_phone,
    "id_card_no": _mask_id_card,
    "email": _mask_email,
    "bank_account": _mask_bank_account,
}


def _mask_recursive(obj: Any, fields: set[str]) -> None:
    """
    就地递归脱敏（作用于 deepcopy 副本，不修改原始对象）。
    支持嵌套 dict 和 list。
    """
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if key in fields:
                masker_fn = _DEFAULT_SENSITIVE.get(key)
                if masker_fn is not None:
                    obj[key] = masker_fn(obj[key])
                else:
                    obj[key] = "***" if obj[key] is not None else None
            else:
                _mask_recursive(obj[key], fields)
    elif isinstance(obj, list):
        for item in obj:
            _mask_recursive(item, fields)


class DataMasker:
    """
    数据脱敏工具类。

    所有 mask_* 静态方法对 None 输入安全（返回 None，不抛异常）。
    mask_dict 深拷贝输入，不修改原始字典（immutable 语义）。
    """

    @staticmethod
    def mask_phone(phone: str | None) -> str | None:
        return _mask_phone(phone)

    @staticmethod
    def mask_id_card(id_card: str | None) -> str | None:
        return _mask_id_card(id_card)

    @staticmethod
    def mask_email(email: str | None) -> str | None:
        return _mask_email(email)

    @staticmethod
    def mask_bank_account(account: str | None) -> str | None:
        return _mask_bank_account(account)

    @staticmethod
    def mask_dict(data: dict, fields: set[str] | None = None) -> dict:
        """
        递归脱敏字典中的敏感字段。

        参数:
            data:   待脱敏的字典
            fields: 需要脱敏的字段名集合，为 None 则使用默认敏感字段集合

        返回:
            脱敏后的新字典（深拷贝，不修改原始 data）
        """
        effective_fields: set[str] = (
            fields if fields is not None else set(_DEFAULT_SENSITIVE.keys())
        )
        result = copy.deepcopy(data)
        _mask_recursive(result, effective_fields)
        return result

    # 暴露默认敏感字段集合，方便外部查询
    DEFAULT_SENSITIVE: dict[str, Callable[[Any], Any]] = _DEFAULT_SENSITIVE
