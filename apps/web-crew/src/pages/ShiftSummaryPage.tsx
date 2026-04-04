/**
 * 交接班智能摘要页面 — 服务员端 PWA
 * 路由：/shift-summary
 */
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 颜色常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  red: '#ef4444',
  yellow: '#FF9F0A',
  success: '#30D158',
};

/* ---------- 类型 ---------- */
interface ShiftStats {
  table_count: number;
  revenue: number;
  turnover_rate: number;
  satisfaction: number;
}

interface PendingItem {
  id: string;
  table_no: string;
  desc: string;
  type: 'complaint' | 'praise' | 'equipment' | 'material' | 'unfinished';
}

interface SummaryHistory {
  id: string;
  summary: string;
  created_at: string;
}

/* ---------- 工具函数 ---------- */
function formatRevenue(fen: number): string {
  return (fen / 100).toFixed(0);
}

/* ---------- 骨架屏 ---------- */
function SummarySkeleton() {
  return (
    <div style={{ padding: '4px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <div style={{
          width: 16, height: 16, borderRadius: '50%',
          background: 'rgba(255,107,53,0.3)',
          animation: 'pulse 1.4s ease-in-out infinite',
        }} />
        <span style={{ fontSize: 14, color: C.muted }}>AI正在生成摘要...</span>
      </div>
      {[80, 95, 70].map((w, i) => (
        <div key={i} style={{
          height: 18,
          width: `${w}%`,
          borderRadius: 4,
          background: 'rgba(255,255,255,0.06)',
          marginBottom: 10,
          animation: 'pulse 1.4s ease-in-out infinite',
          animationDelay: `${i * 0.2}s`,
        }} />
      ))}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.9; }
        }
      `}</style>
    </div>
  );
}

/* ---------- 逐字动画文本 ---------- */
function TypewriterText({ text }: { text: string }) {
  return (
    <p style={{
      fontSize: 17,
      lineHeight: 1.7,
      color: C.text,
      margin: 0,
      animation: 'fadeIn 0.3s ease',
    }}>
      {text}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </p>
  );
}

/* ---------- 数据卡片 ---------- */
function StatCard({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: 12,
      padding: '16px 12px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      minHeight: 80,
    }}>
      <span style={{ fontSize: 13, color: C.muted }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span style={{ fontSize: 24, fontWeight: 700, color: C.primary }}>{value}</span>
        {unit && <span style={{ fontSize: 13, color: C.muted }}>{unit}</span>}
      </div>
    </div>
  );
}

/* ---------- 待交接事项行 ---------- */
function PendingRow({ item }: { item: PendingItem }) {
  const typeConfig = {
    complaint:  { icon: '⚠', color: C.red,     label: '投诉' },
    praise:     { icon: '★', color: C.success,  label: '表扬' },
    equipment:  { icon: '⚙', color: C.yellow,   label: '设备' },
    material:   { icon: '◎', color: C.yellow,   label: '物料' },
    unfinished: { icon: '！', color: C.primary,  label: '待办' },
  };
  const cfg = typeConfig[item.type];
  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      padding: '12px 0',
      borderBottom: `1px solid ${C.border}`,
    }}>
      <div style={{
        minWidth: 28, height: 28, borderRadius: 6,
        background: `${cfg.color}22`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 14, color: cfg.color, fontWeight: 700,
        flexShrink: 0,
      }}>
        {cfg.icon}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
          <span style={{
            fontSize: 12, color: cfg.color,
            background: `${cfg.color}22`,
            borderRadius: 4, padding: '1px 6px',
          }}>{cfg.label}</span>
          <span style={{ fontSize: 13, color: C.muted }}>{item.table_no}</span>
        </div>
        <p style={{ margin: 0, fontSize: 15, color: C.text, lineHeight: 1.5 }}>{item.desc}</p>
      </div>
    </div>
  );
}

/* ---------- 主页面 ---------- */
export function ShiftSummaryPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState('');
  const [displayedSummary, setDisplayedSummary] = useState('');
  const [generating, setGenerating] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [stats, setStats] = useState<ShiftStats | null>(null);
  const [pendingItems, setPendingItems] = useState<PendingItem[]>([]);
  const [history, setHistory] = useState<SummaryHistory[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const charIndexRef = useRef(0);
  const typeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* 逐字显示效果 */
  function startTypewriter(fullText: string) {
    setDisplayedSummary('');
    charIndexRef.current = 0;
    if (typeTimerRef.current) clearTimeout(typeTimerRef.current);

    function tick() {
      charIndexRef.current += 1;
      setDisplayedSummary(fullText.slice(0, charIndexRef.current));
      if (charIndexRef.current < fullText.length) {
        typeTimerRef.current = setTimeout(tick, 35);
      }
    }
    tick();
  }

  /* SSE 流式请求 */
  function fetchSummarySSE(crewId: string, currentStats: ShiftStats | null, currentPending: PendingItem[]) {
    setLoading(true);
    setGenerating(true);
    setSummary('');
    setDisplayedSummary('');

    // 关闭旧连接
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    // 用 POST + SSE 的方式：先 POST 拿到 stream URL，再 EventSource
    // 由于 EventSource 不支持 POST body，改用 fetch + ReadableStream 模拟
    const SHIFT_DATA = {
      table_count: currentStats?.table_count ?? 0,
      revenue_fen: currentStats?.revenue ?? 0,
      turnover_rate: currentStats?.turnover_rate ?? 0,
      satisfaction: currentStats?.satisfaction ?? 0,
      pending_count: currentPending.filter(p => p.type === 'unfinished').length,
      complaint_count: currentPending.filter(p => p.type === 'complaint').length,
    };

    let accumulated = '';

    fetch('/api/v1/crew/generate-shift-summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ crew_id: crewId, shift_data: SHIFT_DATA }),
    }).then(res => {
      if (!res.ok || !res.body) throw new Error('SSE not available');

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      function read() {
        reader.read().then(({ done, value }) => {
          if (done) {
            setLoading(false);
            setGenerating(false);
            setSummary(accumulated);
            startTypewriter(accumulated);
            return;
          }
          const text = decoder.decode(value, { stream: true });
          // 解析 SSE lines
          text.split('\n').forEach(line => {
            if (line.startsWith('data: ')) {
              try {
                const payload = JSON.parse(line.slice(6));
                if (payload.chunk) {
                  accumulated += payload.chunk;
                  setDisplayedSummary(accumulated);
                }
                if (payload.done) {
                  setLoading(false);
                  setGenerating(false);
                  setSummary(accumulated);
                }
              } catch {
                // ignore parse errors
              }
            }
          });
          read();
        }).catch(_err => {
          fallbackMock(currentStats, currentPending);
        });
      }
      read();
    }).catch(_err => {
      fallbackMock(currentStats, currentPending);
    });
  }

  /* 后端不可用时的降级回退（基于真实 stats 数据或空安全占位） */
  function fallbackMock(currentStats: ShiftStats | null, currentPending: PendingItem[]) {
    const tableCount = currentStats?.table_count ?? '-';
    const revenue = currentStats != null ? formatRevenue(currentStats.revenue) : '-';
    const turnover = currentStats != null ? currentStats.turnover_rate.toFixed(1) : '-';
    const satisfaction = currentStats?.satisfaction ?? '-';
    const pendingCount = currentPending.filter(p => p.type === 'unfinished').length;
    const complaintCount = currentPending.filter(p => p.type === 'complaint').length;
    const fallbackText = `本班共接待${tableCount}桌，营业额${revenue}元，翻台率${turnover}次。服务满意度${satisfaction}%，收到${complaintCount}次投诉，有${pendingCount}项待办事项，请下班同事及时跟进处理。`;
    setSummary(fallbackText);
    setLoading(false);
    setGenerating(false);
    startTypewriter(fallbackText);
  }

  /* 初始化加载：先拉取班次数据，再生成摘要 */
  useEffect(() => {
    const crewId = (window as any).__CREW_ID__ || 'crew-001';
    let cancelled = false;

    async function loadData() {
      try {
        const res = await fetch('/api/v1/trade/shift/summary?date=today');
        if (!cancelled && res.ok) {
          const json = await res.json();
          if (json.ok) {
            const loadedStats: ShiftStats | null = json.data?.stats ?? null;
            const loadedPending: PendingItem[] = json.data?.pending_items ?? [];
            const loadedHistory: SummaryHistory[] = json.data?.history ?? [];
            setStats(loadedStats);
            setPendingItems(loadedPending);
            setHistory(loadedHistory);
            fetchSummarySSE(crewId, loadedStats, loadedPending);
            return;
          }
        }
      } catch {
        // 网络失败，继续降级
      }
      if (!cancelled) {
        fetchSummarySSE(crewId, null, []);
      }
    }

    loadData();

    return () => {
      cancelled = true;
      if (esRef.current) esRef.current.close();
      if (typeTimerRef.current) clearTimeout(typeTimerRef.current);
      window.speechSynthesis?.cancel();
    };
  }, []);

  /* 语音播报 */
  function handleSpeak() {
    if (!summary) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const utt = new SpeechSynthesisUtterance(summary);
    utt.lang = 'zh-CN';
    utt.rate = 0.95;
    utt.onstart = () => setSpeaking(true);
    utt.onend = () => setSpeaking(false);
    utt.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utt);
  }

  /* 重新生成 */
  function handleRegenerate() {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
    const crewId = (window as any).__CREW_ID__ || 'crew-001';
    fetchSummarySSE(crewId, stats, pendingItems);
  }

  return (
    <div style={{
      background: C.bg,
      minHeight: '100vh',
      color: C.text,
      paddingBottom: 100,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    }}>
      {/* 顶部导航 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '16px 16px 8px',
        position: 'sticky',
        top: 0,
        background: C.bg,
        zIndex: 10,
        borderBottom: `1px solid ${C.border}`,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'none', border: 'none', color: C.text,
            fontSize: 20, cursor: 'pointer', padding: '4px 8px 4px 0',
            minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center',
          }}
        >
          ←
        </button>
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>交接班摘要</h1>
          <p style={{ margin: 0, fontSize: 13, color: C.muted }}>AI智能生成 · 本班次</p>
        </div>
        <button
          onClick={() => setShowHistory(!showHistory)}
          style={{
            background: 'none', border: `1px solid ${C.border}`,
            borderRadius: 8, color: C.muted, fontSize: 13,
            padding: '6px 12px', cursor: 'pointer',
            minHeight: 48, display: 'flex', alignItems: 'center',
          }}
        >
          历史
        </button>
      </div>

      <div style={{ padding: '16px' }}>
        {/* ── 1. AI摘要卡片 ── */}
        <div style={{
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: 16,
          padding: 20,
          marginBottom: 16,
          position: 'relative',
          overflow: 'hidden',
        }}>
          {/* 渐变装饰条 */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: 3,
            background: `linear-gradient(90deg, ${C.primary}, #ff9f0a)`,
            borderRadius: '16px 16px 0 0',
          }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <span style={{
              fontSize: 20,
              filter: generating ? 'grayscale(0.3)' : 'none',
              animation: generating ? 'spin 2s linear infinite' : 'none',
            }}>
              {generating ? '⟳' : '✦'}
            </span>
            <span style={{ fontSize: 16, fontWeight: 600, color: C.primary }}>AI智能摘要</span>
            {generating && (
              <span style={{ fontSize: 12, color: C.muted, marginLeft: 4 }}>生成中...</span>
            )}
            <style>{`
              @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
              }
            `}</style>
          </div>

          <div style={{ minHeight: 80 }}>
            {loading && !displayedSummary ? (
              <SummarySkeleton />
            ) : (
              <TypewriterText text={displayedSummary || summary} />
            )}
          </div>

          {/* 操作按钮 */}
          {!loading && summary && (
            <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
              <button
                onClick={handleSpeak}
                style={{
                  flex: 1,
                  minHeight: 48,
                  background: speaking ? 'rgba(255,107,53,0.15)' : 'rgba(255,107,53,0.1)',
                  border: `1px solid ${speaking ? C.primary : 'rgba(255,107,53,0.3)'}`,
                  borderRadius: 10, color: C.primary,
                  fontSize: 15, fontWeight: 600, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}
              >
                <span>{speaking ? '■' : '▶'}</span>
                <span>{speaking ? '停止播报' : '🔊 语音播报'}</span>
              </button>
              <button
                onClick={handleRegenerate}
                disabled={generating}
                style={{
                  minWidth: 88, minHeight: 48,
                  background: 'none',
                  border: `1px solid ${C.border}`,
                  borderRadius: 10, color: C.muted,
                  fontSize: 14, cursor: generating ? 'not-allowed' : 'pointer',
                  opacity: generating ? 0.5 : 1,
                }}
              >
                重新生成
              </button>
            </div>
          )}
        </div>

        {/* ── 2. 本班数据卡片 2×2 ── */}
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 12px', color: C.text }}>本班数据</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
          <StatCard label="接待桌次" value={stats?.table_count ?? '-'} unit="桌" />
          <StatCard label="营业额" value={stats != null ? `¥${formatRevenue(stats.revenue)}` : '-'} />
          <StatCard label="翻台率" value={stats != null ? stats.turnover_rate.toFixed(1) : '-'} unit="次" />
          <StatCard label="员工满意度" value={stats != null ? `${stats.satisfaction}%` : '-'} />
        </div>

        {/* ── 3. 重要交接事项 ── */}
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px', color: C.text }}>
          重要交接事项
        </h2>
        <p style={{ fontSize: 13, color: C.muted, margin: '0 0 12px' }}>
          以下事项需告知下班同事
        </p>
        <div style={{
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: 14,
          padding: '0 16px',
          marginBottom: 16,
        }}>
          {pendingItems.length === 0 ? (
            <div style={{ padding: '20px 0', fontSize: 15, color: C.muted, textAlign: 'center' }}>
              暂无待交接事项
            </div>
          ) : (
            pendingItems.map((item, i) => (
              <div key={item.id} style={{ borderBottom: i < pendingItems.length - 1 ? `1px solid ${C.border}` : 'none' }}>
                <PendingRow item={item} />
              </div>
            ))
          )}
        </div>

        {/* ── 历史摘要（折叠） ── */}
        {showHistory && (
          <div style={{ marginBottom: 16 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 12px', color: C.text }}>历史摘要</h2>
            {history.length === 0 ? (
              <div style={{ fontSize: 15, color: C.muted, textAlign: 'center', padding: '16px 0' }}>
                暂无历史摘要
              </div>
            ) : (
              history.map(h => (
                <div key={h.id} style={{
                  background: C.card, border: `1px solid ${C.border}`,
                  borderRadius: 12, padding: 14, marginBottom: 10,
                }}>
                  <p style={{ margin: '0 0 6px', fontSize: 15, color: C.text, lineHeight: 1.6 }}>{h.summary}</p>
                  <span style={{ fontSize: 12, color: C.muted }}>{h.created_at}</span>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* ── 4. 底部操作 ── */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: C.bg,
        borderTop: `1px solid ${C.border}`,
        padding: '12px 16px',
        display: 'flex', gap: 12,
      }}>
        <button
          onClick={() => navigate('/handover')}
          style={{
            flex: 2, minHeight: 54,
            background: C.primary,
            border: 'none', borderRadius: 14,
            color: '#fff', fontSize: 17, fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          确认并交班
        </button>
        <button
          onClick={() => {
            // 打印交班单：通过 TXBridge 或 window.print() 降级
            if ((window as any).TXBridge?.print) {
              (window as any).TXBridge.print('SHIFT_SUMMARY');
            } else {
              window.print();
            }
          }}
          style={{
            flex: 1, minHeight: 54,
            background: 'none',
            border: `1px solid ${C.border}`,
            borderRadius: 14,
            color: C.text, fontSize: 15,
            cursor: 'pointer',
          }}
        >
          打印交班单
        </button>
      </div>
    </div>
  );
}

export default ShiftSummaryPage;
