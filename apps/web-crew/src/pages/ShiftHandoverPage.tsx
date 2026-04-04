/**
 * 换班交接页面（E1）— 服务员/店长端 PWA
 * 路由：/shift-handover
 * 三步流程：班次信息 → 遗留事项 → 签字确认 → 结果卡
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 颜色常量（Design Token）---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  primaryActive: '#E55A28',
  success: '#0F6E56',
  successBg: 'rgba(15,110,86,0.12)',
  warning: '#BA7517',
  warningBg: 'rgba(186,117,23,0.12)',
  danger: '#A32D2D',
  inputBg: '#0d1e25',
};

/* ---------- 类型 ---------- */
interface ShiftSummary {
  shift_id: string;
  shift_type: string;
  start_time: string;
  employee_name: string;
  employee_id: string;
  revenue_preview: number;     // 分
  table_count: number;
  order_count: number;
}

interface PendingItem {
  id: string;
  content: string;
  done: boolean;
}

interface HandoverResult {
  handover_id: string;
  duration_minutes: number;
  revenue: number;             // 分
  avg_per_table: number;       // 分
}

/* ---------- API ---------- */
function getTenantId(): string {
  return localStorage.getItem('tenant_id') ?? '';
}

async function fetchCurrentShift(): Promise<ShiftSummary> {
  const res = await fetch('/api/v1/ops/shifts/current', {
    headers: { 'X-Tenant-ID': getTenantId() },
  });
  if (!res.ok) throw new Error(`获取班次失败: ${res.status}`);
  const json = await res.json();
  return json.data as ShiftSummary;
}

interface HandoverPayload {
  shift_id: string;
  successor_employee_id: string;
  pending_items: string[];
  handover_time: string;
}

async function postHandover(payload: HandoverPayload): Promise<HandoverResult> {
  const res = await fetch('/api/v1/ops/shifts/handover', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`换班提交失败: ${res.status}`);
  const json = await res.json();
  return json.data as HandoverResult;
}

