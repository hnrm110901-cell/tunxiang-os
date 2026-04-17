"""
考试中心聚合服务 — BFF 用

按员工汇总考试中心三列看板数据：
  - pending：已报名课程 + 已有试卷，但没有"已完成/进行中"的 attempt
  - in_progress：attempt.status = 'in_progress'
  - completed：attempt.status IN ('submitted', 'graded')，按 submitted_at DESC 取最近 10 条

设计要点：
  - 纯读查询，不改数据；单次调用内做 N+1 聚合（课程数<=几十条足够）
  - 证书字段（cert_no / cert_expire_at）按 course_id 就近匹配，活跃证书优先
  - 所有时间字段 ISO8601 字符串输出；remaining_sec 按试卷 duration_min - elapsed 推算
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class ExamCenterService:
    """考试中心三列看板聚合"""

    @staticmethod
    async def get_my_exam_center(
        session: AsyncSession, employee_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """主聚合入口：返回 pending / in_progress / completed 三个列表。"""
        from src.models.training import (
            ExamAttempt,
            ExamCertificate,
            ExamPaper,
            TrainingCourse,
            TrainingEnrollment,
        )

        # 1) 员工所有 enrollment（已报名课程）
        enr_res = await session.execute(
            select(TrainingEnrollment).where(TrainingEnrollment.employee_id == employee_id)
        )
        enrollments = enr_res.scalars().all()
        if not enrollments:
            return {"pending": [], "in_progress": [], "completed": []}

        course_ids = list({e.course_id for e in enrollments})

        # 2) 课程信息
        courses: Dict[str, Any] = {}
        if course_ids:
            c_res = await session.execute(
                select(TrainingCourse).where(TrainingCourse.id.in_(course_ids))
            )
            for c in c_res.scalars().all():
                courses[str(c.id)] = c

        # 3) 课程对应的活跃试卷（一个课程可能多张，取最新一张）
        paper_by_course: Dict[str, Any] = {}
        if course_ids:
            p_res = await session.execute(
                select(ExamPaper)
                .where(and_(ExamPaper.course_id.in_(course_ids), ExamPaper.is_active.is_(True)))
                .order_by(ExamPaper.created_at.desc() if hasattr(ExamPaper, "created_at") else ExamPaper.id.desc())
            )
            for p in p_res.scalars().all():
                key = str(p.course_id)
                if key not in paper_by_course:
                    paper_by_course[key] = p

        # 4) 员工全部 attempt（后面按 paper_id 分组）
        a_res = await session.execute(
            select(ExamAttempt)
            .where(ExamAttempt.employee_id == employee_id)
            .order_by(desc(ExamAttempt.attempted_at))
        )
        attempts = a_res.scalars().all()

        # 按 paper_id 聚合该员工的 attempt
        attempts_by_paper: Dict[str, List[Any]] = {}
        for a in attempts:
            if a.paper_id is None:
                continue
            attempts_by_paper.setdefault(str(a.paper_id), []).append(a)

        # 5) 员工活跃证书（按 course_id 索引）
        cert_res = await session.execute(
            select(ExamCertificate).where(
                and_(
                    ExamCertificate.employee_id == employee_id,
                    ExamCertificate.status == "active",
                )
            )
        )
        cert_by_course: Dict[str, Any] = {}
        for c in cert_res.scalars().all():
            cert_by_course[str(c.course_id)] = c

        # ── 组装 pending / in_progress ──
        pending: List[Dict[str, Any]] = []
        in_progress: List[Dict[str, Any]] = []
        now = datetime.utcnow()

        for enr in enrollments:
            cid = str(enr.course_id)
            paper = paper_by_course.get(cid)
            if not paper:
                continue  # 课程无活跃试卷，不在考试中心列

            pid = str(paper.id)
            paper_attempts = attempts_by_paper.get(pid, [])

            # 是否有 in_progress？
            active = next((a for a in paper_attempts if a.status == "in_progress"), None)
            if active:
                # in_progress 记录
                expires_at = None
                remaining_sec = None
                if active.started_at and paper.duration_min:
                    expires_at_dt = active.started_at + timedelta(minutes=int(paper.duration_min))
                    expires_at = expires_at_dt.isoformat()
                    remaining_sec = max(0, int((expires_at_dt - now).total_seconds()))
                in_progress.append(
                    {
                        "attempt_id": str(active.id),
                        "paper_id": pid,
                        "paper_title": paper.title,
                        "started_at": active.started_at.isoformat() if active.started_at else None,
                        "expires_at": expires_at,
                        "remaining_sec": remaining_sec,
                    }
                )
                continue

            # 无 in_progress：如果已有 graded/submitted 且通过，则不算 pending
            has_passed = any(getattr(a, "passed", False) for a in paper_attempts)
            if has_passed:
                continue

            course = courses.get(cid)
            pending.append(
                {
                    "enrollment_id": str(enr.id),
                    "course_id": cid,
                    "course_name": course.title if course else None,
                    "paper_id": pid,
                    "paper_title": paper.title,
                    "duration_min": int(paper.duration_min or 0),
                    "pass_score": int(paper.pass_score or 0),
                }
            )

        # ── 组装 completed：所有员工 attempt 中 submitted/graded 最近 10 条 ──
        completed_attempts = [a for a in attempts if a.status in ("submitted", "graded")]
        # 按 submitted_at DESC（无则回落 attempted_at）
        completed_attempts.sort(
            key=lambda a: (a.submitted_at or a.attempted_at or datetime.min),
            reverse=True,
        )
        completed_attempts = completed_attempts[:10]

        # 为 completed 拉对应 paper（可能在 paper_by_course 没有，需要补）
        missing_paper_ids = [
            uuid.UUID(str(a.paper_id))
            for a in completed_attempts
            if a.paper_id and str(a.paper_id) not in {str(p.id) for p in paper_by_course.values()}
        ]
        extra_papers: Dict[str, Any] = {}
        if missing_paper_ids:
            from src.models.training import ExamPaper as _ExamPaper

            ep_res = await session.execute(
                select(_ExamPaper).where(_ExamPaper.id.in_(missing_paper_ids))
            )
            for p in ep_res.scalars().all():
                extra_papers[str(p.id)] = p

        completed: List[Dict[str, Any]] = []
        for a in completed_attempts:
            pid = str(a.paper_id) if a.paper_id else None
            paper = None
            if pid:
                paper = next((p for p in paper_by_course.values() if str(p.id) == pid), None) or extra_papers.get(pid)
            cert = cert_by_course.get(str(paper.course_id)) if paper else None
            completed.append(
                {
                    "attempt_id": str(a.id),
                    "paper_title": paper.title if paper else None,
                    "score": int(a.score or 0),
                    "passed": bool(a.passed),
                    "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                    "cert_no": cert.cert_no if cert else None,
                    "cert_expire_at": cert.expire_at.isoformat() if (cert and cert.expire_at) else None,
                }
            )

        return {"pending": pending, "in_progress": in_progress, "completed": completed}


exam_center_service = ExamCenterService()
