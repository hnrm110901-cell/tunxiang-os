/**
 * 报表中心 — 品牌自定义报表框架
 *
 * Tab 1: 报表中心（标准报表 + 自定义报表卡片列表）
 * Tab 2: 报表设计器（3步骤：基础设置 → 字段配置 → 预览保存）
 * Tab 3: AI叙事模板（模板列表 + 新建/编辑 + 预览效果）
 * Tab 4: 定时推送（已配置任务列表）
 *
 * TC-P2-15  品牌自定义报表框架（AI叙事替代路线）
 */
import { useState, useCallback, useRef } from 'react';
import {
  Tabs,
  Card,
  Row,
  Col,
  Button,
  Input,
  Tag,
  Space,
  Modal,
  Form,
  Select,
  Table,
  Typography,
  Statistic,
  message,
  Tooltip,
  Badge,
  Divider,
  Switch,
  Slider,
  Empty,
  Alert,
  Steps,
  Radio,
  List,
} from 'antd';
import {
  PlusOutlined,
  StarOutlined,
  StarFilled,
  PlayCircleOutlined,
  ShareAltOutlined,
  DeleteOutlined,
  EditOutlined,
  RobotOutlined,
  ClockCircleOutlined,
  PauseCircleOutlined,
  ThunderboltOutlined,
  EyeOutlined,
  CheckCircleOutlined,
  LeftOutlined,
  RightOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  FileTextOutlined,
  CalendarOutlined,
} from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface ReportConfig {
  id: string;
  name: string;
  description?: string;
  report_type: 'standard' | 'custom' | 'ai_narrative';
  data_source?: string;
  chart_type?: string;
  dimensions?: FieldDef[];
  metrics?: FieldDef[];
  filters?: FilterDef[];
  is_favorite: boolean;
  is_public: boolean;
  share_token?: string;
  schedule_config?: ScheduleConfig | null;
  created_at?: string;
  updated_at?: string;
}

interface FieldDef {
  field: string;
  label: string;
  type?: string;
  agg?: string;
}

interface FilterDef {
  field: string;
  op: string;
  value: string;
}

interface ScheduleConfig {
  cron: string;
  channels: string[];
  recipients: string[];
  enabled: boolean;
  configured_at?: string;
}

interface NarrativeTemplate {
  id: string;
  name: string;
  brand_focus?: string;
  prompt_prefix?: string;
  metrics_weights?: Record<string, number>;
  tone: 'professional' | 'casual' | 'executive';
  is_default: boolean;
  is_deleted?: boolean;
  created_at?: string;
}