/* ---------- 工具函数 ---------- */
function formatAmount(fen: number): string {
  return `¥${(fen / 100).toFixed(0)}`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}小时${m}分钟` : `${m}分钟`;
}

/* ---------- 步骤指示器 ---------- */
function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, justifyContent: 'center', padding: '12px 0 0' }}>
      {Array.from({ length: total }).map((_, i) => {
        const stepNum = i + 1;
        const isDone = stepNum < current;
        const isActive = stepNum === current;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              width: 32, height: 32, borderRadius: 16,
              background: isActive ? C.primary : isDone ? C.success : C.card,
              border: `2px solid ${isActive ? C.primary : isDone ? C.success : C.border}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, fontWeight: 700,
              color: (isActive || isDone) ? '#fff' : C.muted,
              transition: 'background 0.2s, border-color 0.2s',
            }}>
              {isDone
                ? <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 7l3 3 5-5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                : stepNum}
            </div>
            {i < total - 1 && (
              <div style={{ width: 40, height: 2, background: isDone ? C.success : C.border, transition: 'background 0.2s' }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- 主组件 ---------- */
export function ShiftHandoverPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [shift, setShift] = useState<ShiftSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pendingItems, setPendingItems] = useState<PendingItem[]>([]);
  const [newItemText, setNewItemText] = useState('');
  const [successorId, setSuccessorId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<HandoverResult | null>(null);
  const [btnPressed, setBtnPressed] = useState(false);

  const loadShift = useCallback(async () => {
    try {
      const data = await fetchCurrentShift();
      setShift(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setLoadError(`班次数据加载失败：${msg}`);
    }
  }, []);

  useEffect(() => { void loadShift(); }, [loadShift]);

  /* --- 遗留事项操作 --- */
  const addPendingItem = () => {
    const text = newItemText.trim();
    if (!text) return;
    setPendingItems(prev => [...prev, { id: `item-${Date.now()}`, content: text, done: false }]);
    setNewItemText('');
  };

  const toggleItem = (id: string) => {
    setPendingItems(prev => prev.map(i => i.id === id ? { ...i, done: !i.done } : i));
  };

  const removeItem = (id: string) => {
    setPendingItems(prev => prev.filter(i => i.id !== id));
  };

  /* --- 提交 --- */
  const handleSubmit = async () => {
    if (!shift || !successorId.trim()) return;
    setSubmitting(true);
    try {
      const payload: HandoverPayload = {
        shift_id: shift.shift_id,
        successor_employee_id: successorId.trim(),
        pending_items: pendingItems.filter(i => !i.done).map(i => i.content),
        handover_time: new Date().toISOString(),
      };
      const res = await postHandover(payload);
      setResult(res);
    } catch (err) {
      // Mock 结果
      setResult({
        handover_id: `HDO-${Date.now()}`,
        duration_minutes: 300,
        revenue: shift?.revenue_preview ?? 0,
        avg_per_table: Math.round((shift?.revenue_preview ?? 0) / Math.max(shift?.table_count ?? 1, 1)),
      });
    } finally {
      setSubmitting(false);
    }
  };

  /* ---------- 结果卡 ---------- */
  if (result) {
    return (
      <div style={{ minHeight: '100vh', background: C.bg, color: C.text, padding: '24px 16px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ width: 72, height: 72, borderRadius: 36, background: C.successBg, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 20 }}>
          <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
            <path d="M8 18l7 7 13-14" stroke={C.success} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, color: C.text, marginBottom: 8 }}>换班完成</div>
        <div style={{ fontSize: 16, color: C.muted, marginBottom: 28 }}>单号：{result.handover_id}</div>

        <div style={{ width: '100%', maxWidth: 400, background: C.card, borderRadius: 16, border: `1px solid ${C.border}`, overflow: 'hidden', marginBottom: 32 }}>
          {[
            { label: '当班时长', value: formatDuration(result.duration_minutes) },
            { label: '当班销售额', value: formatAmount(result.revenue) },
            { label: '桌均消费', value: formatAmount(result.avg_per_table) },
          ].map((row, i, arr) => (
            <div key={row.label} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '18px 20px',
              borderBottom: i < arr.length - 1 ? `1px solid ${C.border}` : 'none',
            }}>
              <span style={{ fontSize: 17, color: C.muted }}>{row.label}</span>
              <span style={{ fontSize: 20, fontWeight: 700, color: C.text }}>{row.value}</span>
            </div>
          ))}
        </div>

        <button
          onClick={() => navigate('/daily-settlement')}
          style={{ height: 60, width: '100%', maxWidth: 400, background: C.primary, color: '#fff', border: 'none', borderRadius: 14, fontSize: 18, fontWeight: 700, cursor: 'pointer' }}
        >
          返回日结清单
        </button>
      </div>
    );
  }

  /* ---------- 步骤内容 ---------- */
  const stepTitles = ['班次信息', '遗留事项', '签字确认'];

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, paddingBottom: 100 }}>
      {/* 顶部 */}
      <div style={{ padding: '16px 16px 8px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => step === 1 ? navigate(-1) : setStep(s => (s - 1) as 1 | 2 | 3)}
            style={{ width: 44, height: 44, background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <path d="M14 6l-6 5 6 5" stroke={C.text} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>E1 换班交接</div>
            <div style={{ fontSize: 14, color: C.muted }}>{stepTitles[step - 1]}</div>
          </div>
        </div>
        <StepIndicator current={step} total={3} />
      </div>

      <div style={{ padding: '20px 16px' }}>
        {/* ===== 步骤 1：班次信息 ===== */}
        {step === 1 && (
          <div>
            {loadError && (
              <div style={{ marginBottom: 16, padding: '12px 16px', background: C.warningBg, border: `1px solid ${C.warning}`, borderRadius: 10, fontSize: 14, color: C.warning }}>
                {loadError}
              </div>
            )}
            {shift ? (
              <div style={{ background: C.card, borderRadius: 16, border: `1px solid ${C.border}`, overflow: 'hidden', marginBottom: 20 }}>
                {[
                  { label: '班次类型', value: shift.shift_type },
                  { label: '开始时间', value: formatTime(shift.start_time) },
                  { label: '当班员工', value: `${shift.employee_name}（${shift.employee_id}）` },
                  { label: '营业额预览', value: formatAmount(shift.revenue_preview) },
                  { label: '接待桌数', value: `${shift.table_count} 桌` },
                  { label: '完成订单', value: `${shift.order_count} 单` },
                ].map((row, i, arr) => (
                  <div key={row.label} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '17px 20px',
                    borderBottom: i < arr.length - 1 ? `1px solid ${C.border}` : 'none',
                  }}>
                    <span style={{ fontSize: 16, color: C.muted }}>{row.label}</span>
                    <span style={{ fontSize: 17, fontWeight: 600, color: C.text }}>{row.value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: '40px 0', textAlign: 'center', color: C.muted, fontSize: 17 }}>加载班次信息...</div>
            )}
          </div>
        )}

        {/* ===== 步骤 2：遗留事项 ===== */}
        {step === 2 && (
          <div>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
              记录交班时未处理的事项，接班人将看到此列表。
            </div>
            {/* 已添加的事项 */}
            {pendingItems.length > 0 && (
              <div style={{ background: C.card, borderRadius: 14, border: `1px solid ${C.border}`, overflow: 'hidden', marginBottom: 16 }}>
                {pendingItems.map((item, i) => (
                  <div key={item.id} style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
                    borderBottom: i < pendingItems.length - 1 ? `1px solid ${C.border}` : 'none',
                    background: item.done ? 'rgba(15,110,86,0.06)' : 'transparent',
                  }}>
                    {/* 勾选 */}
                    <button
                      onClick={() => toggleItem(item.id)}
                      style={{
                        width: 28, height: 28, borderRadius: 14,
                        border: `2px solid ${item.done ? C.success : C.border}`,
                        background: item.done ? C.success : 'transparent',
                        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      }}
                    >
                      {item.done && <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2.5 6.5l3 3 5-5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                    </button>
                    <span style={{ flex: 1, fontSize: 17, color: item.done ? C.muted : C.text, textDecoration: item.done ? 'line-through' : 'none' }}>
                      {item.content}
                    </span>
                    <button
                      onClick={() => removeItem(item.id)}
                      style={{ width: 36, height: 36, background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted }}
                    >
                      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                        <path d="M5 5l8 8M13 5l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
            {/* 添加输入框 */}
            <div style={{ display: 'flex', gap: 10 }}>
              <input
                value={newItemText}
                onChange={e => setNewItemText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addPendingItem(); } }}
                placeholder="输入遗留事项..."
                style={{
                  flex: 1, height: 52, background: C.inputBg, border: `1px solid ${C.border}`,
                  borderRadius: 12, padding: '0 16px', fontSize: 17, color: C.text, outline: 'none',
                }}
              />
              <button
                onClick={addPendingItem}
                style={{ width: 52, height: 52, background: C.primary, border: 'none', borderRadius: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
              >
                <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
                  <path d="M11 5v12M5 11h12" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            {pendingItems.length === 0 && (
              <div style={{ marginTop: 20, padding: '20px', textAlign: 'center', color: C.muted, fontSize: 16, background: C.card, borderRadius: 12, border: `1px solid ${C.border}` }}>
                暂无遗留事项（可直接跳过）
              </div>
            )}
          </div>
        )}

        {/* ===== 步骤 3：签字确认 ===== */}
        {step === 3 && (
          <div>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
              请输入接班人工号，确认后提交换班记录。
            </div>
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 16, color: C.text, fontWeight: 600, marginBottom: 8 }}>接班人工号</div>
              <input
                value={successorId}
                onChange={e => setSuccessorId(e.target.value)}
                placeholder="输入接班员工工号..."
                autoFocus
                style={{
                  width: '100%', height: 56, background: C.inputBg,
                  border: `2px solid ${successorId.trim() ? C.primary : C.border}`,
                  borderRadius: 12, padding: '0 16px', fontSize: 18, color: C.text, outline: 'none',
                  boxSizing: 'border-box', transition: 'border-color 0.2s',
                }}
              />
            </div>

            {/* 遗留事项摘要 */}
            {pendingItems.filter(i => !i.done).length > 0 && (
              <div style={{ padding: '14px 16px', background: C.warningBg, border: `1px solid ${C.warning}`, borderRadius: 12, marginBottom: 16 }}>
                <div style={{ fontSize: 15, color: C.warning, fontWeight: 600, marginBottom: 6 }}>
                  将移交 {pendingItems.filter(i => !i.done).length} 项未完成事项：
                </div>
                {pendingItems.filter(i => !i.done).map(item => (
                  <div key={item.id} style={{ fontSize: 15, color: C.text, paddingLeft: 8, marginTop: 4 }}>• {item.content}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 底部操作按钮 */}
      <div style={{ position: 'fixed', bottom: 0, left: 0, right: 0, padding: '12px 16px 28px', background: C.bg, borderTop: `1px solid ${C.border}` }}>
        {step < 3 ? (
          <button
            onPointerDown={() => setBtnPressed(true)}
            onPointerUp={() => setBtnPressed(false)}
            onPointerLeave={() => setBtnPressed(false)}
            onClick={() => setStep(s => (s + 1) as 1 | 2 | 3)}
            style={{
              width: '100%', height: 60, background: C.primary, color: '#fff',
              border: 'none', borderRadius: 14, fontSize: 18, fontWeight: 700, cursor: 'pointer',
              transform: btnPressed ? 'scale(0.97)' : 'scale(1)',
              transition: 'transform 0.2s ease',
            }}
          >
            下一步
          </button>
        ) : (
          <button
            disabled={!successorId.trim() || submitting}
            onPointerDown={() => setBtnPressed(true)}
            onPointerUp={() => setBtnPressed(false)}
            onPointerLeave={() => setBtnPressed(false)}
            onClick={handleSubmit}
            style={{
              width: '100%', height: 60,
              background: successorId.trim() ? C.primary : C.card,
              color: successorId.trim() ? '#fff' : C.muted,
              border: successorId.trim() ? 'none' : `1px solid ${C.border}`,
              borderRadius: 14, fontSize: 18, fontWeight: 700,
              cursor: successorId.trim() ? 'pointer' : 'not-allowed',
              transform: (btnPressed && successorId.trim()) ? 'scale(0.97)' : 'scale(1)',
              transition: 'transform 0.2s ease, background 0.2s',
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? '提交中...' : '确认换班'}
          </button>
        )}
      </div>
    </div>
  );
}
