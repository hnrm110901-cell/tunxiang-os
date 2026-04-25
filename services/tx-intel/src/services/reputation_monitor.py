"""AI舆情监控服务 — 负面口碑预警与危机响应

负责：
  - 基于滑动窗口检测负面口碑激增（spike detection）
  - 评分下降检测（rating drop）
  - 预警创建、确认、回应、升级、解决、驳回全流程
  - SLA响应时间追踪与合规报告
  - 预警仪表盘统计
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class ReputationMonitor:
    """舆情监控服务

    通过滑动窗口算法检测负面口碑激增，
    自动创建预警并调用 tx-brain 生成摘要与回应建议。
    """

    async def detect_negative_spike(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID | None,
        db: AsyncSession,
        time_window_minutes: int = 60,
    ) -> dict[str, Any] | None:
        """检测负面口碑激增

        算法：
          - 基线：过去7天负面提及的每小时平均数
          - 当前：过去 time_window_minutes 内的负面提及数
          - 若 current > 2 * baseline * (window/60)，则触发预警

        返回预警数据字典，若无激增返回 None。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id) if store_id else None,
            window_min=time_window_minutes,
        )

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 构建 store 过滤条件
        store_filter = ""
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "window_minutes": time_window_minutes,
        }
        if store_id:
            store_filter = " AND store_id = :store_id"
            params["store_id"] = str(store_id)

        # 1. 滚动基线：过去7天负面提及总数 / (7*24) = 每小时平均
        baseline_result = await db.execute(
            text(f"""
                SELECT COUNT(*)
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND sentiment = 'negative'
                  AND captured_at > NOW() - INTERVAL '7 days'
                  AND is_deleted = false
                  {store_filter}
            """),
            params,
        )
        baseline_total = int(baseline_result.scalar() or 0)
        baseline_per_hour = baseline_total / (7 * 24) if baseline_total > 0 else 0

        # 2. 当前窗口负面提及数
        current_result = await db.execute(
            text(f"""
                SELECT COUNT(*)
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND sentiment = 'negative'
                  AND captured_at > NOW() - INTERVAL '1 minute' * :window_minutes
                  AND is_deleted = false
                  {store_filter}
            """),
            params,
        )
        current_count = int(current_result.scalar() or 0)

        # 3. 判断是否激增
        expected = max(baseline_per_hour * (time_window_minutes / 60), 1)
        spike_ratio = current_count / expected

        log.info(
            "reputation_monitor.spike_check",
            baseline_per_hour=round(baseline_per_hour, 2),
            current_count=current_count,
            expected=round(expected, 2),
            spike_ratio=round(spike_ratio, 2),
        )

        if spike_ratio <= 2.0:
            return None

        # 4. 获取触发提及的 ID 列表
        mention_result = await db.execute(
            text(f"""
                SELECT id
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND sentiment = 'negative'
                  AND captured_at > NOW() - INTERVAL '1 minute' * :window_minutes
                  AND is_deleted = false
                  {store_filter}
                ORDER BY captured_at DESC
                LIMIT 50
            """),
            params,
        )
        mention_ids = [str(r[0]) for r in mention_result.fetchall()]

        # 5. 确定严重级别
        if spike_ratio >= 5.0:
            severity = "critical"
        elif spike_ratio >= 3.5:
            severity = "high"
        elif spike_ratio >= 2.5:
            severity = "medium"
        else:
            severity = "low"

        # 6. 确定主要平台
        platform_result = await db.execute(
            text(f"""
                SELECT platform, COUNT(*) as cnt
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND sentiment = 'negative'
                  AND captured_at > NOW() - INTERVAL '1 minute' * :window_minutes
                  AND is_deleted = false
                  {store_filter}
                GROUP BY platform
                ORDER BY cnt DESC
                LIMIT 1
            """),
            params,
        )
        platform_row = platform_result.fetchone()
        platform = str(platform_row[0]) if platform_row else "dianping"

        alert_data = {
            "store_id": str(store_id) if store_id else None,
            "platform": platform,
            "alert_type": "negative_spike",
            "severity": severity,
            "trigger_mention_ids": mention_ids,
            "trigger_data": {
                "negative_count": current_count,
                "baseline_count": round(baseline_per_hour, 2),
                "spike_ratio": round(spike_ratio, 2),
                "time_window_minutes": time_window_minutes,
            },
        }

        alert = await self.create_alert(tenant_id, alert_data, db)
        log.info(
            "reputation_monitor.spike_detected",
            alert_id=alert["alert_id"],
            severity=severity,
            spike_ratio=round(spike_ratio, 2),
        )
        return alert

    async def detect_rating_drop(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID | None,
        db: AsyncSession,
        drop_threshold: float = 0.3,
    ) -> dict[str, Any] | None:
        """检测评分下降

        比较近24小时平均评分 vs 近30天平均评分，
        若下降超过 drop_threshold，触发预警。
        """
        log = logger.bind(tenant_id=str(tenant_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        store_filter = ""
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if store_id:
            store_filter = " AND store_id = :store_id"
            params["store_id"] = str(store_id)

        # 近24h平均评分
        recent_result = await db.execute(
            text(f"""
                SELECT AVG(rating)
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND rating IS NOT NULL
                  AND captured_at > NOW() - INTERVAL '24 hours'
                  AND is_deleted = false
                  {store_filter}
            """),
            params,
        )
        recent_avg = recent_result.scalar()

        # 近30天平均评分
        monthly_result = await db.execute(
            text(f"""
                SELECT AVG(rating)
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND rating IS NOT NULL
                  AND captured_at > NOW() - INTERVAL '30 days'
                  AND is_deleted = false
                  {store_filter}
            """),
            params,
        )
        monthly_avg = monthly_result.scalar()

        if recent_avg is None or monthly_avg is None:
            return None

        recent_avg = float(recent_avg)
        monthly_avg = float(monthly_avg)
        drop = monthly_avg - recent_avg

        if drop < drop_threshold:
            return None

        severity = "high" if drop >= 0.5 else "medium"

        platform_result = await db.execute(
            text(f"""
                SELECT platform, COUNT(*) as cnt
                FROM public_opinion_mentions
                WHERE tenant_id = :tenant_id
                  AND captured_at > NOW() - INTERVAL '24 hours'
                  AND is_deleted = false
                  {store_filter}
                GROUP BY platform
                ORDER BY cnt DESC
                LIMIT 1
            """),
            params,
        )
        platform_row = platform_result.fetchone()
        platform = str(platform_row[0]) if platform_row else "dianping"

        alert_data = {
            "store_id": str(store_id) if store_id else None,
            "platform": platform,
            "alert_type": "rating_drop",
            "severity": severity,
            "trigger_mention_ids": [],
            "trigger_data": {
                "recent_avg_24h": round(recent_avg, 2),
                "monthly_avg_30d": round(monthly_avg, 2),
                "drop": round(drop, 2),
            },
        }

        alert = await self.create_alert(tenant_id, alert_data, db)
        log.info(
            "reputation_monitor.rating_drop_detected",
            alert_id=alert["alert_id"],
            drop=round(drop, 2),
        )
        return alert

    async def create_alert(
        self,
        tenant_id: uuid.UUID,
        alert_data: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """创建舆情预警

        插入 reputation_alerts 表，自动调用 tx-brain 生成摘要和建议。
        """
        log = logger.bind(tenant_id=str(tenant_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 生成AI摘要
        summary = await self._generate_summary(alert_data, log)

        # 生成建议动作
        recommended_actions = self._build_recommended_actions(
            alert_data.get("alert_type", "negative_spike"),
            alert_data.get("severity", "medium"),
        )

        alert_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO reputation_alerts (
                    id, tenant_id, store_id, platform, alert_type, severity,
                    trigger_mention_ids, trigger_data, summary,
                    recommended_actions, response_status
                ) VALUES (
                    :id, :tenant_id, :store_id, :platform, :alert_type, :severity,
                    :trigger_mention_ids::jsonb, :trigger_data::jsonb, :summary,
                    :recommended_actions::jsonb, 'pending'
                )
            """),
            {
                "id": str(alert_id),
                "tenant_id": str(tenant_id),
                "store_id": alert_data.get("store_id"),
                "platform": alert_data["platform"],
                "alert_type": alert_data["alert_type"],
                "severity": alert_data.get("severity", "medium"),
                "trigger_mention_ids": json.dumps(
                    alert_data.get("trigger_mention_ids", [])
                ),
                "trigger_data": json.dumps(alert_data.get("trigger_data", {})),
                "summary": summary,
                "recommended_actions": json.dumps(recommended_actions),
            },
        )
        await db.commit()

        log.info("reputation_monitor.alert_created", alert_id=str(alert_id))
        return {
            "alert_id": str(alert_id),
            "alert_type": alert_data["alert_type"],
            "severity": alert_data.get("severity", "medium"),
            "summary": summary,
            "recommended_actions": recommended_actions,
        }

    async def acknowledge_alert(
        self,
        tenant_id: uuid.UUID,
        alert_id: uuid.UUID,
        assigned_to: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """确认预警并分配处理人"""
        log = logger.bind(tenant_id=str(tenant_id), alert_id=str(alert_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                UPDATE reputation_alerts
                SET response_status = 'acknowledged',
                    assigned_to = :assigned_to,
                    updated_at = NOW()
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND response_status = 'pending'
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "alert_id": str(alert_id),
                "tenant_id": str(tenant_id),
                "assigned_to": str(assigned_to),
            },
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"预警不存在或状态不正确: {alert_id}")

        await db.commit()
        log.info("reputation_monitor.alert_acknowledged", assigned_to=str(assigned_to))
        return {"alert_id": str(alert_id), "status": "acknowledged"}

    async def respond_to_alert(
        self,
        tenant_id: uuid.UUID,
        alert_id: uuid.UUID,
        response_text: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """回应预警，计算响应时间并检查SLA"""
        log = logger.bind(tenant_id=str(tenant_id), alert_id=str(alert_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)

        # 读取预警信息以计算响应时间
        alert_result = await db.execute(
            text("""
                SELECT created_at, sla_target_sec
                FROM reputation_alerts
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND response_status IN ('pending', 'acknowledged')
                  AND is_deleted = false
            """),
            {"alert_id": str(alert_id), "tenant_id": str(tenant_id)},
        )
        alert_row = alert_result.fetchone()
        if not alert_row:
            raise ValueError(f"预警不存在或已处理: {alert_id}")

        created_at = alert_row[0]
        sla_target_sec = int(alert_row[1])

        # 计算响应时间
        response_time_sec = int((now - created_at).total_seconds())
        sla_met = response_time_sec <= sla_target_sec

        result = await db.execute(
            text("""
                UPDATE reputation_alerts
                SET response_status = 'responding',
                    response_text = :response_text,
                    responded_at = :responded_at,
                    response_time_sec = :response_time_sec,
                    sla_met = :sla_met,
                    updated_at = NOW()
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "alert_id": str(alert_id),
                "tenant_id": str(tenant_id),
                "response_text": response_text,
                "responded_at": now.isoformat(),
                "response_time_sec": response_time_sec,
                "sla_met": sla_met,
            },
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"更新预警失败: {alert_id}")

        await db.commit()
        log.info(
            "reputation_monitor.alert_responded",
            response_time_sec=response_time_sec,
            sla_met=sla_met,
        )
        return {
            "alert_id": str(alert_id),
            "status": "responding",
            "response_time_sec": response_time_sec,
            "sla_met": sla_met,
        }

    async def escalate_alert(
        self,
        tenant_id: uuid.UUID,
        alert_id: uuid.UUID,
        escalated_to: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """升级预警到更高层"""
        log = logger.bind(tenant_id=str(tenant_id), alert_id=str(alert_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        result = await db.execute(
            text("""
                UPDATE reputation_alerts
                SET response_status = 'escalated',
                    escalated_to = :escalated_to,
                    escalated_at = :escalated_at,
                    updated_at = NOW()
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND response_status IN ('pending', 'acknowledged', 'responding')
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "alert_id": str(alert_id),
                "tenant_id": str(tenant_id),
                "escalated_to": str(escalated_to),
                "escalated_at": now.isoformat(),
            },
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"预警不存在或无法升级: {alert_id}")

        await db.commit()
        log.info("reputation_monitor.alert_escalated", escalated_to=str(escalated_to))
        return {"alert_id": str(alert_id), "status": "escalated"}

    async def resolve_alert(
        self,
        tenant_id: uuid.UUID,
        alert_id: uuid.UUID,
        resolution_note: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """解决预警"""
        log = logger.bind(tenant_id=str(tenant_id), alert_id=str(alert_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        result = await db.execute(
            text("""
                UPDATE reputation_alerts
                SET response_status = 'resolved',
                    resolution_note = :resolution_note,
                    resolved_at = :resolved_at,
                    updated_at = NOW()
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND response_status IN (
                      'pending', 'acknowledged', 'responding', 'escalated'
                  )
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "alert_id": str(alert_id),
                "tenant_id": str(tenant_id),
                "resolution_note": resolution_note,
                "resolved_at": now.isoformat(),
            },
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"预警不存在或无法解决: {alert_id}")

        await db.commit()
        log.info("reputation_monitor.alert_resolved")
        return {"alert_id": str(alert_id), "status": "resolved"}

    async def dismiss_alert(
        self,
        tenant_id: uuid.UUID,
        alert_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """驳回预警（误报等）"""
        log = logger.bind(tenant_id=str(tenant_id), alert_id=str(alert_id))

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                UPDATE reputation_alerts
                SET response_status = 'dismissed',
                    updated_at = NOW()
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND response_status IN ('pending', 'acknowledged')
                  AND is_deleted = false
                RETURNING id
            """),
            {"alert_id": str(alert_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"预警不存在或无法驳回: {alert_id}")

        await db.commit()
        log.info("reputation_monitor.alert_dismissed")
        return {"alert_id": str(alert_id), "status": "dismissed"}

    async def get_alert_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        days: int = 30,
    ) -> dict[str, Any]:
        """预警仪表盘统计"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        params: dict[str, Any] = {"tenant_id": str(tenant_id), "days": days}

        # 总预警数
        total_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
            """),
            params,
        )
        total_alerts = int(total_result.scalar() or 0)

        # 按严重级别分组
        severity_result = await db.execute(
            text("""
                SELECT severity, COUNT(*)
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
                GROUP BY severity
            """),
            params,
        )
        by_severity = {str(r[0]): int(r[1]) for r in severity_result.fetchall()}

        # 按平台分组
        platform_result = await db.execute(
            text("""
                SELECT platform, COUNT(*)
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
                GROUP BY platform
            """),
            params,
        )
        by_platform = {str(r[0]): int(r[1]) for r in platform_result.fetchall()}

        # 平均响应时间
        avg_response_result = await db.execute(
            text("""
                SELECT AVG(response_time_sec)
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND response_time_sec IS NOT NULL
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
            """),
            params,
        )
        avg_response_time = avg_response_result.scalar()
        avg_response_sec = round(float(avg_response_time), 1) if avg_response_time else None

        # SLA合规率
        sla_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE sla_met = true) AS met,
                    COUNT(*) FILTER (WHERE sla_met IS NOT NULL) AS total
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
            """),
            params,
        )
        sla_row = sla_result.fetchone()
        sla_met_count = int(sla_row[0]) if sla_row else 0
        sla_total = int(sla_row[1]) if sla_row else 0
        sla_compliance_rate = round(sla_met_count / sla_total * 100, 1) if sla_total > 0 else None

        # 按状态分组
        status_result = await db.execute(
            text("""
                SELECT response_status, COUNT(*)
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
                GROUP BY response_status
            """),
            params,
        )
        by_status = {str(r[0]): int(r[1]) for r in status_result.fetchall()}

        return {
            "total_alerts": total_alerts,
            "by_severity": by_severity,
            "by_platform": by_platform,
            "by_status": by_status,
            "avg_response_time_sec": avg_response_sec,
            "sla_compliance_rate": sla_compliance_rate,
            "sla_met_count": sla_met_count,
            "sla_total": sla_total,
            "days": days,
        }

    async def get_sla_report(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """按门店的SLA合规报告"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT
                    store_id,
                    COUNT(*) AS total_alerts,
                    COUNT(*) FILTER (WHERE sla_met = true) AS sla_met_count,
                    COUNT(*) FILTER (WHERE sla_met = false) AS sla_missed_count,
                    AVG(response_time_sec) FILTER (
                        WHERE response_time_sec IS NOT NULL
                    ) AS avg_response_sec
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id
                  AND created_at > NOW() - MAKE_INTERVAL(days => :days)
                  AND is_deleted = false
                GROUP BY store_id
                ORDER BY sla_missed_count DESC
            """),
            {"tenant_id": str(tenant_id), "days": days},
        )
        rows = result.fetchall()

        return [
            {
                "store_id": str(r[0]) if r[0] else None,
                "total_alerts": int(r[1]),
                "sla_met_count": int(r[2]),
                "sla_missed_count": int(r[3]),
                "compliance_rate": round(
                    int(r[2]) / max(int(r[2]) + int(r[3]), 1) * 100, 1
                ),
                "avg_response_sec": round(float(r[4]), 1) if r[4] else None,
            }
            for r in rows
        ]

    # ── 内部方法 ──

    async def _generate_summary(
        self, alert_data: dict[str, Any], log: Any
    ) -> str:
        """调用 tx-brain 生成预警摘要，降级为模板摘要"""
        import httpx

        alert_type = alert_data.get("alert_type", "negative_spike")
        trigger_data = alert_data.get("trigger_data", {})

        type_desc = {
            "negative_spike": "负面口碑激增",
            "crisis": "舆情危机",
            "trending_negative": "负面趋势",
            "rating_drop": "评分下降",
            "competitor_attack": "竞品攻击",
        }

        prompt = (
            f"品牌在{alert_data.get('platform', '平台')}出现{type_desc.get(alert_type, '舆情异常')}。"
            f"数据：{json.dumps(trigger_data, ensure_ascii=False)}。"
            "请用1-2句话概括情况和影响，不超过100字。"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "http://localhost:8010/api/v1/brain/complete",
                    json={
                        "model": "claude-haiku",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 150,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = str(data.get("data", {}).get("content", ""))
                    if content:
                        return content
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            log.warning("reputation_monitor.ai_summary_fallback", error=str(exc))

        # 降级模板
        if alert_type == "rating_drop":
            drop = trigger_data.get("drop", 0)
            return (
                f"品牌在{alert_data.get('platform', '平台')}的评分"
                f"近24小时下降{drop}分，需关注。"
            )
        count = trigger_data.get("negative_count", 0)
        ratio = trigger_data.get("spike_ratio", 0)
        return (
            f"品牌在{alert_data.get('platform', '平台')}出现负面口碑激增，"
            f"近{trigger_data.get('time_window_minutes', 60)}分钟内{count}条负面提及，"
            f"是基线的{ratio}倍。"
        )

    def _build_recommended_actions(
        self, alert_type: str, severity: str
    ) -> list[dict[str, Any]]:
        """根据预警类型和级别生成建议动作"""
        actions: list[dict[str, Any]] = []

        if alert_type == "negative_spike":
            actions.append({
                "action": "查看负面提及详情，识别主要投诉点",
                "priority": "high",
                "template": "review_mentions",
            })
            actions.append({
                "action": "在对应平台发布官方回应",
                "priority": "high",
                "template": "post_response",
            })
        elif alert_type == "rating_drop":
            actions.append({
                "action": "分析近期差评主因，制定改进计划",
                "priority": "medium",
                "template": "analyze_reviews",
            })
        elif alert_type == "crisis":
            actions.append({
                "action": "启动危机公关预案，通知品牌负责人",
                "priority": "critical",
                "template": "crisis_protocol",
            })

        if severity in ("high", "critical"):
            actions.append({
                "action": "升级至品牌PR团队",
                "priority": "high",
                "template": "escalate_pr",
            })

        actions.append({
            "action": "持续监测舆情走向，72小时内复查",
            "priority": "low",
            "template": "monitor_followup",
        })

        return actions
