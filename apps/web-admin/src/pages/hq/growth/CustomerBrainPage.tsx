/**
 * CustomerBrainPage — 客户大脑工作台
 * Sprint 3: tx-growth 客户大脑，RFM分层 + 流失预警 + 个性化推荐 + 营销活动效果
 */
import { useState } from 'react';
import {
  ConfigProvider, Alert, Row, Col, Card, Statistic, Tabs, Button, Tag, Space, Select, DatePicker,
} from 'antd';
import type { TabsProps } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

const { RangePicker } = DatePicker;

// ---- 类型 ----
interface ChurnRow {
  key: number;
  name: string;
  level: string;
  lastVisit: string;
  churnProb: number;
  churnReason: string;
}

interface RecommendRow {
  key: number;
  name: string;
  dish: string;
  reason: string;
  timing: string;
  status: string;
}

// ---- Mock 数据 ----
const RFM_SEGMENTS = [
  { label: '冠军客户', count: 342,  avgSpend: 2840, color: '#FF6B35', action: '维系 VIP 权益' },
  { label: '忠诚客户', count: 621,  avgSpend: 1580, color: '#0F6E56', action: '升级会员等级' },
  { label: '潜力客户', count: 987,  avgSpend: 890,  color: '#185FA5', action: '发优惠券激活' },
  { label: '需要关注', count: 468,  avgSpend: 640,  color: '#BA7517', action: '定向推送关怀' },
  { label: '即将流失', count: 234,  avgSpend: 420,  color: '#A32D2D', action: '紧急召回活动' },
  { label: '已流失',   count: 689,  avgSpend: 210,  color: '#888',    action: '长期召回旅程' },
];

const CHURN_DATA: ChurnRow[] = [
  { key: 1, name: '张*明', level: '钻石会员', lastVisit: '2026-02-10', churnProb: 87, churnReason: '消费频率骤降，最近60天无到店记录' },
  { key: 2, name: '李*芳', level: '金卡会员', lastVisit: '2026-02-25', churnProb: 76, churnReason: '竞品门店附近新开，触达无响应' },
  { key: 3, name: '王*伟', level: '银卡会员', lastVisit: '2026-03-01', churnProb: 65, churnReason: '历史投诉未妥善处理，复购断层' },
  { key: 4, name: '赵*丽', level: '普通会员', lastVisit: '2026-03-10', churnProb: 58, churnReason: '客单价下降趋势，活跃度衰减' },
  { key: 5, name: '陈*强', level: '金卡会员', lastVisit: '2026-03-12', churnProb: 52, churnReason: '近期推送打开率为零，疑似设备换绑' },
];

const RECOMMEND_DATA: RecommendRow[] = [
  { key: 1, name: '张*华', dish: '蒜蓉蒸鲍鱼', reason: '历史3次点单，喜好度高', timing: '周末晚市前推送', status: '待发送' },
  { key: 2, name: '刘*丽', dish: '清蒸多宝鱼', reason: '同类客群推荐命中率72%', timing: '周五午市', status: '已发送' },
  { key: 3, name: '黄*峰', dish: '龙虾粥', reason: '最后一单含粥类，扩展推荐', timing: '工作日早市', status: '待发送' },
  { key: 4, name: '周*梅', dish: '椒盐濑尿虾', reason: '口味偏辣，符合历史偏好', timing: '周末', status: '已发送' },
  { key: 5, name: '吴*博', dish: '海鲜炒饭', reason: '预算中等，性价比推荐', timing: '午市', status: '待发送' },
];

const CAMPAIGNS = [
  { name: '会员日双倍积分', reach: 3420, conversion: 28.4, roi: 312 },
  { name: '流失召回优惠券', reach: 487,  conversion: 12.3, roi: 168 },
  { name: '新客首单立减',   reach: 623,  conversion: 45.2, roi: 245 },
  { name: '周末家庭套餐推广', reach: 1240, conversion: 18.7, roi: 89  },
];

const roiColor = (roi: number) => {
  if (roi >= 200) return '#0F6E56';
  if (roi >= 100) return '#BA7517';
  return '#A32D2D';
};

// ---- 列定义 ----
const CHURN_COLS: ProColumns<ChurnRow>[] = [
  { title: '会员名', dataIndex: 'name', width: 90 },
  { title: '等级', dataIndex: 'level', width: 90, render: (v) => <Tag color="gold">{v}</Tag> },
  { title: '最后到访', dataIndex: 'lastVisit', width: 110 },
  { title: '预测流失概率', dataIndex: 'churnProb', width: 120,
    render: (v) => {
      const pct = Number(v);
      return <span style={{ color: pct >= 70 ? '#A32D2D' : '#BA7517', fontWeight: 700 }}>{pct}%</span>;
    } },
  { title: '流失原因预测', dataIndex: 'churnReason', ellipsis: true },
  { title: '操作', valueType: 'option', width: 100,
    render: () => [
      <Button key="coupon" size="small" type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
        发优惠券
      </Button>,
    ] },
];

