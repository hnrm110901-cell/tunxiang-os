"""反馈 -> 记忆进化闭环（Phase S4）

信号采集 -> 聚合分析 -> 偏好推断 -> 记忆更新 -> 个性化排序 -> 继续采集

示例闭环：
- 店长连续5天展开"成本分析"板块 -> 推断偏好"关注成本控制"
- 记忆写入(category=cost_focus, importance=0.8)
- 下次推送自动将成本分析提前
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_memory import AgentMemory
from ..models.feedback_signal import MemoryFeedbackSignal

logger = structlog.get_logger(__name__)

# ── 偏好推断阈值 ──
_WEAK_PREFERENCE_DAYS = 3    # 连续3天 -> 弱偏好(confidence=0.7)
_STRONG_PREFERENCE_DAYS = 5  # 连续5天 -> 强偏好(confidence=0.9)

# ── 信号分类映射 ──
_ACTION_TO_CATEGORY: dict[str, str] = {
    # 成本相关
    "expanded_cost_detail": "cost_control",
    "clicked_cost_analysis": "cost_control",
    "viewed_food_cost_rate": "cost_control",
    "checked_ingredient_price": "cost_control",
    # 营收相关
    "expanded_revenue_detail": "revenue_focus",
    "viewed_revenue_trend": "revenue_focus",
    "clicked_revenue_breakdown": "revenue_focus",
    # 效率相关
    "viewed_table_turnover": "serve_speed",
    "checked_serve_time": "serve_speed",
    "expanded_efficiency_detail": "serve_speed",
    # 会员相关
    "viewed_member_stats": "member_engagement",
    "clicked_member_detail": "member_engagement",
    "checked_retention_rate": "member_engagement",
    # 库存相关
    "viewed_inventory_alert": "inventory_management",
    "checked_waste_report": "inventory_management",
    # 食安相关
    "viewed_safety_score": "food_safety",
    "checked_temperature_log": "food_safety",
}

# ── 指标名称映射 ──
_ACTION_TO_METRIC: dict[str, str] = {
    "expanded_cost_detail": "food_cost_rate",
    "clicked_cost_analysis": "food_cost_rate",
    "viewed_food_cost_rate": "food_cost_rate",
    "viewed_revenue_trend": "daily_revenue",
    "expanded_revenue_detail": "daily_revenue",
    "viewed_table_turnover": "table_turnover",
    "checked_serve_time": "avg_serve_time",
    "viewed_member_stats": "member_count",
    "checked_retention_rate": "retention_rate",
    "viewed_inventory_alert": "inventory_alert_count",
    "checked_waste_report": "waste_rate",
    "viewed_safety_score": "safety_score",
}


class FeedbackEvolutionService:
    """反馈信号采集与记忆进化服务"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ══════════════════════════════════════════════════════════════
    # 信号采集
    # ══════════════════════════════════════════════════════════════

    async def record_signal(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
        signal_type: str,
        source: str,
        signal_data: dict,
        *,
        source_id: str | None = None,
    ) -> str:
        """记录一个反馈信号

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            user_id: 用户ID
            signal_type: 信号类型 (click/dismiss/dwell/feedback/override)
            source: 来源 (im_card/dashboard/coaching/sop_task)
            signal_data: 信号数据 (如 {"action": "expanded_cost_detail", "duration_sec": 45})
            source_id: 关联的卡片/任务/建议ID

        Returns:
            新建信号的 ID 字符串
        """
        # 校验信号类型
        valid_types = {"click", "dismiss", "dwell", "feedback", "override"}
        if signal_type not in valid_types:
            raise ValueError(f"signal_type 必须是 {valid_types} 之一，收到: {signal_type}")

        valid_sources = {"im_card", "dashboard", "coaching", "sop_task"}
        if source not in valid_sources:
            raise ValueError(f"source 必须是 {valid_sources} 之一，收到: {source}")

        signal = MemoryFeedbackSignal(
            tenant_id=UUID(tenant_id),
            store_id=UUID(store_id),
            user_id=UUID(user_id),
            signal_type=signal_type,
            source=source,
            source_id=UUID(source_id) if source_id else None,
            signal_data=signal_data,
        )
        self.db.add(signal)
        await self.db.flush()

        logger.info(
            "feedback_signal.recorded",
            signal_id=str(signal.id),
            signal_type=signal_type,
            source=source,
            user_id=user_id,
        )
        return str(signal.id)

    # ══════════════════════════════════════════════════════════════
    # 信号分析
    # ══════════════════════════════════════════════════════════════

    async def analyze_user_signals(
        self,
        tenant_id: str,
        user_id: str,
        *,
        days: int = 7,
    ) -> dict:
        """分析用户近N天的信号模式

        Returns:
            {
                total_signals: int,
                top_actions: [{action, count, avg_dwell_sec}],
                preferred_metrics: [str],
                feedback_sentiment: {helpful: int, not_helpful: int, ignored: int},
                inferred_preferences: [{category, confidence, evidence_count}],
            }
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(MemoryFeedbackSignal)
            .where(
                MemoryFeedbackSignal.tenant_id == UUID(tenant_id),
                MemoryFeedbackSignal.user_id == UUID(user_id),
                MemoryFeedbackSignal.created_at >= cutoff,
            )
            .order_by(MemoryFeedbackSignal.created_at.desc())
        )
        result = await self.db.execute(stmt)
        signals = list(result.scalars().all())

        if not signals:
            return {
                "total_signals": 0,
                "top_actions": [],
                "preferred_metrics": [],
                "feedback_sentiment": {"helpful": 0, "not_helpful": 0, "ignored": 0},
                "inferred_preferences": [],
            }

        # 信号列表转字典
        signal_dicts = [
            {
                "signal_type": s.signal_type,
                "source": s.source,
                "signal_data": s.signal_data,
                "created_at": s.created_at,
            }
            for s in signals
        ]

        # 1. 统计动作频次 + 平均停留时间
        action_counter: Counter = Counter()
        action_dwell: dict[str, list[float]] = defaultdict(list)

        for s in signal_dicts:
            action = s["signal_data"].get("action", "unknown")
            action_counter[action] += 1
            dwell = s["signal_data"].get("duration_sec")
            if dwell is not None:
                action_dwell[action].append(float(dwell))

        top_actions = []
        for action, count in action_counter.most_common(10):
            dwells = action_dwell.get(action, [])
            avg_dwell = round(sum(dwells) / len(dwells), 1) if dwells else 0.0
            top_actions.append({
                "action": action,
                "count": count,
                "avg_dwell_sec": avg_dwell,
            })

        # 2. 最常关注的指标
        metric_counter: Counter = Counter()
        for action, count in action_counter.items():
            metric = _ACTION_TO_METRIC.get(action)
            if metric:
                metric_counter[metric] += count
        preferred_metrics = [m for m, _ in metric_counter.most_common(5)]

        # 3. 反馈情感统计
        sentiment = {"helpful": 0, "not_helpful": 0, "ignored": 0}
        for s in signal_dicts:
            if s["signal_type"] == "feedback":
                fb = s["signal_data"].get("feedback", "")
                if fb == "helpful":
                    sentiment["helpful"] += 1
                elif fb == "not_helpful":
                    sentiment["not_helpful"] += 1
                else:
                    sentiment["ignored"] += 1

        # 4. 推断偏好
        inferred = self._infer_preferences(signal_dicts)

        return {
            "total_signals": len(signals),
            "top_actions": top_actions,
            "preferred_metrics": preferred_metrics,
            "feedback_sentiment": sentiment,
            "inferred_preferences": inferred,
        }

    # ══════════════════════════════════════════════════════════════
    # 记忆进化（批处理）
    # ══════════════════════════════════════════════════════════════

    async def evolve_memories(self, tenant_id: str) -> dict:
        """每日记忆进化批处理

        1. 获取所有用户的近7天信号
        2. 聚合分析：哪些用户对哪些内容有明确偏好
        3. 推断偏好 -> 调用 MemoryEvolutionService.remember()
        4. 更新已有记忆的 importance（信号强化/弱化）

        Returns:
            {users_analyzed: int, memories_created: int, memories_updated: int}
        """
        from .memory_evolution_service import MemoryEvolutionService

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        tid = UUID(tenant_id)

        # 1. 获取近7天所有用户的信号
        stmt = (
            select(
                MemoryFeedbackSignal.user_id,
                MemoryFeedbackSignal.store_id,
            )
            .where(
                MemoryFeedbackSignal.tenant_id == tid,
                MemoryFeedbackSignal.created_at >= cutoff,
            )
            .distinct()
        )
        result = await self.db.execute(stmt)
        user_store_pairs = list(result.all())

        if not user_store_pairs:
            logger.info("evolve_memories.no_signals", tenant_id=tenant_id)
            return {"users_analyzed": 0, "memories_created": 0, "memories_updated": 0}

        mem_svc = MemoryEvolutionService(self.db)
        memories_created = 0
        memories_updated = 0
        users_analyzed = 0

        # 按用户分组处理
        user_ids_seen: set[str] = set()
        for user_id, store_id in user_store_pairs:
            uid_str = str(user_id)
            sid_str = str(store_id)

            if uid_str not in user_ids_seen:
                users_analyzed += 1
                user_ids_seen.add(uid_str)

            # 获取该用户该门店的信号
            sig_stmt = (
                select(MemoryFeedbackSignal)
                .where(
                    MemoryFeedbackSignal.tenant_id == tid,
                    MemoryFeedbackSignal.user_id == user_id,
                    MemoryFeedbackSignal.store_id == store_id,
                    MemoryFeedbackSignal.created_at >= cutoff,
                )
                .order_by(MemoryFeedbackSignal.created_at.desc())
            )
            sig_result = await self.db.execute(sig_stmt)
            user_signals = list(sig_result.scalars().all())

            signal_dicts = [
                {
                    "signal_type": s.signal_type,
                    "source": s.source,
                    "signal_data": s.signal_data,
                    "created_at": s.created_at,
                }
                for s in user_signals
            ]

            # 推断偏好
            preferences = self._infer_preferences(signal_dicts)

            for pref in preferences:
                if pref["confidence"] < 0.6:
                    continue  # 跳过低置信度偏好

                content = (
                    f"用户偏好: {pref['category']} "
                    f"(类型={pref['preference_type']}, "
                    f"置信度={pref['confidence']}, "
                    f"证据={pref['evidence_count']}次)"
                )

                # 检查是否已有同类偏好记忆
                existing_stmt = (
                    select(AgentMemory)
                    .where(
                        AgentMemory.tenant_id == tid,
                        AgentMemory.user_id == user_id,
                        AgentMemory.category == pref["category"],
                        AgentMemory.memory_type == "preference",
                        AgentMemory.is_deleted == False,  # noqa: E712
                    )
                    .limit(1)
                )
                existing_result = await self.db.execute(existing_stmt)
                existing_memory = existing_result.scalars().first()

                if existing_memory:
                    # 强化/弱化已有记忆
                    old_importance = existing_memory.importance
                    if pref["preference_type"] == "positive":
                        existing_memory.importance = min(
                            1.0, old_importance + 0.1 * pref["confidence"]
                        )
                    elif pref["preference_type"] == "negative":
                        existing_memory.importance = max(
                            0.0, old_importance - 0.1 * pref["confidence"]
                        )
                    # 重置 confidence（被重新验证）
                    existing_memory.confidence = min(1.0, existing_memory.confidence + 0.05)
                    memories_updated += 1
                    logger.info(
                        "evolve_memories.memory_updated",
                        memory_id=str(existing_memory.id),
                        category=pref["category"],
                        old_importance=old_importance,
                        new_importance=existing_memory.importance,
                    )
                else:
                    # 创建新偏好记忆
                    importance = 0.8 if pref["confidence"] >= 0.9 else 0.6
                    await mem_svc.remember(
                        tenant_id=tenant_id,
                        store_id=sid_str,
                        user_id=uid_str,
                        content=content,
                        memory_type="preference",
                        category=pref["category"],
                        agent_id="feedback_evolution",
                        source_event="feedback_signal_analysis",
                        importance=importance,
                    )
                    memories_created += 1
                    logger.info(
                        "evolve_memories.memory_created",
                        user_id=uid_str,
                        category=pref["category"],
                        confidence=pref["confidence"],
                    )

        await self.db.flush()

        logger.info(
            "evolve_memories.done",
            tenant_id=tenant_id,
            users_analyzed=users_analyzed,
            memories_created=memories_created,
            memories_updated=memories_updated,
        )
        return {
            "users_analyzed": users_analyzed,
            "memories_created": memories_created,
            "memories_updated": memories_updated,
        }

    # ══════════════════════════════════════════════════════════════
    # 个性化上下文
    # ══════════════════════════════════════════════════════════════

    async def get_personalization_context(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str,
    ) -> dict:
        """获取个性化上下文（供AI Coach使用）

        结合用户记忆 + 近期信号，返回个性化配置：
        {
            focus_areas: ["cost_control", "serve_speed"],
            preferred_detail_level: "high",
            alert_sensitivity: "high",
            favorite_metrics: ["food_cost_rate", "table_turnover"],
            avoid_topics: [],
        }
        """
        tid = UUID(tenant_id)
        uid = UUID(user_id)
        sid = UUID(store_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)

        # 1. 获取用户偏好记忆
        mem_stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.tenant_id == tid,
                AgentMemory.user_id == uid,
                AgentMemory.memory_type == "preference",
                AgentMemory.is_deleted == False,  # noqa: E712
            )
            .order_by(AgentMemory.importance.desc())
            .limit(20)
        )
        mem_result = await self.db.execute(mem_stmt)
        memories = list(mem_result.scalars().all())

        # 2. 获取近14天信号
        sig_stmt = (
            select(MemoryFeedbackSignal)
            .where(
                MemoryFeedbackSignal.tenant_id == tid,
                MemoryFeedbackSignal.user_id == uid,
                MemoryFeedbackSignal.store_id == sid,
                MemoryFeedbackSignal.created_at >= cutoff,
            )
            .order_by(MemoryFeedbackSignal.created_at.desc())
            .limit(200)
        )
        sig_result = await self.db.execute(sig_stmt)
        signals = list(sig_result.scalars().all())

        # 3. 提取关注领域（从记忆的 category）
        focus_areas: list[str] = []
        for m in memories:
            cat = m.category
            if cat and cat not in focus_areas:
                focus_areas.append(cat)

        # 4. 推断详情偏好级别
        dwell_times = [
            s.signal_data.get("duration_sec", 0)
            for s in signals
            if s.signal_type == "dwell" and s.signal_data.get("duration_sec")
        ]
        avg_dwell = sum(dwell_times) / len(dwell_times) if dwell_times else 0
        if avg_dwell > 30:
            preferred_detail_level = "high"
        elif avg_dwell > 15:
            preferred_detail_level = "medium"
        else:
            preferred_detail_level = "low"

        # 5. 推断报警敏感度
        click_count = sum(1 for s in signals if s.signal_type == "click")
        dismiss_count = sum(1 for s in signals if s.signal_type == "dismiss")
        total_interactions = click_count + dismiss_count
        if total_interactions == 0:
            alert_sensitivity = "medium"
        elif dismiss_count / total_interactions > 0.5:
            alert_sensitivity = "low"  # 频繁dismiss -> 降低灵敏度
        elif click_count / total_interactions > 0.7:
            alert_sensitivity = "high"  # 积极点击 -> 提高灵敏度
        else:
            alert_sensitivity = "medium"

        # 6. 最爱指标（从信号动作推断）
        metric_counter: Counter = Counter()
        for s in signals:
            action = s.signal_data.get("action", "")
            metric = _ACTION_TO_METRIC.get(action)
            if metric:
                metric_counter[metric] += 1
        favorite_metrics = [m for m, _ in metric_counter.most_common(5)]

        # 7. 回避主题（被频繁dismiss的类别）
        dismiss_categories: Counter = Counter()
        for s in signals:
            if s.signal_type == "dismiss":
                action = s.signal_data.get("action", "")
                cat = _ACTION_TO_CATEGORY.get(action)
                if cat:
                    dismiss_categories[cat] += 1
        avoid_topics = [
            cat for cat, count in dismiss_categories.items()
            if count >= 3  # 3次以上dismiss才回避
        ]

        context = {
            "focus_areas": focus_areas[:5],  # 最多5个
            "preferred_detail_level": preferred_detail_level,
            "alert_sensitivity": alert_sensitivity,
            "favorite_metrics": favorite_metrics,
            "avoid_topics": avoid_topics,
        }

        logger.info(
            "personalization_context.generated",
            tenant_id=tenant_id,
            user_id=user_id,
            store_id=store_id,
            focus_areas=len(context["focus_areas"]),
            favorite_metrics=len(context["favorite_metrics"]),
        )
        return context

    # ══════════════════════════════════════════════════════════════
    # 信号列表
    # ══════════════════════════════════════════════════════════════

    async def list_signals(
        self,
        tenant_id: str,
        store_id: str,
        *,
        user_id: str | None = None,
        signal_type: str | None = None,
        days: int = 7,
        page: int = 1,
        size: int = 50,
    ) -> dict:
        """列出信号记录

        Returns:
            {"items": [...], "total": int, "page": int, "size": int}
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        # 基础条件
        conditions = [
            MemoryFeedbackSignal.tenant_id == tid,
            MemoryFeedbackSignal.store_id == sid,
            MemoryFeedbackSignal.created_at >= cutoff,
        ]
        if user_id:
            conditions.append(MemoryFeedbackSignal.user_id == UUID(user_id))
        if signal_type:
            conditions.append(MemoryFeedbackSignal.signal_type == signal_type)

        # 计数
        count_stmt = (
            select(func.count())
            .select_from(MemoryFeedbackSignal)
            .where(*conditions)
        )
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * size
        data_stmt = (
            select(MemoryFeedbackSignal)
            .where(*conditions)
            .order_by(MemoryFeedbackSignal.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        data_result = await self.db.execute(data_stmt)
        signals = list(data_result.scalars().all())

        items = [
            {
                "id": str(s.id),
                "store_id": str(s.store_id),
                "user_id": str(s.user_id),
                "signal_type": s.signal_type,
                "source": s.source,
                "source_id": str(s.source_id) if s.source_id else None,
                "signal_data": s.signal_data,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in signals
        ]

        return {"items": items, "total": total, "page": page, "size": size}

    # ══════════════════════════════════════════════════════════════
    # 进化统计
    # ══════════════════════════════════════════════════════════════

    async def get_evolution_stats(self, tenant_id: str) -> dict:
        """获取记忆进化统计

        Returns:
            {
                total_signals: int,
                active_users: int,
                memories_evolved: int,
                last_evolution_at: str | None,
                signal_breakdown: {click: int, dismiss: int, ...},
            }
        """
        tid = UUID(tenant_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        # 总信号数（近30天）
        total_stmt = (
            select(func.count())
            .select_from(MemoryFeedbackSignal)
            .where(
                MemoryFeedbackSignal.tenant_id == tid,
                MemoryFeedbackSignal.created_at >= cutoff,
            )
        )
        total_result = await self.db.execute(total_stmt)
        total_signals = total_result.scalar() or 0

        # 活跃用户数（近30天有信号的用户）
        users_stmt = (
            select(func.count(MemoryFeedbackSignal.user_id.distinct()))
            .where(
                MemoryFeedbackSignal.tenant_id == tid,
                MemoryFeedbackSignal.created_at >= cutoff,
            )
        )
        users_result = await self.db.execute(users_stmt)
        active_users = users_result.scalar() or 0

        # 已进化记忆数（source_event=feedback_signal_analysis 的记忆）
        evolved_stmt = (
            select(func.count())
            .select_from(AgentMemory)
            .where(
                AgentMemory.tenant_id == tid,
                AgentMemory.source_event == "feedback_signal_analysis",
                AgentMemory.is_deleted == False,  # noqa: E712
            )
        )
        evolved_result = await self.db.execute(evolved_stmt)
        memories_evolved = evolved_result.scalar() or 0

        # 最后进化时间
        last_stmt = (
            select(AgentMemory.created_at)
            .where(
                AgentMemory.tenant_id == tid,
                AgentMemory.source_event == "feedback_signal_analysis",
            )
            .order_by(AgentMemory.created_at.desc())
            .limit(1)
        )
        last_result = await self.db.execute(last_stmt)
        last_row = last_result.scalar()
        last_evolution_at = last_row.isoformat() if last_row else None

        # 信号类型分布
        breakdown_stmt = (
            select(
                MemoryFeedbackSignal.signal_type,
                func.count().label("count"),
            )
            .where(
                MemoryFeedbackSignal.tenant_id == tid,
                MemoryFeedbackSignal.created_at >= cutoff,
            )
            .group_by(MemoryFeedbackSignal.signal_type)
        )
        breakdown_result = await self.db.execute(breakdown_stmt)
        signal_breakdown = {
            row.signal_type: row.count
            for row in breakdown_result
        }

        return {
            "total_signals": total_signals,
            "active_users": active_users,
            "memories_evolved": memories_evolved,
            "last_evolution_at": last_evolution_at,
            "signal_breakdown": signal_breakdown,
        }

    # ══════════════════════════════════════════════════════════════
    # 偏好推断引擎（纯函数）
    # ══════════════════════════════════════════════════════════════

    def _infer_preferences(self, signals: list[dict]) -> list[dict]:
        """从信号列表推断偏好

        规则：
        - 连续3天以上点击同类内容 -> 推断偏好(confidence=0.7)
        - 连续5天以上 -> 强偏好(confidence=0.9)
        - feedback=helpful -> 强化
        - feedback=not_helpful -> 弱化
        - dismiss -> 负信号

        Args:
            signals: [{"signal_type", "source", "signal_data", "created_at"}]

        Returns:
            [{category, preference_type, confidence, evidence_count}]
        """
        if not signals:
            return []

        # 按类别统计每天的信号
        category_daily: dict[str, set[str]] = defaultdict(set)  # category -> set of date_str
        category_counts: Counter = Counter()
        category_positive: Counter = Counter()
        category_negative: Counter = Counter()

        for s in signals:
            signal_type = s["signal_type"]
            data = s.get("signal_data", {})
            action = data.get("action", "")
            created_at = s.get("created_at")

            # 解析日期
            if isinstance(created_at, datetime):
                date_str = created_at.strftime("%Y-%m-%d")
            elif isinstance(created_at, str):
                date_str = created_at[:10]
            else:
                continue

            # 映射到类别
            category = _ACTION_TO_CATEGORY.get(action)
            if not category and signal_type == "feedback":
                # feedback信号可能有category字段
                category = data.get("category")

            if not category:
                continue

            if signal_type in ("click", "dwell"):
                category_daily[category].add(date_str)
                category_counts[category] += 1
                category_positive[category] += 1
            elif signal_type == "feedback":
                fb = data.get("feedback", "")
                if fb == "helpful":
                    category_positive[category] += 2  # feedback 权重更高
                    category_daily[category].add(date_str)
                elif fb == "not_helpful":
                    category_negative[category] += 2
            elif signal_type == "dismiss":
                category_negative[category] += 1
            elif signal_type == "override":
                category_negative[category] += 1  # 用户覆盖 = 负信号

        # 推断偏好
        preferences: list[dict] = []
        all_categories = set(category_daily.keys()) | set(category_negative.keys())

        for category in all_categories:
            active_days = len(category_daily.get(category, set()))
            positive = category_positive.get(category, 0)
            negative = category_negative.get(category, 0)
            total = positive + negative

            if total == 0:
                continue

            # 判断偏好方向
            if positive > negative:
                preference_type = "positive"
                # 置信度基于连续天数
                if active_days >= _STRONG_PREFERENCE_DAYS:
                    confidence = 0.9
                elif active_days >= _WEAK_PREFERENCE_DAYS:
                    confidence = 0.7
                else:
                    confidence = 0.5
                # 正面反馈加成
                helpful_count = sum(
                    1 for s in signals
                    if s.get("signal_data", {}).get("feedback") == "helpful"
                    and _ACTION_TO_CATEGORY.get(
                        s.get("signal_data", {}).get("action", "")
                    ) == category
                )
                if helpful_count > 0:
                    confidence = min(1.0, confidence + 0.05 * helpful_count)
            elif negative > positive * 2:
                preference_type = "negative"
                confidence = min(0.9, 0.5 + negative * 0.05)
            else:
                continue  # 信号不明确，跳过

            preferences.append({
                "category": category,
                "preference_type": preference_type,
                "confidence": round(confidence, 2),
                "evidence_count": total,
            })

        # 按置信度排序
        preferences.sort(key=lambda p: p["confidence"], reverse=True)
        return preferences
