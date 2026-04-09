"""
自定义报表框架路由 — DB版

GET    /api/v1/analytics/reports                              — 报表列表
GET    /api/v1/analytics/reports/shared/{share_token}        — 分享token查看（无需认证）
GET    /api/v1/analytics/reports/{report_id}                 — 报表详情
POST   /api/v1/analytics/reports                             — 创建报表配置
PUT    /api/v1/analytics/reports/{report_id}                 — 更新报表配置
DELETE /api/v1/analytics/reports/{report_id}                 — 软删除
POST   /api/v1/analytics/reports/{report_id}/favorite        — 收藏/取消收藏
POST   /api/v1/analytics/reports/{report_id}/execute         — 执行报表
POST   /api/v1/analytics/reports/{report_id}/share           — 生成分享链接
POST   /api/v1/analytics/reports/{report_id}/schedule        — 配置定时推送
DELETE /api/v1/analytics/reports/{report_id}/schedule        — 取消定时推送
GET    /api/v1/analytics/narrative-templates                 — 叙事模板列表
POST   /api/v1/analytics/narrative-templates                 — 创建叙事模板
PUT    /api/v1/analytics/narrative-templates/{template_id}   — 更新叙事模板
POST   /api/v1/analytics/narrative-templates/{template_id}/preview — 预览叙事效果
"""
from __future__ import annotations

import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["custom-reports"])


# ─── DB 依赖 ────────────────────────────────────────────────────────────────

async def _get_db(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── Pydantic 模型 ───────────────────────────────────────────────────────────

class ReportConfigCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = "operation"
    sql_template: Optional[str] = None
    default_params: Optional[dict[str, Any]] = None
    dimensions: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    filters: list[dict[str, Any]] = []
    is_system: bool = False


class ReportConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    sql_template: Optional[str] = None
    default_params: Optional[dict[str, Any]] = None
    dimensions: Optional[list[dict[str, Any]]] = None
    metrics: Optional[list[dict[str, Any]]] = None
    filters: Optional[list[dict[str, Any]]] = None


class ReportExecuteBody(BaseModel):
    params: Optional[dict[str, Any]] = None
    row_limit: int = 500


class ScheduleConfigUpdate(BaseModel):
    cron: str
    channels: list[str]
    recipients: list[str]


class NarrativeTemplateCreate(BaseModel):
    name: str
    brand_focus: Optional[str] = None
    prompt_prefix: Optional[str] = None
    metrics_weights: Optional[dict[str, float]] = None
    tone: str = "professional"
    is_default: bool = False


class NarrativeTemplateUpdate(BaseModel):
    name: Optional[str] = None
    brand_focus: Optional[str] = None
    prompt_prefix: Optional[str] = None
    metrics_weights: Optional[dict[str, float]] = None
    tone: Optional[str] = None
    is_default: Optional[bool] = None


# ─── 叙事模板内存存储（非关键路径，保留内存实现） ─────────────────────────────

MOCK_NARRATIVE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "tpl-001",
        "name": "标准经营日报",
        "brand_focus": "营业额/毛利",
        "prompt_prefix": "请以专业财务视角，分析今日经营数据，重点关注营业额完成情况和毛利变化趋势。",
        "metrics_weights": {"revenue": 0.5, "gross_profit": 0.3, "order_count": 0.2},
        "tone": "professional",
        "is_default": True,
        "is_deleted": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": "tpl-002",
        "name": "徐记海鲜活鲜专报",
        "brand_focus": "活鲜销售/毛利/损耗",
        "prompt_prefix": "请以高端海鲜餐饮品牌视角，重点分析活鲜品类销售、损耗控制和毛利表现，与品牌标准对比。",
        "metrics_weights": {"revenue": 0.3, "seafood_revenue": 0.4, "waste_rate": 0.2, "gross_margin": 0.1},
        "tone": "executive",
        "is_default": False,
        "is_deleted": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": "tpl-003",
        "name": "快餐效率简报",
        "brand_focus": "翻台率/人效/品项销量",
        "prompt_prefix": "请用简洁口语化的方式，报告今日翻台率、人效和热销品项，适合晨会快速分享。",
        "metrics_weights": {"table_turn_rate": 0.35, "labor_efficiency": 0.35, "top_dish_sales": 0.3},
        "tone": "casual",
        "is_default": False,
        "is_deleted": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
]

_custom_templates: dict[str, dict[str, Any]] = {}


