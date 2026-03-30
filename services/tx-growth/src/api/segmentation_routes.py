"""分群引擎 API — 7个端点

端点:
  GET    /api/v1/growth/segments                          所有分群列表（含缓存人数）
  GET    /api/v1/growth/segments/{segment_id}             分群详情
  GET    /api/v1/growth/segments/{segment_id}/members     分群成员（分页）
  POST   /api/v1/growth/segments/{segment_id}/count       快速获取人数
  POST   /api/v1/growth/segments                          创建自定义分群
  DELETE /api/v1/growth/segments/{segment_id}             删除自定义分群
  POST   /api/v1/growth/segments/refresh                  强制刷新缓存

所有端点必须携带 X-Tenant-ID Header（UUID 格式）。
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from services.audience_segmentation import (
    BUILTIN_SEGMENTS,
    AudienceSegmentationService,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/growth/segments", tags=["segmentation"])

_svc = AudienceSegmentationService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: int = 400) -> dict:
    return {"ok": False, "error": {"message": msg, "code": code}}


def _parse_tenant(x_tenant_id: str) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式无效: {x_tenant_id}")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class CustomSegmentRule(BaseModel):
    field: str = Field(..., description="字段名，如 r_score / tags / last_order_at")
    op: str = Field(..., description="操作符：eq/ne/gt/gte/lt/lte/in/contains/between")
    value: Any = Field(..., description="匹配值")


class CreateSegmentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="分群名称")
    rules: list[CustomSegmentRule] = Field(..., min_length=1, description="AND 逻辑规则列表")


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.get("")
async def list_segments(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """返回所有内置分群 + 该租户的自定义分群，附带缓存的 total 人数（5分钟缓存）。

    首次调用时 total 为 null（缓存尚未建立），可调用 /refresh 预热。
    """
    tenant_id = _parse_tenant(x_tenant_id)
    segments = await _svc.list_segments(tenant_id)
    return ok_response({"items": segments, "total": len(segments)})


@router.get("/refresh")
async def refresh_hint() -> dict:
    """提示：刷新缓存请用 POST /refresh。"""
    return error_response("请使用 POST /api/v1/growth/segments/refresh 刷新缓存", 405)


@router.post("/refresh")
async def refresh_segment_cache(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """强制刷新当前租户所有分群的人数缓存（内置 + 自定义）。

    适合后台任务或运营人员手动触发；缓存刷新期间接口响应可能略慢。
    """
    tenant_id = _parse_tenant(x_tenant_id)
    try:
        result = await _svc.refresh_segment_cache(tenant_id)
    except httpx.HTTPError as exc:
        logger.error("segment_cache_refresh_http_error", error=str(exc), exc_info=exc)
        raise HTTPException(status_code=502, detail=f"调用 tx-member 失败: {exc}")
    return ok_response(result)


@router.get("/{segment_id}")
async def get_segment_detail(
    segment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """分群详情：返回分群定义 + 规则（自定义）或参数（内置）。"""
    tenant_id = _parse_tenant(x_tenant_id)

    # 内置分群
    builtin = BUILTIN_SEGMENTS.get(segment_id)
    if builtin:
        return ok_response({
            "segment_id": segment_id,
            "name": builtin["name"],
            "description": builtin.get("description", ""),
            "segment_type": "builtin",
            "definition": builtin,
        })

    # 自定义分群（使用 list 过滤）
    segments = await _svc.list_segments(tenant_id)
    for seg in segments:
        if seg["segment_id"] == segment_id:
            return ok_response(seg)

    raise HTTPException(status_code=404, detail=f"分群不存在: {segment_id}")


@router.get("/{segment_id}/members")
async def get_segment_members(
    segment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(100, ge=1, le=500, description="每页条数"),
) -> dict:
    """获取分群成员列表（分页），返回 customer_id 列表。

    请求 tx-member 实时计算，size 上限 500 条/请求。
    """
    tenant_id = _parse_tenant(x_tenant_id)
    try:
        result = await _svc.get_segment_members(segment_id, tenant_id, page, size)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except httpx.HTTPError as exc:
        logger.error("segment_members_http_error",
                     segment_id=segment_id, tenant_id=str(tenant_id),
                     error=str(exc), exc_info=exc)
        raise HTTPException(status_code=502, detail=f"调用 tx-member 失败: {exc}")
    return ok_response(result)


@router.post("/{segment_id}/count")
async def count_segment(
    segment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """快速获取分群人数（优先读 5 分钟缓存，用于活动预估触达量）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    try:
        count = await _svc.count_segment(segment_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except httpx.HTTPError as exc:
        logger.error("segment_count_http_error",
                     segment_id=segment_id, tenant_id=str(tenant_id),
                     error=str(exc), exc_info=exc)
        raise HTTPException(status_code=502, detail=f"调用 tx-member 失败: {exc}")
    return ok_response({"segment_id": segment_id, "count": count})


@router.post("")
async def create_custom_segment(
    req: CreateSegmentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建自定义分群。

    规则格式（AND 逻辑）：
    ```json
    {
      "name": "高价值沉睡客",
      "rules": [
        {"field": "r_score",  "op": "lte", "value": 2},
        {"field": "m_score",  "op": "gte", "value": 4},
        {"field": "total_order_amount_fen", "op": "gte", "value": 100000}
      ]
    }
    ```

    支持字段：rfm_level / r_score / f_score / m_score / risk_score /
              last_order_at / total_order_count / total_order_amount_fen /
              tags / store_id / source

    支持操作符：eq / ne / gt / gte / lt / lte / in / contains / between
    """
    tenant_id = _parse_tenant(x_tenant_id)
    rules_dicts = [r.model_dump() for r in req.rules]
    try:
        segment = await _svc.create_custom_segment(req.name, rules_dicts, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok_response(segment)


@router.delete("/{segment_id}")
async def delete_custom_segment(
    segment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除租户自定义分群（内置分群不可删除）。"""
    # 不允许删除内置分群
    if segment_id in BUILTIN_SEGMENTS:
        raise HTTPException(status_code=403, detail="内置分群不可删除")

    tenant_id = _parse_tenant(x_tenant_id)
    deleted = await _svc.delete_custom_segment(segment_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"分群不存在: {segment_id}")
    return ok_response({"deleted": True, "segment_id": segment_id})
