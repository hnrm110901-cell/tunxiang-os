/**
 * 直播管理页
 * S3W10-11 — 视频号+直播模块管理后台
 *
 * 五个区域：
 *   1. 直播活动列表（日历/列表视图 + 状态徽标）
 *   2. 创建活动表单（平台/标题/时间/门店）
 *   3. 直播仪表盘（活跃观众/优惠券/实时指标）
 *   4. 活动复盘（观看人数/峰值/优惠券领取核销/营收）
 *   5. 优惠券管理区（活动内嵌）
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import {
  Tabs,
  Card,
  Row,
  Col,
  Statistic,
  Button,
  Tag,
  Space,
  Input,
  message,
  Modal,
  Typography,
  Empty,
  Spin,
  Pagination,
  Form,
  Select,
  DatePicker,
  InputNumber,
  Table,
  Descriptions,
  Progress,
  Badge,
} from 'antd';
import {
  CalendarOutlined,
  CameraOutlined,
  DashboardOutlined,
  EyeOutlined,
  GiftOutlined,
  HeartOutlined,
  LikeOutlined,
  MessageOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  ShopOutlined,
  StopOutlined,
  UserAddOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;

const API_BASE = '/api/v1/growth/live';
const TENANT_ID = 'demo-tenant-001'; // 实际应从 useTenantContext() 获取

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

interface LiveEvent {
  event_id: string;
  store_id: string | null;
  platform: string;
  live_room_id: string | null;
  title: string;
  description: string;
  cover_image_url: string | null;
  host_employee_id: string | null;
  status: 'scheduled' | 'live' | 'ended' | 'cancelled';
  scheduled_at: string;
  started_at: string | null;
  ended_at: string | null;
  viewer_count: number;
  peak_viewer_count: number;
  like_count: number;
  comment_count: number;
  coupon_total_distributed: number;
  coupon_total_redeemed: number;
  revenue_attributed_fen: number;
  new_followers_count: number;
  recording_url: string | null;
  created_at: string;
  coupon_stats?: CouponStats;
}

interface CouponStats {
  event_id: string;
  total: number;
  available: number;
  claimed: number;
  redeemed: number;
  expired: number;
  total_revenue_fen: number;
}

interface DashboardData {
  days: number;
  total_events: number;
  total_viewers: number;
  total_revenue_fen: number;
  total_distributed: number;
  total_redeemed: number;
  conversion_rate: number;
  per_platform: {
    platform: string;
    event_count: number;
    viewers: number;
    revenue_fen: number;
  }[];
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

const fenToYuan = (fen: number) => (fen / 100).toFixed(2);
const pctFormat = (rate: number) => `${(rate * 100).toFixed(1)}%`;

const platformConfig: Record<string, { color: string; label: string }> = {
  wechat_video: { color: 'green', label: '微信视频号' },
  douyin:       { color: 'geekblue', label: '抖音' },
  kuaishou:     { color: 'orange', label: '快手' },
  xiaohongshu:  { color: 'red', label: '小红书' },
};

const statusConfig: Record<string, { color: string; label: string }> = {
  scheduled: { color: 'blue',    label: '已排期' },
  live:      { color: 'green',   label: '直播中' },
  ended:     { color: 'default', label: '已结束' },
  cancelled: { color: 'red',     label: '已取消' },
};

const formatDateTime = (iso: string | null) => {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
};

// ---------------------------------------------------------------------------
// API 调用层
// ---------------------------------------------------------------------------

const apiFetch = async (path: string, init?: RequestInit) => {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
      ...init?.headers,
    },
    ...init,
  });
  const json = await res.json();
  if (!json.ok) {
    throw new Error(json.error?.message || '请求失败');
  }
  return json.data;
};

// ---------------------------------------------------------------------------
// 子组件：创建直播活动弹窗
// ---------------------------------------------------------------------------

interface CreateEventModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const CreateEventModal: React.FC<CreateEventModalProps> = ({ visible, onClose, onSuccess }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      await apiFetch('/events', {
        method: 'POST',
        body: JSON.stringify({
          store_id: values.store_id,
          title: values.title,
          platform: values.platform,
          scheduled_at: values.scheduled_at.toISOString(),
          description: values.description || '',
          cover_image_url: values.cover_image_url || null,
          host_employee_id: values.host_employee_id || null,
        }),
      });
      message.success('直播活动创建成功');
      form.resetFields();
      onSuccess();
    } catch (err: any) {
      message.error(err.message || '创建失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="创建直播活动"
      open={visible}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={loading}
      width={600}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="title" label="直播标题" rules={[{ required: true, message: '请输入直播标题' }]}>
          <Input placeholder="例：周五招牌菜品限时折扣直播" maxLength={200} />
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="platform" label="平台" rules={[{ required: true, message: '请选择平台' }]}>
              <Select placeholder="选择平台">
                <Option value="wechat_video">微信视频号</Option>
                <Option value="douyin">抖音</Option>
                <Option value="kuaishou">快手</Option>
                <Option value="xiaohongshu">小红书</Option>
              </Select>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="scheduled_at" label="开播时间" rules={[{ required: true, message: '请选择开播时间' }]}>
              <DatePicker showTime style={{ width: '100%' }} placeholder="选择开播时间" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="store_id" label="门店ID" rules={[{ required: true, message: '请输入门店ID' }]}>
          <Input placeholder="门店UUID" />
        </Form.Item>
        <Form.Item name="description" label="直播描述">
          <Input.TextArea rows={3} placeholder="直播内容简介" maxLength={500} />
        </Form.Item>
        <Form.Item name="cover_image_url" label="封面图URL">
          <Input placeholder="https://cdn.example.com/cover.jpg" />
        </Form.Item>
        <Form.Item name="host_employee_id" label="主播员工ID">
          <Input placeholder="主播员工UUID（选填）" />
        </Form.Item>
      </Form>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// 子组件：添加优惠券弹窗
// ---------------------------------------------------------------------------

interface AddCouponModalProps {
  visible: boolean;
  eventId: string | null;
  onClose: () => void;
  onSuccess: () => void;
}

const AddCouponModal: React.FC<AddCouponModalProps> = ({ visible, eventId, onClose, onSuccess }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!eventId) return;
    try {
      const values = await form.validateFields();
      setLoading(true);
      await apiFetch(`/events/${eventId}/coupons`, {
        method: 'POST',
        body: JSON.stringify({
          coupon_name: values.coupon_name,
          discount_desc: values.discount_desc || '',
          total_quantity: values.total_quantity,
          expires_at: values.expires_at.toISOString(),
        }),
      });
      message.success('优惠券批次添加成功');
      form.resetFields();
      onSuccess();
    } catch (err: any) {
      message.error(err.message || '添加失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="添加优惠券批次"
      open={visible}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={loading}
      width={500}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="coupon_name" label="优惠券名称" rules={[{ required: true, message: '请输入券名称' }]}>
          <Input placeholder="例：直播专享满100减30" maxLength={200} />
        </Form.Item>
        <Form.Item name="discount_desc" label="折扣描述">
          <Input placeholder="例：满100减30" maxLength={200} />
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="total_quantity" label="发放数量" rules={[{ required: true, message: '请输入数量' }]}>
              <InputNumber min={1} max={10000} style={{ width: '100%' }} placeholder="100" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="expires_at" label="过期时间" rules={[{ required: true, message: '请选择过期时间' }]}>
              <DatePicker showTime style={{ width: '100%' }} placeholder="选择过期时间" />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// 子组件：活动详情抽屉
// ---------------------------------------------------------------------------

interface EventDetailProps {
  event: LiveEvent | null;
  onStart: (id: string) => void;
  onEnd: (id: string) => void;
  onAddCoupon: (id: string) => void;
}

const EventDetailPanel: React.FC<EventDetailProps> = ({ event, onStart, onEnd, onAddCoupon }) => {
  if (!event) return <Empty description="选择一个直播活动查看详情" />;

  const pc = platformConfig[event.platform] || { color: 'default', label: event.platform };
  const sc = statusConfig[event.status] || { color: 'default', label: event.status };
  const coupon = event.coupon_stats;

  return (
    <Card title={event.title} style={{ marginBottom: 16 }}>
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="平台">
          <Tag color={pc.color}>{pc.label}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Badge status={event.status === 'live' ? 'processing' : 'default'} />
          <Tag color={sc.color}>{sc.label}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="排期时间">{formatDateTime(event.scheduled_at)}</Descriptions.Item>
        <Descriptions.Item label="开播时间">{formatDateTime(event.started_at)}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{formatDateTime(event.ended_at)}</Descriptions.Item>
        <Descriptions.Item label="门店ID">{event.store_id || '-'}</Descriptions.Item>
      </Descriptions>

      {/* 实时指标 */}
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={6}>
          <Statistic title="当前观看" value={event.viewer_count} prefix={<EyeOutlined />} />
        </Col>
        <Col span={6}>
          <Statistic title="峰值观看" value={event.peak_viewer_count} prefix={<EyeOutlined />} />
        </Col>
        <Col span={6}>
          <Statistic title="点赞" value={event.like_count} prefix={<LikeOutlined />} />
        </Col>
        <Col span={6}>
          <Statistic title="评论" value={event.comment_count} prefix={<MessageOutlined />} />
        </Col>
      </Row>

      {/* 优惠券统计 */}
      {coupon && (
        <Card size="small" title="优惠券统计" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={4}><Statistic title="总数" value={coupon.total} /></Col>
            <Col span={4}><Statistic title="可领" value={coupon.available} valueStyle={{ color: '#1890ff' }} /></Col>
            <Col span={4}><Statistic title="已领" value={coupon.claimed} valueStyle={{ color: '#faad14' }} /></Col>
            <Col span={4}><Statistic title="已核销" value={coupon.redeemed} valueStyle={{ color: '#52c41a' }} /></Col>
            <Col span={4}><Statistic title="已过期" value={coupon.expired} valueStyle={{ color: '#ff4d4f' }} /></Col>
            <Col span={4}><Statistic title="营收(元)" value={fenToYuan(coupon.total_revenue_fen)} /></Col>
          </Row>
          {coupon.total > 0 && (
            <Progress
              percent={Math.round((coupon.redeemed / coupon.total) * 100)}
              format={() => `核销率 ${pctFormat(coupon.total > 0 ? coupon.redeemed / coupon.total : 0)}`}
              style={{ marginTop: 8 }}
            />
          )}
        </Card>
      )}

      {/* 营收归因 */}
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={8}>
          <Statistic
            title="营收归因"
            value={fenToYuan(event.revenue_attributed_fen)}
            prefix="¥"
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="新增粉丝"
            value={event.new_followers_count}
            prefix={<UserAddOutlined />}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="券分发/核销"
            value={`${event.coupon_total_distributed} / ${event.coupon_total_redeemed}`}
            prefix={<GiftOutlined />}
          />
        </Col>
      </Row>

      {/* 操作按钮 */}
      <Space style={{ marginTop: 16 }}>
        {event.status === 'scheduled' && (
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => onStart(event.event_id)}>
            开始直播
          </Button>
        )}
        {event.status === 'live' && (
          <Button danger icon={<StopOutlined />} onClick={() => onEnd(event.event_id)}>
            结束直播
          </Button>
        )}
        {(event.status === 'scheduled' || event.status === 'live') && (
          <Button icon={<GiftOutlined />} onClick={() => onAddCoupon(event.event_id)}>
            添加优惠券
          </Button>
        )}
      </Space>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// 主页面
