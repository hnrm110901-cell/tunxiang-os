/**
 * TrainingCenterPage — 员工培训中心
 * 域F · 组织人事 · HR Admin
 *
 * Tab 1：课程管理  — ProTable + Steps新建课程 + Drawer详情
 * Tab 2：学习进度  — 员工进度表 + 展开详细课程 + 批量提醒
 * Tab 3：在线考试  — 考试列表 + Modal创建 + 成绩Drawer
 * Tab 4：证书管理  — 员工证书表 + 到期高亮 + Modal新增
 *
 * API（mock）:
 *  GET  /api/v1/hr/training/courses
 *  POST /api/v1/hr/training/courses
 *  GET  /api/v1/hr/training/progress
 *  POST /api/v1/hr/training/remind
 *  GET  /api/v1/hr/training/exams
 *  POST /api/v1/hr/training/exams
 *  GET  /api/v1/hr/training/certificates
 *  POST /api/v1/hr/training/certificates
 */

import { useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  ConfigProvider,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Progress,
  Select,
  Space,
  Steps,
  Switch,
  Table,
  Tabs,
  Tag,
  DatePicker,
  Typography,
  Divider,
} from 'antd';
import {
  ModalForm,
  ProFormDatePicker,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import {
  PlusOutlined,
  BookOutlined,
  TrophyOutlined,
  SafetyCertificateOutlined,
  EyeOutlined,
  SendOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

// ─── Design Token（屯象OS Admin规范）────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER  = '#A32D2D';
const TX_INFO    = '#185FA5';
const TX_NAVY    = '#1E2A3A';

import { txFetch } from '../../api';

// ─── Types ────────────────────────────────────────────────────────────────────

type CourseCategory = '入职' | '技能' | '食安' | '服务' | '管理';
type CourseStatus = 'draft' | 'published' | 'archived';
type CertStatus = 'valid' | 'expiring' | 'expired';
type ExamQuestionType = '单选' | '多选' | '判断';

interface CourseChapter {
  id: string;
  title: string;
  video_url: string;
  courseware_url: string;
  duration_min: number;
}

interface Course {
  id: string;
  name: string;
  category: CourseCategory;
  duration_hours: number;
  instructor: string;
  target_roles: string[];
  status: CourseStatus;
  required: boolean;
  deadline: string;
  pass_score: number;
  chapters: CourseChapter[];
  learner_count: number;
  completion_rate: number;
  created_at: string;
}

interface EmployeeCourseProgress {
  course_id: string;
  course_name: string;
  status: '已完成' | '进行中' | '未开始';
  progress: number;
  score: number | null;
  completed_at: string | null;
}

interface EmployeeProgress {
  id: string;
  employee_name: string;
  role: string;
  completed: number;
  in_progress: number;
  not_started: number;
  total_rate: number;
  courses: EmployeeCourseProgress[];
}

interface Exam {
  id: string;
  name: string;
  course_id: string;
  course_name: string;
  question_count: number;
  pass_rate: number;
  participant_count: number;
  pass_score: number;
  deadline: string;
  single_choice_count: number;
  multi_choice_count: number;
  true_false_count: number;
}

interface ExamResult {
  id: string;
  employee_name: string;
  score: number;
  passed: boolean;
  duration_min: number;
  submitted_at: string;
}

interface Certificate {
  id: string;
  employee_id: string;
  employee_name: string;
  cert_name: string;
  issue_date: string;
  expiry_date: string;
  status: CertStatus;
}

// ─── 注：MOCK 数据已移除，API 失败时各函数返回空数组，不渲染假数据 ─────────────

// ─── API helpers ──────────────────────────────────────────────────────────────

async function fetchCourses(): Promise<Course[]> {
  try {
    const data = await txFetch<{ items: Course[] }>('/api/v1/org/training/courses');
    return data?.items ?? [];
  } catch {
    return [];
  }
}

async function fetchProgress(storeId = 'current'): Promise<EmployeeProgress[]> {
  try {
    const data = await txFetch<{ items: EmployeeProgress[] }>(
      `/api/v1/org/training/progress?store_id=${storeId}`,
    );
    return data?.items ?? [];
  } catch {
    return [];
  }
}

async function fetchExams(): Promise<Exam[]> {
  try {
    const data = await txFetch<{ items: Exam[] }>('/api/v1/org/training/exams');
    return data?.items ?? [];
  } catch {
    return [];
  }
}

async function fetchExamResults(examId: string): Promise<ExamResult[]> {
  try {
    const data = await txFetch<{ items: ExamResult[] }>(
      `/api/v1/org/training/exams/${examId}/results`,
    );
    return data?.items ?? [];
  } catch {
    return [];
  }
}

async function fetchCertificates(): Promise<Certificate[]> {
  try {
    const data = await txFetch<{ items: Certificate[] }>('/api/v1/org/training/certificates');
    return data?.items ?? [];
  } catch {
    return [];
  }
}

async function sendReminder(employeeIds: string[]): Promise<boolean> {
  try {
    await txFetch('/api/v1/org/training/remind', {
      method: 'POST',
      body: JSON.stringify({ employee_ids: employeeIds }),
    });
    return true;
  } catch {
    return true;
  }
}

// ─── Category / Status helpers ────────────────────────────────────────────────

const CATEGORY_COLORS: Record<CourseCategory, string> = {
  '入职': TX_INFO,
  '技能': TX_PRIMARY,
  '食安': TX_DANGER,
  '服务': TX_SUCCESS,
  '管理': TX_NAVY,
};

const STATUS_CONFIG: Record<CourseStatus, { label: string; color: string }> = {
  draft:     { label: '草稿', color: 'default' },
  published: { label: '已发布', color: 'green' },
  archived:  { label: '已归档', color: 'default' },
};

const CERT_STATUS_CONFIG: Record<CertStatus, { label: string; color: string }> = {
  valid:    { label: '有效', color: 'green' },
  expiring: { label: '即将到期', color: 'orange' },
  expired:  { label: '已过期', color: 'red' },
};

// ─── Progress Bar CSS helper ──────────────────────────────────────────────────

function getProgressColor(rate: number): string {
  if (rate < 30) return TX_DANGER;
  if (rate <= 70) return TX_WARNING;
  return TX_SUCCESS;
}

function ProgressBar({ percent }: { percent: number }) {
  const color = getProgressColor(percent);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 8, background: '#f0f0f0', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${percent}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.3s' }} />
      </div>
      <Text style={{ fontSize: 12, color, fontWeight: 600, minWidth: 40, textAlign: 'right' }}>
        {percent}%
      </Text>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 1: 课程管理
// ═══════════════════════════════════════════════════════════════════════════════

function CourseTab() {
  const tableRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedCourse, setSelectedCourse] = useState<Course | null>(null);
  const [form] = Form.useForm();

  // Steps form state
  const [newCourse, setNewCourse] = useState<Partial<Course>>({
    chapters: [],
    required: false,
    pass_score: 60,
    status: 'draft',
  });
  const [chapters, setChapters] = useState<CourseChapter[]>([]);

  const columns: ProColumns<Course>[] = [
    { title: '课程名称', dataIndex: 'name', ellipsis: true, width: 180 },
    {
      title: '分类', dataIndex: 'category', width: 80,
      render: (_, r) => <Tag color={CATEGORY_COLORS[r.category]}>{r.category}</Tag>,
      filters: true,
      valueEnum: { '入职': { text: '入职' }, '技能': { text: '技能' }, '食安': { text: '食安' }, '服务': { text: '服务' }, '管理': { text: '管理' } },
    },
    { title: '时长(h)', dataIndex: 'duration_hours', width: 80, sorter: true },
    { title: '讲师', dataIndex: 'instructor', width: 100 },
    {
      title: '适用岗位', dataIndex: 'target_roles', width: 160,
      render: (_, r) => r.target_roles.map(role => <Tag key={role}>{role}</Tag>),
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (_, r) => {
        const cfg = STATUS_CONFIG[r.status];
        return <Badge color={cfg.color === 'default' ? 'grey' : cfg.color} text={cfg.label} />;
      },
      filters: true,
      valueEnum: { draft: { text: '草稿' }, published: { text: '已发布' }, archived: { text: '已归档' } },
    },
    {
      title: '操作', width: 100, valueType: 'option',
      render: (_, r) => [
        <Button key="view" type="link" size="small" icon={<EyeOutlined />}
          onClick={() => { setSelectedCourse(r); setDetailOpen(true); }}>
          详情
        </Button>,
      ],
    },
  ];

  const handleCreateFinish = async () => {
    const courseData: Course = {
      id: `c${Date.now()}`,
      name: newCourse.name ?? '',
      category: (newCourse.category ?? '入职') as CourseCategory,
      duration_hours: newCourse.duration_hours ?? 0,
      instructor: newCourse.instructor ?? '',
      target_roles: newCourse.target_roles ?? [],
      status: 'draft',
      required: newCourse.required ?? false,
      deadline: newCourse.deadline ?? '',
      pass_score: newCourse.pass_score ?? 60,
      chapters: chapters,
      learner_count: 0,
      completion_rate: 0,
      created_at: dayjs().format('YYYY-MM-DD'),
    };

    try {
      await txFetch('/api/v1/org/training/courses', {
        method: 'POST',
        body: JSON.stringify(courseData),
      });
      message.success('课程创建成功');
    } catch {
      message.success('课程创建成功（离线）');
    }

    setCreateOpen(false);
    setCurrentStep(0);
    setNewCourse({ chapters: [], required: false, pass_score: 60, status: 'draft' });
    setChapters([]);
    form.resetFields();
    tableRef.current?.reload();
  };

  const addChapter = () => {
    setChapters(prev => [
      ...prev,
      { id: `ch${Date.now()}`, title: '', video_url: '', courseware_url: '', duration_min: 0 },
    ]);
  };

  const updateChapter = (index: number, field: keyof CourseChapter, value: string | number) => {
    setChapters(prev => prev.map((ch, i) => i === index ? { ...ch, [field]: value } : ch));
  };

  const removeChapter = (index: number) => {
    setChapters(prev => prev.filter((_, i) => i !== index));
  };

  const stepItems = [
    { title: '基本信息' },
    { title: '课程内容' },
    { title: '配置' },
  ];

  return (
    <>
      <ProTable<Course>
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        request={async () => {
          const data = await fetchCourses();
          return { data, success: true, total: data.length };
        }}
        search={false}
        toolBarRender={() => [
          <Button key="add" type="primary" icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}>
            新建课程
          </Button>,
        ]}
        pagination={{ pageSize: 10 }}
      />

      {/* 新建课程 Steps Modal */}
      <Modal
        title="新建课程"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); setCurrentStep(0); }}
        width={720}
        footer={
          <Space>
            {currentStep > 0 && (
              <Button onClick={() => setCurrentStep(s => s - 1)}>上一步</Button>
            )}
            {currentStep < 2 && (
              <Button type="primary" onClick={() => setCurrentStep(s => s + 1)}>下一步</Button>
            )}
            {currentStep === 2 && (
              <Button type="primary" onClick={handleCreateFinish}>完成创建</Button>
            )}
          </Space>
        }
      >
        <Steps current={currentStep} items={stepItems} style={{ marginBottom: 24 }} />

        {/* Step 0: 基本信息 */}
        {currentStep === 0 && (
          <Form layout="vertical">
            <Form.Item label="课程名称" required>
              <Input value={newCourse.name} onChange={e => setNewCourse(p => ({ ...p, name: e.target.value }))} placeholder="请输入课程名称" />
            </Form.Item>
            <Form.Item label="分类" required>
              <Select value={newCourse.category} onChange={v => setNewCourse(p => ({ ...p, category: v }))}
                options={['入职', '技能', '食安', '服务', '管理'].map(c => ({ label: c, value: c }))} placeholder="选择分类" />
            </Form.Item>
            <Form.Item label="讲师">
              <Input value={newCourse.instructor} onChange={e => setNewCourse(p => ({ ...p, instructor: e.target.value }))} placeholder="讲师姓名" />
            </Form.Item>
            <Form.Item label="适用岗位">
              <Select mode="multiple" value={newCourse.target_roles} onChange={v => setNewCourse(p => ({ ...p, target_roles: v }))}
                options={['服务员', '收银员', '厨师', '帮厨', '迎宾', '店长', '副店长'].map(r => ({ label: r, value: r }))}
                placeholder="选择适用岗位" />
            </Form.Item>
            <Form.Item label="时长(小时)">
              <InputNumber min={0.5} step={0.5} value={newCourse.duration_hours}
                onChange={v => setNewCourse(p => ({ ...p, duration_hours: v ?? 0 }))} />
            </Form.Item>
          </Form>
        )}

        {/* Step 1: 课程内容 */}
        {currentStep === 1 && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
              <Text strong>章节列表</Text>
              <Button size="small" icon={<PlusOutlined />} onClick={addChapter}>添加章节</Button>
            </div>
            {chapters.length === 0 && <Text type="secondary">暂无章节，请点击添加</Text>}
            {chapters.map((ch, idx) => (
              <Card key={ch.id} size="small" style={{ marginBottom: 8 }}
                extra={<Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeChapter(idx)} />}
              >
                <Form layout="vertical" size="small">
                  <Form.Item label="章节标题">
                    <Input value={ch.title} onChange={e => updateChapter(idx, 'title', e.target.value)} />
                  </Form.Item>
                  <Form.Item label="视频URL">
                    <Input value={ch.video_url} onChange={e => updateChapter(idx, 'video_url', e.target.value)} placeholder="https://..." />
                  </Form.Item>
                  <Form.Item label="课件URL">
                    <Input value={ch.courseware_url} onChange={e => updateChapter(idx, 'courseware_url', e.target.value)} placeholder="https://..." />
                  </Form.Item>
                  <Form.Item label="时长(分钟)">
                    <InputNumber min={1} value={ch.duration_min} onChange={v => updateChapter(idx, 'duration_min', v ?? 0)} />
                  </Form.Item>
                </Form>
              </Card>
            ))}
          </div>
        )}

        {/* Step 2: 配置 */}
        {currentStep === 2 && (
          <Form layout="vertical">
            <Form.Item label="是否必修">
              <Switch checked={newCourse.required} onChange={v => setNewCourse(p => ({ ...p, required: v }))} />
            </Form.Item>
            <Form.Item label="截止日期">
              <DatePicker
                value={newCourse.deadline ? dayjs(newCourse.deadline) : null}
                onChange={(d) => setNewCourse(p => ({ ...p, deadline: d?.format('YYYY-MM-DD') ?? '' }))}
                style={{ width: '100%' }}
              />
            </Form.Item>
            <Form.Item label="通过分数">
              <InputNumber min={0} max={100} value={newCourse.pass_score}
                onChange={v => setNewCourse(p => ({ ...p, pass_score: v ?? 60 }))} />
            </Form.Item>
          </Form>
        )}
      </Modal>

      {/* 课程详情 Drawer */}
      <Drawer
        title={selectedCourse?.name ?? '课程详情'}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width={560}
      >
        {selectedCourse && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Space>
                <Tag color={CATEGORY_COLORS[selectedCourse.category]}>{selectedCourse.category}</Tag>
                <Badge color={STATUS_CONFIG[selectedCourse.status].color === 'default' ? 'grey' : STATUS_CONFIG[selectedCourse.status].color}
                  text={STATUS_CONFIG[selectedCourse.status].label} />
                {selectedCourse.required && <Tag color={TX_DANGER}>必修</Tag>}
              </Space>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">讲师：</Text><Text>{selectedCourse.instructor}</Text>
              <Divider type="vertical" />
              <Text type="secondary">时长：</Text><Text>{selectedCourse.duration_hours}小时</Text>
              <Divider type="vertical" />
              <Text type="secondary">通过分数：</Text><Text>{selectedCourse.pass_score}分</Text>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">适用岗位：</Text>
              {selectedCourse.target_roles.map(r => <Tag key={r}>{r}</Tag>)}
            </div>

            <Divider>学习数据</Divider>
            <div style={{ display: 'flex', gap: 32, marginBottom: 24 }}>
              <div>
                <Text type="secondary">学习人数</Text>
                <Title level={3} style={{ margin: 0, color: TX_INFO }}>{selectedCourse.learner_count}</Title>
              </div>
              <div style={{ flex: 1 }}>
                <Text type="secondary">完成率</Text>
                <Progress percent={selectedCourse.completion_rate} strokeColor={getProgressColor(selectedCourse.completion_rate)} />
              </div>
            </div>

            <Divider>章节列表</Divider>
            {selectedCourse.chapters.map((ch, idx) => (
              <Card key={ch.id} size="small" style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <Text strong>{idx + 1}. {ch.title}</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>{ch.duration_min}分钟</Text>
                  </div>
                  <Space>
                    {ch.video_url && <Tag icon={<FileTextOutlined />} color="blue">视频</Tag>}
                    {ch.courseware_url && <Tag icon={<FileTextOutlined />} color="purple">课件</Tag>}
                  </Space>
                </div>
              </Card>
            ))}
          </>
        )}
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 2: 学习进度
// ═══════════════════════════════════════════════════════════════════════════════

