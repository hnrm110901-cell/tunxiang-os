/**
 * 薪资管理页 — Finance Payroll
 * 路由: /finance/payroll
 * 域E: 员工薪资单管理、薪资方案配置、发薪历史
 *
 * 金额单位: 分(fen)，显示时 ÷100
 * API: http://localhost:8007  (tx-finance :8007)
 * 降级: API 失败时使用内嵌 Mock 数据
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  Descriptions,
  Divider,
  Drawer,
  message,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  ModalForm,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components';
import {
  CheckCircleOutlined,
  DollarOutlined,
  TeamOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { txFetch, txFetchData } from '../../api';

const { Title, Text } = Typography;

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface PayrollSummary {
  month: string;
  headcount: number;
  gross_total: number;
  paid_total: number;
  pending_approval: number;
}

interface PayrollRecord {
  id: string;
  store_id: string;
  store_name: string;
  employee_id: string;
  employee_name: string;
  position: string;
  position_label: string;
  period: string;
  base_salary: number;
  overtime_pay: number;
  commission: number;
  performance: number;
  deductions: number;
  gross_pay: number;
  net_pay: number;
  status: 'draft' | 'approved' | 'paid' | 'voided';
  approved_by: string | null;
  approved_at: string | null;
  paid_at: string | null;
  created_at: string;
  line_items?: LineItem[];
}

interface LineItem {
  id: string;
  label: string;
  amount: number;
  type: 'income' | 'deduction';
}

interface PayrollConfig {
  id: string;
  position: string;
  position_label: string;
  salary_type: 'monthly' | 'hourly' | 'piecework';
  base_salary: number;
  hourly_rate: number;
  commission_type: 'none' | 'revenue_pct' | 'profit_pct';
  commission_rate: number;
  performance_cap: number;
  overtime_rate: number;
  updated_at: string;
}

interface HistoryMonth {
  month: string;
  headcount: number;
  gross_pay: number;
  net_pay: number;
  status: string;
}

// ─── 空数据初始值（API 失败时 fallback）────────────────────────────────────────

const EMPTY_SUMMARY: PayrollSummary = {
  month: '',
  headcount: 0,
  gross_total: 0,
  paid_total: 0,
  pending_approval: 0,
};

// ─── 辅助函数 ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number) => (fen / 100).toFixed(2);
const fenToWan = (fen: number) => (fen / 1_000_000).toFixed(2);

const STATUS_CONFIG: Record<
  string,
  { text: string; color: string; badgeStatus: 'default' | 'processing' | 'success' | 'error' | 'warning' }
> = {
  draft:    { text: '草稿',   color: 'default',  badgeStatus: 'default' },
  approved: { text: '已审批', color: '#185FA5',  badgeStatus: 'processing' },
  paid:     { text: '已发放', color: '#0F6E56',  badgeStatus: 'success' },
  voided:   { text: '已作废', color: '#A32D2D',  badgeStatus: 'error' },
};

const SALARY_TYPE_LABEL: Record<string, string> = {
  monthly:   '月薪制',
  hourly:    '时薪制',
  piecework: '计件制',
};

const COMMISSION_TYPE_LABEL: Record<string, string> = {
  none:        '无提成',
  revenue_pct: '营业额百分比',
  profit_pct:  '利润百分比',
};

// ─── SVG 折线图（纯 SVG，不引入外部图表库）──────────────────────────────────────

interface LineChartProps {
  data: HistoryMonth[];
}

function PayrollLineChart({ data }: LineChartProps) {
  const W = 560;
  const H = 140;
  const PAD = { top: 16, right: 24, bottom: 32, left: 56 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const maxVal = Math.max(...data.map((d) => d.gross_pay), 1);
  const minVal = 0;

  const toX = (i: number) => PAD.left + (i / (data.length - 1)) * chartW;
  const toY = (v: number) =>
    PAD.top + chartH - ((v - minVal) / (maxVal - minVal)) * chartH;

  const grossPoints = data.map((d, i) => `${toX(i)},${toY(d.gross_pay)}`).join(' ');
  const netPoints   = data.map((d, i) => `${toX(i)},${toY(d.net_pay)}`).join(' ');

  const yTicks = [0, maxVal / 2, maxVal].map((v) => ({
    v,
    y: toY(v),
    label: `${fenToWan(v)}万`,
  }));

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      {/* y 轴网格线 & 刻度 */}
      {yTicks.map(({ v, y, label }) => (
        <g key={v}>
          <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y}
            stroke="#E8E6E1" strokeWidth={1} strokeDasharray="4 3" />
          <text x={PAD.left - 6} y={y + 4} fontSize={10} fill="#B4B2A9" textAnchor="end">
            {label}
          </text>
        </g>
      ))}

      {/* 应发折线 */}
      <polyline
        points={grossPoints}
        fill="none"
        stroke="#FF6B35"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* 实发折线 */}
      <polyline
        points={netPoints}
        fill="none"
        stroke="#185FA5"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* 数据点 */}
      {data.map((d, i) => (
        <g key={d.month}>
          <circle cx={toX(i)} cy={toY(d.gross_pay)} r={4} fill="#FF6B35" />
          <circle cx={toX(i)} cy={toY(d.net_pay)}   r={3} fill="#185FA5" />
          {/* x 轴月份标签 */}
          <text x={toX(i)} y={H - 6} fontSize={10} fill="#5F5E5A" textAnchor="middle">
            {d.month.slice(5)}月
          </text>
        </g>
      ))}

      {/* 图例 */}
      <circle cx={PAD.left + 8} cy={10} r={4} fill="#FF6B35" />
      <text x={PAD.left + 16} y={14} fontSize={10} fill="#5F5E5A">应发</text>
      <circle cx={PAD.left + 52} cy={10} r={4} fill="#185FA5" />
      <text x={PAD.left + 60} y={14} fontSize={10} fill="#5F5E5A">实发</text>
    </svg>
  );
}

