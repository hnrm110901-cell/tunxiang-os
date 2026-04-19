"""计件提成3.0（对标天财计件提成3.0）— 模块2.6

端点（prefix /api/v1/commission）：

  # 绩效方案管理
  GET    /schemes                      — 方案列表
  POST   /schemes                      — 创建方案（含适用门店/有效期）
  PUT    /schemes/{id}                 — 更新方案
  POST   /schemes/{id}/copy            — 复制方案到其他门店
  DELETE /schemes/{id}                 — 停用方案（软删）

  # 提成维度配置
  GET    /schemes/{id}/rules           — 获取提成规则
  POST   /schemes/{id}/rules           — 配置规则（类型：dish/table/time_slot/revenue_tier）

  # 提成计算与汇总
  POST   /calculate                    — 计算员工提成（员工ID+日期范围）
  GET    /summary                      — 区域/小组汇总视图
  GET    /staff/{id}/detail            — 员工提成明细（自助查询）
  POST   /monthly-settle               — 月度结算（批量生成提成记录）
  GET    /monthly-report               — 月度提成报表

迁移版本：v244_commission_v3（commission_schemes / commission_rules / commission_records）
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/commission", tags=["commission-v3"])


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(msg: str, status: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"ok": False, "data": {}, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS session 变量。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
        {"tid": tenant_id},
    )


def _serialize_row(row: Any) -> dict[str, Any]:
    """将 DB 行转为可 JSON 序列化的 dict。"""
    d = dict(row._mapping)
    for k, v in list(d.items()):
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, date):
            d[k] = str(v)
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────────────────────────────────────


class SchemeCreate(BaseModel):
    name: str = Field(..., max_length=100, description="方案名称")
    applicable_stores: list[str] = Field(
        default_factory=list,
        description="适用门店ID列表，空=集团全部门店",
    )
    effective_date: date | None = Field(None, description="生效日期")
    expiry_date: date | None = Field(None, description="失效日期，NULL=长期有效")
    description: str | None = None
    is_active: bool = True


class SchemeUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    applicable_stores: list[str] | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    description: str | None = None
    is_active: bool | None = None


class SchemeCopyRequest(BaseModel):
    target_stores: list[str] = Field(..., description="目标门店ID列表")
    new_name: str | None = Field(None, description="新方案名称，不传则自动加[副本]后缀")
    effective_date: date | None = None


class RuleCreate(BaseModel):
    rule_type: str = Field(
        ...,
        pattern="^(dish|table|time_slot|revenue_tier)$",
        description="dish=品项提成 / table=桌型提成 / time_slot=时段提成 / revenue_tier=营收阶梯",
    )
    params: dict[str, Any] = Field(
        ...,
        description=(
            "规则参数（JSONB），按类型不同："
            "dish: {dish_id, dish_name, amount_fen, min_qty}；"
            "table: {table_type, amount_fen}；"
            "time_slot: {start_time, end_time, multiplier}；"
            "revenue_tier: {tiers: [{min_fen, max_fen, rate_bps}]}"
        ),
    )
    amount_fen: int = Field(0, ge=0, description="基础金额（分），阶梯类型用 params.tiers")
    description: str | None = None


class CalculateRequest(BaseModel):
    employee_id: uuid.UUID
    store_id: uuid.UUID
    start_date: date
    end_date: date


class MonthlySettleRequest(BaseModel):
    year_month: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="结算月份，格式 YYYY-MM",
    )
    store_ids: list[str] = Field(
        default_factory=list,
        description="门店ID列表，空=当前租户全部门店",
    )


# ──────────────────────────────────────────────────────────────────────────────
# 方案管理
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/schemes")
async def list_schemes(
    is_active: bool = Query(True),
    store_id: uuid.UUID | None = Query(None, description="筛选含该门店的方案"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出绩效方案列表，支持按门店筛选。"""
    try:
        await _set_rls(db, x_tenant_id)
        rows = await db.execute(
            text("""
                SELECT id, tenant_id, name, applicable_stores,
                       effective_date, expiry_date, description,
                       is_active, created_at, updated_at
                FROM commission_schemes
                WHERE tenant_id = :tid
                  AND is_active = :active
                  AND (:store_id IS NULL
                       OR applicable_stores = '[]'::jsonb
                       OR applicable_stores @> to_jsonb(:store_id::text))
                ORDER BY created_at DESC
            """),
            {
                "tid": x_tenant_id,
                "active": is_active,
                "store_id": str(store_id) if store_id else None,
            },
        )
        items = [_serialize_row(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.error("commission.schemes.list.db_error", error=str(exc))
        raise _err(f"查询方案列表失败：{exc}", 500) from exc

    return _ok({"items": items, "total": len(items)})


@router.post("/schemes", status_code=201)
async def create_scheme(
    body: SchemeCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建绩效提成方案。"""
    scheme_id = uuid.uuid4()
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(
            text("""
                INSERT INTO commission_schemes
                    (id, tenant_id, name, applicable_stores,
                     effective_date, expiry_date, description, is_active)
                VALUES (:id, :tid, :name, :stores::jsonb,
                        :eff_date, :exp_date, :desc, :active)
            """),
            {
                "id": str(scheme_id),
                "tid": x_tenant_id,
                "name": body.name,
                "stores": json.dumps(body.applicable_stores),
                "eff_date": body.effective_date,
                "exp_date": body.expiry_date,
                "desc": body.description,
                "active": body.is_active,
            },
        )
        await db.commit()
        logger.info("commission.scheme.created", scheme_id=str(scheme_id), name=body.name)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("commission.scheme.create.failed", error=str(exc))
        raise _err(f"创建方案失败：{exc}", 500) from exc

    return _ok({"id": str(scheme_id), "name": body.name})


@router.put("/schemes/{scheme_id}")
async def update_scheme(
    scheme_id: uuid.UUID,
    body: SchemeUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新方案基本信息（仅传变更字段）。"""
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.applicable_stores is not None:
        fields["applicable_stores"] = json.dumps(body.applicable_stores) + "::jsonb"
    if body.effective_date is not None:
        fields["effective_date"] = body.effective_date
    if body.expiry_date is not None:
        fields["expiry_date"] = body.expiry_date
    if body.description is not None:
        fields["description"] = body.description
    if body.is_active is not None:
        fields["is_active"] = body.is_active

    if not fields:
        raise _err("未提供任何变更字段")

    # 处理 JSONB 字段特殊情况
    set_parts: list[str] = []
    params: dict[str, Any] = {"scheme_id": str(scheme_id), "tid": x_tenant_id}
    for k, v in fields.items():
        if k == "applicable_stores":
            set_parts.append("applicable_stores = :applicable_stores::jsonb")
            params["applicable_stores"] = json.dumps(body.applicable_stores)
        else:
            set_parts.append(f"{k} = :{k}")
            params[k] = v

    set_clause = ", ".join(set_parts)

    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text(
                f"UPDATE commission_schemes SET {set_clause}, updated_at = NOW() "
                f"WHERE id = :scheme_id AND tenant_id = :tid"
            ),
            params,
        )
        if result.rowcount == 0:
            raise _err("方案不存在或无权限", 404)
        await db.commit()
        logger.info("commission.scheme.updated", scheme_id=str(scheme_id))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("commission.scheme.update.failed", error=str(exc))
        raise _err(f"更新方案失败：{exc}", 500) from exc

    return _ok({"id": str(scheme_id), "updated": True})


@router.post("/schemes/{scheme_id}/copy", status_code=201)
async def copy_scheme(
    scheme_id: uuid.UUID,
    body: SchemeCopyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """复制方案到其他门店（含规则完整复制）。"""
    try:
        await _set_rls(db, x_tenant_id)

        # 查询原方案
        src_row = await db.execute(
            text("""
                SELECT name, applicable_stores, effective_date, expiry_date, description
                FROM commission_schemes
                WHERE id = :sid AND tenant_id = :tid
            """),
            {"sid": str(scheme_id), "tid": x_tenant_id},
        )
        src = src_row.fetchone()
        if src is None:
            raise _err("源方案不存在或无权限", 404)

        new_name = body.new_name or f"{src.name}[副本]"
        new_id = uuid.uuid4()
        eff_date = body.effective_date or src.effective_date

        await db.execute(
            text("""
                INSERT INTO commission_schemes
                    (id, tenant_id, name, applicable_stores,
                     effective_date, expiry_date, description, is_active)
                VALUES (:id, :tid, :name, :stores::jsonb,
                        :eff_date, :exp_date, :desc, TRUE)
            """),
            {
                "id": str(new_id),
                "tid": x_tenant_id,
                "name": new_name,
                "stores": json.dumps(body.target_stores),
                "eff_date": eff_date,
                "exp_date": src.expiry_date,
                "desc": src.description,
            },
        )

        # 复制原方案的全部规则
        rules_rows = await db.execute(
            text("""
                SELECT rule_type, params, amount_fen, description
                FROM commission_rules
                WHERE scheme_id = :sid AND tenant_id = :tid
            """),
            {"sid": str(scheme_id), "tid": x_tenant_id},
        )
        rules = rules_rows.fetchall()
        for rule in rules:
            await db.execute(
                text("""
                    INSERT INTO commission_rules
                        (id, tenant_id, scheme_id, rule_type, params, amount_fen, description)
                    VALUES (gen_random_uuid(), :tid, :scheme_id,
                            :rule_type, :params::jsonb, :amount_fen, :desc)
                """),
                {
                    "tid": x_tenant_id,
                    "scheme_id": str(new_id),
                    "rule_type": rule.rule_type,
                    "params": json.dumps(dict(rule.params)) if rule.params else "{}",
                    "amount_fen": rule.amount_fen,
                    "desc": rule.description,
                },
            )

        await db.commit()
        logger.info(
            "commission.scheme.copied",
            src_id=str(scheme_id),
            new_id=str(new_id),
            rules_copied=len(rules),
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("commission.scheme.copy.failed", error=str(exc))
        raise _err(f"复制方案失败：{exc}", 500) from exc

    return _ok({"id": str(new_id), "name": new_name, "rules_copied": len(rules)})


@router.delete("/schemes/{scheme_id}")
async def deactivate_scheme(
    scheme_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """停用方案（软删除，设 is_active=FALSE）。"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("""
                UPDATE commission_schemes
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = :sid AND tenant_id = :tid
            """),
            {"sid": str(scheme_id), "tid": x_tenant_id},
        )
        if result.rowcount == 0:
            raise _err("方案不存在或无权限", 404)
        await db.commit()
        logger.info("commission.scheme.deactivated", scheme_id=str(scheme_id))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("commission.scheme.deactivate.failed", error=str(exc))
        raise _err(f"停用方案失败：{exc}", 500) from exc

    return _ok({"id": str(scheme_id), "deactivated": True})


# ──────────────────────────────────────────────────────────────────────────────
# 提成维度配置（规则）
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/schemes/{scheme_id}/rules")
async def list_rules(
    scheme_id: uuid.UUID,
    rule_type: str | None = Query(None, description="筛选规则类型"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取方案下的提成规则列表（支持4类维度）。"""
    try:
        await _set_rls(db, x_tenant_id)

        # 验证方案归属
        chk = await db.execute(
            text("SELECT id FROM commission_schemes WHERE id = :sid AND tenant_id = :tid"),
            {"sid": str(scheme_id), "tid": x_tenant_id},
        )
        if chk.fetchone() is None:
            raise _err("方案不存在或无权限", 404)

        rows = await db.execute(
            text("""
                SELECT id, scheme_id, rule_type, params, amount_fen, description,
                       created_at, updated_at
                FROM commission_rules
                WHERE scheme_id = :sid AND tenant_id = :tid
                  AND (:rule_type IS NULL OR rule_type = :rule_type)
                ORDER BY rule_type, created_at
            """),
            {"sid": str(scheme_id), "tid": x_tenant_id, "rule_type": rule_type},
        )
        items = [_serialize_row(r) for r in rows]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("commission.rules.list.db_error", error=str(exc))
        raise _err(f"查询提成规则失败：{exc}", 500) from exc

    return _ok({"items": items, "total": len(items)})


@router.post("/schemes/{scheme_id}/rules", status_code=201)
async def create_rule(
    scheme_id: uuid.UUID,
    body: RuleCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """为方案添加提成规则（支持4类维度：品项/桌型/时段/营收阶梯）。"""
    rule_id = uuid.uuid4()
    try:
        await _set_rls(db, x_tenant_id)

        # 验证方案归属
        chk = await db.execute(
            text("SELECT id FROM commission_schemes WHERE id = :sid AND tenant_id = :tid AND is_active = TRUE"),
            {"sid": str(scheme_id), "tid": x_tenant_id},
        )
        if chk.fetchone() is None:
            raise _err("方案不存在、已停用或无权限", 404)

        await db.execute(
            text("""
                INSERT INTO commission_rules
                    (id, tenant_id, scheme_id, rule_type, params, amount_fen, description)
                VALUES (:id, :tid, :scheme_id, :rule_type, :params::jsonb, :amount_fen, :desc)
            """),
            {
                "id": str(rule_id),
                "tid": x_tenant_id,
                "scheme_id": str(scheme_id),
                "rule_type": body.rule_type,
                "params": json.dumps(body.params),
                "amount_fen": body.amount_fen,
                "desc": body.description,
            },
        )
        await db.commit()
        logger.info(
            "commission.rule.created",
            rule_id=str(rule_id),
            scheme_id=str(scheme_id),
            rule_type=body.rule_type,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("commission.rule.create.failed", error=str(exc))
        raise _err(f"创建提成规则失败：{exc}", 500) from exc

    return _ok({"id": str(rule_id), "rule_type": body.rule_type})


# ──────────────────────────────────────────────────────────────────────────────
# 提成计算
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/calculate")
async def calculate_commission(
    body: CalculateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """计算指定员工在日期范围内的提成（按已配置规则逐条匹配汇总）。"""
    try:
        await _set_rls(db, x_tenant_id)

        # 取该门店当前有效方案的所有规则
        rules_rows = await db.execute(
            text("""
                SELECT cr.id AS rule_id, cr.rule_type, cr.params, cr.amount_fen
                FROM commission_rules cr
                JOIN commission_schemes cs ON cs.id = cr.scheme_id
                WHERE cs.tenant_id = :tid
                  AND cs.is_active = TRUE
                  AND (cs.applicable_stores = '[]'::jsonb
                       OR cs.applicable_stores @> to_jsonb(:store_id::text))
                  AND (cs.effective_date IS NULL OR cs.effective_date <= :end_date)
                  AND (cs.expiry_date IS NULL OR cs.expiry_date >= :start_date)
            """),
            {
                "tid": x_tenant_id,
                "store_id": str(body.store_id),
                "start_date": body.start_date,
                "end_date": body.end_date,
            },
        )
        rules = rules_rows.fetchall()

        breakdown: list[dict[str, Any]] = []
        total_fen = 0

        for rule in rules:
            params = rule.params or {}
            rule_type = rule.rule_type
            amount_fen = rule.amount_fen or 0

            if rule_type == "dish":
                # 按品项：从 piecework_records 或订单明细中统计件数
                dish_id = params.get("dish_id")
                min_qty = int(params.get("min_qty", 1))
                if dish_id:
                    qty_row = await db.execute(
                        text("""
                            SELECT COALESCE(SUM(quantity), 0) AS qty
                            FROM piecework_records
                            WHERE tenant_id   = :tid
                              AND store_id    = :store_id
                              AND employee_id = :employee_id
                              AND dish_id     = :dish_id
                              AND recorded_at::date BETWEEN :start_date AND :end_date
                        """),
                        {
                            "tid": x_tenant_id,
                            "store_id": str(body.store_id),
                            "employee_id": str(body.employee_id),
                            "dish_id": dish_id,
                            "start_date": body.start_date,
                            "end_date": body.end_date,
                        },
                    )
                    qty = int(qty_row.fetchone().qty or 0)
                    effective_qty = max(0, qty - min_qty + 1)
                    earned = effective_qty * amount_fen
                else:
                    qty = 0
                    earned = 0

                if earned > 0:
                    breakdown.append(
                        {
                            "rule_id": str(rule.rule_id),
                            "rule_type": rule_type,
                            "description": f"品项提成 qty={qty}",
                            "earned_fen": earned,
                        }
                    )
                    total_fen += earned

            elif rule_type == "revenue_tier":
                # 营收阶梯：查员工期间销售额
                rev_row = await db.execute(
                    text("""
                        SELECT COALESCE(SUM(pr.quantity * pr.unit_fee_fen), 0) AS revenue_fen
                        FROM piecework_records pr
                        WHERE pr.tenant_id   = :tid
                          AND pr.store_id    = :store_id
                          AND pr.employee_id = :employee_id
                          AND pr.recorded_at::date BETWEEN :start_date AND :end_date
                    """),
                    {
                        "tid": x_tenant_id,
                        "store_id": str(body.store_id),
                        "employee_id": str(body.employee_id),
                        "start_date": body.start_date,
                        "end_date": body.end_date,
                    },
                )
                revenue_fen = int(rev_row.fetchone().revenue_fen or 0)
                tiers = params.get("tiers", [])
                earned = 0
                matched_tier = None
                for tier in tiers:
                    min_f = int(tier.get("min_fen", 0))
                    max_f = tier.get("max_fen")
                    rate_bps = int(tier.get("rate_bps", 0))
                    if revenue_fen >= min_f and (max_f is None or revenue_fen < max_f):
                        earned = revenue_fen * rate_bps // 10000
                        matched_tier = tier
                        break
                if earned > 0:
                    breakdown.append(
                        {
                            "rule_id": str(rule.rule_id),
                            "rule_type": rule_type,
                            "description": f"营收阶梯 revenue={revenue_fen}分 tier={matched_tier}",
                            "earned_fen": earned,
                        }
                    )
                    total_fen += earned

            elif rule_type == "table":
                # 桌型提成：统计员工在该桌型服务的桌次数 × 每桌 amount_fen
                # 数据来源：dining_sessions.lead_waiter_id + tables.table_type
                target_table_type = params.get("table_type", "")
                table_filter = ""
                if target_table_type:
                    table_filter = "AND t.table_type = :table_type"
                table_count_row = await db.execute(
                    text(f"""
                        SELECT COUNT(ds.id) AS table_count
                        FROM dining_sessions ds
                        JOIN tables t ON t.id = ds.table_id
                        WHERE ds.tenant_id     = :tid
                          AND ds.store_id      = :store_id
                          AND ds.lead_waiter_id = :employee_id
                          AND ds.opened_at::date BETWEEN :start_date AND :end_date
                          AND ds.status        = 'closed'
                          {table_filter}
                    """),
                    {
                        "tid": x_tenant_id,
                        "store_id": str(body.store_id),
                        "employee_id": str(body.employee_id),
                        "start_date": body.start_date,
                        "end_date": body.end_date,
                        **({"table_type": target_table_type} if target_table_type else {}),
                    },
                )
                table_count = int(table_count_row.fetchone().table_count or 0)
                earned = table_count * amount_fen
                if earned > 0:
                    breakdown.append(
                        {
                            "rule_id": str(rule.rule_id),
                            "rule_type": "table",
                            "description": (
                                f"桌型提成 table_type={target_table_type or '全部'} 桌次={table_count} × {amount_fen}分"
                            ),
                            "earned_fen": earned,
                        }
                    )
                    total_fen += earned

            elif rule_type == "time_slot":
                # 时段提成：统计员工在指定时段服务的桌次，对时段内桌型提成应用 multiplier
                # 或：直接统计时段内 dining_sessions 桌次 × amount_fen × multiplier
                start_time_str = params.get("start_time", "00:00")
                end_time_str = params.get("end_time", "23:59")
                multiplier = float(params.get("multiplier", 1.0))
                slot_count_row = await db.execute(
                    text("""
                        SELECT COUNT(ds.id) AS slot_count
                        FROM dining_sessions ds
                        WHERE ds.tenant_id      = :tid
                          AND ds.store_id       = :store_id
                          AND ds.lead_waiter_id = :employee_id
                          AND ds.opened_at::date BETWEEN :start_date AND :end_date
                          AND ds.opened_at::time BETWEEN :start_time::time AND :end_time::time
                          AND ds.status         = 'closed'
                    """),
                    {
                        "tid": x_tenant_id,
                        "store_id": str(body.store_id),
                        "employee_id": str(body.employee_id),
                        "start_date": body.start_date,
                        "end_date": body.end_date,
                        "start_time": start_time_str,
                        "end_time": end_time_str,
                    },
                )
                slot_count = int(slot_count_row.fetchone().slot_count or 0)
                base = slot_count * amount_fen
                earned = int(base * multiplier)
                if earned > 0:
                    breakdown.append(
                        {
                            "rule_id": str(rule.rule_id),
                            "rule_type": "time_slot",
                            "description": (
                                f"时段提成 {start_time_str}~{end_time_str} "
                                f"桌次={slot_count} × {amount_fen}分 × {multiplier}"
                            ),
                            "earned_fen": earned,
                        }
                    )
                    total_fen += earned

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("commission.calculate.db_error", error=str(exc))
        raise _err(f"提成计算失败：{exc}", 500) from exc

    return _ok(
        {
            "employee_id": str(body.employee_id),
            "store_id": str(body.store_id),
            "start_date": str(body.start_date),
            "end_date": str(body.end_date),
            "total_commission_fen": total_fen,
            "breakdown": breakdown,
        }
    )


@router.get("/summary")
async def commission_summary(
    year_month: str = Query(..., description="月份 YYYY-MM"),
    store_id: uuid.UUID | None = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """区域/小组汇总视图：按月聚合员工提成总额。"""
    try:
        await _set_rls(db, x_tenant_id)
        rows = await db.execute(
            text("""
                SELECT
                    cr.employee_id,
                    cr.store_id,
                    SUM(cr.total_commission_fen) AS total_commission_fen,
                    COUNT(*)                     AS record_count,
                    cr.status
                FROM commission_records cr
                WHERE cr.tenant_id   = :tid
                  AND cr.year_month  = :year_month
                  AND (:store_id IS NULL OR cr.store_id = :store_id)
                GROUP BY cr.employee_id, cr.store_id, cr.status
                ORDER BY total_commission_fen DESC
            """),
            {
                "tid": x_tenant_id,
                "year_month": year_month,
                "store_id": str(store_id) if store_id else None,
            },
        )
        items = [_serialize_row(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.error("commission.summary.db_error", error=str(exc))
        raise _err(f"查询汇总失败：{exc}", 500) from exc

    grand_total = sum(i.get("total_commission_fen", 0) for i in items)
    return _ok(
        {
            "year_month": year_month,
            "store_id": str(store_id) if store_id else None,
            "items": items,
            "total": len(items),
            "grand_total_commission_fen": grand_total,
        }
    )


@router.get("/staff/{employee_id}/detail")
async def staff_commission_detail(
    employee_id: uuid.UUID,
    year_month: str = Query(..., description="月份 YYYY-MM"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """员工提成明细（自助查询）：明细JSONB展开，展示每条来源。"""
    try:
        await _set_rls(db, x_tenant_id)
        rows = await db.execute(
            text("""
                SELECT id, employee_id, store_id, year_month,
                       total_commission_fen, breakdown, status,
                       settled_at, created_at
                FROM commission_records
                WHERE tenant_id   = :tid
                  AND employee_id = :employee_id
                  AND year_month  = :year_month
                ORDER BY created_at DESC
            """),
            {
                "tid": x_tenant_id,
                "employee_id": str(employee_id),
                "year_month": year_month,
            },
        )
        items = [_serialize_row(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.error("commission.staff.detail.db_error", error=str(exc))
        raise _err(f"查询员工提成明细失败：{exc}", 500) from exc

    total = sum(i.get("total_commission_fen", 0) for i in items)
    return _ok(
        {
            "employee_id": str(employee_id),
            "year_month": year_month,
            "records": items,
            "total_commission_fen": total,
        }
    )


@router.post("/monthly-settle")
async def monthly_settle(
    body: MonthlySettleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """月度批量结算：扫描 piecework_records，生成/更新 commission_records。"""
    year, month = body.year_month.split("-")
    start_date = date(int(year), int(month), 1)
    import calendar

    last_day = calendar.monthrange(int(year), int(month))[1]
    end_date = date(int(year), int(month), last_day)

    settled_count = 0
    skipped_count = 0

    try:
        await _set_rls(db, x_tenant_id)

        # 查询月内所有员工+门店的计件汇总
        store_filter = "AND store_id = ANY(:store_ids::uuid[])" if body.store_ids else ""
        agg_rows = await db.execute(
            text(f"""
                SELECT
                    employee_id,
                    store_id,
                    SUM(total_fee_fen)  AS total_fee_fen
                FROM piecework_records
                WHERE tenant_id    = :tid
                  AND recorded_at::date BETWEEN :start_date AND :end_date
                  {store_filter}
                GROUP BY employee_id, store_id
            """),
            {
                "tid": x_tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                **({"store_ids": body.store_ids} if body.store_ids else {}),
            },
        )
        agg_list = agg_rows.fetchall()

        # 批量拉取涉及员工的姓名（一次查询，避免 N+1）
        employee_ids = list({str(r.employee_id) for r in agg_list})
        employee_names: dict[str, str] = {}
        if employee_ids:
            name_rows = await db.execute(
                text("""
                    SELECT id, name FROM employees
                    WHERE tenant_id = :tid AND id = ANY(:ids::uuid[])
                      AND is_deleted = FALSE
                """),
                {"tid": x_tenant_id, "ids": employee_ids},
            )
            for nr in name_rows.fetchall():
                employee_names[str(nr.id)] = nr.name or ""

        for row in agg_list:
            record_id = uuid.uuid4()
            total_fen = int(row.total_fee_fen or 0)
            breakdown_json = json.dumps(
                [
                    {
                        "source": "piecework_records",
                        "total_fen": total_fen,
                        "period": f"{start_date} ~ {end_date}",
                    }
                ]
            )
            emp_name = employee_names.get(str(row.employee_id), "")

            # UPSERT：已结算的不覆盖
            result = await db.execute(
                text("""
                    INSERT INTO commission_records
                        (id, tenant_id, employee_id, store_id, year_month,
                         total_commission_fen, breakdown, status, settled_at,
                         employee_name)
                    VALUES (:id, :tid, :employee_id, :store_id, :year_month,
                            :total_fen, :breakdown::jsonb, 'settled', NOW(),
                            :employee_name)
                    ON CONFLICT (tenant_id, employee_id, store_id, year_month)
                    DO UPDATE SET
                        total_commission_fen = EXCLUDED.total_commission_fen,
                        breakdown            = EXCLUDED.breakdown,
                        status               = EXCLUDED.status,
                        settled_at           = EXCLUDED.settled_at,
                        employee_name        = EXCLUDED.employee_name,
                        updated_at           = NOW()
                    WHERE commission_records.status <> 'settled'
                """),
                {
                    "id": str(record_id),
                    "tid": x_tenant_id,
                    "employee_id": str(row.employee_id),
                    "store_id": str(row.store_id),
                    "year_month": body.year_month,
                    "total_fen": total_fen,
                    "breakdown": breakdown_json,
                    "employee_name": emp_name,
                },
            )
            if result.rowcount > 0:
                settled_count += 1
            else:
                skipped_count += 1

        await db.commit()
        logger.info(
            "commission.monthly_settle.done",
            year_month=body.year_month,
            settled=settled_count,
            skipped=skipped_count,
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("commission.monthly_settle.failed", error=str(exc))
        raise _err(f"月度结算失败：{exc}", 500) from exc

    return _ok(
        {
            "year_month": body.year_month,
            "settled_count": settled_count,
            "skipped_count": skipped_count,
            "total_processed": len(agg_list),
        }
    )


@router.get("/monthly-report")
async def monthly_report(
    year_month: str = Query(..., description="月份 YYYY-MM"),
    store_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """月度提成报表：分页展示当月所有员工结算记录及总计。"""
    offset = (page - 1) * size
    try:
        await _set_rls(db, x_tenant_id)

        total_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(total_commission_fen), 0) AS grand_total_fen
                FROM commission_records
                WHERE tenant_id  = :tid
                  AND year_month = :year_month
                  AND (:store_id IS NULL OR store_id = :store_id)
            """),
            {
                "tid": x_tenant_id,
                "year_month": year_month,
                "store_id": str(store_id) if store_id else None,
            },
        )
        agg = total_row.fetchone()
        total = int(agg.cnt or 0)
        grand_total_fen = int(agg.grand_total_fen or 0)

        rows = await db.execute(
            text("""
                SELECT id, employee_id, store_id, year_month,
                       total_commission_fen, breakdown, status,
                       settled_at, created_at
                FROM commission_records
                WHERE tenant_id  = :tid
                  AND year_month = :year_month
                  AND (:store_id IS NULL OR store_id = :store_id)
                ORDER BY total_commission_fen DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "tid": x_tenant_id,
                "year_month": year_month,
                "store_id": str(store_id) if store_id else None,
                "size": size,
                "offset": offset,
            },
        )
        items = [_serialize_row(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.error("commission.monthly_report.db_error", error=str(exc))
        raise _err(f"查询月报失败：{exc}", 500) from exc

    return _ok(
        {
            "year_month": year_month,
            "page": page,
            "size": size,
            "total": total,
            "grand_total_commission_fen": grand_total_fen,
            "items": items,
        }
    )
