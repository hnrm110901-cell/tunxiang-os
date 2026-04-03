/**
 * 日清日结打卡页面 — 服务员/店长端 PWA
 * 路由：/daily-settlement
 * E1-E8 清单状态 + 日结汇总操作
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
  divider: '#1a2a33',
};

/* ---------- 类型 ---------- */
type ChecklistStatus = 'pending' | 'in_progress' | 'completed';

interface ChecklistItem {
  id: string;
  code: string;      // E1~E8
  name: string;
  status: ChecklistStatus;
  completed_at?: string;
  detail_url?: string;
}

interface ShiftInfo {
  shift_id: string;
  shift_type: string;
  start_time: string;
  duration_minutes: number;
  employee_name: string;
}

interface DailySummaryData {
  date: string;
  shift_info: ShiftInfo | null;
  checklist: ChecklistItem[];
  all_completed: boolean;
}

/* ---------- API 调用 ---------- */
function getTenantId(): string {
  return localStorage.getItem('tenant_id') ?? '';
}

async function fetchChecklist(): Promise<DailySummaryData> {
  const res = await fetch('/api/v1/ops/settlement/checklist', {
    headers: { 'X-Tenant-ID': getTenantId() },
  });
  if (!res.ok) throw new Error(`获取清单失败: ${res.status}`);
  const json = await res.json();
  return json.data as DailySummaryData;
}

async function submitDailySettlement(): Promise<void> {
  const res = await fetch('/api/v1/ops/settlement/close', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
    },
    body: JSON.stringify({ closed_at: new Date().toISOString() }),
  });
  if (!res.ok) throw new Error(`日结提交失败: ${res.status}`);
}

/* ---------- 工具函数 ---------- */
function formatDate(date: Date): string {
  const d = date;
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()];
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 周${week}`;
}

function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}小时${m}分钟` : `${m}分钟`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

/* ---------- 默认 Mock（API 未就绪时的骨架数据）---------- */
const MOCK_DATA: DailySummaryData = {
  date: new Date().toISOString().slice(0, 10),
  shift_info: {
    shift_id: 'mock-001',
    shift_type: '早班',
    start_time: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
    duration_minutes: 240,
    employee_name: '服务员',
  },
  checklist: [
    { id: 'e1', code: 'E1', name: '换班交接', status: 'pending' },
    { id: 'e2', code: 'E2', name: '日汇总确认', status: 'pending' },
    { id: 'e3', code: 'E3', name: '收银核对', status: 'pending' },
    { id: 'e4', code: 'E4', name: '库存盘点', status: 'pending' },
    { id: 'e5', code: 'E5', name: '问题上报', status: 'pending' },
    { id: 'e6', code: 'E6', name: '整改跟踪', status: 'pending' },
    { id: 'e7', code: 'E7', name: '员工绩效', status: 'pending' },
    { id: 'e8', code: 'E8', name: '巡店报告', status: 'pending' },
  ],
  all_completed: false,
};

/* ---------- 子组件：状态徽章 ---------- */
function StatusBadge({ status }: { status: ChecklistStatus }) {
  if (status === 'completed') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        background: C.successBg, color: C.success,
        borderRadius: 20, padding: '4px 10px',
        fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap',
      }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <circle cx="7" cy="7" r="6.5" stroke={C.success} />
          <path d="M4 7l2 2 4-4" stroke={C.success} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        已完成
      </span>
    );
  }
  if (status === 'in_progress') {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        background: 'rgba(255,107,53,0.12)', color: C.primary,
        borderRadius: 20, padding: '4px 10px',
        fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap',
      }}>
        进行中
      </span>
    );
  }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: C.warningBg, color: C.warning,
      borderRadius: 20, padding: '4px 10px',
      fontSize: 14, fontWeight: 600, whiteSpace: 'nowrap',
    }}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <circle cx="7" cy="7" r="6.5" stroke={C.warning} />
        <path d="M7 4v3.5" stroke={C.warning} strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="7" cy="10" r="0.75" fill={C.warning} />
      </svg>
      待完成
    </span>
  );
}

/* ---------- 子组件：清单卡片 ---------- */
interface ChecklistCardProps {
  item: ChecklistItem;
  onAction: (item: ChecklistItem) => void;
}

