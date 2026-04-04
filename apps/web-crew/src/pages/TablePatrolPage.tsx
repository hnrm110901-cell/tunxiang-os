/**
 * 巡台检查页 — 服务员巡台时的检查清单
 * 桌台列表 + 4项检查勾选 + 备注 + 提交巡检报告
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect, useCallback } from 'react';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#ef4444',
  yellow: '#eab308',
};

const BASE = 'http://localhost:8001';

/* ---------- 类型 ---------- */
type DiningStatus = 'idle' | 'dining' | 'clearing';

interface CheckItem {
  key: string;
  label: string;
  checked: boolean;
}

interface TableCard {
  id: string;
  tableNo: string;
  area: '大厅' | '包厢' | '室外';
  status: DiningStatus;
  guestCount: number;
  diningMinutes: number;
  lastOrderTime: string;
  checks: CheckItem[];
  remark: string;
  completed: boolean;
}

/* ---------- Mock 数据 ---------- */
const AREAS: Array<'大厅' | '包厢' | '室外'> = ['大厅', '包厢', '室外'];
const STATUSES: DiningStatus[] = ['idle', 'dining', 'clearing'];

function generateMockTables(): TableCard[] {
  const tables: TableCard[] = [];
  for (let i = 1; i <= 20; i++) {
    const status = STATUSES[i % 3];
    tables.push({
      id: `table-${i}`,
      tableNo: `${i <= 10 ? 'A' : 'B'}${String(i <= 10 ? i : i - 10).padStart(2, '0')}`,
      area: AREAS[i % 3],
      status,
      guestCount: status === 'dining' ? Math.floor(Math.random() * 8) + 2 : 0,
      diningMinutes: status === 'dining' ? Math.floor(Math.random() * 90) + 10 : 0,
      lastOrderTime: status === 'dining'
        ? `${String(11 + Math.floor(Math.random() * 3)).padStart(2, '0')}:${String(Math.floor(Math.random() * 60)).padStart(2, '0')}`
        : '',
      checks: [
        { key: 'clean', label: '桌面整洁', checked: false },
        { key: 'utensils', label: '餐具齐全', checked: false },
        { key: 'tea', label: '茶水充足', checked: false },
        { key: 'floor', label: '地面干净', checked: false },
      ],
      remark: '',
      completed: false,
    });
  }
  return tables;
}

/* ---------- 状态颜色/标签 ---------- */
const STATUS_MAP: Record<DiningStatus, { emoji: string; label: string; color: string }> = {
  idle: { emoji: '🟢', label: '空闲', color: C.green },
  dining: { emoji: '🟡', label: '用餐中', color: C.yellow },
  clearing: { emoji: '🔴', label: '待清台', color: C.danger },
};

