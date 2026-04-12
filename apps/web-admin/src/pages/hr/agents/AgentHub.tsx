/**
 * AgentHub — Agent 总览
 * 域H · Agent 中枢
 *
 * 功能：
 *  1. 6个Agent卡片（合规预警/薪酬顾问/排班优化/缺勤补位/离职风险/成长教练）
 *  2. 每张卡片：Agent名称+描述+状态+最近执行时间+建议数量Badge
 *  3. 点击卡片跳转到具体Agent页面
 *  4. 底部：最近Agent活动Timeline
 *
 * API:
 *  GET /api/v1/hr/dashboard  (agent_summaries)
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Card,
  Col,
  Row,
  Spin,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import {
  AlertOutlined,
  DollarOutlined,
  CalendarOutlined,
  UserSwitchOutlined,
  WarningOutlined,
  RocketOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Title, Text, Paragraph } = Typography;

// ─── Agent 定义 ──────────────────────────────────────────────────────────────

interface AgentDef {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  route: string;
  status: 'active' | 'inactive';
}

const AGENTS: AgentDef[] = [
  {
    id: 'compliance_alert',
    name: '合规预警',
    description: '证件到期、低绩效、考勤异常自动扫描与预警推送',
    icon: <AlertOutlined style={{ fontSize: 28, color: '#A32D2D' }} />,
    route: '/hr/agents/compliance-alert',
    status: 'active',
  },
  {
    id: 'salary_advisor',
    name: 'AI薪酬顾问',
    description: '基于岗位/区域/工龄/绩效的薪酬建议与调薪优化',
    icon: <DollarOutlined style={{ fontSize: 28, color: '#0F6E56' }} />,
    route: '/hr/agents/salary-advisor',
    status: 'active',
  },
  {
    id: 'workforce_planner',
    name: '排班优化',
    description: '基于历史客流分析排班效率，生成下周优化建议',
    icon: <CalendarOutlined style={{ fontSize: 28, color: '#185FA5' }} />,
    route: '/hr/agents/workforce-planner',
    status: 'active',
  },
  {
    id: 'attendance_recovery',
    name: '缺勤补位',
    description: '检测缺勤自动创建缺口，匹配候选人推荐补位',
    icon: <UserSwitchOutlined style={{ fontSize: 28, color: '#BA7517' }} />,
    route: '/hr/agents/attendance-recovery',
    status: 'active',
  },
  {
    id: 'turnover_risk',
    name: '离职风险',
    description: '多维信号扫描计算员工离职风险评分与干预建议',
    icon: <WarningOutlined style={{ fontSize: 28, color: '#A32D2D' }} />,
    route: '/hr/agents/turnover-risk',
    status: 'active',
  },
  {
    id: 'growth_coach',
    name: '成长教练',
    description: '技能差距分析、培训推荐、个性化学习路径生成',
    icon: <RocketOutlined style={{ fontSize: 28, color: '#FF6B35' }} />,
    route: '/hr/agents/growth-coach',
    status: 'active',
  },
];

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface AgentSummary {
  agent_id: string;
  decision_type: string;
  reasoning: string;
  confidence: number;
  created_at: string;
}

interface DashboardResp {
  agent_summaries: AgentSummary[];
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function AgentHub() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [summaries, setSummaries] = useState<AgentSummary[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const data = await txFetchData<DashboardResp>('/api/v1/hr/dashboard/');
      setSummaries(data.agent_summaries || []);
    } catch {
      // 降级：不阻塞页面
      setSummaries([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // 统计每个Agent的建议数量
  const countByAgent: Record<string, number> = {};
  for (const s of summaries) {
    countByAgent[s.agent_id] = (countByAgent[s.agent_id] || 0) + 1;
  }

  // 最近执行时间
  const lastRunByAgent: Record<string, string> = {};
  for (const s of summaries) {
    if (!lastRunByAgent[s.agent_id]) {
      lastRunByAgent[s.agent_id] = s.created_at;
    }
  }

  const agentNameMap: Record<string, string> = {};
  for (const a of AGENTS) {
    agentNameMap[a.id] = a.name;
  }

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <RobotOutlined style={{ marginRight: 8 }} />
        Agent 中枢
      </Title>
      <Paragraph type="secondary">
        6个AI Agent协同工作，自动识别人力风险并生成可执行建议
      </Paragraph>

      <Spin spinning={loading}>
        {/* Agent 卡片网格 */}
        <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
          {AGENTS.map((agent) => (
            <Col xs={24} sm={12} lg={8} key={agent.id}>
              <Badge count={countByAgent[agent.id] || 0} overflowCount={99}>
                <Card
                  hoverable
                  onClick={() => navigate(agent.route)}
                  style={{ height: '100%', minHeight: 160 }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                    <div style={{ flexShrink: 0, marginTop: 2 }}>{agent.icon}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <Text strong style={{ fontSize: 16 }}>{agent.name}</Text>
                        <Tag color={agent.status === 'active' ? 'green' : 'default'}>
                          {agent.status === 'active' ? '运行中' : '未启用'}
                        </Tag>
                      </div>
                      <Paragraph
                        type="secondary"
                        style={{ marginBottom: 8, fontSize: 13 }}
                        ellipsis={{ rows: 2 }}
                      >
                        {agent.description}
                      </Paragraph>
                      {lastRunByAgent[agent.id] && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          最近执行: {new Date(lastRunByAgent[agent.id]).toLocaleString('zh-CN')}
                        </Text>
                      )}
                    </div>
                  </div>
                </Card>
              </Badge>
            </Col>
          ))}
        </Row>

        {/* 最近活动 Timeline */}
        <Card title="最近 Agent 活动" style={{ marginTop: 16 }}>
          {summaries.length === 0 ? (
            <Text type="secondary">暂无 Agent 活动记录</Text>
          ) : (
            <Timeline
              items={summaries.slice(0, 20).map((s) => ({
                color: s.confidence >= 0.8 ? 'green' : s.confidence >= 0.5 ? 'blue' : 'gray',
                children: (
                  <div>
                    <div>
                      <Tag color="blue">AI建议</Tag>
                      <Text strong>{agentNameMap[s.agent_id] || s.agent_id}</Text>
                      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                        {s.decision_type}
                      </Text>
                    </div>
                    <Paragraph
                      style={{ margin: '4px 0', fontSize: 13 }}
                      ellipsis={{ rows: 2 }}
                    >
                      {s.reasoning}
                    </Paragraph>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {new Date(s.created_at).toLocaleString('zh-CN')}
                      {' '}
                      | 置信度 {(s.confidence * 100).toFixed(0)}%
                    </Text>
                  </div>
                ),
              }))}
            />
          )}
        </Card>
      </Spin>
    </div>
  );
}
