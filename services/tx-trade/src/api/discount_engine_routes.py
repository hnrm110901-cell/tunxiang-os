"""多优惠叠加规则引擎 API

GET  /api/v1/discount/rules              — 查询门店激活规则列表（按 priority 排序）
POST /api/v1/discount/calculate          — 计算多优惠叠加结果
POST /api/v1/discount/rules              — 新建规则（管理员）
PUT  /api/v1/discount/rules/{rule_id}   — 更新规则（管理员）

核心逻辑：
  1. 查询 discount_rules，按 priority 排序
  2. 检测传入 discounts 中哪些类型互斥（不在 can_stack_with 内）
  3. 有互斥时，穷举组合，选对顾客最优（saved 最大）的方案
  4. 按 apply_order 依次在上一步结果上叠加，记录 before/after/saved
  5. 写入 checkout_discount_log 审计日志

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

RLS: NULLIF(current_setting('app.tenant_id', true), '')::uuid
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/discount", tags=["discount-engine"])

# ─── 常量 ───────────────────────────────────────────────────────────────────

VALID_TYPES = {"member_discount", "platform_coupon", "manual_discount", "full_reduction"}

# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── Pydantic 模型 ──────────────────────────────────────────────────────────


class DiscountInput(BaseModel):
    """单个优惠输入"""
    type: str = Field(..., description="member_discount | platform_coupon | manual_discount | full_reduction")
    # 会员折扣
    member_id: Optional[str] = None
    rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="折扣率，如 0.85=85折")
    # 平台券 / 手动折扣
    coupon_id: Optional[str] = None
    deduct_fen: Optional[int] = Field(None, ge=0, description="直减金额（分）")
    # 满减
    condition_fen: Optional[int] = Field(None, ge=0, description="满减触发门槛（分）")
    # 手动折扣描述
    description: Optional[str] = None


class CalculateRequest(BaseModel):
    order_id: str
    base_amount_fen: int = Field(..., ge=1, description="原始金额（分）")
    discounts: List[DiscountInput] = Field(..., min_length=1)
    store_id: Optional[str] = None


class CreateRuleRequest(BaseModel):
    store_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    priority: int = Field(default=100, ge=1)
    type: str
    can_stack_with: List[str] = Field(default_factory=list)
    apply_order: int = Field(default=10, ge=1)
    description: Optional[str] = None


class UpdateRuleRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    priority: Optional[int] = Field(None, ge=1)
    can_stack_with: Optional[List[str]] = None
    apply_order: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    description: Optional[str] = None


# ─── 内部：折扣计算核心逻辑 ─────────────────────────────────────────────────


def _describe_discount(d: DiscountInput, amount_before: int) -> str:
    """生成折扣步骤描述文字"""
    if d.description:
        return d.description
    if d.type == "member_discount" and d.rate is not None:
        pct = int(d.rate * 10)
        return f"会员{pct}折"
    if d.type == "platform_coupon" and d.deduct_fen is not None:
        yuan = d.deduct_fen / 100
        return f"平台券{yuan:.0f}元"
    if d.type == "full_reduction" and d.deduct_fen is not None and d.condition_fen is not None:
        cond_yuan = d.condition_fen / 100
        ded_yuan = d.deduct_fen / 100
        return f"满{cond_yuan:.0f}减{ded_yuan:.0f}"
    if d.type == "manual_discount":
        if d.rate is not None:
            pct = int(d.rate * 10)
            return f"手动{pct}折"
        if d.deduct_fen is not None:
            yuan = d.deduct_fen / 100
            return f"手动减{yuan:.0f}元"
    return d.type


def _apply_single_discount(amount_fen: int, d: DiscountInput) -> int:
    """对给定金额应用单个优惠，返回优惠后金额（≥0）"""
    result = amount_fen
    if d.type == "member_discount" and d.rate is not None:
        result = round(amount_fen * d.rate)
    elif d.type == "platform_coupon" and d.deduct_fen is not None:
        result = amount_fen - d.deduct_fen
    elif d.type == "manual_discount":
        if d.rate is not None:
            result = round(amount_fen * d.rate)
        elif d.deduct_fen is not None:
            result = amount_fen - d.deduct_fen
    elif d.type == "full_reduction":
        # 满减：只有当前金额 >= condition_fen 才触发
        if d.condition_fen is not None and d.deduct_fen is not None:
            if amount_fen >= d.condition_fen:
                result = amount_fen - d.deduct_fen
    return max(0, result)


def _calc_combination(base_fen: int, combo: list[DiscountInput]) -> tuple[int, int]:
    """计算一组优惠组合的最终金额和总节省。返回 (final_fen, total_saved)"""
    current = base_fen
    for d in combo:
        current = _apply_single_discount(current, d)
    total_saved = base_fen - current
    return current, total_saved


def _build_steps(
    base_fen: int,
    chosen: list[DiscountInput],
    rule_map: dict[str, dict],
) -> list[dict]:
    """按 apply_order 顺序构建详细步骤列表"""
    # 按 apply_order 排序（apply_order 越小越先执行）
    sorted_chosen = sorted(
        chosen,
        key=lambda d: rule_map.get(d.type, {}).get("apply_order", 999),
    )
    steps = []
    current = base_fen
    for d in sorted_chosen:
        after = _apply_single_discount(current, d)
        steps.append({
            "type": d.type,
            "before": current,
            "after": after,
            "saved": current - after,
            "description": _describe_discount(d, current),
        })
        current = after
    return steps


def _resolve_conflicts(
    base_fen: int,
    discounts: list[DiscountInput],
    rule_map: dict[str, dict],
) -> tuple[list[DiscountInput], list[dict]]:
    """
    检测互斥冲突，通过穷举找对顾客最优的组合。
    返回 (chosen_discounts, conflict_info_list)
    """
    if not discounts:
        return [], []

    # 构建互斥图：对每个 type，找出它不能与哪些 type 共存
    # can_stack_with 列表中的 type 代表可以共存
    def can_stack(type_a: str, type_b: str) -> bool:
        rule_a = rule_map.get(type_a, {})
        rule_b = rule_map.get(type_b, {})
        a_allows_b = type_b in rule_a.get("can_stack_with", [])
        b_allows_a = type_a in rule_b.get("can_stack_with", [])
        # 双方都允许才可叠加
        return a_allows_b and b_allows_a

    # 检查是否存在任何互斥对
    has_conflict = False
    conflict_pairs: list[tuple[str, str]] = []
    discount_types = [d.type for d in discounts]
    for i, ta in enumerate(discount_types):
        for j, tb in enumerate(discount_types):
            if i >= j:
                continue
            if not can_stack(ta, tb):
                has_conflict = True
                conflict_pairs.append((ta, tb))

    if not has_conflict:
        return discounts, []

    # 有互斥，穷举所有子集，找 saved 最大的有效组合
    best_combo: list[DiscountInput] = []
    best_saved = -1
    n = len(discounts)
    for r in range(1, n + 1):
        for combo in itertools.combinations(discounts, r):
            combo_list = list(combo)
            # 检查组合内无互斥
            valid = True
            for i in range(len(combo_list)):
                for j in range(i + 1, len(combo_list)):
                    if not can_stack(combo_list[i].type, combo_list[j].type):
                        valid = False
                        break
                if not valid:
                    break
            if not valid:
                continue
            _, saved = _calc_combination(base_fen, combo_list)
            if saved > best_saved:
                best_saved = saved
                best_combo = combo_list

    # 构建冲突说明
    excluded_types = {d.type for d in discounts} - {d.type for d in best_combo}
    conflicts = []
    for pair in conflict_pairs:
        conflicts.append({
            "type_a": pair[0],
            "type_b": pair[1],
            "reason": f"{pair[0]} 与 {pair[1]} 互斥，已自动选择最优组合",
        })

    if excluded_types:
        conflicts.append({
            "excluded_types": list(excluded_types),
            "message": "已自动为您选择最优优惠组合",
        })

    return best_combo, conflicts


# ─── 数据库查询层 ────────────────────────────────────────────────────────────


async def _fetch_active_rules(
    db: AsyncSession,
    tenant_id: str,
    store_id: Optional[str],
) -> list[dict]:
    """查询激活的折扣规则，全品牌规则(store_id IS NULL) + 门店规则均返回"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    q = """
        SELECT id, store_id, name, priority, type,
               can_stack_with, apply_order, is_active, description
        FROM discount_rules
        WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          AND is_active = TRUE
          AND (store_id IS NULL OR store_id = :store_id)
        ORDER BY priority ASC, apply_order ASC
    """
    result = await db.execute(text(q), {"store_id": store_id})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def _insert_discount_log(
    db: AsyncSession,
    tenant_id: str,
    order_id: str,
    base_amount_fen: int,
    applied_steps: list[dict],
    total_saved_fen: int,
    final_amount_fen: int,
    conflicts: list[dict],
) -> str:
    """写入 checkout_discount_log，返回 log id"""
    import json
    log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO checkout_discount_log
                (id, tenant_id, order_id, base_amount_fen,
                 applied_discounts, total_saved_fen, final_amount_fen, conflicts)
            VALUES
                (:id, :tid::uuid, :order_id::uuid, :base,
                 :applied::jsonb, :saved, :final, :conflicts::jsonb)
        """),
        {
            "id": log_id,
            "tid": tenant_id,
            "order_id": order_id,
            "base": base_amount_fen,
            "applied": json.dumps(applied_steps, ensure_ascii=False),
            "saved": total_saved_fen,
            "final": final_amount_fen,
            "conflicts": json.dumps(conflicts, ensure_ascii=False),
        },
    )
    return log_id


