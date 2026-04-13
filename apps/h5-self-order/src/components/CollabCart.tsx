import { useEffect, useRef, useState, useCallback } from 'react';
import { formatPrice } from '@tx-ds/utils';

// ─── 数据类型 ───

interface Participant {
  openid: string;
  nickname: string;
  joined_at: string;
  item_count: number;
}

interface CartItem {
  dish_id: string;
  dish_name: string;
  quantity: number;
  price_fen: number;
  subtotal_fen: number;
  added_by_openid: string;
  added_at: string;
}

interface SessionPayload {
  id: string;
  session_token: string;
  table_id: string;
  order_id: string | null;
  status: string;
  participants: Participant[];
  cart_items: CartItem[];
  expires_at: string;
  submitted_at: string | null;
}

type WsMessage =
  | ({ type: 'cart_update' } & SessionPayload)
  | ({ type: 'participant_joined' } & SessionPayload)
  | ({ type: 'session_submitted'; session_id: string; order_id: string; total_items: number; total_fen: number; kds_sent: boolean })
  | { type: 'pong' };

type CallType = 'general' | 'add_item' | 'checkout' | 'clean_table';

const CALL_TYPE_LABELS: Record<CallType, string> = {
  general: '一般呼叫',
  add_item: '需要加菜',
  checkout: '请求买单',
  clean_table: '清理桌面',
};

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return formatPrice(fen).replace('¥', '');
}

function getWsBaseUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = (window as any).TX_API_HOST ?? window.location.host;
  return `${proto}://${host}`;
}

function getApiBaseUrl(): string {
  return (window as any).TX_API_HOST
    ? `${window.location.protocol}//${(window as any).TX_API_HOST}`
    : '';
}

// ─── Props ───

interface CollabCartProps {
  sessionToken: string;
  openid: string;
  tenantId: string;
  onSubmit?: (orderId: string) => void;
}

// ─── 主组件 ───

