/**
 * ExportCenterPage -- 数据导出与报表中心
 * 域F . 系统设置 . 导出中心
 *
 * Tab1: 快速导出 -- 报表类型选择 + 参数配置 + 生成进度
 * Tab2: 导出历史 -- ProTable 展示历史记录 + 下载/重新生成/删除
 * Tab3: 定时任务 -- 计划任务列表 + 新建/启用/禁用
 *
 * API: tx-analytics :8009, try/catch 降级 Mock
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  Modal,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  TimePicker,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CloudDownloadOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  FileExcelOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LoadingOutlined,
  PlusOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

const BASE = 'http://localhost:8009';

// ─── 类型定义 ───

type ReportType =
  | 'daily_revenue'
  | 'monthly_pnl'
  | 'member_data'
  | 'dish_sales'
  | 'inventory_check'
  | 'payroll_summary'
  | 'attendance'
  | 'order_detail';

type ExportFormat = 'csv' | 'excel' | 'pdf';
type ExportStatus = 'generating' | 'completed' | 'failed' | 'expired';
type TaskFrequency = 'daily' | 'weekly' | 'monthly';

interface ReportOption {
  key: ReportType;
  label: string;
  icon: React.ReactNode;
  description: string;
  color: string;
}

interface ExportRecord {
  id: string;
  report_name: string;
  report_type: ReportType;
  store_scope: string;
  date_range: string;
  format: ExportFormat;
  file_size: string;
  created_at: string;
  status: ExportStatus;
}

interface ScheduledTask {
  id: string;
  task_name: string;
  report_type: ReportType;
  frequency: TaskFrequency;
  last_run: string | null;
  next_run: string;
  email: string;
  run_time: string;
  enabled: boolean;
}

// ─── 常量 ───

const REPORT_OPTIONS: ReportOption[] = [
  { key: 'daily_revenue', label: '日营业报表', icon: <FileTextOutlined />, description: '每日营业额、订单量、客单价', color: '#FF6B35' },
  { key: 'monthly_pnl', label: '月度损益', icon: <FileExcelOutlined />, description: '月度收入/支出/利润汇总', color: '#1677ff' },
  { key: 'member_data', label: '会员数据', icon: <FileTextOutlined />, description: '会员画像、消费偏好、RFM 分层', color: '#52c41a' },
  { key: 'dish_sales', label: '菜品销量', icon: <FileExcelOutlined />, description: '菜品销量排行、毛利分析', color: '#722ed1' },
  { key: 'inventory_check', label: '库存盘点', icon: <FileTextOutlined />, description: '库存现状、临期预警、差异', color: '#fa8c16' },
  { key: 'payroll_summary', label: '薪资汇总', icon: <FileExcelOutlined />, description: '薪资明细、社保公积金', color: '#eb2f96' },
  { key: 'attendance', label: '考勤记录', icon: <FileTextOutlined />, description: '出勤统计、迟到早退、加班', color: '#13c2c2' },
  { key: 'order_detail', label: '订单明细', icon: <FileExcelOutlined />, description: '全渠道订单逐笔明细', color: '#f5222d' },
];

const REPORT_TYPE_MAP: Record<ReportType, string> = {
  daily_revenue: '日营业报表',
  monthly_pnl: '月度损益',
  member_data: '会员数据',
  dish_sales: '菜品销量',
  inventory_check: '库存盘点',
  payroll_summary: '薪资汇总',
  attendance: '考勤记录',
  order_detail: '订单明细',
};

const FORMAT_ICON: Record<ExportFormat, React.ReactNode> = {
  csv: <FileTextOutlined />,
  excel: <FileExcelOutlined />,
  pdf: <FilePdfOutlined />,
};

// 门店选项由 useStoreOptions hook 从 API 加载
interface StoreOption { value: string; label: string; }

function useStoreOptions(): StoreOption[] {
  const [stores, setStores] = useState<StoreOption[]>([]);
  useEffect(() => {
    fetch(`${BASE}/api/v1/system/tenants/stores`, {
      headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '' },
    })
      .then(r => r.json())
      .then(json => {
        if (json.ok) {
          setStores((json.data?.items ?? []).map((s: { id: string; name: string }) => ({ value: s.id, label: s.name })));
        }
      })
      .catch(() => { /* API 不可用时保持空数组 */ });
  }, []);
  return stores;
}

