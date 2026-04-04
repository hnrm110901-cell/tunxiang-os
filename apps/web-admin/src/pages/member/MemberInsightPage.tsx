/**
 * MemberInsightPage — 会员洞察分析页
 * 调用 POST /api/v1/brain/member/insight
 * 支持单会员分析 + CSV批量分析
 */
import { useState, useRef } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  List,
  Progress,
  Row,
  Space,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  ExclamationCircleOutlined,
  RocketOutlined,
  UploadOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { txFetch } from '../../api';

const { Title, Text } = Typography;

// ─── 类型定义 ───

interface PurchaseHistoryItem {
  order_id: string;
  date: string;
  total_fen: number;
  items: string[];
}

interface InsightPayload {
  customer_id: string;
  purchase_history: PurchaseHistoryItem[];
  member_tier: string;
  visit_count: number;
  total_spend_fen: number;
}

interface DishRecommendation {
  dish_name: string;
  reason: string;
}

interface InsightResult {
  customer_id: string;
  member_tier: 'vip' | 'regular' | 'at_risk' | 'new';
  tags: string[];
  dish_recommendations: DishRecommendation[];
  action_suggestions: { priority: number; text: string }[];
  stats: {
    monthly_avg_spend_fen: number;
    top_categories: string[];
    last_visit_date: string;
  };
}

interface BatchRow {
  key: string;
  customer_id: string;
  member_tier: string;
  dish_count: number;
  action_count: number;
  status: 'pending' | 'success' | 'error';
  error?: string;
}

// ─── 常量 ───

const TIER_COLOR: Record<string, string> = {
  vip: 'gold',
  regular: 'blue',
  at_risk: 'orange',
  new: 'green',
};

const TIER_LABEL: Record<string, string> = {
  vip: 'VIP',
  regular: '普通',
  at_risk: '流失风险',
  new: '新客',
};

const PRIORITY_ICON: Record<number, string> = {
  1: '🔴',
  2: '🟡',
  3: '🟢',
};

function buildMockPayload(customerId: string): InsightPayload {
  return {
    customer_id: customerId,
    purchase_history: [
      { order_id: 'mock1', date: '2026-03-28', total_fen: 23800, items: ['东星斑', '蒸鱼'] },
      { order_id: 'mock2', date: '2026-03-15', total_fen: 45600, items: ['帝王蟹', '龙虾'] },
      { order_id: 'mock3', date: '2026-02-20', total_fen: 18900, items: ['海鲜拼盘'] },
      { order_id: 'mock4', date: '2026-02-05', total_fen: 31200, items: ['花胶鸡', '清蒸石斑'] },
      { order_id: 'mock5', date: '2026-01-18', total_fen: 66900, items: ['波士顿龙虾', '鲍鱼'] },
    ],
    member_tier: 'regular',
    visit_count: 8,
    total_spend_fen: 186400,
  };
}

// ─── 单会员分析 ───

