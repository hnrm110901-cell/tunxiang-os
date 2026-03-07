/**
 * 店长移动端首页
 * 路由：/sm  (index) 和 /sm/home
 *
 * 数据来源：GET /api/v1/bff/sm/{store_id}
 * 布局：
 *   - 时间问候头部 + 刷新
 *   - 告警 banner（有未读告警时显示）
 *   - 4格 KPI 宫格（今日营收 / 成本率 / 待审批 / 排队桌）
 *   - 门店健康指数卡（HealthRing + 最弱维度 + 接待量）
 *   - 今日行动清单（UrgencyList + 跳转决策页）
 *   - 快捷操作栏（4个入口）
 */
import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZEmpty, HealthRing, UrgencyList,
} from '../../design-system/components';
import apiClient from '../../services/api';
import styles from './Home.module.css';

const STORE_ID = localStorage.getItem('store_id') || 'S001';

// ── Types ──────────────────────────────────────────────────────────────────────

interface HealthScore {
  score:             number;
  level:             string;
  weakest_dimension?: string;
}

interface QueueStatus {
  waiting_count: number;
  avg_wait_min:  number;
  served_today?: number;
}

interface Decision {
  rank:                 number;
  title:                string;
  action:               string;
  expected_saving_yuan: number;
  confidence_pct:       number;
  urgency_hours:        number;
}

interface FoodCostSummary {
  actual_cost_pct: number;
  target_pct:      number;
  variance_pct:    number;
  variance_status: 'ok' | 'warning' | 'critical';
}

interface TodayRevenue {
  revenue_yuan: number;
}