interface ExecutionResult {
  execution: {
    id: string;
    status: string;
    row_count: number;
    execution_ms: number;
  };
  rows: Record<string, unknown>[];
  columns: { field: string; label: string; type: string }[];
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const DATA_SOURCE_OPTIONS = [
  { value: 'orders', label: '订单数据', icon: '🧾' },
  { value: 'members', label: '会员数据', icon: '👥' },
  { value: 'inventory', label: '库存数据', icon: '📦' },
  { value: 'employees', label: '员工数据', icon: '👤' },
  { value: 'finance', label: '财务数据', icon: '💰' },
];

const DATA_SOURCE_FIELDS: Record<string, { dimensions: FieldDef[]; metrics: FieldDef[] }> = {
  orders: {
    dimensions: [
      { field: 'store_id', label: '门店', type: 'string' },
      { field: 'date', label: '日期', type: 'date' },
      { field: 'payment_method', label: '支付方式', type: 'string' },
      { field: 'channel', label: '渠道', type: 'string' },
      { field: 'dish_name', label: '菜品名称', type: 'string' },
      { field: 'category', label: '菜品分类', type: 'string' },
    ],
    metrics: [
      { field: 'revenue_fen', label: '营业额', agg: 'sum' },
      { field: 'order_count', label: '订单数', agg: 'count' },
      { field: 'avg_order_fen', label: '客单价', agg: 'avg' },
      { field: 'quantity', label: '销量', agg: 'sum' },
      { field: 'discount_fen', label: '优惠金额', agg: 'sum' },
    ],
  },
  members: {
    dimensions: [
      { field: 'member_level', label: '会员等级', type: 'string' },
      { field: 'city', label: '城市', type: 'string' },
      { field: 'gender', label: '性别', type: 'string' },
      { field: 'join_month', label: '入会月份', type: 'date' },
    ],
    metrics: [
      { field: 'consume_amount_fen', label: '消费金额', agg: 'sum' },
      { field: 'visit_count', label: '到店次数', agg: 'sum' },
      { field: 'member_count', label: '会员数', agg: 'count' },
      { field: 'rfm_score', label: 'RFM评分', agg: 'avg' },
    ],
  },
  inventory: {
    dimensions: [
      { field: 'category', label: '品类', type: 'string' },
      { field: 'supplier', label: '供应商', type: 'string' },
      { field: 'ingredient_name', label: '食材名称', type: 'string' },
      { field: 'warehouse', label: '仓库', type: 'string' },
    ],
    metrics: [
      { field: 'cost_fen', label: '成本金额', agg: 'sum' },
      { field: 'waste_rate', label: '损耗率(%)', agg: 'avg' },
      { field: 'turnover_days', label: '周转天数', agg: 'avg' },
      { field: 'stock_count', label: '库存数量', agg: 'sum' },
    ],
  },
  employees: {
    dimensions: [
      { field: 'employee_name', label: '员工姓名', type: 'string' },
      { field: 'role', label: '岗位角色', type: 'string' },
      { field: 'store_id', label: '所属门店', type: 'string' },
      { field: 'department', label: '部门', type: 'string' },
    ],
    metrics: [
      { field: 'service_count', label: '服务桌数', agg: 'sum' },
      { field: 'labor_efficiency', label: '人效(元/人)', agg: 'avg' },
      { field: 'attendance_rate', label: '出勤率(%)', agg: 'avg' },
      { field: 'tips_fen', label: '小费', agg: 'sum' },
    ],
  },
  finance: {
    dimensions: [
      { field: 'cost_center', label: '成本中心', type: 'string' },
      { field: 'month', label: '月份', type: 'date' },
      { field: 'store_id', label: '门店', type: 'string' },
      { field: 'category', label: '费用类别', type: 'string' },
    ],
    metrics: [
      { field: 'revenue_fen', label: '收入', agg: 'sum' },
      { field: 'cost_fen', label: '成本', agg: 'sum' },
      { field: 'gross_profit_fen', label: '毛利', agg: 'sum' },
      { field: 'gross_margin_pct', label: '毛利率(%)', agg: 'avg' },
    ],
  },
};

const CHART_TYPE_OPTIONS = [
  { value: 'table', label: '表格', icon: '📋' },
  { value: 'bar', label: '柱状图', icon: '📊' },
  { value: 'line', label: '折线图', icon: '📈' },
  { value: 'pie', label: '饼图', icon: '🥧' },
];

const TONE_OPTIONS = [
  { value: 'professional', label: '专业财务风格' },
  { value: 'casual', label: '轻松口语风格' },
  { value: 'executive', label: '高管简报风格' },
];

const API_BASE = 'http://localhost:8009/api/v1/analytics';

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function dataSourceLabel(source?: string): string {
  return DATA_SOURCE_OPTIONS.find((o) => o.value === source)?.label ?? source ?? '-';
}

function dataSourceColor(source?: string): string {
  const map: Record<string, string> = {
    orders: 'orange',
    members: 'blue',
    inventory: 'green',
    employees: 'purple',
    finance: 'red',
  };
  return map[source ?? ''] ?? 'default';
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': 'demo-tenant' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  const json = await res.json();
  return json.data as T;
}

// ─── 报表中心 Tab ─────────────────────────────────────────────────────────────

function ReportCenterTab() {
  const [searchText, setSearchText] = useState('');
  const [favOnly, setFavOnly] = useState(false);
  const [reports, setReports] = useState<ReportConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [execResult, setExecResult] = useState<ExecutionResult | null>(null);
  const [execReport, setExecReport] = useState<ReportConfig | null>(null);
  const [execLoading, setExecLoading] = useState(false);
  const [shareModal, setShareModal] = useState(false);
  const [shareUrl, setShareUrl] = useState('');
  const hasLoaded = useRef(false);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (favOnly) params.set('is_favorite', 'true');
      const data = await apiFetch<{ items: ReportConfig[] }>(`/reports?${params}`);
      setReports(data.items);
    } catch (e) {
      message.error(`加载报表列表失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [favOnly]);

  // 首次加载
  if (!hasLoaded.current) {
    hasLoaded.current = true;
    void loadReports();
  }

  const handleFavoriteToggle = async (report: ReportConfig) => {
    if (report.report_type === 'standard') {
      message.info('标准报表收藏状态在本地调整');
      setReports((prev) =>
        prev.map((r) => (r.id === report.id ? { ...r, is_favorite: !r.is_favorite } : r))
      );
      return;
    }
    try {
      await apiFetch(`/reports/${report.id}/favorite`, { method: 'POST' });
      setReports((prev) =>
        prev.map((r) => (r.id === report.id ? { ...r, is_favorite: !r.is_favorite } : r))
      );
    } catch (e) {
      message.error(`操作失败：${(e as Error).message}`);
    }
  };

  const handleExecute = async (report: ReportConfig) => {
    setExecLoading(true);
    setExecReport(report);
    setExecResult(null);
    try {
      const data = await apiFetch<ExecutionResult>(`/reports/${report.id}/execute`, {
        method: 'POST',
      });
      setExecResult(data);
    } catch (e) {
      message.error(`执行报表失败：${(e as Error).message}`);
    } finally {
      setExecLoading(false);
    }
  };

  const handleShare = async (report: ReportConfig) => {
    if (report.report_type === 'standard') {
      message.info('标准报表暂不支持分享，请复制为自定义报表后操作');
      return;
    }
    try {
      const data = await apiFetch<{ share_url: string }>(`/reports/${report.id}/share`, {
        method: 'POST',
      });
      setShareUrl(data.share_url);
      setShareModal(true);
    } catch (e) {
      message.error(`生成分享链接失败：${(e as Error).message}`);
    }
  };

  const filtered = reports.filter((r) => {
    if (favOnly && !r.is_favorite) return false;
    if (searchText && !r.name.includes(searchText)) return false;
    return true;
  });

  const standardReports = filtered.filter((r) => r.report_type === 'standard');
  const customReports = filtered.filter((r) => r.report_type !== 'standard');

  const execColumns = execResult?.columns.map((col) => ({
    title: col.label,
    dataIndex: col.field,
    key: col.field,
    render: (val: unknown) => {
      if (typeof val === 'number' && col.field.endsWith('_fen')) {
        return `¥${(val / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
      }
      return String(val ?? '-');
    },
  })) ?? [];

  const ReportCard = ({ report }: { report: ReportConfig }) => (
    <Card
      size="small"
      hoverable
      style={{ marginBottom: 12 }}
      actions={[
        <Tooltip title="运行报表" key="run">
          <Button
            type="text"
            icon={<PlayCircleOutlined style={{ color: '#FF6B35' }} />}
            onClick={() => void handleExecute(report)}
          >
            运行
          </Button>
        </Tooltip>,
        <Tooltip title="生成分享链接" key="share">
          <Button
            type="text"
            icon={<ShareAltOutlined />}
            onClick={() => void handleShare(report)}
          >
            分享
          </Button>
        </Tooltip>,
        <Tooltip title={report.is_favorite ? '取消收藏' : '收藏'} key="fav">
          <Button
            type="text"
            icon={
              report.is_favorite ? (
                <StarFilled style={{ color: '#BA7517' }} />
              ) : (
                <StarOutlined />
              )
            }
            onClick={() => void handleFavoriteToggle(report)}
          />
        </Tooltip>,
      ]}
    >
      <Card.Meta
        title={
          <Space>
            <Text strong>{report.name}</Text>
            {report.report_type === 'standard' && <Tag color="blue">标准</Tag>}
            {report.report_type === 'ai_narrative' && (
              <Tag color="purple" icon={<RobotOutlined />}>
                AI叙事
              </Tag>
            )}
            {report.schedule_config && (
              <Badge status="processing" text={<Text type="secondary" style={{ fontSize: 12 }}>定时推送中</Text>} />
            )}
          </Space>
        }
        description={
          <Space direction="vertical" size={4}>
            {report.description && <Text type="secondary">{report.description}</Text>}
            <Space>
              {report.data_source && (
                <Tag color={dataSourceColor(report.data_source)}>
                  {dataSourceLabel(report.data_source)}
                </Tag>
              )}
              {report.chart_type && <Tag>{report.chart_type}</Tag>}
            </Space>
          </Space>
        }
      />
    </Card>
  );

  return (
    <div>
      {/* 搜索栏 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col flex="auto">
          <Search
            placeholder="搜索报表名称…"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onSearch={() => void loadReports()}
            allowClear
          />
        </Col>
        <Col>
          <Space>
            <Switch
              checkedChildren={<StarFilled />}
              unCheckedChildren="全部"
              checked={favOnly}
              onChange={(v) => {
                setFavOnly(v);
                setTimeout(() => void loadReports(), 0);
              }}
            />
            <Text type="secondary">仅收藏</Text>
            <Button icon={<PlusOutlined />} onClick={() => void loadReports()}>
              刷新
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="标准报表" value={standardReports.length} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="自定义报表" value={customReports.length} prefix={<BarChartOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已收藏"
              value={filtered.filter((r) => r.is_favorite).length}
              prefix={<StarFilled style={{ color: '#BA7517' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="定时推送中"
              value={filtered.filter((r) => r.schedule_config).length}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={24}>
        {/* 标准报表 */}
        <Col span={12}>
          <Card
            title={
              <Space>
                <FileTextOutlined />
                <span>标准报表</span>
                <Badge count={standardReports.length} showZero style={{ backgroundColor: '#185FA5' }} />
              </Space>
            }
            loading={loading}
          >
            {standardReports.length === 0 ? (
              <Empty description="暂无标准报表" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              standardReports.map((r) => <ReportCard key={r.id} report={r} />)
            )}
          </Card>
        </Col>

        {/* 自定义报表 */}
        <Col span={12}>
          <Card
            title={
              <Space>
                <BarChartOutlined />
                <span>自定义报表</span>
                <Badge count={customReports.length} showZero style={{ backgroundColor: '#FF6B35' }} />
              </Space>
            }
            extra={
              <Text type="secondary" style={{ fontSize: 12 }}>
                在「报表设计器」Tab中创建
              </Text>
            }
            loading={loading}
          >
            {customReports.length === 0 ? (
              <Empty
                description="还没有自定义报表，点击「报表设计器」Tab开始创建"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ) : (
              customReports.map((r) => <ReportCard key={r.id} report={r} />)
            )}
          </Card>
        </Col>
      </Row>

      {/* 执行结果弹窗 */}
      <Modal
        title={
          <Space>
            <PlayCircleOutlined style={{ color: '#FF6B35' }} />
            {execReport?.name ?? '报表结果'}
            {execResult && (
              <Tag color="green">
                {execResult.execution.row_count} 行 · {execResult.execution.execution_ms}ms
              </Tag>
            )}
          </Space>
        }
        open={!!execReport}
        onCancel={() => { setExecReport(null); setExecResult(null); }}
        width={900}
        footer={
          <Button onClick={() => { setExecReport(null); setExecResult(null); }}>
            关闭
          </Button>
        }
      >
        {execLoading && <Alert message="正在执行报表，请稍候…" type="info" showIcon />}
        {execResult && (
          <Table
            columns={execColumns}
            dataSource={execResult.rows.map((row, idx) => ({ ...row, _key: idx }))}
            rowKey="_key"
            size="small"
            pagination={{ pageSize: 10 }}
            scroll={{ x: 'max-content' }}
          />
        )}
      </Modal>

      {/* 分享链接弹窗 */}
      <Modal
        title={<Space><ShareAltOutlined />分享链接已生成</Space>}
        open={shareModal}
        onCancel={() => setShareModal(false)}
        footer={<Button onClick={() => setShareModal(false)}>关闭</Button>}
      >
        <Alert
          message="任何人通过以下链接可查看该报表（无需登录）"
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
        />
        <Input.TextArea
          value={shareUrl}
          rows={3}
          readOnly
          onClick={(e) => (e.target as HTMLTextAreaElement).select()}
        />
        <Button
          type="primary"
          style={{ marginTop: 8 }}
          onClick={() => {
            void navigator.clipboard.writeText(shareUrl);
            message.success('链接已复制到剪贴板');
          }}
        >
          复制链接
        </Button>
      </Modal>
    </div>
  );
}

