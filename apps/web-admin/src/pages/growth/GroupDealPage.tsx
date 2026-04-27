/**
 * 拼团活动管理页 — Social Viral S4W14-15
 *
 * 四个Tab：拼团列表 / 创建拼团 / 统计仪表盘 / 推荐排行榜
 */
import { useEffect, useRef, useState } from 'react';
import {
  Tabs,
  Card,
  Row,
  Col,
  Statistic,
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  DatePicker,
  Tag,
  Space,
  Progress,
  List,
  Badge,
  Modal,
  Typography,
  Divider,
  message,
} from 'antd';
import {
  TeamOutlined,
  ShareAltOutlined,
  TrophyOutlined,
  PlusOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  FireOutlined,
  DollarOutlined,
  BarChartOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

const API_BASE = '/api/v1/growth/group-deals';
const TENANT_ID = 'demo-tenant-001'; // 实际应从 useTenantContext() 获取

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

interface GroupDeal {
  id: string;
  store_id: string;
  name: string;
  min_participants: number;
  max_participants: number;
  current_participants: number;
  original_price_fen: number;
  deal_price_fen: number;
  discount_fen: number;
  status: 'open' | 'filled' | 'expired' | 'cancelled' | 'completed';
  expires_at: string;
  share_link_code: string;
  total_revenue_fen: number;
  created_at: string;
}

interface GroupDealDetail extends GroupDeal {
  description: string | null;
  dish_id: string | null;
  filled_at: string | null;
  completed_at: string | null;
  initiator_customer_id: string;
  participants: Participant[];
}

interface Participant {
  id: string;
  customer_id: string;
  joined_at: string;
  order_id: string | null;
  paid: boolean;
  paid_at: string | null;
}

interface DealStats {
  total_deals: number;
  filled_count: number;
  completed_count: number;
  fill_rate: number;
  avg_participants: number;
  total_revenue_fen: number;
}

interface LeaderboardItem {
  referrer_id: string;
  successful_referrals: number;
  total_order_amount_fen: number;
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

const fenToYuan = (fen: number) => (fen / 100).toFixed(2);

const statusConfig: Record<string, { color: string; label: string }> = {
  open:      { color: 'processing', label: '拼团中' },
  filled:    { color: 'warning',    label: '已成团' },
  completed: { color: 'success',    label: '已完成' },
  expired:   { color: 'default',    label: '已过期' },
  cancelled: { color: 'error',      label: '已取消' },
};

const getCountdown = (expiresAt: string): string => {
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return '已过期';
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  if (hours > 24) return `${Math.floor(hours / 24)}天${hours % 24}时`;
  return `${hours}时${minutes}分`;
};

const rankMedal = (rank: number) => {
  if (rank === 1) return <span style={{ color: '#FFD700', fontSize: 18 }}>1</span>;
  if (rank === 2) return <span style={{ color: '#C0C0C0', fontSize: 18 }}>2</span>;
  if (rank === 3) return <span style={{ color: '#CD7F32', fontSize: 18 }}>3</span>;
  return <span>{rank}</span>;
};

// ---------------------------------------------------------------------------
// API 调用
// ---------------------------------------------------------------------------

const headers = { 'X-Tenant-ID': TENANT_ID, 'Content-Type': 'application/json' };

const apiGet = async (path: string, params?: Record<string, string>) => {
  const qs = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(`${API_BASE}${path}${qs}`, { headers });
  return res.json();
};

const apiPost = async (path: string, body: object) => {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return res.json();
};

// ---------------------------------------------------------------------------
// 拼团列表 Tab
// ---------------------------------------------------------------------------

const DealListTab = () => {
  const actionRef = useRef<ActionType>();
  const [detailVisible, setDetailVisible] = useState(false);
  const [currentDeal, setCurrentDeal] = useState<GroupDealDetail | null>(null);

  const showDetail = async (id: string) => {
    const res = await apiGet(`/${id}`);
    if (res.ok) {
      setCurrentDeal(res.data);
      setDetailVisible(true);
    } else {
      message.error('获取详情失败');
    }
  };

  const columns: ProColumns<GroupDeal>[] = [
    {
      title: '拼团名称',
      dataIndex: 'name',
      width: 180,
      render: (_, record) => (
        <a onClick={() => showDetail(record.id)}>{record.name}</a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, record) => {
        const cfg = statusConfig[record.status] || statusConfig.open;
        return <Badge status={cfg.color as any} text={cfg.label} />;
      },
      valueEnum: {
        open: { text: '拼团中' },
        filled: { text: '已成团' },
        completed: { text: '已完成' },
        expired: { text: '已过期' },
        cancelled: { text: '已取消' },
      },
    },
    {
      title: '参团进度',
      key: 'progress',
      width: 200,
      render: (_, record) => (
        <Space direction="vertical" size={0} style={{ width: '100%' }}>
          <Progress
            percent={Math.round((record.current_participants / record.min_participants) * 100)}
            size="small"
            format={() => `${record.current_participants}/${record.min_participants}`}
            status={record.current_participants >= record.min_participants ? 'success' : 'active'}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            上限 {record.max_participants} 人
          </Text>
        </Space>
      ),
    },
    {
      title: '价格',
      key: 'price',
      width: 150,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text delete type="secondary">{fenToYuan(record.original_price_fen)}</Text>
          <Text strong style={{ color: '#f5222d' }}>{fenToYuan(record.deal_price_fen)}</Text>
        </Space>
      ),
    },
    {
      title: '倒计时',
      key: 'countdown',
      width: 120,
      render: (_, record) =>
        record.status === 'open' ? (
          <Space>
            <ClockCircleOutlined />
            <Text>{getCountdown(record.expires_at)}</Text>
          </Space>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '收入',
      dataIndex: 'total_revenue_fen',
      width: 100,
      render: (val: any) => `${fenToYuan(val as number)}`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      valueType: 'dateTime',
    },
  ];

  return (
    <>
      <ProTable<GroupDeal>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query: Record<string, string> = {
            page: String(params.current || 1),
            size: String(params.pageSize || 20),
          };
          if (params.status) query.status = params.status;
          const res = await apiGet('', query);
          if (res.ok) {
            return {
              data: res.data.items,
              total: res.data.total,
              success: true,
            };
          }
          return { data: [], total: 0, success: false };
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        search={{ labelWidth: 'auto' }}
        headerTitle="拼团活动列表"
        toolBarRender={() => [
          <Button key="refresh" onClick={() => actionRef.current?.reload()}>
            刷新
          </Button>,
        ]}
      />

      <Modal
        title="拼团详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={700}
      >
        {currentDeal && (
          <div>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic title="拼团名称" value={currentDeal.name} />
              </Col>
              <Col span={12}>
                <Statistic
                  title="状态"
                  valueRender={() => {
                    const cfg = statusConfig[currentDeal.status];
                    return <Badge status={cfg?.color as any} text={cfg?.label} />;
                  }}
                />
              </Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 16 }}>
              <Col span={8}>
                <Statistic title="原价" value={fenToYuan(currentDeal.original_price_fen)} prefix="¥" />
              </Col>
              <Col span={8}>
                <Statistic title="拼团价" value={fenToYuan(currentDeal.deal_price_fen)} prefix="¥" />
              </Col>
              <Col span={8}>
                <Statistic title="总收入" value={fenToYuan(currentDeal.total_revenue_fen)} prefix="¥" />
              </Col>
            </Row>
            <Divider>参与者 ({currentDeal.participants.length}人)</Divider>
            <List
              size="small"
              dataSource={currentDeal.participants}
              renderItem={(p: Participant, idx: number) => (
                <List.Item>
                  <Space>
                    <Text>{idx + 1}.</Text>
                    <Text copyable={{ text: p.customer_id }}>
                      {p.customer_id.slice(0, 8)}...
                    </Text>
                    {p.paid ? (
                      <Tag icon={<CheckCircleOutlined />} color="success">
                        已支付 {p.paid_at ? new Date(p.paid_at).toLocaleString() : ''}
                      </Tag>
                    ) : (
                      <Tag icon={<ClockCircleOutlined />} color="warning">
                        待支付
                      </Tag>
                    )}
                    {idx === 0 && <Tag color="blue">发起者</Tag>}
                  </Space>
                </List.Item>
              )}
            />
          </div>
        )}
      </Modal>
    </>
  );
};

