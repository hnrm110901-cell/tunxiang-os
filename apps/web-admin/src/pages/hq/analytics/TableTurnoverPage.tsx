/**
 * TableTurnoverPage — 翻台率分析
 * Sprint 4: tx-analytics 翻台率分析
 */
import React from 'react';
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, List, Progress,
} from 'antd';
import { BulbOutlined } from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

// ---- 类型 ----
interface TurnoverRow {
  key: number;
  store: string;
  lunchRate: number;
  dinnerRate: number;
  avgRate: number;
  target: number;
  achievement: number;
  aiSuggestion: string;
}

interface TimeSlotItem {
  slot: string;
  rate: number;
  percent: number;
}

// ---- Mock 数据 ----
const turnoverData: TurnoverRow[] = [
  { key: 1, store: '南山旗舰',   lunchRate: 3.2, dinnerRate: 3.8, avgRate: 3.5, target: 2.8, achievement: 125, aiSuggestion: '翻台表现优秀，可作为标杆' },
  { key: 2, store: '福田中心',   lunchRate: 2.1, dinnerRate: 2.8, avgRate: 2.5, target: 2.8, achievement: 89,  aiSuggestion: '午市翻台偏低，建议加快出餐节奏'  },
  { key: 3, store: '罗湖商圈',   lunchRate: 1.8, dinnerRate: 2.4, avgRate: 2.1, target: 2.8, achievement: 75,  aiSuggestion: '整体偏低，建议优化桌台周转流程' },
  { key: 4, store: '天河高端店', lunchRate: 2.5, dinnerRate: 3.0, avgRate: 2.8, target: 2.8, achievement: 100, aiSuggestion: '达标，可尝试提升晚市密度'  },
  { key: 5, store: '龙华新城',   lunchRate: 1.5, dinnerRate: 2.0, avgRate: 1.8, target: 2.8, achievement: 64,  aiSuggestion: '翻台严重不足，需重点关注运营效率' },
];

const timeSlots: TimeSlotItem[] = [
  { slot: '早市（7:00-11:00）',  rate: 1.2, percent: 43 },
  { slot: '午市（11:00-14:00）', rate: 2.3, percent: 82 },
  { slot: '下午茶（14:00-17:00）', rate: 0.8, percent: 29 },
  { slot: '晚市（17:00-22:00）', rate: 2.9, percent: 100 },
];

const aiSuggestions = [
  '罗湖商圈和龙华新城翻台率低于目标，建议减少单桌用餐时间上限，增加翻台提示服务',
  '午市翻台普遍低于晚市，可通过午市限时优惠（如「90分钟享8折」）提升节奏',
  '下午茶时段翻台最低，建议将下午茶改为小吃拼盘快餐模式，降低占台时间',
];

// ---- 列定义 ----
const columns: ProColumns<TurnoverRow>[] = [
  { title: '门店',     dataIndex: 'store',       width: 110 },
  { title: '午市翻台', dataIndex: 'lunchRate',   width: 90, render: (_, r) => `${r.lunchRate}次`  },
  { title: '晚市翻台', dataIndex: 'dinnerRate',  width: 90, render: (_, r) => `${r.dinnerRate}次` },
  { title: '全天均值', dataIndex: 'avgRate',     width: 90, render: (_, r) => `${r.avgRate}次`    },
  { title: '目标',     dataIndex: 'target',      width: 70, render: (_, r) => `${r.target}次`     },
  {
    title: '达成率', dataIndex: 'achievement', width: 140,
    render: (_, r) => (
      <Progress
        percent={r.achievement}
        size="small"
        strokeColor={r.achievement < 80 ? '#A32D2D' : '#FF6B35'}
        format={(p) => `${p}%`}
      />
    ),
  },
  { title: 'AI建议',   dataIndex: 'aiSuggestion', flex: 1 },
  {
    title: '操作', valueType: 'option', width: 80,
    render: () => [<a key="detail" style={{ color: '#FF6B35' }}>查看详情</a>],
  },
];

// ---- 页面组件 ----
export const TableTurnoverPage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card><Statistic title="全店均翻台率" value={2.3} suffix="次" /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="目标" value={2.8} suffix="次" /></Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="达标门店" value="2/5" valueStyle={{ color: '#BA7517' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="最佳门店" value="南山旗舰" valueStyle={{ color: '#0F6E56', fontSize: 16 }} />
            </Card>
          </Col>
        </Row>

        {/* 预警 */}
        <Alert
          type="warning"
          showIcon
          message="tx-analytics：3家门店翻台率低于目标，已生成优化建议"
          style={{ marginBottom: 16 }}
        />

        {/* 主体 */}
        <Row gutter={16}>
          {/* 左侧：门店翻台率列表 */}
          <Col span={16}>
            <Card title="门店翻台率列表">
              <ProTable<TurnoverRow>
                columns={columns}
                dataSource={turnoverData}
                rowKey="key"
                search={false}
                pagination={false}
                toolBarRender={false}
                size="small"
              />
            </Card>
          </Col>

          {/* 右侧：时段分析 + 优化建议 */}
          <Col span={8}>
            <Card title="时段分析">
              {timeSlots.map((item) => (
                <div key={item.slot} style={{ marginBottom: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
                    <span>{item.slot}</span>
                    <span style={{ fontWeight: 600 }}>{item.rate}次</span>
                  </div>
                  <Progress
                    percent={item.percent}
                    size="small"
                    strokeColor="#FF6B35"
                    showInfo={false}
                  />
                </div>
              ))}
            </Card>

            <Card title="优化建议" style={{ marginTop: 16 }}>
              <List
                dataSource={aiSuggestions}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={<BulbOutlined style={{ color: '#FA8C16', fontSize: 16, marginTop: 2 }} />}
                      description={<span style={{ fontSize: 12 }}>{item}</span>}
                    />
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </ConfigProvider>
  );
};
