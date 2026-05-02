"""门店配置模板 API — Task 2.3

将门店的完整运行配置保存为可复用模板，支持：
  - 从现有门店快照创建模板
  - 从模板创建新门店（一键开店）
  - 模板列表/详情/删除

模板包含 7 大配置域（对齐 store_clone CLONE_ITEMS）：
  tables, production_depts, receipt_templates, attendance_rules,
  shift_configs, dispatch_rules, store_push_configs
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/store-templates", tags=["store_templates"])


# ── 模型 ──────────────────────────────────────────────────────────────


class StoreTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    source_store_id: str = Field(..., description="参考门店 ID")
    brand_id: Optional[str] = Field(None)
    business_type: str = Field("dine_in", description="dine_in/takeaway/delivery")


class StoreTemplateItem(BaseModel):
    template_id: str
    name: str
    description: str
    source_store_id: str
    brand_id: Optional[str]
    business_type: str
    config_snapshot: dict
    created_at: str
    updated_at: Optional[str]


class ApplyTemplateRequest(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=100)
    store_address: str = Field("", max_length=300)
    brand_id: Optional[str] = None
    # 可选：覆盖模板中的特定配置域
    override_tables: Optional[List[dict]] = None
    override_printers: Optional[List[dict]] = None


# ── DB 依赖 ────────────────────────────────────────────────────────────


async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 模板 CRUD ──────────────────────────────────────────────────────────


@router.post("", summary="从门店创建配置模板", status_code=201)
async def create_store_template(
    body: StoreTemplateCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """将参考门店的当前运行配置快照保存为模板。

    从 7 个配置域抓取最新数据保存为 JSON 快照。
    """
    tenant_uuid = uuid.UUID(x_tenant_id)
    store_uuid = uuid.UUID(body.source_store_id)

    # 1. 验证门店存在
    store_result = await db.execute(
        text("SELECT id, store_name FROM stores WHERE id = :sid AND tenant_id = :tid"),
        {"sid": store_uuid, "tid": tenant_uuid},
    )
    if not store_result.fetchone():
        raise HTTPException(status_code=404, detail=f"门店不存在: {body.source_store_id}")

    # 2. 抓取配置快照
    snapshot = await _capture_store_config(db, tenant_uuid, store_uuid)

    # 3. 保存模板
    template_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO store_config_templates
                (id, tenant_id, name, description, source_store_id,
                 brand_id, business_type, config_snapshot, created_at)
            VALUES (:id, :tid, :name, :desc, :sid, :bid, :btype, :snap, :now)
        """),
        {
            "id": template_id,
            "tid": tenant_uuid,
            "name": body.name,
            "desc": body.description,
            "sid": store_uuid,
            "bid": uuid.UUID(body.brand_id) if body.brand_id else None,
            "btype": body.business_type,
            "snap": json.dumps(snapshot, ensure_ascii=False, default=str),
            "now": now,
        },
    )
    await db.commit()

    logger.info(
        "store_template_created",
        template_id=str(template_id),
        name=body.name,
        source_store=body.source_store_id,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "template_id": str(template_id),
            "name": body.name,
            "config_domains": list(snapshot.keys()),
        },
    }