// ---------------------------------------------------------------------------

const LiveStreamingPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState('events');
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [platformFilter, setPlatformFilter] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<LiveEvent | null>(null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [createVisible, setCreateVisible] = useState(false);
  const [couponVisible, setCouponVisible] = useState(false);
  const [couponEventId, setCouponEventId] = useState<string | null>(null);
  const actionRef = useRef<ActionType>();

  // 加载活动列表
  const loadEvents = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('page', String(page));
      params.set('size', '20');
      if (statusFilter) params.set('status', statusFilter);
      if (platformFilter) params.set('platform', platformFilter);
      const data = await apiFetch(`/events?${params.toString()}`);
      setEvents(data.items || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      message.error(err.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, platformFilter]);

  // 加载仪表盘
  const loadDashboard = useCallback(async () => {
    try {
      const data = await apiFetch('/dashboard?days=30');
      setDashboard(data);
    } catch (err: any) {
      message.error(err.message || '加载仪表盘失败');
    }
  }, []);

  // 加载活动详情
  const loadEventDetail = useCallback(async (eventId: string) => {
    try {
      const data = await apiFetch(`/events/${eventId}`);
      setSelectedEvent(data);
    } catch (err: any) {
      message.error(err.message || '加载详情失败');
    }
  }, []);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    if (activeTab === 'dashboard') loadDashboard();
  }, [activeTab, loadDashboard]);

  // 开始直播
  const handleStart = async (eventId: string) => {
    try {
      await apiFetch(`/events/${eventId}/start`, { method: 'PUT' });
      message.success('直播已开始');
      loadEvents();
      loadEventDetail(eventId);
    } catch (err: any) {
      message.error(err.message || '开播失败');
    }
  };

  // 结束直播
  const handleEnd = async (eventId: string) => {
    Modal.confirm({
      title: '确认结束直播？',
      content: '结束后将自动汇总数据，该操作不可撤回。',
      onOk: async () => {
        try {
          await apiFetch(`/events/${eventId}/end`, { method: 'PUT' });
          message.success('直播已结束');
          loadEvents();
          loadEventDetail(eventId);
        } catch (err: any) {
          message.error(err.message || '结束失败');
        }
      },
    });
  };

  // 添加优惠券
  const handleAddCoupon = (eventId: string) => {
    setCouponEventId(eventId);
    setCouponVisible(true);
  };

  // 活动列表列定义
  const columns: ProColumns<LiveEvent>[] = [
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      width: 200,
    },
    {
      title: '平台',
      dataIndex: 'platform',
      width: 100,
      render: (_, row) => {
        const pc = platformConfig[row.platform] || { color: 'default', label: row.platform };
        return <Tag color={pc.color}>{pc.label}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, row) => {
        const sc = statusConfig[row.status] || { color: 'default', label: row.status };
        return (
          <Space>
            {row.status === 'live' && <Badge status="processing" />}
            <Tag color={sc.color}>{sc.label}</Tag>
          </Space>
        );
      },
    },
    {
      title: '排期时间',
      dataIndex: 'scheduled_at',
      width: 140,
      render: (_, row) => formatDateTime(row.scheduled_at),
    },
    {
      title: '观看人数',
      dataIndex: 'viewer_count',
      width: 90,
      sorter: (a, b) => a.viewer_count - b.viewer_count,
    },
    {
      title: '峰值',
      dataIndex: 'peak_viewer_count',
      width: 80,
    },
    {
      title: '营收(元)',
      dataIndex: 'revenue_attributed_fen',
      width: 100,
      render: (_, row) => `¥${fenToYuan(row.revenue_attributed_fen)}`,
      sorter: (a, b) => a.revenue_attributed_fen - b.revenue_attributed_fen,
    },
    {
      title: '操作',
      width: 160,
      render: (_, row) => (
        <Space>
          <Button size="small" onClick={() => loadEventDetail(row.event_id)}>详情</Button>
          {row.status === 'scheduled' && (
            <Button size="small" type="primary" onClick={() => handleStart(row.event_id)}>开播</Button>
          )}
          {row.status === 'live' && (
            <Button size="small" danger onClick={() => handleEnd(row.event_id)}>结束</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <VideoCameraOutlined style={{ marginRight: 8 }} />
        直播管理
      </Title>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        {/* =================== 活动列表Tab =================== */}
        <TabPane tab={<span><CalendarOutlined /> 活动列表</span>} key="events">
          <Row gutter={16}>
            <Col span={16}>
              <Card
                title="直播活动"
                extra={
                  <Space>
                    <Select
                      allowClear
                      placeholder="状态筛选"
                      style={{ width: 120 }}
                      value={statusFilter}
                      onChange={(v) => { setStatusFilter(v); setPage(1); }}
                    >
                      <Option value="scheduled">已排期</Option>
                      <Option value="live">直播中</Option>
                      <Option value="ended">已结束</Option>
                      <Option value="cancelled">已取消</Option>
                    </Select>
                    <Select
                      allowClear
                      placeholder="平台筛选"
                      style={{ width: 130 }}
                      value={platformFilter}
                      onChange={(v) => { setPlatformFilter(v); setPage(1); }}
                    >
                      <Option value="wechat_video">微信视频号</Option>
                      <Option value="douyin">抖音</Option>
                      <Option value="kuaishou">快手</Option>
                      <Option value="xiaohongshu">小红书</Option>
                    </Select>
                    <Button icon={<ReloadOutlined />} onClick={loadEvents}>刷新</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>
                      创建活动
                    </Button>
                  </Space>
                }
              >
                <Spin spinning={loading}>
                  <ProTable<LiveEvent>
                    rowKey="event_id"
                    actionRef={actionRef}
                    columns={columns}
                    dataSource={events}
                    search={false}
                    options={false}
                    pagination={false}
                    size="small"
                  />
                  <div style={{ textAlign: 'right', marginTop: 12 }}>
                    <Pagination
                      current={page}
                      total={total}
                      pageSize={20}
                      showTotal={(t) => `共 ${t} 场直播`}
                      onChange={(p) => setPage(p)}
                    />
                  </div>
                </Spin>
              </Card>
            </Col>

            {/* 右侧详情面板 */}
            <Col span={8}>
              <EventDetailPanel
                event={selectedEvent}
                onStart={handleStart}
                onEnd={handleEnd}
                onAddCoupon={handleAddCoupon}
              />
            </Col>
          </Row>
        </TabPane>

        {/* =================== 经营仪表盘Tab =================== */}
        <TabPane tab={<span><DashboardOutlined /> 经营仪表盘</span>} key="dashboard">
          {dashboard ? (
            <>
              <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="直播总场次（30天）"
                      value={dashboard.total_events}
                      prefix={<VideoCameraOutlined />}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="总观看人次"
                      value={dashboard.total_viewers}
                      prefix={<EyeOutlined />}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="总营收"
                      value={fenToYuan(dashboard.total_revenue_fen)}
                      prefix="¥"
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="券核销转化率"
                      value={pctFormat(dashboard.conversion_rate)}
                    />
                  </Card>
                </Col>
              </Row>

              <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
                <Col span={6}>
                  <Card size="small">
                    <Statistic title="券总分发" value={dashboard.total_distributed} prefix={<GiftOutlined />} />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small">
                    <Statistic title="券总核销" value={dashboard.total_redeemed} prefix={<GiftOutlined />} />
                  </Card>
                </Col>
              </Row>

              {/* 分平台统计 */}
              <Card title="分平台统计">
                <Table
                  rowKey="platform"
                  dataSource={dashboard.per_platform}
                  pagination={false}
                  size="small"
                  columns={[
                    {
                      title: '平台',
                      dataIndex: 'platform',
                      render: (v: string) => {
                        const pc = platformConfig[v] || { color: 'default', label: v };
                        return <Tag color={pc.color}>{pc.label}</Tag>;
                      },
                    },
                    { title: '场次', dataIndex: 'event_count' },
                    { title: '观看人次', dataIndex: 'viewers' },
                    {
                      title: '营收(元)',
                      dataIndex: 'revenue_fen',
                      render: (v: number) => `¥${fenToYuan(v)}`,
                    },
                  ]}
                />
              </Card>
            </>
          ) : (
            <Spin style={{ display: 'block', textAlign: 'center', padding: 80 }} />
          )}
        </TabPane>
      </Tabs>

      {/* 创建活动弹窗 */}
      <CreateEventModal
        visible={createVisible}
        onClose={() => setCreateVisible(false)}
        onSuccess={() => { setCreateVisible(false); loadEvents(); }}
      />

      {/* 添加优惠券弹窗 */}
      <AddCouponModal
        visible={couponVisible}
        eventId={couponEventId}
        onClose={() => setCouponVisible(false)}
        onSuccess={() => {
          setCouponVisible(false);
          if (couponEventId) loadEventDetail(couponEventId);
        }}
      />
    </div>
  );
};

export default LiveStreamingPage;
