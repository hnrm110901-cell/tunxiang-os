"""
考试服务 — D11 Should-Fix P1

覆盖：
  - 题库 CRUD（ExamQuestion）
  - 组卷（手动/自动按难度）
  - 开始考试 / 提交答题 / 自动判卷
  - 主观题人工批改
  - 通过后自动发证（ExamCertificate）
  - 证书到期扫描

判卷规则：
  - single / judge / fill：答案完全匹配得分
  - multi：全对得满分；部分对按 (选对数-错选数) / 总正确数 比例；<=0 记 0
  - essay：标记 pending_review，不计分，直到 grade_essay 人工给分
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class ExamService:
    """考试服务（题库 / 试卷 / 考试 / 证书）"""

    # ── 题库 ────────────────────────────────────────────────────────

    @staticmethod
    async def create_question(session: AsyncSession, course_id: str, **fields) -> Dict[str, Any]:
        from src.models.training import ExamQuestion

        q = ExamQuestion(
            id=uuid.uuid4(),
            course_id=uuid.UUID(course_id),
            type=fields.get("type", "single"),
            stem=fields["stem"],
            options_json=fields.get("options_json"),
            correct_answer_json=fields.get("correct_answer_json"),
            score=int(fields.get("score", 5)),
            difficulty=int(fields.get("difficulty", 3)),
            explanation=fields.get("explanation"),
            is_active=fields.get("is_active", True),
        )
        session.add(q)
        await session.flush()
        logger.info("exam.question.created", question_id=str(q.id), type=q.type)
        return {"id": str(q.id), "type": q.type}

    @staticmethod
    async def update_question(session: AsyncSession, question_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.models.training import ExamQuestion

        res = await session.execute(select(ExamQuestion).where(ExamQuestion.id == uuid.UUID(question_id)))
        q = res.scalar_one_or_none()
        if not q:
            raise ValueError("题目不存在")
        for f in ["type", "stem", "options_json", "correct_answer_json", "score", "difficulty", "explanation", "is_active"]:
            if f in data:
                setattr(q, f, data[f])
        await session.flush()
        return {"id": str(q.id), "updated": True}

    @staticmethod
    async def list_by_course(
        session: AsyncSession, course_id: str, is_active: Optional[bool] = True
    ) -> List[Dict[str, Any]]:
        from src.models.training import ExamQuestion

        conds = [ExamQuestion.course_id == uuid.UUID(course_id)]
        if is_active is not None:
            conds.append(ExamQuestion.is_active.is_(is_active))
        res = await session.execute(select(ExamQuestion).where(and_(*conds)).order_by(ExamQuestion.difficulty.asc()))
        return [
            {
                "id": str(r.id),
                "type": r.type,
                "stem": r.stem,
                "options_json": r.options_json,
                "correct_answer_json": r.correct_answer_json,
                "score": r.score,
                "difficulty": r.difficulty,
                "explanation": r.explanation,
                "is_active": r.is_active,
            }
            for r in res.scalars().all()
        ]

    # ── 试卷 ────────────────────────────────────────────────────────

    @staticmethod
    async def create_paper(
        session: AsyncSession,
        course_id: str,
        question_ids: List[str],
        title: str,
        pass_score: int = 60,
        duration_min: int = 30,
        is_random: bool = False,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        from src.models.training import ExamPaper, ExamQuestion

        if not question_ids:
            raise ValueError("题目清单为空")

        # 校验题目存在并计算 total_score
        res = await session.execute(
            select(ExamQuestion).where(ExamQuestion.id.in_([uuid.UUID(qid) for qid in question_ids]))
        )
        qs = res.scalars().all()
        if len(qs) != len(question_ids):
            raise ValueError("存在无效题目 ID")
        total_score = sum(int(q.score) for q in qs)

        paper = ExamPaper(
            id=uuid.uuid4(),
            course_id=uuid.UUID(course_id),
            title=title,
            total_score=total_score,
            pass_score=pass_score,
            duration_min=duration_min,
            question_count=len(question_ids),
            question_ids_json=question_ids,
            is_random=is_random,
            created_by=created_by,
            is_active=True,
        )
        session.add(paper)
        await session.flush()
        logger.info("exam.paper.created", paper_id=str(paper.id), total=total_score)
        return {"id": str(paper.id), "total_score": total_score, "question_count": len(question_ids)}

    @staticmethod
    async def auto_generate_paper(
        session: AsyncSession,
        course_id: str,
        rules: Dict[str, Any],
        title: str = "自动组卷",
        pass_score: int = 60,
        duration_min: int = 30,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按难度抽题自动组卷。

        rules 形如：{"difficulty": {"1": 3, "2": 5, "3": 4, "4": 3, "5": 2}}
        即：难度 1 抽 3 道、难度 2 抽 5 道……
        """
        from src.models.training import ExamQuestion

        difficulty_rules: Dict[int, int] = {int(k): int(v) for k, v in rules.get("difficulty", {}).items()}
        picked: List[str] = []
        for diff, n in difficulty_rules.items():
            if n <= 0:
                continue
            res = await session.execute(
                select(ExamQuestion).where(
                    and_(
                        ExamQuestion.course_id == uuid.UUID(course_id),
                        ExamQuestion.difficulty == diff,
                        ExamQuestion.is_active.is_(True),
                    )
                )
            )
            pool = [str(q.id) for q in res.scalars().all()]
            if len(pool) < n:
                raise ValueError(f"难度 {diff} 题库不足：需 {n} 实有 {len(pool)}")
            picked.extend(random.sample(pool, n))

        if not picked:
            raise ValueError("组卷规则无效：未选中任何题目")

        return await ExamService.create_paper(
            session,
            course_id=course_id,
            question_ids=picked,
            title=title,
            pass_score=pass_score,
            duration_min=duration_min,
            is_random=True,
            created_by=created_by,
        )

    @staticmethod
    async def get_paper(session: AsyncSession, paper_id: str, include_answers: bool = False) -> Dict[str, Any]:
        from src.models.training import ExamPaper, ExamQuestion

        res = await session.execute(select(ExamPaper).where(ExamPaper.id == uuid.UUID(paper_id)))
        paper = res.scalar_one_or_none()
        if not paper:
            raise ValueError("试卷不存在")

        q_ids = [uuid.UUID(qid) for qid in (paper.question_ids_json or [])]
        qres = await session.execute(select(ExamQuestion).where(ExamQuestion.id.in_(q_ids)))
        qmap = {str(q.id): q for q in qres.scalars().all()}

        questions = []
        for qid in paper.question_ids_json or []:
            q = qmap.get(qid)
            if not q:
                continue
            item = {
                "id": str(q.id),
                "type": q.type,
                "stem": q.stem,
                "options_json": q.options_json,
                "score": q.score,
                "difficulty": q.difficulty,
            }
            if include_answers:
                item["correct_answer_json"] = q.correct_answer_json
                item["explanation"] = q.explanation
            questions.append(item)

        return {
            "id": str(paper.id),
            "course_id": str(paper.course_id),
            "title": paper.title,
            "total_score": paper.total_score,
            "pass_score": paper.pass_score,
            "duration_min": paper.duration_min,
            "question_count": paper.question_count,
            "is_random": paper.is_random,
            "questions": questions,
        }

    # ── 考试流程 ────────────────────────────────────────────────────

    @staticmethod
    async def start_attempt(session: AsyncSession, paper_id: str, employee_id: str, store_id: str) -> Dict[str, Any]:
        """开始考试。若已有 in_progress 记录直接返回，禁止重复开启。"""
        from src.models.training import ExamAttempt, ExamPaper

        # 已有进行中？
        ex = await session.execute(
            select(ExamAttempt).where(
                and_(
                    ExamAttempt.paper_id == uuid.UUID(paper_id),
                    ExamAttempt.employee_id == employee_id,
                    ExamAttempt.status == "in_progress",
                )
            )
        )
        existing = ex.scalar_one_or_none()
        if existing:
            return {
                "id": str(existing.id),
                "status": existing.status,
                "started_at": existing.started_at.isoformat() if existing.started_at else None,
                "resumed": True,
            }

        # 读取试卷以锁定题目顺序
        paper_res = await session.execute(select(ExamPaper).where(ExamPaper.id == uuid.UUID(paper_id)))
        paper = paper_res.scalar_one_or_none()
        if not paper:
            raise ValueError("试卷不存在")
        qids = list(paper.question_ids_json or [])
        if paper.is_random:
            random.shuffle(qids)

        attempt = ExamAttempt(
            id=uuid.uuid4(),
            paper_id=paper.id,
            employee_id=employee_id,
            store_id=store_id,
            started_at=datetime.utcnow(),
            attempted_at=datetime.utcnow(),
            status="in_progress",
            answers={"_locked_order": qids, "meta": {"leave_count": 0}},
            score=0,
            passed=False,
        )
        session.add(attempt)
        await session.flush()
        return {
            "id": str(attempt.id),
            "status": attempt.status,
            "started_at": attempt.started_at.isoformat(),
            "question_order": qids,
            "duration_min": paper.duration_min,
        }

    @staticmethod
    def _grade_objective(question_type: str, correct: Any, submitted: Any, score: int) -> Tuple[int, bool]:
        """单题判分：返回 (得分, 是否完全正确)"""
        if submitted is None:
            return 0, False

        if question_type in ("single", "judge", "fill"):
            # 字符串/布尔完全相等
            if isinstance(correct, str) and isinstance(submitted, str):
                return (score, True) if correct.strip().lower() == submitted.strip().lower() else (0, False)
            return (score, True) if correct == submitted else (0, False)

        if question_type == "multi":
            correct_set = set(correct or [])
            submit_set = set(submitted or [])
            if not correct_set:
                return 0, False
            # 有错选直接按 (正确选中数 - 错选数) / 正确数 比例
            right = len(correct_set & submit_set)
            wrong = len(submit_set - correct_set)
            ratio = (right - wrong) / len(correct_set)
            if submit_set == correct_set:
                return score, True
            if ratio <= 0:
                return 0, False
            return int(round(score * ratio)), False

        return 0, False

    @staticmethod
    async def submit_attempt(session: AsyncSession, attempt_id: str, answers: Dict[str, Any]) -> Dict[str, Any]:
        """
        提交答题并自动判卷：
          - 客观题直接打分
          - 主观题（essay）留待 grade_essay 人工批改，status 暂为 submitted
        """
        from src.models.training import ExamAttempt, ExamPaper, ExamQuestion

        res = await session.execute(select(ExamAttempt).where(ExamAttempt.id == uuid.UUID(attempt_id)))
        attempt = res.scalar_one_or_none()
        if not attempt:
            raise ValueError("考试记录不存在")
        if attempt.status not in ("in_progress",):
            raise ValueError(f"当前状态不可提交：{attempt.status}")

        paper_res = await session.execute(select(ExamPaper).where(ExamPaper.id == attempt.paper_id))
        paper = paper_res.scalar_one_or_none()
        if not paper:
            raise ValueError("试卷不存在")

        qids = [uuid.UUID(qid) for qid in (paper.question_ids_json or [])]
        qres = await session.execute(select(ExamQuestion).where(ExamQuestion.id.in_(qids)))
        qmap = {str(q.id): q for q in qres.scalars().all()}

        total_score = 0
        per_item: Dict[str, Dict[str, Any]] = {}
        has_pending_essay = False

        for qid, q in qmap.items():
            user_ans = answers.get(qid)
            if q.type == "essay":
                per_item[qid] = {"score": 0, "pending_review": True, "answer": user_ans}
                has_pending_essay = True
                continue
            gained, correct = ExamService._grade_objective(q.type, q.correct_answer_json, user_ans, int(q.score))
            per_item[qid] = {"score": gained, "correct": correct, "answer": user_ans}
            total_score += gained

        submitted_at = datetime.utcnow()
        duration_sec = None
        if attempt.started_at:
            duration_sec = int((submitted_at - attempt.started_at).total_seconds())

        # 合并 meta（保留作弊信号）
        existing_ans = attempt.answers or {}
        existing_meta = existing_ans.get("meta", {}) if isinstance(existing_ans, dict) else {}
        submitted_meta = answers.get("meta", {}) if isinstance(answers.get("meta"), dict) else {}
        merged_meta = {**existing_meta, **submitted_meta}

        attempt.answers = {
            "submitted": answers,
            "per_item": per_item,
            "meta": merged_meta,
        }
        attempt.score = total_score
        attempt.submitted_at = submitted_at
        attempt.duration_sec = duration_sec
        attempt.attempted_at = submitted_at

        if has_pending_essay:
            attempt.status = "submitted"
            attempt.passed = False
        else:
            attempt.status = "graded"
            attempt.passed = total_score >= int(paper.pass_score)

        await session.flush()

        cert = None
        if attempt.status == "graded" and attempt.passed:
            cert = await ExamService.issue_certificate(
                session,
                employee_id=attempt.employee_id,
                course_id=str(paper.course_id),
                attempt_id=str(attempt.id),
            )

        return {
            "id": str(attempt.id),
            "score": total_score,
            "passed": attempt.passed,
            "status": attempt.status,
            "duration_sec": duration_sec,
            "has_pending_essay": has_pending_essay,
            "certificate": cert,
        }

    @staticmethod
    async def grade_essay(
        session: AsyncSession,
        attempt_id: str,
        item_scores: Dict[str, int],
        reviewer: str,
    ) -> Dict[str, Any]:
        """人工批改主观题。item_scores: {question_id: score}"""
        from src.models.training import ExamAttempt, ExamPaper

        res = await session.execute(select(ExamAttempt).where(ExamAttempt.id == uuid.UUID(attempt_id)))
        attempt = res.scalar_one_or_none()
        if not attempt:
            raise ValueError("考试记录不存在")
        if attempt.status != "submitted":
            raise ValueError(f"当前状态不可批改：{attempt.status}")

        paper_res = await session.execute(select(ExamPaper).where(ExamPaper.id == attempt.paper_id))
        paper = paper_res.scalar_one_or_none()
        if not paper:
            raise ValueError("试卷不存在")

        answers_snapshot: Dict[str, Any] = dict(attempt.answers or {})
        per_item: Dict[str, Dict[str, Any]] = dict(answers_snapshot.get("per_item", {}))

        extra = 0
        for qid, s in item_scores.items():
            item = per_item.get(qid, {})
            item["score"] = int(s)
            item["pending_review"] = False
            item["reviewer"] = reviewer
            per_item[qid] = item
            extra += int(s)

        # 重算总分：所有 per_item.score 相加
        total = sum(int(v.get("score", 0)) for v in per_item.values())
        answers_snapshot["per_item"] = per_item
        answers_snapshot["graded_by"] = reviewer
        attempt.answers = answers_snapshot
        attempt.score = total
        attempt.status = "graded"
        attempt.passed = total >= int(paper.pass_score)
        await session.flush()

        cert = None
        if attempt.passed:
            cert = await ExamService.issue_certificate(
                session,
                employee_id=attempt.employee_id,
                course_id=str(paper.course_id),
                attempt_id=str(attempt.id),
            )
        return {"id": str(attempt.id), "score": total, "passed": attempt.passed, "certificate": cert}

    # ── 证书 ────────────────────────────────────────────────────────

    @staticmethod
    async def issue_certificate(
        session: AsyncSession,
        employee_id: str,
        course_id: str,
        attempt_id: Optional[str] = None,
        valid_days: int = 365,
    ) -> Dict[str, Any]:
        """通过后颁发证书。证书号=COURSE前6+YYYYMM+月内序号(4位)"""
        from src.models.training import ExamCertificate

        # 去重：同员工同课程已有 active 证书则更新 expire_at
        existing_res = await session.execute(
            select(ExamCertificate).where(
                and_(
                    ExamCertificate.employee_id == employee_id,
                    ExamCertificate.course_id == uuid.UUID(course_id),
                    ExamCertificate.status == "active",
                )
            )
        )
        existing = existing_res.scalar_one_or_none()
        now = datetime.utcnow()
        expire_at = now + timedelta(days=valid_days)

        if existing:
            existing.issued_at = now
            existing.expire_at = expire_at
            if attempt_id:
                existing.attempt_id = uuid.UUID(attempt_id)
            await session.flush()
            return {"id": str(existing.id), "cert_no": existing.cert_no, "renewed": True, "expire_at": expire_at.isoformat()}

        # 月内序号：当月已发证数 + 1
        ym = now.strftime("%Y%m")
        count_res = await session.execute(
            select(func.count(ExamCertificate.id)).where(
                func.to_char(ExamCertificate.issued_at, "YYYYMM") == ym
            )
        )
        count = int(count_res.scalar() or 0)
        course_prefix = course_id.replace("-", "")[:6].upper()
        cert_no = f"{course_prefix}{ym}{count + 1:04d}"

        cert = ExamCertificate(
            id=uuid.uuid4(),
            employee_id=employee_id,
            course_id=uuid.UUID(course_id),
            attempt_id=uuid.UUID(attempt_id) if attempt_id else None,
            cert_no=cert_no,
            issued_at=now,
            expire_at=expire_at,
            pdf_url=None,
            status="active",
        )
        session.add(cert)
        await session.flush()
        logger.info("exam.cert.issued", cert_no=cert_no, employee_id=employee_id)

        # D11 z68 — 发证同时发放学习积分（exam_pass），失败不影响发证
        try:
            from src.services.learning_points_service import learning_points_service

            await learning_points_service.award(
                session,
                employee_id=employee_id,
                event_type="exam_pass",
                source_id=str(cert.id),
                remark=f"cert {cert_no}",
            )
        except Exception as _e:  # noqa: BLE001
            logger.warning("learning_points_award_failed", error=str(_e))

        # D11 Nice-to-Have：发证后异步生成 PDF（失败容错，不影响发证）
        try:
            from .certificate_pdf_service import generate_certificate_pdf

            await generate_certificate_pdf(session, str(cert.id), write_pdf_url=True)
        except Exception as e:  # pragma: no cover
            logger.warning("cert.pdf.post_issue.failed", cert_no=cert_no, error=str(e))

        # D9 z68：可选联动电子签（培训完成确认书，学员签字）
        esign_envelope_id: Optional[str] = None
        try:
            from .e_signature_service import ESignatureService

            env = await ESignatureService.prepare_envelope(
                session,
                template_id=None,
                signer_list=[
                    {"signer_id": str(employee_id), "role": "employee",
                     "name": employee_id, "order": 1},
                ],
                subject=f"培训完成确认书 - 证书 {cert_no}",
                initiator_id="system",
                related_contract_id=cert.id,
                related_entity_type="exam_certificate",
                expires_in_days=30,
            )
            esign_envelope_id = str(env.id)
        except Exception as e:  # pragma: no cover
            logger.warning("cert.esign.envelope_failed", cert_no=cert_no, error=str(e))

        return {
            "id": str(cert.id),
            "cert_no": cert_no,
            "renewed": False,
            "expire_at": expire_at.isoformat(),
            "pdf_url": cert.pdf_url,
            "esign_envelope_id": esign_envelope_id,
        }

    @staticmethod
    async def list_my_certificates(session: AsyncSession, employee_id: str) -> List[Dict[str, Any]]:
        from src.models.training import ExamCertificate

        res = await session.execute(
            select(ExamCertificate).where(ExamCertificate.employee_id == employee_id).order_by(
                ExamCertificate.issued_at.desc()
            )
        )
        now = datetime.utcnow()
        out = []
        for r in res.scalars().all():
            # 颜色分级：<=7 红；<=30 黄；其余绿
            level = "green"
            days_left = None
            if r.expire_at:
                days_left = (r.expire_at - now).days
                if days_left <= 7:
                    level = "red"
                elif days_left <= 30:
                    level = "yellow"
            out.append(
                {
                    "id": str(r.id),
                    "cert_no": r.cert_no,
                    "course_id": str(r.course_id),
                    "issued_at": r.issued_at.isoformat() if r.issued_at else None,
                    "expire_at": r.expire_at.isoformat() if r.expire_at else None,
                    "days_left": days_left,
                    "level": level,
                    "status": r.status,
                    "pdf_url": r.pdf_url,
                }
            )
        return out

    @staticmethod
    async def list_expiring_certs(session: AsyncSession, days_ahead: int = 30) -> List[Dict[str, Any]]:
        """证书到期扫描：<=days_ahead 天到期且仍 active。"""
        from src.models.training import ExamCertificate

        now = datetime.utcnow()
        cutoff = now + timedelta(days=days_ahead)
        res = await session.execute(
            select(ExamCertificate).where(
                and_(
                    ExamCertificate.status == "active",
                    ExamCertificate.expire_at.isnot(None),
                    ExamCertificate.expire_at <= cutoff,
                )
            ).order_by(ExamCertificate.expire_at.asc())
        )
        out = []
        for r in res.scalars().all():
            days_left = (r.expire_at - now).days if r.expire_at else None
            out.append(
                {
                    "id": str(r.id),
                    "cert_no": r.cert_no,
                    "employee_id": r.employee_id,
                    "course_id": str(r.course_id),
                    "expire_at": r.expire_at.isoformat() if r.expire_at else None,
                    "days_left": days_left,
                }
            )
        return out

    @staticmethod
    async def get_attempt_result(session: AsyncSession, attempt_id: str) -> Dict[str, Any]:
        """查看结果（包含正确答案+解析，仅在已判卷后返回）"""
        from src.models.training import ExamAttempt, ExamPaper, ExamQuestion

        res = await session.execute(select(ExamAttempt).where(ExamAttempt.id == uuid.UUID(attempt_id)))
        attempt = res.scalar_one_or_none()
        if not attempt:
            raise ValueError("考试记录不存在")

        questions: List[Dict[str, Any]] = []
        if attempt.paper_id:
            pres = await session.execute(select(ExamPaper).where(ExamPaper.id == attempt.paper_id))
            paper = pres.scalar_one_or_none()
            if paper and paper.question_ids_json:
                qids = [uuid.UUID(qid) for qid in paper.question_ids_json]
                qres = await session.execute(select(ExamQuestion).where(ExamQuestion.id.in_(qids)))
                # 只有 graded 才返回正确答案
                include_ans = attempt.status == "graded"
                for q in qres.scalars().all():
                    item: Dict[str, Any] = {
                        "id": str(q.id),
                        "type": q.type,
                        "stem": q.stem,
                        "score": q.score,
                    }
                    if include_ans:
                        item["correct_answer_json"] = q.correct_answer_json
                        item["explanation"] = q.explanation
                    questions.append(item)

        return {
            "id": str(attempt.id),
            "paper_id": str(attempt.paper_id) if attempt.paper_id else None,
            "employee_id": attempt.employee_id,
            "score": attempt.score,
            "passed": attempt.passed,
            "status": attempt.status,
            "duration_sec": attempt.duration_sec,
            "answers": attempt.answers,
            "questions": questions,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        }
