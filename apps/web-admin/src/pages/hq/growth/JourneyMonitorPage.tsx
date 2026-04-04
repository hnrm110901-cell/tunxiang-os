/**
 * JourneyMonitorPage — 会员旅程执行监控仪表板
 * 与 JourneyListPage 风格一致（深色主题，inline styles）
 * 30 秒自动刷新，侧边抽屉展示旅程详情
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetch } from '../../../api/index';

// ---- 颜色常量（与 JourneyListPage 一致）----
const BG_0 = '#0B1A20';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const RED = '#ff4d4f';
const DEEP_GRAY = '#444444';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

interface JourneyStep {
  step_id: string;
  type: string;
  name: string;
  execution_count?: number;
  active_count?: number;
}

interface JourneyStats {
  total_enrollments: number;
  active_enrollments: number;
  completions_today: number;
  triggers_today: number;
}

interface JourneyDefinition {
  id: string;
  name: string;
  status: 'draft' | 'active' | 'paused' | 'ended';
  trigger_event: string;
  steps: JourneyStep[];
  stats: JourneyStats;
  last_triggered_at?: string;
  created_at: string;
}

interface JourneyEnrollment {
  enrollment_id: string;
  customer_id: string;
  entered_at: string;
  current_step: string;
  status: string;
}

// ---- 内置模板定义 ----

const BUILT_IN_TEMPLATES = [
  {
    id: 'first_visit_welcome',
    icon: '👋',
    name: '首次到访欢迎',
    description: '新客首次到访后自动触发欢迎消息，3天后推送复购优惠券',
  },
  {
    id: 'dormant_recall',
    icon: '😴',
    name: '沉睡客唤醒',
    description: '60天未到店客户，分阶段发送唤醒消息和专属折扣',
  },
  {
    id: 'birthday_vip',
    icon: '🎂',
    name: '生日VIP关怀',
    description: '会员生日前后7天，自动推送生日祝福与专属优惠',
  },
  {
    id: 'post_banquet',
    icon: '🥂',
    name: '宴席后关怀',
    description: '宴席结束后24小时内触发感谢消息，7天后邀请再次预订',
  },
  {
    id: 'high_value_nurture',
    icon: '💎',
    name: '高价值客户培育',
    description: '消费满足阈值的客户自动进入VIP培育流程，推送专属权益',
  },
];

// ---- 工具函数 ----

function statusLabel(status: JourneyDefinition['status']): string {
  const MAP = { active: '运行中', paused: '已暂停', draft: '草稿', ended: '已结束' };
  return MAP[status] || status;
}

function statusColor(status: JourneyDefinition['status']): string {
  const MAP: Record<string, string> = {
    active: GREEN,
    paused: YELLOW,
    draft: TEXT_4,
    ended: DEEP_GRAY,
  };
  return MAP[status] || TEXT_4;
}

function stepIcon(type: string): string {
  const MAP: Record<string, string> = {
    trigger: '⚡',
    message: '💬',
    wait: '⏳',
    coupon: '🎫',
    condition: '🔀',
    tag: '🏷️',
    end: '🏁',
  };
  return MAP[type] || '◯';
}

function relativeTime(iso?: string): string {
  if (!iso) return '暂无记录';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  return `${Math.floor(hours / 24)}天前`;
}

function conversionRate(stats: JourneyStats): string {
  if (!stats.triggers_today) return '-';
  return ((stats.completions_today / stats.triggers_today) * 100).toFixed(0) + '%';
}

// ---- Mock 数据已移除，API 失败时 fallback 空数据 ----

// ---- 主页面 ----

export function JourneyMonitorPage() {
  const [journeys, setJourneys] = useState<JourneyDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedJourney, setSelectedJourney] = useState<JourneyDefinition | null>(null);
  const [enrollments, setEnrollments] = useState<JourneyEnrollment[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importingTemplate, setImportingTemplate] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // 加载旅程列表（旅程执行状态监控）
  const loadJourneys = useCallback(async () => {
    try {
      const data = await txFetch<{ items: JourneyDefinition[] }>('/api/v1/growth/journeys');
      setJourneys(data.items ?? []);
    } catch {
      // API 不可用时 fallback 空列表，显示"暂无数据"
      setJourneys([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // 加载节点执行历史
  const loadEnrollments = useCallback(async (journeyId: string) => {
    try {
      const data = await txFetch<{ items: JourneyEnrollment[] }>(
        `/api/v1/growth/journeys/${encodeURIComponent(journeyId)}/executions?limit=20`,
      );
      setEnrollments(data.items ?? []);
    } catch {
      // API 失败时 fallback 空列表
      setEnrollments([]);
    }
  }, []);

  // 首次加载 + 30秒自动刷新
  useEffect(() => {
    loadJourneys();
    const timer = setInterval(loadJourneys, 30000);
    return () => clearInterval(timer);
  }, [loadJourneys]);

  // 打开抽屉时加载参与记录
  const openDrawer = useCallback(async (j: JourneyDefinition) => {
    setSelectedJourney(j);
    setDrawerOpen(true);
    await loadEnrollments(j.id);
  }, [loadEnrollments]);

  // 激活/暂停旅程
  const toggleJourneyStatus = useCallback(async (j: JourneyDefinition) => {
    const isActive = j.status === 'active';
    const endpoint = `/api/v1/growth/journeys/${encodeURIComponent(j.id)}`;

    // 乐观更新
    const newStatus: JourneyDefinition['status'] = isActive ? 'paused' : 'active';
    const newStatusVal = newStatus;
    setJourneys(prev => prev.map(item =>
      item.id === j.id ? { ...item, status: newStatus } : item,
    ));
    if (selectedJourney?.id === j.id) {
      setSelectedJourney(prev => prev ? { ...prev, status: newStatus } : prev);
    }

    setActionLoading(j.id);
    try {
      await txFetch(endpoint, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatusVal }),
      });
    } catch {
      // 回滚乐观更新
      setJourneys(prev => prev.map(item =>
        item.id === j.id ? { ...item, status: j.status } : item,
      ));
      if (selectedJourney?.id === j.id) {
        setSelectedJourney(prev => prev ? { ...prev, status: j.status } : prev);
      }
    } finally {
      setActionLoading(null);
    }
  }, [selectedJourney]);

  // 导入模板
  const importTemplate = useCallback(async (templateId: string) => {
    setImportingTemplate(templateId);
    try {
      await txFetch('/api/v1/growth/journeys/from-template', {
        method: 'POST',
        body: JSON.stringify({ template_id: templateId }),
      });
      await loadJourneys();
    } catch {
      // 即使 API 失败也静默处理
    } finally {
      setImportingTemplate(null);
    }
  }, [loadJourneys]);

  // ---- 汇总数据 ----
  const totalActive = journeys.filter(j => j.status === 'active').length;
  const totalTriggersToday = journeys.reduce((s, j) => s + j.stats.triggers_today, 0);
  const totalActiveEnrollments = journeys.reduce((s, j) => s + j.stats.active_enrollments, 0);
  const totalCompletionsToday = journeys.reduce((s, j) => s + j.stats.completions_today, 0);

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 页头 */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
          🗺️ 旅程执行监控
        </h2>
        <div style={{ fontSize: 12, color: TEXT_3, marginTop: 4 }}>
          实时查看所有会员旅程的运行状态、触发记录和转化效果 · 每30秒自动刷新
        </div>
      </div>

      {/* 顶部汇总卡片行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        <SummaryCard label="运行中旅程" value={totalActive} color={GREEN} icon="▶" suffix="个" />
        <SummaryCard label="今日触发次数" value={totalTriggersToday} color={BLUE} icon="⚡" suffix="次" />
        <SummaryCard label="活跃会员数" value={totalActiveEnrollments} color={BRAND} icon="👥" suffix="人" />
        <SummaryCard label="今日转化次数" value={totalCompletionsToday} color={YELLOW} icon="🎯" suffix="次" />
      </div>

      {/* 旅程状态列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
        {loading && (
          <div style={{ textAlign: 'center', padding: 40, color: TEXT_3, fontSize: 13 }}>
            加载中...
          </div>
        )}
        {!loading && journeys.length === 0 && (
          <div style={{
            textAlign: 'center', padding: 40, color: TEXT_3, fontSize: 13,
            background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
          }}>
            暂无数据
          </div>
        )}
        {!loading && journeys.map(j => (
          <JourneyRow
            key={j.id}
            journey={j}
            actionLoading={actionLoading === j.id}
            onViewDetail={() => openDrawer(j)}
            onToggleStatus={() => toggleJourneyStatus(j)}
          />
        ))}
      </div>

      {/* 模板导入区 */}
      <div style={{
        background: BG_1, borderRadius: 12, padding: '18px 20px',
        border: `1px solid ${BG_2}`, marginBottom: 24,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
          <span style={{ fontSize: 16 }}>📦</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>内置模板库</span>
          <span style={{ fontSize: 11, color: TEXT_3 }}>· 5个精选旅程模板，一键导入即可使用</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
          {BUILT_IN_TEMPLATES.map(t => (
            <TemplateCard
              key={t.id}
              template={t}
              importing={importingTemplate === t.id}
              onImport={() => importTemplate(t.id)}
            />
          ))}
        </div>
      </div>

      {/* 侧边抽屉 */}
      {drawerOpen && selectedJourney && (
        <>
          {/* 遮罩 */}
          <div
            style={{
              position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
              zIndex: 999, cursor: 'pointer',
            }}
            onClick={() => setDrawerOpen(false)}
          />
          {/* 抽屉主体 */}
          <div style={{
            position: 'fixed', top: 0, right: 0, bottom: 0, width: 420,
            background: BG_0, borderLeft: `1px solid ${BG_2}`,
            zIndex: 1000, display: 'flex', flexDirection: 'column',
            boxShadow: '-8px 0 32px rgba(0,0,0,0.6)',
            animation: 'slideInRight .25s ease-out',
          }}>
            <JourneyDrawer
              journey={selectedJourney}
              enrollments={enrollments}
              actionLoading={actionLoading === selectedJourney.id}
              onClose={() => setDrawerOpen(false)}
              onToggleStatus={() => toggleJourneyStatus(selectedJourney)}
            />
          </div>
        </>
      )}
    </div>
  );
}

