/**
 * ContributionDashboard -- 员工经营贡献度实时排名
 * 域F . 组织人事 . HR Admin
 *
 * 功能：
 *  - 门店选择 + 周期选择（本周/本月/自定义）
 *  - 排名ProTable（排名/姓名/岗位/总分/5维度/趋势箭头）
 *  - 前三名金银铜Medal图标
 *  - 选中员工后右侧：Radar雷达图5维度 + 趋势Line图
 *  - StatisticCard：门店平均分/最高分/最低分/分差
 *  - 数据来源标注"AI实时计算"（info蓝色Tag）
 *
 * API:
 *  GET /api/v1/contribution/rankings?store_id=&period_start=&period_end=
 *  GET /api/v1/contribution/score/{employee_id}?period_start=&period_end=
 *  GET /api/v1/contribution/trend/{employee_id}?periods=6
 */

import { useRef, useState, useCallback } from 'react';
import {
  Card, Col, Row, Tag, Typography, Select, DatePicker, Space, Statistic,
} from 'antd';
import {
  TrophyOutlined, ArrowUpOutlined, ArrowDownOutlined, MinusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { ProTable, ProColumns, StatisticCard } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { Radar, Line } from '@ant-design/charts';
import { txFetch } from '../../../api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── Types ───────────────────────────────────────────────────────────────────

interface ContributionDimensions {
  revenue: number;
  efficiency: number;
  satisfaction: number;
  attendance: number;
  teamwork: number;
}

interface RankingItem {
  rank: number;
  employee_id: string;
  name: string;
  role: string;
  total_score: number;
  dimensions: ContributionDimensions;
  trend: 'up' | 'down' | 'same';
  delta: number;
}

interface RankingStats {
  avg: number;
  max: number;
  min: number;
  spread: number;
  total_employees: number;
}

interface TrendPoint {
  period_start: string;
  period_end: string;
  total_score: number;
  dimensions: ContributionDimensions;
}

// ─── Constants ──────────────────────────────────────────────────────────────

const MEDAL_COLORS: Record<number, string> = {
  1: '#FFD700',
  2: '#C0C0C0',
  3: '#CD7F32',
};

const DIMENSION_LABELS: Record<string, string> = {
  revenue: '营收贡献',
  efficiency: '服务效率',
  satisfaction: '客户满意',
  attendance: '出勤纪律',
  teamwork: '团队协作',
};

const PERIOD_OPTIONS = [
  { label: '本周', value: 'week' },
  { label: '本月', value: 'month' },
  { label: '自定义', value: 'custom' },
];

// ─── Helpers ────────────────────────────────────────────────────────────────

function periodRange(mode: string): [string, string] {
  const today = dayjs();
  if (mode === 'week') {
    return [today.startOf('week').format('YYYY-MM-DD'), today.format('YYYY-MM-DD')];
  }
  return [today.startOf('month').format('YYYY-MM-DD'), today.format('YYYY-MM-DD')];
}

function TrendIcon({ trend, delta }: { trend: string; delta: number }) {
  if (trend === 'up')
    return <span style={{ color: '#0F6E56' }}><ArrowUpOutlined /> +{delta}</span>;
  if (trend === 'down')
    return <span style={{ color: '#A32D2D' }}><ArrowDownOutlined /> {delta}</span>;
  return <span style={{ color: '#B4B2A9' }}><MinusOutlined /> 0</span>;
}

function gradeTag(score: number) {
  if (score >= 90) return <Tag color="gold">卓越</Tag>;
  if (score >= 80) return <Tag color="green">优秀</Tag>;
  if (score >= 60) return <Tag color="blue">良好</Tag>;
  if (score >= 40) return <Tag color="orange">合格</Tag>;
  return <Tag color="red">待提升</Tag>;
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function ContributionDashboard() {
  const actionRef = useRef<ActionType>(null);

  const [storeId, setStoreId] = useState('');
  const [periodMode, setPeriodMode] = useState('month');
  const [customRange, setCustomRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  const [stats, setStats] = useState<RankingStats>({
    avg: 0, max: 0, min: 0, spread: 0, total_employees: 0,
  });
  const [selectedEmployee, setSelectedEmployee] = useState<RankingItem | null>(null);
  const [trendData, setTrendData] = useState<TrendPoint[]>([]);

  const getDateRange = useCallback((): [string, string] => {
    if (periodMode === 'custom' && customRange) {
      return [customRange[0].format('YYYY-MM-DD'), customRange[1].format('YYYY-MM-DD')];
    }
    return periodRange(periodMode);
  }, [periodMode, customRange]);

  // 加载员工趋势
  const loadTrend = useCallback(async (employeeId: string) => {
    try {
      const res = await txFetch(`/api/v1/contribution/trend/${employeeId}?periods=6`);
      if (res.ok) setTrendData(res.data);
    } catch { /* ignore */ }
  }, []);

  const handleRowClick = useCallback((record: RankingItem) => {
    setSelectedEmployee(record);
    void loadTrend(record.employee_id);
  }, [loadTrend]);

  // ─── Columns ────────────────────────────────────────────────────

  const columns: ProColumns<RankingItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 80,
      hideInSearch: true,
      render: (_, r) => {
        const medal = MEDAL_COLORS[r.rank];
        return medal ? (
          <Tag color={medal} style={{ fontWeight: 'bold', fontSize: 14 }}>
            <TrophyOutlined /> {r.rank}
          </Tag>
        ) : (
          <span style={{ fontWeight: 500, paddingLeft: 8 }}>{r.rank}</span>
        );
      },
    },
    { title: '姓名', dataIndex: 'name', width: 100, hideInSearch: true },
    { title: '岗位', dataIndex: 'role', width: 80, hideInSearch: true },
    {
      title: '总分',
      dataIndex: 'total_score',
      width: 100,
      hideInSearch: true,
      sorter: true,
      render: (_, r) => (
        <Space>
          <span style={{ fontWeight: 700, fontSize: 16, color: '#FF6B35' }}>
            {r.total_score}
          </span>
          {gradeTag(r.total_score)}
        </Space>
      ),
    },
    {
      title: '营收',
      dataIndex: ['dimensions', 'revenue'],
      width: 70,
      hideInSearch: true,
      render: (_, r) => r.dimensions.revenue,
    },
    {
      title: '效率',
      dataIndex: ['dimensions', 'efficiency'],
      width: 70,
      hideInSearch: true,
      render: (_, r) => r.dimensions.efficiency,
    },
    {
      title: '满意',
      dataIndex: ['dimensions', 'satisfaction'],
      width: 70,
      hideInSearch: true,
      render: (_, r) => r.dimensions.satisfaction,
    },
    {
      title: '出勤',
      dataIndex: ['dimensions', 'attendance'],
      width: 70,
      hideInSearch: true,
      render: (_, r) => r.dimensions.attendance,
    },
    {
      title: '协作',
      dataIndex: ['dimensions', 'teamwork'],
      width: 70,
      hideInSearch: true,
      render: (_, r) => r.dimensions.teamwork,
    },
    {
      title: '趋势',
      dataIndex: 'trend',
      width: 90,
      hideInSearch: true,
      render: (_, r) => <TrendIcon trend={r.trend} delta={r.delta} />,
    },
  ];

  // ─── Radar config ───────────────────────────────────────────────

  const radarData = selectedEmployee
    ? Object.entries(selectedEmployee.dimensions).map(([key, value]) => ({
        dimension: DIMENSION_LABELS[key] || key,
        score: value,
      }))
    : [];

  const radarConfig = {
    data: radarData,
    xField: 'dimension',
    yField: 'score',
    meta: { score: { min: 0, max: 100 } },
    area: { style: { fillOpacity: 0.3 } },
    point: { size: 3 },
    color: '#FF6B35',
    height: 280,
  };

  // ─── Line config ────────────────────────────────────────────────

  const lineData = trendData.map((t) => ({
    period: t.period_end,
    score: t.total_score,
  }));

  const lineConfig = {
    data: lineData,
    xField: 'period',
    yField: 'score',
    smooth: true,
    color: '#FF6B35',
    point: { size: 4, shape: 'circle' },
    yAxis: { min: 0, max: 100 },
    height: 200,
  };

  // ─── Render ─────────────────────────────────────────────────────

  return (
    <div style={{ padding: '24px' }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <ThunderboltOutlined style={{ color: '#FF6B35', marginRight: 8 }} />
            员工经营贡献度排名
            <Tag color="blue" style={{ marginLeft: 12, fontSize: 12 }}>AI实时计算</Tag>
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              placeholder="选择门店"
              value={storeId || undefined}
              onChange={(v) => { setStoreId(v); actionRef.current?.reload(); }}
              style={{ width: 200 }}
              options={[]}
              allowClear
            />
            <Select
              value={periodMode}
              onChange={(v) => { setPeriodMode(v); actionRef.current?.reload(); }}
              options={PERIOD_OPTIONS}
              style={{ width: 120 }}
            />
            {periodMode === 'custom' && (
              <RangePicker
                value={customRange}
                onChange={(v) => { setCustomRange(v as [dayjs.Dayjs, dayjs.Dayjs]); actionRef.current?.reload(); }}
              />
            )}
          </Space>
        </Col>
      </Row>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{ title: '门店平均分', value: stats.avg, precision: 1, suffix: '分' }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '最高分',
              value: stats.max,
              precision: 1,
              suffix: '分',
              valueStyle: { color: '#0F6E56' },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '最低分',
              value: stats.min,
              precision: 1,
              suffix: '分',
              valueStyle: { color: '#A32D2D' },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{ title: '分差', value: stats.spread, precision: 1, suffix: '分' }}
          />
        </Col>
      </Row>

      <Row gutter={16}>
        {/* 排名表格 */}
        <Col span={selectedEmployee ? 14 : 24}>
          <ProTable<RankingItem>
            actionRef={actionRef}
            columns={columns}
            rowKey="employee_id"
            search={false}
            request={async () => {
              if (!storeId) return { data: [], total: 0, success: true };
              const [ps, pe] = getDateRange();
              try {
                const res = await txFetch(
                  `/api/v1/contribution/rankings?store_id=${storeId}&period_start=${ps}&period_end=${pe}`,
                );
                if (res.ok) {
                  setStats(res.data.stats || stats);
                  return {
                    data: res.data.rankings || [],
                    total: (res.data.rankings || []).length,
                    success: true,
                  };
                }
              } catch { /* ignore */ }
              return { data: [], total: 0, success: true };
            }}
            onRow={(record) => ({
              onClick: () => handleRowClick(record),
              style: {
                cursor: 'pointer',
                background: selectedEmployee?.employee_id === record.employee_id
                  ? '#FFF3ED'
                  : undefined,
              },
            })}
            pagination={false}
            toolBarRender={false}
            size="middle"
          />
        </Col>

        {/* 右侧详情面板 */}
        {selectedEmployee && (
          <Col span={10}>
            <Card
              title={
                <Space>
                  <span style={{ fontWeight: 700 }}>{selectedEmployee.name}</span>
                  <Tag>{selectedEmployee.role}</Tag>
                  <span style={{ fontSize: 20, fontWeight: 700, color: '#FF6B35' }}>
                    {selectedEmployee.total_score}分
                  </span>
                  {gradeTag(selectedEmployee.total_score)}
                </Space>
              }
              extra={
                <a onClick={() => setSelectedEmployee(null)}>关闭</a>
              }
            >
              {/* 雷达图 */}
              <div style={{ marginBottom: 16 }}>
                <Text strong>五维能力画像</Text>
                <Radar {...radarConfig} />
              </div>

              {/* 趋势图 */}
              <div>
                <Text strong>近期趋势</Text>
                {lineData.length > 0 ? (
                  <Line {...lineConfig} />
                ) : (
                  <div style={{ color: '#B4B2A9', textAlign: 'center', padding: 32 }}>
                    暂无趋势数据
                  </div>
                )}
              </div>
            </Card>
          </Col>
        )}
      </Row>
    </div>
  );
}
