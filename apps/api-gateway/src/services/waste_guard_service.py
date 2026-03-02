"""
WasteGuardService — 实时损耗监控与跨店 BOM 漂移预警

职责：
  1. check_and_alert(): variance > 10% → 企微推送 ≤30s，五步推理写入 evidence
  2. generate_monthly_report(): 月度损耗报告（四维汇总）
  3. cross_store_bom_drift_alert(): 跨店 BOM 漂移检测（CROSS-011）

与 WasteEventService 的关系：
  - WasteEventService 负责单事件 CRUD + 20% 阈值告警（保留不改）
  - WasteGuardService 是更高层监控调度，阈值 10%，集成五步推理 evidence
"""

import asyncio
from datetime import date, datetime, timedelta
from typing import Dict, List

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# WasteGuard 触发阈值（绝对值 > 10%）
WASTE_GUARD_THRESHOLD_PCT = 10.0
# 整体执行超时（秒）
EXECUTION_TIMEOUT_SECONDS = 30


class WasteGuardService:
    """实时损耗监控调度器（全静态方法，无状态）"""

    @staticmethod
    async def check_and_alert(
        session: AsyncSession,
        store_id: str,
        tenant_id: str,
        variances: List[Dict],
    ) -> List[str]:
        """
        过滤 |diff_rate_pct| > 10% 的 variance，触发五步推理 + 企微推送。

        Args:
            session:   AsyncSession
            store_id:  门店ID
            tenant_id: 租户ID
            variances: 来自 waste_reasoning_service._step1_inventory_variance() 的列表，
                       每项包含 ingredient_id, diff_rate_pct, ingredient_name 等字段

        Returns:
            已触发告警的 waste_event_id 列表
        """
        triggered_ids: List[str] = []

        # 1. 过滤超阈值的 variance
        flagged = [
            v for v in variances
            if abs(float(v.get("diff_rate_pct", 0))) > WASTE_GUARD_THRESHOLD_PCT
        ]
        if not flagged:
            return triggered_ids

        today_str = date.today().isoformat()

        async def _process_one(variance: Dict) -> None:
            ing_id   = variance.get("ingredient_id", "unknown")
            diff_pct = float(variance.get("diff_rate_pct", 0))
            ing_name = variance.get("ingredient_name", ing_id)

            try:
                # 2. 调用五步推理（带超时 25s，给企微推送留 5s）
                from src.services.waste_reasoning_service import run_waste_reasoning
                reasoning_result = await asyncio.wait_for(
                    run_waste_reasoning(
                        session=session,
                        tenant_id=tenant_id,
                        store_id=store_id,
                        date_start=today_str,
                    ),
                    timeout=25.0,
                )

                top3 = reasoning_result.get("top3_root_causes", [])
                top3_text = "；".join(
                    f"{c.get('reason', c.get('dimension', '未知'))}"
                    for c in top3[:3]
                ) or "暂无分析"

                evidence = {
                    "variance_pct": diff_pct,
                    "top3_root_causes": top3,
                    "reasoning_date": today_str,
                    "store_id": store_id,
                }

                # 3. 构建企微卡片消息（食材名、差异量、TOP3根因）
                title = f"损耗预警：{ing_name}（{diff_pct:+.1f}%）"
                description = (
                    f"食材：{ing_name}\n"
                    f"偏差率：{diff_pct:+.1f}%\n"
                    f"TOP3根因：{top3_text}\n"
                    f"发生时间：{today_str}"
                )

                # 4. 企微推送（带超时 5s）
                from src.services.wechat_work_message_service import wechat_work_message_service
                await asyncio.wait_for(
                    wechat_work_message_service.send_card_message(
                        user_id="store_manager",
                        title=title,
                        description=description,
                        url=f"https://app.zhilian.com/waste-events?store_id={store_id}",
                        btntxt="查看详情",
                    ),
                    timeout=5.0,
                )

                # 5. 记录事件 ID（用食材+日期生成唯一标识）
                import hashlib
                raw = f"{store_id}:{ing_id}:{today_str}"
                event_id = "WG-" + hashlib.sha1(raw.encode()).hexdigest()[:10].upper()
                triggered_ids.append(event_id)

                logger.info(
                    "waste_guard.alert_sent",
                    store_id=store_id,
                    ingredient_id=ing_id,
                    diff_pct=diff_pct,
                    event_id=event_id,
                )

            except asyncio.TimeoutError:
                logger.warning(
                    "waste_guard.timeout",
                    store_id=store_id,
                    ingredient_id=ing_id,
                )
            except Exception as e:
                logger.warning(
                    "waste_guard.alert_failed",
                    store_id=store_id,
                    ingredient_id=ing_id,
                    error=str(e),
                )

        # 并发处理，整体 30s 超时
        try:
            await asyncio.wait_for(
                asyncio.gather(*[_process_one(v) for v in flagged]),
                timeout=EXECUTION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("waste_guard.overall_timeout", store_id=store_id)

        return triggered_ids

    @staticmethod
    async def generate_monthly_report(
        session: AsyncSession,
        store_id: str,
        year: int,
        month: int,
    ) -> Dict:
        """
        月度损耗报告：按食材/员工/班次/渠道四维汇总。

        Returns:
            { by_ingredient, by_staff, by_shift, by_channel, period }
        """
        from src.models.waste_event import WasteEvent

        start_dt = datetime(year, month, 1)
        if month == 12:
            end_dt = datetime(year + 1, 1, 1)
        else:
            end_dt = datetime(year, month + 1, 1)

        period = {"year": year, "month": month, "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()}

        # 按食材汇总
        ing_stmt = (
            select(
                WasteEvent.ingredient_id,
                func.sum(WasteEvent.quantity).label("total_qty"),
                func.count(WasteEvent.id).label("event_count"),
                func.avg(WasteEvent.variance_pct).label("avg_variance_pct"),
            )
            .where(
                WasteEvent.store_id == store_id,
                WasteEvent.occurred_at >= start_dt,
                WasteEvent.occurred_at < end_dt,
            )
            .group_by(WasteEvent.ingredient_id)
            .order_by(func.sum(WasteEvent.quantity).desc())
        )
        ing_rows = (await session.execute(ing_stmt)).all()
        by_ingredient = [
            {
                "ingredient_id": r.ingredient_id,
                "total_qty": float(r.total_qty or 0),
                "event_count": r.event_count,
                "avg_variance_pct": round(float(r.avg_variance_pct or 0) * 100, 2),
            }
            for r in ing_rows
        ]

        # 按员工汇总
        staff_stmt = (
            select(
                WasteEvent.assigned_staff_id,
                func.count(WasteEvent.id).label("event_count"),
                func.avg(WasteEvent.variance_pct).label("avg_variance_pct"),
            )
            .where(
                WasteEvent.store_id == store_id,
                WasteEvent.occurred_at >= start_dt,
                WasteEvent.occurred_at < end_dt,
                WasteEvent.assigned_staff_id.isnot(None),
            )
            .group_by(WasteEvent.assigned_staff_id)
            .order_by(func.count(WasteEvent.id).desc())
        )
        staff_rows = (await session.execute(staff_stmt)).all()
        by_staff = [
            {
                "staff_id": r.assigned_staff_id,
                "event_count": r.event_count,
                "avg_variance_pct": round(float(r.avg_variance_pct or 0) * 100, 2),
            }
            for r in staff_rows
        ]

        # 按根因（班次代理）汇总
        shift_stmt = (
            select(
                WasteEvent.root_cause,
                func.count(WasteEvent.id).label("event_count"),
            )
            .where(
                WasteEvent.store_id == store_id,
                WasteEvent.occurred_at >= start_dt,
                WasteEvent.occurred_at < end_dt,
                WasteEvent.root_cause.isnot(None),
            )
            .group_by(WasteEvent.root_cause)
            .order_by(func.count(WasteEvent.id).desc())
        )
        shift_rows = (await session.execute(shift_stmt)).all()
        by_shift = [
            {"root_cause": r.root_cause, "event_count": r.event_count}
            for r in shift_rows
        ]

        # 按渠道汇总（通过关联订单，简化实现）
        by_channel: List[Dict] = []
        try:
            from src.models.order import Order
            from sqlalchemy import and_

            chan_stmt = (
                select(
                    Order.sales_channel,
                    func.count(WasteEvent.id).label("event_count"),
                )
                .join(
                    Order,
                    and_(
                        Order.store_id == store_id,
                        Order.order_time >= start_dt,
                        Order.order_time < end_dt,
                    ),
                    isouter=True,
                )
                .where(
                    WasteEvent.store_id == store_id,
                    WasteEvent.occurred_at >= start_dt,
                    WasteEvent.occurred_at < end_dt,
                )
                .group_by(Order.sales_channel)
                .limit(10)
            )
            chan_rows = (await session.execute(chan_stmt)).all()
            by_channel = [
                {"channel": r.sales_channel or "堂食", "event_count": r.event_count}
                for r in chan_rows
            ]
        except Exception as e:
            logger.warning("waste_guard.monthly_channel_query_failed", error=str(e))

        return {
            "period": period,
            "by_ingredient": by_ingredient,
            "by_staff": by_staff,
            "by_shift": by_shift,
            "by_channel": by_channel,
        }

    @staticmethod
    async def cross_store_bom_drift_alert(
        session: AsyncSession,
        tenant_id: str,
        threshold_pct: float = 20.0,
    ) -> List[Dict]:
        """
        CROSS-011：跨店 BOM 漂移检测。

        对同一 dish_master_id 在不同门店的 BOMTemplate 做差异率对比，
        超过 threshold_pct 的触发企微通知。

        Returns:
            触发告警的菜品-门店对列表
        """
        from src.models.bom import BOMTemplate, BOMItem
        from src.models.dish_master import DishMaster
        from sqlalchemy import and_

        alerts: List[Dict] = []

        try:
            # 查询所有活跃 BOM 模板（含食材成本汇总）
            stmt = (
                select(
                    BOMTemplate.dish_id,
                    BOMTemplate.store_id,
                    func.sum(BOMItem.standard_qty).label("total_qty"),
                )
                .join(BOMItem, BOMItem.bom_id == BOMTemplate.id)
                .where(BOMTemplate.is_active.is_(True))
                .group_by(BOMTemplate.dish_id, BOMTemplate.store_id)
            )
            rows = (await session.execute(stmt)).all()

            if not rows:
                return alerts

            # 按 dish_id 分组，找出同一菜品在不同门店的 BOM 差异
            from collections import defaultdict
            dish_store_map: Dict[str, List[Dict]] = defaultdict(list)
            for r in rows:
                dish_store_map[str(r.dish_id)].append({
                    "store_id": r.store_id,
                    "total_qty": float(r.total_qty or 0),
                })

            for dish_id, store_entries in dish_store_map.items():
                if len(store_entries) < 2:
                    continue

                qtys = [e["total_qty"] for e in store_entries]
                avg_qty = sum(qtys) / len(qtys)
                if avg_qty <= 0:
                    continue

                for entry in store_entries:
                    drift_pct = abs(entry["total_qty"] - avg_qty) / avg_qty * 100
                    if drift_pct > threshold_pct:
                        alert_info = {
                            "dish_id": dish_id,
                            "store_id": entry["store_id"],
                            "total_qty": entry["total_qty"],
                            "avg_qty": round(avg_qty, 4),
                            "drift_pct": round(drift_pct, 2),
                        }
                        alerts.append(alert_info)

                        # 企微推送（非阻塞）
                        try:
                            from src.services.wechat_work_message_service import wechat_work_message_service
                            await asyncio.wait_for(
                                wechat_work_message_service.send_card_message(
                                    user_id="store_manager",
                                    title=f"BOM漂移预警：菜品 {dish_id[:8]}...",
                                    description=(
                                        f"门店 {entry['store_id']} 的 BOM 用量与均值偏差 {drift_pct:.1f}%\n"
                                        f"当前用量：{entry['total_qty']:.4f}，均值：{avg_qty:.4f}"
                                    ),
                                    url=f"https://app.zhilian.com/bom?dish_id={dish_id}",
                                    btntxt="查看BOM",
                                ),
                                timeout=5.0,
                            )
                        except Exception:
                            pass

        except Exception as e:
            logger.warning(
                "waste_guard.cross_store_drift_failed",
                tenant_id=tenant_id,
                error=str(e),
            )

        logger.info(
            "waste_guard.cross_store_drift_checked",
            tenant_id=tenant_id,
            alerts_count=len(alerts),
            threshold_pct=threshold_pct,
        )
        return alerts
