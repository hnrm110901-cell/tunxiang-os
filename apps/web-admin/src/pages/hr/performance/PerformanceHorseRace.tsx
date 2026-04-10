/**
 * PerformanceHorseRace — 门店赛马
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 多门店选择（最多10家）+ 指标选择（营收/客单/出餐速度/好评率）+ 周期
 *  - 赛马排行榜ProTable（排名/门店/指标值/环比）
 *  - Bar横向柱状图对比
 *  - 冠军门店金色高亮
 *
 * API: POST /api/v1/performance/horse-race
 */

import { useRef, useState } from 'react';
import { Button, Card, Col, Row, Select, Space, Tag, Typography, message } from 'antd';
import { CrownOutlined, SearchOutlined } from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { Bar } from '@ant-design/charts';
import { txFetch } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface HorseRaceItem {
  rank: number;
  store_id: string;
  store_name: string;
  metric_value: number;
  metric_unit: string;
  mom_change: number; // 环比变化 %
}

const METRIC_OPTIONS = [
  { label: '营收', value: 'revenue' },
  { label: '客单价', value: 'avg_ticket' },
  { label: '出餐速度', value: 'dish_speed' },
  { label: '好评率', value: 'review_rate' },
];

const PERIOD_OPTIONS = [
  { label: '本周', value: 'this_week' },
  { label: '本月', value: 'this_month' },
  { label: '本季度', value: 'this_quarter' },
];

// ─── Component ───────────────────────────────────────────────────────────────

export default function PerformanceHorseRace() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [storeIds, setStoreIds] = useState<string[]>([]);
  const [metric, setMetric] = useState<string>('revenue');
  const [period, setPeriod] = useState<string>('this_month');
  const [raceData, setRaceData] = useState<HorseRaceItem[]>([]);
  const [loading, setLoading] = useState(false);

  // ─── 查询 ────────────────────────────────────────────────────────────────

  const handleQuery = async () => {
    if (storeIds.length === 0) {
      messageApi.warning('请至少选择一家门店');
      return;
    }
    if (storeIds.length > 10) {
      messageApi.warning('最多选择10家门店');
      return;
    }
    setLoading(true);
    try {
      const res = await txFetch('/api/v1/performance/horse-race', {
        method: 'POST',
        body: JSON.stringify({ store_ids: storeIds, metric, period }),
      }) as { ok: boolean; data: { items: HorseRaceItem[] } };
      if (res.ok) {
        setRaceData(res.data.items ?? []);
      }
    } catch {
      messageApi.error('查询失败');
    } finally {
      setLoading(false);
    }
  };

  // ─── Columns ─────────────────────────────────────────────────────────────

  const columns: ProColumns<HorseRaceItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 80,
      render: (_, r) =>
        r.rank === 1 ? (
          <Tag color="#FFD700" style={{ fontWeight: 'bold' }}>
            <CrownOutlined /> 冠军
          </Tag>
        ) : (
          <span>{r.rank}</span>
        ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 160,
      render: (_, r) => (
        <span style={r.rank === 1 ? { fontWeight: 'bold', color: TX_PRIMARY } : undefined}>
          {r.store_name}
        </span>
      ),
    },
    {
      title: '指标值',
      dataIndex: 'metric_value',
      width: 120,
      render: (_, r) => (
        <span style={r.rank === 1 ? { fontWeight: 'bold', fontSize: 16 } : undefined}>
          {r.metric_value}{r.metric_unit}
        </span>
      ),
    },
    {
      title: '环比',
      dataIndex: 'mom_change',
      width: 100,
      render: (_, r) => (
        <span style={{ color: r.mom_change >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {r.mom_change >= 0 ? '+' : ''}{r.mom_change.toFixed(1)}%
        </span>
      ),
    },
  ];

  // ─── Bar Chart ───────────────────────────────────────────────────────────

  const barConfig = {
    data: [...raceData].reverse(),
    xField: 'metric_value',
    yField: 'store_name',
    seriesField: 'store_name',
    color: (datum: HorseRaceItem) => (datum.rank === 1 ? '#FFD700' : TX_PRIMARY),
    legend: false as const,
    label: { position: 'right' as const },
  };

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>门店赛马</Title>

      {/* ── 筛选区 ── */}
      <Card style={{ marginBottom: 24 }}>
        <Space wrap size="middle">
          <Select
            mode="multiple"
            placeholder="选择门店（最多10家）"
            style={{ minWidth: 300 }}
            maxCount={10}
            value={storeIds}
            onChange={setStoreIds}
            options={[]}
            showSearch
            // 门店列表从API加载，此处简化为空options，实际可用request
          />
          <Select
            placeholder="选择指标"
            style={{ width: 140 }}
            value={metric}
            onChange={setMetric}
            options={METRIC_OPTIONS}
          />
          <Select
            placeholder="选择周期"
            style={{ width: 140 }}
            value={period}
            onChange={setPeriod}
            options={PERIOD_OPTIONS}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loading}
            onClick={handleQuery}
            style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            开始赛马
          </Button>
        </Space>
      </Card>

      {/* ── 结果 ── */}
      <Row gutter={16}>
        <Col span={12}>
          <ProTable<HorseRaceItem>
            headerTitle="赛马排行榜"
            dataSource={raceData}
            rowKey="store_id"
            columns={columns}
            search={false}
            pagination={false}
            rowClassName={(r) => (r.rank === 1 ? 'horse-race-champion' : '')}
          />
        </Col>
        <Col span={12}>
          <Card title="门店对比">
            {raceData.length > 0 && <Bar {...barConfig} height={Math.max(300, raceData.length * 50)} />}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
