/**
 * BriefingCenterPage — 经营简报中心
 * 总部管理员查看 AI 生成的经营报告（日报/周报/门店对标/异常简报）
 */
import { useState, useEffect, useCallback } from 'react';
import {
  ConfigProvider, Tabs, List, Card, Row, Col, Statistic, Tag, Input, Button,
  Space, Modal, Form, TimePicker, Checkbox, Spin, Empty, Badge,
  message, Typography, Progress,
} from 'antd';
import {
  RobotOutlined, SearchOutlined, BellOutlined, ArrowUpOutlined,
  ArrowDownOutlined, ReloadOutlined, WarningOutlined, TrophyOutlined,
  FileTextOutlined, BarChartOutlined, AlertOutlined,
} from '@ant-design/icons';
import type {
  Briefing, SubscribePayload,
} from '../../../api/briefingApi';
import {
  fetchBriefings, fetchBriefingDetail, subscribeBriefing,
} from '../../../api/briefingApi';

const { Text, Paragraph, Title } = Typography;

// ─── 颜色常量 ───
const COLOR = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  error: '#A32D2D',
  info: '#185FA5',
  bg: '#F8F7F5',
  textSecondary: '#5F5E5A',
  textTertiary: '#B4B2A9',
};

// ─── Mock 数据 ───
const MOCK_DAILY: Briefing[] = [
  {
    id: 'd-20260409',
    type: 'daily',
    title: '2026年4月9日 经营日报',
    date: '2026-04-09',
    summary: '整体经营状况良好，总营收 ¥128,640，同比 +8.3%。南山旗舰店表现突出，福田中心店午市翻台率偏低需关注。',
    content: `## 经营概况\n\n今日全品牌整体经营稳中有升，总营收达到 **¥128,640**，环比昨日增长 **+3.2%**，同比上月同日增长 **+8.3%**。\n\n## 业绩亮点\n\n- 南山旗舰店营收 ¥38,420，超额完成日目标 115%\n- 会员消费占比达 42%，较上周提升 2.1pct\n- 蒜蓉蒸鲍鱼连续3日售罄，带动海鲜品类整体毛利率提升\n\n## 需关注事项\n\n- 福田中心店午市翻台率仅 1.6 次，低于目标 2.2 次\n- 龙华店晚市上座率 68%，较上周下滑 5pct\n- 3种蔬菜食材临近保质期，建议加速消耗\n\n## AI 建议\n\n1. 建议福田中心店调整午市排班，增加1名服务员\n2. 龙华店可考虑推出晚市限时优惠套餐\n3. 临期食材建议纳入明日员工餐或特价菜`,
    kpi: {
      revenue_fen: 12864000,
      revenue_change: 8.3,
      gross_margin: 0.623,
      gross_margin_change: 1.2,
      customer_count: 1842,
      customer_change: 5.6,
      table_turnover: 2.4,
      turnover_change: -2.1,
    },
    anomaly_count: 3,
    rectification_rate: 0.78,
    top_stores: [
      { name: '南山旗舰店', score: 95 },
      { name: '宝安万达店', score: 91 },
      { name: '罗湖东门店', score: 88 },
      { name: '福田CBD店', score: 85 },
      { name: '龙岗中心店', score: 83 },
    ],
    bottom_stores: [
      { name: '光明新区店', score: 62 },
      { name: '坪山店', score: 65 },
      { name: '盐田店', score: 68 },
      { name: '龙华店', score: 71 },
      { name: '福田中心店', score: 73 },
    ],
    generated_at: '2026-04-09T09:00:00Z',
    is_read: true,
  },
  {
    id: 'd-20260408',
    type: 'daily',
    title: '2026年4月8日 经营日报',
    date: '2026-04-08',
    summary: '总营收 ¥124,580，环比 -1.2%。工作日客流正常，会员复购率保持稳定。采购成本略有上升需关注。',
    content: `## 经营概况\n\n工作日经营节奏平稳，总营收 **¥124,580**。\n\n## 需关注\n\n- 海鲜采购价格上浮约 5%\n- 2家门店空调设备报修中`,
    kpi: {
      revenue_fen: 12458000,
      revenue_change: -1.2,
      gross_margin: 0.608,
      gross_margin_change: -0.8,
      customer_count: 1756,
      customer_change: -2.3,
      table_turnover: 2.3,
      turnover_change: 0.5,
    },
    anomaly_count: 2,
    rectification_rate: 0.82,
    top_stores: [
      { name: '宝安万达店', score: 92 },
      { name: '南山旗舰店', score: 90 },
      { name: '罗湖东门店', score: 87 },
      { name: '福田CBD店', score: 84 },
      { name: '龙岗中心店', score: 81 },
    ],
    bottom_stores: [
      { name: '坪山店', score: 60 },
      { name: '光明新区店', score: 64 },
      { name: '盐田店', score: 67 },
      { name: '龙华店', score: 70 },
      { name: '福田中心店', score: 72 },
    ],
    generated_at: '2026-04-08T09:00:00Z',
    is_read: true,
  },
  {
    id: 'd-20260407',
    type: 'daily',
    title: '2026年4月7日 经营日报',
    date: '2026-04-07',
    summary: '周日营收 ¥156,320，环比周六 -5.8%。整体表现良好，多项KPI超过月均水平。',
    content: `## 经营概况\n\n周日客流下午段集中，总营收 **¥156,320**。\n\n## 亮点\n\n- 下午茶时段营收创本月新高\n- 3家门店毛利率超过65%`,
    kpi: {
      revenue_fen: 15632000,
      revenue_change: -5.8,
      gross_margin: 0.641,
      gross_margin_change: 2.3,
      customer_count: 2130,
      customer_change: -4.2,
      table_turnover: 2.8,
      turnover_change: -3.1,
    },
    anomaly_count: 1,
    rectification_rate: 0.91,
    top_stores: [
      { name: '南山旗舰店', score: 96 },
      { name: '罗湖东门店', score: 93 },
      { name: '宝安万达店', score: 89 },
      { name: '龙岗中心店', score: 86 },
      { name: '福田CBD店', score: 84 },
    ],
    bottom_stores: [
      { name: '坪山店', score: 63 },
      { name: '光明新区店', score: 66 },
      { name: '盐田店', score: 69 },
      { name: '龙华店', score: 72 },
      { name: '福田中心店', score: 74 },
    ],
    generated_at: '2026-04-07T09:00:00Z',
    is_read: false,
  },
];

