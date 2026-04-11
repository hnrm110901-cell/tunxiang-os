/**
 * AgentROIDashboardPage — Agent 效果量化看板
 *
 * 顶部 ROI 大字卡 + 每 Agent 效果卡片 + 月度对比 + 纯 CSS 柱状图
 *
 * 纯 Mock 数据 + Ant Design 5.x + 纯 CSS 可视化
 */
import { useMemo, useState } from 'react';
import { Card, Col, Row, Select, Space, Tag, Typography } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  FundOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';

const { Title, Text } = Typography;

// ─── Design Tokens ───
const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  navy: '#1E2A3A',
  bgPrimary: '#FFFFFF',
  bgSecondary: '#F8F7F5',
  bgTertiary: '#F0EDE6',
  textPrimary: '#2C2C2A',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
  border: '#E8E6E1',
};

// ─── Agent ROI 数据 ───
interface AgentROI {
  id: string;
  name: string;
  icon: string;
  color: string;
  metrics: {
    label: string;
    value: string;
    unit: string;
    trend: number; // 正数表示环比增长%
  }[];
  thisMonth: number;
  lastMonth: number;
  preLaunch: number;
  monthlyData: number[]; // 近6个月
}

const AGENT_ROI_DATA: AgentROI[] = [
  {
    id: 'discount_guard', name: '折扣守护', icon: '\u{1F6E1}\u{FE0F}', color: C.danger,
    metrics: [
      { label: '拦截金额', value: '12,340', unit: '\u00A5', trend: 18.5 },
      { label: '拦截次数', value: '47', unit: '次', trend: 12.3 },
      { label: '平均拦截金额', value: '262', unit: '\u00A5/次', trend: 5.6 },
    ],
    thisMonth: 12340, lastMonth: 10420, preLaunch: 0,
    monthlyData: [3200, 5800, 7600, 9100, 10420, 12340],
  },
  {
    id: 'inventory_alert', name: '库存预警', icon: '\u{1F4E6}', color: C.warning,
    metrics: [
      { label: '减少缺货', value: '23', unit: '次', trend: 34.2 },
      { label: '减少浪费', value: '8,560', unit: '\u00A5', trend: 22.1 },
      { label: '补货准确率', value: '91.2', unit: '%', trend: 3.8 },
    ],
    thisMonth: 8560, lastMonth: 7010, preLaunch: 0,
    monthlyData: [1800, 3200, 4900, 5800, 7010, 8560],
  },
  {
    id: 'serve_dispatch', name: '出餐调度', icon: '\u26A1', color: C.success,
    metrics: [
      { label: '节省人力', value: '186', unit: '小时', trend: 28.5 },
      { label: '人力成本节省', value: '5,580', unit: '\u00A5', trend: 28.5 },
      { label: '超时率下降', value: '34', unit: '%', trend: 15.2 },
    ],
    thisMonth: 5580, lastMonth: 4340, preLaunch: 0,
    monthlyData: [1200, 2100, 3000, 3800, 4340, 5580],
  },
  {
    id: 'member_insight', name: '会员洞察', icon: '\u{1F464}', color: C.info,
    metrics: [
      { label: '召回会员', value: '156', unit: '人', trend: 42.0 },
      { label: '增量营收', value: '18,720', unit: '\u00A5', trend: 35.6 },
      { label: '精准推荐率', value: '72.3', unit: '%', trend: 8.1 },
    ],
    thisMonth: 18720, lastMonth: 13800, preLaunch: 0,
    monthlyData: [4200, 6800, 9200, 11500, 13800, 18720],
  },
  {
    id: 'smart_menu', name: '智能排菜', icon: '\u{1F35C}', color: '#8B5CF6',
    metrics: [
      { label: '增量利润', value: '8,920', unit: '\u00A5', trend: 15.3 },
      { label: '菜品推荐采纳率', value: '68', unit: '%', trend: 5.2 },
      { label: '客单价提升', value: '4.8', unit: '\u00A5', trend: 2.1 },
    ],
    thisMonth: 8920, lastMonth: 7740, preLaunch: 0,
    monthlyData: [2400, 3800, 5200, 6500, 7740, 8920],
  },
  {
    id: 'finance_audit', name: '财务稽核', icon: '\u{1F4B0}', color: '#D97706',
    metrics: [
      { label: '发现异常', value: '14', unit: '笔', trend: -8.0 },
      { label: '挽回金额', value: '6,240', unit: '\u00A5', trend: 24.5 },
      { label: '审计覆盖率', value: '100', unit: '%', trend: 0 },
    ],
    thisMonth: 6240, lastMonth: 5010, preLaunch: 0,
    monthlyData: [1500, 2800, 3600, 4200, 5010, 6240],
  },
  {
    id: 'smart_service', name: '智能客服', icon: '\u{1F4AC}', color: '#06B6D4',
    metrics: [
      { label: '自动回复', value: '1,240', unit: '条', trend: 22.0 },
      { label: '节省人力', value: '3,720', unit: '\u00A5', trend: 18.5 },
      { label: '满意度', value: '4.6', unit: '/5', trend: 3.2 },
    ],
    thisMonth: 3720, lastMonth: 3140, preLaunch: 0,
    monthlyData: [800, 1400, 2000, 2600, 3140, 3720],
  },
  {
    id: 'store_inspect', name: '巡店质检', icon: '\u{1F50D}', color: '#7C3AED',
    metrics: [
      { label: '识别违规', value: '38', unit: '项', trend: -15.0 },
      { label: '整改率', value: '94.7', unit: '%', trend: 6.3 },
      { label: '食安评分提升', value: '8.2', unit: '分', trend: 4.5 },
    ],
    thisMonth: 2400, lastMonth: 2100, preLaunch: 0,
    monthlyData: [400, 800, 1200, 1600, 2100, 2400],
  },
  {
    id: 'private_ops', name: '私域运营', icon: '\u{1F4E3}', color: '#EC4899',
    metrics: [
      { label: '触达会员', value: '4,680', unit: '人', trend: 56.0 },
      { label: '转化营收', value: '9,360', unit: '\u00A5', trend: 42.3 },
      { label: '内容打开率', value: '32.5', unit: '%', trend: 8.7 },
    ],
    thisMonth: 9360, lastMonth: 6580, preLaunch: 0,
    monthlyData: [1200, 2400, 3800, 5200, 6580, 9360],
  },
];

