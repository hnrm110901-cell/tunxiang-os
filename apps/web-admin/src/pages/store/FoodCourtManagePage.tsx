/**
 * FoodCourtManagePage — 智慧商街/档口管理
 * TC-P2-12
 *
 * 使用 Ant Design 5.x + ProComponents
 * 3个Tab：档口档案 | 营业统计 | 订单明细
 */
import { useState, useRef } from 'react';
import {
  Tabs,
  Button,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  message,
  Statistic,
  Row,
  Col,
  Card,
  DatePicker,
  Badge,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  StopOutlined,
  ShopOutlined,
  BarChartOutlined,
  UnorderedListOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface Outlet {
  id: string;
  name: string;
  outlet_code: string;
  location: string;
  owner_name: string;
  owner_phone: string;
  status: 'active' | 'inactive' | 'suspended';
  settlement_ratio: string;
  today_revenue_fen: number;
  today_order_count: number;
  today_avg_order_fen: number;
  created_at: string;
}

interface OutletOrder {
  id: string;
  outlet_id: string;
  outlet_name: string;
  outlet_code: string;
  order_id: string;
  subtotal_fen: number;
  item_count: number;
  status: string;
  created_at: string;
}

// ─── Mock 数据 ────────────────────────────────────────────────────────────────

const MOCK_OUTLETS: Outlet[] = [
  {
    id: 'out-001',
    name: '张记烤鱼',
    outlet_code: 'A01',
    location: 'A区1号',
    owner_name: '张师傅',
    owner_phone: '13800000001',
    status: 'active',
    settlement_ratio: '1.0000',
    today_revenue_fen: 285600,
    today_order_count: 23,
    today_avg_order_fen: 12417,
    created_at: '2026-01-01T00:00:00+08:00',
  },
  {
    id: 'out-002',
    name: '李家粉面',
    outlet_code: 'A02',
    location: 'A区2号',
    owner_name: '李老板',
    owner_phone: '13800000002',
    status: 'active',
    settlement_ratio: '1.0000',
    today_revenue_fen: 156800,
    today_order_count: 41,
    today_avg_order_fen: 3824,
    created_at: '2026-01-01T00:00:00+08:00',
  },
  {
    id: 'out-003',
    name: '老王串串',
    outlet_code: 'B01',
    location: 'B区1号',
    owner_name: '王老板',
    owner_phone: '13800000003',
    status: 'active',
    settlement_ratio: '1.0000',
    today_revenue_fen: 198400,
    today_order_count: 31,
    today_avg_order_fen: 6400,
    created_at: '2026-01-01T00:00:00+08:00',
  },
];

const MOCK_ORDERS: OutletOrder[] = [
  { id: 'oo-001', outlet_id: 'out-001', outlet_name: '张记烤鱼', outlet_code: 'A01', order_id: 'FC-001001', subtotal_fen: 8800, item_count: 2, status: 'completed', created_at: '2026-04-06T10:30:00+08:00' },
  { id: 'oo-002', outlet_id: 'out-002', outlet_name: '李家粉面', outlet_code: 'A02', order_id: 'FC-001001', subtotal_fen: 2400, item_count: 2, status: 'completed', created_at: '2026-04-06T10:30:00+08:00' },
  { id: 'oo-003', outlet_id: 'out-003', outlet_name: '老王串串', outlet_code: 'B01', order_id: 'FC-001002', subtotal_fen: 5600, item_count: 4, status: 'pending', created_at: '2026-04-06T11:00:00+08:00' },
  { id: 'oo-004', outlet_id: 'out-001', outlet_name: '张记烤鱼', outlet_code: 'A01', order_id: 'FC-001003', subtotal_fen: 13600, item_count: 3, status: 'completed', created_at: '2026-04-06T11:30:00+08:00' },
  { id: 'oo-005', outlet_id: 'out-002', outlet_name: '李家粉面', outlet_code: 'A02', order_id: 'FC-001004', subtotal_fen: 3200, item_count: 2, status: 'completed', created_at: '2026-04-06T12:00:00+08:00' },
];

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

const statusMap: Record<string, { color: string; label: string }> = {
  active: { color: 'success', label: '营业中' },
  inactive: { color: 'default', label: '已停用' },
  suspended: { color: 'warning', label: '暂停营业' },
};

const orderStatusMap: Record<string, { color: string; label: string }> = {
  pending: { color: 'processing', label: '进行中' },
  confirmed: { color: 'blue', label: '已确认' },
  completed: { color: 'success', label: '已完成' },
  cancelled: { color: 'error', label: '已取消' },
};

// ─── Tab 1: 档口档案 ──────────────────────────────────────────────────────────

function OutletArchiveTab() {
  const actionRef = useRef<ActionType>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingOutlet, setEditingOutlet] = useState<Partial<Outlet> | null>(null);
  const [outlets, setOutlets] = useState<Outlet[]>(MOCK_OUTLETS);
  const [form] = Form.useForm();

  const handleEdit = (outlet: Outlet) => {
    setEditingOutlet(outlet);
    form.setFieldsValue({
      ...outlet,
      settlement_ratio: parseFloat(outlet.settlement_ratio) * 100,
    });
    setModalOpen(true);
  };

  const handleCreate = () => {
    setEditingOutlet(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleDeactivate = (outlet: Outlet) => {
    Modal.confirm({
      title: '停用档口',
      content: `确定要停用"${outlet.name}"吗？停用后该档口将无法开单。`,
      okText: '确定停用',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => {
        setOutlets((prev) =>
          prev.map((o) => o.id === outlet.id ? { ...o, status: 'inactive' as const } : o)
        );
        message.success(`档口"${outlet.name}"已停用`);
        actionRef.current?.reload();
      },
    });
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    if (editingOutlet?.id) {
      setOutlets((prev) =>
        prev.map((o) =>
          o.id === editingOutlet.id
            ? { ...o, ...values, settlement_ratio: (values.settlement_ratio / 100).toFixed(4) }
            : o
        )
      );
      message.success('档口信息已更新');
    } else {
      const newOutlet: Outlet = {
        id: `out-${Date.now()}`,
        name: values.name,
        outlet_code: values.outlet_code,
        location: values.location,
        owner_name: values.owner_name,
        owner_phone: values.owner_phone,
        status: 'active',
        settlement_ratio: (values.settlement_ratio / 100).toFixed(4),
        today_revenue_fen: 0,
        today_order_count: 0,
        today_avg_order_fen: 0,
        created_at: new Date().toISOString(),
      };
      setOutlets((prev) => [...prev, newOutlet]);
      message.success('档口创建成功');
    }
    setModalOpen(false);
    actionRef.current?.reload();
  };

  const columns: ProColumns<Outlet>[] = [
    {
      title: '档口名称',
      dataIndex: 'name',
      render: (_, record) => (
        <Space>
          <span style={{ fontWeight: 600 }}>{record.name}</span>
          <Tag>{record.outlet_code}</Tag>
        </Space>
      ),
    },
    { title: '区位', dataIndex: 'location', search: false },
    { title: '负责人', dataIndex: 'owner_name', search: false },
    { title: '联系电话', dataIndex: 'owner_phone', search: false },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: {
        active: { text: '营业中', status: 'Success' },
        inactive: { text: '已停用', status: 'Default' },
        suspended: { text: '暂停营业', status: 'Warning' },
      },
      render: (_, record) => {
        const s = statusMap[record.status] || { color: 'default', label: record.status };
        return <Badge status={s.color as 'success' | 'default' | 'warning'} text={s.label} />;
      },
    },
    {
      title: '今日营业额',
      dataIndex: 'today_revenue_fen',
      search: false,
      render: (_, record) => (
        <span style={{ fontWeight: 600, color: '#FF6B35' }}>
          {fenToYuan(record.today_revenue_fen)}
        </span>
      ),
    },
    {
      title: '今日订单',
      dataIndex: 'today_order_count',
      search: false,
      render: (_, record) => `${record.today_order_count}单`,
    },
    {
      title: '客单价',
      dataIndex: 'today_avg_order_fen',
      search: false,
      render: (_, record) => fenToYuan(record.today_avg_order_fen),
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, record) => [
        <Tooltip key="edit" title="编辑">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
        </Tooltip>,
        record.status === 'active' ? (
          <Tooltip key="stop" title="停用档口">
            <Button
              type="link"
              size="small"
              danger
              icon={<StopOutlined />}
              onClick={() => handleDeactivate(record)}
            >
              停用
            </Button>
          </Tooltip>
        ) : null,
      ],
    },
  ];

  return (
    <>
      <ProTable<Outlet>
        actionRef={actionRef}
        columns={columns}
        dataSource={outlets}
        rowKey="id"
        search={{ labelWidth: 'auto' }}
        options={{ reload: true, density: true, setting: true }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
          >
            新建档口
          </Button>,
        ]}
        pagination={{ defaultPageSize: 10 }}
        headerTitle="档口档案"
        request={async () => ({ data: outlets, success: true, total: outlets.length })}
      />

      {/* 新建/编辑弹窗 */}
      <Modal
        title={editingOutlet?.id ? '编辑档口' : '新建档口'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        okText="确认"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 16 }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="name"
                label="档口名称"
                rules={[{ required: true, message: '请填写档口名称' }]}
              >
                <Input placeholder="如：张记烤鱼" maxLength={100} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="outlet_code"
                label="档口编号"
                rules={[{ required: true, message: '请填写档口编号' }]}
              >
                <Input placeholder="如：A01" maxLength={20} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="location" label="区位描述">
            <Input placeholder="如：A区1号" maxLength={100} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="owner_name" label="负责人姓名">
                <Input placeholder="负责人姓名" maxLength={50} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="owner_phone" label="联系电话">
                <Input placeholder="手机号码" maxLength={20} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="status" label="状态" initialValue="active">
            <Select options={[
              { value: 'active', label: '营业中' },
              { value: 'suspended', label: '暂停营业' },
              { value: 'inactive', label: '停用' },
            ]} />
          </Form.Item>
          <Form.Item
            name="settlement_ratio"
            label="结算分成比例（%）"
            initialValue={100}
            tooltip="统一收银场景下，该档口的结算分成比例。100表示全额结算。"
          >
            <InputNumber min={0} max={100} step={0.1} suffix="%" style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab 2: 营业统计 ──────────────────────────────────────────────────────────

function RevenueStatsTab() {
  const [selectedDate, setSelectedDate] = useState<dayjs.Dayjs>(dayjs());

  const totalRevenue = MOCK_OUTLETS.reduce((s, o) => s + o.today_revenue_fen, 0);
  const totalOrders = MOCK_OUTLETS.reduce((s, o) => s + o.today_order_count, 0);
  const maxRevenue = Math.max(...MOCK_OUTLETS.map((o) => o.today_revenue_fen));

  return (
    <div>
      {/* 日期选择 */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12 }}>
        <DatePicker
          value={selectedDate}
          onChange={(d) => d && setSelectedDate(d)}
          allowClear={false}
          format="YYYY-MM-DD"
        />
        <Button icon={<ReloadOutlined />}>刷新数据</Button>
        <span style={{ color: '#5F5E5A', fontSize: 14 }}>
          数据截至：{new Date().toLocaleTimeString()}
        </span>
      </div>

      {/* 广场汇总指标 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="广场总营业额"
              value={totalRevenue / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#FF6B35', fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="广场总订单数"
              value={totalOrders}
              suffix="单"
              valueStyle={{ fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均客单价"
              value={totalOrders > 0 ? Math.round(totalRevenue / totalOrders) / 100 : 0}
              precision={2}
              prefix="¥"
              valueStyle={{ fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="营业档口数"
              value={MOCK_OUTLETS.filter((o) => o.status === 'active').length}
              suffix="个"
              valueStyle={{ fontWeight: 700 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 档口营业额对比条形图（div模拟） */}
      <Card title="档口营业额对比" style={{ marginBottom: 20 }}>
        <div style={{ padding: '8px 0' }}>
          {MOCK_OUTLETS.map((outlet) => {
            const ratio = maxRevenue > 0 ? outlet.today_revenue_fen / maxRevenue : 0;
            return (
              <div key={outlet.id} style={{ marginBottom: 20 }}>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: 6,
                  alignItems: 'center',
                }}>
                  <Space>
                    <span style={{ fontWeight: 600, fontSize: 15 }}>{outlet.name}</span>
                    <Tag>{outlet.outlet_code}</Tag>
                  </Space>
                  <Space size="large">
                    <span style={{ color: '#FF6B35', fontWeight: 700, fontSize: 16 }}>
                      {fenToYuan(outlet.today_revenue_fen)}
                    </span>
                    <span style={{ color: '#5F5E5A', fontSize: 14 }}>
                      {outlet.today_order_count}单
                    </span>
                    <span style={{ color: '#5F5E5A', fontSize: 14 }}>
                      均价 {fenToYuan(outlet.today_avg_order_fen)}
                    </span>
                  </Space>
                </div>
                <div style={{
                  height: 28,
                  background: '#F8F7F5',
                  borderRadius: 6,
                  overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%',
                    width: `${Math.round(ratio * 100)}%`,
                    background: `linear-gradient(90deg, #FF6B35, #FF8555)`,
                    borderRadius: 6,
                    display: 'flex',
                    alignItems: 'center',
                    paddingLeft: 8,
                    minWidth: 60,
                    transition: 'width 600ms ease',
                  }}>
                    <span style={{ color: '#fff', fontSize: 12, fontWeight: 600 }}>
                      {Math.round(ratio * 100)}%
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* 各档口统计卡片 */}
      <Row gutter={16}>
        {MOCK_OUTLETS.map((outlet) => (
          <Col key={outlet.id} span={8}>
            <Card
              title={
                <Space>
                  <ShopOutlined style={{ color: '#FF6B35' }} />
                  <span>{outlet.name}</span>
                  <Tag color={statusMap[outlet.status]?.color === 'success' ? 'green' : 'default'}>
                    {statusMap[outlet.status]?.label}
                  </Tag>
                </Space>
              }
            >
              <Row gutter={8}>
                <Col span={12}>
                  <Statistic
                    title="营业额"
                    value={outlet.today_revenue_fen / 100}
                    precision={2}
                    prefix="¥"
                    valueStyle={{ fontSize: 20, color: '#FF6B35' }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="订单数"
                    value={outlet.today_order_count}
                    suffix="单"
                    valueStyle={{ fontSize: 20 }}
                  />
                </Col>
              </Row>
              <div style={{ marginTop: 12, color: '#5F5E5A', fontSize: 13 }}>
                客单价：{fenToYuan(outlet.today_avg_order_fen)}
                &nbsp;·&nbsp;
                占广场总额 {Math.round(outlet.today_revenue_fen / totalRevenue * 100)}%
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

// ─── Tab 3: 订单明细 ──────────────────────────────────────────────────────────

function OrderDetailTab() {
  const [filterOutletId, setFilterOutletId] = useState<string | undefined>(undefined);

  const filteredOrders = filterOutletId
    ? MOCK_ORDERS.filter((o) => o.outlet_id === filterOutletId)
    : MOCK_ORDERS;

  const columns: ProColumns<OutletOrder>[] = [
    {
      title: '订单号',
      dataIndex: 'order_id',
      render: (text) => <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{text}</span>,
    },
    {
      title: '档口',
      dataIndex: 'outlet_name',
      render: (_, record) => (
        <Space>
          <span>{record.outlet_name}</span>
          <Tag>{record.outlet_code}</Tag>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, record) => {
        const s = orderStatusMap[record.status] || { color: 'default', label: record.status };
        return <Tag color={s.color}>{s.label}</Tag>;
      },
    },
    {
      title: '品项数',
      dataIndex: 'item_count',
      search: false,
      render: (_, record) => `${record.item_count}件`,
    },
    {
      title: '小计',
      dataIndex: 'subtotal_fen',
      search: false,
      render: (_, record) => (
        <span style={{ fontWeight: 600, color: '#FF6B35' }}>
          {fenToYuan(record.subtotal_fen)}
        </span>
      ),
    },
    {
      title: '下单时间',
      dataIndex: 'created_at',
      search: false,
      render: (_, record) => new Date(record.created_at).toLocaleString('zh-CN'),
    },
  ];

  return (
    <div>
      {/* 档口过滤 */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 14, color: '#5F5E5A' }}>按档口筛选：</span>
        <Select
          style={{ width: 200 }}
          allowClear
          placeholder="全部档口"
          value={filterOutletId}
          onChange={setFilterOutletId}
          options={MOCK_OUTLETS.map((o) => ({
            value: o.id,
            label: `${o.name}（${o.outlet_code}）`,
          }))}
        />
        <span style={{ color: '#5F5E5A', fontSize: 14 }}>
          共 {filteredOrders.length} 条记录
        </span>
      </div>

      <ProTable<OutletOrder>
        columns={columns}
        dataSource={filteredOrders}
        rowKey="id"
        search={false}
        options={{ reload: true, density: true }}
        pagination={{ defaultPageSize: 10 }}
        headerTitle="档口订单流水"
        request={async () => ({
          data: filteredOrders,
          success: true,
          total: filteredOrders.length,
        })}
        summary={() => (
          <ProTable.Summary>
            <ProTable.Summary.Row>
              <ProTable.Summary.Cell index={0} colSpan={3}>
                <span style={{ fontWeight: 600 }}>合计</span>
              </ProTable.Summary.Cell>
              <ProTable.Summary.Cell index={3}>
                {filteredOrders.reduce((s, o) => s + o.item_count, 0)}件
              </ProTable.Summary.Cell>
              <ProTable.Summary.Cell index={4}>
                <span style={{ fontWeight: 700, color: '#FF6B35' }}>
                  {fenToYuan(filteredOrders.reduce((s, o) => s + o.subtotal_fen, 0))}
                </span>
              </ProTable.Summary.Cell>
              <ProTable.Summary.Cell index={5} />
            </ProTable.Summary.Row>
          </ProTable.Summary>
        )}
      />
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function FoodCourtManagePage() {
  const [activeTab, setActiveTab] = useState('archive');

  const totalRevenue = MOCK_OUTLETS.reduce((s, o) => s + o.today_revenue_fen, 0);
  const totalOrders = MOCK_OUTLETS.reduce((s, o) => s + o.today_order_count, 0);

  const tabItems = [
    {
      key: 'archive',
      label: (
        <span>
          <ShopOutlined />
          档口档案
        </span>
      ),
      children: <OutletArchiveTab />,
    },
    {
      key: 'stats',
      label: (
        <span>
          <BarChartOutlined />
          营业统计
        </span>
      ),
      children: <RevenueStatsTab />,
    },
    {
      key: 'orders',
      label: (
        <span>
          <UnorderedListOutlined />
          订单明细
        </span>
      ),
      children: <OrderDetailTab />,
    },
  ];

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      {/* 页面标题 */}
      <div style={{
        marginBottom: 20,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
      }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 800, margin: 0, color: '#2C2C2A' }}>
            智慧商街 · 档口管理
          </h2>
          <p style={{ color: '#5F5E5A', marginTop: 4, fontSize: 14 }}>
            美食广场多档口并行收银 + 独立核算
          </p>
        </div>
        {/* 今日汇总 */}
        <div style={{
          display: 'flex',
          gap: 20,
          background: '#fff',
          border: '1px solid #E8E6E1',
          borderRadius: 10,
          padding: '12px 20px',
          alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 12, color: '#5F5E5A' }}>今日广场总收入</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: '#FF6B35' }}>
              {fenToYuan(totalRevenue)}
            </div>
          </div>
          <div style={{ width: 1, height: 36, background: '#E8E6E1' }} />
          <div>
            <div style={{ fontSize: 12, color: '#5F5E5A' }}>总订单数</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: '#2C2C2A' }}>
              {totalOrders}单
            </div>
          </div>
          <div style={{ width: 1, height: 36, background: '#E8E6E1' }} />
          <div>
            <div style={{ fontSize: 12, color: '#5F5E5A' }}>营业档口</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: '#0F6E56' }}>
              {MOCK_OUTLETS.filter((o) => o.status === 'active').length}个
            </div>
          </div>
        </div>
      </div>

      {/* Tab 面板 */}
      <div style={{
        background: '#fff',
        borderRadius: 12,
        border: '1px solid #E8E6E1',
        overflow: 'hidden',
      }}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          style={{ padding: '0 16px' }}
          tabBarStyle={{ marginBottom: 0 }}
        />
        <div style={{ padding: 20 }}>
          {tabItems.find((t) => t.key === activeTab)?.children}
        </div>
      </div>
    </div>
  );
}
