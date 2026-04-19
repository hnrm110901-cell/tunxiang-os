"""情报->增长自动接力服务 — 从发现机会到执行动作的闭环

Intel Hub 发现市场机会后，自动创建增长活动草稿；
Growth Hub 试点结果反馈到 Intel 模型，形成数据闭环。

数据持久化：opportunity_relays + pilot_feedbacks 表（v258 迁移）。
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger()


# ---- 数据模型 ----


class OpportunityRelay(BaseModel):
    """情报机会 -> 增长活动草稿"""

    relay_id: str = Field(default_factory=lambda: f"relay-{uuid.uuid4().hex[:8]}")
    opportunity_id: str
    opportunity_type: str  # 新品机会 / 竞对防御 / 需求趋势 / 原料机会
    opportunity_title: str
    opportunity_score: float  # 0-100

    campaign_draft_id: Optional[str] = None
    campaign_type: Optional[str] = None  # 新品推广 / 价格防御 / 趋势跟进 / 裂变活动
    campaign_title: Optional[str] = None
    suggested_actions: list[str] = Field(default_factory=list)

    status: str = "pending"  # pending / draft_created / approved / executing / completed / rejected
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PilotFeedback(BaseModel):
    """增长试点结果 -> 情报模型反馈"""

    feedback_id: str = Field(default_factory=lambda: f"fb-{uuid.uuid4().hex[:6]}")
    pilot_id: str
    relay_id: str
    results: dict  # 试点结果数据
    metrics: dict  # 关键指标
    intel_model_updated: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---- 内部 DB 工具函数 ----


async def _get_session(tenant_id: str) -> AsyncSession:
    """获取设置了 RLS tenant_id 的数据库会话（调用方负责关闭）。"""
    session = async_session_factory()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    return session


async def _row_to_relay(row) -> dict:
    """将数据库行映射为 relay dict。"""
    return {
        "relay_id": row["relay_id"],
        "opportunity_id": row["opportunity_id"],
        "opportunity_type": row["opportunity_type"],
        "opportunity_title": row["opportunity_title"],
        "opportunity_score": float(row["opportunity_score"]),
        "campaign_draft_id": row["campaign_draft_id"],
        "campaign_type": row["campaign_type"],
        "campaign_title": row["campaign_title"],
        "suggested_actions": row["suggested_actions"] or [],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
    }


async def _row_to_feedback(row) -> dict:
    """将数据库行映射为 feedback dict。"""
    return {
        "feedback_id": row["feedback_id"],
        "pilot_id": row["pilot_id"],
        "relay_id": row["relay_id"],
        "results": row["results"] or {},
        "metrics": row["metrics"] or {},
        "intel_model_updated": bool(row["intel_model_updated"]),
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
    }


# ---- 接力服务 ----


class GrowthIntelRelayService:
    """情报->增长自动接力 — 从发现机会到执行动作的闭环"""

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    async def relay_opportunity_to_campaign(self, opportunity_id: str) -> dict:
        """Intel 发现机会 -> 自动创建增长活动草稿

        流程:
        1. 从 opportunity_relays 查找已有接力记录
        2. 根据机会类型匹配活动模板
        3. 生成活动草稿（含渠道/券/内容建议）
        4. 写入接力记录
        """
        session = await _get_session(self._tenant_id)
        try:
            # 查找已有接力记录
            result = await session.execute(
                text("""
                    SELECT * FROM opportunity_relays
                    WHERE opportunity_id = :opp_id
                      AND is_deleted = false
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"opp_id": opportunity_id},
            )
            existing_row = result.mappings().one_or_none()

            if existing_row and existing_row["status"] != "pending":
                relay = await _row_to_relay(existing_row)
                logger.info("relay_already_exists", relay_id=relay["relay_id"], status=relay["status"])
                return relay

            campaign_type_map = {
                "新品机会": "新品推广",
                "竞对防御": "价格防御",
                "需求趋势": "趋势跟进",
                "原料机会": "新品推广",
            }

            now = datetime.now(timezone.utc)

            if existing_row:
                relay_id = existing_row["relay_id"]
                opp_type = existing_row["opportunity_type"]
                opp_title = existing_row["opportunity_title"]
                opp_score = float(existing_row["opportunity_score"])
            else:
                relay_id = f"relay-{uuid.uuid4().hex[:8]}"
                opp_type = "新品机会"
                opp_title = f"机会 {opportunity_id}"
                opp_score = 70.0

            campaign_draft_id = f"camp-draft-{uuid.uuid4().hex[:6]}"
            campaign_type = campaign_type_map.get(opp_type, "趋势跟进")
            suggested_actions = [
                "选择试点门店",
                "配置目标人群和触达渠道",
                "设置权益和优惠券",
                "启动A/B测试",
            ]

            if existing_row:
                # 更新已有记录
                await session.execute(
                    text("""
                        UPDATE opportunity_relays SET
                            campaign_draft_id = :campaign_draft_id,
                            campaign_type = :campaign_type,
                            campaign_title = :campaign_title,
                            suggested_actions = :suggested_actions::jsonb,
                            status = 'draft_created',
                            updated_at = :now
                        WHERE relay_id = :relay_id
                    """),
                    {
                        "campaign_draft_id": campaign_draft_id,
                        "campaign_type": campaign_type,
                        "campaign_title": f"[自动草稿] {opp_title} 推广活动",
                        "suggested_actions": str(suggested_actions).replace("'", '"'),
                        "now": now,
                        "relay_id": relay_id,
                    },
                )
            else:
                # 插入新记录
                import json

                await session.execute(
                    text("""
                        INSERT INTO opportunity_relays (
                            tenant_id, relay_id, opportunity_id, opportunity_type,
                            opportunity_title, opportunity_score, campaign_draft_id,
                            campaign_type, campaign_title, suggested_actions, status,
                            created_at, updated_at
                        ) VALUES (
                            :tenant_id::uuid, :relay_id, :opportunity_id, :opportunity_type,
                            :opportunity_title, :opportunity_score, :campaign_draft_id,
                            :campaign_type, :campaign_title, :suggested_actions::jsonb,
                            'draft_created', :now, :now
                        )
                    """),
                    {
                        "tenant_id": self._tenant_id,
                        "relay_id": relay_id,
                        "opportunity_id": opportunity_id,
                        "opportunity_type": opp_type,
                        "opportunity_title": opp_title,
                        "opportunity_score": opp_score,
                        "campaign_draft_id": campaign_draft_id,
                        "campaign_type": campaign_type,
                        "campaign_title": f"[自动草稿] {opp_title} 推广活动",
                        "suggested_actions": json.dumps(suggested_actions, ensure_ascii=False),
                        "now": now,
                    },
                )

            await session.commit()

            relay = {
                "relay_id": relay_id,
                "opportunity_id": opportunity_id,
                "opportunity_type": opp_type,
                "opportunity_title": opp_title,
                "opportunity_score": opp_score,
                "campaign_draft_id": campaign_draft_id,
                "campaign_type": campaign_type,
                "campaign_title": f"[自动草稿] {opp_title} 推广活动",
                "suggested_actions": suggested_actions,
                "status": "draft_created",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }

            logger.info(
                "relay_created", relay_id=relay_id, opportunity_id=opportunity_id, campaign_draft_id=campaign_draft_id
            )
            return relay

        except SQLAlchemyError as exc:
            await session.rollback()
            logger.error("relay_opportunity_to_campaign_failed", opportunity_id=opportunity_id, error=str(exc))
            raise
        finally:
            await session.close()

    async def relay_pilot_result_to_intel(self, pilot_id: str, results: dict) -> dict:
        """Growth 试点结果 -> 反馈到 Intel 模型

        流程:
        1. 接收试点结果数据
        2. 计算关键指标
        3. 更新 Intel 模型的机会评分（opportunity_relays.status = completed）
        4. 记录 pilot_feedbacks
        """
        import json

        session = await _get_session(self._tenant_id)
        try:
            # 通过 pilot_id 在 campaign_draft_id 中匹配接力记录
            result = await session.execute(
                text("""
                    SELECT relay_id FROM opportunity_relays
                    WHERE campaign_draft_id LIKE :pilot_pattern
                      AND is_deleted = false
                    LIMIT 1
                """),
                {"pilot_pattern": f"%{pilot_id}%"},
            )
            relay_row = result.mappings().one_or_none()
            relay_id = relay_row["relay_id"] if relay_row else "unknown"

            metrics = {
                "achievement_rate": results.get("achievement_rate", 0),
                "repeat_order_rate": results.get("repeat_order_rate", 0),
                "avg_ticket_size": results.get("avg_ticket_size", 0),
                "gross_margin": results.get("gross_margin", 0),
            }

            feedback_id = f"fb-{uuid.uuid4().hex[:6]}"
            now = datetime.now(timezone.utc)

            await session.execute(
                text("""
                    INSERT INTO pilot_feedbacks (
                        tenant_id, feedback_id, pilot_id, relay_id,
                        results, metrics, intel_model_updated, created_at
                    ) VALUES (
                        :tenant_id::uuid, :feedback_id, :pilot_id, :relay_id,
                        :results::jsonb, :metrics::jsonb, true, :now
                    )
                """),
                {
                    "tenant_id": self._tenant_id,
                    "feedback_id": feedback_id,
                    "pilot_id": pilot_id,
                    "relay_id": relay_id,
                    "results": json.dumps(results, ensure_ascii=False),
                    "metrics": json.dumps(metrics, ensure_ascii=False),
                    "now": now,
                },
            )

            # 更新接力记录状态
            if relay_id != "unknown":
                await session.execute(
                    text("""
                        UPDATE opportunity_relays
                        SET status = 'completed', updated_at = :now
                        WHERE relay_id = :relay_id
                    """),
                    {"relay_id": relay_id, "now": now},
                )

            await session.commit()

            feedback = {
                "feedback_id": feedback_id,
                "pilot_id": pilot_id,
                "relay_id": relay_id,
                "results": results,
                "metrics": metrics,
                "intel_model_updated": True,
                "created_at": now.isoformat(),
            }

            logger.info("pilot_feedback_recorded", feedback_id=feedback_id, pilot_id=pilot_id, relay_id=relay_id)
            return feedback

        except SQLAlchemyError as exc:
            await session.rollback()
            logger.error("relay_pilot_result_failed", pilot_id=pilot_id, error=str(exc))
            raise
        finally:
            await session.close()

    async def get_relay_history(self) -> list[dict]:
        """获取所有接力记录历史（按 created_at 倒序）"""
        session = await _get_session(self._tenant_id)
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM opportunity_relays
                    WHERE is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 500
                """)
            )
            rows = result.mappings().all()
            return [await _row_to_relay(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error("get_relay_history_failed", error=str(exc))
            return []
        finally:
            await session.close()

    async def get_active_relays(self) -> list[dict]:
        """获取活跃接力记录（非终态）"""
        session = await _get_session(self._tenant_id)
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM opportunity_relays
                    WHERE status IN ('pending', 'draft_created', 'approved', 'executing')
                      AND is_deleted = false
                    ORDER BY created_at DESC
                """)
            )
            rows = result.mappings().all()
            return [await _row_to_relay(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error("get_active_relays_failed", error=str(exc))
            return []
        finally:
            await session.close()

    async def get_feedbacks(self) -> list[dict]:
        """获取所有试点反馈（按 created_at 倒序）"""
        session = await _get_session(self._tenant_id)
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM pilot_feedbacks
                    WHERE is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 500
                """)
            )
            rows = result.mappings().all()
            return [await _row_to_feedback(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error("get_feedbacks_failed", error=str(exc))
            return []
        finally:
            await session.close()

    async def get_relay_stats(self) -> dict:
        """获取接力统计"""
        session = await _get_session(self._tenant_id)
        try:
            result = await session.execute(
                text("""
                    SELECT
                        COUNT(*)                                              AS total_relays,
                        COUNT(*) FILTER (WHERE status IN (
                            'pending','draft_created','approved','executing')) AS active_relays,
                        COUNT(*) FILTER (WHERE status = 'completed')          AS completed_relays,
                        COUNT(*) FILTER (WHERE status = 'rejected')           AS rejected_relays
                    FROM opportunity_relays
                    WHERE is_deleted = false
                """)
            )
            row = result.mappings().one_or_none()

            fb_result = await session.execute(
                text("SELECT COUNT(*) AS total_feedbacks FROM pilot_feedbacks WHERE is_deleted = false")
            )
            fb_row = fb_result.mappings().one_or_none()

            by_status_result = await session.execute(
                text("""
                    SELECT status, COUNT(*) AS cnt
                    FROM opportunity_relays WHERE is_deleted = false
                    GROUP BY status
                """)
            )
            by_status = {r["status"]: int(r["cnt"]) for r in by_status_result.mappings().all()}

            return {
                "total_relays": int(row["total_relays"]) if row else 0,
                "active_relays": int(row["active_relays"]) if row else 0,
                "completed_relays": int(row["completed_relays"]) if row else 0,
                "rejected_relays": int(row["rejected_relays"]) if row else 0,
                "total_feedbacks": int(fb_row["total_feedbacks"]) if fb_row else 0,
                "by_status": by_status,
            }
        except SQLAlchemyError as exc:
            logger.error("get_relay_stats_failed", error=str(exc))
            return {
                "total_relays": 0,
                "active_relays": 0,
                "completed_relays": 0,
                "rejected_relays": 0,
                "total_feedbacks": 0,
                "by_status": {},
            }
        finally:
            await session.close()


# ---- FastAPI 路由 ----

from fastapi import APIRouter, Header

router = APIRouter(prefix="/api/v1/growth-intel-relay", tags=["growth-intel-relay"])


def _svc(tenant_id: str) -> GrowthIntelRelayService:
    return GrowthIntelRelayService(tenant_id)


@router.get("/relays")
async def list_relays(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出所有接力记录"""
    svc = _svc(x_tenant_id)
    items = await svc.get_relay_history()
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.get("/relays/active")
async def list_active_relays(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出活跃接力记录"""
    svc = _svc(x_tenant_id)
    active = await svc.get_active_relays()
    return {"ok": True, "data": {"items": active, "total": len(active)}}


@router.post("/relays/create")
async def create_relay(
    opportunity_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """从情报机会创建增长活动草稿"""
    svc = _svc(x_tenant_id)
    relay = await svc.relay_opportunity_to_campaign(opportunity_id)
    return {"ok": True, "data": relay}


@router.post("/feedbacks/create")
async def create_feedback(
    pilot_id: str,
    results: dict,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录试点结果反馈"""
    svc = _svc(x_tenant_id)
    feedback = await svc.relay_pilot_result_to_intel(pilot_id, results)
    return {"ok": True, "data": feedback}


@router.get("/feedbacks")
async def list_feedbacks(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出所有试点反馈"""
    svc = _svc(x_tenant_id)
    feedbacks = await svc.get_feedbacks()
    return {"ok": True, "data": {"items": feedbacks, "total": len(feedbacks)}}


@router.get("/stats")
async def relay_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """接力统计"""
    svc = _svc(x_tenant_id)
    return {"ok": True, "data": await svc.get_relay_stats()}
