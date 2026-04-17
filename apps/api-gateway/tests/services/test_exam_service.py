"""
D11 Should-Fix P1 考试系统 — 单元测试

覆盖：
  1) 客观题自动判卷正确率（single/multi/judge/fill）
  2) 多选部分匹配按比例
  3) 主观题标记 pending_review
  4) 通过自动发证、不通过不发
  5) 证书号格式 COURSE+YYYYMM+序号
  6) 证书到期扫描 (days_ahead)
  7) 重复开始同一试卷阻止（已 in_progress）
"""

import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

# mock 配置以避免 pydantic_settings
sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest

from src.services.exam_service import ExamService


# ─────────────────────────────────────────────────────────────
# 1. 纯函数：判卷
# ─────────────────────────────────────────────────────────────


class TestGradeObjective:
    def test_single_correct(self):
        s, ok = ExamService._grade_objective("single", "A", "A", 5)
        assert s == 5 and ok

    def test_single_wrong(self):
        s, ok = ExamService._grade_objective("single", "A", "B", 5)
        assert s == 0 and ok is False

    def test_judge_true(self):
        s, ok = ExamService._grade_objective("judge", True, True, 4)
        assert s == 4 and ok

    def test_fill_case_insensitive_strip(self):
        s, ok = ExamService._grade_objective("fill", "hello", " Hello ", 3)
        assert s == 3 and ok

    def test_multi_all_correct(self):
        s, ok = ExamService._grade_objective("multi", ["A", "B", "C"], ["C", "B", "A"], 9)
        assert s == 9 and ok is True

    def test_multi_partial(self):
        # 正确 A/B/C，选 A/B → 比例 2/3 → round(9*2/3) = 6
        s, ok = ExamService._grade_objective("multi", ["A", "B", "C"], ["A", "B"], 9)
        assert s == 6 and ok is False

    def test_multi_wrong_choice_zero(self):
        # 有错选，ratio = (1-2)/3 <= 0
        s, ok = ExamService._grade_objective("multi", ["A"], ["B", "C"], 9)
        assert s == 0 and ok is False

    def test_essay_returns_zero(self):
        s, ok = ExamService._grade_objective("essay", None, "长文", 10)
        assert s == 0 and ok is False

    def test_none_submission(self):
        s, ok = ExamService._grade_objective("single", "A", None, 5)
        assert s == 0 and ok is False


# ─────────────────────────────────────────────────────────────
# 2. 集成：submit_attempt / issue_certificate / start_attempt
#    使用 MagicMock session 模拟 SQLAlchemy async 行为
# ─────────────────────────────────────────────────────────────


def _mock_question(qid, qtype, correct, score=10):
    q = MagicMock()
    q.id = qid
    q.type = qtype
    q.correct_answer_json = correct
    q.score = score
    q.explanation = "解析"
    return q


def _mock_paper(pid, course_id, q_ids, pass_score=60, is_random=False, duration_min=30):
    p = MagicMock()
    p.id = pid
    p.course_id = course_id
    p.question_ids_json = q_ids
    p.pass_score = pass_score
    p.is_random = is_random
    p.duration_min = duration_min
    p.title = "试卷"
    p.total_score = 100
    p.question_count = len(q_ids)
    return p


class _ScalarsShim:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value

    def scalars(self):
        class _S:
            def __init__(self, v):
                self._v = v

            def all(self):
                return self._v

        return _S(self._value if isinstance(self._value, list) else [])


class _ResultQueue:
    """按 session.execute 调用顺序返回预置 result"""

    def __init__(self, queue):
        self.queue = list(queue)

    async def __call__(self, *a, **kw):
        if not self.queue:
            raise RuntimeError("No more results queued")
        v = self.queue.pop(0)
        return v


