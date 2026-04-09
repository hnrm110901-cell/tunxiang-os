/**
 * RevenueOptimizePage — 收益优化看板
 * Sprint 3: tx-analytics 收益优化师
 */

/**
 * RevenueOptimizePage — 收益优化看板
 *
 * API 接入目标（Phase 2）：
 * - 菜品定价优化: GET /api/v1/analytics/dish-analysis (tx-analytics)
 * - 翻台率数据: GET /api/v1/store-analysis/{store_id}/turnover (tx-analytics)
 * - 时段收益: GET /api/v1/analytics/realtime (tx-analytics)
 *
 * 当前 Phase 1: 使用 mock 数据，等待 tx-analytics 数据接口稳定后切换。
 */
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, Tabs, Button, Space,
} from 'antd';
import type { TabsProps } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

// ---- 类型 ----
interface PricingRow {
  key: number;
  dish: string;
  currentPrice: number;
  suggestedPrice: number;
  margin: string;
  reason: string;
}

interface TurnoverRow {
  key: number;
  store: string;
  area: string;
  currentRate: number;
  targetRate: number;
  suggestion: string;
}

interface TimeSlotRow {
  key: number;
  slot: string;
  gmv: number;
  share: string;
  potential: string;
  suggestion: string;
}

// ---- Mock 数据 ----
const PRICING_DATA: PricingRow[] = [
  { key: 1, dish: '蒜蓉蒸鲍鱼',   currentPrice: 128, suggestedPrice: 138, margin: '62%', reason: '竞品均价141，有提价空间' },
  { key: 2, dish: '清蒸多宝鱼',   currentPrice: 188, suggestedPrice: 178, margin: '45%', reason: '点单转化率低，降价提量' },
  { key: 3, dish: '椒盐濑尿虾',   currentPrice: 96,  suggestedPrice: 106, margin: '55%', reason: '周末供不应求，弹性定价' },
  { key: 4, dish: '海鲜炒饭',     currentPrice: 58,  suggestedPrice: 52,  margin: '38%', reason: '竞品价52，高于市场' },
  { key: 5, dish: '龙虾粥',       currentPrice: 128, suggestedPrice: 128, margin: '61%', reason: '价格合理，维持现价' },
];

const TURNOVER_DATA: TurnoverRow[] = [
  { key: 1, store: '南山旗舰', area: '大厅',   currentRate: 2.1, targetRate: 2.8, suggestion: '缩短等位提醒时间至8分钟' },
  { key: 2, store: '福田中心', area: '包厢',   currentRate: 1.4, targetRate: 1.8, suggestion: '增加包厢预定激励' },
  { key: 3, store: '罗湖商圈', area: '散座',   currentRate: 1.9, targetRate: 2.2, suggestion: '午市推行限时套餐' },
];

const TIME_SLOT_DATA: TimeSlotRow[] = [
  { key: 1, slot: '早市 06:00-10:00', gmv: 3200,  share: '5%',  potential: '+¥800/日',  suggestion: '推出早茶限时套餐，配合会员积分' },
  { key: 2, slot: '午市 11:00-14:00', gmv: 22400, share: '35%', potential: '+¥2,200/日', suggestion: '增设快速结账通道，提升翻台率' },
  { key: 3, slot: '下午茶 14:00-17:00', gmv: 6800, share: '11%', potential: '+¥1,400/日', suggestion: '推出下午茶套餐，利用空档期产能' },
  { key: 4, slot: '晚市 17:00-22:00', gmv: 31490, share: '49%', potential: '+¥3,100/日', suggestion: '动态排班补充晚市高峰人手' },
];

