/**
 * 班次KDS生产报表 — Admin后台
 *
 * 技术栈：Ant Design 5.x + ProTable + ProForm + @ant-design/charts
 * 设计规范：admin.md + tokens.md（屯象OS Design Token）
 *
 * 页面结构：
 * 1. 顶部筛选栏：日期 + 班次 + 档口
 * 2. KPI卡片行：完成单量 / 平均出品时间 / 超时率 / 重做率
 * 3. 档口对比 ProTable
 * 4. 厨师绩效 ProTable
 * 5. 7天同班次趋势折线图
 * 6. 导出CSV按钮
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DownloadOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Line } from '@ant-design/charts';
import dayjs, { Dayjs } from 'dayjs';

const { Title, Text } = Typography;

// ─── Design Token 颜色（与 tokens.md 对齐） ─────────────────────────────────
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER = '#A32D2D';
const TX_PRIMARY = '#FF6B35';
const TX_BG_SECONDARY = '#F8F7F5';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface ShiftConfig {
  id: string;
  shift_name: string;
  start_time: string;
  end_time: string;
  color: string;
}

interface DeptRow {
  dept_id: string;
  dept_name: string;
  total_tasks: number;
  finished_tasks: number;
  avg_duration_seconds: number;
  timeout_rate: number;
  remake_rate: number;
}

interface OperatorRow {
  operator_id: string;
  operator_name: string;
  total_tasks: number;
  finished_tasks: number;
  avg_duration_seconds: number;
  remake_rate: number;
}

interface ShiftSummary {
  shift_id: string;
  shift_name: string;
  date: string;
  total_tasks: number;
  finished_tasks: number;
  avg_duration_seconds: number;
  timeout_count: number;
  remake_count: number;
  timeout_rate: number;
  remake_rate: number;
  dept_stats: DeptRow[];
  operator_stats: OperatorRow[];
}

interface TrendPoint {
  date: string;
  shift_name: string;
  total_tasks: number;
  finished_tasks: number;
  avg_duration_seconds: number;
  timeout_rate: number;
  remake_rate: number;
}

// ─── API 工具 ────────────────────────────────────────────────────────────────

function getTenantId(): string {
  return localStorage.getItem('tenantId') || '';
}

function getStoreId(): string {
  return localStorage.getItem('storeId') || '';
}

async function apiFetch<T>(path: string): Promise<T | null> {
  const tenantId = getTenantId();
  const res = await fetch(`/api/v1${path}`, {
    headers: { 'X-Tenant-ID': tenantId },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${text}`);
  }
  const json = await res.json();
  if (!json.ok) {
    throw new Error(json.error?.message || '请求失败');
  }
  return json.data as T;
}

async function fetchShiftConfigs(storeId: string): Promise<ShiftConfig[]> {
  return (await apiFetch<ShiftConfig[]>(`/shifts/${storeId}/config`)) ?? [];
}

async function fetchShiftReport(
  storeId: string,
  date: string,
  shiftId: string,
): Promise<ShiftSummary | null> {
  return apiFetch<ShiftSummary>(
    `/shifts/${storeId}/report?date=${date}&shift_id=${shiftId}`,
  );
}

async function fetchTrend(
  storeId: string,
  shiftId: string,
  days = 7,
): Promise<TrendPoint[]> {
  return (
    (await apiFetch<TrendPoint[]>(
      `/shifts/${storeId}/trend?shift_id=${shiftId}&days=${days}`,
    )) ?? []
  );
}

function buildExportUrl(storeId: string, date: string, shiftId: string): string {
  const tenantId = getTenantId();
  return `/api/v1/shifts/${storeId}/export?date=${date}&shift_id=${shiftId}&format=csv&_tenant=${tenantId}`;
}

// ─── 颜色工具 ────────────────────────────────────────────────────────────────

/** 超时率阈值着色：>15% 红色，5%-15% 黄色，<5% 绿色 */
function timeoutRateColor(rate: number): string {
  if (rate > 15) return TX_DANGER;
  if (rate > 5) return TX_WARNING;
  return TX_SUCCESS;
}

