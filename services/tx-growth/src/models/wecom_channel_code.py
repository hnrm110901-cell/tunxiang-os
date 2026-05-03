"""渠道活码数据模型

WecomChannelCode — 企微渠道活码配置
渠道活码用于追踪不同渠道来源的扫码客户，支持自动打标签、自动回复、自动拉群。

MVP 阶段：数据存储在内存列表中，后续可迁移到 DB。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WecomChannelCode(BaseModel):
    """企微渠道活码配置

    每个渠道活码对应一个企微联系二维码，扫码添加好友后：
    - 自动打标签（auto_tags）
    - 自动回复文案（auto_reply）
    - 自动拉入指定群（group_id）
    - 记录扫码次数（scan_count）
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    merchant_code: str = Field(..., description="商户编码")
    channel_name: str = Field(..., description='渠道名称，如"海报-店门口-2026Q2"')
    qrcode_url: str = Field(..., description="企微联系二维码URL")
    auto_tags: list[str] = Field(default_factory=list, description="自动打标签列表")
    auto_reply: str = Field(default="", description="自动回复文案")
    group_id: str | None = Field(default=None, description="自动拉群ID")
    scan_count: int = Field(default=0, description="扫码次数")
    is_active: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（路由响应用）"""
        return {
            "id": self.id,
            "merchant_code": self.merchant_code,
            "channel_name": self.channel_name,
            "qrcode_url": self.qrcode_url,
            "auto_tags": list(self.auto_tags),
            "auto_reply": self.auto_reply,
            "group_id": self.group_id,
            "scan_count": self.scan_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
