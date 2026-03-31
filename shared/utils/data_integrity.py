"""
HMAC-SHA256数据完整性校验
用于防止数据库记录被篡改（订单金额/财务记录）
密钥：TX_INTEGRITY_SECRET 环境变量
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class DataIntegrity:
    def __init__(self) -> None:
        secret = os.environ.get("TX_INTEGRITY_SECRET", "")
        if not secret:
            logger.warning("TX_INTEGRITY_SECRET未配置，数据完整性校验不可用")
        self._secret: bytes = secret.encode("utf-8")

    def sign(self, data: dict, fields: list[str]) -> str:
        """对指定字段（排序后）计算HMAC-SHA256签名。

        Args:
            data: 包含待签名字段的字典
            fields: 参与签名的字段名列表（顺序无关，内部排序）

        Returns:
            64字符十六进制HMAC-SHA256签名

        Raises:
            RuntimeError: TX_INTEGRITY_SECRET未配置
        """
        if not self._secret:
            raise RuntimeError("TX_INTEGRITY_SECRET未配置，无法计算签名")

        payload = json.dumps(
            {k: str(data[k]) for k in sorted(fields) if k in data},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hmac.new(
            self._secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def verify(self, data: dict, fields: list[str], signature: str) -> bool:
        """验证签名，使用时间恒定比较防时序攻击。

        Args:
            data: 包含待验证字段的字典
            fields: 参与签名的字段名列表
            signature: 待验证的HMAC签名（十六进制字符串）

        Returns:
            True表示签名有效，False表示签名无效或为空
        """
        if not signature:
            return False
        if not self._secret:
            raise RuntimeError("TX_INTEGRITY_SECRET未配置，无法验证签名")
        expected = self.sign(data, fields)
        return hmac.compare_digest(expected, signature)

    # 订单完整性签名字段（金额相关核心字段）
    ORDER_INTEGRITY_FIELDS: list[str] = [
        "id",
        "tenant_id",
        "total_amount",
        "discount_amount",
        "final_amount",
    ]

    # 财务记录完整性签名字段
    FINANCE_INTEGRITY_FIELDS: list[str] = [
        "id",
        "tenant_id",
        "amount",
        "type",
        "reference_id",
    ]


# 模块级单例
_integrity: Optional[DataIntegrity] = None


def _get_integrity() -> DataIntegrity:
    global _integrity
    if _integrity is None:
        _integrity = DataIntegrity()
    return _integrity


def sign_order(order_data: dict) -> str:
    """计算订单完整性签名。"""
    return _get_integrity().sign(order_data, DataIntegrity.ORDER_INTEGRITY_FIELDS)


def verify_order(order_data: dict, signature: str) -> bool:
    """验证订单完整性签名。"""
    return _get_integrity().verify(
        order_data, DataIntegrity.ORDER_INTEGRITY_FIELDS, signature
    )


def sign_finance(finance_data: dict) -> str:
    """计算财务记录完整性签名。"""
    return _get_integrity().sign(finance_data, DataIntegrity.FINANCE_INTEGRITY_FIELDS)


def verify_finance(finance_data: dict, signature: str) -> bool:
    """验证财务记录完整性签名。"""
    return _get_integrity().verify(
        finance_data, DataIntegrity.FINANCE_INTEGRITY_FIELDS, signature
    )
