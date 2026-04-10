/**
 * AgentSalaryAdvisor — AI薪酬顾问 Agent
 * 域H · Agent 中枢
 *
 * 功能：
 *  1. 薪资优化建议列表（偏高/偏低/调整原因）
 *  2. 对话模式：输入问题展示Agent回答
 *  3. 建议采纳/忽略操作
 *
 * API:
 *  POST /api/v1/agent/salary_advisor/recommend_salary
 *  POST /api/v1/agent/salary_advisor/optimize_raise_plan
 */

import { useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Input,
  List,
  message,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  DollarOutlined,
  SendOutlined,
  CheckOutlined,
  CloseOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import { txFetch } from '../../../api';

const { Title, Text, Paragraph } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface SalaryAdvice {
  id: string;
  employee_id: string;
  emp_name: string;
  current_salary_fen: number;
  suggested_raise_fen: number;
  new_salary_fen: number;
  priority: 'high' | 'medium' | 'low';
  reason: string;
  status: 'pending' | 'adopted' | 'dismissed';
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const priorityMap: Record<string, { text: string; color: string }> = {
  high: { text: '优先', color: 'red' },
  medium: { text: '一般', color: 'gold' },
  low: { text: '低', color: 'default' },
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function AgentSalaryAdvisor() {
  const actionRef = useRef<ActionType>();
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);

  const fmtYuan = (fen: number) => `${(fen / 100).toFixed(0)}`;

  const columns: ProColumns<SalaryAdvice>[] = [
    {
      title: '员工',
      dataIndex: 'emp_name',
      hideInSearch: true,
      width: 100,
      render: (_, r) => (
        <div>
          <Tag color="blue" style={{ marginRight: 4 }}>AI建议</Tag>
          <Text strong>{r.emp_name}</Text>
        </div>
      ),
    },
    {
      title: '当前月薪',
      dataIndex: 'current_salary_fen',
      hideInSearch: true,
      width: 110,
      render: (_, r) => `${fmtYuan(r.current_salary_fen)}元`,
    },
    {
      title: '建议调整',
      dataIndex: 'suggested_raise_fen',
      hideInSearch: true,
      width: 110,
      render: (_, r) => {
        const val = r.suggested_raise_fen;
        const color = val > 0 ? '#0F6E56' : val < 0 ? '#A32D2D' : undefined;
        return (
          <Text style={{ color }}>
            {val > 0 ? '+' : ''}{fmtYuan(val)}元
          </Text>
        );
      },
    },
    {
      title: '调整后',
      dataIndex: 'new_salary_fen',
      hideInSearch: true,
      width: 110,
      render: (_, r) => <Text strong>{fmtYuan(r.new_salary_fen)}元</Text>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      valueType: 'select',
      valueEnum: { high: { text: '优先' }, medium: { text: '一般' }, low: { text: '低' } },
      render: (_, r) => {
        const p = priorityMap[r.priority] || priorityMap.low;
        return <Tag color={p.color}>{p.text}</Tag>;
      },
    },
    {
      title: '原因',
      dataIndex: 'reason',
      hideInSearch: true,
      ellipsis: true,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      render: (_, r) =>
        r.status === 'pending' ? (
          <Space>
            <Button
              type="link"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => handleAction(r.id, 'adopted')}
            >
              采纳
            </Button>
            <Button
              type="link"
              size="small"
              danger
              icon={<CloseOutlined />}
              onClick={() => handleAction(r.id, 'dismissed')}
            >
              忽略
            </Button>
          </Space>
        ) : (
          <Tag color={r.status === 'adopted' ? 'green' : 'default'}>
            {r.status === 'adopted' ? '已采纳' : '已忽略'}
          </Tag>
        ),
    },
  ];

  const handleAction = async (id: string, action: string) => {
    try {
      // TODO: 接入真实采纳/忽略API
      message.success(action === 'adopted' ? '已采纳' : '已忽略');
      actionRef.current?.reload();
    } catch {
      message.error('操作失败');
    }
  };

  const handleChat = async () => {
    if (!chatInput.trim()) return;
    const userMsg: ChatMessage = {
      role: 'user',
      content: chatInput,
      timestamp: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setChatInput('');
    setChatLoading(true);

    try {
      // 调用薪酬顾问Agent
      const resp = await txFetch<{ reasoning: string; data: Record<string, unknown> }>(
        '/api/v1/agent/salary_advisor/recommend_salary',
        {
          method: 'POST',
          body: JSON.stringify({ query: chatInput }),
        },
      );
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: resp.reasoning || JSON.stringify(resp.data),
        timestamp: new Date().toISOString(),
      };
      setChatMessages((prev) => [...prev, assistantMsg]);
    } catch {
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: '抱歉，暂时无法获取分析结果。请稍后重试。',
        timestamp: new Date().toISOString(),
      };
      setChatMessages((prev) => [...prev, errorMsg]);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <DollarOutlined style={{ marginRight: 8, color: '#0F6E56' }} />
        AI薪酬顾问
      </Title>

      <Row gutter={16}>
        {/* 左：建议列表 */}
        <Col xs={24} lg={14}>
          <ProTable<SalaryAdvice>
            actionRef={actionRef}
            columns={columns}
            rowKey="id"
            headerTitle="薪资优化建议"
            request={async (params) => {
              try {
                const resp = await txFetch<{
                  data: { allocated_fen: number; plans: SalaryAdvice[] };
                }>('/api/v1/agent/salary_advisor/optimize_raise_plan', {
                  method: 'POST',
                  body: JSON.stringify({
                    store_id: params.store_id || '',
                    budget_fen: 500000,
                  }),
                });
                const plans = resp.data?.plans || [];
                return {
                  data: plans.map((p, i) => ({ ...p, id: p.employee_id || String(i), status: 'pending' as const })),
                  total: plans.length,
                  success: true,
                };
              } catch {
                return { data: [], total: 0, success: true };
              }
            }}
            search={false}
            pagination={{ defaultPageSize: 10 }}
          />
        </Col>

        {/* 右：对话模式 */}
        <Col xs={24} lg={10}>
          <Card title="薪酬对话" style={{ height: '100%', minHeight: 500 }}>
            <div
              style={{
                height: 360,
                overflowY: 'auto',
                marginBottom: 12,
                padding: '8px 0',
              }}
            >
              {chatMessages.length === 0 && (
                <Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 100 }}>
                  输入问题开始对话，例如："张三的薪资在同岗位中什么水平"
                </Text>
              )}
              <List
                dataSource={chatMessages}
                renderItem={(msg) => (
                  <List.Item
                    style={{
                      justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                      border: 'none',
                      padding: '4px 0',
                    }}
                  >
                    <div
                      style={{
                        maxWidth: '85%',
                        padding: '8px 12px',
                        borderRadius: 8,
                        background: msg.role === 'user' ? '#FF6B35' : '#f5f5f5',
                        color: msg.role === 'user' ? '#fff' : '#2C2C2A',
                      }}
                    >
                      {msg.role === 'assistant' && (
                        <Tag color="blue" style={{ marginBottom: 4 }}>AI建议</Tag>
                      )}
                      <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                    </div>
                  </List.Item>
                )}
              />
              {chatLoading && (
                <div style={{ textAlign: 'center', padding: 12 }}>
                  <Spin size="small" />
                  <Text type="secondary" style={{ marginLeft: 8 }}>分析中...</Text>
                </div>
              )}
            </div>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onPressEnter={handleChat}
                placeholder="输入薪酬相关问题..."
                disabled={chatLoading}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleChat}
                loading={chatLoading}
              />
            </Space.Compact>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
