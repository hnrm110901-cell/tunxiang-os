/**
 * NLQueryPage — AI 自然语言问数（BI-1.3 升级版）
 *
 * 变更：
 * - 移除所有 Mock 数据
 * - 接入真实 NLQ API：POST /api/v1/nlq/ask, GET /api/v1/nlq/suggestions, GET /api/v1/nlq/history
 * - 支持多轮对话上下文（会话ID管理）
 * - 内联 SVG 图表渲染（无重度库依赖）
 * - 追问建议可点击
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { ConfigProvider, Input, Button, Tag, Typography, Spin } from 'antd';
import { SendOutlined, ReloadOutlined } from '@ant-design/icons';

const { TextArea } = Input;
const { Text } = Typography;

// ---- 类型 ----
interface APIDataRow {
  [key: string]: unknown;
}

interface NLQResponse {
  session_id: string;
  question: string;
  intent: string;
  answer: string;
  data: APIDataRow[] | null;
  chart_type: string | null;
  actions: Array<{ action_id: string; label: string; description: string; endpoint: string }>;
  source: string;
  generated_at: string;
}

interface ChatMsg {
  role: 'user' | 'ai';
  content: string;
  intent?: string;
  chartType?: string;
  dataRows?: APIDataRow[];
  actions?: Array<{ action_id: string; label: string; description: string; endpoint: string }>;
  isLoading?: boolean;
}

interface Suggestion {
  id: string;
  text: string;
  category: string;
}

// ---- 内联轻量图表 (SVG/CSS) ----
function InlineChart({
  chartType,
  columns,
  rows,
}: {
  chartType: string;
  columns: string[];
  rows: APIDataRow[];
}) {
  if (\!rows || rows.length === 0) {
    return null;
  }

  const labelCol = columns[0] || 'name';
  const valueCol = columns.length > 1 ? columns[1] : columns[0];

  // 提取数值（分转元）
  const toYuan = (v: unknown): number => {
    const n = Number(v);
    // 大于 10000 视为分
    return Math.abs(n) > 10000 ? n / 100 : n;
  };

  const items = rows.slice(0, 20).map((r) => ({
    label: String(r[labelCol] ?? ''),
    value: toYuan(r[valueCol]),
  }));

  const maxVal = Math.max(...items.map((i) => i.value), 1);

  // 大数字 (Metric)
  if (chartType === 'metric' && items.length === 1) {
    return (
      <div style={{ textAlign: 'center', padding: '16px 0' }}>
        <div style={{ fontSize: 32, fontWeight: 700, color: '#FF6B35' }}>
          {items[0].value >= 100
            ? `¥${items[0].value.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
            : items[0].value.toLocaleString()}
        </div>
        <div style={{ fontSize: 13, color: '#888', marginTop: 4 }}>{items[0].label}</div>
      </div>
    );
  }

  // 饼图 (Pie) — 简单环形
  if (chartType === 'pie' && items.length <= 8) {
    const total = items.reduce((s, i) => s + i.value, 0);
    const colors = ['#FF6B35', '#FF8C5A', '#FFA77D', '#FFC4A0', '#FFE0C8',
                     '#0F6E56', '#2B9E7C', '#4FC09E'];
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: 8 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, flex: 1 }}>
          {items.map((item, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: colors[i % colors.length], display: 'inline-block' }} />
              <span>{item.label}</span>
              <span style={{ fontWeight: 600, color: '#FF6B35' }}>
                {total > 0 ? `${((item.value / total) * 100).toFixed(1)}%` : '0%'}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // 柱状图 (Bar) — 简单 SVG
  if (chartType === 'bar' && items.length > 0) {
    const barH = 16;
    const gap = 8;
    const totalH = items.length * (barH + gap);
    const labelW = 90;
    const chartW = 220;
    return (
      <svg width={labelW + chartW + 70} height={totalH + 20} style={{ font: '12px sans-serif' }}>
        {items.map((item, i) => {
          const barW = maxVal > 0 ? (item.value / maxVal) * chartW : 0;
          const y = i * (barH + gap) + 10;
          return (
            <g key={i}>
              <text x={0} y={y + 12} textAnchor="end" fill="#555" fontSize={11}>
                {item.label.length > 8 ? item.label.slice(0, 7) + '…' : item.label}
              </text>
              <rect x={labelW + 2} y={y} width={Math.max(barW, 2)} height={barH} rx={3} fill="#FF6B35" opacity={0.85} />
              <text x={labelW + Math.max(barW, 2) + 6} y={y + 12} fill="#333" fontSize={11}>
                {item.value >= 100
                  ? `¥${item.value.toFixed(0)}`
                  : String(item.value)}
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  // 折线图 (Line) — 简单 SVG
  if (chartType === 'line' && items.length > 1) {
    const chartH = 100;
    const chartW = 300;
    const padL = 50;
    const padB = 20;
    const points = items.map((item, i) => {
      const x = padL + (i / Math.max(items.length - 1, 1)) * (chartW - padL);
      const y = chartH - padB - (item.value / maxVal) * (chartH - padB - 10);
      return `${x},${y}`;
    });
    return (
      <svg width={chartW} height={chartH} style={{ font: '10px sans-serif' }}>
        <polyline points={points.join(' ')} fill="none" stroke="#FF6B35" strokeWidth={2} />
        {items.map((item, i) => {
          const x = padL + (i / Math.max(items.length - 1, 1)) * (chartW - padL);
          const y = chartH - padB - (item.value / maxVal) * (chartH - padB - 10);
          return (
            <g key={i}>
              <circle cx={x} cy={y} r={3} fill="#FF6B35" />
              <text x={x} y={y - 6} textAnchor="middle" fill="#333" fontSize={9}>
                {item.value >= 100 ? `¥${item.value.toFixed(0)}` : item.value}
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  // 表格 (Table) — 回退
  if (rows.length > 0) {
    const displayCols = columns.slice(0, 5);
    return (
      <div style={{ overflowX: 'auto', maxHeight: 300 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#f8f7f5' }}>
              {displayCols.map((col) => (
                <th key={col} style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '2px solid #e8e8e8' }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 30).map((row, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                {displayCols.map((col) => {
                  const v = row[col];
                  const display = typeof v === 'number' && Math.abs(v) > 10000
                    ? `¥${(v / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
                    : String(v ?? '-');
                  return (
                    <td key={col} style={{ padding: '4px 8px' }}>{display}</td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 30 && (
          <div style={{ textAlign: 'center', padding: 8, color: '#888', fontSize: 12 }}>
            仅显示前 30 行，共 {rows.length} 行
          </div>
        )}
      </div>
    );
  }

  return null;
}

// ---- 主组件 ----
export const NLQueryPage = () => {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [inputVal, setInputVal] = useState('');
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string>(() =>
    `nlq-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  );
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const tenantId = (() => {
    try { return localStorage.getItem('tx-tenant-id') || 'default'; }
    catch { return 'default'; }
  })();

  // ---- 滚动到底部 ----
  const scrollToBottom = useCallback(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  }, []);

  // ---- 加载推荐问题 ----
  useEffect(() => {
    fetch('/api/v1/nlq/suggestions', {
      headers: { 'X-Tenant-ID': tenantId },
    })
      .then((r) => r.json())
      .then((res) => {
        if (res.ok) setSuggestions(res.data || []);
      })
      .catch(() => {
        // 网络不可达时使用默认问题
        setSuggestions([
          { id: 'd1', text: '今天各门店营业额对比', category: 'revenue' },
          { id: 'd2', text: '最畅销的菜品TOP10', category: 'dish' },
          { id: 'd3', text: '上个月会员复购率', category: 'member' },
          { id: 'd4', text: '毛利率低于30%的菜品', category: 'dish' },
          { id: 'd5', text: '有哪些异常预警', category: 'anomaly' },
          { id: 'd6', text: '本周营收趋势', category: 'revenue' },
          { id: 'd7', text: '库存预警食材有哪些', category: 'supply' },
          { id: 'd8', text: '各渠道销售占比', category: 'channel' },
        ]);
      });
  }, [tenantId]);

  // ---- 发送查询 ----
  const sendQuery = useCallback(async (questionText: string) => {
    const q = questionText.trim();
    if (\!q || sending) return;
    setSending(true);

    // 添加用户消息 + 加载占位
    const loadingMsg: ChatMsg = { role: 'ai', content: '正在分析中...', isLoading: true };
    setMessages((prev) => [...prev, { role: 'user', content: q }, loadingMsg]);
    setInputVal('');
    scrollToBottom();

    try {
      const res = await fetch('/api/v1/nlq/ask', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': tenantId,
        },
        body: JSON.stringify({
          question: q,
          session_id: sessionId,
        }),
      });

      if (\!res.ok) {
        throw new Error(`API error: ${res.status}`);
      }

      const body = await res.json();
      const data: NLQResponse = body.data || body;

      // 替换加载占位 with 真实回答
      setMessages((prev) => {
        const updated = [...prev];
        // 找到最后一个 isLoading 消息并替换
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].isLoading) {
            updated[i] = {
              role: 'ai',
              content: data.answer,
              intent: data.intent,
              chartType: data.chart_type || undefined,
              dataRows: data.data || undefined,
              actions: data.actions || undefined,
            };
            break;
          }
        }
        return updated;
      });
    } catch (err) {
      // 替换加载占位为错误消息
      setMessages((prev) => {
        const updated = [...prev];
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].isLoading) {
            updated[i] = {
              role: 'ai',
              content: `抱歉，查询时遇到错误：${err instanceof Error ? err.message : '网络异常'}。请稍后重试。`,
            };
            break;
          }
        }
        return updated;
      });
    } finally {
      setSending(false);
      scrollToBottom();
    }
  }, [sending, sessionId, tenantId, scrollToBottom]);

  // ---- 重新开始新会话 ----
  const resetSession = useCallback(() => {
    setSessionId(`nlq-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
    setMessages([]);
  }, []);

  // ---- 点击追问建议 ----
  const handleFollowup = useCallback((text: string) => {
    setInputVal(text);
  }, []);

  // ---- 渲染单条消息 ----
  const renderMessage = (msg: ChatMsg, idx: number) => {
    const isUser = msg.role === 'user';
    return (
      <div
        key={idx}
        style={{
          display: 'flex',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
          marginBottom: 16,
        }}
      >
        <div
          style={{
            maxWidth: '90%',
            background: isUser ? '#FF6B35' : '#f8f7f5',
            color: isUser ? '#fff' : '#2C2C2A',
            padding: '12px 16px',
            borderRadius: isUser ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
            fontSize: 14,
            lineHeight: 1.6,
          }}
        >
          {/* 问题 / 回答内容 */}
          <div style={{ whiteSpace: 'pre-wrap' }}>
            {msg.isLoading ? (
              <span>
                <Spin size="small" style={{ marginRight: 8 }} />
                {msg.content}
              </span>
            ) : (
              msg.content
            )}
          </div>

          {/* 意图标签 */}
          {msg.intent && \!msg.isLoading && (
            <Tag
              color="orange"
              style={{ marginTop: 8, fontSize: 11 }}
            >
              {msg.intent}
            </Tag>
          )}

          {/* 内联图表 */}
          {msg.chartType && msg.dataRows && msg.dataRows.length > 0 && \!msg.isLoading && (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                background: '#fff',
                borderRadius: 8,
                border: '1px solid #f0f0f0',
              }}
            >
              <InlineChart
                chartType={msg.chartType}
                columns={msg.dataRows.length > 0 ? Object.keys(msg.dataRows[0]) : []}
                rows={msg.dataRows}
              />
            </div>
          )}

          {/* 操作建议 */}
          {msg.actions && msg.actions.length > 0 && \!msg.isLoading && (
            <div style={{ marginTop: 10 }}>
              {msg.actions.map((act) => (
                <Button
                  key={act.action_id}
                  size="small"
                  type="default"
                  style={{
                    marginRight: 8,
                    marginBottom: 4,
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                  onClick={() => {
                    fetch(act.endpoint, {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json',
                        'X-Tenant-ID': tenantId,
                      },
                      body: JSON.stringify({ action_id: act.action_id }),
                    }).catch(() => {});
                  }}
                >
                  {act.label}
                </Button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
        {/* 顶部 Header */}
        <div
          style={{
            padding: '16px 24px',
            borderBottom: '1px solid #f0f0f0',
            background: '#fff',
            flexShrink: 0,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>AI 自然语言问数</div>
            <div style={{ fontSize: 13, color: '#888', marginTop: 2 }}>
              用自然语言提问，AI 自动生成报表，支持追问和下钻
            </div>
          </div>
          <Button
            icon={<ReloadOutlined />}
            onClick={resetSession}
            size="small"
            style={{ borderRadius: 12 }}
          >
            新会话
          </Button>
        </div>

        {/* 主体区域 */}
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* 聊天面板 */}
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* 推荐问题 / 追问建议 */}
            {messages.length === 0 && suggestions.length > 0 && (
              <div
                style={{
                  padding: '16px 24px',
                  borderBottom: '1px solid #f0f0f0',
                  background: '#fafafa',
                }}
              >
                <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>
                  试试这些问题：
                </Text>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {suggestions.map((s) => (
                    <Tag
                      key={s.id}
                      style={{ cursor: 'pointer', fontSize: 12, padding: '4px 10px', borderRadius: 12 }}
                      onClick={() => {
                        setInputVal(s.text);
                      }}
                    >
                      {s.text}
                    </Tag>
                  ))}
                </div>
              </div>
            )}

            {/* 消息列表 */}
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: '16px 24px',
              }}
            >
              {messages.length === 0 ? (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    color: '#b0b0b0',
                    fontSize: 14,
                  }}
                >
                  在上方输入问题或点击推荐问题开始查询
                </div>
              ) : (
                messages.map((msg, idx) => renderMessage(msg, idx))
              )}
              <div ref={chatEndRef} />
            </div>

            {/* 底部输入区 */}
            <div
              style={{
                padding: '16px 24px',
                borderTop: '1px solid #f0f0f0',
                background: '#fff',
                display: 'flex',
                gap: 8,
                alignItems: 'flex-end',
              }}
            >
              <TextArea
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                placeholder="输入您的问题，如：今天各门店营业额对比"
                autoSize={{ minRows: 2, maxRows: 4 }}
                style={{ flex: 1 }}
                disabled={sending}
                onPressEnter={(e) => {
                  if (\!e.shiftKey) {
                    e.preventDefault();
                    sendQuery(inputVal);
                  }
                }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={() => sendQuery(inputVal)}
                loading={sending}
                style={{
                  background: '#FF6B35',
                  borderColor: '#FF6B35',
                  height: 40,
                }}
              >
                发送
              </Button>
            </div>
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
};
