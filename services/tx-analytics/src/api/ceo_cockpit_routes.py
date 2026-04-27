"""CEO今日经营驾驶舱 API 路由 — Sprint G6

端点列表：
  GET /api/v1/ceo-cockpit/{store_id}/today          — 单店今日驾驶舱(完整数据)
  GET /api/v1/ceo-cockpit/{store_id}/daypart         — 时段P&L明细
  GET /api/v1/ceo-cockpit/{store_id}/delivery-profit — 外卖真实利润
  GET /api/v1/ceo-cockpit/{store_id}/decisions       — AI决策卡片
  GET /api/v1/ceo-cockpit/{store_id}/anomalies       — 异常高亮
  GET /api/v1/ceo-cockpit/{store_id}/month-progress  — 月度进度
  GET /api/v1/ceo-cockpit/overview                   — 多店概览(总部)

鉴权：X-Tenant-ID header 必填
响应格式：{ "ok": bool, "data": {}, "error": {} }
"""

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.ceo_cockpit_service import CEOCockpitService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/ceo-cockpit", tags=["ceo-cockpit"])

_svc = CEOCockpitService()


# ─── 公共辅助 ───────────────────────────────────────────


def _require_tenant(tenant_id: Optional[str]) -> str:
    """校验 X-Tenant-ID header 必填"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _get_db():
    """获取数据库会话

    实际项目中由 FastAPI Depends 注入。
    这里返回 None 作为占位，服务层会安全降级。
    """
    return None


# ─── 1. 单店今日驾驶舱（完整数据） ───────────────────────────


@router.get("/{store_id}/today")
async def api_ceo_cockpit_today(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """单店今日经营驾驶舱 -- CEO打开看到的完整画面

    返回数据包含：
    - overview: 营业额/成本/利润/客数/翻台率/客单价
    - daypart_pnl: 午市/下午茶/晚市/夜宵 各时段P&L
    - delivery_profit: 外卖真实利润（扣佣金/包装/补贴）
    - top_dishes: TOP5利润菜
    - loss_dishes: 亏损菜列表
    - ai_decisions: AI决策卡片（最多3条）
    - anomalies: 异常高亮（vs上周同日偏离）
    - month_progress: 月度目标进度
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info("api_ceo_cockpit_today", store_id=store_id, tenant_id=tenant_id)

    db = _get_db()
    try:
        data = await _svc.get_today_cockpit(db=db, store_id=store_id, tenant_id=tenant_id)
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_today.error", store_id=store_id, exc_info=True)
        _ = exc
        return {
            "ok": False,
            "data": {},
            "error": {"code": "DB_ERROR", "message": "数据库查询失败，请稍后重试"},
        }


# ─── 2. 时段P&L明细 ─────────────────────────────────────


