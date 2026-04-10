/**
 * P3-05 企微SCRM私域Agent管理页面
 * 三个Tab：生日祝福 / 沉睡唤醒 / 智能回访
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
  Progress,
  Alert,
  Spin,
  Typography,
  Space,
  Badge,
  message,
  Statistic,
  Divider,
  Modal,
  List,
  Avatar,
  InputNumber,
  Segmented,
  Tooltip,
} from 'antd';
import {
  GiftOutlined,
  TeamOutlined,
  MessageOutlined,
  UserOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  PhoneOutlined,
  CalendarOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text, Paragraph } = Typography;

const API_BASE = 'http://localhost:8004';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface BirthdayMember {
  member_id: string;
  name: string;
  phone_masked: string;
  birthday: string;
  days_until: number;
  level: string;
  last_spend_fen: number;
  total_spend_fen: number;
  recommend_template: string;
  send_status: string;
  wecom_connected: boolean;
}

interface DormantMember {
  member_id: string;
  name: string;
  phone_masked: string;
  level: string;
  last_visit_date: string;
  dormant_days: number;
  total_spend_fen: number;
  avg_spend_per_visit_fen: number;
  visit_count: number;
  favorite_dish: string;
  predicted_response_rate: number;
  suggest_offer: string;
  wecom_connected: boolean;
  unsubscribed: boolean;
  wake_advice?: string;
  risk_level?: string;
}

interface PostOrderTask {
  task_id: string;
  order_id: string;
  member_name: string;
  store_name: string;
  order_time: string;
  spend_fen: number;
  dishes: string[];
  schedule_time: string;
  template: string;
  status: string;
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fmtPrice = (fen: number) => `¥${(fen / 100).toFixed(0)}`;

const LEVEL_COLORS: Record<string, string> = {
  super_vip: '#FF6B35',
  VIP: '#185FA5',
  regular: '#0F6E56',
};

const LEVEL_LABELS: Record<string, string> = {
  super_vip: '超级VIP',
  VIP: 'VIP',
  regular: '普通会员',
};

const TEMPLATE_LABELS: Record<string, string> = {
  default: '通用模板',
  vip: 'VIP专属',
  super_vip: '尊享定制',
  satisfaction: '满意度回访',
  recommend: '好友推荐',
  rebuy: '复购召回',
};

const STATUS_MAP: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  pending: { color: '#BA7517', icon: <ClockCircleOutlined />, label: '待发送' },
  sent: { color: '#185FA5', icon: <CheckCircleOutlined />, label: '已发送' },
  replied: { color: '#0F6E56', icon: <CheckCircleOutlined />, label: '已回复' },
  failed: { color: '#A32D2D', icon: <CloseCircleOutlined />, label: '发送失败' },
};

// ─── Tab1: 生日祝福 ──────────────────────────────────────────────────────────

function BirthdayTab() {
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<BirthdayMember[]>([]);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>('default');
  const [sending, setSending] = useState(false);
  const [daysAhead, setDaysAhead] = useState(7);

  const fetchMembers = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=${daysAhead}`);
      const json = await res.json();
      if (json.ok) setMembers(json.data.items);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchMembers(); }, [daysAhead]);

  const handleSend = async () => {
    if (selectedKeys.length === 0) {
      message.warning('请先选择要发送的会员');
      return;
    }
    setSending(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/growth/scrm-agent/birthday/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ member_ids: selectedKeys, message_template: selectedTemplate }),
      });
      const json = await res.json();
      if (json.ok) {
        const { success, failed, skipped } = json.data;
        message.success(`发送完成：成功 ${success} 条，失败 ${failed} 条，跳过 ${skipped} 条`);
        setSelectedKeys([]);
        fetchMembers();
      }
    } finally {
      setSending(false);
    }
  };

  // 按日期分组
  const grouped: Record<string, BirthdayMember[]> = {};
  members.forEach(m => {
    if (!grouped[m.birthday]) grouped[m.birthday] = [];
    grouped[m.birthday].push(m);
  });

  const columns: ColumnsType<BirthdayMember> = [
    {
      title: '会员',
      key: 'member',
      render: (_: unknown, row: BirthdayMember) => (
        <Space>
          <Avatar style={{ background: LEVEL_COLORS[row.level] || '#999', fontSize: 13 }}>
            {row.name[0]}
          </Avatar>
          <div>
            <Text strong>{row.name}</Text>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}><PhoneOutlined /> {row.phone_masked}</Text>
          </div>
        </Space>
      ),
    },
    {
      title: '生日',
      key: 'birthday',
      render: (_: unknown, row: BirthdayMember) => (
        <div>
          <Text><CalendarOutlined style={{ marginRight: 4, color: '#FF6B35' }} />{row.birthday}</Text>
          <br />
          <Tag color={row.days_until <= 2 ? 'red' : row.days_until <= 5 ? 'orange' : 'blue'}>
            还有 {row.days_until} 天
          </Tag>
        </div>
      ),
    },
    {
      title: '会员等级',
      dataIndex: 'level',
      render: (level: string) => (
        <Tag color={LEVEL_COLORS[level]} style={{ color: '#fff' }}>
          {LEVEL_LABELS[level] || level}
        </Tag>
      ),
    },
    {
      title: '最近消费',
      dataIndex: 'last_spend_fen',
      render: (fen: number) => <Text strong>{fmtPrice(fen)}</Text>,
    },
    {
      title: '推荐模板',
      dataIndex: 'recommend_template',
      render: (tpl: string) => <Tag>{TEMPLATE_LABELS[tpl] || tpl}</Tag>,
    },
    {
      title: '企微状态',
      dataIndex: 'wecom_connected',
      render: (connected: boolean) => connected
        ? <Badge status="success" text="已绑定" />
        : <Badge status="default" text="未绑定" />,
    },
  ];

  const TEMPLATE_OPTIONS = [
    { value: 'default', label: '通用模板 — 九折优惠' },
    { value: 'vip', label: 'VIP专属 — 生日礼券到账' },
    { value: 'super_vip', label: '尊享定制 — 总经理邀请' },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title="即将生日（7天内）"
              value={members.length}
              suffix="位会员"
              prefix={<GiftOutlined style={{ color: '#FF6B35' }} />}
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title="企微已绑定"
              value={members.filter(m => m.wecom_connected).length}
              suffix="位"
              prefix={<CheckCircleOutlined style={{ color: '#0F6E56' }} />}
              valueStyle={{ color: '#0F6E56' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title="今月生日转化率"
              value={63.2}
              suffix="%"
              prefix={<TrophyOutlined style={{ color: '#185FA5' }} />}
              valueStyle={{ color: '#185FA5' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title="生日会员列表"
        extra={
          <Space>
            <Text type="secondary">提前</Text>
            <Select
              value={daysAhead}
              onChange={setDaysAhead}
              options={[3, 5, 7, 14].map(d => ({ value: d, label: `${d}天` }))}
              style={{ width: 80 }}
              size="small"
            />
            <Divider type="vertical" />
            <Text type="secondary">消息模板</Text>
            <Select
              value={selectedTemplate}
              onChange={setSelectedTemplate}
              options={TEMPLATE_OPTIONS}
              style={{ width: 200 }}
              size="small"
            />
            <Button
              type="primary"
              icon={<GiftOutlined />}
              loading={sending}
              onClick={handleSend}
              disabled={selectedKeys.length === 0}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              批量发送 {selectedKeys.length > 0 ? `(${selectedKeys.length})` : ''}
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={members}
          rowKey="member_id"
          loading={loading}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys as string[]),
            getCheckboxProps: (record) => ({
              disabled: !record.wecom_connected,
            }),
          }}
          size="middle"
          pagination={false}
        />
      </Card>
    </div>
  );
}

// ─── Tab2: 沉睡唤醒 ──────────────────────────────────────────────────────────

function DormantTab() {
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<DormantMember[]>([]);
  const [dormantDays, setDormantDays] = useState(60);
  const [minSpend, setMinSpend] = useState(10000);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [offerType, setOfferType] = useState<string>('coupon');
  const [offerValue, setOfferValue] = useState<number>(2000);
  const [sending, setSending] = useState(false);

  const fetchMembers = async () => {
    setLoading(true);
    try {
      const url = `${API_BASE}/api/v1/growth/scrm-agent/dormant/list?dormant_days=${dormantDays}&min_historical_spend_fen=${minSpend}`;
      const res = await fetch(url);
      const json = await res.json();
      if (json.ok) setMembers(json.data.items);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchMembers(); }, [dormantDays, minSpend]);

  const handleWake = async () => {
    if (selectedKeys.length === 0) {
      message.warning('请先选择要唤醒的会员');
      return;
    }
    setSending(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/growth/scrm-agent/dormant/wake`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          member_ids: selectedKeys,
          offer_type: offerType,
          offer_value_fen: offerValue,
        }),
      });
      const json = await res.json();
      if (json.ok) {
        const { success, failed, skipped } = json.data;
        message.success(`唤醒任务发送完成：成功 ${success}，失败 ${failed}，跳过 ${skipped}`);
        setSelectedKeys([]);
      }
    } finally {
      setSending(false);
    }
  };

  const getRiskColor = (risk?: string) => {
    if (risk === 'high') return '#A32D2D';
    if (risk === 'medium') return '#BA7517';
    return '#0F6E56';
  };

  const columns: ColumnsType<DormantMember> = [
    {
      title: '会员',
      key: 'member',
      render: (_: unknown, row: DormantMember) => (
        <Space>
          <Avatar style={{ background: LEVEL_COLORS[row.level] || '#999' }}>
            {row.name[0]}
          </Avatar>
          <div>
            <Text strong>{row.name}</Text>
            <Tag color={LEVEL_COLORS[row.level]} style={{ marginLeft: 6, color: '#fff', fontSize: 11 }}>
              {LEVEL_LABELS[row.level] || row.level}
            </Tag>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>{row.phone_masked}</Text>
          </div>
        </Space>
      ),
    },
    {
      title: '最近消费',
      key: 'last_visit',
      render: (_: unknown, row: DormantMember) => (
        <div>
          <Text>{row.last_visit_date}</Text>
          <br />
          <Tag color={row.dormant_days > 180 ? 'red' : row.dormant_days > 90 ? 'orange' : 'gold'}>
            沉睡 {row.dormant_days} 天
          </Tag>
        </div>
      ),
    },
    {
      title: '历史消费',
      key: 'spend',
      render: (_: unknown, row: DormantMember) => (
        <div>
          <Text strong style={{ color: '#FF6B35' }}>{fmtPrice(row.total_spend_fen)}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>均消 {fmtPrice(row.avg_spend_per_visit_fen)} / 次</Text>
        </div>
      ),
    },
    {
      title: '常点菜品',
      dataIndex: 'favorite_dish',
      render: (dish: string) => <Tag>{dish}</Tag>,
    },
    {
      title: '预测响应率',
      dataIndex: 'predicted_response_rate',
      render: (rate: number, row: DormantMember) => (
        <div style={{ minWidth: 120 }}>
          <Progress
            percent={Math.round(rate * 100)}
            size="small"
            strokeColor={rate >= 0.30 ? '#0F6E56' : rate >= 0.15 ? '#BA7517' : '#A32D2D'}
            format={(p) => `${p}%`}
          />
          <Text
            style={{ fontSize: 11, color: getRiskColor(row.risk_level) }}
          >
            {row.wake_advice || ''}
          </Text>
        </div>
      ),
    },
    {
      title: '建议优惠',
      dataIndex: 'suggest_offer',
      render: (offer: string, row: DormantMember) => (
        row.dormant_days > 180
          ? <Tag color="red">{offer}</Tag>
          : <Tag color="blue">{offer}</Tag>
      ),
    },
  ];

  return (
    <div>
      {/* 过滤器 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={24} align="middle">
          <Col>
            <Text strong>沉睡天数 ≥ </Text>
            <Select
              value={dormantDays}
              onChange={setDormantDays}
              options={[60, 90, 120, 180].map(d => ({ value: d, label: `${d}天` }))}
              style={{ width: 100, marginLeft: 8 }}
            />
          </Col>
          <Col>
            <Text strong>历史消费 ≥ </Text>
            <Select
              value={minSpend}
              onChange={setMinSpend}
              options={[5000, 10000, 30000, 50000].map(v => ({ value: v, label: fmtPrice(v) }))}
              style={{ width: 100, marginLeft: 8 }}
            />
          </Col>
          <Col flex="auto" />
          <Col>
            <Space>
              <Text strong>优惠类型</Text>
              <Segmented
                value={offerType}
                onChange={(v) => setOfferType(v as string)}
                options={[
                  { label: '优惠券', value: 'coupon' },
                  { label: '赠积分', value: 'points' },
                  { label: '免费菜', value: 'free_dish' },
                ]}
              />
              <Text strong>金额</Text>
              <InputNumber
                value={offerValue}
                onChange={(v) => setOfferValue(v || 2000)}
                min={500}
                max={50000}
                step={500}
                formatter={(v) => `¥ ${Math.round((v || 0) / 100)}`}
                style={{ width: 90 }}
              />
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={sending}
                onClick={handleWake}
                disabled={selectedKeys.length === 0}
                style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
              >
                发送唤醒 {selectedKeys.length > 0 ? `(${selectedKeys.length})` : ''}
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Alert
        type="warning"
        showIcon
        message="沉睡超180天会员响应率极低（<15%），系统已自动建议跳过，强行发送有骚扰风险。"
        style={{ marginBottom: 12 }}
      />

      <Card title={`沉睡会员列表（${members.length} 位）`}>
        <Table
          columns={columns}
          dataSource={members}
          rowKey="member_id"
          loading={loading}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys as string[]),
            getCheckboxProps: (record) => ({
              disabled: record.unsubscribed || record.dormant_days > 180,
            }),
          }}
          size="middle"
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  );
}

// ─── Tab3: 智能回访 ──────────────────────────────────────────────────────────

interface PostOrderStats {
  tasks_total: number;
  tasks_sent: number;
  reply_rate: number;
  conversion_rate: number;
  revenue_from_conversion_fen: number;
  roi: number;
  by_template: Record<string, { sent: number; replied: number; reply_rate: number; converted: number }>;
  pending_today: PostOrderTask[];
}

function PostOrderTab() {
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<PostOrderStats | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/v1/growth/scrm-agent/post-order/stats`)
      .then(r => r.json())
      .then(json => { if (json.ok) setStats(json.data); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />;
  if (!stats) return null;

  const funnelStages = [
    { label: '已发送', value: stats.tasks_sent, color: '#185FA5' },
    { label: '已回复', value: Math.round(stats.tasks_sent * stats.reply_rate), color: '#0F6E56' },
    { label: '已转化', value: Math.round(stats.tasks_sent * stats.conversion_rate), color: '#FF6B35' },
  ];
  const maxVal = funnelStages[0].value;

  const pendingColumns: ColumnsType<PostOrderTask> = [
    {
      title: '会员',
      dataIndex: 'member_name',
      render: (name: string) => <Space><UserOutlined /><Text strong>{name}</Text></Space>,
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      ellipsis: true,
    },
    {
      title: '就餐时间',
      dataIndex: 'order_time',
      render: (t: string) => <Text type="secondary">{t}</Text>,
    },
    {
      title: '消费金额',
      dataIndex: 'spend_fen',
      render: (fen: number) => <Text strong style={{ color: '#FF6B35' }}>{fmtPrice(fen)}</Text>,
    },
    {
      title: '模板',
      dataIndex: 'template',
      render: (t: string) => <Tag>{TEMPLATE_LABELS[t] || t}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (status: string) => {
        const s = STATUS_MAP[status] || STATUS_MAP.pending;
        return <Badge status={status === 'replied' ? 'success' : status === 'sent' ? 'processing' : 'warning'} text={s.label} />;
      },
    },
    {
      title: '回访时间',
      dataIndex: 'schedule_time',
      render: (t: string) => <Text type="secondary" style={{ fontSize: 12 }}>{t}</Text>,
    },
  ];

  const TEMPLATE_DESCS: Record<string, string> = {
    satisfaction: '感谢光临！您刚才在{store}的就餐体验如何？点击评价（1分钟），即可获得下次优惠：[链接]',
    recommend: '好友推荐更优惠！您可以将{store}分享给好友，好友首单后您可获积分奖励：[分享链接]',
    rebuy: '您上次点的{dish}很受欢迎！今日新鲜到货，欢迎再来：[预订链接]',
  };

  return (
    <div>
      {/* 漏斗统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={16}>
          <Card title="近30天回访ROI漏斗" size="small">
            <div style={{ padding: '12px 0' }}>
              {funnelStages.map((stage, idx) => (
                <div key={stage.label} style={{ marginBottom: 12 }}>
                  <Row align="middle" gutter={12}>
                    <Col style={{ width: 60 }}>
                      <Text type="secondary" style={{ fontSize: 13 }}>{stage.label}</Text>
                    </Col>
                    <Col flex="auto">
                      <div
                        style={{
                          height: 28,
                          width: `${(stage.value / maxVal) * 100}%`,
                          background: stage.color,
                          borderRadius: 4,
                          minWidth: 40,
                          display: 'flex',
                          alignItems: 'center',
                          paddingLeft: 8,
                          transition: 'width 0.6s ease',
                        }}
                      >
                        <Text style={{ color: '#fff', fontWeight: 600, fontSize: 13 }}>
                          {stage.value.toLocaleString()}
                        </Text>
                      </div>
                    </Col>
                    {idx < funnelStages.length - 1 && (
                      <Col style={{ width: 70 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          转化↓ {idx === 0
                            ? `${(stats.reply_rate * 100).toFixed(1)}%`
                            : `${(stats.conversion_rate / stats.reply_rate * 100).toFixed(1)}%`}
                        </Text>
                      </Col>
                    )}
                  </Row>
                </div>
              ))}
            </div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ height: '100%' }}>
            <Statistic
              title="回访带来营收"
              value={fmtPrice(stats.revenue_from_conversion_fen)}
              valueStyle={{ color: '#FF6B35', fontSize: 24 }}
            />
            <Divider style={{ margin: '12px 0' }} />
            <Statistic
              title="回访ROI"
              value={stats.roi}
              suffix="x"
              valueStyle={{ color: '#0F6E56', fontSize: 20 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 各模板效果 */}
      <Card title="各回访模板效果对比" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {Object.entries(stats.by_template).map(([tpl, tplStats]) => (
            <Col span={8} key={tpl}>
              <Card
                size="small"
                style={{ border: '1px solid #E8E6E1', borderRadius: 8 }}
                title={<Tag color="#185FA5">{TEMPLATE_LABELS[tpl] || tpl}</Tag>}
              >
                <Paragraph style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 8 }}>
                  {TEMPLATE_DESCS[tpl]}
                </Paragraph>
                <Row gutter={8}>
                  <Col span={8}><Statistic title="发送" value={tplStats.sent} valueStyle={{ fontSize: 16 }} /></Col>
                  <Col span={8}><Statistic title="回复" value={tplStats.replied} valueStyle={{ fontSize: 16, color: '#0F6E56' }} /></Col>
                  <Col span={8}><Statistic title="转化" value={tplStats.converted} valueStyle={{ fontSize: 16, color: '#FF6B35' }} /></Col>
                </Row>
                <Progress
                  percent={Math.round(tplStats.reply_rate * 100)}
                  size="small"
                  strokeColor="#185FA5"
                  format={p => `回复率 ${p}%`}
                  style={{ marginTop: 8 }}
                />
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* 今日待回访订单 */}
      <Card title={<Space><MessageOutlined style={{ color: '#FF6B35' }} />今日待回访订单</Space>}>
        <Table
          columns={pendingColumns}
          dataSource={stats.pending_today}
          rowKey="task_id"
          size="middle"
          pagination={false}
        />
      </Card>
    </div>
  );
}