/** 重做率阈值着色：>10% 红色，3%-10% 黄色，<3% 绿色 */
function remakeRateColor(rate: number): string {
  if (rate > 10) return TX_DANGER;
  if (rate > 3) return TX_WARNING;
  return TX_SUCCESS;
}

function formatSeconds(sec: number): string {
  if (sec <= 0) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

// ─── 子组件：KPI 卡片 ────────────────────────────────────────────────────────

interface KpiCardsProps {
  summary: ShiftSummary | null;
  loading: boolean;
}

const KpiCards: React.FC<KpiCardsProps> = ({ summary, loading }) => {
  const cards = [
    {
      title: '完成单量',
      value: summary ? `${summary.finished_tasks} / ${summary.total_tasks}` : '—',
      color: TX_PRIMARY,
    },
    {
      title: '平均出品时间',
      value: summary ? formatSeconds(summary.avg_duration_seconds) : '—',
      color: '#1677ff',
    },
    {
      title: '超时率',
      value: summary ? `${summary.timeout_rate}%` : '—',
      color: summary ? timeoutRateColor(summary.timeout_rate) : '#999',
    },
    {
      title: '重做率',
      value: summary ? `${summary.remake_rate}%` : '—',
      color: summary ? remakeRateColor(summary.remake_rate) : '#999',
    },
  ];

  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      {cards.map((card) => (
        <Col span={6} key={card.title}>
          <Card
            loading={loading}
            style={{ borderRadius: 6, background: TX_BG_SECONDARY }}
            bodyStyle={{ padding: 20 }}
          >
            <Statistic
              title={<Text type="secondary">{card.title}</Text>}
              value={card.value}
              valueStyle={{ color: card.color, fontSize: 28, fontWeight: 'bold' }}
            />
          </Card>
        </Col>
      ))}
    </Row>
  );
};

// ─── 子组件：档口对比 ProTable ───────────────────────────────────────────────

interface DeptTableProps {
  data: DeptRow[];
  loading: boolean;
  filterDeptId?: string;
}

const deptColumns: ProColumns<DeptRow>[] = [
  { title: '档口名称', dataIndex: 'dept_name', width: 120 },
  { title: '总单量', dataIndex: 'total_tasks', sorter: (a, b) => a.total_tasks - b.total_tasks },
  { title: '完成单量', dataIndex: 'finished_tasks', sorter: (a, b) => a.finished_tasks - b.finished_tasks },
  {
    title: '平均出品时间',
    dataIndex: 'avg_duration_seconds',
    render: (_, r) => formatSeconds(r.avg_duration_seconds),
    sorter: (a, b) => a.avg_duration_seconds - b.avg_duration_seconds,
  },
  {
    title: '超时率',
    dataIndex: 'timeout_rate',
    render: (_, r) => (
      <Tag color={r.timeout_rate > 15 ? 'red' : r.timeout_rate > 5 ? 'orange' : 'green'}>
        {r.timeout_rate}%
      </Tag>
    ),
    sorter: (a, b) => a.timeout_rate - b.timeout_rate,
  },
  {
    title: '重做率',
    dataIndex: 'remake_rate',
    render: (_, r) => (
      <Tag color={r.remake_rate > 10 ? 'red' : r.remake_rate > 3 ? 'orange' : 'green'}>
        {r.remake_rate}%
      </Tag>
    ),
    sorter: (a, b) => a.remake_rate - b.remake_rate,
  },
];

const DeptTable: React.FC<DeptTableProps> = ({ data, loading, filterDeptId }) => {
  const filtered = filterDeptId ? data.filter((d) => d.dept_id === filterDeptId) : data;
  return (
    <ProTable<DeptRow>
      headerTitle="档口效率对比"
      columns={deptColumns}
      dataSource={filtered}
      loading={loading}
      rowKey="dept_id"
      search={false}
      options={false}
      pagination={false}
      style={{ marginBottom: 24 }}
    />
  );
};

// ─── 子组件：厨师绩效 ProTable ───────────────────────────────────────────────

