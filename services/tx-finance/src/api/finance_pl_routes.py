"""P&L 损益表 API 路由（v2 完整实现）

端点：
  GET  /api/v1/finance/pl/store?store_id=&start_date=&end_date=
       → 门店 P&L 损益表（完整格式）

  GET  /api/v1/finance/pl/brand?brand_id=&month=
       → 品牌级 P&L（多门店汇总）
"""
import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from services.tx_finance.src.services.pl_service import PLService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-pl"])

_pl_svc = PLService()


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD"
        ) from exc


def _validate_month(month: str) -> str:
    """验证 YYYY-MM 格式"""
    if len(month) != 7 or month[4] != "-":
        raise HTTPException(
            status_code=400, detail=f"month 格式错误: {month}，请使用 YYYY-MM"
        )
    try:
        int(month[:4])
        int(month[5:7])
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"month 格式错误: {month}"
        ) from exc
    return month


# ─── GET /pl/store ────────────────────────────────────────────────────────────

@router.get("/pl/store", summary="门店 P&L 损益表")
async def get_store_pl(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店 P&L 损益表（完整格式）

    损益表结构：
    营业收入
      - 堂食收入
      - 外卖收入
      - 储值卡充值（收现）
      - 其他收入
    = 总营收

    营业成本
      - 食材成本（BOM计算，无数据时用30%估算）
      - 食材损耗
    = 食材总成本

    毛利 = 总营收 - 食材总成本
    毛利率

    经营费用
      - 人工成本（来自薪资表）
      - 房租（门店月配置 × 天数摊销）
      - 水电（门店月配置 × 天数摊销）
      - 其他固定费用

    经营利润 = 毛利 - 经营费用
    经营利润率
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start = _parse_date_param(start_date)
    end = _parse_date_param(end_date)

    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    max_days = 366
    if (end - start).days > max_days:
        raise HTTPException(
            status_code=400, detail=f"查询区间不能超过 {max_days} 天"
        )

    try:
        pl = await _pl_svc.get_store_pl(sid, start, end, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": pl.to_dict()}


# ─── GET /pl/brand ────────────────────────────────────────────────────────────

@router.get("/pl/brand", summary="品牌级 P&L（多门店汇总）")
async def get_brand_pl(
    brand_id: str = Query(..., description="品牌ID"),
    month: str = Query(..., description="月份 YYYY-MM"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """品牌级 P&L 损益表

    汇总品牌下所有激活门店的月度 P&L，按毛利率降序排列门店。
    适用场景：
    - 品牌运营总览
    - 门店间横向对标
    - 发现高成本门店

    返回：
    - summary: 品牌级汇总指标
    - cost_health: 整体成本健康度
    - store_details: 各门店明细（按毛利率降序）
    """
    _validate_month(month)
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    try:
        brand_pl = await _pl_svc.get_brand_pl(brand_id, month, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": brand_pl.to_dict()}
