"""KDS显示配置服务 — 层级配置 + 做法过滤 + 表格模式

配置优先级：station > store > default。
UPSERT 语义保证幂等。
"""

import json
import uuid
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 默认 station_id 占位（用于 UNIQUE 约束中 COALESCE）
_NULL_STATION = "00000000-0000-0000-0000-000000000000"


class KdsDisplayConfigService:
    """KDS 显示配置服务"""

    # ── 获取配置（station > store > default 层级） ──────────

    @staticmethod
    async def get_display_config(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        station_id: Optional[str] = None,
        config_key: str,
    ) -> dict:
        """按层级获取配置：station级 → store级 → 系统默认。

        返回最匹配的一条配置及其来源层级。
        """
        # 查询所有匹配的配置（station + store 级）
        result = await db.execute(
            text("""
                SELECT id, station_id, config_key, config_value
                FROM kds_display_configs
                WHERE tenant_id  = :tenant_id
                  AND store_id   = :store_id
                  AND config_key = :config_key
                  AND is_deleted = FALSE
                ORDER BY station_id NULLS LAST
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "config_key": config_key},
        )
        rows = result.fetchall()

        # 匹配优先级：station_id 精确匹配 > store 级（station_id IS NULL）
        if station_id:
            for row in rows:
                if row.station_id and str(row.station_id) == station_id:
                    return {
                        "id": str(row.id),
                        "config_key": row.config_key,
                        "config_value": row.config_value,
                        "level": "station",
                        "station_id": station_id,
                    }

        # store 级
        for row in rows:
            if row.station_id is None:
                return {
                    "id": str(row.id),
                    "config_key": row.config_key,
                    "config_value": row.config_value,
                    "level": "store",
                    "station_id": None,
                }

        # 系统默认
        defaults = _get_system_defaults()
        if config_key in defaults:
            return {
                "id": None,
                "config_key": config_key,
                "config_value": defaults[config_key],
                "level": "default",
                "station_id": None,
            }

        return {
            "id": None,
            "config_key": config_key,
            "config_value": None,
            "level": "not_found",
            "station_id": None,
        }

    # ── 更新/创建配置（UPSERT） ──────────────────────────────

    @staticmethod
    async def update_config(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        station_id: Optional[str] = None,
        config_key: str,
        config_value: dict,
    ) -> dict:
        """UPSERT 配置项。

        使用 ON CONFLICT 在 UNIQUE(tenant_id, store_id, COALESCE(station_id,...), config_key) 上执行。
        """
        config_id = str(uuid.uuid4())
        result = await db.execute(
            text("""
                INSERT INTO kds_display_configs (
                    tenant_id, id, store_id, station_id, config_key, config_value
                ) VALUES (
                    :tenant_id, :id, :store_id, :station_id, :config_key, :config_value::JSONB
                )
                ON CONFLICT (
                    tenant_id,
                    store_id,
                    COALESCE(station_id, '00000000-0000-0000-0000-000000000000'::UUID),
                    config_key
                )
                DO UPDATE SET
                    config_value = EXCLUDED.config_value,
                    updated_at   = now()
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "id": config_id,
                "store_id": store_id,
                "station_id": station_id,
                "config_key": config_key,
                "config_value": json.dumps(config_value),
            },
        )
        row = result.fetchone()
        await db.commit()

        final_id = str(row.id) if row else config_id
        logger.info(
            "kds_display_config_upserted",
            config_id=final_id,
            config_key=config_key,
            station_id=station_id,
        )
        return {"id": final_id, "config_key": config_key, "upserted": True}

    # ── 做法过滤选项 ─────────────────────────────────────────

    @staticmethod
    async def get_practice_filter_options(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
    ) -> list[dict]:
        """获取门店所有可用的做法标签（用于KDS过滤面板）。

        从 kds_piecework_records 中提取 distinct practice_names。
        """
        result = await db.execute(
            text("""
                SELECT DISTINCT practice_names
                FROM kds_piecework_records
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND practice_names IS NOT NULL
                  AND practice_names != ''
                  AND is_deleted = FALSE
                ORDER BY practice_names
                LIMIT 200
            """),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        rows = result.fetchall()
        # 拆分逗号分隔的做法名称
        practice_set: set[str] = set()
        for row in rows:
            if row.practice_names:
                for p in row.practice_names.split(","):
                    p = p.strip()
                    if p:
                        practice_set.add(p)

        return [{"name": p} for p in sorted(practice_set)]

    # ── 做法组合过滤 ─────────────────────────────────────────

    @staticmethod
    async def get_practice_combo_filter(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        practices: list[str],
    ) -> list[dict]:
        """按做法组合过滤计件记录，返回匹配的菜品列表。"""
        if not practices:
            return []

        # 使用 LIKE 匹配任一做法
        conditions = []
        params: dict = {"tenant_id": tenant_id, "store_id": store_id}
        for i, practice in enumerate(practices):
            key = f"practice_{i}"
            conditions.append(f"practice_names LIKE :{key}")
            params[key] = f"%{practice}%"

        where_practices = " OR ".join(conditions)

        result = await db.execute(
            text(f"""
                SELECT DISTINCT dish_id, dish_name, practice_names
                FROM kds_piecework_records
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND ({where_practices})
                  AND is_deleted = FALSE
                ORDER BY dish_name
                LIMIT 100
            """),
            params,
        )
        rows = result.fetchall()
        return [
            {
                "dish_id": str(r.dish_id) if r.dish_id else None,
                "dish_name": r.dish_name,
                "practice_names": r.practice_names,
            }
            for r in rows
        ]

    # ── 表格模式数据 ─────────────────────────────────────────

    @staticmethod
    async def get_table_mode_data(
        db: AsyncSession,
        tenant_id: str,
        *,
        store_id: str,
        station_id: Optional[str] = None,
    ) -> dict:
        """获取KDS表格模式的全量配置数据。

        包括：当前配置、做法选项、汇总统计。
        """
        # 配置
        configs_result = await db.execute(
            text("""
                SELECT config_key, config_value, station_id
                FROM kds_display_configs
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND (station_id = :station_id OR station_id IS NULL)
                  AND is_deleted = FALSE
                ORDER BY station_id NULLS LAST
            """),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "station_id": station_id,
            },
        )
        configs_rows = configs_result.fetchall()

        # 去重（station 级优先）
        config_map: dict = {}
        for row in configs_rows:
            if row.config_key not in config_map:
                config_map[row.config_key] = {
                    "config_key": row.config_key,
                    "config_value": row.config_value,
                    "level": "station" if row.station_id else "store",
                }

        # 补充系统默认
        for key, value in _get_system_defaults().items():
            if key not in config_map:
                config_map[key] = {
                    "config_key": key,
                    "config_value": value,
                    "level": "default",
                }

        return {
            "store_id": store_id,
            "station_id": station_id,
            "configs": list(config_map.values()),
        }


def _get_system_defaults() -> dict:
    """系统默认配置"""
    return {
        "display_mode": {"mode": "card", "columns": 4},
        "auto_refresh_sec": {"value": 10},
        "font_size": {"value": "medium"},
        "color_scheme": {"urgent": "#FF4444", "normal": "#333333", "done": "#00AA00"},
        "show_practice": {"value": True},
        "show_timer": {"value": True},
        "sort_by": {"field": "created_at", "order": "asc"},
    }
