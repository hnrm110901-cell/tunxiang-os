/**
 * BudgetRecommendation -- 门店健康度人力预算
 * P2-6 · 门店健康度人力预算建议
 *
 * 功能：
 *  1. 门店选择 + 月份
 *  2. 当前 vs 建议对比表（增编绿色/减编红色）
 *  3. P&L健康度仪表盘（Gauge）
 *  4. 行业对标
 *  5. Agent理由说明卡片
 *
 * API:
 *  POST /api/v1/agent/salary_advisor/budget_recommendation
 */

import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import { Gauge } from '@ant-design/charts';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  BulbOutlined,
  DashboardOutlined,
  MinusOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { txFetchData } from '../../../api';

const { Title, Text, Paragraph } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface PositionPlan {
  role: string;
  role_label: string;
  current_count: number;
  suggested_count: number;
  current_salary_fen: number;
  suggested_salary_fen: number;
  diff: number;
  action: string;
}

interface BudgetData {
  store_id: string;
  month: string;
  cuisine_type: string;
  current_status: {
    monthly_revenue_fen: number;
    monthly_labor_fen: number;
    labor_cost_rate: number;
    revenue_trend: string;
  };
  industry_benchmark: {
    p25: number;
    p50: number;
    p75: number;
  };
  suggestion: {
    target_labor_rate: number;
    suggested_budget_fen: number;
    predicted_revenue_fen: number;
    budget_diff_fen: number;
    headcount_diff: number;
    action: string;
  };
  position_plan: PositionPlan[];
  reasons: string[];
  ai_tag: string;
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

const fmtYuan = (fen: number) => `${(fen / 100).toLocaleString()}`;
const fmtPct = (rate: number) => `${(rate * 100).toFixed(1)}%`;

const CUISINE_OPTIONS = [
  { label: '正餐', value: '正餐' },
  { label: '快餐', value: '快餐' },
  { label: '火锅', value: '火锅' },
  { label: '宴会', value: '宴会' },
];

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function BudgetRecommendation() {
  const [storeId, setStoreId] = useState('');
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [cuisineType, setCuisineType] = useState('正餐');
  const [data, setData] = useState<BudgetData | null>(null);
  const [loading, setLoading] = useState(false);
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);

  useEffect(() => {
    txFetchData<{ items: { id: string; store_name: string }[] }>('/api/v1/stores?page=1&size=100')
      .then((resp) => {
        const list = (resp.data?.items || []).map((s) => ({ id: s.id, name: s.store_name }));
        setStores(list);
        if (list.length > 0 && !storeId) setStoreId(list[0].id);
      })
      .catch(() => {
        setStores([{ id: 'default', name: '默认门店' }]);
        setStoreId('default');
      });
  }, []);

