/**
 * DemandForecastPage — 需求预测
 * Sprint 4: tx-supply 供应链卫士
 */
import React from 'react';
import {
  ConfigProvider, Alert, Row, Col, Card, Button, Select, Tag, Space,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Progress } from 'antd';

// ---- 类型 ----
interface ForecastRow {
  key: number;
  dish: string;
  category: string;
  tomorrowForecast: number;
  weekForecast: number;
  lastWeekActual: number;
  deviation: string;
  stockStatus: '充足' | '偏低' | '不足';
  confidence: number;
}

// ---- Mock 数据 ----
const forecastData: ForecastRow[] = [
  { key: 1, dish: '蒜蓉蒸鲍鱼',   category: '海鲜', tomorrowForecast: 42,  weekForecast: 280, lastWeekActual: 256, deviation: '+9.4%',  stockStatus: '充足', confidence: 94 },
  { key: 2, dish: '清蒸多宝鱼',   category: '海鲜', tomorrowForecast: 28,  weekForecast: 190, lastWeekActual: 195, deviation: '-2.6%',  stockStatus: '偏低', confidence: 91 },
  { key: 3, dish: '濑尿虾',       category: '海鲜', tomorrowForecast: 48,  weekForecast: 320, lastWeekActual: 298, deviation: '+7.4%',  stockStatus: '不足', confidence: 89 },
  { key: 4, dish: '姜葱炒花蟹',   category: '海鲜', tomorrowForecast: 30,  weekForecast: 210, lastWeekActual: 224, deviation: '-6.3%',  stockStatus: '充足', confidence: 87 },
  { key: 5, dish: '白斩鸡',       category: '禽肉', tomorrowForecast: 55,  weekForecast: 380, lastWeekActual: 362, deviation: '+5.0%',  stockStatus: '充足', confidence: 93 },
  { key: 6, dish: '蒜蓉炒芥蓝',   category: '蔬菜', tomorrowForecast: 60,  weekForecast: 420, lastWeekActual: 415, deviation: '+1.2%',  stockStatus: '充足', confidence: 96 },
  { key: 7, dish: '招牌冬瓜盅',   category: '蔬菜', tomorrowForecast: 35,  weekForecast: 245, lastWeekActual: 230, deviation: '+6.5%',  stockStatus: '偏低', confidence: 88 },
  { key: 8, dish: '杨枝甘露',     category: '饮品', tomorrowForecast: 80,  weekForecast: 560, lastWeekActual: 520, deviation: '+7.7%',  stockStatus: '充足', confidence: 95 },
];

const stockStatusColor: Record<string, string> = {
  '充足': 'green',
  '偏低': 'orange',
  '不足': 'red',
};

// ---- 列定义 ----
const columns: ProColumns<ForecastRow>[] = [
  { title: '菜品名',     dataIndex: 'dish',              width: 130 },
  { title: '品类',       dataIndex: 'category',          width: 70  },
  { title: '明日预测销量', dataIndex: 'tomorrowForecast', width: 100, render: (_, r) => `${r.tomorrowForecast}份` },
  { title: '本周预测',   dataIndex: 'weekForecast',       width: 90,  render: (_, r) => `${r.weekForecast}份`    },
  { title: '上周实际',   dataIndex: 'lastWeekActual',     width: 90,  render: (_, r) => `${r.lastWeekActual}份`  },
  {
    title: '预测偏差', dataIndex: 'deviation', width: 90,
    render: (_, r) => (
      <span style={{ color: r.deviation.startsWith('+') ? '#0F6E56' : '#A32D2D', fontWeight: 500 }}>
        {r.deviation}
      </span>
    ),
  },
  {
    title: '库存充足性', dataIndex: 'stockStatus', width: 100,
    render: (_, r) => <Tag color={stockStatusColor[r.stockStatus]}>{r.stockStatus}</Tag>,
  },
  {
    title: 'AI置信度', dataIndex: 'confidence', width: 130,
    render: (_, r) => <Progress percent={r.confidence} size="small" strokeColor="#FF6B35" />,
  },
];

// ---- 页面组件 ----
export const DemandForecastPage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部筛选栏 */}
        <Row justify="end" style={{ marginBottom: 12 }}>
          <Space>
            <Select
              defaultValue="all"
              style={{ width: 140 }}
              options={[
                { label: '全部门店', value: 'all' },
                { label: '南山旗舰', value: 'ns' },
                { label: '福田中心', value: 'ft' },
                { label: '罗湖商圈', value: 'lh' },
              ]}
            />
            <Button.Group>
              <Button type="primary" style={{ background: '#FF6B35', border: 'none' }}>本周</Button>
              <Button>上周</Button>
              <Button>本月</Button>
            </Button.Group>
          </Space>
        </Row>

        {/* AI 模型信息 */}
        <Alert
          type="success"
          showIcon
          message="AI预测模型准确率 94.2% · 基于历史365天数据 + 天气/节假日/促销因子训练"
          style={{ marginBottom: 16 }}
        />

        {/* 主体 ProTable */}
        <Card>
          <ProTable<ForecastRow>
            columns={columns}
            dataSource={forecastData}
            rowKey="key"
            search={false}
            pagination={false}
            toolBarRender={false}
            size="small"
          />
        </Card>

        {/* 底部操作 */}
        <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
          <Button type="primary" style={{ background: '#FF6B35', border: 'none' }}>
            同步至采购建议
          </Button>
          <Button>导出预测报告</Button>
        </div>
      </div>
    </ConfigProvider>
  );
};
