/**
 * OpsAgentPage — 智链OS 运维 AI 诊断助手
 *
 * 功能：
 * - 自然语言运维问答（POST /ops/query）
 * - 快捷故障诊断（POST /ops/diagnose）
 * - 修复 Runbook 建议（POST /ops/runbook）
 * - 告警收敛查看（GET /ops/alerts/converge/{store_id}）
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Row, Col, Card, Button, Input, Select, Tag, Spin, Space,
  Typography, Divider, List, Badge, Modal, Form, Collapse,
} from 'antd';
import {
  SendOutlined, ThunderboltOutlined, MedicineBoxOutlined,
  CompressOutlined, ReloadOutlined, RobotOutlined, UserOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import apiClient from '../services/api';
import { handleApiError } from '../utils/message';

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;
const { Option } = Select;
const { Panel } = Collapse;

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  loading?: boolean;
  meta?: {
    type: 'query' | 'diagnose' | 'runbook' | 'converge';
    data?: unknown;
  };
}

interface ConvergeEvent {
  event_id?: string;
  root_cause?: string;
  affected_count?: number;
  severity?: string;
  component?: string;
  description?: string;
}

interface ConvergeResult {
  root_events?: ConvergeEvent[];
  summary?: string;
  total_alerts?: number;
  converged_to?: number;
  window_minutes?: number;
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

const severityColor = (s: string) => {
  const map: Record<string, string> = { critical: 'red', high: 'orange', medium: 'gold', low: 'blue' };
  return map[s] || 'default';
};

let msgCounter = 0;
const nextId = () => `msg-${++msgCounter}-${Date.now()}`;

// ── 主组件 ────────────────────────────────────────────────────────────────────

const OpsAgentPage: React.FC = () => {
  const [storeIds, setStoreIds] = useState<string[]>([]);
  const [selectedStore, setSelectedStore] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [sending, setSending] = useState(false);

  // 告警收敛
  const [convergeResult, setConvergeResult] = useState<ConvergeResult | null>(null);
  const [convergeLoading, setConvergeLoading] = useState(false);
  const [windowMinutes, setWindowMinutes] = useState(5);

  // 故障诊断弹窗
  const [diagnoseVisible, setDiagnoseVisible] = useState(false);
  const [diagnoseForm] = Form.useForm();
  const [diagnoseLoading, setDiagnoseLoading] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);

  // 加载门店列表
  useEffect(() => {
    apiClient.get('/api/v1/stores?limit=50')
      .then(res => {
        const ids: string[] = (res.data?.items || res.data?.stores || []).map(
          (s: { id: string }) => s.id
        );
        if (ids.length > 0) {
          setStoreIds(ids);
          setSelectedStore(ids[0]);
        }
      })
      .catch(() => {
        setStoreIds(['STORE001', 'STORE002', 'STORE003']);
        setSelectedStore('STORE001');
      });
  }, []);

  // 滚动到底部
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 添加消息
  const addMessage = (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    setMessages(prev => [...prev, { ...msg, id: nextId(), timestamp: dayjs().format('HH:mm:ss') }]);
  };

  const updateLastAssistantMsg = (content: string, meta?: ChatMessage['meta']) => {
    setMessages(prev => {
      const copy = [...prev];
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].role === 'assistant' && copy[i].loading) {
          copy[i] = { ...copy[i], content, loading: false, meta };
          break;
        }
      }
      return copy;
    });
  };

  // 自然语言问答
  const handleSend = async () => {
    const text = inputText.trim();
    if (!text || !selectedStore || sending) return;
    setInputText('');
    setSending(true);

    addMessage({ role: 'user', content: text });
    addMessage({ role: 'assistant', content: '', loading: true });

    try {
      const res = await apiClient.post('/api/v1/ops/query', {
        store_id: selectedStore,
        question: text,
      });
      const data = res.data;
      const answer = data?.answer || data?.result || data?.response
        || JSON.stringify(data, null, 2);
      updateLastAssistantMsg(answer, { type: 'query', data });
    } catch (err) {
      handleApiError(err, '问答失败');
      updateLastAssistantMsg('抱歉，查询时发生错误，请稍后再试。');
    } finally {
      setSending(false);
    }
  };

  // 故障诊断
  const handleDiagnose = async (values: { component: string; symptom: string }) => {
    setDiagnoseLoading(true);
    const userMsg = `诊断 [${values.component || '未知组件'}]：${values.symptom}`;
    addMessage({ role: 'user', content: userMsg });
    addMessage({ role: 'assistant', content: '', loading: true });
    setDiagnoseVisible(false);
    diagnoseForm.resetFields();

    try {
      const res = await apiClient.post('/api/v1/ops/diagnose', {
        store_id: selectedStore,
        component: values.component || undefined,
        symptom: values.symptom,
      });
      const data = res.data;
      const lines: string[] = [];
      if (data?.root_cause) lines.push(`**根因：** ${data.root_cause}`);
      if (data?.confidence != null) lines.push(`**置信度：** ${Math.round(data.confidence * 100)}%`);
      if (data?.affected_components?.length) {
        lines.push(`**受影响组件：** ${data.affected_components.join('、')}`);
      }
      if (data?.recommended_actions?.length) {
        lines.push(`\n**建议操作：**`);
        data.recommended_actions.forEach((a: string, i: number) => lines.push(`${i + 1}. ${a}`));
      }
      if (data?.fault_type) lines.push(`\n*故障类型：${data.fault_type}*`);
      updateLastAssistantMsg(lines.join('\n') || JSON.stringify(data, null, 2), { type: 'diagnose', data });
    } catch (err) {
      handleApiError(err, '诊断失败');
      updateLastAssistantMsg('诊断请求失败，请检查门店连接状态。');
    } finally {
      setDiagnoseLoading(false);
    }
  };

  // 告警收敛
  const loadConverge = useCallback(async () => {
    if (!selectedStore) return;
    setConvergeLoading(true);
    try {
      const res = await apiClient.get(
        `/api/v1/ops/alerts/converge/${selectedStore}?window_minutes=${windowMinutes}`
      );
      setConvergeResult(res.data);
    } catch (err) {
      handleApiError(err, '告警收敛失败');
    } finally {
      setConvergeLoading(false);
    }
  }, [selectedStore, windowMinutes]);

  // 门店切换时清空对话
  const handleStoreChange = (val: string) => {
    setSelectedStore(val);
    setMessages([]);
    setConvergeResult(null);
  };

  // ── 渲染消息气泡 ────────────────────────────────────────────────────────────

  const renderMessage = (msg: ChatMessage) => {
    const isUser = msg.role === 'user';
    return (
      <div
        key={msg.id}
        style={{
          display: 'flex',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
          marginBottom: 12,
        }}
      >
        {!isUser && (
          <div style={{ marginRight: 8, marginTop: 4 }}>
            <RobotOutlined style={{ fontSize: 20, color: '#1677ff' }} />
          </div>
        )}
        <div style={{ maxWidth: '75%' }}>
          <div
            style={{
              background: isUser ? '#1677ff' : '#f5f5f5',
              color: isUser ? '#fff' : '#333',
              padding: '8px 14px',
              borderRadius: isUser ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontSize: 14,
              lineHeight: 1.6,
            }}
          >
            {msg.loading ? <Spin size="small" /> : (msg.content || '（无内容）')}
          </div>
          <div style={{ textAlign: isUser ? 'right' : 'left', marginTop: 2 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>{msg.timestamp}</Text>
          </div>
        </div>
        {isUser && (
          <div style={{ marginLeft: 8, marginTop: 4 }}>
            <UserOutlined style={{ fontSize: 20, color: '#aaa' }} />
          </div>
        )}
      </div>
    );
  };

  // ── 渲染告警收敛结果 ────────────────────────────────────────────────────────

  const renderConverge = () => {
    if (!convergeResult) return null;
    const { root_events = [], total_alerts, converged_to, summary } = convergeResult;
    return (
      <div style={{ marginTop: 8 }}>
        <Space style={{ marginBottom: 8 }}>
          <Tag color="blue">原始告警 {total_alerts ?? root_events.length}</Tag>
          <Tag color="green">收敛为 {converged_to ?? root_events.length} 条根因</Tag>
        </Space>
        {summary && <Paragraph style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>{summary}</Paragraph>}
        <List
          size="small"
          dataSource={root_events}
          renderItem={(ev) => (
            <List.Item style={{ padding: '6px 0' }}>
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Space>
                  <Tag color={severityColor(ev.severity || '')}>{(ev.severity || 'unknown').toUpperCase()}</Tag>
                  <Text strong style={{ fontSize: 13 }}>{ev.component || '未知组件'}</Text>
                  {ev.affected_count && ev.affected_count > 1 && (
                    <Tag>收敛 {ev.affected_count} 条</Tag>
                  )}
                </Space>
                <Text style={{ fontSize: 12, color: '#555' }}>{ev.root_cause || ev.description || ''}</Text>
              </Space>
            </List.Item>
          )}
          locale={{ emptyText: '无活跃告警' }}
        />
      </div>
    );
  };

  // ── JSX ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: '16px 24px', height: '100%' }}>
      {/* 顶部工具栏 */}
      <Row align="middle" justify="space-between" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Title level={4} style={{ margin: 0 }}>运维 AI 助手</Title>
            <Select
              value={selectedStore}
              onChange={handleStoreChange}
              style={{ width: 160 }}
              placeholder="选择门店"
            >
              {storeIds.map(id => <Option key={id} value={id}>{id}</Option>)}
            </Select>
          </Space>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<MedicineBoxOutlined />}
              onClick={() => setDiagnoseVisible(true)}
              disabled={!selectedStore}
            >
              故障诊断
            </Button>
            <Button
              icon={<CompressOutlined />}
              onClick={loadConverge}
              loading={convergeLoading}
              disabled={!selectedStore}
            >
              告警收敛
            </Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={16} style={{ height: 'calc(100vh - 140px)' }}>
        {/* 聊天区域 */}
        <Col flex="1" style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Card
            style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
            bodyStyle={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 16 }}
          >
            {/* 消息列表 */}
            <div style={{ flex: 1, overflowY: 'auto', paddingRight: 4 }}>
              {messages.length === 0 && (
                <div style={{ textAlign: 'center', marginTop: 80, color: '#aaa' }}>
                  <RobotOutlined style={{ fontSize: 48, marginBottom: 12 }} />
                  <div>你好！我是运维 AI 助手</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    你可以问我：「3号店今天网络为什么慢」「打印机最近有告警吗」
                  </div>
                  <div style={{ marginTop: 16 }}>
                    <Space>
                      <Button size="small" onClick={() => setInputText('当前门店健康状态如何？')}>健康状态</Button>
                      <Button size="small" onClick={() => setInputText('最近24小时有哪些告警？')}>近期告警</Button>
                      <Button size="small" onClick={() => setInputText('食安合规情况怎么样？')}>食安合规</Button>
                    </Space>
                  </div>
                </div>
              )}
              {messages.map(renderMessage)}
              <div ref={chatEndRef} />
            </div>

            <Divider style={{ margin: '12px 0' }} />

            {/* 输入框 */}
            <div style={{ display: 'flex', gap: 8 }}>
              <TextArea
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend(); } }}
                placeholder="输入问题，按 Enter 发送（Shift+Enter 换行）…"
                autoSize={{ minRows: 1, maxRows: 4 }}
                disabled={!selectedStore || sending}
                style={{ flex: 1 }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleSend}
                loading={sending}
                disabled={!inputText.trim() || !selectedStore}
              >
                发送
              </Button>
            </div>
          </Card>
        </Col>

        {/* 右侧面板：告警收敛 */}
        <Col style={{ width: 320 }}>
          <Card
            title={
              <Space>
                <ThunderboltOutlined />
                <span>告警收敛</span>
              </Space>
            }
            extra={
              <Space>
                <Select
                  value={windowMinutes}
                  onChange={setWindowMinutes}
                  size="small"
                  style={{ width: 80 }}
                >
                  <Option value={5}>5 分钟</Option>
                  <Option value={15}>15 分钟</Option>
                  <Option value={30}>30 分钟</Option>
                  <Option value={60}>1 小时</Option>
                </Select>
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={loadConverge}
                  loading={convergeLoading}
                  disabled={!selectedStore}
                />
              </Space>
            }
            style={{ height: '100%', overflow: 'auto' }}
          >
            {convergeLoading ? (
              <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
            ) : convergeResult ? (
              renderConverge()
            ) : (
              <div style={{ textAlign: 'center', color: '#aaa', padding: 32 }}>
                <CompressOutlined style={{ fontSize: 32, marginBottom: 8 }} />
                <div style={{ fontSize: 12 }}>点击「告警收敛」查看根因聚合分析</div>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* 故障诊断弹窗 */}
      <Modal
        title={
          <Space>
            <MedicineBoxOutlined />
            故障诊断
          </Space>
        }
        open={diagnoseVisible}
        onCancel={() => { setDiagnoseVisible(false); diagnoseForm.resetFields(); }}
        footer={null}
        width={480}
      >
        <Form
          form={diagnoseForm}
          layout="vertical"
          onFinish={handleDiagnose}
        >
          <Form.Item
            label="故障组件"
            name="component"
          >
            <Select placeholder="选择组件（可选）" allowClear>
              <Option value="pos">POS 系统</Option>
              <Option value="router">路由器</Option>
              <Option value="printer">打印机</Option>
              <Option value="kds">KDS 显示屏</Option>
              <Option value="network">网络</Option>
            </Select>
          </Form.Item>
          <Form.Item
            label="故障现象"
            name="symptom"
            rules={[{ required: true, message: '请描述故障现象' }]}
          >
            <TextArea
              rows={3}
              placeholder="例如：POS 无法打印小票，打印机指示灯红色闪烁"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => { setDiagnoseVisible(false); diagnoseForm.resetFields(); }}>取消</Button>
              <Button type="primary" htmlType="submit" loading={diagnoseLoading} icon={<MedicineBoxOutlined />}>
                开始诊断
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default OpsAgentPage;
