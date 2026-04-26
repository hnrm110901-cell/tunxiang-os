"""Forge 智能发现引擎 — 意图搜索 + Agent 组合推荐

职责：
  1. intent_search()          — 自然语言意图搜索
  2. record_click()           — 记录搜索点击
  3. get_search_analytics()   — 搜索行为分析
  4. create_combo()           — 创建 Agent 组合
  5. list_combos()            — 列出组合（支持角色筛选）
  6. get_combo()              — 获取组合详情
  7. get_role_recommendations() — 角色推荐
"""

from __future__ import annotations

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import APP_CATEGORIES

logger = structlog.get_logger(__name__)

# ── 意图 → 分类映射（关键词匹配占位，后续接 Claude 解析） ──────
_INTENT_KEYWORD_MAP: dict[str, list[str]] = {
    "supply_chain":  ["采购", "库存", "供应链", "进货", "配送", "仓库"],
    "delivery":      ["外卖", "配送", "骑手", "美团", "饿了么"],
    "finance":       ["财务", "发票", "对账", "税务", "报销", "成本"],
    "ai_addon":      ["AI", "智能", "预测", "推荐", "自动化", "机器人"],
    "iot":           ["IoT", "传感器", "温控", "摄像头", "设备"],
    "analytics":     ["报表", "分析", "数据", "仪表盘", "驾驶舱", "洞察"],
    "marketing":     ["营销", "优惠券", "活动", "私域", "会员", "促销"],
    "hr":            ["排班", "考勤", "薪资", "人力", "员工", "绩效"],
    "payment":       ["支付", "收银", "结算", "刷卡", "微信支付"],
    "compliance":    ["食安", "合规", "审计", "等保", "监管", "检查"],
}

# ── 角色定义 ──────────────────────────────────────────────────
TARGET_ROLES = {"品牌总监", "门店店长", "运营经理", "财务总监", "IT负责人", "供应链经理"}