function SingleInsightPanel() {
  const [customerId, setCustomerId] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<InsightResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    if (!customerId.trim()) {
      message.warning('请输入会员ID');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = buildMockPayload(customerId.trim());
      const data = await txFetch<InsightResult>('/api/v1/brain/member/insight', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setResult(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '分析失败，请重试';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 触发区 */}
      <Card size="small" title="单会员 AI 分析" style={{ borderRadius: 6 }}>
        <Space.Compact style={{ width: '100%', maxWidth: 480 }}>
          <Input
            prefix={<UserOutlined />}
            placeholder="输入会员ID，例如 C20240001"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            onPressEnter={handleAnalyze}
          />
          <Button
            type="primary"
            icon={<RocketOutlined />}
            loading={loading}
            onClick={handleAnalyze}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            AI 分析会员
          </Button>
        </Space.Compact>
      </Card>

      {/* 错误提示 */}
      {error && (
        <Alert
          type="error"
          message="分析失败"
          description={error}
          showIcon
          closable
          onClose={() => setError(null)}
        />
      )}

      {/* 分析结果 */}
      {result && (
        <Row gutter={[16, 16]}>
          {/* 会员标签 */}
          <Col span={24}>
            <Card
              size="small"
              title={
                <Space>
                  <span>会员标签</span>
                  <Tag color={TIER_COLOR[result.member_tier] ?? 'default'}>
                    {TIER_LABEL[result.member_tier] ?? result.member_tier}
                  </Tag>
                </Space>
              }
              style={{ borderRadius: 6 }}
            >
              <Space wrap>
                {result.tags.map((tag) => (
                  <Tag key={tag} color="#185FA5" style={{ borderRadius: 4 }}>
                    {tag}
                  </Tag>
                ))}
              </Space>
            </Card>
          </Col>

          {/* 推荐菜品 */}
          <Col xs={24} lg={12}>
            <Card size="small" title="推荐菜品" style={{ borderRadius: 6, height: '100%' }}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                {result.dish_recommendations.map((dish) => (
                  <Card
                    key={dish.dish_name}
                    size="small"
                    style={{
                      borderRadius: 6,
                      background: '#FFF3ED',
                      border: '1px solid #FFD4B8',
                      minWidth: 160,
                      flex: '1 1 160px',
                    }}
                  >
                    <Text strong style={{ color: '#FF6B35' }}>
                      {dish.dish_name}
                    </Text>
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {dish.reason}
                      </Text>
                    </div>
                  </Card>
                ))}
              </div>
            </Card>
          </Col>

          {/* 行动建议 */}
          <Col xs={24} lg={12}>
            <Card size="small" title="行动建议" style={{ borderRadius: 6, height: '100%' }}>
              <List
                size="small"
                dataSource={result.action_suggestions.sort((a, b) => a.priority - b.priority)}
                renderItem={(item) => (
                  <List.Item>
                    <Space>
                      <span>{PRIORITY_ICON[item.priority] ?? '⚪'}</span>
                      <Text>{item.text}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          </Col>

          {/* 消费统计摘要 */}
          <Col span={24}>
            <Card size="small" title="消费统计摘要" style={{ borderRadius: 6 }}>
              <Descriptions
                column={{ xs: 1, sm: 2, md: 3 }}
                size="small"
                bordered
              >
                <Descriptions.Item label="月均消费">
                  <Text strong style={{ color: '#FF6B35' }}>
                    ¥{(result.stats.monthly_avg_spend_fen / 100).toFixed(2)}
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="常点品类">
                  <Space wrap>
                    {result.stats.top_categories.map((c) => (
                      <Tag key={c}>{c}</Tag>
                    ))}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="最近消费时间">
                  {result.stats.last_visit_date}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}

// ─── 批量分析 ───

function BatchInsightPanel() {
  const [batchRows, setBatchRows] = useState<BatchRow[]>([]);
  const [progress, setProgress] = useState(0);
  const [running, setRunning] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const abortRef = useRef(false);

  const handleUpload = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      const lines = text
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
        .slice(0, 100); // max 100
      const rows: BatchRow[] = lines.map((id) => ({
        key: id,
        customer_id: id,
        member_tier: '-',
        dish_count: 0,
        action_count: 0,
        status: 'pending',
      }));
      setBatchRows(rows);
      setProgress(0);
      setBatchError(null);
    };
    reader.readAsText(file);
    return false; // prevent default upload behavior
  };

  const handleBatchRun = async () => {
    if (batchRows.length === 0) {
      message.warning('请先上传 CSV 文件');
      return;
    }
    setRunning(true);
    abortRef.current = false;
    const updated = [...batchRows];

    for (let i = 0; i < updated.length; i++) {
      if (abortRef.current) break;
      const row = updated[i];
      try {
        const payload = buildMockPayload(row.customer_id);
        const data = await txFetch<InsightResult>('/api/v1/brain/member/insight', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        updated[i] = {
          ...row,
          member_tier: TIER_LABEL[data.member_tier] ?? data.member_tier,
          dish_count: data.dish_recommendations.length,
          action_count: data.action_suggestions.length,
          status: 'success',
        };
      } catch (err: unknown) {
        updated[i] = {
          ...row,
          status: 'error',
          error: err instanceof Error ? err.message : '分析失败',
        };
      }
      setBatchRows([...updated]);
      setProgress(Math.round(((i + 1) / updated.length) * 100));
    }
    setRunning(false);
  };

  const columns: ProColumns<BatchRow>[] = [
    { title: '会员ID', dataIndex: 'customer_id', width: 160 },
    {
      title: '分层结果',
      dataIndex: 'member_tier',
      width: 100,
      render: (val: unknown) => {
        const tierKey = Object.keys(TIER_LABEL).find((k) => TIER_LABEL[k] === val);
        return tierKey ? (
          <Tag color={TIER_COLOR[tierKey]}>{String(val)}</Tag>
        ) : (
          <span style={{ color: '#B4B2A9' }}>-</span>
        );
      },
    },
    {
      title: '推荐菜品数',
      dataIndex: 'dish_count',
      width: 100,
      render: (val: unknown) => <Text>{val === 0 ? '-' : String(val)}</Text>,
    },
    {
      title: '行动建议数',
      dataIndex: 'action_count',
      width: 100,
      render: (val: unknown) => <Text>{val === 0 ? '-' : String(val)}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_: unknown, row: BatchRow) => {
        if (row.status === 'success') return <Tag color="green">成功</Tag>;
        if (row.status === 'error')
          return (
            <Tag color="red" title={row.error}>
              失败
            </Tag>
          );
        return <Tag color="default">待处理</Tag>;
      },
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card
        size="small"
        title="批量分析"
        extra={
          <Space>
            <Upload accept=".csv,.txt" beforeUpload={handleUpload} showUploadList={false}>
              <Button icon={<UploadOutlined />}>上传会员ID列表（CSV，最多100条）</Button>
            </Upload>
            <Button
              type="primary"
              loading={running}
              disabled={batchRows.length === 0}
              onClick={handleBatchRun}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              {running ? '分析中...' : '开始批量分析'}
            </Button>
            {running && (
              <Button
                danger
                onClick={() => {
                  abortRef.current = true;
                }}
              >
                停止
              </Button>
            )}
          </Space>
        }
        style={{ borderRadius: 6 }}
      >
        {batchError && (
          <Alert
            type="error"
            message={batchError}
            showIcon
            closable
            style={{ marginBottom: 12 }}
            onClose={() => setBatchError(null)}
          />
        )}
        {(running || progress > 0) && batchRows.length > 0 && (
          <Progress
            percent={progress}
            status={running ? 'active' : 'success'}
            style={{ marginBottom: 12 }}
            format={(p) => `${p}% (${batchRows.filter((r) => r.status !== 'pending').length}/${batchRows.length})`}
          />
        )}
        {batchRows.length > 0 ? (
          <ProTable<BatchRow>
            dataSource={batchRows}
            columns={columns}
            rowKey="key"
            search={false}
            pagination={{ pageSize: 20 }}
            toolBarRender={false}
            size="small"
          />
        ) : (
          <div style={{ textAlign: 'center', padding: '32px 0', color: '#B4B2A9' }}>
            <ExclamationCircleOutlined style={{ fontSize: 24, marginBottom: 8, display: 'block' }} />
            <span>上传包含会员ID的 CSV 文件（每行一个ID）以开始批量分析</span>
          </div>
        )}
      </Card>
    </div>
  );
}

// ─── 主页面 ───

export function MemberInsightPage() {
  const [tab, setTab] = useState<'single' | 'batch'>('single');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          AI 会员洞察分析
        </Title>
        <Tag color="#185FA5" style={{ fontSize: 11 }}>
          Brain Agent
        </Tag>
      </div>

      {/* Tab 切换 */}
      <Card size="small" style={{ borderRadius: 6 }} bodyStyle={{ padding: '0' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid #E8E6E1' }}>
          {[
            { key: 'single', label: '单会员分析' },
            { key: 'batch', label: '批量分析' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key as 'single' | 'batch')}
              style={{
                padding: '10px 24px',
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: tab === key ? 600 : 400,
                color: tab === key ? '#FF6B35' : '#5F5E5A',
                borderBottom: tab === key ? '2px solid #FF6B35' : '2px solid transparent',
                transition: 'all 0.15s',
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ padding: 16 }}>
          {tab === 'single' ? <SingleInsightPanel /> : <BatchInsightPanel />}
        </div>
      </Card>
    </div>
  );
}