@router.get("/{store_id}/daypart")
async def api_ceo_cockpit_daypart(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """时段P&L明细

    返回午市/下午茶/晚市/夜宵四个时段的独立P&L：
    - 营业额/食材成本/人力成本（按排班工时分摊）/利润
    - 盈亏平衡客数
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info("api_ceo_cockpit_daypart", store_id=store_id, tenant_id=tenant_id)

    db = _get_db()
    today = date.today()
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        ) if db else None

        data = await _svc._compute_daypart_pnl(
            db=db, store_id=store_id, tenant_id=tenant_id, target_date=today
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_daypart.error", store_id=store_id, exc_info=True)
        _ = exc
        return {
            "ok": False,
            "data": {"dayparts": []},
            "error": {"code": "DB_ERROR", "message": "时段P&L查询失败"},
        }


# ─── 3. 外卖真实利润 ────────────────────────────────────


@router.get("/{store_id}/delivery-profit")
async def api_ceo_cockpit_delivery_profit(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """外卖真实利润

    按渠道(美团/饿了么/抖音)分别统计：
    - 营业额/食材成本/平台佣金/包装费/满减补贴/真实利润/单均利润
    - 佣金费率：美团18% / 饿了么20% / 抖音10%
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info("api_ceo_cockpit_delivery_profit", store_id=store_id, tenant_id=tenant_id)

    db = _get_db()
    today = date.today()
    try:
        if db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )

        data = await _svc._compute_delivery_real_profit(
            db=db, store_id=store_id, tenant_id=tenant_id, target_date=today
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error(
            "api_ceo_cockpit_delivery_profit.error",
            store_id=store_id,
            exc_info=True,
        )
        _ = exc
        return {
            "ok": False,
            "data": {"total": {}, "by_channel": []},
            "error": {"code": "DB_ERROR", "message": "外卖利润查询失败"},
        }


# ─── 4. AI决策卡片 ──────────────────────────────────────


@router.get("/{store_id}/decisions")
async def api_ceo_cockpit_decisions(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """AI决策卡片

    最多3条，按优先级排序：
    1. 亏损菜干预
    2. 采购紧急（库存<2天）
    3. VIP客户召回（>30天未消费）
    4. 损耗告警（>8%）
    5. 外卖亏损

    每条包含: action_type / severity / title / description / action_label
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info("api_ceo_cockpit_decisions", store_id=store_id, tenant_id=tenant_id)

    db = _get_db()
    today = date.today()
    try:
        if db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )

        data = await _svc._generate_ai_decisions(
            db=db, store_id=store_id, tenant_id=tenant_id, target_date=today
        )
        return {"ok": True, "data": {"decisions": data, "count": len(data)}}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_decisions.error", store_id=store_id, exc_info=True)
        _ = exc
        return {
            "ok": False,
            "data": {"decisions": [], "count": 0},
            "error": {"code": "DB_ERROR", "message": "AI决策查询失败"},
        }


# ─── 5. 异常高亮 ────────────────────────────────────────


@router.get("/{store_id}/anomalies")
async def api_ceo_cockpit_anomalies(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """异常高亮

    对比今日 vs 上周同日（weekday对齐），只返回偏离的指标：
    - 偏离 +/-20%: warning（标黄）
    - 偏离 +/-35%: critical（标红）
    - 正常范围内的指标不返回

    检测项: 营业额/客数/翻台率/客单价/退菜率/损耗率
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info("api_ceo_cockpit_anomalies", store_id=store_id, tenant_id=tenant_id)

    db = _get_db()
    today = date.today()
    try:
        if db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )

        data = await _svc._detect_anomalies(
            db=db, store_id=store_id, tenant_id=tenant_id, target_date=today
        )
        return {
            "ok": True,
            "data": {
                "anomalies": data,
                "count": len(data),
                "has_critical": any(a["severity"] == "critical" for a in data),
            },
        }
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_anomalies.error", store_id=store_id, exc_info=True)
        _ = exc
        return {
            "ok": False,
            "data": {"anomalies": [], "count": 0, "has_critical": False},
            "error": {"code": "DB_ERROR", "message": "异常检测查询失败"},
        }


# ─── 6. 月度进度 ────────────────────────────────────────


@router.get("/{store_id}/month-progress")
async def api_ceo_cockpit_month_progress(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """月度目标进度条

    返回：
    - 月度目标 vs 实际进度
    - 日期进度 vs 营收进度（判断ahead/on_track/behind）
    - 如果behind，分析拖后腿的日期
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info("api_ceo_cockpit_month_progress", store_id=store_id, tenant_id=tenant_id)

    db = _get_db()
    today = date.today()
    try:
        if db:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )

        data = await _svc._compute_month_progress(
            db=db, store_id=store_id, tenant_id=tenant_id, target_date=today
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error(
            "api_ceo_cockpit_month_progress.error",
            store_id=store_id,
            exc_info=True,
        )
        _ = exc
        return {
            "ok": False,
            "data": {},
            "error": {"code": "DB_ERROR", "message": "月度进度查询失败"},
        }


# ─── 7. 多店概览（总部视角） ─────────────────────────────


@router.get("/overview")
async def api_ceo_cockpit_overview(
    brand_id: Optional[str] = Query(
        default=None,
        description="品牌ID（可选，不传返回全部门店）",
    ),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """多店概览（总部视角）

    汇总所有门店的今日经营数据：
    - summary: 总营收/总利润/总客数/门店数/失血门店数
    - stores: 门店排行（按营收降序）
    - bleeding_stores: 利润为负的门店列表
    """
    tenant_id = _require_tenant(x_tenant_id)
    log.info(
        "api_ceo_cockpit_overview",
        tenant_id=tenant_id,
        brand_id=brand_id,
    )

    db = _get_db()
    try:
        data = await _svc.get_multi_store_cockpit(
            db=db, tenant_id=tenant_id, brand_id=brand_id
        )
        return {"ok": True, "data": data}
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("api_ceo_cockpit_overview.error", tenant_id=tenant_id, exc_info=True)
        _ = exc
        return {
            "ok": False,
            "data": {"summary": {}, "stores": [], "bleeding_stores": []},
            "error": {"code": "DB_ERROR", "message": "多店概览查询失败"},
        }
