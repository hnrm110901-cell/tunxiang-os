/**
 * 闭店检查单 — /manager/closing-checklist
 * P0-12: 闭店检查（未结单/待开票/现金差异/清洁/设备关闭）
 * 对接 tx-ops E5-E6 节点
 *
 * API: GET  /api/v1/ops/checklists/closing?store_id=&date=
 *      POST /api/v1/ops/checklists/closing/submit
 *      GET  /api/v1/ops/daily-settlement/pre-check?store_id=
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import { txFetch } from '../../api';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type CheckStatus = 'unchecked' | 'pass' | 'fail' | 'na';

interface CheckItem {
  id: string;
  category: string;
  title: string;
  description: string;
  required: boolean;
  status: CheckStatus;
  note: string;
}

interface PreCheckSummary {
  unsettledOrderCount: number;
  pendingInvoiceCount: number;
  cashVarianceYuan: number;
  todayRevenueFen: number;
  todayOrders: number;
  shiftClosed: boolean;
}

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const STORE_ID = import.meta.env.VITE_STORE_ID || '';

// ─── Fallback ──────────────────────────────────────────────────────────────────

const FALLBACK_PRECHECK: PreCheckSummary = {
  unsettledOrderCount: 1,
  pendingInvoiceCount: 2,
  cashVarianceYuan: 0,
  todayRevenueFen: 856000,
  todayOrders: 42,
  shiftClosed: false,
};

const FALLBACK_ITEMS: CheckItem[] = [
  // 营业结清
  { id: 'b1', category: '营业结清', title: '未结单处理', description: '确认所有桌台订单已结算，无遗留未结单', required: true, status: 'unchecked', note: '' },
  { id: 'b2', category: '营业结清', title: '交接班完成', description: '当班收银员已完成交接班操作', required: true, status: 'unchecked', note: '' },
  { id: 'b3', category: '营业结清', title: '现金清点', description: '实际现金与系统金额核对一致', required: true, status: 'unchecked', note: '' },
  { id: 'b4', category: '营业结清', title: '待开发票处理', description: '处理当日所有待开发票请求', required: false, status: 'unchecked', note: '' },
  // 厨房闭店
  { id: 'k1', category: '厨房闭店', title: '灶台清洁', description: '所有灶台/炒锅清洁归位', required: true, status: 'unchecked', note: '' },
  { id: 'k2', category: '厨房闭店', title: '食材入库', description: '当日剩余食材分类入库冷藏', required: true, status: 'unchecked', note: '' },
  { id: 'k3', category: '厨房闭店', title: '活鲜缸检查', description: '确认活鲜缸水温/氧气正常，盖好防护网', required: true, status: 'unchecked', note: '' },
  { id: 'k4', category: '厨房闭店', title: '食品留样', description: '当日出品留样保存（125g/品种/48小时）', required: true, status: 'unchecked', note: '' },
  { id: 'k5', category: '厨房闭店', title: '冷柜温度记录', description: '记录所有冷藏/冷冻柜温度，确认在标准范围内', required: true, status: 'unchecked', note: '' },
  // 前厅闭店
  { id: 'f1', category: '前厅闭店', title: '桌椅归位', description: '所有桌椅摆放整齐，椅子倒扣', required: true, status: 'unchecked', note: '' },
  { id: 'f2', category: '前厅闭店', title: '地面清洁', description: '前厅地面拖洗干净无油渍', required: true, status: 'unchecked', note: '' },
  { id: 'f3', category: '前厅闭店', title: '洗手间终清', description: '洗手间最终清洁检查', required: true, status: 'unchecked', note: '' },
  { id: 'f4', category: '前厅闭店', title: '垃圾清运', description: '所有垃圾清运出店', required: true, status: 'unchecked', note: '' },
  // 安全关闭
  { id: 'a1', category: '安全关闭', title: '燃气总阀关闭', description: '关闭厨房燃气总阀', required: true, status: 'unchecked', note: '' },
  { id: 'a2', category: '安全关闭', title: '电器断电', description: '非必要电器断电（保留冷柜/活鲜缸/监控）', required: true, status: 'unchecked', note: '' },
  { id: 'a3', category: '安全关闭', title: '门窗锁闭', description: '所有门窗关闭上锁，启动防盗', required: true, status: 'unchecked', note: '' },
  { id: 'a4', category: '安全关闭', title: '监控确认', description: '确认监控系统正常运行', required: true, status: 'unchecked', note: '' },
];

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ClosingChecklistPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<CheckItem[]>(FALLBACK_ITEMS);
  const [preCheck, setPreCheck] = useState<PreCheckSummary>(FALLBACK_PRECHECK);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [expandedCategory, setExpandedCategory] = useState<string>('营业结清');
  const [noteModal, setNoteModal] = useState<string | null>(null);
  const [noteText, setNoteText] = useState('');

  // ─── 加载 ──────────────────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [checklistRes, preCheckRes] = await Promise.allSettled([
        txFetch<Record<string, unknown>>(`/api/v1/ops/checklists/closing?store_id=${STORE_ID}&date=${today()}`),
        txFetch<Record<string, unknown>>(`/api/v1/ops/daily-settlement/pre-check?store_id=${STORE_ID}`),
      ]);

      if (checklistRes.status === 'fulfilled' && checklistRes.value && Array.isArray(checklistRes.value.items)) {
        setItems((checklistRes.value.items as Record<string, unknown>[]).map(i => ({
          id: String(i.id), category: String(i.category || ''), title: String(i.title || ''),
          description: String(i.description || ''), required: Boolean(i.required),
          status: (i.status as CheckStatus) || 'unchecked', note: String(i.note || ''),
        })));
      }

      if (preCheckRes.status === 'fulfilled' && preCheckRes.value) {
        const p = preCheckRes.value;
        setPreCheck({
          unsettledOrderCount: Number(p.unsettled_order_count || 0),
          pendingInvoiceCount: Number(p.pending_invoice_count || 0),
          cashVarianceYuan: Number(p.cash_variance_yuan || 0),
          todayRevenueFen: Number(p.today_revenue_fen || 0),
          todayOrders: Number(p.today_orders || 0),
          shiftClosed: Boolean(p.shift_closed),
        });
      }
    } catch { /* fallback */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ─── 操作 ──────────────────────────────────────────────────────────────────

  const toggleItem = (itemId: string, newStatus: CheckStatus) => {
    setItems(prev => prev.map(i => i.id === itemId ? { ...i, status: newStatus } : i));
    txFetch(`/api/v1/ops/checklists/closing/items/${itemId}/check`, {
      method: 'POST', body: JSON.stringify({ status: newStatus }),
    }).catch(() => {});
  };

  const saveNote = (itemId: string) => {
    setItems(prev => prev.map(i => i.id === itemId ? { ...i, note: noteText } : i));
    setNoteModal(null);
  };

  const handleSubmit = async () => {
    const requiredUnchecked = items.filter(i => i.required && i.status === 'unchecked');
    if (requiredUnchecked.length > 0) {
      setExpandedCategory(requiredUnchecked[0].category);
      return;
    }
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/checklists/closing/submit', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID, date: today(),
          items: items.map(i => ({ id: i.id, status: i.status, note: i.note })),
        }),
      });
    } catch { /* offline */ }
    setCompleted(true);
    setSubmitting(false);
  };

  // ─── 统计 ──────────────────────────────────────────────────────────────────

  const total = items.length;
  const checked = items.filter(i => i.status !== 'unchecked').length;
  const failed = items.filter(i => i.status === 'fail').length;
  const progress = total > 0 ? Math.round((checked / total) * 100) : 0;
  const categories = [...new Set(items.map(i => i.category))];
  const hasBlockers = preCheck.unsettledOrderCount > 0 || !preCheck.shiftClosed;

  // ─── 已完成 ──────────────────────────────────────────────────────────────

  if (completed) {
    return (
      <div style={pageStyle}>
        <div style={{ textAlign: 'center', paddingTop: 60 }}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>🌙</div>
          <div style={{ fontSize: 22, fontWeight: 600, marginBottom: 8, color: '#52c41a' }}>闭店检查已完成</div>
          <div style={{ fontSize: 16, color: '#9CA3AF', marginBottom: 6 }}>
            今日营业额: <strong style={{ color: '#FF6B35' }}>{fen2yuan(preCheck.todayRevenueFen)}</strong> · {preCheck.todayOrders}单
          </div>
          <div style={{ fontSize: 14, color: '#6B7280' }}>{today()}</div>
          <button type="button" onClick={() => navigate(-1)}
            style={{ marginTop: 32, padding: '14px 48px', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 10, fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 52 }}>
            返回
          </button>
        </div>
      </div>
    );
  }

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>闭店检查单</div>
          <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>{today()}</div>
        </div>
        <button type="button" onClick={() => navigate(-1)} style={backBtnStyle}>← 返回</button>
      </div>

      {/* 营业概览 + 阻断提示 */}
      <div style={{ background: '#112228', borderRadius: 10, padding: 16, marginBottom: 16 }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 10 }}>今日营业概览</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <SummaryCard label="营业额" value={fen2yuan(preCheck.todayRevenueFen)} color="#FF6B35" />
          <SummaryCard label="订单数" value={`${preCheck.todayOrders} 单`} color="#fff" />
        </div>
      </div>

      {/* 阻断项 */}
      {hasBlockers && (
        <div style={{ background: 'rgba(255,77,79,0.08)', border: '1px solid rgba(255,77,79,0.3)', borderRadius: 10, padding: 14, marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#ff4d4f', marginBottom: 8 }}>需要处理</div>
          {preCheck.unsettledOrderCount > 0 && (
            <div style={{ fontSize: 14, color: '#ff4d4f', marginBottom: 4 }}>
              · 有 <strong>{preCheck.unsettledOrderCount}</strong> 笔未结单
            </div>
          )}
          {!preCheck.shiftClosed && (
            <div style={{ fontSize: 14, color: '#faad14', marginBottom: 4 }}>
              · 当班尚未交接
            </div>
          )}
          {preCheck.pendingInvoiceCount > 0 && (
            <div style={{ fontSize: 14, color: '#faad14' }}>
              · 有 {preCheck.pendingInvoiceCount} 张待开发票
            </div>
          )}
          {preCheck.cashVarianceYuan !== 0 && (
            <div style={{ fontSize: 14, color: '#ff4d4f' }}>
              · 现金差异: ¥{preCheck.cashVarianceYuan.toFixed(2)}
            </div>
          )}
        </div>
      )}

      {/* 进度条 */}
      <div style={{ background: '#112228', borderRadius: 10, padding: 14, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>检查进度</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: progress === 100 ? '#52c41a' : '#FF6B35' }}>{progress}%</span>
        </div>
        <div style={{ height: 6, background: '#1a2a33', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${progress}%`, background: progress === 100 ? '#52c41a' : '#FF6B35', borderRadius: 3, transition: 'width 300ms ease' }} />
        </div>
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {/* 分类列表 */}
      {categories.map(cat => {
        const catItems = items.filter(i => i.category === cat);
        const catChecked = catItems.filter(i => i.status !== 'unchecked').length;
        const isExpanded = expandedCategory === cat;

        return (
          <div key={cat} style={{ marginBottom: 10 }}>
            <button type="button" onClick={() => setExpandedCategory(isExpanded ? '' : cat)}
              style={{
                width: '100%', padding: '12px 16px', background: '#112228', border: 'none',
                borderRadius: isExpanded ? '10px 10px 0 0' : 10,
                color: '#fff', fontSize: 16, fontWeight: 600, cursor: 'pointer',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', minHeight: 48,
              }}>
              <span>{cat}</span>
              <span style={{ fontSize: 13, color: catChecked === catItems.length ? '#52c41a' : '#9CA3AF' }}>
                {catChecked}/{catItems.length} {isExpanded ? '▼' : '▶'}
              </span>
            </button>

            {isExpanded && catItems.map(item => (
              <div key={item.id} style={{
                padding: '12px 16px', background: '#0e1e25', borderBottom: '1px solid #1a2a33',
                display: 'flex', gap: 10, alignItems: 'flex-start',
              }}>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0, paddingTop: 2 }}>
                  <CheckBtn label="✓" active={item.status === 'pass'} color="#52c41a"
                    onClick={() => toggleItem(item.id, item.status === 'pass' ? 'unchecked' : 'pass')} />
                  <CheckBtn label="✗" active={item.status === 'fail'} color="#ff4d4f"
                    onClick={() => toggleItem(item.id, item.status === 'fail' ? 'unchecked' : 'fail')} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 500, color: item.status === 'fail' ? '#ff4d4f' : '#fff' }}>
                    {item.title}{item.required && <span style={{ color: '#ff4d4f', marginLeft: 4 }}>*</span>}
                  </div>
                  <div style={{ fontSize: 13, color: '#6B7280', marginTop: 2 }}>{item.description}</div>
                  {item.note && <div style={{ fontSize: 13, color: '#faad14', marginTop: 4 }}>备注: {item.note}</div>}
                  <button type="button" onClick={() => { setNoteModal(item.id); setNoteText(item.note); }}
                    style={{ marginTop: 4, padding: '3px 8px', background: 'transparent', border: '1px solid #333', borderRadius: 4, color: '#6B7280', fontSize: 12, cursor: 'pointer' }}>
                    {item.note ? '改备注' : '+ 备注'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        );
      })}

      {/* 提交 */}
      <div style={{ marginTop: 16, paddingBottom: 20 }}>
        <button type="button" onClick={handleSubmit} disabled={submitting || checked === 0}
          style={{
            width: '100%', padding: '16px 0', border: 'none', borderRadius: 10, fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 56,
            background: checked > 0 && !submitting ? '#FF6B35' : '#444', color: '#fff', opacity: submitting ? 0.6 : 1,
          }}>
          {submitting ? '提交中...' : `提交闭店检查 (${checked}/${total}${failed > 0 ? ` · ${failed}异常` : ''})`}
        </button>
        {hasBlockers && (
          <div style={{ fontSize: 13, color: '#faad14', textAlign: 'center', marginTop: 8 }}>
            仍有未处理的阻断项，提交后将记录异常
          </div>
        )}
      </div>

      {/* 备注弹窗 */}
      {noteModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }} onClick={() => setNoteModal(null)}>
          <div style={{ background: '#1a2a33', borderRadius: '16px 16px 0 0', padding: 20, width: '100%', maxWidth: 500 }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>添加备注</div>
            <textarea value={noteText} onChange={e => setNoteText(e.target.value)} rows={3} placeholder="描述异常情况..."
              style={{ width: '100%', padding: 10, background: '#112228', border: '1px solid #333', borderRadius: 8, color: '#fff', fontSize: 16, resize: 'none', boxSizing: 'border-box', outline: 'none' }} />
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <button type="button" onClick={() => setNoteModal(null)}
                style={{ flex: 1, padding: '12px 0', background: '#333', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 48 }}>取消</button>
              <button type="button" onClick={() => saveNote(noteModal)}
                style={{ flex: 1, padding: '12px 0', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 500, cursor: 'pointer', minHeight: 48 }}>保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function CheckBtn({ label, active, color, onClick }: { label: string; active: boolean; color: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{
      width: 44, height: 44, borderRadius: 8, fontSize: 16, fontWeight: 700, cursor: 'pointer',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: active ? color : 'transparent',
      border: `2px solid ${active ? color : '#333'}`,
      color: active ? '#fff' : '#6B7280',
      transition: 'all 150ms ease',
    }}>
      {label}
    </button>
  );
}

function SummaryCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ padding: 12, background: '#0e1e25', borderRadius: 8, textAlign: 'center' }}>
      <div style={{ fontSize: 12, color: '#9CA3AF', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

const pageStyle: React.CSSProperties = {
  padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
  maxWidth: 500, margin: '0 auto',
};

const backBtnStyle: React.CSSProperties = {
  padding: '6px 14px', background: '#1a2a33', color: '#9CA3AF', border: '1px solid #333',
  borderRadius: 6, fontSize: 14, cursor: 'pointer', minHeight: 36,
};
