"""巡店管理服务

功能：
- create_template()       — 创建巡检模板（含检查项列表）
- start_patrol()          — 开始巡检，生成巡检记录和空白明细
- submit_patrol()         — 提交巡检结果，计算百分制总分，自动触发整改任务
- get_store_patrol_ranking() — 查询门店排名（按最近N天平均分）
- create_issue()          — 创建整改任务，severity=critical 时自动创建紧急审批
- update_issue_status()   — 更新整改任务状态

架构：Service → Repository → DB（async/await + Pydantic V2）
RLS：SET LOCAL app.tenant_id 由调用方（API层）在事务中设置。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

VALID_CATEGORIES = frozenset(["safety", "hygiene", "service", "equipment"])
VALID_ITEM_TYPES = frozenset(["check", "score", "photo", "text"])
VALID_SEVERITIES = frozenset(["critical", "major", "minor"])
VALID_ISSUE_STATUSES = frozenset(["open", "in_progress", "resolved", "closed"])

# 低于满分该比例时视为不合格，自动创建整改任务
PASS_THRESHOLD = 0.60


# ── 延迟导入 ApprovalEngine（避免循环依赖） ────────────────────────────────────


def _get_approval_engine():
    """延迟导入审批引擎。"""
    from .approval_workflow_engine import ApprovalEngine

    return ApprovalEngine


# 暴露给外部 mock 用
class _ApprovalEngineProxy:
    """代理类，转发调用到真实 ApprovalEngine，便于测试 mock。"""

    @staticmethod
    async def create_instance(
        tenant_id: str,
        business_type: str,
        business_id: str,
        title: str,
        initiator_id: str,
        context_data: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        ApprovalEngine = _get_approval_engine()
        return await ApprovalEngine.create_instance(
            tenant_id=tenant_id,
            business_type=business_type,
            business_id=business_id,
            title=title,
            initiator_id=initiator_id,
            context_data=context_data,
            db=db,
        )


# 模块级引用，测试中可 patch
ApprovalEngine = _ApprovalEngineProxy


# ── Repository 层 ─────────────────────────────────────────────────────────────


class PatrolRepository:
    """巡店模块数据访问层。所有方法均为静态异步方法。"""

    # -- 模板 --

    @staticmethod
    async def insert_template(
        tenant_id: str,
        brand_id: str | None,
        name: str,
        description: str | None,
        category: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        result = await db.execute(
            text(
                "INSERT INTO patrol_templates "
                "(tenant_id, brand_id, name, description, category) "
                "VALUES (:tenant_id, :brand_id, :name, :description, :category) "
                "RETURNING id, tenant_id, brand_id, name, description, category, "
                "          is_active, created_at, updated_at"
            ),
            {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "name": name,
                "description": description,
                "category": category,
            },
        )
        return dict(result.mappings().first())

    @staticmethod
    async def insert_template_items(
        tenant_id: str,
        template_id: str,
        items: list[dict[str, Any]],
        db: AsyncSession,
    ) -> None:
        for item in items:
            await db.execute(
                text(
                    "INSERT INTO patrol_template_items "
                    "(tenant_id, template_id, item_name, item_type, max_score, is_required, sort_order) "
                    "VALUES (:tenant_id, :template_id, :item_name, :item_type, "
                    "        :max_score, :is_required, :sort_order)"
                ),
                {
                    "tenant_id": tenant_id,
                    "template_id": template_id,
                    "item_name": item["item_name"],
                    "item_type": item.get("item_type", "score"),
                    "max_score": item.get("max_score", 10.0),
                    "is_required": item.get("is_required", True),
                    "sort_order": item.get("sort_order", 0),
                },
            )

    @staticmethod
    async def get_template(
        tenant_id: str,
        template_id: str,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        result = await db.execute(
            text(
                "SELECT id, tenant_id, brand_id, name, description, category, is_active "
                "FROM patrol_templates "
                "WHERE id = :template_id AND tenant_id = :tenant_id "
                "AND is_active = TRUE AND is_deleted = FALSE"
            ),
            {"template_id": template_id, "tenant_id": tenant_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def get_templates(
        tenant_id: str,
        brand_id: str | None,
        category: str | None,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        conditions = ["tenant_id = :tenant_id", "is_active = TRUE", "is_deleted = FALSE"]
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "offset": (page - 1) * size,
            "size": size,
        }
        if brand_id:
            conditions.append("brand_id = :brand_id")
            params["brand_id"] = brand_id
        if category:
            conditions.append("category = :category")
            params["category"] = category

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(
                f"SELECT id, tenant_id, brand_id, name, description, category, "
                f"       is_active, created_at, updated_at "
                f"FROM patrol_templates WHERE {where} "
                f"ORDER BY created_at DESC LIMIT :size OFFSET :offset"
            ),
            params,
        )
        count_row = await db.execute(
            text(f"SELECT COUNT(*) FROM patrol_templates WHERE {where}"),
            {k: v for k, v in params.items() if k not in ("offset", "size")},
        )
        items = [dict(r) for r in rows.mappings().fetchall()]
        total = count_row.scalar() or 0
        return {"items": items, "total": int(total)}

    @staticmethod
    async def get_template_items(
        tenant_id: str,
        template_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            text(
                "SELECT id, template_id, item_name, item_type, max_score, is_required, sort_order "
                "FROM patrol_template_items "
                "WHERE template_id = :template_id AND tenant_id = :tenant_id "
                "AND is_deleted = FALSE "
                "ORDER BY sort_order ASC"
            ),
            {"template_id": template_id, "tenant_id": tenant_id},
        )
        return [dict(r) for r in result.mappings().fetchall()]

    # -- 巡检记录 --

    @staticmethod
    async def insert_record(
        tenant_id: str,
        store_id: str,
        template_id: str,
        patrol_date: date,
        patroller_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        result = await db.execute(
            text(
                "INSERT INTO patrol_records "
                "(tenant_id, store_id, template_id, patrol_date, patroller_id, status) "
                "VALUES (:tenant_id, :store_id, :template_id, :patrol_date, :patroller_id, 'in_progress') "
                "RETURNING id, tenant_id, store_id, template_id, patrol_date, "
                "          patroller_id, status, total_score, created_at"
            ),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "template_id": template_id,
                "patrol_date": patrol_date,
                "patroller_id": patroller_id,
            },
        )
        return dict(result.mappings().first())

    @staticmethod
    async def insert_record_items(
        tenant_id: str,
        record_id: str,
        template_items: list[dict[str, Any]],
        db: AsyncSession,
    ) -> None:
        for item in template_items:
            await db.execute(
                text(
                    "INSERT INTO patrol_record_items "
                    "(tenant_id, record_id, template_item_id, item_name, max_score) "
                    "VALUES (:tenant_id, :record_id, :template_item_id, :item_name, :max_score)"
                ),
                {
                    "tenant_id": tenant_id,
                    "record_id": record_id,
                    "template_item_id": item["id"],
                    "item_name": item["item_name"],
                    "max_score": item.get("max_score", 10.0),
                },
            )

    @staticmethod
    async def get_record(
        tenant_id: str,
        record_id: str,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        result = await db.execute(
            text(
                "SELECT id, tenant_id, store_id, template_id, patrol_date, "
                "       patroller_id, status, total_score "
                "FROM patrol_records "
                "WHERE id = :record_id AND tenant_id = :tenant_id AND is_deleted = FALSE"
            ),
            {"record_id": record_id, "tenant_id": tenant_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def get_record_items(
        tenant_id: str,
        record_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            text(
                "SELECT id, record_id, template_item_id, item_name, "
                "       actual_score, max_score, is_passed, photo_urls, notes "
                "FROM patrol_record_items "
                "WHERE record_id = :record_id AND tenant_id = :tenant_id "
                "AND is_deleted = FALSE"
            ),
            {"record_id": record_id, "tenant_id": tenant_id},
        )
        return [dict(r) for r in result.mappings().fetchall()]

    @staticmethod
    async def update_record_item(
        tenant_id: str,
        item_id: str,
        actual_score: float | None,
        is_passed: bool | None,
        photo_urls: list[str],
        notes: str | None,
        db: AsyncSession,
    ) -> None:
        await db.execute(
            text(
                "UPDATE patrol_record_items "
                "SET actual_score = :actual_score, is_passed = :is_passed, "
                "    photo_urls = :photo_urls::jsonb, notes = :notes, "
                "    updated_at = NOW() "
                "WHERE id = :item_id AND tenant_id = :tenant_id"
            ),
            {
                "item_id": item_id,
                "tenant_id": tenant_id,
                "actual_score": actual_score,
                "is_passed": is_passed,
                "photo_urls": json.dumps(photo_urls, ensure_ascii=False),
                "notes": notes,
            },
        )

    @staticmethod
    async def update_record_status(
        tenant_id: str,
        record_id: str,
        status: str,
        total_score: float | None,
        db: AsyncSession,
    ) -> None:
        await db.execute(
            text(
                "UPDATE patrol_records "
                "SET status = :status, total_score = :total_score, updated_at = NOW() "
                "WHERE id = :record_id AND tenant_id = :tenant_id"
            ),
            {
                "record_id": record_id,
                "tenant_id": tenant_id,
                "status": status,
                "total_score": total_score,
            },
        )

    # -- 整改任务 --

    @staticmethod
    async def insert_issue(
        tenant_id: str,
        record_id: str | None,
        store_id: str,
        item_name: str,
        severity: str,
        description: str | None,
        photo_urls: list[str],
        db: AsyncSession,
    ) -> dict[str, Any]:
        result = await db.execute(
            text(
                "INSERT INTO patrol_issues "
                "(tenant_id, record_id, store_id, item_name, severity, description, photo_urls) "
                "VALUES (:tenant_id, :record_id, :store_id, :item_name, "
                "        :severity, :description, :photo_urls::jsonb) "
                "RETURNING id, tenant_id, record_id, store_id, item_name, severity, "
                "          description, photo_urls, status, assignee_id, due_date, created_at"
            ),
            {
                "tenant_id": tenant_id,
                "record_id": record_id,
                "store_id": store_id,
                "item_name": item_name,
                "severity": severity,
                "description": description,
                "photo_urls": json.dumps(photo_urls, ensure_ascii=False),
            },
        )
        return dict(result.mappings().first())

    @staticmethod
    async def update_issue(
        tenant_id: str,
        issue_id: str,
        new_status: str,
        resolution_notes: str | None,
        db: AsyncSession,
    ) -> None:
        resolved_at_expr = "NOW()" if new_status == "resolved" else "resolved_at"
        await db.execute(
            text(
                f"UPDATE patrol_issues "
                f"SET status = :status, resolution_notes = :notes, "
                f"    resolved_at = {resolved_at_expr}, updated_at = NOW() "
                f"WHERE id = :issue_id AND tenant_id = :tenant_id"
            ),
            {
                "status": new_status,
                "notes": resolution_notes,
                "issue_id": issue_id,
                "tenant_id": tenant_id,
            },
        )

    @staticmethod
    async def get_issue(
        tenant_id: str,
        issue_id: str,
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        result = await db.execute(
            text(
                "SELECT id, tenant_id, record_id, store_id, item_name, severity, "
                "       description, photo_urls, status, assignee_id, due_date, "
                "       resolved_at, resolution_notes, created_at, updated_at "
                "FROM patrol_issues "
                "WHERE id = :issue_id AND tenant_id = :tenant_id AND is_deleted = FALSE"
            ),
            {"issue_id": issue_id, "tenant_id": tenant_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def list_issues(
        tenant_id: str,
        store_id: str | None,
        status: str | None,
        severity: str | None,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "offset": (page - 1) * size,
            "size": size,
        }
        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if severity:
            conditions.append("severity = :severity")
            params["severity"] = severity

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(
                f"SELECT id, record_id, store_id, item_name, severity, description, "
                f"       photo_urls, status, assignee_id, due_date, resolved_at, "
                f"       resolution_notes, created_at, updated_at "
                f"FROM patrol_issues WHERE {where} "
                f"ORDER BY created_at DESC LIMIT :size OFFSET :offset"
            ),
            params,
        )
        count_row = await db.execute(
            text(f"SELECT COUNT(*) FROM patrol_issues WHERE {where}"),
            {k: v for k, v in params.items() if k not in ("offset", "size")},
        )
        items = [dict(r) for r in rows.mappings().fetchall()]
        total = count_row.scalar() or 0
        return {"items": items, "total": int(total)}

    # -- 门店排名 --

    @staticmethod
    async def query_store_ranking(
        tenant_id: str,
        days: int,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            text(
                "SELECT store_id, "
                "       ROUND(AVG(total_score)::NUMERIC, 1) AS avg_score, "
                "       COUNT(*) AS patrol_count, "
                "       RANK() OVER (ORDER BY AVG(total_score) DESC) AS rank "
                "FROM patrol_records "
                "WHERE tenant_id = :tenant_id "
                "  AND status IN ('submitted', 'reviewed') "
                "  AND is_deleted = FALSE "
                "  AND patrol_date >= CURRENT_DATE - :days * INTERVAL '1 day' "
                "  AND total_score IS NOT NULL "
                "GROUP BY store_id "
                "ORDER BY avg_score DESC"
            ),
            {"tenant_id": tenant_id, "days": days},
        )
        return [dict(r) for r in result.mappings().fetchall()]


# ── Service 层 ────────────────────────────────────────────────────────────────


class PatrolService:
    """巡店管理业务逻辑层。

    所有方法为静态异步方法，通过显式参数接受 tenant_id 和 db，
    不持有任何实例状态，便于在 FastAPI 依赖注入体系中使用。
    """

    # ── 创建巡检模板 ───────────────────────────────────────────────────────────

    @staticmethod
    async def create_template(
        tenant_id: str,
        brand_id: str | None,
        name: str,
        description: str | None,
        category: str,
        items: list[dict[str, Any]],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """创建巡检模板，包含检查项列表。

        Args:
            tenant_id: 租户ID
            brand_id: 品牌ID（可选，为空则适用所有品牌）
            name: 模板名称
            description: 模板描述
            category: 检查类别，safety/hygiene/service/equipment
            items: 检查项列表，每项包含 item_name/item_type/max_score/is_required/sort_order
            db: 数据库会话

        Returns:
            新建的模板信息（含 id）

        Raises:
            ValueError: category 不合法
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(f"不支持的检查类别: {category}，支持: {', '.join(sorted(VALID_CATEGORIES))}")

        for item in items:
            item_type = item.get("item_type", "score")
            if item_type not in VALID_ITEM_TYPES:
                raise ValueError(f"不支持的检查项类型: {item_type}，支持: {', '.join(sorted(VALID_ITEM_TYPES))}")

        template = await PatrolRepository.insert_template(
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=name,
            description=description,
            category=category,
            db=db,
        )

        if items:
            await PatrolRepository.insert_template_items(
                tenant_id=tenant_id,
                template_id=str(template["id"]),
                items=items,
                db=db,
            )

        await db.commit()

        log.info(
            "patrol_template_created",
            tenant_id=tenant_id,
            template_id=str(template["id"]),
            item_count=len(items),
        )

        return template

    # ── 获取模板列表 ───────────────────────────────────────────────────────────

    @staticmethod
    async def list_templates(
        tenant_id: str,
        brand_id: str | None,
        category: str | None,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """获取巡检模板列表，支持按品牌和类别过滤。"""
        return await PatrolRepository.get_templates(
            tenant_id=tenant_id,
            brand_id=brand_id,
            category=category,
            page=page,
            size=size,
            db=db,
        )

    # ── 开始巡检 ───────────────────────────────────────────────────────────────

    @staticmethod
    async def start_patrol(
        tenant_id: str,
        store_id: str,
        template_id: str,
        patroller_id: str,
        db: AsyncSession,
        patrol_date: date | None = None,
    ) -> dict[str, Any]:
        """开始巡检，创建巡检记录和空白明细。

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            template_id: 巡检模板ID
            patroller_id: 巡检员工ID
            db: 数据库会话
            patrol_date: 巡检日期，默认今日

        Returns:
            新建的巡检记录

        Raises:
            ValueError: 模板不存在或已停用
        """
        patrol_date = patrol_date or date.today()

        # 验证模板存在且有效
        template = await PatrolRepository.get_template(
            tenant_id=tenant_id,
            template_id=template_id,
            db=db,
        )
        if not template:
            raise ValueError(f"模板不存在或已停用: {template_id}")

        # 获取模板检查项
        template_items = await PatrolRepository.get_template_items(
            tenant_id=tenant_id,
            template_id=template_id,
            db=db,
        )

        # 创建巡检记录
        record = await PatrolRepository.insert_record(
            tenant_id=tenant_id,
            store_id=store_id,
            template_id=template_id,
            patrol_date=patrol_date,
            patroller_id=patroller_id,
            db=db,
        )

        # 创建空白明细（每个检查项对应一条）
        if template_items:
            await PatrolRepository.insert_record_items(
                tenant_id=tenant_id,
                record_id=str(record["id"]),
                template_items=template_items,
                db=db,
            )

        await db.commit()

        log.info(
            "patrol_started",
            tenant_id=tenant_id,
            record_id=str(record["id"]),
            store_id=store_id,
            template_id=template_id,
            item_count=len(template_items),
        )

        return record

    # ── 提交巡检结果 ───────────────────────────────────────────────────────────

    @staticmethod
    async def submit_patrol(
        tenant_id: str,
        record_id: str,
        items: list[dict[str, Any]],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """提交巡检结果，自动计算百分制总分，低分项自动创建整改任务。

        Args:
            tenant_id: 租户ID
            record_id: 巡检记录ID
            items: 提交的检查项结果，每项含：
                   template_item_id, actual_score, photo_urls, notes
            db: 数据库会话

        Returns:
            更新后的巡检记录（含 total_score）

        Raises:
            ValueError: 记录不存在或状态不允许提交
        """
        # 查询记录
        record = await PatrolRepository.get_record(
            tenant_id=tenant_id,
            record_id=record_id,
            db=db,
        )
        if not record:
            raise ValueError(f"巡检记录不存在: {record_id}")
        if record["status"] != "in_progress":
            raise ValueError(f"只有 in_progress 状态的巡检才能提交，当前状态: {record['status']}")

        # 查询记录明细（含 max_score）
        record_items = await PatrolRepository.get_record_items(
            tenant_id=tenant_id,
            record_id=record_id,
            db=db,
        )

        # 建立 template_item_id → record_item 映射
        item_map: dict[str, dict[str, Any]] = {str(ri["template_item_id"]): ri for ri in record_items}

        total_actual = 0.0
        total_max = 0.0
        low_score_items: list[dict[str, Any]] = []  # 需要整改的项目

        # 更新每个检查项
        for submit_item in items:
            tid_key = str(submit_item["template_item_id"])
            record_item = item_map.get(tid_key)
            if not record_item:
                continue

            actual_score: float | None = submit_item.get("actual_score")
            max_score: float = float(record_item.get("max_score") or 10.0)
            photo_urls: list[str] = submit_item.get("photo_urls") or []
            notes: str | None = submit_item.get("notes")

            # 判断是否通过（score类型：实际分 >= 满分60%；check类型：actual_score > 0）
            is_passed: bool | None = None
            if actual_score is not None:
                is_passed = actual_score >= max_score * PASS_THRESHOLD
                total_actual += actual_score
                total_max += max_score

                # 未通过则加入整改列表
                if not is_passed:
                    low_score_items.append(
                        {
                            "item_name": record_item["item_name"],
                            "actual_score": actual_score,
                            "max_score": max_score,
                            "photo_urls": photo_urls,
                            "notes": notes,
                        }
                    )

            await PatrolRepository.update_record_item(
                tenant_id=tenant_id,
                item_id=str(record_item["id"]),
                actual_score=actual_score,
                is_passed=is_passed,
                photo_urls=photo_urls,
                notes=notes,
                db=db,
            )

        # 计算百分制总分
        total_score: float | None = None
        if total_max > 0:
            total_score = round(total_actual / total_max * 100, 1)

        # 更新记录状态
        await PatrolRepository.update_record_status(
            tenant_id=tenant_id,
            record_id=record_id,
            status="submitted",
            total_score=total_score,
            db=db,
        )

        await db.commit()

        log.info(
            "patrol_submitted",
            tenant_id=tenant_id,
            record_id=record_id,
            total_score=total_score,
            low_score_count=len(low_score_items),
        )

        # 查询更新后记录（含 store_id，用于整改任务）
        updated_record = await PatrolRepository.get_record(
            tenant_id=tenant_id,
            record_id=record_id,
            db=db,
        )

        store_id = str(updated_record["store_id"]) if updated_record else str(record.get("store_id", ""))

        # 自动创建整改任务（低分项）
        for low_item in low_score_items:
            # 根据得分比例判断严重程度
            score_ratio = low_item["actual_score"] / low_item["max_score"] if low_item["max_score"] > 0 else 0
            if score_ratio < 0.3:
                severity = "critical"
            elif score_ratio < 0.5:
                severity = "major"
            else:
                severity = "minor"

            await PatrolService.create_issue(
                tenant_id=tenant_id,
                record_id=record_id,
                store_id=store_id,
                item_name=low_item["item_name"],
                severity=severity,
                description=low_item.get("notes")
                or f"检查项得分不足（{low_item['actual_score']}/{low_item['max_score']}）",
                photo_urls=low_item.get("photo_urls") or [],
                db=db,
            )

        return updated_record or {**record, "status": "submitted", "total_score": total_score}

    # ── 创建整改任务 ───────────────────────────────────────────────────────────

    @staticmethod
    async def create_issue(
        tenant_id: str,
        record_id: str | None,
        store_id: str,
        item_name: str,
        severity: str,
        description: str | None,
        photo_urls: list[str],
        db: AsyncSession,
        initiator_id: str | None = None,
    ) -> dict[str, Any]:
        """创建整改任务。

        severity=critical 时自动创建紧急审批流程。

        Args:
            tenant_id: 租户ID
            record_id: 关联巡检记录ID（可选）
            store_id: 门店ID
            item_name: 检查项名称
            severity: 严重程度：critical/major/minor
            description: 问题描述
            photo_urls: 现场照片URL列表
            db: 数据库会话
            initiator_id: 整改发起人ID（用于审批，默认为系统）

        Returns:
            新建的整改任务

        Raises:
            ValueError: severity 不合法
        """
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"不支持的整改严重程度: {severity}，支持: {', '.join(sorted(VALID_SEVERITIES))}")

        issue = await PatrolRepository.insert_issue(
            tenant_id=tenant_id,
            record_id=record_id,
            store_id=store_id,
            item_name=item_name,
            severity=severity,
            description=description,
            photo_urls=photo_urls,
            db=db,
        )

        await db.commit()

        log.info(
            "patrol_issue_created",
            tenant_id=tenant_id,
            issue_id=str(issue["id"]),
            store_id=store_id,
            severity=severity,
        )

        # critical 级别：自动创建紧急审批
        if severity == "critical":
            try:
                await ApprovalEngine.create_instance(
                    tenant_id=tenant_id,
                    business_type="patrol_issue",
                    business_id=str(issue["id"]),
                    title=f"【紧急整改审批】{item_name}",
                    initiator_id=initiator_id or "system",
                    context_data={
                        "severity": severity,
                        "store_id": store_id,
                        "record_id": record_id,
                        "item_name": item_name,
                        "description": description,
                    },
                    db=db,
                )
                log.info(
                    "patrol_critical_approval_created",
                    tenant_id=tenant_id,
                    issue_id=str(issue["id"]),
                )
            except (ValueError, RuntimeError) as exc:
                # 审批创建失败不阻塞整改任务本身
                log.warning(
                    "patrol_critical_approval_failed",
                    tenant_id=tenant_id,
                    issue_id=str(issue["id"]),
                    error=str(exc),
                )

        return issue

    # ── 更新整改状态 ───────────────────────────────────────────────────────────

    @staticmethod
    async def update_issue_status(
        tenant_id: str,
        issue_id: str,
        new_status: str,
        resolution_notes: str | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """更新整改任务状态。

        Args:
            tenant_id: 租户ID
            issue_id: 整改任务ID
            new_status: 新状态：open/in_progress/resolved/closed
            resolution_notes: 整改说明（resolved 时必填）
            db: 数据库会话

        Returns:
            更新后的整改任务

        Raises:
            ValueError: 状态不合法
        """
        if new_status not in VALID_ISSUE_STATUSES:
            raise ValueError(f"不支持的整改状态: {new_status}，支持: {', '.join(sorted(VALID_ISSUE_STATUSES))}")

        await PatrolRepository.update_issue(
            tenant_id=tenant_id,
            issue_id=issue_id,
            new_status=new_status,
            resolution_notes=resolution_notes,
            db=db,
        )

        await db.commit()

        updated = await PatrolRepository.get_issue(
            tenant_id=tenant_id,
            issue_id=issue_id,
            db=db,
        )

        log.info(
            "patrol_issue_updated",
            tenant_id=tenant_id,
            issue_id=issue_id,
            new_status=new_status,
        )

        return updated or {}

    # ── 门店排名 ───────────────────────────────────────────────────────────────

    @staticmethod
    async def get_store_patrol_ranking(
        tenant_id: str,
        db: AsyncSession,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """查询门店巡检排名（按最近N天平均分降序）。

        Args:
            tenant_id: 租户ID
            db: 数据库会话
            days: 统计时间窗口（天），默认30天

        Returns:
            排名列表，每项含：store_id, avg_score, patrol_count, rank
        """
        return await PatrolRepository.query_store_ranking(
            tenant_id=tenant_id,
            days=days,
            db=db,
        )

    # ── 整改任务列表 ───────────────────────────────────────────────────────────

    @staticmethod
    async def list_issues(
        tenant_id: str,
        store_id: str | None,
        status: str | None,
        severity: str | None,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """获取整改任务列表，支持按门店/状态/严重程度过滤。"""
        return await PatrolRepository.list_issues(
            tenant_id=tenant_id,
            store_id=store_id,
            status=status,
            severity=severity,
            page=page,
            size=size,
            db=db,
        )