# ─── 端点：查询规则 ──────────────────────────────────────────────────────────


@router.get("/rules")
async def get_discount_rules(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/discount/rules — 返回门店激活规则列表（按 priority 排序）"""
    tenant_id = _get_tenant_id(request)
    try:
        rules = await _fetch_active_rules(db, tenant_id, store_id)
        # UUID 对象序列化处理
        for r in rules:
            r["id"] = str(r["id"]) if r["id"] else None
            r["store_id"] = str(r["store_id"]) if r["store_id"] else None
            r["can_stack_with"] = list(r["can_stack_with"] or [])
        return _ok({"rules": rules, "total": len(rules)})
    except SQLAlchemyError as e:
        _err(f"查询规则失败: {e}", 500)


# ─── 端点：计算折扣叠加 ──────────────────────────────────────────────────────


@router.post("/calculate")
async def calculate_discount(
    req: CalculateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/discount/calculate — 多优惠叠加计算

    引擎逻辑：
      1. 查询门店 discount_rules，按 priority 排序
      2. 检测传入 discounts 中的互斥关系
      3. 有互斥时，穷举子集选 saved 最大方案
      4. 按 apply_order 依次叠加，记录每步 before/after/saved
      5. 写入 checkout_discount_log 审计日志
    """
    tenant_id = _get_tenant_id(request)

    # 校验 discount type
    for d in req.discounts:
        if d.type not in VALID_TYPES:
            _err(f"无效的优惠类型: {d.type}，有效值: {', '.join(VALID_TYPES)}")

    try:
        # 1. 查询规则
        rules = await _fetch_active_rules(db, tenant_id, req.store_id)
        # 构建 type -> rule 映射（优先门店规则，后全品牌）
        rule_map: dict[str, dict] = {}
        for r in rules:
            t = r["type"]
            if t not in rule_map:  # priority 排序后，第一条优先
                rule_map[t] = {
                    "can_stack_with": list(r["can_stack_with"] or []),
                    "apply_order": r["apply_order"],
                }

        # 2 & 3. 冲突检测 + 选最优组合
        chosen, conflicts = _resolve_conflicts(
            req.base_amount_fen, req.discounts, rule_map
        )

        # 4. 按 apply_order 构建详细步骤
        applied_steps = _build_steps(req.base_amount_fen, chosen, rule_map)

        # 计算汇总
        final_amount_fen = applied_steps[-1]["after"] if applied_steps else req.base_amount_fen
        total_saved_fen = req.base_amount_fen - final_amount_fen

        # 5. 写审计日志（忽略失败，不影响主流程）
        try:
            log_id = await _insert_discount_log(
                db,
                tenant_id=tenant_id,
                order_id=req.order_id,
                base_amount_fen=req.base_amount_fen,
                applied_steps=applied_steps,
                total_saved_fen=total_saved_fen,
                final_amount_fen=final_amount_fen,
                conflicts=conflicts,
            )
            await db.commit()
        except (OSError, ValueError, RuntimeError):  # noqa: BLE001 — DB写入失败时降级，日志ID设为None
            log_id = None
            await db.rollback()

        return _ok({
            "base_amount_fen": req.base_amount_fen,
            "applied_steps": applied_steps,
            "total_saved_fen": total_saved_fen,
            "final_amount_fen": final_amount_fen,
            "conflicts": conflicts,
            "log_id": log_id,
        })

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        _err(f"折扣计算失败: {e}", 500)
    except Exception as e:
        await db.rollback()
        _err(f"折扣计算异常: {e}", 500)


# ─── 端点：新建规则（管理员）────────────────────────────────────────────────


@router.post("/rules")
async def create_discount_rule(
    req: CreateRuleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/discount/rules — 新建折扣规则（需管理员权限）"""
    tenant_id = _get_tenant_id(request)

    if req.type not in VALID_TYPES:
        _err(f"无效的规则类型: {req.type}")
    for t in req.can_stack_with:
        if t not in VALID_TYPES:
            _err(f"can_stack_with 包含无效类型: {t}")

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        import json
        rule_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO discount_rules
                    (id, tenant_id, store_id, name, priority, type,
                     can_stack_with, apply_order, is_active, description)
                VALUES
                    (:id, :tid::uuid, :store_id::uuid,
                     :name, :priority, :type,
                     :can_stack_with::text[], :apply_order, TRUE, :description)
            """),
            {
                "id": rule_id,
                "tid": tenant_id,
                "store_id": req.store_id,
                "name": req.name,
                "priority": req.priority,
                "type": req.type,
                "can_stack_with": "{" + ",".join(req.can_stack_with) + "}",
                "apply_order": req.apply_order,
                "description": req.description,
            },
        )
        await db.commit()
        return _ok({"rule_id": rule_id, "message": "规则创建成功"})
    except SQLAlchemyError as e:
        await db.rollback()
        _err(f"创建规则失败: {e}", 500)