class ForgeDiscoveryService:
    """智能发现引擎 — 意图搜索 + Agent 组合推荐"""

    # ── 1. 意图搜索 ─────────────────────────────────────────────
    async def intent_search(
        self,
        db: AsyncSession,
        *,
        query: str,
    ) -> dict:
        """自然语言搜索：关键词匹配意图 → 分类 → 搜索应用 + 组合。"""
        if not query or not query.strip():
            raise HTTPException(status_code=422, detail="搜索关键词不能为空")

        # 1. 关键词匹配意图（placeholder for Claude intent parsing）
        matched_categories: list[str] = []
        for category, keywords in _INTENT_KEYWORD_MAP.items():
            for kw in keywords:
                if kw.lower() in query.lower():
                    matched_categories.append(category)
                    break

        intents = [
            {"category": cat, "category_name": APP_CATEGORIES.get(cat, {}).get("name", cat)}
            for cat in matched_categories
        ]

        # 2. 搜索应用：按分类 + ILIKE 描述
        params: dict = {"query": f"%{query}%"}
        category_filter = ""
        if matched_categories:
            category_filter = "OR a.category = ANY(:categories)"
            params["categories"] = matched_categories

        apps_result = await db.execute(
            text(f"""
                SELECT a.app_id, a.app_name, a.category, a.description,
                       a.pricing_model, a.rating, a.install_count,
                       a.icon_url
                FROM forge_apps a
                WHERE a.is_deleted = false
                  AND a.status = 'published'
                  AND (
                      a.app_name ILIKE :query
                      OR a.description ILIKE :query
                      {category_filter}
                  )
                ORDER BY a.install_count DESC
                LIMIT 20
            """),
            params,
        )
        apps = [dict(r) for r in apps_result.mappings().all()]

        # 3. 搜索匹配的 Agent 组合
        combos_result = await db.execute(
            text("""
                SELECT combo_id, combo_name, description, use_case,
                       target_role, synergy_score
                FROM forge_app_combos
                WHERE is_active = true
                  AND (
                      combo_name ILIKE :query
                      OR description ILIKE :query
                      OR use_case ILIKE :query
                  )
                ORDER BY synergy_score DESC
                LIMIT 5
            """),
            {"query": f"%{query}%"},
        )
        combos = [dict(r) for r in combos_result.mappings().all()]

        # 4. 记录搜索意图
        search_id = f"si_{uuid4().hex[:12]}"
        await db.execute(
            text("""
                INSERT INTO forge_search_intents
                    (search_id, query, matched_categories, result_count)
                VALUES
                    (:search_id, :query, :categories::jsonb, :result_count)
            """),
            {
                "search_id": search_id,
                "query": query,
                "categories": json.dumps(matched_categories),
                "result_count": len(apps),
            },
        )
        await db.commit()

        logger.info(
            "intent_search",
            search_id=search_id,
            query=query,
            intent_count=len(intents),
            app_count=len(apps),
            combo_count=len(combos),
        )

        return {
            "search_id": search_id,
            "query": query,
            "intents": intents,
            "apps": apps,
            "combos": combos,
        }

    # ── 2. 记录搜索点击 ────────────────────────────────────────
    async def record_click(
        self,
        db: AsyncSession,
        search_id: str,
        *,
        clicked_app_id: str,
    ) -> dict:
        """记录用户在搜索结果中点击了哪个应用。"""
        result = await db.execute(
            text("""
                UPDATE forge_search_intents
                SET clicked_app_id = :clicked_app_id,
                    clicked_at = NOW()
                WHERE search_id = :search_id
                RETURNING search_id, query, clicked_app_id, clicked_at
            """),
            {"search_id": search_id, "clicked_app_id": clicked_app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"搜索记录不存在: {search_id}")

        await db.commit()
        return dict(row)

    # ── 3. 搜索分析 ────────────────────────────────────────────
    async def get_search_analytics(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
    ) -> dict:
        """汇总搜索行为：搜索量、CTR、热门查询、零结果查询。"""
        params: dict = {"days": days}

        # 总量 + CTR
        summary_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                            AS total_searches,
                    COUNT(clicked_app_id)                               AS total_clicks,
                    ROUND(
                        COUNT(clicked_app_id)::numeric / NULLIF(COUNT(*), 0) * 100, 2
                    )                                                   AS ctr_pct
                FROM forge_search_intents
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
            """),
            params,
        )
        summary = dict(summary_result.mappings().one())

        # 热门查询 Top 10
        top_queries_result = await db.execute(
            text("""
                SELECT query, COUNT(*) AS search_count
                FROM forge_search_intents
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
                GROUP BY query
                ORDER BY search_count DESC
                LIMIT 10
            """),
            params,
        )
        top_queries = [dict(r) for r in top_queries_result.mappings().all()]

        # 热门点击 App Top 10
        top_clicks_result = await db.execute(
            text("""
                SELECT clicked_app_id, COUNT(*) AS click_count
                FROM forge_search_intents
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
                  AND clicked_app_id IS NOT NULL
                GROUP BY clicked_app_id
                ORDER BY click_count DESC
                LIMIT 10
            """),
            params,
        )
        top_clicked_apps = [dict(r) for r in top_clicks_result.mappings().all()]

        # 零结果查询
        zero_result_queries = await db.execute(
            text("""
                SELECT query, COUNT(*) AS search_count
                FROM forge_search_intents
                WHERE created_at >= NOW() - MAKE_INTERVAL(days => :days)
                  AND result_count = 0
                GROUP BY query
                ORDER BY search_count DESC
                LIMIT 10
            """),
            params,
        )
        zero_results = [dict(r) for r in zero_result_queries.mappings().all()]

        return {
            **summary,
            "days": days,
            "top_queries": top_queries,
            "top_clicked_apps": top_clicked_apps,
            "zero_result_queries": zero_results,
        }

    # ── 4. 创建 Agent 组合 ─────────────────────────────────────
    async def create_combo(
        self,
        db: AsyncSession,
        *,
        combo_name: str,
        description: str,
        app_ids: list[str],
        use_case: str,
        target_role: str = "",
        synergy_score: float = 0,
        evidence: dict | None = None,
    ) -> dict:
        """创建 Agent 组合推荐包。"""
        if evidence is None:
            evidence = {}

        if not app_ids:
            raise HTTPException(status_code=422, detail="app_ids 不能为空")

        # 验证所有 app_id 存在
        check_result = await db.execute(
            text("""
                SELECT app_id FROM forge_apps
                WHERE app_id = ANY(:app_ids) AND is_deleted = false
            """),
            {"app_ids": app_ids},
        )
        found_ids = {r["app_id"] for r in check_result.mappings().all()}
        missing = set(app_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"以下应用不存在: {sorted(missing)}",
            )

        combo_id = f"combo_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_app_combos
                    (combo_id, combo_name, description, app_ids,
                     use_case, target_role, synergy_score, evidence)
                VALUES
                    (:combo_id, :combo_name, :description, :app_ids::jsonb,
                     :use_case, :target_role, :synergy_score, :evidence::jsonb)
                RETURNING combo_id, combo_name, description, app_ids,
                          use_case, target_role, synergy_score,
                          is_active, created_at
            """),
            {
                "combo_id": combo_id,
                "combo_name": combo_name,
                "description": description,
                "app_ids": json.dumps(app_ids),
                "use_case": use_case,
                "target_role": target_role,
                "synergy_score": synergy_score,
                "evidence": json.dumps(evidence, ensure_ascii=False),
            },
        )
        row = dict(result.mappings().one())
        await db.commit()

        logger.info(
            "combo_created",
            combo_id=combo_id,
            app_count=len(app_ids),
            target_role=target_role,
        )
        return row

    # ── 5. 列出组合 ────────────────────────────────────────────
    async def list_combos(
        self,
        db: AsyncSession,
        *,
        target_role: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页列出 Agent 组合，含关联应用详情。"""
        clauses: list[str] = ["c.is_active = true"]
        params: dict = {}

        if target_role:
            clauses.append("c.target_role = :target_role")
            params["target_role"] = target_role

        where = "WHERE " + " AND ".join(clauses)
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        # 总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_app_combos c {where}"),
            params,
        )
        total = count_result.scalar_one()

        # 数据
        result = await db.execute(
            text(f"""
                SELECT c.combo_id, c.combo_name, c.description, c.app_ids,
                       c.use_case, c.target_role, c.synergy_score, c.created_at
                FROM forge_app_combos c
                {where}
                ORDER BY c.synergy_score DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        combos = [dict(r) for r in result.mappings().all()]

        # 批量查询关联应用详情
        all_app_ids: list[str] = []
        for combo in combos:
            ids = combo.get("app_ids") or []
            if isinstance(ids, str):
                ids = json.loads(ids)
            all_app_ids.extend(ids)

        app_map: dict[str, dict] = {}
        if all_app_ids:
            apps_result = await db.execute(
                text("""
                    SELECT app_id, app_name, category, icon_url, rating
                    FROM forge_apps
                    WHERE app_id = ANY(:app_ids) AND is_deleted = false
                """),
                {"app_ids": list(set(all_app_ids))},
            )
            for app_row in apps_result.mappings().all():
                app_map[app_row["app_id"]] = dict(app_row)

        # 填充应用详情
        for combo in combos:
            ids = combo.get("app_ids") or []
            if isinstance(ids, str):
                ids = json.loads(ids)
            combo["apps"] = [app_map[aid] for aid in ids if aid in app_map]

        return {"items": combos, "total": total, "page": page, "size": size}

    # ── 6. 获取组合详情 ────────────────────────────────────────
    async def get_combo(
        self,
        db: AsyncSession,
        combo_id: str,
    ) -> dict:
        """获取单个组合的完整信息（含应用详情）。"""
        result = await db.execute(
            text("""
                SELECT combo_id, combo_name, description, app_ids,
                       use_case, target_role, synergy_score,
                       evidence, is_active, created_at
                FROM forge_app_combos
                WHERE combo_id = :combo_id
            """),
            {"combo_id": combo_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"组合不存在: {combo_id}")

        combo = dict(row)
        app_ids = combo.get("app_ids") or []
        if isinstance(app_ids, str):
            app_ids = json.loads(app_ids)

        # 查关联应用
        if app_ids:
            apps_result = await db.execute(
                text("""
                    SELECT app_id, app_name, category, description,
                           pricing_model, rating, install_count, icon_url
                    FROM forge_apps
                    WHERE app_id = ANY(:app_ids) AND is_deleted = false
                """),
                {"app_ids": app_ids},
            )
            combo["apps"] = [dict(r) for r in apps_result.mappings().all()]
        else:
            combo["apps"] = []

        return combo

    # ── 7. 角色推荐 ────────────────────────────────────────────
    async def get_role_recommendations(
        self,
        db: AsyncSession,
        role: str,
    ) -> dict:
        """基于角色推荐 Agent 组合 + 热门单应用。"""
        # 角色组合
        combos_result = await db.execute(
            text("""
                SELECT combo_id, combo_name, description, app_ids,
                       use_case, synergy_score
                FROM forge_app_combos
                WHERE target_role = :role AND is_active = true
                ORDER BY synergy_score DESC
                LIMIT 5
            """),
            {"role": role},
        )
        combos = [dict(r) for r in combos_result.mappings().all()]

        # 角色热门单应用（按安装量）
        # 根据角色映射分类
        role_category_map: dict[str, list[str]] = {
            "品牌总监":   ["analytics", "marketing", "ai_addon"],
            "门店店长":   ["iot", "hr", "compliance"],
            "运营经理":   ["analytics", "supply_chain", "hr"],
            "财务总监":   ["finance", "analytics", "payment"],
            "IT负责人":   ["ai_addon", "iot", "compliance"],
            "供应链经理": ["supply_chain", "finance", "analytics"],
        }
        categories = role_category_map.get(role, [])

        top_apps: list[dict] = []
        if categories:
            apps_result = await db.execute(
                text("""
                    SELECT app_id, app_name, category, description,
                           pricing_model, rating, install_count, icon_url
                    FROM forge_apps
                    WHERE category = ANY(:categories)
                      AND is_deleted = false
                      AND status = 'published'
                    ORDER BY install_count DESC
                    LIMIT 10
                """),
                {"categories": categories},
            )
            top_apps = [dict(r) for r in apps_result.mappings().all()]

        return {
            "role": role,
            "combos": combos,
            "top_apps": top_apps,
            "suggested_categories": [
                {"category": cat, "name": APP_CATEGORIES.get(cat, {}).get("name", cat)}
                for cat in categories
            ],
        }