export default function CollabCart({
  sessionToken,
  openid,
  tenantId,
  onSubmit,
}: CollabCartProps) {
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const [showCallModal, setShowCallModal] = useState(false);
  const [selectedCallType, setSelectedCallType] = useState<CallType>('general');
  const [callNote, setCallNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [calling, setCalling] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 加载初始会话 ───

  const fetchSession = useCallback(async () => {
    try {
      const res = await fetch(
        `${getApiBaseUrl()}/api/v1/collab-order/sessions/${sessionToken}`,
        { headers: { 'X-Tenant-ID': tenantId } },
      );
      const json = await res.json();
      if (json.ok) setSession(json.data as SessionPayload);
    } catch {
      setErrorMsg('加载会话失败，请刷新重试');
    }
  }, [sessionToken, tenantId]);

  useEffect(() => {
    fetchSession();
  }, [fetchSession]);

  // ─── WebSocket 连接 ───

  useEffect(() => {
    const url = `${getWsBaseUrl()}/api/v1/collab-order/ws/session/${sessionToken}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('connected');
      // 心跳
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, 25_000);
    };

    ws.onmessage = (evt) => {
      try {
        const msg: WsMessage = JSON.parse(evt.data as string);
        if (msg.type === 'cart_update' || msg.type === 'participant_joined') {
          setSession(msg as SessionPayload);
        } else if (msg.type === 'session_submitted') {
          setSubmitted(true);
          onSubmit?.(msg.order_id);
        }
      } catch {
        // 忽略非 JSON 消息（如 "pong"）
      }
    };

    ws.onclose = () => {
      setWsStatus('disconnected');
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };

    ws.onerror = () => setWsStatus('disconnected');

    return () => {
      ws.close();
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, [sessionToken, onSubmit]);

  // ─── 操作：提交点餐 ───

  const handleSubmit = async () => {
    if (submitting || !session?.cart_items.length) return;
    setSubmitting(true);
    setErrorMsg('');
    try {
      const res = await fetch(
        `${getApiBaseUrl()}/api/v1/collab-order/sessions/${sessionToken}/submit`,
        {
          method: 'POST',
          headers: { 'X-Tenant-ID': tenantId, 'Content-Type': 'application/json' },
        },
      );
      const json = await res.json();
      if (!json.ok) setErrorMsg(json.error?.message ?? '提交失败');
    } catch {
      setErrorMsg('网络错误，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  // ─── 操作：移除菜品 ───

  const handleRemove = async (dishId: string) => {
    setErrorMsg('');
    try {
      const res = await fetch(
        `${getApiBaseUrl()}/api/v1/collab-order/sessions/${sessionToken}/cart/${dishId}?openid=${encodeURIComponent(openid)}`,
        {
          method: 'DELETE',
          headers: { 'X-Tenant-ID': tenantId },
        },
      );
      const json = await res.json();
      if (!json.ok) setErrorMsg(json.error?.message ?? '移除失败');
    } catch {
      setErrorMsg('网络错误，请重试');
    }
  };

  // ─── 操作：呼叫服务员 ───

  const handleCallWaiter = async () => {
    if (calling) return;
    setCalling(true);
    setErrorMsg('');
    try {
      const res = await fetch(
        `${getApiBaseUrl()}/api/v1/collab-order/sessions/${sessionToken}/call-waiter`,
        {
          method: 'POST',
          headers: { 'X-Tenant-ID': tenantId, 'Content-Type': 'application/json' },
          body: JSON.stringify({ call_type: selectedCallType, note: callNote }),
        },
      );
      const json = await res.json();
      if (json.ok) {
        setShowCallModal(false);
        setCallNote('');
        setSelectedCallType('general');
      } else {
        setErrorMsg(json.error?.message ?? '呼叫失败');
      }
    } catch {
      setErrorMsg('网络错误，请重试');
    } finally {
      setCalling(false);
    }
  };

  // ─── 工具：获取昵称 ───

  const getNickname = (oid: string): string => {
    if (!session) return oid.slice(-4);
    const p = session.participants.find((x) => x.openid === oid);
    return p?.nickname || oid.slice(-4);
  };

  const isMine = (item: CartItem) => item.added_by_openid === openid;

  // ─── 已提交状态 ───

  if (submitted) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50 px-6">
        <div className="w-20 h-20 rounded-full bg-green-100 flex items-center justify-center mb-4">
          <svg className="w-10 h-10 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-gray-800 mb-2">点餐成功！</h2>
        <p className="text-gray-500 text-sm">菜品已发送到厨房，请耐心等待</p>
      </div>
    );
  }

  // ─── 加载中 ───

  if (!session) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-gray-400 text-sm">加载中...</div>
      </div>
    );
  }

  const totalFen = session.cart_items.reduce((s, c) => s + c.subtotal_fen, 0);
  const totalCount = session.cart_items.reduce((s, c) => s + c.quantity, 0);

  // ─── 渲染 ───

  return (
    <div className="flex flex-col min-h-screen bg-gray-50">
      {/* 顶部状态栏 */}
      <div className="sticky top-0 z-10 bg-white shadow-sm px-4 py-3">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-bold text-gray-800">多人协同点餐</h1>
          <span
            className={`text-xs px-2 py-1 rounded-full ${
              wsStatus === 'connected'
                ? 'bg-green-100 text-green-600'
                : wsStatus === 'connecting'
                ? 'bg-yellow-100 text-yellow-600'
                : 'bg-red-100 text-red-500'
            }`}
          >
            {wsStatus === 'connected' ? '实时同步' : wsStatus === 'connecting' ? '连接中' : '已断线'}
          </span>
        </div>
      </div>

      {/* 错误提示 */}
      {errorMsg && (
        <div className="mx-4 mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">
          {errorMsg}
        </div>
      )}

      {/* 参与者列表 */}
      <div className="mx-4 mt-3 bg-white rounded-xl shadow-sm p-3">
        <p className="text-xs text-gray-400 mb-2">同桌 {session.participants.length} 人</p>
        <div className="flex flex-wrap gap-2">
          {session.participants.map((p) => (
            <div
              key={p.openid}
              className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs ${
                p.openid === openid
                  ? 'bg-orange-100 text-orange-600 font-medium'
                  : 'bg-gray-100 text-gray-600'
              }`}
            >
              <span>{p.nickname || p.openid.slice(-4)}</span>
              {p.item_count > 0 && (
                <span className="bg-orange-500 text-white rounded-full w-4 h-4 flex items-center justify-center text-[10px]">
                  {p.item_count}
                </span>
              )}
              {p.openid === openid && <span className="text-[10px]">（我）</span>}
            </div>
          ))}
        </div>
      </div>

      {/* 购物车列表 */}
      <div className="mx-4 mt-3 flex-1">
        {session.cart_items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-300">
            <svg className="w-12 h-12 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z" />
            </svg>
            <p className="text-sm">购物车还是空的</p>
          </div>
        ) : (
          <div className="space-y-2">
            {session.cart_items.map((item) => (
              <div
                key={item.dish_id}
                className="bg-white rounded-xl shadow-sm p-3 flex items-center justify-between"
              >
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-800 text-sm truncate">{item.dish_name}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-gray-400">
                      by {getNickname(item.added_by_openid)}
                      {isMine(item) && <span className="text-orange-400 ml-1">（我）</span>}
                    </span>
                    <span className="text-xs text-gray-300">×{item.quantity}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 ml-3 shrink-0">
                  <span className="text-sm font-semibold text-orange-500">
                    ¥{fenToYuan(item.subtotal_fen)}
                  </span>
                  {isMine(item) && (
                    <button
                      onClick={() => handleRemove(item.dish_id)}
                      className="w-6 h-6 rounded-full bg-red-50 flex items-center justify-center active:scale-95 transition-transform"
                      aria-label="移除"
                    >
                      <svg className="w-3.5 h-3.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 底部操作栏 */}
      <div className="sticky bottom-0 bg-white border-t border-gray-100 px-4 py-3 pb-safe">
        {/* 合计 */}
        {totalCount > 0 && (
          <div className="flex justify-between items-center mb-3 text-sm">
            <span className="text-gray-500">共 {totalCount} 道菜</span>
            <span className="font-bold text-gray-800">合计：<span className="text-orange-500">¥{fenToYuan(totalFen)}</span></span>
          </div>
        )}

        <div className="flex gap-3">
          {/* 呼叫服务员 */}
          <button
            onClick={() => setShowCallModal(true)}
            className="flex-1 py-3 rounded-xl border border-orange-400 text-orange-500 text-sm font-medium active:scale-[0.98] transition-transform"
          >
            呼叫服务员
          </button>

          {/* 提交点餐 */}
          <button
            onClick={handleSubmit}
            disabled={submitting || totalCount === 0 || session.status !== 'active'}
            className="flex-[2] py-3 rounded-xl bg-orange-500 text-white text-sm font-bold active:scale-[0.98] transition-transform disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? '提交中...' : session.status === 'submitted' ? '已提交' : '提交点餐'}
          </button>
        </div>
      </div>

      {/* 呼叫服务员 Modal */}
      {showCallModal && (
        <div className="fixed inset-0 z-50 flex items-end bg-black/40">
          <div className="w-full bg-white rounded-t-2xl px-4 pt-5 pb-8 pb-safe animate-slide-up">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-base font-bold text-gray-800">呼叫服务员</h3>
              <button
                onClick={() => setShowCallModal(false)}
                className="w-7 h-7 flex items-center justify-center text-gray-400"
              >
                ✕
              </button>
            </div>

            {/* 类型选择 */}
            <div className="grid grid-cols-2 gap-2 mb-4">
              {(Object.keys(CALL_TYPE_LABELS) as CallType[]).map((ct) => (
                <button
                  key={ct}
                  onClick={() => setSelectedCallType(ct)}
                  className={`py-3 rounded-xl text-sm font-medium border transition-colors active:scale-[0.98] ${
                    selectedCallType === ct
                      ? 'bg-orange-500 text-white border-orange-500'
                      : 'bg-white text-gray-600 border-gray-200'
                  }`}
                >
                  {CALL_TYPE_LABELS[ct]}
                </button>
              ))}
            </div>

            {/* 备注输入 */}
            <textarea
              value={callNote}
              onChange={(e) => setCallNote(e.target.value)}
              placeholder="备注（选填）：如"需要辣椒"、"宝宝椅"..."
              className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm text-gray-700 placeholder-gray-300 resize-none h-20 mb-4 focus:outline-none focus:border-orange-400"
              maxLength={100}
            />

            <button
              onClick={handleCallWaiter}
              disabled={calling}
              className="w-full py-3 bg-orange-500 text-white rounded-xl font-bold text-sm disabled:opacity-50"
            >
              {calling ? '呼叫中...' : '确认呼叫'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
