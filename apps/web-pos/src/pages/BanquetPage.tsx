/**
 * 宴会管理页面 — POS端全流程
 * 看板视图 + 新建宴会 + 合同详情 + 阶段操作
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '';

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(TENANT ? { 'X-Tenant-ID': TENANT } : {}) };
  const resp = await fetch(`${BASE}${path}`, { ...options, headers: { ...headers, ...(options.headers as Record<string, string> || {}) } });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`;

// ── 类型 ──

interface BanquetLead {
  lead_id: string;
  customer_name: string;
  phone: string;
  event_type: string;
  event_date: string;
  guest_count: number;
  budget_per_person_fen: number;
  stage: string;
  contract_id?: string;
  notes: string;
  created_at: string;
}

type Tab = 'board' | 'create' | 'contracts';

const EVENT_TYPES = [
  { key: 'wedding', label: '婚宴', color: '#e6002d', bg: '#e6002d22' },
  { key: 'birthday', label: '寿宴', color: '#faad14', bg: '#faad1422' },
  { key: 'business', label: '商务宴', color: '#185FA5', bg: '#185FA522' },
  { key: 'team_building', label: '团建', color: '#0F6E56', bg: '#0F6E5622' },
  { key: 'anniversary', label: '周年庆', color: '#722ed1', bg: '#722ed122' },
];

const STAGES = [
  { key: 'lead', label: '线索' },
  { key: 'consultation', label: '咨询' },
  { key: 'proposal', label: '方案' },
  { key: 'quotation', label: '报价' },
  { key: 'contract', label: '签约' },
  { key: 'deposit_paid', label: '已收定金' },
  { key: 'menu_confirmed', label: '菜单确认' },
  { key: 'preparation', label: '备料' },
  { key: 'execution', label: '执行中' },
  { key: 'settlement', label: '结算' },
  { key: 'feedback', label: '反馈' },
  { key: 'archived', label: '归档' },
];

const BOARD_STAGES = ['lead', 'quotation', 'contract', 'deposit_paid', 'menu_confirmed', 'execution', 'settlement'];

export function BanquetPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('board');
  const [leads, setLeads] = useState<BanquetLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<BanquetLead | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // 创建表单
  const [form, setForm] = useState({ customer_name: '', phone: '', event_type: 'wedding', event_date: '', guest_count: 10, budget_per_person_fen: 98800, notes: '' });
  const [creating, setCreating] = useState(false);

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const data = await txFetch<{ items: BanquetLead[] }>(`/api/v1/banquets/leads?store_id=${STORE_ID}`);
      setLeads(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadLeads(); }, [loadLeads]);

  const getEventConfig = (type: string) => EVENT_TYPES.find(e => e.key === type) || EVENT_TYPES[0];
  const getStageLabel = (stage: string) => STAGES.find(s => s.key === stage)?.label || stage;

  // ── 阶段操作 ──
  const advanceStage = async (leadId: string, nextStage: string) => {
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/banquets/leads/${leadId}/stage`, { method: 'PUT', body: JSON.stringify({ next_stage: nextStage }) });
      await loadLeads();
      setSelected(prev => prev ? { ...prev, stage: nextStage } : null);
    } catch (err) { alert(err instanceof Error ? err.message : '操作失败'); }
    finally { setActionLoading(false); }
  };

  const createQuotation = async (leadId: string) => {
    setActionLoading(true);
    try {
      await txFetch('/api/v1/banquets/quotations', { method: 'POST', body: JSON.stringify({ lead_id: leadId, menu_tier: 'standard', per_person_fen: 98800, table_count: 5, notes: '' }) });
      await loadLeads();
    } catch (err) { alert(err instanceof Error ? err.message : '创建报价失败'); }
    finally { setActionLoading(false); }
  };

  const handleCreate = async () => {
    if (!form.customer_name || !form.phone || !form.event_date) return;
    setCreating(true);
    try {
      await txFetch('/api/v1/banquets/leads', { method: 'POST', body: JSON.stringify({ ...form, store_id: STORE_ID }) });
      await loadLeads();
      setTab('board');
      setForm({ customer_name: '', phone: '', event_type: 'wedding', event_date: '', guest_count: 10, budget_per_person_fen: 98800, notes: '' });
    } catch (err) { alert(err instanceof Error ? err.message : '创建失败'); }
    finally { setCreating(false); }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' }}>
      {/* 左侧主区 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* 顶部 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderBottom: '1px solid #1a2a33', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button onClick={() => navigate('/tables')} style={backBtn}>{'<'} 返回</button>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>宴会管理</h2>
          </div>
          <div style={{ display: 'flex', gap: 4, background: '#112228', borderRadius: 10, padding: 3 }}>
            {([['board', '看板'], ['create', '新建'], ['contracts', '合同']] as [Tab, string][]).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: tab === k ? '#FF6B2C' : 'transparent', color: '#fff', fontSize: 15, fontWeight: tab === k ? 700 : 400, cursor: 'pointer' }}>{l}</button>
            ))}
          </div>
        </div>

        {/* 内容区 */}
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          {loading && <div style={{ textAlign: 'center', padding: 60, color: '#8A94A4' }}>加载中...</div>}
          {error && <div style={{ textAlign: 'center', padding: 40, color: '#ff4d4f' }}>{error}<br /><button onClick={loadLeads} style={{ marginTop: 12, padding: '8px 20px', background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>重试</button></div>}

          {/* 看板 */}
          {!loading && !error && tab === 'board' && (
            <div style={{ display: 'flex', gap: 12, overflowX: 'auto', minHeight: '100%' }}>
              {BOARD_STAGES.map(stageKey => {
                const stageLeads = leads.filter(l => l.stage === stageKey);
                return (
                  <div key={stageKey} style={{ minWidth: 220, flex: '0 0 220px', display: 'flex', flexDirection: 'column' }}>
                    <div style={{ padding: '8px 12px', background: '#112228', borderRadius: '10px 10px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 15, fontWeight: 700 }}>{getStageLabel(stageKey)}</span>
                      <span style={{ fontSize: 13, color: '#8A94A4', background: '#1a2a33', padding: '2px 8px', borderRadius: 10 }}>{stageLeads.length}</span>
                    </div>
                    <div style={{ flex: 1, background: '#0d1f28', borderRadius: '0 0 10px 10px', padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {stageLeads.length === 0 && <div style={{ color: '#555', fontSize: 13, textAlign: 'center', padding: 20 }}>暂无</div>}
                      {stageLeads.map(lead => {
                        const evtCfg = getEventConfig(lead.event_type);
                        return (
                          <button key={lead.lead_id} onClick={() => setSelected(lead)} style={{
                            width: '100%', padding: 12, borderRadius: 10, background: '#112228', border: selected?.lead_id === lead.lead_id ? '2px solid #FF6B2C' : '2px solid transparent',
                            color: '#fff', textAlign: 'left', cursor: 'pointer',
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                              <span style={{ fontWeight: 600, fontSize: 15 }}>{lead.customer_name}</span>
                              <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 6, background: evtCfg.bg, color: evtCfg.color }}>{evtCfg.label}</span>
                            </div>
                            <div style={{ fontSize: 13, color: '#8A94A4' }}>{lead.event_date} · {lead.guest_count}人</div>
                            <div style={{ fontSize: 14, color: '#FF6B2C', fontWeight: 600, marginTop: 4 }}>{fen2yuan(lead.budget_per_person_fen)}/人</div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 新建 */}
          {!loading && !error && tab === 'create' && (
            <div style={{ maxWidth: 600, margin: '0 auto' }}>
              <div style={cardStyle}>
                <h3 style={{ margin: '0 0 20px', fontSize: 20 }}>新建宴会线索</h3>
                <Field label="客户姓名 *"><input value={form.customer_name} onChange={e => setForm(f => ({ ...f, customer_name: e.target.value }))} style={inputStyle} placeholder="张总" /></Field>
                <Field label="联系电话 *"><input value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} style={inputStyle} placeholder="13800138000" /></Field>
                <Field label="宴会类型">
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {EVENT_TYPES.map(e => (
                      <button key={e.key} onClick={() => setForm(f => ({ ...f, event_type: e.key }))} style={{
                        padding: '10px 16px', borderRadius: 8, border: form.event_type === e.key ? `2px solid ${e.color}` : '2px solid #1a2a33',
                        background: form.event_type === e.key ? e.bg : '#0B1A20', color: form.event_type === e.key ? e.color : '#999', fontSize: 15, cursor: 'pointer',
                      }}>{e.label}</button>
                    ))}
                  </div>
                </Field>
                <Field label="宴会日期 *"><input type="date" value={form.event_date} onChange={e => setForm(f => ({ ...f, event_date: e.target.value }))} style={inputStyle} /></Field>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <Field label="预计人数"><input type="number" value={form.guest_count} onChange={e => setForm(f => ({ ...f, guest_count: Number(e.target.value) }))} style={inputStyle} /></Field>
                  <Field label="人均预算(元)"><input type="number" value={form.budget_per_person_fen / 100} onChange={e => setForm(f => ({ ...f, budget_per_person_fen: Math.round(Number(e.target.value) * 100) }))} style={inputStyle} /></Field>
                </div>
                <Field label="备注"><textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} style={{ ...inputStyle, minHeight: 60, resize: 'vertical' }} placeholder="特殊要求、忌口、布置等" /></Field>
                <button onClick={handleCreate} disabled={creating || !form.customer_name || !form.phone || !form.event_date} style={{
                  width: '100%', padding: 16, borderRadius: 12, border: 'none', background: creating ? '#444' : '#FF6B2C', color: '#fff', fontSize: 18, fontWeight: 700, cursor: creating ? 'not-allowed' : 'pointer', minHeight: 56, marginTop: 8,
                }}>{creating ? '创建中...' : '创建宴会线索'}</button>
              </div>
            </div>
          )}

          {/* 合同 (简化列表) */}
          {!loading && !error && tab === 'contracts' && (
            <div>
              {leads.filter(l => ['contract', 'deposit_paid', 'menu_confirmed', 'preparation', 'execution', 'settlement'].includes(l.stage)).length === 0 && (
                <div style={{ textAlign: 'center', padding: 60, color: '#666' }}>暂无合同</div>
              )}
              {leads.filter(l => ['contract', 'deposit_paid', 'menu_confirmed', 'preparation', 'execution', 'settlement'].includes(l.stage)).map(lead => {
                const evtCfg = getEventConfig(lead.event_type);
                return (
                  <button key={lead.lead_id} onClick={() => { setSelected(lead); setTab('board'); }} style={{ ...poCardStyle }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span style={{ fontSize: 18, fontWeight: 700 }}>{lead.customer_name} — {evtCfg.label}</span>
                      <span style={{ padding: '4px 12px', borderRadius: 8, background: evtCfg.bg, color: evtCfg.color, fontSize: 14, fontWeight: 600 }}>{getStageLabel(lead.stage)}</span>
                    </div>
                    <div style={{ color: '#8A94A4' }}>{lead.event_date} · {lead.guest_count}人 · {fen2yuan(lead.budget_per_person_fen)}/人</div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* 右侧详情面板 */}
      {selected && (
        <div style={{ width: 380, background: '#112228', borderLeft: '1px solid #1a2a33', padding: 20, overflowY: 'auto', flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ margin: 0, fontSize: 20 }}>宴会详情</h3>
            <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', color: '#999', fontSize: 20, cursor: 'pointer' }}>✕</button>
          </div>

          {/* 客户信息 */}
          <div style={{ ...cardStyle, marginBottom: 12 }}>
            <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>{selected.customer_name}</div>
            <div style={{ color: '#8A94A4', marginBottom: 8 }}>{selected.phone}</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Badge bg={getEventConfig(selected.event_type).bg} color={getEventConfig(selected.event_type).color}>{getEventConfig(selected.event_type).label}</Badge>
              <Badge bg="#1a2a33" color="#8A94A4">{selected.event_date}</Badge>
              <Badge bg="#1a2a33" color="#8A94A4">{selected.guest_count}人</Badge>
              <Badge bg="#FF6B2C22" color="#FF6B2C">{fen2yuan(selected.budget_per_person_fen)}/人</Badge>
            </div>
          </div>

          {/* 阶段时间线 */}
          <div style={{ ...cardStyle, marginBottom: 12 }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: '#8A94A4' }}>进度</div>
            {STAGES.filter(s => BOARD_STAGES.includes(s.key) || s.key === selected.stage).map((stage, idx) => {
              const isCurrent = stage.key === selected.stage;
              const isPast = STAGES.findIndex(s => s.key === selected.stage) > STAGES.findIndex(s => s.key === stage.key);
              return (
                <div key={stage.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
                  <div style={{
                    width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, flexShrink: 0,
                    background: isCurrent ? '#FF6B2C' : isPast ? '#0F6E56' : '#1a2a33', color: '#fff',
                  }}>{isPast ? '✓' : idx + 1}</div>
                  <span style={{ fontSize: 15, fontWeight: isCurrent ? 700 : 400, color: isCurrent ? '#FF6B2C' : isPast ? '#0F6E56' : '#666' }}>{stage.label}</span>
                </div>
              );
            })}
          </div>

          {/* 操作按钮 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {selected.stage === 'lead' && (
              <ActionBtn onClick={() => createQuotation(selected.lead_id)} loading={actionLoading}>创建报价</ActionBtn>
            )}
            {selected.stage === 'quotation' && (
              <ActionBtn onClick={() => advanceStage(selected.lead_id, 'contract')} loading={actionLoading}>签约</ActionBtn>
            )}
            {selected.stage === 'contract' && (
              <ActionBtn onClick={() => advanceStage(selected.lead_id, 'deposit_paid')} loading={actionLoading}>确认收定金</ActionBtn>
            )}
            {selected.stage === 'deposit_paid' && (
              <ActionBtn onClick={() => advanceStage(selected.lead_id, 'menu_confirmed')} loading={actionLoading}>确认菜单</ActionBtn>
            )}
            {selected.stage === 'menu_confirmed' && (
              <ActionBtn onClick={() => advanceStage(selected.lead_id, 'execution')} loading={actionLoading} accent>开始执行</ActionBtn>
            )}
            {selected.stage === 'execution' && (
              <ActionBtn onClick={() => advanceStage(selected.lead_id, 'settlement')} loading={actionLoading}>结算</ActionBtn>
            )}
            {selected.stage === 'settlement' && (
              <ActionBtn onClick={() => advanceStage(selected.lead_id, 'archived')} loading={actionLoading}>归档</ActionBtn>
            )}
          </div>

          {selected.notes && (
            <div style={{ ...cardStyle, marginTop: 12 }}>
              <div style={{ fontSize: 14, color: '#8A94A4', marginBottom: 4 }}>备注</div>
              <div style={{ fontSize: 15 }}>{selected.notes}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 子组件 ──

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div style={{ marginBottom: 14 }}><label style={{ display: 'block', fontSize: 14, color: '#8A94A4', marginBottom: 6 }}>{label}</label>{children}</div>;
}

function Badge({ children, bg, color }: { children: React.ReactNode; bg: string; color: string }) {
  return <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 13, fontWeight: 600, background: bg, color }}>{children}</span>;
}

function ActionBtn({ children, onClick, loading, accent }: { children: React.ReactNode; onClick: () => void; loading: boolean; accent?: boolean }) {
  return (
    <button onClick={onClick} disabled={loading} style={{
      width: '100%', padding: 14, borderRadius: 10, border: accent ? 'none' : '1.5px solid #FF6B2C', minHeight: 48,
      background: accent ? '#FF6B2C' : 'transparent', color: accent ? '#fff' : '#FF6B2C',
      fontSize: 16, fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
    }}>{loading ? '处理中...' : children}</button>
  );
}

// ── 样式 ──
const cardStyle: React.CSSProperties = { background: '#0B1A20', borderRadius: 12, padding: 16 };
const inputStyle: React.CSSProperties = { width: '100%', padding: '12px 14px', borderRadius: 8, border: '1.5px solid #1a2a33', background: '#112228', color: '#fff', fontSize: 16, outline: 'none', boxSizing: 'border-box' };
const backBtn: React.CSSProperties = { minHeight: 44, padding: '8px 16px', background: '#112228', border: '1px solid #1a2a33', borderRadius: 8, color: '#fff', fontSize: 16, cursor: 'pointer' };
const poCardStyle: React.CSSProperties = { width: '100%', padding: 20, marginBottom: 10, borderRadius: 12, background: '#112228', border: '2px solid #1a2a33', color: '#fff', textAlign: 'left', cursor: 'pointer' };
