/**
 * AlertAggregationPage — AI人力预警中心（聚合分析页）
 *
 * Section 1: 预警处理效率指标 (4张StatisticCard)
 * Section 2: 预警趋势图 (Line chart + 时间范围切换)
 * Section 3: 门店风险排名 (ProTable)
 * Section 4: 风险矩阵 (热力图表格)
 * Section 5: 问题店列表 (Table + Tags)
 * Section 6: 周度简报 (Card + Descriptions + Timeline)
 *
 * API: GET /api/v1/alert-aggregation/*
 */

import { useEffect, useState } from 'react';
import { StatisticCard } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import {
  Button,
  Card,
  Col,
  Descriptions,
  message,
  Radio,
  Row,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  RiseOutlined,
  FallOutlined,
} from '@ant-design/icons';
import { Line } from '@ant-design/charts';
import { txFetchData } from '../../api/client';

const { Title, Text } = Typography;

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型定义
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface EffectivenessData {
  resolution_rate: number;
  avg_resolution_hours: number;
  dri_conversion_rate: number;
  total: number;
  resolved: number;
  by_type: { alert_type: string; resolution_rate: number; avg_hours: number; count: number }[];
}

interface TrendItem {
  period: string;
  alert_type: string;
  new_count: number;
  resolved_count: number;
}

interface StoreRisk {
  store_id: string;
  risk_score: number;
  alert_score: number;
  readiness_penalty: number;
  coverage_penalty: number;
}

interface MatrixCell {
  store_id: string;
  alert_type: string;
  critical_count: number;
  warning_count: number;
  info_count: number;
  weighted_score: number;
}

interface MatrixData {
  matrix: MatrixCell[];
  stores: string[];
  alert_types: string[];
}

interface ProblemStore {
  store_id: string;
  reasons: string[];
  critical_count: number;
  readiness_score: number | null;
  coverage_score: number | null;
}