  const handleAnalyze = async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const resp = await txFetchData<{ data: BudgetData }>('/api/v1/agent/salary_advisor/budget_recommendation', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          month: month.format('YYYY-MM'),
          cuisine_type: cuisineType,
        }),
      });
      setData(resp.data?.data || resp.data);
    } catch {
      message.error('分析失败');
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    { title: '岗位', dataIndex: 'role_label', key: 'role' },
    { title: '当前人数', dataIndex: 'current_count', key: 'cur_count', align: 'center' as const },
    { title: '建议人数', dataIndex: 'suggested_count', key: 'sug_count', align: 'center' as const },
    {
      title: '当前薪资',
      dataIndex: 'current_salary_fen',
      key: 'cur_sal',
      render: (v: number) => `${fmtYuan(v)}元`,
      align: 'right' as const,
    },
    {
      title: '建议薪资上限',
      dataIndex: 'suggested_salary_fen',
      key: 'sug_sal',
      render: (v: number) => `${fmtYuan(v)}元`,
      align: 'right' as const,
    },
    {
      title: '差异',
      dataIndex: 'diff',
      key: 'diff',
      align: 'center' as const,
      render: (diff: number, record: PositionPlan) => {
        if (diff > 0) return <Tag color="green" icon={<ArrowUpOutlined />}>+{diff} 增编</Tag>;
        if (diff < 0) return <Tag color="red" icon={<ArrowDownOutlined />}>{diff} 减编</Tag>;
        return <Tag icon={<MinusOutlined />}>持平</Tag>;
      },
    },
  ];

  // Gauge配置
  const gaugePercent = data ? Math.min(1, data.current_status.labor_cost_rate / 0.40) : 0;

  return (
    <div>
      <Title level={4}>门店健康度人力预算</Title>

      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          value={storeId}
          onChange={setStoreId}
          style={{ width: 200 }}
          placeholder="选择门店"
          options={stores.map((s) => ({ label: s.name, value: s.id }))}
        />
        <DatePicker
          picker="month"
          value={month}
          onChange={(d) => d && setMonth(d)}
          allowClear={false}
        />
        <Select
          value={cuisineType}
          onChange={setCuisineType}
          style={{ width: 120 }}
          options={CUISINE_OPTIONS}
        />
        <Button type="primary" onClick={handleAnalyze} loading={loading}>
          分析预算建议
        </Button>
      </Space>

      {data && (
        <>
          {/* KPI 卡片 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <StatisticCard
                statistic={{
                  title: '月营收',
                  value: fmtYuan(data.current_status.monthly_revenue_fen),
                  suffix: '元',
                }}
              />
            </Col>
            <Col span={6}>
              <StatisticCard
                statistic={{
                  title: '当前人力成本',
                  value: fmtYuan(data.current_status.monthly_labor_fen),
                  suffix: '元',
                  description: (
                    <Tag color={data.current_status.labor_cost_rate > 0.30 ? 'red' : 'green'}>
                      占比 {fmtPct(data.current_status.labor_cost_rate)}
                    </Tag>
                  ),
                }}
              />
            </Col>
            <Col span={6}>
              <StatisticCard
                statistic={{
                  title: '建议预算上限',
                  value: fmtYuan(data.suggestion.suggested_budget_fen),
                  suffix: '元',
                  description: (
                    <Text type={data.suggestion.budget_diff_fen > 0 ? 'success' : 'danger'}>
                      {data.suggestion.budget_diff_fen > 0 ? '+' : ''}{fmtYuan(data.suggestion.budget_diff_fen)}元
                    </Text>
                  ),
                }}
              />
            </Col>
            <Col span={6}>
              <StatisticCard
                statistic={{
                  title: '编制调整',
                  value: data.suggestion.headcount_diff,
                  prefix: <TeamOutlined />,
                  suffix: '人',
                  description: (
                    <Tag color={data.suggestion.action === '增编' ? 'green' : data.suggestion.action === '减编' ? 'red' : 'default'}>
                      {data.suggestion.action}
                    </Tag>
                  ),
                }}
              />
            </Col>
          </Row>

          <Row gutter={16} style={{ marginBottom: 16 }}>
            {/* Gauge仪表盘 */}
            <Col span={8}>
              <Card title={<><DashboardOutlined /> P&amp;L健康度</>}>
                <Gauge
                  percent={gaugePercent}
                  height={200}
                  range={{ color: ['#0F6E56', '#BA7517', '#A32D2D'], ticks: [0, 0.625, 0.875, 1] }}
                  indicator={{
                    pointer: { style: { stroke: '#2C2C2A' } },
                    pin: { style: { stroke: '#2C2C2A' } },
                  }}
                  statistic={{
                    title: { formatter: () => '人力成本率' },
                    content: { formatter: () => fmtPct(data.current_status.labor_cost_rate) },
                  }}
                />
              </Card>
            </Col>

            {/* 行业对标 */}
            <Col span={8}>
              <Card title="行业对标">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="当前成本率">
                    <Tag color={marginTagColor(data.current_status.labor_cost_rate, data.industry_benchmark)}>
                      {fmtPct(data.current_status.labor_cost_rate)}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="行业P25">
                    {fmtPct(data.industry_benchmark.p25)}
                  </Descriptions.Item>
                  <Descriptions.Item label="行业P50（建议）">
                    <Tag color="blue">{fmtPct(data.industry_benchmark.p50)}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="行业P75">
                    {fmtPct(data.industry_benchmark.p75)}
                  </Descriptions.Item>
                  <Descriptions.Item label="营收趋势">
                    <Tag color={data.current_status.revenue_trend === 'rising' ? 'green' : data.current_status.revenue_trend === 'declining' ? 'red' : 'default'}>
                      {data.current_status.revenue_trend === 'rising' ? '上升' : data.current_status.revenue_trend === 'declining' ? '下降' : '稳定'}
                    </Tag>
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>

            {/* AI建议理由 */}
            <Col span={8}>
              <Card
                title={
                  <Space>
                    <BulbOutlined />
                    <span>预算建议</span>
                    <Tag color="blue">{data.ai_tag}</Tag>
                  </Space>
                }
              >
                {data.reasons.map((reason, i) => (
                  <Paragraph key={i} style={{ marginBottom: 8 }}>
                    {i + 1}. {reason}
                  </Paragraph>
                ))}
              </Card>
            </Col>
          </Row>

          {/* 岗位对比表 */}
          <Card title="岗位编制对比">
            <Table
              dataSource={data.position_plan}
              columns={columns}
              rowKey="role"
              pagination={false}
              size="small"
              rowClassName={(record) =>
                record.diff > 0
                  ? 'budget-row-increase'
                  : record.diff < 0
                    ? 'budget-row-decrease'
                    : ''
              }
            />
          </Card>
        </>
      )}

      <style>{`
        .budget-row-increase { background-color: rgba(15, 110, 86, 0.04) !important; }
        .budget-row-decrease { background-color: rgba(163, 45, 45, 0.04) !important; }
      `}</style>
    </div>
  );
}

function marginTagColor(rate: number, bench: { p25: number; p50: number; p75: number }): string {
  if (rate <= bench.p25) return 'green';
  if (rate <= bench.p50) return 'blue';
  if (rate <= bench.p75) return 'gold';
  return 'red';
}
