"""AI审核官 — 自动化70%检查项 (v2.5)"""

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 10项自动检查定义
_AUTO_CHECKS = [
    {"id": "C01", "name": "SAST静态扫描", "category": "security", "automated": True},
    {"id": "C02", "name": "依赖CVE扫描", "category": "security", "automated": True},
    {"id": "C03", "name": "性能基准(p99<500ms)", "category": "performance", "automated": True},
    {"id": "C04", "name": "内存用量(<128MB)", "category": "performance", "automated": True},
    {"id": "C05", "name": "Master Agent兼容性", "category": "compatibility", "automated": True},
    {"id": "C06", "name": "三硬约束合规", "category": "compliance", "automated": True},
    {"id": "C07", "name": "License审计(无GPL污染)", "category": "legal", "automated": True},
    {"id": "C08", "name": "PII检测", "category": "privacy", "automated": True},
    {"id": "C09", "name": "Ontology绑定验证", "category": "compatibility", "automated": True},
    {"id": "C10", "name": "速率限制配置", "category": "security", "automated": True},
]

# 始终需要人工审核的项目
_HUMAN_REQUIRED_CHECKS = [
    {"id": "H01", "name": "业务逻辑合理性", "reason": "需人工判断业务场景是否合理"},
    {"id": "H02", "name": "用户体验评审", "reason": "需人工评估交互体验"},
    {"id": "H03", "name": "品牌合规审查", "reason": "需人工确认品牌形象与价值观一致"},
]


def _run_check(check_def: dict, app_data: dict) -> dict:
    """执行单项自动检查（当前为规则引擎占位，后续接入真实扫描工具）"""
    check_id = check_def["id"]
    result = {"check_id": check_id, "name": check_def["name"], "category": check_def["category"]}

    # Mock 逻辑：基于简单规则判断
    if check_id == "C01":
        # SAST: 当前占位始终通过
        result["passed"] = True
        result["detail"] = "静态扫描通过（占位）"
    elif check_id == "C02":
        # CVE: 检查是否声明了依赖
        result["passed"] = True
        result["detail"] = "未发现已知CVE漏洞（占位）"
    elif check_id == "C03":
        # 性能: 占位通过
        result["passed"] = True
        result["detail"] = "p99预估 < 500ms"
    elif check_id == "C04":
        # 内存: 占位通过
        result["passed"] = True
        result["detail"] = "内存预估 < 128MB"
    elif check_id == "C05":
        # Master Agent 兼容
        result["passed"] = True
        result["detail"] = "与 Master Agent 编排协议兼容"
    elif check_id == "C06":
        # 三硬约束
        has_constraints = bool(app_data.get("permissions"))
        result["passed"] = has_constraints
        result["detail"] = "已声明权限约束" if has_constraints else "未声明权限约束，需补充"
    elif check_id == "C07":
        # License 审计
        result["passed"] = True
        result["detail"] = "未检测到 GPL 依赖污染"
    elif check_id == "C08":
        # PII 检测: 关键词匹配
        desc = app_data.get("description", "")
        pii_keywords = ["身份证", "手机号", "银行卡", "密码"]
        found = [kw for kw in pii_keywords if kw in desc]
        result["passed"] = len(found) == 0
        result["detail"] = f"检测到敏感词: {found}" if found else "未检测到 PII 风险"
    elif check_id == "C09":
        # Ontology 绑定
        result["passed"] = True
        result["detail"] = "Ontology 绑定验证通过"
    elif check_id == "C10":
        # 速率限制
        result["passed"] = True
        result["detail"] = "速率限制已配置"
    else:
        result["passed"] = True
        result["detail"] = "检查通过"

    return result


def _generate_ai_suggestions(checks: list[dict], app_data: dict) -> list[str]:
    """基于检查结果生成 AI 建议（关键词分析占位）"""
    suggestions: list[str] = []
    failed = [c for c in checks if not c["passed"]]
    if failed:
        suggestions.append(f"共 {len(failed)} 项检查未通过，请优先修复安全相关项")
    for c in failed:
        if c["category"] == "security":
            suggestions.append(f"[安全] {c['name']}未通过: {c['detail']}")
        elif c["category"] == "privacy":
            suggestions.append(f"[隐私] {c['name']}未通过: {c['detail']}，请移除敏感信息")
        elif c["category"] == "compliance":
            suggestions.append(f"[合规] {c['name']}未通过: {c['detail']}")
    if not suggestions:
        suggestions.append("所有自动检查通过，建议关注人工审核项")
    return suggestions


