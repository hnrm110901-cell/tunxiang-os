/**
 * 计件提成3.0 管理中心
 * 路由: /org/piecework
 * 域F · 组织人事 · 计件提成
 *
 * Tab 1 — 首页仪表盘：今日集团汇总 + TOP5员工 + 按门店柱状
 * Tab 2 — 区域管理：计件区域 CRUD
 * Tab 3 — 绩效设置：方案列表 + 两步新建（基本信息 + 明细配置）
 * Tab 4 — 绩效统计：门店/员工/品项三维度统计 + CSV导出
 * Tab 5 — 系统设置：日报推送时间 / 推送方式
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  DatePicker,
  Divider,
  Form,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Steps,
  Table,
  Tabs,
  Tag,
  TimePicker,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  TeamOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

// ─── 品牌主题 ──────────────────────────────────────────────────────────────
const txAdminTheme = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Table: { headerBg: '#F8F7F5' },
  },
};

// ─── API base ──────────────────────────────────────────────────────────────
const TENANT_ID = localStorage.getItem('tenantId') ?? 'demo-tenant';
const BASE = '/api/v1/org/piecework';

async function apiFetch<T = unknown>(
  path: string,
  opts?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
      ...(opts?.headers ?? {}),
    },
    ...opts,
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message ?? '请求失败');
  return json.data as T;
}

// ─── 类型定义 ─────────────────────────────────────────────────────────────
interface PieceworkZone {
  id: string;
  name: string;
  store_id: string | null;
  description: string | null;
  is_active: boolean;
}

interface PieceworkScheme {
  id: string;
  name: string;
  zone_id: string | null;
  zone_name: string | null;
  calc_type: 'by_dish' | 'by_method';
  applicable_role: 'chef' | 'waiter' | 'runner';
  effective_date: string | null;
  is_active: boolean;
}

interface SchemeItem {
  dish_name: string | null;
  unit_fee_fen: number;
  min_qty: number;
}

interface StoreStatRow {
  employee_id: string;
  employee_name?: string;
  total_fee_fen: number;
  total_quantity: number;
  record_count: number;
}

interface EmployeeStatRow {
  dish_name: string;
  total_quantity: number;
  unit_fee_fen: number;
  total_fee_fen: number;
}

interface DishStatRow {
  dish_name: string;
  total_quantity: number;
  total_fee_fen: number;
  rank: number;
}

interface DailyReport {
  date: string;
  total_fee_fen: number;
  total_quantity: number;
  participant_count: number;
  top5: Array<{
    rank: number;
    employee_name?: string;
    employee_id?: string;
    total_fee_fen: number;
    quantity: number;
  }>;
}

// ─── 辅助工具 ─────────────────────────────────────────────────────────────
/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

const ROLE_MAP: Record<string, string> = {
  chef: '厨师',
  waiter: '服务员',
  runner: '传菜员',
};

const CALC_MAP: Record<string, string> = {
  by_dish: '按品项',
  by_method: '按做法',
};

// ─────────────────────────────────────────────────────────────────────────────
// Tab 1: 首页仪表盘
// ─────────────────────────────────────────────────────────────────────────────
function DashboardTab() {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [storeStats, setStoreStats] = useState<StoreStatRow[]>([]);
  const today = dayjs().format('YYYY-MM-DD');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // 使用 demo store_id 加载当日数据
      const [rep, storeStat] = await Promise.all([
        apiFetch<DailyReport>(`/daily-report?store_id=00000000-0000-0000-0000-000000000099&date=${today}`),
        apiFetch<{ items: StoreStatRow[] }>(`/stats/store?store_id=00000000-0000-0000-0000-000000000099&start_date=${today}&end_date=${today}`),
      ]);
      setReport(rep);
      setStoreStats(storeStat.items);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => { loadData(); }, [loadData]);

  const maxFee = storeStats.length > 0 ? Math.max(...storeStats.map((s) => s.total_fee_fen)) : 1;

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 集团今日汇总 */}
        <Row gutter={16}>
          <Col span={8}>
            <Card bordered={false} style={{ background: '#FFF3ED' }}>
              <Statistic
                title="今日计件总金额"
                value={report ? (report.total_fee_fen / 100).toFixed(2) : '--'}
                prefix="¥"
                valueStyle={{ color: '#FF6B35', fontWeight: 700, fontSize: 28 }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card bordered={false} style={{ background: '#F0F9F6' }}>
              <Statistic
                title="今日计件总件数"
                value={report?.total_quantity ?? '--'}
                suffix="件"
                valueStyle={{ color: '#0F6E56', fontWeight: 700, fontSize: 28 }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card bordered={false} style={{ background: '#EEF4FC' }}>
              <Statistic
                title="参与员工人数"
                value={report?.participant_count ?? '--'}
                suffix="人"
                prefix={<TeamOutlined />}
                valueStyle={{ color: '#185FA5', fontWeight: 700, fontSize: 28 }}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={16}>
          {/* TOP5员工排行 */}
          <Col span={10}>
            <Card
              title={
                <Space>
                  <TrophyOutlined style={{ color: '#FF6B35' }} />
                  <span>今日 TOP5 员工</span>
                </Space>
              }
              bordered={false}
            >
              {report?.top5?.map((emp) => (
                <div
                  key={emp.employee_id ?? emp.rank}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '8px 0',
                    borderBottom: '1px solid #F0EDE6',
                  }}
                >
                  <Space>
                    <Tag
                      color={emp.rank === 1 ? '#FF6B35' : emp.rank <= 3 ? '#BA7517' : '#d9d9d9'}
                      style={{ fontWeight: 700 }}
                    >
                      {emp.rank}
                    </Tag>
                    <Text>{emp.employee_name ?? emp.employee_id ?? `员工${emp.rank}`}</Text>
                  </Space>
                  <Space direction="vertical" align="end" size={0}>
                    <Text strong style={{ color: '#FF6B35' }}>
                      {fenToYuan(emp.total_fee_fen)}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {emp.quantity} 件
                    </Text>
                  </Space>
                </div>
              ))}
              {(!report?.top5 || report.top5.length === 0) && (
                <Text type="secondary">暂无数据</Text>
              )}
            </Card>
          </Col>

          {/* 按门店汇总柱状（div模拟，不引入图表库） */}
          <Col span={14}>
            <Card
              title="各员工计件金额汇总"
              bordered={false}
              extra={
                <Button size="small" icon={<ReloadOutlined />} onClick={loadData}>
                  刷新
                </Button>
              }
            >
              {storeStats.map((row) => (
                <div key={row.employee_id} style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <Text>{row.employee_name ?? row.employee_id.slice(0, 8)}</Text>
                    <Text strong>{fenToYuan(row.total_fee_fen)}</Text>
                  </div>
                  <div
                    style={{
                      background: '#F0EDE6',
                      borderRadius: 4,
                      height: 12,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${(row.total_fee_fen / maxFee) * 100}%`,
                        height: '100%',
                        background: 'linear-gradient(90deg, #FF6B35, #FF8555)',
                        borderRadius: 4,
                        transition: 'width 0.5s ease',
                      }}
                    />
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {row.total_quantity} 件 · {row.record_count} 笔
                  </Text>
                </div>
              ))}
              {storeStats.length === 0 && <Text type="secondary">暂无数据</Text>}
            </Card>
          </Col>
        </Row>
      </Space>
    </Spin>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 2: 区域管理
// ─────────────────────────────────────────────────────────────────────────────
function ZonesTab() {
  const actionRef = useRef<ActionType>();
  const [editTarget, setEditTarget] = useState<PieceworkZone | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [form] = Form.useForm();

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认停用该区域？',
      content: '停用后该区域不会显示在新建方案中。',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await apiFetch(`/zones/${id}`, { method: 'DELETE' });
          message.success('已停用');
          actionRef.current?.reload();
        } catch (e: unknown) {
          message.error(e instanceof Error ? e.message : '操作失败');
        }
      },
    });
  };

  const handleEdit = (zone: PieceworkZone) => {
    setEditTarget(zone);
    form.setFieldsValue({ name: zone.name, description: zone.description });
    setEditOpen(true);
  };

  const handleEditSave = async () => {
    const values = await form.validateFields();
    try {
      await apiFetch(`/zones/${editTarget!.id}`, {
        method: 'PUT',
        body: JSON.stringify(values),
      });
      message.success('更新成功');
      setEditOpen(false);
      actionRef.current?.reload();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '更新失败');
    }
  };

  const columns: ProColumns<PieceworkZone>[] = [
    { title: '区域名称', dataIndex: 'name', width: 160 },
    {
      title: '绑定门店',
      dataIndex: 'store_id',
      render: (v) => v ? <Text code>{String(v).slice(0, 8)}…</Text> : <Tag color="blue">集团通用</Tag>,
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v) => <Badge status={v ? 'success' : 'default'} text={v ? '启用' : '停用'} />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, record) => [
        <a key="edit" onClick={() => handleEdit(record)}>
          <EditOutlined /> 编辑
        </a>,
        <a
          key="del"
          style={{ color: '#A32D2D', marginLeft: 8 }}
          onClick={() => handleDelete(record.id)}
        >
          <DeleteOutlined /> 停用
        </a>,
      ],
    },
  ];

  return (
    <>
      <ProTable<PieceworkZone>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => {
          const data = await apiFetch<{ items: PieceworkZone[]; total: number }>('/zones');
          return { data: data.items, total: data.total, success: true };
        }}
        search={false}
        toolBarRender={() => [
          <ModalForm<{ name: string; description?: string }>
            key="create"
            title="新建计件区域"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                新建区域
              </Button>
            }
            onFinish={async (values) => {
              await apiFetch('/zones', {
                method: 'POST',
                body: JSON.stringify(values),
              });
              message.success('创建成功');
              actionRef.current?.reload();
              return true;
            }}
          >
            <ProFormText
              name="name"
              label="区域名称"
              placeholder="如：热菜区 / 凉菜区 / 传菜组"
              rules={[{ required: true, message: '请输入区域名称' }]}
            />
            <ProFormText name="store_id" label="绑定门店ID" placeholder="留空=集团通用" />
            <ProFormTextArea name="description" label="描述" placeholder="可选" />
          </ModalForm>,
        ]}
        pagination={{ pageSize: 20 }}
      />

      {/* 编辑弹窗 */}
      <Modal
        title="编辑区域"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleEditSave}
        okText="保存"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="区域名称" rules={[{ required: true }]}>
            <input className="ant-input" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <textarea className="ant-input" rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 3: 绩效设置（方案列表 + 两步新建）
// ─────────────────────────────────────────────────────────────────────────────
function SchemesTab() {
  const actionRef = useRef<ActionType>();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState(0);
  const [baseInfo, setBaseInfo] = useState<Record<string, unknown>>({});
  const [items, setItems] = useState<SchemeItem[]>([
    { dish_name: '', unit_fee_fen: 100, min_qty: 1 },
  ]);
  const [baseForm] = Form.useForm();

  const handleWizardNext = async () => {
    const vals = await baseForm.validateFields();
    setBaseInfo(vals);
    setWizardStep(1);
  };

  const handleWizardSubmit = async () => {
    const validItems = items.filter((i) => i.dish_name?.trim());
    if (validItems.length === 0) {
      message.warning('请至少添加一条明细');
      return;
    }
    try {
      await apiFetch('/schemes', {
        method: 'POST',
        body: JSON.stringify({ ...baseInfo, items: validItems }),
      });
      message.success('方案创建成功');
      setWizardOpen(false);
      setWizardStep(0);
      setItems([{ dish_name: '', unit_fee_fen: 100, min_qty: 1 }]);
      baseForm.resetFields();
      actionRef.current?.reload();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '创建失败');
    }
  };

  const addItem = () => {
    setItems((prev) => [...prev, { dish_name: '', unit_fee_fen: 100, min_qty: 1 }]);
  };

  const removeItem = (idx: number) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateItem = <K extends keyof SchemeItem>(
    idx: number,
    key: K,
    val: SchemeItem[K],
  ) => {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [key]: val } : it)));
  };

  const columns: ProColumns<PieceworkScheme>[] = [
    { title: '方案名称', dataIndex: 'name', width: 200 },
    {
      title: '计算方式',
      dataIndex: 'calc_type',
      width: 100,
      render: (v) => <Tag color="blue">{CALC_MAP[String(v)] ?? String(v)}</Tag>,
    },
    {
      title: '适用岗位',
      dataIndex: 'applicable_role',
      width: 100,
      render: (v) => <Tag color="orange">{ROLE_MAP[String(v)] ?? String(v)}</Tag>,
    },
    { title: '所属区域', dataIndex: 'zone_name', render: (v) => v ?? '-' },
    { title: '生效日期', dataIndex: 'effective_date', valueType: 'date' },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v) => <Badge status={v ? 'success' : 'default'} text={v ? '启用' : '停用'} />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 80,
      render: (_, record) => [
        <a key="detail" onClick={() => message.info(`方案ID: ${record.id}`)}>
          详情
        </a>,
      ],
    },
  ];

  return (
    <>
      <ProTable<PieceworkScheme>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => {
          const data = await apiFetch<{ items: PieceworkScheme[]; total: number }>('/schemes');
          return { data: data.items, total: data.total, success: true };
        }}
        search={false}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setWizardOpen(true)}
          >
            新建方案
          </Button>,
        ]}
        pagination={{ pageSize: 20 }}
      />

      {/* 两步新建方案 Modal */}
      <Modal
        title="新建计件方案"
        open={wizardOpen}
        width={640}
        onCancel={() => {
          setWizardOpen(false);
          setWizardStep(0);
        }}
        footer={
          <Space>
            {wizardStep === 1 && (
              <Button onClick={() => setWizardStep(0)}>上一步</Button>
            )}
            <Button onClick={() => { setWizardOpen(false); setWizardStep(0); }}>
              取消
            </Button>
            {wizardStep === 0 ? (
              <Button type="primary" onClick={handleWizardNext}>
                下一步：配置明细
              </Button>
            ) : (
              <Button type="primary" onClick={handleWizardSubmit}>
                完成创建
              </Button>
            )}
          </Space>
        }
      >
        <Steps
          current={wizardStep}
          size="small"
          style={{ marginBottom: 24 }}
          items={[{ title: '基本信息' }, { title: '明细配置' }]}
        />

        {/* Step 1: 基本信息 */}
        {wizardStep === 0 && (
          <Form form={baseForm} layout="vertical">
            <Form.Item name="name" label="方案名称" rules={[{ required: true }]}>
              <input className="ant-input" placeholder="如：热菜厨师计件方案" style={{ width: '100%', padding: '4px 11px', border: '1px solid #d9d9d9', borderRadius: 6 }} />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="calc_type" label="计算方式" rules={[{ required: true }]}>
                  <Select placeholder="请选择">
                    <Select.Option value="by_dish">按品项计件</Select.Option>
                    <Select.Option value="by_method">按做法计件</Select.Option>
                  </Select>
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="applicable_role" label="适用岗位" rules={[{ required: true }]}>
                  <Select placeholder="请选择">
                    <Select.Option value="chef">厨师</Select.Option>
                    <Select.Option value="waiter">服务员</Select.Option>
                    <Select.Option value="runner">传菜员</Select.Option>
                  </Select>
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="effective_date" label="生效日期">
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Form>
        )}

        {/* Step 2: 明细配置 */}
        {wizardStep === 1 && (
          <div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 120px 80px 40px',
                gap: 8,
                marginBottom: 8,
                fontWeight: 600,
                color: '#5F5E5A',
              }}
            >
              <span>品项/做法名称</span>
              <span>单价（分）</span>
              <span>最低件数</span>
              <span />
            </div>
            {items.map((item, idx) => (
              <div
                key={idx}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 120px 80px 40px',
                  gap: 8,
                  marginBottom: 8,
                  alignItems: 'center',
                }}
              >
                <input
                  className="ant-input"
                  value={item.dish_name ?? ''}
                  onChange={(e) => updateItem(idx, 'dish_name', e.target.value)}
                  placeholder="品项名称"
                  style={{ padding: '4px 11px', border: '1px solid #d9d9d9', borderRadius: 6 }}
                />
                <InputNumber
                  min={1}
                  value={item.unit_fee_fen}
                  onChange={(v) => updateItem(idx, 'unit_fee_fen', v ?? 1)}
                  style={{ width: '100%' }}
                />
                <InputNumber
                  min={1}
                  value={item.min_qty}
                  onChange={(v) => updateItem(idx, 'min_qty', v ?? 1)}
                  style={{ width: '100%' }}
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeItem(idx)}
                  disabled={items.length === 1}
                />
              </div>
            ))}
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={addItem}
              style={{ width: '100%', marginTop: 8 }}
            >
              添加明细
            </Button>
          </div>
        )}
      </Modal>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 4: 绩效统计
// ─────────────────────────────────────────────────────────────────────────────
function StatsTab() {
  const [subTab, setSubTab] = useState('store');
  const [dateRange, setDateRange] = useState<[string, string]>([
    dayjs().subtract(7, 'day').format('YYYY-MM-DD'),
    dayjs().format('YYYY-MM-DD'),
  ]);
  const [storeId] = useState('00000000-0000-0000-0000-000000000099');
  const [employeeId] = useState('00000000-0000-0000-0000-000000000001');
  const [storeData, setStoreData] = useState<StoreStatRow[]>([]);
  const [empData, setEmpData] = useState<EmployeeStatRow[]>([]);
  const [dishData, setDishData] = useState<DishStatRow[]>([]);
  const [loading, setLoading] = useState(false);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      if (subTab === 'store') {
        const d = await apiFetch<{ items: StoreStatRow[] }>(
          `/stats/store?store_id=${storeId}&start_date=${dateRange[0]}&end_date=${dateRange[1]}`,
        );
        setStoreData(d.items);
      } else if (subTab === 'employee') {
        const d = await apiFetch<{ items: EmployeeStatRow[] }>(
          `/stats/employee?employee_id=${employeeId}&start_date=${dateRange[0]}&end_date=${dateRange[1]}`,
        );
        setEmpData(d.items);
      } else {
        const d = await apiFetch<{ items: DishStatRow[] }>(
          `/stats/by-dish?store_id=${storeId}&date=${dateRange[1]}`,
        );
        setDishData(d.items);
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '加载统计失败');
    } finally {
      setLoading(false);
    }
  }, [subTab, dateRange, storeId, employeeId]);

  useEffect(() => { loadStats(); }, [loadStats]);

  // CSV 导出
  const exportCSV = (data: Record<string, unknown>[], filename: string) => {
    if (data.length === 0) { message.warning('无数据可导出'); return; }
    const headers = Object.keys(data[0]);
    const rows = data.map((r) => headers.map((h) => r[h] ?? '').join(','));
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename}_${dateRange[0]}_${dateRange[1]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const storeColumns: ProColumns<StoreStatRow>[] = [
    { title: '员工ID', dataIndex: 'employee_id', ellipsis: true },
    { title: '计件金额', dataIndex: 'total_fee_fen', render: (v) => fenToYuan(Number(v)), sorter: (a, b) => a.total_fee_fen - b.total_fee_fen },
    { title: '计件件数', dataIndex: 'total_quantity', sorter: (a, b) => a.total_quantity - b.total_quantity },
    { title: '记录数', dataIndex: 'record_count' },
  ];

  const empColumns: ProColumns<EmployeeStatRow>[] = [
    { title: '品项名称', dataIndex: 'dish_name' },
    { title: '件数', dataIndex: 'total_quantity', sorter: (a, b) => a.total_quantity - b.total_quantity },
    { title: '单价', dataIndex: 'unit_fee_fen', render: (v) => fenToYuan(Number(v)) },
    { title: '合计', dataIndex: 'total_fee_fen', render: (v) => fenToYuan(Number(v)), sorter: (a, b) => a.total_fee_fen - b.total_fee_fen },
  ];

  const dishColumns: ProColumns<DishStatRow>[] = [
    { title: '排名', dataIndex: 'rank', width: 60 },
    { title: '品项名称', dataIndex: 'dish_name' },
    { title: '计件件数', dataIndex: 'total_quantity', sorter: (a, b) => a.total_quantity - b.total_quantity },
    { title: '计件总额', dataIndex: 'total_fee_fen', render: (v) => fenToYuan(Number(v)) },
  ];

  return (
    <Spin spinning={loading}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Row justify="space-between" align="middle">
          <Col>
            <DatePicker.RangePicker
              value={[dayjs(dateRange[0]), dayjs(dateRange[1])]}
              onChange={(_, s) => setDateRange(s as [string, string])}
            />
          </Col>
          <Col>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => {
                const data =
                  subTab === 'store' ? storeData :
                  subTab === 'employee' ? empData :
                  dishData;
                exportCSV(data as Record<string, unknown>[], `计件统计_${subTab}`);
              }}
            >
              导出 CSV
            </Button>
          </Col>
        </Row>

        <Tabs
          activeKey={subTab}
          onChange={setSubTab}
          items={[
            {
              key: 'store',
              label: '门店维度',
              children: (
                <ProTable<StoreStatRow>
                  rowKey="employee_id"
                  columns={storeColumns}
                  dataSource={storeData}
                  search={false}
                  toolBarRender={false}
                  pagination={{ pageSize: 20 }}
                />
              ),
            },
            {
              key: 'employee',
              label: '员工维度',
              children: (
                <ProTable<EmployeeStatRow>
                  rowKey="dish_name"
                  columns={empColumns}
                  dataSource={empData}
                  search={false}
                  toolBarRender={false}
                  pagination={{ pageSize: 20 }}
                />
              ),
            },
            {
              key: 'dish',
              label: '品项维度',
              children: (
                <ProTable<DishStatRow>
                  rowKey="dish_name"
                  columns={dishColumns}
                  dataSource={dishData}
                  search={false}
                  toolBarRender={false}
                  pagination={{ pageSize: 20 }}
                />
              ),
            },
          ]}
        />
      </Space>
    </Spin>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 5: 系统设置
// ─────────────────────────────────────────────────────────────────────────────
function SystemSettingsTab() {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      // 系统设置暂存本地
      localStorage.setItem('piecework_settings', JSON.stringify(values));
      message.success('设置已保存');
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    const saved = localStorage.getItem('piecework_settings');
    if (saved) {
      try {
        const v = JSON.parse(saved);
        if (v.push_time) v.push_time = dayjs(v.push_time, 'HH:mm');
        form.setFieldsValue(v);
      } catch {
        // 忽略解析错误
      }
    }
  }, [form]);

  return (
    <Card style={{ maxWidth: 480 }}>
      <Title level={5}>日报推送设置</Title>
      <Divider />
      <Form form={form} layout="vertical">
        <Form.Item name="push_time" label="日报推送时间" rules={[{ required: true }]}>
          <TimePicker format="HH:mm" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="push_method" label="推送方式" rules={[{ required: true }]}>
          <Select mode="multiple" placeholder="请选择推送渠道">
            <Select.Option value="wecom">企业微信</Select.Option>
            <Select.Option value="sms">短信</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item>
          <Button
            type="primary"
            onClick={handleSave}
            loading={saving}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            保存设置
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 主页面：PieceworkPage
// ─────────────────────────────────────────────────────────────────────────────
export function PieceworkPage() {
  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ padding: '24px', minWidth: 1280 }}>
        <Title level={3} style={{ marginBottom: 0 }}>
          计件提成 3.0
        </Title>
        <Text type="secondary">厨师 / 传菜员按品项计件提成管理</Text>
        <Divider />

        <Tabs
          defaultActiveKey="dashboard"
          size="large"
          items={[
            { key: 'dashboard', label: '首页仪表盘', children: <DashboardTab /> },
            { key: 'zones',     label: '区域管理',   children: <ZonesTab /> },
            { key: 'schemes',   label: '绩效设置',   children: <SchemesTab /> },
            { key: 'stats',     label: '绩效统计',   children: <StatsTab /> },
            { key: 'settings',  label: '系统设置',   children: <SystemSettingsTab /> },
          ]}
        />
      </div>
    </ConfigProvider>
  );
}

export default PieceworkPage;
