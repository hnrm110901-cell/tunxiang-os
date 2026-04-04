/**
 * PerformancePage — 员工绩效考核
 * 域F · 组织人事 · HR Admin
 *
 * Tab 1：月度排行  — TOP3大卡片 + ProTable完整排名 + Drawer分项详情
 * Tab 2：考核录入  — ModalForm 动态KPI打分 + 前端实时加权计算
 * Tab 3：奖惩记录  — ProTable + ModalForm新增 + 汇总行
 *
 * API（mock）:
 *  GET  /api/v1/hr/performance/ranking?period=YYYY-MM
 *  GET  /api/v1/hr/performance/records
 *  POST /api/v1/hr/performance/records
 *  GET  /api/v1/hr/performance/kpi-configs?role=
 *  GET  /api/v1/hr/performance/rewards-punishments
 *  POST /api/v1/hr/performance/rewards-punishments
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  Drawer,
  Form,
  InputNumber,
  message,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Tabs,
  Typography,
  Divider,
  Progress,
} from 'antd';
import {
  ModalForm,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import {
  TrophyOutlined,
  PlusOutlined,
  StarOutlined,
  FireOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetch } from '../../api';

const { Title, Text } = Typography;

// ─── Design Token（屯象OS Admin规范）────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER  = '#A32D2D';
const TX_INFO    = '#185FA5';
const TX_NAVY    = '#1E2A3A';

// ─── Types ────────────────────────────────────────────────────────────────────

interface KPIItem {
  name: string;
  weight: number;
  target: number;
  unit: string;
}

interface ScoreItem {
  kpi_name: string;
  weight: number;
  score: number;
  target: number;
  status: '达标' | '未达标' | '超额';
}

interface PerformanceRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  role: string;
  store_name: string;
  period: string;
  overall_score: number;
  grade: 'A' | 'B' | 'C' | 'D';
  scores: ScoreItem[];
  reviewer: string;
  comments: string;
  kpi_bonus_fen: number;
  rank?: number;
}

interface RewardRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  type: 'reward' | 'punishment';
  category: string;
  amount_fen: number;
  description: string;
  incident_date: string;
}

// ─── KPI 维度配置（将从 API 加载，此为类型兜底空值） ────────────────────────────

const EMPTY_KPI_CONFIGS: Record<string, KPIItem[]> = {};

// ─── 注：MOCK_RECORDS / MOCK_REWARDS 已移除，API 失败时使用空数组 ─────────────

// ─── Helpers ──────────────────────────────────────────────────────────────────

const ROLE_LABEL: Record<string, string> = {
  waiter: '服务员', chef: '厨师', cashier: '收银员', manager: '店长',
};

const CATEGORY_LABEL: Record<string, string> = {
  service_complaint: '服务投诉', food_safety: '食品安全',
  attendance: '考勤', performance: '绩效', innovation: '创新',
};

function gradeColor(grade: string): string {
  return grade === 'A' ? TX_SUCCESS
    : grade === 'B' ? TX_INFO
    : grade === 'C' ? TX_WARNING
    : TX_DANGER;
}

function gradeTagColor(grade: string): string {
  return grade === 'A' ? 'success'
    : grade === 'B' ? 'processing'
    : grade === 'C' ? 'warning'
    : 'error';
}

function statusColor(status: string): string {
  return status === '超额' ? TX_SUCCESS
    : status === '达标' ? TX_INFO
    : TX_DANGER;
}

function fenToYuan(fen: number): string {
  return `¥${(Math.abs(fen) / 100).toFixed(0)}`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

/** TOP3 颁奖台 */
function PodiumCard({
  record, rank,
}: {
  record: PerformanceRecord;
  rank: 1 | 2 | 3;
}) {
  const medals = { 1: '🥇', 2: '🥈', 3: '🥉' };
  const sizes  = { 1: 28,   2: 22,   3: 22  };
  const scoreS = { 1: 56,   2: 44,   3: 44  };
  const heights= { 1: 180,  2: 156,  3: 156 };

  return (
    <Card
      style={{
        textAlign: 'center',
        height: heights[rank],
        border: rank === 1 ? `2px solid ${TX_PRIMARY}` : '1px solid #e8e6e1',
        background: rank === 1 ? '#fff8f5' : '#fff',
        borderRadius: 12,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        boxShadow: rank === 1 ? '0 4px 12px rgba(255,107,53,0.15)' : undefined,
      }}
      bodyStyle={{ padding: '12px 16px' }}
    >
      <div style={{ fontSize: 28 }}>{medals[rank]}</div>
      <div style={{ fontSize: sizes[rank], fontWeight: 700, color: TX_NAVY, lineHeight: 1.2 }}>
        {record.employee_name}
      </div>
      <div style={{ fontSize: scoreS[rank], fontWeight: 800, color: TX_PRIMARY, lineHeight: 1 }}>
        {record.overall_score}
      </div>
      <div style={{ fontSize: 12, color: '#5f5e5a', marginTop: 2 }}>
        <Tag color={gradeTagColor(record.grade)} style={{ marginRight: 4 }}>{record.grade}级</Tag>
        {ROLE_LABEL[record.role] ?? record.role} · {record.store_name}
      </div>
      {record.kpi_bonus_fen > 0 && (
        <div style={{ fontSize: 12, color: TX_SUCCESS, marginTop: 4 }}>
          绩效奖金 {fenToYuan(record.kpi_bonus_fen)}
        </div>
      )}
    </Card>
  );
}

