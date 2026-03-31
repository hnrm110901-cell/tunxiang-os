/**
 * 顾客自助分账付款页面 (C5+C6)
 * 路由：/self-pay-link?order_id=xxx
 * 服务员端 PWA — dark theme, #FF6B35 主色, 最小字体16px, 按钮≥48px
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

const PRIMARY = '#FF6B35';
const BG = '#0B1A20';
const SURFACE = '#112228';
const SURFACE2 = '#1a2f38';
const TEXT = '#FFFFFF';
const MUTED = '#94a3b8';
const SUCCESS = '#22c55e';
const BASE_URL = '/api/v1';

// ──────────────────────────────────────────────
//  轻量 SVG 二维码（数据矩阵风格占位，展示链接文本）
// ──────────────────────────────────────────────

function QRDisplay({ value, size = 200 }: { value: string; size?: number }) {
  // 用简单的格子图案表示 QR（正式场景接入 qrcode 库）
  const cells = 21;
  const cellSize = size / cells;

  // 用字符串 hash 生成确定性的格子
  const hash = (s: string) => {
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = (h * 33) ^ s.charCodeAt(i);
    return h >>> 0;
  };

  const filled = (r: number, c: number): boolean => {
    // 固定的定位角 (3x3 finder patterns)
    const inFinder = (row: number, col: number) =>
      (row < 7 && col < 7) ||
      (row < 7 && col >= cells - 7) ||
      (row >= cells - 7 && col < 7);
    if (inFinder(r, c)) {
      const dr = r < 7 ? r : r - (cells - 7);
      const dc = c < 7 ? c : c - (cells - 7);
      return dr === 0 || dr === 6 || dc === 0 || dc === 6 || (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4);
    }
    return !!(hash(value + r * cells + c) % 2);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <div style={{ padding: 12, background: '#fff', borderRadius: 8, display: 'inline-block' }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {Array.from({ length: cells }, (_, r) =>
            Array.from({ length: cells }, (_, c) =>
              filled(r, c) ? (
                <rect
                  key={`${r}-${c}`}
                  x={c * cellSize}
                  y={r * cellSize}
                  width={cellSize}
                  height={cellSize}
                  fill="#000"
                />
              ) : null
            )
          )}
        </svg>
      </div>
      <p style={{ fontSize: 12, color: MUTED, wordBreak: 'break-all', maxWidth: size, textAlign: 'center', margin: 0 }}>
        {value.length > 60 ? value.slice(0, 60) + '…' : value}
      </p>
    </div>
  );
}

// ──────────────────────────────────────────────
//  API helpers
// ──────────────────────────────────────────────

async function fetchOrderDetail(orderId: string) {
  const res = await fetch(`${BASE_URL}/orders/${orderId}`, {
    headers: { 'X-Tenant-ID': (window as any).__TENANT_ID__ || 'default' },
  });
  if (!res.ok) throw new Error('订单查询失败');
  const json = await res.json();
  return json.data;
}

async function createSelfPayLink(orderId: string, splitCount: number) {
  const res = await fetch(`${BASE_URL}/orders/${orderId}/self-pay-link`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': (window as any).__TENANT_ID__ || 'default',
    },
    body: JSON.stringify({ split_count: splitCount }),
  });
  if (!res.ok) throw new Error('生成付款链接失败');
  const json = await res.json();
  return json.data;
}

async function fetchPaymentStatus(orderId: string) {
  const res = await fetch(`${BASE_URL}/orders/${orderId}/payment-status`, {
    headers: { 'X-Tenant-ID': (window as any).__TENANT_ID__ || 'default' },
  });
  if (!res.ok) throw new Error('查询状态失败');
  const json = await res.json();
  return json.data;
}

// ──────────────────────────────────────────────
//  主页面
// ──────────────────────────────────────────────

interface OrderInfo {
  id: string;
  table_no?: string;
  status: string;
  final_amount_fen?: number;
  total_amount_fen?: number;
  items?: Array<{ name: string; qty: number; price_fen: number }>;
}

interface LinkResult {
  token: string;
  deep_link: string;
  total_amount_fen: number;
  per_person_amount_fen: number;
  split_count: number;
}

type Mode = 'full' | 'split';

export default function SelfPayLinkPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const orderId = params.get('order_id') || '';

  const [order, setOrder] = useState<OrderInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [mode, setMode] = useState<Mode>('full');
  const [splitCount, setSplitCount] = useState(2);
  const [linkResult, setLinkResult] = useState<LinkResult | null>(null);
  const [generating, setGenerating] = useState(false);

  const [polling, setPolling] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState<'pending' | 'paid'>('pending');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 加载订单
  useEffect(() => {
    if (!orderId) {
      setError('缺少 order_id 参数');
      setLoading(false);
      return;
    }
    fetchOrderDetail(orderId)
      .then(data => {
        setOrder(data);
        if (data.status === 'paid') setPaymentStatus('paid');
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [orderId]);

  // 停止轮询
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setPolling(false);
  }, []);

  // 开始轮询
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    setPolling(true);
    pollRef.current = setInterval(async () => {
      try {
        const status = await fetchPaymentStatus(orderId);
        if (status.paid) {
          setPaymentStatus('paid');
          stopPolling();
        }
      } catch {
        // 网络抖动忽略
      }
    }, 3000);
  }, [orderId, stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // 生成二维码
  const handleGenerate = async () => {
    setGenerating(true);
    setLinkResult(null);
    try {
      const count = mode === 'full' ? 1 : Math.max(2, splitCount);
      const result = await createSelfPayLink(orderId, count);
      setLinkResult(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const totalYuan = order
    ? ((order.final_amount_fen ?? order.total_amount_fen ?? 0) / 100).toFixed(2)
    : '0.00';

  // ── 渲染 ──

  if (loading) {
    return (
      <div style={{ background: BG, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <p style={{ color: MUTED, fontSize: 18 }}>加载中…</p>
      </div>
    );
  }

  if (error && !order) {
    return (
      <div style={{ background: BG, minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24 }}>
        <p style={{ color: '#f87171', fontSize: 18, textAlign: 'center' }}>{error}</p>
        <button onClick={() => navigate(-1)} style={btnStyle(MUTED)}>返回</button>
      </div>
    );
  }

  return (
    <div style={{ background: BG, minHeight: '100vh', color: TEXT, fontFamily: 'system-ui, sans-serif', paddingBottom: 32 }}>
      {/* 顶栏 */}
      <div style={{ background: SURFACE, padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={() => navigate(-1)}
          style={{ background: 'none', border: 'none', color: TEXT, fontSize: 22, cursor: 'pointer', lineHeight: 1, padding: 4 }}
        >
          ‹
        </button>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>顾客自助付款</h1>
          {order?.table_no && (
            <p style={{ margin: 0, fontSize: 14, color: MUTED }}>{order.table_no} 桌</p>
          )}
        </div>
      </div>

      <div style={{ padding: '20px 20px 0' }}>
        {/* 已支付状态 */}
        {paymentStatus === 'paid' && (
          <div style={{ background: '#14532d', borderRadius: 12, padding: '20px 24px', textAlign: 'center', marginBottom: 20 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>✓</div>
            <p style={{ color: SUCCESS, fontSize: 22, fontWeight: 700, margin: 0 }}>已完成支付</p>
            <p style={{ color: MUTED, fontSize: 16, margin: '8px 0 0' }}>¥{totalYuan}</p>
          </div>
        )}

        {/* 订单摘要 */}
        {order && (
          <div style={{ background: SURFACE, borderRadius: 12, padding: '16px 20px', marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontSize: 16, color: MUTED }}>订单总金额</span>
              <span style={{ fontSize: 28, fontWeight: 700, color: PRIMARY }}>¥{totalYuan}</span>
            </div>

            {/* 菜品列表 */}
            {order.items && order.items.length > 0 && (
              <div style={{ borderTop: `1px solid ${SURFACE2}`, paddingTop: 12 }}>
                {order.items.map((item, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, padding: '4px 0' }}>
                    <span style={{ color: TEXT }}>{item.name} × {item.qty}</span>
                    <span style={{ color: MUTED }}>¥{(item.price_fen / 100).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 分账模式选择 */}
        {paymentStatus !== 'paid' && (
          <>
            <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
              <button
                onClick={() => { setMode('full'); setLinkResult(null); }}
                style={btnStyle(mode === 'full' ? PRIMARY : SURFACE2, mode === 'full' ? '#fff' : MUTED)}
              >
                全单付
              </button>
              <button
                onClick={() => { setMode('split'); setLinkResult(null); }}
                style={btnStyle(mode === 'split' ? PRIMARY : SURFACE2, mode === 'split' ? '#fff' : MUTED)}
              >
                按人分摊
              </button>
            </div>

            {mode === 'split' && (
              <div style={{ background: SURFACE, borderRadius: 12, padding: '16px 20px', marginBottom: 20 }}>
                <label style={{ fontSize: 16, color: MUTED, display: 'block', marginBottom: 10 }}>就餐人数</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <button
                    onClick={() => setSplitCount(n => Math.max(2, n - 1))}
                    style={{ width: 48, height: 48, borderRadius: 8, background: SURFACE2, border: 'none', color: TEXT, fontSize: 24, cursor: 'pointer' }}
                  >
                    −
                  </button>
                  <span style={{ fontSize: 28, fontWeight: 700, minWidth: 40, textAlign: 'center' }}>{splitCount}</span>
                  <button
                    onClick={() => setSplitCount(n => n + 1)}
                    style={{ width: 48, height: 48, borderRadius: 8, background: SURFACE2, border: 'none', color: TEXT, fontSize: 24, cursor: 'pointer' }}
                  >
                    +
                  </button>
                  <span style={{ fontSize: 16, color: MUTED }}>
                    每人约 ¥{(((order?.final_amount_fen ?? order?.total_amount_fen ?? 0) / 100) / splitCount).toFixed(2)}
                  </span>
                </div>
              </div>
            )}

            <button
              onClick={handleGenerate}
              disabled={generating}
              style={btnStyle(generating ? SURFACE2 : PRIMARY, generating ? MUTED : '#fff')}
            >
              {generating ? '生成中…' : '生成付款二维码'}
            </button>
          </>
        )}

        {/* 二维码展示 */}
        {linkResult && paymentStatus !== 'paid' && (
          <div style={{ background: SURFACE, borderRadius: 12, padding: '20px', marginTop: 20, textAlign: 'center' }}>
            <p style={{ fontSize: 16, color: MUTED, margin: '0 0 16px' }}>
              {linkResult.split_count > 1
                ? `每人应付 ¥${(linkResult.per_person_amount_fen / 100).toFixed(2)}`
                : `全单 ¥${(linkResult.total_amount_fen / 100).toFixed(2)}`}
            </p>

            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
              <QRDisplay value={linkResult.deep_link} size={200} />
            </div>

            <p style={{ fontSize: 16, color: MUTED, margin: '0 0 20px' }}>
              顾客扫码后可在手机上完成支付
            </p>

            {/* 查看支付状态 */}
            {!polling ? (
              <button onClick={startPolling} style={btnStyle('#1e3a4a', TEXT)}>
                查看支付状态
              </button>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                <span style={{ fontSize: 16, color: MUTED }}>等待顾客付款…</span>
                <button onClick={stopPolling} style={{ background: 'none', border: 'none', color: MUTED, fontSize: 14, cursor: 'pointer', textDecoration: 'underline' }}>
                  停止
                </button>
              </div>
            )}
          </div>
        )}

        {/* 支付完成大提示 */}
        {paymentStatus === 'paid' && (
          <button onClick={() => navigate(-1)} style={{ ...btnStyle('#22c55e', '#fff'), marginTop: 20 }}>
            返回桌台
          </button>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
//  样式工具
// ──────────────────────────────────────────────

function btnStyle(bg: string, color = '#fff'): React.CSSProperties {
  return {
    width: '100%',
    minHeight: 52,
    padding: '12px 20px',
    background: bg,
    color,
    border: 'none',
    borderRadius: 10,
    fontSize: 18,
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  };
}
