/**
 * Customer360Page — 客户360画像（私域视角）
 *
 * 功能：
 *   - 门店 + 客户ID 检索入口
 *   - 会员档案卡片（RFM等级、生命周期、消费摘要、马斯洛层级）
 *   - 旅程历史 Timeline（最近10条）
 *   - 近期订单表格（最近5笔）
 *   - 个性化定价策略推荐卡片
 */
import React, { useState } from 'react';
import {
  Card, Row, Col, Button, Input, Select, Tag, Typography,
  Statistic, Timeline, Table, Alert, Spin, Empty, Space, Progress,
} from 'antd';
import {
  UserOutlined, SearchOutlined, ReloadOutlined, TrophyOutlined,
  ShoppingOutlined, SendOutlined, TagOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import apiClient from '../services/api';

const { Text, Title } = Typography;
const { Option } = Select;

// ── Types ─────────────────────────────────────────────────────────────────────

interface MemberProfile {
  customer_id: string;
  rfm_level: string;
  lifecycle_state: string | null;
  birth_date: string | null;
  wechat_openid: string | null;
  channel_source: string | null;
  recency_days: number;
  frequency: number;
  monetary: number;
  monetary_yuan: number;
  last_visit: string | null;
  is_active: boolean;
  joined_at: string | null;
}

interface Journey {
  journey_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
}

interface OrderRecord {
  order_id: string;
  total_amount: number;
  total_amount_yuan: number;
  created_at: string | null;
  status: string;
}

interface PricingOffer {
  offer_type: string;
  title: string;
  description: string;
  discount_pct: number;
  maslow_level: number;
  strategy_note: string;
  is_peak_hour: boolean;
  confidence: number;
}

interface Customer360 {
  store_id: string;
  customer_id: string;
  member: MemberProfile;
  recent_journeys: Journey[];
  recent_orders: OrderRecord[];
  pricing_offer: PricingOffer | null;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STORE_OPTIONS = ['S001', 'S002', 'S003'];

const LIFECYCLE_COLOR: Record<string, string> = {
  lead: 'default', registered: 'blue', first_order_pending: 'gold',
  repeat: 'green', high_frequency: 'cyan', vip: 'purple',
  at_risk: 'orange', dormant: 'red', lost: 'default',
};
const LIFECYCLE_LABEL: Record<string, string> = {
  lead: '潜客', registered: '已注册', first_order_pending: '待首单',
  repeat: '复购', high_frequency: '高频', vip: 'VIP',
  at_risk: '风险', dormant: '沉睡', lost: '流失',
};
const RFM_COLOR: Record<string, string> = {
  S1: 'gold', S2: 'blue', S3: 'green', S4: 'orange', S5: 'default',
};
const JOURNEY_STATUS_COLOR: Record<string, string> = {
  pending: 'default', running: 'processing', completed: 'success', failed: 'error',
};
const JOURNEY_LABEL: Record<string, string> = {
  member_activation: '入会激活', first_order_conversion: '首单转化',
  dormant_wakeup: '沉睡唤醒', proactive_remind: '主动提醒',
  birthday_greeting: '生日祝福', anniversary_greeting: '入会周年',
};
const MASLOW_LABEL: Record<number, string> = {
  1: 'L1 初次接触', 2: 'L2 初步信任', 3: 'L3 社交习惯',
  4: 'L4 高频忠实', 5: 'L5 深度忠诚',
};
const OFFER_TYPE_COLOR: Record<string, string> = {
  quality_story: 'default', discount_coupon: 'red',
  group_bundle: 'orange', exclusive_access: 'purple', experience: 'gold',
};

// ── Sub-components ─────────────────────────────────────────────────────────────

const MemberCard: React.FC<{ member: MemberProfile }> = ({ member }) => (
  <Card
    title={<><UserOutlined /> 会员档案</>}
    extra={
      <Space>
        {member.is_active
          ? <Tag color="green">活跃</Tag>
          : <Tag color="red">已停用</Tag>}
      </Space>
    }
    style={{ marginBottom: 16 }}
  >
    <Row gutter={[16, 16]}>
      <Col xs={12} sm={8} md={6}>
        <Statistic title="消费金额" value={member.monetary_yuan} prefix="¥" precision={2} />
      </Col>
      <Col xs={12} sm={8} md={6}>
        <Statistic title="消费次数" value={member.frequency} suffix="次" />
      </Col>
      <Col xs={12} sm={8} md={6}>
        <Statistic title="最近到访" value={member.recency_days} suffix="天前" />
      </Col>
      <Col xs={12} sm={8} md={6}>
        <Statistic title="入会时间" value={member.joined_at?.slice(0, 10) || '—'} />
      </Col>
    </Row>

    <Row gutter={[8, 8]} style={{ marginTop: 16 }}>
      <Col>
        <Text type="secondary">RFM等级：</Text>
        <Tag color={RFM_COLOR[member.rfm_level] || 'default'}>{member.rfm_level || '—'}</Tag>
      </Col>
      <Col>
        <Text type="secondary">生命周期：</Text>
        {member.lifecycle_state
          ? <Tag color={LIFECYCLE_COLOR[member.lifecycle_state] || 'default'}>
              {LIFECYCLE_LABEL[member.lifecycle_state] || member.lifecycle_state}
            </Tag>
          : <Text type="secondary">—</Text>}
      </Col>
      <Col>
        <Text type="secondary">渠道来源：</Text>
        <Text>{member.channel_source || '—'}</Text>
      </Col>
      {member.birth_date && (
        <Col>
          <Text type="secondary">生日：</Text>
          <Text>{member.birth_date}</Text>
        </Col>
      )}
      {member.wechat_openid && (
        <Col>
          <Text type="secondary">企微ID：</Text>
          <Text type="secondary" ellipsis={{ tooltip: member.wechat_openid }}>
            {member.wechat_openid.slice(0, 16)}…
          </Text>
        </Col>
      )}
    </Row>
  </Card>
);

const JourneyHistory: React.FC<{ journeys: Journey[] }> = ({ journeys }) => (
  <Card
    title={<><SendOutlined /> 旅程历史</>}
    style={{ marginBottom: 16 }}
    bodyStyle={{ maxHeight: 320, overflowY: 'auto' }}
  >
    {journeys.length === 0
      ? <Empty description="暂无旅程记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      : (
        <Timeline
          items={journeys.map(j => ({
            color: j.status === 'completed' ? 'green'
                 : j.status === 'failed' ? 'red'
                 : j.status === 'running' ? 'blue' : 'gray',
            children: (
              <Space direction="vertical" size={0}>
                <Space>
                  <Text strong>{JOURNEY_LABEL[j.journey_type] || j.journey_type}</Text>
                  <Tag color={JOURNEY_STATUS_COLOR[j.status] || 'default'}>{j.status}</Tag>
                </Space>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {j.started_at?.slice(0, 16) || '—'}
                  {j.completed_at ? ` → ${j.completed_at.slice(0, 16)}` : ''}
                </Text>
              </Space>
            ),
          }))}
        />
      )}
  </Card>
);

const ORDER_COLUMNS: ColumnsType<OrderRecord> = [
  {
    title: '订单ID',
    dataIndex: 'order_id',
    width: 160,
    ellipsis: true,
    render: (v: string) => <Text code>{v.slice(0, 12)}…</Text>,
  },
  {
    title: '金额',
    dataIndex: 'total_amount_yuan',
    width: 100,
    align: 'right',
    render: (v: number) => <Text strong>¥{v.toFixed(2)}</Text>,
  },
  {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (v: string) => (
      <Tag color={v === 'completed' ? 'green' : v === 'cancelled' ? 'red' : 'default'}>{v}</Tag>
    ),
  },
  {
    title: '下单时间',
    dataIndex: 'created_at',
    render: (v: string | null) => v ? v.slice(0, 16) : '—',
  },
];

const RecentOrders: React.FC<{ orders: OrderRecord[] }> = ({ orders }) => (
  <Card title={<><ShoppingOutlined /> 近期订单</>} style={{ marginBottom: 16 }}>
    {orders.length === 0
      ? <Empty description="暂无订单记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      : (
        <Table<OrderRecord>
          rowKey="order_id"
          columns={ORDER_COLUMNS}
          dataSource={orders}
          size="small"
          pagination={false}
        />
      )}
  </Card>
);