const MONTH_LABELS = ['11月', '12月', '1月', '2月', '3月', '4月'];

// ─── 纯 CSS 趋势箭头 ───
function TrendBadge({ value }: { value: number }) {
  if (value === 0) return <Text style={{ fontSize: 12, color: C.textMuted }}>--</Text>;
  const isUp = value > 0;
  const color = isUp ? C.success : C.danger;
  const Icon = isUp ? ArrowUpOutlined : ArrowDownOutlined;
  return (
    <span style={{ fontSize: 12, color, fontWeight: 600 }}>
      <Icon style={{ fontSize: 10, marginRight: 2 }} />
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}

// ─── 纯 CSS 迷你趋势条 ───
function MiniTrendBar({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 40 }}>
      {data.map((v, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div
            style={{
              width: '100%',
              maxWidth: 28,
              height: Math.max(4, (v / max) * 36),
              background: i === data.length - 1 ? color : `${color}50`,
              borderRadius: '3px 3px 0 0',
              transition: 'height 0.3s ease',
            }}
          />
        </div>
      ))}
    </div>
  );
}

// ─── 纯 CSS 柱状图（月度对比大图） ───
function BarChart({ agents, period }: { agents: AgentROI[]; period: string }) {
  const dataMap: Record<string, { name: string; value: number; color: string }[]> = {
    thisMonth: agents.map(a => ({ name: a.name, value: a.thisMonth, color: a.color })),
    lastMonth: agents.map(a => ({ name: a.name, value: a.lastMonth, color: a.color })),
  };
  const data = dataMap[period] ?? dataMap.thisMonth;
  const maxVal = Math.max(...data.map(d => d.value), 1);

  return (
    <div style={{ padding: '16px 0' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 200, padding: '0 8px' }}>
        {data.map((d, i) => {
          const h = Math.max(8, (d.value / maxVal) * 180);
          return (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <Text style={{ fontSize: 11, color: C.textSub, fontWeight: 600 }}>
                {d.value >= 10000 ? `${(d.value / 10000).toFixed(1)}w` : d.value.toLocaleString()}
              </Text>
              <div
                style={{
                  width: '80%',
                  maxWidth: 48,
                  height: h,
                  background: `linear-gradient(180deg, ${d.color}, ${d.color}90)`,
                  borderRadius: '4px 4px 0 0',
                  transition: 'height 0.5s ease',
                  position: 'relative',
                }}
              />
              <Text style={{ fontSize: 11, color: C.textMuted, textAlign: 'center', lineHeight: '1.2' }}>
                {d.name}
              </Text>
            </div>
          );
        })}
      </div>
      {/* X轴 */}
      <div style={{ height: 1, background: C.border, margin: '4px 8px 0' }} />
    </div>
  );
}

