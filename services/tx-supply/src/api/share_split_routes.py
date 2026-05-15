"""share_split_routes — POS 销售分成转入库 API（PRD-11 sub-A / Phase 2 W11 / T2 + Tier 1 邻接）

接口列表:
  CRUD:
    POST   /api/v1/supply/share-split-rules                       新建规则 (UNIQUE per dish)
    GET    /api/v1/supply/share-split-rules                       列表 (?only_active=&limit=&offset=)
    GET    /api/v1/supply/share-split-rules/{rule_id}             单条详情
    GET    /api/v1/supply/share-split-rules/by-dish/{dish_id}     按 dish_id 查 (auto_deduction caller 用)
    PATCH  /api/v1/supply/share-split-rules/{rule_id}             更新
    DELETE /api/v1/supply/share-split-rules/{rule_id}             软删

  Validate (前端预校验 — POS 拆单 modal 提交前预跑):
    POST   /api/v1/supply/share-split-rules/validate              校验 spec + 计算 cost 分配

设计要点：
  - ValueError("已存在但被禁用") → 409 (P0-2 lesson 沿用)
  - ValueError("已存在") → 409
  - ValueError("不存在") → 404
  - ValueError("不允许分享") / ValueError("超过") → 422 (业务规则违反)
  - 其他 ValueError → 422 (参数错误)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.share_split_models import (
    ShareSplitRuleCreate,
    ShareSplitRuleUpdate,
    ValidateSpecRequest,
)
from ..services.share_split_service import (
    apply_split,
    create_rule,
    delete_rule,
    get_rule,
    get_rule_by_dish,
    list_rules,
    update_rule,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/share-split-rules",
    tags=["share-split-rules"],
)


# ─── CRUD ────────────────────────────────────────────────────────────────────


@router.post("")
async def create_supply_share_split_rule(
    body: ShareSplitRuleCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建分享规则。UNIQUE per dish (软禁用 row 给 PATCH 引导)."""
    try:
        item = await create_rule(
            db=db,
            tenant_id=x_tenant_id,
            dish_id=str(body.dish_id),
            created_by=x_user_id,
            allow_share=body.allow_share,
            default_method=body.default_method.value,
            max_share_count=body.max_share_count,
            notes=body.notes,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "RULE_DUPLICATE", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "RULE_CREATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.get("")
async def list_supply_share_split_rules(
    only_active: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """规则列表 — created_at 倒序; only_active 过滤."""
    try:
        items = await list_rules(
            db=db,
            tenant_id=x_tenant_id,
            only_active=only_active,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "RULE_LIST_INVALID", "message": str(e)},
        ) from e
    return {"ok": True, "data": items}


@router.get("/by-dish/{dish_id}")
async def get_supply_share_split_rule_by_dish(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """按 dish_id 查规则 (auto_deduction caller 入口)."""
    item = await get_rule_by_dish(db=db, tenant_id=x_tenant_id, dish_id=dish_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "RULE_NOT_FOUND",
                "message": f"dish_id={dish_id} 未配置 share_split_rule",
            },
        )
    return {"ok": True, "data": item}


@router.get("/{rule_id}")
async def get_supply_share_split_rule(
    rule_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """单条规则详情."""
    item = await get_rule(db=db, tenant_id=x_tenant_id, rule_id=rule_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "RULE_NOT_FOUND",
                "message": f"rule_id={rule_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": item}


@router.patch("/{rule_id}")
async def update_supply_share_split_rule(
    rule_id: str,
    body: ShareSplitRuleUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新规则 (PRD-08 P0-1 lesson: model_dump(exclude_unset=True) 区分"未提供"vs"显式 None")."""
    raw_updates = body.model_dump(exclude_unset=True)
    # default_method enum → str 值
    if "default_method" in raw_updates and raw_updates["default_method"] is not None:
        raw_updates["default_method"] = raw_updates["default_method"].value
    try:
        item = await update_rule(
            db=db,
            tenant_id=x_tenant_id,
            rule_id=rule_id,
            updates=raw_updates,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "RULE_NOT_FOUND", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "RULE_UPDATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/{rule_id}")
async def delete_supply_share_split_rule(
    rule_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删规则 (is_deleted=TRUE + is_active=FALSE)."""
    ok = await delete_rule(db=db, tenant_id=x_tenant_id, rule_id=rule_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "RULE_NOT_FOUND",
                "message": f"rule_id={rule_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "rule_id": rule_id}}


# ─── Validate-Spec (前端预校验) ───────────────────────────────────────────────


@router.post("/validate")
async def validate_supply_share_split_spec(
    body: ValidateSpecRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """前端预校验 — POS 拆单 modal 提交前调本接口, 拿到 cost 分配预览.

    业务场景: 服务员选 1 份酸菜鱼分给 2 人 → POS UI 调本接口 → 返回每人成本归属
    → 收银员确认后落单. 服务端 apply_split 综合 rule (允许分享 / 上限) + spec
    (3-way enum + weights/amounts_fen 校验) + resolve cost 分摊.
    """
    try:
        result = await apply_split(
            db=db,
            tenant_id=x_tenant_id,
            dish_id=str(body.dish_id),
            spec=body.spec,
            bom_cost_total_fen=body.bom_cost_total_fen,
        )
    except ValueError as e:
        msg = str(e)
        if "未配置" in msg or "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "RULE_NOT_FOUND", "message": msg},
            ) from e
        if "不允许分享" in msg or "超过" in msg or "禁用" in msg:
            raise HTTPException(
                status_code=422,
                detail={"code": "SHARE_NOT_ALLOWED", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATE_INVALID", "message": msg},
        ) from e
    # 序列化 ResolvedSplitResult (含 Decimal weight → str)
    return {
        "ok": True,
        "data": {
            "method": result.method.value,
            "count": result.count,
            "bom_cost_total_fen": result.bom_cost_total_fen,
            "shares": [
                {
                    "share_index": s.share_index,
                    "weight": str(s.weight),
                    "attributed_cost_fen": s.attributed_cost_fen,
                }
                for s in result.shares
            ],
        },
    }


__all__ = ["router"]
