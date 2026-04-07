/**
 * 全渠道订单中心 — Y-A12
 * 堂食 / 美团外卖 / 小程序自助 / 团餐企业 / 宴席预订 统一视图
 *
 * Admin 终端 · Ant Design 5.x + ProTable
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Drawer,
  Descriptions,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Input,
  Tabs,
  Divider,
  Empty,
  Skeleton,
} from 'antd';
import {
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  ShopOutlined,
  CarOutlined,
  MobileOutlined,
  TeamOutlined,
  CalendarOutlined,
} from '@ant-design/icons';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { ProTable, StatisticCard } from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface OmniOrder {
  order_id: string;
  channel: string;
  channel_label: string;
  channel_color: string;
  order_no: string;
  channel_order_id?: string | null;
  store_name?: string;
  store_id?: string;
  table_no?: string | null;
  customer_name?: string;
  customer_phone?: string;
  golden_id?: string;
  items_count: number;
  total_fen: number;
  discount_fen: number;
  paid_fen: number;
  payment_method?: string;
  status: string;
  status_label: string;
  created_at?: string;
  closed_at?: string;
}

interface OmniOrderDetail extends OmniOrder {
  items: Array<{ name: string; quantity: number; price_fen: number; notes: string }>;
  payment_records: Array<{ method: string; amount_fen: number; paid_at: string }>;
  channel_info: { channel: string; label: string; color: string; channel_order_id?: string };
  discount_detail: { total_discount_fen: number; discount_rate: number };
}

interface ChannelStat {
  channel: string;
  channel_label: string;
  channel_color: string;
  order_count: number;
  revenue_fen: number;
  avg_ticket_fen: number;
  growth_rate: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const CHANNEL_OPTIONS = [
  { value: 'all',        label: '全部渠道' },
  { value: 'dine_in',   label: '堂食' },
  { value: 'takeaway',  label: '美团外卖' },
  { value: 'miniapp',   label: '小程序自助' },
  { value: 'group_meal',label: '团餐企业' },
  { value: 'banquet',   label: '宴席预订' },
];

const STATUS_OPTIONS = [
  { value: 'all',      label: '全部状态' },
  { value: 'open',     label: '进行中' },
  { value: 'closed',   label: '已完成' },
  { value: 'cancelled',label: '已取消' },
];

const CHANNEL_TAB_ICONS: Record<string, React.ReactNode> = {
  all:        <ShopOutlined />,
  dine_in:    <ShopOutlined />,
  takeaway:   <CarOutlined />,
  miniapp:    <MobileOutlined />,
  group_meal: <TeamOutlined />,
  banquet:    <CalendarOutlined />,
};

const STATUS_TAG_COLOR: Record<string, string> = {
  open:      'processing',
  closed:    'success',
  cancelled: 'error',
  voided:    'default',
  pending:   'warning',
};

const PAYMENT_LABEL: Record<string, string> = {
  wechat:          '微信支付',
  alipay:          '支付宝',
  meituan_pay:     '美团支付',
  bank_transfer:   '银行转账',
  deposit_deduct:  '预付款抵扣',
  cash:            '现金',
};

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function fenToYuanShort(fen: number): string {
  if (fen >= 10_000_00) return `¥${(fen / 10_000_00).toFixed(1)}万`;
  return `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function formatGrowth(rate: number): React.ReactNode {
  const pct = (rate * 100).toFixed(1);
  const color = rate >= 0 ? '#0F6E56' : '#A32D2D';
  return <span style={{ color }}>{rate >= 0 ? '+' : ''}{pct}%</span>;
}

// ─── API 调用 ────────────────────────────────────────────────────────────────

const BASE = '/api/v1/trade/omni-orders';
const TENANT_ID = 'demo-tenant';

async function fetchOrders(params: {
  channel?: string;
  status?: string;
  store_id?: string;
  date_from?: string;
  date_to?: string;
  phone?: string;
  page: number;
  size: number;
}) {
  const qs = new URLSearchParams();
  if (params.channel && params.channel !== 'all') qs.set('channel', params.channel);
  if (params.status && params.status !== 'all') qs.set('status', params.status);
  if (params.store_id) qs.set('store_id', params.store_id);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  if (params.phone) qs.set('phone', params.phone);
  qs.set('page', String(params.page));
  qs.set('size', String(params.size));
  const resp = await fetch(`${BASE}?${qs}`, { headers: { 'X-Tenant-ID': TENANT_ID } });
  const json = await resp.json();
  return json.data as { items: OmniOrder[]; total: number; channel_summary: Record<string, number> };
}

async function fetchStats() {
  const resp = await fetch(`${BASE}/stats`, { headers: { 'X-Tenant-ID': TENANT_ID } });
  const json = await resp.json();
  return json.data as { channel_stats: ChannelStat[]; total_revenue_fen: number; total_order_count: number; overall_growth_rate: number };
}

async function fetchDetail(orderId: string) {
  const resp = await fetch(`${BASE}/${orderId}`, { headers: { 'X-Tenant-ID': TENANT_ID } });
  const json = await resp.json();
  return json.data as OmniOrderDetail;
}

async function searchOrders(q: string) {
  const resp = await fetch(`${BASE}/search?q=${encodeURIComponent(q)}&limit=20`, {
    headers: { 'X-Tenant-ID': TENANT_ID },
  });
  const json = await resp.json();
  return json.data as { items: OmniOrder[]; total: number };
}

// ─── 渠道汇总卡片行 ──────────────────────────────────────────────────────────

function ChannelStatCards({ stats }: { stats: ChannelStat[] }) {
  return (
    <Row gutter={12} style={{ marginBottom: 16 }}>
      {stats.map((s) => (
        <Col key={s.channel} flex="1">
          <Card size="small" bordered style={{ borderTop: `3px solid var(--ant-color-primary, #FF6B35)` }}>
            <Statistic
              title={
                <Space size={4}>
                  {CHANNEL_TAB_ICONS[s.channel]}
                  <span>{s.channel_label}</span>
                </Space>
              }
              value={s.revenue_fen / 100}
              prefix="¥"
              precision={0}
              valueStyle={{ fontSize: 18 }}
            />
            <Space size="small" style={{ marginTop: 4, fontSize: 12, color: '#5F5E5A' }}>
              <span>{s.order_count}单</span>
              <Divider type="vertical" />
              <span>客单{fenToYuan(s.avg_ticket_fen)}</span>
              <Divider type="vertical" />
              {formatGrowth(s.growth_rate)}
            </Space>
          </Card>
        </Col>
      ))}
    </Row>
  );
}

// ─── 订单详情抽屉 ────────────────────────────────────────────────────────────

function OrderDetailDrawer({
  orderId,
  open,
  onClose,
}: {
  orderId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<OmniOrderDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!orderId || !open) return;
    setLoading(true);
    setDetail(null);
    fetchDetail(orderId)
      .then(setDetail)
      .finally(() => setLoading(false));
  }, [orderId, open]);

  const cfg = detail ? {
    dine_in:    { color: 'blue',   label: '堂食' },
    takeaway:   { color: 'orange', label: '美团外卖' },
    miniapp:    { color: 'green',  label: '小程序自助' },
    group_meal: { color: 'purple', label: '团餐企业' },
    banquet:    { color: 'gold',   label: '宴席预订' },
  }[detail.channel] : null;

  return (
    <Drawer
      title={
        <Space>
          <span>订单详情</span>
          {detail && cfg && <Tag color={cfg.color}>{cfg.label}</Tag>}
          {detail && <Tag color={STATUS_TAG_COLOR[detail.status] || 'default'}>{detail.status_label}</Tag>}
        </Space>
      }
      width={560}
      open={open}
      onClose={onClose}
      bodyStyle={{ padding: '16px 24px' }}
    >
      {loading && <Skeleton active paragraph={{ rows: 8 }} />}
      {!loading && !detail && <Empty description="订单不存在" />}
      {!loading && detail && (
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {/* 基础信息 */}
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="订单号" span={2}>{detail.order_no}</Descriptions.Item>
            {detail.channel_order_id && (
              <Descriptions.Item label="平台单号" span={2}>{detail.channel_order_id}</Descriptions.Item>
            )}
            <Descriptions.Item label="门店">{detail.store_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="桌台/区域">{detail.table_no || '-'}</Descriptions.Item>
            <Descriptions.Item label="顾客">{detail.customer_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="电话">{detail.customer_phone || '-'}</Descriptions.Item>
            <Descriptions.Item label="Golden ID" span={2}>{detail.golden_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="下单时间" span={2}>
              {detail.created_at ? dayjs(detail.created_at).format('YYYY-MM-DD HH:mm') : '-'}
            </Descriptions.Item>
            {detail.closed_at && (
              <Descriptions.Item label="完成时间" span={2}>
                {dayjs(detail.closed_at).format('YYYY-MM-DD HH:mm')}
              </Descriptions.Item>
            )}
          </Descriptions>

          {/* 品项明细 */}
          <div>
            <Title level={5} style={{ marginBottom: 8 }}>品项明细</Title>
            <Table
              dataSource={detail.items}
              rowKey={(r) => r.name}
              size="small"
              pagination={false}
              columns={[
                { title: '菜品', dataIndex: 'name', key: 'name' },
                { title: '数量', dataIndex: 'quantity', key: 'quantity', width: 60, align: 'center' },
                { title: '单价', dataIndex: 'price_fen', key: 'price_fen', width: 90, align: 'right',
                  render: (v: number) => fenToYuan(v) },
                { title: '备注', dataIndex: 'notes', key: 'notes', render: (v: string) => v || '-' },
              ]}
              summary={() => (
                <Table.Summary.Row>
                  <Table.Summary.Cell index={0} colSpan={2}><Text strong>合计</Text></Table.Summary.Cell>
                  <Table.Summary.Cell index={2} align="right">
                    <Text type="danger" strong>{fenToYuan(detail.total_fen)}</Text>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={3} />
                </Table.Summary.Row>
              )}
            />
          </div>

          {/* 折扣与支付 */}
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="订单金额">{fenToYuan(detail.total_fen)}</Descriptions.Item>
            <Descriptions.Item label="折扣金额">
              <Text type="danger">-{fenToYuan(detail.discount_fen)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="折扣率">
              {(detail.discount_detail.discount_rate * 100).toFixed(1)}%
            </Descriptions.Item>
            <Descriptions.Item label="实付金额">
              <Text strong style={{ color: '#0F6E56' }}>{fenToYuan(detail.paid_fen)}</Text>
            </Descriptions.Item>
          </Descriptions>

          {/* 支付记录 */}
          {detail.payment_records.length > 0 && (
            <div>
              <Title level={5} style={{ marginBottom: 8 }}>支付记录</Title>
              {detail.payment_records.map((pr, idx) => (
                <div key={idx} style={{ display: 'flex', justifyContent: 'space-between',
                  padding: '6px 0', borderBottom: '1px solid #E8E6E1' }}>
                  <Text>{PAYMENT_LABEL[pr.method] || pr.method}</Text>
                  <Space>
                    <Text strong>{fenToYuan(pr.amount_fen)}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {pr.paid_at ? dayjs(pr.paid_at).format('HH:mm') : ''}
                    </Text>
                  </Space>
                </div>
              ))}
            </div>
          )}
        </Space>
      )}
    </Drawer>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function OmniOrderCenterPage() {
  const actionRef = useRef<ActionType>();

  // 筛选条件
  const [activeChannel, setActiveChannel] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterStore, setFilterStore] = useState<string>('');
  const [filterPhone, setFilterPhone] = useState<string>('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [searchQ, setSearchQ] = useState<string>('');

  // 统计数据
  const [statsData, setStatsData] = useState<{
    channel_stats: ChannelStat[];
    total_revenue_fen: number;
    total_order_count: number;
    overall_growth_rate: number;
  } | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // 渠道 Tab 订单数（由最近一次列表结果更新）
  const [channelCounts, setChannelCounts] = useState<Record<string, number>>({});

  // 详情抽屉
  const [detailOrderId, setDetailOrderId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 搜索模式结果
  const [searchResults, setSearchResults] = useState<OmniOrder[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);

  // 加载统计数据
  useEffect(() => {
    setStatsLoading(true);
    fetchStats()
      .then(setStatsData)
      .finally(() => setStatsLoading(false));
  }, []);

  const handleSearch = useCallback(async () => {
    if (!searchQ.trim()) {
      setSearchResults(null);
      return;
    }
    setSearchLoading(true);
    try {
      const res = await searchOrders(searchQ.trim());
      setSearchResults(res.items);
    } finally {
      setSearchLoading(false);
    }
  }, [searchQ]);

  const handleClearSearch = () => {
    setSearchQ('');
    setSearchResults(null);
  };

  const openDetail = (orderId: string) => {
    setDetailOrderId(orderId);
    setDrawerOpen(true);
  };

  // 渠道 Tab 配置
  const channelTabs = [
    { key: 'all',        label: '全部' },
    { key: 'dine_in',   label: '堂食' },
    { key: 'takeaway',  label: '外卖' },
    { key: 'miniapp',   label: '小程序' },
    { key: 'group_meal',label: '团餐' },
    { key: 'banquet',   label: '宴席' },
  ];

  // ProTable 列定义
  const columns: ProColumns<OmniOrder>[] = [
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 110,
      render: (_, r) => (
        <Tag color={r.channel_color}>{r.channel_label}</Tag>
      ),
    },
    {
      title: '订单号',
      dataIndex: 'order_no',
      width: 160,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 13 }}>{r.order_no}</Text>
          {r.channel_order_id && (
            <Text type="secondary" style={{ fontSize: 11 }}>{r.channel_order_id}</Text>
          )}
        </Space>
      ),
    },
    {
      title: '门店/桌台',
      dataIndex: 'store_name',
      width: 130,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 13 }}>{r.store_name || '-'}</Text>
          {r.table_no && <Text type="secondary" style={{ fontSize: 11 }}>桌：{r.table_no}</Text>}
        </Space>
      ),
    },
    {
      title: '顾客',
      dataIndex: 'customer_name',
      width: 120,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text>{r.customer_name || '-'}</Text>
          {r.customer_phone && (
            <Text type="secondary" style={{ fontSize: 11 }}>{r.customer_phone}</Text>
          )}
        </Space>
      ),
    },
    {
      title: '品项数',
      dataIndex: 'items_count',
      width: 70,
      align: 'center',
    },
    {
      title: '实付金额',
      dataIndex: 'paid_fen',
      width: 110,
      align: 'right',
      render: (v: number, r) => (
        <Space direction="vertical" size={0} style={{ textAlign: 'right' }}>
          <Text strong style={{ color: '#2C2C2A' }}>{fenToYuan(v)}</Text>
          {r.discount_fen > 0 && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              折扣 -{fenToYuan(r.discount_fen)}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '支付方式',
      dataIndex: 'payment_method',
      width: 100,
      render: (v: string) => PAYMENT_LABEL[v] || v || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => (
        <Badge
          status={
            r.status === 'closed' ? 'success' :
            r.status === 'open' ? 'processing' :
            r.status === 'cancelled' ? 'error' : 'default'
          }
          text={r.status_label}
        />
      ),
    },
    {
      title: '下单时间',
      dataIndex: 'created_at',
      width: 130,
      render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      valueType: 'option',
      width: 70,
      render: (_, r) => [
        <a key="detail" onClick={() => openDetail(r.order_id)}>
          <EyeOutlined /> 详情
        </a>,
      ],
    },
  ];

  return (
    <div style={{ padding: '24px', background: '#F8F7F5', minHeight: '100vh' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>全渠道订单中心</Title>
        <Text type="secondary">堂食 · 外卖 · 小程序 · 团餐 · 宴席 统一视图（Y-A12）</Text>
      </div>

      {/* 渠道汇总统计卡片 */}
      {statsLoading ? (
        <Skeleton active paragraph={{ rows: 2 }} style={{ marginBottom: 16 }} />
      ) : statsData ? (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <StatisticCard
                statistic={{
                  title: '今日总营业额',
                  value: statsData.total_revenue_fen / 100,
                  prefix: '¥',
                  precision: 0,
                  description: (
                    <Space>
                      <span style={{ fontSize: 12 }}>vs上期</span>
                      {formatGrowth(statsData.overall_growth_rate)}
                    </Space>
                  ),
                }}
              />
            </Col>
            <Col span={18}>
              <ChannelStatCards stats={statsData.channel_stats} />
            </Col>
          </Row>
        </>
      ) : null}

      {/* 主内容卡片 */}
      <Card bodyStyle={{ padding: 0 }}>
        {/* 渠道 Tab */}
        <Tabs
          activeKey={activeChannel}
          onChange={(k) => {
            setActiveChannel(k);
            setSearchResults(null);
            actionRef.current?.reload();
          }}
          style={{ padding: '0 16px', borderBottom: '1px solid #E8E6E1' }}
          items={channelTabs.map((t) => ({
            key: t.key,
            label: (
              <Space size={4}>
                {CHANNEL_TAB_ICONS[t.key]}
                <span>{t.label}</span>
                {channelCounts[t.key] !== undefined && (
                  <Badge count={channelCounts[t.key]} showZero={false}
                    style={{ backgroundColor: '#FF6B35' }} />
                )}
              </Space>
            ),
          }))}
        />

        <div style={{ padding: '16px 16px 0' }}>
          {/* 过滤器行 */}
          <Space wrap style={{ marginBottom: 12 }}>
            <Select
              value={filterStatus}
              onChange={(v) => { setFilterStatus(v); actionRef.current?.reload(); }}
              options={STATUS_OPTIONS}
              style={{ width: 120 }}
              placeholder="状态"
            />
            <Input
              placeholder="门店ID"
              value={filterStore}
              onChange={(e) => setFilterStore(e.target.value)}
              style={{ width: 140 }}
              allowClear
            />
            <Input
              placeholder="手机号/尾4位"
              value={filterPhone}
              onChange={(e) => setFilterPhone(e.target.value)}
              style={{ width: 140 }}
              allowClear
            />
            <RangePicker
              value={dateRange}
              onChange={(v) => setDateRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null)}
              placeholder={['开始日期', '结束日期']}
            />
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setSearchResults(null);
                actionRef.current?.reload();
              }}
            >
              刷新
            </Button>

            <Divider type="vertical" />

            {/* 快速搜索 */}
            <Input.Search
              placeholder="搜索：订单号/手机/桌台/顾客名/美团/宴席…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onSearch={handleSearch}
              loading={searchLoading}
              style={{ width: 280 }}
              allowClear
              onClear={handleClearSearch}
              enterButton={<SearchOutlined />}
            />
          </Space>

          {/* 搜索模式提示 */}
          {searchResults !== null && (
            <div style={{ marginBottom: 8, padding: '6px 8px',
              background: '#FFF3ED', borderRadius: 4, fontSize: 12 }}>
              搜索 "{searchQ}" 找到 {searchResults.length} 条结果
              <a style={{ marginLeft: 8, color: '#FF6B35' }} onClick={handleClearSearch}>
                清除搜索
              </a>
            </div>
          )}
        </div>

        {/* 订单表格 */}
        {searchResults !== null ? (
          // 搜索模式：直接显示搜索结果
          <Table<OmniOrder>
            dataSource={searchResults}
            columns={columns}
            rowKey="order_id"
            size="small"
            pagination={{ pageSize: 20 }}
            style={{ padding: '0 16px 16px' }}
            onRow={(r) => ({ onDoubleClick: () => openDetail(r.order_id) })}
            locale={{ emptyText: <Empty description="未找到匹配订单" /> }}
          />
        ) : (
          // 正常模式：ProTable 分页请求
          <ProTable<OmniOrder>
            actionRef={actionRef}
            columns={columns}
            rowKey="order_id"
            search={false}
            toolBarRender={false}
            tableAlertRender={false}
            pagination={{ defaultPageSize: 20, showSizeChanger: true }}
            style={{ padding: '0 16px 16px' }}
            request={async (params) => {
              const d_from = dateRange?.[0]?.format('YYYY-MM-DD');
              const d_to = dateRange?.[1]?.format('YYYY-MM-DD');
              const res = await fetchOrders({
                channel: activeChannel,
                status: filterStatus,
                store_id: filterStore || undefined,
                date_from: d_from,
                date_to: d_to,
                phone: filterPhone || undefined,
                page: params.current ?? 1,
                size: params.pageSize ?? 20,
              });
              setChannelCounts(res.channel_summary);
              return { data: res.items, total: res.total, success: true };
            }}
            onRow={(r) => ({ onDoubleClick: () => openDetail(r.order_id) })}
            locale={{ emptyText: <Empty description="暂无订单数据" /> }}
          />
        )}
      </Card>

      {/* 订单详情抽屉 */}
      <OrderDetailDrawer
        orderId={detailOrderId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
