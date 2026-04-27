/**
 * Copilot 抽屉 — 右侧滑出对话式 AI 助手
 *
 * 设计参考 Anthropic Console 的 AI 助手。
 * 快捷键 ⌘/ 打开/关闭，SSE 流式接收响应。
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ── 颜色常量 ──
const SURFACE = '#0E1E24';
const SURFACE2 = '#132932';
const SURFACE3 = '#1A3540';
const BORDER = '#1A3540';
const BORDER2 = '#23485a';
const TEXT = '#E6EDF1';
const TEXT2 = '#94A8B3';
const TEXT3 = '#647985';
const ORANGE = '#FF6B2C';

// ── 类型定义 ──

export interface CopilotContext {
  workspace?: string;
  object_id?: string;
  tab?: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  streaming?: boolean;
}

interface CopilotDrawerProps {
  open: boolean;
  onClose: () => void;
  context?: CopilotContext;
}

// ── 样式 ──

const DRAWER_WIDTH = 420;

const s = {
  overlay: {
    position: 'fixed' as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'rgba(0,0,0,0.3)',
    zIndex: 8000,
  } as React.CSSProperties,

  drawer: (open: boolean) => ({
    position: 'fixed' as const,
    top: 0,
    right: 0,
    bottom: 0,
    width: DRAWER_WIDTH,
    background: SURFACE,
    borderLeft: `1px solid ${BORDER2}`,
    display: 'flex',
    flexDirection: 'column' as const,
    zIndex: 8001,
    transform: open ? 'translateX(0)' : `translateX(${DRAWER_WIDTH}px)`,
    transition: 'transform 300ms ease-out',
    boxShadow: open ? '-8px 0 32px rgba(0,0,0,0.3)' : 'none',
  }) as React.CSSProperties,

  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 16px',
    borderBottom: `1px solid ${BORDER}`,
    flexShrink: 0,
  } as React.CSSProperties,

  headerTitle: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 15,
    fontWeight: 700,
    color: TEXT,
  } as React.CSSProperties,

  closeBtn: {
    background: 'transparent',
    border: 'none',
    color: TEXT3,
    fontSize: 18,
    cursor: 'pointer',
    padding: '4px 8px',
    borderRadius: 4,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: 'inherit',
  } as React.CSSProperties,

  contextBar: {
    padding: '8px 16px',
    borderBottom: `1px solid ${BORDER}`,
    fontSize: 12,
    color: TEXT3,
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  } as React.CSSProperties,

  contextLabel: {
    color: TEXT2,
    fontWeight: 500,
  } as React.CSSProperties,

  messages: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: 16,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 12,
  } as React.CSSProperties,

  msgBubble: (role: 'user' | 'assistant') => ({
    maxWidth: '88%',
    padding: '10px 14px',
    borderRadius: 10,
    fontSize: 13,
    lineHeight: 1.55,
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
    alignSelf: role === 'user' ? 'flex-end' : 'flex-start',
    background: role === 'user' ? ORANGE + '22' : SURFACE2,
    color: role === 'user' ? TEXT : TEXT,
    border: role === 'user' ? `1px solid ${ORANGE}33` : `1px solid ${BORDER}`,
  }) as React.CSSProperties,

  cursor: {
    display: 'inline-block',
    width: 2,
    height: 14,
    background: ORANGE,
    marginLeft: 1,
    verticalAlign: 'text-bottom',
    animation: 'copilotBlink 0.8s step-end infinite',
  } as React.CSSProperties,

  inputBar: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: 8,
    padding: '12px 16px',
    borderTop: `1px solid ${BORDER}`,
    flexShrink: 0,
  } as React.CSSProperties,

  input: {
    flex: 1,
    background: SURFACE3,
    border: `1px solid ${BORDER2}`,
    borderRadius: 8,
    color: TEXT,
    fontSize: 13,
    padding: '10px 14px',
    outline: 'none',
    fontFamily: 'inherit',
    resize: 'none' as const,
    maxHeight: 120,
    lineHeight: 1.4,
  } as React.CSSProperties,

  sendBtn: (enabled: boolean) => ({
    background: enabled ? ORANGE : SURFACE3,
    color: enabled ? '#fff' : TEXT3,
    border: 'none',
    borderRadius: 8,
    padding: '10px 14px',
    fontSize: 13,
    fontWeight: 600,
    cursor: enabled ? 'pointer' : 'not-allowed',
    flexShrink: 0,
    fontFamily: 'inherit',
    transition: 'background 0.15s',
  }) as React.CSSProperties,
};

// ── 注入关键帧（仅一次）──

let styleInjected = false;
function injectStyles() {
  if (styleInjected) return;
  styleInjected = true;
  const style = document.createElement('style');
  style.textContent = `
    @keyframes copilotBlink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0; }
    }
  `;
  document.head.appendChild(style);
}

// ── ID 生成 ──

let msgCounter = 0;
function nextMsgId(): string {
  return `msg-${Date.now()}-${++msgCounter}`;
}

// ── 上下文格式化 ──

function formatContext(ctx?: CopilotContext): string {
  if (!ctx) return '';
  const parts: string[] = [];
  if (ctx.workspace) parts.push(ctx.workspace);
  if (ctx.object_id) parts.push(ctx.object_id);
  if (ctx.tab) parts.push(ctx.tab);
  return parts.join(' > ');
}

function getPlaceholder(ctx?: CopilotContext): string {
  if (ctx?.object_id) return `问关于 ${ctx.object_id} 的任何问题...`;
  if (ctx?.workspace) return `问关于 ${ctx.workspace} 的任何问题...`;
  return '问关于当前对象的任何问题...';
}

// ── 组件 ──

export function CopilotDrawer({ open, onClose, context }: CopilotDrawerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { injectStyles(); }, []);

  // 初始欢迎消息
  useEffect(() => {
    if (open && messages.length === 0) {
      const contextStr = formatContext(context);
      const greeting = contextStr
        ? `你好！我是屯象 Copilot。\n当前正在查看 ${contextStr}。\n有什么可以帮你的？`
        : '你好！我是屯象 Copilot。有什么可以帮你的？';
      setMessages([
        { id: nextMsgId(), role: 'assistant', content: greeting, timestamp: Date.now() },
      ]);
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // 打开时聚焦
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 350);
  }, [open]);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // SSE 流式发送
  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg: ChatMessage = { id: nextMsgId(), role: 'user', content: text, timestamp: Date.now() };
    const assistantId = nextMsgId();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput('');
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch('/api/v1/hub/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          context: {
            workspace: context?.workspace || null,
            object_id: context?.object_id || null,
            tab: context?.tab || null,
          },
        }),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        // API 不可用时使用 mock 回复
        const mockReply = getMockReply(text, context);
        await streamMockReply(assistantId, mockReply, setMessages);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') break;
            try {
              const parsed = JSON.parse(data) as { text?: string };
              if (parsed.text) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, content: m.content + parsed.text } : m,
                  ),
                );
              }
            } catch {
              // 忽略非 JSON 行
            }
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      // 网络错误时 mock 回复
      const mockReply = getMockReply(text, context);
      await streamMockReply(assistantId, mockReply, setMessages);
    } finally {
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m)),
      );
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, context]);

  // Enter 发送（Shift+Enter 换行）
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    },
    [sendMessage],
  );

  // 关闭时中断流式
  const handleClose = useCallback(() => {
    abortRef.current?.abort();
    onClose();
  }, [onClose]);

  const ctxStr = formatContext(context);
  const canSend = input.trim().length > 0 && !streaming;

  return (
    <>
      {/* 遮罩层 */}
      {open && <div style={s.overlay} onClick={handleClose} />}

      {/* 抽屉 */}
      <div style={s.drawer(open)}>
        {/* 头部 */}
        <div style={s.header}>
          <div style={s.headerTitle}>
            <span>&#x1F916;</span>
            <span>屯象 Copilot</span>
          </div>
          <button style={s.closeBtn} onClick={handleClose} title="关闭 (⌘/)">
            &#x2715;
          </button>
        </div>

        {/* 上下文栏 */}
        {ctxStr && (
          <div style={s.contextBar}>
            <span style={s.contextLabel}>当前上下文:</span>
            <span>{ctxStr}</span>
          </div>
        )}

        {/* 消息列表 */}
        <div style={s.messages}>
          {messages.map((msg) => (
            <div key={msg.id} style={s.msgBubble(msg.role)}>
              {msg.content}
              {msg.streaming && <span style={s.cursor} />}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区 */}
        <div style={s.inputBar}>
          <textarea
            ref={inputRef}
            style={s.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={getPlaceholder(context)}
            rows={1}
            disabled={streaming}
          />
          <button style={s.sendBtn(canSend)} onClick={sendMessage} disabled={!canSend}>
            发送
          </button>
        </div>
      </div>
    </>
  );
}

// ── 全局快捷键 Hook ──

export function useCopilot() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '/') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return { open, setOpen, onClose: () => setOpen(false) };
}

