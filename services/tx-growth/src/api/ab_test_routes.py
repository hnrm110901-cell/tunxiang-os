"""AB测试 API — 实验创建/管理/统计结果

端点：
  POST /api/v1/growth/ab-tests                   创建AB测试
  GET  /api/v1/growth/ab-tests                   测试列表
  GET  /api/v1/growth/ab-tests/{id}              测试详情（含实时结果）
  POST /api/v1/growth/ab-tests/{id}/start        开始测试
  POST /api/v1/growth/ab-tests/{id}/pause        暂停测试
  POST /api/v1/growth/ab-tests/{id}/conclude     手动结论
  POST /api/v1/growth/ab-tests/{id}/apply-winner 应用获胜变体
  GET  /api/v1/growth/ab-tests/{id}/results      详细统计结果
"""

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator
from services.ab_test_service import ABTestService
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/growth/ab-tests", tags=["ab-tests"])
_ab_svc = ABTestService()


# ---------------------------------------------------------------------------
# 统一响应格式
# ---------------------------------------------------------------------------


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _err(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ---------------------------------------------------------------------------
# 依赖：解析 X-Tenant-ID
# ---------------------------------------------------------------------------


async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误，需为 UUID")


# ---------------------------------------------------------------------------
# 依赖：DB Session
# ---------------------------------------------------------------------------


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------


class VariantItem(BaseModel):
    variant: str  # "A" 或 "B"
    name: str  # "控制组" / "实验组"
    weight: int  # 流量占比，所有变体 weight 之和须为 100
    content: dict[str, Any]  # {"title": ..., "description": ..., "offer_fen": ...}


class CreateABTestRequest(BaseModel):
    name: str
    campaign_id: Optional[str] = None
    journey_id: Optional[str] = None
    split_type: str = "random"  # random | rfm_based | store_based
    variants: list[VariantItem]
    primary_metric: str = "conversion_rate"  # conversion_rate | revenue | click_rate
    min_sample_size: int = 100
    confidence_level: float = 0.95

    @field_validator("variants")
    @classmethod
    def variants_weight_sum(cls, v: list[VariantItem]) -> list[VariantItem]:
        total = sum(item.weight for item in v)
        if total != 100:
            raise ValueError(f"variants weight 之和必须为 100，当前为 {total}")
        if len(v) < 2:
            raise ValueError("至少需要两个变体")
        return v

    @field_validator("confidence_level")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 < v < 1.0):
            raise ValueError("confidence_level 必须在 (0, 1) 之间")
        return v


class ConcludeRequest(BaseModel):
    winner_variant: Optional[str] = None  # None 表示"无结论"，"A"/"B" 表示手动指定


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("", summary="创建AB测试")
async def create_ab_test(
    req: CreateABTestRequest,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建一个新的 AB 测试实验。

    变体 weight 之和必须为 100。
    """
    try:
        test_data = req.model_dump()
        # VariantItem 转为普通 dict 列表
        test_data["variants"] = [v.model_dump() for v in req.variants]
        test = await _ab_svc.create_test(test_data, tenant_id, db)
        await db.commit()
        log.info("api.ab_test.created", test_id=str(test.id), tenant_id=str(tenant_id))
        return _ok(
            {
                "test_id": str(test.id),
                "name": test.name,
                "status": test.status,
                "split_type": test.split_type,
            }
        )
    except ValueError as exc:
        return _err(str(exc))


@router.get("", summary="AB测试列表")
async def list_ab_tests(
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出当前租户所有 AB 测试，附带实时结果摘要。"""
    tests = await _ab_svc.list_tests(tenant_id, db)
    return _ok({"items": tests, "total": len(tests)})


@router.get("/{test_id}", summary="测试详情+实时结果")
async def get_ab_test(
    test_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 AB 测试详情，包含实时统计结果。"""
    try:
        results = await _ab_svc.calculate_results(test_id, tenant_id, db)
        return _ok(results)
    except ValueError as exc:
        return _err(str(exc))


@router.post("/{test_id}/start", summary="开始测试")
async def start_ab_test(
    test_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将 AB 测试从 draft 切换到 running 状态。"""
    try:
        test = await _ab_svc.start_test(test_id, tenant_id, db)
        await db.commit()
        return _ok(
            {
                "test_id": str(test.id),
                "status": test.status,
                "started_at": test.started_at.isoformat() if test.started_at else None,
            }
        )
    except ValueError as exc:
        return _err(str(exc))


@router.post("/{test_id}/pause", summary="暂停测试")
async def pause_ab_test(
    test_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将 AB 测试从 running 切换到 paused 状态。"""
    try:
        test = await _ab_svc.pause_test(test_id, tenant_id, db)
        await db.commit()
        return _ok({"test_id": str(test.id), "status": test.status})
    except ValueError as exc:
        return _err(str(exc))


@router.post("/{test_id}/conclude", summary="手动结论")
async def conclude_ab_test(
    test_id: uuid.UUID,
    req: ConcludeRequest,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动指定 AB 测试结论，切换至 completed 状态。

    若未指定 winner_variant，则表示"无结论"（两组差异不显著，均不推广）。
    """
    try:
        test = await _ab_svc.conclude_test(test_id, tenant_id, req.winner_variant, db)
        await db.commit()
        return _ok(
            {
                "test_id": str(test.id),
                "status": test.status,
                "winner_variant": test.winner_variant,
                "ended_at": test.ended_at.isoformat() if test.ended_at else None,
            }
        )
    except ValueError as exc:
        return _err(str(exc))


@router.post("/{test_id}/apply-winner", summary="应用获胜变体")
async def apply_winner(
    test_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将统计显著的获胜变体内容应用到关联的活动/旅程。

    若实验尚未 completed，会先尝试自动结论。
    """
    try:
        result = await _ab_svc.apply_winner(test_id, tenant_id, db)
        await db.commit()
        return _ok(result)
    except ValueError as exc:
        return _err(str(exc))


@router.get("/{test_id}/results", summary="详细统计结果")
async def get_results(
    test_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取 AB 测试详细统计结果，含双比例 Z 检验 p 值与推荐结论。"""
    try:
        results = await _ab_svc.calculate_results(test_id, tenant_id, db)
        return _ok(results)
    except ValueError as exc:
        return _err(str(exc))
