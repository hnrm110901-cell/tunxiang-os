"""马来西亚 SSM 企业注册验证 API 端点

端点：
  - POST /api/v1/ssm/verify              验证公司注册
  - GET  /api/v1/ssm/search               搜索公司
  - GET  /api/v1/ssm/company/{reg_no}     获取公司详情
  - POST /api/v1/ssm/validate-director    验证董事身份
"""

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.ssm_service import SSMService

router = APIRouter(prefix="/api/v1/ssm", tags=["ssm"])


# ── DI ──────────────────────────────────────────────────────────


async def get_ssm_service() -> SSMService:
    return SSMService()


# ── 请求/响应模型 ─────────────────────────────────────────────


class VerifyCompanyRequest(BaseModel):
    """公司验证请求"""

    registration_no: str = Field(..., min_length=1, description="SSM 注册号（如 202001000001）")
    company_name: str = Field(..., min_length=1, description="公司全名")


class VerifyCompanyResponse(BaseModel):
    """公司验证结果"""

    verified: bool
    company_name: str
    registration_no: str
    status: str
    company_type: str
    business_nature: str
    registered_address: dict[str, Any]
    expiry_date: str

    class Config:
        json_schema_extra = {
            "example": {
                "verified": True,
                "company_name": "Tunxiang Technology Sdn Bhd",
                "registration_no": "202001000001",
                "status": "active",
                "company_type": "Sdn Bhd",
                "business_nature": "软件开发与餐饮科技解决方案",
                "registered_address": {
                    "line1": "Level 12, Menara Bintang",
                    "line2": "Jalan Ampang",
                    "city": "Kuala Lumpur",
                    "postcode": "50450",
                    "state": "Wilayah Persekutuan",
                },
                "expiry_date": "2025-01-15",
            }
        }


class SearchCompanyResponse(BaseModel):
    """公司搜索结果"""

    total: int
    page: int
    size: int
    items: list[dict[str, Any]]


class CompanyDetailResponse(BaseModel):
    """公司详细信息"""

    found: bool
    registration_no: str
    company_name: Optional[str] = None
    former_name: Optional[str] = None
    status: Optional[str] = None
    company_type: Optional[str] = None
    business_nature: Optional[str] = None
    registered_address: Optional[dict[str, Any]] = None
    incorporation_date: Optional[str] = None
    expiry_date: Optional[str] = None
    last_agm_date: Optional[str] = None
    paid_up_capital_fen: Optional[int] = None
    directors: list[dict[str, Any]] = []
    shareholders: list[dict[str, Any]] = []


class ValidateDirectorRequest(BaseModel):
    """董事验证请求"""

    registration_no: str = Field(..., min_length=1, description="SSM 注册号")
    director_name: str = Field(..., min_length=1, description="董事姓名")
    ic_number: str = Field(..., min_length=1, description="身份证号码")


class ValidateDirectorResponse(BaseModel):
    """董事验证结果"""

    validated: bool
    registration_no: str
    director_name: str
    ic_number: str
    position: str
    is_active: bool


# ── 端点 ──────────────────────────────────────────────────────


@router.post("/verify", response_model=VerifyCompanyResponse)
async def verify_company(
    req: VerifyCompanyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: SSMService = Depends(get_ssm_service),
):
    """验证公司注册号 + 公司名是否匹配 SSM 记录

    用于商户入驻、补贴申请等场景的实名制校验。
    """
    try:
        result = await service.verify_company(
            registration_no=req.registration_no,
            company_name=req.company_name,
        )
        return VerifyCompanyResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/search", response_model=SearchCompanyResponse)
async def search_company(
    keyword: str = Query(..., min_length=1, description="搜索关键词（公司名/注册号）"),
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: SSMService = Depends(get_ssm_service),
):
    """按公司名或注册号模糊搜索 SSM 企业"""
    try:
        result = await service.search_company(
            keyword=keyword,
            page=page,
            size=size,
        )
        return SearchCompanyResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/company/{registration_no}", response_model=CompanyDetailResponse)
async def get_company_detail(
    registration_no: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: SSMService = Depends(get_ssm_service),
):
    """获取公司详细资料（包括董事、股东信息）"""
    try:
        result = await service.get_company_detail(
            registration_no=registration_no,
        )
        return CompanyDetailResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/validate-director", response_model=ValidateDirectorResponse)
async def validate_director(
    req: ValidateDirectorRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: SSMService = Depends(get_ssm_service),
):
    """验证董事身份（姓名 + IC 号码是否匹配 SSM 记录）

    用于商户入驻的高风险验证场景。
    """
    try:
        result = await service.validate_director(
            registration_no=req.registration_no,
            director_name=req.director_name,
            ic_number=req.ic_number,
        )
        return ValidateDirectorResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