const operatorColumns: ProColumns<OperatorRow>[] = [
  { title: '姓名', dataIndex: 'operator_name', width: 120 },
  { title: '总单量', dataIndex: 'total_tasks', sorter: (a, b) => a.total_tasks - b.total_tasks },
  { title: '完成单量', dataIndex: 'finished_tasks', sorter: (a, b) => a.finished_tasks - b.finished_tasks },
  {
    title: '平均出品时间',
    dataIndex: 'avg_duration_seconds',
    render: (_, r) => formatSeconds(r.avg_duration_seconds),
    sorter: (a, b) => a.avg_duration_seconds - b.avg_duration_seconds,
  },
  {
    title: '重做率',
    dataIndex: 'remake_rate',
    render: (_, r) => (
      <Tag color={r.remake_rate > 10 ? 'red' : r.remake_rate > 3 ? 'orange' : 'green'}>
        {r.remake_rate}%
      </Tag>
    ),
    sorter: (a, b) => a.remake_rate - b.remake_rate,
  },
];

interface OperatorTableProps {
  data: OperatorRow[];
  loading: boolean;
}

const OperatorTable: React.FC<OperatorTableProps> = ({ data, loading }) => (
  <ProTable<OperatorRow>
    headerTitle="厨师个人绩效"
    columns={operatorColumns}
    dataSource={data}
    loading={loading}
    rowKey="operator_id"
    search={false}
    options={false}
    pagination={{ defaultPageSize: 10 }}
    style={{ marginBottom: 24 }}
  />
);

// ─── 子组件：7天趋势折线图 ────────────────────────────────────────────────────

interface TrendChartProps {
  data: TrendPoint[];
  loading: boolean;
}