interface BffSmData {
  store_id:               string;
  as_of:                  string;
  health_score:           HealthScore | null;
  top3_decisions:         Decision[];
  queue_status:           QueueStatus | null;
  pending_approvals_count: number;
  today_revenue_yuan:     TodayRevenue | null;
  food_cost_summary:      FoodCostSummary | null;
  unread_alerts_count:    number;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function greeting(): string {
  const h = new Date().getHours();
  if (h < 6)  return '凌晨好';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

function formatRevenue(yuan: number): string {
  if (yuan >= 10000) return `${(yuan / 10000).toFixed(1)}万`;
  return `${Math.round(yuan)}`;
}

function revenuUnit(yuan: number): string {
  return yuan >= 10000 ? '元' : '元';
}

const HEALTH_LEVEL_MAP: Record<string, { label: string; type: 'success' | 'info' | 'warning' | 'critical' }> = {
  excellent: { label: '优秀', type: 'success' },
  good:      { label: '良好', type: 'info' },
  warning:   { label: '需关注', type: 'warning' },
  critical:  { label: '危险', type: 'critical' },
};

// ── Quick action button ────────────────────────────────────────────────────────

interface QuickAction {
  icon:  string;
  label: string;
  to:    string;
  badge?: number;
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function SmHome() {
  const navigate = useNavigate();
  const [data,    setData]    = useState<BffSmData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.get(
        `/api/v1/bff/sm/${STORE_ID}${refresh ? '?refresh=true' : ''}`
      );
      setData(resp.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || '数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Derived values ──────────────────────────────────────────────────────────

  const health   = data?.health_score;
  const queue    = data?.queue_status;
  const fc       = data?.food_cost_summary;
  const revenue  = data?.today_revenue_yuan;
  const pending  = data?.pending_approvals_count ?? 0;
  const alerts   = data?.unread_alerts_count ?? 0;

  const decisions = data?.top3_decisions ?? [];
  const urgencyItems = decisions.map(d => ({
    id:           String(d.rank),
    title:        d.title,
    description:  d.action,
    urgency:      (d.urgency_hours <= 4 ? 'critical' : d.urgency_hours <= 12 ? 'warning' : 'info') as 'critical' | 'warning' | 'info',
    amount_yuan:  d.expected_saving_yuan,
    action_label: '去处理',
    onAction:     () => navigate('/sm/decisions'),
  }));

  const quickActions: QuickAction[] = [
    { icon: '📋', label: '审批决策', to: '/sm/decisions', badge: pending || undefined },
    { icon: '📦', label: '库存查询', to: '/inventory' },
    { icon: '📊', label: '损耗报告', to: '/waste-reasoning' },
    { icon: '🔔', label: '告警管理', to: '/sm/alerts',    badge: alerts || undefined },
  ];

  // ── Render ──────────────────────────────────────────────────────────────────

  const today = new Date().toLocaleDateString('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'short',
  });

  return (
    <div className={styles.page}>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className={styles.header}>
        <div>
          <div className={styles.greeting}>{greeting()}，店长</div>
          <div className={styles.date}>{today} · {STORE_ID}</div>
        </div>
        <ZButton variant="ghost" size="sm" onClick={() => load(true)}>
          ↺ 刷新
        </ZButton>
      </div>

      {loading && !data ? (
        <div className={styles.body}>
          <ZSkeleton block rows={3} style={{ gap: 16 }} />
        </div>
      ) : error ? (
        <div className={styles.body}>
          <ZEmpty
            icon="⚠️"
            title="加载失败"
            description={error}
            action={<ZButton size="sm" onClick={() => load()}>重试</ZButton>}
          />
        </div>
      ) : (
        <div className={styles.body}>

          {/* ── 告警 banner ──────────────────────────────────────────────── */}
          {alerts > 0 && (
            <button className={styles.alertBanner} onClick={() => navigate('/sm/alerts')}>
              <span className={styles.alertIcon}>‼</span>
              <span className={styles.alertText}>{alerts} 条运营告警待处理，点击查看</span>
              <span className={styles.alertArrow}>›</span>
            </button>
          )}

          {/* ── KPI 宫格 ─────────────────────────────────────────────────── */}
          <div className={styles.kpiGrid}>
            <div className={styles.kpiCell}>
              <ZKpi
                label="今日营收"
                value={revenue ? formatRevenue(revenue.revenue_yuan) : '—'}
                unit={revenue ? revenuUnit(revenue.revenue_yuan) : ''}
                size="md"
              />
            </div>
            <div className={styles.kpiCell}>
              <ZKpi
                label="食材成本率"
                value={fc ? `${fc.actual_cost_pct}` : '—'}
                unit="%"
                size="md"
                change={fc ? fc.variance_pct : undefined}
                changeLabel="较目标"
              />
            </div>
            <div className={`${styles.kpiCell} ${pending > 0 ? styles.kpiCellAlert : ''}`}>
              <ZKpi
                label="待审批"
                value={pending}
                unit="项"
                size="md"
              />
            </div>
            <div className={styles.kpiCell}>
              <ZKpi
                label="排队等候"
                value={queue?.waiting_count ?? 0}
                unit="组"
                size="md"
              />
            </div>
          </div>

          {/* ── 门店健康指数 ──────────────────────────────────────────────── */}
          <ZCard
            title="门店健康指数"
            extra={
              health
                ? <ZBadge
                    type={HEALTH_LEVEL_MAP[health.level]?.type ?? 'info'}
                    text={HEALTH_LEVEL_MAP[health.level]?.label ?? health.level}
                  />
                : null
            }
          >
            <div className={styles.healthRow}>
              <HealthRing score={health?.score ?? 0} size={96} label="综合评分" />
              <div className={styles.healthMeta}>
                {health?.weakest_dimension && (
                  <div className={styles.weakDim}>
                    <span className={styles.weakLabel}>最弱维度</span>
                    <span className={styles.weakValue}>{health.weakest_dimension}</span>
                  </div>
                )}
                <div className={styles.healthStats}>
                  <div className={styles.statItem}>
                    <span className={styles.statValue}>{queue?.served_today ?? '—'}</span>
                    <span className={styles.statLabel}>今日接待</span>
                  </div>
                  <div className={styles.statDivider} />
                  <div className={styles.statItem}>
                    <span className={styles.statValue}>{queue?.avg_wait_min ?? '—'}</span>
                    <span className={styles.statLabel}>均等(分)</span>
                  </div>
                  <div className={styles.statDivider} />
                  <div className={styles.statItem}>
                    <span className={styles.statValue}>{queue?.waiting_count ?? 0}</span>
                    <span className={styles.statLabel}>候位中</span>
                  </div>
                </div>
              </div>
            </div>
          </ZCard>

          {/* ── 今日行动清单 ──────────────────────────────────────────────── */}
          <ZCard
            title="今日行动清单"
            subtitle={urgencyItems.length > 0 ? `${urgencyItems.length} 项待处理` : '暂无待处理'}
            extra={
              urgencyItems.length > 0
                ? <ZButton variant="ghost" size="sm" onClick={() => navigate('/sm/decisions')}>
                    全部 ›
                  </ZButton>
                : null
            }
          >
            <UrgencyList items={urgencyItems} maxItems={3} />
          </ZCard>

          {/* ── 快捷操作 ──────────────────────────────────────────────────── */}
          <ZCard title="快捷操作">
            <div className={styles.quickGrid}>
              {quickActions.map((a) => (
                <button
                  key={a.to}
                  className={styles.quickBtn}
                  onClick={() => navigate(a.to)}
                >
                  <span className={styles.quickIcon}>{a.icon}</span>
                  <span className={styles.quickLabel}>{a.label}</span>
                  {a.badge != null && a.badge > 0 && (
                    <span className={styles.quickBadge}>{a.badge}</span>
                  )}
                </button>
              ))}
            </div>
          </ZCard>

        </div>
      )}
    </div>
  );
}
