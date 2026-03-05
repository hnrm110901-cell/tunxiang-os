import React, { useState, useCallback, useEffect } from 'react';
import {
  Row, Col, Card, Select, Button, Alert, Tag, Table, Statistic,
  Space, Spin, Typography, DatePicker,
} from 'antd';
import { FilePdfOutlined, ReloadOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import dayjs from 'dayjs';
import { apiClient } from '../services/api';
import { handleApiError } from '../utils/message';

const { Option } = Select;
const { Text } = Typography;

const MonthlyReportPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [stores, setStores] = useState<any[]>([]);
  const [selectedStore, setSelectedStore] = useState(localStorage.getItem('store_id') || 'STORE001');
  const [selectedMonth, setSelectedMonth] = useState(dayjs().subtract(1, 'month'));
  const [report, setReport] = useState<any>(null);

  const loadStores = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v1/stores');
      setStores(res.data?.stores || res.data || []);
    } catch (err: any) {
      handleApiError(err, '加载门店列表失败');
    }
  }, []);

  const loadReport = useCallback(async () => {
    if (!selectedStore) return;
    setLoading(true);
    try {
      const res = await apiClient.get(`/api/v1/reports/monthly/${selectedStore}`, {
        params: { year: selectedMonth.year(), month: selectedMonth.month() + 1 },
      });
      setReport(res.data);
    } catch (err: any) {
      handleApiError(err, '加载月报失败');
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [selectedStore, selectedMonth]);

  useEffect(() => { loadStores(); }, [loadStores]);
  useEffect(() => { loadReport(); }, [loadReport]);

  const handlePrintPdf = () => {
    const year = selectedMonth.year();
    const month = selectedMonth.month() + 1;
    window.open(
      `/api/v1/reports/monthly/${selectedStore}/html?year=${year}&month=${month}`,
      '_blank'
    );
  };

  const summary = report?.executive_summary;
  const chart   = report?.weekly_trend_chart;
  const top3    = report?.top3_decisions || [];

  const chartOption = chart ? {
    tooltip: { trigger: 'axis' },
    legend: { data: ['成本率%', '营业额¥'], bottom: 0 },
    xAxis: { type: 'category', data: chart.x_axis },
    yAxis: [
      { type: 'value', name: '成本率%', axisLabel: { formatter: '{value}%' } },
      { type: 'value', name: '营业额¥', axisLabel: { formatter: (v: number) => `¥${(v / 10000).toFixed(0)}万` } },
    ],
    series: [
      {
        name: '成本率%',
        type: 'line',
        smooth: true,
        data: chart.cost_rate_data,
        yAxisIndex: 0,
        itemStyle: { color: '#f5222d' },
        markLine: {
          data: [{ yAxis: 33, lineStyle: { color: '#faad14', type: 'dashed' }, label: { formatter: '警戒线33%' } }],
        },
      },
      {
        name: '营业额¥',
        type: 'bar',
        data: chart.revenue_data,
        yAxisIndex: 1,
        itemStyle: { color: '#1890ff', opacity: 0.4 },
      },
    ],
  } : null;

  const top3Columns = [
    {
      title: '#', key: 'rank', width: 36,
      render: (_: any, __: any, i: number) => (
        <Tag color={i === 0 ? 'red' : i === 1 ? 'orange' : 'blue'}>#{i + 1}</Tag>
      ),
    },
    { title: '执行动作', dataIndex: 'action', key: 'action' },
    {
      title: '预期节省¥', dataIndex: 'expected_saving_yuan', key: 'saving',
      render: (v: number) => (
        <Text style={{ color: '#52c41a', fontWeight: 600 }}>
          ¥{(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}
        </Text>
      ),
    },
    {
      title: '实际结果', dataIndex: 'outcome', key: 'outcome',
      render: (v: string) => v || <Text type="secondary">待统计</Text>,
    },
  ];

  const statusColor = (s: string) =>
    s === 'critical' ? '#f5222d' : s === 'warning' ? '#faad14' : '#52c41a';
  const statusLabel = (s: string) =>
    s === 'critical' ? '超标' : s === 'warning' ? '偏高' : '正常';
  const alertType = (s: string): 'error' | 'warning' | 'success' =>
    s === 'critical' ? 'error' : s === 'warning' ? 'warning' : 'success';

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          value={selectedStore}
          onChange={setSelectedStore}
          style={{ width: 160 }}
          placeholder="选择门店"
        >
          {stores.length > 0
            ? stores.map((s: any) => (
                <Option key={s.store_id || s.id} value={s.store_id || s.id}>
                  {s.name || s.store_id || s.id}
                </Option>
              ))
            : <Option value="STORE001">STORE001</Option>}
        </Select>
        <DatePicker
          picker="month"
          value={selectedMonth}
          onChange={(d) => d && setSelectedMonth(d)}
          disabledDate={(d) => d && d.isAfter(dayjs())}
          style={{ width: 120 }}
        />
        <Button icon={<ReloadOutlined />} onClick={loadReport} loading={loading}>刷新</Button>
        <Button
          type="primary"
          icon={<FilePdfOutlined />}
          onClick={handlePrintPdf}
          disabled={!report}
        >
          打印 / 导出 PDF
        </Button>
      </Space>

      <Spin spinning={loading}>
        {!report && !loading && (
          <Alert message="暂无报告数据，请选择门店和月份后加载" type="info" showIcon />
        )}

        {summary && (
          <>
            <Alert
              message={summary.headline}
              description={`报告周期：${summary.period}`}
              type={alertType(summary.cost_rate_status)}
              showIcon
              style={{ marginBottom: 16 }}
            />

            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col xs={12} md={4}>
                <Card size="small">
                  <Statistic title="月度营业额" value={summary.revenue_yuan} prefix="¥" precision={0} />
                </Card>
              </Col>
              <Col xs={12} md={4}>
                <Card size="small">
                  <Statistic
                    title="食材成本率"
                    value={summary.actual_cost_pct ?? 0}
                    suffix="%"
                    precision={1}
                    valueStyle={{ color: statusColor(summary.cost_rate_status) }}
                  />
                  <Tag
                    color={summary.cost_rate_status === 'critical' ? 'error'
                      : summary.cost_rate_status === 'warning' ? 'warning' : 'success'}
                    style={{ fontSize: 11, marginTop: 4 }}
                  >
                    {statusLabel(summary.cost_rate_status)}
                  </Tag>
                </Card>
              </Col>
              <Col xs={12} md={4}>
                <Card size="small">
                  <Statistic title="损耗金额" value={summary.waste_cost_yuan ?? 0} prefix="¥" precision={0} />
                </Card>
              </Col>
              <Col xs={12} md={4}>
                <Card size="small">
                  <Statistic
                    title="决策采纳率"
                    value={summary.decision_adoption_pct ?? 0}
                    suffix="%"
                    precision={1}
                  />
                </Card>
              </Col>
              <Col xs={12} md={4}>
                <Card size="small">
                  <Statistic
                    title="决策节省¥"
                    value={summary.total_saving_yuan ?? 0}
                    prefix="¥"
                    precision={0}
                    valueStyle={{ color: '#52c41a' }}
                  />
                </Card>
              </Col>
              <Col xs={12} md={4}>
                <Card size="small">
                  <Statistic
                    title="审批决策"
                    value={`${summary.decisions_approved ?? 0}/${summary.decisions_total ?? 0}`}
                  />
                </Card>
              </Col>
            </Row>

            {summary.narrative && (
              <Card
                size="small"
                style={{ marginBottom: 16, background: '#f6ffed', borderColor: '#b7eb8f' }}
              >
                <Text style={{ fontSize: 13, lineHeight: 1.8 }}>{summary.narrative}</Text>
              </Card>
            )}
          </>
        )}

        {chartOption && (
          <Card title="周成本率趋势" size="small" style={{ marginBottom: 16 }}>
            <ReactECharts option={chartOption} style={{ height: 260 }} />
          </Card>
        )}

        {top3.length > 0 && (
          <Card title="本月 Top3 节省决策" size="small">
            <Table
              dataSource={top3}
              columns={top3Columns}
              rowKey={(_: any, i: any) => i}
              size="small"
              pagination={false}
            />
          </Card>
        )}
      </Spin>
    </div>
  );
};

export default MonthlyReportPage;
