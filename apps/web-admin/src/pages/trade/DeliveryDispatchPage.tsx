/**
 * 外卖自营配送调度台
 * Y-M4
 *
 * Tab 1: 调度台 — 4列状态看板（待派/已派/配送中/已完成）
 * Tab 2: 配送员管理 — 在线配送员列表 + 工作量可视化
 * Tab 3: 统计报表 — 今日配送效率指标
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Tabs,
  Typography,
  message,
} from 'antd';
import {
  CarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  EnvironmentOutlined,
  PhoneOutlined,
  PlusOutlined,
  ReloadOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';

const { Text, Title } = Typography;
const { TabPane } = Tabs;

// ─── 类型定义 ──────────────────────────────────────────────────────────────

interface DeliveryOrder {
  id: string;
  order_id: string;
  store_id: string;
  delivery_address: string;
  distance_meters: number;
  estimated_minutes: number;
  actual_minutes?: number;
  rider_id?: string;
  rider_name?: string;
  rider_phone?: string;
  status: 'pending' | 'assigned' | 'picked_up' | 'delivering' | 'delivered' | 'failed';
  dispatch_at?: string;
  picked_up_at?: string;
  delivered_at?: string;
  failed_reason?: string;
  delivery_fee_fen: number;
  created_at: string;
}

interface Rider {
  id: string;
  name: string;
  phone: string;
  status: 'online' | 'offline' | 'delivering';
  current_orders: number;
  today_completed: number;
}

interface DeliveryStats {
  date: string;
  dispatched_count: number;
  completed_count: number;
  failed_count: number;
  pending_count: number;
  avg_delivery_minutes: number;
  on_time_rate_percent: number;
  rider_count_online: number;
}

const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';
const API_BASE = '/api/v1/trade/delivery';

const fetchJson = async (url: string, options?: RequestInit) => {
  const resp = await fetch(url, {
    ...options,
    headers: { 'X-Tenant-ID': TENANT_ID, 'Content-Type': 'application/json', ...(options?.headers || {}) },
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
};

// ─── 状态色/标签 ──────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  pending:    { color: 'default',  label: '待派单', icon: <ClockCircleOutlined /> },
  assigned:   { color: 'blue',    label: '已派单', icon: <UserOutlined /> },
  picked_up:  { color: 'cyan',    label: '已取货', icon: <CarOutlined /> },
  delivering: { color: 'orange',  label: '配送中', icon: <CarOutlined /> },
  delivered:  { color: 'green',   label: '已送达', icon: <CheckCircleOutlined /> },
  failed:     { color: 'red',     label: '配送失败', icon: <CloseCircleOutlined /> },
};

const RIDER_STATUS_CONFIG: Record<string, { color: string; label: string }> = {
  online:     { color: 'green',  label: '空闲中' },
  delivering: { color: 'orange', label: '配送中' },
  offline:    { color: 'default', label: '已下线' },
};

// ─── 配送单卡片 ────────────────────────────────────────────────────────────

const DeliveryCard = ({
  order,
  onAssign,
  onPickup,
  onComplete,
  onFail,
}: {
  order: DeliveryOrder;
  onAssign: (order: DeliveryOrder) => void;
  onPickup: (id: string) => void;
  onComplete: (id: string) => void;
  onFail: (id: string) => void;
}) => {
  const cfg = STATUS_CONFIG[order.status] || STATUS_CONFIG.pending;
  const feeYuan = (order.delivery_fee_fen / 100).toFixed(2);

  return (
    <Card
      size="small"
      style={{ marginBottom: 8, borderLeft: `3px solid`, borderLeftColor:
        order.status === 'failed' ? '#A32D2D' :
        order.status === 'delivered' ? '#0F6E56' :
        order.status === 'delivering' || order.status === 'picked_up' ? '#BA7517' : '#185FA5'
      }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={4}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Text strong style={{ fontSize: 12 }}>{order.id}</Text>
          <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
        </Space>

        <Space>
          <EnvironmentOutlined style={{ color: '#BA7517' }} />
          <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: order.delivery_address }}>
            {order.delivery_address}
          </Text>
        </Space>

        <Space split={<Divider type="vertical" />} style={{ fontSize: 12 }}>
          <Text type="secondary">{(order.distance_meters / 1000).toFixed(1)} km</Text>
          <Text type="secondary">预计 {order.estimated_minutes} 分钟</Text>
          {order.actual_minutes && (
            <Text type={order.actual_minutes <= order.estimated_minutes ? 'success' : 'warning'}>
              实际 {order.actual_minutes} 分钟
            </Text>
          )}
          <Text style={{ color: '#FF6B35' }}>¥{feeYuan}</Text>
        </Space>

        {order.rider_name && (
          <Space style={{ fontSize: 12 }}>
            <UserOutlined />
            <Text>{order.rider_name}</Text>
            <PhoneOutlined />
            <Text>{order.rider_phone}</Text>
          </Space>
        )}

        {order.failed_reason && (
          <Text type="danger" style={{ fontSize: 12 }}>失败：{order.failed_reason}</Text>
        )}

        <Space>
          {order.status === 'pending' && (
            <Button type="primary" size="small" onClick={() => onAssign(order)}
              style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}>
              派单
            </Button>
          )}
          {order.status === 'assigned' && (
            <Button type="primary" size="small" onClick={() => onPickup(order.id)}>
              确认取货
            </Button>
          )}
          {(order.status === 'picked_up' || order.status === 'delivering') && (
            <Button type="primary" size="small" onClick={() => onComplete(order.id)}>
              确认送达
            </Button>
          )}
          {!['delivered', 'failed'].includes(order.status) && (
            <Button danger size="small" onClick={() => onFail(order.id)}>
              失败
            </Button>
          )}
        </Space>
      </Space>
    </Card>
  );
};

// ─── Tab 1: 调度台看板 ──────────────────────────────────────────────────────

const DispatchBoard = () => {
  const [orders, setOrders] = useState<DeliveryOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [assignModal, setAssignModal] = useState<{ visible: boolean; order?: DeliveryOrder }>({ visible: false });
  const [failModal, setFailModal] = useState<{ visible: boolean; id?: string }>({ visible: false });
  const [riders, setRiders] = useState<Rider[]>([]);
  const [form] = Form.useForm();
  const [failForm] = Form.useForm();

  const loadOrders = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchJson(`${API_BASE}/orders?size=100`);
      setOrders(res.data?.items || []);
    } catch {
      // mock 数据降级
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRiders = useCallback(async () => {
    try {
      const res = await fetchJson(`${API_BASE}/riders`);
      setRiders(res.data?.items || []);
    } catch {
      setRiders([]);
    }
  }, []);

  useEffect(() => { loadOrders(); loadRiders(); }, [loadOrders, loadRiders]);

  const handleAssign = async (values: { rider_id: string; rider_name: string; rider_phone: string }) => {
    if (!assignModal.order) return;
    try {
      await fetchJson(`${API_BASE}/orders/${assignModal.order.id}/assign`, {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('派单成功');
      setAssignModal({ visible: false });
      form.resetFields();
      loadOrders();
    } catch {
      message.error('派单失败，请重试');
    }
  };

  const handlePickup = async (id: string) => {
    try {
      await fetchJson(`${API_BASE}/orders/${id}/pickup`, { method: 'POST' });
      message.success('已确认取货');
      loadOrders();
    } catch {
      message.error('操作失败');
    }
  };

  const handleComplete = async (id: string) => {
    try {
      await fetchJson(`${API_BASE}/orders/${id}/complete`, { method: 'POST' });
      message.success('已确认送达');
      loadOrders();
    } catch {
      message.error('操作失败');
    }
  };

  const handleFail = async (values: { reason: string }) => {
    if (!failModal.id) return;
    try {
      await fetchJson(`${API_BASE}/orders/${failModal.id}/fail`, {
        method: 'POST',
        body: JSON.stringify({ reason: values.reason }),
      });
      message.warning('已标记配送失败');
      setFailModal({ visible: false });
      failForm.resetFields();
      loadOrders();
    } catch {
      message.error('操作失败');
    }
  };

  const columns: Array<{ key: string; title: string; statuses: string[] }> = [
    { key: 'pending',    title: '待派单',  statuses: ['pending'] },
    { key: 'assigned',   title: '已派单',  statuses: ['assigned'] },
    { key: 'on_road',    title: '配送中',  statuses: ['picked_up', 'delivering'] },
    { key: 'done',       title: '已完成',  statuses: ['delivered', 'failed'] },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, alignItems: 'center' }}>
        <Title level={5} style={{ margin: 0 }}>实时配送看板</Title>
        <Button icon={<ReloadOutlined />} onClick={loadOrders} loading={loading}>刷新</Button>
      </div>

      <Row gutter={12}>
        {columns.map(col => {
          const colOrders = orders.filter(o => col.statuses.includes(o.status));
          return (
            <Col key={col.key} span={6}>
              <Card
                title={
                  <Space>
                    <span>{col.title}</span>
                    <Badge count={colOrders.length} style={{ backgroundColor: colOrders.length > 0 ? '#FF6B35' : '#d9d9d9' }} />
                  </Space>
                }
                size="small"
                style={{ minHeight: 400, backgroundColor: '#F8F7F5' }}
                bodyStyle={{ padding: 8 }}
              >
                {colOrders.length === 0
                  ? <Empty description="暂无订单" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  : colOrders.map(o => (
                    <DeliveryCard
                      key={o.id}
                      order={o}
                      onAssign={(order) => setAssignModal({ visible: true, order })}
                      onPickup={handlePickup}
                      onComplete={handleComplete}
                      onFail={(id) => setFailModal({ visible: true, id })}
                    />
                  ))
                }
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* 派单弹窗 */}
      <Modal
        title="派单给配送员"
        open={assignModal.visible}
        onCancel={() => { setAssignModal({ visible: false }); form.resetFields(); }}
        onOk={() => form.submit()}
        okText="确认派单"
        okButtonProps={{ style: { backgroundColor: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form form={form} layout="vertical" onFinish={handleAssign}>
          <Form.Item name="rider_id" label="选择配送员" rules={[{ required: true, message: '请选择配送员' }]}>
            <Input placeholder="配送员 ID（如 rider-001）" />
          </Form.Item>
          <Form.Item name="rider_name" label="配送员姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="rider_phone" label="联系电话" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Form>
        {riders.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>在线配送员：</Text>
            <Space wrap style={{ marginTop: 4 }}>
              {riders.filter(r => r.status !== 'offline').map(r => (
                <Tag
                  key={r.id}
                  color={r.status === 'online' ? 'green' : 'orange'}
                  style={{ cursor: 'pointer' }}
                  onClick={() => form.setFieldsValue({ rider_id: r.id, rider_name: r.name, rider_phone: r.phone })}
                >
                  {r.name}（在途{r.current_orders}单）
                </Tag>
              ))}
            </Space>
          </div>
        )}
      </Modal>

      {/* 失败原因弹窗 */}
      <Modal
        title="标记配送失败"
        open={failModal.visible}
        onCancel={() => { setFailModal({ visible: false }); failForm.resetFields(); }}
        onOk={() => failForm.submit()}
        okText="确认失败"
        okButtonProps={{ danger: true }}
      >
        <Form form={failForm} layout="vertical" onFinish={handleFail}>
          <Form.Item name="reason" label="失败原因" rules={[{ required: true, message: '请填写失败原因' }]}>
            <Input.TextArea rows={3} placeholder="如：顾客无人接听/地址错误/超时未取货" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

// ─── Tab 2: 配送员管理 ──────────────────────────────────────────────────────

const RiderManagement = () => {
  const [riders, setRiders] = useState<Rider[]>([]);
  const [loading, setLoading] = useState(false);

  const loadRiders = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchJson(`${API_BASE}/riders`);
      setRiders(res.data?.items || []);
    } catch {
      setRiders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRiders(); }, [loadRiders]);

  const MAX_ORDERS = 5; // 单骑手最大在途单数

  return (
    <Row gutter={16}>
      <Col span={24}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16, alignItems: 'center' }}>
          <Title level={5} style={{ margin: 0 }}>配送员管理</Title>
          <Space>
            <Tag color="green">在线 {riders.filter(r => r.status !== 'offline').length} 人</Tag>
            <Tag color="default">离线 {riders.filter(r => r.status === 'offline').length} 人</Tag>
            <Button icon={<ReloadOutlined />} onClick={loadRiders} loading={loading}>刷新</Button>
          </Space>
        </div>
      </Col>

      {riders.map(rider => {
        const cfg = RIDER_STATUS_CONFIG[rider.status] || RIDER_STATUS_CONFIG.offline;
        const workloadPct = Math.min(100, (rider.current_orders / MAX_ORDERS) * 100);
        const workloadColor = rider.current_orders >= MAX_ORDERS ? '#A32D2D'
          : rider.current_orders >= 3 ? '#BA7517' : '#0F6E56';

        return (
          <Col key={rider.id} xs={24} sm={12} md={8} lg={6} xl={6}>
            <Card
              size="small"
              style={{ marginBottom: 16 }}
              actions={[
                <Button type="link" size="small" key="workload">查看工作量</Button>,
              ]}
            >
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space>
                  <Avatar
                    icon={<UserOutlined />}
                    style={{ backgroundColor: rider.status === 'offline' ? '#d9d9d9' : '#FF6B35' }}
                  />
                  <div>
                    <Text strong>{rider.name}</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      <PhoneOutlined /> {rider.phone}
                    </Text>
                  </div>
                  <Badge
                    status={rider.status === 'online' ? 'success' : rider.status === 'delivering' ? 'processing' : 'default'}
                    text={<Tag color={cfg.color}>{cfg.label}</Tag>}
                  />
                </Space>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <Text style={{ fontSize: 12 }}>在途单数</Text>
                    <Text strong style={{ fontSize: 12, color: workloadColor }}>
                      {rider.current_orders} / {MAX_ORDERS}
                    </Text>
                  </div>
                  <Progress
                    percent={workloadPct}
                    strokeColor={workloadColor}
                    showInfo={false}
                    size="small"
                  />
                </div>

                <Space split={<Divider type="vertical" />} style={{ fontSize: 12 }}>
                  <Text type="secondary">今日完成</Text>
                  <Text strong style={{ color: '#0F6E56' }}>{rider.today_completed} 单</Text>
                </Space>
              </Space>
            </Card>
          </Col>
        );
      })}

      {riders.length === 0 && !loading && (
        <Col span={24}>
          <Empty description="暂无配送员数据" />
        </Col>
      )}
    </Row>
  );
};

