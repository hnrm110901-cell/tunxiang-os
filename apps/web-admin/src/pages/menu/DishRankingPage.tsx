/**
 * P3-04 菜品5因子动态排名引擎页面
 * 三个Tab：排行榜 / 四象限矩阵 / 健康诊断报告
 */
import { useState, useEffect } from 'react';
import {
  Tabs,
  Table,
  Tag,
  Progress,
  Card,
  Row,
  Col,
  Slider,
  Button,
  Alert,
  Spin,
  Typography,
  Space,
  Tooltip,
  Badge,
  message,
  Statistic,
  Divider,
  List,
} from 'antd';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  MinusOutlined,
  FireOutlined,
  InfoCircleOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text, Paragraph } = Typography;

const API_BASE = 'http://localhost:8002';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface DishScores {
  volume: number;
  margin: number;
  reorder: number;
  satisfaction: number;
  trend: number;
}

interface DishRankItem {
  dish_id: string;
  dish_name: string;
  category: string;
  price_fen: number;
  scores: DishScores;
  composite_score: number;
  rank: number;
  rank_change: number;
  recommendation_tag: string;
}

interface MatrixQuadrant {
  label: string;
  advice: string;
  dishes: { dish_name: string; composite_score: number; volume_score: number; margin_score: number }[];
  count: number;
}

interface HealthItem {
  dish_id: string;
  dish_name: string;
  composite_score?: number;
  volume_score?: number;
  margin_score?: number;
  price_fen?: number;
  reason: string;
  suggestion: string;
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

/** @deprecated — use formatPrice from @tx-ds/utils */
const fmtPrice = (fen: number) => `¥${(fen / 100).toFixed(0)}`;

const TAG_COLORS: Record<string, string> = {
  明星菜品: '#FF6B35',
  现金牛: '#0F6E56',
  问题菜品: '#BA7517',
  瘦狗: '#A32D2D',
  潜力菜品: '#185FA5',
};

const QUADRANT_BG: Record<string, string> = {
  star: '#FFF3ED',
  cash_cow: '#F0FDF4',
  question: '#FFFBEB',
  dog: '#FEF2F2',
};

const QUADRANT_BORDER: Record<string, string> = {
  star: '#FF6B35',
  cash_cow: '#0F6E56',
  question: '#BA7517',
  dog: '#A32D2D',
};

// ─── 子组件：5因子Mini进度条 ─────────────────────────────────────────────────

function ScoreBars({ scores }: { scores: DishScores }) {
  const factors = [
    { key: 'volume', label: '销量', color: '#FF6B35' },
    { key: 'margin', label: '毛利', color: '#0F6E56' },
    { key: 'reorder', label: '复购', color: '#185FA5' },
    { key: 'satisfaction', label: '满意', color: '#BA7517' },
    { key: 'trend', label: '趋势', color: '#7C3AED' },
  ] as const;

  return (
    <div style={{ minWidth: 180 }}>
      {factors.map(f => (
        <div key={f.key} style={{ display: 'flex', alignItems: 'center', marginBottom: 2 }}>
          <Text style={{ fontSize: 11, color: '#5F5E5A', width: 28, flexShrink: 0 }}>{f.label}</Text>
          <Progress
            percent={Math.round(scores[f.key] * 100)}
            size="small"
            strokeColor={f.color}
            showInfo={false}
            style={{ flex: 1, margin: '0 6px' }}
          />
          <Text style={{ fontSize: 11, color: '#2C2C2A', width: 28, textAlign: 'right' }}>
            {(scores[f.key] * 100).toFixed(0)}
          </Text>
        </div>
      ))}
    </div>
  );
}

// ─── 子组件：排名变化箭头 ────────────────────────────────────────────────────

function RankChange({ change }: { change: number }) {
  if (change > 0) {
    return (
      <Space>
        <ArrowUpOutlined style={{ color: '#0F6E56' }} />
        <Text style={{ color: '#0F6E56', fontWeight: 600 }}>+{change}</Text>
      </Space>
    );
  }
  if (change < 0) {
    return (
      <Space>
        <ArrowDownOutlined style={{ color: '#A32D2D' }} />
        <Text style={{ color: '#A32D2D', fontWeight: 600 }}>{change}</Text>
      </Space>
    );
  }
  return (
    <Space>
      <MinusOutlined style={{ color: '#B4B2A9' }} />
      <Text style={{ color: '#B4B2A9' }}>持平</Text>
    </Space>
  );
}

// ─── Tab1: 排行榜 ────────────────────────────────────────────────────────────

function RankingTab({ storeId }: { storeId: string }) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DishRankItem[]>([]);
  const [weights, setWeights] = useState({
    volume: 30, margin: 30, reorder: 20, satisfaction: 10, trend: 10,
  });
  const [weightsTotal, setWeightsTotal] = useState(100);
  const [saving, setSaving] = useState(false);

