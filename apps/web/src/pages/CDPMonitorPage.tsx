/**
 * CDP Monitor Page — 消费者数据平台监控面板
 *
 * 功能：
 * 1. KPI达标状态（填充率≥80% + RFM偏差<5%）
 * 2. 填充率看板（orders/reservations/queues）
 * 3. RFM等级分布（S1-S5柱状图）
 * 4. 待回填统计 + 一键全量回填
 * 5. RFM偏差校验结果
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Button, Tag, Progress, Table, Statistic, Alert, Space, Select, message, Modal } from 'antd';
import {
  CheckCircleOutlined, WarningOutlined, CloseCircleOutlined,
  SyncOutlined, DatabaseOutlined, TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { apiClient } from '../utils/apiClient';
import styles from './CDPMonitorPage.module.css';

interface FillRateItem {
  total: number;
  filled: number;
  rate: number;
}

interface KPIItem {
  target: string;
  actual: number;
  met: boolean;
}

interface RFMLevelItem {
  count: number;
  rate: number;
}

interface CDPDashboard {
  consumer_stats: {
    total_consumers: number;
    merged_count: number;
    active_mappings: number;
  };
  fill_rate: {
    orders: FillRateItem;
    reservations: FillRateItem;
    queues: FillRateItem;
  };
  fill_rate_health: string;
  rfm_distribution: {
    S1: RFMLevelItem;
    S2: RFMLevelItem;
    S3: RFMLevelItem;
    S4: RFMLevelItem;
    S5: RFMLevelItem;
    total: number;
  };
  deviation: {
    total: number;
    deviated: number;
    deviation_rate: number;
    kpi_met?: boolean;
  };
  kpi_summary: {
    fill_rate_kpi: KPIItem;
    deviation_kpi: KPIItem;
    all_met: boolean;
  };
  pending_backfill: {
    orders: number;
    members: number;
    total: number;
  };
}

const healthColor: Record<string, string> = {
  excellent: '#52c41a',
  good: '#1890ff',
  warning: '#faad14',
  critical: '#ff4d4f',
};

const healthLabel: Record<string, string> = {
  excellent: '优秀',
  good: '达标',
  warning: '需关注',
  critical: '告警',
};

const CDPMonitorPage: React.FC = () => {
  const [data, setData] = useState<CDPDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [storeId, setStoreId] = useState<string | undefined>(
    localStorage.getItem('store_id') || undefined
  );

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const params = storeId ? `?store_id=${storeId}` : '';
      const resp = await apiClient.get<CDPDashboard>(
        `/api/v1/cdp/monitor/dashboard${params}`
      );
      setData(resp);
    } catch {
      message.error('加载CDP监控数据失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const handleFullBackfill = async () => {
    Modal.confirm({
      title: '确认执行全量回填？',
      content: '将依次执行：订单回填 → 会员回填 → RFM重算 → 偏差校验。数据量大时可能需要数分钟。',
      okText: '开始回填',
      cancelText: '取消',
      onOk: async () => {
        setBackfilling(true);
        try {
          const result = await apiClient.post<any>('/api/v1/cdp/monitor/full-backfill', {
            store_id: storeId || null,
            batch_size: 500,
          });
          const kpi = result.kpi_summary;
          if (kpi?.all_met) {
            message.success('全量回填完成，所有KPI达标');
          } else {
            message.warning('全量回填完成，部分KPI未达标');
          }
          loadDashboard();
        } catch {
          message.error('回填失败，请重试');
        } finally {
          setBackfilling(false);
        }
      },
    });
  };

  if (!data && loading) {
    return <div style={{ padding: 24, textAlign: 'center' }}>加载中...</div>;
  }

  if (!data) {
    return <Alert type="error" message="无法加载CDP监控数据" showIcon style={{ margin: 24 }} />;
  }

  const { kpi_summary, fill_rate, rfm_distribution, deviation, consumer_stats, pending_backfill, fill_rate_health } = data;

  // RFM ECharts option
  const rfmOption = {
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: ['S1 核心', 'S2 成长', 'S3 普通', 'S4 待挽回', 'S5 流失'],
      axisLabel: { fontSize: 12 },
    },
    yAxis: { type: 'value' as const },
    series: [{
      type: 'bar',
      data: [
        { value: rfm_distribution.S1?.count || 0, itemStyle: { color: '#52c41a' } },
        { value: rfm_distribution.S2?.count || 0, itemStyle: { color: '#1890ff' } },
        { value: rfm_distribution.S3?.count || 0, itemStyle: { color: '#722ed1' } },
        { value: rfm_distribution.S4?.count || 0, itemStyle: { color: '#faad14' } },
        { value: rfm_distribution.S5?.count || 0, itemStyle: { color: '#ff4d4f' } },
      ],
      barWidth: '50%',
      label: { show: true, position: 'top' as const, fontSize: 12 },
    }],
    grid: { top: 30, bottom: 40, left: 50, right: 20 },
  };

  // Fill rate table data
  const fillRateRows = [
    { key: 'orders', name: '订单', ...fill_rate.orders },
    { key: 'reservations', name: '预订', ...fill_rate.reservations },
    { key: 'queues', name: '排队', ...fill_rate.queues },
  ];

  const fillRateColumns = [
    { title: '数据表', dataIndex: 'name', key: 'name' },
    { title: '总记录', dataIndex: 'total', key: 'total', render: (v: number) => v.toLocaleString() },
    { title: '已填充', dataIndex: 'filled', key: 'filled', render: (v: number) => v.toLocaleString() },
    {
      title: '填充率',
      dataIndex: 'rate',
      key: 'rate',
      render: (v: number) => (
        <Progress
          percent={Math.round(v * 100)}
          size="small"
          status={v >= 0.8 ? 'success' : v >= 0.6 ? 'normal' : 'exception'}
          style={{ width: 120 }}
        />
      ),
    },
  ];

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <h2 className={styles.title}>
          <DatabaseOutlined style={{ marginRight: 8 }} />
          CDP 监控面板
        </h2>
        <Space>
          <Select
            placeholder="全部门店"
            allowClear
            value={storeId}
            onChange={(v) => setStoreId(v)}
            style={{ width: 160 }}
            options={[{ label: '全部门店', value: undefined as any }]}
          />
          <Button
            icon={<SyncOutlined spin={loading} />}
            onClick={loadDashboard}
            loading={loading}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleFullBackfill}
            loading={backfilling}
            danger={pending_backfill.total > 0}
          >
            {backfilling ? '回填中...' : `全量回填${pending_backfill.total > 0 ? ` (${pending_backfill.total}条待处理)` : ''}`}
          </Button>
        </Space>
      </div>

      {/* KPI Status Banner */}
      <Alert
        type={kpi_summary.all_met ? 'success' : 'warning'}
        showIcon
        icon={kpi_summary.all_met ? <CheckCircleOutlined /> : <WarningOutlined />}
        message={
          <span style={{ fontWeight: 600 }}>
            {kpi_summary.all_met ? 'KPI 全部达标' : 'KPI 未全部达标'}
          </span>
        }
        description={
          <Space size={24}>
            <span>
              填充率：{kpi_summary.fill_rate_kpi.actual}%
              {' '}
              <Tag color={kpi_summary.fill_rate_kpi.met ? 'green' : 'red'}>
                目标 {kpi_summary.fill_rate_kpi.target}
              </Tag>
            </span>
            <span>
              RFM偏差：{kpi_summary.deviation_kpi.actual}%
              {' '}
              <Tag color={kpi_summary.deviation_kpi.met ? 'green' : 'red'}>
                目标 {kpi_summary.deviation_kpi.target}
              </Tag>
            </span>
          </Space>
        }
        style={{ marginBottom: 16 }}
      />

      {/* Row 1: Consumer Stats + Fill Rate Health */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="消费者总数"
              value={consumer_stats.total_consumers}
              prefix={<TeamOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已合并"
              value={consumer_stats.merged_count}
              suffix="次"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="ID映射"
              value={consumer_stats.active_mappings}
              suffix="条"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="填充率状态"
              value={healthLabel[fill_rate_health] || fill_rate_health}
              valueStyle={{ color: healthColor[fill_rate_health] || '#999' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Row 2: Fill Rate Table + Pending */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={16}>
          <Card title="consumer_id 填充率" size="small">
            <Table
              dataSource={fillRateRows}
              columns={fillRateColumns}
              pagination={false}
              size="small"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="待回填统计" size="small">
            <div className={styles.pendingCard}>
              <div className={styles.pendingRow}>
                <span>待回填订单</span>
                <Tag color={pending_backfill.orders > 0 ? 'orange' : 'green'}>
                  {pending_backfill.orders.toLocaleString()}
                </Tag>
              </div>
              <div className={styles.pendingRow}>
                <span>待回填会员</span>
                <Tag color={pending_backfill.members > 0 ? 'orange' : 'green'}>
                  {pending_backfill.members.toLocaleString()}
                </Tag>
              </div>
              <div className={styles.pendingRow} style={{ fontWeight: 600, borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
                <span>合计</span>
                <Tag color={pending_backfill.total > 0 ? 'red' : 'green'}>
                  {pending_backfill.total.toLocaleString()}
                </Tag>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      {/* Row 3: RFM Distribution + Deviation */}
      <Row gutter={16}>
        <Col span={16}>
          <Card title={`RFM 等级分布（共 ${rfm_distribution.total || 0} 人）`} size="small">
            <ReactECharts option={rfmOption} style={{ height: 260 }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="RFM 偏差校验" size="small">
            <div className={styles.deviationCard}>
              <div className={styles.deviationMain}>
                <div className={styles.deviationRate}>
                  {(deviation.deviation_rate * 100).toFixed(2)}%
                </div>
                <div className={styles.deviationLabel}>偏差率</div>
                <Tag
                  color={deviation.kpi_met ?? deviation.deviation_rate < 0.05 ? 'green' : 'red'}
                  style={{ marginTop: 8, fontSize: 13 }}
                  icon={deviation.kpi_met ?? deviation.deviation_rate < 0.05 ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                >
                  {deviation.kpi_met ?? deviation.deviation_rate < 0.05 ? 'KPI达标 (<5%)' : 'KPI未达标'}
                </Tag>
              </div>
              <div className={styles.deviationDetail}>
                <div className={styles.pendingRow}>
                  <span>校验总数</span>
                  <span>{deviation.total.toLocaleString()}</span>
                </div>
                <div className={styles.pendingRow}>
                  <span>偏差记录</span>
                  <span style={{ color: deviation.deviated > 0 ? '#ff4d4f' : '#52c41a' }}>
                    {deviation.deviated.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default CDPMonitorPage;
