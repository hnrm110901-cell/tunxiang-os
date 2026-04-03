"""竞对外部数据监测服务 — 执行快照采集和变化检测

负责：
  - 调用平台适配器执行竞对快照
  - 比对新旧快照检测菜品/价格/评分变化
  - 生成结构化情报预警
  - 将快照写入 competitor_snapshots 表
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 评分变化触发预警的最小阈值
_RATING_CHANGE_THRESHOLD = Decimal("0.2")
# 价格变化触发预警的最小百分比（0.10 = 10%）
_PRICE_CHANGE_THRESHOLD = Decimal("0.10")


class CompetitorMonitorExtService:
    """竞对外部数据监测（数据库持久化版本）"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def run_competitor_snapshot(
        self,
        tenant_id: uuid.UUID,
        competitor_brand_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        执行一次竞对完整快照采集并写入数据库。

        流程：
          1. 从 competitor_brands 读取 platform_ids
          2. 按优先级选择平台（美团 > 抖音 > 饿了么）
          3. 调用适配器采集数据
          4. 写入 competitor_snapshots
          5. 返回本次快照摘要
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            competitor_brand_id=str(competitor_brand_id),
        )

        # 1. 查询竞对品牌档案
        row = await self._db.execute(
            text("""
                SELECT id, name, platform_ids
                FROM competitor_brands
                WHERE id = :brand_id AND tenant_id = :tenant_id AND is_active = TRUE
            """),
            {"brand_id": str(competitor_brand_id), "tenant_id": str(tenant_id)},
        )
        brand = row.mappings().first()
        if not brand:
            log.warning("competitor_monitor_ext.brand_not_found")
            return {"ok": False, "error": "竞对品牌不存在或已停用"}

        platform_ids: dict[str, str] = brand["platform_ids"] or {}
        source, platform_store_id = _pick_platform(platform_ids)
        if not source:
            log.warning("competitor_monitor_ext.no_platform_id", brand=brand["name"])
            return {"ok": False, "error": "该竞对品牌未配置任何平台 ID"}

        log = log.bind(source=source, platform_store_id=platform_store_id)

        # 2. 调用对应适配器采集数据
        try:
            snapshot_data = await _fetch_from_platform(source, platform_store_id)
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            error_msg = f"{type(exc).__name__}: {exc}"
            log.error("competitor_monitor_ext.fetch_failed", error=error_msg)
            # 记录错误到 intel_crawl_tasks（由调用方处理），不中断流程
            return {"ok": False, "error": error_msg}

        # 3. 写入快照
        snapshot_id = uuid.uuid4()
        today = date.today()
        await self._db.execute(
            text("""
                INSERT INTO competitor_snapshots (
                    id, tenant_id, competitor_brand_id, snapshot_date,
                    avg_rating, review_count, price_range,
                    top_dishes, active_promotions, raw_data, source
                ) VALUES (
                    :id, :tenant_id, :brand_id, :snapshot_date,
                    :avg_rating, :review_count, :price_range,
                    :top_dishes, :active_promotions, :raw_data, :source
                )
                ON CONFLICT DO NOTHING
            """),
            {
                "id": str(snapshot_id),
                "tenant_id": str(tenant_id),
                "brand_id": str(competitor_brand_id),
                "snapshot_date": today,
                "avg_rating": snapshot_data.get("avg_rating"),
                "review_count": snapshot_data.get("review_count"),
                "price_range": snapshot_data.get("price_range"),
                "top_dishes": snapshot_data.get("top_dishes"),
                "active_promotions": snapshot_data.get("active_promotions"),
                "raw_data": snapshot_data.get("raw_data"),
                "source": source,
            },
        )
        await self._db.commit()

        log.info(
            "competitor_monitor_ext.snapshot_saved",
            snapshot_id=str(snapshot_id),
            snapshot_date=today.isoformat(),
        )
        return {
            "ok": True,
            "snapshot_id": str(snapshot_id),
            "brand_name": brand["name"],
            "source": source,
            "snapshot_date": today.isoformat(),
            "summary": {
                "avg_rating": snapshot_data.get("avg_rating"),
                "review_count": snapshot_data.get("review_count"),
                "top_dish_count": len(snapshot_data.get("top_dishes") or []),
            },
        }

    async def detect_changes(
        self,
        old_snapshot: dict[str, Any],
        new_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """
        比对新旧快照，检测菜品增减、价格变动、评分变化。

        参数均为 competitor_snapshots 行的字段字典。
        返回变化摘要。
        """
        changes: list[dict[str, Any]] = []

        # ── 评分变化 ──
        old_rating = Decimal(str(old_snapshot.get("avg_rating") or "0"))
        new_rating = Decimal(str(new_snapshot.get("avg_rating") or "0"))
        if old_rating > 0 and abs(new_rating - old_rating) >= _RATING_CHANGE_THRESHOLD:
            direction = "上升" if new_rating > old_rating else "下降"
            changes.append({
                "type": "rating_change",
                "severity": "high" if abs(new_rating - old_rating) >= Decimal("0.5") else "medium",
                "description": f"评分{direction} {old_rating} → {new_rating}",
                "old_value": float(old_rating),
                "new_value": float(new_rating),
            })

        # ── 菜品增减 ──
        old_dishes: list[dict] = old_snapshot.get("top_dishes") or []
        new_dishes: list[dict] = new_snapshot.get("top_dishes") or []
        old_names = {d.get("name", "") for d in old_dishes}
        new_names = {d.get("name", "") for d in new_dishes}

        added = new_names - old_names
        removed = old_names - new_names
        if added:
            changes.append({
                "type": "new_dishes",
                "severity": "medium",
                "description": f"新增热门菜品 {len(added)} 个：{', '.join(list(added)[:5])}",
                "dishes": list(added),
            })
        if removed:
            changes.append({
                "type": "removed_dishes",
                "severity": "low",
                "description": f"下架热门菜品 {len(removed)} 个：{', '.join(list(removed)[:5])}",
                "dishes": list(removed),
            })

        # ── 价格变动（扫描 top_dishes 中同名菜品的价格）──
        old_price_map = {d.get("name", ""): d.get("price_fen", 0) for d in old_dishes}
        for dish in new_dishes:
            name = dish.get("name", "")
            new_price = dish.get("price_fen", 0)
            old_price = old_price_map.get(name, 0)
            if old_price > 0 and new_price > 0:
                pct = abs(new_price - old_price) / old_price
                if Decimal(str(pct)) >= _PRICE_CHANGE_THRESHOLD:
                    direction = "涨价" if new_price > old_price else "降价"
                    changes.append({
                        "type": "price_change",
                        "severity": "high" if pct >= 0.20 else "medium",
                        "description": f"菜品「{name}」{direction} {round(pct * 100, 1)}%",
                        "dish": name,
                        "old_price_fen": old_price,
                        "new_price_fen": new_price,
                        "change_pct": round(float(pct) * 100, 1),
                    })

        return {
            "has_changes": len(changes) > 0,
            "change_count": len(changes),
            "high_severity_count": sum(1 for c in changes if c["severity"] == "high"),
            "changes": changes,
            "snapshot_date_old": old_snapshot.get("snapshot_date"),
            "snapshot_date_new": new_snapshot.get("snapshot_date"),
        }

    def generate_intel_alert(self, changes: dict[str, Any]) -> dict[str, Any]:
        """
        根据 detect_changes 返回结果生成情报预警结构。
        预警等级：critical（高严重度≥2）/ high（高严重度≥1）/ medium（有变化）/ none
        """
        high_count = changes.get("high_severity_count", 0)
        has_changes = changes.get("has_changes", False)

        if high_count >= 2:
            alert_level = "critical"
            title = "竞对重大变化预警"
        elif high_count >= 1:
            alert_level = "high"
            title = "竞对重要变化提醒"
        elif has_changes:
            alert_level = "medium"
            title = "竞对动态更新"
        else:
            return {"alert_level": "none", "should_notify": False}

        return {
            "alert_level": alert_level,
            "should_notify": True,
            "title": title,
            "summary": f"检测到 {changes['change_count']} 项变化，其中高严重度 {high_count} 项",
            "changes": changes.get("changes", []),
            "suggested_actions": _suggest_actions(changes.get("changes", [])),
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }


# ─── 内部辅助函数 ───

def _pick_platform(platform_ids: dict[str, str]) -> tuple[str, str]:
    """按优先级选择采集平台（美团 > 抖音 > 饿了么 > 大众点评）"""
    for platform in ("meituan", "douyin", "eleme", "dianping"):
        if pid := platform_ids.get(platform):
            return platform, pid
    return "", ""


async def _fetch_from_platform(source: str, platform_store_id: str) -> dict[str, Any]:
    """
    调用对应平台适配器采集快照数据，返回标准化字典。
    适配器实例由调用方注入（此处为简化的工厂调用，生产中通过 DI 注入）。
    """
    import os

    from adapters.douyin_adapter import DouyinAdapter
    from adapters.meituan_adapter import MeituanAdapter

    if source == "meituan":
        adapter = MeituanAdapter(
            app_key=os.environ.get("MEITUAN_APP_KEY", ""),
            app_secret=os.environ.get("MEITUAN_APP_SECRET", ""),
        )
        try:
            store_info = await adapter.fetch_store_info(platform_store_id)
            menu = await adapter.fetch_competitor_menu(platform_store_id)
            top_dishes = [
                {
                    "name": d.name,
                    "price_fen": d.price_fen,
                    "monthly_sales": d.monthly_sales,
                }
                for d in sorted(menu, key=lambda x: x.monthly_sales, reverse=True)[:20]
            ]
            return {
                "avg_rating": float(store_info.avg_rating),
                "review_count": store_info.review_count,
                "price_range": {
                    "avg_fen": store_info.price_per_person_fen,
                },
                "top_dishes": top_dishes,
                "active_promotions": [],
                "raw_data": store_info.model_dump(mode="json"),
            }
        finally:
            await adapter.close()

    if source == "douyin":
        adapter = DouyinAdapter(
            client_key=os.environ.get("DOUYIN_CLIENT_KEY", ""),
            client_secret=os.environ.get("DOUYIN_CLIENT_SECRET", ""),
        )
        try:
            reviews = await adapter.fetch_store_reviews(platform_store_id, days=30)
            avg_rating = (
                sum(float(r.rating) for r in reviews) / len(reviews)
                if reviews else 0.0
            )
            return {
                "avg_rating": round(avg_rating, 2),
                "review_count": len(reviews),
                "price_range": {},
                "top_dishes": [],
                "active_promotions": [],
                "raw_data": {"review_sample_count": len(reviews)},
            }
        finally:
            await adapter.close()

    raise ValueError(f"不支持的平台: {source}")


def _suggest_actions(changes: list[dict[str, Any]]) -> list[str]:
    """根据变化列表生成建议响应动作"""
    actions: list[str] = []
    types = {c["type"] for c in changes}

    if "rating_change" in types:
        actions.append("分析竞对评分变化原因，对比自身近期评分趋势")
    if "price_change" in types:
        price_changes = [c for c in changes if c["type"] == "price_change"]
        if any(c.get("change_pct", 0) < 0 for c in price_changes):
            actions.append("竞对有降价动作，评估是否需要调整定价策略")
        if any(c.get("change_pct", 0) > 0 for c in price_changes):
            actions.append("竞对涨价，可评估跟价空间")
    if "new_dishes" in types:
        actions.append("研究竞对新品，评估是否有跟进研发价值")
    if not actions:
        actions.append("持续跟踪观察")

    return actions
