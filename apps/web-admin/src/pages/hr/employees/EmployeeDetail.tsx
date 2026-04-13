/**
 * EmployeeDetail — 员工详情 7Tab (P0)
 * Sprint 5 · 员工主档
 *
 * API: GET /api/v1/employees/{employee_id}
 *      GET /api/v1/employees/{employee_id}/profile-tabs
 */

import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Tabs,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import { EditOutlined, UserOutlined } from '@ant-design/icons';
import { ProColumns, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Line } from '@ant-design/charts';
import { txFetchData } from '../../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface EmployeeBasic {
  id: string;
  name: string;
  employee_no: string;
  gender: string;
  birthday: string;
  phone: string;
  email: string;
  id_card: string;
  education: string;
  emergency_contact: string;
  emergency_phone: string;
  avatar_url: string | null;
  department_name: string;
  position_name: string;
  status: 'active' | 'probation' | 'resigned' | 'terminated';
}

interface PositionInfo {
  department_name: string;
  position_name: string;
  grade_name: string;
  employment_type: string;
  contract_start: string;
  contract_end: string;
  probation_end: string | null;
  transfer_history: { date: string; from_dept: string; to_dept: string; reason: string }[];
}

interface DocInfo {
  id: string;
  doc_type: string;
  doc_no: string;
  expiry_date: string;
  days_remaining: number;
}

interface AttendanceStat {
  present_days: number;
  late_count: number;
  early_leave_count: number;
  absent_days: number;
  schedule_grid: { date: string; shift: string; status: string }[];
}

interface PerformanceRecord {
  id: string;
  period: string;
  score: number;
  evaluator: string;
  comment: string;
}

interface SalaryRecord {
  id: string;
  month: string;
  gross_fen: number;
  net_fen: number;
  status: 'draft' | 'confirmed' | 'paid';
}

interface TrainingRecord {
  id: string;
  course_name: string;
  completed_at: string;
  score: number | null;
}

interface GrowthInfo {
  trainings: TrainingRecord[];
  skills: string[];
  promotions: { date: string; from_grade: string; to_grade: string }[];
}