// ---------------------------------------------------------------------------
// 创建拼团 Tab
// ---------------------------------------------------------------------------

const CreateDealTab = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      const body = {
        store_id: values.store_id,
        name: values.name,
        description: values.description || null,
        dish_id: values.dish_id || null,
        min_participants: values.min_participants,
        max_participants: values.max_participants || 10,
        original_price_fen: Math.round(values.original_price_yuan * 100),
        deal_price_fen: Math.round(values.deal_price_yuan * 100),
        expires_at: values.expires_at.toISOString(),
        initiator_customer_id: values.initiator_customer_id,
      };
      const res = await apiPost('', body);
      if (res.ok) {
        message.success(`拼团创建成功! 分享码: ${res.data.share_link_code}`);
        form.resetFields();
      } else {
        message.error(res.error?.message || '创建失败');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="创建拼团活动" style={{ maxWidth: 600 }}>
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item name="name" label="拼团名称" rules={[{ required: true }]}>
          <Input placeholder="例：三人团购招牌菜" maxLength={200} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} placeholder="拼团活动描述（可选）" />
        </Form.Item>
        <Form.Item name="store_id" label="门店ID" rules={[{ required: true }]}>
          <Input placeholder="UUID" />
        </Form.Item>
        <Form.Item name="dish_id" label="菜品ID">
          <Input placeholder="UUID（可选）" />
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="min_participants"
              label="最少参团人数"
              rules={[{ required: true }]}
            >
              <InputNumber min={2} max={50} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="max_participants" label="最大参团人数">
              <InputNumber min={2} max={100} style={{ width: '100%' }} placeholder="默认10" />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="original_price_yuan"
              label="原价(元)"
              rules={[{ required: true }]}
            >
              <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="deal_price_yuan"
              label="拼团价(元)"
              rules={[{ required: true }]}
            >
              <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="expires_at"
          label="过期时间"
          rules={[{ required: true }]}
        >
          <DatePicker showTime style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item
          name="initiator_customer_id"
          label="发起者客户ID"
          rules={[{ required: true }]}
        >
          <Input placeholder="UUID" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} icon={<PlusOutlined />}>
            创建拼团
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// 统计仪表盘 Tab
// ---------------------------------------------------------------------------

