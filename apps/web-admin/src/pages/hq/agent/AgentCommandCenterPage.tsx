/**
 * AgentCommandCenterPage — 运营指挥官大盘
 * Sprint 1: 运营指挥官基础层
 */
import { Alert, Button, Card, Col, ConfigProvider, Row, Tag, Timeline } from 'antd';
import { ProTable, StatisticCard } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

/* ─── 行动队列类型 ─── */
interface ActionItem {
  id: string;
  priority: 'critical' | 'warning' | 'info';
  agent: string;
  scenario: string;
  suggestion: string;
  status: string;
  time: string;
}

/* ─── Mock 行动队列 ─── */
const MOCK_ACTIONS: ActionItem[] = [
  { id: '1',  priority: 'critical', agent: '运营指挥官', scenario: '菜品超时出餐',   suggestion: 'B01桌剁椒鱼头超时8分钟，立即催单并告知客人',        status: '待确认', time: '14:32' },
  { id: '2',  priority: 'critical', agent: '运营指挥官', scenario: '高峰期翻台率低', suggestion: '当前翻台率52%，建议加快B区3桌结账引导',              status: '待确认', time: '14:30' },
  { id: '3',  priority: 'critical', agent: '供应链卫士', scenario: '库存临界告警',   suggestion: '皮皮虾仅余2份，建议立即沽清避免超卖投诉',            status: '待确认', time: '14:28' },
  { id: '4',  priority: 'warning',  agent: '运营指挥官', scenario: '排队等位超时',   suggestion: 'A027号赵先生等38分钟，A07台已空，建议立即叫号',      status: '处理中', time: '14:25' },
  { id: '5',  priority: 'warning',  agent: '客户大脑',   scenario: 'VIP会员到店',   suggestion: 'D04桌王总(钻石会员)，建议推荐存酒续存并安排专属服务', status: '已确认', time: '14:20' },
  { id: '6',  priority: 'warning',  agent: '收益优化师', scenario: '外卖订单接入',  suggestion: '美团MT-5892已自动接单，¥218，建议优先排入厨房',       status: '已执行', time: '14:18' },
  { id: '7',  priority: 'warning',  agent: '菜品智能体', scenario: '推荐时机识别',  suggestion: '张桌用餐58分钟，识别为潜在续餐场景，推荐甜品',        status: '待确认', time: '14:15' },
  { id: '8',  priority: 'info',     agent: '经营分析师', scenario: '经营健康监控',  suggestion: '今日毛利率68.2%，高于目标3.2%，整体运营状况良好',     status: '已通知', time: '14:10' },
  { id: '9',  priority: 'info',     agent: '供应链卫士', scenario: '采购建议',      suggestion: '根据明日预订量，建议增加鲍鱼采购量20%',              status: '已通知', time: '14:05' },
  { id: '10', priority: 'info',     agent: '运营指挥官', scenario: '班次交接提醒',  suggestion: '14:30晚市班次开始，建议提醒相关员工完成交接',         status: '已执行', time: '14:00' },
];

/* ─── 实时事件流数据 ─── */
const TIMELINE_EVENTS = [
  { color: 'red',    label: '14:32', content: '🔴 B01桌超时 — 剁椒鱼头已超时8分钟，自动催单通知已发出' },
  { color: 'orange', label: '14:25', content: '🟡 A027叫号 — 赵先生4人，A07台就绪，建议立即叫号' },
  { color: 'blue',   label: '14:20', content: '🔵 D04结账识别 — 王总钻石会员，建议推荐存酒续存' },
  { color: 'green',  label: '14:10', content: '🟢 美团MT-5891外卖接单 — ¥128，厨房负载60%，预计准时' },
  { color: 'orange', label: '14:05', content: '🟡 椒盐皮皮虾库存预警 — 剩余2份，供应链卫士建议沽清' },
];

/* ─── 列定义 ─── */
const ACTION_COLUMNS: ProColumns<ActionItem>[] = [
  {
    title: '优先级',
    dataIndex: 'priority',
    width: 90,
    render: (_, r) => (
      <Tag color={r.priority === 'critical' ? 'red' : r.priority === 'warning' ? 'orange' : 'blue'}>
        {r.priority === 'critical' ? '紧急' : r.priority === 'warning' ? '警告' : '提示'}
      </Tag>
    ),
  },
  { title: 'Agent',   dataIndex: 'agent',      width: 100 },
  { title: '触发场景', dataIndex: 'scenario',   width: 120 },
  { title: '建议行动', dataIndex: 'suggestion', ellipsis: true },
  {
    title: '状态',
    dataIndex: 'status',
    width: 80,
    render: (_, r) => (
      <Tag color={r.status === '已执行' || r.status === '已确认' || r.status === '已通知' ? 'green' : r.status === '处理中' ? 'blue' : 'gold'}>
        {r.status}
      </Tag>
    ),
  },
  { title: '时间', dataIndex: 'time', width: 70 },
  {
    title: '操作',
    width: 140,
    render: () => (
      <div style={{ display: 'flex', gap: 6 }}>
        <Button size="small" type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>确认</Button>
        <Button size="small" type="default">忽略</Button>
      </div>
    ),
  },
];

/* ─── 主页面 ─── */
export function AgentCommandCenterPage() {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>运营大盘</h2>

        {/* 连接状态 */}
        <Alert
          message="连接状态：已连接 Agent 服务器 · 实时同步中 (SSE)"
          type="success"
          showIcon
          style={{ marginBottom: 24 }}
        />

        {/* 统计卡 */}
        <StatisticCard.Group style={{ marginBottom: 24 }}>
          <StatisticCard statistic={{ title: '在线 Agent 数', value: 6, suffix: '个', valueStyle: { color: '#52c41a' } }} />
          <StatisticCard statistic={{ title: '今日行动数',    value: 47, suffix: '次' }} />
          <StatisticCard statistic={{ title: '待确认',        value: 3,  suffix: '条', valueStyle: { color: '#FF6B35' } }} />
          <StatisticCard statistic={{ title: '自动处理率',    value: 89, suffix: '%',  valueStyle: { color: '#185FA5' } }} />
        </StatisticCard.Group>

        {/* 主体：行动队列 + 实时事件流 */}
        <Row gutter={16}>
          <Col span={17}>
            <ProTable<ActionItem>
              headerTitle="行动队列"
              columns={ACTION_COLUMNS}
              dataSource={MOCK_ACTIONS}
              rowKey="id"
              search={false}
              pagination={false}
              options={false}
              rowClassName={(r) => r.priority === 'critical' ? 'ant-table-row-danger' : ''}
              cardProps={{ bodyStyle: { padding: 0 } }}
              style={{ background: '#fff', borderRadius: 8 }}
            />
          </Col>
          <Col span={7}>
            <Card title="实时事件流" style={{ height: '100%' }}>
              <Timeline
                items={TIMELINE_EVENTS.map((e) => ({
                  color: e.color,
                  children: (
                    <div>
                      <div style={{ fontSize: 11, color: '#999', marginBottom: 2 }}>{e.label}</div>
                      <div style={{ fontSize: 13, lineHeight: 1.5 }}>{e.content}</div>
                    </div>
                  ),
                }))}
              />
            </Card>
          </Col>
        </Row>
      </div>
    </ConfigProvider>
  );
}