// ─── Tab1: 薪资单列表 ──────────────────────────────────────────────────────────

interface Tab1Props {
  actionRef: React.MutableRefObject<ActionType | undefined>;
}

function RecordsTab({ actionRef }: Tab1Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailRecord, setDetailRecord] = useState<PayrollRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);

  const handleViewDetail = useCallback(async (record: PayrollRecord) => {
    setDetailLoading(true);
    setDrawerOpen(true);
    try {
      const data = await txFetchData<PayrollRecord>(`/api/v1/org/payroll/records/${record.id}`);
      setDetailRecord(data);
    } catch (err) {
      console.error('[PayrollPage] fetchDetail error', err);
      setDetailRecord(record);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleApprove = useCallback(async (record: PayrollRecord) => {
    try {
      await txFetchData(`/api/v1/org/payroll/records/${record.id}/approve`, { method: 'POST' });
      message.success('审批通过');
      actionRef.current?.reload();
    } catch (err) {
      console.error('[PayrollPage] approve error', err);
      message.error('审批请求失败，请重试');
    }
  }, [actionRef]);

  const handleMarkPaid = useCallback(async (record: PayrollRecord) => {
    try {
      await txFetchData(`/api/v1/org/payroll/records/${record.id}/mark-paid`, { method: 'PATCH' });
      message.success('已标记为发放');
      actionRef.current?.reload();
    } catch (err) {
      console.error('[PayrollPage] markPaid error', err);
      message.error('请求失败，请重试');
    }
  }, [actionRef]);

  const handleBatchCalculate = useCallback(async () => {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    setBatchLoading(true);
    try {
      await txFetchData('/api/v1/org/payroll/batch-calculate', {
        method: 'POST',
        body: JSON.stringify({ year, month }),
      });
      message.success(`${year}年${month}月薪资批量计算已完成`);
      actionRef.current?.reload();
    } catch (err) {
      console.error('[PayrollPage] batchCalculate error', err);
      message.error('批量计算失败，请重试');
    } finally {
      setBatchLoading(false);
    }
  }, [actionRef]);

  const columns: ProColumns<PayrollRecord>[] = [
    { title: '员工姓名', dataIndex: 'employee_name', width: 90 },
    { title: '岗位', dataIndex: 'position_label', width: 80, search: false },
    { title: '周期', dataIndex: 'period', width: 90 },
    {
      title: '底薪',
      dataIndex: 'base_salary',
      width: 100,
      search: false,
      render: (_, r) => `¥${fenToYuan(r.base_salary)}`,
    },
    {
      title: '加班费',
      dataIndex: 'overtime_pay',
      width: 90,
      search: false,
      render: (_, r) => `¥${fenToYuan(r.overtime_pay)}`,
    },
    {
      title: '提成',
      dataIndex: 'commission',
      width: 90,
      search: false,
      render: (_, r) => `¥${fenToYuan(r.commission)}`,
    },
    {
      title: '绩效',
      dataIndex: 'performance',
      width: 90,
      search: false,
      render: (_, r) => `¥${fenToYuan(r.performance)}`,
    },
    {
      title: '扣款',
      dataIndex: 'deductions',
      width: 80,
      search: false,
      render: (_, r) => (
        <Text type="danger">-¥{fenToYuan(r.deductions)}</Text>
      ),
    },
    {
      title: '应发',
      dataIndex: 'gross_pay',
      width: 100,
      search: false,
      render: (_, r) => (
        <Text strong>¥{fenToYuan(r.gross_pay)}</Text>
      ),
    },
    {
      title: '实发',
      dataIndex: 'net_pay',
      width: 100,
      search: false,
      render: (_, r) => (
        <Text strong style={{ color: '#0F6E56' }}>¥{fenToYuan(r.net_pay)}</Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      valueType: 'select',
      valueEnum: {
        draft:    { text: '草稿' },
        approved: { text: '已审批' },
        paid:     { text: '已发放' },
        voided:   { text: '已作废' },
      },
      render: (_, r) => {
        const cfg = STATUS_CONFIG[r.status] ?? STATUS_CONFIG.draft;
        return (
          <Badge
            status={cfg.badgeStatus}
            text={<span style={{ color: cfg.color === 'default' ? undefined : cfg.color }}>{cfg.text}</span>}
          />
        );
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 180,
      render: (_, record) => [
        <a key="view" onClick={() => handleViewDetail(record)}>详情</a>,
        record.status === 'draft' && (
          <Popconfirm
            key="approve"
            title="确认审批通过此薪资单？"
            onConfirm={() => handleApprove(record)}
            okText="确认"
            cancelText="取消"
          >
            <a style={{ color: '#185FA5' }}>审批</a>
          </Popconfirm>
        ),
        record.status === 'approved' && (
          <a key="paid" style={{ color: '#0F6E56' }} onClick={() => handleMarkPaid(record)}>
            标记已发
          </a>
        ),
      ].filter(Boolean),
    },
  ];

  return (
    <>
      <ProTable<PayrollRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          try {
            const now = new Date();
            const year = now.getFullYear();
            const month = now.getMonth() + 1;
            const qs = new URLSearchParams({
              page: String(params.current ?? 1),
              size: String(params.pageSize ?? 20),
              year: String(year),
              month: String(month),
              ...(params.status ? { status: params.status } : {}),
              ...(params.period ? { month: params.period } : {}),
            });
            const body = await txFetchData<{ items: PayrollRecord[]; total: number }>(
              `/api/v1/org/payroll/records?${qs}`,
            );
            return { data: body.items, total: body.total, success: true };
          } catch (err) {
            console.error('[PayrollPage] list records error', err);
            return { data: [], total: 0, success: true };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        scroll={{ x: 1200 }}
        toolBarRender={() => [
          <Button
            key="batch-calc"
            type="primary"
            loading={batchLoading}
            onClick={handleBatchCalculate}
          >
            批量计算本月薪资
          </Button>,
          <Button key="export" type="default">导出</Button>,
        ]}
      />

      {/* 薪资单详情 Drawer */}
      <Drawer
        title={detailRecord ? `薪资单详情 — ${detailRecord.employee_name}` : '薪资单详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setDetailRecord(null); }}
        width={480}
        loading={detailLoading}
      >
        {detailRecord && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="员工">{detailRecord.employee_name}</Descriptions.Item>
              <Descriptions.Item label="岗位">{detailRecord.position_label}</Descriptions.Item>
              <Descriptions.Item label="门店">{detailRecord.store_name}</Descriptions.Item>
              <Descriptions.Item label="周期">{detailRecord.period}</Descriptions.Item>
              <Descriptions.Item label="应发" span={2}>
                <Text strong style={{ fontSize: 16 }}>¥{fenToYuan(detailRecord.gross_pay)}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="实发" span={2}>
                <Text strong style={{ fontSize: 16, color: '#0F6E56' }}>
                  ¥{fenToYuan(detailRecord.net_pay)}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="状态" span={2}>
                <Badge
                  status={STATUS_CONFIG[detailRecord.status]?.badgeStatus ?? 'default'}
                  text={STATUS_CONFIG[detailRecord.status]?.text ?? detailRecord.status}
                />
              </Descriptions.Item>
            </Descriptions>

            <Divider orientation="left" plain style={{ marginTop: 16 }}>明细行</Divider>
            {(detailRecord.line_items ?? []).map((li) => (
              <Row key={li.id} justify="space-between" style={{ padding: '6px 0', borderBottom: '1px solid #F0EDE6' }}>
                <Col>
                  <Tag color={li.type === 'income' ? 'green' : 'red'}>
                    {li.type === 'income' ? '收入' : '扣款'}
                  </Tag>
                  {li.label}
                </Col>
                <Col>
                  <Text type={li.type === 'deduction' ? 'danger' : undefined}>
                    {li.type === 'deduction' ? '-' : '+'}¥{fenToYuan(li.amount)}
                  </Text>
                </Col>
              </Row>
            ))}
          </>
        )}
      </Drawer>
    </>
  );
}

// ─── Tab2: 薪资方案配置 ────────────────────────────────────────────────────────

function ConfigTab() {
  const [configs, setConfigs] = useState<PayrollConfig[]>([]);
  const [editTarget, setEditTarget] = useState<PayrollConfig | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const loadConfigs = useCallback(async () => {
    try {
      const body = await txFetchData<{ items: PayrollConfig[] }>('/api/v1/org/payroll/configs');
      setConfigs(body.items);
    } catch (err) {
      console.error('[PayrollPage] load configs error', err);
    }
  }, []);

  useEffect(() => { loadConfigs(); }, [loadConfigs]);

  const handleEdit = (cfg: PayrollConfig) => {
    setEditTarget(cfg);
    setModalOpen(true);
  };

  const handleSave = async (values: Record<string, unknown>) => {
    try {
      await txFetchData('/api/v1/org/payroll/configs', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('方案已保存');
      loadConfigs();
      return true;
    } catch (err) {
      console.error('[PayrollPage] save config error', err);
      message.error('保存请求失败');
      return false;
    }
  };


  return (
    <>
      <Row gutter={[16, 16]}>
        {configs.map((cfg) => (
          <Col xs={24} sm={12} lg={6} key={cfg.id}>
            <Card
              title={cfg.position_label}
              extra={<a onClick={() => handleEdit(cfg)}>编辑</a>}
              size="small"
              style={{ height: '100%' }}
            >
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Row justify="space-between">
                  <Text type="secondary">薪资类型</Text>
                  <Tag>{SALARY_TYPE_LABEL[cfg.salary_type] ?? cfg.salary_type}</Tag>
                </Row>
                {cfg.salary_type === 'monthly' && (
                  <Row justify="space-between">
                    <Text type="secondary">底薪</Text>
                    <Text strong>¥{fenToYuan(cfg.base_salary)}</Text>
                  </Row>
                )}
                {cfg.salary_type === 'hourly' && (
                  <Row justify="space-between">
                    <Text type="secondary">时薪</Text>
                    <Text strong>¥{fenToYuan(cfg.hourly_rate)}/h</Text>
                  </Row>
                )}
                <Row justify="space-between">
                  <Text type="secondary">提成类型</Text>
                  <Text>{COMMISSION_TYPE_LABEL[cfg.commission_type] ?? cfg.commission_type}</Text>
                </Row>
                {cfg.commission_type !== 'none' && (
                  <Row justify="space-between">
                    <Text type="secondary">提成比例</Text>
                    <Text>{cfg.commission_rate}%</Text>
                  </Row>
                )}
                <Row justify="space-between">
                  <Text type="secondary">绩效上限</Text>
                  <Text>¥{fenToYuan(cfg.performance_cap)}</Text>
                </Row>
                <Row justify="space-between">
                  <Text type="secondary">加班倍率</Text>
                  <Text>{(cfg.overtime_rate / 100).toFixed(1)}倍</Text>
                </Row>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <ModalForm
        title={`编辑薪资方案 — ${editTarget?.position_label ?? ''}`}
        open={modalOpen}
        onOpenChange={(v) => { if (!v) { setModalOpen(false); setEditTarget(null); } }}
        initialValues={editTarget ?? undefined}
        onFinish={handleSave}
        modalProps={{ destroyOnClose: true }}
      >
        <ProFormText name="position" label="岗位代码" rules={[{ required: true }]} />
        <ProFormText name="position_label" label="岗位名称" rules={[{ required: true }]} />
        <ProFormSelect
          name="salary_type"
          label="薪资类型"
          options={[
            { label: '月薪制', value: 'monthly' },
            { label: '时薪制', value: 'hourly' },
            { label: '计件制', value: 'piecework' },
          ]}
          rules={[{ required: true }]}
        />
        <ProFormDigit name="base_salary" label="底薪（分）" min={0} fieldProps={{ precision: 0 }} />
        <ProFormDigit name="hourly_rate" label="时薪（分）" min={0} fieldProps={{ precision: 0 }} />
        <ProFormSelect
          name="commission_type"
          label="提成类型"
          options={[
            { label: '无提成', value: 'none' },
            { label: '营业额百分比', value: 'revenue_pct' },
            { label: '利润百分比', value: 'profit_pct' },
          ]}
        />
        <ProFormDigit name="commission_rate" label="提成比例（%）" min={0} max={100} />
        <ProFormDigit name="performance_cap" label="绩效上限（分）" min={0} fieldProps={{ precision: 0 }} />
        <ProFormDigit name="overtime_rate" label="加班倍率（×100，150=1.5倍）" min={100} max={300} />
      </ModalForm>
    </>
  );
}

// ─── Tab3: 发薪历史 ────────────────────────────────────────────────────────────

function HistoryTab() {
  const [history, setHistory] = useState<HistoryMonth[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const body = await txFetchData<{ items: HistoryMonth[] }>('/api/v1/org/payroll/history');
        setHistory(body.items);
      } catch (err) {
        console.error('[PayrollPage] load history error', err);
      }
    })();
  }, []);

  const STATUS_LABELS: Record<string, { label: string; color: string }> = {
    settled:     { label: '已结算', color: 'green' },
    in_progress: { label: '进行中', color: 'blue' },
    pending:     { label: '待处理', color: 'orange' },
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 折线图 */}
      <Card title="近6月应发/实发走势" size="small">
        <PayrollLineChart data={history} />
        <div style={{ textAlign: 'center', marginTop: 4 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>单位：万元</Text>
        </div>
      </Card>

      {/* 月度卡片 */}
      <Row gutter={[12, 12]}>
        {[...history].reverse().map((h) => {
          const stCfg = STATUS_LABELS[h.status] ?? { label: h.status, color: 'default' };
          return (
            <Col xs={24} sm={12} lg={8} key={h.month}>
              <Card
                size="small"
                title={
                  <Space>
                    <Text strong>{h.month}</Text>
                    <Tag color={stCfg.color}>{stCfg.label}</Tag>
                  </Space>
                }
              >
                <Row gutter={8}>
                  <Col span={8}>
                    <Statistic title="人数" value={h.headcount} suffix="人" valueStyle={{ fontSize: 18 }} />
                  </Col>
                  <Col span={8}>
                    <Statistic
                      title="应发"
                      value={fenToWan(h.gross_pay)}
                      suffix="万"
                      valueStyle={{ fontSize: 18, color: '#FF6B35' }}
                      precision={2}
                    />
                  </Col>
                  <Col span={8}>
                    <Statistic
                      title="实发"
                      value={fenToWan(h.net_pay)}
                      suffix="万"
                      valueStyle={{ fontSize: 18, color: '#0F6E56' }}
                      precision={2}
                    />
                  </Col>
                </Row>
              </Card>
            </Col>
          );
        })}
      </Row>
    </Space>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function PayrollPage() {
  const actionRef = useRef<ActionType>();
  const [summary, setSummary] = useState<PayrollSummary>(EMPTY_SUMMARY);
  const [summaryLoading, setSummaryLoading] = useState(false);

  useEffect(() => {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1;
    setSummaryLoading(true);
    txFetchData<PayrollSummary>(
      `/api/v1/org/payroll/summary?year=${year}&month=${month}`,
    )
      .then(setSummary)
      .catch((err: unknown) => console.error('[PayrollPage] load summary error', err))
      .finally(() => setSummaryLoading(false));
  }, []);

  const summaryCards = [
    {
      title: '本月员工总数',
      value: summary.headcount,
      suffix: '人',
      icon: <TeamOutlined style={{ color: '#FF6B35', fontSize: 22 }} />,
      color: '#FF6B35',
    },
    {
      title: '应发合计',
      value: fenToWan(summary.gross_total),
      suffix: '万',
      icon: <DollarOutlined style={{ color: '#0F6E56', fontSize: 22 }} />,
      color: '#0F6E56',
    },
    {
      title: '已发合计',
      value: fenToWan(summary.paid_total),
      suffix: '万',
      icon: <CheckCircleOutlined style={{ color: '#185FA5', fontSize: 22 }} />,
      color: '#185FA5',
    },
    {
      title: '待审批数量',
      value: summary.pending_approval,
      suffix: '单',
      icon: <ClockCircleOutlined style={{ color: '#BA7517', fontSize: 22 }} />,
      color: '#BA7517',
    },
  ];

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#FF6B35',
          colorSuccess: '#0F6E56',
          colorWarning: '#BA7517',
          colorError: '#A32D2D',
          colorInfo: '#185FA5',
          colorTextBase: '#2C2C2A',
          borderRadius: 6,
          fontSize: 14,
        },
        components: {
          Table: { headerBg: '#F8F7F5' },
        },
      }}
    >
      <div style={{ padding: '0 0 24px' }}>
        <Title level={4} style={{ marginBottom: 16 }}>薪资管理</Title>

        {/* 顶部统计卡 */}
        <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
          {summaryCards.map((card) => (
            <Col xs={24} sm={12} lg={6} key={card.title}>
              <Card size="small" style={{ borderTop: `3px solid ${card.color}` }}>
                <Row align="middle" justify="space-between">
                  <Col>
                    <div style={{ color: '#5F5E5A', fontSize: 12, marginBottom: 4 }}>{card.title}</div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: card.color }}>
                      {card.value}
                      <span style={{ fontSize: 13, fontWeight: 400, marginLeft: 2 }}>{card.suffix}</span>
                    </div>
                  </Col>
                  <Col>{card.icon}</Col>
                </Row>
              </Card>
            </Col>
          ))}
        </Row>

        {/* Tab 内容 */}
        <Card bodyStyle={{ padding: '0 16px 16px' }}>
          <Tabs
            defaultActiveKey="records"
            items={[
              {
                key: 'records',
                label: '薪资单列表',
                children: <RecordsTab actionRef={actionRef} />,
              },
              {
                key: 'configs',
                label: '薪资方案配置',
                children: <ConfigTab />,
              },
              {
                key: 'history',
                label: '发薪历史',
                children: <HistoryTab />,
              },
            ]}
          />
        </Card>
      </div>
    </ConfigProvider>
  );
}
