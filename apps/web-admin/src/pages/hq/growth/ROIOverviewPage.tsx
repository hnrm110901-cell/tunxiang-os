/**
 * ROIOverviewPage — 全渠道 ROI 总览
 * 路由: /hq/growth/roi
 *
 * 数据来源（真实 API，降级策略）：
 *   1. /api/v1/private-domain/roi-trend        — 私域 ROI 趋势
 *   2. /api/v1/finance/analytics/revenue-composition — 渠道收入
 *   3. /api/v1/finance/analytics/trend         — 财务趋势（月度投入/产出/利润）
 *   4. /api/v1/member/analytics/growth         — 拉新数据
 *
 * 如 API 返回空数据，各 Section 独立降级显示"数据收集中"占位，不崩溃。
 */
import { useState, useEffect, useMemo } from 'react';
import {
  Card,
  Row,
  Col,
  Table,
  Tag,
  Statistic,
  Alert,
  Select,
  Typography,
  Space,
  Spin,
  Empty,
  Badge,
  Tooltip,
} from 'antd';
import {
  RiseOutlined,
  FallOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { formatPrice } from '@tx-ds/utils';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface RoiTrendPoint {
  date: string;              // "2026-03-01"
  attributed_revenue: number; // 归因收入（分）
  marketing_cost: number;    // 营销成本（分）
  roi: number;               // ROI 倍数
  degraded?: boolean;
}

interface RevenueChannel {
  name: string;
  amount_fen: number;
  percent: number;
}

interface FinanceTrendPoint {
  date: string;
  revenue_fen: number;
  cost_fen: number;
  profit_fen: number;
  margin_rate: number;
}

interface MemberGrowthPoint {
  date: string;
  new_members: number;
  total_members: number;
  growth_rate: number;
}

// ─── 渠道 ROI 配置（静态元数据，名称/颜色，数据来自 API） ───────────────────

const CHANNEL_META: Record<string, { color: string; defaultCAC: number; defaultLTV: number }> = {
  '美团/点评':  { color: '#FF6B35', defaultCAC: 35,  defaultLTV: 680 },
  '抖音本地':   { color: '#1890ff', defaultCAC: 28,  defaultLTV: 520 },
  '微信私域':   { color: '#0F6E56', defaultCAC: 12,  defaultLTV: 890 },
  '小红书':     { color: '#722ed1', defaultCAC: 45,  defaultLTV: 450 },
  '线下地推':   { color: '#BA7517', defaultCAC: 18,  defaultLTV: 720 },
};

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fen2wan = (fen: number) => (fen / 1_000_000).toFixed(1) + '万';
/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => (fen / 100).toFixed(0);

/** ROI 数字颜色规则：≥3=绿色 / 1-3=蓝色 / <1=红色 */
function roiColor(roi: number): string {
  if (roi >= 3) return '#0F6E56';
  if (roi >= 1) return '#185FA5';
  return '#A32D2D';
}

function roiTag(roi: number) {
  if (roi >= 3) return <Tag color="success">{roi.toFixed(1)}x</Tag>;
  if (roi >= 1) return <Tag color="blue">{roi.toFixed(1)}x</Tag>;
  return <Tag color="error">{roi.toFixed(1)}x</Tag>;
}

// ─── 纯 SVG 折线图 ───────────────────────────────────────────────────────────

interface SVGLineChartProps {
  data: Array<{ label: string; investment: number; revenue: number; profit: number }>;
}

function SVGLineChart({ data }: SVGLineChartProps) {
  if (!data.length) return null;

  const W = 600;
  const H = 200;
  const PAD_L = 60;
  const PAD_R = 20;
  const PAD_T = 20;
  const PAD_B = 36;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const maxVal = Math.max(...data.flatMap(d => [d.investment, d.revenue, d.profit]));
  const n = data.length;

  const xPos = (i: number) => PAD_L + (i / (n - 1 || 1)) * chartW;
  const yPos = (v: number) => PAD_T + chartH - (v / (maxVal || 1)) * chartH;

  type LineKey = 'investment' | 'revenue' | 'profit';
  const lines: Array<{ key: LineKey; color: string; label: string }> = [
    { key: 'revenue',    color: '#1890ff', label: '产出' },
    { key: 'profit',     color: '#0F6E56', label: '利润' },
    { key: 'investment', color: '#A32D2D', label: '投入' },
  ];

  const polyline = (key: LineKey) =>
    data.map((d, i) => `${xPos(i).toFixed(1)},${yPos(d[key]).toFixed(1)}`).join(' ');

  // Y 轴刻度
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(t => ({
    y: PAD_T + chartH * (1 - t),
    label: fen2wan(maxVal * t),
  }));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
      {/* 网格线 */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} y1={t.y} x2={W - PAD_R} y2={t.y}
            stroke="#E8E6E1" strokeWidth="1" strokeDasharray="4 4" />
          <text x={PAD_L - 6} y={t.y + 4} textAnchor="end"
            fontSize="10" fill="#B4B2A9">{t.label}</text>
        </g>
      ))}

      {/* 折线 */}
      {lines.map(l => (
        <polyline
          key={l.key}
          points={polyline(l.key)}
          fill="none"
          stroke={l.color}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ))}

      {/* 数据点 */}
      {lines.map(l =>
        data.map((d, i) => (
          <circle
            key={`${l.key}-${i}`}
            cx={xPos(i)}
            cy={yPos(d[l.key])}
            r="3"
            fill={l.color}
          />
        ))
      )}

      {/* X 轴标签 */}
      {data.map((d, i) => (
        <text
          key={i}
          x={xPos(i)}
          y={H - 6}
          textAnchor="middle"
          fontSize="10"
          fill="#B4B2A9"
        >{d.label}</text>
      ))}

      {/* 图例 */}
      {lines.map((l, i) => (
        <g key={l.key} transform={`translate(${PAD_L + i * 70}, ${PAD_T - 8})`}>
          <line x1="0" y1="0" x2="16" y2="0" stroke={l.color} strokeWidth="2" />
          <circle cx="8" cy="0" r="3" fill={l.color} />
          <text x="20" y="4" fontSize="10" fill="#5F5E5A">{l.label}</text>
        </g>
      ))}
    </svg>
  );
}