const MOCK_WEEKLY: Briefing[] = [
  {
    id: 'w-202614',
    type: 'weekly',
    title: '2026年第14周 经营周报（03/31 - 04/06）',
    date: '2026-04-06',
    summary: '本周总营收 ¥892,450，环比上周 +4.6%。客流量持续增长，会员占比提升至39%。建议重点关注食材成本控制。',
    content: `## 本周总结\n\n本周整体经营表现优于上周，总营收 **¥892,450**，目标达成率 **103%**。\n\n## 关键趋势\n\n- 连续3周营收环比增长，增速趋缓\n- 会员新增 286 人，累计活跃会员 12,340 人\n- 海鲜品类毛利率从 58% 提升至 62%\n\n## 门店对比\n\n南山旗舰店以 ¥268,000 周营收领跑，较第二名宝安万达店高出 21%。\n\n## 下周重点\n\n1. 清明假期预计客流增长 15-20%\n2. 提前备货海鲜及时令蔬菜\n3. 关注龙华店持续下滑趋势`,
    kpi: {
      revenue_fen: 89245000,
      revenue_change: 4.6,
      gross_margin: 0.618,
      gross_margin_change: 0.9,
      customer_count: 12680,
      customer_change: 6.2,
      table_turnover: 2.5,
      turnover_change: 1.8,
    },
    anomaly_count: 8,
    rectification_rate: 0.85,
    top_stores: [
      { name: '南山旗舰店', score: 94 },
      { name: '宝安万达店', score: 90 },
      { name: '罗湖东门店', score: 87 },
      { name: '福田CBD店', score: 84 },
      { name: '龙岗中心店', score: 82 },
    ],
    bottom_stores: [
      { name: '坪山店', score: 61 },
      { name: '光明新区店', score: 64 },
      { name: '盐田店', score: 67 },
      { name: '龙华店', score: 70 },
      { name: '福田中心店', score: 72 },
    ],
    generated_at: '2026-04-07T08:00:00Z',
    is_read: true,
  },
];

