"""今日特供 API"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/specials", tags=["specials"])


@router.post("/generate")
async def generate_specials(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """生成今日特供方案（调用 AI 分析，约3-5秒）"""
    from ..agents.master import MasterAgent
    from ..agents.skills import ALL_SKILL_AGENTS
    from ..services.model_router import ModelRouter
    from ..services.specials_engine import SpecialsEngine

    try:
        model_router = ModelRouter()
    except ValueError:
        model_router = None

    master = MasterAgent(tenant_id=x_tenant_id)
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id=x_tenant_id, model_router=model_router))

    report = await SpecialsEngine.generate_specials(x_tenant_id, store_id, master)
    return {
        "ok": True,
        "data": {
            "store_id": report.store_id,
            "date": report.date,
            "total_specials": report.total_specials,
            "generated_at": report.generated_at,
            "specials": [
                {
                    "dish_id": s.dish_id,
                    "dish_name": s.dish_name,
                    "original_price_fen": s.original_price_fen,
                    "special_price_fen": s.special_price_fen,
                    "discount_rate": s.discount_rate,
                    "reason": s.reason,
                    "ingredient_name": s.ingredient_name,
                    "expiry_days": s.expiry_days,
                    "sales_script": s.sales_script,
                    "banner_text": s.banner_text,
                    "pushed": s.pushed,
                }
                for s in report.specials
            ],
            "alternatives": report.alternatives,
        },
    }


@router.get("/today")
async def get_today_specials(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """获取今日已生成的特供方案（无需重新生成）"""
    from ..services.specials_engine import SpecialsEngine

    report = SpecialsEngine.get_report(x_tenant_id, store_id)
    if not report:
        return {"ok": True, "data": None}
    return {
        "ok": True,
        "data": {
            "store_id": report.store_id,
            "date": report.date,
            "total_specials": report.total_specials,
            "pushed_count": report.pushed_count,
            "generated_at": report.generated_at,
            "pushed_at": report.pushed_at,
            "specials": [vars(s) for s in report.specials],
            "alternatives": report.alternatives,
        },
    }


class PushRequest(BaseModel):
    store_id: str
    dish_ids: list[str]


@router.post("/push")
async def push_specials(
    req: PushRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
):
    """推送选中的特供菜到 POS + 小程序"""
    from ..agents.master import MasterAgent
    from ..agents.skills import ALL_SKILL_AGENTS
    from ..services.model_router import ModelRouter
    from ..services.specials_engine import SpecialsEngine

    try:
        model_router = ModelRouter()
    except ValueError:
        model_router = None

    master = MasterAgent(tenant_id=x_tenant_id)
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id=x_tenant_id, model_router=model_router))

    result = await SpecialsEngine.push_specials(x_tenant_id, req.store_id, req.dish_ids, master)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result