@pytest.mark.asyncio
class TestSubmitAttempt:
    async def test_objective_pass_issues_cert(self):
        """全部客观题，全对 → 及格 → 自动发证"""
        import uuid as _u

        attempt = MagicMock()
        attempt.id = _u.uuid4()
        attempt.paper_id = _u.uuid4()
        attempt.status = "in_progress"
        attempt.started_at = datetime.utcnow() - timedelta(minutes=10)
        attempt.answers = {}
        attempt.employee_id = "E001"

        course_id = _u.uuid4()
        # UUID 统一走 str(uuid4()) —— service 内部 uuid.UUID(qid) 需要合法十六进制 UUID 串
        q1_id = str(_u.uuid4())
        q2_id = str(_u.uuid4())
        q1 = _mock_question(q1_id, "single", "A", 50)
        q2 = _mock_question(q2_id, "judge", True, 50)
        paper = _mock_paper(attempt.paper_id, course_id, [q1_id, q2_id], pass_score=60)

        session = MagicMock()
        # 1) attempt 查询  2) paper 查询  3) questions 查询
        # issue_certificate 内又会：existing active 查询、count 查询
        results = [
            _ScalarsShim(attempt),
            _ScalarsShim(paper),
            _ScalarsShim([q1, q2]),
            _ScalarsShim(None),  # 无已存证书
            _ScalarsShim(0),  # 本月已发 0
        ]
        session.execute = _ResultQueue(results)
        session.add = MagicMock()
        session.flush = AsyncMock()

        out = await ExamService.submit_attempt(
            session,
            str(attempt.id),
            {q1_id: "A", q2_id: True},
        )
        assert out["passed"] is True
        assert out["score"] == 100
        assert out["status"] == "graded"
        assert out["certificate"] is not None
        assert out["certificate"]["cert_no"].endswith("0001")

    async def test_objective_fail_no_cert(self):
        import uuid as _u

        attempt = MagicMock()
        attempt.id = _u.uuid4()
        attempt.paper_id = _u.uuid4()
        attempt.status = "in_progress"
        attempt.started_at = datetime.utcnow()
        attempt.answers = {}
        attempt.employee_id = "E002"

        q1_id = str(_u.uuid4())
        q2_id = str(_u.uuid4())
        q1 = _mock_question(q1_id, "single", "A", 50)
        q2 = _mock_question(q2_id, "single", "B", 50)
        paper = _mock_paper(attempt.paper_id, _u.uuid4(), [q1_id, q2_id], pass_score=60)

        session = MagicMock()
        session.execute = _ResultQueue(
            [_ScalarsShim(attempt), _ScalarsShim(paper), _ScalarsShim([q1, q2])]
        )
        session.add = MagicMock()
        session.flush = AsyncMock()

        out = await ExamService.submit_attempt(session, str(attempt.id), {q1_id: "A", q2_id: "C"})
        assert out["passed"] is False
        assert out["score"] == 50
        assert out["certificate"] is None

    async def test_essay_marks_pending_review(self):
        import uuid as _u

        attempt = MagicMock()
        attempt.id = _u.uuid4()
        attempt.paper_id = _u.uuid4()
        attempt.status = "in_progress"
        attempt.started_at = datetime.utcnow()
        attempt.answers = {}
        attempt.employee_id = "E003"

        q1_id = str(_u.uuid4())
        q2_id = str(_u.uuid4())
        q1 = _mock_question(q1_id, "single", "A", 40)
        q2 = _mock_question(q2_id, "essay", None, 60)
        paper = _mock_paper(attempt.paper_id, _u.uuid4(), [q1_id, q2_id], pass_score=60)

        session = MagicMock()
        session.execute = _ResultQueue(
            [_ScalarsShim(attempt), _ScalarsShim(paper), _ScalarsShim([q1, q2])]
        )
        session.add = MagicMock()
        session.flush = AsyncMock()

        out = await ExamService.submit_attempt(session, str(attempt.id), {q1_id: "A", q2_id: "答题内容"})
        assert out["status"] == "submitted"  # 未判卷完
        assert out["has_pending_essay"] is True
        assert out["certificate"] is None
        # per_item 的 essay 项 pending_review=True
        per = attempt.answers["per_item"]
        assert per[q2_id]["pending_review"] is True