// ─── Tab 3: 统计报表 ───────────────────────────────────────────────────────

const DeliveryStats = () => {
  const [stats, setStats] = useState<DeliveryStats | null>(null);
  const [loading, setLoading] = useState(false);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchJson(`${API_BASE}/stats`);
      setStats(res.data);
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  if (!stats) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Button loading={loading} onClick={loadStats} type="primary"
          style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}>
          加载今日统计
        </Button>
      </div>
    );
  }

  const completionRate = stats.dispatched_count > 0
    ? Math.round((stats.completed_count / stats.dispatched_count) * 100) : 0;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={5} style={{ margin: 0 }}>今日配送效率 · {stats.date}</Title>
        <Button icon={<ReloadOutlined />} onClick={loadStats} loading={loading}>刷新</Button>
      </div>

      {/* KPI 卡片组 */}
      <Row gutter={16}>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="今日派单" value={stats.dispatched_count} suffix="单"
              valueStyle={{ color: '#185FA5' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="已完成" value={stats.completed_count} suffix="单"
              valueStyle={{ color: '#0F6E56' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="配送失败" value={stats.failed_count} suffix="单"
              valueStyle={{ color: stats.failed_count > 0 ? '#A32D2D' : '#2C2C2A' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="进行中" value={stats.pending_count} suffix="单"
              valueStyle={{ color: '#BA7517' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="平均配送时长" value={stats.avg_delivery_minutes} suffix="分钟"
              valueStyle={{ color: stats.avg_delivery_minutes > 40 ? '#A32D2D' : '#2C2C2A' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="准时率" value={stats.on_time_rate_percent} suffix="%"
              valueStyle={{ color: stats.on_time_rate_percent >= 90 ? '#0F6E56' : '#BA7517' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6}>
          <Card size="small">
            <Statistic title="在线配送员" value={stats.rider_count_online} suffix="人"
              valueStyle={{ color: '#0F6E56' }} />
          </Card>
        </Col>
      </Row>

      {/* 完成率环形图（用 Progress 模拟） */}
      <Row gutter={16}>
        <Col span={8}>
          <Card title="完成率" size="small">
            <div style={{ textAlign: 'center', padding: '16px 0' }}>
              <Progress
                type="circle"
                percent={completionRate}
                strokeColor={completionRate >= 90 ? '#0F6E56' : completionRate >= 70 ? '#BA7517' : '#A32D2D'}
                format={pct => <span style={{ fontSize: 20, fontWeight: 'bold' }}>{pct}%</span>}
              />
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">已完成 {stats.completed_count} / 共 {stats.dispatched_count} 单</Text>
              </div>
            </div>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="准时率" size="small">
            <div style={{ textAlign: 'center', padding: '16px 0' }}>
              <Progress
                type="circle"
                percent={stats.on_time_rate_percent}
                strokeColor={
                  stats.on_time_rate_percent >= 90 ? '#0F6E56'
                  : stats.on_time_rate_percent >= 70 ? '#BA7517' : '#A32D2D'
                }
                format={pct => <span style={{ fontSize: 20, fontWeight: 'bold' }}>{pct}%</span>}
              />
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">平均用时 {stats.avg_delivery_minutes} 分钟</Text>
              </div>
            </div>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="配送员在线情况" size="small">
            <div style={{ padding: '16px 0' }}>
              <Progress
                percent={100}
                success={{ percent: Math.round((stats.rider_count_online / 3) * 100) }}
                strokeColor="#d9d9d9"
                showInfo={false}
              />
              <div style={{ marginTop: 8 }}>
                <Space>
                  <Badge color="#0F6E56" text={`在线 ${stats.rider_count_online} 人`} />
                </Space>
              </div>
            </div>
          </Card>
        </Col>
      </Row>
    </Space>
  );
};

// ─── 主页面 ────────────────────────────────────────────────────────────────

export default function DeliveryDispatchPage() {
  const [activeTab, setActiveTab] = useState('dispatch');

  return (
    <div style={{ padding: 24, minWidth: 1280 }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <CarOutlined style={{ fontSize: 20, color: '#FF6B35' }} />
        <Title level={4} style={{ margin: 0 }}>自营配送调度台</Title>
        <Tag color="orange" icon={<CarOutlined />}>Y-M4</Tag>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'dispatch',
            label: (
              <Space>
                <CarOutlined />
                调度台
              </Space>
            ),
            children: <DispatchBoard />,
          },
          {
            key: 'riders',
            label: (
              <Space>
                <TeamOutlined />
                配送员管理
              </Space>
            ),
            children: <RiderManagement />,
          },
          {
            key: 'stats',
            label: (
              <Space>
                <ClockCircleOutlined />
                统计报表
              </Space>
            ),
            children: <DeliveryStats />,
          },
        ]}
      />
    </div>
  );
}