# ─── 端点：更新规则（管理员）────────────────────────────────────────────────


@router.put("/rules/{rule_id}")
async def update_discount_rule(
    rule_id: str,
    req: UpdateRuleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PUT /api/v1/discount/rules/{rule_id} — 更新折扣规则（需管理员权限）"""
    tenant_id = _get_tenant_id(request)

    if req.can_stack_with is not None:
        for t in req.can_stack_with:
            if t not in VALID_TYPES:
                _err(f"can_stack_with 包含无效类型: {t}")

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 动态构建 SET 子句
        set_clauses: list[str] = ["updated_at = NOW()"]
        params: dict = {"rule_id": rule_id, "tid": tenant_id}

        if req.name is not None:
            set_clauses.append("name = :name")
            params["name"] = req.name
        if req.priority is not None:
            set_clauses.append("priority = :priority")
            params["priority"] = req.priority
        if req.can_stack_with is not None:
            set_clauses.append("can_stack_with = :can_stack_with::text[]")
            params["can_stack_with"] = "{" + ",".join(req.can_stack_with) + "}"
        if req.apply_order is not None:
            set_clauses.append("apply_order = :apply_order")
            params["apply_order"] = req.apply_order
        if req.is_active is not None:
            set_clauses.append("is_active = :is_active")
            params["is_active"] = req.is_active
        if req.description is not None:
            set_clauses.append("description = :description")
            params["description"] = req.description

        result = await db.execute(
            text(f"""
                UPDATE discount_rules
                SET {', '.join(set_clauses)}
                WHERE id = :rule_id::uuid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                RETURNING id
            """),
            params,
        )
        if not result.fetchone():
            _err("规则不存在或无权限修改", 404)

        await db.commit()
        return _ok({"rule_id": rule_id, "message": "规则更新成功"})
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        _err(f"更新规则失败: {e}", 500)
