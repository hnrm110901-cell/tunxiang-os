/**
 * AgentHubPage — AI 中枢首页
 * Sprint 1: 运营指挥官基础层
 */
import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Col, ConfigProvider, Row, Tag } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

/* ─── Agent 卡片数据 ─── */
interface AgentCardData {
  emoji: string;
  nameZh: string;
  nameEn: string;
  agentId: string;
  color: string;
  todayCount: number;
}

const AGENT_CARDS: AgentCardData[] = [
  { emoji: '🎯', nameZh: '运营指挥官',   nameEn: 'Operations Commander',        agentId: 'tx-ops',       color: '#FF6B35', todayCount: 12 },
  { emoji: '🍳', nameZh: '菜品智能体',   nameEn: 'Dish Intelligence Agent',      agentId: 'tx-menu',      color: '#0F6E56', todayCount: 7  },
  { emoji: '👤', nameZh: '客户大脑',     nameEn: 'Customer Intelligence Agent',  agentId: 'tx-growth',    color: '#6D3EA8', todayCount: 15 },
  { emoji: '💰', nameZh: '收益优化师',   nameEn: 'Revenue Optimization Agent',   agentId: 'tx-analytics', color: '#BA7517', todayCount: 5  },
  { emoji: '📦', nameZh: '供应链卫士',   nameEn: 'Supply Chain Guardian',        agentId: 'tx-supply',    color: '#0D7377', todayCount: 8  },
  { emoji: '📊', nameZh: '经营分析师',   nameEn: 'Business Intelligence Agent',  agentId: 'tx-brain',     color: '#185FA5', todayCount: 3  },
];

/* ─── 决策日志类型 ─── */
interface DecisionLog {
  id: string;
  time: string;
  agent: string;
  actionType: string;
  summary: string;
  result: string;
  confidence: number;
}

/* ─── Mock 日志数据 ─── */
const MOCK_LOGS: DecisionLog[] = [
  { id: '1',  time: '14:32:05', agent: '运营指挥官',  actionType: '超时催单',   summary: 'B01桌剁椒鱼头已超时8分钟，自动触发催单通知',      result: '已执行', confidence: 94 },
  { id: '2',  time: '14:28:41', agent: '运营指挥官',  actionType: 'AI叫号',     summary: 'A07空台就绪，推荐叫A027号赵先生(4人)',              result: '待确认', confidence: 91 },
  { id: '3',  time: '14:15:22', agent: '客户大脑',    actionType: '会员识别',   summary: 'D04桌识别钻石会员王总，建议推荐存酒续存服务',       result: '已执行', confidence: 98 },
  { id: '4',  time: '14:10:07', agent: '运营指挥官',  actionType: '自动接单',   summary: '美团外卖MT-5891自动接单，金额¥128，厨房负载60%',   result: '已执行', confidence: 99 },
  { id: '5',  time: '13:58:33', agent: '供应链卫士',  actionType: '沽清同步',   summary: '椒盐皮皮虾库存仅剩2份，建议临时沽清以防超卖',       result: '待确认', confidence: 87 },
  { id: '6',  time: '13:45:18', agent: '收益优化师',  actionType: '定价建议',   summary: '周末晚市人均消费低于目标，建议增加套餐曝光',        result: '已确认', confidence: 82 },
  { id: '7',  time: '13:30:55', agent: '菜品智能体',  actionType: '排菜优化',   summary: '今日特供：佛跳墙毛利率最高，建议加大推荐力度',      result: '已执行', confidence: 89 },
  { id: '8',  time: '13:22:10', agent: '经营分析师',  actionType: '异常检测',   summary: '午市翻台率较上周同期下降12%，触发经营异常预警',      result: '已通知', confidence: 95 },
  { id: '9',  time: '12:55:44', agent: '客户大脑',    actionType: '复购提醒',   summary: 'VIP客户陈女士30天未到店，触发召回旅程推送优惠',     result: '已执行', confidence: 76 },
  { id: '10', time: '12:40:29', agent: '供应链卫士',  actionType: '库存预警',   summary: '生蚝库存低于安全阈值，建议今日下午补货采购',        result: '已确认', confidence: 93 },
];

