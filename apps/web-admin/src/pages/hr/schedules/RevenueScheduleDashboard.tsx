/**
 * RevenueScheduleDashboard -- 营收驱动智能排班
 * 域F . 组织人事 . HR Admin
 *
 * 核心差异化：基于POS营收数据自动推导各时段最优人力配置
 * 这是屯象OS vs i人事/乐才的核心壁垒——它们没有POS数据。
 *
 * 布局：
 *  - 顶部：门店选择 + 周选择
 *  - 左侧：时段营收热力图（X=星期, Y=时段, 颜色=营收）
 *  - 右侧：最优人力 vs 当前配置对比表
 *  - 底部左：客流趋势折线图（过去4周）
 *  - 底部右：岗位人力缺口/冗余柱状图
 *  - 底部卡片：成本节约预估
 *
 * API:
 *   GET /api/v1/revenue-schedule/analysis?store_id=&weeks=4
 *   GET /api/v1/revenue-schedule/optimal-plan?store_id=&week_start=
 *   GET /api/v1/revenue-schedule/comparison?store_id=&week_start=
 *   GET /api/v1/revenue-schedule/savings-estimate?store_id=&month=
 *   POST /api/v1/revenue-schedule/apply-plan
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Divider,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  DollarOutlined,
  ExclamationCircleOutlined,
  FireOutlined,
  RocketOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { StatisticCard } from '@ant-design/pro-components';
import { Heatmap, Column, Line } from '@ant-design/charts';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import isoWeek from 'dayjs/plugin/isoWeek';
import { txFetchData } from '../../../api';

dayjs.extend(isoWeek);

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER = '#A32D2D';
const TX_INFO = '#185FA5';

// ---- Types ----

interface SlotPlan {
  slot_key: string;
  slot_name: string;
  start_time: string;
  end_time: string;
  predicted_revenue_fen: number;
  optimal_staff: Record<string, number>;
  current_staff: Record<string, number>;
  delta: Record<string, number>;
  suggested_employees: { employee_id: string; name: string; position: string; reason: string }[];
}

interface DailyPlan {
  date: string;
  weekday: number;
  weekday_name: string;
  slots: SlotPlan[];
}

interface WeeklyPlan {
  store_id: string;
  week_start: string;
  week_end: string;
  daily_plans: DailyPlan[];
  summary: {
    total_labor_cost_current_fen: number;
    total_labor_cost_optimal_fen: number;
    savings_fen: number;
    savings_pct: number;
  };
  employee_count: number;
}

interface RevenueSlot {
  slot_key: string;
  slot_name: string;
  start_time: string;
  end_time: string;
  avg_revenue_fen: number;
  peak_revenue_fen: number;
  std_dev_fen: number;
  sample_days: number;
}

interface AnalysisData {
  slots: RevenueSlot[];
  total_avg_daily_revenue_fen: number;
  data_source: string;
}

interface SavingsData {
  month: string;
  monthly_current_fen: number;
  monthly_optimal_fen: number;
  monthly_savings_fen: number;
  savings_pct: number;
}

// ---- Helpers ----

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number): string => (fen / 100).toFixed(2);
const fen2yuanInt = (fen: number): string => Math.round(fen / 100).toLocaleString();

const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const POSITIONS = ['前厅', '后厨', '收银', '清洁'];

/** 获取下周一 */
function getNextMonday(): dayjs.Dayjs {
  const today = dayjs();
  const dow = today.isoWeekday(); // 1=Mon ... 7=Sun
  return today.add(dow === 1 ? 7 : 8 - dow, 'day').startOf('day');
}

// ---- Mock store list (will be replaced by API) ----

const MOCK_STORES = [
  { value: 'store-001', label: '长沙万达店' },
  { value: 'store-002', label: '长沙IFS店' },
  { value: 'store-003', label: '长沙德思勤店' },
];

// ---- Component ----

