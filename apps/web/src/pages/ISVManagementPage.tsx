import React, { useState, useEffect, useCallback } from 'react';
import { Form, Input, message } from 'antd';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZTable, ZModal, ZEmpty, ZSelect } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components';
import { apiClient, handleApiError } from '../services/api';
import styles from './ISVManagementPage.module.css';

// ── Types ──────────────────────────────────────────────────────────────────────

interface Developer {
  id: string;
  name: string;
  email: string;
  company: string | null;
  tier: string;
  status: string;
  is_verified: boolean;
  webhook_url: string | null;
  upgrade_request_tier: string | null;
  upgrade_requested_at: string | null;
  upgrade_reviewed_at: string | null;
  active_keys: number;
  created_at: string;
}

interface AdminStats {
  active_developers: number;
  suspended_developers: number;
  verified_developers: number;
  pending_upgrade_reviews: number;
  by_tier: Record<string, number>;
}

const TIER_BADGE: Record<string, 'neutral' | 'success' | 'warning' | 'error'> = {
  free: 'neutral', basic: 'success', pro: 'warning', enterprise: 'error',
};
const TIER_LABELS: Record<string, string> = {
  free: '免费版', basic: '基础版', pro: '专业版', enterprise: '企业版',
};

// ── Columns ────────────────────────────────────────────────────────────────────

const makeColumns = (
  onReview: (dev: Developer) => void,
  onToggleStatus: (dev: Developer) => void,
): ZTableColumn<Developer>[] => [
  {
    key: 'name',
    title: '开发者',
    render: (name, row) => (
      <div>
        <div style={{ fontWeight: 600 }}>{name}</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{row.email}</div>
        {row.company && <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{row.company}</div>}
      </div>
    ),
  },
  {
    key: 'tier',
    title: '套餐',
    align: 'center',
    render: (tier) => <ZBadge type={TIER_BADGE[tier] || 'neutral'} text={TIER_LABELS[tier] || tier} />,
  },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (status, row) => (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
        <ZBadge type={status === 'active' ? 'success' : 'error'} text={status === 'active' ? '活跃' : '已暂停'} />
        {row.is_verified && <ZBadge type="neutral" text="已验证" />}
      </div>
    ),
  },
  {
    key: 'active_keys',
    title: 'API Key',
    align: 'center',
    render: (n) => <span style={{ fontWeight: 600 }}>{n}</span>,
  },
  {
    key: 'upgrade_request_tier',
    title: '升级申请',
    align: 'center',
    render: (tier, row) => {
      if (!tier) return <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>—</span>;
      const isPending = !row.upgrade_reviewed_at;
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <ZBadge type={TIER_BADGE[tier] || 'neutral'} text={`→ ${TIER_LABELS[tier] || tier}`} />
          <ZBadge type={isPending ? 'warning' : 'success'} text={isPending ? '待审核' : '已处理'} />
        </div>
      );
    },
  },
  {
    key: 'created_at',
    title: '注册时间',
    render: (dt) => dt ? new Date(dt).toLocaleDateString('zh-CN') : '—',
  },
  {
    key: 'id',
    title: '操作',
    render: (_, row) => (
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {row.upgrade_request_tier && !row.upgrade_reviewed_at && (
          <ZButton variant="primary" onClick={() => onReview(row)}>审核升级</ZButton>
        )}
        <ZButton onClick={() => onToggleStatus(row)}>
          {row.status === 'active' ? '暂停' : '恢复'}
        </ZButton>
      </div>
    ),
  },
];

// ── Component ──────────────────────────────────────────────────────────────────

const STATUS_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'active', label: '活跃' },
  { value: 'suspended', label: '已暂停' },
];

