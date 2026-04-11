/**
 * NLQChatPanel — 精简可嵌入 AI 自然语言问数聊天面板
 * 供其他页面内嵌使用
 */
import { useState, useRef } from 'react';
import { Input, Button, Tag, Spin } from 'antd';
import { SendOutlined } from '@ant-design/icons';

const { TextArea } = Input;

export interface NLQChatPanelProps {
  placeholder?: string;
  height?: number;
  onQuery?: (query: string) => void;
}

interface ChatMsg {
  role: 'user' | 'ai';
  content: string;
}

const QUICK_QUESTIONS = [
  '今日营业额',
  '本周热销菜品',
  '会员复购率',
  '毛利率排名',
  '翻台率趋势',
];

const NLQChatPanel = ({ placeholder = '输入问题，如：今天各门店营业额…', height = 400, onQuery }: NLQChatPanelProps) => {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [inputVal, setInputVal] = useState('');
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const handleSend = async () => {
    const q = inputVal.trim();
    if (!q || loading) return;
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    setInputVal('');
    setLoading(true);
    onQuery?.(q);

    // mock AI 响应延迟
    await new Promise((r) => setTimeout(r, 1200));
    setMessages((prev) => [
      ...prev,
      { role: 'ai', content: `AI 正在分析「${q}」— 模拟响应（待接入 tx-brain API）` },
    ]);
    setLoading(false);
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const handleQuickQuestion = (q: string) => {
    setInputVal(q);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height }}>
      {/* 快捷问题 Tag（水平滚动） */}
      <div style={{
        overflowX: 'auto', whiteSpace: 'nowrap', padding: '6px 0',
        marginBottom: 8, flexShrink: 0,
      }}>
        {QUICK_QUESTIONS.map((q) => (
          <Tag
            key={q}
            onClick={() => handleQuickQuestion(q)}
            style={{ cursor: 'pointer', marginRight: 6, display: 'inline-block' }}
            color="blue"
          >
            {q}
          </Tag>
        ))}
      </div>

      {/* 聊天历史区域 */}
      <div style={{
        flexGrow: 1, overflowY: 'auto', display: 'flex',
        flexDirection: 'column', gap: 8, padding: '4px 0',
      }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#aaa', fontSize: 12, paddingTop: 24 }}>
            请输入问题开始对话
          </div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              maxWidth: '90%',
              background: msg.role === 'user' ? '#FF6B35' : '#f8f7f5',
              color: msg.role === 'user' ? '#fff' : '#2C2C2A',
              padding: '8px 12px',
              borderRadius: msg.role === 'user' ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
              fontSize: 13,
            }}>
              {msg.content}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#888', fontSize: 12 }}>
            <Spin size="small" />
            AI 正在分析...
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* 底部 Input + 发送按钮 */}
      <div style={{ display: 'flex', gap: 8, marginTop: 8, flexShrink: 0 }}>
        <TextArea
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          placeholder={placeholder}
          autoSize={{ minRows: 1, maxRows: 3 }}
          style={{ flex: 1 }}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); void handleSend(); } }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={() => void handleSend()}
          loading={loading}
          style={{ background: '#FF6B35', borderColor: '#FF6B35', height: 36 }}
        />
      </div>
    </div>
  );
};

export default NLQChatPanel;
