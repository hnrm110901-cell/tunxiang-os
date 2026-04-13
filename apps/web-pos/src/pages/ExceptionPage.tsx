/**
 * 异常中心 — /exceptions
 * 退菜/反结账/补打/客诉/设备故障/库存预警/折扣异常 + 店长覆盖审批
 *
 * API: GET  /api/v1/ops/exceptions?store_id=
 *      POST /api/v1/ops/exceptions/{id}/resolve
 *      POST /api/v1/ops/exceptions/{id}/escalate
 *      POST /api/v1/trade/orders/{orderId}/items/{itemId}/return  (退菜)
 *      POST /api/v1/trade/orders/{orderId}/reverse-settle         (反结账)
 *      POST /api/v1/trade/orders/{orderId}/print/receipt          (补打)
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}), ...(options.headers as Record<string, string> || {}) },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type ExceptionType = 'return_dish' | 'reverse_settle' | 'reprint' | 'complaint' | 'equipment' | 'shortage' | 'discount' | 'manager_override';
type Severity = 'critical' | 'high' | 'medium' | 'low';
type ExStatus = 'pending' | 'processing' | 'awaiting_approval' | 'resolved' | 'rejected';

interface ExceptionItem {
  id: string;
  type: ExceptionType;
  title: string;
  description: string;
  severity: Severity;
  status: ExStatus;
  time: string;
  table?: string;
  orderId?: string;
  itemId?: string;
  operatorName?: string;
  amountFen?: number;
  reason?: string;
  resolvedBy?: string;
  resolvedAt?: string;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<ExceptionType, { icon: string; label: string }> = {
  return_dish:       { icon: '↩️', label: '退菜' },
  reverse_settle:    { icon: '🔄', label: '反结账' },
  reprint:           { icon: '🖨', label: '补打' },
  complaint:         { icon: '😤', label: '客诉' },
  equipment:         { icon: '🔧', label: '设备故障' },
  shortage:          { icon: '📦', label: '缺料预警' },
  discount:          { icon: '💰', label: '异常折扣' },
  manager_override:  { icon: '🔑', label: '店长覆盖' },
};

const SEVERITY_COLOR: Record<Severity, string> = { critical: '#ff4d4f', high: '#faad14', medium: '#1890ff', low: '#52c41a' };

const STATUS_CONFIG: Record<ExStatus, { label: string; color: string; bg: string }> = {
  pending:            { label: '待处理', color: '#ff4d4f', bg: 'rgba(255,77,79,0.13)' },
  processing:         { label: '处理中', color: '#faad14', bg: 'rgba(250,173,20,0.13)' },
  awaiting_approval:  { label: '待审批', color: '#1890ff', bg: 'rgba(24,144,255,0.13)' },
  resolved:           { label: '已解决', color: '#52c41a', bg: 'rgba(82,196,26,0.13)' },
  rejected:           { label: '已驳回', color: '#ff4d4f', bg: 'rgba(255,77,79,0.13)' },
};

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ─── Fallback 数据 ──────────────────────────────────────────────────────────────

const FALLBACK_EXCEPTIONS: ExceptionItem[] = [
  { id: '1', type: 'discount', title: '异常折扣: A05桌 折扣率65%', description: '折扣守护Agent检测到异常折扣，超过30%阈值', severity: 'critical', time: '14:30', status: 'pending', table: 'A05', orderId: 'ord-001', amountFen: 28600 },
  { id: '2', type: 'return_dish', title: '退菜: 口味虾（不新鲜）', description: '客人反映口味虾不新鲜要求退菜', severity: 'high', time: '14:10', status: 'awaiting_approval', table: 'B01', orderId: 'ord-002', itemId: 'item-003', amountFen: 12800, reason: '食材不新鲜' },
  { id: '3', type: 'complaint', title: '客诉: A03桌菜品太咸', description: '客人投诉剁椒鱼头太咸，要求重做或退菜', severity: 'high', time: '14:25', status: 'processing', table: 'A03', orderId: 'ord-003' },
  { id: '4', type: 'reverse_settle', title: '反结账: B02桌少算1道菜', description: '服务员发现漏录蛋炒饭1份，需要反结账补录', severity: 'medium', time: '14:35', status: 'pending', table: 'B02', orderId: 'ord-004', amountFen: 1800 },
  { id: '5', type: 'shortage', title: '鲈鱼库存不足(仅剩2kg)', description: '供应链卫士Agent预警：鲈鱼库存低于安全线', severity: 'high', time: '13:30', status: 'pending' },
  { id: '6', type: 'equipment', title: '2号打印机卡纸', description: '后厨2号打印机卡纸无法出单', severity: 'medium', time: '13:50', status: 'resolved', resolvedBy: '张师傅', resolvedAt: '14:05' },
  { id: '7', type: 'reprint', title: '补打: A01桌小票遗失', description: '客人要求补打消费小票', severity: 'low', time: '14:40', status: 'pending', table: 'A01', orderId: 'ord-005' },
  { id: '8', type: 'manager_override', title: '店长覆盖: 赠菜审批', description: '服务员申请赠送凉拌黄瓜1份给C02桌（老客户）', severity: 'medium', time: '14:45', status: 'awaiting_approval', table: 'C02', orderId: 'ord-006', amountFen: 900, operatorName: '小王' },
];

// ─── 退菜原因选项 ──────────────────────────────────────────────────────────────

const RETURN_REASONS = ['食材不新鲜', '菜品有异物', '做错菜', '上错桌', '口味不符', '等待时间太长', '客人主动取消', '其他'];

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ExceptionPage() {
  const navigate = useNavigate();
  const [exceptions, setExceptions] = useState<ExceptionItem[]>(FALLBACK_EXCEPTIONS);
  const [filterType, setFilterType] = useState<ExceptionType | ''>('');
  const [filterStatus, setFilterStatus] = useState<ExStatus | ''>('');
  const [loading, setLoading] = useState(false);

  // 弹窗
  const [selectedEx, setSelectedEx] = useState<ExceptionItem | null>(null);
  const [showResolveModal, setShowResolveModal] = useState(false);
  const [resolveNote, setResolveNote] = useState('');
  const [returnReason, setReturnReason] = useState('');
  const [processing, setProcessing] = useState(false);

  // ─── 数据加载 ──────────────────────────────────────────────────────────────

  const loadExceptions = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ store_id: STORE_ID });
      if (filterType) params.set('type', filterType);
      if (filterStatus) params.set('status', filterStatus);
      const data = await txFetch<{ items: ExceptionItem[] }>(`/api/v1/ops/exceptions?${params}`);
      if (data && Array.isArray(data.items) && data.items.length > 0) {
        setExceptions(data.items);
      }
    } catch { /* fallback */ }
    setLoading(false);
  }, [filterType, filterStatus]);

  useEffect(() => { loadExceptions(); }, [loadExceptions]);

  // ─── 统计 ──────────────────────────────────────────────────────────────────

  const counts = {
    pending: exceptions.filter(e => e.status === 'pending').length,
    processing: exceptions.filter(e => e.status === 'processing').length,
    awaiting: exceptions.filter(e => e.status === 'awaiting_approval').length,
    resolved: exceptions.filter(e => e.status === 'resolved' || e.status === 'rejected').length,
  };

  // ─── 操作 ──────────────────────────────────────────────────────────────────

  const handleResolve = async () => {
    if (!selectedEx) return;
    setProcessing(true);

    try {
      if (selectedEx.type === 'return_dish' && selectedEx.orderId && selectedEx.itemId) {
        // 退菜
        await txFetch(`/api/v1/trade/orders/${selectedEx.orderId}/items/${selectedEx.itemId}/return`, {
          method: 'POST', body: JSON.stringify({ reason: returnReason || resolveNote }),
        });
      } else if (selectedEx.type === 'reverse_settle' && selectedEx.orderId) {
        // 反结账
        await txFetch(`/api/v1/trade/orders/${selectedEx.orderId}/reverse-settle`, { method: 'POST' });
      } else if (selectedEx.type === 'reprint' && selectedEx.orderId) {
        // 补打
        await txFetch(`/api/v1/trade/orders/${selectedEx.orderId}/print/receipt`, { method: 'POST' });
      } else {
        // 通用解决
        await txFetch(`/api/v1/ops/exceptions/${selectedEx.id}/resolve`, {
          method: 'POST', body: JSON.stringify({ note: resolveNote }),
        });
      }
    } catch { /* offline ok */ }

    setExceptions(prev => prev.map(e => e.id === selectedEx.id ? { ...e, status: 'resolved' as ExStatus } : e));
    setProcessing(false);
    setShowResolveModal(false);
    setSelectedEx(null);
    setResolveNote('');
    setReturnReason('');
  };

  const handleApprove = async (ex: ExceptionItem) => {
    try {
      await txFetch(`/api/v1/ops/exceptions/${ex.id}/resolve`, {
        method: 'POST', body: JSON.stringify({ action: 'approve' }),
      });
    } catch { /* offline */ }
    setExceptions(prev => prev.map(e => e.id === ex.id ? { ...e, status: 'resolved' as ExStatus } : e));
  };

  const handleReject = async (ex: ExceptionItem) => {
    try {
      await txFetch(`/api/v1/ops/exceptions/${ex.id}/resolve`, {
        method: 'POST', body: JSON.stringify({ action: 'reject' }),
      });
    } catch { /* offline */ }
    setExceptions(prev => prev.map(e => e.id === ex.id ? { ...e, status: 'rejected' as ExStatus } : e));
  };

  const openResolve = (ex: ExceptionItem) => {
    setSelectedEx(ex);
    setResolveNote('');
    setReturnReason(ex.reason || '');
    setShowResolveModal(true);
  };

  // ─── 筛选 ──────────────────────────────────────────────────────────────────

  const filtered = exceptions.filter(e => {
    if (filterType && e.type !== filterType) return false;
    if (filterStatus && e.status !== filterStatus) return false;
    return true;
  });

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h3 style={{ margin: 0, fontSize: 20 }}>异常中心</h3>
          <button type="button" onClick={() => navigate('/tables')} style={{ padding: '6px 14px', background: '#1a2a33', color: '#9CA3AF', border: '1px solid #333', borderRadius: 6, fontSize: 14, cursor: 'pointer', minHeight: 36 }}>
            ← 桌台
          </button>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 14 }}>
          <span style={{ color: '#ff4d4f' }}>待处理 {counts.pending}</span>
          <span style={{ color: '#faad14' }}>处理中 {counts.processing}</span>
          <span style={{ color: '#1890ff' }}>待审批 {counts.awaiting}</span>
          <span style={{ color: '#52c41a' }}>已完结 {counts.resolved}</span>
        </div>
      </div>

      {/* 筛选 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <FilterBtn label="全部类型" active={!filterType} onClick={() => setFilterType('')} />
        {Object.entries(TYPE_CONFIG).map(([k, v]) => (
          <FilterBtn key={k} label={`${v.icon} ${v.label}`} active={filterType === k} onClick={() => setFilterType(k as ExceptionType)} />
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <FilterBtn label="全部状态" active={!filterStatus} onClick={() => setFilterStatus('')} />
        {Object.entries(STATUS_CONFIG).map(([k, v]) => (
          <FilterBtn key={k} label={v.label} active={filterStatus === k} onClick={() => setFilterStatus(k as ExStatus)} />
        ))}
      </div>

      {/* 列表 */}
      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {filtered.length === 0 && !loading && (
        <div style={{ textAlign: 'center', color: '#6B7280', paddingTop: 40, fontSize: 16 }}>暂无异常记录</div>
      )}

      {filtered.map(e => {
        const tc = TYPE_CONFIG[e.type];
        const sc = STATUS_CONFIG[e.status];
        return (
          <div key={e.id} style={{
            padding: 16, marginBottom: 10, borderRadius: 10, background: '#112228',
            borderLeft: `4px solid ${SEVERITY_COLOR[e.severity]}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
                <span style={{ fontSize: 28, flexShrink: 0 }}>{tc.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 16 }}>{e.title}</div>
                  <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>{e.description}</div>
                  <div style={{ fontSize: 12, color: '#6B7280', marginTop: 4 }}>
                    {e.time} {e.table ? `· ${e.table}` : ''} {e.amountFen ? `· ${fen2yuan(e.amountFen)}` : ''}
                    {e.operatorName ? ` · ${e.operatorName}` : ''}
                  </div>
                  {e.resolvedBy && <div style={{ fontSize: 12, color: '#52c41a', marginTop: 2 }}>已由 {e.resolvedBy} 于 {e.resolvedAt} 解决</div>}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 12 }}>
                <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 500, color: sc.color, background: sc.bg }}>
                  {sc.label}
                </span>
                {/* 操作按钮 */}
                {e.status === 'pending' && (
                  <button type="button" onClick={() => openResolve(e)}
                    style={{ padding: '6px 14px', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 500, minHeight: 36 }}>
                    处理
                  </button>
                )}
                {e.status === 'awaiting_approval' && (
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button type="button" onClick={() => handleApprove(e)}
                      style={{ padding: '6px 12px', background: '#0F6E56', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 500, minHeight: 36 }}>
                      批准
                    </button>
                    <button type="button" onClick={() => handleReject(e)}
                      style={{ padding: '6px 12px', background: 'transparent', color: '#ff4d4f', border: '1px solid #ff4d4f', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 500, minHeight: 36 }}>
                      驳回
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* 处理弹窗 */}
      {showResolveModal && selectedEx && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowResolveModal(false)}>
          <div style={{ background: '#1a2a33', borderRadius: 12, padding: 24, width: 420, maxWidth: '90vw' }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>
              {TYPE_CONFIG[selectedEx.type].icon} 处理{TYPE_CONFIG[selectedEx.type].label}
            </div>
            <div style={{ fontSize: 14, color: '#9CA3AF', marginBottom: 16 }}>{selectedEx.title}</div>

            {/* 退菜原因选择 */}
            {selectedEx.type === 'return_dish' && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 14, color: '#ccc', marginBottom: 8 }}>退菜原因</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {RETURN_REASONS.map(r => (
                    <button key={r} type="button" onClick={() => setReturnReason(r)}
                      style={{
                        padding: '8px 14px', borderRadius: 8, fontSize: 14, cursor: 'pointer', minHeight: 40,
                        background: returnReason === r ? 'rgba(255,107,53,0.2)' : '#112228',
                        border: returnReason === r ? '1px solid #FF6B35' : '1px solid #333',
                        color: returnReason === r ? '#FF6B35' : '#ccc',
                      }}>
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 反结账提示 */}
            {selectedEx.type === 'reverse_settle' && (
              <div style={{ padding: '10px 14px', background: 'rgba(255,77,79,0.08)', borderRadius: 8, marginBottom: 16, fontSize: 14, color: '#faad14' }}>
                反结账将撤销该订单的结算状态，允许重新加菜/改价后再次结算。
              </div>
            )}

            {/* 补打提示 */}
            {selectedEx.type === 'reprint' && (
              <div style={{ padding: '10px 14px', background: 'rgba(82,196,26,0.08)', borderRadius: 8, marginBottom: 16, fontSize: 14, color: '#52c41a' }}>
                将重新打印该订单的消费小票。
              </div>
            )}

            {/* 处理备注 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 14, color: '#ccc', marginBottom: 4 }}>处理备注</div>
              <textarea value={resolveNote} onChange={e => setResolveNote(e.target.value)} rows={2} placeholder="描述处理方式..."
                style={{ width: '100%', padding: 10, background: '#112228', border: '1px solid #333', borderRadius: 8, color: '#fff', fontSize: 14, resize: 'vertical', boxSizing: 'border-box', outline: 'none' }} />
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button type="button" onClick={() => setShowResolveModal(false)}
                style={{ flex: 1, padding: '12px 0', background: '#333', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 48 }}>取消</button>
              <button type="button" onClick={handleResolve} disabled={processing || (selectedEx.type === 'return_dish' && !returnReason)}
                style={{
                  flex: 1, padding: '12px 0', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 600, cursor: 'pointer', minHeight: 48,
                  background: processing || (selectedEx.type === 'return_dish' && !returnReason) ? '#444' : '#FF6B35', color: '#fff',
                  opacity: processing ? 0.6 : 1,
                }}>
                {processing ? '处理中...' : '确认处理'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function FilterBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{
      padding: '6px 12px', borderRadius: 6, fontSize: 13, cursor: 'pointer', minHeight: 32,
      background: active ? 'rgba(255,107,53,0.15)' : 'transparent',
      border: active ? '1px solid #FF6B35' : '1px solid #333',
      color: active ? '#FF6B35' : '#9CA3AF',
      fontWeight: active ? 600 : 400,
    }}>
      {label}
    </button>
  );
}

const pageStyle: React.CSSProperties = {
  padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
};