const MOCK_BENCHMARK: Briefing[] = [
  {
    id: 'b-20260409-ns',
    type: 'benchmark',
    title: '南山旗舰店 对标简报',
    date: '2026-04-09',
    summary: '南山旗舰店综合评分 95 分，在同类型大店中排名第1。营收、毛利率、翻台率均高于同类平均水平。',
    content: `## 对标分析\n\n### 与同类型门店对比（大店Pro业态）\n\n| 指标 | 南山旗舰店 | 同类均值 | 差异 |\n|------|-----------|---------|------|\n| 日均营收 | ¥36,800 | ¥28,500 | +29.1% |\n| 毛利率 | 63.2% | 58.6% | +4.6pct |\n| 翻台率 | 2.6次 | 2.2次 | +18.2% |\n| 客单价 | ¥186 | ¥162 | +14.8% |\n\n### 优势领域\n- 海鲜品类经营能力突出\n- 会员转化率领先\n\n### 改进空间\n- 午市上座率可进一步提升\n- 外卖渠道占比偏低`,
    kpi: {
      revenue_fen: 3680000,
      revenue_change: 12.5,
      gross_margin: 0.632,
      gross_margin_change: 2.1,
      customer_count: 198,
      customer_change: 8.3,
      table_turnover: 2.6,
      turnover_change: 3.2,
    },
    anomaly_count: 0,
    rectification_rate: 0.95,
    top_stores: [],
    bottom_stores: [],
    generated_at: '2026-04-09T10:00:00Z',
    is_read: false,
  },
];

const MOCK_ANOMALY: Briefing[] = [
  {
    id: 'a-20260409-01',
    type: 'anomaly',
    title: '异常简报：福田中心店折扣率异常',
    date: '2026-04-09',
    summary: '福田中心店今日折扣率达 28.5%，超过预警阈值 20%。折扣守护Agent已介入，建议立即核查。',
    content: `## 异常详情\n\n**异常类型：** 折扣率超标\n**触发门店：** 福田中心店\n**当前折扣率：** 28.5%（阈值 20%）\n**影响金额：** 约 ¥3,200\n\n## 异常分析\n\n经 AI 分析，异常折扣主要集中在：\n- 午市套餐叠加使用了会员折扣 + 满减优惠\n- 3笔订单存在手动改价记录\n\n## Agent 行动\n\n1. 折扣守护Agent已暂停该店"满200减30"活动\n2. 已通知门店店长进行核查\n3. 建议调整优惠叠加规则\n\n## 整改要求\n\n- 48小时内完成折扣规则复核\n- 提交手动改价订单的审批记录`,
    kpi: {
      revenue_fen: 2480000,
      revenue_change: -6.2,
      gross_margin: 0.485,
      gross_margin_change: -12.3,
      customer_count: 156,
      customer_change: -3.8,
      table_turnover: 1.6,
      turnover_change: -8.5,
    },
    anomaly_count: 5,
    rectification_rate: 0.45,
    top_stores: [],
    bottom_stores: [],
    generated_at: '2026-04-09T14:30:00Z',
    is_read: false,
  },
  {
    id: 'a-20260408-01',
    type: 'anomaly',
    title: '异常简报：龙华店食材损耗超标',
    date: '2026-04-08',
    summary: '龙华店本周食材损耗率 6.8%，超过预警线 5%。主要集中在蔬菜类和海鲜类。',
    content: `## 异常详情\n\n**异常类型：** 食材损耗超标\n**触发门店：** 龙华店\n**当前损耗率：** 6.8%（预警线 5%）\n\n## 分析\n\n- 蔬菜类损耗占比 45%，主因为采购量过大\n- 海鲜类损耗占比 30%，主因为保鲜设备故障\n\n## 建议\n\n1. 调整蔬菜采购周期为每日采购\n2. 尽快维修海鲜暂养池温控设备`,
    kpi: {
      revenue_fen: 1890000,
      revenue_change: -3.5,
      gross_margin: 0.528,
      gross_margin_change: -5.6,
      customer_count: 132,
      customer_change: -1.2,
      table_turnover: 1.9,
      turnover_change: -4.3,
    },
    anomaly_count: 3,
    rectification_rate: 0.62,
    top_stores: [],
    bottom_stores: [],
    generated_at: '2026-04-08T16:00:00Z',
    is_read: true,
  },
];