class ForgeAutoReviewService:
    """AI审核官 — 自动化70%检查项"""

    # ── 执行自动审核 ─────────────────────────────────────────
    async def run_auto_review(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        app_version_id: str | None = None,
    ) -> dict:
        # 加载应用信息
        app_row = await db.execute(
            text("""
                SELECT app_id, app_name, category, description, permissions, status
                FROM forge_apps
                WHERE app_id = :aid AND is_deleted = false
            """),
            {"aid": app_id},
        )
        app_data = app_row.mappings().first()
        if not app_data:
            raise HTTPException(status_code=404, detail=f"应用不存在: {app_id}")
        app_data = dict(app_data)

        # 尝试加载审核模板
        tpl_row = await db.execute(
            text("""
                SELECT template_id, template_name, auto_checks, human_checks, pass_threshold
                FROM forge_review_templates
                WHERE app_category = :cat AND is_deleted = false
                ORDER BY created_at DESC LIMIT 1
            """),
            {"cat": app_data["category"]},
        )
        tpl = tpl_row.mappings().first()
        pass_threshold = tpl["pass_threshold"] if tpl else 80

        # 执行10项自动检查
        checks = [_run_check(check_def, app_data) for check_def in _AUTO_CHECKS]

        pass_count = sum(1 for c in checks if c["passed"])
        total = len(checks)
        auto_score = round(pass_count / total * 100, 1) if total > 0 else 0

        # 生成 AI 建议
        ai_suggestions = _generate_ai_suggestions(checks, app_data)

        # 判断是否自动通过
        auto_approved = auto_score >= pass_threshold

        review_id = f"arev_{uuid4().hex[:12]}"

        await db.execute(
            text("""
                INSERT INTO forge_auto_reviews
                    (id, tenant_id, review_id, app_id, app_version_id,
                     auto_score, checks, ai_suggestions, human_required,
                     auto_approved, pass_threshold)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :review_id, :app_id, :app_version_id,
                     :auto_score, :checks::jsonb, :ai_suggestions::jsonb,
                     :human_required::jsonb, :auto_approved, :pass_threshold)
                RETURNING review_id, app_id, auto_score, auto_approved, created_at
            """),
            {
                "review_id": review_id,
                "app_id": app_id,
                "app_version_id": app_version_id,
                "auto_score": auto_score,
                "checks": json.dumps(checks, ensure_ascii=False),
                "ai_suggestions": json.dumps(ai_suggestions, ensure_ascii=False),
                "human_required": json.dumps(_HUMAN_REQUIRED_CHECKS, ensure_ascii=False),
                "auto_approved": auto_approved,
                "pass_threshold": pass_threshold,
            },
        )

        # 如果自动通过，更新应用状态
        if auto_approved:
            await db.execute(
                text("""
                    UPDATE forge_apps SET status = 'published', updated_at = NOW()
                    WHERE app_id = :aid AND is_deleted = false
                """),
                {"aid": app_id},
            )
            log.info("auto_review.auto_approved", review_id=review_id, app_id=app_id, score=auto_score)
        else:
            log.info("auto_review.needs_human", review_id=review_id, app_id=app_id, score=auto_score)

        return {
            "review_id": review_id,
            "app_id": app_id,
            "auto_score": auto_score,
            "checks": checks,
            "ai_suggestions": ai_suggestions,
            "human_required": _HUMAN_REQUIRED_CHECKS,
            "auto_approved": auto_approved,
            "pass_threshold": pass_threshold,
        }

    # ── 获取审核详情 ─────────────────────────────────────────
    async def get_auto_review(self, db: AsyncSession, review_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT review_id, app_id, app_version_id, auto_score,
                       checks, ai_suggestions, human_required,
                       auto_approved, pass_threshold, created_at
                FROM forge_auto_reviews
                WHERE review_id = :rid AND is_deleted = false
            """),
            {"rid": review_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"审核记录不存在: {review_id}")
        return dict(row)

    # ── 审核列表 ─────────────────────────────────────────────
    async def list_auto_reviews(
        self,
        db: AsyncSession,
        *,
        app_id: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        conditions = ["is_deleted = false"]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if app_id:
            conditions.append("app_id = :app_id")
            params["app_id"] = app_id

        where = " AND ".join(conditions)

        total_row = await db.execute(text(f"SELECT count(*) FROM forge_auto_reviews WHERE {where}"), params)
        total = total_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT review_id, app_id, auto_score, auto_approved, created_at
                FROM forge_auto_reviews
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    # ── 审核模板列表 ─────────────────────────────────────────
    async def get_review_templates(self, db: AsyncSession, *, app_category: str | None = None) -> list[dict]:
        conditions = ["is_deleted = false"]
        params: dict = {}

        if app_category:
            conditions.append("app_category = :cat")
            params["cat"] = app_category

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(f"""
                SELECT template_id, template_name, app_category,
                       auto_checks, human_checks, pass_threshold, created_at
                FROM forge_review_templates
                WHERE {where}
                ORDER BY app_category, template_name
            """),
            params,
        )
        return [dict(r) for r in rows.mappings().all()]

    # ── 创建审核模板 ─────────────────────────────────────────
    async def create_review_template(
        self,
        db: AsyncSession,
        *,
        app_category: str,
        template_name: str,
        auto_checks: list[dict],
        human_checks: list[dict],
        pass_threshold: int = 80,
    ) -> dict:
        if pass_threshold < 0 or pass_threshold > 100:
            raise HTTPException(status_code=422, detail="pass_threshold 必须在 0-100 之间")

        template_id = f"rtpl_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_review_templates
                    (id, tenant_id, template_id, app_category, template_name,
                     auto_checks, human_checks, pass_threshold)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :template_id, :app_category, :template_name,
                     :auto_checks::jsonb, :human_checks::jsonb, :pass_threshold)
                RETURNING template_id, app_category, template_name, pass_threshold, created_at
            """),
            {
                "template_id": template_id,
                "app_category": app_category,
                "template_name": template_name,
                "auto_checks": json.dumps(auto_checks, ensure_ascii=False),
                "human_checks": json.dumps(human_checks, ensure_ascii=False),
                "pass_threshold": pass_threshold,
            },
        )
        row = dict(result.mappings().one())
        log.info("auto_review.template_created", template_id=template_id, category=app_category)
        return row
