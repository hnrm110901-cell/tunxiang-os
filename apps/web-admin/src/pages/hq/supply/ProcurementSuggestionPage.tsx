/**
 * ProcurementSuggestionPage — AI 采购建议
 * Sprint 4: tx-supply 供应链卫士
 */
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, Tabs, Button, Space,
  Tag,
} from 'antd';
import type { TabsProps } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Progress } from 'antd';

// ---- 类型 ----
interface ProcurementRow {
  key: number;
  name: string;
  currentStock: string;
  dailyConsume: string;
  suggestQty: string;
  supplier: string;
  refPrice: string;
}

interface ExpiryRow {
  key: number;
  name: string;
  expiryDate: string;
  daysLeft: number;
  stock: string;
  suggestion: string;
}

interface ForecastRow {
  key: number;
  name: string;
  weekForecast: string;
  lastWeekActual: string;
  deviation: string;
  confidence: number;
}

// ---- Mock 数据 ----
const procurementData: ProcurementRow[] = [
  { key: 1, name: '蒜蓉',   currentStock: '3.2kg', dailyConsume: '1.8kg', suggestQty: '12kg',  supplier: '南山海鲜行',     refPrice: '¥45/kg'  },
  { key: 2, name: '多宝鱼', currentStock: '8条',   dailyConsume: '5条',   suggestQty: '20条',  supplier: '顺丰活鲜',       refPrice: '¥68/条'  },
  { key: 3, name: '濑尿虾', currentStock: '5kg',   dailyConsume: '3kg',   suggestQty: '15kg',  supplier: '海产批发',       refPrice: '¥42/kg'  },
  { key: 4, name: '鲍鱼',   currentStock: '15头',  dailyConsume: '8头',   suggestQty: '30头',  supplier: '高档食材供应商', refPrice: '¥128/头' },
  { key: 5, name: '食用油', currentStock: '12L',   dailyConsume: '4L',    suggestQty: '20L',   supplier: '粮油批发',       refPrice: '¥18/L'   },
  { key: 6, name: '生姜',   currentStock: '2kg',   dailyConsume: '0.5kg', suggestQty: '4kg',   supplier: '蔬菜供应',       refPrice: '¥8/kg'   },
];

const expiryData: ExpiryRow[] = [
  { key: 1, name: '鲍鱼（A批）',   expiryDate: '2026-04-09', daysLeft: 2, stock: '8头',  suggestion: '优先出餐'  },
  { key: 2, name: '三文鱼（B批）', expiryDate: '2026-04-11', daysLeft: 4, stock: '3kg',  suggestion: '特价促销'  },
  { key: 3, name: '蒜蓉酱',        expiryDate: '2026-04-14', daysLeft: 7, stock: '1.5kg', suggestion: '降价处理' },
];

const forecastData: ForecastRow[] = [
  { key: 1, name: '蒜蓉蒸鲍鱼',   weekForecast: '280份', lastWeekActual: '256份', deviation: '+9.4%',  confidence: 94 },
  { key: 2, name: '清蒸多宝鱼',   weekForecast: '190份', lastWeekActual: '195份', deviation: '-2.6%',  confidence: 91 },
  { key: 3, name: '濑尿虾',       weekForecast: '320份', lastWeekActual: '298份', deviation: '+7.4%',  confidence: 89 },
  { key: 4, name: '姜葱炒花蟹',   weekForecast: '210份', lastWeekActual: '224份', deviation: '-6.3%',  confidence: 87 },
  { key: 5, name: '蒜蓉粉丝扇贝', weekForecast: '165份', lastWeekActual: '158份', deviation: '+4.4%',  confidence: 92 },
];

