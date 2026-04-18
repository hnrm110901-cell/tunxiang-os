"""
脉搏调研服务 — 模板 / 下发 / 作答 / 聚合 / 情感分析 / 趋势
支持匿名（is_anonymous=True 时用 employee_hash 去重）
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pulse_survey import (
    PulseSurveyInstance,
    PulseSurveyResponse,
    PulseSurveyTemplate,
)

logger = logging.getLogger(__name__)


class PulseSurveyService:
    """脉搏调研服务"""

    @staticmethod
    def _hash_employee(employee_id: str, instance_id: str) -> str:
        """匿名去重哈希（同一个 instance 内同一员工仅一次）"""
        raw = f"{employee_id}|{instance_id}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ─── 模板 ─────────────────────────────────────
    async def create_template(
        self,
        db: AsyncSession,
        *,
        code: str,
        name: str,
        questions: List[Dict[str, Any]],
        frequency: str = "monthly",
        target_scope: str = "all",
        allow_anonymous: bool = True,
        created_by: Optional[str] = None,
    ) -> str:
        tpl = PulseSurveyTemplate(
            id=uuid.uuid4(),
            code=code,
            name=name,
            questions_json=questions,
            frequency=frequency,
            target_scope=target_scope,
            allow_anonymous=allow_anonymous,
            created_by=created_by,
        )
        db.add(tpl)
        await db.flush()
        return str(tpl.id)

    # ─── 下发 ─────────────────────────────────────
    async def send_survey(
        self,
        db: AsyncSession,
        *,
        template_id: str,
        store_id: Optional[str] = None,
        target_employee_ids: Optional[List[str]] = None,
        scheduled_date: Optional[date] = None,
        response_days: int = 7,
    ) -> str:
        """批量下发给门店员工"""
        tpl = await db.get(
            PulseSurveyTemplate, uuid.UUID(template_id) if isinstance(template_id, str) else template_id
        )
        if not tpl:
            raise ValueError(f"Template {template_id} not found")

        inst = PulseSurveyInstance(
            id=uuid.uuid4(),
            template_id=tpl.id,
            store_id=store_id,
            scheduled_date=scheduled_date or date.today(),
            target_employee_ids_json=list(target_employee_ids or []),
            status="sent",
            response_deadline=datetime.utcnow() + timedelta(days=response_days),
            sent_count=len(target_employee_ids or []),
        )
        db.add(inst)
        await db.flush()
        return str(inst.id)

    # ─── 作答 ─────────────────────────────────────
    async def submit_response(
        self,
        db: AsyncSession,
        *,
        instance_id: str,
        employee_id: str,
        responses: List[Dict[str, Any]],
        is_anonymous: bool = False,
    ) -> str:
        """提交作答"""
        # 匿名去重
        emp_hash = self._hash_employee(employee_id, instance_id) if is_anonymous else None
        if is_anonymous:
            existing = (
                await db.execute(
                    select(PulseSurveyResponse).where(
                        PulseSurveyResponse.instance_id == instance_id,
                        PulseSurveyResponse.employee_hash == emp_hash,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                raise ValueError("重复提交（匿名）")
        else:
            existing = (
                await db.execute(
                    select(PulseSurveyResponse).where(
                        PulseSurveyResponse.instance_id == instance_id,
                        PulseSurveyResponse.employee_id == employee_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                raise ValueError("重复提交")

        resp = PulseSurveyResponse(
            id=uuid.uuid4(),
            instance_id=instance_id,
            employee_id=None if is_anonymous else employee_id,
            employee_hash=emp_hash,
            is_anonymous=is_anonymous,
            responses_json=responses,
        )
        db.add(resp)

        # 更新实例计数
        inst = await db.get(
            PulseSurveyInstance, uuid.UUID(instance_id) if isinstance(instance_id, str) else instance_id
        )
        if inst:
            inst.response_count = (inst.response_count or 0) + 1
            inst.status = "collecting"

        await db.flush()
        return str(resp.id)

    # ─── 聚合 ─────────────────────────────────────
    async def aggregate_results(
        self, db: AsyncSession, *, instance_id: str
    ) -> Dict[str, Any]:
        """聚合 — rating 均分 / text 计数 / multi 占比，脱敏"""
        inst = await db.get(
            PulseSurveyInstance, uuid.UUID(instance_id) if isinstance(instance_id, str) else instance_id
        )
        if not inst:
            raise ValueError("Instance not found")
        tpl = await db.get(PulseSurveyTemplate, inst.template_id)
        questions = tpl.questions_json or [] if tpl else []

        rows = (
            await db.execute(
                select(PulseSurveyResponse).where(
                    PulseSurveyResponse.instance_id == instance_id
                )
            )
        ).scalars().all()

        # 按 question_id 聚合
        per_q: Dict[Any, Dict[str, Any]] = {}
        for q in questions:
            per_q[q.get("id")] = {
                "question_id": q.get("id"),
                "type": q.get("type"),
                "text": q.get("text"),
                "count": 0,
                "rating_sum": 0.0,
                "rating_avg": None,
                "options_count": {},
                "text_samples": [],
            }

        for r in rows:
            for ans in r.responses_json or []:
                qid = ans.get("question_id")
                if qid not in per_q:
                    continue
                bucket = per_q[qid]
                bucket["count"] += 1
                a = ans.get("answer")
                if bucket["type"] == "rating":
                    try:
                        bucket["rating_sum"] += float(a)
                    except Exception:
                        pass
                elif bucket["type"] == "multi_choice":
                    bucket["options_count"][a] = bucket["options_count"].get(a, 0) + 1
                elif bucket["type"] == "text":
                    if a and len(bucket["text_samples"]) < 20:
                        bucket["text_samples"].append(str(a)[:200])

        # 均分
        for qid, b in per_q.items():
            if b["type"] == "rating" and b["count"] > 0:
                b["rating_avg"] = round(b["rating_sum"] / b["count"], 2)

        summary = {
            "instance_id": str(inst.id),
            "template_id": str(inst.template_id),
            "response_count": len(rows),
            "anonymous_count": sum(1 for r in rows if r.is_anonymous),
            "per_question": list(per_q.values()),
        }
        inst.summary_json = summary
        if inst.response_deadline and datetime.utcnow() > inst.response_deadline:
            inst.status = "completed"
        await db.flush()
        return summary

    # ─── 情感分析 ───────────────────────────────
    async def sentiment_analysis(
        self, db: AsyncSession, *, instance_id: str
    ) -> Dict[str, Any]:
        """LLM 分析文本回答情感倾向（正向/中性/负向比例）；LLM 失败时用关键词 fallback"""
        rows = (
            await db.execute(
                select(PulseSurveyResponse).where(
                    PulseSurveyResponse.instance_id == instance_id
                )
            )
        ).scalars().all()

        texts: List[str] = []
        row_map = []
        for r in rows:
            for ans in r.responses_json or []:
                a = ans.get("answer")
                if isinstance(a, str) and len(a.strip()) > 2:
                    texts.append(a.strip()[:300])
                    row_map.append(r)

        if not texts:
            return {"positive": 0, "neutral": 0, "negative": 0, "total": 0}

        # LLM 调用（失败走关键词 fallback）
        sentiments: List[str] = []
        try:
            from src.services.llm_gateway.gateway import LLMGateway

            llm = LLMGateway()
            joined = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
            resp = await llm.chat(
                messages=[{"role": "user", "content": joined}],
                system=(
                    "你是情感分析助手。对每条文本返回 positive/neutral/negative 之一，"
                    "每行一个判断，仅输出单词，共 %d 行。" % len(texts)
                ),
                temperature=0.0,
                max_tokens=500,
            )
            raw = resp.get("text", "") if isinstance(resp, dict) else ""
            for line in raw.splitlines():
                line = line.strip().lower()
                for tok in ("positive", "neutral", "negative"):
                    if tok in line:
                        sentiments.append(tok)
                        break
        except Exception as e:
            logger.warning("pulse_sentiment_llm_failed: %s", e)

        if len(sentiments) != len(texts):
            # 关键词 fallback
            sentiments = [self._kw_sentiment(t) for t in texts]

        # 回写 sentiment_label 到 response（按首条文本）
        updated_ids: set = set()
        for text, senti, row in zip(texts, sentiments, row_map):
            if row.id in updated_ids:
                continue
            row.sentiment_label = senti
            row.sentiment_score = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}.get(senti, 0.0)
            updated_ids.add(row.id)

        counts = {"positive": 0, "neutral": 0, "negative": 0}
        for s in sentiments:
            counts[s] = counts.get(s, 0) + 1
        counts["total"] = len(sentiments)
        await db.flush()
        return counts

    @staticmethod
    def _kw_sentiment(text: str) -> str:
        pos_kw = ("好", "棒", "满意", "喜欢", "开心", "赞", "感谢")
        neg_kw = ("差", "糟糕", "不满", "累", "烦", "投诉", "失望", "辞")
        t = text.lower()
        if any(k in text for k in neg_kw):
            return "negative"
        if any(k in text for k in pos_kw):
            return "positive"
        return "neutral"

    # ─── 趋势 ─────────────────────────────────────
    async def trend_analysis(
        self, db: AsyncSession, *, template_id: str, last_n_periods: int = 6
    ) -> List[Dict[str, Any]]:
        """多期趋势 — 取近 N 期实例的 rating 平均"""
        rows = (
            await db.execute(
                select(PulseSurveyInstance)
                .where(PulseSurveyInstance.template_id == template_id)
                .order_by(PulseSurveyInstance.scheduled_date.desc())
                .limit(last_n_periods)
            )
        ).scalars().all()

        trend: List[Dict[str, Any]] = []
        for inst in reversed(rows):
            summary = inst.summary_json or {}
            rating_vals: List[float] = []
            for q in summary.get("per_question", []):
                if q.get("type") == "rating" and q.get("rating_avg") is not None:
                    rating_vals.append(float(q["rating_avg"]))
            avg = round(sum(rating_vals) / len(rating_vals), 2) if rating_vals else None
            trend.append(
                {
                    "instance_id": str(inst.id),
                    "scheduled_date": inst.scheduled_date.isoformat() if inst.scheduled_date else None,
                    "response_count": inst.response_count,
                    "avg_rating": avg,
                }
            )
        return trend


pulse_survey_service = PulseSurveyService()
