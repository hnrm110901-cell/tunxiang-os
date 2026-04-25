/**
 * GeoSEOPage — GEO搜索优化仪表盘
 * 五大模块：整体SEO评分 / 门店档案列表 / AI引用监测 / 档案完整度 / 操作按钮
 * API: tx-intel :8011
 */
import { useRef, useState, useEffect, useCallback } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
} from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  message,
  Modal,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  Input,
  Select,
} from 'antd';
import {
  SearchOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  GlobalOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;

// ─── 类型 ──────────────────────────────────

interface DashboardData {
  total_profiles: number;
  stores_with_profiles: number;
  avg_seo_score: number;
  score_distribution: { high: number; mid: number; low: number };
  citation_rate: number;
  total_citation_checks: number;
  total_mentions_found: number;
  platform_breakdown: PlatformStat[];
}

interface PlatformStat {
  platform: string;
  profile_count: number;
  avg_score: number;
  citations_found: number;
}

interface ProfileItem {
  store_id: string;
  store_name: string;
  platform: string;
  seo_score: number;
  address: string;
  phone: string;
  cuisine_type: string;
  citation_found: boolean;
  updated_at: string;
}

interface CitationItem {
  id: string;
  query: string;
  platform: string;
  mention_found: boolean;
  mention_text: string | null;
  mention_position: number | null;
  competitor_mentions: { name: string; position: number }[];
  sentiment: string;
  checked_at: string;
  check_round: number;
}

interface OptimizeSuggestion {
  field: string;
  message: string;
  points: number;
}

// ─── 常量 ──────────────────────────────────

const EMPTY_DASHBOARD: DashboardData = {
  total_profiles: 0,
  stores_with_profiles: 0,
  avg_seo_score: 0,
  score_distribution: { high: 0, mid: 0, low: 0 },
  citation_rate: 0,
  total_citation_checks: 0,
  total_mentions_found: 0,
  platform_breakdown: [],
};

const PLATFORM_LABELS: Record<string, string> = {
  google: 'Google',
  baidu: '百度',
  chatgpt: 'ChatGPT',
  perplexity: 'Perplexity',
  xiaohongshu: '小红书',
  dianping: '大众点评',
  google_ai: 'Google AI',
  baidu_ai: '百度AI',
};

const SENTIMENT_COLORS: Record<string, string> = {
  positive: 'green',
  neutral: 'blue',
  negative: 'red',
};

// ─── 辅助函数 ──────────────────────────────

function scoreColor(score: number): string {
  if (score >= 80) return '#52c41a';
  if (score >= 50) return '#faad14';
  return '#f5222d';
}

// ─── 主组件 ──────────────────────────────────

export default function GeoSEOPage() {
  const [dashboard, setDashboard] = useState<DashboardData>(EMPTY_DASHBOARD);
  const [loading, setLoading] = useState(false);
  const [citationQuery, setCitationQuery] = useState('');
  const [citationPlatform, setCitationPlatform] = useState('chatgpt');
  const [optimizeModal, setOptimizeModal] = useState<{
    visible: boolean;
    storeId: string;
    storeName: string;
    suggestions: OptimizeSuggestion[];
    currentScore: number;
    potentialScore: number;
  }>({ visible: false, storeId: '', storeName: '', suggestions: [], currentScore: 0, potentialScore: 0 });

  const profileTableRef = useRef<ActionType>();
  const citationTableRef = useRef<ActionType>();

  // ─── 加载仪表盘 ────────────────────

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const res = await txFetchData('/api/v1/intel/geo-seo/dashboard');
      if (res.ok) setDashboard(res.data);
    } catch {
      message.error('仪表盘加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDashboard(); }, [fetchDashboard]);

  // ─── 生成档案 ─────────────────────

  const handleGenerateProfile = async (storeId: string) => {
    try {
      const res = await txFetchData(`/api/v1/intel/geo-seo/profile/${storeId}`, { method: 'POST' });
      if (res.ok) {
        message.success(`档案已生成，SEO评分: ${res.data.seo_score}`);
        profileTableRef.current?.reload();
        fetchDashboard();
      } else {
        message.error(res.error?.message || '生成失败');
      }
    } catch {
      message.error('请求失败');
    }
  };

  // ─── 引用检测 ─────────────────────

  const handleCheckCitation = async () => {
    if (!citationQuery.trim()) {
      message.warning('请输入查询语句');
      return;
    }
    try {
      const res = await txFetchData('/api/v1/intel/geo-seo/citation-check', {
        method: 'POST',
        body: JSON.stringify({ query: citationQuery, platform: citationPlatform }),
      });
      if (res.ok) {
        const found = res.data.mention_found;
        message.info(found ? `品牌被引用！位置 #${res.data.mention_position}` : '未被引用');
        citationTableRef.current?.reload();
        fetchDashboard();
      }
    } catch {
      message.error('检测失败');
    }
  };

  // ─── 优化建议 ─────────────────────

  const handleOptimize = async (storeId: string, storeName: string) => {
    try {
      const res = await txFetchData(`/api/v1/intel/geo-seo/optimize/${storeId}`, { method: 'POST' });
      if (res.ok) {
        setOptimizeModal({
          visible: true,
          storeId,
          storeName,
          suggestions: res.data.suggestions,
          currentScore: res.data.current_score,
          potentialScore: res.data.potential_score,
        });
      }
    } catch {
      message.error('获取建议失败');
    }
  };

  // ─── 档案列表列定义 ────────────────

  const profileColumns: ProColumns<ProfileItem>[] = [
    { title: '门店', dataIndex: 'store_name', width: 160, ellipsis: true },
    {
      title: '平台', dataIndex: 'platform', width: 100,
      render: (_, r) => <Tag>{PLATFORM_LABELS[r.platform] || r.platform}</Tag>,
    },
    {
      title: 'SEO评分', dataIndex: 'seo_score', width: 140, sorter: true,
      render: (_, r) => (
        <Space>
          <Progress
            type="circle"
            percent={r.seo_score}
            size={40}
            strokeColor={scoreColor(r.seo_score)}
            format={(p) => `${p}`}
          />
        </Space>
      ),
    },
    {
      title: '被引用', dataIndex: 'citation_found', width: 80,
      render: (_, r) => r.citation_found
        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
        : <CloseCircleOutlined style={{ color: '#ccc' }} />,
    },
    { title: '地址', dataIndex: 'address', width: 200, ellipsis: true },
    { title: '菜系', dataIndex: 'cuisine_type', width: 100 },
    {
      title: '操作', width: 180,
      render: (_, r) => (
        <Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => handleGenerateProfile(r.store_id)}>
            刷新
          </Button>
          <Button size="small" type="link" icon={<RocketOutlined />} onClick={() => handleOptimize(r.store_id, r.store_name || '')}>
            优化
          </Button>
        </Space>
      ),
    },
  ];

  // ─── 引用列表列定义 ────────────────

  const citationColumns: ProColumns<CitationItem>[] = [
    { title: '查询语句', dataIndex: 'query', width: 220, ellipsis: true },
    {
      title: '平台', dataIndex: 'platform', width: 110,
      render: (_, r) => <Tag>{PLATFORM_LABELS[r.platform] || r.platform}</Tag>,
    },
    {
      title: '引用', dataIndex: 'mention_found', width: 80,
      render: (_, r) => r.mention_found
        ? <Badge status="success" text="是" />
        : <Badge status="default" text="否" />,
    },
    { title: '位置', dataIndex: 'mention_position', width: 70, render: (_, r) => r.mention_position ? `#${r.mention_position}` : '-' },
    {
      title: '情感', dataIndex: 'sentiment', width: 80,
      render: (_, r) => <Tag color={SENTIMENT_COLORS[r.sentiment]}>{r.sentiment}</Tag>,
    },
    { title: '引用文本', dataIndex: 'mention_text', width: 260, ellipsis: true },
    { title: '轮次', dataIndex: 'check_round', width: 70 },
    { title: '检测时间', dataIndex: 'checked_at', width: 160, valueType: 'dateTime' },
  ];

  // ─── 渲染 ─────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}><GlobalOutlined /> GEO搜索优化</Title>

      {/* ── 顶部指标卡片 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="平均SEO评分" value={dashboard.avg_seo_score} suffix="/ 100"
              valueStyle={{ color: scoreColor(dashboard.avg_seo_score) }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="门店档案数" value={dashboard.stores_with_profiles} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="引用率" value={dashboard.citation_rate} suffix="%" precision={1}
              valueStyle={{ color: dashboard.citation_rate > 30 ? '#52c41a' : '#faad14' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="引用检测次数" value={dashboard.total_citation_checks} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="总引用数" value={dashboard.total_mentions_found} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="总档案数" value={dashboard.total_profiles} />
          </Card>
        </Col>
      </Row>

      {/* ── 评分分布 + 平台分解 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card title="评分分布" loading={loading}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label={<Tag color="green">优秀 (≥80)</Tag>}>
                {dashboard.score_distribution.high} 个
              </Descriptions.Item>
              <Descriptions.Item label={<Tag color="orange">中等 (50-79)</Tag>}>
                {dashboard.score_distribution.mid} 个
              </Descriptions.Item>
              <Descriptions.Item label={<Tag color="red">待优化 (&lt;50)</Tag>}>
                {dashboard.score_distribution.low} 个
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col span={16}>
          <Card title="平台分解" loading={loading}>
            <Table
              dataSource={dashboard.platform_breakdown}
              rowKey="platform"
              size="small"
              pagination={false}
              columns={[
                { title: '平台', dataIndex: 'platform', render: (v: string) => PLATFORM_LABELS[v] || v },
                { title: '档案数', dataIndex: 'profile_count' },
                { title: '平均分', dataIndex: 'avg_score', render: (v: number) => <Text style={{ color: scoreColor(v) }}>{v}</Text> },
                { title: '被引用', dataIndex: 'citations_found' },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* ── 标签页：档案 / 引用 ── */}
      <Tabs defaultActiveKey="profiles" items={[
        {
          key: 'profiles',
          label: '门店档案',
          children: (
            <ProTable<ProfileItem>
              actionRef={profileTableRef}
              columns={profileColumns}
              rowKey={(r) => `${r.store_id}-${r.platform}`}
              request={async (params) => {
                const res = await txFetchData(
                  `/api/v1/intel/geo-seo/profiles?page=${params.current || 1}&size=${params.pageSize || 20}`
                );
                return {
                  data: res.ok ? res.data.items : [],
                  total: res.ok ? res.data.total : 0,
                  success: res.ok,
                };
              }}
              search={false}
              pagination={{ defaultPageSize: 20 }}
              headerTitle="门店GEO档案"
              toolBarRender={() => [
                <Button key="refresh" icon={<ReloadOutlined />} onClick={() => { profileTableRef.current?.reload(); fetchDashboard(); }}>
                  刷新
                </Button>,
              ]}
            />
          ),
        },
        {
          key: 'citations',
          label: 'AI引用监测',
          children: (
            <>
              <Card size="small" style={{ marginBottom: 16 }}>
                <Space>
                  <Input
                    placeholder="输入查询语句，如：长沙最好的海鲜餐厅"
                    value={citationQuery}
                    onChange={(e) => setCitationQuery(e.target.value)}
                    style={{ width: 360 }}
                    prefix={<SearchOutlined />}
                  />
                  <Select
                    value={citationPlatform}
                    onChange={setCitationPlatform}
                    style={{ width: 140 }}
                    options={[
                      { label: 'ChatGPT', value: 'chatgpt' },
                      { label: 'Perplexity', value: 'perplexity' },
                      { label: 'Google AI', value: 'google_ai' },
                      { label: '百度AI', value: 'baidu_ai' },
                      { label: '小红书', value: 'xiaohongshu' },
                    ]}
                  />
                  <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleCheckCitation}>
                    检测引用
                  </Button>
                </Space>
              </Card>
              <ProTable<CitationItem>
                actionRef={citationTableRef}
                columns={citationColumns}
                rowKey="id"
                request={async (params) => {
                  const res = await txFetchData(
                    `/api/v1/intel/geo-seo/citations?page=${params.current || 1}&size=${params.pageSize || 20}`
                  );
                  return {
                    data: res.ok ? res.data.items : [],
                    total: res.ok ? res.data.total : 0,
                    success: res.ok,
                  };
                }}
                search={false}
                pagination={{ defaultPageSize: 20 }}
                headerTitle="引用监测记录"
              />
            </>
          ),
        },
      ]} />

      {/* ── 优化建议弹窗 ── */}
      <Modal
        title={`优化建议 — ${optimizeModal.storeName}`}
        open={optimizeModal.visible}
        onCancel={() => setOptimizeModal((s) => ({ ...s, visible: false }))}
        footer={null}
        width={600}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Row gutter={16}>
            <Col span={12}>
              <Statistic title="当前评分" value={optimizeModal.currentScore} suffix="/ 100"
                valueStyle={{ color: scoreColor(optimizeModal.currentScore) }} />
            </Col>
            <Col span={12}>
              <Statistic title="潜在评分" value={optimizeModal.potentialScore} suffix="/ 100"
                valueStyle={{ color: '#52c41a' }} />
            </Col>
          </Row>
          <Table
            dataSource={optimizeModal.suggestions}
            rowKey="field"
            size="small"
            pagination={false}
            columns={[
              { title: '字段', dataIndex: 'field', width: 120 },
              { title: '建议', dataIndex: 'message' },
              { title: '可提升', dataIndex: 'points', width: 80, render: (v: number) => <Tag color="blue">+{v}</Tag> },
            ]}
          />
        </Space>
      </Modal>
    </div>
  );
}
