"""Sprint E2 — 菜品一键发布 Orchestrator

职责：
  1. 接收 DishPublishSpec + target platforms 列表
  2. 遍历平台，对每个调用 Publisher（sync，fallback stub）
  3. 写 registry（UPSERT）+ publish_tasks（审计 trail）
  4. 返回每个平台的 PublishResult

设计：
  · orchestrate_publish — 首次或更新发布到多个平台
  · orchestrate_operation — 批量执行 pause / resume / unpublish / update_price / update_stock
  · Worker / cron 消费异步任务是 follow-up PR

并发策略：
  · 本实现串行调用各平台 publisher（for-loop）；失败不影响其他
  · 真实部署：`asyncio.gather(*platforms, return_exceptions=True)` 并发
    但要注意各平台 rate limit；此处保守串行
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.delivery_publish import (
    DishPublishSpec,
    PublishOperation,
    PublishResult,
    publish_to_platform,
)
from shared.adapters.delivery_publish.base import PublishError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 输入 / 输出 dataclass
# ─────────────────────────────────────────────────────────────


@dataclass
class PlatformTarget:
    """目标平台 + 商家该平台的门店 ID"""

    platform: str
    platform_shop_id: str
    brand_id: Optional[str] = None
    store_id: Optional[str] = None


@dataclass
class OrchestrationOutcome:
    """一个平台的编排结果"""

    platform: str
    registry_id: Optional[str]
    task_id: Optional[str]
    result: PublishResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "registry_id": self.registry_id,
            "task_id": self.task_id,
            **self.result.to_dict(),
        }


# ─────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────


class DishPublishOrchestrator:
    """菜品一键发布编排器"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def orchestrate_publish(
        self,
        *,
        spec: DishPublishSpec,
        targets: list[PlatformTarget],
        triggered_by: Optional[str] = None,
        trigger_source: str = "api",
    ) -> list[OrchestrationOutcome]:
        """首次上架 / 全量更新（update_full if registry 已存在）"""
        outcomes: list[OrchestrationOutcome] = []
        for target in targets:
            outcome = await self._publish_one_platform(
                spec=spec,
                target=target,
                triggered_by=triggered_by,
                trigger_source=trigger_source,
            )
            outcomes.append(outcome)
        return outcomes

    async def orchestrate_operation(
        self,
        *,
        dish_id: str,
        operation: PublishOperation,
        platforms: list[str],
        spec: Optional[DishPublishSpec] = None,
        triggered_by: Optional[str] = None,
        trigger_source: str = "api",
    ) -> list[OrchestrationOutcome]:
        """针对已在 registry 的菜品，批量执行非首次操作

        operation 可以是：
          - UPDATE_PRICE (需 spec.price_fen)
          - UPDATE_STOCK (需 spec.stock)
          - UPDATE_FULL  (需完整 spec)
          - PAUSE / RESUME / UNPUBLISH (不需 spec；RESUME 可选 spec.stock)
        """
        outcomes: list[OrchestrationOutcome] = []
        for platform in platforms:
            outcome = await self._operation_one_platform(
                dish_id=dish_id,
                operation=operation,
                platform=platform,
                spec=spec,
                triggered_by=triggered_by,
                trigger_source=trigger_source,
            )
            outcomes.append(outcome)
        return outcomes

    # ─────────────────────────────────────────────────────────────
    # 内部
    # ─────────────────────────────────────────────────────────────

    async def _publish_one_platform(
        self,
        *,
        spec: DishPublishSpec,
        target: PlatformTarget,
        triggered_by: Optional[str],
        trigger_source: str,
    ) -> OrchestrationOutcome:
        # 1. 查 / upsert registry（先占位 status='publishing'）
        registry_id, existing_sku = await self._upsert_registry(
            dish_id=spec.dish_id,
            brand_id=target.brand_id,
            store_id=target.store_id,
            platform=target.platform,
            platform_shop_id=target.platform_shop_id,
            target_price_fen=spec.price_fen,
            original_price_fen=spec.original_price_fen,
            stock_target=spec.stock,
            mark_status="publishing",
        )

        # 2. 判断 operation：新 registry → publish；已有 SKU → update_full
        operation = (
            PublishOperation.UPDATE_FULL if existing_sku else PublishOperation.PUBLISH
        )

        # 3. 写 publish_task（审计）
        task_id = await self._enqueue_task(
            registry_id=registry_id,
            dish_id=spec.dish_id,
            platform=target.platform,
            operation=operation,
            payload=spec.to_dict(),
            triggered_by=triggered_by,
            trigger_source=trigger_source,
        )

        # 4. 调 publisher（同步）
        try:
            result = await publish_to_platform(
                platform=target.platform,
                tenant_id=self._tenant_id,
                platform_shop_id=target.platform_shop_id,
                spec=spec,
                operation=operation,
                platform_sku_id=existing_sku,
            )
        except PublishError as exc:
            logger.exception(
                "dish_publish_publisher_error",
                extra={
                    "platform": target.platform,
                    "dish_id": spec.dish_id,
                    "operation": operation.value,
                },
            )
            result = PublishResult.failure(
                platform=target.platform,
                operation=operation,
                error_message=str(exc),
                error_code="PUBLISHER_ERROR",
            )

        # 5. 回写 registry + task
        await self._record_result(
            registry_id=registry_id,
            task_id=task_id,
            result=result,
            operation=operation,
        )

        return OrchestrationOutcome(
            platform=target.platform,
            registry_id=registry_id,
            task_id=task_id,
            result=result,
        )

    async def _operation_one_platform(
        self,
        *,
        dish_id: str,
        operation: PublishOperation,
        platform: str,
        spec: Optional[DishPublishSpec],
        triggered_by: Optional[str],
        trigger_source: str,
    ) -> OrchestrationOutcome:
        # 查 registry 获取 platform_sku_id
        registry = await self._fetch_registry(dish_id=dish_id, platform=platform)
        if registry is None:
            result = PublishResult.failure(
                platform=platform,
                operation=operation,
                error_message=f"未在 registry 中找到 dish={dish_id} platform={platform}，请先 publish",
                error_code="NOT_PUBLISHED",
            )
            return OrchestrationOutcome(
                platform=platform,
                registry_id=None,
                task_id=None,
                result=result,
            )

        platform_sku_id = registry["platform_sku_id"]
        platform_shop_id = registry["platform_shop_id"] or ""

        # UPDATE_PRICE / UPDATE_STOCK 场景可能 spec 只含局部字段，
        # 用 registry 里的兜底
        working_spec = spec or _minimal_spec_from_registry(registry)

        # 写 task + 更新 registry 占位
        task_id = await self._enqueue_task(
            registry_id=str(registry["id"]),
            dish_id=dish_id,
            platform=platform,
            operation=operation,
            payload=working_spec.to_dict(),
            triggered_by=triggered_by,
            trigger_source=trigger_source,
        )
        await self._mark_registry_status(
            registry_id=str(registry["id"]),
            status="publishing",
        )

        # 调 publisher
        try:
            result = await publish_to_platform(
                platform=platform,
                tenant_id=self._tenant_id,
                platform_shop_id=platform_shop_id,
                spec=working_spec,
                operation=operation,
                platform_sku_id=platform_sku_id,
            )
        except PublishError as exc:
            logger.exception("dish_publish_op_publisher_error")
            result = PublishResult.failure(
                platform=platform,
                operation=operation,
                error_message=str(exc),
                error_code="PUBLISHER_ERROR",
            )

        await self._record_result(
            registry_id=str(registry["id"]),
            task_id=task_id,
            result=result,
            operation=operation,
        )

        return OrchestrationOutcome(
            platform=platform,
            registry_id=str(registry["id"]),
            task_id=task_id,
            result=result,
        )

    async def _upsert_registry(
        self,
        *,
        dish_id: str,
        brand_id: Optional[str],
        store_id: Optional[str],
        platform: str,
        platform_shop_id: str,
        target_price_fen: int,
        original_price_fen: Optional[int],
        stock_target: Optional[int],
        mark_status: str,
    ) -> tuple[str, Optional[str]]:
        """UPSERT registry，返回 (registry_id, existing_platform_sku_id)"""
        row = await self._db.execute(
            text("""
                INSERT INTO dish_publish_registry (
                    tenant_id, dish_id, brand_id, store_id, platform,
                    platform_shop_id, status, target_price_fen,
                    original_price_fen, stock_target
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:dish_id AS uuid),
                    CAST(:brand_id AS uuid), CAST(:store_id AS uuid),
                    :platform, :platform_shop_id, :status, :target_price_fen,
                    :original_price_fen, :stock_target
                )
                ON CONFLICT (
                    tenant_id, dish_id, platform,
                    COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid)
                ) WHERE is_deleted = false
                DO UPDATE SET
                    platform_shop_id = EXCLUDED.platform_shop_id,
                    status = :status,
                    target_price_fen = EXCLUDED.target_price_fen,
                    original_price_fen = EXCLUDED.original_price_fen,
                    stock_target = EXCLUDED.stock_target,
                    updated_at = NOW()
                RETURNING id, platform_sku_id
            """),
            {
                "tenant_id": self._tenant_id,
                "dish_id": dish_id,
                "brand_id": brand_id,
                "store_id": store_id,
                "platform": platform,
                "platform_shop_id": platform_shop_id,
                "status": mark_status,
                "target_price_fen": target_price_fen,
                "original_price_fen": original_price_fen,
                "stock_target": stock_target,
            },
        )
        rec = row.mappings().first()
        return str(rec["id"]), rec["platform_sku_id"]

    async def _enqueue_task(
        self,
        *,
        registry_id: str,
        dish_id: str,
        platform: str,
        operation: PublishOperation,
        payload: dict[str, Any],
        triggered_by: Optional[str],
        trigger_source: str,
    ) -> str:
        row = await self._db.execute(
            text("""
                INSERT INTO dish_publish_tasks (
                    tenant_id, registry_id, dish_id, platform,
                    operation, payload, status, triggered_by, trigger_source,
                    started_at
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:registry_id AS uuid),
                    CAST(:dish_id AS uuid), :platform, :operation,
                    CAST(:payload AS jsonb), 'running',
                    CAST(:triggered_by AS uuid), :trigger_source, NOW()
                )
                RETURNING id
            """),
            {
                "tenant_id": self._tenant_id,
                "registry_id": registry_id,
                "dish_id": dish_id,
                "platform": platform,
                "operation": operation.value,
                "payload": json.dumps(payload, ensure_ascii=False),
                "triggered_by": triggered_by,
                "trigger_source": trigger_source,
            },
        )
        return str(row.scalar_one())

    async def _record_result(
        self,
        *,
        registry_id: str,
        task_id: str,
        result: PublishResult,
        operation: PublishOperation,
    ) -> None:
        """回写 registry + task 的最终结果"""
        if result.ok:
            await self._db.execute(
                text("""
                    UPDATE dish_publish_registry SET
                        platform_sku_id = COALESCE(:sku_id, platform_sku_id),
                        status = :status,
                        published_price_fen = COALESCE(
                            :published_price, published_price_fen
                        ),
                        stock_available = COALESCE(
                            :published_stock, stock_available
                        ),
                        last_sync_at = NOW(),
                        last_sync_operation = :operation,
                        last_error = NULL,
                        consecutive_error_count = 0,
                        platform_metadata = CAST(:platform_metadata AS jsonb),
                        updated_at = NOW()
                    WHERE id = CAST(:registry_id AS uuid)
                """),
                {
                    "sku_id": result.platform_sku_id,
                    "status": result.status.value,
                    "published_price": result.published_price_fen,
                    "published_stock": result.published_stock,
                    "operation": operation.value,
                    "platform_metadata": json.dumps(
                        result.platform_response, ensure_ascii=False
                    ),
                    "registry_id": registry_id,
                },
            )
            await self._db.execute(
                text("""
                    UPDATE dish_publish_tasks SET
                        status = 'completed',
                        completed_at = NOW(),
                        attempts = attempts + 1,
                        platform_response = CAST(:response AS jsonb),
                        updated_at = NOW()
                    WHERE id = CAST(:task_id AS uuid)
                """),
                {
                    "task_id": task_id,
                    "response": json.dumps(
                        result.platform_response, ensure_ascii=False
                    ),
                },
            )
        else:
            await self._db.execute(
                text("""
                    UPDATE dish_publish_registry SET
                        status = 'error',
                        last_sync_at = NOW(),
                        last_sync_operation = :operation,
                        last_error = :error,
                        error_count = error_count + 1,
                        consecutive_error_count = consecutive_error_count + 1,
                        updated_at = NOW()
                    WHERE id = CAST(:registry_id AS uuid)
                """),
                {
                    "operation": operation.value,
                    "error": (
                        result.error_message or "unknown error"
                    )[:2000],
                    "registry_id": registry_id,
                },
            )
            await self._db.execute(
                text("""
                    UPDATE dish_publish_tasks SET
                        status = 'failed',
                        completed_at = NOW(),
                        attempts = attempts + 1,
                        error_message = :error,
                        platform_response = CAST(:response AS jsonb),
                        updated_at = NOW()
                    WHERE id = CAST(:task_id AS uuid)
                """),
                {
                    "task_id": task_id,
                    "error": (
                        result.error_message or "unknown"
                    )[:2000],
                    "response": json.dumps(
                        result.platform_response, ensure_ascii=False
                    ),
                },
            )

        await self._db.commit()

    async def _mark_registry_status(
        self, *, registry_id: str, status: str
    ) -> None:
        await self._db.execute(
            text("""
                UPDATE dish_publish_registry
                SET status = :status, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": registry_id, "status": status},
        )

    async def _fetch_registry(
        self, *, dish_id: str, platform: str
    ) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT id, dish_id, platform, platform_sku_id,
                       platform_shop_id, status, target_price_fen,
                       original_price_fen, stock_target, stock_available
                FROM dish_publish_registry
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND dish_id = CAST(:dish_id AS uuid)
                  AND platform = :platform
                  AND is_deleted = false
                LIMIT 1
            """),
            {
                "tenant_id": self._tenant_id,
                "dish_id": dish_id,
                "platform": platform,
            },
        )
        result = row.mappings().first()
        return dict(result) if result else None


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────


def _minimal_spec_from_registry(registry: dict[str, Any]) -> DishPublishSpec:
    """从 registry 行拼一个最小 DishPublishSpec（供 PAUSE / UNPUBLISH 操作）"""
    return DishPublishSpec(
        dish_id=str(registry["dish_id"]),
        name="[from_registry]",
        category="unknown",
        price_fen=int(registry.get("target_price_fen") or 0),
        original_price_fen=registry.get("original_price_fen"),
        stock=registry.get("stock_target"),
    )
