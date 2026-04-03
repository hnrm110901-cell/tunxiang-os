"""营销活动 Repository — 内存 → DB 迁移（v097）

覆盖 campaign_engine.py 的三块内存存储：
  _campaigns             → campaigns
  _campaign_participants → campaign_participants
  _campaign_rewards      → campaign_rewards

设计说明：
  - stats 字段（participant_count/reward_count/spent_fen/total_cost_fen）
    用原子 UPDATE col = col + N 保证并发安全
  - check_eligibility 的参与次数限制通过 COUNT(campaign_participants) 实现
  - TriggerEngine 的活动匹配通过 campaign_type + status 索引查询实现
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 合法状态转换（与 campaign_engine.py 保持一致）
_VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["active"],
    "active": ["paused", "ended"],
    "paused": ["active", "ended"],
    "ended": [],
}


class CampaignRepository:
    """营销活动数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 活动 CRUD
    # ══════════════════════════════════════════════════════

    async def create_campaign(self, campaign_type: str, config: dict) -> dict:
        """创建营销活动（status=draft）"""
        await self._set_tenant()
        campaign_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await self.db.execute(
            text("""
                INSERT INTO campaigns
                    (id, tenant_id, campaign_type, name, description, status,
                     config, start_time, end_time, target_stores, target_segments,
                     budget_fen, ab_test_id, variants, created_at, updated_at)
                VALUES
                    (:id, :tid, :ctype, :name, :desc, 'draft',
                     :config::jsonb, :start_time, :end_time,
                     :stores::jsonb, :segments::jsonb,
                     :budget, :ab_test_id, :variants::jsonb, :now, :now)
            """),
            {
                "id": campaign_id,
                "tid": self._tid,
                "ctype": campaign_type,
                "name": config.get("name", f"{campaign_type}活动"),
                "desc": config.get("description", ""),
                "config": json.dumps(config),
                "start_time": config.get("start_time"),
                "end_time": config.get("end_time"),
                "stores": json.dumps(config.get("target_stores", [])),
                "segments": json.dumps(config.get("target_segments", [])),
                "budget": config.get("budget_fen", 0),
                "ab_test_id": uuid.UUID(config["ab_test_id"]) if config.get("ab_test_id") else None,
                "variants": json.dumps(config.get("variants")) if config.get("variants") else None,
                "now": now,
            },
        )
        await self.db.flush()
        log.info("campaign.created", campaign_id=str(campaign_id),
                 campaign_type=campaign_type, tenant_id=self.tenant_id)
        result = await self.get_campaign(str(campaign_id))
        return result  # type: ignore[return-value]

    async def get_campaign(self, campaign_id: str) -> Optional[dict]:
        """查询活动详情"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, campaign_type, name, description, status, config,
                       start_time, end_time, target_stores, target_segments,
                       budget_fen, spent_fen, ab_test_id, variants,
                       participant_count, reward_count, total_cost_fen, conversion_count,
                       created_at, updated_at
                FROM campaigns
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": uuid.UUID(campaign_id), "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    async def list_campaigns(self, status: Optional[str] = None) -> list[dict]:
        """列出租户活动"""
        await self._set_tenant()
        sql = """
            SELECT id, campaign_type, name, description, status, config,
                   start_time, end_time, target_stores, target_segments,
                   budget_fen, spent_fen, ab_test_id, variants,
                   participant_count, reward_count, total_cost_fen, conversion_count,
                   created_at, updated_at
            FROM campaigns
            WHERE tenant_id = :tid AND is_deleted = false
        """
        params: dict = {"tid": self._tid}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"

        result = await self.db.execute(text(sql), params)
        return [self._row_to_dict(r) for r in result.fetchall()]

    async def get_active_by_types(self, campaign_types: set[str]) -> list[dict]:
        """查询指定类型的活跃活动（供 TriggerEngine 使用）"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, campaign_type, name, status, config,
                       target_segments, budget_fen, spent_fen,
                       participant_count, ab_test_id, variants,
                       created_at, updated_at
                FROM campaigns
                WHERE tenant_id = :tid AND status = 'active'
                  AND campaign_type = ANY(:types)
                  AND is_deleted = false
            """),
            {"tid": self._tid, "types": list(campaign_types)},
        )
        return [self._row_to_dict(r) for r in result.fetchall()]

    # ══════════════════════════════════════════════════════
    # 状态转换
    # ══════════════════════════════════════════════════════

    async def transition_status(self, campaign_id: str, new_status: str) -> Optional[dict]:
        """状态转换（验证合法性后更新）"""
        await self._set_tenant()
        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return None

        current = campaign["status"]
        if new_status not in _VALID_TRANSITIONS.get(current, []):
            raise ValueError(f"活动状态 {current} 不允许转换为 {new_status}")

        await self.db.execute(
            text("""
                UPDATE campaigns
                SET status = :status, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid
            """),
            {"status": new_status, "id": uuid.UUID(campaign_id), "tid": self._tid},
        )
        await self.db.flush()
        return await self.get_campaign(campaign_id)

    # ══════════════════════════════════════════════════════
    # 参与次数限制
    # ══════════════════════════════════════════════════════

    async def count_customer_participations(
        self, campaign_id: str, customer_id: str
    ) -> int:
        """统计某客户在某活动的参与次数"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM campaign_participants
                WHERE tenant_id = :tid AND campaign_id = :cid AND customer_id = :uid
            """),
            {
                "tid": self._tid,
                "cid": uuid.UUID(campaign_id),
                "uid": uuid.UUID(customer_id),
            },
        )
        return result.scalar() or 0

    # ══════════════════════════════════════════════════════
    # 参与记录 & 奖励记录
    # ══════════════════════════════════════════════════════

    async def add_participation(
        self,
        campaign_id: str,
        customer_id: str,
        trigger_event: dict,
        reward: dict,
        ab_variant: Optional[str],
        reward_cost_fen: int,
    ) -> None:
        """写入参与记录 + 奖励记录 + 原子更新活动统计"""
        await self._set_tenant()
        cid = uuid.UUID(campaign_id)
        uid = uuid.UUID(customer_id)

        # 参与记录
        await self.db.execute(
            text("""
                INSERT INTO campaign_participants
                    (id, tenant_id, campaign_id, customer_id,
                     trigger_event, reward, ab_variant, participated_at)
                VALUES
                    (:id, :tid, :cid, :uid,
                     :event::jsonb, :reward::jsonb, :variant, NOW())
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "cid": cid,
                "uid": uid,
                "event": json.dumps(trigger_event),
                "reward": json.dumps(reward),
                "variant": ab_variant,
            },
        )

        # 奖励记录
        reward_type = reward.get("reward_type", "coupon")
        await self.db.execute(
            text("""
                INSERT INTO campaign_rewards
                    (id, tenant_id, campaign_id, customer_id,
                     reward_type, reward_data, cost_fen, status, granted_at)
                VALUES
                    (:id, :tid, :cid, :uid,
                     :rtype, :rdata::jsonb, :cost, 'granted', NOW())
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "cid": cid,
                "uid": uid,
                "rtype": reward_type,
                "rdata": json.dumps(reward),
                "cost": reward_cost_fen,
            },
        )

        # 原子更新统计
        await self.db.execute(
            text("""
                UPDATE campaigns
                SET participant_count = participant_count + 1,
                    reward_count      = reward_count + 1,
                    total_cost_fen    = total_cost_fen + :cost,
                    spent_fen         = spent_fen + :cost,
                    updated_at        = NOW()
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cost": reward_cost_fen, "cid": cid, "tid": self._tid},
        )
        await self.db.flush()

    # ══════════════════════════════════════════════════════
    # Analytics
    # ══════════════════════════════════════════════════════

    async def get_analytics(self, campaign_id: str) -> Optional[dict]:
        """获取活动效果分析（含奖励类型分组）"""
        await self._set_tenant()
        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return None

        # 奖励类型分组统计
        result = await self.db.execute(
            text("""
                SELECT reward_type, COUNT(*) AS cnt
                FROM campaign_rewards
                WHERE tenant_id = :tid AND campaign_id = :cid
                GROUP BY reward_type
            """),
            {"tid": self._tid, "cid": uuid.UUID(campaign_id)},
        )
        reward_breakdown = {r.reward_type: r.cnt for r in result.fetchall()}

        participant_count = campaign["participant_count"]
        total_cost_fen = campaign["total_cost_fen"]
        budget_fen = campaign["budget_fen"]

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign["name"],
            "campaign_type": campaign["campaign_type"],
            "status": campaign["status"],
            "participant_count": participant_count,
            "reward_count": campaign["reward_count"],
            "total_cost_fen": total_cost_fen,
            "total_cost_yuan": round(total_cost_fen / 100, 2),
            "budget_fen": budget_fen,
            "budget_usage": round(campaign["spent_fen"] / budget_fen, 4) if budget_fen > 0 else 0.0,
            "reward_breakdown": reward_breakdown,
            "avg_cost_per_participant_fen": total_cost_fen // max(1, participant_count),
        }

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    def _row_to_dict(self, row) -> dict:
        def _json(v):
            if v is None:
                return None
            return v if isinstance(v, (dict, list)) else json.loads(v)

        return {
            "campaign_id": str(row.id),
            "campaign_type": row.campaign_type,
            "tenant_id": self.tenant_id,
            "name": row.name,
            "description": getattr(row, "description", None),
            "status": row.status,
            "config": _json(row.config) or {},
            "start_time": row.start_time.isoformat() if row.start_time else None,
            "end_time": row.end_time.isoformat() if row.end_time else None,
            "target_stores": _json(getattr(row, "target_stores", None)) or [],
            "target_segments": _json(getattr(row, "target_segments", None)) or [],
            "budget_fen": row.budget_fen,
            "spent_fen": row.spent_fen,
            "ab_test_id": str(row.ab_test_id) if row.ab_test_id else None,
            "variants": _json(getattr(row, "variants", None)),
            "stats": {
                "participant_count": row.participant_count,
                "reward_count": row.reward_count,
                "total_cost_fen": row.total_cost_fen,
                "conversion_count": getattr(row, "conversion_count", 0),
            },
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