// ── Mock 回复（API 不可用时）──

function getMockReply(userMessage: string, ctx?: CopilotContext): string {
  const objName = ctx?.object_id || '当前对象';
  const workspace = ctx?.workspace || '';

  if (userMessage.includes('异常') || userMessage.includes('问题')) {
    return `根据最近 24 小时的监控数据，${objName} 运行状态正常。\n\n主要指标：\n- CPU 平均使用率: 34%\n- 内存使用: 2.1 GB / 8 GB\n- 网络延迟: 12ms\n- 错误率: 0.02%\n\n没有检测到显著异常。上次告警是 3 天前的一次短暂网络波动（已自动恢复）。`;
  }

  if (userMessage.includes('成本') || userMessage.includes('费用')) {
    return `${objName} 本月累计成本 ¥2,340，较上月同期下降 8%。\n\n成本构成：\n- 计算资源: ¥1,200 (51%)\n- 存储: ¥680 (29%)\n- 网络流量: ¥460 (20%)\n\n优化建议：可考虑在非高峰时段降低计算资源配置，预计可节省 ¥300/月。`;
  }

  if (workspace === 'edges' || workspace === 'Edges') {
    return `${objName} 是一个边缘节点（Mac mini M4），当前在线且运行正常。\n\n- 最近同步: 2 分钟前\n- 本地 PG 数据量: 1.2 GB\n- Core ML 推理延迟: 8ms\n- Tailscale 连接: 稳定\n\n需要我帮你做什么操作吗？`;
  }

  return `我理解你关于 ${objName} 的问题。让我为你分析一下：\n\n基于当前的监控数据和历史记录，${objName} 的各项指标都在正常范围内。\n\n如果你需要更详细的信息，可以切换到 Timeline 或 Logs 标签页查看完整的历史记录。\n\n还有其他问题吗？`;
}

async function streamMockReply(
  msgId: string,
  text: string,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
): Promise<void> {
  // 模拟逐字输出
  for (let i = 0; i < text.length; i++) {
    await new Promise((r) => setTimeout(r, 15 + Math.random() * 10));
    const char = text[i];
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, content: m.content + char } : m)),
    );
  }
}
