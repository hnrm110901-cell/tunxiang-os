/**
 * PlatformAuditLogPage — /platform/audit-log
 *
 * 审计日志管理：记录所有用户操作行为，支持按操作类型/资源/状态/时间筛选
 * 后端 API:
 *   GET  /api/v1/audit/logs                 — 分页列表
 *   GET  /api/v1/audit/logs/system/stats    — 统计摘要
 *   GET  /api/v1/audit/logs/actions         — 操作类型枚举
 *   GET  /api/v1/audit/logs/resource-types  — 资源类型枚举
 *   DELETE /api/v1/audit/logs/cleanup       — 清理旧日志
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ZCard, ZBadge, ZButton, ZEmpty, ZAlert, ZSkeleton, ZInput, ZSelect,
} from '../../design-system/components';
import type { ZTableColumn } from '../../design-system/components';
import ZTable from '../../design-system/components/ZTable';
import type { SelectOption } from '../../design-system/components/ZSelect';
import { apiClient } from '../../services/api';
import styles from './PlatformAuditLogPage.module.css';

// ── 类型 ────────────────────────────────────────────────────────────────────

interface AuditLog {
  id: string;
  created_at: string;
  user_id?: string;
  username?: string;
  user_role?: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  description?: string;
  ip_address?: string;
  status: 'success' | 'failure' | 'warning';
  duration_ms?: number;
}

interface SystemStats {
  total_logs?: number;
  success_count?: number;
  failure_count?: number;
  warning_count?: number;
  unique_users?: number;
  most_common_action?: string;
  most_active_user?: string;
}

// ── 工具函数 ──────────────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch { return iso; }
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}
function sevenDaysAgo() {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

// ── 状态胶囊 ─────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, 'success' | 'error' | 'warning'> = {
  success: 'success',
  failure: 'error',
  warning: 'warning',
};
const STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failure: '失败',
  warning: '警告',
};

// ── 操作类型颜色 ─────────────────────────────────────────────────────────

const ACTION_BADGE: Record<string, 'info' | 'success' | 'warning' | 'error' | 'default'> = {
  login: 'info',
  logout: 'default',
  create: 'success',
  update: 'info',
  delete: 'error',
  read: 'default',
  export: 'warning',
};

function actionBadge(action: string): 'info' | 'success' | 'warning' | 'error' | 'default' {
  const key = action.toLowerCase().split('_')[0];
  return ACTION_BADGE[key] ?? 'default';
}

// ── 主组件 ───────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

export default function PlatformAuditLogPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);            // skip = page * PAGE_SIZE
  const [loadingLogs, setLoadingLogs] = useState(true);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [actionOptions, setActionOptions] = useState<SelectOption[]>([]);
  const [resourceOptions, setResourceOptions] = useState<SelectOption[]>([]);
  const [cleaning, setCleaning] = useState(false);
  const [cleanOk, setCleanOk] = useState<string | null>(null);
  const [cleanErr, setCleanErr] = useState<string | null>(null);

  // 过滤状态
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState<string | null>(null);
  const [resourceFilter, setResourceFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [startDate, setStartDate] = useState(sevenDaysAgo());
  const [endDate, setEndDate] = useState(todayStr());

  // ── 加载统计 ──
  useEffect(() => {
    (async () => {
      try {
        const res = await apiClient.get('/api/v1/audit/logs/system/stats', { params: { days: 7 } });
        setStats(res);
      } catch { /* silent */ }
    })();
  }, []);

  // ── 加载枚举 ──
  useEffect(() => {
    (async () => {
      try {
        const [actRes, resRes] = await Promise.allSettled([
          apiClient.get('/api/v1/audit/logs/actions'),
          apiClient.get('/api/v1/audit/logs/resource-types'),
        ]);
        if (actRes.status === 'fulfilled') {
          const actions: string[] = actRes.value?.actions ?? [];
          setActionOptions([
            { value: '', label: '全部操作' },
            ...actions.map((a: string) => ({ value: a, label: a })),
          ]);
        }
        if (resRes.status === 'fulfilled') {
          const types: string[] = resRes.value?.resource_types ?? [];
          setResourceOptions([
            { value: '', label: '全部资源' },
            ...types.map((t: string) => ({ value: t, label: t })),
          ]);
        }
      } catch { /* silent */ }
    })();
  }, []);

  // ── 加载日志 ──
  const loadLogs = useCallback(async (pg = 0) => {
    setLoadingLogs(true);
    try {
      const params: Record<string, unknown> = {
        skip: pg * PAGE_SIZE,
        limit: PAGE_SIZE,
      };
      if (search)         params.search        = search;
      if (actionFilter)   params.action        = actionFilter;
      if (resourceFilter) params.resource_type = resourceFilter;
      if (statusFilter)   params.status        = statusFilter;
      if (startDate)      params.start_date    = startDate;
      if (endDate)        params.end_date      = endDate;

      const res = await apiClient.get('/api/v1/audit/logs', { params });
      setLogs(res?.logs ?? []);
      setTotal(res?.total ?? 0);
      setPage(pg);
    } catch {
      setLogs([]);
    } finally {
      setLoadingLogs(false);
    }
  }, [search, actionFilter, resourceFilter, statusFilter, startDate, endDate]);

  useEffect(() => { loadLogs(0); }, [loadLogs]);

  // ── 清理旧日志 ──
  const handleCleanup = async () => {
    setCleaning(true);
    setCleanOk(null);
    setCleanErr(null);
    try {
      const res = await apiClient.delete('/api/v1/audit/logs/cleanup', { params: { days: 90 } });
      setCleanOk(`已清理 ${res?.deleted_count ?? 0} 条 90 天前的日志`);
      loadLogs(0);
    } catch (e: any) {
      setCleanErr(e?.message ?? '清理失败');
    } finally {
      setCleaning(false);
    }
  };

  // ── 重置筛选 ──
  const handleReset = () => {
    setSearch('');
    setActionFilter(null);
    setResourceFilter(null);
    setStatusFilter(null);
    setStartDate(sevenDaysAgo());
    setEndDate(todayStr());
  };

  // ── 表格列定义 ──
  const columns: ZTableColumn<AuditLog>[] = [
    {
      key: 'created_at',
      title: '时间',
      width: 150,
      render: (_, row) => (
        <span className={styles.timeCell}>{fmtTime(row.created_at)}</span>
      ),
    },
    {
      key: 'user',
      title: '用户 / 角色',
      width: 130,
      render: (_, row) => (
        <div className={styles.userCell}>
          <span className={styles.userName}>{row.username || row.user_id || '—'}</span>
          {row.user_role && (
            <ZBadge type="info" text={row.user_role} />
          )}
        </div>
      ),
    },
    {
      key: 'action',
      title: '操作',
      width: 150,
      render: (_, row) => (
        <ZBadge type={actionBadge(row.action)} text={row.action} />
      ),
    },
    {
      key: 'resource_type',
      title: '资源类型',
      width: 130,
      render: (_, row) => (
        <span className={styles.resourceTag}>{row.resource_type}</span>
      ),
    },
    {
      key: 'description',
      title: '描述',
      render: (_, row) => (
        <span className={styles.descCell}>{row.description || '—'}</span>
      ),
    },
    {
      key: 'ip_address',
      title: 'IP 地址',
      width: 130,
      render: (_, row) => (
        <span className={styles.ipCell}>{row.ip_address || '—'}</span>
      ),
    },
    {
      key: 'status',
      title: '状态',
      width: 80,
      align: 'center',
      render: (_, row) => (
        <ZBadge
          type={STATUS_BADGE[row.status] ?? 'default'}
          text={STATUS_LABEL[row.status] ?? row.status}
        />
      ),
    },
  ];

  // ── 统计值 ──
  const successRate = stats && stats.total_logs && stats.total_logs > 0
    ? ((stats.success_count ?? 0) / stats.total_logs * 100).toFixed(1)
    : null;

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const STATUS_OPTS: SelectOption[] = [
    { value: '', label: '全部状态' },
    { value: 'success', label: '✅ 成功' },
    { value: 'failure', label: '❌ 失败' },
    { value: 'warning', label: '⚠️ 警告' },
  ];

  return (
    <div className={styles.page}>
      {/* 页头 */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>审计日志</h1>
          <p className={styles.pageSubtitle}>
            追踪所有用户操作行为，满足合规审查与安全溯源需求
          </p>
        </div>
        <div className={styles.headerActions}>
          <ZButton
            size="sm"
            variant="ghost"
            onClick={() => loadLogs(page)}
          >
            刷新
          </ZButton>
          <ZButton
            size="sm"
            variant="secondary"
            onClick={handleCleanup}
          >
            {cleaning ? '清理中…' : '清理 90 天前日志'}
          </ZButton>
        </div>
      </div>

      {/* 清理结果提示 */}
      {cleanOk && (
        <div className={styles.alertRow}>
          <ZAlert variant="success" title={cleanOk} />
        </div>
      )}
      {cleanErr && (
        <div className={styles.alertRow}>
          <ZAlert variant="error" title={cleanErr} />
        </div>
      )}

      {/* 统计行 */}
      <div className={styles.statsRow}>
        <ZCard className={styles.statCard}>
          <div className={styles.statNum}>{stats?.total_logs?.toLocaleString() ?? '—'}</div>
          <div className={styles.statLabel}>7日日志总量</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={`${styles.statNum} ${styles.statNumGreen}`}>
            {successRate ? `${successRate}%` : '—'}
          </div>
          <div className={styles.statLabel}>操作成功率</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={`${styles.statNum} ${styles.statNumRed}`}>
            {stats?.failure_count?.toLocaleString() ?? '—'}
          </div>
          <div className={styles.statLabel}>失败操作</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={styles.statNum}>{stats?.unique_users ?? '—'}</div>
          <div className={styles.statLabel}>活跃用户数</div>
        </ZCard>
      </div>

      {/* 过滤栏 */}
      <ZCard className={styles.filterCard}>
        <div className={styles.filterRow}>
          <ZInput
            placeholder="搜索用户名 / 描述 / IP"
            value={search}
            onChange={setSearch}
            style={{ flex: 1, minWidth: 180 }}
          />
          <ZSelect
            options={actionOptions.length ? actionOptions : [{ value: '', label: '全部操作' }]}
            value={actionFilter ?? ''}
            onChange={(v) => setActionFilter(v || null)}
            placeholder="全部操作"
            style={{ minWidth: 140 }}
          />
          <ZSelect
            options={resourceOptions.length ? resourceOptions : [{ value: '', label: '全部资源' }]}
            value={resourceFilter ?? ''}
            onChange={(v) => setResourceFilter(v || null)}
            placeholder="全部资源"
            style={{ minWidth: 140 }}
          />
          <ZSelect
            options={STATUS_OPTS}
            value={statusFilter ?? ''}
            onChange={(v) => setStatusFilter(v || null)}
            placeholder="全部状态"
            style={{ minWidth: 120 }}
          />
          <div className={styles.dateRange}>
            <input
              type="date"
              className={styles.dateInput}
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
            />
            <span className={styles.dateSep}>—</span>
            <input
              type="date"
              className={styles.dateInput}
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
            />
          </div>
          <div className={styles.filterBtns}>
            <ZButton size="sm" variant="primary" onClick={() => loadLogs(0)}>
              查询
            </ZButton>
            <ZButton size="sm" variant="ghost" onClick={handleReset}>
              重置
            </ZButton>
          </div>
        </div>
      </ZCard>

      {/* 日志总数 */}
      <div className={styles.tableHeader}>
        <span className={styles.totalLabel}>
          共 <strong>{total.toLocaleString()}</strong> 条记录
        </span>
        {total > 0 && (
          <div className={styles.pagination}>
            <ZButton
              size="sm"
              variant="ghost"
              onClick={() => loadLogs(page - 1)}
            >
              ‹ 上一页
            </ZButton>
            <span className={styles.pageInfo}>
              第 {page + 1} / {Math.max(1, totalPages)} 页
            </span>
            <ZButton
              size="sm"
              variant="ghost"
              onClick={() => loadLogs(page + 1)}
            >
              下一页 ›
            </ZButton>
          </div>
        )}
      </div>

      {/* 日志表格 */}
      {loadingLogs ? (
        <ZCard>
          <ZSkeleton rows={8} />
        </ZCard>
      ) : logs.length === 0 ? (
        <ZCard>
          <ZEmpty text="暂无审计日志，调整筛选条件后重试" />
        </ZCard>
      ) : (
        <ZCard className={styles.tableCard}>
          <ZTable<AuditLog>
            columns={columns}
            data={logs}
            rowKey="id"
          />
        </ZCard>
      )}
    </div>
  );
}
