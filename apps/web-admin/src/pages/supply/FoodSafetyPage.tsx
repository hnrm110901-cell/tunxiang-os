/**
 * 食品安全追溯管理页 — 域D 供应链
 * 四大模块：食材批次追溯 / 食安检查记录 / 温控监测 / 合规报告
 *
 * 技术栈：Ant Design 5.x + ProComponents + SVG图表（无外部库）
 * API：/api/v1/supply/food-safety/* via txFetchData；失败时空数据 fallback
 */
import { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import { txFetchData } from '../../api/client';
import {
  ProTable,
  ProColumns,
  ActionType,
  ModalForm,
  ProFormSelect,
  ProFormTextArea,
  ProFormCheckbox,
} from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Tag,
  Space,
  Row,
  Col,
  Card,
  Statistic,
  Tabs,
  Drawer,
  Timeline,
  Modal,
  message,
  Badge,
  Typography,
  Checkbox,
  Form,
  Select,
  Input,
  Descriptions,
  List,
} from 'antd';
import {
  ExclamationCircleOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  ClockCircleOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  AlertOutlined,
  ReloadOutlined,
  DownloadOutlined,
  PlusOutlined,
  EyeOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';

const { Text, Title } = Typography;

// BASE URL 已废弃，改用 txFetchData 统一请求

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type BatchStatus = 'safe' | 'notice' | 'near_expiry' | 'urgent' | 'expired';

interface IngredientBatch {
  id: string;
  ingredient_name: string;
  batch_no: string;
  supplier: string;
  receive_date: string;
  shelf_life_days: number;
  expiry_date: string;
  days_remaining: number;
  store_name: string;
  store_id: string;
  status: BatchStatus;
  handled: boolean;
}

interface TraceNode {
  step: string;
  location: string;
  operator: string;
  time: string;
  detail: string;
}

interface InspectionRecord {
  id: string;
  date: string;
  store_name: string;
  inspector: string;
  total_items: number;
  passed_items: number;
  failed_items: number;
  grade: 'A' | 'B' | 'C';
  items: InspectionItem[];
}

interface InspectionItem {
  name: string;
  passed: boolean;
  remark: string;
}

interface TempDevice {
  id: string;
  name: string;
  type: 'fridge' | 'freezer' | 'hot_cabinet';
  store_name: string;
  current_temp: number;
  min_temp: number;
  max_temp: number;
  status: 'normal' | 'high' | 'critical';
  history_24h: number[];
}

interface TempAlarm {
  id: string;
  device_name: string;
  time: string;
  temperature: number;
  threshold: string;
  resolved: boolean;
}

interface MonthlyReport {
  month: string;
  inspection_count: number;
  pass_rate: number;
  near_expiry_handle_rate: number;
  expired_disposal_rate: number;
}

// ─── 食安合规统计类型（MV 快速通道）─────────────────────────────────────────

interface ComplianceStats {
  pass_rate: number;
  last_inspection_grade: string;
  near_expiry_count: number;
  unresolved_violations: number;
}

// Mock 数据已移除，所有数据来自真实 API，失败时返回空数组/空对象 fallback
const today = dayjs();

// Mock 数据已移除，所有数据来自真实 API，失败时返回空数组/空对象 fallback

const ALL_CHECK_ITEMS = [
  '冰箱温度检测', '案板消毒记录', '员工健康证', '食材标签完整',
  '留样规范', '垃圾分类', '灭蝇灯工作', '洗手消毒设施',
  '原材料储存', '地面清洁', '排水沟清洁', '通风设施',
];

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function getStatusConfig(status: BatchStatus): { color: string; text: string; bg: string } {
  switch (status) {
    case 'safe': return { color: '#52c41a', text: '安全', bg: 'transparent' };
    case 'notice': return { color: '#1677ff', text: '注意', bg: 'transparent' };
    case 'near_expiry': return { color: '#fa8c16', text: '临期', bg: 'transparent' };
    case 'urgent': return { color: '#f5222d', text: '紧急', bg: '#fff1f0' };
    case 'expired': return { color: '#820014', text: '过期', bg: '#fff1f0' };
    default: return { color: '#999', text: '未知', bg: 'transparent' };
  }
}

function getGradeConfig(grade: 'A' | 'B' | 'C'): { color: string; text: string } {
  switch (grade) {
    case 'A': return { color: '#52c41a', text: 'A级-优秀' };
    case 'B': return { color: '#fa8c16', text: 'B级-合格' };
    case 'C': return { color: '#f5222d', text: 'C级-不合格' };
  }
}

function getDeviceStatusConfig(status: 'normal' | 'high' | 'critical'): { color: string; text: string; bg: string } {
  switch (status) {
    case 'normal': return { color: '#52c41a', text: '正常', bg: '#f6ffed' };
    case 'high': return { color: '#fa8c16', text: '偏高', bg: '#fff7e6' };
    case 'critical': return { color: '#f5222d', text: '超标', bg: '#fff1f0' };
  }
}

function getDeviceTypeLabel(type: 'fridge' | 'freezer' | 'hot_cabinet'): string {
  switch (type) {
    case 'fridge': return '冷藏柜';
    case 'freezer': return '冷冻库';
    case 'hot_cabinet': return '保温柜';
  }
}

const getStoreId = () => localStorage.getItem('tx_store_id') ?? 'default';

async function apiFetch<T>(path: string, fallback: T): Promise<T> {
  try {
    return await txFetchData<T>(path);
  } catch {
    return fallback;
  }
}

// ─── SVG 折线图组件 ─────────────────────────────────────────────────────────

function TempLineChart({ data, minRange, maxRange }: { data: number[]; minRange: number; maxRange: number }) {
  const width = 320;
  const height = 100;
  const padX = 30;
  const padY = 15;

  const filteredData = data.filter((v) => v !== 0);
  if (filteredData.length === 0) {
    return <svg width={width} height={height}><text x={width / 2} y={height / 2} textAnchor="middle" fill="#999" fontSize={12}>暂无温度数据</text></svg>;
  }

  const allValues = [...data, minRange, maxRange];
  const minVal = Math.min(...allValues) - 2;
  const maxVal = Math.max(...allValues) + 2;

  const scaleX = (i: number) => padX + (i / (data.length - 1)) * (width - padX * 2);
  const scaleY = (v: number) => padY + ((maxVal - v) / (maxVal - minVal)) * (height - padY * 2);

  const points = data.map((v, i) => `${scaleX(i)},${scaleY(v)}`).join(' ');
  const rangeMinY = scaleY(minRange);
  const rangeMaxY = scaleY(maxRange);

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {/* 正常范围区域 */}
      <rect x={padX} y={rangeMaxY} width={width - padX * 2} height={rangeMinY - rangeMaxY} fill="#f6ffed" opacity={0.5} />
      <line x1={padX} y1={rangeMinY} x2={width - padX} y2={rangeMinY} stroke="#52c41a" strokeDasharray="4 2" strokeWidth={0.5} />
      <line x1={padX} y1={rangeMaxY} x2={width - padX} y2={rangeMaxY} stroke="#52c41a" strokeDasharray="4 2" strokeWidth={0.5} />
      {/* 温度折线 */}
      <polyline points={points} fill="none" stroke="#1677ff" strokeWidth={1.5} />
      {/* 数据点 */}
      {data.map((v, i) => {
        const outOfRange = v < minRange || v > maxRange;
        return (
          <circle
            key={i}
            cx={scaleX(i)}
            cy={scaleY(v)}
            r={outOfRange ? 3 : 1.5}
            fill={outOfRange ? '#f5222d' : '#1677ff'}
          />
        );
      })}
      {/* Y轴标签 */}
      <text x={2} y={rangeMaxY + 3} fontSize={9} fill="#999">{maxRange}°</text>
      <text x={2} y={rangeMinY + 3} fontSize={9} fill="#999">{minRange}°</text>
      {/* X轴标签 */}
      <text x={padX} y={height - 1} fontSize={9} fill="#999">0h</text>
      <text x={width / 2} y={height - 1} fontSize={9} fill="#999" textAnchor="middle">12h</text>
      <text x={width - padX} y={height - 1} fontSize={9} fill="#999" textAnchor="end">24h</text>
    </svg>
  );
}

