/**
 * 评价管理页 — 顾客评价管理（配合小程序评价系统）
 * 路由：/ops/reviews
 * API：GET  /api/v1/trade/reviews
 *      POST /api/v1/trade/reviews/{id}/reply
 *      POST /api/v1/trade/reviews/{id}/hide
 *      GET  /api/v1/trade/reviews/stats
 */
import { useRef, useState, useEffect } from 'react';
import {
  ConfigProvider, Card, Row, Col, Statistic, Tag, Button, Modal,
  Input, Space, Select, Drawer, message, Rate, Typography, Tooltip,
  Divider, Badge, Popconfirm,
} from 'antd';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import {
  StarFilled, MessageOutlined, EyeInvisibleOutlined,
  BarChartOutlined, CommentOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// ─── Design Token ──────────────────────────────────────────────────────────
const txAdminTheme = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Table: { headerBg: '#F8F7F5' },
  },
};

// ─── 类型 ──────────────────────────────────────────────────────────────────
type ReviewStatus = 'published' | 'pending_review' | 'hidden';

interface SubRatings {
  food: number;
  service: number;
  environment: number;
  speed: number;
}

interface Review {
  id: string;
  order_id: string;
  store_name: string;
  customer_name: string;
  is_anonymous: boolean;
  overall_rating: number;
  sub_ratings: SubRatings;
  content: string | null;
  tags: string[];
  image_urls: string[];
  merchant_reply: string | null;
  merchant_replied_at: string | null;
  created_at: string;
  status: ReviewStatus;
}

interface ReviewListData {
  items: Review[];
  total: number;
  avg_rating: number;
  positive_rate: number;
  unreplied_count: number;
  _is_mock?: boolean;
}

interface StatsData {
  avg_rating: number;
  total_reviews: number;
  rating_distribution: Record<string, number>;
  sub_rating_avg: SubRatings;
  positive_rate: number;
  unreplied_count: number;
  top_tags: { tag: string; count: number }[];
  _is_mock?: boolean;
}

// ─── 工具函数 ──────────────────────────────────────────────────────────────
const STATUS_MAP: Record<ReviewStatus, { label: string; color: string }> = {
  published: { label: '已发布', color: 'success' },
  pending_review: { label: '待审核', color: 'warning' },
  hidden: { label: '已隐藏', color: 'default' },
};

function StarDisplay({ value }: { value: number }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <StarFilled
          key={i}
          style={{
            fontSize: 13,
            color: i <= value ? '#FAAD14' : '#E0E0E0',
          }}
        />
      ))}
      <span style={{ marginLeft: 4, fontSize: 12, color: '#5F5E5A', fontWeight: 600 }}>
        {value.toFixed(1)}
      </span>
    </span>
  );
}

