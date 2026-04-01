/**
 * AgentDrawer — V1 统一 Agent 抽屉组件
 *
 * 所有关键页面右侧挂载，4 个 Tab:
 *   建议 — 当前上下文推荐动作
 *   解释 — 为什么给出建议
 *   动作 — 可触发按钮
 *   记录 — Agent 工具调用日志
 *
 * 遵循 Admin 终端规范：Ant Design 5.x 组件
 */
import { useState } from 'react';
import { Tabs, Button, Tag, Timeline, Empty, Spin, Space, Typography, Card } from 'antd';
import {
  BulbOutlined,
  QuestionCircleOutlined,
  ThunderboltOutlined,
  FileSearchOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

export interface AgentSuggestion {
  id: string;
  title: string;
  description: string;
  confidence: number;
  agentName: string;
  severity?: 'info' | 'warning' | 'critical';
}

export interface AgentAction {
  id: string;
  label: string;
  type: 'primary' | 'default' | 'danger';
  icon?: React.ReactNode;
  onExecute: () => void;
  requiresConfirmation?: boolean;
}

export interface AgentExplanation {
  id: string;
  question: string;
  answer: string;
  dataPoints?: string[];
}

export interface AgentLogEntry {
  id: string;
  timestamp: string;
  agentName: string;
  toolName: string;
  success: boolean;
  durationMs: number;
  summary: string;
}

export interface AgentDrawerProps {
  /** 当前页面上下文摘要 */
  contextSummary?: string;
  suggestions?: AgentSuggestion[];
  explanations?: AgentExplanation[];
  actions?: AgentAction[];
  logs?: AgentLogEntry[];
  loading?: boolean;
  /** AI 价值统计（本月节省金额，分） */
  monthlySavingsFen?: number;
}

const severityColor = {
  info: '#185FA5',
  warning: '#BA7517',
  critical: '#A32D2D',
};

export function AgentDrawer({
  contextSummary,
  suggestions = [],
  explanations = [],
  actions = [],
  logs = [],
  loading = false,
  monthlySavingsFen,
}: AgentDrawerProps) {
  const [activeTab, setActiveTab] = useState('suggestions');

  const tabItems = [
    {
      key: 'suggestions',
      label: (
        <span><BulbOutlined /> 建议{suggestions.length > 0 && ` (${suggestions.length})`}</span>
      ),
      children: (
        <div style={{ padding: '0 4px' }}>
          {contextSummary && (
            <Card size="small" style={{ marginBottom: 12, background: '#F8F7F5' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>当前上下文</Text>
              <Paragraph style={{ margin: '4px 0 0', fontSize: 13 }}>{contextSummary}</Paragraph>
            </Card>
          )}
          {suggestions.length === 0 ? (
            <Empty description="暂无建议" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            suggestions.map((s) => (
              <Card
                key={s.id}
                size="small"
                style={{
                  marginBottom: 8,
                  borderLeft: `3px solid ${severityColor[s.severity || 'info']}`,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <Tag color={s.severity === 'critical' ? 'red' : s.severity === 'warning' ? 'orange' : 'blue'}>
                    {s.agentName}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    置信度 {(s.confidence * 100).toFixed(0)}%
                  </Text>
                </div>
                <Text strong style={{ fontSize: 13 }}>{s.title}</Text>
                <Paragraph style={{ margin: '4px 0 0', fontSize: 12, color: '#5F5E5A' }}>
                  {s.description}
                </Paragraph>
              </Card>
            ))
          )}
        </div>
      ),
    },
    {
      key: 'explanations',
      label: <span><QuestionCircleOutlined /> 解释</span>,
      children: (
        <div style={{ padding: '0 4px' }}>
          {explanations.length === 0 ? (
            <Empty description="暂无解释" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            explanations.map((e) => (
              <Card key={e.id} size="small" style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>{e.question}</Text>
                <Paragraph style={{ margin: '8px 0 0', fontSize: 12, color: '#5F5E5A' }}>
                  {e.answer}
                </Paragraph>
                {e.dataPoints && e.dataPoints.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 11 }}>数据依据：</Text>
                    {e.dataPoints.map((d, i) => (
                      <Tag key={i} style={{ marginTop: 4, fontSize: 11 }}>{d}</Tag>
                    ))}
                  </div>
                )}
              </Card>
            ))
          )}
        </div>
      ),
    },
    {
      key: 'actions',
      label: <span><ThunderboltOutlined /> 动作</span>,
      children: (
        <div style={{ padding: '0 4px' }}>
          {actions.length === 0 ? (
            <Empty description="暂无可执行动作" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Space direction="vertical" style={{ width: '100%' }}>
              {actions.map((a) => (
                <Button
                  key={a.id}
                  type={a.type === 'primary' ? 'primary' : a.type === 'danger' ? 'primary' : 'default'}
                  danger={a.type === 'danger'}
                  icon={a.icon || <ArrowRightOutlined />}
                  block
                  onClick={a.onExecute}
                >
                  {a.label}
                </Button>
              ))}
            </Space>
          )}
        </div>
      ),
    },
    {
      key: 'logs',
      label: <span><FileSearchOutlined /> 记录</span>,
      children: (
        <div style={{ padding: '0 4px' }}>
          {logs.length === 0 ? (
            <Empty description="暂无调用记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <Timeline
              items={logs.map((l) => ({
                color: l.success ? 'green' : 'red',
                dot: l.success ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />,
                children: (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Text strong style={{ fontSize: 12 }}>{l.agentName}</Text>
                      <Text type="secondary" style={{ fontSize: 10 }}>{l.timestamp}</Text>
                    </div>
                    <Text style={{ fontSize: 12 }}>
                      调用 <Tag style={{ fontSize: 10 }}>{l.toolName}</Tag> {l.durationMs}ms
                    </Text>
                    <div style={{ fontSize: 11, color: '#5F5E5A', marginTop: 2 }}>{l.summary}</div>
                  </div>
                ),
              }))}
            />
          )}
        </div>
      ),
    },
  ];

  return (
    <aside style={{
      width: 340,
      background: '#FFFFFF',
      borderLeft: '1px solid #E8E6E1',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      height: '100%',
    }}>
      <Spin spinning={loading} style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          size="small"
          style={{ flex: 1, overflow: 'hidden' }}
          tabBarStyle={{ padding: '0 12px', margin: 0 }}
        />
      </Spin>

      {/* AI 价值可视化 */}
      {monthlySavingsFen !== undefined && (
        <div style={{
          padding: '10px 16px',
          borderTop: '1px solid #E8E6E1',
          textAlign: 'center',
          background: '#F8F7F5',
        }}>
          <Text type="secondary" style={{ fontSize: 12 }}>本月 AI 为你节省</Text>
          <Text strong style={{ fontSize: 18, color: '#0F6E56', marginLeft: 8 }}>
            ¥{(monthlySavingsFen / 100).toLocaleString()}
          </Text>
        </div>
      )}
    </aside>
  );
}