const MOCK_MAP: Record<string, Briefing[]> = {
  daily: MOCK_DAILY,
  weekly: MOCK_WEEKLY,
  benchmark: MOCK_BENCHMARK,
  anomaly: MOCK_ANOMALY,
};

// ─── 工具函数 ───

/** 格式化分为元 */
const fmtYuan = (fen: number): string => {
  const yuan = fen / 100;
  if (yuan >= 10000) return `${(yuan / 10000).toFixed(2)}万`;
  return yuan.toLocaleString('zh-CN', { minimumFractionDigits: 0 });
};

/** 变化率颜色 */
const changeColor = (v: number): string => {
  if (v > 0) return COLOR.success;
  if (v < 0) return COLOR.error;
  return COLOR.textSecondary;
};

/** 转义HTML特殊字符，防止XSS */
const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** 渲染 markdown 风格文本为简单 HTML（先转义再替换，防止XSS） */
const renderMarkdown = (md: string): string => {
  const safe = escapeHtml(md);
  return safe
    .replace(/^### (.+)$/gm, '<h4 style="margin:16px 0 8px;color:#2C2C2A">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 style="margin:20px 0 10px;color:#2C2C2A;border-bottom:1px solid #E8E6E1;padding-bottom:6px">$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^\- (.+)$/gm, '<div style="padding:2px 0 2px 16px">&#8226; $1</div>')
    .replace(/^\d+\. (.+)$/gm, (_match, p1, offset, str) => {
      const lines = str.substring(0, offset).split('\n');
      const idx = lines.filter((l: string) => /^\d+\./.test(l)).length + 1;
      return `<div style="padding:2px 0 2px 16px">${idx}. ${p1}</div>`;
    })
    .replace(/\|(.+)\|/g, (match) => `<div style="font-family:monospace;font-size:13px;padding:2px 0">${match}</div>`)
    .replace(/\n\n/g, '<br/>')
    .replace(/\n/g, '');
};

// ─── KPI 卡片组件 ───

interface KPICardsProps {
  kpi: Briefing['kpi'];
}

const KPICards: React.FC<KPICardsProps> = ({ kpi }) => {
  const items = [
    {
      title: '营收',
      value: `¥${fmtYuan(kpi.revenue_fen)}`,
      change: kpi.revenue_change,
      color: COLOR.primary,
    },
    {
      title: '毛利率',
      value: `${(kpi.gross_margin * 100).toFixed(1)}%`,
      change: kpi.gross_margin_change,
      color: kpi.gross_margin < 0.5 ? COLOR.error : COLOR.success,
    },
    {
      title: '客流量',
      value: kpi.customer_count.toLocaleString(),
      change: kpi.customer_change,
      color: COLOR.info,
    },
    {
      title: '翻台率',
      value: `${kpi.table_turnover}次`,
      change: kpi.turnover_change,
      color: COLOR.warning,
    },
  ];

  return (
    <Row gutter={12} style={{ marginBottom: 16 }}>
      {items.map((item) => (
        <Col span={6} key={item.title}>
          <Card size="small" style={{ borderTop: `3px solid ${item.color}` }}>
            <Statistic
              title={item.title}
              value={item.value}
              valueStyle={{ color: item.color, fontWeight: 700, fontSize: 20 }}
            />
            <div style={{ marginTop: 4 }}>
              <Text style={{ color: changeColor(item.change), fontSize: 13 }}>
                {item.change > 0 ? <ArrowUpOutlined /> : item.change < 0 ? <ArrowDownOutlined /> : null}
                {' '}环比 {item.change > 0 ? '+' : ''}{item.change}%
              </Text>
            </div>
          </Card>
        </Col>
      ))}
    </Row>
  );
};

// ─── 门店排名组件 ───

interface StoreRankProps {
  title: string;
  stores: Briefing['top_stores'];
  type: 'top' | 'bottom';
}

const StoreRank: React.FC<StoreRankProps> = ({ title, stores, type }) => {
  if (!stores || stores.length === 0) return null;
  return (
    <Card
      size="small"
      title={
        <Space>
          <TrophyOutlined style={{ color: type === 'top' ? COLOR.success : COLOR.warning }} />
          <span>{title}</span>
        </Space>
      }
      style={{ marginBottom: 12 }}
    >
      {stores.map((s, i) => (
        <div
          key={s.name}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '6px 0',
            borderBottom: i < stores.length - 1 ? '1px solid #f0f0f0' : 'none',
          }}
        >
          <Space>
            <Tag
              color={type === 'top'
                ? (i < 3 ? COLOR.success : undefined)
                : (i < 3 ? COLOR.error : COLOR.warning)}
              style={{ minWidth: 24, textAlign: 'center' }}
            >
              {i + 1}
            </Tag>
            <Text>{s.name}</Text>
          </Space>
          <Text strong style={{ color: type === 'top' ? COLOR.success : COLOR.error }}>
            {s.score}分
          </Text>
        </div>
      ))}
    </Card>
  );
};