interface ProfileTabs {
  position: PositionInfo;
  documents: DocInfo[];
  attendance: AttendanceStat;
  performance: { records: PerformanceRecord[]; point_balance: number; trend: { month: string; score: number }[] };
  salary: { records: SalaryRecord[]; trend: { month: string; net_yuan: number }[] };
  growth: GrowthInfo;
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

const statusBadge: Record<string, { status: 'success' | 'processing' | 'default'; text: string }> = {
  active: { status: 'success', text: '在职' },
  probation: { status: 'processing', text: '试用' },
  resigned: { status: 'default', text: '离职' },
  terminated: { status: 'default', text: '解除' },
};

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function docExpiryTag(days: number) {
  if (days < 0) return <Tag color="red" style={{ animation: 'pulse 1s infinite' }}>已过期</Tag>;
  if (days < 7) return <Tag color="red">{days}天</Tag>;
  if (days < 30) return <Tag color="orange">{days}天</Tag>;
  return <Tag color="green">{days}天</Tag>;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function EmployeeDetail() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const [basic, setBasic] = useState<EmployeeBasic | null>(null);
  const [tabs, setTabs] = useState<ProfileTabs | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!employeeId) return;
    setLoading(true);
    Promise.all([
      txFetchData<EmployeeBasic>(`/api/v1/employees/${employeeId}`),
      txFetchData<ProfileTabs>(`/api/v1/employees/${employeeId}/profile-tabs`),
    ])
      .then(([bResp, tResp]) => {
        setBasic(bResp.data);
        setTabs(tResp.data);
      })
      .catch(() => message.error('加载员工信息失败'))
      .finally(() => setLoading(false));
  }, [employeeId]);

  if (loading || !basic) return <Card loading />;

  const sb = statusBadge[basic.status] ?? statusBadge.active;

  // ─── Tab1: 基本信息 ───
  const Tab1 = (
    <Card
      extra={<Button icon={<EditOutlined />} onClick={() => message.info('编辑基本信息')}>编辑</Button>}
    >
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="姓名">{basic.name}</Descriptions.Item>
        <Descriptions.Item label="工号">{basic.employee_no}</Descriptions.Item>
        <Descriptions.Item label="性别">{basic.gender}</Descriptions.Item>
        <Descriptions.Item label="生日">{basic.birthday}</Descriptions.Item>
        <Descriptions.Item label="学历">{basic.education}</Descriptions.Item>
        <Descriptions.Item label="手机">{basic.phone}</Descriptions.Item>
        <Descriptions.Item label="邮箱">{basic.email}</Descriptions.Item>
        <Descriptions.Item label="身份证">{basic.id_card}</Descriptions.Item>
        <Descriptions.Item label="紧急联系人">{basic.emergency_contact}</Descriptions.Item>
        <Descriptions.Item label="紧急联系电话">{basic.emergency_phone}</Descriptions.Item>
      </Descriptions>
    </Card>
  );

  // ─── Tab2: 任职信息 ───
  const pos = tabs?.position;
  const Tab2 = (
    <Card>
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="部门">{pos?.department_name}</Descriptions.Item>
        <Descriptions.Item label="岗位">{pos?.position_name}</Descriptions.Item>
        <Descriptions.Item label="职级">{pos?.grade_name}</Descriptions.Item>
        <Descriptions.Item label="用工类型">{pos?.employment_type}</Descriptions.Item>
        <Descriptions.Item label="合同起始">{pos?.contract_start}</Descriptions.Item>
        <Descriptions.Item label="合同到期">{pos?.contract_end}</Descriptions.Item>
        {pos?.probation_end && (
          <Descriptions.Item label="试用期至">{pos.probation_end}</Descriptions.Item>
        )}
      </Descriptions>
      <Title level={5} style={{ marginTop: 24 }}>调岗记录</Title>
      <Timeline
        items={(pos?.transfer_history ?? []).map((t) => ({
          children: `${t.date} 从 ${t.from_dept} 调至 ${t.to_dept}（${t.reason}）`,
        }))}
      />
    </Card>
  );

  // ─── Tab3: 证照合同 ───
  const docCols: ProColumns<DocInfo>[] = [
    { title: '证照类型', dataIndex: 'doc_type' },
    { title: '证照编号', dataIndex: 'doc_no' },
    { title: '到期日期', dataIndex: 'expiry_date', valueType: 'date' },
    {
      title: '剩余天数',
      dataIndex: 'days_remaining',
      render: (_, r) => docExpiryTag(r.days_remaining),
    },
  ];
  const Tab3 = (
    <ProTable<DocInfo>
      columns={docCols}
      dataSource={tabs?.documents ?? []}
      rowKey="id"
      search={false}
      pagination={false}
      toolBarRender={false}
    />
  );

  // ─── Tab4: 班表考勤 ───
  const att = tabs?.attendance;
  const Tab4 = (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard statistic={{ title: '出勤天数', value: att?.present_days ?? 0, suffix: '天' }} />
        </Col>
        <Col span={6}>
          <StatisticCard statistic={{ title: '迟到', value: att?.late_count ?? 0, suffix: '次' }} />
        </Col>
        <Col span={6}>
          <StatisticCard statistic={{ title: '早退', value: att?.early_leave_count ?? 0, suffix: '次' }} />
        </Col>
        <Col span={6}>
          <StatisticCard statistic={{ title: '缺勤', value: att?.absent_days ?? 0, suffix: '天' }} />
        </Col>
      </Row>
      <Card title="本月排班">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
          {['一', '二', '三', '四', '五', '六', '日'].map((d) => (
            <div key={d} style={{ textAlign: 'center', fontWeight: 600, padding: 4 }}>{d}</div>
          ))}
          {(att?.schedule_grid ?? []).map((g, i) => (
            <div
              key={i}
              style={{
                textAlign: 'center',
                padding: 4,
                background: g.status === 'absent' ? '#fff1f0' : g.status === 'late' ? '#fff7e6' : '#f6ffed',
                borderRadius: 4,
                fontSize: 12,
              }}
            >
              <div>{g.date.slice(-2)}</div>
              <div style={{ color: '#888' }}>{g.shift}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );

  // ─── Tab5: 绩效积分 ───
  const perf = tabs?.performance;
  const perfCols: ProColumns<PerformanceRecord>[] = [
    { title: '考核期', dataIndex: 'period' },
    { title: '评分', dataIndex: 'score', valueType: 'digit' },
    { title: '评估人', dataIndex: 'evaluator' },
    { title: '评语', dataIndex: 'comment', ellipsis: true },
  ];
  const Tab5 = (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <StatisticCard statistic={{ title: '积分余额', value: perf?.point_balance ?? 0 }} />
        </Col>
        <Col span={16}>
          <Card title="绩效趋势">
            <Line
              data={perf?.trend ?? []}
              xField="month"
              yField="score"
              height={200}
              point={{ size: 4 }}
              color="#FF6B35"
            />
          </Card>
        </Col>
      </Row>
      <ProTable<PerformanceRecord>
        headerTitle="绩效记录"
        columns={perfCols}
        dataSource={perf?.records ?? []}
        rowKey="id"
        search={false}
        pagination={{ pageSize: 5 }}
        toolBarRender={false}
      />
    </div>
  );

  // ─── Tab6: 薪资记录 ───
  const sal = tabs?.salary;
  const salCols: ProColumns<SalaryRecord>[] = [
    { title: '月份', dataIndex: 'month' },
    { title: '应发(元)', dataIndex: 'gross_fen', render: (_, r) => `¥${fenToYuan(r.gross_fen)}` },
    { title: '实发(元)', dataIndex: 'net_fen', render: (_, r) => `¥${fenToYuan(r.net_fen)}` },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, r) => {
        const m: Record<string, { text: string; color: string }> = {
          draft: { text: '草稿', color: 'default' },
          confirmed: { text: '已确认', color: 'blue' },
          paid: { text: '已发放', color: 'green' },
        };
        const s = m[r.status] ?? m.draft;
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
  ];
  const Tab6 = (
    <div>
      <Card title="薪资趋势" style={{ marginBottom: 16 }}>
        <Line
          data={sal?.trend ?? []}
          xField="month"
          yField="net_yuan"
          height={200}
          point={{ size: 4 }}
          color="#FF6B35"
        />
      </Card>
      <ProTable<SalaryRecord>
        headerTitle="近6个月薪资"
        columns={salCols}
        dataSource={sal?.records ?? []}
        rowKey="id"
        search={false}
        pagination={false}
        toolBarRender={false}
      />
    </div>
  );

  // ─── Tab7: 成长记录 ───
  const growth = tabs?.growth;
  const trainCols: ProColumns<TrainingRecord>[] = [
    { title: '课程', dataIndex: 'course_name' },
    { title: '完成时间', dataIndex: 'completed_at', valueType: 'date' },
    { title: '成绩', dataIndex: 'score', render: (_, r) => r.score ?? '-' },
  ];
  const Tab7 = (
    <div>
      <ProTable<TrainingRecord>
        headerTitle="培训记录"
        columns={trainCols}
        dataSource={growth?.trainings ?? []}
        rowKey="id"
        search={false}
        pagination={{ pageSize: 5 }}
        toolBarRender={false}
      />
      <Card title="技能标签" style={{ marginTop: 16 }}>
        <Space wrap>
          {(growth?.skills ?? []).map((s) => (
            <Tag key={s} color="blue">{s}</Tag>
          ))}
        </Space>
      </Card>
      <Card title="晋升记录" style={{ marginTop: 16 }}>
        <Timeline
          items={(growth?.promotions ?? []).map((p) => ({
            children: `${p.date} 从 ${p.from_grade} 晋升至 ${p.to_grade}`,
            color: 'green',
          }))}
        />
      </Card>
    </div>
  );

  return (
    <div>
      {/* 顶部员工摘要 */}
      <Card style={{ marginBottom: 16 }}>
        <Space size="large" align="center">
          <Avatar size={64} src={basic.avatar_url} icon={<UserOutlined />} />
          <div>
            <Space>
              <Title level={4} style={{ margin: 0 }}>{basic.name}</Title>
              <Badge status={sb.status} text={sb.text} />
            </Space>
            <div>
              <Text type="secondary">{basic.department_name} · {basic.position_name} · {basic.employee_no}</Text>
            </div>
          </div>
        </Space>
      </Card>

      {/* 7 Tab */}
      <Card>
        <Tabs
          defaultActiveKey="basic"
          items={[
            { key: 'basic', label: '基本信息', children: Tab1 },
            { key: 'position', label: '任职信息', children: Tab2 },
            { key: 'docs', label: '证照合同', children: Tab3 },
            { key: 'attendance', label: '班表考勤', children: Tab4 },
            { key: 'performance', label: '绩效积分', children: Tab5 },
            { key: 'salary', label: '薪资记录', children: Tab6 },
            { key: 'growth', label: '成长记录', children: Tab7 },
          ]}
        />
      </Card>
    </div>
  );
}
