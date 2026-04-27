"""菜品利润周报推送Worker — 每周一03:00触发

调度方式：async函数，由外部调度器（APScheduler / crontab）调用
核心流程：
  1. 遍历所有活跃 tenant + store
  2. 调用 dish_pricing_advisor_service 生成本周定价建议
  3. 调用 compute_dish_co_occurrence 更新共现数据
  4. 组装 Markdown 周报：TOP5利润/亏损菜、BCG变动、定价建议摘要
  5. 通过 IM 通道推送（调用已有推送接口）

金额单位: 分(fen), int
"""

from datetime import date, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .dish_pricing_advisor_service import (
    _classify_bcg,
    _fen_to_yuan,
    _fetch_dish_bcg_data,
    _set_rls,
    compute_dish_co_occurrence,
    generate_pricing_suggestions,
)

log = structlog.get_logger(__name__)


class DishProfitWeeklyWorker:
    """菜品利润周报Worker — 每周一03:00由外部调度器调用"""

    async def tick(self, db: AsyncSession) -> dict[str, Any]:
        """单次 tick: 遍历所有活跃 tenant+store 生成并推送周报

        Returns:
            {
                "tenants_processed": int,
                "stores_processed": int,
                "reports_sent": int,
                "errors": int,
            }
        """
        stats: dict[str, Any] = {
            "tenants_processed": 0,
            "stores_processed": 0,
            "reports_sent": 0,
            "errors": 0,
        }

        try:
            # 查询所有有近期订单的 tenant+store 组合
            result = await db.execute(
                text("""
                    SELECT DISTINCT o.tenant_id, o.store_id, s.store_name
                    FROM orders o
                    LEFT JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
                    WHERE o.status IN ('completed', 'paid')
                      AND o.is_deleted = FALSE
                      AND o.order_time >= NOW() - INTERVAL '14 days'
                    ORDER BY o.tenant_id, o.store_id
                """),
            )
            combos = result.mappings().all()

            seen_tenants: set[str] = set()

            for combo in combos:
                tenant_id = str(combo["tenant_id"])
                store_id = str(combo["store_id"])
                store_name = combo.get("store_name", store_id[:8])

                if tenant_id not in seen_tenants:
                    seen_tenants.add(tenant_id)
                    stats["tenants_processed"] += 1

                try:
                    report_md = await self.generate_weekly_report(
                        db, tenant_id, store_id, store_name,
                    )
                    if report_md:
                        await self._push_report(db, tenant_id, store_id, store_name, report_md)
                        stats["reports_sent"] += 1

                    stats["stores_processed"] += 1

                except SQLAlchemyError as exc:
                    log.error(
                        "weekly_worker.store_error",
                        tenant_id=tenant_id,
                        store_id=store_id,
                        error=str(exc),
                    )
                    stats["errors"] += 1

        except SQLAlchemyError as exc:
            log.error("weekly_worker.query_error", error=str(exc))
            stats["errors"] += 1

        log.info("weekly_worker.tick_complete", **stats)
        return stats

    async def generate_weekly_report(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        store_name: str,
    ) -> Optional[str]:
        """为单个门店生成周报

        Returns:
            Markdown 格式的周报内容，无数据时返回 None
        """
        today = date.today()
        week_start = today - timedelta(days=7)
        prev_week_start = week_start - timedelta(days=7)

        await _set_rls(db, tenant_id)

        # ─── 1. 生成本周定价建议 ─────────────────────────────────
        suggestions = await generate_pricing_suggestions(
            db, tenant_id, store_id, period_days=7,
        )

        # ─── 2. 更新共现数据 ─────────────────────────────────────
        try:
            await compute_dish_co_occurrence(
                db, tenant_id, store_id, week_start, today,
            )
        except SQLAlchemyError as exc:
            log.warning("weekly_worker.co_occurrence_error", error=str(exc), store_id=store_id)

        # ─── 3. 获取本周 & 上周BCG数据 ──────────────────────────
        this_week_dishes = await _fetch_dish_bcg_data(db, tenant_id, store_id, week_start, today)
        prev_week_dishes = await _fetch_dish_bcg_data(db, tenant_id, store_id, prev_week_start, week_start)

        if not this_week_dishes:
            log.info("weekly_worker.no_data", store_id=store_id)
            return None

        this_week_bcg = _classify_bcg(this_week_dishes)
        prev_bcg_map: dict[str, str] = {}
        if prev_week_dishes:
            for d in _classify_bcg(prev_week_dishes):
                prev_bcg_map[d["dish_id"]] = d["bcg_quadrant"]

        # ─── 4. 组装报告数据 ─────────────────────────────────────

        # TOP5 利润菜（按毛利额降序）
        for d in this_week_bcg:
            d["margin_fen"] = d["price_fen"] - d["cost_fen"]
            d["total_margin_fen"] = d["margin_fen"] * d["sales_qty"]
        profit_sorted = sorted(this_week_bcg, key=lambda x: x["total_margin_fen"], reverse=True)
        top5_profit = profit_sorted[:5]

        # TOP5 亏损菜（毛利额最低，含负值）
        top5_loss = profit_sorted[-5:][::-1] if len(profit_sorted) >= 5 else list(reversed(profit_sorted))

        # BCG变动检测
        bcg_changes: list[dict[str, Any]] = []
        _QUADRANT_LABELS = {
            "star": "明星菜",
            "cash_cow": "耕牛菜",
            "question_mark": "问题菜",
            "dog": "瘦狗菜",
        }
        for d in this_week_bcg:
            prev_q = prev_bcg_map.get(d["dish_id"])
            curr_q = d["bcg_quadrant"]
            if prev_q and prev_q != curr_q:
                bcg_changes.append({
                    "dish_name": d["dish_name"],
                    "from": prev_q,
                    "from_label": _QUADRANT_LABELS.get(prev_q, prev_q),
                    "to": curr_q,
                    "to_label": _QUADRANT_LABELS.get(curr_q, curr_q),
                })

        # ─── 5. 组装 Markdown 周报 ───────────────────────────────
        md = self._build_markdown(
            store_name=store_name,
            week_start=week_start,
            today=today,
            top5_profit=top5_profit,
            top5_loss=top5_loss,
            bcg_changes=bcg_changes,
            suggestions=suggestions,
            total_dishes=len(this_week_bcg),
        )

        log.info(
            "weekly_worker.report_generated",
            store_id=store_id,
            store_name=store_name,
            suggestions_count=len(suggestions),
            bcg_changes_count=len(bcg_changes),
        )

        return md

    def _build_markdown(
        self,
        store_name: str,
        week_start: date,
        today: date,
        top5_profit: list[dict[str, Any]],
        top5_loss: list[dict[str, Any]],
        bcg_changes: list[dict[str, Any]],
        suggestions: list[dict[str, Any]],
        total_dishes: int,
    ) -> str:
        """组装 Markdown 格式周报"""
        lines: list[str] = []

        # 标题
        lines.append(f"# 菜品利润周报 — {store_name}")
        lines.append(f"**报告周期**: {week_start} ~ {today}")
        lines.append(f"**在售菜品数**: {total_dishes}")
        lines.append("")

        # TOP5 利润菜
        lines.append("## TOP5 利润贡献菜品")
        lines.append("| 排名 | 菜品 | 售价 | 毛利率 | 周销量 | 周毛利 |")
        lines.append("|------|------|------|--------|--------|--------|")
        for i, d in enumerate(top5_profit, 1):
            lines.append(
                f"| {i} | {d['dish_name']} "
                f"| {_fen_to_yuan(d['price_fen'])}元 "
                f"| {d['margin_rate']}% "
                f"| {d['sales_qty']}份 "
                f"| {_fen_to_yuan(d['total_margin_fen'])}元 |"
            )
        lines.append("")

        # TOP5 亏损/低利菜
        lines.append("## TOP5 低利/亏损菜品")
        lines.append("| 排名 | 菜品 | 售价 | 毛利率 | 周销量 | 周毛利 |")
        lines.append("|------|------|------|--------|--------|--------|")
        for i, d in enumerate(top5_loss, 1):
            lines.append(
                f"| {i} | {d['dish_name']} "
                f"| {_fen_to_yuan(d['price_fen'])}元 "
                f"| {d['margin_rate']}% "
                f"| {d['sales_qty']}份 "
                f"| {_fen_to_yuan(d['total_margin_fen'])}元 |"
            )
        lines.append("")

        # BCG象限变动
        if bcg_changes:
            lines.append("## BCG象限变动预警")
            lines.append("| 菜品 | 上周 | 本周 | 变动方向 |")
            lines.append("|------|------|------|----------|")
            for c in bcg_changes:
                arrow = "↑" if c["to"] in ("star", "cash_cow") else "↓"
                lines.append(
                    f"| {c['dish_name']} "
                    f"| {c['from_label']} "
                    f"| {c['to_label']} "
                    f"| {arrow} |"
                )
            lines.append("")
        else:
            lines.append("## BCG象限变动")
            lines.append("本周无象限变动。")
            lines.append("")

        # 定价建议摘要
        if suggestions:
            lines.append("## 定价建议摘要")
            by_type: dict[str, list[dict[str, Any]]] = {}
            for s in suggestions:
                stype = s["suggestion_type"]
                by_type.setdefault(stype, []).append(s)

            type_labels = {
                "raise": "建议提价",
                "lower": "成本预警",
                "delist": "建议下架",
                "promote": "建议推广",
                "bundle": "建议组合",
            }
            for stype, items in by_type.items():
                label = type_labels.get(stype, stype)
                lines.append(f"\n### {label} ({len(items)}道)")
                for s in items[:5]:  # 每类最多展示5道
                    price_info = ""
                    if s.get("suggested_price_yuan"):
                        price_info = f" → 建议价{s['suggested_price_yuan']}元"
                    impact_info = ""
                    if s.get("estimated_impact_fen") and s["estimated_impact_fen"] != 0:
                        impact_info = f"，预估月利润影响+{s['estimated_impact_yuan']}元"
                    lines.append(
                        f"- **{s['dish_name']}**（{s.get('bcg_quadrant', '')}）"
                        f"：现价{s['current_price_yuan']}元{price_info}{impact_info}"
                    )
                    lines.append(f"  > {s['reason']}")
            lines.append("")

        # 底部
        lines.append("---")
        lines.append("*本报告由屯象OS菜品利润引擎自动生成，建议数据仅供参考，请结合实际经营判断。*")

        return "\n".join(lines)

    async def _push_report(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        store_name: str,
        report_md: str,
    ) -> None:
        """推送周报到 IM 通道

        当前实现：写入 notifications 表，由 IM 网关异步消费推送。
        后续可对接企业微信机器人/钉钉等。
        """
        try:
            await _set_rls(db, tenant_id)
            await db.execute(
                text("""
                    INSERT INTO notifications
                        (tenant_id, store_id, channel, title, content,
                         notification_type, priority, status)
                    VALUES
                        (:tenant_id::uuid, :store_id::uuid, 'im',
                         :title, :content, 'weekly_report', 'normal', 'pending')
                """),
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "title": f"菜品利润周报 — {store_name}",
                    "content": report_md,
                },
            )
            await db.commit()
            log.info(
                "weekly_worker.report_pushed",
                store_id=store_id,
                store_name=store_name,
                content_len=len(report_md),
            )
        except SQLAlchemyError as exc:
            log.error(
                "weekly_worker.push_error",
                store_id=store_id,
                error=str(exc),
            )
            # 不抛出，推送失败不影响整体流程