  const fetchRanking = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/menu/ranking/dishes?store_id=${storeId}&limit=20`);
      const json = await res.json();
      if (json.ok) setData(json.data.items);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchRanking(); }, []);

  const handleWeightChange = (key: keyof typeof weights, val: number) => {
    const next = { ...weights, [key]: val };
    setWeights(next);
    setWeightsTotal(Object.values(next).reduce((a, b) => a + b, 0));
  };

  const handleSaveWeights = async () => {
    if (Math.abs(weightsTotal - 100) > 0) {
      message.error('5因子权重之和必须等于100（即1.0），请调整后再保存');
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/menu/ranking/weights`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          volume: weights.volume / 100,
          margin: weights.margin / 100,
          reorder: weights.reorder / 100,
          satisfaction: weights.satisfaction / 100,
          trend: weights.trend / 100,
        }),
      });
      const json = await res.json();
      if (json.ok) {
        message.success('权重已更新，排名将重新计算');
        fetchRanking();
      } else {
        message.error(json.detail || '保存失败');
      }
    } finally {
      setSaving(false);
    }
  };

  const weightTotalOk = Math.abs(weightsTotal - 100) <= 0;
  const totalColor = weightTotalOk ? '#0F6E56' : '#A32D2D';

  const columns: ColumnsType<DishRankItem> = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 60,
      render: (rank: number) => (
        <div
          style={{
            width: 28, height: 28, borderRadius: '50%',
            background: rank <= 3 ? '#FF6B35' : '#F8F7F5',
            color: rank <= 3 ? '#fff' : '#2C2C2A',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 600, fontSize: 13,
          }}
        >
          {rank}
        </div>
      ),
    },
    {
      title: '菜品',
      dataIndex: 'dish_name',
      width: 130,
      render: (name: string, row: DishRankItem) => (
        <div>
          <Text strong style={{ fontSize: 14 }}>{name}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>{row.category} · {fmtPrice(row.price_fen)}</Text>
        </div>
      ),
    },
    {
      title: '5因子评分',
      key: 'scores',
      width: 220,
      render: (_: unknown, row: DishRankItem) => <ScoreBars scores={row.scores} />,
    },
    {
      title: '综合分',
      dataIndex: 'composite_score',
      width: 90,
      sorter: (a, b) => a.composite_score - b.composite_score,
      render: (score: number) => (
        <div style={{ textAlign: 'center' }}>
          <Text
            strong
            style={{
              fontSize: 20,
              color: score >= 0.8 ? '#FF6B35' : score >= 0.6 ? '#0F6E56' : score >= 0.4 ? '#BA7517' : '#A32D2D',
            }}
          >
            {(score * 100).toFixed(0)}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>/100</Text>
        </div>
      ),
    },
    {
      title: '周变化',
      dataIndex: 'rank_change',
      width: 80,
      render: (change: number) => <RankChange change={change} />,
    },
    {
      title: '标签',
      dataIndex: 'recommendation_tag',
      width: 90,
      render: (tag: string) => (
        <Tag
          color={TAG_COLORS[tag] || '#999'}
          style={{ color: '#fff', border: 'none', fontWeight: 500 }}
        >
          {tag}
        </Tag>
      ),
    },
  ];

  const WEIGHT_FACTORS = [
    { key: 'volume' as const, label: '销量因子', desc: '绝对销售量标准化' },
    { key: 'margin' as const, label: '毛利因子', desc: '毛利率×销售额综合' },
    { key: 'reorder' as const, label: '复购率因子', desc: '同会员N天内复点率' },
    { key: 'satisfaction' as const, label: '满意度因子', desc: '好评率+低退菜率综合' },
    { key: 'trend' as const, label: '热度趋势', desc: '近7天 vs 前7天增长率' },
  ];

  return (
    <div>
      {/* 权重配置区 */}
      <Card
        title={
          <Space>
            <ThunderboltOutlined style={{ color: '#FF6B35' }} />
            <span>5因子权重配置</span>
          </Space>
        }
        extra={
          <Space>
            <Text style={{ color: totalColor, fontWeight: 600 }}>
              权重合计：{weightsTotal}%
              {weightTotalOk ? ' ✓' : ' ✗ 需等于100%'}
            </Text>
            <Button
              type="primary"
              size="small"
              loading={saving}
              disabled={!weightTotalOk}
              onClick={handleSaveWeights}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              保存权重
            </Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
        bodyStyle={{ padding: '12px 24px' }}
      >
        <Row gutter={32}>
          {WEIGHT_FACTORS.map(f => (
            <Col span={4} key={f.key}>
              <div>
                <Tooltip title={f.desc}>
                  <Text strong style={{ fontSize: 13 }}>{f.label}</Text>
                  <InfoCircleOutlined style={{ marginLeft: 4, color: '#B4B2A9', fontSize: 12 }} />
                </Tooltip>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                  <Slider
                    min={0}
                    max={100}
                    step={5}
                    value={weights[f.key]}
                    onChange={(v) => handleWeightChange(f.key, v)}
                    style={{ flex: 1 }}
                    tooltip={{ formatter: (v) => `${v}%` }}
                    styles={{ track: { background: '#FF6B35' } }}
                  />
                  <Text style={{ width: 38, textAlign: 'right', fontWeight: 600, color: totalColor }}>
                    {weights[f.key]}%
                  </Text>
                </div>
              </div>
            </Col>
          ))}
        </Row>
      </Card>

      {/* 排名表格 */}
      <Card>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="dish_id"
          loading={loading}
          pagination={false}
          size="middle"
          rowClassName={(_, index) => index < 3 ? 'top3-row' : ''}
        />
      </Card>
    </div>
  );
}