// ─── 简报详情组件 ───

interface BriefingDetailProps {
  briefing: Briefing;
}

const BriefingDetail: React.FC<BriefingDetailProps> = ({ briefing }) => {
  return (
    <div style={{ padding: '0 8px' }}>
      {/* KPI 卡片 */}
      <KPICards kpi={briefing.kpi} />

      {/* 异常 & 整改 */}
      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card size="small">
            <Statistic
              title="异常事件数"
              value={briefing.anomaly_count}
              suffix="件"
              valueStyle={{
                color: briefing.anomaly_count > 3 ? COLOR.error : COLOR.warning,
                fontWeight: 700,
              }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small">
            <div style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 13 }}>整改完成率</Text>
            </div>
            <Progress
              percent={Math.round(briefing.rectification_rate * 100)}
              strokeColor={briefing.rectification_rate >= 0.8 ? COLOR.success : COLOR.warning}
              format={(p) => `${p}%`}
            />
          </Card>
        </Col>
      </Row>

      {/* AI 叙事文本 */}
      <Card
        size="small"
        title={
          <Space>
            <RobotOutlined style={{ color: COLOR.info }} />
            <span>AI 分析报告</span>
            <Tag color={COLOR.info}>tx-brain 生成</Tag>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <div
          style={{ lineHeight: 1.8, fontSize: 14, color: '#2C2C2A' }}
          dangerouslySetInnerHTML={{ __html: renderMarkdown(briefing.content) }}
        />
      </Card>

      {/* 门店排名 */}
      {(briefing.top_stores.length > 0 || briefing.bottom_stores.length > 0) && (
        <Row gutter={12}>
          <Col span={12}>
            <StoreRank title="Top 5 门店" stores={briefing.top_stores} type="top" />
          </Col>
          <Col span={12}>
            <StoreRank title="Bottom 5 门店" stores={briefing.bottom_stores} type="bottom" />
          </Col>
        </Row>
      )}
    </div>
  );
};

// ─── Tab 图标 ───
const TAB_ICONS: Record<string, React.ReactNode> = {
  daily: <FileTextOutlined />,
  weekly: <BarChartOutlined />,
  benchmark: <TrophyOutlined />,
  anomaly: <AlertOutlined />,
};

// ─── 主组件 ───

