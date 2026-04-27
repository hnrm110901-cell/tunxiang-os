"""加购推荐话术生成服务 — 基于Claude API生成个性化加购文案

核心功能：
  1. generate_upsell_prompt — 为单个菜品对生成加购话术
  2. batch_generate_prompts — 批量生成高亲和菜品对的加购话术
  3. get_upsell_for_cart — 根据购物车返回最佳加购推荐+话术
  4. record_impression / record_conversion — 记录曝光/转化

数据源：
  dish_affinity_matrix — 亲和关系
  upsell_prompts — 话术存储
  dishes — 菜品信息
"""

import json
import os
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

log = structlog.get_logger(__name__)

# Claude API配置
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


async def _set_rls(db: Any, tenant_id: str) -> None:
    """设置RLS租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def _call_claude_api(prompt: str) -> str:
    """调用Claude API生成文案

    通过httpx异步调用Anthropic Messages API。
    生产环境应通过ModelRouter统一路由。
    """
    import httpx

    if not CLAUDE_API_KEY:
        log.warning("claude_api_key_missing", msg="ANTHROPIC_API_KEY未配置，返回默认话术")
        return ""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"].strip()
    except httpx.HTTPStatusError as exc:
        log.error("claude_api_http_error", status=exc.response.status_code)
        raise
    except httpx.RequestError as exc:
        log.error("claude_api_request_error", error=str(exc))
        raise


def _build_upsell_prompt(
    trigger_dish_name: str,
    suggest_dish_name: str,
    prompt_type: str,
    brand_style: str = "亲切专业",
) -> str:
    """构建Claude API的提示词"""
    type_desc = {
        "add_on": "搭配加购",
        "upgrade": "升级推荐",
        "combo": "组合优惠",
        "seasonal": "时令推荐",
        "popular": "人气必点",
    }
    scene = type_desc.get(prompt_type, "搭配加购")

    return (
        f"你是一个连锁餐饮品牌的菜品推荐文案专家。\n"
        f"风格要求：{brand_style}，简短有力，不超过30个字。\n"
        f"场景：顾客点了「{trigger_dish_name}」，请为「{suggest_dish_name}」写一条{scene}推荐话术。\n"
        f"只输出推荐话术文本，不要加引号或其他说明。"
    )


async def generate_upsell_prompt(
    db: Any,
    tenant_id: str,
    trigger_dish_id: str,
    suggest_dish_id: str,
    prompt_type: str = "add_on",
    store_id: Optional[str] = None,
) -> dict:
    """为单个菜品对生成加购话术并存储

    Returns: {id, trigger_dish_id, suggest_dish_id, prompt_text, prompt_type}
    """
    await _set_rls(db, tenant_id)

    try:
        # 获取菜品名称
        dish_result = await db.execute(
            text("""
                SELECT id, dish_name FROM dishes
                WHERE id IN (:trigger_id, :suggest_id)
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {
                "trigger_id": str(trigger_dish_id),
                "suggest_id": str(suggest_dish_id),
                "tenant_id": str(tenant_id),
            },
        )
        dish_map = {str(r["id"]): r["dish_name"] for r in dish_result.mappings().all()}

        trigger_name = dish_map.get(str(trigger_dish_id), "未知菜品")
        suggest_name = dish_map.get(str(suggest_dish_id), "未知菜品")

        # 调用Claude API生成话术
        api_prompt = _build_upsell_prompt(trigger_name, suggest_name, prompt_type)
        generated_text = await _call_claude_api(api_prompt)

        if not generated_text:
            generated_text = f"点了{trigger_name}，再来一份{suggest_name}更配哦~"

        # 存入数据库
        insert_result = await db.execute(
            text("""
                INSERT INTO upsell_prompts
                    (tenant_id, store_id, trigger_dish_id, suggest_dish_id,
                     prompt_text, prompt_type, metadata)
                VALUES
                    (:tenant_id, :store_id, :trigger_id, :suggest_id,
                     :prompt_text, :prompt_type, :metadata ::jsonb)
                RETURNING id, prompt_text, prompt_type, created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id) if store_id else None,
                "trigger_id": str(trigger_dish_id),
                "suggest_id": str(suggest_dish_id),
                "prompt_text": generated_text,
                "prompt_type": prompt_type,
                "metadata": json.dumps(
                    {
                        "trigger_dish_name": trigger_name,
                        "suggest_dish_name": suggest_name,
                        "model": CLAUDE_MODEL,
                    }
                ),
            },
        )
        row = insert_result.mappings().fetchone()
        await db.commit()

        log.info(
            "upsell_prompt_generated",
            tenant_id=str(tenant_id),
            trigger_dish=trigger_name,
            suggest_dish=suggest_name,
        )
        return {
            "id": str(row["id"]),
            "trigger_dish_id": str(trigger_dish_id),
            "suggest_dish_id": str(suggest_dish_id),
            "prompt_text": row["prompt_text"],
            "prompt_type": row["prompt_type"],
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("generate_upsell_db_error", error=str(exc))
        raise


async def batch_generate_prompts(
    db: Any,
    tenant_id: str,
    store_id: str,
    top_n: int = 20,
    period: str = "last_30d",
    prompt_type: str = "add_on",
) -> dict:
    """批量为亲和度最高的菜品对生成加购话术

    1. 从dish_affinity_matrix取top_n对
    2. 过滤已有话术的菜品对
    3. 逐对调用Claude生成话术

    Returns: {generated: int, skipped: int, errors: int}
    """
    await _set_rls(db, tenant_id)

    stats = {"generated": 0, "skipped": 0, "errors": 0}

    try:
        # 取高亲和菜品对
        affinity_result = await db.execute(
            text("""
                SELECT dam.dish_a_id, dam.dish_b_id, dam.affinity_score
                FROM dish_affinity_matrix dam
                WHERE dam.tenant_id = :tenant_id
                  AND dam.store_id = :store_id
                  AND dam.period = :period
                  AND dam.is_deleted = FALSE
                ORDER BY dam.affinity_score DESC
                LIMIT :top_n
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "period": period,
                "top_n": top_n,
            },
        )
        pairs = affinity_result.mappings().all()

        for pair in pairs:
            dish_a = str(pair["dish_a_id"])
            dish_b = str(pair["dish_b_id"])

            # 检查是否已有话术
            existing = await db.execute(
                text("""
                    SELECT id FROM upsell_prompts
                    WHERE tenant_id = :tenant_id
                      AND trigger_dish_id = :trigger_id
                      AND suggest_dish_id = :suggest_id
                      AND prompt_type = :prompt_type
                      AND is_deleted = FALSE
                    LIMIT 1
                """),
                {
                    "tenant_id": str(tenant_id),
                    "trigger_id": dish_a,
                    "suggest_id": dish_b,
                    "prompt_type": prompt_type,
                },
            )
            if existing.fetchone():
                stats["skipped"] += 1
                continue

            try:
                # A->B方向
                await generate_upsell_prompt(
                    db,
                    str(tenant_id),
                    dish_a,
                    dish_b,
                    prompt_type=prompt_type,
                    store_id=str(store_id),
                )
                stats["generated"] += 1

                # B->A方向
                await generate_upsell_prompt(
                    db,
                    str(tenant_id),
                    dish_b,
                    dish_a,
                    prompt_type=prompt_type,
                    store_id=str(store_id),
                )
                stats["generated"] += 1
            except (SQLAlchemyError, Exception) as exc:
                stats["errors"] += 1
                log.warning("batch_generate_pair_error", error=str(exc), dish_a=dish_a, dish_b=dish_b)

        log.info("batch_generate_done", tenant_id=str(tenant_id), **stats)
        return stats

    except SQLAlchemyError as exc:
        log.error("batch_generate_db_error", error=str(exc))
        raise


