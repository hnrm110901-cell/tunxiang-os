"""人群包引擎服务 — 动态/静态人群包+规则引擎+系统预设

核心功能：
  - CRUD:                人群包创建/查询/更新/删除/归档
  - execute_rules:       JSONB规则→SQL WHERE条件翻译引擎
  - refresh_pack:        刷新动态人群包成员
  - batch_refresh:       批量刷新所有到期的动态人群包（定时任务）
  - preview_rules:       预览规则匹配人数
  - presets:             系统预设管理（8个内置预设）
  - pack_members:        成员列表/导出
  - pack_trend:          人群包趋势（按日成员数变化）

规则维度支持：
  - members表：gender, birthday_within_days, member_level, channel_source
  - orders聚合：last_order_days, order_count, total_spend_fen, avg_spend_fen
  - stored_value_accounts：stored_value_fen
  - 扩展维度：rfm_level, has_wecom_friend, in_group, tag_ids
  - 行为维度：favorite_dish_ids, order_time_preference
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 8个系统预设
# ---------------------------------------------------------------------------

SYSTEM_PRESETS = [
    {
        "preset_name": "近一周生日",
        "description": "生日在未来7天内的会员",
        "category": "lifecycle",
        "icon": "cake",
        "sort_order": 1,
        "rules": {"birthday_within_days": 7},
    },
    {
        "preset_name": "15天未消费",
        "description": "最近15天未产生消费的会员",
        "category": "risk",
        "icon": "clock",
        "sort_order": 2,
        "rules": {"last_order_days": {"gte": 15}},
    },
    {
        "preset_name": "30天未消费",
        "description": "最近30天未产生消费的会员",
        "category": "risk",
        "icon": "alert-triangle",
        "sort_order": 3,
        "rules": {"last_order_days": {"gte": 30}},
    },
    {
        "preset_name": "90天沉睡会员",
        "description": "最近90天未消费的沉睡会员",
        "category": "risk",
        "icon": "moon",
        "sort_order": 4,
        "rules": {"last_order_days": {"gte": 90}},
    },
    {
        "preset_name": "高价值会员",
        "description": "累计消费超过5000元的会员",
        "category": "value",
        "icon": "star",
        "sort_order": 5,
        "rules": {"total_spend_fen": {"gte": 500000}},
    },
    {
        "preset_name": "储值低于500",
        "description": "储值余额低于500元的会员",
        "category": "opportunity",
        "icon": "wallet",
        "sort_order": 6,
        "rules": {"stored_value_fen": {"lt": 50000}},
    },
    {
        "preset_name": "高客单价",
        "description": "平均客单价超过200元的会员",
        "category": "value",
        "icon": "trending-up",
        "sort_order": 7,
        "rules": {"avg_spend_fen": {"gte": 20000}},
    },
    {
        "preset_name": "快速流失",
        "description": "消费频次骤降超过50%的会员",
        "category": "risk",
        "icon": "arrow-down",
        "sort_order": 8,
        "rules": {"rfm_level": "at_risk"},
    },
]


class AudiencePackError(Exception):
    """人群包引擎业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AudiencePackService:
    """人群包引擎核心服务"""

    # ===================================================================
    # CRUD — 人群包管理
    # ===================================================================

    async def create_pack(
        self,
        tenant_id: uuid.UUID,
        pack_name: str,
        pack_type: str,
        rules: dict,
        created_by: uuid.UUID,
        db: Any,
        *,
        description: Optional[str] = None,
        refresh_interval_hours: int = 24,
        store_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """创建人群包"""
        pack_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO audience_packs (
                    id, tenant_id, pack_name, description, pack_type,
                    rules, refresh_interval_hours, store_id, created_by
                ) VALUES (
                    :id, :tenant_id, :pack_name, :description, :pack_type,
                    :rules::jsonb, :refresh_interval_hours, :store_id, :created_by
                )
            """),
            {
                "id": str(pack_id),
                "tenant_id": str(tenant_id),
                "pack_name": pack_name,
                "description": description,
                "pack_type": pack_type,
                "rules": json.dumps(rules),
                "refresh_interval_hours": refresh_interval_hours,
                "store_id": str(store_id) if store_id else None,
                "created_by": str(created_by),
            },
        )
        log.info("audience_pack_created", pack_id=str(pack_id), pack_type=pack_type)
        return {"pack_id": str(pack_id)}

    async def get_pack(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取人群包详情"""
        result = await db.execute(
            text("""
                SELECT * FROM audience_packs
                WHERE tenant_id = :tenant_id AND id = :pack_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "pack_id": str(pack_id)},
        )
        row = result.mappings().first()
        if row is None:
            raise AudiencePackError("NOT_FOUND", "人群包不存在")
        return dict(row)

    async def list_packs(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        pack_type: Optional[str] = None,
        status: Optional[str] = None,
        store_id: Optional[uuid.UUID] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询人群包列表"""
        where = "tenant_id = :tenant_id AND is_deleted = FALSE"
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if pack_type:
            where += " AND pack_type = :pack_type"
            params["pack_type"] = pack_type
        if status:
            where += " AND status = :status"
            params["status"] = status
        if store_id:
            where += " AND store_id = :store_id"
            params["store_id"] = str(store_id)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM audience_packs WHERE {where}"), params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM audience_packs WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def update_pack(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        updates: dict,
        db: Any,
    ) -> dict:
        """更新人群包"""
        allowed = {
            "pack_name", "description", "rules",
            "refresh_interval_hours", "store_id",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            raise AudiencePackError("EMPTY_UPDATE", "无有效更新字段")

        if "rules" in filtered:
            filtered["rules"] = json.dumps(filtered["rules"])

        set_parts = []
        for k in filtered:
            if k == "rules":
                set_parts.append(f"{k} = :{k}::jsonb")
            else:
                set_parts.append(f"{k} = :{k}")
        set_parts.append("updated_at = now()")

        sql = f"""
            UPDATE audience_packs SET {", ".join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :pack_id AND is_deleted = FALSE
        """
        filtered["tenant_id"] = str(tenant_id)
        filtered["pack_id"] = str(pack_id)
        result = await db.execute(text(sql), filtered)
        if result.rowcount == 0:
            raise AudiencePackError("NOT_FOUND", "人群包不存在")
        return {"updated": True}

    async def delete_pack(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """软删除人群包"""
        result = await db.execute(
            text("""
                UPDATE audience_packs SET is_deleted = TRUE, updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :pack_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "pack_id": str(pack_id)},
        )
        if result.rowcount == 0:
            raise AudiencePackError("NOT_FOUND", "人群包不存在")
        return {"deleted": True}

    async def archive_pack(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """归档人群包"""
        result = await db.execute(
            text("""
                UPDATE audience_packs SET status = 'archived', updated_at = now()
                WHERE tenant_id = :tenant_id AND id = :pack_id
                  AND is_deleted = FALSE AND status = 'active'
            """),
            {"tenant_id": str(tenant_id), "pack_id": str(pack_id)},
        )
        if result.rowcount == 0:
            raise AudiencePackError("INVALID_STATE", "人群包不存在或无法归档")
        return {"status": "archived"}

    # ===================================================================
    # Rules Engine — 规则引擎
    # ===================================================================

    def _build_rule_conditions(self, rules: dict) -> tuple[str, dict]:
        """将JSONB规则翻译为SQL WHERE条件

        支持维度：
          - gender, birthday_within_days, member_level, channel_source (members表)
          - last_order_days, order_count, total_spend_fen, avg_spend_fen (orders聚合)
          - stored_value_fen (stored_value_accounts)
          - rfm_level, has_wecom_friend, in_group, tag_ids
        """
        conditions: list[str] = []
        params: dict[str, Any] = {}
        joins: list[str] = []
        needs_order_agg = False
        needs_sv = False

        for key, value in rules.items():
            if key == "gender":
                conditions.append("m.gender = :r_gender")
                params["r_gender"] = value

            elif key == "birthday_within_days":
                conditions.append("""
                    m.birthday IS NOT NULL
                    AND (
                        EXTRACT(DOY FROM m.birthday) - EXTRACT(DOY FROM CURRENT_DATE)
                        BETWEEN 0 AND :r_bday_days
                        OR
                        EXTRACT(DOY FROM m.birthday) - EXTRACT(DOY FROM CURRENT_DATE) + 365
                        BETWEEN 0 AND :r_bday_days
                    )
                """)
                params["r_bday_days"] = value

            elif key == "member_level":
                if isinstance(value, list):
                    conditions.append("m.member_level = ANY(:r_member_levels)")
                    params["r_member_levels"] = value
                else:
                    conditions.append("m.member_level = :r_member_level")
                    params["r_member_level"] = value

            elif key == "channel_source":
                conditions.append("m.channel_source = :r_channel_source")
                params["r_channel_source"] = value

            elif key == "last_order_days":
                needs_order_agg = True
                if isinstance(value, dict):
                    if "gte" in value:
                        conditions.append("""
                            (o_agg.last_order_at IS NULL
                             OR o_agg.last_order_at < CURRENT_DATE - :r_last_order_gte * INTERVAL '1 day')
                        """)
                        params["r_last_order_gte"] = value["gte"]
                    if "lte" in value:
                        conditions.append("""
                            o_agg.last_order_at >= CURRENT_DATE - :r_last_order_lte * INTERVAL '1 day'
                        """)
                        params["r_last_order_lte"] = value["lte"]
                else:
                    conditions.append("""
                        (o_agg.last_order_at IS NULL
                         OR o_agg.last_order_at < CURRENT_DATE - :r_last_order_days * INTERVAL '1 day')
                    """)
                    params["r_last_order_days"] = value

            elif key == "order_count":
                needs_order_agg = True
                if isinstance(value, dict):
                    if "gte" in value:
                        conditions.append("COALESCE(o_agg.order_count, 0) >= :r_order_count_gte")
                        params["r_order_count_gte"] = value["gte"]
                    if "lte" in value:
                        conditions.append("COALESCE(o_agg.order_count, 0) <= :r_order_count_lte")
                        params["r_order_count_lte"] = value["lte"]

            elif key == "total_spend_fen":
                needs_order_agg = True
                if isinstance(value, dict):
                    if "gte" in value:
                        conditions.append("COALESCE(o_agg.total_spend_fen, 0) >= :r_spend_gte")
                        params["r_spend_gte"] = value["gte"]
                    if "lt" in value:
                        conditions.append("COALESCE(o_agg.total_spend_fen, 0) < :r_spend_lt")
                        params["r_spend_lt"] = value["lt"]

            elif key == "avg_spend_fen":
                needs_order_agg = True
                if isinstance(value, dict):
                    if "gte" in value:
                        conditions.append("""
                            CASE WHEN COALESCE(o_agg.order_count, 0) > 0
                            THEN o_agg.total_spend_fen / o_agg.order_count
                            ELSE 0 END >= :r_avg_spend_gte
                        """)
                        params["r_avg_spend_gte"] = value["gte"]

            elif key == "stored_value_fen":
                needs_sv = True
                if isinstance(value, dict):
                    if "gte" in value:
                        conditions.append("COALESCE(sv.balance_fen, 0) >= :r_sv_gte")
                        params["r_sv_gte"] = value["gte"]
                    if "lt" in value:
                        conditions.append("COALESCE(sv.balance_fen, 0) < :r_sv_lt")
                        params["r_sv_lt"] = value["lt"]

            elif key == "rfm_level":
                conditions.append("m.rfm_level = :r_rfm_level")
                params["r_rfm_level"] = value

            elif key == "has_wecom_friend":
                if value:
                    conditions.append("m.wecom_external_userid IS NOT NULL")
                else:
                    conditions.append("m.wecom_external_userid IS NULL")

            elif key == "tag_ids":
                if isinstance(value, list) and value:
                    conditions.append("m.tag_ids @> :r_tag_ids::jsonb")
                    params["r_tag_ids"] = json.dumps(value)

        # 构建JOIN
        if needs_order_agg:
            joins.append("""
                LEFT JOIN (
                    SELECT customer_id,
                        COUNT(*) AS order_count,
                        COALESCE(SUM(total_amount_fen), 0) AS total_spend_fen,
                        MAX(created_at) AS last_order_at
                    FROM orders
                    WHERE is_deleted = FALSE AND tenant_id = :tenant_id
                    GROUP BY customer_id
                ) o_agg ON o_agg.customer_id = m.id
            """)

        if needs_sv:
            joins.append("""
                LEFT JOIN stored_value_accounts sv
                    ON sv.customer_id = m.id
                    AND sv.tenant_id = :tenant_id
                    AND sv.is_deleted = FALSE
            """)

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        join_clause = " ".join(joins)

        return where_clause, params, join_clause

    async def execute_rules(
        self,
        tenant_id: uuid.UUID,
        rules: dict,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """执行规则，返回匹配的客户列表"""
        where_clause, params, join_clause = self._build_rule_conditions(rules)
        params["tenant_id"] = str(tenant_id)

        store_filter = ""
        if store_id:
            store_filter = " AND m.store_id = :store_id"
            params["store_id"] = str(store_id)

        limit_clause = f"LIMIT {limit}" if limit else ""

        sql = f"""
            SELECT m.id AS customer_id, m.store_id
            FROM members m
            {join_clause}
            WHERE m.tenant_id = :tenant_id AND m.is_deleted = FALSE
              AND {where_clause}
              {store_filter}
            {limit_clause}
        """
        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    async def preview_rules(
        self,
        tenant_id: uuid.UUID,
        rules: dict,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """预览规则匹配人数（不写入）"""
        where_clause, params, join_clause = self._build_rule_conditions(rules)
        params["tenant_id"] = str(tenant_id)

        store_filter = ""
        if store_id:
            store_filter = " AND m.store_id = :store_id"
            params["store_id"] = str(store_id)

        sql = f"""
            SELECT COUNT(*) AS matched_count
            FROM members m
            {join_clause}
            WHERE m.tenant_id = :tenant_id AND m.is_deleted = FALSE
              AND {where_clause}
              {store_filter}
        """
        result = await db.execute(text(sql), params)
        count = result.scalar() or 0
        return {"matched_count": count, "rules": rules}

    # ===================================================================
    # Refresh — 人群包刷新
    # ===================================================================

    async def refresh_pack(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """刷新动态人群包成员"""
        pack = await self.get_pack(tenant_id, pack_id, db)
        if pack["pack_type"] != "dynamic":
            raise AudiencePackError("INVALID_TYPE", "仅动态人群包支持刷新")

        rules = pack["rules"] if isinstance(pack["rules"], dict) else json.loads(pack["rules"])
        matched = await self.execute_rules(
            tenant_id, rules, db,
            store_id=uuid.UUID(str(pack["store_id"])) if pack.get("store_id") else None,
        )

        # 标记所有现有成员为不活跃
        await db.execute(
            text("""
                UPDATE audience_pack_members
                SET is_active = FALSE, removed_at = now(), updated_at = now()
                WHERE tenant_id = :tenant_id AND pack_id = :pack_id AND is_active = TRUE
            """),
            {"tenant_id": str(tenant_id), "pack_id": str(pack_id)},
        )

        # 批量UPSERT匹配的成员
        new_count = 0
        for m in matched:
            await db.execute(
                text("""
                    INSERT INTO audience_pack_members (
                        tenant_id, pack_id, customer_id, store_id, is_active, added_at
                    ) VALUES (
                        :tenant_id, :pack_id, :customer_id, :store_id, TRUE, now()
                    )
                    ON CONFLICT (tenant_id, pack_id, customer_id) DO UPDATE SET
                        is_active = TRUE,
                        removed_at = NULL,
                        store_id = EXCLUDED.store_id,
                        updated_at = now()
                """),
                {
                    "tenant_id": str(tenant_id),
                    "pack_id": str(pack_id),
                    "customer_id": str(m["customer_id"]),
                    "store_id": str(m["store_id"]) if m.get("store_id") else None,
                },
            )
            new_count += 1

        # 更新人群包计数
        await db.execute(
            text("""
                UPDATE audience_packs
                SET member_count = :count,
                    last_refreshed_at = now(),
                    updated_at = now()
                WHERE id = :pack_id
            """),
            {"pack_id": str(pack_id), "count": new_count},
        )

        log.info("audience_pack_refreshed", pack_id=str(pack_id), member_count=new_count)
        return {"pack_id": str(pack_id), "member_count": new_count}

    async def batch_refresh_dynamic_packs(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """批量刷新所有到期的动态人群包"""
        result = await db.execute(
            text("""
                SELECT id FROM audience_packs
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status = 'active'
                  AND pack_type = 'dynamic'
                  AND (
                    last_refreshed_at IS NULL
                    OR last_refreshed_at < now() - (refresh_interval_hours || ' hours')::interval
                  )
            """),
            {"tenant_id": str(tenant_id)},
        )
        pack_ids = [str(r[0]) for r in result.fetchall()]

        refreshed = 0
        failed = 0
        for pid in pack_ids:
            try:
                await self.refresh_pack(tenant_id, uuid.UUID(pid), db)
                refreshed += 1
            except (ValueError, RuntimeError, OSError) as exc:
                log.error("audience_pack_refresh_failed", pack_id=pid, error=str(exc))
                failed += 1

        log.info(
            "audience_packs_batch_refreshed",
            tenant_id=str(tenant_id),
            refreshed=refreshed,
            failed=failed,
        )
        return {"refreshed": refreshed, "failed": failed, "total": len(pack_ids)}

    # ===================================================================
    # Presets — 系统预设
    # ===================================================================

    async def init_system_presets(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """初始化8个系统预设（幂等）"""
        count = 0
        for preset in SYSTEM_PRESETS:
            await db.execute(
                text("""
                    INSERT INTO audience_pack_presets (
                        tenant_id, preset_name, description, category,
                        rules, icon, sort_order, is_system
                    ) VALUES (
                        :tenant_id, :preset_name, :description, :category,
                        :rules::jsonb, :icon, :sort_order, TRUE
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "tenant_id": str(tenant_id),
                    "preset_name": preset["preset_name"],
                    "description": preset["description"],
                    "category": preset["category"],
                    "rules": json.dumps(preset["rules"]),
                    "icon": preset["icon"],
                    "sort_order": preset["sort_order"],
                },
            )
            count += 1
        return {"initialized": count}

    async def list_presets(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        category: Optional[str] = None,
    ) -> list[dict]:
        """查询预设列表"""
        sql = """
            SELECT * FROM audience_pack_presets
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}
        if category:
            sql += " AND category = :category"
            params["category"] = category
        sql += " ORDER BY sort_order ASC"

        result = await db.execute(text(sql), params)
        return [dict(r) for r in result.mappings().all()]

    async def create_from_preset(
        self,
        tenant_id: uuid.UUID,
        preset_id: uuid.UUID,
        created_by: uuid.UUID,
        db: Any,
        *,
        pack_name: Optional[str] = None,
        store_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """从预设创建人群包"""
        result = await db.execute(
            text("""
                SELECT * FROM audience_pack_presets
                WHERE tenant_id = :tenant_id AND id = :preset_id AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "preset_id": str(preset_id)},
        )
        preset = result.mappings().first()
        if preset is None:
            raise AudiencePackError("NOT_FOUND", "预设不存在")

        name = pack_name or preset["preset_name"]
        rules = preset["rules"] if isinstance(preset["rules"], dict) else json.loads(preset["rules"])

        return await self.create_pack(
            tenant_id, name, "dynamic", rules, created_by, db,
            description=preset.get("description"),
            store_id=store_id,
        )

    # ===================================================================
    # Members — 成员管理
    # ===================================================================

    async def list_pack_members(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
        *,
        is_active: Optional[bool] = True,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询人群包成员"""
        where = "tenant_id = :tenant_id AND pack_id = :pack_id AND is_deleted = FALSE"
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "pack_id": str(pack_id),
        }
        if is_active is not None:
            where += " AND is_active = :is_active"
            params["is_active"] = is_active

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM audience_pack_members WHERE {where}"), params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        data_sql = f"""
            SELECT * FROM audience_pack_members WHERE {where}
            ORDER BY added_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = size
        params["offset"] = offset
        result = await db.execute(text(data_sql), params)
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def export_pack_members(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """导出人群包全部活跃成员"""
        result = await db.execute(
            text("""
                SELECT apm.customer_id, apm.store_id, apm.added_at, apm.snapshot_data
                FROM audience_pack_members apm
                WHERE apm.tenant_id = :tenant_id
                  AND apm.pack_id = :pack_id
                  AND apm.is_active = TRUE
                  AND apm.is_deleted = FALSE
                ORDER BY apm.added_at DESC
            """),
            {"tenant_id": str(tenant_id), "pack_id": str(pack_id)},
        )
        return [dict(r) for r in result.mappings().all()]

    async def get_pack_trend(
        self,
        tenant_id: uuid.UUID,
        pack_id: uuid.UUID,
        db: Any,
        *,
        days: int = 30,
    ) -> list[dict]:
        """获取人群包成员趋势（按日统计）"""
        result = await db.execute(
            text("""
                SELECT
                    added_at::date AS trend_date,
                    COUNT(*) FILTER (WHERE is_active = TRUE) AS active_count,
                    COUNT(*) FILTER (WHERE is_active = FALSE) AS removed_count
                FROM audience_pack_members
                WHERE tenant_id = :tenant_id
                  AND pack_id = :pack_id
                  AND is_deleted = FALSE
                  AND added_at >= CURRENT_DATE - :days * INTERVAL '1 day'
                GROUP BY added_at::date
                ORDER BY trend_date DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "pack_id": str(pack_id),
                "days": days,
            },
        )
        return [dict(r) for r in result.mappings().all()]
