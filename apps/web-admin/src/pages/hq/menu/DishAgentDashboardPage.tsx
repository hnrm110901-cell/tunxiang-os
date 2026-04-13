/**
 * DishAgentDashboardPage — 菜品智能体仪表盘
 * Sprint 4: tx-menu 菜品智能体 Admin层
 */
import React from 'react';
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, Tabs, Tag, Button,
} from 'antd';
import type { TabsProps } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Progress } from 'antd';

// ---- 类型 ----
interface HealthRow {
  key: number;
  dish: string;
  category: string;
  monthlySales: number;
  margin: number;
  conversionRate: string;
  stockStatus: '正常' | '偏低' | '不足';
  healthScore: number;
  aiSuggestion: string;
}

interface NewDishRow {
  key: number;
  name: string;
  launchDate: string;
  trialPeriod: string;
  totalSales: number;
  rating: number;
  cost: string;
  margin: number;
  suggestion: '转正式' | '延长试销' | '下架';
}

interface SoldOutRow {
  key: number;
  dish: string;
  stock: string;
  soldToday: number;
  predictSoldOutTime: string;
  alternative: string;
}

interface KitchenRow {
  key: number;
  timeSlot: string;
  expectedFlow: number;
  topDishes: string;
  suggestConfig: string;
  currentConfig: string;
  gap: string;
}

// ---- Mock 数据 ----
const healthData: HealthRow[] = [
  { key: 1, dish: '蒜蓉蒸鲍鱼',   category: '海鲜', monthlySales: 1280, margin: 52, conversionRate: '18.2%', stockStatus: '正常', healthScore: 92, aiSuggestion: '明星产品，保持' },
  { key: 2, dish: '清蒸多宝鱼',   category: '海鲜', monthlySales: 860,  margin: 45, conversionRate: '12.1%', stockStatus: '偏低', healthScore: 78, aiSuggestion: '可考虑周末特价促销' },
  { key: 3, dish: '麻辣小龙虾',   category: '海鲜', monthlySales: 420,  margin: 28, conversionRate: '6.3%',  stockStatus: '正常', healthScore: 54, aiSuggestion: '毛利偏低，建议调价或优化BOM' },
  { key: 4, dish: '白斩鸡',       category: '禽肉', monthlySales: 1580, margin: 48, conversionRate: '22.4%', stockStatus: '正常', healthScore: 88, aiSuggestion: '高转化明星，可适度提价' },
  { key: 5, dish: '招牌豆腐',     category: '蔬菜', monthlySales: 980,  margin: 62, conversionRate: '13.9%', stockStatus: '正常', healthScore: 85, aiSuggestion: '高毛利单品，重点推广' },
  { key: 6, dish: '炒杂蔬',       category: '蔬菜', monthlySales: 320,  margin: 22, conversionRate: '4.5%',  stockStatus: '不足', healthScore: 38, aiSuggestion: '建议下架，拉低整体形象' },
];

const newDishData: NewDishRow[] = [
  { key: 1, name: '花雕蒸花蟹',   launchDate: '2026-03-20', trialPeriod: '18天', totalSales: 286, rating: 4.7, cost: '¥88', margin: 43, suggestion: '转正式'   },
  { key: 2, name: '姜葱炒龙虾头', launchDate: '2026-03-28', trialPeriod: '10天', totalSales: 124, rating: 4.5, cost: '¥38', margin: 51, suggestion: '延长试销' },
  { key: 3, name: '泰式椰汁鸡',   launchDate: '2026-04-01', trialPeriod: '6天',  totalSales: 31,  rating: 3.8, cost: '¥42', margin: 29, suggestion: '下架'     },
];

