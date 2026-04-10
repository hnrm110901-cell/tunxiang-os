/**
 * LaborMarginDashboard -- 人力成本实时毛利仪表盘
 * P2-5 · 人力成本毛利联动
 *
 * 功能：
 *  1. 顶部4卡片：日营收/食材成本/人力成本/真实毛利
 *  2. 堆叠面积图：每小时营收 vs 三项成本
 *  3. 亏损时段高亮
 *  4. ProTable小时明细
 *  5. 优化建议卡片（AI分析）
 *
 * API:
 *  GET /api/v1/labor-margin/realtime?store_id=&date=
 *  GET /api/v1/labor-margin/hourly?store_id=&date=
 *  GET /api/v1/labor-margin/loss-hours?store_id=&date=
 */

import { useEffect, useState } from 'react';
import {
  Alert,
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import { Area } from '@ant-design/charts';
import {
  DollarOutlined,
  ShoppingCartOutlined,
  TeamOutlined,
  TrophyOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface RealtimeMargin {
  store_id: string;
  date: string;
  revenue_fen: number;
  food_cost_fen: number;
  channel_fee_fen: number;
  labor_cost_fen: number;
  real_margin_fen: number;
  real_margin_rate: number;
  labor_cost_rate: number;
  peak_staff_count: number;
  hourly_count: number;
}

interface HourlyRow {
  hour: number;
  revenue_fen: number;
  food_cost_fen: number;
  channel_fee_fen: number;
  labor_cost_fen: number;
  real_margin_fen: number;
  margin_rate: number;
  staff_count: number;
  revenue_per_staff_fen: number;
}

interface LossHoursData {
  loss_hours: (HourlyRow & { suggestion: string })[];
  loss_hour_count: number;
  total_loss_fen: number;
  low_margin_hours: HourlyRow[];
  ai_tag: string;
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

const fmtYuan = (fen: number) => `\u00A5${(fen / 100).toFixed(0)}`;
const fmtPct = (rate: number) => `${(rate * 100).toFixed(1)}%`;

function marginColor(rate: number): string {
  if (rate < 0) return '#A32D2D';
  if (rate < 0.15) return '#BA7517';
  if (rate < 0.30) return '#FF6B35';
  return '#0F6E56';
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function LaborMarginDashboard() {
  const [storeId, setStoreId] = useState<string>('');
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [summary, setSummary] = useState<RealtimeMargin | null>(null);
  const [hourly, setHourly] = useState<HourlyRow[]>([]);
  const [lossData, setLossData] = useState<LossHoursData | null>(null);
  const [loading, setLoading] = useState(false);
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);

  // 加载门店列表
  useEffect(() => {
    txFetch<{ items: { id: string; store_name: string }[] }>('/api/v1/stores?page=1&size=100')
      .then((resp) => {
        const list = (resp.data?.items || []).map((s) => ({ id: s.id, name: s.store_name }));
        setStores(list);
        if (list.length > 0 && !storeId) setStoreId(list[0].id);
      })
      .catch(() => {
        // 降级：使用默认
        setStores([{ id: 'default', name: '默认门店' }]);
        setStoreId('default');
      });
  }, []);

  // 加载数据
  useEffect(() => {
    if (!storeId) return;
    const dateStr = selectedDate.format('YYYY-MM-DD');
    setLoading(true);

    Promise.all([
      txFetch<RealtimeMargin>(`/api/v1/labor-margin/realtime?store_id=${storeId}&target_date=${dateStr}`),
      txFetch<HourlyRow[]>(`/api/v1/labor-margin/hourly?store_id=${storeId}&target_date=${dateStr}`),
      txFetch<LossHoursData>(`/api/v1/labor-margin/loss-hours?store_id=${storeId}&target_date=${dateStr}`),
    ])
      .then(([summaryResp, hourlyResp, lossResp]) => {
        setSummary(summaryResp.data);
        setHourly(hourlyResp.data || []);
        setLossData(lossResp.data);
      })
      .catch(() => message.error('加载毛利数据失败'))
      .finally(() => setLoading(false));
  }, [storeId, selectedDate]);

  // 面积图数据
  const chartData = hourly
    .filter((h) => h.revenue_fen > 0)
    .flatMap((h) => [
      { hour: `${h.hour}:00`, type: '食材成本', value: h.food_cost_fen / 100 },
      { hour: `${h.hour}:00`, type: '渠道佣金', value: h.channel_fee_fen / 100 },
      { hour: `${h.hour}:00`, type: '人力成本', value: h.labor_cost_fen / 100 },
      { hour: `${h.hour}:00`, type: '真实毛利', value: Math.max(0, h.real_margin_fen / 100) },
    ]);

  const lossHourSet = new Set((lossData?.loss_hours || []).map((h) => h.hour));

  // 表格列
  const columns = [
    {
      title: '时段',
      dataIndex: 'hour',
      key: 'hour',
      width: 80,
      render: (h: number) => (
        <span style={{ color: lossHourSet.has(h) ? '#A32D2D' : undefined, fontWeight: lossHourSet.has(h) ? 600 : 400 }}>
          {h}:00
        </span>
      ),
    },
    { title: '营收', dataIndex: 'revenue_fen', key: 'revenue', render: fmtYuan, align: 'right' as const },
    { title: '食材成本', dataIndex: 'food_cost_fen', key: 'food', render: fmtYuan, align: 'right' as const },
    { title: '渠道佣金', dataIndex: 'channel_fee_fen', key: 'channel', render: fmtYuan, align: 'right' as const },
    { title: '人力成本', dataIndex: 'labor_cost_fen', key: 'labor', render: fmtYuan, align: 'right' as const },
    {
      title: '真实毛利',
      dataIndex: 'real_margin_fen',
      key: 'margin',
      render: (v: number) => <span style={{ color: marginColor(v / 100) }}>{fmtYuan(v)}</span>,
      align: 'right' as const,
    },
    {
      title: '毛利率',
      dataIndex: 'margin_rate',
      key: 'rate',
      render: (v: number) => <Tag color={v < 0.30 ? 'red' : v < 0.45 ? 'gold' : 'green'}>{fmtPct(v)}</Tag>,
      align: 'center' as const,
    },
    { title: '在岗', dataIndex: 'staff_count', key: 'staff', align: 'center' as const },
    { title: '人均产出', dataIndex: 'revenue_per_staff_fen', key: 'rps', render: fmtYuan, align: 'right' as const },
  ];

  return (
    <div>
      <Title level={4}>人力成本实时毛利仪表盘</Title>

      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }}>
        <Select
          value={storeId}
          onChange={setStoreId}
          style={{ width: 200 }}
          placeholder="选择门店"
          options={stores.map((s) => ({ label: s.name, value: s.id }))}
        />
        <DatePicker
          value={selectedDate}
          onChange={(d) => d && setSelectedDate(d)}
          allowClear={false}
        />
      </Space>

      {/* KPI 卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '日营收',
              value: summary ? (summary.revenue_fen / 100).toFixed(0) : '-',
              prefix: <DollarOutlined style={{ color: '#FF6B35' }} />,
              suffix: '元',
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '食材成本',
              value: summary ? (summary.food_cost_fen / 100).toFixed(0) : '-',
              prefix: <ShoppingCartOutlined />,
              suffix: '元',
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '人力成本',
              value: summary ? (summary.labor_cost_fen / 100).toFixed(0) : '-',
              prefix: <TeamOutlined />,
              suffix: '元',
              description: summary ? (
                <Text type={summary.labor_cost_rate > 0.30 ? 'danger' : 'secondary'}>
                  占比 {fmtPct(summary.labor_cost_rate)}
                </Text>
              ) : undefined,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '真实毛利',
              value: summary ? (summary.real_margin_fen / 100).toFixed(0) : '-',
              prefix: <TrophyOutlined style={{ color: summary && summary.real_margin_rate < 0.30 ? '#A32D2D' : '#0F6E56' }} />,
              suffix: '元',
              description: summary ? (
                <Tag color={summary.real_margin_rate < 0.30 ? 'red' : 'green'}>
                  毛利率 {fmtPct(summary.real_margin_rate)}
                </Tag>
              ) : undefined,
            }}
          />
        </Col>
      </Row>

      {/* 堆叠面积图 */}
      <Card title="小时成本结构" style={{ marginBottom: 16 }} loading={loading}>
        {chartData.length > 0 ? (
          <Area
            data={chartData}
            xField="hour"
            yField="value"
            seriesField="type"
            isStack
            height={320}
            areaStyle={{ fillOpacity: 0.7 }}
            color={['#A32D2D', '#BA7517', '#185FA5', '#0F6E56']}
            yAxis={{ label: { formatter: (v: string) => `${v}元` } }}
            tooltip={{ formatter: (datum) => ({ name: datum.type, value: `${Number(datum.value).toFixed(0)}元` }) }}
            annotations={
              Array.from(lossHourSet).map((h) => ({
                type: 'region',
                start: [`${h}:00`, 'min'] as [string, string],
                end: [`${h}:00`, 'max'] as [string, string],
                style: { fill: '#A32D2D', fillOpacity: 0.08 },
              }))
            }
          />
        ) : (
          <Text type="secondary">暂无数据</Text>
        )}
      </Card>

      {/* 亏损时段预警 */}
      {lossData && lossData.loss_hour_count > 0 && (
        <Card
          title={
            <Space>
              <WarningOutlined style={{ color: '#A32D2D' }} />
              <span>亏损时段识别</span>
              <Tag color="blue">{lossData.ai_tag}</Tag>
            </Space>
          }
          style={{ marginBottom: 16 }}
        >
          <Alert
            type="error"
            message={`发现 ${lossData.loss_hour_count} 个亏损时段，合计亏损 ${fmtYuan(Math.abs(lossData.total_loss_fen))}`}
            style={{ marginBottom: 12 }}
          />
          {lossData.loss_hours.map((lh) => (
            <Alert
              key={lh.hour}
              type="warning"
              message={lh.suggestion}
              style={{ marginBottom: 8 }}
              showIcon
            />
          ))}
        </Card>
      )}

      {/* 小时明细表 */}
      <Card title="小时明细">
        <Table
          loading={loading}
          dataSource={hourly.filter((h) => h.revenue_fen > 0 || h.staff_count > 0)}
          columns={columns}
          rowKey="hour"
          pagination={false}
          size="small"
          rowClassName={(record) => (lossHourSet.has(record.hour) ? 'ant-table-row-loss' : '')}
        />
      </Card>

      <style>{`
        .ant-table-row-loss {
          background-color: rgba(163, 45, 45, 0.06) !important;
        }
      `}</style>
    </div>
  );
}

