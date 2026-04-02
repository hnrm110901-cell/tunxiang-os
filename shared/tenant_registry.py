"""商户编码 ↔ 租户 UUID — 单一事实源

与 `services/gateway/src/auth.py` 中 DEMO 用户（尝在一起 / 最黔线 / 尚宫厨）的
`tenant_id` 保持一致，供 POS 同步、集成任务等引用。

生产环境应以数据库 `tenants` 表为准；本映射用于演示与品智商户码对齐。
"""

from __future__ import annotations

from uuid import UUID

# 商户编码（品智/集成）→ 租户 UUID（与 Gateway DEMO changzaiyiqi / zuiqianxian / shanggongchu 对齐）
MERCHANT_CODE_TO_TENANT_UUID: dict[str, str] = {
    "czyz": "a0000000-0000-0000-0000-000000000002",  # 尝在一起
    "zqx": "a0000000-0000-0000-0000-000000000003",  # 最黔线
    "sgc": "a0000000-0000-0000-0000-000000000004",  # 尚宫厨
}


def tenant_uuid_for_merchant_code(merchant_code: str) -> UUID:
    """解析商户编码为租户 UUID；未知编码抛 KeyError。"""
    s = merchant_code.strip().lower()
    tid = MERCHANT_CODE_TO_TENANT_UUID.get(s)
    if not tid:
        raise KeyError(f"unknown_merchant_code:{merchant_code}")
    return UUID(tid)