const PricingCard: React.FC<{ offer: PricingOffer | null }> = ({ offer }) => {
  if (!offer) return null;
  return (
    <Card
      title={<><TagOutlined /> 个性化定价推荐</>}
      extra={<Tag color={offer.is_peak_hour ? 'volcano' : 'cyan'}>{offer.is_peak_hour ? '高峰时段' : '平峰时段'}</Tag>}
      style={{ marginBottom: 16 }}
    >
      <Row gutter={16} align="middle">
        <Col flex="auto">
          <Title level={5} style={{ marginBottom: 4 }}>{offer.title}</Title>
          <Text>{offer.description}</Text>
          <div style={{ marginTop: 8 }}>
            <Tag color={OFFER_TYPE_COLOR[offer.offer_type] || 'default'}>{offer.offer_type}</Tag>
            <Tag color="blue">{MASLOW_LABEL[offer.maslow_level] || `L${offer.maslow_level}`}</Tag>
            {offer.discount_pct > 0 && <Tag color="red">{offer.discount_pct}折</Tag>}
          </div>
          <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
            {offer.strategy_note}
          </Text>
        </Col>
        <Col style={{ minWidth: 80, textAlign: 'center' }}>
          <Progress
            type="circle"
            percent={Math.round(offer.confidence * 100)}
            size={64}
            format={p => <span style={{ fontSize: 12 }}>{p}%</span>}
          />
          <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>置信度</div>
        </Col>
      </Row>
    </Card>
  );
};

