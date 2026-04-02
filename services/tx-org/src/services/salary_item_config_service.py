"""门店级薪资项目配置服务 — store_salary_configs 异步读写。

金额单位：分（fen）。RLS：每次操作前设置 app.tenant_id，SQL 中显式带 tenant_id。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.salary_item_library import STORE_TEMPLATES, _ITEM_INDEX

log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _require_known_item(item_code: str) -> None:
    if item_code not in _ITEM_INDEX:
        raise ValueError(f"未知薪资项目编码: {item_code}")


async def enable_item(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    item_code: str,
    custom_value_fen: Optional[int] = None,
) -> None:
    """启用指定薪资项目；若已存在则更新为启用并可选更新自定义金额（分）。"""
    _require_known_item(item_code)
    await _set_tenant(db, tenant_id)
    await db.execute(
        text(
            """
            INSERT INTO store_salary_configs (
                id, tenant_id, store_id, item_code, enabled, custom_value_fen, created_at, updated_at
            )
            VALUES (
                :id, :tid, :sid, :code, TRUE, :cv, NOW(), NOW()
            )
            ON CONFLICT (tenant_id, store_id, item_code)
            DO UPDATE SET
                enabled = TRUE,
                custom_value_fen = COALESCE(EXCLUDED.custom_value_fen, store_salary_configs.custom_value_fen),
                updated_at = NOW()
            """
        ),
        {
            "id": uuid4(),
            "tid": tenant_id,
            "sid": store_id,
            "code": item_code,
            "cv": custom_value_fen,
        },
    )
    log.info(
        "salary_item_enabled",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        item_code=item_code,
        has_custom_value=custom_value_fen is not None,
    )


async def disable_item(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    item_code: str,
) -> None:
    """停用指定薪资项目。"""
    _require_known_item(item_code)
    await _set_tenant(db, tenant_id)
    await db.execute(
        text(
            """
            UPDATE store_salary_configs
            SET enabled = FALSE, updated_at = NOW()
            WHERE tenant_id = :tid AND store_id = :sid AND item_code = :code
            """
        ),
        {"tid": tenant_id, "sid": store_id, "code": item_code},
    )
    log.info(
        "salary_item_disabled",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        item_code=item_code,
    )


async def get_store_config(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
) -> List[Dict[str, Any]]:
    """查询门店当前已启用的薪资项目配置列表。"""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, store_id, item_code, enabled, custom_value_fen, created_at, updated_at
            FROM store_salary_configs
            WHERE tenant_id = :tid AND store_id = :sid AND enabled = TRUE
            ORDER BY item_code
            """
        ),
        {"tid": tenant_id, "sid": store_id},
    )
    rows = result.mappings().fetchall()
    return [dict(r) for r in rows]


async def batch_init_from_template(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    template: str,
) -> int:
    """按薪资模板批量写入/更新门店配置，返回成功处理的条目数。"""
    tpl = STORE_TEMPLATES.get(template)
    if tpl is None:
        raise ValueError(f"未知模板: {template}，可选: {list(STORE_TEMPLATES.keys())}")
    overrides: Dict[str, int] = dict(tpl.get("default_overrides", {}))
    codes: List[str] = list(tpl["enabled_items"])
    await _set_tenant(db, tenant_id)
    n = 0
    for code in codes:
        if code not in _ITEM_INDEX:
            log.warning(
                "salary_template_skip_unknown_code",
                template=template,
                item_code=code,
            )
            continue
        cv: Optional[int] = overrides.get(code)
        await db.execute(
            text(
                """
                INSERT INTO store_salary_configs (
                    id, tenant_id, store_id, item_code, enabled, custom_value_fen, created_at, updated_at
                )
                VALUES (
                    :id, :tid, :sid, :code, TRUE, :cv, NOW(), NOW()
                )
                ON CONFLICT (tenant_id, store_id, item_code)
                DO UPDATE SET
                    enabled = TRUE,
                    custom_value_fen = COALESCE(EXCLUDED.custom_value_fen, store_salary_configs.custom_value_fen),
                    updated_at = NOW()
                """
            ),
            {
                "id": uuid4(),
                "tid": tenant_id,
                "sid": store_id,
                "code": code,
                "cv": cv,
            },
        )
        n += 1
    log.info(
        "salary_batch_init_from_template",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        template=template,
        rows=n,
    )
    return n


async def update_item_value(
    db: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    item_code: str,
    custom_value_fen: int,
) -> None:
    """更新已存在行的自定义金额（分）。"""
    _require_known_item(item_code)
    await _set_tenant(db, tenant_id)
    res = await db.execute(
        text(
            """
            UPDATE store_salary_configs
            SET custom_value_fen = :cv, updated_at = NOW()
            WHERE tenant_id = :tid AND store_id = :sid AND item_code = :code
            RETURNING id
            """
        ),
        {"cv": custom_value_fen, "tid": tenant_id, "sid": store_id, "code": item_code},
    )
    if res.mappings().first() is None:
        raise ValueError(
            f"门店薪资配置中不存在该项目: store_id={store_id} item_code={item_code}"
        )
    log.info(
        "salary_item_value_updated",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        item_code=item_code,
    )