// ─── 主组件 ───
export default function AgentROIDashboardPage() {
  const [chartPeriod, setChartPeriod] = useState('thisMonth');

  const totalROI = useMemo(
    () => AGENT_ROI_DATA.reduce((s, a) => s + a.thisMonth, 0),
    [],
  );
  const lastMonthTotal = useMemo(
    () => AGENT_ROI_DATA.reduce((s, a) => s + a.lastMonth, 0),
    [],
  );
  const totalGrowth = lastMonthTotal > 0 ? ((totalROI - lastMonthTotal) / lastMonthTotal * 100) : 0;

  return (
    <div style={{ padding: 24, background: C.bgSecondary, minHeight: '100vh' }}>
      {/* 标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0, color: C.textPrimary }}>
          <FundOutlined style={{ color: C.primary, marginRight: 8 }} />
          Agent 效果量化看板
        </Title>
        <Text style={{ color: C.textSub }}>量化展示每个 Agent 的 ROI 效果</Text>
      </div>

      {/* 顶部 ROI 大字卡 */}
      <Card
        style={{
          marginBottom: 24, borderRadius: 12,
          background: `linear-gradient(135deg, ${C.navy} 0%, ${C.navy}DD 100%)`,
          border: 'none',
        }}
        styles={{ body: { padding: 32 } }}
      >
        <Row align="middle" gutter={32}>
          <Col flex="auto">
            <Text style={{ color: '#ffffff90', fontSize: 14 }}>本月 AI 为您节省</Text>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 4 }}>
              <span style={{ color: '#ffffff60', fontSize: 24 }}>\u00A5</span>
              <span style={{
                fontSize: 56, fontWeight: 800, color: '#FFFFFF',
                letterSpacing: -2, lineHeight: 1,
              }}>
                {totalROI.toLocaleString()}
              </span>
            </div>
            <div style={{ marginTop: 8 }}>
              <TrendBadge value={totalGrowth} />
              <Text style={{ color: '#ffffff60', fontSize: 12, marginLeft: 8 }}>环比上月</Text>
            </div>
          </Col>
          <Col>
            <div style={{ display: 'flex', gap: 24 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ color: '#ffffff60', fontSize: 12 }}>活跃 Agent</div>
                <div style={{ color: '#fff', fontSize: 28, fontWeight: 700 }}>9</div>
              </div>
              <div style={{ width: 1, background: '#ffffff20' }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ color: '#ffffff60', fontSize: 12 }}>本月决策次数</div>
                <div style={{ color: '#fff', fontSize: 28, fontWeight: 700 }}>2,847</div>
              </div>
              <div style={{ width: 1, background: '#ffffff20' }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ color: '#ffffff60', fontSize: 12 }}>平均置信度</div>
                <div style={{ color: '#fff', fontSize: 28, fontWeight: 700 }}>87.3%</div>
              </div>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 每Agent效果卡片 */}
      <Title level={5} style={{ color: C.textPrimary, marginBottom: 16 }}>各 Agent 效果明细</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
        {AGENT_ROI_DATA.map(agent => (
          <Col xs={24} sm={12} lg={8} key={agent.id}>
            <Card
              size="small"
              style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}
              styles={{ body: { padding: 16 } }}
            >
              {/* 顶部色条 */}
              <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: agent.color }} />

              {/* Agent标题 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <Space>
                  <span style={{ fontSize: 22 }}>{agent.icon}</span>
                  <Text strong style={{ fontSize: 15 }}>{agent.name}</Text>
                </Space>
                <Tag style={{ color: agent.color, borderColor: `${agent.color}40`, background: `${agent.color}10` }}>
                  \u00A5{agent.thisMonth.toLocaleString()}
                </Tag>
              </div>

              {/* 指标列表 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                {agent.metrics.map((m, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '4px 8px', background: i % 2 === 0 ? C.bgSecondary : 'transparent',
                    borderRadius: 4,
                  }}>
                    <Text style={{ fontSize: 12, color: C.textSub }}>{m.label}</Text>
                    <Space size={8}>
                      <Text strong style={{ fontSize: 13 }}>
                        {m.unit === '\u00A5' || m.unit === '\u00A5/次' ? `${m.unit}${m.value}` : `${m.value}${m.unit}`}
                      </Text>
                      <TrendBadge value={m.trend} />
                    </Space>
                  </div>
                ))}
              </div>

              {/* 对比行 */}
              <div style={{
                display: 'flex', gap: 8, padding: '8px 0',
                borderTop: `1px solid ${C.border}`, marginBottom: 8,
              }}>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: C.textMuted }}>本月</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: agent.color }}>
                    \u00A5{agent.thisMonth.toLocaleString()}
                  </div>
                </div>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: C.textMuted }}>上月</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: C.textSub }}>
                    \u00A5{agent.lastMonth.toLocaleString()}
                  </div>
                </div>
                <div style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: C.textMuted }}>上线前</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: C.textMuted }}>
                    \u00A50
                  </div>
                </div>
              </div>

              {/* 迷你趋势 */}
              <MiniTrendBar data={agent.monthlyData} color={agent.color} />
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                <Text style={{ fontSize: 10, color: C.textMuted }}>11月</Text>
                <Text style={{ fontSize: 10, color: C.textMuted }}>4月</Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 月度效果柱状图 */}
      <Card
        title={
          <Space>
            <ThunderboltOutlined style={{ color: C.primary }} />
            <span>各 Agent 月度效果对比</span>
          </Space>
        }
        extra={
          <Select
            value={chartPeriod}
            onChange={setChartPeriod}
            size="small"
            style={{ width: 120 }}
            options={[
              { value: 'thisMonth', label: '本月' },
              { value: 'lastMonth', label: '上月' },
            ]}
          />
        }
        style={{ borderRadius: 8 }}
      >
        <BarChart agents={AGENT_ROI_DATA} period={chartPeriod} />

        {/* 图例 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 12, justifyContent: 'center' }}>
          {AGENT_ROI_DATA.map(a => (
            <Space key={a.id} size={4}>
              <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: a.color }} />
              <Text style={{ fontSize: 12, color: C.textSub }}>{a.name}</Text>
            </Space>
          ))}
        </div>
      </Card>

      {/* 底部总结卡片 */}
      <Card style={{ marginTop: 24, borderRadius: 8, background: `${C.success}08`, border: `1px solid ${C.success}20` }}>
        <Row gutter={24} align="middle">
          <Col flex="auto">
            <Title level={5} style={{ margin: 0, color: C.success }}>
              <RobotOutlined style={{ marginRight: 8 }} />
              AI Agent 月度总结
            </Title>
            <Text style={{ color: C.textSub, fontSize: 13 }}>
              本月 9 个 Agent 累计为您节省 \u00A5{totalROI.toLocaleString()}，环比上月增长 {totalGrowth.toFixed(1)}%。
              其中会员洞察 Agent 贡献最大（\u00A518,720），折扣守护 Agent 成功拦截 47 笔异常折扣。
              建议将库存预警 Agent 升级至 L3 全自治模式以进一步提升效率。
            </Text>
          </Col>
          <Col>
            <div style={{
              width: 80, height: 80, borderRadius: '50%',
              background: `linear-gradient(135deg, ${C.success}, ${C.success}90)`,
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            }}>
              <span style={{ color: '#fff', fontSize: 18, fontWeight: 800 }}>A+</span>
              <span style={{ color: '#ffffffCC', fontSize: 10 }}>整体评级</span>
            </div>
          </Col>
        </Row>
      </Card>
    </div>
  );
}
