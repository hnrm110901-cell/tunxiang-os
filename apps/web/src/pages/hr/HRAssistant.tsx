/**
 * HR 数字人助手 — 员工自助自然语言查询 HR 数据
 * 路由：/hr/assistant
 *
 * 功能：
 *  - ChatGPT 风格聊天 + 首屏推荐问题
 *  - 工具调用结果以卡片展示
 *  - 写入类操作（请假/换班/报名）弹 Modal 二次确认
 *  - 浏览器原生 SpeechRecognition（失败回退到文字输入）
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { apiClient, handleApiError } from '../../services/api';
import styles from './HRAssistant.module.css';

interface ToolInvocation {
  name: string;
  ok?: boolean;
  args?: Record<string, any>;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolInvocations?: ToolInvocation[];
}

interface ChatResp {
  conversation_id: string;
  reply: string;
  tool_invocations: ToolInvocation[];
  suggested_actions: string[];
  pending_confirm: { tool: string; args: Record<string, any>; prompt: string } | null;
  ok: boolean;
}

interface Conversation {
  id: string;
  last_active_at: string;
  status: string;
  message_count: number;
  summary?: string | null;
}

const DEFAULT_SUGGESTS = [
  '我这个月工资多少？',
  '我的考勤有没有异常？',
  '我下周排几个班？',
  '我的请假余额还剩多少？',
  '我的健康证什么时候过期？',
  '我的培训进度？',
  '我能参加哪些培训？',
  '帮我申请明天请假',
];

export default function HRAssistant() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [sending, setSending] = useState(false);
  const [suggests, setSuggests] = useState<string[]>(DEFAULT_SUGGESTS);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<ChatResp['pending_confirm']>(null);
  const chatRef = useRef<HTMLDivElement>(null);

  const isEmptyChat = useMemo(() => messages.length === 0, [messages]);

  // 首次加载：推荐问题 + 历史对话
  useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get<{ questions: string[] }>(
          '/api/v1/hr/assistant/suggested-questions',
        );
        if (r?.questions?.length) setSuggests(r.questions);
      } catch (err) {
        // 静默失败，用默认推荐
      }
      try {
        const list = await apiClient.get<Conversation[]>(
          '/api/v1/hr/assistant/conversations/my?limit=20',
        );
        setConversations(list || []);
      } catch (err) {
        // 静默
      }
    })();
  }, []);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  async function sendMessage(text: string, confirmToken?: ChatResp['pending_confirm']) {
    const content = (text || '').trim();
    if (!content && !confirmToken) return;
    setSending(true);
    // 乐观渲染用户气泡
    if (content) setMessages((prev) => [...prev, { role: 'user', content }]);
    try {
      const resp = await apiClient.post<ChatResp>('/api/v1/hr/assistant/chat', {
        conversation_id: conversationId,
        message: content || '（确认执行）',
        confirm_token: confirmToken ? { tool: confirmToken.tool, args: confirmToken.args } : null,
      });
      if (!conversationId) setConversationId(resp.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.reply,
          toolInvocations: resp.tool_invocations,
        },
      ]);
      if (resp.pending_confirm) {
        setPendingConfirm(resp.pending_confirm);
      } else {
        setPendingConfirm(null);
      }
    } catch (err) {
      const msg = handleApiError(err);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `请求失败：${msg}` },
      ]);
    } finally {
      setSending(false);
      setInputText('');
    }
  }

  // 语音输入（浏览器原生 SpeechRecognition，失败提示）
  function startVoiceInput() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      alert('当前浏览器不支持语音输入，请用文字输入');
      return;
    }
    try {
      const rec = new SR();
      rec.lang = 'zh-CN';
      rec.interimResults = false;
      rec.onresult = (e: any) => {
        const text = e.results?.[0]?.[0]?.transcript;
        if (text) setInputText(text);
      };
      rec.onerror = () => alert('语音识别失败，请用文字输入');
      rec.start();
    } catch {
      alert('语音识别启动失败，请用文字输入');
    }
  }

  function confirmPending() {
    if (!pendingConfirm) return;
    sendMessage('', pendingConfirm);
  }

  function cancelPending() {
    setPendingConfirm(null);
    setMessages((prev) => [...prev, { role: 'assistant', content: '已取消该操作。' }]);
  }

  async function loadConversation(id: string) {
    setConversationId(id);
    setMessages([]);
    // 简化：仅切会话 id，历史消息由后续 API 懒加载（此处先留空）
  }

  return (
    <div className={styles.shell}>
      {/* 左侧历史对话 */}
      <aside className={styles.sidebar}>
        <div className={styles.sidebarTitle}>历史对话</div>
        <div
          className={`${styles.convItem} ${!conversationId ? styles.convItemActive : ''}`}
          onClick={() => {
            setConversationId(null);
            setMessages([]);
          }}
        >
          + 新对话
        </div>
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`${styles.convItem} ${
              c.id === conversationId ? styles.convItemActive : ''
            }`}
            onClick={() => loadConversation(c.id)}
          >
            {c.summary || `对话 · ${c.message_count} 条`}
          </div>
        ))}
      </aside>

      {/* 主聊天区 */}
      <main className={styles.main}>
        <div ref={chatRef} className={styles.chatArea}>
          {isEmptyChat ? (
            <div className={styles.suggestions}>
              {suggests.map((q) => (
                <div
                  key={q}
                  className={styles.suggestCard}
                  onClick={() => sendMessage(q)}
                >
                  {q}
                </div>
              ))}
            </div>
          ) : (
            messages.map((m, i) => (
              <div
                key={i}
                className={`${styles.row} ${m.role === 'user' ? styles.rowRight : ''}`}
              >
                <div>
                  <div
                    className={`${styles.bubble} ${
                      m.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant
                    }`}
                  >
                    {m.content}
                  </div>
                  {m.toolInvocations?.map((t, idx) => (
                    <div key={idx} className={styles.toolCard}>
                      🔧 调用工具：{t.name}
                      {t.ok === false ? ' ✗ 失败' : ' ✓'}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        <div className={styles.inputBar}>
          <button
            className={styles.voiceBtn}
            title="语音输入"
            onClick={startVoiceInput}
            disabled={sending}
          >
            🎙️
          </button>
          <input
            value={inputText}
            placeholder="有什么想问的？如：我这个月工资多少？"
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(inputText);
              }
            }}
            disabled={sending}
          />
          <button
            className={styles.btn}
            onClick={() => sendMessage(inputText)}
            disabled={sending || !inputText.trim()}
          >
            发送
          </button>
        </div>
      </main>

      {/* 二次确认 Modal */}
      {pendingConfirm && (
        <div className={styles.modalMask}>
          <div className={styles.modal}>
            <div className={styles.modalTitle}>请确认操作</div>
            <div className={styles.modalBody}>{pendingConfirm.prompt}</div>
            <div className={styles.modalFoot}>
              <button className={styles.btnGhost} onClick={cancelPending}>
                取消
              </button>
              <button className={styles.btn} onClick={confirmPending}>
                确认
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