export default function RevenueScheduleDashboard() {
  // State
  const [storeId, setStoreId] = useState<string>(MOCK_STORES[0].value);
  const [weekStart, setWeekStart] = useState<dayjs.Dayjs>(getNextMonday());
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  const [plan, setPlan] = useState<WeeklyPlan | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [savings, setSavings] = useState<SavingsData | null>(null);

  // ---- Data fetching ----

  const fetchAll = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const weekStr = weekStart.format('YYYY-MM-DD');
      const monthStr = weekStart.format('YYYY-MM');

      const [planRes, analysisRes, savingsRes] = await Promise.allSettled([
        txFetchData<WeeklyPlan>(`/api/v1/revenue-schedule/optimal-plan?store_id=${storeId}&week_start=${weekStr}`),
        txFetchData<AnalysisData>(`/api/v1/revenue-schedule/analysis?store_id=${storeId}&weeks=4`),
        txFetchData<SavingsData>(`/api/v1/revenue-schedule/savings-estimate?store_id=${storeId}&month=${monthStr}`),
      ]);

      if (planRes.status === 'fulfilled' && planRes.value) {
        setPlan(planRes.value);
      }
      if (analysisRes.status === 'fulfilled' && analysisRes.value) {
        setAnalysis(analysisRes.value);
      }
      if (savingsRes.status === 'fulfilled' && savingsRes.value) {
        setSavings(savingsRes.value);
      }
    } catch (err) {
      console.error('Revenue schedule fetch failed:', err);
    } finally {
      setLoading(false);
    }
  }, [storeId, weekStart]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // ---- Apply plan ----

  const handleApplyPlan = useCallback(async () => {
    Modal.confirm({
      title: '确认生成排班草稿？',
      content: (
        <div>
          <p>将基于营收数据生成最优排班方案，写入排班表（状态=草稿）。</p>
          <p>
            <Tag color="blue">30分钟内可回滚</Tag>
            需店长确认后生效。
          </p>
        </div>
      ),
      okText: '生成草稿',
      okButtonProps: { style: { background: TX_PRIMARY, borderColor: TX_PRIMARY } },
      onOk: async () => {
        setApplying(true);
        try {
          const res = await txFetchData<{ inserted_count?: number }>('/api/v1/revenue-schedule/apply-plan', {
            method: 'POST',
            body: JSON.stringify({
              store_id: storeId,
              week_start: weekStart.format('YYYY-MM-DD'),
              operator_id: 'admin', // TODO: from auth context
            }),
          });
          message.success(`已生成${res?.inserted_count ?? 0}条排班草稿，30分钟内可回滚`);
          fetchAll();
        } catch {
          message.error('请求失败');
        } finally {
          setApplying(false);
        }
      },
    });
  }, [storeId, weekStart, fetchAll]);

  // ---- Heatmap data ----

  const heatmapData = useMemo(() => {
    if (!plan) return [];
    const data: { weekday: string; slot: string; revenue: number }[] = [];
    for (const day of plan.daily_plans) {
      for (const slot of day.slots) {
        data.push({
          weekday: day.weekday_name,
          slot: slot.slot_name,
          revenue: Math.round(slot.predicted_revenue_fen / 100),
        });
      }
    }
    return data;
  }, [plan]);

  // ---- Line chart data (trend by slot over 4 weeks) ----

  const trendData = useMemo(() => {
    if (!analysis) return [];
    return analysis.slots.map((s) => ({
      slot: s.slot_name,
      avg_yuan: Math.round(s.avg_revenue_fen / 100),
      peak_yuan: Math.round(s.peak_revenue_fen / 100),
    }));
  }, [analysis]);

  // ---- Gap bar chart data ----

  const gapData = useMemo(() => {
    if (!plan) return [];
    const gaps: { position: string; type: string; count: number }[] = [];
    // Aggregate across all days and slots
    const posAgg: Record<string, { surplus: number; deficit: number }> = {};
    for (const pos of POSITIONS) {
      posAgg[pos] = { surplus: 0, deficit: 0 };
    }
    for (const day of plan.daily_plans) {
      for (const slot of day.slots) {
        for (const [pos, diff] of Object.entries(slot.delta)) {
          if (posAgg[pos]) {
            if (diff > 0) posAgg[pos].deficit += diff;
            else posAgg[pos].surplus += Math.abs(diff);
          }
        }
      }
    }
    for (const pos of POSITIONS) {
      if (posAgg[pos].deficit > 0) {
        gaps.push({ position: pos, type: '缺人', count: posAgg[pos].deficit });
      }
      if (posAgg[pos].surplus > 0) {
        gaps.push({ position: pos, type: '冗余', count: -posAgg[pos].surplus });
      }
    }
    return gaps;
  }, [plan]);

  // ---- Comparison table data ----

  const comparisonRows = useMemo(() => {
    if (!plan) return [];
    const rows: {
      key: string;
      date: string;
      weekday_name: string;
      slot_name: string;
      predicted_revenue: string;
      optimal: string;
      current: string;
      delta_text: string;
      has_gap: boolean;
    }[] = [];
    for (const day of plan.daily_plans) {
      for (const slot of day.slots) {
        const optTotal = Object.values(slot.optimal_staff).reduce((a, b) => a + b, 0);
        const curTotal = Object.values(slot.current_staff).reduce((a, b) => a + b, 0);
        const deltaEntries = Object.entries(slot.delta)
          .filter(([, v]) => v !== 0)
          .map(([k, v]) => `${k}${v > 0 ? '+' : ''}${v}`)
          .join(', ');
        rows.push({
          key: `${day.date}-${slot.slot_key}`,
          date: day.date,
          weekday_name: day.weekday_name,
          slot_name: slot.slot_name,
          predicted_revenue: fen2yuanInt(slot.predicted_revenue_fen),
          optimal: `${optTotal}人`,
          current: `${curTotal}人`,
          delta_text: deltaEntries || '-',
          has_gap: deltaEntries.length > 0,
        });
      }
    }
    return rows;
  }, [plan]);

  const comparisonColumns: ColumnsType<(typeof comparisonRows)[0]> = [
    { title: '日期', dataIndex: 'weekday_name', width: 70, filters: WEEKDAY_NAMES.map((n) => ({ text: n, value: n })), onFilter: (v, r) => r.weekday_name === v },
    { title: '时段', dataIndex: 'slot_name', width: 80 },
    { title: '预测营收', dataIndex: 'predicted_revenue', width: 100, align: 'right', render: (v: string) => <Text>{v}元</Text> },
    { title: '最优', dataIndex: 'optimal', width: 70, align: 'center' },
    { title: '当前', dataIndex: 'current', width: 70, align: 'center' },
    {
      title: '差异',
      dataIndex: 'delta_text',
      width: 140,
      render: (text: string, r) => {
        if (!r.has_gap) return <Tag color="green">匹配</Tag>;
        return <Tag color="orange">{text}</Tag>;
      },
    },
  ];

  // ---- Render ----

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={3} style={{ margin: 0 }}>
            <ThunderboltOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            营收驱动智能排班
          </Title>
          <Text type="secondary">
            基于POS交易数据，自动推导各时段最优人力配置
          </Text>
        </Col>
        <Col>
          <Space size="middle">
            <Select
              value={storeId}
              onChange={setStoreId}
              options={MOCK_STORES}
              style={{ width: 180 }}
              placeholder="选择门店"
            />
            <DatePicker
              value={weekStart}
              onChange={(d) => d && setWeekStart(d.startOf('isoWeek'))}
              picker="week"
              format="YYYY [第]ww[周]"
              allowClear={false}
            />
            <Button
              type="primary"
              icon={<RocketOutlined />}
              onClick={handleApplyPlan}
              loading={applying}
              style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            >
              生成最优排班
            </Button>
          </Space>
        </Col>
      </Row>

      {/* AI badge */}
      {plan && (
        <Alert
          type="info"
          showIcon
          icon={<FireOutlined />}
          message={
            <span>
              AI分析完成：本周预计可节省人力成本{' '}
              <Text strong style={{ color: TX_SUCCESS }}>
                {fen2yuanInt(plan.summary.savings_fen)}元
              </Text>
              （{plan.summary.savings_pct}%），覆盖{plan.employee_count}名员工
              {plan.summary.savings_fen < 0 && (
                <Text type="danger" style={{ marginLeft: 8 }}>
                  当前排班人力不足，建议增员
                </Text>
              )}
            </span>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Summary cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '当前周人力成本',
              value: plan ? fen2yuanInt(plan.summary.total_labor_cost_current_fen) : '-',
              prefix: <DollarOutlined />,
              suffix: '元',
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '最优方案成本',
              value: plan ? fen2yuanInt(plan.summary.total_labor_cost_optimal_fen) : '-',
              prefix: <DollarOutlined />,
              suffix: '元',
              valueStyle: { color: TX_SUCCESS },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '预计节省',
              value: plan ? fen2yuanInt(plan.summary.savings_fen) : '-',
              prefix: <DollarOutlined />,
              suffix: '元',
              valueStyle: {
                color: plan && plan.summary.savings_fen >= 0 ? TX_SUCCESS : TX_DANGER,
              },
            }}
            footer={
              <Statistic
                title="节省比例"
                value={plan?.summary.savings_pct ?? 0}
                suffix="%"
                valueStyle={{ fontSize: 14 }}
              />
            }
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '月度预计节省',
              value: savings ? fen2yuanInt(savings.monthly_savings_fen) : '-',
              prefix: <DollarOutlined />,
              suffix: '元',
              valueStyle: {
                color: savings && savings.monthly_savings_fen >= 0 ? TX_SUCCESS : TX_DANGER,
              },
            }}
            footer={
              <Statistic
                title="月度节省比例"
                value={savings?.savings_pct ?? 0}
                suffix="%"
                valueStyle={{ fontSize: 14 }}
              />
            }
          />
        </Col>
      </Row>

      {/* Main area: Heatmap + Comparison table */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {/* Heatmap */}
        <Col span={12}>
          <Card
            title={
              <span>
                <CalendarOutlined style={{ marginRight: 8 }} />
                时段营收热力图
              </span>
            }
            loading={loading}
            bodyStyle={{ padding: 16 }}
          >
            {heatmapData.length > 0 ? (
              <Heatmap
                data={heatmapData}
                xField="weekday"
                yField="slot"
                colorField="revenue"
                height={320}
                color={['#FFF3ED', '#FFB899', '#FF8555', TX_PRIMARY, '#C44A1C']}
                meta={{
                  revenue: { alias: '营收(元)' },
                }}
                tooltip={{
                  formatter: (datum: Record<string, unknown>) => ({
                    name: `${datum.weekday} ${datum.slot}`,
                    value: `${(datum.revenue as number).toLocaleString()}元`,
                  }),
                }}
                label={{
                  style: { fill: '#fff', fontSize: 11 },
                  formatter: (v: Record<string, unknown>) =>
                    `${((v as Record<string, unknown>).revenue as number).toLocaleString()}`,
                }}
              />
            ) : (
              <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Text type="secondary">暂无数据</Text>
              </div>
            )}
          </Card>
        </Col>

        {/* Comparison table */}
        <Col span={12}>
          <Card
            title={
              <span>
                <TeamOutlined style={{ marginRight: 8 }} />
                最优人力 vs 当前配置
              </span>
            }
            loading={loading}
            bodyStyle={{ padding: 0 }}
          >
            <Table
              dataSource={comparisonRows}
              columns={comparisonColumns}
              size="small"
              scroll={{ y: 280 }}
              pagination={false}
              rowClassName={(r) => (r.has_gap ? '' : '')}
            />
          </Card>
        </Col>
      </Row>

      {/* Bottom area: Trend line + Gap bar */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {/* Trend line chart */}
        <Col span={12}>
          <Card
            title="各时段平均营收（过去4周）"
            loading={loading}
            bodyStyle={{ padding: 16 }}
          >
            {trendData.length > 0 ? (
              <Column
                data={trendData}
                xField="slot"
                yField="avg_yuan"
                height={260}
                color={TX_PRIMARY}
                label={{
                  position: 'top',
                  formatter: (v: Record<string, unknown>) =>
                    `${((v as Record<string, unknown>).avg_yuan as number).toLocaleString()}元`,
                }}
                meta={{
                  avg_yuan: { alias: '平均营收(元)' },
                  slot: { alias: '时段' },
                }}
                tooltip={{
                  formatter: (datum: Record<string, unknown>) => ({
                    name: '平均营收',
                    value: `${(datum.avg_yuan as number).toLocaleString()}元`,
                  }),
                }}
              />
            ) : (
              <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Text type="secondary">暂无数据</Text>
              </div>
            )}
          </Card>
        </Col>

        {/* Gap bar chart */}
        <Col span={12}>
          <Card
            title="岗位人力缺口 / 冗余（本周汇总）"
            loading={loading}
            bodyStyle={{ padding: 16 }}
          >
            {gapData.length > 0 ? (
              <Column
                data={gapData}
                xField="position"
                yField="count"
                seriesField="type"
                isGroup
                height={260}
                color={({ type }: { type: string }) =>
                  type === '缺人' ? TX_DANGER : TX_SUCCESS
                }
                label={{
                  position: 'top',
                  formatter: (v: Record<string, unknown>) => {
                    const c = v.count as number;
                    return c > 0 ? `缺${c}` : c < 0 ? `余${Math.abs(c)}` : '';
                  },
                }}
                meta={{
                  count: { alias: '人数差异' },
                  position: { alias: '岗位' },
                }}
                tooltip={{
                  formatter: (datum: Record<string, unknown>) => ({
                    name: datum.type as string,
                    value: `${Math.abs(datum.count as number)}人`,
                  }),
                }}
              />
            ) : (
              <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Tag icon={<CheckCircleOutlined />} color="green">
                  人力配置匹配，无缺口
                </Tag>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* Data source indicator */}
      {analysis && (
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            数据来源：
            {analysis.data_source === 'actual' ? (
              <Tag color="green" style={{ marginLeft: 4 }}>POS实际交易</Tag>
            ) : (
              <Tag color="orange" style={{ marginLeft: 4 }}>模拟数据（POS对接后自动切换）</Tag>
            )}
            {' | '}
            日均营收：{fen2yuanInt(analysis.total_avg_daily_revenue_fen)}元
          </Text>
        </div>
      )}
    </div>
  );
}