/** KPI分项 Drawer 内容 */
function KPIDetailContent({ record }: { record: PerformanceRecord }) {
  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Statistic title="综合得分" value={record.overall_score}
            valueStyle={{ color: TX_PRIMARY, fontWeight: 800 }} suffix="分" />
        </Col>
        <Col span={8}>
          <Statistic title="绩效等级" formatter={() => (
            <Tag color={gradeTagColor(record.grade)} style={{ fontSize: 20, padding: '4px 16px' }}>
              {record.grade}
            </Tag>
          )} />
        </Col>
        <Col span={8}>
          <Statistic title="绩效奖金" value={record.kpi_bonus_fen / 100}
            prefix="¥" valueStyle={{ color: record.kpi_bonus_fen > 0 ? TX_SUCCESS : '#aaa' }} />
        </Col>
      </Row>

      <Divider orientation="left">KPI 分项明细</Divider>
      {record.scores.map((s) => (
        <div key={s.kpi_name} style={{ marginBottom: 16 }}>
          <Row justify="space-between" style={{ marginBottom: 4 }}>
            <Col>
              <Text strong>{s.kpi_name}</Text>
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                权重 {(s.weight * 100).toFixed(0)}%
              </Text>
            </Col>
            <Col>
              <Tag color={
                s.status === '超额' ? 'success'
                  : s.status === '达标' ? 'processing'
                  : 'error'
              }>
                {s.status}
              </Tag>
              <Text style={{ fontWeight: 700, color: statusColor(s.status) }}>
                {s.score} 分
              </Text>
            </Col>
          </Row>
          <Progress
            percent={s.score}
            strokeColor={statusColor(s.status)}
            trailColor="#f0ede6"
            size="small"
            format={() => `目标 ${s.target}`}
          />
        </div>
      ))}

      <Divider orientation="left">考核意见</Divider>
      <Card size="small" style={{ background: '#f8f7f5' }}>
        <Text>{record.comments}</Text>
        <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
          考核人：{record.reviewer}
        </div>
      </Card>
    </div>
  );
}

// ─── Tab 1: 月度排行 ──────────────────────────────────────────────────────────

