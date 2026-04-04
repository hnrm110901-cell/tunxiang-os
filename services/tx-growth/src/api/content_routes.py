"""内容模板管理 API — prefix /api/v1/content

端点（5个）:
1. POST /api/v1/content/templates                创建内容模板
2. GET  /api/v1/content/templates                内容模板列表（支持 content_type 过滤）
3. GET  /api/v1/content/templates/{template_id}  模板详情
4. POST /api/v1/content/generate                 基于模板生成内容（变量填充）
5. GET  /api/v1/content/{template_id}/performance 模板使用统计

v144 表：content_templates
内置模板：首次请求时通过 UPSERT 写入 DB（幂等）
RLS 通过 set_config('app.tenant_id') 激活
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/content", tags=["growth-content"])

# ---------------------------------------------------------------------------
# 内置模板定义（首次使用时 UPSERT 到 DB，绑定 tenant_id）
# ---------------------------------------------------------------------------

_BUILTIN_TEMPLATES: dict[str, dict] = {
    "wecom_chat_retention": {
        "name": "企微留存话术",
        "content_type": "wecom_chat",
        "body_template": "{customer_name}您好！上次您点的{dish_name}，好多老客都说念念不忘呢～这周我们{event_or_benefit}，专门给您留了位子，方便的话提前跟我说一声哦😊",
        "variables": ["customer_name", "dish_name", "event_or_benefit"],
    },
    "wecom_chat_new_dish": {
        "name": "企微新品推荐",
        "content_type": "wecom_chat",
        "body_template": "{customer_name}～我们新上了一道{dish_name}，{dish_story}，还没正式推就被内部试吃会一抢而空了！本周到店优先为您预留一份，要来尝尝吗？",
        "variables": ["customer_name", "dish_name", "dish_story"],
    },
    "moments_seasonal": {
        "name": "朋友圈时令推广",
        "content_type": "moments",
        "body_template": "🌿 {season_theme}\n{dish_name} | {dish_description}\n主厨说：「{chef_quote}」\n📍 {store_name}·{store_address}\n🎁 {benefit_text}",
        "variables": ["season_theme", "dish_name", "dish_description", "chef_quote", "store_name", "store_address", "benefit_text"],
    },
    "sms_reactivation": {
        "name": "短信召回",
        "content_type": "sms",
        "body_template": "【{brand_name}】{customer_name}，好久没见到您了！我们为您准备了{offer_text}，{validity_text}。退订回T",
        "variables": ["brand_name", "customer_name", "offer_text", "validity_text"],
    },
    "miniapp_banner_promo": {
        "name": "小程序横幅促销",
        "content_type": "miniapp_banner",
        "body_template": "{headline}\n{sub_headline}\n{cta_text}",
        "variables": ["headline", "sub_headline", "cta_text"],
    },
    "dish_story_template": {
        "name": "菜品故事",
        "content_type": "dish_story",
        "body_template": "📖 {dish_name}的故事\n\n{origin_story}\n\n🔥 烹饪秘诀：{cooking_secret}\n\n💡 主厨推荐搭配：{pairing_suggestion}",
        "variables": ["dish_name", "origin_story", "cooking_secret", "pairing_suggestion"],
    },
    "referral_invite_template": {
        "name": "老带新邀请",
        "content_type": "referral_invite",
        "body_template": "我在{brand_name}发现了一家宝藏店！{dish_highlight}。分享给你{offer_text}，一起来尝尝？",
        "variables": ["brand_name", "dish_highlight", "offer_text"],
    },
    "banquet_invite_template": {
        "name": "宴会邀请",
        "content_type": "banquet_invite",
        "body_template": "尊敬的{customer_name}：\n\n{brand_name}诚邀您参加{event_name}。\n\n📅 时间：{event_date}\n📍 地点：{venue}\n🍽️ 菜单亮点：{menu_highlight}\n\n{benefit_text}\n\n期待您的光临！",
        "variables": ["customer_name", "brand_name", "event_name", "event_date", "venue", "menu_highlight", "benefit_text"],
    },
}

_VALID_CONTENT_TYPES = {
    "wecom_chat", "moments", "miniapp_banner", "sms",
    "dish_story", "new_dish_promo", "seasonal_event",
    "referral_invite", "store_manager_script", "banquet_invite",
}


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


async def _ensure_builtin_templates(db: AsyncSession, tid: uuid.UUID) -> None:
    """为当前租户 UPSERT 内置模板（幂等，首次调用时初始化）"""
    import json
    now = datetime.now(timezone.utc)
    for key, tpl in _BUILTIN_TEMPLATES.items():
        await db.execute(
            text("""
                INSERT INTO content_templates
                    (id, tenant_id, template_key, name, content_type,
                     body_template, variables, is_builtin, is_active,
                     usage_count, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid, :key, :name, :content_type,
                     :body, :variables::jsonb, true, true,
                     0, :now, :now)
                ON CONFLICT ON CONSTRAINT uq_content_templates_tenant_key DO NOTHING
            """),
            {
                "tid": tid,
                "key": key,
                "name": tpl["name"],
                "content_type": tpl["content_type"],
                "body": tpl["body_template"],
                "variables": json.dumps(tpl["variables"]),
                "now": now,
            },
        )


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class CreateTemplateRequest(BaseModel):
    name: str
    content_type: str
    body_template: str
    variables: list[str] = []

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in _VALID_CONTENT_TYPES:
            raise ValueError(f"content_type 须为 {_VALID_CONTENT_TYPES} 之一")
        return v

    @field_validator("body_template")
    @classmethod
    def validate_body(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body_template 不能为空")
        return v


class GenerateContentRequest(BaseModel):
    content_type: str
    template_id: Optional[str] = None   # 指定模板 ID；不传则自动选内置模板
    variables: dict = {}                # {"customer_name": "张三", "dish_name": "佛跳墙"}
    brand_id: Optional[str] = None
    target_segment: Optional[str] = None


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.post("/templates")
async def create_template(
    req: CreateTemplateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建自定义内容模板

    正文使用 {variable_name} 标记变量占位符，
    variables 列表声明模板中用到的所有变量名。
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        import json
        now = datetime.now(timezone.utc)
        new_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO content_templates
                    (id, tenant_id, template_key, name, content_type,
                     body_template, variables, is_builtin, is_active,
                     usage_count, created_at, updated_at)
                VALUES
                    (:id, :tid, null, :name, :content_type,
                     :body, :variables::jsonb, false, true,
                     0, :now, :now)
            """),
            {
                "id": new_id,
                "tid": tid,
                "name": req.name,
                "content_type": req.content_type,
                "body": req.body_template,
                "variables": json.dumps(req.variables),
                "now": now,
            },
        )
        await db.commit()

        logger.info(
            "content_template.created",
            template_id=str(new_id),
            content_type=req.content_type,
            tenant_id=x_tenant_id,
        )
        return ok_response({
            "template_id": str(new_id),
            "name": req.name,
            "content_type": req.content_type,
            "variables": req.variables,
            "is_builtin": False,
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("content_template.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "内容模板功能尚未初始化")
        logger.error("content_template.create_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "创建模板失败")


@router.get("/templates")
async def list_templates(
    content_type: Optional[str] = Query(default=None, description="按 content_type 过滤"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """内容模板列表（含内置 + 自定义）

    首次调用时自动初始化当前租户的内置模板。
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)

        # 确保内置模板已初始化
        try:
            await _ensure_builtin_templates(db, tid)
            await db.commit()
        except SQLAlchemyError as exc:
            if _is_table_missing(exc):
                logger.warning("content_template.table_not_ready", error=str(exc))
                return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
            await db.rollback()

        where_parts = ["tenant_id = :tid", "is_active = true", "is_deleted = false"]
        params: dict = {"tid": tid, "limit": size, "offset": (page - 1) * size}

        if content_type:
            if content_type not in _VALID_CONTENT_TYPES:
                return error_response("INVALID_TYPE", f"content_type 须为 {_VALID_CONTENT_TYPES} 之一")
            where_parts.append("content_type = :content_type")
            params["content_type"] = content_type

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM content_templates WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text(f"""
                SELECT id, template_key, name, content_type, body_template,
                       variables, is_builtin, usage_count, created_at, updated_at
                FROM content_templates
                WHERE {where_clause}
                ORDER BY is_builtin DESC, usage_count DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()
        items = [
            {
                "template_id": str(r.id),
                "template_key": r.template_key,
                "name": r.name,
                "content_type": r.content_type,
                "body_template": r.body_template,
                "variables": r.variables if isinstance(r.variables, list) else [],
                "is_builtin": r.is_builtin,
                "usage_count": r.usage_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
        return ok_response({"items": items, "total": int(total), "page": page, "size": size})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("content_template.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
        logger.error("content_template.list_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询模板列表失败")


@router.post("/generate")
async def generate_content(
    req: GenerateContentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """基于模板生成内容（变量填充）

    流程：
    1. 若指定 template_id 则使用该模板；否则按 content_type 选使用次数最高的模板
    2. 将 req.variables 填入模板变量，生成最终文本
    3. 递增 usage_count
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)

        # 查询模板
        if req.template_id:
            tpl_id = uuid.UUID(req.template_id)
            result = await db.execute(
                text("""
                    SELECT id, name, content_type, body_template, variables
                    FROM content_templates
                    WHERE id = :tid_tpl AND tenant_id = :tid AND is_active = true AND is_deleted = false
                    LIMIT 1
                """),
                {"tid_tpl": tpl_id, "tid": tid},
            )
        else:
            # 自动选 content_type 下 usage_count 最高的模板
            if req.content_type not in _VALID_CONTENT_TYPES:
                return error_response("INVALID_TYPE", f"content_type 须为 {_VALID_CONTENT_TYPES} 之一")
            result = await db.execute(
                text("""
                    SELECT id, name, content_type, body_template, variables
                    FROM content_templates
                    WHERE tenant_id = :tid AND content_type = :ctype
                      AND is_active = true AND is_deleted = false
                    ORDER BY usage_count DESC, is_builtin DESC
                    LIMIT 1
                """),
                {"tid": tid, "ctype": req.content_type},
            )

        row = result.fetchone()
        if not row:
            # 内置模板尚未初始化：触发初始化后重试
            try:
                await _ensure_builtin_templates(db, tid)
                await db.commit()
            except SQLAlchemyError as exc:
                if _is_table_missing(exc):
                    await db.rollback()
                    return error_response("TABLE_NOT_READY", "内容模板功能尚未初始化")
                raise
            return error_response(
                "TEMPLATE_NOT_FOUND",
                f"未找到 content_type={req.content_type} 的模板，内置模板已初始化，请重试",
            )

        # 变量替换
        body: str = row.body_template
        missing_vars: list[str] = []
        declared_vars: list[str] = row.variables if isinstance(row.variables, list) else []

        for var in declared_vars:
            placeholder = f"{{{var}}}"
            if placeholder in body:
                if var in req.variables:
                    body = body.replace(placeholder, str(req.variables[var]))
                else:
                    missing_vars.append(var)

        # 递增使用次数
        try:
            await db.execute(
                text("""
                    UPDATE content_templates
                    SET usage_count = usage_count + 1, updated_at = NOW()
                    WHERE id = :tpl_id AND tenant_id = :tid
                """),
                {"tpl_id": row.id, "tid": tid},
            )
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()

        return ok_response({
            "template_id": str(row.id),
            "template_name": row.name,
            "content_type": row.content_type,
            "generated_text": body,
            "missing_variables": missing_vars,
            "_note": "missing_variables 中的变量使用了占位符原文，请补充后重新生成" if missing_vars else "",
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("content_template.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "内容模板功能尚未初始化")
        logger.error("content_template.generate_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "生成内容失败")


@router.get("/{template_id}/performance")
async def get_template_performance(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """模板使用统计（usage_count + 基础元信息）"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        tpl_id = uuid.UUID(template_id)

        result = await db.execute(
            text("""
                SELECT id, name, content_type, is_builtin, usage_count, created_at, updated_at
                FROM content_templates
                WHERE id = :tpl_id AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"tpl_id": tpl_id, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return error_response("NOT_FOUND", f"模板不存在: {template_id}")

        return ok_response({
            "template_id": str(row.id),
            "template_name": row.name,
            "content_type": row.content_type,
            "is_builtin": row.is_builtin,
            "usage_count": row.usage_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_used_at": row.updated_at.isoformat() if row.updated_at else None,
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("content_template.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "内容模板功能尚未初始化")
        logger.error("content_template.performance_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询模板统计失败")


# ---------------------------------------------------------------------------
# 内容合规校验
# ---------------------------------------------------------------------------

_GENERAL_FORBIDDEN_WORDS = ["最低价", "保证", "100%", "绝对", "第一名", "全网最"]


class ValidateContentRequest(BaseModel):
    brand_id: str
    content_text: str


@router.post("/validate")
async def validate_content(
    req: ValidateContentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """品牌内容合规校验

    基础校验：
    - 内容长度（10–2000字符）
    - 广告法禁用词（最低价/保证/100%等）
    纯计算，不读写 DB。
    """
    errors: list[str] = []
    warnings: list[str] = []

    if len(req.content_text) > 2000:
        warnings.append("内容超过2000字符，建议精简")

    if len(req.content_text) < 10:
        errors.append("内容过短，不足10字符")

    for word in _GENERAL_FORBIDDEN_WORDS:
        if word in req.content_text:
            errors.append(f"包含广告法禁用词「{word}」")

    valid = len(errors) == 0
    logger.info(
        "content.validated",
        brand_id=req.brand_id,
        valid=valid,
        error_count=len(errors),
        tenant_id=x_tenant_id,
    )
    return ok_response({
        "valid": valid,
        "brand_id": req.brand_id,
        "errors": errors,
        "warnings": warnings,
    })