@router.get("", summary="模板列表")
async def list_store_templates(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """列出当前租户所有门店配置模板"""
    tenant_uuid = uuid.UUID(x_tenant_id)
    result = await db.execute(
        text("""
            SELECT id, name, description, source_store_id, brand_id,
                   business_type, config_snapshot, created_at, updated_at
            FROM store_config_templates
            WHERE tenant_id = :tid AND is_deleted = FALSE
            ORDER BY created_at DESC
        """),
        {"tid": tenant_uuid},
    )
    items = [
        {
            "template_id": str(r.id),
            "name": r.name,
            "description": r.description,
            "source_store_id": str(r.source_store_id),
            "brand_id": str(r.brand_id) if r.brand_id else None,
            "business_type": r.business_type,
            "config_domains": (
                list(r.config_snapshot.keys())
                if isinstance(r.config_snapshot, dict)
                else []
            ),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in result.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/{template_id}", summary="模板详情")
async def get_store_template(
    template_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """获取模板完整配置快照"""
    tenant_uuid = uuid.UUID(x_tenant_id)
    result = await db.execute(
        text("""
            SELECT id, name, description, source_store_id, brand_id,
                   business_type, config_snapshot, created_at, updated_at
            FROM store_config_templates
            WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"id": uuid.UUID(template_id), "tid": tenant_uuid},
    )
    r = result.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {
        "ok": True,
        "data": {
            "template_id": str(r.id),
            "name": r.name,
            "description": r.description,
            "source_store_id": str(r.source_store_id),
            "brand_id": str(r.brand_id) if r.brand_id else None,
            "business_type": r.business_type,
            "config_snapshot": (
                r.config_snapshot if isinstance(r.config_snapshot, dict)
                else json.loads(r.config_snapshot or "{}")
            ),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        },
    }


@router.delete("/{template_id}", summary="删除模板")
async def delete_store_template(
    template_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """软删除模板"""
    tenant_uuid = uuid.UUID(x_tenant_id)
    result = await db.execute(
        text("""
            UPDATE store_config_templates
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"id": uuid.UUID(template_id), "tid": tenant_uuid},
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True, "data": {"template_id": template_id, "deleted": True}}


# ── 从模板创建门店 ──────────────────────────────────────────────────────


@router.post("/{template_id}/apply", summary="从模板创建门店", status_code=201)
async def apply_store_template(
    template_id: str = Path(...),
    body: ApplyTemplateRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """应用模板创建新门店，自动复制全部配置域。

    步骤：
    1. 创建 stores 记录
    2. 复制 tables（重置状态为 free）
    3. 复制 production_depts
    4. 复制 receipt_templates
    5. 复制 attendance_rules（effective_from = 今天）
    6. 复制 shift_configs
    7. 复制 dispatch_rules（target_printer_id 设为 NULL）
    8. 复制 store_push_configs
    """
    tenant_uuid = uuid.UUID(x_tenant_id)

    # 1. 读模板
    tmpl_result = await db.execute(
        text("""
            SELECT config_snapshot, business_type, brand_id
            FROM store_config_templates
            WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"id": uuid.UUID(template_id), "tid": tenant_uuid},
    )
    tmpl = tmpl_result.fetchone()
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")

    snapshot = (
        tmpl.config_snapshot
        if isinstance(tmpl.config_snapshot, dict)
        else json.loads(tmpl.config_snapshot or "{}")
    )

    # 2. 创建门店
    new_store_id = uuid.uuid4()
    store_code = f"S{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code, address, brand_id, status)
            VALUES (:id, :tid, :name, :code, :addr, :bid, 'inactive')
        """),
        {
            "id": new_store_id,
            "tid": tenant_uuid,
            "name": body.store_name,
            "code": store_code,
            "addr": body.store_address,
            "bid": uuid.UUID(body.brand_id or tmpl.brand_id) if (body.brand_id or tmpl.brand_id) else None,
        },
    )

    # 3. 复制配置域
    applied_domains = await _apply_config_snapshot(
        db, tenant_uuid, new_store_id, snapshot, body
    )
    await db.commit()

    logger.info(
        "store_template_applied",
        template_id=template_id,
        new_store_id=str(new_store_id),
        store_name=body.store_name,
        applied_domains=applied_domains,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "store_id": str(new_store_id),
            "store_name": body.store_name,
            "store_code": store_code,
            "template_id": template_id,
            "applied_domains": applied_domains,
            "status": "inactive",
        },
    }


# ── 内部辅助 ────────────────────────────────────────────────────────────


async def _capture_store_config(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    store_uuid: uuid.UUID,
) -> Dict[str, Any]:
    """从数据库抓取门店当前配置快照（7 域）"""
    snapshot: Dict[str, Any] = {}

    # tables
    result = await db.execute(
        text("SELECT * FROM tables WHERE store_id = :sid AND is_deleted = FALSE"),
        {"sid": store_uuid},
    )
    snapshot["tables"] = [_row_to_dict(r) for r in result.fetchall()]

    # production_depts
    result = await db.execute(
        text("SELECT * FROM production_depts WHERE store_id = :sid"),
        {"sid": store_uuid},
    )
    snapshot["production_depts"] = [_row_to_dict(r) for r in result.fetchall()]

    # receipt_templates
    result = await db.execute(
        text("SELECT * FROM receipt_templates WHERE store_id = :sid"),
        {"sid": store_uuid},
    )
    snapshot["receipt_templates"] = [_row_to_dict(r) for r in result.fetchall()]

    # attendance_rules
    result = await db.execute(
        text("SELECT * FROM attendance_rules WHERE store_id = :sid"),
        {"sid": store_uuid},
    )
    snapshot["attendance_rules"] = [_row_to_dict(r) for r in result.fetchall()]

    # shift_configs
    result = await db.execute(
        text("SELECT * FROM shift_configs WHERE store_id = :sid"),
        {"sid": store_uuid},
    )
    snapshot["shift_configs"] = [_row_to_dict(r) for r in result.fetchall()]

    # dispatch_rules
    result = await db.execute(
        text("SELECT * FROM dispatch_rules WHERE store_id = :sid"),
        {"sid": store_uuid},
    )
    snapshot["dispatch_rules"] = [_row_to_dict(r) for r in result.fetchall()]

    # store_push_configs
    result = await db.execute(
        text("SELECT * FROM store_push_configs WHERE store_id = :sid"),
        {"sid": store_uuid},
    )
    snapshot["store_push_configs"] = [_row_to_dict(r) for r in result.fetchall()]

    return snapshot


async def _apply_config_snapshot(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    new_store_id: uuid.UUID,
    snapshot: Dict[str, Any],
    body: ApplyTemplateRequest,
) -> List[str]:
    """将模板快照中的配置复制到新门店"""
    applied = []

    # tables
    for item in snapshot.get("tables", []):
        await db.execute(
            text("""
                INSERT INTO tables (id, store_id, table_no, area, floor, seats,
                                    min_consume_fen, sort_order, status, config)
                VALUES (:id, :sid, :tno, :area, :floor, :seats,
                        :min_fen, :sort, 'free', :cfg::jsonb)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "tno": item.get("table_no", ""),
                "area": item.get("area", ""),
                "floor": item.get("floor", 1),
                "seats": item.get("seats", 4),
                "min_fen": item.get("min_consume_fen", 0),
                "sort": item.get("sort_order", 0),
                "cfg": json.dumps(item.get("config", {})),
            },
        )
    if snapshot.get("tables"):
        applied.append("tables")

    # production_depts
    for item in snapshot.get("production_depts", []):
        await db.execute(
            text("""
                INSERT INTO production_depts (id, store_id, dept_name, dept_code, sort_order)
                VALUES (:id, :sid, :name, :code, :sort)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "name": item.get("dept_name", ""),
                "code": item.get("dept_code", ""),
                "sort": item.get("sort_order", 0),
            },
        )
    if snapshot.get("production_depts"):
        applied.append("production_depts")

    # receipt_templates
    for item in snapshot.get("receipt_templates", []):
        await db.execute(
            text("""
                INSERT INTO receipt_templates (id, store_id, template_type,
                    template_content, paper_width)
                VALUES (:id, :sid, :type, :content, :width)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "type": item.get("template_type", "receipt"),
                "content": item.get("template_content", ""),
                "width": item.get("paper_width", 80),
            },
        )
    if snapshot.get("receipt_templates"):
        applied.append("receipt_templates")

    # attendance_rules — effective_from 重置为今天
    for item in snapshot.get("attendance_rules", []):
        await db.execute(
            text("""
                INSERT INTO attendance_rules (id, store_id, rule_name,
                    grace_minutes, deduction_rule, clock_method, effective_from)
                VALUES (:id, :sid, :name, :grace, :deduct, :clock, CURRENT_DATE)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "name": item.get("rule_name", ""),
                "grace": item.get("grace_minutes", 0),
                "deduct": item.get("deduction_rule", "{}"),
                "clock": item.get("clock_method", "gps"),
            },
        )
    if snapshot.get("attendance_rules"):
        applied.append("attendance_rules")

    # shift_configs
    for item in snapshot.get("shift_configs", []):
        await db.execute(
            text("""
                INSERT INTO shift_configs (id, store_id, shift_name,
                    start_time, end_time, color)
                VALUES (:id, :sid, :name, :start, :end, :color)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "name": item.get("shift_name", ""),
                "start": item.get("start_time", "09:00"),
                "end": item.get("end_time", "18:00"),
                "color": item.get("color", "#1890ff"),
            },
        )
    if snapshot.get("shift_configs"):
        applied.append("shift_configs")

    # dispatch_rules — target_printer_id 设为 NULL（每店打印机不同）
    for item in snapshot.get("dispatch_rules", []):
        await db.execute(
            text("""
                INSERT INTO dispatch_rules (id, store_id, match_dish_id,
                    match_dish_category, match_channel, dept_id, priority)
                VALUES (:id, :sid, :dish, :cat, :channel, :dept, :priority)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "dish": item.get("match_dish_id") or None,
                "cat": item.get("match_dish_category") or None,
                "channel": item.get("match_channel") or None,
                "dept": item.get("dept_id") or None,
                "priority": item.get("priority", 0),
            },
        )
    if snapshot.get("dispatch_rules"):
        applied.append("dispatch_rules")

    # store_push_configs
    for item in snapshot.get("store_push_configs", []):
        await db.execute(
            text("""
                INSERT INTO store_push_configs (id, store_id, push_mode)
                VALUES (:id, :sid, :mode)
            """),
            {
                "id": uuid.uuid4(),
                "sid": new_store_id,
                "mode": item.get("push_mode", "immediate"),
            },
        )
    if snapshot.get("store_push_configs"):
        applied.append("store_push_configs")

    return applied


def _row_to_dict(row) -> Dict[str, Any]:
    """将 SQLAlchemy Row 转为 dict，排除内部字段"""
    result = {}
    for key in row._mapping.keys():
        if key.startswith("_"):
            continue
        val = row._mapping[key]
        if isinstance(val, uuid.UUID):
            result[key] = str(val)
        elif isinstance(val, datetime):
            result[key] = val.isoformat()
        elif isinstance(val, (dict, list)):
            result[key] = val
        else:
            result[key] = val
    return result
