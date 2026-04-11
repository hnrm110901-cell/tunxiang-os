/**
 * 巡检整改执行 — /manager/patrol-execution
 * 店长/岗位负责人进行门店巡检、发现问题、生成整改任务并执行反馈
 *
 * API:
 *   GET   /api/v1/ops/inspection/today
 *   GET   /api/v1/ops/inspection/items
 *   PATCH /api/v1/ops/inspection/items/:id
 *   POST  /api/v1/ops/inspection/submit
 *   GET   /api/v1/ops/rectification/my-tasks
 *   PATCH /api/v1/ops/rectification/tasks/:id/feedback
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchInspectionToday,
  fetchInspectionItems,
  updateInspectionItem,
  submitInspection,
  fetchRectifyTasks,
  submitRectifyFeedback,
} from '../../api/patrolApi';
import type {
  CheckStatus,
  InspectionCategory,
  InspectionItem,
  InspectionSummary,
  RectifyTask,
} from '../../api/patrolApi';

// ─── 设计Token ───

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
};

const pageStyle: React.CSSProperties = {
  padding: 16,
  background: C.bg,
  minHeight: '100vh',
  color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
  maxWidth: 500,
  margin: '0 auto',
  paddingBottom: 80,
};

const cardStyle: React.CSSProperties = {
  background: C.card,
  borderRadius: 10,
  padding: 14,
  marginBottom: 12,
};

// ─── 分类配置 ───

const CATEGORY_CONFIG: Record<InspectionCategory, { label: string; icon: string }> = {
  food_safety: { label: '食品安全', icon: '🛡️' },
  hygiene: { label: '环境卫生', icon: '🧹' },
  equipment: { label: '设备检查', icon: '🔧' },
  service: { label: '服务规范', icon: '🤝' },
  fire_safety: { label: '消防安全', icon: '🧯' },
};

const STATUS_CONFIG: Record<CheckStatus, { label: string; color: string; icon: string }> = {
  pending: { label: '待检', color: C.muted, icon: '⏳' },
  pass: { label: '合格', color: '#0F6E56', icon: '✅' },
  fail: { label: '不合格', color: '#A32D2D', icon: '❌' },
  na: { label: '不适用', color: '#6B7280', icon: '⚪' },
};

const SEVERITY_CONFIG: Record<string, { label: string; color: string }> = {
  high: { label: '严重', color: C.danger },
  medium: { label: '一般', color: C.warning },
  low: { label: '轻微', color: C.success },
};

const RECTIFY_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: '待执行', color: C.danger },
  in_progress: { label: '执行中', color: C.warning },
  completed: { label: '已完成', color: C.success },
};

// ─── Fallback 数据 ───

const FALLBACK_ITEMS: InspectionItem[] = [
  // 食品安全
  { id: 'fs1', category: 'food_safety', name: '食品留样', description: '检查当日食品留样是否规范（每样125g以上，冷藏保存48h）', status: 'pending' },
  { id: 'fs2', category: 'food_safety', name: '食材效期', description: '检查冷库/货架食材标签，确认无过期食材', status: 'pending' },
  { id: 'fs3', category: 'food_safety', name: '员工健康证', description: '检查当日在岗人员健康证是否在有效期内', status: 'pending' },
  { id: 'fs4', category: 'food_safety', name: '冷链温度', description: '检查冷藏（0-4°C）、冷冻（-18°C以下）温度是否达标', status: 'pending' },
  // 环境卫生
  { id: 'hy1', category: 'hygiene', name: '前厅清洁', description: '地面/桌面/椅子清洁无污渍、无异味', status: 'pending' },
  { id: 'hy2', category: 'hygiene', name: '后厨卫生', description: '灶台/切配台/排水沟清洁，无积水积油', status: 'pending' },
  { id: 'hy3', category: 'hygiene', name: '洗手间检查', description: '洗手间清洁、纸巾/洗手液充足、无异味', status: 'pending' },
  { id: 'hy4', category: 'hygiene', name: '垃圾分类', description: '各区域垃圾桶分类正确，未超满', status: 'pending' },
  // 设备检查
  { id: 'eq1', category: 'equipment', name: 'POS设备', description: '收银机/打印机/扫码枪正常运行', status: 'pending' },
  { id: 'eq2', category: 'equipment', name: '厨房设备', description: '灶具/蒸柜/炸炉等设备运行正常、无异常声响', status: 'pending' },
  { id: 'eq3', category: 'equipment', name: '制冷设备', description: '冰箱/冰柜/展示柜正常制冷，无结霜过厚', status: 'pending' },
  // 服务规范
  { id: 'sv1', category: 'service', name: '员工仪容', description: '着装整洁、佩戴工牌、指甲整洁', status: 'pending' },
  { id: 'sv2', category: 'service', name: '服务话术', description: '迎宾/点餐/送客标准话术执行到位', status: 'pending' },
  { id: 'sv3', category: 'service', name: '台面摆设', description: '餐具/调料/纸巾等台面物品摆放规范', status: 'pending' },
  // 消防安全
  { id: 'fr1', category: 'fire_safety', name: '灭火器', description: '灭火器在位、压力正常、在有效期内', status: 'pending' },
  { id: 'fr2', category: 'fire_safety', name: '安全通道', description: '安全出口标识清晰、通道无堵塞', status: 'pending' },
  { id: 'fr3', category: 'fire_safety', name: '燃气安全', description: '燃气管道无泄漏，阀门可正常开关', status: 'pending' },
];

const FALLBACK_RECTIFY: RectifyTask[] = [
  {
    id: 'rt1', title: '后厨排水沟清洁不达标', source: '区域督导巡检',
    deadline: '2026-04-11', status: 'pending',
    description: '4月8日区域督导巡检发现后厨B区排水沟有油污积聚，需彻底清洗并整改防滑措施',
  },
  {
    id: 'rt2', title: '3号灭火器过期更换', source: '消防安全自查',
    deadline: '2026-04-12', status: 'in_progress',
    description: '3号灭火器已过有效期，需联系供应商更换新灭火器并登记',
    feedback: '已联系消防器材公司，预计明日送达',
  },
  {
    id: 'rt3', title: '冷库温度偏高预警', source: 'AI库存Agent',
    deadline: '2026-04-10', status: 'pending',
    description: '系统检测到1号冷库温度连续2小时高于4°C（实测5.2°C），需检修制冷系统',
  },
];

// ─── Tab配置 ───

type PageTab = 'inspection' | 'rectify';

// ─── 主组件 ───

export function PatrolExecutionPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<PageTab>('inspection');

  // 巡检状态
  const [items, setItems] = useState<InspectionItem[]>(FALLBACK_ITEMS);
  const [summary, setSummary] = useState<InspectionSummary>({
    total: FALLBACK_ITEMS.length, completed: 0, pass: 0, fail: 0, na: 0,
  });
  const [expandedCategory, setExpandedCategory] = useState<InspectionCategory | null>('food_safety');
  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);
  const [failNote, setFailNote] = useState('');
  const [failSeverity, setFailSeverity] = useState<'high' | 'medium' | 'low'>('medium');
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 整改状态
  const [rectifyTasks, setRectifyTasks] = useState<RectifyTask[]>(FALLBACK_RECTIFY);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [feedbackText, setFeedbackText] = useState('');
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);

  // ─── 加载数据 ───

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [todayData, itemsData, tasksData] = await Promise.all([
        fetchInspectionToday(),
        fetchInspectionItems(),
        fetchRectifyTasks(),
      ]);
      if (todayData) setSummary(todayData);
      if (itemsData?.items?.length) setItems(itemsData.items);
      if (tasksData?.items) setRectifyTasks(tasksData.items);
    } catch { /* fallback */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ─── 计算统计 ───

  const total = items.length;
  const completed = items.filter(i => i.status !== 'pending').length;
  const passCount = items.filter(i => i.status === 'pass').length;
  const failCount = items.filter(i => i.status === 'fail').length;
  const naCount = items.filter(i => i.status === 'na').length;
  const progress = total > 0 ? Math.round((completed / total) * 100) : 0;
  const categories = Object.keys(CATEGORY_CONFIG) as InspectionCategory[];

  // ─── 巡检操作 ───

  const handleStatusChange = async (itemId: string, newStatus: CheckStatus) => {
    if (newStatus === 'fail') {
      // 不合格：展开填写区
      setExpandedItemId(itemId);
      setFailNote('');
      setFailSeverity('medium');
      setItems(prev => prev.map(i => i.id === itemId ? { ...i, status: 'fail' } : i));
      return;
    }

    setItems(prev => prev.map(i =>
      i.id === itemId ? { ...i, status: newStatus, note: undefined, severity: undefined } : i,
    ));
    if (expandedItemId === itemId) setExpandedItemId(null);

    try {
      await updateInspectionItem(itemId, { status: newStatus });
    } catch { /* offline ok */ }
  };

  const confirmFail = async (itemId: string) => {
    if (!failNote.trim()) return;
    setItems(prev => prev.map(i =>
      i.id === itemId ? { ...i, status: 'fail', note: failNote.trim(), severity: failSeverity } : i,
    ));
    setExpandedItemId(null);

    try {
      await updateInspectionItem(itemId, {
        status: 'fail',
        note: failNote.trim(),
        severity: failSeverity,
      });
    } catch { /* offline ok */ }
  };

  const handleSubmitInspection = async () => {
    const pending = items.filter(i => i.status === 'pending');
    if (pending.length > 0) {
      // 有未检查项，定位到第一个
      const cat = pending[0].category;
      setExpandedCategory(cat);
      return;
    }

    setSubmitting(true);
    try {
      await submitInspection(
        items.map(i => ({ id: i.id, status: i.status, note: i.note, severity: i.severity })),
      );
    } catch { /* offline */ }
    setSubmitted(true);
    setSubmitting(false);
  };

  // ─── 整改操作 ───

  const handleRectifyFeedback = async (taskId: string, status: 'in_progress' | 'completed') => {
    if (status === 'completed' && !feedbackText.trim()) return;
    setFeedbackSubmitting(true);
    try {
      await submitRectifyFeedback(taskId, {
        feedback: feedbackText.trim(),
        status,
      });
      setRectifyTasks(prev => prev.map(t =>
        t.id === taskId ? { ...t, status, feedback: feedbackText.trim() || t.feedback } : t,
      ));
      setExpandedTaskId(null);
      setFeedbackText('');
    } catch { /* offline ok */ }
    setFeedbackSubmitting(false);
  };

  // ─── 已提交巡检报告 ───

  if (submitted) {
    return (
      <div style={pageStyle}>
        <div style={{ textAlign: 'center', paddingTop: 60 }}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>✅</div>
          <div style={{ fontSize: 22, fontWeight: 600, marginBottom: 8, color: '#0F6E56' }}>巡检已完成</div>
          <div style={{ fontSize: 14, color: '#9CA3AF', marginBottom: 24 }}>
            {new Date().toISOString().slice(0, 10)}
          </div>

          {/* 巡检报告摘要 */}
          <div style={{ ...cardStyle, textAlign: 'left', marginBottom: 20 }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>巡检报告摘要</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
              <SummaryCell label="检查总数" value={total} color={C.text} />
              <SummaryCell label="合格" value={passCount} color="#0F6E56" />
              <SummaryCell label="不合格" value={failCount} color="#A32D2D" />
              <SummaryCell label="不适用" value={naCount} color="#6B7280" />
            </div>
            {failCount > 0 && (
              <div style={{ marginTop: 12, padding: 10, background: `${C.danger}22`, borderRadius: 6, fontSize: 13, color: '#A32D2D' }}>
                已自动生成 {failCount} 条整改任务，请在整改跟踪区查看
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <button type="button" onClick={() => { setSubmitted(false); setActiveTab('rectify'); }}
              style={{ flex: 1, padding: '14px 0', background: C.card, color: C.text, border: `1px solid ${C.border}`, borderRadius: 10, fontSize: 16, fontWeight: 500, cursor: 'pointer', minHeight: 52 }}>
              查看整改任务
            </button>
            <button type="button" onClick={() => navigate(-1)}
              style={{ flex: 1, padding: '14px 0', background: C.primary, color: '#fff', border: 'none', borderRadius: 10, fontSize: 16, fontWeight: 600, cursor: 'pointer', minHeight: 52 }}>
              返回
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── 主渲染 ───

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>巡检整改执行</div>
          <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>
            {new Date().toISOString().slice(0, 10)}
            {summary.last_inspection_at && (
              <span> · 上次巡检 {formatTime(summary.last_inspection_at)}</span>
            )}
          </div>
        </div>
        <button type="button" onClick={() => navigate(-1)} style={backBtnStyle}>← 返回</button>
      </div>

      {/* 今日概览 */}
      <div style={{ ...cardStyle, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>今日巡检进度</span>
          <span style={{ fontSize: 16, fontWeight: 600, color: progress === 100 ? '#0F6E56' : C.primary }}>
            {progress}%
          </span>
        </div>
        <div style={{ height: 8, background: C.border, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${progress}%`,
            background: progress === 100 ? '#0F6E56' : C.primary,
            borderRadius: 4, transition: 'width 300ms ease',
          }} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 10 }}>
          <MiniStat label="待检" value={total - completed} color={C.muted} />
          <MiniStat label="合格" value={passCount} color="#0F6E56" />
          <MiniStat label="不合格" value={failCount} color="#A32D2D" />
          <MiniStat label="不适用" value={naCount} color="#6B7280" />
        </div>
      </div>

      {/* Tab切换 */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 16 }}>
        <TabBtn label="巡检执行" active={activeTab === 'inspection'} onClick={() => setActiveTab('inspection')}
          badge={total - completed > 0 ? total - completed : undefined} />
        <TabBtn label="整改跟踪" active={activeTab === 'rectify'} onClick={() => setActiveTab('rectify')}
          badge={rectifyTasks.filter(t => t.status !== 'completed').length || undefined} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {/* ─── 巡检执行区 ─── */}
      {activeTab === 'inspection' && (
        <>
          {categories.map(cat => {
            const cfg = CATEGORY_CONFIG[cat];
            const catItems = items.filter(i => i.category === cat);
            const catCompleted = catItems.filter(i => i.status !== 'pending').length;
            const isExpanded = expandedCategory === cat;

            return (
              <div key={cat} style={{ marginBottom: 12 }}>
                {/* 分类头 */}
                <button type="button" onClick={() => setExpandedCategory(isExpanded ? null : cat)}
                  style={{
                    width: '100%', padding: '14px 16px', background: C.card, border: 'none',
                    borderRadius: isExpanded ? '10px 10px 0 0' : 10,
                    color: '#fff', fontSize: 16, fontWeight: 600, cursor: 'pointer',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center', minHeight: 52,
                  }}>
                  <span>{cfg.icon} {cfg.label}</span>
                  <span style={{ fontSize: 14, color: catCompleted === catItems.length ? '#0F6E56' : '#9CA3AF' }}>
                    {catCompleted}/{catItems.length} {isExpanded ? '▼' : '▶'}
                  </span>
                </button>

                {/* 检查项列表 */}
                {isExpanded && catItems.map(item => {
                  const stCfg = STATUS_CONFIG[item.status];
                  const isItemExpanded = expandedItemId === item.id;

                  return (
                    <div key={item.id} style={{
                      padding: '14px 16px', background: '#0e1e25',
                      borderBottom: `1px solid ${C.border}`,
                    }}>
                      {/* 检查项信息 */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{
                            fontSize: 15, fontWeight: 500,
                            color: item.status === 'fail' ? '#A32D2D' : '#fff',
                          }}>
                            {item.name}
                          </div>
                          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>{item.description}</div>
                        </div>
                        {item.status !== 'pending' && (
                          <span style={{
                            fontSize: 11, padding: '2px 8px', borderRadius: 4,
                            background: `${stCfg.color}22`, color: stCfg.color, fontWeight: 500,
                            flexShrink: 0, marginLeft: 8,
                          }}>
                            {stCfg.label}
                          </span>
                        )}
                      </div>

                      {/* 不合格备注 */}
                      {item.status === 'fail' && item.note && !isItemExpanded && (
                        <div style={{ fontSize: 12, color: '#faad14', marginBottom: 6, padding: '4px 8px', background: `${C.warning}11`, borderRadius: 4 }}>
                          {item.severity && <span style={{ color: SEVERITY_CONFIG[item.severity].color, marginRight: 6 }}>[{SEVERITY_CONFIG[item.severity].label}]</span>}
                          {item.note}
                        </div>
                      )}

                      {/* 快捷状态按钮 */}
                      <div style={{ display: 'flex', gap: 6 }}>
                        <StatusBtn label="合格 ✅" active={item.status === 'pass'} color="#0F6E56"
                          onClick={() => handleStatusChange(item.id, item.status === 'pass' ? 'pending' : 'pass')} />
                        <StatusBtn label="不合格 ❌" active={item.status === 'fail'} color="#A32D2D"
                          onClick={() => handleStatusChange(item.id, item.status === 'fail' ? 'pending' : 'fail')} />
                        <StatusBtn label="不适用 ⚪" active={item.status === 'na'} color="#6B7280"
                          onClick={() => handleStatusChange(item.id, item.status === 'na' ? 'pending' : 'na')} />
                      </div>

                      {/* 不合格展开区 */}
                      {isItemExpanded && item.status === 'fail' && (
                        <div style={{ marginTop: 10, padding: 12, background: C.card, borderRadius: 8 }}>
                          <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 8 }}>问题描述（必填）</div>
                          <textarea
                            value={failNote}
                            onChange={e => setFailNote(e.target.value)}
                            placeholder="描述不合格情况..."
                            rows={3}
                            style={{
                              width: '100%', padding: 10, background: '#0e1e25',
                              border: `1px solid ${C.border}`, borderRadius: 8, color: '#fff',
                              fontSize: 14, resize: 'none', boxSizing: 'border-box', outline: 'none',
                              fontFamily: 'inherit',
                            }}
                          />

                          {/* 严重度选择 */}
                          <div style={{ fontSize: 13, fontWeight: 500, marginTop: 10, marginBottom: 6 }}>严重程度</div>
                          <div style={{ display: 'flex', gap: 8 }}>
                            {(['high', 'medium', 'low'] as const).map(s => (
                              <button key={s} type="button" onClick={() => setFailSeverity(s)}
                                style={{
                                  flex: 1, padding: '8px 0', borderRadius: 6, fontSize: 13, fontWeight: 500,
                                  cursor: 'pointer', minHeight: 36, border: 'none',
                                  background: failSeverity === s ? `${SEVERITY_CONFIG[s].color}33` : '#0e1e25',
                                  color: failSeverity === s ? SEVERITY_CONFIG[s].color : C.muted,
                                }}>
                                {SEVERITY_CONFIG[s].label}
                              </button>
                            ))}
                          </div>

                          {/* 拍照上传（UI预留） */}
                          <button type="button" style={{
                            width: '100%', marginTop: 10, padding: '14px 0',
                            background: '#0e1e25', border: `2px dashed ${C.border}`, borderRadius: 8,
                            color: C.muted, fontSize: 13, cursor: 'pointer',
                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                          }}>
                            <span style={{ fontSize: 18 }}>📷</span> 拍照上传（开发中）
                          </button>

                          {/* 确认/取消 */}
                          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                            <button type="button" onClick={() => { setExpandedItemId(null); setItems(prev => prev.map(i => i.id === item.id ? { ...i, status: 'pending' } : i)); }}
                              style={{ flex: 1, padding: '10px 0', background: '#0e1e25', color: C.muted, border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 14, cursor: 'pointer', minHeight: 40 }}>
                              取消
                            </button>
                            <button type="button" onClick={() => confirmFail(item.id)}
                              disabled={!failNote.trim()}
                              style={{
                                flex: 1, padding: '10px 0', borderRadius: 6, fontSize: 14, fontWeight: 500,
                                cursor: failNote.trim() ? 'pointer' : 'default', minHeight: 40, border: 'none',
                                background: failNote.trim() ? '#A32D2D' : C.muted, color: '#fff',
                                opacity: failNote.trim() ? 1 : 0.5,
                              }}>
                              确认不合格
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}

          {/* 提交巡检按钮 */}
          <div style={{ marginTop: 20, paddingBottom: 20 }}>
            <button type="button" onClick={handleSubmitInspection}
              disabled={submitting || completed === 0}
              style={{
                width: '100%', padding: '16px 0', border: 'none', borderRadius: 10,
                fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 56,
                background: completed === total && completed > 0 ? '#0F6E56' : (completed > 0 ? C.primary : '#444'),
                color: '#fff', opacity: submitting ? 0.6 : 1,
              }}>
              {submitting
                ? '提交中...'
                : completed === total
                  ? `提交巡检报告 (${completed}/${total})`
                  : `还有 ${total - completed} 项未检查`}
            </button>
          </div>
        </>
      )}

      {/* ─── 整改跟踪区 ─── */}
      {activeTab === 'rectify' && (
        <>
          {rectifyTasks.length === 0 && !loading && (
            <div style={{ textAlign: 'center', color: C.muted, padding: 40, fontSize: 14 }}>
              暂无整改任务
            </div>
          )}

          {rectifyTasks.map(task => {
            const sts = RECTIFY_STATUS[task.status];
            const isExpanded = expandedTaskId === task.id;
            const isOverdue = new Date(task.deadline) < new Date() && task.status !== 'completed';

            return (
              <div key={task.id} style={{ ...cardStyle, position: 'relative', overflow: 'hidden' }}>
                {/* 状态颜色条 */}
                <div style={{
                  position: 'absolute', left: 0, top: 0, bottom: 0, width: 4,
                  background: isOverdue ? '#A32D2D' : sts.color,
                  borderRadius: '10px 0 0 10px',
                }} />

                <div onClick={() => { setExpandedTaskId(isExpanded ? null : task.id); setFeedbackText(task.feedback || ''); }}
                  style={{ cursor: 'pointer', paddingLeft: 6 }}>
                  {/* 头部 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4,
                      background: `${sts.color}22`, color: sts.color, fontWeight: 500,
                    }}>{sts.label}</span>
                    {isOverdue && (
                      <span style={{
                        fontSize: 11, padding: '2px 8px', borderRadius: 4,
                        background: '#A32D2D22', color: '#A32D2D', fontWeight: 500,
                      }}>已逾期</span>
                    )}
                    <span style={{ fontSize: 12, color: C.muted, marginLeft: 'auto' }}>
                      截止 {task.deadline}
                    </span>
                  </div>

                  {/* 标题 */}
                  <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>{task.title}</div>

                  {/* 来源 */}
                  <div style={{ fontSize: 12, color: C.muted }}>
                    来源：{task.source}
                  </div>

                  <div style={{ textAlign: 'center', marginTop: 4 }}>
                    <span style={{ fontSize: 10, color: C.muted }}>{isExpanded ? '▲ 收起' : '▼ 展开详情'}</span>
                  </div>
                </div>

                {/* 展开详情 */}
                {isExpanded && (
                  <div style={{ paddingLeft: 6, marginTop: 10, borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>
                    {/* 描述 */}
                    <div style={{ fontSize: 13, color: C.text, marginBottom: 12, lineHeight: 1.6 }}>
                      {task.description}
                    </div>

                    {/* 已有反馈 */}
                    {task.feedback && task.status !== 'pending' && (
                      <div style={{ fontSize: 13, color: '#faad14', marginBottom: 12, padding: 8, background: `${C.warning}11`, borderRadius: 6 }}>
                        <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>执行反馈</div>
                        {task.feedback}
                      </div>
                    )}

                    {/* Before/After 照片预留 */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
                      <div style={{
                        padding: '20px 0', background: '#0e1e25', border: `2px dashed ${C.border}`,
                        borderRadius: 8, textAlign: 'center', color: C.muted, fontSize: 12,
                      }}>
                        <div style={{ fontSize: 18, marginBottom: 4 }}>📷</div>
                        整改前照片
                      </div>
                      <div style={{
                        padding: '20px 0', background: '#0e1e25', border: `2px dashed ${C.border}`,
                        borderRadius: 8, textAlign: 'center', color: C.muted, fontSize: 12,
                      }}>
                        <div style={{ fontSize: 18, marginBottom: 4 }}>📷</div>
                        整改后照片
                      </div>
                    </div>

                    {/* 操作区 */}
                    {task.status !== 'completed' && (
                      <>
                        <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>执行反馈</div>
                        <textarea
                          value={feedbackText}
                          onChange={e => setFeedbackText(e.target.value)}
                          placeholder="描述整改执行情况..."
                          rows={3}
                          onClick={e => e.stopPropagation()}
                          style={{
                            width: '100%', padding: 10, background: '#0e1e25',
                            border: `1px solid ${C.border}`, borderRadius: 8, color: '#fff',
                            fontSize: 14, resize: 'none', boxSizing: 'border-box', outline: 'none',
                            fontFamily: 'inherit', marginBottom: 10,
                          }}
                        />
                        <div style={{ display: 'flex', gap: 8 }}>
                          {task.status === 'pending' && (
                            <button type="button"
                              onClick={e => { e.stopPropagation(); handleRectifyFeedback(task.id, 'in_progress'); }}
                              disabled={feedbackSubmitting}
                              style={{
                                flex: 1, padding: '10px 0', background: C.warning, color: '#fff',
                                border: 'none', borderRadius: 6, fontSize: 14, fontWeight: 500,
                                cursor: 'pointer', minHeight: 40, opacity: feedbackSubmitting ? 0.6 : 1,
                              }}>
                              开始执行
                            </button>
                          )}
                          <button type="button"
                            onClick={e => { e.stopPropagation(); handleRectifyFeedback(task.id, 'completed'); }}
                            disabled={feedbackSubmitting || !feedbackText.trim()}
                            style={{
                              flex: 1, padding: '10px 0', border: 'none', borderRadius: 6,
                              fontSize: 14, fontWeight: 500, cursor: feedbackText.trim() ? 'pointer' : 'default',
                              minHeight: 40, opacity: feedbackSubmitting ? 0.6 : 1,
                              background: feedbackText.trim() ? C.success : C.muted, color: '#fff',
                            }}>
                            完成整改
                          </button>
                        </div>
                      </>
                    )}

                    {task.status === 'completed' && (
                      <div style={{ textAlign: 'center', padding: 10, color: '#0F6E56', fontSize: 14, fontWeight: 500 }}>
                        ✅ 整改已完成
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

// ─── 子组件 ───

function StatusBtn({ label, active, color, onClick }: {
  label: string; active: boolean; color: string; onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} style={{
      flex: 1, padding: '8px 0', borderRadius: 6, fontSize: 12, fontWeight: 600,
      cursor: 'pointer', border: 'none', minHeight: 36, transition: 'all 150ms ease',
      background: active ? `${color}33` : '#0e1e25',
      color: active ? color : C.muted,
    }}>
      {label}
    </button>
  );
}

function TabBtn({ label, active, onClick, badge }: {
  label: string; active: boolean; onClick: () => void; badge?: number;
}) {
  return (
    <button type="button" onClick={onClick} style={{
      flex: 1, padding: '12px 0', border: 'none', cursor: 'pointer', minHeight: 44,
      fontSize: 15, fontWeight: active ? 600 : 400, position: 'relative',
      background: active ? C.card : 'transparent',
      color: active ? '#fff' : C.muted,
      borderBottom: active ? `2px solid ${C.primary}` : `2px solid transparent`,
    }}>
      {label}
      {badge !== undefined && badge > 0 && (
        <span style={{
          position: 'absolute', top: 6, right: '20%',
          width: 18, height: 18, borderRadius: '50%',
          background: C.danger, color: '#fff', fontSize: 11,
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600,
        }}>
          {badge}
        </span>
      )}
    </button>
  );
}

function MiniStat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{label}</div>
    </div>
  );
}

function SummaryCell({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ background: '#0e1e25', borderRadius: 8, padding: 12, textAlign: 'center' }}>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>{label}</div>
    </div>
  );
}

// ─── 工具函数 ───

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const h = d.getHours().toString().padStart(2, '0');
    const m = d.getMinutes().toString().padStart(2, '0');
    return `${h}:${m}`;
  } catch {
    return iso;
  }
}

const backBtnStyle: React.CSSProperties = {
  padding: '6px 14px',
  background: '#1a2a33',
  color: '#9CA3AF',
  border: '1px solid #333',
  borderRadius: 6,
  fontSize: 14,
  cursor: 'pointer',
  minHeight: 36,
};
