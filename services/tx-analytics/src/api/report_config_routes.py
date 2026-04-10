"""
自定义报表框架路由

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
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/analytics", tags=["custom-reports"])

# ─── Mock数据 ────────────────────────────────────────────────────────────────

STANDARD_REPORTS: list[dict[str, Any]] = [
    {
        "id": "std-001",
        "name": "日营业汇总",
        "description": "按门店/日期汇总营业额、订单数、客单价",
        "report_type": "standard",
        "data_source": "orders",
        "chart_type": "bar",
        "is_favorite": True,
        "is_public": False,
        "dimensions": [
            {"field": "store_id", "label": "门店", "type": "dimension"},
            {"field": "date", "label": "日期", "type": "dimension"},
        ],
        "metrics": [
            {"field": "revenue_fen", "label": "营业额", "agg": "sum"},
            {"field": "order_count", "label": "订单数", "agg": "count"},
        ],
        "filters": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": "std-002",
        "name": "会员消费分析",
        "description": "按会员等级/城市分析消费行为",
        "report_type": "standard",
        "data_source": "members",
        "chart_type": "pie",
        "is_favorite": False,
        "is_public": False,
        "dimensions": [
            {"field": "member_level", "label": "会员等级", "type": "dimension"},
            {"field": "city", "label": "城市", "type": "dimension"},
        ],
        "metrics": [
            {"field": "consume_amount_fen", "label": "消费金额", "agg": "sum"},
            {"field": "visit_count", "label": "到店次数", "agg": "sum"},
        ],
        "filters": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": "std-003",
        "name": "菜品销售排行",
        "description": "菜品销量/销售额排行榜",
        "report_type": "standard",
        "data_source": "orders",
        "chart_type": "table",
        "is_favorite": True,
        "is_public": False,
        "dimensions": [
            {"field": "dish_name", "label": "菜品名称", "type": "dimension"},
            {"field": "category", "label": "分类", "type": "dimension"},
        ],
        "metrics": [
            {"field": "quantity", "label": "销量", "agg": "sum"},
            {"field": "revenue_fen", "label": "销售额", "agg": "sum"},
        ],
        "filters": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": "std-004",
        "name": "员工绩效汇总",
        "description": "服务员/收银员绩效数据汇总",
        "report_type": "standard",
        "data_source": "employees",
        "chart_type": "table",
        "is_favorite": False,
        "is_public": False,
        "dimensions": [
            {"field": "employee_name", "label": "员工姓名", "type": "dimension"},
            {"field": "role", "label": "角色", "type": "dimension"},
        ],
        "metrics": [
            {"field": "service_count", "label": "服务桌数", "agg": "sum"},
            {"field": "tips_fen", "label": "小费", "agg": "sum"},
        ],
        "filters": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": "std-005",
        "name": "食材成本报表",
        "description": "按品类/供应商分析食材采购成本",
        "report_type": "standard",
        "data_source": "inventory",
        "chart_type": "line",
        "is_favorite": False,
        "is_public": False,
        "dimensions": [
            {"field": "category", "label": "品类", "type": "dimension"},
            {"field": "supplier", "label": "供应商", "type": "dimension"},
        ],
        "metrics": [
            {"field": "cost_fen", "label": "成本金额", "agg": "sum"},
            {"field": "waste_rate", "label": "损耗率", "agg": "avg"},
        ],
        "filters": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    },
]

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

# 自定义报表内存存储（mock，生产环境接数据库）
_custom_reports: dict[str, dict[str, Any]] = {}
_custom_executions: dict[str, dict[str, Any]] = {}
_custom_templates: dict[str, dict[str, Any]] = {}

# ─── 各数据源的可选字段 ──────────────────────────────────────────────────────

DATA_SOURCE_FIELDS: dict[str, dict[str, list[dict[str, str]]]] = {
    "orders": {
        "dimensions": [
            {"field": "store_id", "label": "门店", "type": "string"},
            {"field": "date", "label": "日期", "type": "date"},
            {"field": "payment_method", "label": "支付方式", "type": "string"},
            {"field": "channel", "label": "渠道", "type": "string"},
            {"field": "dish_name", "label": "菜品名称", "type": "string"},
            {"field": "category", "label": "菜品分类", "type": "string"},
        ],
        "metrics": [
            {"field": "revenue_fen", "label": "营业额(分)", "agg_options": ["sum", "avg"]},
            {"field": "order_count", "label": "订单数", "agg_options": ["count", "sum"]},
            {"field": "avg_order_fen", "label": "客单价(分)", "agg_options": ["avg"]},
            {"field": "quantity", "label": "销量", "agg_options": ["sum"]},
            {"field": "discount_fen", "label": "优惠金额(分)", "agg_options": ["sum"]},
        ],
    },
    "members": {
        "dimensions": [
            {"field": "member_level", "label": "会员等级", "type": "string"},
            {"field": "city", "label": "城市", "type": "string"},
            {"field": "gender", "label": "性别", "type": "string"},
            {"field": "join_month", "label": "入会月份", "type": "date"},
        ],
        "metrics": [
            {"field": "consume_amount_fen", "label": "消费金额(分)", "agg_options": ["sum", "avg"]},
            {"field": "visit_count", "label": "到店次数", "agg_options": ["sum", "avg"]},
            {"field": "member_count", "label": "会员数", "agg_options": ["count"]},
            {"field": "rfm_score", "label": "RFM评分", "agg_options": ["avg"]},
        ],
    },
    "inventory": {
        "dimensions": [
            {"field": "category", "label": "品类", "type": "string"},
            {"field": "supplier", "label": "供应商", "type": "string"},
            {"field": "ingredient_name", "label": "食材名称", "type": "string"},
            {"field": "warehouse", "label": "仓库", "type": "string"},
        ],
        "metrics": [
            {"field": "cost_fen", "label": "成本金额(分)", "agg_options": ["sum"]},
            {"field": "waste_rate", "label": "损耗率(%)", "agg_options": ["avg"]},
            {"field": "turnover_days", "label": "周转天数", "agg_options": ["avg"]},
            {"field": "stock_count", "label": "库存数量", "agg_options": ["sum"]},
        ],
    },
    "employees": {
        "dimensions": [
            {"field": "employee_name", "label": "员工姓名", "type": "string"},
            {"field": "role", "label": "岗位角色", "type": "string"},
            {"field": "store_id", "label": "所属门店", "type": "string"},
            {"field": "department", "label": "部门", "type": "string"},
        ],
        "metrics": [
            {"field": "service_count", "label": "服务桌数", "agg_options": ["sum"]},
            {"field": "labor_efficiency", "label": "人效(元/人)", "agg_options": ["avg"]},
            {"field": "attendance_rate", "label": "出勤率(%)", "agg_options": ["avg"]},
            {"field": "tips_fen", "label": "小费(分)", "agg_options": ["sum"]},
        ],
    },
    "finance": {
        "dimensions": [
            {"field": "cost_center", "label": "成本中心", "type": "string"},
            {"field": "month", "label": "月份", "type": "date"},
            {"field": "store_id", "label": "门店", "type": "string"},
            {"field": "category", "label": "费用类别", "type": "string"},
        ],
        "metrics": [
            {"field": "revenue_fen", "label": "收入(分)", "agg_options": ["sum"]},
            {"field": "cost_fen", "label": "成本(分)", "agg_options": ["sum"]},
            {"field": "gross_profit_fen", "label": "毛利(分)", "agg_options": ["sum"]},
            {"field": "gross_margin_pct", "label": "毛利率(%)", "agg_options": ["avg"]},
        ],
    },
}

# ─── Mock执行数据生成 ────────────────────────────────────────────────────────

def _generate_mock_rows(data_source: str, row_limit: int = 10) -> list[dict[str, Any]]:
    """根据数据源生成mock数据行"""
    if data_source == "orders":
        return [
            {
                "store_id": f"门店{i:02d}",
                "date": f"2026-04-0{i % 6 + 1}",
                "revenue_fen": 28560_00 + i * 1234_00,
                "order_count": 120 + i * 5,
                "avg_order_fen": 238_00 + i * 10_00,
            }
            for i in range(1, min(row_limit + 1, 11))
        ]
    if data_source == "members":
        levels = ["普通会员", "银卡会员", "金卡会员", "钻石会员"]
        return [
            {
                "member_level": levels[i % 4],
                "city": ["长沙", "深圳", "北京", "上海"][i % 4],
                "member_count": 1200 - i * 80,
                "consume_amount_fen": 380_00 * (i + 1),
                "visit_count": 3 + i,
            }
            for i in range(min(row_limit, 8))
        ]
    if data_source == "inventory":
        categories = ["活鲜", "蔬菜", "肉类", "调料", "主食"]
        return [
            {
                "category": categories[i % 5],
                "supplier": f"供应商{chr(65 + i)}",
                "cost_fen": 45000_00 + i * 3200_00,
                "waste_rate": round(2.1 + i * 0.3, 1),
                "turnover_days": 3 + i,
            }
            for i in range(min(row_limit, 8))
        ]
    if data_source == "employees":
        roles = ["服务员", "收银员", "厨师", "领班", "经理"]
        return [
            {
                "employee_name": f"员工_{i:03d}",
                "role": roles[i % 5],
                "service_count": 18 + i * 2,
                "labor_efficiency": 320_00 + i * 15_00,
                "attendance_rate": round(96.5 - i * 0.5, 1),
            }
            for i in range(min(row_limit, 10))
        ]
    if data_source == "finance":
        return [
            {
                "cost_center": f"门店{i:02d}",
                "month": f"2026-0{i % 3 + 1}",
                "revenue_fen": 850000_00 + i * 50000_00,
                "cost_fen": 510000_00 + i * 30000_00,
                "gross_profit_fen": 340000_00 + i * 20000_00,
                "gross_margin_pct": round(40.0 - i * 0.5, 1),
            }
            for i in range(min(row_limit, 8))
        ]
    # 默认
    return [{"id": i, "value": i * 100} for i in range(min(row_limit, 10))]


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
    # professional/executive
    return (
        f"【{name}】今日整体经营表现良好。{focus}核心指标：营业额¥28,560（达成率102.3%），"
        f"毛利率48.6%，较上周同期提升1.8个百分点。"
        f"重点关注：会员到店率较昨日下降3.2%，建议营销团队跟进复购触达策略。"
    )


# ─── Pydantic 模型 ───────────────────────────────────────────────────────────

class ReportConfigCreate(BaseModel):
    name: str
    description: Optional[str] = None
    report_type: str = "custom"
    data_source: Optional[str] = None
    dimensions: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    filters: list[dict[str, Any]] = []
    sort_by: Optional[str] = None
    sort_order: str = "desc"
    chart_type: str = "table"
    is_public: bool = False


class ReportConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    data_source: Optional[str] = None
    dimensions: Optional[list[dict[str, Any]]] = None
    metrics: Optional[list[dict[str, Any]]] = None
    filters: Optional[list[dict[str, Any]]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
    chart_type: Optional[str] = None
    is_public: Optional[bool] = None


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


# ─── 报表配置 CRUD ────────────────────────────────────────────────────────────

@router.get("/reports")
async def list_reports(
    report_type: Optional[str] = Query(None, description="standard/custom/ai_narrative"),
    is_favorite: Optional[bool] = Query(None, description="仅显示收藏"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """获取报表列表（标准报表 + 自定义报表）"""
    all_reports: list[dict[str, Any]] = []

    # 标准报表
    if report_type is None or report_type == "standard":
        std = list(STANDARD_REPORTS)
        if is_favorite is True:
            std = [r for r in std if r.get("is_favorite")]
        all_reports.extend(std)

    # 自定义报表
    if report_type is None or report_type in ("custom", "ai_narrative"):
        custom = [
            r for r in _custom_reports.values()
            if not r.get("is_deleted")
            and (report_type is None or r.get("report_type") == report_type)
        ]
        if is_favorite is True:
            custom = [r for r in custom if r.get("is_favorite")]
        all_reports.extend(custom)

    total = len(all_reports)
    offset = (page - 1) * size
    items = all_reports[offset: offset + size]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/reports/shared/{share_token}")
async def get_shared_report(share_token: str) -> dict[str, Any]:
    """通过分享token查看报表（无需认证）"""
    # 在自定义报表中查找
    report: Optional[dict[str, Any]] = None
    for r in _custom_reports.values():
        if r.get("share_token") == share_token and r.get("is_public") and not r.get("is_deleted"):
            report = r
            break

    if report is None:
        raise HTTPException(status_code=404, detail="分享链接不存在或已失效")

    # 生成执行数据
    data_source = report.get("data_source", "orders")
    rows = _generate_mock_rows(data_source)

    return {
        "ok": True,
        "data": {
            "report": report,
            "rows": rows,
            "row_count": len(rows),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/reports/{report_id}")
async def get_report(report_id: str) -> dict[str, Any]:
    """获取报表详情"""
    # 先查标准报表
    for r in STANDARD_REPORTS:
        if r["id"] == report_id:
            return {"ok": True, "data": r}

    # 再查自定义报表
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    return {"ok": True, "data": report}


@router.post("/reports")
async def create_report(body: ReportConfigCreate) -> dict[str, Any]:
    """创建自定义报表配置"""
    import uuid
    report_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    report: dict[str, Any] = {
        "id": report_id,
        "name": body.name,
        "description": body.description,
        "report_type": body.report_type,
        "data_source": body.data_source,
        "dimensions": body.dimensions,
        "metrics": body.metrics,
        "filters": body.filters,
        "sort_by": body.sort_by,
        "sort_order": body.sort_order,
        "chart_type": body.chart_type,
        "is_public": body.is_public,
        "share_token": None,
        "schedule_config": None,
        "is_favorite": False,
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    _custom_reports[report_id] = report

    logger.info("report_config_created", report_id=report_id, name=body.name)
    return {"ok": True, "data": report}


@router.put("/reports/{report_id}")
async def update_report(report_id: str, body: ReportConfigUpdate) -> dict[str, Any]:
    """更新报表配置"""
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    update_fields = body.model_dump(exclude_none=True)
    report.update(update_fields)
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("report_config_updated", report_id=report_id, fields=list(update_fields.keys()))
    return {"ok": True, "data": report}


@router.delete("/reports/{report_id}")
async def delete_report(report_id: str) -> dict[str, Any]:
    """软删除报表"""
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    report["is_deleted"] = True
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("report_config_deleted", report_id=report_id)
    return {"ok": True, "data": {"deleted": True, "report_id": report_id}}


@router.post("/reports/{report_id}/favorite")
async def toggle_favorite(report_id: str) -> dict[str, Any]:
    """收藏/取消收藏报表"""
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    report["is_favorite"] = not report.get("is_favorite", False)
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    return {"ok": True, "data": {"report_id": report_id, "is_favorite": report["is_favorite"]}}


# ─── 报表执行与分享 ───────────────────────────────────────────────────────────

@router.post("/reports/{report_id}/execute")
async def execute_report(report_id: str) -> dict[str, Any]:
    """执行报表，返回数据行 + 执行记录"""
    import uuid

    # 查找报表（含标准报表）
    report: Optional[dict[str, Any]] = None
    for r in STANDARD_REPORTS:
        if r["id"] == report_id:
            report = r
            break
    if report is None:
        report = _custom_reports.get(report_id)
    if report is None or (isinstance(report, dict) and report.get("is_deleted")):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    start_ms = int(time.time() * 1000)

    data_source = report.get("data_source", "orders")
    rows = _generate_mock_rows(data_source)
    row_count = len(rows)

    end_ms = int(time.time() * 1000)
    execution_ms = max(1, end_ms - start_ms)

    execution_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    execution_record = {
        "id": execution_id,
        "report_id": report_id,
        "status": "completed",
        "row_count": row_count,
        "execution_ms": execution_ms,
        "error_msg": None,
        "created_at": now,
        "completed_at": now,
    }
    _custom_executions[execution_id] = execution_record

    logger.info("report_executed", report_id=report_id, row_count=row_count, execution_ms=execution_ms)

    return {
        "ok": True,
        "data": {
            "execution": execution_record,
            "rows": rows,
            "columns": _get_columns(report),
        },
    }


def _get_columns(report: dict[str, Any]) -> list[dict[str, str]]:
    """从报表配置提取列定义"""
    cols: list[dict[str, str]] = []
    for dim in report.get("dimensions", []):
        cols.append({"field": dim.get("field", ""), "label": dim.get("label", ""), "type": "dimension"})
    for metric in report.get("metrics", []):
        cols.append({"field": metric.get("field", ""), "label": metric.get("label", ""), "type": "metric"})
    return cols


@router.post("/reports/{report_id}/share")
async def generate_share_link(report_id: str) -> dict[str, Any]:
    """生成分享链接"""
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    # 生成64字符的hex token
    share_token = secrets.token_hex(32)  # token_hex(32) 产生64字符hex字符串
    share_url = f"https://admin.tunxiang.com/analytics/reports/shared/{share_token}"

    report["is_public"] = True
    report["share_token"] = share_token
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("report_share_link_created", report_id=report_id, share_token=share_token[:8] + "...")

    return {
        "ok": True,
        "data": {
            "report_id": report_id,
            "share_token": share_token,
            "share_url": share_url,
        },
    }


# ─── 定时推送 ─────────────────────────────────────────────────────────────────

@router.post("/reports/{report_id}/schedule")
async def configure_schedule(report_id: str, body: ScheduleConfigUpdate) -> dict[str, Any]:
    """配置定时推送"""
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    schedule_config = {
        "cron": body.cron,
        "channels": body.channels,
        "recipients": body.recipients,
        "enabled": True,
        "configured_at": datetime.now(timezone.utc).isoformat(),
    }
    report["schedule_config"] = schedule_config
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("report_schedule_configured", report_id=report_id, cron=body.cron)

    return {"ok": True, "data": {"report_id": report_id, "schedule_config": schedule_config}}


@router.delete("/reports/{report_id}/schedule")
async def cancel_schedule(report_id: str) -> dict[str, Any]:
    """取消定时推送"""
    report = _custom_reports.get(report_id)
    if report is None or report.get("is_deleted"):
        raise HTTPException(status_code=404, detail=f"报表 {report_id} 不存在")

    report["schedule_config"] = None
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("report_schedule_cancelled", report_id=report_id)

    return {"ok": True, "data": {"report_id": report_id, "schedule_config": None}}


# ─── AI叙事模板 ───────────────────────────────────────────────────────────────

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
    import uuid
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
    template_id: str, body: NarrativeTemplateUpdate
) -> dict[str, Any]:
    """更新叙事模板"""
    # 内置模板不可修改
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
    """预览叙事效果（用mock数据+模板生成示例叙事文本）"""
    # 查找模板（内置 + 自定义）
    template: Optional[dict[str, Any]] = None
    for tpl in MOCK_NARRATIVE_TEMPLATES:
        if tpl["id"] == template_id:
            template = tpl
            break
    if template is None:
        template = _custom_templates.get(template_id)
    if template is None or (isinstance(template, dict) and template.get("is_deleted")):
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 不存在")

    mock_data = {
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


# ─── 数据源字段查询（辅助端点） ───────────────────────────────────────────────

@router.get("/data-sources/{data_source}/fields")
async def get_data_source_fields(data_source: str) -> dict[str, Any]:
    """获取指定数据源的可选维度和指标字段"""
    fields = DATA_SOURCE_FIELDS.get(data_source)
    if fields is None:
        raise HTTPException(
            status_code=404,
            detail=f"数据源 {data_source} 不支持，可选：{list(DATA_SOURCE_FIELDS.keys())}",
        )
    return {"ok": True, "data": {"data_source": data_source, **fields}}