// Mock 数据已移除，由 API 提供数据

// ─── Tab1 快速导出 ───

function QuickExportTab() {
  const [selectedType, setSelectedType] = useState<ReportType | null>(null);
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [storeScope, setStoreScope] = useState<'all' | 'selected'>('all');
  const [selectedStores, setSelectedStores] = useState<string[]>([]);
  const [format, setFormat] = useState<ExportFormat>('excel');
  const storeOptions = useStoreOptions();
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!selectedType) {
      message.warning('请先选择报表类型');
      return;
    }
    if (!dateRange) {
      message.warning('请选择时间范围');
      return;
    }

    setGenerating(true);
    setProgress(0);

    try {
      const resp = await fetch(`${BASE}/api/v1/system/exports`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
        },
        body: JSON.stringify({
          type: selectedType,
          params: {
            date_from: dateRange[0].format('YYYY-MM-DD'),
            date_to: dateRange[1].format('YYYY-MM-DD'),
            store_scope: storeScope === 'all' ? 'all' : selectedStores,
            format,
          },
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.ok) {
        setProgress(100);
        setGenerating(false);
        message.success('报表生成任务已提交，请前往"导出历史"查看进度');
        return;
      }
      throw new Error('API returned error');
    } catch {
      // 模拟进度条（API 不可用时）
      let current = 0;
      timerRef.current = setInterval(() => {
        current += Math.random() * 15 + 5;
        if (current >= 100) {
          current = 100;
          if (timerRef.current) clearInterval(timerRef.current);
          timerRef.current = null;
          setProgress(100);
          setGenerating(false);
          message.warning(`${REPORT_TYPE_MAP[selectedType]} 任务已提交，API 暂不可用`);
          return;
        }
        setProgress(Math.round(current));
      }, 300);
    }
  }, [selectedType, dateRange, storeScope, selectedStores, format]);

  const selected = REPORT_OPTIONS.find((r) => r.key === selectedType);

  return (
    <div>
      {/* 报表类型选择 - Card Grid */}
      <Title level={5} style={{ marginBottom: 16 }}>选择报表类型</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {REPORT_OPTIONS.map((opt) => (
          <Col xs={12} sm={8} md={6} key={opt.key}>
            <Card
              hoverable
              size="small"
              onClick={() => { setSelectedType(opt.key); setGenerating(false); setProgress(0); }}
              style={{
                borderColor: selectedType === opt.key ? '#FF6B35' : undefined,
                borderWidth: selectedType === opt.key ? 2 : 1,
                cursor: 'pointer',
              }}
              styles={{
                body: { padding: 16, textAlign: 'center' },
              }}
            >
              <div style={{ fontSize: 28, color: opt.color, marginBottom: 8 }}>{opt.icon}</div>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>{opt.label}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{opt.description}</Text>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 参数配置 */}
      {selectedType && (
        <Card
          title={<Space><ThunderboltOutlined style={{ color: '#FF6B35' }} />参数配置 — {selected?.label}</Space>}
          style={{ marginBottom: 24 }}
        >
          <Form layout="vertical">
            <Row gutter={24}>
              <Col xs={24} md={8}>
                <Form.Item label="时间范围" required>
                  <RangePicker
                    style={{ width: '100%' }}
                    value={dateRange}
                    onChange={(v) => setDateRange(v as [Dayjs, Dayjs] | null)}
                    presets={[
                      { label: '今天', value: [dayjs(), dayjs()] },
                      { label: '最近7天', value: [dayjs().subtract(7, 'day'), dayjs()] },
                      { label: '最近30天', value: [dayjs().subtract(30, 'day'), dayjs()] },
                      { label: '本月', value: [dayjs().startOf('month'), dayjs()] },
                      { label: '上月', value: [dayjs().subtract(1, 'month').startOf('month'), dayjs().subtract(1, 'month').endOf('month')] },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="门店范围">
                  <Radio.Group value={storeScope} onChange={(e) => setStoreScope(e.target.value)}>
                    <Radio value="all">全部门店</Radio>
                    <Radio value="selected">指定门店</Radio>
                  </Radio.Group>
                  {storeScope === 'selected' && (
                    <Select
                      mode="multiple"
                      placeholder="选择门店"
                      style={{ width: '100%', marginTop: 8 }}
                      options={storeOptions}
                      value={selectedStores}
                      onChange={setSelectedStores}
                    />
                  )}
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="导出格式">
                  <Radio.Group value={format} onChange={(e) => setFormat(e.target.value)}>
                    <Radio.Button value="csv"><FileTextOutlined /> CSV</Radio.Button>
                    <Radio.Button value="excel"><FileExcelOutlined /> Excel</Radio.Button>
                    <Radio.Button value="pdf"><FilePdfOutlined /> PDF</Radio.Button>
                  </Radio.Group>
                </Form.Item>
              </Col>
            </Row>

            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Button
                type="primary"
                size="large"
                icon={<CloudDownloadOutlined />}
                loading={generating && progress < 100}
                onClick={handleGenerate}
                disabled={generating && progress < 100}
                style={{ minWidth: 200 }}
              >
                {generating && progress < 100 ? '生成中...' : '生成报表'}
              </Button>
            </div>

            {/* 进度条 */}
            {(generating || progress === 100) && (
              <div style={{ marginTop: 24, maxWidth: 480, margin: '24px auto 0' }}>
                <Progress
                  percent={progress}
                  status={progress === 100 ? 'success' : 'active'}
                  strokeColor={progress === 100 ? '#52c41a' : '#FF6B35'}
                  format={(p) => (p === 100 ? '完成' : `${p}%`)}
                />
                {progress === 100 && (
                  <div style={{ textAlign: 'center', marginTop: 12 }}>
                    <Tag color="success" icon={<CheckCircleOutlined />}>报表已生成，可在"导出历史"中下载</Tag>
                  </div>
                )}
              </div>
            )}
          </Form>
        </Card>
      )}
    </div>
  );
}

// ─── Tab2 导出历史 ───

function ExportHistoryTab() {
  const actionRef = useRef<ActionType>();
  const [records, setRecords] = useState<ExportRecord[]>([]);

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    const tenantId = localStorage.getItem('tx_tenant_id') ?? '';
    try {
      const resp = await fetch(`${BASE}/api/v1/system/exports`, {
        headers: { 'X-Tenant-ID': tenantId },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.ok) {
        setRecords(data.data.items ?? data.data ?? []);
        return;
      }
    } catch { /* API 不可用 */ }
    setRecords([]);
  };

  const handleDownload = (record: ExportRecord) => {
    // 通过 window.open 触发下载链接
    const tenantId = localStorage.getItem('tx_tenant_id') ?? '';
    const url = `${BASE}/api/v1/system/exports/${record.id}/download`;
    // 带 tenant_id 参数用于下载鉴权
    window.open(`${url}?tenant_id=${tenantId}`, '_blank');
    message.info(`正在下载：${record.report_name}`);
  };

  const handleRegenerate = async (record: ExportRecord) => {
    try {
      const resp = await fetch(`${BASE}/api/v1/system/exports`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
        },
        body: JSON.stringify({ type: record.report_type, params: { date_range: record.date_range, format: record.format } }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    } catch { /* API 不可用，乐观更新 */ }
    setRecords((prev) =>
      prev.map((r) => (r.id === record.id ? { ...r, status: 'generating' as ExportStatus } : r)),
    );
    message.info(`已重新提交生成：${record.report_name}`);
  };

  const handleDelete = (record: ExportRecord) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除「${record.report_name}」吗？`,
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => {
        setRecords((prev) => prev.filter((r) => r.id !== record.id));
        message.success('已删除');
      },
    });
  };

  const statusConfig: Record<ExportStatus, { color: string; icon: React.ReactNode; text: string }> = {
    generating: { color: 'processing', icon: <SyncOutlined spin />, text: '生成中' },
    completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
    failed: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
    expired: { color: 'default', icon: <ClockCircleOutlined />, text: '已过期' },
  };

  const columns: ProColumns<ExportRecord>[] = [
    {
      title: '报表名称',
      dataIndex: 'report_name',
      ellipsis: true,
      width: 200,
    },
    {
      title: '类型',
      dataIndex: 'report_type',
      width: 110,
      valueEnum: Object.fromEntries(
        Object.entries(REPORT_TYPE_MAP).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, r) => <Tag>{REPORT_TYPE_MAP[r.report_type]}</Tag>,
    },
    {
      title: '门店',
      dataIndex: 'store_scope',
      width: 120,
      ellipsis: true,
    },
    {
      title: '时间范围',
      dataIndex: 'date_range',
      width: 200,
      search: false,
    },
    {
      title: '格式',
      dataIndex: 'format',
      width: 80,
      render: (_, r) => (
        <Space size={4}>
          {FORMAT_ICON[r.format]}
          <span>{r.format.toUpperCase()}</span>
        </Space>
      ),
      valueEnum: { csv: { text: 'CSV' }, excel: { text: 'Excel' }, pdf: { text: 'PDF' } },
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      width: 100,
      search: false,
    },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      width: 170,
      valueType: 'dateTime',
      search: false,
      sorter: (a, b) => dayjs(a.created_at).unix() - dayjs(b.created_at).unix(),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, r) => {
        const cfg = statusConfig[r.status];
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.text}</Tag>;
      },
      valueEnum: {
        generating: { text: '生成中', status: 'Processing' },
        completed: { text: '已完成', status: 'Success' },
        failed: { text: '失败', status: 'Error' },
        expired: { text: '已过期', status: 'Default' },
      },
    },
    {
      title: '操作',
      width: 200,
      search: false,
      render: (_, r) => (
        <Space>
          {r.status === 'completed' && (
            <Button type="link" size="small" icon={<CloudDownloadOutlined />} onClick={() => handleDownload(r)}>
              下载
            </Button>
          )}
          {(r.status === 'failed' || r.status === 'expired') && (
            <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => handleRegenerate(r)}>
              重新生成
            </Button>
          )}
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Tag color="warning" icon={<ExclamationCircleOutlined />}>
          导出文件保留 7 天，过期后将自动清理，请及时下载
        </Tag>
      </div>
      <ProTable<ExportRecord>
        actionRef={actionRef}
        columns={columns}
        dataSource={records}
        rowKey="id"
        search={{ labelWidth: 80 }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        dateFormatter="string"
        headerTitle="导出记录"
        toolBarRender={() => [
          <Button key="refresh" icon={<ReloadOutlined />} onClick={loadHistory}>
            刷新
          </Button>,
        ]}
      />
    </div>
  );
}

// ─── Tab3 定时任务 ───

function ScheduledTaskTab() {
  const actionRef = useRef<ActionType>();
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    loadTasks();
  }, []);

  const loadTasks = async () => {
    try {
      const resp = await fetch(`${BASE}/api/v1/system/exports/schedules`, {
        headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.ok) {
        setTasks(data.data.items ?? data.data ?? []);
        return;
      }
    } catch { /* API 不可用 */ }
    setTasks([]);
  };

  const handleToggle = (taskId: string, enabled: boolean) => {
    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, enabled } : t)),
    );
    message.success(enabled ? '已启用' : '已禁用');
  };

  const handleDelete = (task: ScheduledTask) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除定时任务「${task.task_name}」吗？`,
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => {
        setTasks((prev) => prev.filter((t) => t.id !== task.id));
        message.success('已删除');
      },
    });
  };

  const handleCreate = () => {
    form.validateFields().then((values) => {
      const newTask: ScheduledTask = {
        id: `task_${String(Date.now()).slice(-6)}`,
        task_name: values.task_name,
        report_type: values.report_type,
        frequency: values.frequency,
        last_run: null,
        next_run: dayjs().add(1, 'day').format(`YYYY-MM-DD ${values.run_time.format('HH:mm')}`),
        email: values.email,
        run_time: values.run_time.format('HH:mm'),
        enabled: true,
      };
      setTasks((prev) => [newTask, ...prev]);
      setModalOpen(false);
      form.resetFields();
      message.success('定时任务已创建');
    });
  };

  const freqLabel: Record<TaskFrequency, string> = {
    daily: '每日',
    weekly: '每周',
    monthly: '每月',
  };

  const freqColor: Record<TaskFrequency, string> = {
    daily: 'blue',
    weekly: 'purple',
    monthly: 'cyan',
  };

  const columns: ProColumns<ScheduledTask>[] = [
    {
      title: '任务名',
      dataIndex: 'task_name',
      width: 180,
    },
    {
      title: '报表类型',
      dataIndex: 'report_type',
      width: 120,
      render: (_, r) => <Tag>{REPORT_TYPE_MAP[r.report_type]}</Tag>,
    },
    {
      title: '频率',
      dataIndex: 'frequency',
      width: 80,
      render: (_, r) => <Tag color={freqColor[r.frequency]}>{freqLabel[r.frequency]}</Tag>,
    },
    {
      title: '执行时间',
      dataIndex: 'run_time',
      width: 90,
      search: false,
    },
    {
      title: '最近执行',
      dataIndex: 'last_run',
      width: 160,
      search: false,
      render: (_, r) => r.last_run ? <Text>{r.last_run}</Text> : <Text type="secondary">尚未执行</Text>,
    },
    {
      title: '下次执行',
      dataIndex: 'next_run',
      width: 160,
      search: false,
    },
    {
      title: '接收邮箱',
      dataIndex: 'email',
      width: 180,
      ellipsis: true,
      search: false,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 80,
      search: false,
      render: (_, r) => (
        <Switch
          checked={r.enabled}
          checkedChildren="启用"
          unCheckedChildren="禁用"
          onChange={(checked) => handleToggle(r.id, checked)}
        />
      ),
    },
    {
      title: '操作',
      width: 80,
      search: false,
      render: (_, r) => (
        <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r)}>
          删除
        </Button>
      ),
    },
  ];

  return (
    <div>
      <ProTable<ScheduledTask>
        actionRef={actionRef}
        columns={columns}
        dataSource={tasks}
        rowKey="id"
        search={false}
        pagination={false}
        headerTitle="定时导出任务"
        toolBarRender={() => [
          <Button key="add" type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
            新建定时任务
          </Button>,
          <Button key="refresh" icon={<ReloadOutlined />} onClick={loadTasks}>
            刷新
          </Button>,
        ]}
      />

      {/* 新建定时任务 Modal */}
      <Modal
        title="新建定时导出任务"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        okText="创建"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="task_name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="例：每日营业日报" />
          </Form.Item>
          <Form.Item name="report_type" label="报表类型" rules={[{ required: true, message: '请选择报表类型' }]}>
            <Select
              placeholder="选择报表类型"
              options={REPORT_OPTIONS.map((o) => ({ value: o.key, label: o.label }))}
            />
          </Form.Item>
          <Form.Item name="frequency" label="执行频率" rules={[{ required: true, message: '请选择频率' }]}>
            <Radio.Group>
              <Radio.Button value="daily">每日</Radio.Button>
              <Radio.Button value="weekly">每周</Radio.Button>
              <Radio.Button value="monthly">每月</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="run_time" label="执行时间" rules={[{ required: true, message: '请选择时间' }]}>
            <TimePicker format="HH:mm" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="email"
            label="接收邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效的邮箱地址' },
            ]}
          >
            <Input placeholder="报表生成后发送到此邮箱" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ─── 主页面 ───

export function ExportCenterPage() {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>
          <CloudDownloadOutlined style={{ color: '#FF6B35', marginRight: 8 }} />
          数据导出中心
        </Title>
        <Text type="secondary">统一管理报表导出、历史记录与定时任务</Text>
      </div>

      <Tabs
        defaultActiveKey="quick"
        items={[
          {
            key: 'quick',
            label: <span><ThunderboltOutlined /> 快速导出</span>,
            children: <QuickExportTab />,
          },
          {
            key: 'history',
            label: <span><HistoryOutlined /> 导出历史</span>,
            children: <ExportHistoryTab />,
          },
          {
            key: 'schedule',
            label: <span><ScheduleOutlined /> 定时任务</span>,
            children: <ScheduledTaskTab />,
          },
        ]}
      />
    </div>
  );
}
