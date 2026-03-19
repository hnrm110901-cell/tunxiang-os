"""
数据血缘查询 API

GET /api/v1/lineage/{output_id}
    — 从指定输出 ID 向上追溯完整血缘链（决策→食材成本→POS数据）

GET /api/v1/lineage/steps/{store_id}
    — 查看指定门店近期的血缘步骤（用于排查数据质量问题）
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_active_user, get_db
from ..models.user import User
from ..services.lineage_tracker import lineage_tracker

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/lineage", tags=["data_lineage"])


@router.get("/{output_id}")
async def get_lineage(
    output_id:  str,
    max_depth:  int  = Query(10, ge=1, le=20),
    db:         AsyncSession = Depends(get_db),
    _:          User         = Depends(get_current_active_user),
):
    """
    从 output_id 向上追溯完整数据血缘链。

    output_id 可以是任何已被 lineage_tracker.record 记录过的实体 ID，
    例如决策 ID、食材成本分析 ID 等。

    返回从最早祖先到当前节点的有序步骤列表。
    """
    chain = await lineage_tracker.get_lineage_chain(
        output_id=output_id, db=db, max_depth=max_depth
    )
    return {
        "output_id":  output_id,
        "depth":      len(chain),
        "chain":      chain,
    }


@router.get("/steps/{store_id}")
async def list_store_lineage_steps(
    store_id: str,
    step_name: Optional[str] = Query(None, description="过滤特定步骤，如 pos_ingest"),
    limit:     int = Query(50, ge=1, le=200),
    db:        AsyncSession = Depends(get_db),
    _:         User         = Depends(get_current_active_user),
):
    """
    列出门店近期的血缘追踪步骤，用于排查数据质量问题。
    """
    where = "WHERE store_id = :sid"
    params: dict = {"sid": store_id, "limit": limit}
    if step_name:
        where += " AND step_name = :step"
        params["step"] = step_name

    rows = (await db.execute(
        text(f"""
            SELECT transform_id, step_name, output_id, parent_ids,
                   input_summary, meta, recorded_at
            FROM data_lineage
            {where}
            ORDER BY recorded_at DESC
            LIMIT :limit
        """),
        params,
    )).fetchall()

    steps = [
        {
            "transform_id":  r[0],
            "step_name":     r[1],
            "output_id":     r[2],
            "parent_ids":    r[3] or [],
            "input_summary": r[4] or {},
            "meta":          r[5] or {},
            "recorded_at":   r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]
    return {"store_id": store_id, "steps": steps, "total": len(steps)}