@pytest.mark.asyncio
class TestStartAttempt:
    async def test_blocks_duplicate_in_progress(self):
        """已有 in_progress 记录 → 返回 resumed=True，不新建"""
        import uuid as _u

        existing = MagicMock()
        existing.id = _u.uuid4()
        existing.status = "in_progress"
        existing.started_at = datetime.utcnow()

        session = MagicMock()
        session.execute = _ResultQueue([_ScalarsShim(existing)])
        session.add = MagicMock()
        session.flush = AsyncMock()

        out = await ExamService.start_attempt(session, str(_u.uuid4()), "E010", "S001")
        assert out["resumed"] is True
        assert out["status"] == "in_progress"
        # 没有 add 新 attempt
        session.add.assert_not_called()

    async def test_creates_new_attempt(self):
        import uuid as _u

        paper = _mock_paper(_u.uuid4(), _u.uuid4(), ["q1", "q2", "q3"], is_random=False)

        session = MagicMock()
        # 1) 查询已有 → None  2) 查询 paper
        session.execute = _ResultQueue([_ScalarsShim(None), _ScalarsShim(paper)])
        session.add = MagicMock()
        session.flush = AsyncMock()

        out = await ExamService.start_attempt(session, str(paper.id), "E011", "S001")
        assert out["status"] == "in_progress"
        assert out["question_order"] == ["q1", "q2", "q3"]
        session.add.assert_called_once()


@pytest.mark.asyncio
class TestCertificateScan:
    async def test_expiring_includes_within_window(self):
        now = datetime.utcnow()
        c1 = MagicMock()
        c1.id = "uuid1"
        c1.cert_no = "COURSE1202604001"
        c1.employee_id = "E001"
        c1.course_id = "course-uuid-1"
        c1.expire_at = now + timedelta(days=10)

        c2 = MagicMock()
        c2.id = "uuid2"
        c2.cert_no = "COURSE1202604002"
        c2.employee_id = "E002"
        c2.course_id = "course-uuid-2"
        c2.expire_at = now + timedelta(days=3)

        session = MagicMock()
        session.execute = _ResultQueue([_ScalarsShim([c1, c2])])

        out = await ExamService.list_expiring_certs(session, days_ahead=30)
        assert len(out) == 2
        assert all(o["days_left"] <= 30 for o in out)


@pytest.mark.asyncio
class TestIssueCertificate:
    async def test_renew_existing_cert(self):
        import uuid as _u

        existing = MagicMock()
        existing.id = _u.uuid4()
        existing.cert_no = "OLDNO"
        existing.issued_at = datetime.utcnow() - timedelta(days=400)
        existing.expire_at = datetime.utcnow() - timedelta(days=35)
        existing.attempt_id = None

        session = MagicMock()
        session.execute = _ResultQueue([_ScalarsShim(existing)])
        session.add = MagicMock()
        session.flush = AsyncMock()

        out = await ExamService.issue_certificate(
            session, employee_id="E001", course_id=str(_u.uuid4()), attempt_id=str(_u.uuid4())
        )
        assert out["renewed"] is True
        assert out["cert_no"] == "OLDNO"
        # 未新增 add（只更新现有）
        session.add.assert_not_called()

    async def test_new_cert_number_format(self):
        import uuid as _u

        session = MagicMock()
        session.execute = _ResultQueue(
            [
                _ScalarsShim(None),  # 无 existing active
                _ScalarsShim(2),  # 本月已发 2
            ]
        )
        session.add = MagicMock()
        session.flush = AsyncMock()

        course_id = str(_u.uuid4())
        out = await ExamService.issue_certificate(session, employee_id="E099", course_id=course_id)
        ym = datetime.utcnow().strftime("%Y%m")
        # COURSE 前6位来自 course_id 去横杠
        expected_prefix = course_id.replace("-", "")[:6].upper()
        assert out["cert_no"] == f"{expected_prefix}{ym}0003"
        assert out["renewed"] is False
