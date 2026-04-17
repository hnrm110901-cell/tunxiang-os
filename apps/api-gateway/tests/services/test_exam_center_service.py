"""
考试中心聚合服务 — 单元测试

覆盖：
  1) 无 enrollment → 三列全空
  2) 有 enrollment 无 attempt → pending 含一条
  3) attempt in_progress → in_progress 含一条，remaining_sec 正确
  4) attempt submitted/graded 且有证书 → completed 含 cert 字段
"""

import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.exam_center_service import ExamCenterService  # noqa: E402


# ─── 通用 MagicMock 构造 ───────────────────────────────────────────


class _Scalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _Scalars(self._items)


class _ResultQueue:
    """按 execute 调用顺序返回预置 list"""

    def __init__(self, queue):
        self.queue = list(queue)

    async def __call__(self, *a, **kw):
        if not self.queue:
            # 多余调用 → 空
            return _Result([])
        return _Result(self.queue.pop(0))


def _mk_enr(course_id, employee_id="E001"):
    e = MagicMock()
    e.id = uuid.uuid4()
    e.course_id = course_id
    e.employee_id = employee_id
    return e


def _mk_course(cid, title="课程"):
    c = MagicMock()
    c.id = cid
    c.title = title
    return c


def _mk_paper(pid, course_id, title="试卷", duration=30, pass_score=60):
    p = MagicMock()
    p.id = pid
    p.course_id = course_id
    p.title = title
    p.duration_min = duration
    p.pass_score = pass_score
    p.is_active = True
    return p


def _mk_attempt(pid, status, **kw):
    a = MagicMock()
    a.id = uuid.uuid4()
    a.paper_id = pid
    a.status = status
    a.started_at = kw.get("started_at")
    a.submitted_at = kw.get("submitted_at")
    a.attempted_at = kw.get("attempted_at") or datetime.utcnow()
    a.score = kw.get("score", 0)
    a.passed = kw.get("passed", False)
    return a


# ─── 用例 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_enrollment_returns_empty():
    """无 enrollment → pending/in_progress/completed 全空"""
    session = MagicMock()
    session.execute = _ResultQueue([[]])  # 第一个调用：enrollments 为空，直接返回
    out = await ExamCenterService.get_my_exam_center(session, "E001")
    assert out == {"pending": [], "in_progress": [], "completed": []}


@pytest.mark.asyncio
async def test_enrollment_no_attempt_goes_to_pending():
    """已报名 + 有活跃试卷 + 无 attempt → pending 一条"""
    course_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    enr = _mk_enr(course_id)
    course = _mk_course(course_id, "食品安全基础")
    paper = _mk_paper(paper_id, course_id, "食品安全考试")

    session = MagicMock()
    session.execute = _ResultQueue(
        [
            [enr],      # 1. enrollments
            [course],   # 2. courses
            [paper],    # 3. active papers
            [],         # 4. attempts
            [],         # 5. certs
        ]
    )
    out = await ExamCenterService.get_my_exam_center(session, "E001")
    assert len(out["pending"]) == 1
    assert out["in_progress"] == []
    assert out["completed"] == []
    p = out["pending"][0]
    assert p["course_name"] == "食品安全基础"
    assert p["paper_id"] == str(paper_id)
    assert p["duration_min"] == 30
    assert p["pass_score"] == 60


@pytest.mark.asyncio
async def test_in_progress_attempt_has_remaining_sec():
    """attempt.status=in_progress → 应出现在 in_progress，且 remaining_sec 符合预期"""
    course_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    enr = _mk_enr(course_id)
    course = _mk_course(course_id)
    paper = _mk_paper(paper_id, course_id, duration=60)  # 60 分钟
    # 10 分钟前开始 → 剩余约 50 分钟
    started = datetime.utcnow() - timedelta(minutes=10)
    att = _mk_attempt(paper_id, "in_progress", started_at=started)

    session = MagicMock()
    session.execute = _ResultQueue(
        [
            [enr],
            [course],
            [paper],
            [att],
            [],
        ]
    )
    out = await ExamCenterService.get_my_exam_center(session, "E001")
    assert out["pending"] == []
    assert len(out["in_progress"]) == 1
    ip = out["in_progress"][0]
    assert ip["attempt_id"] == str(att.id)
    assert ip["paper_id"] == str(paper_id)
    # 剩余秒应在 (49*60, 50*60) 附近
    assert 49 * 60 <= ip["remaining_sec"] <= 50 * 60


@pytest.mark.asyncio
async def test_completed_attempt_with_certificate():
    """attempt.status=graded + 通过 + 活跃证书 → completed 含 cert 字段"""
    course_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    enr = _mk_enr(course_id)
    course = _mk_course(course_id, "服务礼仪")
    paper = _mk_paper(paper_id, course_id, "礼仪考试")
    now = datetime.utcnow()
    att = _mk_attempt(
        paper_id,
        "graded",
        submitted_at=now - timedelta(hours=1),
        attempted_at=now - timedelta(hours=1),
        score=85,
        passed=True,
    )

    cert = MagicMock()
    cert.cert_no = "SERVIC2026040001"
    cert.course_id = course_id
    cert.expire_at = now + timedelta(days=300)
    cert.status = "active"

    session = MagicMock()
    session.execute = _ResultQueue(
        [
            [enr],
            [course],
            [paper],
            [att],
            [cert],
        ]
    )
    out = await ExamCenterService.get_my_exam_center(session, "E001")
    # 已通过 → pending 不应出现
    assert out["pending"] == []
    assert out["in_progress"] == []
    assert len(out["completed"]) == 1
    c = out["completed"][0]
    assert c["attempt_id"] == str(att.id)
    assert c["score"] == 85
    assert c["passed"] is True
    assert c["cert_no"] == "SERVIC2026040001"
    assert c["cert_expire_at"] is not None
