"""营销活动 API — 8个端点（v097 DB 化版本）

端点:
1. POST   /api/v1/campaigns              创建活动
2. POST   /api/v1/campaigns/{id}/start    启动活动
3. POST   /api/v1/campaigns/{id}/pause    暂停活动
4. POST   /api/v1/campaigns/{id}/end      结束活动
5. GET    /api/v1/campaigns/{id}          活动详情
6. GET    /api/v1/campaigns               活动列表
7. POST   /api/v1/campaigns/{id}/check    资格检查
8. GET    /api/v1/campaigns/{id}/analytics 活动效果分析
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.campaign_engine import CampaignEngine
from ..services.campaign_repository import CampaignRepository

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

engine = CampaignEngine()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    campaign_type: str
    config: dict


class CheckEligibilityRequest(BaseModel):
    customer_id: str


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.post("")
async def create_campaign(
    req: CreateCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建营销活动"""
    result = await engine.create_campaign(req.campaign_type, req.config, x_tenant_id, db=db)
    if "error" in result:
        return error_response(result["error"])
    await db.commit()
    return ok_response(result)


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """启动活动"""
    result = await engine.start_campaign(campaign_id, x_tenant_id, db=db)
    if "error" in result:
        return error_response(result["error"])
    await db.commit()
    return ok_response(result)


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """暂停活动"""
    result = await engine.pause_campaign(campaign_id, x_tenant_id, db=db)
    if "error" in result:
        return error_response(result["error"])
    await db.commit()
    return ok_response(result)


@router.post("/{campaign_id}/end")
async def end_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """结束活动"""
    result = await engine.end_campaign(campaign_id, x_tenant_id, db=db)
    if "error" in result:
        return error_response(result["error"])
    await db.commit()
    return ok_response(result)


@router.get("/{campaign_id}")
async def get_campaign_detail(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取活动详情"""
    repo = CampaignRepository(db, x_tenant_id)
    campaign = await repo.get_campaign(campaign_id)
    if not campaign:
        return error_response(f"活动不存在: {campaign_id}")
    return ok_response(campaign)


@router.get("")
async def list_campaigns_endpoint(
    status: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取活动列表"""
    repo = CampaignRepository(db, x_tenant_id)
    result = await repo.list_campaigns(status)
    return ok_response({"items": result, "total": len(result)})


@router.post("/{campaign_id}/check")
async def check_eligibility(
    campaign_id: str,
    req: CheckEligibilityRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """检查客户活动资格"""
    result = await engine.check_eligibility(
        req.customer_id, campaign_id, x_tenant_id, db=db
    )
    return ok_response(result)


@router.get("/{campaign_id}/analytics")
async def get_campaign_analytics(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取活动效果分析"""
    result = await engine.get_campaign_analytics(campaign_id, x_tenant_id, db=db)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)