// ─── Tab2: 四象限矩阵 ────────────────────────────────────────────────────────

function MatrixTab({ storeId }: { storeId: string }) {
  const [loading, setLoading] = useState(false);
  const [matrix, setMatrix] = useState<Record<string, MatrixQuadrant> | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/v1/menu/ranking/matrix?store_id=${storeId}`)
      .then(r => r.json())
      .then(json => { if (json.ok) setMatrix(json.data); })
      .finally(() => setLoading(false));
  }, [storeId]);

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />;
  if (!matrix) return null;

  const QUADRANTS = [
    { key: 'question', position: 'top-left', title: '问题菜品', subtitle: '低销量 · 高毛利', icon: '❓' },
    { key: 'star', position: 'top-right', title: '明星菜品', subtitle: '高销量 · 高毛利', icon: '⭐' },
    { key: 'dog', position: 'bottom-left', title: '瘦狗', subtitle: '低销量 · 低毛利', icon: '🐕' },
    { key: 'cash_cow', position: 'bottom-right', title: '现金牛', subtitle: '高销量 · 低毛利', icon: '💰' },
  ];

  return (
    <div>
      <Alert
        message="BCG四象限矩阵"
        description="横轴：销量因子得分（高→右）| 纵轴：毛利因子得分（高→上）。每个象限代表不同的菜品经营策略。"
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        style={{ marginBottom: 16 }}
      />

      {/* 坐标轴标签 */}
      <div style={{ position: 'relative', marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginBottom: 4 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>↑ 毛利高</Text>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gridTemplateRows: '1fr 1fr',
            gap: 12,
            minHeight: 460,
          }}
        >
          {QUADRANTS.map(q => {
            const qData = matrix[q.key];
            return (
              <Card
                key={q.key}
                size="small"
                style={{
                  background: QUADRANT_BG[q.key],
                  border: `2px solid ${QUADRANT_BORDER[q.key]}`,
                  borderRadius: 8,
                }}
                title={
                  <Space>
                    <span>{q.icon}</span>
                    <Text strong style={{ color: QUADRANT_BORDER[q.key] }}>{q.title}</Text>
                    <Badge count={qData.count} style={{ background: QUADRANT_BORDER[q.key] }} />
                    <Text type="secondary" style={{ fontSize: 12 }}>{q.subtitle}</Text>
                  </Space>
                }
              >
                <Paragraph
                  style={{
                    fontSize: 12, color: '#5F5E5A',
                    background: '#fff', borderRadius: 4, padding: '6px 8px', marginBottom: 8,
                  }}
                >
                  💡 {qData.advice}
                </Paragraph>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {qData.dishes.map(d => (
                    <Tooltip
                      key={d.dish_name}
                      title={`综合分: ${(d.composite_score * 100).toFixed(0)} | 销量: ${(d.volume_score * 100).toFixed(0)} | 毛利: ${(d.margin_score * 100).toFixed(0)}`}
                    >
                      <Tag
                        style={{
                          cursor: 'default',
                          borderColor: QUADRANT_BORDER[q.key],
                          color: QUADRANT_BORDER[q.key],
                          background: '#fff',
                        }}
                      >
                        {d.dish_name}
                      </Tag>
                    </Tooltip>
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>销量高 →</Text>
        </div>
      </div>
    </div>
  );
}

// ─── Tab3: 健康诊断报告 ──────────────────────────────────────────────────────

interface HealthReport {
  attention_needed: HealthItem[];
  worth_promoting: HealthItem[];
  price_depression: HealthItem[];
  summary: { total_dishes: number; healthy_count: number; warning_count: number; critical_count: number };
}

function HealthTab({ storeId }: { storeId: string }) {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<HealthReport | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/v1/menu/ranking/health-report?store_id=${storeId}`)
      .then(r => r.json())
      .then(json => { if (json.ok) setReport(json.data); })
      .finally(() => setLoading(false));
  }, [storeId]);

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />;
  if (!report) return null;

  return (
    <div>
      {/* 汇总指标 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic title="品项总数" value={report.summary.total_dishes} />
          </Card>
        </Col>
        <Col span={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title="健康品项"
              value={report.summary.healthy_count}
              valueStyle={{ color: '#0F6E56' }}
              suffix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title="需关注"
              value={report.summary.warning_count}
              valueStyle={{ color: '#BA7517' }}
              suffix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title="需立即处理"
              value={report.summary.critical_count}
              valueStyle={{ color: '#A32D2D' }}
              suffix={<FireOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 需要立即关注 */}
      <Alert
        type="error"
        showIcon
        icon={<FireOutlined />}
        message={`需要立即关注（${report.attention_needed.length} 道菜）`}
        description="综合评分低于30分，建议考虑下架或大幅调整"
        style={{ marginBottom: 12 }}
      />
      {report.attention_needed.length === 0 ? (
        <Alert type="success" message="暂无需要立即关注的菜品" style={{ marginBottom: 16 }} />
      ) : (
        <List
          dataSource={report.attention_needed}
          style={{ marginBottom: 20 }}
          renderItem={(item) => (
            <List.Item>
              <Card size="small" style={{ width: '100%', border: '1px solid #FECACA', background: '#FEF2F2' }}>
                <Row align="middle" gutter={16}>
                  <Col span={5}><Text strong>{item.dish_name}</Text></Col>
                  <Col span={3}>
                    <Text strong style={{ color: '#A32D2D', fontSize: 18 }}>
                      {item.composite_score !== undefined ? (item.composite_score * 100).toFixed(0) : '--'}
                    </Text>
                    <Text type="secondary"> /100</Text>
                  </Col>
                  <Col span={6}><Text type="secondary">{item.reason}</Text></Col>
                  <Col span={10}>
                    <Tag color="red" style={{ padding: '2px 8px' }}>{item.suggestion}</Tag>
                  </Col>
                </Row>
              </Card>
            </List.Item>
          )}
        />
      )}

      <Divider />

      {/* 值得推广 */}
      <Alert
        type="info"
        showIcon
        icon={<ThunderboltOutlined />}
        message={`值得推广的潜力菜（${report.worth_promoting.length} 道菜）`}
        description="综合品质高但曝光不足，营销推广后可能成为下一个明星菜品"
        style={{ marginBottom: 12 }}
      />
      {report.worth_promoting.length === 0 ? (
        <Alert type="success" message="暂无待推广菜品" style={{ marginBottom: 16 }} />
      ) : (
        <List
          dataSource={report.worth_promoting}
          style={{ marginBottom: 20 }}
          renderItem={(item) => (
            <List.Item>
              <Card size="small" style={{ width: '100%', border: '1px solid #BAE6FD', background: '#F0F9FF' }}>
                <Row align="middle" gutter={16}>
                  <Col span={5}><Text strong>{item.dish_name}</Text></Col>
                  <Col span={3}>
                    <Text strong style={{ color: '#185FA5', fontSize: 18 }}>
                      {item.composite_score !== undefined ? (item.composite_score * 100).toFixed(0) : '--'}
                    </Text>
                    <Text type="secondary"> /100</Text>
                  </Col>
                  <Col span={6}><Text type="secondary">{item.reason}</Text></Col>
                  <Col span={10}>
                    <Tag color="blue" style={{ padding: '2px 8px' }}>{item.suggestion}</Tag>
                  </Col>
                </Row>
              </Card>
            </List.Item>
          )}
        />
      )}

      <Divider />

      {/* 价格洼地 */}
      <Alert
        type="warning"
        showIcon
        icon={<WarningOutlined />}
        message={`价格洼地（${report.price_depression.length} 道菜）`}
        description="销量好但毛利低，存在明显提价空间，适当调价预计影响销量不超过10%"
        style={{ marginBottom: 12 }}
      />
      {report.price_depression.length === 0 ? (
        <Alert type="success" message="暂无价格洼地菜品" style={{ marginBottom: 16 }} />
      ) : (
        <List
          dataSource={report.price_depression}
          renderItem={(item) => (
            <List.Item>
              <Card size="small" style={{ width: '100%', border: '1px solid #FDE68A', background: '#FFFBEB' }}>
                <Row align="middle" gutter={16}>
                  <Col span={4}><Text strong>{item.dish_name}</Text></Col>
                  <Col span={3}>
                    <Text style={{ color: '#5F5E5A' }}>现价 {item.price_fen !== undefined ? fmtPrice(item.price_fen) : '--'}</Text>
                  </Col>
                  <Col span={5}><Text type="secondary">{item.reason}</Text></Col>
                  <Col span={12}>
                    <Tag color="gold" style={{ padding: '2px 8px' }}>{item.suggestion}</Tag>
                  </Col>
                </Row>
              </Card>
            </List.Item>
          )}
        />
      )}
    </div>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function DishRankingPage() {
  const storeId = 'store-001'; // 实际应从租户上下文获取

  const tabItems = [
    {
      key: 'ranking',
      label: (
        <Space>
          <FireOutlined />
          菜品排行榜
        </Space>
      ),
      children: <RankingTab storeId={storeId} />,
    },
    {
      key: 'matrix',
      label: (
        <Space>
          <InfoCircleOutlined />
          四象限矩阵
        </Space>
      ),
      children: <MatrixTab storeId={storeId} />,
    },
    {
      key: 'health',
      label: (
        <Space>
          <CheckCircleOutlined />
          健康诊断报告
        </Space>
      ),
      children: <HealthTab storeId={storeId} />,
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0, color: '#2C2C2A' }}>
          菜品5因子动态排名
        </Title>
        <Text type="secondary">
          基于销量 · 毛利 · 复购率 · 满意度 · 热度趋势五大因子综合评分，驱动菜品结构持续优化
        </Text>
      </div>

      <Tabs
        defaultActiveKey="ranking"
        items={tabItems}
        size="large"
        style={{ background: '#fff', padding: '0 16px', borderRadius: 8 }}
      />
    </div>
  );
}
