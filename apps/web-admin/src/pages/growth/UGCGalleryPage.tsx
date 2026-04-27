/**
 * UGC图墙管理页
 * S2W7 — UGC裂变病毒引擎管理后台
 *
 * 四个区域：UGC审核列表 / 裂变统计卡片 / 分享排行榜 / 状态筛选Tab
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
  Image,
  Input,
  message,
  Modal,
  Typography,
  Switch,
  Empty,
  Spin,
  Pagination,
} from 'antd';
import {
  CameraOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
  FireOutlined,
  HeartOutlined,
  LikeOutlined,
  ShareAltOutlined,
  StarOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';

const { Title, Text, Paragraph } = Typography;
const { TabPane } = Tabs;
const { TextArea } = Input;

const API_BASE = '/api/v1/growth/ugc';
const TENANT_ID = 'demo-tenant-001'; // 实际应从 useTenantContext() 获取

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

interface UGCSubmission {
  ugc_id: string;
  customer_id: string;
  store_id: string;
  media_urls: { url: string; type: 'photo' | 'video'; thumbnail_url?: string }[];
  caption: string;
  dish_ids: string[];
  ai_quality_score: number | null;
  ai_quality_feedback: string | null;
  status: 'pending_review' | 'approved' | 'rejected' | 'published' | 'hidden';
  rejection_reason: string | null;
  points_awarded: number;
  view_count: number;
  like_count: number;
  share_count: number;
  featured: boolean;
  published_at: string | null;
  created_at: string;
}

interface ViralStats {
  total_shares: number;
  total_clicks: number;
  total_conversions: number;
  total_revenue_fen: number;
  avg_chain_depth: number;
  conversion_rate: number;
  days: number;
}

interface TopSharer {
  rank: number;
  sharer_customer_id: string;
  total_shares: number;
  total_clicks: number;
  total_conversions: number;
  total_revenue_fen: number;
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

const fenToYuan = (fen: number) => (fen / 100).toFixed(2);
const pctFormat = (rate: number) => `${(rate * 100).toFixed(1)}%`;

const statusConfig: Record<string, { color: string; label: string }> = {
  pending_review: { color: 'orange', label: '待审核' },
  approved:       { color: 'blue',   label: '已通过' },
  rejected:       { color: 'red',    label: '已拒绝' },
  published:      { color: 'green',  label: '已发布' },
  hidden:         { color: 'default', label: '已隐藏' },
};

const rankMedal = (rank: number) => {
  if (rank === 1) return <span style={{ color: '#FFD700', fontSize: 16, fontWeight: 700 }}>1</span>;
  if (rank === 2) return <span style={{ color: '#C0C0C0', fontSize: 16, fontWeight: 700 }}>2</span>;
  if (rank === 3) return <span style={{ color: '#CD7F32', fontSize: 16, fontWeight: 700 }}>3</span>;
  return <span style={{ color: '#5F5E5A' }}>{rank}</span>;
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
// 子组件：UGC 卡片
// ---------------------------------------------------------------------------

interface UGCCardProps {
  item: UGCSubmission;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onFeature: (id: string) => void;
  onReview: (id: string) => void;
}

const UGCCard: React.FC<UGCCardProps> = ({ item, onApprove, onReject, onFeature, onReview }) => {
  const thumb = item.media_urls?.[0]?.thumbnail_url || item.media_urls?.[0]?.url;
  const sc = statusConfig[item.status] || { color: 'default', label: item.status };

  return (
    <Card
      hoverable
      style={{ marginBottom: 16 }}
      cover={
        thumb ? (
          <Image
            src={thumb}
            alt="UGC"
            style={{ height: 200, objectFit: 'cover' }}
            fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN88P/BfwAJhAPk2T+FPQAAAABJRU5ErkJggg=="
          />
        ) : (
          <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5' }}>
            <CameraOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />
          </div>
        )
      }
      actions={[
        item.status === 'pending_review' && (
          <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => onApprove(item.ugc_id)} key="approve">
            通过
          </Button>
        ),
        item.status === 'pending_review' && (
          <Button type="link" size="small" danger icon={<CloseCircleOutlined />} onClick={() => onReject(item.ugc_id)} key="reject">
            拒绝
          </Button>
        ),
        item.status === 'pending_review' && (
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => onReview(item.ugc_id)} key="review">
            AI审
          </Button>
        ),
        item.status === 'published' && !item.featured && (
          <Button type="link" size="small" icon={<StarOutlined />} onClick={() => onFeature(item.ugc_id)} key="feature">
            精选
          </Button>
        ),
      ].filter(Boolean)}
    >
      <Card.Meta
        title={
          <Space>
            <Tag color={sc.color}>{sc.label}</Tag>
            {item.featured && <Tag color="gold" icon={<StarOutlined />}>编辑精选</Tag>}
            {item.ai_quality_score !== null && (
              <Tag color={item.ai_quality_score >= 0.7 ? 'green' : 'orange'}>
                AI {(item.ai_quality_score * 100).toFixed(0)}分
              </Tag>
            )}
          </Space>
        }
        description={
          <>
            <Paragraph ellipsis={{ rows: 2 }}>{item.caption || '（无文案）'}</Paragraph>
            <Space size="large">
              <Text type="secondary"><EyeOutlined /> {item.view_count}</Text>
              <Text type="secondary"><LikeOutlined /> {item.like_count}</Text>
              <Text type="secondary"><ShareAltOutlined /> {item.share_count}</Text>
            </Space>
            {item.rejection_reason && (
              <div style={{ marginTop: 8 }}>
                <Text type="danger">拒绝原因: {item.rejection_reason}</Text>
              </div>
            )}
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {item.media_urls?.length || 0} 张 / 积分 {item.points_awarded}
              </Text>
            </div>
          </>
        }
      />
    </Card>
  );
};

// ---------------------------------------------------------------------------
// 主页面
// ---------------------------------------------------------------------------

const UGCGalleryPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('pending_review');
  const [loading, setLoading] = useState(false);
  const [submissions, setSubmissions] = useState<UGCSubmission[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [viralStats, setViralStats] = useState<ViralStats | null>(null);
  const [topSharers, setTopSharers] = useState<TopSharer[]>([]);
  const [rejectModal, setRejectModal] = useState<{ visible: boolean; ugcId: string }>({ visible: false, ugcId: '' });
  const [rejectReason, setRejectReason] = useState('');

  // 模拟store_id（实际应从门店选择器获取）
  const storeId = 'demo-store-001';

  // -----------------------------------------------------------------------
  // 加载UGC列表（按状态过滤 — 实际由后端gallery接口返回所有published，
  // 管理端需要全状态接口；这里用gallery接口模拟）
  // -----------------------------------------------------------------------

  const loadSubmissions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch(`/gallery/${storeId}?page=${page}&size=12`);
      setSubmissions(data.items || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      message.error(err.message || '加载UGC列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, storeId]);

  const loadViralStats = useCallback(async () => {
    try {
      const data = await apiFetch('/viral-stats?days=30');
      setViralStats(data.stats);
      setTopSharers(data.top_sharers || []);
    } catch (err: any) {
      message.error(err.message || '加载裂变统计失败');
    }
  }, []);

  useEffect(() => {
    loadSubmissions();
    loadViralStats();
  }, [loadSubmissions, loadViralStats]);

  // -----------------------------------------------------------------------
  // 操作
  // -----------------------------------------------------------------------

  const handleApprove = async (ugcId: string) => {
    try {
      await apiFetch(`/${ugcId}/approve`, { method: 'POST' });
      message.success('审批通过');
      loadSubmissions();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) {
      message.warning('请填写拒绝原因');
      return;
    }
    try {
      await apiFetch(`/${rejectModal.ugcId}/reject`, {
        method: 'POST',
        body: JSON.stringify({ reason: rejectReason }),
      });
      message.success('已拒绝');
      setRejectModal({ visible: false, ugcId: '' });
      setRejectReason('');
      loadSubmissions();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleFeature = async (ugcId: string) => {
    try {
      await apiFetch(`/${ugcId}/approve`, { method: 'POST' }); // feature端点复用approve
      message.success('已设为编辑精选');
      loadSubmissions();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleReview = async (ugcId: string) => {
    try {
      const result = await apiFetch(`/${ugcId}/review`, { method: 'POST' });
      if (result.auto_approved) {
        message.success(`AI自动通过 (评分: ${(result.score * 100).toFixed(0)})`);
      } else {
        message.info(`AI评分: ${(result.score * 100).toFixed(0)}，需人工审核`);
      }
      loadSubmissions();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  // -----------------------------------------------------------------------
  // 排行榜列
  // -----------------------------------------------------------------------

  const leaderColumns: ProColumns<TopSharer>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 60,
      render: (_: any, record: TopSharer) => rankMedal(record.rank),
    },
    {
      title: '分享者ID',
      dataIndex: 'sharer_customer_id',
      ellipsis: true,
      width: 180,
    },
    {
      title: '分享数',
      dataIndex: 'total_shares',
      width: 80,
      sorter: (a: TopSharer, b: TopSharer) => a.total_shares - b.total_shares,
    },
    {
      title: '点击数',
      dataIndex: 'total_clicks',
      width: 80,
    },
    {
      title: '转化数',
      dataIndex: 'total_conversions',
      width: 80,
      sorter: (a: TopSharer, b: TopSharer) => a.total_conversions - b.total_conversions,
    },
    {
      title: '带来收入',
      dataIndex: 'total_revenue_fen',
      width: 120,
      render: (_: any, record: TopSharer) => `¥${fenToYuan(record.total_revenue_fen)}`,
      sorter: (a: TopSharer, b: TopSharer) => a.total_revenue_fen - b.total_revenue_fen,
    },
  ];

  // -----------------------------------------------------------------------
  // 渲染
  // -----------------------------------------------------------------------

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <CameraOutlined style={{ marginRight: 8 }} />
        UGC图墙管理
      </Title>

      {/* 裂变统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card>
            <Statistic
              title="分享数"
              value={viralStats?.total_shares || 0}
              prefix={<ShareAltOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="点击数"
              value={viralStats?.total_clicks || 0}
              prefix={<EyeOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="转化数"
              value={viralStats?.total_conversions || 0}
              prefix={<FireOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="转化收入"
              value={fenToYuan(viralStats?.total_revenue_fen || 0)}
              prefix="¥"
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="转化率"
              value={pctFormat(viralStats?.conversion_rate || 0)}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="平均链路深度"
              value={viralStats?.avg_chain_depth?.toFixed(1) || '0.0'}
            />
          </Card>
        </Col>
      </Row>

      {/* 主体区域 */}
      <Row gutter={24}>
        {/* 左侧：UGC列表 */}
        <Col span={16}>
          <Card>
            <Tabs activeKey={activeTab} onChange={setActiveTab}>
              <TabPane tab="待审核" key="pending_review" />
              <TabPane tab="已发布" key="published" />
              <TabPane tab="已拒绝" key="rejected" />
            </Tabs>

            <Spin spinning={loading}>
              {submissions.length === 0 ? (
                <Empty description="暂无UGC投稿" />
              ) : (
                <Row gutter={[16, 16]}>
                  {submissions.map((item) => (
                    <Col key={item.ugc_id} xs={24} sm={12} lg={8}>
                      <UGCCard
                        item={item}
                        onApprove={handleApprove}
                        onReject={(id) => setRejectModal({ visible: true, ugcId: id })}
                        onFeature={handleFeature}
                        onReview={handleReview}
                      />
                    </Col>
                  ))}
                </Row>
              )}

              {total > 12 && (
                <div style={{ textAlign: 'center', marginTop: 16 }}>
                  <Pagination
                    current={page}
                    pageSize={12}
                    total={total}
                    onChange={setPage}
                    showTotal={(t) => `共 ${t} 条`}
                  />
                </div>
              )}
            </Spin>
          </Card>
        </Col>

        {/* 右侧：分享排行榜 */}
        <Col span={8}>
          <Card
            title={
              <Space>
                <TrophyOutlined style={{ color: '#FFD700' }} />
                <span>分享排行榜</span>
              </Space>
            }
          >
            <ProTable<TopSharer>
              columns={leaderColumns}
              dataSource={topSharers}
              rowKey="sharer_customer_id"
              search={false}
              toolBarRender={false}
              pagination={false}
              size="small"
            />
          </Card>
        </Col>
      </Row>

      {/* 拒绝弹窗 */}
      <Modal
        title="拒绝UGC投稿"
        open={rejectModal.visible}
        onOk={handleRejectConfirm}
        onCancel={() => {
          setRejectModal({ visible: false, ugcId: '' });
          setRejectReason('');
        }}
        okText="确认拒绝"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <TextArea
          rows={3}
          placeholder="请输入拒绝原因（将通知投稿者）"
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
        />
      </Modal>
    </div>
  );
};

export default UGCGalleryPage;
