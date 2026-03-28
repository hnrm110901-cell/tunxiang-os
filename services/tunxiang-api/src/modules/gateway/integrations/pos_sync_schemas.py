"""POS同步请求/响应模型"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class BackfillRequest(BaseModel):
    """手动回填请求"""

    merchant_code: str = Field(
        ...,
        description="商户编码：czyz(尝在一起) / zqx(最黔线) / sgc(尚宫厨)",
        pattern="^(czyz|zqx|sgc)$",
    )
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")
    store_ids: list[str] | None = Field(
        None, description="指定门店ID列表，为空则同步所有活跃门店"
    )
    max_days: int = Field(31, ge=1, le=90, description="最大允许天数")


class SyncTodayRequest(BaseModel):
    """同步今日数据请求（可选指定门店）"""

    store_ids: list[str] | None = Field(
        None, description="指定门店ID列表，为空则同步所有活跃门店"
    )


# ── 响应模型 ──────────────────────────────────────────────────────────────────


class StoreSyncSummary(BaseModel):
    """单门店同步结果"""

    store_id: str
    store_name: str
    orders_synced: int = 0
    orders_skipped: int = 0
    revenue_fen: int = 0
    error: str | None = None


class SyncResult(BaseModel):
    """一次同步操作结果"""

    success: bool
    merchant_code: str
    sync_date: str
    triggered_at: str
    stores: list[StoreSyncSummary]
    totals: dict[str, Any]


class SyncStatusResponse(BaseModel):
    """同步状态查询结果"""

    merchant_code: str
    last_sync_at: str | None = None
    last_sync_date: str | None = None
    stores_count: int = 0
    total_orders_today: int = 0
    status: str = "unknown"  # idle / syncing / error
