"""应用管理服务 — PostgreSQL 异步实现"""

from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import APP_CATEGORIES, PRICING_MODELS

log = structlog.get_logger(__name__)


def _compute_price_display(pricing_model: str, price_fen: int) -> str:
    """根据定价模型和价格（分）生成展示文本"""
    if pricing_model == "free":
        return "免费"
    yuan = price_fen / 100
    label = PRICING_MODELS[pricing_model]["name"]
    if pricing_model == "one_time":
        return f"¥{yuan:.0f}"
    if pricing_model == "monthly":
        return f"¥{yuan:.0f}/月"
    if pricing_model == "per_store":
        return f"¥{yuan:.0f}/店/月"
    if pricing_model == "usage_based":
        return f"按用量 ¥{yuan:.0f}起"
    if pricing_model == "freemium":
        return f"免费增值 (Pro ¥{yuan:.0f}/月)"
    return f"{label} ¥{yuan:.0f}"


class ForgeAppService:
    """应用提交、更新、搜索、详情"""

    _ALLOWED_UPDATE_FIELDS = {
        "app_name",
        "description",
        "icon_url",
        "screenshots",
        "pricing_model",
        "price_fen",
        "permissions",
        "api_endpoints",
        "webhook_urls",
    }

    _SORT_MAP = {
        "popularity": "a.install_count DESC",
        "newest": "a.created_at DESC",
        "rating": "a.rating DESC",
        "price": "a.price_fen ASC",
    }

    # ── 提交应用 ─────────────────────────────────────────────
    async def submit_app(
        self,
        db: AsyncSession,
        *,
        developer_id: str,
        app_name: str,
        category: str,
        description: str,
        version: str,
        icon_url: str = "",
        screenshots: list[str] | None = None,
        pricing_model: str = "free",
        price_fen: int = 0,
        permissions: list[str] | None = None,
        api_endpoints: list[str] | None = None,
        webhook_urls: list[str] | None = None,
    ) -> dict:
        # ── 校验 ──
        if category not in APP_CATEGORIES:
            raise HTTPException(
                status_code=422,
                detail=f"无效分类: {category}，可选: {sorted(APP_CATEGORIES)}",
            )
        if pricing_model not in PRICING_MODELS:
            raise HTTPException(
                status_code=422,
                detail=f"无效定价模型: {pricing_model}，可选: {sorted(PRICING_MODELS)}",
            )

        # ── 验证开发者存在 ──
        dev_check = await db.execute(
            text("SELECT 1 FROM forge_developers WHERE developer_id = :did AND is_deleted = false"),
            {"did": developer_id},
        )
        if not dev_check.first():
            raise HTTPException(status_code=404, detail=f"开发者不存在: {developer_id}")

        app_id = f"app_{uuid4().hex[:12]}"
        price_display = _compute_price_display(pricing_model, price_fen)

        # ── 插入应用 ──
        result = await db.execute(
            text("""
                INSERT INTO forge_apps
                    (id, tenant_id, app_id, developer_id, app_name, category,
                     description, icon_url, screenshots, pricing_model, price_fen,
                     price_display, permissions, api_endpoints, webhook_urls,
                     status, current_version)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :app_id, :developer_id, :app_name, :category,
                     :description, :icon_url, :screenshots::jsonb, :pricing_model, :price_fen,
                     :price_display, :permissions::jsonb, :api_endpoints::jsonb, :webhook_urls::jsonb,
                     'pending_review', :version)
                RETURNING app_id, app_name, developer_id, category, status, created_at
            """),
            {
                "app_id": app_id,
                "developer_id": developer_id,
                "app_name": app_name,
                "category": category,
                "description": description,
                "icon_url": icon_url,
                "screenshots": _json_or_empty(screenshots),
                "pricing_model": pricing_model,
                "price_fen": price_fen,
                "price_display": price_display,
                "permissions": _json_or_empty(permissions),
                "api_endpoints": _json_or_empty(api_endpoints),
                "webhook_urls": _json_or_empty(webhook_urls),
                "version": version,
            },
        )
        app_row = dict(result.mappings().one())

        # ── 插入首个版本记录 ──
        await db.execute(
            text("""
                INSERT INTO forge_app_versions
                    (id, tenant_id, app_id, version, changelog, package_url,
                     package_hash, status, submitted_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :app_id, :version, '初始版本', '', '', 'submitted', NOW())
            """),
            {"app_id": app_id, "version": version},
        )

        log.info("app_submitted", app_id=app_id, category=category)
        return app_row

    # ── 更新应用 ─────────────────────────────────────────────
    async def update_app(self, db: AsyncSession, app_id: str, updates: dict) -> dict:
        filtered = {k: v for k, v in updates.items() if k in self._ALLOWED_UPDATE_FIELDS}
        if not filtered:
            raise HTTPException(
                status_code=422,
                detail=f"无有效更新字段，允许: {sorted(self._ALLOWED_UPDATE_FIELDS)}",
            )

        # JSONB 字段需要 cast
        jsonb_fields = {"screenshots", "permissions", "api_endpoints", "webhook_urls"}
        set_parts = []
        for k in filtered:
            if k in jsonb_fields:
                set_parts.append(f"{k} = :{k}::jsonb")
            else:
                set_parts.append(f"{k} = :{k}")

        # 如果定价相关字段变更，重新计算展示文本
        if "pricing_model" in filtered or "price_fen" in filtered:
            # 需要完整的 pricing_model 和 price_fen
            if "pricing_model" not in filtered or "price_fen" not in filtered:
                existing = await db.execute(
                    text("SELECT pricing_model, price_fen FROM forge_apps WHERE app_id = :aid AND is_deleted = false"),
                    {"aid": app_id},
                )
                row = existing.mappings().first()
                if not row:
                    raise HTTPException(status_code=404, detail=f"应用不存在: {app_id}")
                pm = filtered.get("pricing_model", row["pricing_model"])
                pf = filtered.get("price_fen", row["price_fen"])
            else:
                pm = filtered["pricing_model"]
                pf = filtered["price_fen"]

            if pm not in PRICING_MODELS:
                raise HTTPException(
                    status_code=422,
                    detail=f"无效定价模型: {pm}，可选: {sorted(PRICING_MODELS)}",
                )
            filtered["price_display"] = _compute_price_display(pm, pf)
            set_parts.append("price_display = :price_display")

        # 序列化 JSONB 值
        for k in jsonb_fields:
            if k in filtered:
                filtered[k] = _json_or_empty(filtered[k])

        set_clause = ", ".join(set_parts)
        filtered["aid"] = app_id

        result = await db.execute(
            text(f"""
                UPDATE forge_apps
                SET {set_clause}, updated_at = NOW()
                WHERE app_id = :aid AND is_deleted = false
                RETURNING app_id, app_name, category, description, icon_url,
                          pricing_model, price_fen, price_display, status,
                          updated_at
            """),
            filtered,
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"应用不存在: {app_id}")

        log.info("app_updated", app_id=app_id, fields=list(filtered.keys()))
        return dict(row)

    # ── 应用列表 ─────────────────────────────────────────────
    async def list_apps(
        self,
        db: AsyncSession,
        *,
        category: str | None = None,
        status: str | None = None,
        sort_by: str = "popularity",
        page: int = 1,
        size: int = 20,
    ) -> dict:
        where = "WHERE a.is_deleted = false"
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if category:
            where += " AND a.category = :category"
            params["category"] = category
        if status:
            where += " AND a.status = :status"
            params["status"] = status

        order = self._SORT_MAP.get(sort_by, "a.install_count DESC")

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_apps a {where}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT a.app_id, a.app_name, a.category, a.description,
                       a.icon_url, a.pricing_model, a.price_display,
                       a.rating, a.install_count, a.status, a.created_at
                FROM forge_apps a
                {where}
                ORDER BY {order}
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}

    # ── 应用详情 ─────────────────────────────────────────────
    async def get_app_detail(self, db: AsyncSession, app_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT
                    a.app_id, a.app_name, a.developer_id, a.category,
                    a.description, a.icon_url, a.screenshots,
                    a.pricing_model, a.price_fen, a.price_display,
                    a.permissions, a.api_endpoints, a.webhook_urls,
                    a.status, a.current_version, a.rating, a.rating_count,
                    a.install_count, a.published_at, a.created_at, a.updated_at,
                    d.name AS developer_name, d.company AS developer_company
                FROM forge_apps a
                LEFT JOIN forge_developers d ON d.developer_id = a.developer_id
                    AND d.is_deleted = false
                WHERE a.app_id = :aid AND a.is_deleted = false
            """),
            {"aid": app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"应用不存在: {app_id}")

        app_dict = dict(row)

        # 版本历史
        versions_result = await db.execute(
            text("""
                SELECT version, changelog, status, submitted_at, published_at
                FROM forge_app_versions
                WHERE app_id = :aid AND is_deleted = false
                ORDER BY submitted_at DESC
            """),
            {"aid": app_id},
        )
        app_dict["versions"] = [dict(v) for v in versions_result.mappings().all()]
        return app_dict

    # ── 搜索 ─────────────────────────────────────────────────
    async def search_apps(
        self,
        db: AsyncSession,
        query: str,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        like_pattern = f"%{query}%"
        params: dict = {
            "q": like_pattern,
            "limit": size,
            "offset": (page - 1) * size,
        }

        where = """
            WHERE a.is_deleted = false
              AND a.status IN ('published', 'approved')
              AND (a.app_name ILIKE :q OR a.description ILIKE :q)
        """

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_apps a {where}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT a.app_id, a.app_name, a.category, a.description,
                       a.icon_url, a.pricing_model, a.price_display,
                       a.rating, a.install_count, a.status
                FROM forge_apps a
                {where}
                ORDER BY a.install_count DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}


# ── 工具函数 ─────────────────────────────────────────────────


def _json_or_empty(val: list | None) -> str:
    """将 list 序列化为 JSON 字符串供 ::jsonb cast，None → '[]'"""
    import json

    if val is None:
        return "[]"
    return json.dumps(val, ensure_ascii=False)