// ─── 整体效果汇总 ─────────────────────────────────────────────────────────────

function PerformanceBar() {
  const [data, setData] = useState<{
    birthday: { sent: number; conversion_rate: number; revenue_fen: number; trend: string };
    dormant_wake: { touched: number; awaken_rate: number; roi: number; trend: string };
    post_order: { sent: number; reply_rate: number; repurchase_lift: number; trend: string };
    total_revenue_fen: number;
    overall_roi: number;
  } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/growth/scrm-agent/performance`)
      .then(r => r.json())
      .then(json => { if (json.ok) setData(json.data); });
  }, []);

  if (!data) return null;

  return (
    <Alert
      type="info"
      showIcon
      icon={<TrophyOutlined />}
      message={
        <Row gutter={24} style={{ width: '100%' }}>
          <Col>
            <Text strong>本月SCRM总营收：</Text>
            <Text strong style={{ color: '#FF6B35', fontSize: 16 }}>{fmtPrice(data.total_revenue_fen)}</Text>
          </Col>
          <Col>
            <Text>生日祝福转化率：</Text>
            <Text strong style={{ color: '#0F6E56' }}>{(data.birthday.conversion_rate * 100).toFixed(1)}%</Text>
            <Text type="secondary" style={{ fontSize: 12 }}> {data.birthday.trend}</Text>
          </Col>
          <Col>
            <Text>沉睡唤醒ROI：</Text>
            <Text strong style={{ color: '#0F6E56' }}>{data.dormant_wake.roi}x</Text>
            <Text type="secondary" style={{ fontSize: 12 }}> {data.dormant_wake.trend}</Text>
          </Col>
          <Col>
            <Text>回访复购提升：</Text>
            <Text strong style={{ color: '#0F6E56' }}>+{(data.post_order.repurchase_lift * 100).toFixed(1)}%</Text>
            <Text type="secondary" style={{ fontSize: 12 }}> {data.post_order.trend}</Text>
          </Col>
          <Col>
            <Text>整体ROI：</Text>
            <Text strong style={{ color: '#FF6B35', fontSize: 15 }}>{data.overall_roi}x</Text>
          </Col>
        </Row>
      }
      style={{ marginBottom: 16 }}
    />
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function SCRMAgentPage() {
  const tabItems = [
    {
      key: 'birthday',
      label: (
        <Space>
          <GiftOutlined />
          生日祝福
        </Space>
      ),
      children: <BirthdayTab />,
    },
    {
      key: 'dormant',
      label: (
        <Space>
          <TeamOutlined />
          沉睡唤醒
        </Space>
      ),
      children: <DormantTab />,
    },
    {
      key: 'post_order',
      label: (
        <Space>
          <MessageOutlined />
          智能回访
        </Space>
      ),
      children: <PostOrderTab />,
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0, color: '#2C2C2A' }}>
          企微SCRM私域Agent
        </Title>
        <Text type="secondary">
          生日祝福 · 沉睡唤醒 · 订单后回访 — 自动化精准触达，驱动会员复购与留存
        </Text>
      </div>

      <PerformanceBar />

      <Tabs
        defaultActiveKey="birthday"
        items={tabItems}
        size="large"
        style={{ background: '#fff', padding: '0 16px', borderRadius: 8 }}
      />
    </div>
  );
}