/* ─── ProTable 列定义 ─── */
const LOG_COLUMNS: ProColumns<DecisionLog>[] = [
  { title: '时间',     dataIndex: 'time',       width: 90,  valueType: 'text' },
  { title: 'Agent',   dataIndex: 'agent',      width: 100, valueType: 'text',
    render: (_, r) => <Tag color="blue">{r.agent}</Tag> },
  { title: '动作类型', dataIndex: 'actionType', width: 100, valueType: 'text',
    render: (_, r) => <Tag color="orange">{r.actionType}</Tag> },
  { title: '内容摘要', dataIndex: 'summary',    ellipsis: true },
  { title: '结果',     dataIndex: 'result',     width: 80,
    render: (_, r) => (
      <Tag color={r.result === '已执行' || r.result === '已确认' || r.result === '已通知' ? 'green' : 'gold'}>
        {r.result}
      </Tag>
    ),
  },
  { title: '置信度',   dataIndex: 'confidence', width: 80,
    render: (_, r) => <span style={{ color: r.confidence >= 90 ? '#52c41a' : '#faad14' }}>{r.confidence}%</span> },
];

/* ─── Agent 卡片组件 ─── */
function AgentCard({ card }: { card: AgentCardData }) {
  return (
    <Card
      style={{ borderLeft: `4px solid ${card.color}`, borderRadius: 8 }}
      bodyStyle={{ padding: '16px' }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>
            {card.emoji} {card.nameZh}
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>{card.nameEn}</div>
        </div>
        <Badge
          count="建议模式"
          style={{ backgroundColor: '#FF6B35', fontSize: 10, padding: '0 6px' }}
        />
      </div>
      <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>
        今日行动：<span style={{ fontWeight: 600, color: '#333' }}>{card.todayCount}</span> 次
      </div>
      <div style={{ fontSize: 13, marginBottom: 12 }}>
        状态：<span style={{ color: '#52c41a', fontWeight: 600 }}>● 在线</span>
      </div>
      <Button size="small" type="default" style={{ borderColor: card.color, color: card.color }}>
        查看详情
      </Button>
    </Card>
  );
}

/* ─── 主页面 ─── */
export function AgentHubPage() {
  const [agentData, setAgentData] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const tenantId = localStorage.getItem('tx-tenant-id') || 'default';
    fetch('/api/v1/agent-hub/status', {
      headers: { 'X-Tenant-ID': tenantId },
    })
      .then(r => r.json())
      .then(res => {
        if (res.ok) {
          setAgentData(res.data.agents);
          setSummary(res.data.summary);
        }
      })
      .catch(() => {/* 保留 mock 数据 */})
      .finally(() => setLoading(false));
  }, []);

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>AI 中枢首页</h2>

        {/* Phase 1 提示 */}
        <Alert
          message="Phase 1 · 建议模式 — 所有 Agent 行动需人工确认后执行"
          type="info"
          showIcon
          style={{ marginBottom: 24 }}
        />

        {/* Agent 卡片网格 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          {AGENT_CARDS.slice(0, 3).map((card) => (
            <Col key={card.agentId} span={8}>
              <AgentCard card={card} />
            </Col>
          ))}
        </Row>
        <Row gutter={16} style={{ marginBottom: 24 }}>
          {AGENT_CARDS.slice(3, 6).map((card) => (
            <Col key={card.agentId} span={8}>
              <AgentCard card={card} />
            </Col>
          ))}
        </Row>

        {/* 决策日志 ProTable */}
        <ProTable<DecisionLog>
          headerTitle="近期 Agent 决策日志"
          columns={LOG_COLUMNS}
          dataSource={MOCK_LOGS}
          rowKey="id"
          search={false}
          pagination={{ pageSize: 10 }}
          options={false}
          cardProps={{ bodyStyle: { padding: 0 } }}
        />
      </div>
    </ConfigProvider>
  );
}
