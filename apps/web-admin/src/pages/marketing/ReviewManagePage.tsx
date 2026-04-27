/**
 * ReviewManagePage — AI评论管理中心 (S2W6)
 * 三大模块：评论管理 | NPS追踪 | 改进建议
 * API: tx-intel :8011
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  message,
  Modal,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CheckOutlined,
  CommentOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  LikeOutlined,
  DislikeOutlined,
  RobotOutlined,
  SendOutlined,
  SmileOutlined,
  FrownOutlined,
  MehOutlined,
  StarOutlined,
  BarChartOutlined,
  BulbOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

// ─── 类型定义 ───

interface AutoReply {
  id: string;
  review_id: string;
  platform: string;
  original_rating: number | null;
  original_text: string | null;
  generated_reply: string;
  brand_voice_config: Record<string, unknown>;
  model_used: string;
  status: 'draft' | 'approved' | 'posted' | 'failed' | 'expired';
  approved_by: string | null;
  approved_at: string | null;
  posted_at: string | null;
  failure_reason: string | null;
  created_at: string | null;
}

interface NPSDashboard {
  nps_score: number;
  total_sent: number;
  total_responded: number;
  response_rate: number;
  promoters: number;
  passives: number;
  detractors: number;
  avg_score: number;
  avg_response_time_sec: number;
  period_days: number;
  trend: NPSTrend[];
}

interface NPSTrend {
  date: string;
  nps_score: number;
  responded: number;
  promoters: number;
  detractors: number;
}

interface StoreNPS {
  store_id: string;
  nps_score: number;
  total_sent: number;
  total_responded: number;
  promoters: number;
  detractors: number;
  avg_score: number;
}

interface Detractor {
  survey_id: string;
  customer_id: string;
  store_id: string;
  order_id: string | null;
  nps_score: number | null;
  feedback_text: string | null;
  tags: string[];
  responded_at: string | null;
  channel: string;
}

interface Recommendation {
  theme: string;
  frequency: number;
  pct_of_negative: number;
  affected_stores: string[];
  example_reviews: { id: string; text: string; rating: number | null; source: string }[];
  recommendation_text: string;
}

interface BrandVoiceConfig {
  tone: string;
  style: string;
  keywords: string[];
}

// ─── 常量 ───

const PLATFORM_TAG: Record<string, { color: string; label: string }> = {
  dianping: { color: 'orange', label: '大众点评' },
  meituan: { color: 'gold', label: '美团' },
  douyin: { color: 'magenta', label: '抖音' },
  google: { color: 'blue', label: 'Google' },
  xiaohongshu: { color: 'red', label: '小红书' },
};

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '待审批' },
  approved: { color: 'processing', label: '已审批' },
  posted: { color: 'success', label: '已发布' },
  failed: { color: 'error', label: '发布失败' },
  expired: { color: 'default', label: '已过期' },
};

const TONE_OPTIONS = [
  { value: 'warm', label: '温暖亲切' },
  { value: 'professional', label: '专业正式' },
  { value: 'casual', label: '轻松随和' },
];

const EMPTY_NPS: NPSDashboard = {
  nps_score: 0,
  total_sent: 0,
  total_responded: 0,
  response_rate: 0,
  promoters: 0,
  passives: 0,
  detractors: 0,
  avg_score: 0,
  avg_response_time_sec: 0,
  period_days: 30,
  trend: [],
};

// ─── API 封装 ───

async function fetchAutoReplies(params?: {
  page?: number;
  size?: number;
  status?: string;
  platform?: string;
}): Promise<{ items: AutoReply[]; total: number }> {
  try {
    const qs = new URLSearchParams();
    if (params?.page) qs.set('page', String(params.page));
    if (params?.size) qs.set('size', String(params.size));
    if (params?.status) qs.set('status', params.status);
    if (params?.platform) qs.set('platform', params.platform);
    const query = qs.toString() ? `?${qs.toString()}` : '';
    return await txFetchData<{ items: AutoReply[]; total: number }>(
      `/api/v1/intel/reviews/auto-replies${query}`,
    );
  } catch {
    return { items: [], total: 0 };
  }
}

async function generateReply(reviewId: string): Promise<AutoReply | null> {
  try {
    return await txFetchData<AutoReply>(`/api/v1/intel/reviews/${reviewId}/generate-reply`, {
      method: 'POST',
    });
  } catch {
    return null;
  }
}

async function approveReply(replyId: string, approvedBy: string): Promise<boolean> {
  try {
    await txFetchData(`/api/v1/intel/reviews/${replyId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved_by: approvedBy }),
    });
    return true;
  } catch {
    return false;
  }
}

async function postReply(replyId: string): Promise<boolean> {
  try {
    await txFetchData(`/api/v1/intel/reviews/${replyId}/post`, { method: 'POST' });
    return true;
  } catch {
    return false;
  }
}

async function fetchNPSDashboard(days = 30): Promise<NPSDashboard> {
  try {
    return await txFetchData<NPSDashboard>(`/api/v1/intel/nps/dashboard?days=${days}`);
  } catch {
    return EMPTY_NPS;
  }
}

async function fetchNPSByStore(days = 30): Promise<StoreNPS[]> {
  try {
    const res = await txFetchData<{ stores: StoreNPS[] }>(`/api/v1/intel/nps/by-store?days=${days}`);
    return res?.stores ?? [];
  } catch {
    return [];
  }
}

async function fetchDetractors(days = 30): Promise<Detractor[]> {
  try {
    const res = await txFetchData<{ detractors: Detractor[] }>(`/api/v1/intel/nps/detractors?days=${days}`);
    return res?.detractors ?? [];
  } catch {
    return [];
  }
}

async function fetchBrandVoiceConfig(): Promise<BrandVoiceConfig> {
  try {
    return await txFetchData<BrandVoiceConfig>('/api/v1/intel/reviews/brand-voice-config');
  } catch {
    return { tone: 'warm', style: '亲切关怀', keywords: [] };
  }
}

async function updateBrandVoiceConfig(config: BrandVoiceConfig): Promise<boolean> {
  try {
    await txFetchData('/api/v1/intel/reviews/brand-voice-config', {
      method: 'PUT',
      body: JSON.stringify(config),
    });
    return true;
  } catch {
    return false;
  }
}

// ─── 工具函数 ───

function sentimentColor(rating: number | null): string {
  if (rating === null) return '#999';
  if (rating >= 4) return '#52c41a';
  if (rating >= 3) return '#faad14';
  return '#f5222d';
}

function sentimentIcon(rating: number | null) {
  if (rating === null) return <MehOutlined style={{ color: '#999' }} />;
  if (rating >= 4) return <SmileOutlined style={{ color: '#52c41a' }} />;
  if (rating >= 3) return <MehOutlined style={{ color: '#faad14' }} />;
  return <FrownOutlined style={{ color: '#f5222d' }} />;
}

function npsColor(score: number): string {
  if (score >= 50) return '#52c41a';
  if (score >= 0) return '#faad14';
  return '#f5222d';
}

// ─── 评论管理Tab ───

function ReviewTab() {
  const [replies, setReplies] = useState<AutoReply[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [platformFilter, setPlatformFilter] = useState<string | undefined>();
  const [selectedReply, setSelectedReply] = useState<AutoReply | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const loadReplies = useCallback(async () => {
    setLoading(true);
    const res = await fetchAutoReplies({ page, size: 20, status: statusFilter, platform: platformFilter });
    setReplies(res.items);
    setTotal(res.total);
    setLoading(false);
  }, [page, statusFilter, platformFilter]);

  useEffect(() => {
    loadReplies();
  }, [loadReplies]);

  const handleApprove = async (replyId: string) => {
    // TODO: 从auth context获取当前用户ID
    const ok = await approveReply(replyId, '00000000-0000-0000-0000-000000000000');
    if (ok) {
      message.success('审批通过');
      loadReplies();
    } else {
      message.error('审批失败');
    }
  };

  const handlePost = async (replyId: string) => {
    Modal.confirm({
      title: '确认发布',
      icon: <ExclamationCircleOutlined />,
      content: '确定将此回复发布到平台吗？',
      onOk: async () => {
        const ok = await postReply(replyId);
        if (ok) {
          message.success('发布成功');
          loadReplies();
        } else {
          message.error('发布失败');
        }
      },
    });
  };

  const columns = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 100,
      render: (p: string) => {
        const tag = PLATFORM_TAG[p] || { color: 'default', label: p };
        return <Tag color={tag.color}>{tag.label}</Tag>;
      },
    },
    {
      title: '评分',
      dataIndex: 'original_rating',
      width: 80,
      render: (r: number | null) => (
        <Space>
          {sentimentIcon(r)}
          <Text style={{ color: sentimentColor(r) }}>{r !== null ? `${r}星` : '-'}</Text>
        </Space>
      ),
    },
    {
      title: '原评价',
      dataIndex: 'original_text',
      ellipsis: true,
      render: (t: string | null) => <Text ellipsis={{ tooltip: t }}>{t || '-'}</Text>,
    },
    {
      title: 'AI回复',
      dataIndex: 'generated_reply',
      ellipsis: true,
      render: (t: string) => (
        <Space>
          <RobotOutlined style={{ color: '#1890ff' }} />
          <Text ellipsis={{ tooltip: t }}>{t}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const st = STATUS_MAP[s] || { color: 'default', label: s };
        return <Badge status={st.color as any} text={st.label} />;
      },
    },
    {
      title: '操作',
      width: 200,
      render: (_: unknown, record: AutoReply) => (
        <Space>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => {
              setSelectedReply(record);
              setDrawerOpen(true);
            }}
          >
            查看
          </Button>
          {record.status === 'draft' && (
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              onClick={() => handleApprove(record.id)}
            >
              审批
            </Button>
          )}
          {record.status === 'approved' && (
            <Button
              size="small"
              icon={<SendOutlined />}
              onClick={() => handlePost(record.id)}
            >
              发布
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        bodyStyle={{ padding: '12px 16px' }}
      >
        <Space>
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 120 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'draft', label: '待审批' },
              { value: 'approved', label: '已审批' },
              { value: 'posted', label: '已发布' },
              { value: 'failed', label: '失败' },
            ]}
          />
          <Select
            placeholder="平台"
            allowClear
            style={{ width: 120 }}
            value={platformFilter}
            onChange={setPlatformFilter}
            options={Object.entries(PLATFORM_TAG).map(([k, v]) => ({
              value: k,
              label: v.label,
            }))}
          />
        </Space>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={replies}
        loading={loading}
        pagination={{
          current: page,
          pageSize: 20,
          total,
          onChange: setPage,
          showTotal: (t) => `共 ${t} 条`,
        }}
      />

      <Drawer
        title="回复详情"
        width={600}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {selectedReply && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="平台">
              <Tag color={PLATFORM_TAG[selectedReply.platform]?.color}>
                {PLATFORM_TAG[selectedReply.platform]?.label || selectedReply.platform}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="评分">
              <Space>
                {sentimentIcon(selectedReply.original_rating)}
                {selectedReply.original_rating !== null ? `${selectedReply.original_rating}星` : '-'}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="原评价">
              <Paragraph>{selectedReply.original_text || '-'}</Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="AI回复">
              <Paragraph style={{ background: '#f0f5ff', padding: 12, borderRadius: 6 }}>
                <RobotOutlined style={{ marginRight: 8, color: '#1890ff' }} />
                {selectedReply.generated_reply}
              </Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="模型">{selectedReply.model_used}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Badge
                status={STATUS_MAP[selectedReply.status]?.color as any}
                text={STATUS_MAP[selectedReply.status]?.label}
              />
            </Descriptions.Item>
            {selectedReply.failure_reason && (
              <Descriptions.Item label="失败原因">
                <Text type="danger">{selectedReply.failure_reason}</Text>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="创建时间">{selectedReply.created_at || '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </>
  );
}

// ─── NPS追踪Tab ───

function NPSTab() {
  const [dashboard, setDashboard] = useState<NPSDashboard>(EMPTY_NPS);
  const [stores, setStores] = useState<StoreNPS[]>([]);
  const [detractors, setDetractors] = useState<Detractor[]>([]);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(30);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [d, s, det] = await Promise.all([
      fetchNPSDashboard(days),
      fetchNPSByStore(days),
      fetchDetractors(days),
    ]);
    setDashboard(d);
    setStores(s);
    setDetractors(det);
    setLoading(false);
  }, [days]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const storeColumns = [
    { title: '门店', dataIndex: 'store_id', ellipsis: true },
    {
      title: 'NPS',
      dataIndex: 'nps_score',
      sorter: (a: StoreNPS, b: StoreNPS) => a.nps_score - b.nps_score,
      render: (v: number) => <Text style={{ color: npsColor(v), fontWeight: 600 }}>{v}</Text>,
    },
    { title: '发送', dataIndex: 'total_sent' },
    { title: '回复', dataIndex: 'total_responded' },
    {
      title: '推荐者',
      dataIndex: 'promoters',
      render: (v: number) => <Tag color="green">{v}</Tag>,
    },
    {
      title: '贬损者',
      dataIndex: 'detractors',
      render: (v: number) => <Tag color="red">{v}</Tag>,
    },
  ];

  const detractorColumns = [
    { title: '客户', dataIndex: 'customer_id', ellipsis: true, width: 200 },
    {
      title: 'NPS评分',
      dataIndex: 'nps_score',
      width: 80,
      render: (v: number | null) => (
        <Tag color="red">{v !== null ? v : '-'}</Tag>
      ),
    },
    {
      title: '反馈',
      dataIndex: 'feedback_text',
      ellipsis: true,
      render: (t: string | null) => t || '-',
    },
    {
      title: '标签',
      dataIndex: 'tags',
      render: (tags: string[]) =>
        tags?.map((t) => (
          <Tag key={t} color="orange" style={{ marginBottom: 2 }}>
            {t}
          </Tag>
        )),
    },
    { title: '渠道', dataIndex: 'channel', width: 80 },
    {
      title: '回复时间',
      dataIndex: 'responded_at',
      width: 160,
      render: (t: string | null) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
  ];

  return (
    <Spin spinning={loading}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="NPS得分"
              value={dashboard.nps_score}
              valueStyle={{ color: npsColor(dashboard.nps_score), fontSize: 32 }}
              suffix={<span style={{ fontSize: 14 }}>/ 100</span>}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="回复率"
              value={dashboard.response_rate}
              suffix="%"
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="推荐者"
              value={dashboard.promoters}
              prefix={<LikeOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="被动者"
              value={dashboard.passives}
              prefix={<MehOutlined style={{ color: '#faad14' }} />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="贬损者"
              value={dashboard.detractors}
              prefix={<DislikeOutlined style={{ color: '#f5222d' }} />}
              valueStyle={{ color: '#f5222d' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="平均回复时间"
              value={Math.round(dashboard.avg_response_time_sec / 60)}
              suffix="分钟"
            />
          </Card>
        </Col>
      </Row>

      {/* NPS趋势（简化表格替代图表，生产环境接入ECharts） */}
      <Card
        title="NPS趋势"
        size="small"
        style={{ marginBottom: 16 }}
        extra={
          <Radio.Group value={days} onChange={(e) => setDays(e.target.value)} size="small">
            <Radio.Button value={7}>7天</Radio.Button>
            <Radio.Button value={30}>30天</Radio.Button>
            <Radio.Button value={90}>90天</Radio.Button>
          </Radio.Group>
        }
      >
        {dashboard.trend.length > 0 ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {dashboard.trend.map((t) => (
              <Card key={t.date} size="small" style={{ width: 140, textAlign: 'center' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t.date}
                </Text>
                <div style={{ fontSize: 24, fontWeight: 600, color: npsColor(t.nps_score) }}>
                  {t.nps_score}
                </div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  回复: {t.responded}
                </Text>
              </Card>
            ))}
          </div>
        ) : (
          <Empty description="暂无趋势数据" />
        )}
      </Card>

      {/* 门店NPS排名 */}
      <Card title="门店NPS排名" size="small" style={{ marginBottom: 16 }}>
        <Table
          rowKey="store_id"
          columns={storeColumns}
          dataSource={stores}
          pagination={false}
          size="small"
        />
      </Card>

      {/* 贬损者跟进 */}
      <Card
        title={
          <Space>
            <FrownOutlined style={{ color: '#f5222d' }} />
            贬损者跟进列表
          </Space>
        }
        size="small"
      >
        <Table
          rowKey="survey_id"
          columns={detractorColumns}
          dataSource={detractors}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 位` }}
          size="small"
        />
      </Card>
    </Spin>
  );
}

// ─── 改进建议Tab ───

function ImprovementTab() {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [voiceConfig, setVoiceConfig] = useState<BrandVoiceConfig>({
    tone: 'warm',
    style: '亲切关怀',
    keywords: [],
  });
  const [configLoading, setConfigLoading] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    loadRecommendations();
    loadBrandVoice();
  }, []);

  const loadRecommendations = async () => {
    setLoading(true);
    try {
      const res = await txFetchData<Recommendation[]>('/api/v1/intel/reviews/recommendations?days=30');
      setRecommendations(res ?? []);
    } catch {
      setRecommendations([]);
    }
    setLoading(false);
  };

  const loadBrandVoice = async () => {
    const config = await fetchBrandVoiceConfig();
    setVoiceConfig(config);
    form.setFieldsValue({
      tone: config.tone,
      style: config.style,
      keywords: config.keywords?.join(',') || '',
    });
  };

  const handleSaveConfig = async (values: Record<string, string>) => {
    setConfigLoading(true);
    const config: BrandVoiceConfig = {
      tone: values.tone,
      style: values.style,
      keywords: values.keywords
        ? values.keywords.split(',').map((k: string) => k.trim()).filter(Boolean)
        : [],
    };
    const ok = await updateBrandVoiceConfig(config);
    if (ok) {
      message.success('品牌语调已更新');
      setVoiceConfig(config);
    } else {
      message.error('更新失败');
    }
    setConfigLoading(false);
  };

  return (
    <Row gutter={16}>
      {/* 左：改进建议 */}
      <Col span={16}>
        <Card
          title={
            <Space>
              <BulbOutlined style={{ color: '#faad14' }} />
              改进建议（按差评频次排名）
            </Space>
          }
          size="small"
          loading={loading}
        >
          {recommendations.length > 0 ? (
            <List
              dataSource={recommendations}
              renderItem={(item, index) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <Row align="middle" style={{ marginBottom: 8 }}>
                      <Col flex="auto">
                        <Space>
                          <Tag
                            color={index < 3 ? 'red' : 'orange'}
                            style={{ fontSize: 14, padding: '2px 10px' }}
                          >
                            #{index + 1}
                          </Tag>
                          <Text strong style={{ fontSize: 15 }}>
                            {item.theme}
                          </Text>
                          <Text type="secondary">
                            {item.frequency}次 ({item.pct_of_negative}%)
                          </Text>
                        </Space>
                      </Col>
                      <Col>
                        <Progress
                          percent={item.pct_of_negative}
                          size="small"
                          style={{ width: 100 }}
                          strokeColor={index < 3 ? '#f5222d' : '#faad14'}
                          showInfo={false}
                        />
                      </Col>
                    </Row>

                    <Paragraph
                      style={{
                        background: '#fffbe6',
                        padding: '8px 12px',
                        borderRadius: 6,
                        marginBottom: 8,
                      }}
                    >
                      <BulbOutlined style={{ marginRight: 8, color: '#faad14' }} />
                      {item.recommendation_text}
                    </Paragraph>

                    {item.affected_stores.length > 0 && (
                      <div style={{ marginBottom: 4 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          影响门店：
                        </Text>
                        {item.affected_stores.slice(0, 5).map((s) => (
                          <Tag key={s} style={{ fontSize: 11 }}>
                            {s.substring(0, 8)}...
                          </Tag>
                        ))}
                        {item.affected_stores.length > 5 && (
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            +{item.affected_stores.length - 5}
                          </Text>
                        )}
                      </div>
                    )}

                    {item.example_reviews.length > 0 && (
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          示例评价：
                        </Text>
                        {item.example_reviews.map((r) => (
                          <div
                            key={r.id}
                            style={{
                              background: '#fafafa',
                              padding: '4px 8px',
                              borderRadius: 4,
                              marginTop: 4,
                              fontSize: 12,
                            }}
                          >
                            <CommentOutlined style={{ marginRight: 4 }} />
                            {r.text}
                            {r.rating !== null && (
                              <Tag color={sentimentColor(r.rating)} style={{ marginLeft: 8, fontSize: 11 }}>
                                {r.rating}星
                              </Tag>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </List.Item>
              )}
            />
          ) : (
            <Empty description="暂无改进建议" />
          )}
        </Card>
      </Col>

      {/* 右：品牌语调配置 */}
      <Col span={8}>
        <Card
          title={
            <Space>
              <StarOutlined style={{ color: '#1890ff' }} />
              品牌语调配置
            </Space>
          }
          size="small"
        >
          <Form
            form={form}
            layout="vertical"
            onFinish={handleSaveConfig}
            initialValues={{
              tone: voiceConfig.tone,
              style: voiceConfig.style,
              keywords: voiceConfig.keywords?.join(',') || '',
            }}
          >
            <Form.Item label="语调风格" name="tone">
              <Select options={TONE_OPTIONS} />
            </Form.Item>
            <Form.Item label="风格描述" name="style">
              <Input placeholder="例如：亲切关怀" />
            </Form.Item>
            <Form.Item label="品牌关键词" name="keywords">
              <TextArea rows={3} placeholder="逗号分隔，例如：感谢,期待再次光临,持续改进" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={configLoading} block>
                保存配置
              </Button>
            </Form.Item>
          </Form>

          <div
            style={{
              background: '#f0f5ff',
              padding: 12,
              borderRadius: 6,
              marginTop: 16,
            }}
          >
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前配置预览：
            </Text>
            <br />
            <Tag color="blue">{TONE_OPTIONS.find((t) => t.value === voiceConfig.tone)?.label || voiceConfig.tone}</Tag>
            <Text style={{ fontSize: 13 }}>{voiceConfig.style}</Text>
            <br />
            {voiceConfig.keywords?.map((kw) => (
              <Tag key={kw} style={{ marginTop: 4 }}>
                {kw}
              </Tag>
            ))}
          </div>
        </Card>
      </Col>
    </Row>
  );
}

// ─── 主页面 ───

export default function ReviewManagePage() {
  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <BarChartOutlined style={{ marginRight: 8 }} />
        AI 评论管理中心
      </Title>

      <Tabs
        defaultActiveKey="reviews"
        items={[
          {
            key: 'reviews',
            label: (
              <span>
                <CommentOutlined />
                评论管理
              </span>
            ),
            children: <ReviewTab />,
          },
          {
            key: 'nps',
            label: (
              <span>
                <SmileOutlined />
                NPS追踪
              </span>
            ),
            children: <NPSTab />,
          },
          {
            key: 'improvement',
            label: (
              <span>
                <BulbOutlined />
                改进建议
              </span>
            ),
            children: <ImprovementTab />,
          },
        ]}
      />
    </div>
  );
}
