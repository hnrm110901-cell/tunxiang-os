/**
 * 门店异常事件中心 — /manager/incidents
 * 统一记录和处理门店各类异常事件
 * 分类Tab + 异常列表 + 快速上报 + 详情展开 + 今日统计
 *
 * API:
 *   GET  /api/v1/ops/incidents?category=&status=
 *   GET  /api/v1/ops/incidents/summary
 *   POST /api/v1/ops/incidents
 *   PATCH /api/v1/ops/incidents/:id/status
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchIncidents,
  fetchIncidentSummary,
  createIncident,
  updateIncidentStatus,
} from '../../api/storeLiveApi';
import type {
  Incident,
  IncidentCategory,
  IncidentStatus,
  IncidentSummary,
  CreateIncidentPayload,
} from '../../api/storeLiveApi';

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

const CATEGORY_CONFIG: Record<IncidentCategory, { label: string; icon: string; color: string }> = {
  shortage: { label: '缺货', icon: '📦', color: '#BA7517' },
  complaint: { label: '客诉', icon: '😤', color: '#A32D2D' },
  slow_dish: { label: '出品超时', icon: '⏱️', color: '#FF6B35' },
  return: { label: '退菜', icon: '🔄', color: '#A32D2D' },
  equipment: { label: '设备异常', icon: '🔧', color: '#185FA5' },
  staff: { label: '人员异常', icon: '👤', color: '#BA7517' },
};

const ALL_CATEGORIES: (IncidentCategory | 'all')[] = [
  'all', 'shortage', 'complaint', 'slow_dish', 'return', 'equipment', 'staff',
];

const STATUS_LABEL: Record<IncidentStatus, { label: string; color: string }> = {
  open: { label: '待处理', color: C.danger },
  processing: { label: '处理中', color: C.warning },
  closed: { label: '已关闭', color: C.success },
};

const SEVERITY_COLOR: Record<string, string> = {
  high: C.danger,
  medium: C.warning,
  low: C.success,
};

const SEVERITY_LABEL: Record<string, string> = {
  high: '紧急',
  medium: '一般',
  low: '低',
};

// ─── Fallback ───

const FALLBACK_SUMMARY: IncidentSummary = { today_new: 8, today_open: 3, today_closed: 5 };

const FALLBACK_INCIDENTS: Incident[] = [
  {
    id: 'inc_001',
    category: 'complaint',
    title: 'B12桌客人投诉等菜超30分钟',
    description: '客人12:05入座点餐，12:35仍有3道菜未上，情绪激动要求退菜并给予补偿',
    severity: 'high',
    status: 'open',
    created_at: '2026-04-10T12:40:00',
    updated_at: '2026-04-10T12:40:00',
    reporter: '张小凤',
    timeline: [
      { time: '12:40', action: '服务员上报客诉', operator: '张小凤' },
    ],
  },
  {
    id: 'inc_002',
    category: 'slow_dish',
    title: '剁椒鱼头出品超时22分钟',
    description: 'A05桌剁椒鱼头超时，后厨反馈蒸柜排队导致延误',
    severity: 'high',
    status: 'processing',
    created_at: '2026-04-10T12:30:00',
    updated_at: '2026-04-10T12:35:00',
    reporter: '系统自动',
    handler: '王大厨',
    timeline: [
      { time: '12:30', action: '系统检测出品超时', operator: '系统' },
      { time: '12:35', action: '后厨确认处理中', operator: '王大厨' },
    ],
  },
  {
    id: 'inc_003',
    category: 'shortage',
    title: '活鲜鲈鱼库存不足',
    description: '当前库存仅剩2.8kg，预计只能满足3-4份订单，建议临时沽清或紧急采购',
    severity: 'medium',
    status: 'open',
    created_at: '2026-04-10T11:20:00',
    updated_at: '2026-04-10T11:20:00',
    reporter: '库存Agent',
    timeline: [
      { time: '11:20', action: '库存预警触发', operator: '库存Agent' },
    ],
  },
  {
    id: 'inc_004',
    category: 'equipment',
    title: '3号打印机离线',
    description: 'B区后厨3号打印机断开连接，已自动切换到4号打印机',
    severity: 'medium',
    status: 'processing',
    created_at: '2026-04-10T10:50:00',
    updated_at: '2026-04-10T11:00:00',
    reporter: '系统自动',
    handler: '李工',
    timeline: [
      { time: '10:50', action: '检测到打印机离线', operator: '系统' },
      { time: '10:52', action: '自动切换备用打印机', operator: '系统' },
      { time: '11:00', action: '通知维修人员', operator: '李工' },
    ],
  },
  {
    id: 'inc_005',
    category: 'return',
    title: '皮蛋豆腐退菜 - 菜品变质',
    description: 'A02桌退回皮蛋豆腐一份，发现豆腐有异味，已通知后厨下架该批次',
    severity: 'high',
    status: 'closed',
    created_at: '2026-04-10T12:35:00',
    updated_at: '2026-04-10T12:45:00',
    reporter: '张小凤',
    handler: '王大厨',
    timeline: [
      { time: '12:35', action: '服务员上报退菜', operator: '张小凤' },
      { time: '12:38', action: '后厨确认下架该批次', operator: '王大厨' },
      { time: '12:45', action: '已为客人更换新菜品并致歉', operator: '张小凤' },
    ],
    rectification_task_id: 'task_001',
  },
  {
    id: 'inc_006',
    category: 'staff',
    title: '晚班服务员小刘请假',
    description: '小刘临时请假（身体不适），晚班B区服务员缺1人，需安排替补',
    severity: 'medium',
    status: 'open',
    created_at: '2026-04-10T14:00:00',
    updated_at: '2026-04-10T14:00:00',
    reporter: '小刘',
    timeline: [
      { time: '14:00', action: '员工提交请假申请', operator: '小刘' },
    ],
  },
];

// ─── 主组件 ───

export function StoreIncidentsCenterPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<IncidentSummary>(FALLBACK_SUMMARY);
  const [incidents, setIncidents] = useState<Incident[]>(FALLBACK_INCIDENTS);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<IncidentCategory | 'all'>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [s, d] = await Promise.all([
        fetchIncidentSummary(),
        fetchIncidents(activeTab === 'all' ? undefined : activeTab),
      ]);
      if (s) setSummary(s);
      if (d?.items) setIncidents(d.items);
    } catch { /* fallback */ }
    setLoading(false);
  }, [activeTab]);

  useEffect(() => { loadData(); }, [loadData]);

  const filtered = activeTab === 'all'
    ? incidents
    : incidents.filter(inc => inc.category === activeTab);

  const handleStatusUpdate = async (id: string, status: IncidentStatus) => {
    try {
      await updateIncidentStatus(id, status);
      setIncidents(prev =>
        prev.map(inc => inc.id === id ? { ...inc, status, updated_at: new Date().toISOString() } : inc)
      );
    } catch { /* ignore */ }
  };

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>异常事件中心</div>
          <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>
            {new Date().toISOString().slice(0, 10)}
          </div>
        </div>
        <button type="button" onClick={() => navigate(-1)} style={backBtnStyle}>
          ← 返回
        </button>
      </div>

      {/* 今日统计条 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
        <StatCard label="今日新增" value={summary.today_new} color={C.primary} />
        <StatCard label="待处理" value={summary.today_open} color={C.danger} />
        <StatCard label="已处理" value={summary.today_closed} color={C.success} />
      </div>

      {/* 分类Tab */}
      <div style={{
        display: 'flex',
        gap: 6,
        overflowX: 'auto',
        paddingBottom: 8,
        marginBottom: 12,
        WebkitOverflowScrolling: 'touch',
      }}>
        {ALL_CATEGORIES.map(cat => {
          const isActive = activeTab === cat;
          const cfg = cat === 'all' ? null : CATEGORY_CONFIG[cat];
          return (
            <button
              key={cat}
              type="button"
              onClick={() => setActiveTab(cat)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                padding: '6px 12px',
                borderRadius: 16,
                border: 'none',
                background: isActive ? C.primary : C.card,
                color: isActive ? '#fff' : C.text,
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                minHeight: 32,
              }}
            >
              {cfg ? <span>{cfg.icon}</span> : null}
              {cat === 'all' ? '全部' : cfg!.label}
            </button>
          );
        })}
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {/* 异常列表 */}
      {filtered.map(inc => {
        const cfg = CATEGORY_CONFIG[inc.category];
        const sts = STATUS_LABEL[inc.status];
        const isExpanded = expandedId === inc.id;

        return (
          <div key={inc.id} style={{ ...cardStyle, position: 'relative', overflow: 'hidden' }}>
            {/* 严重度颜色条 */}
            <div style={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: 4,
              background: SEVERITY_COLOR[inc.severity],
              borderRadius: '10px 0 0 10px',
            }} />

            <div
              onClick={() => setExpandedId(isExpanded ? null : inc.id)}
              style={{ cursor: 'pointer', paddingLeft: 6 }}
            >
              {/* 头部行 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 18 }}>{cfg.icon}</span>
                <span style={{
                  fontSize: 11,
                  background: `${cfg.color}22`,
                  color: cfg.color,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 500,
                }}>{cfg.label}</span>
                <span style={{
                  fontSize: 11,
                  background: `${sts.color}22`,
                  color: sts.color,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 500,
                  marginLeft: 'auto',
                }}>{sts.label}</span>
              </div>

              {/* 标题 */}
              <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4, paddingRight: 20 }}>
                {inc.title}
              </div>

              {/* 时间与严重度 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: C.muted }}>
                <span>{formatTime(inc.created_at)}</span>
                <span style={{ color: SEVERITY_COLOR[inc.severity] }}>
                  {SEVERITY_LABEL[inc.severity]}
                </span>
              </div>

              {/* 展开箭头 */}
              <div style={{ textAlign: 'center', marginTop: 4 }}>
                <span style={{ fontSize: 10, color: C.muted }}>{isExpanded ? '▲ 收起' : '▼ 展开详情'}</span>
              </div>
            </div>

            {/* 展开详情 */}
            {isExpanded && (
              <div style={{ paddingLeft: 6, marginTop: 10, borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>
                {/* 完整描述 */}
                <div style={{ fontSize: 13, color: C.text, marginBottom: 12, lineHeight: 1.6 }}>
                  {inc.description}
                </div>

                {/* 信息行 */}
                <div style={{ fontSize: 12, color: C.muted, marginBottom: 12 }}>
                  <div>上报人: {inc.reporter}</div>
                  {inc.handler && <div style={{ marginTop: 2 }}>处理人: {inc.handler}</div>}
                  {inc.rectification_task_id && (
                    <div style={{ marginTop: 2, color: C.primary }}>
                      关联整改: {inc.rectification_task_id}
                    </div>
                  )}
                </div>

                {/* 处理记录时间线 */}
                {inc.timeline.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: C.muted, marginBottom: 8 }}>处理记录</div>
                    {inc.timeline.map((t, i) => (
                      <div key={i} style={{ display: 'flex', gap: 10, marginBottom: 8, position: 'relative' }}>
                        {/* 时间线轴 */}
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 12 }}>
                          <div style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: i === inc.timeline.length - 1 ? C.primary : C.muted,
                            flexShrink: 0,
                            marginTop: 4,
                          }} />
                          {i < inc.timeline.length - 1 && (
                            <div style={{ width: 1, flex: 1, background: C.border, marginTop: 2 }} />
                          )}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13 }}>{t.action}</div>
                          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{t.time} · {t.operator}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* 操作按钮 */}
                {inc.status !== 'closed' && (
                  <div style={{ display: 'flex', gap: 8 }}>
                    {inc.status === 'open' && (
                      <button
                        type="button"
                        onClick={() => handleStatusUpdate(inc.id, 'processing')}
                        style={{
                          flex: 1,
                          padding: '10px 0',
                          background: C.warning,
                          color: '#fff',
                          border: 'none',
                          borderRadius: 6,
                          fontSize: 14,
                          fontWeight: 500,
                          cursor: 'pointer',
                          minHeight: 40,
                        }}
                      >
                        开始处理
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleStatusUpdate(inc.id, 'closed')}
                      style={{
                        flex: 1,
                        padding: '10px 0',
                        background: C.success,
                        color: '#fff',
                        border: 'none',
                        borderRadius: 6,
                        fontSize: 14,
                        fontWeight: 500,
                        cursor: 'pointer',
                        minHeight: 40,
                      }}
                    >
                      关闭事件
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      {filtered.length === 0 && !loading && (
        <div style={{ textAlign: 'center', color: C.muted, padding: 40, fontSize: 14 }}>
          暂无异常事件
        </div>
      )}

      {/* 快速上报悬浮按钮 */}
      <button
        type="button"
        onClick={() => setShowReport(true)}
        style={{
          position: 'fixed',
          bottom: 96,
          right: 20,
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: C.primary,
          color: '#fff',
          border: 'none',
          fontSize: 28,
          fontWeight: 300,
          cursor: 'pointer',
          boxShadow: '0 4px 16px rgba(255,107,53,0.4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100,
        }}
      >
        +
      </button>

      {/* 上报弹窗 */}
      {showReport && (
        <ReportModal
          onClose={() => setShowReport(false)}
          onSubmit={async (payload) => {
            try {
              await createIncident(payload);
              setShowReport(false);
              loadData();
            } catch { /* ignore */ }
          }}
        />
      )}
    </div>
  );
}

// ─── 上报弹窗组件 ───

function ReportModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void;
  onSubmit: (payload: CreateIncidentPayload) => Promise<void>;
}) {
  const [category, setCategory] = useState<IncidentCategory>('complaint');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [severity, setSeverity] = useState<'high' | 'medium' | 'low'>('medium');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!title.trim()) return;
    setSubmitting(true);
    await onSubmit({ category, title: title.trim(), description: description.trim(), severity });
    setSubmitting(false);
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.7)',
      zIndex: 200,
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'center',
    }}>
      <div style={{
        background: C.bg,
        borderRadius: '16px 16px 0 0',
        width: '100%',
        maxWidth: 500,
        maxHeight: '85vh',
        overflow: 'auto',
        padding: 20,
      }}>
        {/* 头部 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>上报异常</div>
          <button type="button" onClick={onClose} style={{
            background: 'none',
            border: 'none',
            color: C.muted,
            fontSize: 24,
            cursor: 'pointer',
            padding: 4,
          }}>
            ✕
          </button>
        </div>

        {/* 异常类型 */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>异常类型</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {(Object.entries(CATEGORY_CONFIG) as [IncidentCategory, typeof CATEGORY_CONFIG[IncidentCategory]][]).map(
              ([key, cfg]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setCategory(key)}
                  style={{
                    padding: '10px 0',
                    background: category === key ? `${cfg.color}22` : C.card,
                    border: `1px solid ${category === key ? cfg.color : C.border}`,
                    borderRadius: 8,
                    color: category === key ? cfg.color : C.text,
                    fontSize: 13,
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 4,
                    minHeight: 52,
                  }}
                >
                  <span>{cfg.icon}</span>
                  {cfg.label}
                </button>
              ),
            )}
          </div>
        </div>

        {/* 标题 */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>标题</div>
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="简要描述异常情况"
            style={{
              width: '100%',
              padding: '10px 12px',
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              color: '#fff',
              fontSize: 14,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* 描述 */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>详细描述</div>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            placeholder="详细描述异常情况、影响范围等"
            rows={4}
            style={{
              width: '100%',
              padding: '10px 12px',
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              color: '#fff',
              fontSize: 14,
              outline: 'none',
              resize: 'vertical',
              boxSizing: 'border-box',
              fontFamily: 'inherit',
            }}
          />
        </div>

        {/* 拍照上传（预留） */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>拍照上传</div>
          <button
            type="button"
            style={{
              width: '100%',
              padding: '20px 0',
              background: C.card,
              border: `2px dashed ${C.border}`,
              borderRadius: 8,
              color: C.muted,
              fontSize: 14,
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <span style={{ fontSize: 24 }}>📷</span>
            点击拍照或上传图片
          </button>
        </div>

        {/* 严重度 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>严重程度</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['high', 'medium', 'low'] as const).map(s => (
              <button
                key={s}
                type="button"
                onClick={() => setSeverity(s)}
                style={{
                  flex: 1,
                  padding: '10px 0',
                  background: severity === s ? `${SEVERITY_COLOR[s]}22` : C.card,
                  border: `1px solid ${severity === s ? SEVERITY_COLOR[s] : C.border}`,
                  borderRadius: 8,
                  color: severity === s ? SEVERITY_COLOR[s] : C.text,
                  fontSize: 14,
                  fontWeight: severity === s ? 600 : 400,
                  cursor: 'pointer',
                  minHeight: 40,
                }}
              >
                {SEVERITY_LABEL[s]}
              </button>
            ))}
          </div>
        </div>

        {/* 提交 */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!title.trim() || submitting}
          style={{
            width: '100%',
            padding: '14px 0',
            background: !title.trim() ? C.muted : C.primary,
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            fontSize: 16,
            fontWeight: 500,
            cursor: !title.trim() ? 'default' : 'pointer',
            minHeight: 48,
            opacity: submitting ? 0.6 : 1,
            marginBottom: 20,
          }}
        >
          {submitting ? '提交中...' : '提交上报'}
        </button>
      </div>
    </div>
  );
}

// ─── 子组件 ───

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{
      background: C.card,
      borderRadius: 10,
      padding: 12,
      textAlign: 'center',
    }}>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
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
