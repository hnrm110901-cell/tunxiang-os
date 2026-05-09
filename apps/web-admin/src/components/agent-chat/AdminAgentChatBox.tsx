/**
 * AdminAgentChatBox — Admin AI 对话面板（落到 AgentConsole.chat tab 内）
 *
 * 职责：
 *   - 输入框 + 发送（Enter 触发，Shift+Enter 换行预留）
 *   - 流式 token 累积（typewriter 效果）
 *   - A2UI Surface 内联渲染（A2UIRenderer）
 *   - 历史会话列表（user / assistant 气泡）
 *
 * 数据源：
 *   - 当前：mockNlqStream（mock SSE 生成器）
 *   - S4-02 #289 接通后：替换为真实 SSE 客户端，StreamEvent 协议契约不变
 *
 * 历史持久化：
 *   - 当前：组件内 useState（刷新后丢失）
 *   - 后续 follow-up：IndexedDB 7 天保留
 *
 * Sprint 4 / S4-01 / Tier 2
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { A2UIRenderer } from '../a2ui';
import type { A2UIDeclaration } from '../a2ui/types';
import { mockNlqStream } from './mockSSE';
import { createPin } from '../../api/pinnedDashboard';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  surface?: A2UIDeclaration;
  /** 用户问题（assistant 消息附带，Pin 时作为 source_natural_query 持久化）*/
  sourceQuery?: string;
}

export function AdminAgentChatBox() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const [streamingSurface, setStreamingSurface] = useState<A2UIDeclaration | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingText]);

  // 挂载时自动 focus
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || isStreaming) return;
    setInput('');
    setError(null);
    setStreamingText('');
    setStreamingSurface(null);
    setIsStreaming(true);

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-u`,
      role: 'user',
      text: question,
    };
    setMessages((prev) => [...prev, userMsg]);

    let accumulated = '';
    let surface: A2UIDeclaration | undefined;
    try {
      for await (const ev of mockNlqStream(question)) {
        if (ev.type === 'token') {
          accumulated += ev.text;
          setStreamingText(accumulated);
        } else if (ev.type === 'surface') {
          surface = ev.declaration;
          setStreamingSurface(ev.declaration);
        } else if (ev.type === 'error') {
          setError(ev.message);
          break;
        } else if (ev.type === 'done') {
          break;
        }
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-${Date.now()}-a`,
          role: 'assistant',
          text: accumulated,
          surface,
          sourceQuery: question,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败');
    } finally {
      setStreamingText('');
      setStreamingSurface(null);
      setIsStreaming(false);
    }
  }, [input, isStreaming]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  const isEmpty = messages.length === 0 && !isStreaming;
  const sendDisabled = isStreaming || !input.trim();

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        padding: 12,
        overflow: 'hidden',
      }}
    >
      {/* 历史消息 + 流式临时块 */}
      <div
        ref={scrollRef}
        style={{ flex: 1, overflow: 'auto', marginBottom: 8, paddingRight: 4 }}
      >
        {isEmpty && (
          <div
            style={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-4)',
            }}
          >
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>💬</div>
              <div style={{ fontSize: 13 }}>用自然语言查询经营数据</div>
              <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 4 }}>
                试试："今天营收多少？" "鲈鱼损耗排名？"
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 12 }}>
                按 ⌘J / Ctrl+J 在任意页面唤起
              </div>
            </div>
          </div>
        )}

        {messages.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}

        {/* 流式中：临时 assistant 块 */}
        {isStreaming && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: 'var(--text-4)', marginBottom: 4 }}>
              AI 助手
            </div>
            <div
              style={{
                fontSize: 12,
                color: 'var(--text-2)',
                whiteSpace: 'pre-wrap',
                padding: '8px 12px',
                borderRadius: 8,
                background: 'var(--bg-0)',
                border: '1px solid var(--bg-2)',
              }}
            >
              {streamingText}
              <span style={{ opacity: 0.5 }}>▍</span>
            </div>
            {streamingSurface && (
              <div style={{ marginTop: 8 }}>
                <A2UIRenderer declaration={streamingSurface} />
              </div>
            )}
          </div>
        )}

        {error && (
          <div
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              fontSize: 12,
              color: 'var(--red)',
              background: 'var(--bg-0)',
              border: '1px solid var(--red)',
              marginBottom: 12,
            }}
          >
            ⚠️ {error}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder={isStreaming ? '正在思考…' : '输入问题，回车发送'}
          style={{
            flex: 1,
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid var(--bg-2)',
            background: 'var(--bg-0)',
            color: 'var(--text-2)',
            fontSize: 13,
            outline: 'none',
          }}
        />
        <button
          onClick={() => void handleSend()}
          disabled={sendDisabled}
          style={{
            padding: '10px 14px',
            borderRadius: 8,
            border: 'none',
            cursor: sendDisabled ? 'not-allowed' : 'pointer',
            background: 'var(--brand)',
            color: 'var(--text-1)',
            fontSize: 13,
            fontWeight: 600,
            opacity: sendDisabled ? 0.5 : 1,
          }}
        >
          发送
        </button>
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  const canPin = !isUser && Boolean(message.surface);
  const [pinState, setPinState] = useState<'idle' | 'pinning' | 'pinned' | 'error'>(
    'idle',
  );

  const handlePin = useCallback(async () => {
    if (!message.surface || pinState !== 'idle') return;
    setPinState('pinning');
    try {
      await createPin(
        message.surface as unknown as Record<string, unknown>,
        message.sourceQuery,
      );
      setPinState('pinned');
    } catch {
      setPinState('error');
    }
  }, [message.surface, message.sourceQuery, pinState]);

  return (
    <div
      style={{
        marginBottom: 12,
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
      }}
    >
      <div style={{ fontSize: 10, color: 'var(--text-4)', marginBottom: 4 }}>
        {isUser ? '我' : 'AI 助手'}
      </div>
      <div
        style={{
          maxWidth: '90%',
          padding: '8px 12px',
          borderRadius: 8,
          fontSize: 12,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          background: isUser ? 'var(--brand)' : 'var(--bg-0)',
          color: isUser ? 'var(--text-1)' : 'var(--text-2)',
          border: isUser ? 'none' : '1px solid var(--bg-2)',
        }}
      >
        {message.text}
      </div>
      {message.surface && (
        <div style={{ marginTop: 8, alignSelf: 'stretch' }}>
          <A2UIRenderer declaration={message.surface} />
        </div>
      )}
      {canPin && (
        <button
          onClick={() => void handlePin()}
          disabled={pinState !== 'idle'}
          style={{
            marginTop: 6,
            alignSelf: 'flex-end',
            background: 'transparent',
            border: '1px solid var(--bg-2)',
            color:
              pinState === 'pinned'
                ? 'var(--green)'
                : pinState === 'error'
                  ? 'var(--red)'
                  : 'var(--text-3)',
            fontSize: 11,
            padding: '3px 8px',
            borderRadius: 6,
            cursor: pinState === 'idle' ? 'pointer' : 'default',
          }}
          title="保存到驾驶舱"
        >
          {pinState === 'idle' && '📌 Pin 到驾驶舱'}
          {pinState === 'pinning' && '保存中…'}
          {pinState === 'pinned' && '✓ 已 Pin'}
          {pinState === 'error' && '⚠️ Pin 失败，重试'}
        </button>
      )}
    </div>
  );
}