// ─── 渠道 ROI 表格行类型 ────────────────────────────────────────────────────

interface ChannelROIRow {
  key: string;
  name: string;
  investment: number;    // 分
  revenue: number;       // 分
  roi: number;
  cac: number;           // 元
  ltv: number;           // 元
  color: string;
}

// ─── 主页面 ─────────────────────────────────────────────────────────────────

export function ROIOverviewPage() {
  const [period, setPeriod] = useState<'month' | 'quarter' | 'year'>('month');
  const [roiTrend, setRoiTrend]           = useState<RoiTrendPoint[]>([]);
  const [revenueChannels, setRevenueChannels] = useState<RevenueChannel[]>([]);
  const [financeTrend, setFinanceTrend]   = useState<FinanceTrendPoint[]>([]);
  const [memberGrowth, setMemberGrowth]   = useState<MemberGrowthPoint[]>([]);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState<string | null>(null);
  const [degradedChannels, setDegradedChannels] = useState(false);

  // ── 拉取数据 ──────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const daysByPeriod = { month: 30, quarter: 90, year: 365 };
    const days = daysByPeriod[period];

    Promise.allSettled([
      txFetchData<{ items: RoiTrendPoint[]; degraded?: boolean }>(
        `/api/v1/private-domain/roi-trend?days=${days}`,
      ),
      txFetchData<{ items: RevenueChannel[] }>(
        `/api/v1/finance/analytics/revenue-composition?period=${period}`,
      ),
      txFetchData<{ items: FinanceTrendPoint[] }>(
        `/api/v1/finance/analytics/trend?period=month&days=${days}`,
      ),
      txFetchData<{ items: MemberGrowthPoint[] }>(
        `/api/v1/member/analytics/growth?period=month&days=${days}`,
      ),
    ]).then(([roiRes, chRes, finRes, memRes]) => {
      if (cancelled) return;

      if (roiRes.status === 'fulfilled') {
        setRoiTrend(roiRes.value.items ?? []);
      }

      if (chRes.status === 'fulfilled' && (chRes.value.items ?? []).length > 0) {
        setRevenueChannels(chRes.value.items);
        setDegradedChannels(false);
      } else {
        setRevenueChannels([]);
        setDegradedChannels(true);
      }

      if (finRes.status === 'fulfilled') {
        setFinanceTrend(finRes.value.items ?? []);
      }

      if (memRes.status === 'fulfilled') {
        setMemberGrowth(memRes.value.items ?? []);
      }

      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [period]);

  // ── 计算汇总指标 ──────────────────────────────────────────────────────────

  const kpi = useMemo(() => {
    if (!roiTrend.length && !financeTrend.length) return null;

    const latestFinance = financeTrend[financeTrend.length - 1];
    const prevFinance   = financeTrend[financeTrend.length - 2];

    const totalInvestment = financeTrend.reduce((s, d) => s + d.cost_fen,    0);
    const totalRevenue    = financeTrend.reduce((s, d) => s + d.revenue_fen, 0);
    const totalProfit     = financeTrend.reduce((s, d) => s + d.profit_fen,  0);
    const overallROI      = totalInvestment > 0 ? totalRevenue / totalInvestment : 0;

    // 月环比（使用最近两个月的 profit）
    const momProfit = (latestFinance && prevFinance && prevFinance.profit_fen > 0)
      ? ((latestFinance.profit_fen - prevFinance.profit_fen) / prevFinance.profit_fen * 100)
      : null;

    // 新增会员
    const totalNewMembers = memberGrowth.reduce((s, d) => s + d.new_members, 0);

    return { totalInvestment, totalRevenue, totalProfit, overallROI, momProfit, totalNewMembers };
  }, [financeTrend, memberGrowth]);

  // ── 渠道 ROI 表格数据（从 revenue-composition 组合） ─────────────────────

  const channelRows = useMemo((): ChannelROIRow[] => {
    if (!revenueChannels.length) return [];

    const totalRevenue  = revenueChannels.reduce((s, c) => s + c.amount_fen, 0);
    const totalInvestment = financeTrend.reduce((s, d) => s + d.cost_fen, 0);

    return revenueChannels
      .filter(c => c.amount_fen > 0)
      .map((ch, i) => {
        const meta = CHANNEL_META[ch.name] ?? {
          color: '#8c8c8c',
          defaultCAC: 30,
          defaultLTV: 500,
        };
        // 按渠道收入占比估算投入
        const investmentShare = totalRevenue > 0 ? ch.amount_fen / totalRevenue : 0;
        const investment      = Math.round(totalInvestment * investmentShare);
        const roi             = investment > 0 ? ch.amount_fen / investment : 0;

        return {
          key:        String(i),
          name:       ch.name,
          investment,
          revenue:    ch.amount_fen,
          roi,
          cac:        meta.defaultCAC,
          ltv:        meta.defaultLTV,
          color:      meta.color,
        };
      })
      .sort((a, b) => b.roi - a.roi);
  }, [revenueChannels, financeTrend]);

  // ── ROI 趋势折线图数据（聚合到月份） ─────────────────────────────────────

  const svgChartData = useMemo(() => {
    if (!financeTrend.length) return [];
    return financeTrend.slice(-6).map(d => ({
      label: d.date.slice(0, 7).replace('-', '/'),
      investment: d.cost_fen,
      revenue:    d.revenue_fen,
      profit:     d.profit_fen,
    }));
  }, [financeTrend]);

  // ── 渠道 ROI 表格列 ───────────────────────────────────────────────────────

  const channelColumns = [
    {
      title: '渠道',
      dataIndex: 'name',
      render: (name: string, row: ChannelROIRow) => (
        <Space>
          <span style={{ display: 'inline-block', width: 10, height: 10,
            borderRadius: '50%', background: row.color }} />
          <Text strong>{name}</Text>
        </Space>
      ),
    },
    {
      title: '投入（元）',
      dataIndex: 'investment',
      align: 'right' as const,
      render: (v: number) => <Text>{Number(fen2yuan(v)).toLocaleString()}</Text>,
    },
    {
      title: '带来收益（元）',
      dataIndex: 'revenue',
      align: 'right' as const,
      render: (v: number) => <Text type="success">{Number(fen2yuan(v)).toLocaleString()}</Text>,
    },
    {
      title: 'ROI',
      dataIndex: 'roi',
      align: 'center' as const,
      render: (v: number) => roiTag(v),
      sorter: (a: ChannelROIRow, b: ChannelROIRow) => a.roi - b.roi,
    },
    {
      title: '获客成本（元）',
      dataIndex: 'cac',
      align: 'right' as const,
      render: (v: number) => <Text>{v}</Text>,
    },
    {
      title: 'LTV（元）',
      dataIndex: 'ltv',
      align: 'right' as const,
      render: (v: number, row: ChannelROIRow) => (
        <Tooltip title={`LTV/CAC = ${(row.ltv / row.cac).toFixed(1)}x`}>
          <Text>{v}</Text>
        </Tooltip>
      ),
    },
  ];

  // ── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: '24px 0' }}>
      {/* 标题 + 筛选栏 */}
      <Row align="middle" justify="space-between" style={{ marginBottom: 20 }}>
        <Col>
          <Title level={3} style={{ margin: 0 }}>全渠道 ROI 总览</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            基于私域归因、财务趋势、收入构成综合计算
          </Text>
        </Col>
        <Col>
          <Space>
            <Select
              value={period}
              onChange={setPeriod}
              style={{ width: 110 }}
              options={[
                { value: 'month',   label: '近 30 天' },
                { value: 'quarter', label: '近 90 天' },
                { value: 'year',    label: '近一年'   },
              ]}
            />
          </Space>
        </Col>
      </Row>

      <Spin spinning={loading} tip="加载中...">

        {/* ── Section 1：核心 ROI 指标卡片 ──────────────────────────────── */}
        {kpi ? (
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={24} sm={12} md={6}>
              <Card size="small" bordered style={{ background: '#F8F7F5' }}>
                <Statistic
                  title="总营销投入"
                  value={fen2wan(kpi.totalInvestment)}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>含所有渠道推广费</Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card size="small" bordered style={{ background: '#F8F7F5' }}>
                <Statistic
                  title="总拉新收益"
                  value={fen2wan(kpi.totalRevenue)}
                  valueStyle={{ color: '#185FA5' }}
                />
                <Text style={{ fontSize: 12 }}>
                  新增会员 {kpi.totalNewMembers.toLocaleString()} 人
                </Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card size="small" bordered style={{ background: '#F8F7F5' }}>
                <Statistic
                  title="综合 ROI"
                  value={kpi.overallROI.toFixed(2) + 'x'}
                  valueStyle={{ color: roiColor(kpi.overallROI) }}
                />
                {kpi.overallROI >= 3
                  ? <Tag color="success" style={{ fontSize: 11 }}>目标达成</Tag>
                  : kpi.overallROI >= 1
                    ? <Tag color="blue" style={{ fontSize: 11 }}>增长中</Tag>
                    : <Tag color="error" style={{ fontSize: 11 }}>待优化</Tag>}
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card size="small" bordered style={{ background: '#F8F7F5' }}>
                <Statistic
                  title="利润贡献"
                  value={fen2wan(kpi.totalProfit)}
                  valueStyle={{ color: '#0F6E56' }}
                />
                {kpi.momProfit !== null ? (
                  <Space size={4} style={{ fontSize: 12 }}>
                    {kpi.momProfit >= 0
                      ? <RiseOutlined style={{ color: '#0F6E56' }} />
                      : <FallOutlined style={{ color: '#A32D2D' }} />}
                    <Text style={{ fontSize: 12, color: kpi.momProfit >= 0 ? '#0F6E56' : '#A32D2D' }}>
                      月环比 {Math.abs(kpi.momProfit).toFixed(1)}%
                    </Text>
                  </Space>
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>环比数据不足</Text>
                )}
              </Card>
            </Col>
          </Row>
        ) : !loading && (
          <Alert
            type="info"
            icon={<InfoCircleOutlined />}
            showIcon
            message="核心指标数据收集中"
            description="需要完整接入财务趋势接口后可查看准确 ROI 汇总。当前显示的渠道数据可能不完整。"
            style={{ marginBottom: 24 }}
          />
        )}

        {/* ── Section 2：渠道 ROI 对比表格 ──────────────────────────────── */}
        <Card
          title={
            <Space>
              渠道 ROI 对比
              <Badge
                color={degradedChannels ? '#BA7517' : '#0F6E56'}
                text={
                  <Text style={{ fontSize: 12 }} type={degradedChannels ? 'warning' : 'success'}>
                    {degradedChannels ? '数据估算中' : '实时数据'}
                  </Text>
                }
              />
            </Space>
          }
          style={{ marginBottom: 24 }}
          extra={
            degradedChannels && (
              <Tooltip title="渠道收入数据来自 revenue-composition 接口，获客成本/LTV 为行业参考值，接入广告平台 API 后可精确计算">
                <InfoCircleOutlined style={{ color: '#BA7517', cursor: 'pointer' }} />
              </Tooltip>
            )
          }
        >
          {degradedChannels && (
            <Alert
              type="warning"
              showIcon
              message="数据收集中，需要完整接入各渠道广告数据后可查看准确 ROI"
              description="当前渠道投入根据收入占比估算，CAC/LTV 为行业参考基准值。"
              style={{ marginBottom: 16 }}
              closable
            />
          )}
          {channelRows.length > 0 ? (
            <Table<ChannelROIRow>
              dataSource={channelRows}
              columns={channelColumns}
              pagination={false}
              size="middle"
              rowKey="key"
              summary={rows => {
                const totalInv = rows.reduce((s, r) => s + r.investment, 0);
                const totalRev = rows.reduce((s, r) => s + r.revenue, 0);
                const totalRoi = totalInv > 0 ? totalRev / totalInv : 0;
                return (
                  <Table.Summary.Row style={{ fontWeight: 700 }}>
                    <Table.Summary.Cell index={0}>合计</Table.Summary.Cell>
                    <Table.Summary.Cell index={1} align="right">
                      {Number(fen2yuan(totalInv)).toLocaleString()}
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={2} align="right">
                      <Text type="success">{Number(fen2yuan(totalRev)).toLocaleString()}</Text>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={3} align="center">
                      {roiTag(totalRoi)}
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={4} />
                    <Table.Summary.Cell index={5} />
                  </Table.Summary.Row>
                );
              }}
            />
          ) : !loading && (
            <Empty
              description={
                <span>
                  渠道数据暂无<br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    请确认 /api/v1/finance/analytics/revenue-composition 接口已返回数据
                  </Text>
                </span>
              }
            />
          )}
        </Card>

        {/* ── Section 3：活动 ROI 列表（来自私域 ROI 趋势聚合） ─────────── */}
        <Card
          title="私域渠道 ROI 趋势明细"
          style={{ marginBottom: 24 }}
          extra={
            <Text type="secondary" style={{ fontSize: 12 }}>
              数据源：/api/v1/private-domain/roi-trend
            </Text>
          }
        >
          {roiTrend.length > 0 ? (
            <Table<RoiTrendPoint>
              dataSource={roiTrend.slice(-10).reverse()}
              rowKey="date"
              size="small"
              pagination={false}
              columns={[
                {
                  title: '日期',
                  dataIndex: 'date',
                  render: (d: string) => <Text code style={{ fontSize: 12 }}>{d}</Text>,
                },
                {
                  title: '归因收入（元）',
                  dataIndex: 'attributed_revenue',
                  align: 'right' as const,
                  render: (v: number) => <Text type="success">{Number(fen2yuan(v)).toLocaleString()}</Text>,
                },
                {
                  title: '营销成本（元）',
                  dataIndex: 'marketing_cost',
                  align: 'right' as const,
                  render: (v: number) => <Text>{Number(fen2yuan(v)).toLocaleString()}</Text>,
                },
                {
                  title: 'ROI',
                  dataIndex: 'roi',
                  align: 'center' as const,
                  render: (v: number) => roiTag(v),
                },
                {
                  title: '状态',
                  dataIndex: 'degraded',
                  align: 'center' as const,
                  render: (v: boolean) => v
                    ? <Tag color="warning">估算</Tag>
                    : <Tag color="success">精确</Tag>,
                },
              ]}
            />
          ) : !loading && (
            <Alert
              type="info"
              showIcon
              message="私域 ROI 数据收集中"
              description="需要完整接入企微/小程序归因数据后可查看每日 ROI 趋势。当前私域运营数据尚未接入。"
            />
          )}
        </Card>

        {/* ── Section 4：利润趋势折线图（纯 SVG） ───────────────────────── */}
        <Card title="利润贡献趋势（近6个月）">
          {svgChartData.length >= 2 ? (
            <div style={{ padding: '8px 0' }}>
              <SVGLineChart data={svgChartData} />
              {/* 数据明细表 */}
              <Table
                dataSource={svgChartData.map((d, i) => ({ ...d, key: i }))}
                size="small"
                pagination={false}
                style={{ marginTop: 16 }}
                columns={[
                  {
                    title: '月份',
                    dataIndex: 'label',
                    render: (v: string) => <Text code style={{ fontSize: 12 }}>{v}</Text>,
                  },
                  {
                    title: '产出',
                    dataIndex: 'revenue',
                    align: 'right' as const,
                    render: (v: number) => <Text style={{ color: '#1890ff' }}>{fen2wan(v)}</Text>,
                  },
                  {
                    title: '投入',
                    dataIndex: 'investment',
                    align: 'right' as const,
                    render: (v: number) => <Text style={{ color: '#A32D2D' }}>{fen2wan(v)}</Text>,
                  },
                  {
                    title: '利润',
                    dataIndex: 'profit',
                    align: 'right' as const,
                    render: (v: number) => <Text style={{ color: '#0F6E56', fontWeight: 700 }}>{fen2wan(v)}</Text>,
                  },
                  {
                    title: 'ROI',
                    align: 'center' as const,
                    render: (_: unknown, row: typeof svgChartData[0]) => {
                      const roi = row.investment > 0 ? row.revenue / row.investment : 0;
                      return roiTag(roi);
                    },
                  },
                ]}
              />
            </div>
          ) : !loading && (
            <Alert
              type="info"
              showIcon
              message="利润趋势数据不足"
              description="需要至少 2 个月的财务趋势数据才能绘制折线图。请确认 /api/v1/finance/analytics/trend 接口已返回数据。"
            />
          )}
        </Card>

      </Spin>

      {error && (
        <Alert
          type="error"
          showIcon
          message="数据加载失败"
          description={error}
          style={{ marginTop: 16 }}
          closable
          onClose={() => setError(null)}
        />
      )}
    </div>
  );
}