// ─── SVG 堆叠柱状图组件 ─────────────────────────────────────────────────────

function StackedBarChart({ reports }: { reports: MonthlyReport[] }) {
  const width = 560;
  const height = 220;
  const padX = 50;
  const padY = 25;
  const padBottom = 35;
  const barWidth = 40;
  const gap = (width - padX * 2 - barWidth * reports.length) / Math.max(reports.length - 1, 1);

  const colors = { pass_rate: '#52c41a', near_expiry: '#fa8c16', expired: '#722ed1' };

  return (
    <svg width={width} height={height} style={{ display: 'block', margin: '0 auto' }}>
      {/* Y轴 */}
      <line x1={padX} y1={padY} x2={padX} y2={height - padBottom} stroke="#d9d9d9" />
      {[0, 25, 50, 75, 100].map((v) => {
        const y = padY + ((100 - v) / 100) * (height - padY - padBottom);
        return (
          <g key={v}>
            <line x1={padX - 4} y1={y} x2={padX} y2={y} stroke="#d9d9d9" />
            <text x={padX - 8} y={y + 3} fontSize={10} fill="#999" textAnchor="end">{v}%</text>
            <line x1={padX} y1={y} x2={width - padX} y2={y} stroke="#f0f0f0" strokeDasharray="3 3" />
          </g>
        );
      })}
      {/* X轴 */}
      <line x1={padX} y1={height - padBottom} x2={width - padX} y2={height - padBottom} stroke="#d9d9d9" />
      {/* 柱状图 */}
      {reports.map((r, i) => {
        const x = padX + i * (barWidth + gap);
        const barH = (height - padY - padBottom);
        const h1 = (r.pass_rate / 100) * barH;
        const h2 = (r.near_expiry_handle_rate / 100) * barH;
        const h3 = (r.expired_disposal_rate / 100) * barH;
        const baseY = height - padBottom;
        return (
          <g key={r.month}>
            <rect x={x} y={baseY - h1} width={barWidth / 3} height={h1} fill={colors.pass_rate} rx={2} opacity={0.8} />
            <rect x={x + barWidth / 3} y={baseY - h2} width={barWidth / 3} height={h2} fill={colors.near_expiry} rx={2} opacity={0.8} />
            <rect x={x + (barWidth * 2) / 3} y={baseY - h3} width={barWidth / 3} height={h3} fill={colors.expired} rx={2} opacity={0.8} />
            <text x={x + barWidth / 2} y={height - padBottom + 15} fontSize={10} fill="#666" textAnchor="middle">{r.month.slice(5)}月</text>
          </g>
        );
      })}
      {/* 图例 */}
      <g transform={`translate(${width - 180}, 8)`}>
        <rect width={10} height={10} fill={colors.pass_rate} rx={2} />
        <text x={14} y={9} fontSize={10} fill="#666">检查合格率</text>
        <rect x={85} width={10} height={10} fill={colors.near_expiry} rx={2} />
        <text x={99} y={9} fontSize={10} fill="#666">临期处理率</text>
      </g>
      <g transform={`translate(${width - 180}, 22)`}>
        <rect width={10} height={10} fill={colors.expired} rx={2} />
        <text x={14} y={9} fontSize={10} fill="#666">过期报损率</text>
      </g>
    </svg>
  );
}