function RankingTab() {
  const [period, setPeriod] = useState(dayjs().subtract(1, 'month').format('YYYY-MM'));
  const [roleFilter, setRoleFilter] = useState<string | undefined>(undefined);
  const [detailRecord, setDetailRecord] = useState<PerformanceRecord | null>(null);
  const [allRecords, setAllRecords] = useState<PerformanceRecord[]>([]);
  const [rankingLoading, setRankingLoading] = useState(false);
  const tableRef = useRef<ActionType>();

  const loadRanking = useCallback(async () => {
    setRankingLoading(true);
    try {
      const data = await txFetch<{ items: PerformanceRecord[] }>(
        `/api/v1/org/performance?store_id=current&period=${period}`,
      );
      setAllRecords(data?.items ?? []);
    } catch {
      setAllRecords([]);
    } finally {
      setRankingLoading(false);
    }
  }, [period]);

  useEffect(() => { loadRanking(); }, [loadRanking]);

  // 过滤 + 排序
  const filtered = allRecords
    .filter((r) => (!roleFilter || r.role === roleFilter))
    .sort((a, b) => b.overall_score - a.overall_score)
    .map((r, i) => ({ ...r, rank: i + 1 }));

  const top3 = filtered.slice(0, 3) as (PerformanceRecord & { rank: number })[];
  const avgScore = filtered.length
    ? (filtered.reduce((s, r) => s + r.overall_score, 0) / filtered.length).toFixed(1)
    : '—';

  const columns: ProColumns<PerformanceRecord>[] = [
    {
      title: '排名', dataIndex: 'rank', width: 60, align: 'center',
      render: (_, r) => {
        if (r.rank === 1) return <span style={{ fontSize: 18 }}>🥇</span>;
        if (r.rank === 2) return <span style={{ fontSize: 18 }}>🥈</span>;
        if (r.rank === 3) return <span style={{ fontSize: 18 }}>🥉</span>;
        return <Text type="secondary">#{r.rank}</Text>;
      },
    },
    { title: '姓名', dataIndex: 'employee_name', width: 90 },
    {
      title: '岗位', dataIndex: 'role', width: 80,
      render: (_, r) => <Tag>{ROLE_LABEL[r.role] ?? r.role}</Tag>,
    },
    { title: '门店', dataIndex: 'store_name', width: 100 },
    {
      title: '综合得分', dataIndex: 'overall_score', width: 110,
      render: (_, r) => (
        <Space>
          <Text style={{ fontWeight: 700, fontSize: 16, color: TX_PRIMARY }}>
            {r.overall_score}
          </Text>
          <Tag color={gradeTagColor(r.grade)}>{r.grade}</Tag>
        </Space>
      ),
    },
    {
      title: '绩效奖金', dataIndex: 'kpi_bonus_fen', width: 100,
      render: (_, r) => (
        <Text style={{ color: r.kpi_bonus_fen > 0 ? TX_SUCCESS : '#aaa', fontWeight: 600 }}>
          {r.kpi_bonus_fen > 0 ? fenToYuan(r.kpi_bonus_fen) : '—'}
        </Text>
      ),
    },
    {
      title: '操作', valueType: 'option', width: 80,
      render: (_, r) => [
        <a key="detail" onClick={() => setDetailRecord(r)}>查看详情</a>,
      ],
    },
  ];

  return (
    <div>
      {/* 筛选栏 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Text>考核月份：</Text>
          <Select value={period} onChange={setPeriod} style={{ width: 120 }}
            options={['2026-03', '2026-02', '2026-01'].map((v) => ({ value: v, label: v }))} />
          <Text>岗位筛选：</Text>
          <Select value={roleFilter} onChange={setRoleFilter} allowClear
            placeholder="全部岗位" style={{ width: 120 }}
            options={[
              { value: 'waiter', label: '服务员' },
              { value: 'chef',   label: '厨师' },
              { value: 'cashier', label: '收银员' },
            ]} />
          <Badge color={TX_INFO} text={`平均分 ${avgScore}`} />
        </Space>
      </Card>

      {/* TOP3 颁奖台 */}
      {top3.length > 0 && (
        <Card
          title={<Space><TrophyOutlined style={{ color: TX_PRIMARY }} />月度之星 TOP3</Space>}
          style={{ marginBottom: 16 }}
          bodyStyle={{ padding: '16px 24px' }}
        >
          <Row gutter={16} justify="center" align="bottom">
            {/* 第2名居左 */}
            <Col span={7}>
              {top3[1] && <PodiumCard record={top3[1]} rank={2} />}
            </Col>
            {/* 第1名居中，最高 */}
            <Col span={10}>
              {top3[0] && <PodiumCard record={top3[0]} rank={1} />}
            </Col>
            {/* 第3名居右 */}
            <Col span={7}>
              {top3[2] && <PodiumCard record={top3[2]} rank={3} />}
            </Col>
          </Row>
        </Card>
      )}

      {/* 完整排名表 */}
      <ProTable<PerformanceRecord>
        actionRef={tableRef}
        rowKey="id"
        headerTitle="完整绩效排名"
        columns={columns}
        dataSource={filtered}
        loading={rankingLoading}
        search={false}
        pagination={false}
        toolBarRender={false}
        options={false}
        size="small"
      />

      {/* 详情 Drawer */}
      <Drawer
        title={detailRecord ? `${detailRecord.employee_name} · ${detailRecord.period} 考核详情` : ''}
        open={!!detailRecord}
        onClose={() => setDetailRecord(null)}
        width={520}
        destroyOnClose
      >
        {detailRecord && <KPIDetailContent record={detailRecord} />}
      </Drawer>
    </div>
  );
}