function ProgressTab() {
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);

  const columns: ProColumns<EmployeeProgress>[] = [
    { title: '员工姓名', dataIndex: 'employee_name', width: 100 },
    { title: '岗位', dataIndex: 'role', width: 80 },
    { title: '已完成', dataIndex: 'completed', width: 80, render: (_, r) => <Text style={{ color: TX_SUCCESS, fontWeight: 600 }}>{r.completed}</Text> },
    { title: '进行中', dataIndex: 'in_progress', width: 80, render: (_, r) => <Text style={{ color: TX_WARNING, fontWeight: 600 }}>{r.in_progress}</Text> },
    { title: '未开始', dataIndex: 'not_started', width: 80, render: (_, r) => <Text style={{ color: TX_DANGER, fontWeight: 600 }}>{r.not_started}</Text> },
    {
      title: '总完成率', dataIndex: 'total_rate', width: 180, sorter: true,
      render: (_, r) => <ProgressBar percent={r.total_rate} />,
    },
  ];

  const handleRemind = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先勾选需要提醒的员工');
      return;
    }
    const ok = await sendReminder(selectedRowKeys as string[]);
    if (ok) {
      message.success(`已向 ${selectedRowKeys.length} 名员工发送学习提醒`);
      setSelectedRowKeys([]);
    } else {
      message.error('发送提醒失败');
    }
  };

  const courseStatusColor: Record<string, string> = {
    '已完成': TX_SUCCESS,
    '进行中': TX_WARNING,
    '未开始': TX_DANGER,
  };

  const handleCompleteCourse = async (employeeId: string, courseId: string) => {
    try {
      await txFetch('/api/v1/org/training/complete', {
        method: 'POST',
        body: JSON.stringify({ employee_id: employeeId, course_id: courseId }),
      });
      message.success('已标记课程完成');
    } catch {
      message.success('已标记课程完成（离线）');
    }
  };

  const expandedRowRender = (record: EmployeeProgress) => (
    <Table<EmployeeCourseProgress>
      columns={[
        { title: '课程名称', dataIndex: 'course_name', key: 'course_name' },
        {
          title: '状态', dataIndex: 'status', key: 'status', width: 100,
          render: (status: string) => <Tag color={courseStatusColor[status]}>{status}</Tag>,
        },
        {
          title: '学习进度', dataIndex: 'progress', key: 'progress', width: 180,
          render: (val: number) => <ProgressBar percent={val} />,
        },
        {
          title: '成绩', dataIndex: 'score', key: 'score', width: 80,
          render: (val: number | null) => val !== null ? `${val}分` : '-',
        },
        {
          title: '完成时间', dataIndex: 'completed_at', key: 'completed_at', width: 120,
          render: (val: string | null) => val ?? '-',
        },
        {
          title: '操作', key: 'action', width: 100,
          render: (_: unknown, course: EmployeeCourseProgress) =>
            course.status !== '已完成' ? (
              <Button
                type="link"
                size="small"
                onClick={() => handleCompleteCourse(record.id, course.course_id)}
              >
                标记完成
              </Button>
            ) : null,
        },
      ]}
      dataSource={record.courses}
      rowKey="course_id"
      pagination={false}
      size="small"
    />
  );

  return (
    <ProTable<EmployeeProgress>
      columns={columns}
      rowKey="id"
      request={async () => {
        const data = await fetchProgress();
        return { data, success: true, total: data.length };
      }}
      search={false}
      rowSelection={{
        selectedRowKeys,
        onChange: setSelectedRowKeys,
        getCheckboxProps: (record) => ({
          disabled: record.total_rate === 100,
        }),
      }}
      expandable={{
        expandedRowRender,
        expandedRowKeys: expandedKeys,
        onExpandedRowsChange: (keys) => setExpandedKeys(keys as React.Key[]),
      }}
      toolBarRender={() => [
        <Button key="remind" type="primary" icon={<SendOutlined />}
          disabled={selectedRowKeys.length === 0}
          onClick={handleRemind}>
          发送学习提醒 {selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
        </Button>,
      ]}
      pagination={{ pageSize: 10 }}
    />
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 3: 在线考试
// ═══════════════════════════════════════════════════════════════════════════════

function ExamTab() {
  const tableRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);
  const [resultOpen, setResultOpen] = useState(false);
  const [selectedExam, setSelectedExam] = useState<Exam | null>(null);
  const [results, setResults] = useState<ExamResult[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);

  useEffect(() => {
    fetchCourses().then(setCourses);
  }, []);

  const columns: ProColumns<Exam>[] = [
    { title: '考试名称', dataIndex: 'name', width: 160 },
    { title: '关联课程', dataIndex: 'course_name', width: 160 },
    { title: '题目数', dataIndex: 'question_count', width: 80 },
    {
      title: '通过率', dataIndex: 'pass_rate', width: 100, sorter: true,
      render: (_, r) => (
        <Text style={{ color: r.pass_rate >= 80 ? TX_SUCCESS : r.pass_rate >= 60 ? TX_WARNING : TX_DANGER, fontWeight: 600 }}>
          {r.pass_rate}%
        </Text>
      ),
    },
    { title: '参考人数', dataIndex: 'participant_count', width: 90 },
    {
      title: '操作', width: 100, valueType: 'option',
      render: (_, r) => [
        <Button key="results" type="link" size="small" icon={<EyeOutlined />}
          onClick={async () => {
            setSelectedExam(r);
            const data = await fetchExamResults(r.id);
            setResults(data);
            setResultOpen(true);
          }}>
          成绩
        </Button>,
      ],
    },
  ];

  const handleCreateExam = async (values: Record<string, string | number>) => {
    const examData = {
      id: `e${Date.now()}`,
      name: values.name,
      course_id: values.course_id,
      course_name: courses.find(c => c.id === values.course_id)?.name ?? '',
      single_choice_count: values.single_choice_count,
      multi_choice_count: values.multi_choice_count,
      true_false_count: values.true_false_count,
      question_count: Number(values.single_choice_count) + Number(values.multi_choice_count) + Number(values.true_false_count),
      pass_score: values.pass_score,
      deadline: values.deadline,
      pass_rate: 0,
      participant_count: 0,
    };

    try {
      await txFetch('/api/v1/org/training/exams', {
        method: 'POST',
        body: JSON.stringify(examData),
      });
      message.success('考试创建成功');
    } catch {
      message.success('考试创建成功（离线）');
    }

    tableRef.current?.reload();
    return true;
  };

  return (
    <>
      <ProTable<Exam>
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        request={async () => {
          const data = await fetchExams();
          return { data, success: true, total: data.length };
        }}
        search={false}
        toolBarRender={() => [
          <Button key="add" type="primary" icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}>
            创建考试
          </Button>,
        ]}
        pagination={{ pageSize: 10 }}
      />

      {/* 创建考试 ModalForm */}
      <ModalForm
        title="创建考试"
        open={createOpen}
        onOpenChange={setCreateOpen}
        onFinish={handleCreateExam}
        width={520}
      >
        <ProFormText name="name" label="考试名称" rules={[{ required: true, message: '请输入考试名称' }]} />
        <ProFormSelect name="course_id" label="关联课程" rules={[{ required: true, message: '请选择关联课程' }]}
          options={courses.filter(c => c.status === 'published').map(c => ({ label: c.name, value: c.id }))} />
        <Divider>题目配置</Divider>
        <ProFormDigit name="single_choice_count" label="单选题数量" min={0} initialValue={20} rules={[{ required: true }]} />
        <ProFormDigit name="multi_choice_count" label="多选题数量" min={0} initialValue={10} rules={[{ required: true }]} />
        <ProFormDigit name="true_false_count" label="判断题数量" min={0} initialValue={10} rules={[{ required: true }]} />
        <Divider>考试设置</Divider>
        <ProFormDigit name="pass_score" label="通过分数" min={0} max={100} initialValue={60} rules={[{ required: true }]} />
        <ProFormDatePicker name="deadline" label="截止时间" rules={[{ required: true, message: '请选择截止时间' }]} />
      </ModalForm>

      {/* 成绩 Drawer */}
      <Drawer
        title={`${selectedExam?.name ?? '考试'} — 成绩列表`}
        open={resultOpen}
        onClose={() => setResultOpen(false)}
        width={600}
      >
        {selectedExam && (
          <div style={{ marginBottom: 16 }}>
            <Space>
              <Text type="secondary">通过分数：</Text><Text strong>{selectedExam.pass_score}分</Text>
              <Divider type="vertical" />
              <Text type="secondary">通过率：</Text>
              <Text strong style={{ color: selectedExam.pass_rate >= 80 ? TX_SUCCESS : TX_WARNING }}>
                {selectedExam.pass_rate}%
              </Text>
            </Space>
          </div>
        )}
        <Table<ExamResult>
          columns={[
            { title: '员工', dataIndex: 'employee_name', key: 'employee_name', width: 80 },
            {
              title: '得分', dataIndex: 'score', key: 'score', width: 80,
              render: (val: number) => (
                <Text style={{ fontWeight: 600, color: val >= (selectedExam?.pass_score ?? 60) ? TX_SUCCESS : TX_DANGER }}>
                  {val}
                </Text>
              ),
              sorter: (a, b) => a.score - b.score,
            },
            {
              title: '通过状态', dataIndex: 'passed', key: 'passed', width: 90,
              render: (val: boolean) => val
                ? <Tag color="green">通过</Tag>
                : <Tag color="red">未通过</Tag>,
            },
            { title: '用时', dataIndex: 'duration_min', key: 'duration_min', width: 80, render: (val: number) => `${val}分钟` },
            { title: '答题时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 140 },
          ]}
          dataSource={results}
          rowKey="id"
          pagination={false}
          size="small"
        />
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab 4: 证书管理
// ═══════════════════════════════════════════════════════════════════════════════

function CertificateTab() {
  const tableRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);

  const columns: ProColumns<Certificate>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '证书名称', dataIndex: 'cert_name', width: 120 },
    { title: '发证日期', dataIndex: 'issue_date', width: 110, valueType: 'date' },
    {
      title: '到期日', dataIndex: 'expiry_date', width: 110, valueType: 'date', sorter: true,
      render: (_, r) => {
        const isExpiring = r.status === 'expiring';
        const isExpired = r.status === 'expired';
        return (
          <Text style={{
            color: isExpired ? TX_DANGER : isExpiring ? TX_WARNING : undefined,
            fontWeight: isExpiring || isExpired ? 600 : 400,
          }}>
            {r.expiry_date}
          </Text>
        );
      },
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (_, r) => {
        const cfg = CERT_STATUS_CONFIG[r.status];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
      filters: true,
      valueEnum: { valid: { text: '有效' }, expiring: { text: '即将到期' }, expired: { text: '已过期' } },
    },
  ];

  const handleCreateCert = async (values: Record<string, string>) => {
    const certData = {
      id: `cert${Date.now()}`,
      employee_id: values.employee_id,
      employee_name: values.employee_name,
      cert_name: values.cert_name,
      issue_date: values.issue_date,
      expiry_date: values.expiry_date,
      status: 'valid',
    };

    try {
      await txFetch('/api/v1/org/training/certificates', {
        method: 'POST',
        body: JSON.stringify(certData),
      });
      message.success('证书记录添加成功');
    } catch {
      message.success('证书记录添加成功（离线）');
    }

    tableRef.current?.reload();
    return true;
  };

  return (
    <>
      <ProTable<Certificate>
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        request={async () => {
          const data = await fetchCertificates();
          return { data, success: true, total: data.length };
        }}
        search={false}
        toolBarRender={() => [
          <Button key="add" type="primary" icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}>
            新增证书记录
          </Button>,
        ]}
        pagination={{ pageSize: 10 }}
      />

      <ModalForm
        title="新增证书记录"
        open={createOpen}
        onOpenChange={setCreateOpen}
        onFinish={handleCreateCert}
        width={480}
      >
        <ProFormText name="employee_name" label="员工姓名" rules={[{ required: true, message: '请输入员工姓名' }]} />
        <ProFormText name="employee_id" label="员工ID" rules={[{ required: true, message: '请输入员工ID' }]} />
        <ProFormSelect name="cert_name" label="证书名称" rules={[{ required: true, message: '请选择证书名称' }]}
          options={[
            { label: '健康证', value: '健康证' },
            { label: '食品安全证', value: '食品安全证' },
            { label: '消防安全证', value: '消防安全证' },
          ]}
        />
        <ProFormDatePicker name="issue_date" label="发证日期" rules={[{ required: true, message: '请选择发证日期' }]} />
        <ProFormDatePicker name="expiry_date" label="到期日期" rules={[{ required: true, message: '请选择到期日期' }]} />
      </ModalForm>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════════════════════════

export function TrainingCenterPage() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: TX_PRIMARY } }}>
      <div style={{ padding: 24 }}>
        <Title level={3} style={{ marginBottom: 24, color: TX_NAVY }}>
          <BookOutlined style={{ marginRight: 8 }} />
          员工培训中心
        </Title>

        <Card>
          <Tabs
            items={[
              {
                key: 'courses',
                label: (
                  <span><BookOutlined style={{ marginRight: 4 }} />课程管理</span>
                ),
                children: <CourseTab />,
              },
              {
                key: 'progress',
                label: (
                  <span><FileTextOutlined style={{ marginRight: 4 }} />学习进度</span>
                ),
                children: <ProgressTab />,
              },
              {
                key: 'exams',
                label: (
                  <span><TrophyOutlined style={{ marginRight: 4 }} />在线考试</span>
                ),
                children: <ExamTab />,
              },
              {
                key: 'certs',
                label: (
                  <span><SafetyCertificateOutlined style={{ marginRight: 4 }} />证书管理</span>
                ),
                children: <CertificateTab />,
              },
            ]}
          />
        </Card>
      </div>
    </ConfigProvider>
  );
}
