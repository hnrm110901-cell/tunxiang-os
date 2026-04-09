/**
 * 任务中心页 — /hq/tasks
 * P0-D2: 聚合展示开店检查/催菜/客诉/闭店检查/异常上报等任务
 * 状态机: 新建→待受理→处理中→待复核→已升级→已关闭
 * API: GET /api/v1/agent/tasks?store_id=XXX
 *      POST /api/v1/agent/tasks/{id}/actions/assign
 *      POST /api/v1/agent/tasks/{id}/actions/close
 */
import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../../api/client';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type TaskStatus = 'new' | 'assigned' | 'accepted' | 'processing' | 'pending_review' | 'escalated' | 'ignored' | 'cancelled' | 'closed';
type TaskPriority = 'low' | 'normal' | 'high' | 'urgent';
type TaskType = 'queue_seating_suggestion' | 'kitchen_overtime_alert' | 'billing_risk_review' | 'unsettled_order_followup' | 'closing_check_exception' | 'invoice_pending_action' | 'customer_complaint' | 'service_recovery';

interface TaskItem {
  id: string;
  store_id: string;
  store_name?: string;
  business_day_id: string | null;
  shift_id: string | null;
  task_type: TaskType;
  title: string;
  description: string | null;
  related_object_type: string;
  related_object_id: string;
  status: TaskStatus;
  priority: TaskPriority;
  assignee_role: string | null;
  assignee_staff_id: string | null;
  assignee_name?: string | null;
  suggestion_text: string | null;
  sla_due_at: string | null;
  closed_reason: string | null;
  created_at: string;
  updated_at: string;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<TaskStatus, { label: string; color: string; bg: string }> = {
  new:            { label: '新建',   color: '#185FA5', bg: '#185FA518' },
  assigned:       { label: '待受理', color: '#D97706', bg: '#D9770618' },
  accepted:       { label: '已接受', color: '#0F6E56', bg: '#0F6E5618' },
  processing:     { label: '处理中', color: '#FF6B35', bg: '#FF6B3518' },
  pending_review: { label: '待复核', color: '#8B5CF6', bg: '#8B5CF618' },
  escalated:      { label: '已升级', color: '#A32D2D', bg: '#A32D2D18' },
  ignored:        { label: '已忽略', color: '#666',    bg: '#66666618' },
  cancelled:      { label: '已取消', color: '#666',    bg: '#66666618' },
  closed:         { label: '已关闭', color: '#0F6E56', bg: '#0F6E5618' },
};

const PRIORITY_CONFIG: Record<TaskPriority, { label: string; color: string; bg: string }> = {
  low:    { label: '低', color: '#0F6E56', bg: '#0F6E5618' },
  normal: { label: '中', color: '#185FA5', bg: '#185FA518' },
  high:   { label: '高', color: '#D97706', bg: '#D9770618' },
  urgent: { label: '紧急', color: '#A32D2D', bg: '#A32D2D18' },
};

const TYPE_CONFIG: Record<TaskType, { label: string; icon: string }> = {
  queue_seating_suggestion:  { label: '排位建议', icon: '🪑' },
  kitchen_overtime_alert:    { label: '后厨超时', icon: '🔥' },
  billing_risk_review:       { label: '收银异常', icon: '💳' },
  unsettled_order_followup:  { label: '未结单追踪', icon: '📋' },
  closing_check_exception:   { label: '闭店检查', icon: '🔒' },
  invoice_pending_action:    { label: '发票待办', icon: '🧾' },
  customer_complaint:        { label: '客诉登记', icon: '😞' },
  service_recovery:          { label: '服务补偿', icon: '🎁' },
};

// ─── 降级数据 ──────────────────────────────────────────────────────────────────

const FALLBACK_TASKS: TaskItem[] = [
  { id: 'task_001', store_id: 'demo_store_01', store_name: '五一广场店', business_day_id: 'bd_01', shift_id: 'shift_01', task_type: 'kitchen_overtime_alert', title: 'B01桌剁椒鱼头超时6分钟', description: '热菜档口积压，需要厨师长确认', related_object_type: 'production_item', related_object_id: 'prod_001', status: 'assigned', priority: 'urgent', assignee_role: 'kitchen_lead', assignee_staff_id: 'staff_888', assignee_name: '王大厨', suggestion_text: '建议优先出品并同步前厅安抚客人', sla_due_at: '2026-04-09T12:35:00+08:00', closed_reason: null, created_at: '2026-04-09T12:28:00+08:00', updated_at: '2026-04-09T12:29:00+08:00' },
  { id: 'task_002', store_id: 'demo_store_01', store_name: '五一广场店', business_day_id: 'bd_01', shift_id: 'shift_01', task_type: 'billing_risk_review', title: 'A12桌折扣率38%超阈值', description: '手动折扣¥320，需店长审批', related_object_type: 'order', related_object_id: 'ord_1012', status: 'new', priority: 'high', assignee_role: 'store_manager', assignee_staff_id: null, assignee_name: null, suggestion_text: '折扣超过30%需店长确认', sla_due_at: '2026-04-09T12:40:00+08:00', closed_reason: null, created_at: '2026-04-09T12:30:00+08:00', updated_at: '2026-04-09T12:30:00+08:00' },
  { id: 'task_003', store_id: 'demo_store_01', store_name: '五一广场店', business_day_id: 'bd_01', shift_id: 'shift_01', task_type: 'customer_complaint', title: 'V02包厢客人投诉上菜慢', description: '宴席客人等待25分钟未上主菜', related_object_type: 'table', related_object_id: 'tbl_v02', status: 'processing', priority: 'urgent', assignee_role: 'service_lead', assignee_staff_id: 'staff_101', assignee_name: '李经理', suggestion_text: '建议赠送果盘并优先出品', sla_due_at: '2026-04-09T12:32:00+08:00', closed_reason: null, created_at: '2026-04-09T12:25:00+08:00', updated_at: '2026-04-09T12:27:00+08:00' },
  { id: 'task_004', store_id: 'demo_store_01', store_name: '五一广场店', business_day_id: 'bd_01', shift_id: 'shift_01', task_type: 'unsettled_order_followup', title: '3张桌未结账（A08/B03/C11）', description: '即将闭店，需跟进未结单', related_object_type: 'shift', related_object_id: 'shift_01', status: 'assigned', priority: 'high', assignee_role: 'cashier', assignee_staff_id: 'staff_201', assignee_name: '张收银', suggestion_text: '提醒服务员协助催单', sla_due_at: '2026-04-09T22:00:00+08:00', closed_reason: null, created_at: '2026-04-09T21:30:00+08:00', updated_at: '2026-04-09T21:30:00+08:00' },
  { id: 'task_005', store_id: 'demo_store_01', store_name: '五一广场店', business_day_id: 'bd_01', shift_id: 'shift_01', task_type: 'closing_check_exception', title: '备用金差异¥20', description: '实点金额与系统差异¥20', related_object_type: 'shift', related_object_id: 'shift_01', status: 'closed', priority: 'normal', assignee_role: 'store_manager', assignee_staff_id: 'staff_301', assignee_name: '赵店长', suggestion_text: null, sla_due_at: null, closed_reason: '确认为找零误差，已登记', created_at: '2026-04-08T22:45:00+08:00', updated_at: '2026-04-08T23:10:00+08:00' },
];

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export function TaskCenterPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('active'); // active = 非closed/cancelled
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await apiGet<{ items: TaskItem[] }>('/api/v1/agent/tasks?page=1&size=100');
        setTasks(res.items?.length ? res.items : FALLBACK_TASKS);
      } catch { setTasks(FALLBACK_TASKS); }
      setLoading(false);
    })();
  }, []);

  // ─── 过滤 ──────────────────────────────────────────────────────────────────
  const filtered = tasks.filter((t) => {
    if (filterType !== 'all' && t.task_type !== filterType) return false;
    if (filterStatus === 'active' && (t.status === 'closed' || t.status === 'cancelled' || t.status === 'ignored')) return false;
    if (filterStatus === 'closed' && t.status !== 'closed') return false;
    return true;
  });

  // ─── 统计 ──────────────────────────────────────────────────────────────────
  const urgentCount = tasks.filter((t) => t.priority === 'urgent' && t.status !== 'closed' && t.status !== 'cancelled').length;
  const activeCount = tasks.filter((t) => t.status !== 'closed' && t.status !== 'cancelled' && t.status !== 'ignored').length;
  const closedToday = tasks.filter((t) => t.status === 'closed').length;

  // ─── 操作 ──────────────────────────────────────────────────────────────────
  const handleClose = async (taskId: string) => {
    try {
      await apiPost(`/api/v1/agent/tasks/${taskId}/actions/close`, { closed_reason: '手动关闭' });
      setTasks((prev) => prev.map((t) => t.id === taskId ? { ...t, status: 'closed' as TaskStatus } : t));
      setSelectedTask(null);
    } catch (err) { console.error('关闭失败', err); }
  };

  // ─── 时间格式化 ────────────────────────────────────────────────────────────
  const formatTime = (iso: string | null) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  };
  const timeAgo = (iso: string) => {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (diff < 1) return '刚刚';
    if (diff < 60) return `${diff}分钟前`;
    return `${Math.floor(diff / 60)}小时前`;
  };

  const brand = '#FF6B35';
  const bg1 = '#112228';
  const bg2 = '#1a2a33';
  const text1 = '#E8E6E1';
  const text2 = '#999';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, color: text1 }}>
      {/* 页头 */}
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>任务中心</h2>
        <p style={{ fontSize: 13, color: text2, margin: '4px 0 0' }}>聚合展示门店执行任务、Agent异常发现、审批待办</p>
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <div style={{ background: urgentCount > 0 ? '#A32D2D18' : bg1, borderRadius: 12, padding: '16px 20px', border: `1px solid ${urgentCount > 0 ? '#A32D2D44' : bg2}` }}>
          <div style={{ fontSize: 11, color: text2 }}>🚨 紧急任务</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: urgentCount > 0 ? '#A32D2D' : text1 }}>{urgentCount}</div>
        </div>
        <div style={{ background: bg1, borderRadius: 12, padding: '16px 20px', border: `1px solid ${bg2}` }}>
          <div style={{ fontSize: 11, color: text2 }}>📋 进行中</div>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{activeCount}</div>
        </div>
        <div style={{ background: bg1, borderRadius: 12, padding: '16px 20px', border: `1px solid ${bg2}` }}>
          <div style={{ fontSize: 11, color: text2 }}>✅ 今日已关闭</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#0F6E56' }}>{closedToday}</div>
        </div>
      </div>

      {/* 过滤器 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <button onClick={() => setFilterType('all')} style={{ padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, background: filterType === 'all' ? `${brand}22` : 'transparent', color: filterType === 'all' ? brand : text2 }}>全部</button>
          {Object.entries(TYPE_CONFIG).map(([k, v]) => (
            <button key={k} onClick={() => setFilterType(k)} style={{ padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, background: filterType === k ? `${brand}22` : 'transparent', color: filterType === k ? brand : text2 }}>
              {v.icon} {v.label}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[{ k: 'active', l: '进行中' }, { k: 'closed', l: '已关闭' }, { k: 'all', l: '全部' }].map((f) => (
            <button key={f.k} onClick={() => setFilterStatus(f.k)} style={{ padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, background: filterStatus === f.k ? `${brand}22` : 'transparent', color: filterStatus === f.k ? brand : text2 }}>{f.l}</button>
          ))}
        </div>
      </div>

      {/* 任务列表 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: text2 }}>加载中...</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filtered.map((t) => {
            const tc = TYPE_CONFIG[t.task_type] || { label: t.task_type, icon: '📌' };
            const sc = STATUS_CONFIG[t.status];
            const pc = PRIORITY_CONFIG[t.priority];
            const isOverdue = t.sla_due_at && new Date(t.sla_due_at) < new Date() && t.status !== 'closed';
            return (
              <div
                key={t.id}
                onClick={() => setSelectedTask(t)}
                style={{ background: bg1, borderRadius: 12, padding: 16, border: `1px solid ${isOverdue ? '#A32D2D44' : bg2}`, cursor: 'pointer', transition: 'border-color .15s', display: 'flex', gap: 14, alignItems: 'flex-start' }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = brand)}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = isOverdue ? '#A32D2D44' : bg2)}
              >
                <span style={{ fontSize: 24 }}>{tc.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 14, fontWeight: 600 }}>{t.title}</span>
                    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: pc.bg, color: pc.color }}>{pc.label}</span>
                    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: sc.bg, color: sc.color }}>{sc.label}</span>
                    {isOverdue && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: '#A32D2D18', color: '#A32D2D', fontWeight: 600 }}>超时</span>}
                  </div>
                  {t.description && <div style={{ fontSize: 12, color: text2, marginBottom: 4 }}>{t.description}</div>}
                  {t.suggestion_text && <div style={{ fontSize: 12, color: '#185FA5', marginBottom: 4 }}>💡 {t.suggestion_text}</div>}
                  <div style={{ display: 'flex', gap: 12, fontSize: 11, color: text2 }}>
                    <span>{tc.label}</span>
                    {t.assignee_name && <span>👤 {t.assignee_name}</span>}
                    {t.store_name && <span>🏪 {t.store_name}</span>}
                    <span>🕐 {timeAgo(t.created_at)}</span>
                    {t.sla_due_at && <span style={{ color: isOverdue ? '#A32D2D' : text2 }}>截止 {formatTime(t.sla_due_at)}</span>}
                  </div>
                </div>
              </div>
            );
          })}
          {filtered.length === 0 && <div style={{ textAlign: 'center', padding: 40, color: text2 }}>暂无任务</div>}
        </div>
      )}

      {/* 任务详情弹窗 */}
      {selectedTask && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setSelectedTask(null)}>
          <div style={{ background: bg1, borderRadius: 16, padding: 28, width: 520, maxHeight: '80vh', overflow: 'auto', border: `1px solid ${bg2}` }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={{ fontSize: 24 }}>{(TYPE_CONFIG[selectedTask.task_type] || { icon: '📌' }).icon}</span>
                  <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{selectedTask.title}</h3>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: PRIORITY_CONFIG[selectedTask.priority].bg, color: PRIORITY_CONFIG[selectedTask.priority].color }}>{PRIORITY_CONFIG[selectedTask.priority].label}</span>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: STATUS_CONFIG[selectedTask.status].bg, color: STATUS_CONFIG[selectedTask.status].color }}>{STATUS_CONFIG[selectedTask.status].label}</span>
                </div>
              </div>
              <button onClick={() => setSelectedTask(null)} style={{ border: 'none', background: 'transparent', color: text2, fontSize: 20, cursor: 'pointer' }}>✕</button>
            </div>
            {selectedTask.description && <div style={{ fontSize: 13, color: text2, marginBottom: 12, padding: 12, background: bg2, borderRadius: 8 }}>{selectedTask.description}</div>}
            {selectedTask.suggestion_text && <div style={{ fontSize: 13, color: '#185FA5', marginBottom: 12, padding: 12, background: '#185FA510', borderRadius: 8 }}>💡 AI建议：{selectedTask.suggestion_text}</div>}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 12, color: text2, marginBottom: 16 }}>
              <div>任务类型：{(TYPE_CONFIG[selectedTask.task_type] || { label: selectedTask.task_type }).label}</div>
              <div>关联对象：{selectedTask.related_object_type} / {selectedTask.related_object_id}</div>
              <div>指派岗位：{selectedTask.assignee_role || '—'}</div>
              <div>处理人：{selectedTask.assignee_name || '—'}</div>
              <div>创建时间：{new Date(selectedTask.created_at).toLocaleString('zh-CN')}</div>
              <div>SLA截止：{selectedTask.sla_due_at ? new Date(selectedTask.sla_due_at).toLocaleString('zh-CN') : '—'}</div>
              {selectedTask.closed_reason && <div style={{ gridColumn: '1/-1' }}>关闭原因：{selectedTask.closed_reason}</div>}
            </div>
            {selectedTask.status !== 'closed' && selectedTask.status !== 'cancelled' && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button onClick={() => handleClose(selectedTask.id)} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: '#0F6E56', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>关闭任务</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default TaskCenterPage;
