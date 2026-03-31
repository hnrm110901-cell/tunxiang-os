"""定价中心 API — 多渠道定价扩展

覆盖：标准售价查询、时价设置、称重计价、套餐定价、
多渠道差异价、促销价、毛利校验、调价审批。
扩展：价格矩阵、批量调价、加价规则、调价预览。
"""
import uuid as _uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.pricing_engine import PricingEngine

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])

_CHANNELS = ("dine_in", "meituan", "eleme", "miniapp", "douyin")


# ─── 依赖注入占位 ───

async def get_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求/响应模型 ───

class SetMarketPriceReq(BaseModel):
    dish_id: str
    price_fen: int = Field(gt=0, description="时价（分）")
    effective_from: datetime = Field(description="生效时间")


class CalculateWeighingReq(BaseModel):
    dish_id: str
    weight_g: int = Field(gt=0, description="称重重量（克）")


class ComboItemReq(BaseModel):
    dish_id: str
    quantity: int = Field(ge=1, default=1)


class CreateComboReq(BaseModel):
    dishes: list[ComboItemReq]
    discount_rate: float = Field(gt=0, le=1.0, description="折扣率，如 0.85 = 85折")


class SetChannelPriceReq(BaseModel):
    dish_id: str
    channel_prices: dict[str, int] = Field(
        description="渠道价格映射，如 {'dine_in': 5800, 'takeaway': 5500}"
    )


class SetPromotionReq(BaseModel):
    dish_id: str
    promo_price_fen: int = Field(gt=0, description="促销价（分）")
    start: datetime
    end: datetime


class ValidateMarginReq(BaseModel):
    dish_id: str
    proposed_price_fen: int = Field(gt=0, description="提议售价（分）")
    store_id: Optional[str] = None


class ApprovePriceChangeReq(BaseModel):
    change_id: str
    approver_id: str


# ─── 1. 查询标准售价 ───