// ---- 汇总卡片 ----

function SummaryCard({
  label, value, color, icon, suffix,
}: {
  label: string; value: number; color: string; icon: string; suffix: string;
}) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 18px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{ fontSize: 11, color: TEXT_4 }}>{label}</span>
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color }}>
        {value.toLocaleString()}
        <span style={{ fontSize: 13, fontWeight: 400, color: TEXT_3, marginLeft: 4 }}>{suffix}</span>
      </div>
    </div>
  );
}

// ---- 旅程行卡片 ----

function JourneyRow({
  journey: j,
  actionLoading,
  onViewDetail,
  onToggleStatus,
}: {
  journey: JourneyDefinition;
  actionLoading: boolean;
  onViewDetail: () => void;
  onToggleStatus: () => void;
}) {
  const sc = statusColor(j.status);
  const sl = statusLabel(j.status);
  const cr = conversionRate(j.stats);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 20px',
      border: `1px solid ${BG_2}`,
    }}>
      {/* 第一行：名称 + 状态徽章 + 统计 + 操作按钮 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        {/* 状态指示点 */}
        <span style={{
          width: 8, height: 8, borderRadius: '50%', background: sc,
          boxShadow: j.status === 'active' ? `0 0 6px ${sc}` : 'none',
          flexShrink: 0,
        }} />

        {/* 旅程名 */}
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{j.name}</span>

        {/* 状态徽章 */}
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 10,
          background: sc + '22', color: sc, fontWeight: 600, flexShrink: 0,
        }}>{sl}</span>

        {/* 统计 */}
        <div style={{ display: 'flex', gap: 16, marginLeft: 4, fontSize: 12 }}>
          <span>
            <span style={{ color: TEXT_4 }}>触发: </span>
            <span style={{ color: TEXT_2, fontWeight: 600 }}>{j.stats.triggers_today}</span>
            <span style={{ color: TEXT_4 }}>次</span>
          </span>
          <span>
            <span style={{ color: TEXT_4 }}>转化: </span>
            <span style={{ color: j.stats.completions_today > 0 ? GREEN : TEXT_3, fontWeight: 600 }}>
              {j.stats.completions_today}
            </span>
            <span style={{ color: TEXT_4 }}>次</span>
            {cr !== '-' && (
              <span style={{
                marginLeft: 4, fontSize: 10, padding: '1px 5px', borderRadius: 8,
                background: GREEN + '22', color: GREEN,
              }}>
                {cr}
              </span>
            )}
          </span>
          <span>
            <span style={{ color: TEXT_4 }}>活跃: </span>
            <span style={{ color: BLUE, fontWeight: 600 }}>{j.stats.active_enrollments}</span>
            <span style={{ color: TEXT_4 }}>人</span>
          </span>
        </div>

        {/* 弹性空间 */}
        <div style={{ flex: 1 }} />

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          <button
            onClick={onViewDetail}
            style={{
              padding: '5px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
              background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
            }}
          >查看详情</button>
          {(j.status === 'active' || j.status === 'paused') && (
            <button
              onClick={onToggleStatus}
              disabled={actionLoading}
              style={{
                padding: '5px 14px', borderRadius: 6, border: 'none',
                background: j.status === 'active' ? YELLOW + '22' : GREEN + '22',
                color: j.status === 'active' ? YELLOW : GREEN,
                fontSize: 12, cursor: actionLoading ? 'not-allowed' : 'pointer',
                opacity: actionLoading ? 0.6 : 1, fontWeight: 600,
              }}
            >
              {actionLoading ? '...' : j.status === 'active' ? '暂停' : '激活'}
            </button>
          )}
        </div>
      </div>

      {/* 第二行：节点数 + 最近触发时间 */}
      <div style={{ marginTop: 8, display: 'flex', gap: 16, fontSize: 11, color: TEXT_4 }}>
        <span>📍 {j.steps.length} 步节点</span>
        <span>⚡ 触发事件: <span style={{ color: TEXT_3 }}>{j.trigger_event}</span></span>
        <span>🕐 最近触发: <span style={{ color: TEXT_3 }}>{relativeTime(j.last_triggered_at)}</span></span>
        <span>📅 创建: <span style={{ color: TEXT_3 }}>{j.created_at.slice(0, 10)}</span></span>
      </div>
    </div>
  );
}

