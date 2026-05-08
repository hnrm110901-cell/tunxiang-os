"""驾驶舱 Pin 洞察 service 层 — S4-04 Issue #291 / Tier 3。

职责（PR1 范围）：
  - PinnedItem 数据结构（A2UI surface_snapshot + 元数据）
  - add_pin / list_pins / remove_pin 三个核心操作
  - tenant 隔离（in-memory store 按 tenant_id 分区）
  - FIFO 淘汰（每 tenant 上限 20，超出从最旧开始淘汰）

不在 PR1 范围（留 PR2）：
  - DB 持久化（迁移 v230+ 加 dashboard_pinned 表 + RLS policy）
  - HTTP 路由 + tx-analytics main.py 注册
  - 真 RLS 反测（PR1 in-memory tenant 隔离仅靠 dict key，PR2 上 RLS 后真验）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Pin 数量上限（每 tenant），超出 FIFO 淘汰最旧项
PIN_LIMIT_PER_TENANT = 20


@dataclass
class PinnedItem:
    pin_id: str
    tenant_id: str
    pinner_user_id: str
    pinned_at: datetime
    surface_snapshot: dict[str, Any]  # A2UI JSON declaration
    source_query_id: Optional[str] = None
    source_natural_query: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin_id": self.pin_id,
            "tenant_id": self.tenant_id,
            "pinner_user_id": self.pinner_user_id,
            "pinned_at": self.pinned_at.isoformat(),
            "surface_snapshot": self.surface_snapshot,
            "source_query_id": self.source_query_id,
            "source_natural_query": self.source_natural_query,
        }


# In-memory store: tenant_id -> list[PinnedItem]，最新在 list[0]（PR2 接 DB 后此 store 删除）
_PINNED_STORE: dict[str, list[PinnedItem]] = {}


def add_pin(
    *,
    tenant_id: str,
    pinner_user_id: str,
    surface_snapshot: dict[str, Any],
    source_query_id: Optional[str] = None,
    source_natural_query: Optional[str] = None,
) -> PinnedItem:
    """新增 Pin。最新插在列表头；超出 PIN_LIMIT_PER_TENANT 时尾部 FIFO 淘汰。

    tenant_id 必填非空 — 防止 RLS 绕过（PR2 接 DB 后由 RLS policy 强制）。
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id 必填非空（防 RLS 绕过）")
    if not pinner_user_id or not pinner_user_id.strip():
        raise ValueError("pinner_user_id 必填非空（决策留痕）")

    item = PinnedItem(
        pin_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        pinner_user_id=pinner_user_id,
        pinned_at=datetime.now(timezone.utc),
        surface_snapshot=surface_snapshot,
        source_query_id=source_query_id,
        source_natural_query=source_natural_query,
    )
    bucket = _PINNED_STORE.setdefault(tenant_id, [])
    bucket.insert(0, item)  # 最新在头
    # FIFO 淘汰：超出 PIN_LIMIT_PER_TENANT 时砍掉尾部
    if len(bucket) > PIN_LIMIT_PER_TENANT:
        del bucket[PIN_LIMIT_PER_TENANT:]
    return item


def list_pins(tenant_id: str) -> list[PinnedItem]:
    """列出 tenant 的所有 pinned items（最新在前）。"""
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id 必填非空（防 RLS 绕过）")
    return list(_PINNED_STORE.get(tenant_id, []))


def remove_pin(*, tenant_id: str, pin_id: str) -> bool:
    """删除 Pin。返回 True 表示找到并删，False 表示该 tenant 下无此 pin_id。"""
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id 必填非空（防 RLS 绕过）")
    bucket = _PINNED_STORE.get(tenant_id, [])
    for i, item in enumerate(bucket):
        if item.pin_id == pin_id:
            del bucket[i]
            return True
    return False


def _clear_for_test() -> None:
    """测试 fixture 用：清空 in-memory store。生产代码不调用。"""
    _PINNED_STORE.clear()
