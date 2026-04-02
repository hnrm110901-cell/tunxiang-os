"""门店快速开店克隆服务

克隆7类配置：
1. menu_config     — 菜品分类、菜品、BOM配方
2. pricing         — 价格体系、折扣规则
3. roles           — 角色权限配置
4. print_templates — 小票/厨房单模板
5. kds_routes      — KDS路由规则（档口→打印机/KDS映射）
6. business_hours  — 营业时间、休息日
7. thresholds      — 毛利底线、折扣阈值、临期预警天数
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class CloneStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分成功


class CloneItemType(str, Enum):
    MENU_CONFIG = "menu_config"
    PRICING = "pricing"
    ROLES = "roles"
    PRINT_TEMPLATES = "print_templates"
    KDS_ROUTES = "kds_routes"
    BUSINESS_HOURS = "business_hours"
    THRESHOLDS = "thresholds"


@dataclass
class CloneProgress:
    task_id: str
    status: CloneStatus
    total_items: int
    completed_items: int
    current_step: str
    errors: list[str] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    @property
    def progress_pct(self) -> float:
        if self.total_items == 0:
            return 0.0
        return self.completed_items / self.total_items * 100


class StoreCloneService:
    """
    门店克隆服务

    使用方式：
        task_id = await StoreCloneService.start_clone(
            db=db,
            tenant_id=tenant_id,
            source_store_id=source_id,
            target_store_id=target_id,
            items=[CloneItemType.MENU_CONFIG, CloneItemType.PRICING, ...],
            operator_id=operator_id,
        )
        # 轮询进度
        progress = await StoreCloneService.get_progress(db, task_id)
    """

    # 内存中的进度缓存（生产环境应存 Redis）
    _progress_cache: dict[str, CloneProgress] = {}

    @classmethod
    async def start_clone(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        source_store_id: UUID,
        target_store_id: UUID,
        items: list[CloneItemType],
        operator_id: UUID,
    ) -> str:
        """启动克隆任务，返回 task_id"""
        task_id = str(uuid4())

        progress = CloneProgress(
            task_id=task_id,
            status=CloneStatus.PENDING,
            total_items=len(items),
            completed_items=0,
            current_step="初始化",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        cls._progress_cache[task_id] = progress

        # 写入 store_clone_tasks 表
        await cls._create_task_record(
            db, task_id, tenant_id, source_store_id, target_store_id, items, operator_id
        )

        # 异步执行（不阻塞 API 响应）
        asyncio.create_task(
            cls._execute_clone(
                db, task_id, tenant_id, source_store_id, target_store_id, items
            )
        )

        logger.info(
            "store_clone_started",
            task_id=task_id,
            source=str(source_store_id),
            target=str(target_store_id),
            items=[i.value for i in items],
        )
        return task_id

    @classmethod
    async def get_progress(cls, task_id: str) -> Optional[CloneProgress]:
        return cls._progress_cache.get(task_id)

    @classmethod
    async def _execute_clone(
        cls,
        db: AsyncSession,
        task_id: str,
        tenant_id: UUID,
        source_store_id: UUID,
        target_store_id: UUID,
        items: list[CloneItemType],
    ) -> None:
        progress = cls._progress_cache[task_id]
        progress.status = CloneStatus.RUNNING
        errors: list[str] = []

        clone_handlers = {
            CloneItemType.MENU_CONFIG:     cls._clone_menu_config,
            CloneItemType.PRICING:         cls._clone_pricing,
            CloneItemType.ROLES:           cls._clone_roles,
            CloneItemType.PRINT_TEMPLATES: cls._clone_print_templates,
            CloneItemType.KDS_ROUTES:      cls._clone_kds_routes,
            CloneItemType.BUSINESS_HOURS:  cls._clone_business_hours,
            CloneItemType.THRESHOLDS:      cls._clone_thresholds,
        }

        for item_type in items:
            progress.current_step = f"克隆 {item_type.value}"
            handler = clone_handlers.get(item_type)
            if handler:
                try:
                    await handler(db, tenant_id, source_store_id, target_store_id)
                    progress.completed_items += 1
                    logger.info(
                        "clone_item_done",
                        task_id=task_id,
                        item=item_type.value,
                    )
                except (ValueError, RuntimeError, OSError) as exc:
                    errors.append(f"{item_type.value}: {exc}")
                    logger.warning(
                        "clone_item_failed",
                        task_id=task_id,
                        item=item_type.value,
                        error=str(exc),
                    )

        progress.errors = errors
        progress.completed_at = datetime.now(timezone.utc).isoformat()
        progress.status = CloneStatus.PARTIAL if errors else CloneStatus.COMPLETED
        progress.current_step = "完成" if not errors else f"完成（{len(errors)} 个错误）"

        # 更新 DB 状态
        await cls._update_task_status(db, task_id, progress.status, errors)

    # ── 各类克隆逻辑（使用 INSERT ... SELECT 模式）────────────────────────────

    @classmethod
    async def _clone_menu_config(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆菜品分类和菜品（不克隆库存）"""
        # 菜品分类
        await db.execute(
            text("""
                INSERT INTO dish_categories
                    (id, tenant_id, store_id, name, sort_order, is_available, created_at, updated_at)
                SELECT gen_random_uuid(), :tenant_id, :tgt,
                       name, sort_order, is_available, NOW(), NOW()
                FROM dish_categories
                WHERE tenant_id = :tenant_id
                  AND store_id = :src
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    @classmethod
    async def _clone_pricing(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆折扣规则"""
        await db.execute(
            text("""
                INSERT INTO discount_rules
                    (id, tenant_id, store_id, name, discount_rate,
                     min_amount_fen, valid_days, created_at, updated_at)
                SELECT gen_random_uuid(), :tenant_id, :tgt,
                       name, discount_rate, min_amount_fen, valid_days, NOW(), NOW()
                FROM discount_rules
                WHERE tenant_id = :tenant_id
                  AND store_id = :src
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    @classmethod
    async def _clone_roles(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆角色权限配置"""
        await db.execute(
            text("""
                INSERT INTO role_configs
                    (id, tenant_id, store_id, role_name, role_level, permissions,
                     created_at, updated_at)
                SELECT gen_random_uuid(), :tenant_id, :tgt,
                       role_name, role_level, permissions, NOW(), NOW()
                FROM role_configs
                WHERE tenant_id = :tenant_id
                  AND store_id = :src
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    @classmethod
    async def _clone_print_templates(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆小票/厨房单模板"""
        await db.execute(
            text("""
                INSERT INTO receipt_templates
                    (id, tenant_id, store_id, template_type, template_name,
                     content_json, is_default, created_at, updated_at)
                SELECT gen_random_uuid(), :tenant_id, :tgt,
                       template_type, template_name, content_json, is_default, NOW(), NOW()
                FROM receipt_templates
                WHERE tenant_id = :tenant_id
                  AND store_id = :src
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    @classmethod
    async def _clone_kds_routes(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆 KDS 路由规则"""
        await db.execute(
            text("""
                INSERT INTO dish_dept_mappings
                    (id, tenant_id, store_id, dish_id, dept_id, created_at, updated_at)
                SELECT gen_random_uuid(), :tenant_id, :tgt,
                       dish_id, dept_id, NOW(), NOW()
                FROM dish_dept_mappings
                WHERE tenant_id = :tenant_id
                  AND store_id = :src
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    @classmethod
    async def _clone_business_hours(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆营业时间配置"""
        await db.execute(
            text("""
                UPDATE stores
                SET business_hours = (
                        SELECT business_hours FROM stores
                        WHERE id = :src AND tenant_id = :tenant_id
                    ),
                    updated_at = NOW()
                WHERE id = :tgt AND tenant_id = :tenant_id
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    @classmethod
    async def _clone_thresholds(
        cls, db: AsyncSession, tenant_id: UUID, src: UUID, tgt: UUID
    ) -> None:
        """克隆毛利底线、折扣阈值等经营阈值"""
        await db.execute(
            text("""
                UPDATE stores
                SET min_gross_margin_rate = (
                        SELECT min_gross_margin_rate FROM stores
                        WHERE id = :src AND tenant_id = :tenant_id
                    ),
                    max_discount_rate = (
                        SELECT max_discount_rate FROM stores
                        WHERE id = :src AND tenant_id = :tenant_id
                    ),
                    expiry_warning_days = (
                        SELECT expiry_warning_days FROM stores
                        WHERE id = :src AND tenant_id = :tenant_id
                    ),
                    updated_at = NOW()
                WHERE id = :tgt AND tenant_id = :tenant_id
            """),
            {"tenant_id": str(tenant_id), "src": str(src), "tgt": str(tgt)},
        )
        await db.flush()

    # ── DB 辅助方法 ───────────────────────────────────────────────────────────

    @classmethod
    async def _create_task_record(
        cls,
        db: AsyncSession,
        task_id: str,
        tenant_id: UUID,
        source: UUID,
        target: UUID,
        items: list[CloneItemType],
        operator_id: UUID,
    ) -> None:
        await db.execute(
            text("""
                INSERT INTO store_clone_tasks
                    (id, tenant_id, source_store_id, target_store_id,
                     selected_items, status, progress, created_by, created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :source, :target,
                     :items, 'pending', 0, :operator_id, NOW(), NOW())
            """),
            {
                "id": task_id,
                "tenant_id": str(tenant_id),
                "source": str(source),
                "target": str(target),
                "items": json.dumps([i.value for i in items]),
                "operator_id": str(operator_id),
            },
        )
        await db.flush()

    @classmethod
    async def _update_task_status(
        cls,
        db: AsyncSession,
        task_id: str,
        status: CloneStatus,
        errors: list[str],
    ) -> None:
        is_terminal = status in (CloneStatus.COMPLETED, CloneStatus.PARTIAL, CloneStatus.FAILED)
        progress_pct = 100 if is_terminal else 0
        try:
            await db.execute(
                text("""
                    UPDATE store_clone_tasks
                    SET status = :status,
                        progress = :progress,
                        result_summary = :summary,
                        error_message = :error_msg,
                        updated_at = NOW()
                    WHERE id = :task_id
                """),
                {
                    "task_id": task_id,
                    "status": status.value,
                    "progress": progress_pct,
                    "summary": json.dumps({"errors": errors}),
                    "error_msg": "; ".join(errors) if errors else None,
                },
            )
            await db.commit()
        except (OSError, RuntimeError) as exc:  # outermost guard — commit must not propagate
            logger.error(
                "clone_task_update_failed",
                task_id=task_id,
                error=str(exc),
                exc_info=True,
            )
