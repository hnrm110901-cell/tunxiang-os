/**
 * Y-D7 付费会员卡产品管理
 * 三个Tab：卡档案列表 / 产品配置 / 销售统计
 */
import { useState, useEffect } from 'react';
import {
  Tabs,
  Table,
  Tag,
  Button,
  Card,
  Row,
  Col,
  Select,
  Alert,
  Spin,
  Typography,
  Space,
  Badge,
  message,
  Statistic,
  Modal,
  Form,
  Progress,
  Tooltip,
  Divider,
  List,
  Avatar,
} from 'antd';
import {
  CrownOutlined,
  GiftOutlined,
  StarOutlined,
  ReloadOutlined,
  DollarOutlined,
  ClockCircleOutlined,
  UserOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;

const API_BASE = 'http://localhost:8003';
const TENANT_ID = 'demo-tenant-id';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface PremiumCard {
  id: string;
  card_no: string;
  member_id: string;
  card_type: 'monthly' | 'quarterly' | 'annual' | 'lifetime';
  card_name: string;
  price_fen: number;
  start_date: string;
  end_date: string | null;
  days_remaining: number | null;
  status: 'active' | 'expired' | 'cancelled' | 'suspended';
  benefits: Record<string, unknown>;
  purchase_channel: string | null;
  auto_renew: boolean;
  is_expiring_soon: boolean;
  created_at: string | null;
}

interface CardProduct {
  card_type: string;
  name: string;
  price_fen: number;
  price_yuan: number;
  duration_days: number | null;
  benefits: Record<string, unknown>;
  description: string;
  highlight: string;
  refundable: boolean;
}

interface CardStats {
  active_count: number;
  sold_this_month: number;
  expiring_soon: number;
  total_revenue_fen: number;
  total_revenue_yuan: number;
  by_type: {
    monthly: number;
    quarterly: number;
    annual: number;
    lifetime: number;
  };
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function statusTag(status: string) {
  const map: Record<string, { color: string; label: string }> = {
    active: { color: 'success', label: '有效' },
    expired: { color: 'default', label: '已到期' },
    cancelled: { color: 'error', label: '已取消' },
    suspended: { color: 'warning', label: '已暂停' },
  };
  const info = map[status] || { color: 'default', label: status };
  return <Tag color={info.color}>{info.label}</Tag>;
}

function cardTypeIcon(type: string) {
  const icons: Record<string, React.ReactNode> = {
    lifetime: <CrownOutlined style={{ color: '#FFB800' }} />,
    annual: <StarOutlined style={{ color: '#FF6B35' }} />,
    quarterly: <GiftOutlined style={{ color: '#0F6E56' }} />,
    monthly: <UserOutlined style={{ color: '#185FA5' }} />,
  };
  return icons[type] || <UserOutlined />;
}

// ─── 子组件：卡档案列表Tab ────────────────────────────────────────────────────

function CardListTab() {
  const [cards, setCards] = useState<PremiumCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterType, setFilterType] = useState<string>('');
  const [total, setTotal] = useState(0);

  const fetchCards = async (page = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), size: '20' });
      if (filterStatus) params.set('status', filterStatus);
      if (filterType) params.set('card_type', filterType);
      const res = await fetch(`${API_BASE}/api/v1/member/premium-memberships?${params}`, {
        headers: { 'X-Tenant-ID': TENANT_ID },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setCards(json.data?.items || []);
      setTotal(json.data?.total || 0);
    } catch {
      // Mock 卡档案数据
      const today = new Date();
      const mockCards: PremiumCard[] = [
        {
          id: 'card-001', card_no: 'PMC-202604-A1B2', member_id: 'member-001',
          card_type: 'annual', card_name: '年卡', price_fen: 88800,
          start_date: '2026-01-01',
          end_date: new Date(today.getTime() + 5 * 86400000).toISOString().split('T')[0],
          days_remaining: 5, status: 'active',
          benefits: { discount_rate: 0.88, priority_booking: true },
          purchase_channel: 'miniapp', auto_renew: false, is_expiring_soon: true,
          created_at: '2026-01-01T10:00:00',
        },
        {
          id: 'card-002', card_no: 'PMC-202603-C3D4', member_id: 'member-002',
          card_type: 'quarterly', card_name: '季卡', price_fen: 24900,
          start_date: '2026-01-15', end_date: '2026-04-15', days_remaining: 9,
          status: 'active', benefits: { discount_rate: 0.92, birthday_bonus: true },
          purchase_channel: 'pos', auto_renew: true, is_expiring_soon: false,
          created_at: '2026-01-15T14:00:00',
        },
        {
          id: 'card-003', card_no: 'PMC-202602-E5F6', member_id: 'member-003',
          card_type: 'lifetime', card_name: '终身卡', price_fen: 288800,
          start_date: '2026-02-01', end_date: null, days_remaining: null,
          status: 'active', benefits: { discount_rate: 0.85, all_benefits: true },
          purchase_channel: 'wecom', auto_renew: false, is_expiring_soon: false,
          created_at: '2026-02-01T09:00:00',
        },
        {
          id: 'card-004', card_no: 'PMC-202601-G7H8', member_id: 'member-004',
          card_type: 'monthly', card_name: '月卡', price_fen: 9900,
          start_date: '2026-02-01', end_date: '2026-03-02', days_remaining: -35,
          status: 'expired', benefits: { discount_rate: 0.95 },
          purchase_channel: 'miniapp', auto_renew: false, is_expiring_soon: false,
          created_at: '2026-02-01T11:00:00',
        },
        {
          id: 'card-005', card_no: 'PMC-202603-I9J0', member_id: 'member-005',
          card_type: 'annual', card_name: '年卡', price_fen: 88800,
          start_date: '2026-03-01', end_date: '2027-03-01', days_remaining: 330,
          status: 'cancelled', benefits: { discount_rate: 0.88 },
          purchase_channel: 'pos', auto_renew: false, is_expiring_soon: false,
          created_at: '2026-03-01T10:00:00',
        },
      ];
      const filtered = mockCards.filter(c => {
        if (filterStatus && c.status !== filterStatus) return false;
        if (filterType && c.card_type !== filterType) return false;
        return true;
      });
      setCards(filtered);
      setTotal(filtered.length);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchCards(); }, [filterStatus, filterType]);

  const columns: ColumnsType<PremiumCard> = [
    {
      title: '卡号',
      dataIndex: 'card_no',
      width: 160,
      render: (v: string, r: PremiumCard) => (
        <Space>
          {cardTypeIcon(r.card_type)}
          <Text code>{v}</Text>
        </Space>
      ),
    },
    {
      title: '卡类型',
      dataIndex: 'card_name',
      width: 80,
      render: (v: string, r: PremiumCard) => {
        const colorMap: Record<string, string> = {
          lifetime: 'gold', annual: 'orange', quarterly: 'green', monthly: 'blue',
        };
        return <Tag color={colorMap[r.card_type] || 'default'}>{v}</Tag>;
      },
    },
    {
      title: '会员ID',
      dataIndex: 'member_id',
      width: 120,
      ellipsis: true,
      render: (v: string) => <Text copyable={{ text: v }}>{v.slice(0, 8)}…</Text>,
    },
    {
      title: '购买价格',
      dataIndex: 'price_fen',
      width: 90,
      render: (v: number) => <Text strong>¥{(v / 100).toFixed(0)}</Text>,
    },
    {
      title: '到期日',
      width: 120,
      render: (_: unknown, r: PremiumCard) =>
        r.end_date ? (
          <Space direction="vertical" size={0}>
            <Text>{r.end_date}</Text>
            {r.is_expiring_soon && (
              <Tag color="warning" icon={<ClockCircleOutlined />}>
                {r.days_remaining}天后到期
              </Tag>
            )}
          </Space>
        ) : (
          <Tag color="gold" icon={<CrownOutlined />}>永久有效</Tag>
        ),
    },
    {
      title: '剩余天数',
      width: 110,
      render: (_: unknown, r: PremiumCard) => {
        if (r.end_date === null) return <Text type="secondary">终身</Text>;
        const days = r.days_remaining ?? 0;
        if (days < 0) return <Text type="danger">已过期{Math.abs(days)}天</Text>;
        const pct = Math.min((days / 365) * 100, 100);
        return (
          <Tooltip title={`剩余 ${days} 天`}>
            <Progress
              percent={pct}
              showInfo={false}
              size="small"
              strokeColor={days <= 7 ? '#A32D2D' : days <= 30 ? '#BA7517' : '#0F6E56'}
              style={{ width: 80 }}
            />
          </Tooltip>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => statusTag(v),
    },
    {
      title: '购买渠道',
      dataIndex: 'purchase_channel',
      width: 90,
      render: (v: string | null) => {
        const map: Record<string, string> = { miniapp: '小程序', pos: 'POS', wecom: '企微' };
        return v ? <Tag>{map[v] || v}</Tag> : <Text type="secondary">—</Text>;
      },
    },
    {
      title: '自动续费',
      dataIndex: 'auto_renew',
      width: 80,
      render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#0F6E56' }} /> : <CloseCircleOutlined style={{ color: '#B4B2A9' }} />,
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Text strong>状态：</Text>
            <Select
              placeholder="全部状态"
              style={{ width: 120 }}
              allowClear
              value={filterStatus || undefined}
              onChange={v => setFilterStatus(v || '')}
            >
              <Option value="active">有效</Option>
              <Option value="expired">已到期</Option>
              <Option value="cancelled">已取消</Option>
              <Option value="suspended">已暂停</Option>
            </Select>
            <Text strong>类型：</Text>
            <Select
              placeholder="全部类型"
              style={{ width: 120 }}
              allowClear
              value={filterType || undefined}
              onChange={v => setFilterType(v || '')}
            >
              <Option value="monthly">月卡</Option>
              <Option value="quarterly">季卡</Option>
              <Option value="annual">年卡</Option>
              <Option value="lifetime">终身卡</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={() => fetchCards()}>刷新</Button>
          </Space>
        </Col>
      </Row>

      <Alert
        type="info"
        showIcon
        message="付费卡与储值卡互斥规则：结算时付费卡折扣优先，储值卡余额作为补充支付。"
        style={{ marginBottom: 16 }}
      />

      <Table<PremiumCard>
        columns={columns}
        dataSource={cards}
        rowKey="id"
        loading={loading}
        size="middle"
        pagination={{ pageSize: 20, total, showTotal: t => `共 ${t} 条` }}
        scroll={{ x: 1000 }}
        rowClassName={r => r.is_expiring_soon ? 'row-expiring' : ''}
      />
      <style>{`
        .row-expiring td { background: #fff7e6 !important; }
      `}</style>
    </div>
  );
}

// ─── 子组件：产品配置Tab ──────────────────────────────────────────────────────

function ProductConfigTab() {
  const [products, setProducts] = useState<CardProduct[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchProducts = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/member/premium-memberships/products`, {
        headers: { 'X-Tenant-ID': TENANT_ID },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setProducts(json.data?.products || []);
    } catch {
      setProducts([
        { card_type: 'monthly', name: '月卡', price_fen: 9900, price_yuan: 99, duration_days: 30, benefits: { discount_rate: 0.95, free_parking: false }, description: '享受9.5折优惠，有效期30天', highlight: '适合尝鲜用户', refundable: true },
        { card_type: 'quarterly', name: '季卡', price_fen: 24900, price_yuan: 249, duration_days: 90, benefits: { discount_rate: 0.92, birthday_bonus: true }, description: '享受9.2折 + 生日双倍积分，有效期90天', highlight: '性价比首选', refundable: true },
        { card_type: 'annual', name: '年卡', price_fen: 88800, price_yuan: 888, duration_days: 365, benefits: { discount_rate: 0.88, free_dishes: ['招牌汤'], priority_booking: true, birthday_bonus: true }, description: '享受8.8折 + 每月赠招牌汤 + 优先订位，有效期365天', highlight: '忠实会员首选', refundable: true },
        { card_type: 'lifetime', name: '终身卡', price_fen: 288800, price_yuan: 2888, duration_days: null, benefits: { discount_rate: 0.85, all_benefits: true }, description: '享受全部尊享权益，永久有效', highlight: '顶级体验', refundable: false },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchProducts(); }, []);

  const colorMap: Record<string, string> = {
    lifetime: '#FFB800', annual: '#FF6B35', quarterly: '#0F6E56', monthly: '#185FA5',
  };

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', paddingTop: 60 }} />;

  return (
    <div>
      <Alert
        type="info"
        showIcon
        message="产品配置说明"
        description="当前为系统默认产品配置。如需调整价格或权益，请联系运营配置（版本v196支持数据库级别的产品定制）。"
        style={{ marginBottom: 24 }}
      />
      <Row gutter={24}>
        {products.map(p => (
          <Col key={p.card_type} xs={24} sm={12} lg={6} style={{ marginBottom: 16 }}>
            <Card
              title={
                <Space>
                  <div style={{
                    width: 32, height: 32, borderRadius: '50%',
                    background: colorMap[p.card_type] || '#999',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {p.card_type === 'lifetime' ? (
                      <CrownOutlined style={{ color: '#fff' }} />
                    ) : (
                      <StarOutlined style={{ color: '#fff' }} />
                    )}
                  </div>
                  <span>{p.name}</span>
                </Space>
              }
              extra={<Tag color={p.card_type === 'lifetime' ? 'gold' : 'default'}>{p.highlight}</Tag>}
              bordered
              style={{ borderTop: `3px solid ${colorMap[p.card_type] || '#999'}` }}
            >
              <Statistic
                title="售价"
                value={p.price_yuan}
                prefix="¥"
                valueStyle={{ color: colorMap[p.card_type] || '#333', fontSize: 28 }}
              />
              <Text type="secondary">
                {p.duration_days ? `有效期 ${p.duration_days} 天` : '永久有效'}
              </Text>

              <Divider style={{ margin: '12px 0' }} />

              <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                {p.description}
              </Paragraph>

              <div>
                <Text strong style={{ fontSize: 12 }}>权益包：</Text>
                <div style={{ marginTop: 4 }}>
                  {!!p.benefits.discount_rate && (
                    <Tag color="blue">{((p.benefits.discount_rate as number) * 10).toFixed(1)}折优惠</Tag>
                  )}
                  {!!p.benefits.priority_booking && <Tag color="purple">优先订位</Tag>}
                  {!!p.benefits.birthday_bonus && <Tag color="pink">生日双倍积分</Tag>}
                  {!!p.benefits.all_benefits && <Tag color="gold">全部权益</Tag>}
                  {Array.isArray(p.benefits.free_dishes) && (
                    <Tag color="green">赠 {(p.benefits.free_dishes as string[]).join('/')}</Tag>
                  )}
                </div>
              </div>

              <Divider style={{ margin: '12px 0' }} />
              <Space>
                <Tag color={p.refundable ? 'success' : 'error'}>
                  {p.refundable ? '支持按比例退款' : '不可退款'}
                </Tag>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

// ─── 子组件：销售统计Tab ──────────────────────────────────────────────────────

function SalesStatsTab() {
  const [stats, setStats] = useState<CardStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [expiring, setExpiring] = useState<Array<{ card_no: string; card_name: string; expires_at: string; days_remaining: number; auto_renew: boolean }>>([]);

  const fetchStats = async () => {
    setLoading(true);
    try {
      const [statsRes, expiringRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/member/premium-memberships/stats`, { headers: { 'X-Tenant-ID': TENANT_ID } }),
        fetch(`${API_BASE}/api/v1/member/premium-memberships/expiring?days_ahead=7`, { headers: { 'X-Tenant-ID': TENANT_ID } }),
      ]);
      const statsJson = await statsRes.json();
      const expiringJson = await expiringRes.json();
      setStats(statsJson.data);
      setExpiring(expiringJson.data?.items || []);
    } catch {
      setStats({
        active_count: 142,
        sold_this_month: 28,
        expiring_soon: 7,
        total_revenue_fen: 8880000,
        total_revenue_yuan: 88800,
        by_type: { monthly: 35, quarterly: 52, annual: 48, lifetime: 7 },
      });
      setExpiring([
        { card_no: 'PMC-202604-A1B2', card_name: '年卡', expires_at: '2026-04-11', days_remaining: 5, auto_renew: false },
        { card_no: 'PMC-202604-C3D4', card_name: '季卡', expires_at: '2026-04-13', days_remaining: 7, auto_renew: true },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', paddingTop: 60 }} />;

  return (
    <div>
      {stats && (
        <>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="在售付费卡"
                  value={stats.active_count}
                  suffix="张"
                  prefix={<CheckCircleOutlined style={{ color: '#0F6E56' }} />}
                  valueStyle={{ color: '#0F6E56' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="本月售出"
                  value={stats.sold_this_month}
                  suffix="张"
                  prefix={<GiftOutlined style={{ color: '#FF6B35' }} />}
                  valueStyle={{ color: '#FF6B35' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="7天内到期"
                  value={stats.expiring_soon}
                  suffix="张"
                  prefix={<ClockCircleOutlined style={{ color: stats.expiring_soon > 0 ? '#BA7517' : '#B4B2A9' }} />}
                  valueStyle={{ color: stats.expiring_soon > 0 ? '#BA7517' : '#B4B2A9' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="累计收入"
                  value={stats.total_revenue_yuan}
                  prefix={<DollarOutlined style={{ color: '#185FA5' }} />}
                  suffix="元"
                  valueStyle={{ color: '#185FA5' }}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Card title="在售卡类型分布">
                <Row gutter={8}>
                  {[
                    { type: 'monthly', name: '月卡', color: '#185FA5' },
                    { type: 'quarterly', name: '季卡', color: '#0F6E56' },
                    { type: 'annual', name: '年卡', color: '#FF6B35' },
                    { type: 'lifetime', name: '终身卡', color: '#FFB800' },
                  ].map(t => (
                    <Col key={t.type} span={12} style={{ marginBottom: 12 }}>
                      <Card size="small" style={{ borderLeft: `3px solid ${t.color}` }}>
                        <Statistic
                          title={t.name}
                          value={stats.by_type[t.type as keyof typeof stats.by_type]}
                          suffix="张"
                          valueStyle={{ fontSize: 20, color: t.color }}
                        />
                      </Card>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>

            <Col span={12}>
              <Card
                title={
                  <Space>
                    <ClockCircleOutlined style={{ color: '#BA7517' }} />
                    <span>7天内到期预警</span>
                    {expiring.length > 0 && <Badge count={expiring.length} />}
                  </Space>
                }
              >
                {expiring.length === 0 ? (
                  <Alert type="success" message="近7天无到期卡" showIcon />
                ) : (
                  <List
                    size="small"
                    dataSource={expiring}
                    renderItem={item => (
                      <List.Item
                        extra={
                          item.auto_renew ? (
                            <Tag color="green">自动续费</Tag>
                          ) : (
                            <Tag color="orange">待提醒</Tag>
                          )
                        }
                      >
                        <List.Item.Meta
                          avatar={<Avatar icon={<CrownOutlined />} style={{ background: '#FF6B35' }} size="small" />}
                          title={<Text code>{item.card_no}</Text>}
                          description={
                            <Space>
                              <Tag>{item.card_name}</Tag>
                              <Text type="warning">{item.expires_at} 到期（剩余{item.days_remaining}天）</Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function PremiumCardPage() {
  const tabItems = [
    {
      key: 'cards',
      label: (
        <Space>
          <CrownOutlined />
          卡档案列表
        </Space>
      ),
      children: <CardListTab />,
    },
    {
      key: 'products',
      label: (
        <Space>
          <GiftOutlined />
          产品配置
        </Space>
      ),
      children: <ProductConfigTab />,
    },
    {
      key: 'stats',
      label: (
        <Space>
          <DollarOutlined />
          销售统计
        </Space>
      ),
      children: <SalesStatsTab />,
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          <Space>
            <CrownOutlined style={{ color: '#FFB800' }} />
            付费会员卡管理
          </Space>
        </Title>
        <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
          月卡/季卡/年卡/终身卡 — 独立产品体系，按剩余天数比例退款，与储值卡互补使用
        </Paragraph>
      </div>

      <Card>
        <Tabs defaultActiveKey="cards" items={tabItems} />
      </Card>
    </div>
  );
}
