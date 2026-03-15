/**
 * 集成中心 — /platform/integration-hub
 *
 * 单页仪表盘，展示所有外部集成（POS / 外卖 / 财务 / 合规 / 评论 / 采购 / IM）
 * 的健康状态、同步统计和错误日志。30 秒自动刷新。
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient } from '../../services/api';
import styles from './IntegrationHubPage.module.css';

// ── 类型定义 ─────────────────────────────────────────────────────────────────

interface IntegrationStatus {
  id: string;
  integration_key: string;
  display_name: string;
  category: string;
  status: 'healthy' | 'degraded' | 'error' | 'disconnected' | 'not_configured';
  last_sync_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  sync_count_today: number;
  error_count_today: number;
  config_complete: boolean;
  metadata: Record<string, unknown> | null;
}

interface DashboardSummary {
  total: number;
  healthy: number;
  degraded: number;
  error: number;
  disconnected: number;
  not_configured: number;
  total_syncs_today: number;
  total_errors_today: number;
  recent_errors: RecentError[];
}

interface RecentError {
  integration_key: string;
  display_name: string;
  error_message: string | null;
  error_at: string | null;
}

interface CategoryGroup {
  category: string;
  label: string;
  total: number;
  healthy: number;
  degraded: number;
  error: number;
  disconnected: number;
  not_configured: number;
  integrations: IntegrationStatus[];
}

// ── 常量 ─────────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL = 30_000; // 30 秒

const CATEGORY_ICONS: Record<string, string> = {
  pos: '\u{1F4B3}',         // 💳
  channel: '\u{1F6F5}',     // 🛵
  financial: '\u{1F4CA}',   // 📊
  compliance: '\u{1F6E1}',  // 🛡
  review: '\u{2B50}',       // ⭐
  procurement: '\u{1F4E6}', // 📦
  im: '\u{1F4AC}',          // 💬
};

const STATUS_LABELS: Record<string, string> = {
  healthy: '正常',
  degraded: '降级',
  error: '异常',
  disconnected: '已断开',
  not_configured: '未配置',
};

// ── 工具函数 ─────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null): string {
  if (!iso) return '从未同步';
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return '刚刚';
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}秒前`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}

function statusDotClass(status: string): string {
  switch (status) {
    case 'healthy':
      return styles.statusHealthy;
    case 'degraded':
      return styles.statusDegraded;
    case 'error':
      return styles.statusError;
    case 'disconnected':
      return styles.statusDisconnected;
    default:
      return styles.statusNotConfigured;
  }
}

// ── 组件 ─────────────────────────────────────────────────────────────────────

const IntegrationHubPage: React.FC = () => {
  const [categories, setCategories] = useState<CategoryGroup[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [collapsedCats, setCollapsedCats] = useState<Set<string>>(new Set());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 数据加载 ───────────────────────────────────────────────────────────────

  const fetchData = useCallback(async () => {
    try {
      const [summaryData, categoryData] = await Promise.all([
        apiClient.get<DashboardSummary>('/api/v1/integration-hub/summary'),
        apiClient.get<CategoryGroup[]>('/api/v1/integration-hub/categories'),
      ]);
      setSummary(summaryData);
      setCategories(categoryData);
    } catch (err) {
      console.error('集成中心数据加载失败', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    timerRef.current = setInterval(fetchData, REFRESH_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchData]);

  // ── 健康检查 ───────────────────────────────────────────────────────────────

  const handleHealthCheck = async () => {
    setChecking(true);
    try {
      await apiClient.post('/api/v1/integration-hub/health-check');
      await fetchData();
    } catch (err) {
      console.error('健康检查失败', err);
    } finally {
      setChecking(false);
    }
  };

  // ── 分类折叠 ───────────────────────────────────────────────────────────────

  const toggleCategory = (cat: string) => {
    setCollapsedCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  };

  // ── 渲染 ───────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.loading}>加载集成中心数据...</div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      {/* 页头 */}
      <div className={styles.pageHeader}>
        <div className={styles.headerLeft}>
          <h1 className={styles.pageTitle}>集成中心</h1>
          <p className={styles.pageSubtitle}>
            监控所有外部系统集成的健康状态和同步情况 &middot; 每 30 秒自动刷新
          </p>
        </div>
        <div className={styles.headerActions}>
          <button
            onClick={handleHealthCheck}
            disabled={checking}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              border: '1px solid var(--border, #e5e7eb)',
              background: checking ? 'var(--surface-elevated, #f3f4f6)' : 'var(--surface, #fff)',
              cursor: checking ? 'not-allowed' : 'pointer',
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--text-primary, #111827)',
              fontFamily: 'inherit',
            }}
          >
            {checking ? '检查中...' : '健康检查'}
          </button>
        </div>
      </div>

      {/* 概览卡片 */}
      {summary && (
        <div className={styles.statsRow}>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>总集成数</span>
            <span className={styles.statValue}>{summary.total}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>正常运行</span>
            <span className={styles.statValueGreen}>{summary.healthy}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>降级/告警</span>
            <span className={styles.statValueYellow}>
              {summary.degraded + summary.disconnected}
            </span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>异常</span>
            <span className={styles.statValueRed}>{summary.error}</span>
          </div>
        </div>
      )}

      {/* 分类区块 */}
      {categories.map((cat) => {
        const collapsed = collapsedCats.has(cat.category);
        return (
          <div key={cat.category} className={styles.categorySection}>
            <div
              className={styles.categoryHeader}
              onClick={() => toggleCategory(cat.category)}
            >
              <span className={styles.categoryTitle}>
                <span>{CATEGORY_ICONS[cat.category] || '\u{1F50C}'}</span>
                {cat.label}
                <span className={styles.categoryCount}>{cat.total}</span>
              </span>
              <span
                className={`${styles.collapseIcon} ${
                  !collapsed ? styles.collapseIconOpen : ''
                }`}
              >
                &#x25BC;
              </span>
            </div>

            {!collapsed && (
              <div className={styles.cardGrid}>
                {cat.integrations.map((item) => (
                  <div key={item.integration_key} className={styles.integrationCard}>
                    {/* 顶部：图标 + 名称 + 状态点 */}
                    <div className={styles.cardTop}>
                      <div className={styles.cardIcon}>
                        {CATEGORY_ICONS[cat.category] || '\u{1F50C}'}
                      </div>
                      <div className={styles.cardNameRow}>
                        <span className={styles.cardName}>{item.display_name}</span>
                        <span className={styles.cardKey}>{item.integration_key}</span>
                      </div>
                      <div
                        className={`${styles.statusDot} ${statusDotClass(item.status)}`}
                        title={STATUS_LABELS[item.status] || item.status}
                      />
                    </div>

                    {/* 指标行 */}
                    <div className={styles.cardMetrics}>
                      <span className={styles.metric}>
                        <span className={styles.metricIcon}>{'\u{1F504}'}</span>
                        {relativeTime(item.last_sync_at)}
                      </span>

                      {item.sync_count_today > 0 && (
                        <span className={styles.syncBadge}>
                          {item.sync_count_today} 次同步
                        </span>
                      )}

                      {item.error_count_today > 0 && (
                        <span className={styles.errorBadge}>
                          {item.error_count_today} 错误
                        </span>
                      )}

                      {item.status === 'not_configured' && (
                        <span
                          style={{
                            fontSize: 11,
                            color: 'var(--text-tertiary, #9ca3af)',
                            fontStyle: 'italic',
                          }}
                        >
                          未配置
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* 错误日志面板 */}
      {summary && (
        <div className={styles.errorPanel}>
          <div className={styles.errorPanelHeader}>
            <span className={styles.errorPanelTitle}>
              {'\u26A0\uFE0F'} 近期错误日志
            </span>
            {summary.total_errors_today > 0 && (
              <span className={styles.errorBadge}>
                今日 {summary.total_errors_today} 个错误
              </span>
            )}
          </div>

          {summary.recent_errors.length === 0 ? (
            <div className={styles.emptyErrors}>
              暂无错误记录，一切正常运行中
            </div>
          ) : (
            <ul className={styles.errorList}>
              {summary.recent_errors.map((err, idx) => (
                <li key={`${err.integration_key}-${idx}`} className={styles.errorItem}>
                  <span className={styles.errorIntegration}>
                    {err.display_name}
                  </span>
                  <span className={styles.errorMessage}>
                    {err.error_message || '未知错误'}
                  </span>
                  <span className={styles.errorTime}>
                    {relativeTime(err.error_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};

export default IntegrationHubPage;