// ─── 纯CSS雷达图（4维度） ──────────────────────────────────────────────────
function SubRatingRadar({ data }: { data: SubRatings }) {
  const dims = [
    { key: 'food', label: '口味', color: '#FF6B35' },
    { key: 'service', label: '服务', color: '#185FA5' },
    { key: 'environment', label: '环境', color: '#0F6E56' },
    { key: 'speed', label: '速度', color: '#BA7517' },
  ] as const;

  return (
    <div>
      {dims.map(({ key, label, color }) => {
        const val = data[key];
        const pct = (val / 5) * 100;
        return (
          <div key={key} style={{ marginBottom: 10 }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              marginBottom: 4, fontSize: 12, color: '#5F5E5A',
            }}>
              <span>{label}</span>
              <span style={{ fontWeight: 600, color }}>{val.toFixed(1)}</span>
            </div>
            <div style={{
              height: 6, background: '#F0EDE6', borderRadius: 3, overflow: 'hidden',
            }}>
              <div style={{
                width: `${pct}%`, height: '100%',
                background: color, borderRadius: 3,
                transition: 'width 0.5s ease',
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 近7天评分趋势（SVG折线） ──────────────────────────────────────────────
const TREND_DATA = [
  { day: '3/27', score: 4.1 },
  { day: '3/28', score: 3.8 },
  { day: '3/29', score: 4.3 },
  { day: '3/30', score: 3.9 },
  { day: '3/31', score: 4.2 },
  { day: '4/1', score: 4.0 },
  { day: '4/2', score: 3.9 },
];

function RatingTrendSVG() {
  const W = 240, H = 80, PAD = 16;
  const minScore = 3, maxScore = 5;
  const points = TREND_DATA.map((d, i) => {
    const x = PAD + (i / (TREND_DATA.length - 1)) * (W - PAD * 2);
    const y = PAD + ((maxScore - d.score) / (maxScore - minScore)) * (H - PAD * 2);
    return { x, y, ...d };
  });
  const polyline = points.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <div>
      <svg width={W} height={H} style={{ display: 'block', overflow: 'visible' }}>
        {/* 网格线 */}
        {[3, 3.5, 4, 4.5, 5].map((v) => {
          const y = PAD + ((maxScore - v) / (maxScore - minScore)) * (H - PAD * 2);
          return (
            <line key={v} x1={PAD} y1={y} x2={W - PAD} y2={y}
              stroke="#E8E6E1" strokeWidth={1} strokeDasharray="3,3" />
          );
        })}
        {/* 折线 */}
        <polyline
          points={polyline}
          fill="none"
          stroke="#FF6B35"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {/* 数据点 */}
        {points.map((p) => (
          <circle key={p.day} cx={p.x} cy={p.y} r={3}
            fill="#FF6B35" stroke="#fff" strokeWidth={1.5} />
        ))}
      </svg>
      {/* X轴标签 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        fontSize: 10, color: '#B4B2A9', marginTop: 4,
        paddingLeft: PAD, paddingRight: PAD,
      }}>
        {TREND_DATA.map((d) => <span key={d.day}>{d.day}</span>)}
      </div>
    </div>
  );
}

// ─── 标签词云 ──────────────────────────────────────────────────────────────
function TagCloud({ tags }: { tags: { tag: string; count: number }[] }) {
  if (!tags.length) return null;
  const maxCount = Math.max(...tags.map((t) => t.count));
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {tags.map(({ tag, count }) => {
        const ratio = count / maxCount;
        const size = 11 + Math.round(ratio * 8);
        const opacity = 0.5 + ratio * 0.5;
        return (
          <span key={tag} style={{
            fontSize: size,
            color: `rgba(255, 107, 53, ${opacity})`,
            background: '#FFF3ED',
            padding: '3px 8px',
            borderRadius: 12,
            lineHeight: 1.4,
          }}>
            {tag}
            <span style={{ fontSize: 10, color: '#B4B2A9', marginLeft: 3 }}>
              {count}
            </span>
          </span>
        );
      })}
    </div>
  );
}

// ─── 主页面组件 ────────────────────────────────────────────────────────────
export function ReviewManagePage() {
  const actionRef = useRef<ActionType>();

  // 筛选状态
  const [ratingFilter, setRatingFilter] = useState<number | undefined>();
  const [repliedFilter, setRepliedFilter] = useState<boolean | undefined>();
  const [statusFilter, setStatusFilter] = useState<ReviewStatus | undefined>();

  // 回复弹窗
  const [replyModal, setReplyModal] = useState<{
    open: boolean; reviewId: string; existing?: string | null;
  }>({ open: false, reviewId: '' });
  const [replyText, setReplyText] = useState('');
  const [replyLoading, setReplyLoading] = useState(false);

  // 详情展示状态（展开行辅助）
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // 统计面板
  const [statsDrawer, setStatsDrawer] = useState(false);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // 顶部统计快照（从列表API获取）
  const [summary, setSummary] = useState({
    avg_rating: 0,
    positive_rate: 0,
    total: 0,
    unreplied_count: 0,
  });

  // ── 加载统计面板数据 ──
  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const data = await txFetchData<StatsData>('/api/v1/trade/reviews/stats');
      setStats(data);
    } catch {
      // Mock fallback
      setStats({
        avg_rating: 3.9,
        total_reviews: 4,
        rating_distribution: { '5': 35, '4': 28, '3': 20, '2': 10, '1': 7 },
        sub_rating_avg: { food: 4.2, service: 3.8, environment: 3.7, speed: 3.5 },
        positive_rate: 62.5,
        unreplied_count: 2,
        top_tags: [
          { tag: '味道棒极了', count: 45 },
          { tag: '服务热情', count: 32 },
          { tag: '性价比高', count: 28 },
          { tag: '分量充足', count: 21 },
          { tag: '会再来', count: 18 },
        ],
        _is_mock: true,
      });
    } finally {
      setStatsLoading(false);
    }
  };

  // ── 商家回复提交 ──
  const handleReplySubmit = async () => {
    if (!replyText.trim()) {
      message.warning('回复内容不能为空');
      return;
    }
    setReplyLoading(true);
    try {
      await txFetchData(`/api/v1/trade/reviews/${replyModal.reviewId}/reply`, {
        method: 'POST',
        body: JSON.stringify({ content: replyText }),
      });
      message.success('回复成功');
      setReplyModal({ open: false, reviewId: '' });
      setReplyText('');
      actionRef.current?.reload();
    } catch {
      message.error('回复失败，请重试');
    } finally {
      setReplyLoading(false);
    }
  };

  // ── 隐藏评价 ──
  const handleHide = async (reviewId: string) => {
    try {
      await txFetchData(`/api/v1/trade/reviews/${reviewId}/hide`, { method: 'POST' });
      message.success('评价已隐藏');
      actionRef.current?.reload();
    } catch {
      message.error('操作失败');
    }
  };

  // ── 展开行内容 ──
  const expandedRowRender = (record: Review) => (
    <div style={{ padding: '12px 24px', background: '#FAFAFA', borderRadius: 6 }}>
      <Row gutter={24}>
        {/* 完整评价内容 */}
        <Col span={12}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            完整评价
          </Text>
          <Paragraph style={{ margin: 0, fontSize: 14, lineHeight: 1.7 }}>
            {record.content || <Text type="secondary">（无文字评价）</Text>}
          </Paragraph>

          {/* 图片缩略图 */}
          {record.image_urls.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {record.image_urls.map((url, i) => (
                <img key={i} src={url} alt="" style={{
                  width: 64, height: 64, borderRadius: 4,
                  objectFit: 'cover', border: '1px solid #E8E6E1',
                }} />
              ))}
            </div>
          )}

          {/* 标签 */}
          {record.tags.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {record.tags.map((tag) => (
                <Tag key={tag} color="orange" style={{ marginBottom: 4 }}>{tag}</Tag>
              ))}
            </div>
          )}
        </Col>

        {/* 分项评分 */}
        <Col span={6}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            分项评分
          </Text>
          <SubRatingRadar data={record.sub_ratings} />
        </Col>

        {/* 商家回复 */}
        <Col span={6}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            商家回复
          </Text>
          {record.merchant_reply ? (
            <div style={{
              background: '#FFF3ED', borderRadius: 6, padding: '10px 12px',
              borderLeft: '3px solid #FF6B35',
            }}>
              <Paragraph style={{ margin: 0, fontSize: 13, lineHeight: 1.6 }}>
                {record.merchant_reply}
              </Paragraph>
              {record.merchant_replied_at && (
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
                  {new Date(record.merchant_replied_at).toLocaleString('zh-CN')}
                </Text>
              )}
            </div>
          ) : (
            <Text type="secondary" style={{ fontSize: 13 }}>暂未回复</Text>
          )}
        </Col>
      </Row>
    </div>
  );

  // ── ProTable 列定义 ──
  const columns: ProColumns<Review>[] = [
    {
      title: '评价者',
      dataIndex: 'customer_name',
      width: 80,
      render: (_, r) => (
        <span style={{ fontSize: 13 }}>
          {r.is_anonymous
            ? <Text type="secondary">匿名用户</Text>
            : r.customer_name}
        </span>
      ),
    },
    {
      title: '星级',
      dataIndex: 'overall_rating',
      width: 140,
      render: (_, r) => <StarDisplay value={r.overall_rating} />,
    },
    {
      title: '评价摘要',
      dataIndex: 'content',
      ellipsis: true,
      render: (_, r) => {
        const text = r.content || '';
        const short = text.length > 50 ? text.slice(0, 50) + '…' : text;
        return (
          <Tooltip title={text} placement="topLeft">
            <span style={{ fontSize: 13, color: '#2C2C2A' }}>
              {short || <Text type="secondary">（无文字）</Text>}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: '标签',
      dataIndex: 'tags',
      width: 160,
      render: (_, r) => (
        <Space wrap size={[4, 4]}>
          {r.tags.slice(0, 3).map((tag) => (
            <Tag key={tag} style={{
              fontSize: 11, padding: '0 6px', margin: 0,
              background: '#FFF3ED', color: '#FF6B35', border: '1px solid #FFD5B8',
            }}>
              {tag}
            </Tag>
          ))}
          {r.tags.length > 3 && (
            <Text type="secondary" style={{ fontSize: 11 }}>+{r.tags.length - 3}</Text>
          )}
        </Space>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 110,
      render: (text) => <Text style={{ fontSize: 12 }}>{text as string}</Text>,
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 130,
      render: (_, r) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {new Date(r.created_at).toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
          })}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = STATUS_MAP[r.status];
        return <Tag color={s.color}>{s.label}</Tag>;
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => {
        const actions: React.ReactNode[] = [];

        // 未回复：显示回复按钮
        if (!r.merchant_reply && r.status !== 'hidden') {
          actions.push(
            <Button
              key="reply"
              type="primary"
              size="small"
              icon={<MessageOutlined />}
              onClick={() => {
                setReplyModal({ open: true, reviewId: r.id });
                setReplyText('');
              }}
              style={{ fontSize: 12 }}
            >
              回复
            </Button>
          );
        }

        // 已回复：查看对话
        if (r.merchant_reply) {
          actions.push(
            <Button
              key="view-reply"
              size="small"
              icon={<CommentOutlined />}
              onClick={() => {
                setExpandedKeys((prev) =>
                  prev.includes(r.id)
                    ? prev.filter((k) => k !== r.id)
                    : [...prev, r.id]
                );
              }}
              style={{ fontSize: 12 }}
            >
              查看对话
            </Button>
          );
        }

        // 待审核的差评（rating≤2）：通过发布 + 隐藏屏蔽
        if (r.status === 'pending_review' && r.overall_rating <= 2) {
          actions.push(
            <Button
              key="approve"
              size="small"
              style={{
                fontSize: 12,
                color: '#0F6E56', borderColor: '#0F6E56',
              }}
              onClick={async () => {
                message.success('已通过发布');
                actionRef.current?.reload();
              }}
            >
              通过发布
            </Button>
          );
          actions.push(
            <Popconfirm
              key="hide"
              title="确认屏蔽该评价？"
              description="违规/不实内容可以屏蔽，屏蔽后顾客不可见。"
              onConfirm={() => handleHide(r.id)}
              okText="确认屏蔽"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button
                size="small"
                danger
                icon={<EyeInvisibleOutlined />}
                style={{ fontSize: 12 }}
              >
                隐藏屏蔽
              </Button>
            </Popconfirm>
          );
        }

        // 已发布但未隐藏：也可隐藏
        if (r.status === 'published') {
          actions.push(
            <Popconfirm
              key="hide"
              title="确认屏蔽该评价？"
              onConfirm={() => handleHide(r.id)}
              okText="确认"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button
                size="small"
                type="text"
                icon={<EyeInvisibleOutlined />}
                style={{ fontSize: 12, color: '#B4B2A9' }}
              >
                屏蔽
              </Button>
            </Popconfirm>
          );
        }

        return <Space size={4}>{actions}</Space>;
      },
    },
  ];

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ padding: 0 }}>
        {/* ── 顶部标题栏 ── */}
        <div style={{
          display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', marginBottom: 20,
        }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A', fontWeight: 700 }}>
              评价管理
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#5F5E5A' }}>
              管理顾客评价、商家回复和差评处理
            </p>
          </div>
          <Button
            icon={<BarChartOutlined />}
            onClick={() => {
              setStatsDrawer(true);
              loadStats();
            }}
            style={{ borderColor: '#FF6B35', color: '#FF6B35' }}
          >
            数据统计
          </Button>
        </div>

        {/* ── 顶部5个统计卡片 ── */}
        <Row gutter={16} style={{ marginBottom: 20 }}>
          {/* 综合评分 */}
          <Col span={5}>
            <Card
              size="small"
              style={{ borderRadius: 8, border: '1px solid #E8E6E1' }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <StarFilled style={{ color: '#FAAD14', fontSize: 16 }} />
                <span style={{ fontSize: 12, color: '#5F5E5A' }}>综合评分</span>
              </div>
              <div style={{ fontSize: 32, fontWeight: 800, color: '#FF6B35', lineHeight: 1 }}>
                {summary.avg_rating || 3.5}
              </div>
              <Rate
                disabled
                value={summary.avg_rating || 3.5}
                allowHalf
                style={{ fontSize: 12, marginTop: 6 }}
              />
            </Card>
          </Col>

          {/* 好评率 */}
          <Col span={5}>
            <Card
              size="small"
              style={{ borderRadius: 8, border: '1px solid #E8E6E1' }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <Statistic
                title={<span style={{ fontSize: 12 }}>好评率</span>}
                value={summary.positive_rate || 62.5}
                suffix="%"
                valueStyle={{ color: '#0F6E56', fontWeight: 800 }}
                precision={1}
              />
            </Card>
          </Col>

          {/* 近30天评价数 */}
          <Col span={5}>
            <Card
              size="small"
              style={{ borderRadius: 8, border: '1px solid #E8E6E1' }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <Statistic
                title={<span style={{ fontSize: 12 }}>近30天评价数</span>}
                value={summary.total || 0}
                valueStyle={{ fontWeight: 800 }}
                suffix="条"
              />
            </Card>
          </Col>

          {/* 待回复数 */}
          <Col span={5}>
            <Card
              size="small"
              style={{
                borderRadius: 8,
                border: `1px solid ${summary.unreplied_count > 0 ? '#FFB8A3' : '#E8E6E1'}`,
                background: summary.unreplied_count > 0 ? '#FFF8F6' : '#fff',
              }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <Statistic
                title={
                  <span style={{ fontSize: 12, color: summary.unreplied_count > 0 ? '#A32D2D' : undefined }}>
                    待回复数
                    {summary.unreplied_count > 0 && (
                      <span style={{ marginLeft: 4, fontSize: 10 }}>⚡ 需及时回复</span>
                    )}
                  </span>
                }
                value={summary.unreplied_count || 0}
                valueStyle={{
                  color: summary.unreplied_count > 0 ? '#A32D2D' : '#2C2C2A',
                  fontWeight: 800,
                }}
                suffix="条"
              />
            </Card>
          </Col>

          {/* 差评待处理 */}
          <Col span={4}>
            <Card
              size="small"
              style={{ borderRadius: 8, border: '1px solid #FFD591', background: '#FFFBE6' }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <Statistic
                title={<span style={{ fontSize: 12, color: '#BA7517' }}>差评待处理</span>}
                value={1}
                valueStyle={{ color: '#BA7517', fontWeight: 800 }}
                suffix="条"
              />
            </Card>
          </Col>
        </Row>

        {/* ── ProTable ── */}
        <ProTable<Review>
          actionRef={actionRef}
          rowKey="id"
          columns={columns}
          search={false}
          toolBarRender={() => [
            <Select
              key="rating"
              placeholder="星级筛选"
              allowClear
              style={{ width: 110 }}
              value={ratingFilter}
              onChange={setRatingFilter}
              options={[
                { label: '⭐⭐⭐⭐⭐ 5星', value: 5 },
                { label: '⭐⭐⭐⭐ 4星', value: 4 },
                { label: '⭐⭐⭐ 3星', value: 3 },
                { label: '⭐⭐ 2星', value: 2 },
                { label: '⭐ 1星', value: 1 },
              ]}
            />,
            <Select
              key="replied"
              placeholder="回复状态"
              allowClear
              style={{ width: 110 }}
              value={repliedFilter as boolean | undefined}
              onChange={setRepliedFilter}
              options={[
                { label: '已回复', value: true },
                { label: '未回复', value: false },
              ]}
            />,
            <Select
              key="status"
              placeholder="评价状态"
              allowClear
              style={{ width: 110 }}
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { label: '已发布', value: 'published' },
                { label: '待审核', value: 'pending_review' },
                { label: '已隐藏', value: 'hidden' },
              ]}
            />,
            <Select
              key="store"
              placeholder="全部门店"
              allowClear
              style={{ width: 130 }}
              options={[
                { label: '五一广场店', value: 'wuyiguangchang' },
                { label: '东塘店', value: 'dongtang' },
                { label: '河西万达店', value: 'hexiwanda' },
              ]}
            />,
          ]}
          request={async (params) => {
            const qp = new URLSearchParams();
            if (ratingFilter) qp.set('rating_filter', String(ratingFilter));
            if (repliedFilter !== undefined) qp.set('replied', String(repliedFilter));
            if (statusFilter) qp.set('status', statusFilter);
            qp.set('page', String(params.current ?? 1));
            qp.set('size', String(params.pageSize ?? 20));

            try {
              const data = await txFetchData<ReviewListData>(
                `/api/v1/trade/reviews?${qp.toString()}`
              );
              // 同步顶部统计
              setSummary({
                avg_rating: data.avg_rating,
                positive_rate: data.positive_rate,
                total: data.total,
                unreplied_count: data.unreplied_count,
              });
              return {
                data: data.items,
                total: data.total,
                success: true,
              };
            } catch {
              return { data: [], total: 0, success: false };
            }
          }}
          expandable={{
            expandedRowRender,
            expandedRowKeys: expandedKeys,
            onExpandedRowsChange: (keys) => setExpandedKeys(keys as string[]),
          }}
          pagination={{ defaultPageSize: 20, showSizeChanger: true }}
          scroll={{ x: 1100 }}
          cardBordered
          options={{ density: true, fullScreen: true }}
          headerTitle={
            <Space>
              <span style={{ fontWeight: 600 }}>评价列表</span>
              <Badge count={summary.unreplied_count} style={{ backgroundColor: '#A32D2D' }}>
                <span />
              </Badge>
            </Space>
          }
        />

        {/* ── 商家回复 Modal ── */}
        <Modal
          title="回复顾客评价"
          open={replyModal.open}
          onCancel={() => setReplyModal({ open: false, reviewId: '' })}
          footer={[
            <Button key="cancel" onClick={() => setReplyModal({ open: false, reviewId: '' })}>
              取消
            </Button>,
            <Button
              key="submit"
              type="primary"
              loading={replyLoading}
              onClick={handleReplySubmit}
            >
              提交回复
            </Button>,
          ]}
          width={480}
        >
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              回复将公开展示在顾客评价页面，请保持专业友好的语气。
            </Text>
          </div>
          <TextArea
            rows={4}
            placeholder="感谢您的评价，欢迎您再次光临…"
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            maxLength={200}
            showCount
            autoFocus
          />
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>快捷回复：</Text>
            <Space wrap style={{ marginTop: 4 }}>
              {[
                '感谢您的好评，欢迎下次再来！',
                '非常抱歉给您带来不好的体验，我们会努力改进！',
                '感谢您的反馈，我们已记录并会及时改善。',
              ].map((t) => (
                <Tag
                  key={t}
                  style={{ cursor: 'pointer', fontSize: 11 }}
                  onClick={() => setReplyText(t)}
                >
                  {t.slice(0, 12)}…
                </Tag>
              ))}
            </Space>
          </div>
        </Modal>

        {/* ── 统计面板 Drawer ── */}
        <Drawer
          title={
            <Space>
              <BarChartOutlined style={{ color: '#FF6B35' }} />
              <span>评价数据统计</span>
            </Space>
          }
          placement="right"
          width={360}
          open={statsDrawer}
          onClose={() => setStatsDrawer(false)}
          loading={statsLoading}
        >
          {stats && (
            <div>
              {/* 综合评分 */}
              <Row gutter={16} style={{ marginBottom: 20 }}>
                <Col span={12}>
                  <Card size="small" style={{ borderRadius: 8, textAlign: 'center' }}>
                    <div style={{ fontSize: 28, fontWeight: 800, color: '#FF6B35' }}>
                      {stats.avg_rating}
                    </div>
                    <div style={{ fontSize: 12, color: '#5F5E5A' }}>综合评分</div>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size="small" style={{ borderRadius: 8, textAlign: 'center' }}>
                    <div style={{ fontSize: 28, fontWeight: 800, color: '#0F6E56' }}>
                      {stats.positive_rate}%
                    </div>
                    <div style={{ fontSize: 12, color: '#5F5E5A' }}>好评率</div>
                  </Card>
                </Col>
              </Row>

              {/* 分项评分雷达 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{
                  fontSize: 13, fontWeight: 600, color: '#2C2C2A',
                  marginBottom: 12,
                }}>
                  分项评分
                </div>
                <SubRatingRadar data={stats.sub_rating_avg} />
              </div>

              <Divider style={{ margin: '16px 0' }} />

              {/* 评分分布 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{
                  fontSize: 13, fontWeight: 600, color: '#2C2C2A',
                  marginBottom: 12,
                }}>
                  评分分布
                </div>
                {(['5', '4', '3', '2', '1'] as const).map((star) => {
                  const count = stats.rating_distribution[star] ?? 0;
                  const total = Object.values(stats.rating_distribution).reduce((a, b) => a + b, 0);
                  const pct = total > 0 ? (count / total) * 100 : 0;
                  return (
                    <div key={star} style={{
                      display: 'flex', alignItems: 'center',
                      gap: 8, marginBottom: 6,
                    }}>
                      <span style={{ fontSize: 12, color: '#5F5E5A', width: 20 }}>
                        {star}星
                      </span>
                      <div style={{
                        flex: 1, height: 8, background: '#F0EDE6',
                        borderRadius: 4, overflow: 'hidden',
                      }}>
                        <div style={{
                          width: `${pct}%`, height: '100%',
                          background: Number(star) >= 4 ? '#0F6E56'
                            : Number(star) === 3 ? '#BA7517' : '#A32D2D',
                          borderRadius: 4,
                        }} />
                      </div>
                      <span style={{ fontSize: 11, color: '#B4B2A9', width: 28 }}>
                        {pct.toFixed(0)}%
                      </span>
                    </div>
                  );
                })}
              </div>

              <Divider style={{ margin: '16px 0' }} />

              {/* 近7天趋势 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{
                  fontSize: 13, fontWeight: 600, color: '#2C2C2A',
                  marginBottom: 12,
                }}>
                  近7天评分趋势
                </div>
                <RatingTrendSVG />
              </div>

              <Divider style={{ margin: '16px 0' }} />

              {/* 高频标签词云 */}
              <div>
                <div style={{
                  fontSize: 13, fontWeight: 600, color: '#2C2C2A',
                  marginBottom: 12,
                }}>
                  高频评价标签
                </div>
                <TagCloud tags={stats.top_tags} />
              </div>

              {stats._is_mock && (
                <div style={{
                  marginTop: 20, padding: '6px 10px',
                  background: '#FFF3ED', borderRadius: 4,
                  fontSize: 11, color: '#BA7517',
                }}>
                  当前显示 Mock 数据，接入真实数据库后自动生效
                </div>
              )}
            </div>
          )}
        </Drawer>
      </div>
    </ConfigProvider>
  );
}
