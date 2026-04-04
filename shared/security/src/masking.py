"""数据脱敏工具 — API 返回时对敏感字段脱敏

等保三级要求：敏感个人信息在展示层必须脱敏，防止越权查看。

用法:
    mask_phone("13812345678")              → "138****5678"
    mask_id_card("420102199001011234")     → "4201**********1234"
    mask_bank_card("6222021234567890")     → "6222****7890"
    mask_name("张三丰")                    → "张**"
    mask_email("test@example.com")         → "t***@example.com"

规则说明:
    - 手机号: 保留前3后4，中间4位用 * 替换
    - 身份证: 保留前4后4，中间用 * 替换
    - 银行卡: 保留前4后4，中间用 * 替换
    - 姓名: 保留第一个字，其余用 * 替换
    - 邮箱: 用户名保留首字符，其余用 * 替换，@ 后域名保留
"""
from __future__ import annotations


def mask_phone(phone: str) -> str:
    """手机号脱敏：138****5678。

    支持 11 位手机号和带 +86 前缀的格式。
    """
    if not phone:
        return ""
    # 去除可能的 +86 前缀
    digits = phone.lstrip("+").lstrip("86") if phone.startswith("+86") else phone
    if len(digits) == 11:
        return f"{digits[:3]}****{digits[-4:]}"
    # 非标准长度：保留前后各 1/4，中间脱敏
    if len(phone) >= 4:
        keep = max(1, len(phone) // 4)
        return phone[:keep] + "*" * (len(phone) - keep * 2) + phone[-keep:]
    return "***"


def mask_id_card(id_card: str) -> str:
    """身份证号脱敏：4201**********1234。

    支持 15 位和 18 位身份证号。
    """
    if not id_card:
        return ""
    if len(id_card) >= 8:
        return f"{id_card[:4]}{'*' * (len(id_card) - 8)}{id_card[-4:]}"
    return "***"


def mask_bank_card(card_no: str) -> str:
    """银行卡号脱敏：6222****7890。

    保留前 4 后 4，中间用 * 替换。
    """
    if not card_no:
        return ""
    if len(card_no) >= 8:
        return f"{card_no[:4]}{'*' * (len(card_no) - 8)}{card_no[-4:]}"
    return "***"


def mask_name(name: str) -> str:
    """姓名脱敏：张**。

    保留第一个字（姓），其余用 * 替换。
    """
    if not name:
        return ""
    if len(name) == 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


def mask_email(email: str) -> str:
    """邮箱脱敏：t***@example.com。

    用户名保留首字符，其余用 * 替换，@ 后域名完整保留。
    """
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) == 1:
        return f"{local}***@{domain}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"