# ─── 叙事辅助 ───────────────────────────────────────────────────────────────

def _generate_narrative_preview(template: dict[str, Any], mock_data: dict[str, Any]) -> str:
    """根据模板生成示例叙事文本"""
    name = template.get("name", "经营日报")
    focus = template.get("brand_focus", "营业额/毛利")
    tone = template.get("tone", "professional")

    if "活鲜" in focus:
        return (
            f"【{name}】今日营业额 ¥28,560，较昨日+12.3%。"
            f"{focus}方面：活鲜销售占比38.2%（螃蟹/虾/鱼类合计¥10,920），"
            f"毛利率52.1%，高于品牌均线4.2个百分点。"
            f"建议关注：波士顿龙虾库存仅剩6只，预计今晚售罄，可提前备货。"
        )
    if "翻台率" in focus or tone == "casual":
        return (
            f"【{name}】今天翻台2.8轮，比昨天好一点。"
            f"人效318元/人，跑赢上周均值。"
            f"热销TOP3：剁椒鱼头/佛跳墙/小炒黄牛肉，合计占营收31%。"
            f"晚市高峰期18:30-20:00出菜稍慢，明天提前准备。"
        )
    return (
        f"【{name}】今日整体经营表现良好。{focus}核心指标：营业额¥28,560（达成率102.3%），"
        f"毛利率48.6%，较上周同期提升1.8个百分点。"
        f"重点关注：会员到店率较昨日下降3.2%，建议营销团队跟进复购触达策略。"
    )


# ─── 报表配置 CRUD（纯DB） ──────────────────────────────────────────────────