const ISVManagementPage: React.FC = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [developers, setDevelopers] = useState<Developer[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState('all');
  const [pendingOnly, setPendingOnly] = useState(false);

  // Review modal
  const [reviewModal, setReviewModal] = useState(false);
  const [reviewTarget, setReviewTarget] = useState<Developer | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewForm] = Form.useForm();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: '50', offset: '0' };
      if (statusFilter !== 'all') params.status = statusFilter;
      if (pendingOnly) params.pending_upgrade = 'true';

      const [statsRes, devRes] = await Promise.allSettled([
        apiClient.get('/api/v1/open/isv/admin/stats'),
        apiClient.get('/api/v1/open/isv/admin/list', { params }),
      ]);
      if (statsRes.status === 'fulfilled') setStats(statsRes.value.data);
      if (devRes.status === 'fulfilled') {
        setDevelopers(devRes.value.data.developers || []);
        setTotal(devRes.value.data.total || 0);
      }
    } catch (e) {
      handleApiError(e);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, pendingOnly]);

  useEffect(() => { loadData(); }, [loadData]);

  const openReview = (dev: Developer) => {
    setReviewTarget(dev);
    setReviewModal(true);
  };

  const handleToggleStatus = async (dev: Developer) => {
    const newStatus = dev.status === 'active' ? 'suspended' : 'active';
    try {
      await apiClient.put(`/api/v1/open/isv/admin/${dev.id}/status`, { status: newStatus });
      message.success(`账号已${newStatus === 'suspended' ? '暂停' : '恢复'}`);
      loadData();
    } catch (e) {
      handleApiError(e);
    }
  };

  const handleReviewSubmit = async (values: { approved: string; note?: string }) => {
    if (!reviewTarget) return;
    setReviewLoading(true);
    try {
      await apiClient.post(`/api/v1/open/isv/admin/${reviewTarget.id}/review-upgrade`, {
        approved: values.approved === 'true',
        note: values.note,
      });
      message.success(values.approved === 'true' ? '升级申请已批准' : '升级申请已驳回');
      setReviewModal(false);
      reviewForm.resetFields();
      setReviewTarget(null);
      loadData();
    } catch (e) {
      handleApiError(e);
    } finally {
      setReviewLoading(false);
    }
  };

  const columns = makeColumns(openReview, handleToggleStatus);

  const reviewFooter = (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
      <ZButton onClick={() => { setReviewModal(false); reviewForm.resetFields(); }}>取消</ZButton>
      <ZButton variant="primary" disabled={reviewLoading} onClick={() => reviewForm.submit()}>
        {reviewLoading ? '提交中…' : '提交审核'}
      </ZButton>
    </div>
  );

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>ISV 管理后台</h1>
          <p className={styles.pageSub}>开发者认证 · 套餐升级审核 · 账号管理</p>
        </div>
        <div className={styles.headerActions}>
          <ZButton onClick={loadData}>刷新</ZButton>
          <ZButton
            variant={pendingOnly ? 'primary' : undefined}
            onClick={() => setPendingOnly(v => !v)}
          >
            {pendingOnly ? '✓ 仅待审核' : '待审核升级'}
          </ZButton>
        </div>
      </div>

      {/* KPI Row */}
      <div className={styles.kpiGrid}>
        {loading ? (
          [...Array(5)].map((_, i) => <ZSkeleton key={i} height={88} />)
        ) : (
          <>
            <ZCard><ZKpi label="活跃开发者" value={stats?.active_developers ?? '-'} unit="个" /></ZCard>
            <ZCard><ZKpi label="已暂停" value={stats?.suspended_developers ?? 0} unit="个" /></ZCard>
            <ZCard><ZKpi label="邮箱已验证" value={stats?.verified_developers ?? 0} unit="个" /></ZCard>
            <ZCard>
              <ZKpi
                label="待审核升级"
                value={stats?.pending_upgrade_reviews ?? 0}
                unit="个"
              />
            </ZCard>
            <ZCard>
              <div className={styles.tierBreakdown}>
                <div className={styles.tierBreakdownTitle}>套餐分布</div>
                {Object.entries(stats?.by_tier || {}).map(([tier, count]) => (
                  <div key={tier} className={styles.tierBreakdownRow}>
                    <ZBadge type={TIER_BADGE[tier] || 'neutral'} text={TIER_LABELS[tier] || tier} />
                    <span className={styles.tierBreakdownCount}>{count}</span>
                  </div>
                ))}
              </div>
            </ZCard>
          </>
        )}
      </div>

      {/* Filter + Table */}
      <ZCard
        title={`开发者列表（${total} 个）`}
        extra={
          <ZSelect
            value={statusFilter}
            options={STATUS_OPTIONS}
            onChange={setStatusFilter}
          />
        }
      >
        {loading ? <ZSkeleton height={300} /> : (
          developers.length > 0
            ? <ZTable columns={columns} data={developers} rowKey="id" />
            : <ZEmpty text="暂无符合条件的开发者" />
        )}
      </ZCard>

      {/* Review Modal */}
      <ZModal
        open={reviewModal}
        title={`审核升级申请 — ${reviewTarget?.name}`}
        onClose={() => { setReviewModal(false); reviewForm.resetFields(); }}
        footer={reviewFooter}
        width={480}
      >
        {reviewTarget && (
          <>
            <div className={styles.reviewInfo}>
              <div className={styles.reviewRow}>
                <span className={styles.reviewLabel}>申请人</span>
                <span>{reviewTarget.name} ({reviewTarget.email})</span>
              </div>
              <div className={styles.reviewRow}>
                <span className={styles.reviewLabel}>当前套餐</span>
                <ZBadge type={TIER_BADGE[reviewTarget.tier] || 'neutral'} text={TIER_LABELS[reviewTarget.tier] || reviewTarget.tier} />
              </div>
              <div className={styles.reviewRow}>
                <span className={styles.reviewLabel}>目标套餐</span>
                <ZBadge
                  type={TIER_BADGE[reviewTarget.upgrade_request_tier || ''] || 'neutral'}
                  text={TIER_LABELS[reviewTarget.upgrade_request_tier || ''] || reviewTarget.upgrade_request_tier || '—'}
                />
              </div>
              <div className={styles.reviewRow}>
                <span className={styles.reviewLabel}>申请时间</span>
                <span>{reviewTarget.upgrade_requested_at ? new Date(reviewTarget.upgrade_requested_at).toLocaleString('zh-CN') : '—'}</span>
              </div>
            </div>
            <Form form={reviewForm} layout="vertical" onFinish={handleReviewSubmit}>
              <Form.Item name="approved" label="审核结论" initialValue="true" rules={[{ required: true }]}>
                <select className={styles.nativeSelect}>
                  <option value="true">批准升级</option>
                  <option value="false">驳回申请</option>
                </select>
              </Form.Item>
              <Form.Item name="note" label="审核意见">
                <Input.TextArea rows={3} placeholder="可选填写审核意见（驳回时必填）" />
              </Form.Item>
            </Form>
          </>
        )}
      </ZModal>
    </div>
  );
};

export default ISVManagementPage;
