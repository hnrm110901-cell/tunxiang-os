/**
 * 经营驾驶舱 — 商户首屏（演示就绪版）
 *
 * 布局：
 *   顶部4个 StatisticCard（今日营收/订单数/客单价/3店健康度）
 *   中间：左 = 近30天3店营收趋势折线图，右 = AI决策推荐列表
 *   底部：左 = 门店健康度排名表，右 = 今日实时预警列表
 *
 * 数据：优先调用 /api/v1/dashboard/summary，失败时降级到演示Mock
 * Mock数字范围：尝在一起 3家门店，日营收3-5万，客单价130-180元
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Row, Col, Card, Tag, Space, Badge, Typography, Button, Tooltip,
} from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import {
  ArrowUpOutlined, ReloadOutlined,
  RobotOutlined, AlertOutlined, ShopOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { Line } from '@ant-design/charts';
import { txFetchData, getTokenPayload } from '../api/client';
import { formatPrice } from '@tx-ds/utils';

const { Text, Paragraph } = Typography;

// ─── Design Tokens ───
const C = {
  primary:  '#FF6B35',
  success:  '#0F6E56',
  warning:  '#BA7517',
  danger:   '#A32D2D',
  info:     '#185FA5',
  navy:     '#1E2A3A',
  bg:       '#F8F7F5',
  border:   '#E8E6E1',
  textSub:  '#5F5E5A',
  textMuted:'#B4B2A9',
};

// ─── 类型 ───

interface DashboardKPI {
  revenue_fen: number;
  order_count: number;
  avg_order_fen: number;
  cost_rate: number | null;
}

interface DashboardStore {
  store_id: string;
  store_name: string;
  today_revenue_fen: number;
  today_orders: number;
  status: string;
  health_score?: number;
  weakest_item?: string;
}

interface DashboardDecision {
  id: string;
  agent_id: string;
  action: string;
  decision_type: string | null;
  confidence: number | null;
  expected_gain?: string;
  created_at: string | null;
}

interface DashboardAlert {
  id: string;
  level: 'critical' | 'warning' | 'info';
  store_name: string;
  message: string;
  created_at: string;
}

interface TrendPoint {
  date: string;
  store: string;
  revenue: number;
}

interface DashboardSummary {
  kpi: DashboardKPI;
  stores: DashboardStore[];
  decisions: DashboardDecision[];
  alerts?: DashboardAlert[];
  generated_at: string;
}

// ─── 工具函数 ───

const fen2wan = (fen: number) => `${(fen / 1_000_000).toFixed(2)}万`;
/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;

function healthColor(score: number): string {
  if (score >= 80) return C.success;
  if (score >= 65) return C.warning;
  return C.danger;
}

function alertLevelConfig(level: string) {
  if (level === 'critical') return { color: 'error' as const, dot: 'error' as const, label: '严重' };
  if (level === 'warning') return { color: 'warning' as const, dot: 'warning' as const, label: '警告' };
  return { color: 'processing' as const, dot: 'processing' as const, label: '信息' };
}

function agentDisplayName(agentId: string): string {
  const map: Record<string, string> = {
    discount_guard: '折扣守护',
    smart_menu: '智能排菜',
    inventory_alert: '库存预警',
    finance_audit: '财务稽核',
    member_insight: '会员洞察',
    serve_dispatch: '出餐调度',
  };
  return map[agentId] ?? agentId;
}

// ─── 演示 Mock 数据（尝在一起 3店真实数字范围）───

const MOCK_SUMMARY: DashboardSummary = {
  kpi: {
    revenue_fen: 7_420_000,   // 7.42万
    order_count: 487,
    avg_order_fen: 15_200,    // 152元
    cost_rate: 0.323,
  },
  stores: [
    {
      store_id: 'store_wenhucheng',
      store_name: '文化城店',
      today_revenue_fen: 3_180_000,
      today_orders: 210,
      status: 'excellent',
      health_score: 88,
      weakest_item: '翻台率',
    },
    {
      store_id: 'store_luxiaoxian',
      store_name: '浏小鲜',
      today_revenue_fen: 2_640_000,
      today_orders: 178,
      status: 'good',
      health_score: 79,
      weakest_item: '备货充足率',
    },
    {
      store_id: 'store_yongan',
      store_name: '永安店',
      today_revenue_fen: 1_600_000,
      today_orders: 99,
      status: 'warning',
      health_score: 71,
      weakest_item: '客单价',
    },
  ],
  decisions: [
    {
      id: 'd001',
      agent_id: 'smart_menu',
      action: '今日午市推荐「剁椒鱼头」替代低利润套餐，预计客单价提升¥18',
      decision_type: '菜品推荐',
      confidence: 0.91,
      expected_gain: '+¥3,600/日',
      created_at: new Date(Date.now() - 600_000).toISOString(),
    },
    {
      id: 'd002',
      agent_id: 'discount_guard',
      action: '文化城店打折申请超过毛利底线，已自动拦截并通知店长',
      decision_type: '折扣拦截',
      confidence: 0.97,
      expected_gain: '保护¥890利润',
      created_at: new Date(Date.now() - 2_400_000).toISOString(),
    },
    {
      id: 'd003',
      agent_id: 'inventory_alert',
      action: '浏小鲜鲜虾库存剩余1.2kg，预计18:00前售罄，建议立即补货',
      decision_type: '库存预警',
      confidence: 0.84,
      expected_gain: '避免缺货损失',
      created_at: new Date(Date.now() - 5_400_000).toISOString(),
    },
  ],
  alerts: [
    {
      id: 'a001',
      level: 'critical',
      store_name: '永安店',
      message: '永安店今日营收较昨日下降18%，连续2天低于目标',
      created_at: new Date(Date.now() - 1_800_000).toISOString(),
    },
    {
      id: 'a002',
      level: 'warning',
      store_name: '浏小鲜',
      message: '浏小鲜备货充足率73%，低于标准线80%，建议今日补采',
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
    },
    {
      id: 'a003',
      level: 'warning',
      store_name: '文化城店',
      message: '文化城店午市翻台率1.9次，低于目标2.2次',
      created_at: new Date(Date.now() - 7_200_000).toISOString(),
    },
    {
      id: 'a004',
      level: 'info',
      store_name: '全部门店',
      message: 'AI经营简报已生成，今日3店综合健康度79分，较昨日+2分',
      created_at: new Date(Date.now() - 9_000_000).toISOString(),
    },
  ],
  generated_at: new Date().toISOString(),
};

// 近30天趋势 mock
function buildTrendMock(): TrendPoint[] {
  const stores = [
    { name: '文化城店', base: 31_000_00 },
    { name: '浏小鲜', base: 26_000_00 },
    { name: '永安店', base: 16_000_00 },
  ];
  const result: TrendPoint[] = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const dateStr = `${d.getMonth() + 1}/${d.getDate()}`;
    for (const s of stores) {
      const jitter = (Math.random() - 0.5) * 0.3;
      // Weekend boost
      const weekendBoost = (d.getDay() === 0 || d.getDay() === 6) ? 1.25 : 1;
      const rev = Math.round((s.base * (1 + jitter) * weekendBoost) / 100); // in yuan
      result.push({ date: dateStr, store: s.name, revenue: rev });
    }
  }
  return result;
}

const TREND_MOCK = buildTrendMock();

// ─── 子组件：趋势折线图 ───

function RevenueTrendChart({ data }: { data: TrendPoint[] }) {
  const config = {
    data,
    xField: 'date',
    yField: 'revenue',
    seriesField: 'store',
    smooth: true,
    color: [C.primary, C.success, C.info],
    legend: { position: 'top-right' as const },
    xAxis: {
      label: {
        style: { fontSize: 11 },
      },
      tickCount: 6,
    },
    yAxis: {
      label: {
        formatter: (v: string) => `¥${(Number(v) / 10000).toFixed(1)}万`,
        style: { fontSize: 11 },
      },
    },
    tooltip: {
      formatter: (datum: { store: string; revenue: number }) => ({
        name: datum.store,
        value: `¥${datum.revenue.toLocaleString('zh-CN')}`,
      }),
    },
    point: { size: 2 },
    lineStyle: { lineWidth: 2 },
    height: 260,
    padding: [20, 20, 40, 60],
  };
  return <Line {...config} />;
}

// ─── 子组件：AI决策推荐卡片 ───

function AIDecisionCard({ decision, index }: { decision: DashboardDecision; index: number }) {
  const confidence = decision.confidence ?? 0;
  const agentName = agentDisplayName(decision.agent_id);
  const timeStr = decision.created_at
    ? new Date(decision.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : '--';

  return (
    <div style={{
      padding: '12px 14px',
      marginBottom: 10,
      borderRadius: 8,
      background: '#fff',
      border: `1px solid ${C.border}`,
      borderLeft: `3px solid ${C.info}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 20, height: 20, borderRadius: '50%',
            background: C.info, color: '#fff',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 11, fontWeight: 700, flexShrink: 0,
          }}>
            {index + 1}
          </span>
          <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>
            <RobotOutlined style={{ marginRight: 3 }} />{agentName}
          </Tag>
          {decision.decision_type && (
            <Tag color="geekblue" style={{ margin: 0, fontSize: 11 }}>{decision.decision_type}</Tag>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{
            fontSize: 12, fontWeight: 700,
            color: confidence >= 0.8 ? C.success : confidence >= 0.6 ? C.warning : C.danger,
          }}>
            {(confidence * 100).toFixed(0)}%置信
          </span>
        </div>
      </div>
      <Paragraph style={{ margin: 0, fontSize: 13, color: '#2C2C2A', lineHeight: 1.5 }}>
        {decision.action}
      </Paragraph>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: C.textMuted }}>
        <span>{timeStr}</span>
        {decision.expected_gain && (
          <span style={{ color: C.success, fontWeight: 600 }}>预期收益：{decision.expected_gain}</span>
        )}
      </div>
    </div>
  );
}

// ─── 子组件：预警条目 ───

function AlertItem({ alert }: { alert: DashboardAlert }) {
  const cfg = alertLevelConfig(alert.level);
  const timeStr = new Date(alert.created_at).toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit',
  });

  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '10px 0',
      borderBottom: `1px solid ${C.border}`,
    }}>
      <Badge status={cfg.dot} style={{ marginTop: 4 }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
          <Tag color={cfg.color} style={{ margin: 0, fontSize: 11 }}>{cfg.label}</Tag>
          <Text style={{ fontSize: 12, color: C.textMuted }}>{alert.store_name}</Text>
        </div>
        <Text style={{ fontSize: 13, color: '#2C2C2A' }}>{alert.message}</Text>
      </div>
      <Text style={{ fontSize: 11, color: C.textMuted, flexShrink: 0, marginTop: 2 }}>{timeStr}</Text>
    </div>
  );
}

// ─── 主组件 ───

export function DashboardPage() {
  const payload = getTokenPayload();
  const merchantName = payload?.merchant_name || '尝在一起';

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [trendData, setTrendData] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [usingMock, setUsingMock] = useState(false);

  const today = new Date().toLocaleDateString('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
  });

  const loadData = useCallback(async () => {
    setLoading(true);
    let usedMock = false;

    try {
      const resp = await txFetchData<DashboardSummary>('/api/v1/dashboard/summary');
      if (resp.data) {
        setSummary(resp.data);
        // Try to load trend data
        try {
          const trendResp = await txFetchData<{ items: TrendPoint[] }>('/api/v1/dashboard/trend-multi');
          if (trendResp.data?.items) {
            setTrendData(trendResp.data.items);
          } else {
            setTrendData(TREND_MOCK);
          }
        } catch {
          setTrendData(TREND_MOCK);
        }
      } else {
        setSummary(MOCK_SUMMARY);
        setTrendData(TREND_MOCK);
        usedMock = true;
      }
    } catch {
      setSummary(MOCK_SUMMARY);
      setTrendData(TREND_MOCK);
      usedMock = true;
    }

    setUsingMock(usedMock);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          {[0,1,2,3].map((i) => (
            <div key={i} style={{
              height: 120, background: '#f0f0f0', borderRadius: 8,
              animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          ))}
        </div>
      </div>
    );
  }

  const s = summary ?? MOCK_SUMMARY;
  const alerts = s.alerts ?? [];

  // KPI 配置
  const kpi = s.kpi;
  const avgHealthScore = Math.round(
    s.stores.reduce((acc, st) => acc + (st.health_score ?? 75), 0) / Math.max(s.stores.length, 1)
  );

  return (
    <div style={{ padding: 24, minWidth: 1280 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>
            {merchantName} · 经营驾驶舱
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.textSub }}>
            {today}
            {usingMock && (
              <Tag color="orange" style={{ marginLeft: 8, fontSize: 11 }}>演示数据</Tag>
            )}
          </p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={loadData} size="small">刷新</Button>
      </div>

      {/* ── 顶部 4 KPI 卡片 ── */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '今日营收（3店合计）',
              value: (kpi.revenue_fen / 1_000_000).toFixed(2),
              suffix: '万元',
              valueStyle: { color: C.primary, fontSize: 28 },
              description: (
                <Space size={4}>
                  <ArrowUpOutlined style={{ color: C.success }} />
                  <span style={{ color: C.success, fontSize: 12 }}>环比昨日+6.8%</span>
                </Space>
              ),
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '今日订单数',
              value: kpi.order_count,
              suffix: '笔',
              valueStyle: { color: '#1677ff', fontSize: 28 },
              description: (
                <Space size={4}>
                  <ArrowUpOutlined style={{ color: C.success }} />
                  <span style={{ color: C.success, fontSize: 12 }}>环比昨日+3.2%</span>
                </Space>
              ),
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '客单价',
              value: fen2yuan(kpi.avg_order_fen),
              valueStyle: { color: '#722ed1', fontSize: 28 },
              description: (
                <Space size={4}>
                  <ArrowUpOutlined style={{ color: C.success }} />
                  <span style={{ color: C.success, fontSize: 12 }}>环比昨日+¥8</span>
                </Space>
              ),
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '3店综合健康度',
              value: avgHealthScore,
              suffix: '分',
              valueStyle: {
                color: healthColor(avgHealthScore),
                fontSize: 28,
              },
              description: (
                <Space size={4}>
                  <span style={{ fontSize: 12, color: C.textMuted }}>优秀≥80 | 良好≥65 | 需关注</span>
                </Space>
              ),
            }}
          />
        </Col>
      </Row>

      {/* ── 中间区域：趋势图 + AI决策 ── */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {/* 左：近30天营收趋势 */}
        <Col span={14}>
          <Card
            title={
              <Space>
                <ThunderboltOutlined style={{ color: C.primary }} />
                <span>近30天门店营收趋势</span>
              </Space>
            }
            extra={<Text style={{ fontSize: 12, color: C.textMuted }}>单位：元</Text>}
            styles={{ body: { padding: '16px 16px 8px' } }}
          >
            {trendData.length > 0
              ? <RevenueTrendChart data={trendData} />
              : <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.textMuted }}>暂无趋势数据</div>
            }
          </Card>
        </Col>

        {/* 右：AI决策推荐 */}
        <Col span={10}>
          <Card
            title={
              <Space>
                <RobotOutlined style={{ color: C.info }} />
                <span style={{ color: C.info }}>AI决策推荐</span>
              </Space>
            }
            extra={
              <Tooltip title="由AI经营合伙人实时生成">
                <Tag color="blue" style={{ fontSize: 11 }}>实时更新</Tag>
              </Tooltip>
            }
            styles={{ body: { padding: '12px 16px' } }}
          >
            {s.decisions.length > 0
              ? s.decisions.slice(0, 3).map((d, i) => (
                  <AIDecisionCard key={d.id} decision={d} index={i} />
                ))
              : (
                  <div style={{ color: C.textMuted, fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                    暂无AI决策记录
                  </div>
                )
            }
          </Card>
        </Col>
      </Row>

      {/* ── 底部区域：门店健康排名 + 实时预警 ── */}
      <Row gutter={16}>
        {/* 左：门店健康度排名 */}
        <Col span={12}>
          <Card
            title={
              <Space>
                <ShopOutlined style={{ color: C.primary }} />
                <span>门店健康度排名</span>
              </Space>
            }
            styles={{ body: { padding: 0 } }}
          >
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#F8F7F5' }}>
                  {['排名', '门店', '今日营收', '健康分', '最弱项'].map((h) => (
                    <th key={h} style={{
                      padding: '10px 14px', textAlign: 'left',
                      fontSize: 12, color: C.textSub, fontWeight: 600,
                      borderBottom: `1px solid ${C.border}`,
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.stores
                  .slice()
                  .sort((a, b) => (b.health_score ?? 0) - (a.health_score ?? 0))
                  .map((store, i) => {
                    const score = store.health_score ?? 75;
                    const isLow = score < 65;
                    return (
                      <tr
                        key={store.store_id}
                        style={{
                          borderBottom: `1px solid ${C.border}`,
                          background: i % 2 === 0 ? '#fff' : '#fafaf9',
                        }}
                      >
                        <td style={{ padding: '12px 14px' }}>
                          <span style={{
                            width: 24, height: 24, borderRadius: '50%',
                            background: i === 0 ? C.primary : '#e0e0e0',
                            color: i === 0 ? '#fff' : '#666',
                            display: 'inline-flex', alignItems: 'center',
                            justifyContent: 'center', fontSize: 12, fontWeight: 700,
                          }}>
                            {i + 1}
                          </span>
                        </td>
                        <td style={{ padding: '12px 14px', fontSize: 13, fontWeight: 500 }}>
                          {store.store_name}
                          <div style={{ fontSize: 11, color: C.textMuted }}>{store.today_orders}单</div>
                        </td>
                        <td style={{ padding: '12px 14px', fontSize: 13, fontWeight: 600, color: C.primary }}>
                          {fen2wan(store.today_revenue_fen)}万
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <Tag color={isLow ? 'red' : score >= 80 ? 'green' : 'orange'} style={{ fontSize: 12 }}>
                            {score}分
                          </Tag>
                        </td>
                        <td style={{ padding: '12px 14px', fontSize: 12, color: C.textSub }}>
                          {store.weakest_item ?? '--'}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </Card>
        </Col>

        {/* 右：今日实时预警 */}
        <Col span={12}>
          <Card
            title={
              <Space>
                <AlertOutlined style={{ color: C.danger }} />
                <span>今日实时预警</span>
              </Space>
            }
            extra={
              <Badge count={alerts.filter((a) => a.level === 'critical').length} size="small">
                <Tag color="error" style={{ fontSize: 11 }}>严重</Tag>
              </Badge>
            }
            styles={{ body: { padding: '0 16px' } }}
          >
            {alerts.length > 0
              ? alerts.map((alert) => (
                  <AlertItem key={alert.id} alert={alert} />
                ))
              : (
                  <div style={{ color: C.textMuted, fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                    今日暂无预警
                  </div>
                )
            }
            {s.generated_at && (
              <div style={{ textAlign: 'right', padding: '8px 0', fontSize: 11, color: C.textMuted }}>
                更新于 {new Date(s.generated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
