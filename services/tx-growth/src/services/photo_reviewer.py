"""AI照片审核服务 — 调用tx-brain Claude Vision API审核UGC照片质量

核心流程：
  1. 接收UGC媒体列表
  2. 调用tx-brain的Claude Vision API对每张照片评分
  3. 综合评分：是否食物相关、照片质量、内容合规
  4. 高于阈值(0.7)自动通过，低于阈值需人工审核

评分维度：
  - 是否食物/餐厅相关（非食物直接0分）
  - 照片质量（光线、对焦、构图）
  - 呈现吸引力
  - 无不良内容

环境变量：TX_BRAIN_BASE_URL（默认 http://tx-brain:8000）
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)

TX_BRAIN_BASE_URL: str = os.environ.get("TX_BRAIN_BASE_URL", "http://tx-brain:8000")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

AUTO_APPROVE_THRESHOLD: float = 0.7


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class PhotoReviewError(Exception):
    """AI照片审核异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# PhotoReviewer
# ---------------------------------------------------------------------------


class PhotoReviewer:
    """AI照片质量审核服务"""

    auto_approve_threshold: float = AUTO_APPROVE_THRESHOLD

    # ------------------------------------------------------------------
    # 审核照片
    # ------------------------------------------------------------------

    async def review_photo(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        media_urls: list[dict],
        db: Any,
    ) -> dict:
        """调用tx-brain Claude Vision API审核UGC照片

        Args:
            tenant_id: 租户ID
            ugc_id: UGC投稿ID
            media_urls: 媒体列表 [{url, type, thumbnail_url}]
            db: AsyncSession

        Returns:
            {ugc_id, score, is_food, quality, feedback, auto_approved}
        """
        if not media_urls:
            raise PhotoReviewError("EMPTY_MEDIA", "没有可审核的媒体文件")

        # 取第一张照片进行主审核（多张取平均分）
        scores: list[float] = []
        final_feedback_parts: list[str] = []
        is_food_overall = True
        quality_overall = "medium"

        for media in media_urls:
            url = media.get("url", "")
            if not url:
                continue

            review_result = await self._call_vision_api(url, tenant_id)
            scores.append(review_result.get("score", 0.0))
            final_feedback_parts.append(review_result.get("feedback", ""))

            if not review_result.get("is_food", False):
                is_food_overall = False

            q = review_result.get("quality", "medium")
            if q == "low":
                quality_overall = "low"
            elif q == "high" and quality_overall != "low":
                quality_overall = "high"

        avg_score = sum(scores) / len(scores) if scores else 0.0
        combined_feedback = "; ".join(f for f in final_feedback_parts if f)
        auto_approved = avg_score >= self.auto_approve_threshold and is_food_overall

        # 写入审核结果
        now = datetime.now(timezone.utc)
        new_status = "approved" if auto_approved else "pending_review"

        await db.execute(
            text("""
                UPDATE ugc_submissions
                SET ai_quality_score = :score,
                    ai_quality_feedback = :feedback,
                    ai_reviewed_at = :now,
                    status = CASE
                        WHEN status = 'pending_review' THEN :new_status
                        ELSE status
                    END,
                    published_at = CASE
                        WHEN :auto_approved AND status = 'pending_review'
                        THEN :now ELSE published_at
                    END,
                    points_awarded = CASE
                        WHEN :auto_approved AND status = 'pending_review'
                        THEN 50 ELSE points_awarded
                    END,
                    updated_at = :now
                WHERE id = :ugc_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "ugc_id": str(ugc_id),
                "tenant_id": str(tenant_id),
                "score": round(avg_score, 3),
                "feedback": combined_feedback,
                "now": now,
                "new_status": new_status,
                "auto_approved": auto_approved,
            },
        )
        row_check = (
            await db.execute(
                text(
                    "SELECT 1 FROM ugc_submissions WHERE id = :ugc_id AND tenant_id = :tenant_id AND is_deleted = false"
                ),
                {"ugc_id": str(ugc_id), "tenant_id": str(tenant_id)},
            )
        ).fetchone()
        if not row_check:
            raise PhotoReviewError("UGC_NOT_FOUND", "UGC投稿不存在")

        await db.commit()

        log.info(
            "ugc.photo_reviewed",
            ugc_id=str(ugc_id),
            score=round(avg_score, 3),
            is_food=is_food_overall,
            quality=quality_overall,
            auto_approved=auto_approved,
            tenant_id=str(tenant_id),
        )

        return {
            "ugc_id": str(ugc_id),
            "score": round(avg_score, 3),
            "is_food": is_food_overall,
            "quality": quality_overall,
            "feedback": combined_feedback,
            "auto_approved": auto_approved,
        }

    # ------------------------------------------------------------------
    # 调用tx-brain Vision API
    # ------------------------------------------------------------------

    async def _call_vision_api(
        self,
        image_url: str,
        tenant_id: uuid.UUID,
    ) -> dict:
        """调用tx-brain Claude Vision API评估单张照片

        Returns:
            {"score": 0.0-1.0, "is_food": bool, "quality": str, "feedback": str}
        """
        prompt = (
            "Review this restaurant food photo. Score 0-1 on: "
            "1) Is it food/restaurant related? (0 if not) "
            "2) Photo quality (lighting, focus, composition) "
            "3) Appetizing presentation "
            "4) No inappropriate content "
            'Return JSON: {"score": 0.0-1.0, "is_food": true/false, '
            '"quality": "high/medium/low", "feedback": "..."}'
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{TX_BRAIN_BASE_URL}/api/v1/brain/vision/analyze",
                    json={
                        "image_url": image_url,
                        "prompt": prompt,
                        "tenant_id": str(tenant_id),
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                data = resp.json()

                # tx-brain返回的data字段包含AI评估结果
                result = data.get("data", {})
                return {
                    "score": float(result.get("score", 0.5)),
                    "is_food": bool(result.get("is_food", True)),
                    "quality": str(result.get("quality", "medium")),
                    "feedback": str(result.get("feedback", "")),
                }

        except httpx.TimeoutException:
            log.warning("ugc.vision_api_timeout", image_url=image_url)
            # 超时降级：返回中等分数，需人工审核
            return {
                "score": 0.5,
                "is_food": True,
                "quality": "medium",
                "feedback": "AI审核超时，需人工审核",
            }
        except httpx.HTTPStatusError as exc:
            log.error(
                "ugc.vision_api_error",
                status_code=exc.response.status_code,
                image_url=image_url,
            )
            return {
                "score": 0.5,
                "is_food": True,
                "quality": "medium",
                "feedback": f"AI审核服务异常(HTTP {exc.response.status_code})，需人工审核",
            }