@router.get("/standard-price/{dish_id}")
async def get_standard_price(
    dish_id: str,
    channel: str = "dine_in",
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询菜品标准售价（优先级：时价 > 渠道价 > 促销价 > 基础售价）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.get_standard_price(dish_id, channel)
    return {"ok": True, "data": result}


# ─── 2. 设置时价（海鲜/活鲜） ───

@router.post("/market-price")
async def set_market_price(
    req: SetMarketPriceReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置时价菜价格（每日按市场价浮动）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.set_market_price(
        dish_id=req.dish_id,
        price_fen=req.price_fen,
        effective_from=req.effective_from,
    )
    return {"ok": True, "data": result}


# ─── 3. 称重计价 ───

@router.post("/weighing-price")
async def calculate_weighing_price(
    req: CalculateWeighingReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """称重计价：单价(分/500g) x 重量(g)"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.calculate_weighing_price(
        dish_id=req.dish_id,
        weight_g=req.weight_g,
    )
    return {"ok": True, "data": result}


# ─── 4. 套餐组合定价 ───

@router.post("/combo-price")
async def create_combo_price(
    req: CreateComboReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """套餐组合定价（原价合计 x 折扣率）"""
    dishes_with_qty = [{"dish_id": d.dish_id, "quantity": d.quantity} for d in req.dishes]
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.create_combo_price(
        dishes_with_qty=dishes_with_qty,
        discount_rate=req.discount_rate,
    )
    return {"ok": True, "data": result}


# ─── 5. 多渠道差异价 ───

@router.post("/channel-price")
async def set_channel_price(
    req: SetChannelPriceReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置多渠道差异价（堂食/外卖/外带等）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.set_channel_price(
        dish_id=req.dish_id,
        channel_prices=req.channel_prices,
    )
    return {"ok": True, "data": result}


# ─── 6. 促销价 ───

@router.post("/promotion-price")
async def set_promotion_price(
    req: SetPromotionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置促销价（限时）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.set_promotion_price(
        dish_id=req.dish_id,
        promo_price_fen=req.promo_price_fen,
        start=req.start,
        end=req.end,
    )
    return {"ok": True, "data": result}


# ─── 7. 毛利底线校验 ───

@router.post("/validate-margin")
async def validate_margin(
    req: ValidateMarginReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """毛利底线校验 — 联动 BOM 理论成本"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.validate_margin(
        dish_id=req.dish_id,
        proposed_price_fen=req.proposed_price_fen,
        store_id=req.store_id,
    )
    return {"ok": True, "data": result}


# ─── 8. 调价审批 ───

@router.post("/approve-change")
async def approve_price_change(
    req: ApprovePriceChangeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """审批调价申请（自动校验毛利底线）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.approve_price_change(
        change_id=req.change_id,
        approver_id=req.approver_id,
    )
    return {"ok": True, "data": result}


# ─── 多渠道定价扩展 ────────────────────────────────────────────────────────────


class BatchPriceItem(BaseModel):
    dish_id: str
    channel: str = Field(..., description="渠道: dine_in/meituan/eleme/miniapp/douyin")
    new_price_fen: int = Field(..., gt=0)


class BatchPriceUpdateReq(BaseModel):
    store_id: str
    items: list[BatchPriceItem] = Field(..., min_length=1, max_length=500)


class PricingRuleReq(BaseModel):
    store_id: str
    channel: str = Field(..., description="目标渠道: meituan/eleme/miniapp/douyin")
    rule_type: str = Field(
        ...,
        pattern="^(percent|fixed)$",
        description="percent=按比例加价（如5表示+5%），fixed=固定加价（分）",
    )
    value: float = Field(..., description="加价幅度：percent类型为百分比整数，fixed类型为分")
    description: Optional[str] = None


class PreviewPricingReq(BaseModel):
    store_id: str
    channel: str
    rule_type: str = Field(..., pattern="^(percent|fixed)$")
    value: float


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 9. 全菜品×全渠道价格矩阵 ───

@router.get("/matrix")
async def get_pricing_matrix(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店所有菜品 × 所有渠道的价格矩阵。

    返回：每道菜在每个渠道的实际价格（有渠道价用渠道价，否则用基础价）。
    """
    await _set_tenant(db, x_tenant_id)
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(store_id)

    # 获取所有菜品基础价
    dishes_result = await db.execute(
        text("""
            SELECT id, dish_name, price_fen
            FROM dishes
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND is_available = true
            ORDER BY dish_name
        """),
        {"tid": tid},
    )
    dishes = dishes_result.fetchall()

    if not dishes:
        return {"ok": True, "data": {"channels": list(_CHANNELS), "dishes": [], "total_dishes": 0}}

    dish_ids = [r[0] for r in dishes]
    dish_map = {str(r[0]): {"name": r[1], "base_price_fen": r[2]} for r in dishes}

    # 批量获取渠道价（channel_menu_items）
    placeholders = ", ".join(f":did_{i}" for i in range(len(dish_ids)))
    params: dict = {"tid": tid, "sid": sid}
    for i, did in enumerate(dish_ids):
        params[f"did_{i}"] = did

    channel_result = await db.execute(
        text(f"""
            SELECT dish_id, channel, channel_price_fen
            FROM channel_menu_items
            WHERE tenant_id = :tid
              AND store_id  = :sid
              AND dish_id IN ({placeholders})
        """),
        params,
    )
    channel_prices: dict[str, dict[str, Optional[int]]] = {}
    for row in channel_result.fetchall():
        dish_id_str = str(row[0])
        ch = row[1]
        price = row[2]
        if dish_id_str not in channel_prices:
            channel_prices[dish_id_str] = {}
        channel_prices[dish_id_str][ch] = price

    # 构建矩阵
    matrix = []
    for did, dinfo in dish_map.items():
        base = dinfo["base_price_fen"]
        ch_prices = channel_prices.get(did, {})
        row_data: dict = {
            "dish_id": did,
            "dish_name": dinfo["name"],
            "base_price_fen": base,
        }
        for ch in _CHANNELS:
            row_data[f"price_{ch}"] = ch_prices.get(ch, base)
        matrix.append(row_data)

    log.info("pricing.matrix", store_id=store_id, dish_count=len(matrix))
    return {
        "ok": True,
        "data": {
            "channels": list(_CHANNELS),
            "dishes": matrix,
            "total_dishes": len(matrix),
        },
    }


# ─── 10. 批量更新价格 ───

@router.put("/batch")
async def batch_update_prices(
    req: BatchPriceUpdateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量更新渠道价格（支持跨菜品、跨渠道批量写入）。

    每条记录写入 channel_menu_items 表（存在则更新 channel_price_fen）。
    """
    invalid_channels = {item.channel for item in req.items if item.channel not in _CHANNELS}
    if invalid_channels:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {invalid_channels}")

    await _set_tenant(db, x_tenant_id)
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(req.store_id)

    updated = 0
    errors: list[dict] = []
    for item in req.items:
        try:
            did = _uuid.UUID(item.dish_id)
            await db.execute(
                text("""
                    INSERT INTO channel_menu_items
                        (tenant_id, store_id, dish_id, channel, channel_price_fen, is_available)
                    VALUES
                        (:tid, :sid, :did, :channel, :price, true)
                    ON CONFLICT (tenant_id, store_id, dish_id, channel) DO UPDATE SET
                        channel_price_fen = EXCLUDED.channel_price_fen,
                        updated_at        = NOW()
                """),
                {"tid": tid, "sid": sid, "did": did, "channel": item.channel, "price": item.new_price_fen},
            )
            updated += 1
        except (ValueError, Exception) as exc:
            errors.append({"dish_id": item.dish_id, "channel": item.channel, "error": str(exc)})

    await db.commit()
    log.info("pricing.batch_updated", store_id=req.store_id, updated=updated, errors=len(errors))
    return {
        "ok": True,
        "data": {
            "updated": updated,
            "errors": errors,
            "total_requested": len(req.items),
        },
    }


# ─── 11. 加价规则列表 ───

@router.get("/rules")
async def list_pricing_rules(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店渠道加价规则列表（所有有效规则）。"""
    await _set_tenant(db, x_tenant_id)
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT id, channel, rule_type, value, description, is_active, created_at, updated_at
            FROM channel_pricing_rules
            WHERE tenant_id = :tid
              AND store_id  = :sid
            ORDER BY channel
        """),
        {"tid": tid, "sid": sid},
    )
    rules = [
        {
            "id": str(r[0]),
            "channel": r[1],
            "rule_type": r[2],
            "value": float(r[3]),
            "description": r[4],
            "is_active": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
            "updated_at": r[7].isoformat() if r[7] else None,
        }
        for r in result.fetchall()
    ]
    return {"ok": True, "data": {"rules": rules, "total": len(rules)}}


# ─── 12. 创建加价规则 ───

@router.post("/rules", status_code=201)
async def create_pricing_rule(
    req: PricingRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建渠道加价规则（同一渠道已有规则则覆盖）。

    rule_type=percent: value=5 表示该渠道所有菜品统一加价 5%
    rule_type=fixed: value=200 表示加价 2元（200分）
    """
    if req.channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {req.channel}")
    if req.channel == "dine_in":
        raise HTTPException(status_code=400, detail="堂食渠道不支持加价规则（使用基础价）")

    await _set_tenant(db, x_tenant_id)
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(req.store_id)

    result = await db.execute(
        text("""
            INSERT INTO channel_pricing_rules
                (tenant_id, store_id, channel, rule_type, value, description, is_active)
            VALUES
                (:tid, :sid, :channel, :rule_type, :value, :description, true)
            ON CONFLICT (tenant_id, store_id, channel) DO UPDATE SET
                rule_type   = EXCLUDED.rule_type,
                value       = EXCLUDED.value,
                description = COALESCE(EXCLUDED.description, channel_pricing_rules.description),
                is_active   = true,
                updated_at  = NOW()
            RETURNING id, channel, rule_type, value, description, is_active, created_at, updated_at
        """),
        {
            "tid": tid,
            "sid": sid,
            "channel": req.channel,
            "rule_type": req.rule_type,
            "value": req.value,
            "description": req.description,
        },
    )
    row = result.fetchone()
    await db.commit()
    log.info("pricing_rule.created", channel=req.channel, store_id=req.store_id, rule_type=req.rule_type, value=req.value)
    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "channel": row[1],
            "rule_type": row[2],
            "value": float(row[3]),
            "description": row[4],
            "is_active": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        },
    }


# ─── 13. 预览调价结果 ───

@router.post("/preview")
async def preview_pricing(
    req: PreviewPricingReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """预览按指定规则调价后的结果（不实际写库）。

    返回门店所有菜品在目标渠道的当前价格与调价后价格对比。
    """
    if req.channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {req.channel}")

    await _set_tenant(db, x_tenant_id)
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(req.store_id)

    # 获取所有在该渠道上架的菜品（或回退到所有菜品基础价）
    result = await db.execute(
        text("""
            SELECT
                d.id,
                d.dish_name,
                d.price_fen AS base_price_fen,
                cmi.channel_price_fen AS current_channel_price_fen
            FROM dishes d
            LEFT JOIN channel_menu_items cmi
                   ON cmi.dish_id = d.id
                  AND cmi.tenant_id = d.tenant_id
                  AND cmi.store_id  = :sid
                  AND cmi.channel   = :channel
            WHERE d.tenant_id = :tid
              AND d.is_deleted = false
              AND d.is_available = true
            ORDER BY d.dish_name
        """),
        {"tid": tid, "sid": sid, "channel": req.channel},
    )
    rows = result.fetchall()

    previews = []
    for r in rows:
        base_price = int(r[2]) if r[2] else 0
        current_price = int(r[3]) if r[3] is not None else base_price

        if req.rule_type == "percent":
            new_price = int(round(base_price * (1 + req.value / 100)))
        else:  # fixed
            new_price = base_price + int(req.value)

        new_price = max(1, new_price)  # 至少 1 分
        diff = new_price - current_price

        previews.append({
            "dish_id": str(r[0]),
            "dish_name": r[1],
            "base_price_fen": base_price,
            "current_channel_price_fen": current_price,
            "preview_price_fen": new_price,
            "diff_fen": diff,
        })

    log.info("pricing.preview", channel=req.channel, store_id=req.store_id, dish_count=len(previews))
    return {
        "ok": True,
        "data": {
            "channel": req.channel,
            "rule_type": req.rule_type,
            "value": req.value,
            "dishes": previews,
            "total": len(previews),
            "note": "预览结果未写入数据库，请调用 PUT /pricing/batch 批量确认",
        },
    }