const TrendChart: React.FC<TrendChartProps> = ({ data, loading }) => {
  // 将每个 TrendPoint 展开为两条线：超时率 + 重做率
  const chartData = data.flatMap((p) => [
    { date: p.date, value: p.timeout_rate, metric: '超时率(%)' },
    { date: p.date, value: p.remake_rate, metric: '重做率(%)' },
    { date: p.date, value: p.avg_duration_seconds / 60, metric: '平均出品(分钟)' },
  ]);

  if (loading || data.length === 0) {
    return (
      <Card style={{ marginBottom: 24, textAlign: 'center', color: '#999' }} bodyStyle={{ padding: 40 }}>
        {loading ? '加载中...' : '暂无趋势数据'}
      </Card>
    );
  }

  return (
    <Card
      title="近7天同班次趋势"
      style={{ marginBottom: 24, borderRadius: 6 }}
    >
      <Line
        data={chartData}
        xField="date"
        yField="value"
        seriesField="metric"
        color={[TX_DANGER, TX_WARNING, TX_PRIMARY]}
        point={{ size: 4 }}
        smooth
        legend={{ position: 'top' }}
        yAxis={{ label: { formatter: (v: string) => `${v}` } }}
        tooltip={{
          formatter: (datum: { metric: string; value: number }) => ({
            name: datum.metric,
            value: datum.value.toFixed(1),
          }),
        }}
        height={280}
      />
    </Card>
  );
};

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export const ShiftReport: React.FC = () => {
  const storeId = getStoreId();

  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [shifts, setShifts] = useState<ShiftConfig[]>([]);
  const [selectedShiftId, setSelectedShiftId] = useState<string>('');
  const [filterDeptId, setFilterDeptId] = useState<string | undefined>(undefined);
  const [summary, setSummary] = useState<ShiftSummary | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loadingConfigs, setLoadingConfigs] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const [loadingTrend, setLoadingTrend] = useState(false);

  // 加载班次配置列表
  useEffect(() => {
    if (!storeId) return;
    setLoadingConfigs(true);
    fetchShiftConfigs(storeId)
      .then((configs) => {
        setShifts(configs);
        if (configs.length > 0 && !selectedShiftId) {
          setSelectedShiftId(configs[0].id);
        }
      })
      .catch((err: Error) => message.error(`加载班次配置失败：${err.message}`))
      .finally(() => setLoadingConfigs(false));
  }, [storeId]);

  // 加载报表
  const loadReport = useCallback(async () => {
    if (!storeId || !selectedShiftId || !selectedDate) return;
    const dateStr = selectedDate.format('YYYY-MM-DD');
    setLoadingReport(true);
    try {
      const result = await fetchShiftReport(storeId, dateStr, selectedShiftId);
      setSummary(result);
    } catch (err) {
      const e = err as Error;
      message.error(`加载报表失败：${e.message}`);
      setSummary(null);
    } finally {
      setLoadingReport(false);
    }
  }, [storeId, selectedShiftId, selectedDate]);

  // 加载趋势
  const loadTrend = useCallback(async () => {
    if (!storeId || !selectedShiftId) return;
    setLoadingTrend(true);
    try {
      const data = await fetchTrend(storeId, selectedShiftId, 7);
      setTrend(data);
    } catch (err) {
      const e = err as Error;
      message.error(`加载趋势失败：${e.message}`);
      setTrend([]);
    } finally {
      setLoadingTrend(false);
    }
  }, [storeId, selectedShiftId]);

  useEffect(() => {
    loadReport();
    loadTrend();
  }, [loadReport, loadTrend]);

  // 导出 CSV
  const handleExport = () => {
    if (!storeId || !selectedShiftId || !selectedDate) return;
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const url = buildExportUrl(storeId, dateStr, selectedShiftId);
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    a.click();
  };

  // 档口筛选选项（从报表数据中提取）
  const deptOptions = summary?.dept_stats.map((d) => ({
    label: d.dept_name,
    value: d.dept_id,
  })) ?? [];

  // 当前选中班次信息
  const currentShift = shifts.find((s) => s.id === selectedShiftId);

  return (
    <div style={{ padding: 24, minWidth: 1280 }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>班次KDS生产报表</Title>
          {currentShift && (
            <Text type="secondary">
              {currentShift.shift_name}&nbsp;
              {currentShift.start_time}–{currentShift.end_time}
            </Text>
          )}
        </div>
        <Button
          icon={<DownloadOutlined />}
          onClick={handleExport}
          disabled={!summary || loadingReport}
        >
          导出 CSV
        </Button>
      </div>

      {/* 筛选栏 */}
      <Card style={{ marginBottom: 24, borderRadius: 6 }} bodyStyle={{ padding: '16px 24px' }}>
        <Space size="large" wrap>
          <Space>
            <Text>日期：</Text>
            <DatePicker
              value={selectedDate}
              onChange={(val) => val && setSelectedDate(val)}
              allowClear={false}
              style={{ width: 140 }}
            />
          </Space>
          <Space>
            <Text>班次：</Text>
            <Select
              value={selectedShiftId}
              onChange={setSelectedShiftId}
              loading={loadingConfigs}
              style={{ width: 140 }}
              placeholder="选择班次"
              options={shifts.map((s) => ({
                label: (
                  <Space>
                    <span
                      style={{
                        display: 'inline-block',
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: s.color,
                      }}
                    />
                    {s.shift_name}
                  </Space>
                ),
                value: s.id,
              }))}
            />
          </Space>
          <Space>
            <Text>档口：</Text>
            <Select
              value={filterDeptId}
              onChange={setFilterDeptId}
              style={{ width: 140 }}
              placeholder="全部档口"
              allowClear
              options={deptOptions}
            />
          </Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => { loadReport(); loadTrend(); }}
            loading={loadingReport}
          >
            刷新
          </Button>
        </Space>
      </Card>

      {/* KPI 卡片行 */}
      <KpiCards summary={summary} loading={loadingReport} />

      {/* 档口对比 */}
      <DeptTable
        data={summary?.dept_stats ?? []}
        loading={loadingReport}
        filterDeptId={filterDeptId}
      />

      {/* 厨师绩效 */}
      <OperatorTable
        data={summary?.operator_stats ?? []}
        loading={loadingReport}
      />

      {/* 7天趋势图 */}
      <TrendChart data={trend} loading={loadingTrend} />
    </div>
  );
};

export default ShiftReport;
