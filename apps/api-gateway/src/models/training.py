"""
Training Models — 培训课程/报名/考试/认证
对标麦麦e学：课程→学习→考试→认证→学分
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID

from .base import Base, TimestampMixin


class TrainingCourse(Base, TimestampMixin):
    """培训课程"""

    __tablename__ = "training_courses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(String(50), nullable=False, index=True)
    store_id = Column(String(50), nullable=True, index=True)  # NULL=品牌通用

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False)  # safety/service/cooking/management/culture
    course_type = Column(String(30), nullable=False, default="online")  # online/offline/practice
    applicable_positions = Column(JSON, nullable=True)  # ["waiter","chef"]
    duration_minutes = Column(Integer, nullable=False, default=60)
    content_url = Column(String(500), nullable=True)  # 课件链接
    pass_score = Column(Integer, default=60)
    credits = Column(Integer, default=1)  # 学分
    is_mandatory = Column(Boolean, default=False)  # 必修/选修
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<TrainingCourse(title='{self.title}', category='{self.category}')>"


class TrainingEnrollment(Base, TimestampMixin):
    """培训报名/学习记录"""

    __tablename__ = "training_enrollments"
    __table_args__ = (UniqueConstraint("employee_id", "course_id", name="uq_training_enrollment"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    employee_id = Column(String(50), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id"), nullable=False, index=True)

    status = Column(String(20), nullable=False, default="enrolled")  # enrolled/in_progress/completed/failed
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    progress_pct = Column(Integer, default=0)  # 0-100
    score = Column(Integer, nullable=True)  # 考试分数
    certificate_no = Column(String(50), nullable=True)
    certified_at = Column(Date, nullable=True)

    def __repr__(self):
        return f"<TrainingEnrollment(emp='{self.employee_id}', status='{self.status}')>"


class TrainingExam(Base, TimestampMixin):
    """考试/测验"""

    __tablename__ = "training_exams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    questions = Column(JSON, nullable=False)  # [{q, options, answer, score}]
    total_score = Column(Integer, nullable=False, default=100)
    pass_score = Column(Integer, nullable=False, default=60)
    time_limit_minutes = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<TrainingExam(title='{self.title}')>"


class ExamAttempt(Base, TimestampMixin):
    """考试记录 — D11 Should-Fix P1 扩展：paper_id / 计时 / 状态"""

    __tablename__ = "exam_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 兼容历史：exam_id 保留可空；新考试流程统一走 paper_id
    exam_id = Column(UUID(as_uuid=True), ForeignKey("training_exams.id"), nullable=True, index=True)
    paper_id = Column(UUID(as_uuid=True), ForeignKey("exam_papers.id"), nullable=True, index=True)
    employee_id = Column(String(50), nullable=False, index=True)
    store_id = Column(String(50), nullable=False, index=True)
    answers = Column(JSON, nullable=True)  # {"q1":"A","q2":["A","B"],"meta":{"leave_count":0}}
    score = Column(Integer, nullable=False, default=0)
    passed = Column(Boolean, nullable=False, default=False)
    attempted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Should-Fix P1 新增
    started_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    # in_progress / submitted / graded / expired
    status = Column(String(20), nullable=False, default="in_progress")

    def __repr__(self):
        return f"<ExamAttempt(paper='{self.paper_id}', score={self.score}, status='{self.status}')>"


class ExamQuestion(Base, TimestampMixin):
    """考试题库题目 — D11 Should-Fix P1"""

    __tablename__ = "exam_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id"), nullable=False, index=True)
    # single / multi / judge / fill / essay
    type = Column(String(20), nullable=False, default="single")
    stem = Column(Text, nullable=False)  # 题干
    options_json = Column(JSON, nullable=True)  # [{"key":"A","text":"..."}]；填空/主观可空
    correct_answer_json = Column(JSON, nullable=True)  # 单:"A" 多:["A","B"] 判:true 填:"xxx" 主观:null
    score = Column(Integer, nullable=False, default=5)
    difficulty = Column(Integer, nullable=False, default=3)  # 1-5
    explanation = Column(Text, nullable=True)  # 答案解析
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<ExamQuestion(type='{self.type}', score={self.score})>"


class ExamPaper(Base, TimestampMixin):
    """试卷 — 题目集合快照 + 及格线 + 考试时长"""

    __tablename__ = "exam_papers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    total_score = Column(Integer, nullable=False, default=100)
    pass_score = Column(Integer, nullable=False, default=60)
    duration_min = Column(Integer, nullable=False, default=30)
    question_count = Column(Integer, nullable=False, default=0)
    question_ids_json = Column(JSON, nullable=False)  # ["uuid1","uuid2",...]
    is_random = Column(Boolean, default=False, nullable=False)  # 是否随机题序
    created_by = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<ExamPaper(title='{self.title}', q_count={self.question_count})>"


class ExamCertificate(Base, TimestampMixin):
    """考试通过后颁发的证书（PDF 留待后续实现）"""

    __tablename__ = "exam_certificates"
    __table_args__ = (UniqueConstraint("employee_id", "course_id", "cert_no", name="uq_exam_cert"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), nullable=False, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id"), nullable=False, index=True)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("exam_attempts.id"), nullable=True)
    cert_no = Column(String(64), nullable=False, index=True)  # 形如 COURSE+YYYYMM+序号
    issued_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expire_at = Column(DateTime, nullable=True)  # 默认 1 年
    pdf_url = Column(String(500), nullable=True)  # 先占位，暂不生成
    # active / expired / revoked
    status = Column(String(20), nullable=False, default="active")

    def __repr__(self):
        return f"<ExamCertificate(cert_no='{self.cert_no}', status='{self.status}')>"


class TrainingMaterial(Base, TimestampMixin):
    """培训课件/资料（视频/PDF/文本） — D11 Must-Fix P0 补齐存储基础"""

    __tablename__ = "training_materials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id"), nullable=False, index=True)

    # 课件基础属性
    title = Column(String(200), nullable=False)
    material_type = Column(String(20), nullable=False, default="video")  # video/pdf/ppt/image/text/link
    file_url = Column(String(500), nullable=True)  # OSS/对象存储URL
    file_size_bytes = Column(Integer, nullable=True)  # 文件大小（字节）
    duration_seconds = Column(Integer, nullable=True)  # 时长（秒，视频/音频用）
    text_content = Column(Text, nullable=True)  # 纯文本/富文本内容
    sort_order = Column(Integer, default=0, nullable=False)  # 章节排序
    is_required = Column(Boolean, default=True, nullable=False)  # 是否必学
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<TrainingMaterial(title='{self.title}', type='{self.material_type}')>"