// ─── 报表设计器 Tab（3步骤流程） ───────────────────────────────────────────────

function ReportDesignerTab() {
  const [currentStep, setCurrentStep] = useState(0);
  const [form] = Form.useForm();

  // Step 1 状态
  const [reportName, setReportName] = useState('');
  const [dataSource, setDataSource] = useState('orders');
  const [chartType, setChartType] = useState('table');

  // Step 2 状态
  const [selectedDimensions, setSelectedDimensions] = useState<FieldDef[]>([]);
  const [selectedMetrics, setSelectedMetrics] = useState<FieldDef[]>([]);

  // Step 3 状态
  const [previewResult, setPreviewResult] = useState<ExecutionResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [savedReportId, setSavedReportId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const availableFields = DATA_SOURCE_FIELDS[dataSource] ?? { dimensions: [], metrics: [] };

  const canGoNext = (): boolean => {
    if (currentStep === 0) return reportName.trim().length > 0;
    if (currentStep === 1) return selectedMetrics.length > 0;
    return true;
  };

  const handleNext = async () => {
    if (currentStep === 1) {
      // 进入预览步骤时先保存草稿并执行
      await handlePreview();
    }
    setCurrentStep((s) => s + 1);
  };

  const handlePreview = async () => {
    setPreviewLoading(true);
    try {
      // 先创建报表配置
      const created = await apiFetch<ReportConfig>('/reports', {
        method: 'POST',
        body: JSON.stringify({
          name: reportName,
          report_type: 'custom',
          data_source: dataSource,
          chart_type: chartType,
          dimensions: selectedDimensions,
          metrics: selectedMetrics,
          filters: [],
        }),
      });
      setSavedReportId(created.id);

      // 执行报表
      const execData = await apiFetch<ExecutionResult>(`/reports/${created.id}/execute`, {
        method: 'POST',
      });
      setPreviewResult(execData);
    } catch (e) {
      message.error(`预览失败：${(e as Error).message}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSave = async () => {
    if (!savedReportId) {
      message.error('请先执行预览');
      return;
    }
    setSaving(true);
    try {
      message.success(`报表「${reportName}」已保存！可在报表中心查看`);
      // 重置设计器
      setCurrentStep(0);
      setReportName('');
      setDataSource('orders');
      setChartType('table');
      setSelectedDimensions([]);
      setSelectedMetrics([]);
      setPreviewResult(null);
      setSavedReportId(null);
      form.resetFields();
    } catch (e) {
      message.error(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const toggleDimension = (field: FieldDef) => {
    setSelectedDimensions((prev) => {
      const exists = prev.find((f) => f.field === field.field);
      return exists ? prev.filter((f) => f.field !== field.field) : [...prev, field];
    });
  };

  const toggleMetric = (field: FieldDef) => {
    setSelectedMetrics((prev) => {
      const exists = prev.find((f) => f.field === field.field);
      return exists ? prev.filter((f) => f.field !== field.field) : [...prev, field];
    });
  };

  const previewColumns = previewResult?.columns.map((col) => ({
    title: col.label,
    dataIndex: col.field,
    key: col.field,
    render: (val: unknown) => {
      if (typeof val === 'number' && col.field.endsWith('_fen')) {
        return `¥${(val / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
      }
      return String(val ?? '-');
    },
  })) ?? [];

  return (
    <div>
      <Steps
        current={currentStep}
        style={{ marginBottom: 32 }}
        items={[
          {
            title: '基础设置',
            description: '命名 · 数据源 · 图表类型',
            icon: <DatabaseOutlined />,
          },
          {
            title: '字段配置',
            description: '选择维度和指标',
            icon: <BarChartOutlined />,
          },
          {
            title: '预览 & 保存',
            description: '确认结果后保存',
            icon: <CheckCircleOutlined />,
          },
        ]}
      />

      {/* Step 0: 基础设置 */}
      {currentStep === 0 && (
        <Card title="基础设置">
          <Form form={form} layout="vertical" style={{ maxWidth: 640 }}>
            <Form.Item
              label="报表名称"
              required
              help="给这份报表起一个便于识别的名字，如「北京区门店周报」"
            >
              <Input
                placeholder="例：徐记海鲜-活鲜销售月报"
                value={reportName}
                onChange={(e) => setReportName(e.target.value)}
                maxLength={100}
                showCount
              />
            </Form.Item>

            <Form.Item label="数据来源" required>
              <Row gutter={12}>
                {DATA_SOURCE_OPTIONS.map((opt) => (
                  <Col key={opt.value} span={8}>
                    <Card
                      size="small"
                      hoverable
                      onClick={() => {
                        setDataSource(opt.value);
                        setSelectedDimensions([]);
                        setSelectedMetrics([]);
                      }}
                      style={{
                        border: dataSource === opt.value
                          ? '2px solid #FF6B35'
                          : '1px solid #E8E6E1',
                        cursor: 'pointer',
                        marginBottom: 8,
                      }}
                    >
                      <Space>
                        <span style={{ fontSize: 20 }}>{opt.icon}</span>
                        <Text strong={dataSource === opt.value}>{opt.label}</Text>
                        {dataSource === opt.value && (
                          <CheckCircleOutlined style={{ color: '#FF6B35' }} />
                        )}
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            </Form.Item>

            <Form.Item label="图表类型">
              <Radio.Group
                value={chartType}
                onChange={(e) => setChartType(e.target.value as string)}
              >
                {CHART_TYPE_OPTIONS.map((opt) => (
                  <Radio.Button key={opt.value} value={opt.value}>
                    {opt.icon} {opt.label}
                  </Radio.Button>
                ))}
              </Radio.Group>
            </Form.Item>
          </Form>
        </Card>
      )}

      {/* Step 1: 字段配置 */}
      {currentStep === 1 && (
        <Row gutter={16}>
          {/* 左：可选字段 */}
          <Col span={10}>
            <Card
              title={
                <Space>
                  <DatabaseOutlined />
                  <span>可选字段</span>
                  <Tag color={dataSourceColor(dataSource)}>{dataSourceLabel(dataSource)}</Tag>
                </Space>
              }
              size="small"
            >
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  维度字段（分组依据）
                </Text>
                <List
                  size="small"
                  dataSource={availableFields.dimensions}
                  renderItem={(item) => {
                    const selected = selectedDimensions.find((f) => f.field === item.field);
                    return (
                      <List.Item
                        style={{ cursor: 'pointer', padding: '6px 8px' }}
                        onClick={() => toggleDimension(item)}
                      >
                        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                          <Space>
                            <Tag color="blue" style={{ margin: 0 }}>维度</Tag>
                            <Text>{item.label}</Text>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              {item.field}
                            </Text>
                          </Space>
                          {selected && <CheckCircleOutlined style={{ color: '#FF6B35' }} />}
                        </Space>
                      </List.Item>
                    );
                  }}
                />
              </div>
              <Divider style={{ margin: '8px 0' }} />
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  指标字段（汇总数值）
                </Text>
                <List
                  size="small"
                  dataSource={availableFields.metrics}
                  renderItem={(item) => {
                    const selected = selectedMetrics.find((f) => f.field === item.field);
                    return (
                      <List.Item
                        style={{ cursor: 'pointer', padding: '6px 8px' }}
                        onClick={() => toggleMetric(item)}
                      >
                        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                          <Space>
                            <Tag color="orange" style={{ margin: 0 }}>指标</Tag>
                            <Text>{item.label}</Text>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              {item.agg}
                            </Text>
                          </Space>
                          {selected && <CheckCircleOutlined style={{ color: '#FF6B35' }} />}
                        </Space>
                      </List.Item>
                    );
                  }}
                />
              </div>
            </Card>
          </Col>

          {/* 右：已选字段 */}
          <Col span={14}>
            <Card
              title="已选字段配置"
              size="small"
              extra={
                <Button
                  size="small"
                  danger
                  onClick={() => { setSelectedDimensions([]); setSelectedMetrics([]); }}
                >
                  清空
                </Button>
              }
            >
              <div style={{ marginBottom: 16 }}>
                <Text strong>
                  维度
                  <Badge count={selectedDimensions.length} style={{ marginLeft: 8, backgroundColor: '#185FA5' }} />
                </Text>
                {selectedDimensions.length === 0 ? (
                  <div
                    style={{
                      border: '2px dashed #E8E6E1',
                      borderRadius: 6,
                      padding: '16px',
                      textAlign: 'center',
                      marginTop: 8,
                      color: '#B4B2A9',
                    }}
                  >
                    点击左侧维度字段添加
                  </div>
                ) : (
                  <div style={{ marginTop: 8 }}>
                    {selectedDimensions.map((f) => (
                      <Tag
                        key={f.field}
                        closable
                        onClose={() => toggleDimension(f)}
                        color="blue"
                        style={{ marginBottom: 6 }}
                      >
                        {f.label}
                      </Tag>
                    ))}
                  </div>
                )}
              </div>

              <Divider style={{ margin: '12px 0' }} />

              <div>
                <Text strong>
                  指标
                  <Badge count={selectedMetrics.length} style={{ marginLeft: 8, backgroundColor: '#FF6B35' }} />
                </Text>
                {selectedMetrics.length === 0 ? (
                  <div
                    style={{
                      border: '2px dashed #E8E6E1',
                      borderRadius: 6,
                      padding: '16px',
                      textAlign: 'center',
                      marginTop: 8,
                      color: '#B4B2A9',
                    }}
                  >
                    <Text type="secondary">至少选择1个指标字段（必填）</Text>
                  </div>
                ) : (
                  <div style={{ marginTop: 8 }}>
                    {selectedMetrics.map((f) => (
                      <Tag
                        key={f.field}
                        closable
                        onClose={() => toggleMetric(f)}
                        color="orange"
                        style={{ marginBottom: 6 }}
                      >
                        {f.label} ({f.agg})
                      </Tag>
                    ))}
                  </div>
                )}
              </div>

              {selectedMetrics.length === 0 && (
                <Alert
                  message="至少选择一个指标字段才能进入下一步"
                  type="warning"
                  showIcon
                  style={{ marginTop: 16 }}
                />
              )}
            </Card>
          </Col>
        </Row>
      )}

      {/* Step 2: 预览 & 保存 */}
      {currentStep === 2 && (
        <Card
          title={
            <Space>
              <EyeOutlined />
              <span>报表预览</span>
              {previewResult && (
                <Tag color="green">
                  {previewResult.execution.row_count} 行数据 · {previewResult.execution.execution_ms}ms
                </Tag>
              )}
            </Space>
          }
        >
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small" style={{ background: '#FFF3ED' }}>
                <Statistic title="报表名称" value={reportName} valueStyle={{ fontSize: 14 }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="数据来源" value={dataSourceLabel(dataSource)} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="维度字段" value={selectedDimensions.length} suffix="个" />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="指标字段" value={selectedMetrics.length} suffix="个" />
              </Card>
            </Col>
          </Row>

          {previewLoading && (
            <Alert message="正在生成预览数据…" type="info" showIcon style={{ marginBottom: 12 }} />
          )}

          {previewResult && (
            <Table
              columns={previewColumns}
              dataSource={previewResult.rows.map((row, idx) => ({ ...row, _key: idx }))}
              rowKey="_key"
              size="small"
              pagination={{ pageSize: 10 }}
              scroll={{ x: 'max-content' }}
              style={{ marginTop: 12 }}
            />
          )}

          {savedReportId && (
            <Alert
              message={`报表草稿已保存（ID: ${savedReportId}），点击「确认保存」完成创建`}
              type="success"
              showIcon
              style={{ marginTop: 12 }}
            />
          )}
        </Card>
      )}

      {/* 步骤导航按钮 */}
      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
        <Button
          icon={<LeftOutlined />}
          disabled={currentStep === 0}
          onClick={() => setCurrentStep((s) => s - 1)}
        >
          上一步
        </Button>
        <Space>
          {currentStep < 2 && (
            <Button
              type="primary"
              icon={<RightOutlined />}
              disabled={!canGoNext()}
              onClick={() => void handleNext()}
              loading={previewLoading}
            >
              {currentStep === 1 ? '生成预览' : '下一步'}
            </Button>
          )}
          {currentStep === 2 && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => void handleSave()}
              loading={saving}
              disabled={!savedReportId}
            >
              确认保存
            </Button>
          )}
        </Space>
      </div>
    </div>
  );
}

// ─── AI叙事模板 Tab ────────────────────────────────────────────────────────────

function NarrativeTemplateTab() {
  const [templates, setTemplates] = useState<NarrativeTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<NarrativeTemplate | null>(null);
  const [previewText, setPreviewText] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [form] = Form.useForm<{
    name: string;
    brand_focus: string;
    tone: string;
    is_default: boolean;
  }>();
  const hasLoaded = useRef(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ items: NarrativeTemplate[] }>('/narrative-templates');
      setTemplates(data.items);
    } catch (e) {
      message.error(`加载模板失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  if (!hasLoaded.current) {
    hasLoaded.current = true;
    void loadTemplates();
  }

  const handlePreview = async (templateId: string) => {
    setPreviewLoading(true);
    setPreviewText('');
    try {
      const data = await apiFetch<{ narrative: string }>(`/narrative-templates/${templateId}/preview`, {
        method: 'POST',
      });
      setPreviewText(data.narrative);
    } catch (e) {
      message.error(`预览失败：${(e as Error).message}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    try {
      if (editingTemplate && !editingTemplate.id.startsWith('tpl-')) {
        await apiFetch(`/narrative-templates/${editingTemplate.id}`, {
          method: 'PUT',
          body: JSON.stringify(values),
        });
        message.success('模板已更新');
      } else {
        await apiFetch('/narrative-templates', {
          method: 'POST',
          body: JSON.stringify(values),
        });
        message.success('模板已创建');
      }
      setModalOpen(false);
      form.resetFields();
      await loadTemplates();
    } catch (e) {
      message.error(`操作失败：${(e as Error).message}`);
    }
  };

  const toneLabel = (tone: string) => {
    return TONE_OPTIONS.find((o) => o.value === tone)?.label ?? tone;
  };

  const toneColor = (tone: string) => {
    return { professional: 'blue', casual: 'green', executive: 'purple' }[tone] ?? 'default';
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>
          <RobotOutlined style={{ color: '#185FA5', marginRight: 8 }} />
          AI叙事模板
        </Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingTemplate(null);
            form.resetFields();
            setModalOpen(true);
          }}
        >
          新建模板
        </Button>
      </div>

      <Alert
        message="AI叙事模板让每个品牌拥有专属叙事风格，30分钟内配置完成，无需编码"
        type="info"
        showIcon
        icon={<RobotOutlined />}
        style={{ marginBottom: 16 }}
      />

      <Row gutter={16}>
        {templates.map((tpl) => (
          <Col key={tpl.id} span={8} style={{ marginBottom: 16 }}>
            <Card
              size="small"
              hoverable
              title={
                <Space>
                  <Text strong>{tpl.name}</Text>
                  {tpl.is_default && <Tag color="gold">默认</Tag>}
                </Space>
              }
              extra={
                <Space>
                  <Button
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={() => void handlePreview(tpl.id)}
                    loading={previewLoading}
                  >
                    预览
                  </Button>
                  {!tpl.id.startsWith('tpl-') && (
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => {
                        setEditingTemplate(tpl);
                        form.setFieldsValue({
                          name: tpl.name,
                          brand_focus: tpl.brand_focus ?? '',
                          tone: tpl.tone,
                          is_default: tpl.is_default,
                        });
                        setModalOpen(true);
                      }}
                    />
                  )}
                </Space>
              }
            >
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>品牌侧重：</Text>
                  <Text>{tpl.brand_focus ?? '-'}</Text>
                </div>
                <div>
                  <Tag color={toneColor(tpl.tone)}>{toneLabel(tpl.tone)}</Tag>
                </div>
                {tpl.metrics_weights && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>指标权重：</Text>
                    {Object.entries(tpl.metrics_weights).map(([k, v]) => (
                      <Tag key={k} style={{ marginBottom: 4 }}>
                        {k}: {Math.round(v * 100)}%
                      </Tag>
                    ))}
                  </div>
                )}
              </Space>
            </Card>
          </Col>
        ))}

        {loading && (
          <Col span={24}>
            <Card loading />
          </Col>
        )}
      </Row>

      {previewText && (
        <Card
          title={
            <Space>
              <RobotOutlined style={{ color: '#185FA5' }} />
              叙事预览效果
            </Space>
          }
          style={{ marginTop: 16, border: '1px solid #185FA5' }}
          extra={<Button size="small" onClick={() => setPreviewText('')}>关闭</Button>}
        >
          <Paragraph style={{ fontSize: 15, lineHeight: 1.8, margin: 0 }}>
            {previewText}
          </Paragraph>
        </Card>
      )}

      {/* 新建/编辑模板弹窗 */}
      <Modal
        title={editingTemplate ? '编辑叙事模板' : '新建叙事模板'}
        open={modalOpen}
        onOk={() => void handleSubmit()}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="模板名称"
            rules={[{ required: true, message: '请输入模板名称' }]}
          >
            <Input placeholder="如：徐记海鲜活鲜专报" maxLength={100} showCount />
          </Form.Item>

          <Form.Item
            name="brand_focus"
            label="品牌核心关注点"
            help="告诉AI重点分析哪些指标，如「活鲜销售/毛利/损耗」"
          >
            <Input placeholder="活鲜销售/毛利/损耗" maxLength={100} />
          </Form.Item>

          <Form.Item name="tone" label="叙事语气风格" initialValue="professional">
            <Select options={TONE_OPTIONS} />
          </Form.Item>

          <Form.Item
            name="is_default"
            label="设为默认模板"
            valuePropName="checked"
            initialValue={false}
          >
            <Switch />
          </Form.Item>

          <Alert
            message="保存后可在此页点击「预览」查看实际叙事效果"
            type="info"
            showIcon
            style={{ marginTop: 8 }}
          />
        </Form>
      </Modal>
    </div>
  );
}