function ChecklistCard({ item, onAction }: ChecklistCardProps) {
  const [pressed, setPressed] = useState(false);
  const isCompleted = item.status === 'completed';

  return (
    <div
      style={{
        display: 'flex', alignItems: 'center',
        padding: '16px 16px',
        background: isCompleted ? 'rgba(15,110,86,0.04)' : C.card,
        borderBottom: `1px solid ${C.divider}`,
        gap: 12,
        opacity: isCompleted ? 0.85 : 1,
        transition: 'background 0.15s',
      }}
    >
      {/* 序号 / 图标 */}
      <div style={{
        width: 40, height: 40, borderRadius: 10, flexShrink: 0,
        background: isCompleted ? C.successBg : C.warningBg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 13, fontWeight: 700,
        color: isCompleted ? C.success : C.warning,
      }}>
        {isCompleted
          ? <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path d="M4 9l3.5 3.5L14 6" stroke={C.success} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          : <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M8 4v4.5" stroke={C.warning} strokeWidth="1.8" strokeLinecap="round" />
              <circle cx="8" cy="11.5" r="1" fill={C.warning} />
            </svg>
        }
      </div>

      {/* 内容区 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, color: C.muted, fontWeight: 600 }}>{item.code}</span>
          <span style={{ fontSize: 17, color: C.text, fontWeight: 600 }}>{item.name}</span>
        </div>
        {isCompleted && item.completed_at && (
          <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>
            完成于 {formatTime(item.completed_at)}
          </div>
        )}
      </div>

      {/* 状态 + 操作 */}
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        <StatusBadge status={item.status} />
        {!isCompleted && (
          <button
            onPointerDown={() => setPressed(true)}
            onPointerUp={() => setPressed(false)}
            onPointerLeave={() => setPressed(false)}
            onClick={() => onAction(item)}
            style={{
              height: 48, padding: '0 18px',
              background: C.primary,
              color: '#fff', border: 'none', borderRadius: 10,
              fontSize: 16, fontWeight: 600, cursor: 'pointer',
              transform: pressed ? 'scale(0.97)' : 'scale(1)',
              transition: 'transform 0.2s ease, background 0.15s',
              whiteSpace: 'nowrap',
            }}
          >
            去完成
          </button>
        )}
        {isCompleted && (
          <button
            onPointerDown={() => setPressed(true)}
            onPointerUp={() => setPressed(false)}
            onPointerLeave={() => setPressed(false)}
            onClick={() => onAction(item)}
            style={{
              width: 40, height: 40,
              background: 'transparent', border: `1px solid ${C.border}`,
              borderRadius: 8, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transform: pressed ? 'scale(0.97)' : 'scale(1)',
              transition: 'transform 0.2s ease',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path d="M7 9l4-4m0 0l-4-4m4 4H3" stroke={C.muted} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------- 主页面 ---------- */
export function DailySettlementPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<DailySummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [settled, setSettled] = useState(false);
  const [submitBtnPressed, setSubmitBtnPressed] = useState(false);

  const loadChecklist = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchChecklist();
      setData(result);
    } catch (err) {
      // 网络/API 未就绪时降级到 mock 数据
      setData(MOCK_DATA);
      const msg = err instanceof Error ? err.message : '未知错误';
      setError(`数据加载失败（已显示示例数据）：${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadChecklist();
  }, [loadChecklist]);

  const handleItemAction = (item: ChecklistItem) => {
    if (item.status === 'completed') return; // 已完成：可扩展跳转详情
    // E1 换班 → 换班页
    if (item.code === 'E1') { navigate('/shift-handover'); return; }
    // E5 问题上报 → 问题上报页
    if (item.code === 'E5') { navigate('/issue-report'); return; }
    // 其余 E2/E3/E4/E6/E7/E8：提示暂未开放
    alert(`${item.code} ${item.name} 功能即将上线`);
  };

  const handleSettle = async () => {
    if (!data?.all_completed) return;
    setSubmitting(true);
    try {
      await submitDailySettlement();
      setSettled(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      alert(`日结失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  const completedCount = data?.checklist.filter(i => i.status === 'completed').length ?? 0;
  const totalCount = data?.checklist.length ?? 8;
  const allDone = data?.all_completed ?? false;

  /* ------ 日结成功界面 ------ */
  if (settled) {
    return (
      <div style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ width: 80, height: 80, borderRadius: 40, background: C.successBg, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 24 }}>
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
            <path d="M10 20l7 7 13-14" stroke={C.success} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, color: C.text, marginBottom: 10 }}>日结完成</div>
        <div style={{ fontSize: 17, color: C.muted, marginBottom: 40, textAlign: 'center' }}>
          今日 E1-E8 全部完成，数据已汇总
        </div>
        <button
          onClick={() => navigate('/tables')}
          style={{ height: 56, padding: '0 40px', background: C.primary, color: '#fff', border: 'none', borderRadius: 12, fontSize: 18, fontWeight: 600, cursor: 'pointer' }}
        >
          返回首页
        </button>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, paddingBottom: 100 }}>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '16px 16px 12px', borderBottom: `1px solid ${C.border}` }}>
        <button
          onClick={() => navigate(-1)}
          style={{ width: 44, height: 44, background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: 8 }}
        >
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <path d="M14 6l-6 5 6 5" stroke={C.text} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.text }}>日清日结</div>
          <div style={{ fontSize: 14, color: C.muted }}>{formatDate(new Date())}</div>
        </div>
        <button
          onClick={loadChecklist}
          style={{ width: 44, height: 44, background: 'transparent', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M17 10A7 7 0 1 1 10 3a7 7 0 0 1 5 2.1M17 3v4h-4" stroke={C.muted} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* 班次信息卡 */}
      {data?.shift_info && (
        <div style={{ margin: '16px 16px 0', padding: '16px 20px', background: C.card, borderRadius: 14, border: `1px solid ${C.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>当前班次</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.text }}>{data.shift_info.shift_type}</div>
              <div style={{ fontSize: 15, color: C.muted, marginTop: 4 }}>
                {formatTime(data.shift_info.start_time)} 开始 · {data.shift_info.employee_name}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 14, color: C.muted, marginBottom: 4 }}>已工作</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.primary }}>
                {formatDuration(data.shift_info.duration_minutes)}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 进度条 */}
      <div style={{ margin: '16px 16px 0', padding: '14px 20px', background: C.card, borderRadius: 14, border: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
          <span style={{ fontSize: 16, color: C.text, fontWeight: 600 }}>完成进度</span>
          <span style={{ fontSize: 16, color: C.primary, fontWeight: 700 }}>{completedCount} / {totalCount}</span>
        </div>
        <div style={{ height: 8, background: C.border, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 4,
            background: allDone ? C.success : C.primary,
            width: `${Math.round((completedCount / totalCount) * 100)}%`,
            transition: 'width 0.4s ease, background 0.3s',
          }} />
        </div>
        {allDone && (
          <div style={{ fontSize: 15, color: C.success, marginTop: 8, fontWeight: 600 }}>
            全部完成，可进行日结
          </div>
        )}
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{ margin: '12px 16px 0', padding: '12px 16px', background: 'rgba(186,117,23,0.12)', border: `1px solid ${C.warning}`, borderRadius: 10, fontSize: 14, color: C.warning }}>
          {error}
        </div>
      )}

      {/* 清单列表 */}
      <div style={{ margin: '16px 0 0' }}>
        <div style={{ padding: '0 16px 10px', fontSize: 16, color: C.muted, fontWeight: 600 }}>
          E1 - E8 清单
        </div>
        {loading ? (
          <div style={{ padding: '40px 16px', textAlign: 'center', color: C.muted, fontSize: 17 }}>
            加载中...
          </div>
        ) : (
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden', margin: '0 16px' }}>
            {(data?.checklist ?? []).map((item) => (
              <ChecklistCard key={item.id} item={item} onAction={handleItemAction} />
            ))}
          </div>
        )}
      </div>

      {/* 底部日结按钮（固定底部）*/}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px 28px', background: C.bg,
        borderTop: `1px solid ${C.border}`,
      }}>
        <button
          disabled={!allDone || submitting}
          onPointerDown={() => setSubmitBtnPressed(true)}
          onPointerUp={() => setSubmitBtnPressed(false)}
          onPointerLeave={() => setSubmitBtnPressed(false)}
          onClick={handleSettle}
          style={{
            width: '100%', height: 60,
            background: allDone ? C.primary : C.card,
            color: allDone ? '#fff' : C.muted,
            border: allDone ? 'none' : `1px solid ${C.border}`,
            borderRadius: 14, fontSize: 18, fontWeight: 700,
            cursor: allDone ? 'pointer' : 'not-allowed',
            transform: (submitBtnPressed && allDone) ? 'scale(0.97)' : 'scale(1)',
            transition: 'transform 0.2s ease, background 0.3s',
            opacity: submitting ? 0.7 : 1,
          }}
        >
          {submitting ? '提交中...' : allDone ? '确认日结' : `还有 ${totalCount - completedCount} 项未完成`}
        </button>
      </div>
    </div>
  );
}