// ---- 列定义 ----
const procurementColumns: ProColumns<ProcurementRow>[] = [
  { title: '食材名称', dataIndex: 'name',         width: 90 },
  { title: '当前库存', dataIndex: 'currentStock', width: 90 },
  { title: '预计消耗', dataIndex: 'dailyConsume', width: 90 },
  { title: '建议采购量', dataIndex: 'suggestQty', width: 100 },
  { title: '供应商',   dataIndex: 'supplier',     width: 130 },
  { title: '参考价',   dataIndex: 'refPrice',     width: 90 },
  {
    title: '操作', valueType: 'option', width: 110,
    render: () => [
      <Button key="add" type="primary" size="small" style={{ background: '#FF6B35', border: 'none' }}>
        加入采购单
      </Button>,
    ],
  },
];

const expiryColumns: ProColumns<ExpiryRow>[] = [
  { title: '食材', dataIndex: 'name', width: 130 },
  { title: '到期日', dataIndex: 'expiryDate', width: 110 },
  {
    title: '剩余天数', dataIndex: 'daysLeft', width: 90,
    render: (_, r) => (
      <span style={{ color: r.daysLeft <= 3 ? '#A32D2D' : '#BA7517', fontWeight: 600 }}>
        {r.daysLeft}天
      </span>
    ),
  },
  { title: '库存量', dataIndex: 'stock', width: 80 },
  {
    title: '建议处理', dataIndex: 'suggestion', width: 100,
    render: (_, r) => {
      const colorMap: Record<string, string> = { '优先出餐': 'orange', '特价促销': 'volcano', '降价处理': 'gold' };
      return <Tag color={colorMap[r.suggestion] ?? 'default'}>{r.suggestion}</Tag>;
    },
  },
  {
    title: '操作', valueType: 'option', width: 80,
    render: () => [<a key="handle">处理</a>],
  },
];

const forecastColumns: ProColumns<ForecastRow>[] = [
  { title: '食材', dataIndex: 'name', width: 130 },
  { title: '本周预测需求', dataIndex: 'weekForecast', width: 110 },
  { title: '上周实际', dataIndex: 'lastWeekActual', width: 100 },
  {
    title: '预测偏差', dataIndex: 'deviation', width: 90,
    render: (_, r) => (
      <span style={{ color: r.deviation.startsWith('+') ? '#0F6E56' : '#A32D2D' }}>
        {r.deviation}
      </span>
    ),
  },
  {
    title: 'AI置信度', dataIndex: 'confidence', width: 130,
    render: (_, r) => <Progress percent={r.confidence} size="small" strokeColor="#FF6B35" />,
  },
];

// ---- Tabs ----
const tabItems: TabsProps['items'] = [
  {
    key: '1',
    label: '今日采购建议',
    children: (
      <ProTable<ProcurementRow>
        columns={procurementColumns}
        dataSource={procurementData}
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
    label: '临期预警',
    children: (
      <ProTable<ExpiryRow>
        columns={expiryColumns}
        dataSource={expiryData}
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
    label: '需求预测',
    children: (
      <ProTable<ForecastRow>
        columns={forecastColumns}
        dataSource={forecastData}
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
export const ProcurementSuggestionPage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部预警 */}
        <Alert
          type="warning"
          showIcon
          message="🛡️ tx-supply 供应链卫士 · 发现 3 个采购风险 · 建议今日处理"
          action={
            <Button size="small" style={{ background: '#FF6B35', color: 'white', border: 'none' }}>
              查看详情
            </Button>
          }
          style={{ marginBottom: 16 }}
        />

        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card><Statistic title="建议采购品类" value={12} suffix="个" /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="临期预警" value={3} suffix="个" valueStyle={{ color: '#A32D2D' }} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="库存不足风险" value={5} suffix="个" valueStyle={{ color: '#BA7517' }} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="预计采购金额" value="8,420" prefix="¥" /></Card>
          </Col>
        </Row>

        {/* 主体 Tabs */}
        <Card>
          <Tabs items={tabItems} defaultActiveKey="1" />
        </Card>

        {/* 底部操作 */}
        <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
          <Button type="primary" style={{ background: '#FF6B35', border: 'none' }}>
            生成采购单
          </Button>
          <Button>发送给供应商</Button>
        </div>
      </div>
    </ConfigProvider>
  );
};

// React import needed for JSX
import React from 'react';
