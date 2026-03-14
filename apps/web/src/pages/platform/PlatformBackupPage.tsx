/**
 * PlatformBackupPage — /platform/backup
 *
 * 备份管理：查看/创建/下载/删除数据库备份任务
 * 后端 API:
 *   GET    /api/v1/backups/            — 备份列表
 *   POST   /api/v1/backups/            — 创建备份（full / incremental）
 *   GET    /api/v1/backups/{id}        — 单条查询（用于进度轮询）
 *   DELETE /api/v1/backups/{id}        — 删除备份
 *   (browser) /api/v1/backups/{id}/download — 文件下载链接
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ZCard, ZBadge, ZButton, ZEmpty, ZAlert, ZSkeleton, ZModal,
} from '../../design-system/components';
import type { ZTableColumn } from '../../design-system/components';
import ZTable from '../../design-system/components/ZTable';
import { apiClient } from '../../services/api';
import styles from './PlatformBackupPage.module.css';

// ── 类型 ─────────────────────────────────────────────────────────────────────

interface BackupJob {
  job_id: string;
  backup_type: 'full' | 'incremental';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress?: number;
  size?: number;      // bytes
  checksum?: string;
  created_at?: string;
  completed_at?: string;
}

// ── 工具函数 ─────────────────────────────────────────────────────────────────

function fmtBytes(bytes?: number): string {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function fmtTime(iso?: string): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

const STATUS_TYPE: Record<string, 'success' | 'warning' | 'error' | 'default' | 'info'> = {
  pending:   'default',
  running:   'warning',
  completed: 'success',
  failed:    'error',
};
const STATUS_LABEL: Record<string, string> = {
  pending:   '等待中',
  running:   '进行中',
  completed: '已完成',
  failed:    '失败',
};
const TYPE_LABEL: Record<string, string> = {
  full:        '全量',
  incremental: '增量',
};

// ── 进度条 ─────────────────────────────────────────────────────────────────

function ProgressBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div className={styles.progressTrack}>
      <div className={styles.progressBar} style={{ width: `${pct}%` }} />
      <span className={styles.progressLabel}>{pct}%</span>
    </div>
  );
}

// ── 创建备份 Modal ────────────────────────────────────────────────────────────

function CreateBackupModal({
  open, onClose, onCreated,
}: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [backupType, setBackupType] = useState<'full' | 'incremental'>('full');
  const [cutoffDate, setCutoffDate] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleCreate = async () => {
    setSubmitting(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = { backup_type: backupType };
      if (backupType === 'incremental' && cutoffDate) {
        body.cutoff_date = cutoffDate;
      }
      await apiClient.post('/api/v1/backups/', body);
      onCreated();
      onClose();
      setBackupType('full');
      setCutoffDate('');
    } catch (e: any) {
      setErr(e?.message ?? '创建备份失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ZModal
      open={open}
      title="创建新备份"
      onClose={onClose}
      width={440}
      footer={
        <div className={styles.modalFooter}>
          <ZButton variant="ghost" onClick={onClose}>取消</ZButton>
          <ZButton variant="primary" onClick={handleCreate}>
            {submitting ? '创建中…' : '创建备份'}
          </ZButton>
        </div>
      }
    >
      <div className={styles.modalBody}>
        {err && <div className={styles.modalErr}><ZAlert variant="error" title={err} /></div>}

        <div className={styles.fieldRow}>
          <label className={styles.fieldLabel}>备份类型</label>
          <div className={styles.typeGroup}>
            {(['full', 'incremental'] as const).map(t => (
              <button
                key={t}
                className={`${styles.typeBtn} ${backupType === t ? styles.typeBtnActive : ''}`}
                onClick={() => setBackupType(t)}
                type="button"
              >
                {t === 'full' ? '🗄️ 全量备份' : '📦 增量备份'}
              </button>
            ))}
          </div>
          <span className={styles.fieldHint}>
            {backupType === 'full'
              ? '备份全部数据库数据，适合定期归档（文件较大）'
              : '仅备份上次全量备份后的变更数据，速度快、体积小'}
          </span>
        </div>

        {backupType === 'incremental' && (
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel}>截止日期（可选）</label>
            <input
              type="date"
              className={styles.dateInput}
              value={cutoffDate}
              onChange={e => setCutoffDate(e.target.value)}
            />
            <span className={styles.fieldHint}>留空则使用当前时间作为截止点</span>
          </div>
        )}
      </div>
    </ZModal>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

export default function PlatformBackupPage() {
  const [backups, setBackups] = useState<BackupJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 加载备份列表 ──
  const loadBackups = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.get('/api/v1/backups/');
      const list: BackupJob[] = Array.isArray(res) ? res : (res?.backups ?? res?.items ?? []);
      setBackups(list);
    } catch {
      setBackups([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadBackups(); }, [loadBackups]);

  // ── 轮询运行中的备份 ──
  useEffect(() => {
    const hasRunning = backups.some(b => b.status === 'running' || b.status === 'pending');
    if (hasRunning && !pollingRef.current) {
      pollingRef.current = setInterval(() => loadBackups(), 4000);
    } else if (!hasRunning && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
    };
  }, [backups, loadBackups]);

  // ── 下载 ──
  const handleDownload = (jobId: string) => {
    window.open(`/api/v1/backups/${jobId}/download`, '_blank');
  };

  // ── 删除 ──
  const handleDelete = async (jobId: string) => {
    setDeletingId(jobId);
    setErrMsg(null);
    try {
      await apiClient.delete(`/api/v1/backups/${jobId}`);
      setSuccessMsg('备份已删除');
      setConfirmDeleteId(null);
      loadBackups();
    } catch (e: any) {
      setErrMsg(e?.message ?? '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  // ── 统计 ──
  const totalCount     = backups.length;
  const completedCount = backups.filter(b => b.status === 'completed').length;
  const runningCount   = backups.filter(b => b.status === 'running' || b.status === 'pending').length;
  const failedCount    = backups.filter(b => b.status === 'failed').length;
  const totalSize      = backups
    .filter(b => b.status === 'completed')
    .reduce((acc, b) => acc + (b.size ?? 0), 0);

  // ── 表格列 ──
  const columns: ZTableColumn<BackupJob>[] = [
    {
      key: 'created_at',
      title: '创建时间',
      width: 130,
      render: (_, row) => (
        <span className={styles.timeCell}>{fmtTime(row.created_at)}</span>
      ),
    },
    {
      key: 'backup_type',
      title: '类型',
      width: 80,
      render: (_, row) => (
        <ZBadge
          type={row.backup_type === 'full' ? 'info' : 'default'}
          text={TYPE_LABEL[row.backup_type] ?? row.backup_type}
        />
      ),
    },
    {
      key: 'status',
      title: '状态',
      width: 100,
      render: (_, row) => (
        row.status === 'running' ? (
          <div className={styles.runningCell}>
            <ZBadge type="warning" text="进行中" />
            {row.progress != null && <ProgressBar value={row.progress} />}
          </div>
        ) : (
          <ZBadge
            type={STATUS_TYPE[row.status] ?? 'default'}
            text={STATUS_LABEL[row.status] ?? row.status}
          />
        )
      ),
    },
    {
      key: 'size',
      title: '文件大小',
      width: 110,
      align: 'right',
      render: (_, row) => (
        <span className={styles.sizeCell}>{fmtBytes(row.size)}</span>
      ),
    },
    {
      key: 'completed_at',
      title: '完成时间',
      width: 130,
      render: (_, row) => (
        <span className={styles.timeCell}>{fmtTime(row.completed_at)}</span>
      ),
    },
    {
      key: 'checksum',
      title: '校验和',
      render: (_, row) => (
        <span className={styles.checksumCell}>{row.checksum ? row.checksum.slice(0, 16) + '…' : '—'}</span>
      ),
    },
    {
      key: 'actions',
      title: '操作',
      width: 150,
      align: 'right',
      render: (_, row) => (
        <div className={styles.actionGroup}>
          {row.status === 'completed' && (
            <ZButton size="sm" variant="ghost" onClick={() => handleDownload(row.job_id)}>
              下载
            </ZButton>
          )}
          <ZButton
            size="sm"
            variant="ghost"
            onClick={() => setConfirmDeleteId(row.job_id)}
          >
            {deletingId === row.job_id ? '删除中…' : '删除'}
          </ZButton>
        </div>
      ),
    },
  ];

  return (
    <div className={styles.page}>
      {/* 页头 */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>备份管理</h1>
          <p className={styles.pageSubtitle}>
            创建和管理数据库备份，保障数据安全与业务连续性
          </p>
        </div>
        <div className={styles.headerActions}>
          <ZButton size="sm" variant="ghost" onClick={loadBackups}>刷新</ZButton>
          <ZButton size="sm" variant="primary" onClick={() => setCreateOpen(true)}>
            + 创建备份
          </ZButton>
        </div>
      </div>

      {/* 提示 */}
      {successMsg && (
        <div className={styles.alertRow}>
          <ZAlert variant="success" title={successMsg} />
        </div>
      )}
      {errMsg && (
        <div className={styles.alertRow}>
          <ZAlert variant="error" title={errMsg} />
        </div>
      )}

      {/* 统计行 */}
      <div className={styles.statsRow}>
        <ZCard className={styles.statCard}>
          <div className={styles.statNum}>{totalCount}</div>
          <div className={styles.statLabel}>备份总数</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={`${styles.statNum} ${styles.statGreen}`}>{completedCount}</div>
          <div className={styles.statLabel}>已完成</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={`${styles.statNum} ${runningCount > 0 ? styles.statOrange : ''}`}>
            {runningCount}
          </div>
          <div className={styles.statLabel}>进行中</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={`${styles.statNum} ${failedCount > 0 ? styles.statRed : ''}`}>
            {failedCount}
          </div>
          <div className={styles.statLabel}>失败</div>
        </ZCard>
        <ZCard className={styles.statCard}>
          <div className={styles.statNum}>{fmtBytes(totalSize)}</div>
          <div className={styles.statLabel}>已完成备份总体积</div>
        </ZCard>
      </div>

      {/* 备份列表 */}
      {loading ? (
        <ZCard><ZSkeleton rows={6} /></ZCard>
      ) : backups.length === 0 ? (
        <ZCard>
          <ZEmpty text="暂无备份记录，点击「创建备份」开始第一次备份" />
        </ZCard>
      ) : (
        <ZCard className={styles.tableCard}>
          <ZTable<BackupJob>
            columns={columns}
            data={backups}
            rowKey="job_id"
          />
        </ZCard>
      )}

      {/* 创建备份 Modal */}
      <CreateBackupModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setSuccessMsg('备份任务已创建，正在后台运行…');
          loadBackups();
          setTimeout(() => setSuccessMsg(null), 5000);
        }}
      />

      {/* 删除确认 Modal */}
      <ZModal
        open={!!confirmDeleteId}
        title="确认删除备份"
        onClose={() => setConfirmDeleteId(null)}
        width={400}
        footer={
          <div className={styles.modalFooter}>
            <ZButton variant="ghost" onClick={() => setConfirmDeleteId(null)}>取消</ZButton>
            <ZButton
              variant="primary"
              onClick={() => confirmDeleteId && handleDelete(confirmDeleteId)}
            >
              {deletingId ? '删除中…' : '确认删除'}
            </ZButton>
          </div>
        }
      >
        <div className={styles.modalBody}>
          <ZAlert
            variant="warning"
            title="删除后该备份文件将无法恢复，请确认操作"
          />
        </div>
      </ZModal>
    </div>
  );
}