const RECOMMEND_COLS: ProColumns<RecommendRow>[] = [
  { title: '会员名', dataIndex: 'name', width: 90 },
  { title: '推荐菜品', dataIndex: 'dish', width: 120 },
  { title: '推荐理由', dataIndex: 'reason', ellipsis: true },
  { title: '推荐时机', dataIndex: 'timing', width: 140 },
  { title: '状态', dataIndex: 'status', width: 90,
    render: (v) => <Tag color={v === '已发送' ? 'green' : 'blue'}>{v}</Tag> },
];

// ---- Tab 内容 ----
const tabItems: TabsProps['items'] = [
  {
    key: 'rfm',
    label: 'RFM 客户分层',
    children: (
      <Row gutter={[16, 16]}>
        {RFM_SEGMENTS.map((seg) => (
          <Col span={8} key={seg.label}>
            <Card
              style={{ borderTop: `4px solid ${seg.color}` }}
              styles={{ body: { padding: 16 } }}
            >
              <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 8 }}>{seg.label}</div>
              <div style={{ color: '#666', marginBottom: 4 }}>人数：<span style={{ color: seg.color, fontWeight: 700 }}>{seg.count}</span> 人</div>
              <div style={{ color: '#666', marginBottom: 12 }}>平均消费：<span style={{ fontWeight: 600 }}>¥{seg.avgSpend}</span></div>
              <Button size="small" style={{ borderColor: seg.color, color: seg.color }}>触达</Button>
            </Card>
          </Col>
        ))}
      </Row>
    ),
  },
  {
    key: 'churn',
    label: 'AI 流失预警',
    children: (
      <ProTable<ChurnRow>
        dataSource={CHURN_DATA}
        columns={CHURN_COLS}
        rowKey="key"
        search={false}
        toolBarRender={false}
        pagination={false}
        size="small"
        rowClassName={(r) => r.churnProb >= 70 ? 'ant-table-row-danger' : ''}
      />
    ),
  },
  {
    key: 'recommend',
    label: '个性化推荐',
    children: (
      <ProTable<RecommendRow>
        dataSource={RECOMMEND_DATA}
        columns={RECOMMEND_COLS}
        rowKey="key"
        search={false}
        toolBarRender={false}
        pagination={false}
        size="small"
      />
    ),
  },
  {
    key: 'campaigns',
    label: '营销活动效果',
    children: (
      <Row gutter={[16, 16]}>
        {CAMPAIGNS.map((c) => (
          <Col span={12} key={c.name}>
            <Card title={c.name} styles={{ header: { fontWeight: 600 } }}>
              <Row gutter={16}>
                <Col span={8}>
                  <Statistic title="触达人数" value={c.reach} suffix="人" valueStyle={{ fontSize: 18 }} />
                </Col>
                <Col span={8}>
                  <Statistic title="转化率" value={c.conversion} suffix="%" valueStyle={{ fontSize: 18 }} />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="ROI"
                    value={c.roi}
                    suffix="%"
                    valueStyle={{ fontSize: 18, color: roiColor(c.roi), fontWeight: 700 }}
                  />
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>
    ),
  },
];

// ---- 主组件 ----
export const CustomerBrainPage = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24 }}>
        {/* 顶部过滤器行 */}
        <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
          <Col>
            <Alert
              type="info"
              showIcon
              message="tx-growth 客户大脑 · 已分析 12,847 名会员 · RFM模型最后更新: 今日 04:00"
              style={{ marginBottom: 0 }}
            />
          </Col>
          <Col>
            <Space>
              <Select
                placeholder="全部门店"
                style={{ width: 160 }}
                options={[
                  { value: 'all',   label: '全部门店' },
                  { value: 'nm',    label: '南山旗舰店' },
                  { value: 'ft',    label: '福田中心店' },
                  { value: 'lh',    label: '罗湖商圈店' },
                ]}
              />
              <RangePicker style={{ width: 220 }} />
            </Space>
          </Col>
        </Row>

        {/* 4 个 Statistic 卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic title="总活跃会员" value={12847} suffix="人" valueStyle={{ color: '#2C2C2A', fontWeight: 700 }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="AI 识别高价值" value={2341} suffix="人" valueStyle={{ color: '#FF6B35', fontWeight: 700 }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="流失预警" value={487} suffix="人" valueStyle={{ color: '#A32D2D', fontWeight: 700 }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="本月新增" value={623} suffix="人" valueStyle={{ color: '#0F6E56', fontWeight: 700 }} />
            </Card>
          </Col>
        </Row>

        {/* 主体 Tabs */}
        <Card>
          <Tabs items={tabItems} />
        </Card>
      </div>
    </ConfigProvider>
  );
};