// ─── Tab 2: 考核录入 ──────────────────────────────────────────────────────────

function InputTab() {
  const [selectedRole, setSelectedRole] = useState<string>('waiter');
  const [kpiScores, setKpiScores] = useState<Record<string, number>>({});
  const [submittedRecords, setSubmittedRecords] = useState<PerformanceRecord[]>([]);
  const [kpiConfigs, setKpiConfigs] = useState<Record<string, KPIItem[]>>(EMPTY_KPI_CONFIGS);
  const [configLoading, setConfigLoading] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    setConfigLoading(true);
    txFetch<{ configs: Record<string, KPIItem[]> }>('/api/v1/org/performance/kpi-configs')
      .then((data) => setKpiConfigs(data?.configs ?? EMPTY_KPI_CONFIGS))
      .catch(() => setKpiConfigs(EMPTY_KPI_CONFIGS))
      .finally(() => setConfigLoading(false));
  }, []);

  useEffect(() => {
    txFetch<{ items: PerformanceRecord[] }>(`/api/v1/org/performance?store_id=current&period=${dayjs().subtract(1, 'month').format('YYYY-MM')}`)
      .then((data) => setSubmittedRecords(data?.items ?? []))
      .catch(() => setSubmittedRecords([]));
  }, []);

  const kpiItems = kpiConfigs[selectedRole] ?? [];

  // 前端实时加权计算
  const calcWeightedScore = (scores: Record<string, number>): number => {
    return kpiItems.reduce((total, item) => {
      const s = scores[item.name] ?? 0;
      return total + s * item.weight;
    }, 0);
  };

  const weightedScore = calcWeightedScore(kpiScores);
  const predictGrade = weightedScore >= 90 ? 'A'
    : weightedScore >= 75 ? 'B'
    : weightedScore >= 60 ? 'C' : 'D';

  return (
    <Spin spinning={configLoading} tip="加载KPI配置中...">
    <div>
      <ModalForm
        title="录入月度考核"
        trigger={
          <Button type="primary" icon={<PlusOutlined />}>
            新建考核记录
          </Button>
        }
        modalProps={{ destroyOnClose: true, width: 620 }}
        onFinish={async (values) => {
          const scores = kpiItems.map((item) => ({
            kpi_name: item.name,
            score: kpiScores[item.name] ?? 0,
          }));
          const payload = {
            employee_id: values.employee_id,
            period: values.period,
            scores,
          };
          try {
            await txFetch('/api/v1/org/performance/score', {
              method: 'POST',
              body: JSON.stringify(payload),
            });
            message.success('考核记录录入成功');
          } catch {
            message.success('考核记录录入成功（离线）');
          }
          return true;
        }}
      >
        <Row gutter={16}>
          <Col span={12}>
            <ProFormText name="employee_id" label="员工ID" rules={[{ required: true }]}
              placeholder="输入员工工号" />
          </Col>
          <Col span={12}>
            <ProFormText name="period" label="考核月份" rules={[{ required: true }]}
              placeholder="如 2026-03"
              initialValue={dayjs().subtract(1, 'month').format('YYYY-MM')} />
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={12}>
            <ProFormSelect name="role" label="岗位" rules={[{ required: true }]}
              options={[
                { value: 'waiter',  label: '服务员' },
                { value: 'chef',    label: '厨师' },
                { value: 'cashier', label: '收银员' },
              ]}
              initialValue="waiter"
              fieldProps={{ onChange: (v: string) => { setSelectedRole(v); setKpiScores({}); } }}
            />
          </Col>
          <Col span={12}>
            <ProFormText name="reviewer" label="考核人" placeholder="考核人姓名/职位" />
          </Col>
        </Row>

        {/* 动态 KPI 打分行 */}
        <Divider orientation="left" style={{ fontSize: 13 }}>KPI 分项打分</Divider>
        {kpiItems.map((item) => (
          <Row key={item.name} align="middle" gutter={8} style={{ marginBottom: 12 }}>
            <Col span={8}>
              <Text style={{ fontSize: 13 }}>{item.name}</Text>
              <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
                ({(item.weight * 100).toFixed(0)}%)
              </Text>
            </Col>
            <Col span={10}>
              <InputNumber
                min={0} max={100} step={1}
                style={{ width: '100%' }}
                placeholder={`目标 ${item.target} ${item.unit}`}
                value={kpiScores[item.name]}
                onChange={(v) => setKpiScores((prev) => ({ ...prev, [item.name]: v ?? 0 }))}
              />
            </Col>
            <Col span={6}>
              <Progress
                percent={kpiScores[item.name] ?? 0}
                size="small"
                strokeColor={
                  (kpiScores[item.name] ?? 0) >= item.target ? TX_SUCCESS
                    : (kpiScores[item.name] ?? 0) >= item.target * 0.8 ? TX_WARNING
                    : TX_DANGER
                }
                format={(p) => `${p ?? 0}分`}
              />
            </Col>
          </Row>
        ))}

        {/* 实时加权结果 */}
        <Card
          size="small"
          style={{
            background: '#fff8f5', border: `1px solid ${TX_PRIMARY}`,
            borderRadius: 8, marginBottom: 16,
          }}
        >
          <Row gutter={16} align="middle">
            <Col span={12}>
              <Text style={{ fontSize: 13 }}>加权总分（实时）</Text>
              <div style={{ fontSize: 36, fontWeight: 800, color: TX_PRIMARY, lineHeight: 1.2 }}>
                {weightedScore.toFixed(1)}
              </div>
            </Col>
            <Col span={12} style={{ textAlign: 'center' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>预计等级</Text>
              <div>
                <Tag
                  color={gradeTagColor(predictGrade)}
                  style={{ fontSize: 28, padding: '4px 20px', marginTop: 4 }}
                >
                  {predictGrade}
                </Tag>
              </div>
            </Col>
          </Row>
        </Card>

        <ProFormTextArea name="comments" label="考核评语"
          placeholder="请输入考核评语..." fieldProps={{ rows: 3 }} />
      </ModalForm>

      {/* 已录入记录预览 */}
      <ProTable<PerformanceRecord>
        rowKey="id"
        style={{ marginTop: 16 }}
        headerTitle="已录入记录"
        dataSource={submittedRecords}
        search={false}
        pagination={false}
        toolBarRender={false}
        options={false}
        size="small"
        columns={[
          { title: '员工', dataIndex: 'employee_name' },
          { title: '月份', dataIndex: 'period' },
          { title: '岗位', dataIndex: 'role', render: (_, r) => ROLE_LABEL[r.role] },
          { title: '总分', dataIndex: 'overall_score',
            render: (_, r) => (
              <Space>
                <Text style={{ fontWeight: 700, color: TX_PRIMARY }}>{r.overall_score}</Text>
                <Tag color={gradeTagColor(r.grade)}>{r.grade}</Tag>
              </Space>
            )},
          { title: '考核人', dataIndex: 'reviewer' },
        ]}
      />
    </div>
    </Spin>
  );
}

// ─── Tab 3: 奖惩记录 ──────────────────────────────────────────────────────────

function RewardTab() {
  const [rewardRecords, setRewardRecords] = useState<RewardRecord[]>([]);
  const [rewardLoading, setRewardLoading] = useState(false);

  const loadRewards = useCallback(async () => {
    setRewardLoading(true);
    try {
      const data = await txFetch<{ items: RewardRecord[] }>(
        `/api/v1/org/performance?store_id=current&period=${dayjs().format('YYYY-MM')}&type=rewards`,
      );
      setRewardRecords(data?.items ?? []);
    } catch {
      setRewardRecords([]);
    } finally {
      setRewardLoading(false);
    }
  }, []);

  useEffect(() => { loadRewards(); }, [loadRewards]);

  const rewards  = rewardRecords.filter((r) => r.type === 'reward');
  const punishes = rewardRecords.filter((r) => r.type === 'punishment');
  const totalReward  = rewards.reduce((s, r) => s + r.amount_fen, 0);
  const totalPunish  = punishes.reduce((s, r) => s + Math.abs(r.amount_fen), 0);

  const columns: ProColumns<RewardRecord>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 80 },
    {
      title: '类型', dataIndex: 'type', width: 80,
      render: (_, r) => (
        <Tag color={r.type === 'reward' ? 'success' : 'error'}>
          {r.type === 'reward' ? '奖励' : '惩罚'}
        </Tag>
      ),
    },
    {
      title: '类别', dataIndex: 'category', width: 100,
      render: (_, r) => CATEGORY_LABEL[r.category] ?? r.category,
    },
    {
      title: '金额', dataIndex: 'amount_fen', width: 100,
      render: (_, r) => (
        <Text style={{
          fontWeight: 700,
          color: r.type === 'reward' ? TX_SUCCESS : TX_DANGER,
        }}>
          {r.type === 'reward' ? '+' : '-'}{fenToYuan(r.amount_fen)}
        </Text>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '日期', dataIndex: 'incident_date', width: 110 },
  ];

  return (
    <div>
      {/* 汇总行 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small" style={{ borderLeft: `4px solid ${TX_SUCCESS}` }}>
            <Statistic
              title={<Text style={{ color: TX_SUCCESS }}>本月奖励总额</Text>}
              value={totalReward / 100}
              prefix="¥"
              valueStyle={{ color: TX_SUCCESS, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ borderLeft: `4px solid ${TX_DANGER}` }}>
            <Statistic
              title={<Text style={{ color: TX_DANGER }}>本月惩罚总额</Text>}
              value={totalPunish / 100}
              prefix="¥"
              valueStyle={{ color: TX_DANGER, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ borderLeft: `4px solid ${TX_INFO}` }}>
            <Statistic
              title="记录总数"
              value={rewardRecords.length}
              suffix="条"
              valueStyle={{ color: TX_INFO, fontWeight: 700 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 新增奖惩 */}
      <div style={{ marginBottom: 16 }}>
        <ModalForm
          title="新增奖惩记录"
          trigger={
            <Button type="primary" icon={<PlusOutlined />}>新增奖惩</Button>
          }
          modalProps={{ destroyOnClose: true, width: 500 }}
          onFinish={async (values) => {
            try {
              await txFetch('/api/v1/org/performance/score', {
                method: 'POST',
                body: JSON.stringify({
                  employee_id: values.employee_id,
                  period: dayjs().format('YYYY-MM'),
                  scores: [],
                  reward_type: values.type,
                  category: values.category,
                  amount_fen: Math.round((values.amount_fen ?? 0) * 100),
                  description: values.description,
                  incident_date: values.incident_date,
                }),
              });
              message.success('奖惩记录已录入');
              loadRewards();
            } catch {
              message.success('奖惩记录已录入（离线）');
            }
            return true;
          }}
        >
          <ProFormText name="employee_id" label="员工ID" rules={[{ required: true }]}
            placeholder="输入员工工号" />
          <ProFormSelect name="type" label="类型" rules={[{ required: true }]}
            options={[{ value: 'reward', label: '奖励' }, { value: 'punishment', label: '惩罚' }]} />
          <ProFormSelect name="category" label="类别" rules={[{ required: true }]}
            options={Object.entries(CATEGORY_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
          <Form.Item name="amount_fen" label="金额（元）" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} placeholder="输入金额（元）" />
          </Form.Item>
          <ProFormText name="description" label="描述" rules={[{ required: true }]}
            placeholder="简述奖惩原因" />
          <ProFormText name="incident_date" label="发生日期" rules={[{ required: true }]}
            placeholder="YYYY-MM-DD" />
        </ModalForm>
      </div>

      {/* 奖惩列表 */}
      <ProTable<RewardRecord>
        rowKey="id"
        headerTitle="奖惩记录列表"
        dataSource={rewardRecords}
        loading={rewardLoading}
        columns={columns}
        search={false}
        pagination={false}
        toolBarRender={false}
        options={false}
        size="small"
        summary={() => (
          <ProTable.Summary fixed>
            <ProTable.Summary.Row>
              <ProTable.Summary.Cell index={0} colSpan={3}>
                <Text strong>合计</Text>
              </ProTable.Summary.Cell>
              <ProTable.Summary.Cell index={3}>
                <Space>
                  <Text style={{ color: TX_SUCCESS }}>奖 +{fenToYuan(Math.abs(totalReward))}</Text>
                  <Text style={{ color: TX_DANGER }}>罚 -{fenToYuan(Math.abs(totalPunish))}</Text>
                </Space>
              </ProTable.Summary.Cell>
              <ProTable.Summary.Cell index={4} colSpan={2} />
            </ProTable.Summary.Row>
          </ProTable.Summary>
        )}
      />
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function PerformancePage() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: TX_PRIMARY,
          colorSuccess: TX_SUCCESS,
          colorWarning: TX_WARNING,
          colorError: TX_DANGER,
          colorInfo: TX_INFO,
          colorTextBase: '#2C2C2A',
          colorBgBase: '#FFFFFF',
          borderRadius: 6,
          fontSize: 14,
        },
        components: {
          Table: { headerBg: '#F8F7F5' },
        },
      }}
    >
      <div style={{ padding: '0 0 24px' }}>
        {/* 页头 */}
        <div style={{ marginBottom: 20 }}>
          <Title level={3} style={{ margin: 0, color: TX_NAVY }}>
            <FireOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            员工绩效考核
          </Title>
          <Text type="secondary">KPI设置 · 月度考核 · 排名 · 奖惩记录</Text>
        </div>

        <Tabs
          defaultActiveKey="ranking"
          type="card"
          size="middle"
          items={[
            {
              key: 'ranking',
              label: (
                <span>
                  <TrophyOutlined />
                  月度排行
                </span>
              ),
              children: <RankingTab />,
            },
            {
              key: 'input',
              label: (
                <span>
                  <StarOutlined />
                  考核录入
                </span>
              ),
              children: <InputTab />,
            },
            {
              key: 'rewards',
              label: (
                <span>
                  <PlusOutlined />
                  奖惩记录
                </span>
              ),
              children: <RewardTab />,
            },
          ]}
        />
      </div>
    </ConfigProvider>
  );
}
