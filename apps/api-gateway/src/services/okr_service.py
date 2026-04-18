"""
OKR 服务 — 目标/关键结果/进度打卡/健康分/对齐
核心公式: objective.progress = sum(kr.progress_pct * kr.weight) / sum(kr.weight)
健康分: >=70 green / 40-70 yellow / <40 red
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.okr import KeyResult, Objective, OKRAlignment, OKRUpdate

logger = logging.getLogger(__name__)


class OKRService:
    """OKR 服务"""

    HEALTH_GREEN_THRESHOLD = 70.0
    HEALTH_YELLOW_THRESHOLD = 40.0

    # ─── 目标 ─────────────────────────────────────
    async def create_objective(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        title: str,
        period: str,
        owner_type: str = "personal",
        description: Optional[str] = None,
        parent_objective_id: Optional[str] = None,
        target_value: Optional[float] = None,
        weight: int = 100,
        store_id: Optional[str] = None,
    ) -> str:
        """新建目标，支持上下级目标树"""
        obj = Objective(
            id=uuid.uuid4(),
            owner_id=owner_id,
            owner_type=owner_type,
            title=title,
            description=description,
            period=period,
            parent_objective_id=parent_objective_id,
            target_value=Decimal(str(target_value)) if target_value is not None else None,
            weight=weight,
            status="draft",
            progress_pct=Decimal("0"),
            health="green",
            store_id=store_id,
        )
        db.add(obj)
        await db.flush()
        return str(obj.id)

    async def add_key_result(
        self,
        db: AsyncSession,
        *,
        objective_id: str,
        title: str,
        metric_type: str = "numeric",
        start_value: float = 0.0,
        target_value: float = 0.0,
        unit: Optional[str] = None,
        weight: int = 100,
        owner_id: Optional[str] = None,
    ) -> str:
        """新建 KR"""
        kr = KeyResult(
            id=uuid.uuid4(),
            objective_id=objective_id,
            title=title,
            metric_type=metric_type,
            start_value=Decimal(str(start_value)),
            target_value=Decimal(str(target_value)),
            current_value=Decimal(str(start_value)),
            unit=unit,
            weight=weight,
            owner_id=owner_id,
            status="active",
            progress_pct=Decimal("0"),
        )
        db.add(kr)
        await db.flush()
        return str(kr.id)

    # ─── 打卡更新 ────────────────────────────────
    async def update_progress(
        self,
        db: AsyncSession,
        *,
        kr_id: str,
        value: float,
        comment: Optional[str] = None,
        evidence_url: Optional[str] = None,
        updated_by: str,
    ) -> Dict[str, Any]:
        """KR 打卡更新，自动重算 Objective 进度和健康分"""
        kr = await db.get(KeyResult, uuid.UUID(kr_id) if isinstance(kr_id, str) else kr_id)
        if not kr:
            raise ValueError(f"KR {kr_id} not found")

        # 更新 current_value
        kr.current_value = Decimal(str(value))
        kr.progress_pct = self._calc_kr_progress(kr)
        if kr.progress_pct >= Decimal("100"):
            kr.status = "completed"

        # 写入 update 日志
        update = OKRUpdate(
            id=uuid.uuid4(),
            key_result_id=kr.id,
            value=Decimal(str(value)),
            comment=comment,
            evidence_url=evidence_url,
            updated_by=updated_by,
        )
        db.add(update)

        # 重算目标进度
        new_progress = await self.compute_objective_progress(db, str(kr.objective_id))
        health = self.health_check_by_progress(new_progress)
        await db.flush()
        return {
            "kr_id": str(kr.id),
            "kr_progress_pct": float(kr.progress_pct),
            "objective_progress_pct": new_progress,
            "health": health,
        }

    @staticmethod
    def _calc_kr_progress(kr: KeyResult) -> Decimal:
        """按 metric_type 计算单个 KR 进度百分比"""
        try:
            if kr.metric_type == "boolean":
                return Decimal("100") if float(kr.current_value) >= 1 else Decimal("0")
            if kr.metric_type == "milestone":
                # milestone 里程碑：current_value 直接存储 0-100
                v = max(0.0, min(100.0, float(kr.current_value)))
                return Decimal(str(round(v, 2)))
            target = float(kr.target_value or 0)
            start = float(kr.start_value or 0)
            cur = float(kr.current_value or 0)
            if target == start:
                return Decimal("100") if cur >= target else Decimal("0")
            pct = (cur - start) / (target - start) * 100.0
            pct = max(0.0, min(100.0, pct))
            return Decimal(str(round(pct, 2)))
        except Exception:
            return Decimal("0")

    # ─── 目标进度计算 ──────────────────────────────
    async def compute_objective_progress(self, db: AsyncSession, objective_id: str) -> float:
        """按 KR 加权平均算 Objective 进度"""
        result = await db.execute(
            select(KeyResult).where(KeyResult.objective_id == objective_id)
        )
        krs = result.scalars().all()
        if not krs:
            return 0.0
        total_weight = sum(int(kr.weight or 0) for kr in krs)
        if total_weight <= 0:
            return 0.0
        weighted = sum(float(kr.progress_pct or 0) * int(kr.weight or 0) for kr in krs)
        progress = round(weighted / total_weight, 2)

        obj = await db.get(Objective, uuid.UUID(objective_id) if isinstance(objective_id, str) else objective_id)
        if obj:
            obj.progress_pct = Decimal(str(progress))
            obj.health = self.health_check_by_progress(progress)
            if progress >= 100 and obj.status == "active":
                obj.status = "completed"
        return progress

    def health_check_by_progress(self, progress: float) -> str:
        """绿/黄/红判定"""
        if progress >= self.HEALTH_GREEN_THRESHOLD:
            return "green"
        if progress >= self.HEALTH_YELLOW_THRESHOLD:
            return "yellow"
        return "red"

    async def health_check(self, db: AsyncSession, objective_id: str) -> str:
        """单目标健康分"""
        progress = await self.compute_objective_progress(db, objective_id)
        return self.health_check_by_progress(progress)

    # ─── 对齐 ─────────────────────────────────────
    async def align(
        self,
        db: AsyncSession,
        *,
        parent_obj_id: str,
        child_obj_id: str,
        alignment_type: str = "contribute_to",
        notes: Optional[str] = None,
    ) -> str:
        align = OKRAlignment(
            id=uuid.uuid4(),
            parent_objective_id=parent_obj_id,
            child_objective_id=child_obj_id,
            alignment_type=alignment_type,
            notes=notes,
        )
        db.add(align)
        await db.flush()
        return str(align.id)

    # ─── 查询 ─────────────────────────────────────
    async def get_my_okr(
        self, db: AsyncSession, *, owner_id: str, period: str
    ) -> List[Dict[str, Any]]:
        """我的 OKR 列表（目标 + KR）"""
        result = await db.execute(
            select(Objective).where(
                Objective.owner_id == owner_id,
                Objective.period == period,
            )
        )
        objectives = result.scalars().all()
        out: List[Dict[str, Any]] = []
        for obj in objectives:
            kr_result = await db.execute(
                select(KeyResult).where(KeyResult.objective_id == obj.id)
            )
            krs = kr_result.scalars().all()
            out.append(
                {
                    "id": str(obj.id),
                    "title": obj.title,
                    "period": obj.period,
                    "status": obj.status,
                    "progress_pct": float(obj.progress_pct or 0),
                    "health": obj.health,
                    "weight": obj.weight,
                    "key_results": [
                        {
                            "id": str(k.id),
                            "title": k.title,
                            "metric_type": k.metric_type,
                            "start_value": float(k.start_value or 0),
                            "target_value": float(k.target_value or 0),
                            "current_value": float(k.current_value or 0),
                            "unit": k.unit,
                            "weight": k.weight,
                            "progress_pct": float(k.progress_pct or 0),
                            "status": k.status,
                        }
                        for k in krs
                    ],
                }
            )
        return out

    async def get_team_okr_tree(
        self, db: AsyncSession, *, manager_id: str, period: str
    ) -> Dict[str, Any]:
        """团队目标树 — 以 manager 的目标为根，递归下钻对齐的子目标"""
        # 取 manager 所有目标
        result = await db.execute(
            select(Objective).where(
                Objective.owner_id == manager_id,
                Objective.period == period,
            )
        )
        roots = result.scalars().all()

        async def _expand(obj: Objective) -> Dict[str, Any]:
            # 通过 parent_objective_id 向下找孩子
            child_result = await db.execute(
                select(Objective).where(
                    Objective.parent_objective_id == obj.id,
                    Objective.period == period,
                )
            )
            children = child_result.scalars().all()
            # 通过 alignments 找关联子目标
            align_result = await db.execute(
                select(OKRAlignment).where(OKRAlignment.parent_objective_id == obj.id)
            )
            aligned_ids = [str(a.child_objective_id) for a in align_result.scalars().all()]

            node = {
                "id": str(obj.id),
                "title": obj.title,
                "owner_id": obj.owner_id,
                "owner_type": obj.owner_type,
                "progress_pct": float(obj.progress_pct or 0),
                "health": obj.health,
                "aligned_child_ids": aligned_ids,
                "children": [await _expand(c) for c in children],
            }
            return node

        tree = [await _expand(r) for r in roots]
        return {"manager_id": manager_id, "period": period, "tree": tree}


okr_service = OKRService()