// ── Main Component ─────────────────────────────────────────────────────────────

const Customer360Page: React.FC = () => {
  const storeId = localStorage.getItem('store_id') || 'S001';

  const [selectedStore, setSelectedStore] = useState(storeId);
  const [customerId, setCustomerId]       = useState('');
  const [data, setData]                   = useState<Customer360 | null>(null);
  const [loading, setLoading]             = useState(false);
  const [error, setError]                 = useState<string | null>(null);

  const search = async () => {
    if (!customerId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get(
        `/api/v1/private-domain/customer360/${selectedStore}/${customerId.trim()}`
      );
      setData(res.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(status === 404 ? '未找到该会员，请确认客户ID是否正确' : '加载失败，请稍后重试');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* 搜索栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            value={selectedStore}
            onChange={setSelectedStore}
            style={{ width: 100 }}
          >
            {STORE_OPTIONS.map(s => <Option key={s} value={s}>{s}</Option>)}
          </Select>
          <Input
            placeholder="输入客户ID（如 C001）"
            value={customerId}
            onChange={e => setCustomerId(e.target.value)}
            onPressEnter={search}
            style={{ width: 220 }}
            allowClear
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={search}
            loading={loading}
            disabled={!customerId.trim()}
          >
            查询
          </Button>
          {data && (
            <Button icon={<ReloadOutlined />} onClick={search} loading={loading}>
              刷新
            </Button>
          )}
        </Space>
      </Card>

      {/* 错误提示 */}
      {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}

      {/* 加载中 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" tip="加载中…" />
        </div>
      )}

      {/* 空状态 */}
      {!loading && !data && !error && (
        <Card>
          <Empty
            image={<TrophyOutlined style={{ fontSize: 64, color: '#bbb' }} />}
            description="请输入客户ID查询其360画像"
          />
        </Card>
      )}

      {/* 结果 */}
      {!loading && data && (
        <Row gutter={16}>
          <Col xs={24} lg={14}>
            <MemberCard member={data.member} />
            <RecentOrders orders={data.recent_orders} />
            <PricingCard offer={data.pricing_offer} />
          </Col>
          <Col xs={24} lg={10}>
            <JourneyHistory journeys={data.recent_journeys} />
          </Col>
        </Row>
      )}
    </div>
  );
};

export default Customer360Page;