const StatsDashboardTab = () => {
  const [stats, setStats] = useState<DealStats | null>(null);
  const [loading, setLoading] = useState(false);

  const loadStats = async (days = 30) => {
    setLoading(true);
    try {
      const res = await apiGet('/stats', { days: String(days) });
      if (res.ok) setStats(res.data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button onClick={() => loadStats(7)}>近7天</Button>
        <Button onClick={() => loadStats(30)} type="primary">近30天</Button>
        <Button onClick={() => loadStats(90)}>近90天</Button>
      </Space>

      {stats && (
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={8}>
            <Card>
              <Statistic
                title="总拼团数"
                value={stats.total_deals}
                prefix={<TeamOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Card>
              <Statistic
                title="成团率"
                value={stats.fill_rate}
                suffix="%"
                prefix={<FireOutlined />}
                valueStyle={{ color: stats.fill_rate >= 50 ? '#3f8600' : '#cf1322' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Card>
              <Statistic
                title="平均参团人数"
                value={stats.avg_participants}
                precision={1}
                prefix={<TeamOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Card>
              <Statistic
                title="已完成"
                value={stats.completed_count}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#3f8600' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Card>
              <Statistic
                title="已成团"
                value={stats.filled_count}
                prefix={<ShareAltOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Card>
              <Statistic
                title="总收入"
                value={fenToYuan(stats.total_revenue_fen)}
                prefix={<DollarOutlined />}
                suffix="元"
              />
            </Card>
          </Col>
        </Row>
      )}

      {stats && (
        <Card style={{ marginTop: 16 }} title="成团率趋势">
          <Progress
            percent={stats.fill_rate}
            strokeColor={{
              '0%': '#108ee9',
              '100%': '#87d068',
            }}
            format={(pct) => `${pct}%`}
          />
          <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
            {stats.filled_count} 个拼团达到最低人数 / 共 {stats.total_deals} 个拼团
          </Text>
        </Card>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// 推荐排行榜 Tab
// ---------------------------------------------------------------------------

const LeaderboardTab = () => {
  const [data, setData] = useState<LeaderboardItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await apiGet('/leaderboard', { limit: '20' });
      if (res.ok) setData(res.data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const columns: ProColumns<LeaderboardItem>[] = [
    {
      title: '排名',
      key: 'rank',
      width: 60,
      render: (_, __, index) => rankMedal(index + 1),
    },
    {
      title: '推荐人ID',
      dataIndex: 'referrer_id',
      width: 200,
      render: (val: any) => (
        <Text copyable={{ text: val as string }}>
          {(val as string).slice(0, 12)}...
        </Text>
      ),
    },
    {
      title: '成功推荐数',
      dataIndex: 'successful_referrals',
      width: 120,
      render: (val: any) => (
        <Space>
          <TrophyOutlined style={{ color: '#faad14' }} />
          <Text strong>{val as number}</Text>
        </Space>
      ),
    },
    {
      title: '贡献订单金额',
      dataIndex: 'total_order_amount_fen',
      width: 150,
      render: (val: any) => `¥${fenToYuan(val as number)}`,
    },
  ];

  return (
    <ProTable<LeaderboardItem>
      columns={columns}
      dataSource={data}
      loading={loading}
      rowKey="referrer_id"
      search={false}
      pagination={false}
      headerTitle={
        <Space>
          <TrophyOutlined style={{ color: '#faad14', fontSize: 18 }} />
          <span>推荐排行榜 Top 20</span>
        </Space>
      }
      toolBarRender={() => [
        <Button key="refresh" onClick={loadData}>刷新</Button>,
      ]}
    />
  );
};

// ---------------------------------------------------------------------------
// 主页面
// ---------------------------------------------------------------------------

const GroupDealPage = () => {
  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <TeamOutlined /> 拼团活动管理
      </Title>
      <Text type="secondary" style={{ marginBottom: 24, display: 'block' }}>
        社交裂变 — 拼团 + 双向奖励
      </Text>

      <Tabs defaultActiveKey="list" size="large">
        <TabPane
          tab={<span><TeamOutlined /> 拼团列表</span>}
          key="list"
        >
          <DealListTab />
        </TabPane>
        <TabPane
          tab={<span><PlusOutlined /> 创建拼团</span>}
          key="create"
        >
          <CreateDealTab />
        </TabPane>
        <TabPane
          tab={<span><BarChartOutlined /> 统计仪表盘</span>}
          key="stats"
        >
          <StatsDashboardTab />
        </TabPane>
        <TabPane
          tab={<span><TrophyOutlined /> 推荐排行榜</span>}
          key="leaderboard"
        >
          <LeaderboardTab />
        </TabPane>
      </Tabs>
    </div>
  );
};

export default GroupDealPage;
