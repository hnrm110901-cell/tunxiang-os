"""宴会合同 API"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


from ..services.banquet_contract_service import BanquetContractService

router = APIRouter(prefix="/api/v1/banquet/contracts", tags=["banquet-contract"])


class GenerateContractReq(BaseModel):
    banquet_id: str
    quote_id: str
    party_b_name: str
    party_b_license: Optional[str] = None
    terms_override: Optional[dict] = None


class SignContractReq(BaseModel):
    signed_by_customer: str


class CreateAmendmentReq(BaseModel):
    change_type: str
    old_value: dict = {}
    new_value: dict = {}
    reason: str
    price_diff_fen: int = 0


class ApproveReq(BaseModel):
    approved_by: str


class TerminateReq(BaseModel):
    reason: str


class RecordPaymentReq(BaseModel):
    payment_method: str


@router.post("/")
async def generate_contract(req: GenerateContractReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        result = await svc.generate_from_quote(
            req.banquet_id, req.quote_id, req.party_b_name, req.party_b_license, req.terms_override
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/by-banquet/{banquet_id}")
async def get_contract_by_banquet(banquet_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    result = await svc.get_contract_by_banquet(banquet_id)
    return _ok(result)


@router.get("/{contract_id}")
async def get_contract(contract_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        result = await svc.get_contract(contract_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e), 404)


@router.post("/{contract_id}/sign")
async def sign_contract(
    contract_id: str, req: SignContractReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        return _ok(await svc.sign_contract(contract_id, req.signed_by_customer))
    except ValueError as e:
        _err(str(e))


@router.post("/{contract_id}/amendments")
async def create_amendment(
    contract_id: str, req: CreateAmendmentReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        return _ok(
            await svc.create_amendment(
                contract_id, req.change_type, req.old_value, req.new_value, req.reason, req.price_diff_fen
            )
        )
    except ValueError as e:
        _err(str(e))


@router.patch("/amendments/{amendment_id}/approve")
async def approve_amendment(
    amendment_id: str, req: ApproveReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        return _ok(await svc.approve_amendment(amendment_id, req.approved_by))
    except ValueError as e:
        _err(str(e))


@router.post("/{contract_id}/terminate")
async def terminate_contract(
    contract_id: str, req: TerminateReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        return _ok(await svc.terminate_contract(contract_id, req.reason))
    except ValueError as e:
        _err(str(e))


@router.get("/{contract_id}/amendments")
async def list_amendments(contract_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    return _ok(await svc.list_amendments(contract_id))


@router.get("/{contract_id}/payments")
async def get_payment_schedule(contract_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    return _ok(await svc.get_payment_schedule(contract_id))


@router.post("/{contract_id}/payments/{index}/record")
async def record_payment(
    contract_id: str, index: int, req: RecordPaymentReq, request: Request, db: AsyncSession = Depends(_get_db_session)
):
    tid = _get_tenant_id(request)
    svc = BanquetContractService(db=db, tenant_id=tid)
    try:
        return _ok(await svc.record_payment(contract_id, index, req.payment_method))
    except ValueError as e:
        _err(str(e))
