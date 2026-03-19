"""
数据血缘追踪器（Data Lineage Tracker）

解决的问题：
  从 POS 原始数据 → 食材成本差异 → 决策推送，经过多个 service 计算步骤，
  但没有任何血缘追踪机制。出错时无法溯源，数据质量问题无法定位。

设计（轻量级）：
  - 每次关键计算生成一个 transform_id（UUID）
  - 记录：输入 IDs、输出 ID、步骤名称、时间戳、元数据
  - transform_id 作为"血缘令牌"在函数调用链中传递
  - 写入 data_lineage 表（异步，失败不阻塞主流程）

典型调用链：
  POS Webhook → adapter → lineage_tracker.record("pos_ingest", ...)
  → FoodCostService → lineage_tracker.record("food_cost_compute", parent=pos_id)
  → DecisionPriorityEngine → lineage_tracker.record("decision_rank", parent=fc_id)
  → WeChat Push → lineage_tracker.record("push_sent", parent=decision_id)

查询血缘：
  lineage_tracker.get_lineage_chain(output_id) → 完整因果链
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def new_transform_id() -> str:
    """生成一个新的血缘令牌（UUID hex）"""
    return uuid.uuid4().hex


class LineageTracker:
    """
    轻量数据血缘追踪器。

    设计为无状态单例，每次调用传入 db session。
    所有写入操作失败静默（不阻塞业务主流程）。
    """

    async def record(
        self,
        transform_id:  str,
        step_name:     str,
        store_id:      str,
        output_id:     str,
        db:            AsyncSession,
        parent_ids:    Optional[List[str]] = None,
        input_summary: Optional[Dict[str, Any]] = None,
        meta:          Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录一个数据变换步骤。

        Args:
            transform_id:  本步骤的血缘令牌
            step_name:     步骤名称（如 "pos_ingest" / "food_cost_compute"）
            store_id:      关联门店
            output_id:     本步骤输出的主实体 ID（如 decision_id）
            parent_ids:    上游步骤的 output_id 列表（构建有向无环图）
            input_summary: 输入数据摘要（不存原始数据，只存关键字段）
            meta:          附加元数据（版本、模型名等）
        """
        try:
            await db.execute(
                text("""
                    INSERT INTO data_lineage
                        (transform_id, step_name, store_id, output_id,
                         parent_ids, input_summary, meta, recorded_at)
                    VALUES
                        (:tid, :step, :sid, :oid,
                         :parent_ids::jsonb, :input_summary::jsonb, :meta::jsonb, :ts)
                    ON CONFLICT (transform_id) DO NOTHING
                """),
                {
                    "tid":          transform_id,
                    "step":         step_name,
                    "sid":          store_id,
                    "oid":          output_id,
                    "parent_ids":   __import__("json").dumps(parent_ids or []),
                    "input_summary":__import__("json").dumps(input_summary or {}),
                    "meta":         __import__("json").dumps(meta or {}),
                    "ts":           datetime.utcnow(),
                },
            )
            await db.commit()
        except Exception as exc:
            logger.debug("lineage.record_failed", step=step_name, error=str(exc))
            try:
                await db.rollback()
            except Exception:
                pass

    async def get_lineage_chain(
        self,
        output_id: str,
        db:        AsyncSession,
        max_depth: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        从 output_id 向上追溯完整血缘链（递归查 parent_ids）。

        Returns:
            list of step dicts, 从最早祖先到当前节点排列
        """
        visited: set = set()
        chain:   List[Dict] = []

        async def _fetch(oid: str, depth: int) -> None:
            if depth > max_depth or oid in visited:
                return
            visited.add(oid)
            try:
                rows = (await db.execute(
                    text("""
                        SELECT transform_id, step_name, store_id, output_id,
                               parent_ids, input_summary, meta, recorded_at
                        FROM data_lineage
                        WHERE output_id = :oid
                        ORDER BY recorded_at DESC
                        LIMIT 5
                    """),
                    {"oid": oid},
                )).fetchall()
            except Exception:
                return
            for r in rows:
                step = {
                    "transform_id":  r[0],
                    "step_name":     r[1],
                    "store_id":      r[2],
                    "output_id":     r[3],
                    "parent_ids":    r[4] or [],
                    "input_summary": r[5] or {},
                    "meta":          r[6] or {},
                    "recorded_at":   r[7].isoformat() if r[7] else None,
                }
                chain.append(step)
                for parent_id in (step["parent_ids"] or []):
                    await _fetch(parent_id, depth + 1)

        await _fetch(output_id, 0)
        # 按时间升序（祖先在前）
        chain.sort(key=lambda x: x["recorded_at"] or "")
        return chain


# 模块级单例
lineage_tracker = LineageTracker()