@router.get("/reports")
async def list_reports(
    category: Optional[str] = Query(None, description="finance/operation/member/hr"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取报表列表"""
    conditions = ["is_deleted = FALSE", "is_active = TRUE"]
    params: dict[str, Any] = {}
    if category:
        conditions.append("category = :category")
        params["category"] = category

    where = " AND ".join(conditions)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM report_configs WHERE {where}"),  # noqa: S608
        params,
    )
    total = count_result.scalar_one()

    result = await db.execute(
        text(
            f"SELECT id, name, description, category, dimensions, metrics, filters, "  # noqa: S608
            f"is_system, is_active, created_at, updated_at "
            f"FROM report_configs WHERE {where} "
            f"ORDER BY is_system DESC, created_at DESC "
            f"LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = result.mappings().all()
    items = [dict(r) for r in rows]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/reports/shared/{share_token}")
async def get_shared_report(share_token: str) -> dict[str, Any]:
    """通过分享token查看报表（无需认证） — 保留占位，后续接入"""
    raise HTTPException(status_code=501, detail="分享功能待接入")


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取报表详情"""
    result = await db.execute(
        text(
            "SELECT id, name, description, category, sql_template, default_params, "
            "dimensions, metrics, filters, is_system, is_active, created_at, updated_at "
            "FROM report_configs WHERE id = :id AND is_deleted = FALSE"
        ),
        {"id": report_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    return {"ok": True, "data": dict(row)}


@router.post("/reports")
async def create_report(
    body: ReportConfigCreate,
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """创建报表配置"""
    report_id = f"custom_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            "INSERT INTO report_configs "
            "(id, tenant_id, name, description, category, sql_template, "
            "default_params, dimensions, metrics, filters, is_system, "
            "created_at, updated_at) "
            "VALUES (:id, current_setting('app.tenant_id')::uuid, :name, :description, "
            ":category, :sql_template, :default_params::jsonb, "
            ":dimensions::jsonb, :metrics::jsonb, :filters::jsonb, :is_system, "
            ":created_at, :updated_at)"
        ),
        {
            "id": report_id,
            "name": body.name,
            "description": body.description or "",
            "category": body.category,
            "sql_template": body.sql_template or "",
            "default_params": _json_str(body.default_params or {}),
            "dimensions": _json_str(body.dimensions),
            "metrics": _json_str(body.metrics),
            "filters": _json_str(body.filters),
            "is_system": body.is_system,
            "created_at": now,
            "updated_at": now,
        },
    )
    logger.info("report_config_created", report_id=report_id, name=body.name)

    return {
        "ok": True,
        "data": {
            "id": report_id,
            "name": body.name,
            "category": body.category,
            "created_at": now.isoformat(),
        },
    }


@router.put("/reports/{report_id}")
async def update_report(
    report_id: str,
    body: ReportConfigUpdate,
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """更新报表配置"""
    # 检查存在
    check = await db.execute(
        text("SELECT is_system FROM report_configs WHERE id = :id AND is_deleted = FALSE"),
        {"id": report_id},
    )
    row = check.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")
    if row["is_system"]:
        raise HTTPException(status_code=400, detail="系统报表不可修改")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新字段")

    set_clauses: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": report_id}
    json_fields = {"default_params", "dimensions", "metrics", "filters"}

    for field, value in updates.items():
        if field in json_fields:
            set_clauses.append(f"{field} = :{field}::jsonb")
            params[field] = _json_str(value)
        else:
            set_clauses.append(f"{field} = :{field}")
            params[field] = value

    await db.execute(
        text(f"UPDATE report_configs SET {', '.join(set_clauses)} WHERE id = :id"),  # noqa: S608
        params,
    )
    logger.info("report_config_updated", report_id=report_id, fields=list(updates.keys()))

    return {"ok": True, "data": {"report_id": report_id, "updated_fields": list(updates.keys())}}


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """软删除报表"""
    check = await db.execute(
        text("SELECT is_system FROM report_configs WHERE id = :id AND is_deleted = FALSE"),
        {"id": report_id},
    )
    row = check.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")
    if row["is_system"]:
        raise HTTPException(status_code=400, detail="系统报表不可删除")

    await db.execute(
        text("UPDATE report_configs SET is_deleted = TRUE, updated_at = NOW() WHERE id = :id"),
        {"id": report_id},
    )
    logger.info("report_config_deleted", report_id=report_id)

    return {"ok": True, "data": {"deleted": True, "report_id": report_id}}


@router.post("/reports/{report_id}/favorite")
async def toggle_favorite(report_id: str) -> dict[str, Any]:
    """收藏/取消收藏 — 保留占位（收藏状态未来存user_preferences表）"""
    return {"ok": True, "data": {"report_id": report_id, "is_favorite": True}}


# ─── 报表执行 ────────────────────────────────────────────────────────────────

@router.post("/reports/{report_id}/execute")
async def execute_report(
    report_id: str,
    body: ReportExecuteBody = ReportExecuteBody(),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """执行报表：读取 sql_template，替换参数，执行查询返回结果"""
    # 1. 读取报表配置
    result = await db.execute(
        text(
            "SELECT sql_template, default_params, dimensions, metrics "
            "FROM report_configs WHERE id = :id AND is_deleted = FALSE"
        ),
        {"id": report_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    sql_template = row["sql_template"]
    if not sql_template or not sql_template.strip():
        raise HTTPException(status_code=400, detail="报表未配置 SQL 模板")

    # 2. 合并参数：default_params + 请求参数
    merged_params: dict[str, Any] = {}
    default_params = row["default_params"]
    if isinstance(default_params, dict):
        merged_params.update(default_params)
    if body.params:
        merged_params.update(body.params)

    # 3. 添加行数限制
    limited_sql = f"SELECT * FROM ({sql_template}) AS _rpt LIMIT :_row_limit"
    merged_params["_row_limit"] = body.row_limit

    # 4. 执行
    start_ms = int(time.time() * 1000)
    try:
        query_result = await db.execute(text(limited_sql), merged_params)
        rows = [dict(r) for r in query_result.mappings().all()]
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.error("report_execute_failed", report_id=report_id, error=str(exc))
        raise HTTPException(status_code=400, detail=f"SQL执行失败: {exc}") from exc

    end_ms = int(time.time() * 1000)
    execution_ms = max(1, end_ms - start_ms)

    logger.info(
        "report_executed",
        report_id=report_id,
        row_count=len(rows),
        execution_ms=execution_ms,
    )

    return {
        "ok": True,
        "data": {
            "execution": {
                "report_id": report_id,
                "status": "completed",
                "row_count": len(rows),
                "execution_ms": execution_ms,
            },
            "rows": rows,
            "columns": _build_columns(row["dimensions"], row["metrics"]),
        },
    }


def _build_columns(
    dimensions: Any, metrics: Any
) -> list[dict[str, str]]:
    """从报表配置提取列定义"""
    cols: list[dict[str, str]] = []
    if isinstance(dimensions, list):
        for dim in dimensions:
            cols.append({"field": dim.get("name", ""), "label": dim.get("label", ""), "type": "dimension"})
    if isinstance(metrics, list):
        for m in metrics:
            cols.append({"field": m.get("name", ""), "label": m.get("label", ""), "type": "metric"})
    return cols


@router.post("/reports/{report_id}/share")
async def generate_share_link(report_id: str) -> dict[str, Any]:
    """生成分享链接 — 保留占位"""
    share_token = secrets.token_hex(32)
    share_url = f"https://admin.tunxiang.com/analytics/reports/shared/{share_token}"
    return {
        "ok": True,
        "data": {"report_id": report_id, "share_token": share_token, "share_url": share_url},
    }


# ─── 定时推送（保留占位） ────────────────────────────────────────────────────

@router.post("/reports/{report_id}/schedule")
async def configure_schedule(report_id: str, body: ScheduleConfigUpdate) -> dict[str, Any]:
    """配置定时推送 — 保留占位"""
    schedule_config = {
        "cron": body.cron,
        "channels": body.channels,
        "recipients": body.recipients,
        "enabled": True,
        "configured_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"ok": True, "data": {"report_id": report_id, "schedule_config": schedule_config}}


@router.delete("/reports/{report_id}/schedule")
async def cancel_schedule(report_id: str) -> dict[str, Any]:
    """取消定时推送 — 保留占位"""
    return {"ok": True, "data": {"report_id": report_id, "schedule_config": None}}


# ─── AI叙事模板（保留内存实现，非关键路径） ──────────────────────────────────

@router.get("/narrative-templates")
async def list_narrative_templates() -> dict[str, Any]:
    """获取叙事模板列表"""
    built_in = list(MOCK_NARRATIVE_TEMPLATES)
    custom_tpls = [t for t in _custom_templates.values() if not t.get("is_deleted")]
    all_templates = built_in + custom_tpls
    return {"ok": True, "data": {"items": all_templates, "total": len(all_templates)}}


@router.post("/narrative-templates")
async def create_narrative_template(body: NarrativeTemplateCreate) -> dict[str, Any]:
    """创建叙事模板"""
    template_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    template: dict[str, Any] = {
        "id": template_id,
        "name": body.name,
        "brand_focus": body.brand_focus,
        "prompt_prefix": body.prompt_prefix,
        "metrics_weights": body.metrics_weights,
        "tone": body.tone,
        "is_default": body.is_default,
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    _custom_templates[template_id] = template
    logger.info("narrative_template_created", template_id=template_id, name=body.name)
    return {"ok": True, "data": template}


@router.put("/narrative-templates/{template_id}")
async def update_narrative_template(
    template_id: str, body: NarrativeTemplateUpdate,
) -> dict[str, Any]:
    """更新叙事模板"""
    for tpl in MOCK_NARRATIVE_TEMPLATES:
        if tpl["id"] == template_id:
            raise HTTPException(status_code=400, detail="内置模板不可修改，请创建自定义模板")

    template = _custom_templates.get(template_id)
    if template is None or template.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 不存在")

    update_fields = body.model_dump(exclude_none=True)
    template.update(update_fields)
    template["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("narrative_template_updated", template_id=template_id)
    return {"ok": True, "data": template}


@router.post("/narrative-templates/{template_id}/preview")
async def preview_narrative_template(template_id: str) -> dict[str, Any]:
    """预览叙事效果"""
    template: Optional[dict[str, Any]] = None
    for tpl in MOCK_NARRATIVE_TEMPLATES:
        if tpl["id"] == template_id:
            template = tpl
            break
    if template is None:
        template = _custom_templates.get(template_id)
    if template is None or (isinstance(template, dict) and template.get("is_deleted")):
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 不存在")

    mock_data: dict[str, Any] = {
        "revenue_fen": 2856000,
        "revenue_change_pct": 12.3,
        "gross_margin_pct": 48.6,
        "order_count": 142,
        "table_turn_rate": 2.8,
        "date": "2026-04-06",
    }
    narrative_text = _generate_narrative_preview(template, mock_data)

    return {
        "ok": True,
        "data": {
            "template_id": template_id,
            "template_name": template.get("name"),
            "brand_focus": template.get("brand_focus"),
            "tone": template.get("tone"),
            "narrative": narrative_text,
            "mock_data_used": mock_data,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _json_str(obj: Any) -> str:
    """将 Python 对象序列化为 JSON 字符串，供 ::jsonb 类型转换使用"""
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