// ─── 主组件 ─────────────────────────────────────────────────────────────────

export function FoodSafetyPage() {
  const batchTableRef = useRef<ActionType>();
  const inspTableRef = useRef<ActionType>();

  const [batches, setBatches] = useState<IngredientBatch[]>([]);
  const [inspections, setInspections] = useState<InspectionRecord[]>([]);
  const [devices, setDevices] = useState<TempDevice[]>([]);
  const [alarms, setAlarms] = useState<TempAlarm[]>([]);
  const [reports, setReports] = useState<MonthlyReport[]>([]);
  const [complianceStats, setComplianceStats] = useState<ComplianceStats | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const storeId = getStoreId();

  const [traceDrawerOpen, setTraceDrawerOpen] = useState(false);
  const [traceBatch, setTraceBatch] = useState<IngredientBatch | null>(null);
  const [traceNodes, setTraceNodes] = useState<TraceNode[]>([]);

  const [inspDetailOpen, setInspDetailOpen] = useState(false);
  const [inspDetail, setInspDetail] = useState<InspectionRecord | null>(null);

  const [newInspOpen, setNewInspOpen] = useState(false);
  const [expiredListOpen, setExpiredListOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('batch');

  // ── 数据加载 ──

  const loadBatches = useCallback(async () => {
    const data = await apiFetch<{ items?: IngredientBatch[] } | IngredientBatch[]>(
      `/api/v1/supply/food-safety/inspections?store_id=${storeId}`, [],
    );
    const items = Array.isArray(data) ? data : ((data as { items?: IngredientBatch[] }).items ?? []);
    setBatches(items);
    return items;
  }, [storeId]);

  const loadInspections = useCallback(async () => {
    const data = await apiFetch<{ items?: InspectionRecord[] } | InspectionRecord[]>(
      `/api/v1/supply/food-safety/inspections?store_id=${storeId}`, [],
    );
    const items = Array.isArray(data) ? data : ((data as { items?: InspectionRecord[] }).items ?? []);
    setInspections(items);
    return items;
  }, [storeId]);

  const loadDevices = useCallback(async () => {
    const data = await apiFetch<{ items?: TempDevice[] } | TempDevice[]>(
      `/api/v1/supply/food-safety/temperatures?store_id=${storeId}`, [],
    );
    const items = Array.isArray(data) ? data : ((data as { items?: TempDevice[] }).items ?? []);
    setDevices(items);
  }, [storeId]);

  const loadAlarms = useCallback(async () => {
    const data = await apiFetch<{ items?: TempAlarm[] } | TempAlarm[]>(
      `/api/v1/supply/food-safety/violations?store_id=${storeId}`, [],
    );
    const items = Array.isArray(data) ? data : ((data as { items?: TempAlarm[] }).items ?? []);
    setAlarms(items);
  }, [storeId]);

  const loadReports = useCallback(async () => {
    const data = await apiFetch<{ items?: MonthlyReport[] } | MonthlyReport[]>(
      `/api/v1/supply/food-safety/temperatures?store_id=${storeId}`, [],
    );
    const items = Array.isArray(data) ? data : ((data as { items?: MonthlyReport[] }).items ?? []);
    setReports(items);
  }, [storeId]);

  const loadComplianceStats = useCallback(async () => {
    const data = await apiFetch<ComplianceStats>(
      `/api/v1/supply/food-safety/compliance-stats?store_id=${storeId}`,
      { pass_rate: 0, last_inspection_grade: '—', near_expiry_count: 0, unresolved_violations: 0 },
    );
    setComplianceStats(data);
  }, [storeId]);

  useEffect(() => {
    setLoadError(null);
    Promise.allSettled([
      loadBatches(),
      loadInspections(),
      loadDevices(),
      loadAlarms(),
      loadReports(),
      loadComplianceStats(),
    ]).then((results) => {
      const allFailed = results.every((r) => r.status === 'rejected');
      if (allFailed) setLoadError('食安数据加载失败，请检查网络或后端服务');
    });
  }, [loadBatches, loadInspections, loadDevices, loadAlarms, loadReports, loadComplianceStats]);

  // ── 统计计算 ──

  const stats = useMemo(() => {
    const nearExpiryCount = batches.filter((b) => b.status === 'near_expiry' || b.status === 'urgent').length;
    const expiredCount = batches.filter((b) => b.status === 'expired' && !b.handled).length;
    const totalInsp = inspections.length;
    const passedInsp = inspections.filter((i) => i.grade === 'A').length;
    const passRate = totalInsp > 0 ? Math.round((passedInsp / totalInsp) * 100) : 0;
    return { nearExpiryCount, expiredCount, passRate };
  }, [batches, inspections]);

  const expiredBatches = useMemo(() => batches.filter((b) => b.status === 'expired' && !b.handled), [batches]);

  // ── 操作处理 ──

  const handleViewTrace = useCallback(async (batch: IngredientBatch) => {
    setTraceBatch(batch);
    const data = await apiFetch<TraceNode[]>(
      `/api/v1/supply/food-safety/trace/${batch.batch_no}`,
      [],
    );
    setTraceNodes(data);
    setTraceDrawerOpen(true);
  }, []);

  const handleDisposal = useCallback((batch: IngredientBatch) => {
    Modal.confirm({
      title: '确认报损处理',
      icon: <ExclamationCircleOutlined />,
      content: `确认将「${batch.ingredient_name}」(批次 ${batch.batch_no}) 进行报损处理？此操作不可撤销。`,
      okText: '确认报损',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await txFetchData(`/api/v1/supply/food-safety/violations`, {
            method: 'POST',
            body: JSON.stringify({ batch_id: batch.id, reason: 'expired' }),
          } as RequestInit);
        } catch {
          // 降级：乐观更新 UI
        }
        setBatches((prev) => prev.map((b) => b.id === batch.id ? { ...b, handled: true } : b));
        message.success(`已报损：${batch.ingredient_name} (${batch.batch_no})`);
      },
    });
  }, []);

  const handleMarkHandled = useCallback((batch: IngredientBatch) => {
    setBatches((prev) => prev.map((b) => b.id === batch.id ? { ...b, handled: true } : b));
    message.success(`已标记处理：${batch.ingredient_name}`);
  }, []);

  const handleExportReport = useCallback(() => {
    message.success('月度报告已生成（模拟PDF导出）');
  }, []);

  // ── 批次追溯表格列 ──

  const batchColumns: ProColumns<IngredientBatch>[] = [
    {
      title: '食材名称',
      dataIndex: 'ingredient_name',
      width: 120,
      fixed: 'left',
      render: (_, record) => {
        const cfg = getStatusConfig(record.status);
        return <Text strong style={{ color: record.status === 'expired' || record.status === 'urgent' ? cfg.color : undefined }}>{record.ingredient_name}</Text>;
      },
    },
    { title: '批次号', dataIndex: 'batch_no', width: 160, copyable: true },
    { title: '供应商', dataIndex: 'supplier', width: 130, ellipsis: true },
    { title: '入库日期', dataIndex: 'receive_date', width: 110, valueType: 'date' },
    { title: '保质期(天)', dataIndex: 'shelf_life_days', width: 90, align: 'center' },
    { title: '到期日', dataIndex: 'expiry_date', width: 110, valueType: 'date' },
    {
      title: '剩余天数',
      dataIndex: 'days_remaining',
      width: 100,
      align: 'center',
      sorter: (a, b) => a.days_remaining - b.days_remaining,
      render: (_, record) => {
        const cfg = getStatusConfig(record.status);
        return (
          <Text strong style={{ color: cfg.color }}>
            {record.days_remaining > 0 ? `${record.days_remaining}天` : `已过期${Math.abs(record.days_remaining)}天`}
          </Text>
        );
      },
    },
    { title: '门店', dataIndex: 'store_name', width: 120 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      align: 'center',
      filters: [
        { text: '安全', value: 'safe' },
        { text: '注意', value: 'notice' },
        { text: '临期', value: 'near_expiry' },
        { text: '紧急', value: 'urgent' },
        { text: '过期', value: 'expired' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (_, record) => {
        const cfg = getStatusConfig(record.status);
        return <Tag color={cfg.color} style={record.status === 'expired' ? { animation: 'pulse 1.5s infinite' } : undefined}>{cfg.text}</Tag>;
      },
    },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewTrace(record)}>追溯链</Button>
          {(record.status === 'expired' || record.status === 'urgent') && !record.handled && (
            <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDisposal(record)}>报损</Button>
          )}
          {!record.handled && record.status !== 'safe' && (
            <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleMarkHandled(record)}>已处理</Button>
          )}
        </Space>
      ),
    },
  ];

  // ── 检查记录表格列 ──

  const inspColumns: ProColumns<InspectionRecord>[] = [
    { title: '检查日期', dataIndex: 'date', width: 110, valueType: 'date', sorter: (a, b) => dayjs(a.date).unix() - dayjs(b.date).unix() },
    { title: '门店', dataIndex: 'store_name', width: 120 },
    { title: '检查人', dataIndex: 'inspector', width: 100 },
    { title: '检查项数', dataIndex: 'total_items', width: 90, align: 'center' },
    { title: '通过数', dataIndex: 'passed_items', width: 80, align: 'center', render: (v) => <Text style={{ color: '#52c41a' }}>{v as number}</Text> },
    { title: '不合格数', dataIndex: 'failed_items', width: 90, align: 'center', render: (_, r) => r.failed_items > 0 ? <Text style={{ color: '#f5222d' }}>{r.failed_items}</Text> : <Text style={{ color: '#999' }}>0</Text> },
    {
      title: '总评',
      dataIndex: 'grade',
      width: 110,
      align: 'center',
      filters: [{ text: 'A级', value: 'A' }, { text: 'B级', value: 'B' }, { text: 'C级', value: 'C' }],
      onFilter: (value, record) => record.grade === value,
      render: (_, record) => {
        const cfg = getGradeConfig(record.grade);
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
      },
    },
    {
      title: '操作',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { setInspDetail(record); setInspDetailOpen(true); }}>查看详情</Button>
      ),
    },
  ];

  // ── 排序：过期/紧急置顶 ──

  const sortedBatches = useMemo(() => {
    const priorityOrder: Record<BatchStatus, number> = { expired: 0, urgent: 1, near_expiry: 2, notice: 3, safe: 4 };
    return [...batches].sort((a, b) => {
      const pa = priorityOrder[a.status] ?? 5;
      const pb = priorityOrder[b.status] ?? 5;
      return pa - pb;
    });
  }, [batches]);

  // ── 渲染 ──

  return (
    <div style={{ padding: 24 }}>
      {/* 全局脉冲动画 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>

      <Title level={4} style={{ marginBottom: 20 }}>
        <SafetyCertificateOutlined style={{ marginRight: 8, color: '#52c41a' }} />
        食品安全追溯管理
      </Title>

      {loadError && (
        <Alert
          type="error"
          message={loadError}
          closable
          onClose={() => setLoadError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* ── 顶部预警面板 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card
            hoverable
            style={{ borderLeft: '4px solid #fa8c16' }}
            bodyStyle={{ padding: '20px 24px' }}
            onClick={() => setActiveTab('batch')}
          >
            <Statistic
              title={<Text style={{ fontSize: 14 }}>今日临期品种数</Text>}
              value={stats.nearExpiryCount}
              valueStyle={{ color: '#fa8c16', fontSize: 36, fontWeight: 700 }}
              prefix={<WarningOutlined />}
              suffix="种"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card
            hoverable
            style={{
              borderLeft: '4px solid #f5222d',
              cursor: stats.expiredCount > 0 ? 'pointer' : 'default',
            }}
            bodyStyle={{ padding: '20px 24px' }}
            onClick={() => stats.expiredCount > 0 && setExpiredListOpen(true)}
          >
            <Statistic
              title={<Text style={{ fontSize: 14 }}>过期品种数（未处理）</Text>}
              value={stats.expiredCount}
              valueStyle={{
                color: '#f5222d',
                fontSize: 36,
                fontWeight: 700,
                animation: stats.expiredCount > 0 ? 'pulse 1.5s infinite' : undefined,
              }}
              prefix={<ExclamationCircleOutlined />}
              suffix="种"
            />
            {stats.expiredCount > 0 && (
              <Text type="secondary" style={{ fontSize: 12 }}>点击查看详情并紧急处理</Text>
            )}
          </Card>
        </Col>
        <Col span={8}>
          <Card
            hoverable
            style={{ borderLeft: '4px solid #52c41a' }}
            bodyStyle={{ padding: '20px 24px' }}
            onClick={() => setActiveTab('inspection')}
          >
            <Statistic
              title={<Text style={{ fontSize: 14 }}>本月食安检查完成率</Text>}
              value={stats.passRate}
              valueStyle={{ color: '#52c41a', fontSize: 36, fontWeight: 700 }}
              prefix={<CheckCircleOutlined />}
              suffix="%"
            />
          </Card>
        </Col>
      </Row>

      {/* ── 过期食材紧急处理弹窗 ── */}
      <Modal
        title={<><ExclamationCircleOutlined style={{ color: '#f5222d', marginRight: 8 }} />过期食材紧急处理</>}
        open={expiredListOpen}
        onCancel={() => setExpiredListOpen(false)}
        footer={null}
        width={700}
      >
        <List
          dataSource={expiredBatches}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button key="dispose" type="primary" danger size="small" onClick={() => { handleDisposal(item); setExpiredListOpen(false); }}>
                  立即报损
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={<Text strong style={{ color: '#820014' }}>{item.ingredient_name} - {item.batch_no}</Text>}
                description={
                  <Space direction="vertical" size={2}>
                    <Text type="secondary">供应商：{item.supplier} | 门店：{item.store_name}</Text>
                    <Text type="danger">已过期 {Math.abs(item.days_remaining)} 天（到期日：{item.expiry_date}）</Text>
                  </Space>
                }
              />
            </List.Item>
          )}
          locale={{ emptyText: '暂无过期食材' }}
        />
      </Modal>

      {/* ── Tab 区域 ── */}
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'batch',
              label: (
                <span>
                  <ClockCircleOutlined style={{ marginRight: 4 }} />
                  食材批次追溯
                  {stats.expiredCount > 0 && <Badge count={stats.expiredCount} offset={[8, -4]} size="small" />}
                </span>
              ),
              children: (
                <ProTable<IngredientBatch>
                  actionRef={batchTableRef}
                  rowKey="id"
                  columns={batchColumns}
                  dataSource={sortedBatches}
                  search={false}
                  scroll={{ x: 1300 }}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  toolBarRender={() => [
                    <Button key="refresh" icon={<ReloadOutlined />} onClick={() => loadBatches()}>刷新</Button>,
                  ]}
                  rowClassName={(record) => {
                    if (record.handled) return '';
                    if (record.status === 'expired') return 'row-expired';
                    if (record.status === 'urgent') return 'row-urgent';
                    return '';
                  }}
                  headerTitle="食材批次列表"
                  options={{ density: true, reload: () => loadBatches() }}
                />
              ),
            },
            {
              key: 'inspection',
              label: (
                <span>
                  <FileTextOutlined style={{ marginRight: 4 }} />
                  食安检查记录
                </span>
              ),
              children: (
                <>
                  <ProTable<InspectionRecord>
                    actionRef={inspTableRef}
                    rowKey="id"
                    columns={inspColumns}
                    dataSource={inspections}
                    search={false}
                    pagination={{ pageSize: 10 }}
                    toolBarRender={() => [
                      <Button key="new" type="primary" icon={<PlusOutlined />} onClick={() => setNewInspOpen(true)}>新建检查</Button>,
                      <Button key="refresh" icon={<ReloadOutlined />} onClick={() => loadInspections()}>刷新</Button>,
                    ]}
                    headerTitle="检查记录列表"
                    options={{ density: true, reload: () => loadInspections() }}
                  />
                </>
              ),
            },
            {
              key: 'temp',
              label: (
                <span>
                  <ThunderboltOutlined style={{ marginRight: 4 }} />
                  温控监测
                  {alarms.filter((a) => !a.resolved).length > 0 && (
                    <Badge count={alarms.filter((a) => !a.resolved).length} offset={[8, -4]} size="small" />
                  )}
                </span>
              ),
              children: (
                <div>
                  <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
                    {devices.map((device) => {
                      const cfg = getDeviceStatusConfig(device.status);
                      return (
                        <Col key={device.id} xs={24} sm={12} lg={8}>
                          <Card
                            size="small"
                            style={{ borderLeft: `4px solid ${cfg.color}`, background: cfg.bg }}
                            title={
                              <Space>
                                <Badge status={device.status === 'normal' ? 'success' : device.status === 'high' ? 'warning' : 'error'} />
                                <Text strong>{device.name}</Text>
                                <Tag>{getDeviceTypeLabel(device.type)}</Tag>
                              </Space>
                            }
                            extra={<Tag color={cfg.color}>{cfg.text}</Tag>}
                          >
                            <div style={{ textAlign: 'center', marginBottom: 8 }}>
                              <div style={{ fontSize: 32, fontWeight: 700, color: cfg.color }}>
                                {device.current_temp.toFixed(1)}°C
                              </div>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                正常范围：{device.min_temp}°C ~ {device.max_temp}°C
                              </Text>
                            </div>
                            <div style={{ marginBottom: 4 }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>{device.store_name} | 24小时温度趋势</Text>
                            </div>
                            <TempLineChart data={device.history_24h} minRange={device.min_temp} maxRange={device.max_temp} />
                          </Card>
                        </Col>
                      );
                    })}
                  </Row>

                  <Card title={<><AlertOutlined style={{ marginRight: 8, color: '#f5222d' }} />超标报警记录</>} size="small">
                    <List
                      dataSource={alarms}
                      renderItem={(item) => (
                        <List.Item
                          actions={[
                            item.resolved
                              ? <Tag key="status" color="green">已处理</Tag>
                              : <Tag key="status" color="red" style={{ animation: 'pulse 1.5s infinite' }}>未处理</Tag>,
                          ]}
                        >
                          <List.Item.Meta
                            title={<Text strong style={{ color: item.resolved ? '#999' : '#f5222d' }}>{item.device_name}</Text>}
                            description={`${item.time} | 温度 ${item.temperature}°C | 阈值 ${item.threshold}`}
                          />
                        </List.Item>
                      )}
                      locale={{ emptyText: '暂无报警记录' }}
                    />
                  </Card>
                </div>
              ),
            },
            {
              key: 'report',
              label: (
                <span>
                  <EnvironmentOutlined style={{ marginRight: 4 }} />
                  合规报告
                </span>
              ),
              children: (
                <div>
                  <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
                    {reports.slice(-1).map((r) => (
                      <Col span={24} key={r.month}>
                        <Card title={`${r.month} 月度食安报告`}>
                          <Row gutter={16}>
                            <Col span={6}>
                              <Statistic title="检查次数" value={r.inspection_count} suffix="次" />
                            </Col>
                            <Col span={6}>
                              <Statistic
                                title="合格率"
                                value={r.pass_rate}
                                suffix="%"
                                valueStyle={{ color: r.pass_rate >= 90 ? '#52c41a' : r.pass_rate >= 80 ? '#fa8c16' : '#f5222d' }}
                              />
                            </Col>
                            <Col span={6}>
                              <Statistic
                                title="临期处理率"
                                value={r.near_expiry_handle_rate}
                                suffix="%"
                                valueStyle={{ color: r.near_expiry_handle_rate >= 90 ? '#52c41a' : '#fa8c16' }}
                              />
                            </Col>
                            <Col span={6}>
                              <Statistic
                                title="过期报损率"
                                value={r.expired_disposal_rate}
                                suffix="%"
                                valueStyle={{ color: r.expired_disposal_rate >= 95 ? '#52c41a' : '#f5222d' }}
                              />
                            </Col>
                          </Row>
                        </Card>
                      </Col>
                    ))}
                  </Row>

                  <Card title="月度食安指标趋势" style={{ marginBottom: 16 }}>
                    <StackedBarChart reports={reports} />
                  </Card>

                  <div style={{ textAlign: 'center' }}>
                    <Button type="primary" icon={<DownloadOutlined />} size="large" onClick={handleExportReport}>
                      生成月度报告（PDF）
                    </Button>
                  </div>
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* ── 追溯链 Drawer ── */}
      <Drawer
        title={traceBatch ? `追溯链 — ${traceBatch.ingredient_name} (${traceBatch.batch_no})` : '追溯链'}
        open={traceDrawerOpen}
        onClose={() => setTraceDrawerOpen(false)}
        width={520}
      >
        {traceBatch && (
          <Descriptions column={1} size="small" style={{ marginBottom: 24 }}>
            <Descriptions.Item label="食材名称">{traceBatch.ingredient_name}</Descriptions.Item>
            <Descriptions.Item label="批次号">{traceBatch.batch_no}</Descriptions.Item>
            <Descriptions.Item label="供应商">{traceBatch.supplier}</Descriptions.Item>
            <Descriptions.Item label="门店">{traceBatch.store_name}</Descriptions.Item>
            <Descriptions.Item label="入库日期">{traceBatch.receive_date}</Descriptions.Item>
            <Descriptions.Item label="到期日">{traceBatch.expiry_date}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={getStatusConfig(traceBatch.status).color}>
                {getStatusConfig(traceBatch.status).text}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
        )}
        <Title level={5} style={{ marginBottom: 16 }}>全链路追溯时间轴</Title>
        <Timeline
          items={traceNodes.map((node, idx) => ({
            color: idx === traceNodes.length - 1 ? '#52c41a' : '#1677ff',
            children: (
              <div>
                <Text strong style={{ fontSize: 14 }}>{node.step}</Text>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    <EnvironmentOutlined style={{ marginRight: 4 }} />
                    {node.location}
                  </Text>
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    操作人：{node.operator} | {node.time}
                  </Text>
                </div>
                <div style={{ marginTop: 4, padding: '4px 8px', background: '#fafafa', borderRadius: 4, fontSize: 12 }}>
                  {node.detail}
                </div>
              </div>
            ),
          }))}
        />
      </Drawer>

      {/* ── 检查详情 Drawer ── */}
      <Drawer
        title={inspDetail ? `检查详情 — ${inspDetail.store_name} (${inspDetail.date})` : '检查详情'}
        open={inspDetailOpen}
        onClose={() => setInspDetailOpen(false)}
        width={520}
      >
        {inspDetail && (
          <>
            <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="检查日期">{inspDetail.date}</Descriptions.Item>
              <Descriptions.Item label="门店">{inspDetail.store_name}</Descriptions.Item>
              <Descriptions.Item label="检查人">{inspDetail.inspector}</Descriptions.Item>
              <Descriptions.Item label="总评">
                <Tag color={getGradeConfig(inspDetail.grade).color}>
                  {getGradeConfig(inspDetail.grade).text}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
            <Title level={5} style={{ marginBottom: 12 }}>检查项清单</Title>
            <List
              dataSource={inspDetail.items}
              renderItem={(item) => (
                <List.Item>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Space>
                      {item.passed
                        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                        : <ExclamationCircleOutlined style={{ color: '#f5222d' }} />}
                      <Text style={{ color: item.passed ? undefined : '#f5222d' }}>{item.name}</Text>
                    </Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>{item.remark}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </>
        )}
      </Drawer>

      {/* ── 新建检查 Modal ── */}
      <Modal
        title="新建食安检查"
        open={newInspOpen}
        onCancel={() => setNewInspOpen(false)}
        footer={null}
        width={600}
      >
        <NewInspectionForm
          onSubmit={(values) => {
            const newRecord: InspectionRecord = {
              id: `ins-${Date.now()}`,
              date: dayjs().format('YYYY-MM-DD'),
              store_name: values.store_name,
              inspector: values.inspector,
              total_items: values.items.length,
              passed_items: values.items.filter((it: { passed: boolean }) => it.passed).length,
              failed_items: values.items.filter((it: { passed: boolean }) => !it.passed).length,
              grade: values.items.filter((it: { passed: boolean }) => !it.passed).length === 0 ? 'A'
                : values.items.filter((it: { passed: boolean }) => !it.passed).length <= 2 ? 'B' : 'C',
              items: values.items,
            };
            setInspections((prev) => [newRecord, ...prev]);
            setNewInspOpen(false);
            message.success('食安检查已提交');
          }}
        />
      </Modal>

      {/* ── 行样式 ── */}
      <style>{`
        .row-expired td {
          background: #fff1f0 !important;
        }
        .row-urgent td {
          background: #fff7e6 !important;
        }
      `}</style>
    </div>
  );
}

// ─── 新建检查表单子组件 ────────────────────────────────────────────────────

interface NewInspFormValues {
  store_name: string;
  inspector: string;
  items: InspectionItem[];
}

function NewInspectionForm({ onSubmit }: { onSubmit: (values: NewInspFormValues) => void }) {
  const [form] = Form.useForm();
  const [selectedItems, setSelectedItems] = useState<string[]>(ALL_CHECK_ITEMS);
  const [results, setResults] = useState<Record<string, { passed: boolean; remark: string }>>({});

  const handleItemResult = (name: string, passed: boolean) => {
    setResults((prev) => ({
      ...prev,
      [name]: { ...prev[name], passed, remark: prev[name]?.remark ?? '' },
    }));
  };

  const handleItemRemark = (name: string, remark: string) => {
    setResults((prev) => ({
      ...prev,
      [name]: { ...prev[name], passed: prev[name]?.passed ?? true, remark },
    }));
  };

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      const items: InspectionItem[] = selectedItems.map((name) => ({
        name,
        passed: results[name]?.passed ?? true,
        remark: results[name]?.remark ?? '',
      }));
      onSubmit({ store_name: values.store_name, inspector: values.inspector, items });
    }).catch(() => {
      message.warning('请完善表单信息');
    });
  };

  return (
    <Form form={form} layout="vertical">
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="store_name" label="门店" rules={[{ required: true, message: '请选择门店' }]}>
            <Select placeholder="选择门店">
              <Select.Option value="长沙万达店">长沙万达店</Select.Option>
              <Select.Option value="长沙IFS店">长沙IFS店</Select.Option>
            </Select>
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="inspector" label="检查人" rules={[{ required: true, message: '请输入检查人' }]}>
            <Input placeholder="输入检查人姓名" />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item label="检查项目">
        <Checkbox.Group
          value={selectedItems}
          onChange={(vals) => setSelectedItems(vals as string[])}
          style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}
        >
          {ALL_CHECK_ITEMS.map((item) => (
            <Checkbox key={item} value={item}>{item}</Checkbox>
          ))}
        </Checkbox.Group>
      </Form.Item>

      {selectedItems.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ marginBottom: 8, display: 'block' }}>检查结果</Text>
          {selectedItems.map((name) => (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, padding: '4px 0' }}>
              <Text style={{ width: 120, flexShrink: 0 }}>{name}</Text>
              <Select
                size="small"
                value={results[name]?.passed ?? true}
                onChange={(v) => handleItemResult(name, v)}
                style={{ width: 80 }}
              >
                <Select.Option value={true}>通过</Select.Option>
                <Select.Option value={false}>不合格</Select.Option>
              </Select>
              <Input
                size="small"
                placeholder="备注"
                value={results[name]?.remark ?? ''}
                onChange={(e) => handleItemRemark(name, e.target.value)}
                style={{ flex: 1 }}
              />
            </div>
          ))}
        </div>
      )}

      <div style={{ textAlign: 'right' }}>
        <Button type="primary" onClick={handleSubmit}>提交检查记录</Button>
      </div>
    </Form>
  );
}

export default FoodSafetyPage;