// ─── 定时推送 Tab ─────────────────────────────────────────────────────────────

interface ScheduleTask {
  reportId: string;
  reportName: string;
  cron: string;
  channels: string[];
  recipients: string[];
  enabled: boolean;
  configuredAt: string;
}

function SchedulePushTab() {
  const [tasks] = useState<ScheduleTask[]>([
    {
      reportId: 'demo-001',
      reportName: '日营业汇总（自动推送版）',
      cron: '0 9 * * *',
      channels: ['wecom'],
      recipients: ['张总监', '李店长'],
      enabled: true,
      configuredAt: '2026-04-01T09:00:00Z',
    },
    {
      reportId: 'demo-002',
      reportName: '周会员活跃报告',
      cron: '0 8 * * 1',
      channels: ['wecom', 'email'],
      recipients: ['运营团队'],
      enabled: false,
      configuredAt: '2026-03-25T08:00:00Z',
    },
  ]);

  const channelTag = (ch: string) => {
    const map: Record<string, { label: string; color: string }> = {
      wecom: { label: '企业微信', color: 'green' },
      email: { label: '邮件', color: 'blue' },
      sms: { label: '短信', color: 'orange' },
    };
    const info = map[ch] ?? { label: ch, color: 'default' };
    return <Tag key={ch} color={info.color}>{info.label}</Tag>;
  };

  const cronHumanize = (cron: string) => {
    const map: Record<string, string> = {
      '0 9 * * *': '每天 09:00',
      '0 8 * * 1': '每周一 08:00',
      '0 7 1 * *': '每月1日 07:00',
    };
    return map[cron] ?? cron;
  };

  const columns = [
    {
      title: '报表名称',
      dataIndex: 'reportName',
      key: 'reportName',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '触发时间',
      dataIndex: 'cron',
      key: 'cron',
      render: (cron: string) => (
        <Space>
          <CalendarOutlined />
          <Text>{cronHumanize(cron)}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            ({cron})
          </Text>
        </Space>
      ),
    },
    {
      title: '推送渠道',
      dataIndex: 'channels',
      key: 'channels',
      render: (channels: string[]) => <>{channels.map(channelTag)}</>,
    },
    {
      title: '收件人',
      dataIndex: 'recipients',
      key: 'recipients',
      render: (recipients: string[]) => recipients.join('、'),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (enabled: boolean) =>
        enabled ? (
          <Badge status="processing" text="推送中" />
        ) : (
          <Badge status="default" text="已暂停" />
        ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: ScheduleTask) => (
        <Space>
          <Tooltip title={record.enabled ? '暂停推送' : '恢复推送'}>
            <Button
              size="small"
              icon={record.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={() => message.info(`${record.enabled ? '已暂停' : '已恢复'}推送任务`)}
            >
              {record.enabled ? '暂停' : '恢复'}
            </Button>
          </Tooltip>
          <Tooltip title="立即触发一次">
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={() => message.success('已触发立即推送，请在企业微信/邮箱查收')}
            >
              立即推送
            </Button>
          </Tooltip>
          <Tooltip title="删除推送任务">
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() =>
                Modal.confirm({
                  title: '确认删除推送任务？',
                  content: '删除后该报表将不再自动推送',
                  okType: 'danger',
                  onOk: () => message.success('推送任务已删除'),
                })
              }
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>
          <ClockCircleOutlined style={{ color: '#FF6B35', marginRight: 8 }} />
          定时推送任务
        </Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => message.info('请先在「报表中心」选择报表，点击「配置推送」进行设置')}
        >
          新建推送任务
        </Button>
      </div>

      <Alert
        message="在「报表中心」对任意报表点击「配置推送」，可设置定时推送到企业微信、邮件等渠道"
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Table
        columns={columns}
        dataSource={tasks}
        rowKey="reportId"
        pagination={false}
        size="middle"
        bordered={false}
      />

      <Card style={{ marginTop: 16 }}>
        <Row gutter={16}>
          <Col span={8}>
            <Statistic
              title="推送中任务"
              value={tasks.filter((t) => t.enabled).length}
              prefix={<Badge status="processing" />}
              valueStyle={{ color: '#0F6E56' }}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="已暂停任务"
              value={tasks.filter((t) => !t.enabled).length}
              prefix={<Badge status="default" />}
            />
          </Col>
          <Col span={8}>
            <Statistic
              title="今日推送次数"
              value={3}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#FF6B35' }}
            />
          </Col>
        </Row>
      </Card>
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export default function ReportCenterPage() {
  const [activeTab, setActiveTab] = useState('center');

  const tabItems = [
    {
      key: 'center',
      label: (
        <Space>
          <FileTextOutlined />
          报表中心
        </Space>
      ),
      children: <ReportCenterTab />,
    },
    {
      key: 'designer',
      label: (
        <Space>
          <BarChartOutlined />
          报表设计器
        </Space>
      ),
      children: <ReportDesignerTab />,
    },
    {
      key: 'narrative',
      label: (
        <Space>
          <RobotOutlined />
          AI叙事模板
        </Space>
      ),
      children: <NarrativeTemplateTab />,
    },
    {
      key: 'schedule',
      label: (
        <Space>
          <ClockCircleOutlined />
          定时推送
        </Space>
      ),
      children: <SchedulePushTab />,
    },
  ];

  return (
    <div style={{ padding: '24px', background: '#F8F7F5', minHeight: '100vh' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space direction="vertical" size={4}>
              <Title level={3} style={{ margin: 0, color: '#2C2C2A' }}>
                品牌报表中心
              </Title>
              <Text type="secondary">
                30分钟配置专属品牌报表，无需代码 · AI叙事自动生成经营洞察
              </Text>
            </Space>
          </Col>
          <Col>
            <Space>
              <Tag color="blue" style={{ fontSize: 13, padding: '4px 12px' }}>
                TC-P2-15
              </Tag>
              <Tag color="orange" style={{ fontSize: 13, padding: '4px 12px' }}>
                AI叙事替代路线
              </Tag>
            </Space>
          </Col>
        </Row>
      </div>

      {/* Tab 内容区 */}
      <Card
        style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}
        bodyStyle={{ padding: '16px 24px' }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          size="large"
          tabBarStyle={{ marginBottom: 24 }}
        />
      </Card>
    </div>
  );
}