async def get_upsell_for_cart(
    db: Any,
    tenant_id: str,
    store_id: str,
    cart_dish_ids: list[str],
    limit: int = 3,
) -> list[dict]:
    """根据购物车已选菜品返回最佳加购推荐+话术

    1. 从affinity矩阵找到与购物车菜品关联度最高的推荐菜品
    2. 匹配已有的upsell_prompts话术
    3. 返回带话术的推荐列表

    Returns: [{dish_id, dish_name, prompt_text, prompt_type, affinity_score}, ...]
    """
    await _set_rls(db, tenant_id)

    if not cart_dish_ids:
        return []

    cart_ids = [str(d) for d in cart_dish_ids]

    try:
        result = await db.execute(
            text("""
                WITH cart_affinities AS (
                    SELECT
                        CASE
                            WHEN dish_a_id = ANY(:cart_ids) THEN dish_b_id
                            ELSE dish_a_id
                        END AS suggest_id,
                        CASE
                            WHEN dish_a_id = ANY(:cart_ids) THEN dish_a_id
                            ELSE dish_b_id
                        END AS trigger_id,
                        affinity_score
                    FROM dish_affinity_matrix
                    WHERE tenant_id = :tenant_id
                      AND store_id = :store_id
                      AND is_deleted = FALSE
                      AND (dish_a_id = ANY(:cart_ids) OR dish_b_id = ANY(:cart_ids))
                ),
                ranked AS (
                    SELECT suggest_id, trigger_id, affinity_score,
                           ROW_NUMBER() OVER (
                               PARTITION BY suggest_id ORDER BY affinity_score DESC
                           ) AS rn
                    FROM cart_affinities
                    WHERE suggest_id != ALL(:cart_ids)
                )
                SELECT
                    r.suggest_id AS dish_id,
                    d.dish_name,
                    d.price_fen,
                    r.affinity_score,
                    up.prompt_text,
                    up.prompt_type,
                    up.id AS prompt_id
                FROM ranked r
                JOIN dishes d ON d.id = r.suggest_id AND d.is_deleted = FALSE
                LEFT JOIN upsell_prompts up
                    ON up.trigger_dish_id = r.trigger_id
                    AND up.suggest_dish_id = r.suggest_id
                    AND up.tenant_id = :tenant_id
                    AND up.is_deleted = FALSE
                    AND up.is_enabled = TRUE
                WHERE r.rn = 1
                ORDER BY r.affinity_score DESC
                LIMIT :lim
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "cart_ids": cart_ids,
                "lim": limit,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "dish_id": str(r["dish_id"]),
                "dish_name": r["dish_name"],
                "price_fen": r["price_fen"],
                "affinity_score": round(float(r["affinity_score"]), 4),
                "prompt_text": r["prompt_text"] or "",
                "prompt_type": r["prompt_type"] or "add_on",
                "prompt_id": str(r["prompt_id"]) if r["prompt_id"] else None,
            }
            for r in rows
        ]
    except SQLAlchemyError as exc:
        log.error("get_upsell_for_cart_error", error=str(exc))
        raise


async def record_impression(
    db: Any,
    tenant_id: str,
    prompt_id: str,
) -> None:
    """记录话术曝光+1"""
    await _set_rls(db, tenant_id)
    try:
        await db.execute(
            text("""
                UPDATE upsell_prompts
                SET impression_count = impression_count + 1,
                    updated_at = NOW()
                WHERE id = :prompt_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"prompt_id": str(prompt_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("record_impression_error", error=str(exc), prompt_id=str(prompt_id))
        raise


async def record_conversion(
    db: Any,
    tenant_id: str,
    prompt_id: str,
) -> None:
    """记录话术转化+1"""
    await _set_rls(db, tenant_id)
    try:
        await db.execute(
            text("""
                UPDATE upsell_prompts
                SET conversion_count = conversion_count + 1,
                    updated_at = NOW()
                WHERE id = :prompt_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"prompt_id": str(prompt_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("record_conversion_error", error=str(exc), prompt_id=str(prompt_id))
        raise
