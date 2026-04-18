"""
多国合规 API 路由 — 税务规则查询 + 试算
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.services.country_compliance_service import CountryComplianceService

router = APIRouter(prefix="/api/v1/country-compliance", tags=["country-compliance"])


@router.get("/rules")
async def list_rules(
    country_code: str = Query(..., description="CN / HK / SG / VN"),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    svc = CountryComplianceService(db)
    rules = await svc.get_payroll_rules(country_code)
    return [
        {
            "id": str(r.id),
            "country_code": r.country_code,
            "rule_type": r.rule_type,
            "config_json": r.config_json,
            "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        }
        for r in rules
    ]


@router.post("/calc")
async def calc_payroll(
    employee_id: str,
    pay_month: str,
    gross_fen: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    svc = CountryComplianceService(db)
    try:
        result = await svc.calc_by_country(employee_id, pay_month, gross_fen=gross_fen)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result.to_dict()