const soldOutData: SoldOutRow[] = [
  { key: 1, dish: '濑尿虾',     stock: '5kg',  soldToday: 18, predictSoldOutTime: '今日14:30', alternative: '白灼基围虾'   },
  { key: 2, dish: '花蟹',       stock: '3只',  soldToday: 8,  predictSoldOutTime: '今日16:00', alternative: '肉蟹'         },
  { key: 3, dish: '鲍鱼（A批）', stock: '8头', soldToday: 12, predictSoldOutTime: '今日18:30', alternative: '鲍鱼（B批）' },
];

const kitchenData: KitchenRow[] = [
  { key: 1, timeSlot: '早市（7:00-11:00）',  expectedFlow: 120, topDishes: '粥品/点心/白粥',       suggestConfig: '2名厨师', currentConfig: '2名厨师', gap: '无缺口' },
  { key: 2, timeSlot: '午市（11:00-14:00）', expectedFlow: 380, topDishes: '白斩鸡/海鲜/蒸菜',     suggestConfig: '5名厨师', currentConfig: '4名厨师', gap: '缺1人'  },
  { key: 3, timeSlot: '下午茶（14:00-17:00）', expectedFlow: 80,  topDishes: '小吃/甜品/冷盘',   suggestConfig: '2名厨师', currentConfig: '2名厨师', gap: '无缺口' },
  { key: 4, timeSlot: '晚市（17:00-22:00）', expectedFlow: 520, topDishes: '鲍鱼/龙虾/花蟹/白斩鸡', suggestConfig: '6名厨师', currentConfig: '5名厨师', gap: '缺1人'  },
];

// ---- 列定义 ----
const healthColumns: ProColumns<HealthRow>[] = [
  { title: '菜品名', dataIndex: 'dish',     width: 120 },
  { title: '品类',   dataIndex: 'category', width: 70  },
  { title: '月销量', dataIndex: 'monthlySales', width: 80, render: (_, r) => `${r.monthlySales}份` },
  {
    title: '毛利率', dataIndex: 'margin', width: 90,
    render: (_, r) => (
      <span style={{ color: r.margin < 30 ? '#A32D2D' : r.margin < 45 ? '#BA7517' : '#0F6E56', fontWeight: 600 }}>
        {r.margin}%
      </span>
    ),
  },
  { title: '点单转化率', dataIndex: 'conversionRate', width: 100 },
  {
    title: '库存状态', dataIndex: 'stockStatus', width: 90,
    render: (_, r) => {
      const c = r.stockStatus === '正常' ? 'green' : r.stockStatus === '偏低' ? 'orange' : 'red';
      return <Tag color={c}>{r.stockStatus}</Tag>;
    },
  },
  {
    title: '健康评分', dataIndex: 'healthScore', width: 90,
    render: (_, r) => (
      <span style={{ color: r.healthScore < 60 ? '#A32D2D' : '#2C2C2A', fontWeight: 700 }}>
        {r.healthScore}
      </span>
    ),
  },
  { title: 'AI建议', dataIndex: 'aiSuggestion'},
];

const newDishColumns: ProColumns<NewDishRow>[] = [
  { title: '新品名',   dataIndex: 'name',        width: 120 },
  { title: '上架日期', dataIndex: 'launchDate',  width: 110 },
  { title: '试销期',   dataIndex: 'trialPeriod', width: 80  },
  { title: '累计销量', dataIndex: 'totalSales',  width: 90, render: (_, r) => `${r.totalSales}份` },
  { title: '客户评价均分', dataIndex: 'rating',  width: 100, render: (_, r) => `${r.rating}分` },
  { title: '成本',     dataIndex: 'cost',         width: 70  },
  { title: '毛利率',   dataIndex: 'margin',        width: 80, render: (_, r) => `${r.margin}%` },
  {
    title: '建议', dataIndex: 'suggestion', width: 90,
    render: (_, r) => {
      const c = r.suggestion === '转正式' ? 'green' : r.suggestion === '延长试销' ? 'orange' : 'red';
      return <Tag color={c}>{r.suggestion}</Tag>;
    },
  },
];

