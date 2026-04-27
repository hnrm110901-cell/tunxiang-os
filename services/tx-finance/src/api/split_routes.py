"""分账引擎 API — 8 个端点（v100 + 通道通知）

端点：
1. POST   /api/v1/finance/splits/rules              创建/更新分润规则
2. GET    /api/v1/finance/splits/rules              查询规则列表
3. DELETE /api/v1/finance/splits/rules/{id}         停用规则
4. POST   /api/v1/finance/splits/execute            执行分账（对一笔交易）
5. POST   /api/v1/finance/splits/settle             批量结算（pending→settled）
6. GET    /api/v1/finance/splits/transactions       分润流水
7. GET    /api/v1/finance/splits/settlement         分账汇总（按收款方）
8. POST   /api/v1/finance/splits/channel-notify     通道异步结果（Y-B2 骨架 + 可选 HMAC）
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.split_engine import RECIPIENT_TYPES, SPLIT_METHODS, SplitEngine
from ..services.split_notify_security import verify_split_channel_notify_signature

router = APIRouter(prefix="/api/v1/finance/splits", tags=["split_engine"])


# ─── DB 依赖 ──────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _engine(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> SplitEngine:
    return SplitEngine(db, x_tenant_id)


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class UpsertRuleRequest(BaseModel):
    id: Optional[str] = Field(None, description="规则 ID（更新时传入）")
    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    recipient_type: str = Field(..., description="收款方类型: brand/franchise/supplier/platform/custom")
    recipient_id: Optional[str] = Field(None, description="收款方 ID（NULL=集团总部）")
    split_method: str = Field(..., description="分账方式: percentage/fixed_fen")
    percentage: Optional[float] = Field(None, ge=0, le=1, description="按比例时填写，如 0.05 = 5%")
    fixed_fen: Optional[int] = Field(None, ge=0, description="固定金额（分）")
    applicable_stores: List[str] = Field(default_factory=list, description="适用门店 ID，空=全部门店")
    applicable_channels: List[str] = Field(default_factory=list, description="适用渠道，空=全部渠道")
    priority: int = Field(0, ge=0, description="规则优先级，数字越小越先执行")
    is_active: bool = Field(True, description="是否启用")
    valid_from: Optional[str] = Field(None, description="有效期开始 YYYY-MM-DD")
    valid_to: Optional[str] = Field(None, description="有效期结束 YYYY-MM-DD")

    @field_validator("recipient_type")
    @classmethod
    def check_recipient_type(cls, v: str) -> str:
        if v not in RECIPIENT_TYPES:
            raise ValueError(f"recipient_type 必须是: {', '.join(sorted(RECIPIENT_TYPES))}")
        return v

    @field_validator("split_method")
    @classmethod
    def check_split_method(cls, v: str) -> str:
        if v not in SPLIT_METHODS:
            raise ValueError(f"split_method 必须是: {', '.join(SPLIT_METHODS)}")
        return v


class ExecuteSplitRequest(BaseModel):
    order_id: str = Field(..., description="订单 ID")
    store_id: str = Field(..., description="门店 ID")
    channel: Optional[str] = Field(None, description="渠道（dine_in/takeaway/meituan/eleme/douyin 等）")
    gross_amount_fen: int = Field(..., gt=0, description="交易总金额（分）")
    transaction_date: Optional[str] = Field(None, description="交易日期 YYYY-MM-DD，默认今日")


class SettleRequest(BaseModel):
    record_ids: List[str] = Field(..., min_length=1, description="要结算的流水 ID 列表")


class ChannelNotifyItem(BaseModel):
    record_id: str = Field(..., min_length=1, description="profit_split_records.id")
    outcome: Literal["settled", "failed"] = Field(
        ...,
        description="settled=通道分账成功 → pending→settled；failed→pending→cancelled",
    )
    channel_transaction_id: Optional[str] = Field(
        None,
        max_length=200,
        description="微信/支付宝返回的分账单号（仅记录用途，当前不入库）",
    )


class ChannelNotifyRequest(BaseModel):
    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="调用方幂等键（日志与对账；重试应使用同一键）",
    )
    items: List[ChannelNotifyItem] = Field(
        ...,
        min_length=1,
        description="本批通道结果，一条对应一条分润流水",
    )


# ─── 1. 创建/更新规则 ─────────────────────────────────────────────────────────


@router.post("/rules", summary="创建或更新分润规则", status_code=201)
async def upsert_split_rule(
    body: UpsertRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """创建新分润规则，或更新已有规则（body 中传 id 则更新）。

    - split_method=percentage 时必须填写 percentage（0.0-1.0）
    - split_method=fixed_fen 时必须填写 fixed_fen
    - applicable_stores/applicable_channels 空数组 = 全适用
    """
    if body.split_method == "percentage" and body.percentage is None:
        raise HTTPException(status_code=400, detail="split_method=percentage 时 percentage 不能为空")
    if body.split_method == "fixed_fen" and body.fixed_fen is None:
        raise HTTPException(status_code=400, detail="split_method=fixed_fen 时 fixed_fen 不能为空")

    engine = SplitEngine(db, x_tenant_id)
    try:
        rule = await engine.upsert_rule(body.model_dump())
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": rule}


# ─── 2. 查询规则列表 ──────────────────────────────────────────────────────────


@router.get("/rules", summary="查询分润规则列表")
async def list_split_rules(
    is_active: Optional[bool] = Query(None, description="是否启用过滤"),
    recipient_type: Optional[str] = Query(None, description="收款方类型过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """返回当前租户的所有分润规则，按 priority 升序排列。"""
    engine = SplitEngine(db, x_tenant_id)
    rules = await engine.list_rules(is_active=is_active, recipient_type=recipient_type)
    return {"ok": True, "data": {"items": rules, "total": len(rules)}}


# ─── 3. 停用规则 ──────────────────────────────────────────────────────────────


@router.delete("/rules/{rule_id}", summary="停用分润规则")
async def deactivate_split_rule(
    rule_id: str = Path(..., description="规则 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """将规则标记为 is_active=FALSE（软删除）。历史流水数据保留不受影响。"""
    engine = SplitEngine(db, x_tenant_id)
    ok = await engine.deactivate_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"规则不存在或已停用: {rule_id}")
    await db.commit()
    return {"ok": True, "data": {"rule_id": rule_id, "is_active": False}}


# ─── 4. 执行分账 ──────────────────────────────────────────────────────────────


@router.post("/execute", summary="执行分账（对一笔交易）")
async def execute_split(
    body: ExecuteSplitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """对一笔交易匹配所有有效分润规则，生成 profit_split_records 流水。

    同一笔订单可多次调用（幂等由业务层控制，建议每笔订单只调用一次）。
    返回本次生成的所有分润记录。
    """
    from datetime import date as date_type

    t_date = date_type.fromisoformat(body.transaction_date) if body.transaction_date else None

    engine = SplitEngine(db, x_tenant_id)
    try:
        records = await engine.execute_split(
            order_id=body.order_id,
            store_id=body.store_id,
            channel=body.channel,
            gross_amount_fen=body.gross_amount_fen,
            transaction_date=t_date,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    total_split_fen = sum(r["split_amount_fen"] for r in records)
    return {
        "ok": True,
        "data": {
            "order_id": body.order_id,
            "gross_amount_fen": body.gross_amount_fen,
            "total_split_fen": total_split_fen,
            "total_split_yuan": round(total_split_fen / 100, 2),
            "records": records,
            "record_count": len(records),
        },
    }


# ─── 5. 批量结算 ──────────────────────────────────────────────────────────────


@router.post("/settle", summary="批量结算分润流水")
async def settle_split_records(
    body: SettleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """将 pending 状态的分润流水批量更新为 settled。

    适用场景：实际付款完成后（银行转账/支付宝打款）回调触发。
    """
    engine = SplitEngine(db, x_tenant_id)
    settled_count = await engine.settle_records(body.record_ids)
    await db.commit()
    return {
        "ok": True,
        "data": {
            "requested": len(body.record_ids),
            "settled": settled_count,
        },
    }


# ─── 5b. 通道异步通知（微信/支付宝分账结果回调形状）────────────────────────────


@router.post("/channel-notify", summary="通道分账异步结果（幂等）")
async def channel_split_notify(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
    x_split_notify_signature: Optional[str] = Header(None, alias="X-Split-Notify-Signature"),
) -> Dict[str, Any]:
    """接收支付机构分账完成/失败通知，更新 ``profit_split_records``。

    - 仅 ``pending`` 行会被更新；已 ``settled`` / ``cancelled`` 的重复通知无副作用（幂等）。
    - 生产环境建议配置 ``TX_FINANCE_SPLIT_NOTIFY_SECRET``，并传入
      ``X-Split-Notify-Signature: hex(hmac_sha256(secret, raw_body))``。
    - 真实微信/支付宝回调需再适配各自报文结构与平台公钥验签；本端点为内部统一入口骨架。
    """
    body_bytes = await request.body()
    try:
        verify_split_channel_notify_signature(body_bytes, x_split_notify_signature)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        raw = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    try:
        body = ChannelNotifyRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    engine = SplitEngine(db, x_tenant_id)
    try:
        result = await engine.apply_channel_notification(
            [i.model_dump() for i in body.items],
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "data": {
            "idempotency_key": body.idempotency_key,
            **result,
        },
    }


# ─── 6. 分润流水 ──────────────────────────────────────────────────────────────


@router.get("/transactions", summary="分润流水列表")
async def list_split_transactions(
    order_id: Optional[str] = Query(None, description="按订单 ID 过滤"),
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    recipient_type: Optional[str] = Query(None, description="按收款方类型过滤"),
    status: Optional[str] = Query(None, description="状态: pending/settled/cancelled"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询分润流水，支持多维过滤分页。"""
    engine = SplitEngine(db, x_tenant_id)
    result = await engine.list_split_records(
        order_id=order_id,
        store_id=store_id,
        recipient_type=recipient_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size,
    )
    return {"ok": True, "data": {**result, "page": page, "size": size}}


# ─── 7. 分账汇总 ──────────────────────────────────────────────────────────────


@router.get("/settlement", summary="分账汇总（按收款方）")
async def get_settlement_summary(
    recipient_type: Optional[str] = Query(None, description="收款方类型过滤"),
    recipient_id: Optional[str] = Query(None, description="收款方 ID 过滤"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """按收款方汇总应付和已付金额。

    用于：品牌总部查看各加盟商/平台待结算金额；财务核对月度分润。
    """
    engine = SplitEngine(db, x_tenant_id)
    summary = await engine.get_settlement_summary(
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        start_date=start_date,
        end_date=end_date,
    )
    return {"ok": True, "data": summary}