interface WeeklyDigest {
  new_alerts: number;
  resolved_alerts: number;
  net_change: number;
  critical_events: { title: string; store_id: string; created_at: string }[];
  top_problem_stores: { store_id: string; risk_score: number }[];
  training_completions: number;
  new_certifications: number;
  wow_change: { alerts: number; resolution_rate: number };
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  常量
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const ALERT_TYPE_MAP: Record<string, string> = {
  turnover: '离职风险',
  peak_gap: '高峰缺口',
  training_lag: '培训滞后',
  schedule_imbalance: '排班失衡',
  new_store_gap: '新店缺编',
};

function getMatrixCellStyle(score: number): React.CSSProperties {
  if (score >= 7) return { backgroundColor: '#ff4d4f', color: '#fff', fontWeight: 600 };
  if (score >= 4) return { backgroundColor: '#fa8c16', color: '#fff', fontWeight: 600 };
  if (score >= 1) return { backgroundColor: '#fff7e6', color: '#d48806' };
  return { backgroundColor: '#fff' };
}

function getRiskScoreColor(score: number): string {
  if (score >= 10) return 'red';
  if (score >= 5) return 'orange';
  return 'green';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function AlertAggregationPage() {
  // ── state ──
  const [effectiveness, setEffectiveness] = useState<EffectivenessData | null>(null);
  const [trendData, setTrendData] = useState<TrendItem[]>([]);
  const [trendDays, setTrendDays] = useState<number>(30);
  const [trendMetric, setTrendMetric] = useState<'new' | 'resolved' | 'net'>('new');
  const [ranking, setRanking] = useState<StoreRisk[]>([]);
  const [matrix, setMatrix] = useState<MatrixData | null>(null);
  const [problems, setProblems] = useState<ProblemStore[]>([]);
  const [digest, setDigest] = useState<WeeklyDigest | null>(null);
  const [loading, setLoading] = useState(false);

  // ── 数据加载 ──
  const loadAll = async () => {
    setLoading(true);
    try {
      const [effRes, rankRes, matrixRes, probRes, digestRes] = await Promise.all([
        txFetchData<EffectivenessData>('/api/v1/alert-aggregation/action-effectiveness'),
        txFetchData<{ items: StoreRisk[] }>('/api/v1/alert-aggregation/store-risk-ranking'),
        txFetchData<MatrixData>('/api/v1/alert-aggregation/risk-matrix'),
        txFetchData<{ items: ProblemStore[] }>('/api/v1/alert-aggregation/problem-stores'),
        txFetchData<WeeklyDigest>('/api/v1/alert-aggregation/weekly-digest'),
      ]);
      setEffectiveness(effRes);
      setRanking(rankRes.items);
      setMatrix(matrixRes);
      setProblems(probRes.items);
      setDigest(digestRes);
    } catch {
      message.error('加载预警聚合数据失败');
    } finally {
      setLoading(false);
    }
  };

  const loadTrend = async (days: number) => {
    try {
      const res = await txFetchData<{ items: TrendItem[] }>(
        `/api/v1/alert-aggregation/trend-analysis?days=${days}&group_by=day`,
      );
      setTrendData(res.items);
    } catch {
      message.error('加载趋势数据失败');
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    loadTrend(trendDays);
  }, [trendDays]);

  // ── Section 2: 趋势图数据转换 ──
  const chartData = (() => {
    const grouped: Record<string, Record<string, { new_count: number; resolved_count: number }>> = {};
    for (const item of trendData) {
      if (!grouped[item.period]) grouped[item.period] = {};
      if (!grouped[item.period][item.alert_type]) {
        grouped[item.period][item.alert_type] = { new_count: 0, resolved_count: 0 };
      }
      grouped[item.period][item.alert_type].new_count += item.new_count;
      grouped[item.period][item.alert_type].resolved_count += item.resolved_count;
    }

    const result: { period: string; alert_type: string; count: number }[] = [];
    for (const [period, types] of Object.entries(grouped)) {
      for (const [alertType, counts] of Object.entries(types)) {
        let count = 0;
        if (trendMetric === 'new') count = counts.new_count;
        else if (trendMetric === 'resolved') count = counts.resolved_count;
        else count = counts.new_count - counts.resolved_count;

        result.push({
          period,
          alert_type: ALERT_TYPE_MAP[alertType] || alertType,
          count,
        });
      }
    }
    return result.sort((a, b) => a.period.localeCompare(b.period));
  })();

  // ── Section 3: 门店风险排名列 ──
  const rankingColumns: ProColumns<StoreRisk>[] = [
    {
      title: '排名',
      dataIndex: 'index',
      width: 60,
      search: false,
      render: (_: unknown, __: StoreRisk, index: number) => index + 1,
    },
    { title: '门店', dataIndex: 'store_id', width: 140 },
    {
      title: '综合风险分',
      dataIndex: 'risk_score',
      width: 120,
      sorter: true,
      search: false,
      render: (_: unknown, r: StoreRisk) => (
        <Tag color={getRiskScoreColor(r.risk_score)}>{r.risk_score.toFixed(1)}</Tag>
      ),
    },
    { title: '预警加权分', dataIndex: 'alert_score', width: 110, search: false },
    { title: '就绪度扣分', dataIndex: 'readiness_penalty', width: 110, search: false },
    { title: '覆盖度扣分', dataIndex: 'coverage_penalty', width: 110, search: false },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_: unknown, r: StoreRisk) => (
        <a onClick={() => message.info(`跳转门店画像: ${r.store_id}`)}>查看画像</a>
      ),
    },
  ];

  // ── Section 4: 风险矩阵动态列 ──
  const matrixColumns = (() => {
    if (!matrix) return [];
    const cols: Array<{
      title: string;
      dataIndex: string;
      key: string;
      width?: number;
      fixed?: 'left';
      render?: (_: unknown, row: Record<string, number | string>) => React.ReactNode;
    }> = [
      { title: '门店', dataIndex: 'store_id', key: 'store_id', width: 120, fixed: 'left' as const },
    ];
    for (const alertType of matrix.alert_types) {
      cols.push({
        title: ALERT_TYPE_MAP[alertType] || alertType,
        dataIndex: alertType,
        key: alertType,
        width: 100,
        render: (_: unknown, row: Record<string, number | string>) => {
          const score = (row[alertType] as number) || 0;
          return (
            <div
              style={{
                ...getMatrixCellStyle(score),
                textAlign: 'center',
                padding: '4px 8px',
                borderRadius: 4,
                minWidth: 40,
              }}
            >
              {score > 0 ? score.toFixed(1) : '-'}
            </div>
          );
        },
      });
    }
    return cols;
  })();