const soldOutColumns: ProColumns<SoldOutRow>[] = [
  { title: '菜品',     dataIndex: 'dish',              width: 120 },
  { title: '当前库存', dataIndex: 'stock',             width: 90  },
  { title: '今日已售', dataIndex: 'soldToday',         width: 90, render: (_, r) => `${r.soldToday}份` },
  {
    title: '预计沽清时间', dataIndex: 'predictSoldOutTime', width: 130,
    render: (_, r) => <span style={{ color: '#A32D2D', fontWeight: 600 }}>{r.predictSoldOutTime}</span>,
  },
  { title: '替代菜品', dataIndex: 'alternative', width: 110 },
  {
    title: '操作', valueType: 'option', width: 160,
    render: () => [
      <Button key="soldout" size="small" danger style={{ marginRight: 4 }}>设为沽清</Button>,
      <Button key="alt" size="small">推替代品</Button>,
    ],
  },
];

const kitchenColumns: ProColumns<KitchenRow>[] = [
  { title: '时段',       dataIndex: 'timeSlot',      width: 180 },
  { title: '预计客流',   dataIndex: 'expectedFlow',  width: 90, render: (_, r) => `${r.expectedFlow}人次` },
  { title: '需求菜品TOP5', dataIndex: 'topDishes'},
  { title: '建议厨师配置', dataIndex: 'suggestConfig', width: 110 },
  { title: '当前配置',   dataIndex: 'currentConfig', width: 90  },
  {
    title: '缺口', dataIndex: 'gap', width: 80,
    render: (_, r) => (
      <span style={{ color: r.gap === '无缺口' ? '#0F6E56' : '#A32D2D', fontWeight: 600 }}>
        {r.gap}
      </span>
    ),
  },
];

// ---- Tabs ----
const tabItems: TabsProps['items'] = [
  {
    key: '1',
    label: '菜品健康度',
    children: (
      <ProTable<HealthRow>
        columns={healthColumns}
        dataSource={healthData}
        rowKey="key"
        search={false}
        pagination={false}
        toolBarRender={false}
        size="small"
      />
    ),
  },
  {
    key: '2',
    label: '新品追踪',
    children: (
      <ProTable<NewDishRow>
        columns={newDishColumns}
        dataSource={newDishData}
        rowKey="key"
        search={false}
        pagination={false}
        toolBarRender={false}
        size="small"
      />
    ),
  },
  {
    key: '3',
    label: '沽清预警',
    children: (
      <ProTable<SoldOutRow>
        columns={soldOutColumns}
        dataSource={soldOutData}
        rowKey="key"
        search={false}
        pagination={false}
        toolBarRender={false}
        size="small"
      />
    ),
  },
  {
    key: '4',
    label: '厨房排班建议',
    children: (
      <ProTable<KitchenRow>
        columns={kitchenColumns}
        dataSource={kitchenData}
        rowKey="key"
        search={false}
        pagination={false}
        toolBarRender={false}
        size="small"
      />
    ),
  },
];

// ---- 页面组件 ----
export const DishAgentDashboardPage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部 Alert */}
        <Alert
          type="success"
          showIcon
          message="🍳 tx-menu 菜品智能体 · 已分析 287 道菜品 · 本周优化建议 15 条 · 3道菜品面临沽清风险"
          style={{ marginBottom: 16 }}
        />

        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card><Statistic title="监控菜品数" value={287} suffix="道" /></Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="本周新品" value={3} suffix="道" valueStyle={{ color: '#0F6E56' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="建议下架" value={2} suffix="道" valueStyle={{ color: '#A32D2D' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="毛利预警" value={8} suffix="道" valueStyle={{ color: '#BA7517' }} />
            </Card>
          </Col>
        </Row>

        {/* 主体 Tabs */}
        <Card>
          <Tabs items={tabItems} defaultActiveKey="1" />
        </Card>
      </div>
    </ConfigProvider>
  );
};