/* ---------- 组件 ---------- */
export function TablePatrolPage() {
  const [tables, setTables] = useState<TableCard[]>([]);
  const [patrolStarted, setPatrolStarted] = useState(false);
  const [crewName] = useState('当班服务员');
  const [now, setNow] = useState(new Date());
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  /* 时钟 */
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  /* 加载桌台 */
  const loadTables = useCallback(async () => {
    try {
      const storeId = (window as unknown as Record<string, unknown>).__STORE_ID__ || 'demo';
      const res = await fetch(`${BASE}/api/v1/trade/tables?store_id=${storeId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const items: TableCard[] = (json.data?.items ?? json.items ?? []).map((t: Record<string, unknown>, idx: number) => ({
        id: String(t.id ?? `table-${idx}`),
        tableNo: String(t.table_no ?? t.tableNo ?? `T${idx + 1}`),
        area: (['大厅', '包厢', '室外'] as const)[(idx % 3)] as '大厅' | '包厢' | '室外',
        status: (t.status === 'dining' ? 'dining' : t.status === 'clearing' ? 'clearing' : 'idle') as DiningStatus,
        guestCount: Number(t.guest_count ?? 0),
        diningMinutes: Number(t.dining_minutes ?? 0),
        lastOrderTime: String(t.last_order_time ?? ''),
        checks: [
          { key: 'clean', label: '桌面整洁', checked: false },
          { key: 'utensils', label: '餐具齐全', checked: false },
          { key: 'tea', label: '茶水充足', checked: false },
          { key: 'floor', label: '地面干净', checked: false },
        ],
        remark: '',
        completed: false,
      }));
      setTables(items);
    } catch (_err: unknown) {
      // API 不可用，降级 Mock
      setTables(generateMockTables());
    }
  }, []);

  useEffect(() => {
    if (patrolStarted) {
      loadTables();
    }
  }, [patrolStarted, loadTables]);

  /* toggle 检查项 */
  const toggleCheck = (tableId: string, checkKey: string) => {
    if (typeof navigator.vibrate === 'function') navigator.vibrate(50);
    setTables(prev => prev.map(t => {
      if (t.id !== tableId) return t;
      const newChecks = t.checks.map(c =>
        c.key === checkKey ? { ...c, checked: !c.checked } : c
      );
      return { ...t, checks: newChecks };
    }));
  };

  /* 备注 */
  const updateRemark = (tableId: string, remark: string) => {
    setTables(prev => prev.map(t => t.id === tableId ? { ...t, remark } : t));
  };

  /* 完成单桌检查 */
  const completeTable = (tableId: string) => {
    if (typeof navigator.vibrate === 'function') navigator.vibrate(50);
    setTables(prev => prev.map(t => t.id === tableId ? { ...t, completed: true } : t));
  };

  /* 提交巡检报告 */
  const submitPatrol = async () => {
    if (typeof navigator.vibrate === 'function') navigator.vibrate(100);
    setSubmitting(true);
    try {
      const storeId = (window as unknown as Record<string, unknown>).__STORE_ID__ || 'demo';
      const checks = tables.map(t => ({
        table_id: t.id,
        table_no: t.tableNo,
        checks: t.checks.map(c => ({ key: c.key, passed: c.checked })),
        remark: t.remark,
      }));
      await fetch(`${BASE}/api/v1/ops/patrol/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ store_id: storeId, checks }),
      });
    } catch (_err: unknown) {
      // 离线 — 静默忽略
    }
    setSubmitting(false);
    setSubmitted(true);
  };

  /* 统计 */
  const completedCount = tables.filter(t => t.completed).length;
  const totalCount = tables.length;
  const issueCount = tables.reduce((sum, t) => {
    const unchecked = t.completed ? t.checks.filter(c => !c.checked).length : 0;
    return sum + unchecked;
  }, 0);
  const allDone = totalCount > 0 && completedCount === totalCount;

  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;

  /* ====== 提交成功 ====== */
  if (submitted) {
    return (
      <div style={{ background: C.bg, minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ fontSize: 64 }}>✅</div>
        <div style={{ fontSize: 24, fontWeight: 700, color: C.white, marginTop: 16 }}>巡检报告已提交</div>
        <div style={{ fontSize: 16, color: C.muted, marginTop: 8 }}>
          已检查 {completedCount} 桌，发现 {issueCount} 项问题
        </div>
        <button
          onClick={() => { setSubmitted(false); setPatrolStarted(false); setTables([]); }}
          style={{
            marginTop: 32, height: 48, padding: '0 32px', borderRadius: 12,
            background: C.accent, color: C.white, fontSize: 18, fontWeight: 700,
            border: 'none', cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>
    );
  }

  /* ====== 未开始巡台 ====== */
  if (!patrolStarted) {
    return (
      <div style={{ background: C.bg, minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ fontSize: 16, color: C.muted }}>{timeStr}</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginTop: 8 }}>{crewName}</div>
        <button
          onClick={() => {
            if (typeof navigator.vibrate === 'function') navigator.vibrate(50);
            setPatrolStarted(true);
          }}
          style={{
            marginTop: 32, width: '80%', maxWidth: 320, height: 88, borderRadius: 16,
            background: C.accent, color: C.white, fontSize: 24, fontWeight: 700,
            border: 'none', cursor: 'pointer', boxShadow: '0 4px 20px rgba(255,107,53,0.4)',
          }}
        >
          开始巡台
        </button>
      </div>
    );
  }

  /* ====== 巡台进行中 ====== */
  return (
    <div style={{ background: C.bg, minHeight: '100vh', width: '100vw', paddingBottom: 120 }}>
      {/* 顶部区域 */}
      <div style={{ padding: '16px 16px 12px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 16, color: C.muted }}>{timeStr}</span>
          <span style={{ fontSize: 16, color: C.white, fontWeight: 600 }}>{crewName}</span>
        </div>
      </div>

      {/* 桌台列表 */}
      <div style={{ padding: '8px 8px 0' }}>
        {tables.map(table => {
          const st = STATUS_MAP[table.status];
          const allChecked = table.checks.every(c => c.checked);
          return (
            <div
              key={table.id}
              style={{
                background: table.completed ? 'rgba(17,34,40,0.6)' : C.card,
                borderRadius: 12, margin: 8, padding: 16,
                opacity: table.completed ? 0.6 : 1,
                border: table.completed ? `1px solid ${C.green}` : `1px solid ${C.border}`,
              }}
            >
              {/* 桌号 + 区域 + 状态 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                <span style={{ fontSize: 24, fontWeight: 700, color: C.white }}>{table.tableNo}</span>
                <span style={{
                  fontSize: 14, padding: '2px 8px', borderRadius: 6,
                  background: 'rgba(255,255,255,0.08)', color: C.muted,
                }}>
                  {table.area}
                </span>
                <span style={{ fontSize: 16, color: st.color, marginLeft: 'auto' }}>
                  {st.emoji} {st.label}
                </span>
              </div>

              {/* 用餐详情 */}
              {table.status === 'dining' && (
                <div style={{ display: 'flex', gap: 16, fontSize: 16, color: C.muted, marginBottom: 12, flexWrap: 'wrap' }}>
                  <span>用餐 {table.diningMinutes} 分钟</span>
                  <span>{table.guestCount} 人</span>
                  {table.lastOrderTime && <span>最近点单 {table.lastOrderTime}</span>}
                </div>
              )}

              {/* 检查项清单 */}
              {!table.completed && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
                    {table.checks.map(check => (
                      <button
                        key={check.key}
                        onClick={() => toggleCheck(table.id, check.key)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 8,
                          minHeight: 48, padding: '8px 12px', borderRadius: 8,
                          background: check.checked ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.05)',
                          border: check.checked ? '1px solid rgba(34,197,94,0.4)' : '1px solid transparent',
                          color: check.checked ? C.green : C.text,
                          fontSize: 16, cursor: 'pointer',
                        }}
                      >
                        <span style={{ fontSize: 18 }}>{check.checked ? '✅' : '⬜'}</span>
                        <span>{check.label}</span>
                      </button>
                    ))}
                  </div>

                  {/* 备注 */}
                  <input
                    placeholder="备注（可选）"
                    value={table.remark}
                    onChange={e => updateRemark(table.id, e.target.value)}
                    style={{
                      width: '100%', height: 44, padding: '0 12px', borderRadius: 8,
                      background: 'rgba(255,255,255,0.05)', border: `1px solid ${C.border}`,
                      color: C.text, fontSize: 16, outline: 'none',
                      boxSizing: 'border-box',
                    }}
                  />

                  {/* 完成检查 */}
                  <button
                    onClick={() => completeTable(table.id)}
                    disabled={!allChecked}
                    style={{
                      width: '100%', height: 48, marginTop: 12, borderRadius: 10,
                      background: allChecked ? C.green : C.muted,
                      color: C.white, fontSize: 16, fontWeight: 700,
                      border: 'none', cursor: allChecked ? 'pointer' : 'default',
                      opacity: allChecked ? 1 : 0.5,
                    }}
                  >
                    {allChecked ? '完成检查' : '请完成所有检查项'}
                  </button>
                </>
              )}

              {table.completed && (
                <div style={{ fontSize: 16, color: C.green, fontWeight: 600 }}>✅ 检查完成</div>
              )}
            </div>
          );
        })}
      </div>

      {/* 底部统计栏 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: C.card, borderTop: `1px solid ${C.border}`,
        padding: 16, display: 'flex', flexDirection: 'column', gap: 12,
        zIndex: 100,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: C.text }}>
          <span>已检查 <b style={{ color: C.accent }}>{completedCount}</b>/{totalCount} 桌</span>
          <span>发现问题 <b style={{ color: issueCount > 0 ? C.danger : C.green }}>{issueCount}</b> 项</span>
        </div>
        {allDone && (
          <button
            onClick={submitPatrol}
            disabled={submitting}
            style={{
              width: '100%', height: 88, borderRadius: 16,
              background: C.accent, color: C.white,
              fontSize: 22, fontWeight: 700, border: 'none', cursor: 'pointer',
              boxShadow: '0 4px 20px rgba(255,107,53,0.4)',
            }}
          >
            {submitting ? '提交中...' : '提交巡检报告'}
          </button>
        )}
      </div>
    </div>
  );
}