// ---- 侧边抽屉内容 ----

function JourneyDrawer({
  journey: j,
  enrollments,
  actionLoading,
  onClose,
  onToggleStatus,
}: {
  journey: JourneyDefinition;
  enrollments: JourneyEnrollment[];
  actionLoading: boolean;
  onClose: () => void;
  onToggleStatus: () => void;
}) {
  const sc = statusColor(j.status);
  const sl = statusLabel(j.status);

  return (
    <>
      {/* 抽屉顶部 */}
      <div style={{
        padding: '16px 20px', borderBottom: `1px solid ${BG_2}`,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{j.name}</span>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 10,
              background: sc + '22', color: sc, fontWeight: 600,
            }}>{sl}</span>
          </div>
          <div style={{ fontSize: 11, color: TEXT_4 }}>
            创建于 {j.created_at.slice(0, 10)} · 触发事件: {j.trigger_event}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            width: 28, height: 28, borderRadius: '50%', border: 'none',
            background: BG_2, color: TEXT_3, fontSize: 16, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
        >×</button>
      </div>

      {/* 滚动内容区 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>

        {/* 统计数字 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 20 }}>
          {[
            { label: '累计参与', value: j.stats.total_enrollments, color: TEXT_1 },
            { label: '当前活跃', value: j.stats.active_enrollments, color: BLUE },
            { label: '今日触发', value: j.stats.triggers_today, color: BRAND },
            { label: '今日转化', value: j.stats.completions_today, color: GREEN },
          ].map(item => (
            <div key={item.label} style={{
              background: BG_2, borderRadius: 8, padding: '10px 12px',
            }}>
              <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: item.color }}>{item.value}</div>
            </div>
          ))}
        </div>

        {/* 节点流程图（纵向列表）*/}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: TEXT_2, marginBottom: 10 }}>
            节点执行流程
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {j.steps.map((step, idx) => (
              <div key={step.step_id}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  {/* 步骤图标 + 连接线 */}
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                    <div style={{
                      width: 28, height: 28, borderRadius: '50%',
                      background: step.execution_count && step.execution_count > 0 ? BG_2 : 'transparent',
                      border: `1px solid ${step.execution_count && step.execution_count > 0 ? BRAND : BG_2}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 13,
                    }}>
                      {stepIcon(step.type)}
                    </div>
                    {idx < j.steps.length - 1 && (
                      <div style={{ width: 1, height: 20, background: BG_2, margin: '2px 0' }} />
                    )}
                  </div>
                  {/* 步骤信息 */}
                  <div style={{ paddingTop: 4, flex: 1 }}>
                    <div style={{ fontSize: 12, color: TEXT_1, fontWeight: 500 }}>
                      {step.name}
                    </div>
                    <div style={{ fontSize: 10, color: TEXT_4, marginTop: 1 }}>
                      {step.execution_count != null && (
                        <span style={{ marginRight: 8 }}>
                          已完成 <span style={{ color: TEXT_3 }}>{step.execution_count}</span> 次
                        </span>
                      )}
                      {step.active_count != null && step.active_count > 0 && (
                        <span style={{ color: BLUE }}>
                          进行中 {step.active_count} 人
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 最近参与记录 */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: TEXT_2, marginBottom: 10 }}>
            最近10条参与记录
          </div>
          {enrollments.length === 0 ? (
            <div style={{ fontSize: 12, color: TEXT_4, textAlign: 'center', padding: 16 }}>
              暂无参与记录
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {enrollments.slice(0, 10).map(e => (
                <div key={e.enrollment_id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  background: BG_2, borderRadius: 6, padding: '8px 10px', fontSize: 11,
                }}>
                  <span style={{ color: TEXT_2, fontWeight: 600, width: 70 }}>
                    {e.customer_id}
                  </span>
                  <span style={{ color: TEXT_4, flex: 1, marginLeft: 8 }}>
                    {e.current_step}
                  </span>
                  <span style={{
                    color: e.status === 'completed' ? GREEN : BLUE,
                    fontSize: 10, marginLeft: 8,
                  }}>
                    {e.status === 'completed' ? '已完成' : '进行中'}
                  </span>
                  <span style={{ color: TEXT_4, marginLeft: 8, flexShrink: 0 }}>
                    {relativeTime(e.entered_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 抽屉底部操作按钮 */}
      <div style={{
        padding: '14px 20px', borderTop: `1px solid ${BG_2}`, flexShrink: 0,
        display: 'flex', gap: 10,
      }}>
        {j.status === 'active' && (
          <button
            onClick={onToggleStatus}
            disabled={actionLoading}
            style={{
              flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
              background: YELLOW + '22', color: YELLOW,
              fontSize: 13, fontWeight: 700, cursor: actionLoading ? 'not-allowed' : 'pointer',
              opacity: actionLoading ? 0.6 : 1,
            }}
          >
            {actionLoading ? '处理中...' : '⏸ 暂停旅程'}
          </button>
        )}
        {j.status === 'paused' && (
          <button
            onClick={onToggleStatus}
            disabled={actionLoading}
            style={{
              flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
              background: GREEN + '22', color: GREEN,
              fontSize: 13, fontWeight: 700, cursor: actionLoading ? 'not-allowed' : 'pointer',
              opacity: actionLoading ? 0.6 : 1,
            }}
          >
            {actionLoading ? '处理中...' : '▶ 激活旅程'}
          </button>
        )}
        {j.status === 'draft' && (
          <button
            onClick={onToggleStatus}
            disabled={actionLoading}
            style={{
              flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
              background: BRAND + '22', color: BRAND,
              fontSize: 13, fontWeight: 700, cursor: actionLoading ? 'not-allowed' : 'pointer',
              opacity: actionLoading ? 0.6 : 1,
            }}
          >
            {actionLoading ? '处理中...' : '🚀 发布并激活'}
          </button>
        )}
        {j.status === 'ended' && (
          <div style={{ flex: 1, textAlign: 'center', fontSize: 12, color: TEXT_4, padding: '10px 0' }}>
            旅程已结束，无法操作
          </div>
        )}
        <button
          onClick={onClose}
          style={{
            padding: '10px 20px', borderRadius: 8, border: `1px solid ${BG_2}`,
            background: BG_2, color: TEXT_3, fontSize: 13, cursor: 'pointer',
          }}
        >关闭</button>
      </div>
    </>
  );
}

// ---- 模板卡片 ----

function TemplateCard({
  template: t,
  importing,
  onImport,
}: {
  template: { id: string; icon: string; name: string; description: string };
  importing: boolean;
  onImport: () => void;
}) {
  return (
    <div style={{
      background: BG_2, borderRadius: 10, padding: '14px 14px 12px',
      border: `1px solid ${BG_2}`, display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ fontSize: 24 }}>{t.icon}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: TEXT_1 }}>{t.name}</div>
      <div style={{ fontSize: 11, color: TEXT_4, flex: 1, lineHeight: 1.5 }}>{t.description}</div>
      <button
        onClick={onImport}
        disabled={importing}
        style={{
          padding: '6px 0', borderRadius: 6, border: 'none',
          background: importing ? BG_1 : BRAND + '22',
          color: importing ? TEXT_4 : BRAND,
          fontSize: 12, fontWeight: 700, cursor: importing ? 'not-allowed' : 'pointer',
          transition: 'all .15s',
        }}
      >
        {importing ? '导入中...' : '+ 导入'}
      </button>
    </div>
  );
}