export const BriefingCenterPage = () => {
  const [activeTab, setActiveTab] = useState<Briefing['type']>('daily');
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<Record<string, Briefing>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);

  // 订阅弹窗
  const [subscribeOpen, setSubscribeOpen] = useState(false);
  const [subscribeLoading, setSubscribeLoading] = useState(false);
  const [subscribeForm] = Form.useForm();

  const pageSize = 10;

  // ─── 加载列表 ───
  const loadList = useCallback(async (type: Briefing['type'], pg: number, kw: string) => {
    setLoading(true);
    try {
      const result = await fetchBriefings(type, pg, pageSize, kw || undefined);
      setBriefings(result.items);
      setTotal(result.total);
    } catch {
      // 后端未就绪，使用 mock 数据
      const mockData = MOCK_MAP[type] || [];
      const filtered = kw
        ? mockData.filter((b) => b.title.includes(kw) || b.summary.includes(kw))
        : mockData;
      setBriefings(filtered);
      setTotal(filtered.length);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
    setExpandedId(null);
    loadList(activeTab, 1, keyword);
  }, [activeTab, keyword, loadList]);

  // ─── 展开详情 ───
  const handleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);

    if (!detailData[id]) {
      setDetailLoading(id);
      try {
        const detail = await fetchBriefingDetail(id);
        setDetailData((prev) => ({ ...prev, [id]: detail }));
      } catch {
        // 使用列表中的数据
        const found = briefings.find((b) => b.id === id);
        if (found) {
          setDetailData((prev) => ({ ...prev, [id]: found }));
        }
      } finally {
        setDetailLoading(null);
      }
    }
  };

  // ─── 搜索 ───
  const handleSearch = () => {
    setKeyword(searchInput);
  };

  // ─── 分页 ───
  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    setExpandedId(null);
    loadList(activeTab, newPage, keyword);
  };

  // ─── 订阅 ───
  const handleSubscribe = async () => {
    try {
      const values = await subscribeForm.validateFields();
      setSubscribeLoading(true);
      const payload: SubscribePayload = {
        channels: values.channels,
        push_time: values.push_time?.format('HH:mm') || '09:00',
        types: values.types,
      };
      try {
        await subscribeBriefing(payload);
        message.success('订阅设置已保存');
      } catch {
        // mock 成功
        message.success('订阅设置已保存（模拟）');
      }
      setSubscribeOpen(false);
    } catch {
      // 表单校验不通过，不做处理
    } finally {
      setSubscribeLoading(false);
    }
  };

  // ─── 类型标签样式 ───
  const typeTag = (type: Briefing['type']) => {
    const map: Record<string, { color: string; label: string }> = {
      daily: { color: COLOR.primary, label: '日报' },
      weekly: { color: COLOR.info, label: '周报' },
      benchmark: { color: COLOR.success, label: '对标' },
      anomaly: { color: COLOR.error, label: '异常' },
    };
    const cfg = map[type] || { color: COLOR.primary, label: type };
    return <Tag color={cfg.color}>{cfg.label}</Tag>;
  };

  // ─── 渲染列表项 ───
  const renderBriefingItem = (item: Briefing) => {
    const isExpanded = expandedId === item.id;
    const detail = detailData[item.id] || item;
    const isLoadingDetail = detailLoading === item.id;

    return (
      <List.Item
        key={item.id}
        style={{
          display: 'block',
          padding: 0,
          marginBottom: 12,
        }}
      >
        <Card
          hoverable
          size="small"
          style={{
            borderLeft: item.is_read ? '3px solid transparent' : `3px solid ${COLOR.primary}`,
            background: isExpanded ? '#FAFAF8' : '#fff',
          }}
          bodyStyle={{ padding: '12px 16px' }}
          onClick={() => handleExpand(item.id)}
        >
          {/* 列表摘要行 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <Space style={{ marginBottom: 6 }}>
                {!item.is_read && <Badge status="processing" />}
                {typeTag(item.type)}
                <Text strong style={{ fontSize: 15 }}>{item.title}</Text>
              </Space>
              <Paragraph
                type="secondary"
                ellipsis={{ rows: 2 }}
                style={{ marginBottom: 6, fontSize: 13 }}
              >
                {item.summary}
              </Paragraph>
              <Space size={16}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {item.date}
                </Text>
                <Space size={8}>
                  <Text style={{ fontSize: 12, color: changeColor(item.kpi.revenue_change) }}>
                    营收 {item.kpi.revenue_change > 0 ? '+' : ''}{item.kpi.revenue_change}%
                  </Text>
                  <Text style={{ fontSize: 12, color: changeColor(item.kpi.gross_margin_change) }}>
                    毛利 {item.kpi.gross_margin_change > 0 ? '+' : ''}{item.kpi.gross_margin_change}pct
                  </Text>
                  <Text style={{ fontSize: 12, color: changeColor(item.kpi.customer_change) }}>
                    客流 {item.kpi.customer_change > 0 ? '+' : ''}{item.kpi.customer_change}%
                  </Text>
                </Space>
                <Tag
                  color={COLOR.info}
                  style={{ fontSize: 11 }}
                  icon={<RobotOutlined />}
                >
                  AI 生成
                </Tag>
              </Space>
            </div>
            {item.anomaly_count > 0 && (
              <Tag
                color={item.anomaly_count > 3 ? COLOR.error : COLOR.warning}
                style={{ marginLeft: 12 }}
              >
                <WarningOutlined /> {item.anomaly_count}项异常
              </Tag>
            )}
          </div>

          {/* 展开的详情 */}
          {isExpanded && (
            <div
              style={{ marginTop: 16, borderTop: '1px solid #E8E6E1', paddingTop: 16 }}
              onClick={(e) => e.stopPropagation()}
            >
              {isLoadingDetail ? (
                <div style={{ textAlign: 'center', padding: 24 }}>
                  <Spin tip="加载详情..." />
                </div>
              ) : (
                <BriefingDetail briefing={detail} />
              )}
            </div>
          )}
        </Card>
      </List.Item>
    );
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: COLOR.bg, minHeight: '100vh' }}>
        {/* 页面标题 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <Title level={4} style={{ margin: 0 }}>
              <RobotOutlined style={{ color: COLOR.primary, marginRight: 8 }} />
              经营简报中心
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              AI 自动生成的经营分析报告，覆盖日报、周报、门店对标与异常预警
            </Text>
          </div>
          <Space>
            <Button
              icon={<BellOutlined />}
              onClick={() => setSubscribeOpen(true)}
            >
              订阅设置
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => loadList(activeTab, page, keyword)}
            >
              刷新
            </Button>
          </Space>
        </div>

        {/* 搜索栏 */}
        <div style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索历史简报（按标题、摘要关键词）"
            allowClear
            enterButton={<><SearchOutlined /> 搜索</>}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onSearch={handleSearch}
            style={{ maxWidth: 480 }}
          />
        </div>

        {/* Tab 切换 */}
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as Briefing['type'])}
          items={[
            { key: 'daily', label: <Space>{TAB_ICONS.daily} 日报</Space> },
            { key: 'weekly', label: <Space>{TAB_ICONS.weekly} 周报</Space> },
            { key: 'benchmark', label: <Space>{TAB_ICONS.benchmark} 门店对标简报</Space> },
            { key: 'anomaly', label: <Space>{TAB_ICONS.anomaly} 异常简报</Space> },
          ]}
        />

        {/* 列表 */}
        <Spin spinning={loading}>
          {briefings.length === 0 && !loading ? (
            <Empty
              description={keyword ? '未找到匹配的简报' : '暂无简报数据'}
              style={{ padding: 48 }}
            />
          ) : (
            <List
              dataSource={briefings}
              renderItem={renderBriefingItem}
              pagination={
                total > pageSize
                  ? {
                      current: page,
                      pageSize,
                      total,
                      onChange: handlePageChange,
                      showTotal: (t) => `共 ${t} 条简报`,
                      style: { marginTop: 16 },
                    }
                  : false
              }
            />
          )}
        </Spin>

        {/* 订阅设置弹窗 */}
        <Modal
          title={
            <Space>
              <BellOutlined style={{ color: COLOR.primary }} />
              <span>简报订阅设置</span>
            </Space>
          }
          open={subscribeOpen}
          onCancel={() => setSubscribeOpen(false)}
          onOk={handleSubscribe}
          confirmLoading={subscribeLoading}
          okText="保存"
          cancelText="取消"
          width={480}
        >
          <Form
            form={subscribeForm}
            layout="vertical"
            initialValues={{
              channels: ['wecom'],
              types: ['daily', 'anomaly'],
            }}
          >
            <Form.Item
              name="channels"
              label="推送渠道"
              rules={[{ required: true, message: '请选择至少一个推送渠道' }]}
            >
              <Checkbox.Group>
                <Checkbox value="wecom">企业微信</Checkbox>
                <Checkbox value="email">邮件</Checkbox>
              </Checkbox.Group>
            </Form.Item>

            <Form.Item
              name="types"
              label="订阅类型"
              rules={[{ required: true, message: '请选择至少一个简报类型' }]}
            >
              <Checkbox.Group>
                <Checkbox value="daily">日报</Checkbox>
                <Checkbox value="weekly">周报</Checkbox>
                <Checkbox value="benchmark">门店对标简报</Checkbox>
                <Checkbox value="anomaly">异常简报</Checkbox>
              </Checkbox.Group>
            </Form.Item>

            <Form.Item
              name="push_time"
              label="推送时间"
              extra="日报将在指定时间推送，异常简报实时推送不受此设置影响"
            >
              <TimePicker
                format="HH:mm"
                placeholder="选择推送时间"
                style={{ width: '100%' }}
                minuteStep={15}
              />
            </Form.Item>
          </Form>
        </Modal>
      </div>
    </ConfigProvider>
  );
};