  const matrixDataSource = (() => {
    if (!matrix) return [];
    const map: Record<string, Record<string, number | string>> = {};
    for (const store of matrix.stores) {
      map[store] = { store_id: store, key: store };
    }
    for (const cell of matrix.matrix) {
      if (map[cell.store_id]) {
        map[cell.store_id][cell.alert_type] = cell.weighted_score;
      }
    }
    return Object.values(map);
  })();

  // ── Section 5: 问题店列表列 ──
  const problemColumns = [
    { title: '门店', dataIndex: 'store_id', key: 'store_id', width: 120 },
    {
      title: '问题类型',
      dataIndex: 'reasons',
      key: 'reasons',
      render: (reasons: string[]) => (
        <Space wrap>
          {reasons.map((r) => (
            <Tag key={r} color="volcano">{r}</Tag>
          ))}
        </Space>
      ),
    },
    { title: 'Critical预警数', dataIndex: 'critical_count', key: 'critical_count', width: 120 },
    {
      title: '就绪度',
      dataIndex: 'readiness_score',
      key: 'readiness_score',
      width: 100,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(0)}%` : '-'),
    },
    {
      title: '覆盖度',
      dataIndex: 'coverage_score',
      key: 'coverage_score',
      width: 100,
      render: (v: number | null) => (v != null ? `${(v * 100).toFixed(0)}%` : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, r: ProblemStore) => (
        <Button
          type="link"
          icon={<FileTextOutlined />}
          onClick={() => message.info(`创建DRI工单: ${r.store_id}`)}
        >
          创建DRI工单
        </Button>
      ),
    },
  ];

  // ── 渲染 ──
  const unresolved = effectiveness ? effectiveness.total - effectiveness.resolved : 0;

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <AlertOutlined style={{ marginRight: 8 }} />
        AI人力预警中心
      </Title>

      {/* ══ Section 1: 预警处理效率指标 ══ */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '解决率',
              value: effectiveness?.resolution_rate ?? 0,
              suffix: '%',
              valueStyle: { color: '#0F6E56' },
              icon: <CheckCircleOutlined style={{ color: '#0F6E56' }} />,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '平均解决时间',
              value: effectiveness?.avg_resolution_hours ?? 0,
              suffix: '小时',
              precision: 1,
              icon: <ClockCircleOutlined style={{ color: '#185FA5' }} />,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: 'DRI转化率',
              value: effectiveness?.dri_conversion_rate ?? 0,
              suffix: '%',
              icon: <RiseOutlined style={{ color: '#BA7517' }} />,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={loading}
            statistic={{
              title: '总未解决',
              value: unresolved,
              valueStyle: unresolved > 0 ? { color: '#A32D2D' } : undefined,
              icon: <AlertOutlined style={{ color: '#A32D2D' }} />,
            }}
          />
        </Col>
      </Row>

      {/* ══ Section 2: 预警趋势图 ══ */}
      <Card
        title="预警趋势"
        style={{ marginBottom: 24 }}
        extra={
          <Space>
            <Radio.Group
              value={trendMetric}
              onChange={(e) => setTrendMetric(e.target.value)}
              optionType="button"
              buttonStyle="solid"
              size="small"
            >
              <Radio.Button value="new">新增</Radio.Button>
              <Radio.Button value="resolved">解决</Radio.Button>
              <Radio.Button value="net">净增</Radio.Button>
            </Radio.Group>
            <Radio.Group
              value={trendDays}
              onChange={(e) => setTrendDays(e.target.value)}
              optionType="button"
              size="small"
            >
              <Radio.Button value={7}>7天</Radio.Button>
              <Radio.Button value={14}>14天</Radio.Button>
              <Radio.Button value={30}>30天</Radio.Button>
            </Radio.Group>
          </Space>
        }
      >
        <Line
          data={chartData}
          xField="period"
          yField="count"
          seriesField="alert_type"
          height={320}
          smooth
          point={{ size: 3 }}
          tooltip={{ shared: true }}
          legend={{ position: 'top' }}
          yAxis={{ title: { text: trendMetric === 'new' ? '新增数' : trendMetric === 'resolved' ? '解决数' : '净增数' } }}
          xAxis={{ title: { text: '日期' } }}
        />
      </Card>

      {/* ══ Section 3: 门店风险排名 ══ */}
      <Card title="门店风险排名" style={{ marginBottom: 24 }}>
        <ProTable<StoreRisk>
          columns={rankingColumns}
          dataSource={ranking}
          rowKey="store_id"
          loading={loading}
          search={false}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          options={{ density: true, reload: () => loadAll() }}
          dateFormatter="string"
        />
      </Card>

      {/* ══ Section 4: 风险矩阵 ══ */}
      <Card title="风险矩阵" style={{ marginBottom: 24 }}>
        <Table
          columns={matrixColumns}
          dataSource={matrixDataSource}
          loading={loading}
          pagination={false}
          scroll={{ x: 'max-content' }}
          bordered
          size="middle"
        />
      </Card>

      {/* ══ Section 5: 问题店列表 ══ */}
      <Card title="问题店整治清单" style={{ marginBottom: 24 }}>
        <Table<ProblemStore>
          columns={problemColumns}
          dataSource={problems}
          rowKey="store_id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* ══ Section 6: 周度简报 ══ */}
      <Card title="本周人力简报" style={{ marginBottom: 24 }}>
        {digest && (
          <Row gutter={24}>
            <Col span={12}>
              <Descriptions column={2} bordered size="small">
                <Descriptions.Item label="新增预警">{digest.new_alerts}</Descriptions.Item>
                <Descriptions.Item label="解决预警">{digest.resolved_alerts}</Descriptions.Item>
                <Descriptions.Item label="净变化">
                  <Text
                    style={{ color: digest.net_change > 0 ? '#A32D2D' : '#0F6E56', fontWeight: 600 }}
                  >
                    {digest.net_change > 0 ? (
                      <><RiseOutlined /> +{digest.net_change}</>
                    ) : (
                      <><FallOutlined /> {digest.net_change}</>
                    )}
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="训练完成数">{digest.training_completions}</Descriptions.Item>
                <Descriptions.Item label="新认证数">{digest.new_certifications}</Descriptions.Item>
                <Descriptions.Item label="预警环比">
                  <Text style={{ color: digest.wow_change.alerts > 0 ? '#A32D2D' : '#0F6E56' }}>
                    {digest.wow_change.alerts > 0 ? '+' : ''}{digest.wow_change.alerts}%
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="解决率环比">
                  <Text style={{ color: digest.wow_change.resolution_rate >= 0 ? '#0F6E56' : '#A32D2D' }}>
                    {digest.wow_change.resolution_rate > 0 ? '+' : ''}{digest.wow_change.resolution_rate}%
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="问题门店" span={2}>
                  <Space wrap>
                    {digest.top_problem_stores.map((s) => (
                      <Tag key={s.store_id} color={getRiskScoreColor(s.risk_score)}>
                        {s.store_id} ({s.risk_score.toFixed(1)})
                      </Tag>
                    ))}
                  </Space>
                </Descriptions.Item>
              </Descriptions>
            </Col>
            <Col span={12}>
              <Text strong style={{ marginBottom: 12, display: 'block' }}>Critical事件</Text>
              {digest.critical_events.length > 0 ? (
                <Timeline
                  items={digest.critical_events.map((evt) => ({
                    color: 'red',
                    children: (
                      <>
                        <Text strong>{evt.title}</Text>
                        <br />
                        <Text type="secondary">{evt.store_id} | {evt.created_at}</Text>
                      </>
                    ),
                  }))}
                />
              ) : (
                <Text type="secondary">本周无Critical事件</Text>
              )}
            </Col>
          </Row>
        )}
      </Card>
    </div>
  );
}