// ---- 列定义 ----
const PRICING_COLS: ProColumns<PricingRow>[] = [
  { title: '菜品名', dataIndex: 'dish', width: 120 },
  { title: '当前价', dataIndex: 'currentPrice', width: 90, render: (v) => `¥${v}` },
  { title: '建议价', dataIndex: 'suggestedPrice', width: 90,
    render: (_, r) => {
      const diff = r.suggestedPrice - r.currentPrice;
      const color = diff > 0 ? '#0F6E56' : diff < 0 ? '#A32D2D' : '#888';
      return <span style={{ color, fontWeight: 600 }}>¥{r.suggestedPrice}{diff !== 0 && ` (${diff > 0 ? '+' : ''}${diff})`}</span>;
    } },
  { title: '毛利率', dataIndex: 'margin', width: 80,
    render: (v) => {
      const pct = parseInt(String(v));
      return <span style={{ color: pct < 40 ? '#A32D2D' : '#0F6E56', fontWeight: 600 }}>{v}</span>;
    } },
  { title: '建议理由', dataIndex: 'reason', ellipsis: true },
  { title: '操作', valueType: 'option', width: 80,
    render: () => [
      <Button key="adopt" size="small" type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
        采纳
      </Button>,
    ] },
];

const TURNOVER_COLS: ProColumns<TurnoverRow>[] = [
  { title: '门店', dataIndex: 'store', width: 100 },
  { title: '区域', dataIndex: 'area', width: 80 },
  { title: '当前翻台率', dataIndex: 'currentRate', width: 110, render: (v) => `${v} 次/日` },
  { title: '目标翻台率', dataIndex: 'targetRate', width: 110, render: (v) => `${v} 次/日` },
  { title: 'AI 建议', dataIndex: 'suggestion', ellipsis: true },
  { title: '操作', valueType: 'option', width: 80,
    render: () => [
      <Button key="adopt" size="small" type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
        采纳
      </Button>,
    ] },
];

const TIME_SLOT_COLS: ProColumns<TimeSlotRow>[] = [
  { title: '时段', dataIndex: 'slot', width: 170 },
  { title: '当前 GMV', dataIndex: 'gmv', width: 110, render: (v) => `¥${Number(v).toLocaleString()}` },
  { title: 'GMV 占比', dataIndex: 'share', width: 90 },
  { title: '可提升空间', dataIndex: 'potential', width: 120,
    render: (v) => <span style={{ color: '#0F6E56', fontWeight: 600 }}>{v}</span> },
  { title: 'AI 建议', dataIndex: 'suggestion', ellipsis: true },
];

// ---- Tab 内容 ----
const tabItems: TabsProps['items'] = [
  {
    key: 'pricing',
    label: '菜品定价优化',
    children: (
      <ProTable<PricingRow>
        dataSource={PRICING_DATA}
        columns={PRICING_COLS}
        rowKey="key"
        search={false}
        toolBarRender={false}
        pagination={false}
        size="small"
      />
    ),
  },
  {
    key: 'turnover',
    label: '翻台率优化',
    children: (
      <ProTable<TurnoverRow>
        dataSource={TURNOVER_DATA}
        columns={TURNOVER_COLS}
        rowKey="key"
        search={false}
        toolBarRender={false}
        pagination={false}
        size="small"
      />
    ),
  },
  {
    key: 'timeslot',
    label: '时段收益分析',
    children: (
      <ProTable<TimeSlotRow>
        dataSource={TIME_SLOT_DATA}
        columns={TIME_SLOT_COLS}
        rowKey="key"
        search={false}
        toolBarRender={false}
        pagination={false}
        size="small"
      />
    ),
  },
];

// ---- 主组件 ----
export const RevenueOptimizePage = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24 }}>
        {/* 顶部 Alert */}
        <Alert
          type="success"
          showIcon
          message="tx-analytics 收益优化师 分析模式 — 已扫描 287 个菜品 · 生成 12 条优化建议"
          style={{ marginBottom: 16 }}
        />

        {/* 3 个 Statistic 卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card>
              <Statistic
                title="潜在收益提升"
                value="+¥12,400/月"
                valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="毛利低于阈值菜品"
                value={8}
                suffix="个"
                valueStyle={{ color: '#A32D2D', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="建议调价菜品"
                value={5}
                suffix="个"
                valueStyle={{ color: '#BA7517', fontWeight: 700 }}
              />
            </Card>
          </Col>
        </Row>

        {/* 主体 Tabs */}
        <Card style={{ marginBottom: 16 }}>
          <Tabs items={tabItems} />
        </Card>

        {/* 底部操作 */}
        <Space>
          <Button type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
            一键生成调价方案
          </Button>
          <Button>导出分析报告</Button>
        </Space>
      </div>
    </ConfigProvider>
  );
};
