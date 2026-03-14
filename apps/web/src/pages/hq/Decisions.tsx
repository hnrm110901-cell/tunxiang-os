/**
 * 总部决策审批页（跨门店）
 * 路由：/hq/decisions
 * 数据：GET /api/v1/approvals?status=pending
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  ZCard, ZBadge, ZButton, ZSkeleton, ZEmpty, ZModal,
} from '../../design-system/components';
import apiClient from '../../services/api';
import styles from './Decisions.module.css';

interface PendingDecision {
  id:                   string;
  store_id:             string;
  store_name?:          string;
  title:                string;
  type:                 string;
  decision_type:        string;
  expected_saving_yuan: number;
  confidence_pct:       number;
  trust_score:          number;
  ai_reasoning:         string;
  outcome:              string | null;
  created_at:           string | null;
}

export default function HQDecisions() {
  const [items,     setItems]     = useState<PendingDecision[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string | null>(null);
  const [selected,  setSelected]  = useState<PendingDecision | null>(null);
  const [approving, setApproving] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [feedback,  setFeedback]  = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.get('/api/v1/approvals', { params: { status: 'pending' } });
      const raw: any[] = resp.items ?? resp ?? [];
      setItems(raw.map(d => ({
        id:                   d.id,
        store_id:             d.store_id,
        store_name:           d.store_name ?? d.store_id,
        title:                d.title ?? d.ai_suggestion?.action ?? d.ai_suggestion?.title ?? '待审批决策',
        type:                 d.type ?? d.decision_type ?? '',
        decision_type:        d.decision_type ?? d.type ?? '',
        expected_saving_yuan: d.expected_saving_yuan ?? d.ai_suggestion?.expected_saving_yuan ?? 0,
        confidence_pct:       d.confidence_pct ?? (d.ai_confidence != null ? d.ai_confidence * 100 : 0),
        trust_score:          d.trust_score ?? 0,
        ai_reasoning:         d.ai_suggestion?.reasoning ?? '',
        outcome:              d.outcome ?? null,
        created_at:           d.created_at ?? null,
      })));
    } catch (e: any) {
      setError(e?.response?.data?.detail || '数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleApprove = async (id: string) => {
    setApproving(id);
    try {
      await apiClient.post(`/api/v1/approvals/${id}/approve`, {});
      setItems(prev => prev.filter(i => i.id !== id));
      setSelected(null);
    } catch (e: any) {
      alert(e?.response?.data?.detail || '审批失败，请重试');
    } finally {
      setApproving(null);
    }
  };

  const handleReject = async (id: string) => {
    setRejecting(id);
    try {
      await apiClient.post(`/api/v1/approvals/${id}/reject`, { feedback });
      setItems(prev => prev.filter(i => i.id !== id));
      setSelected(null);
      setFeedback('');
    } catch (e: any) {
      alert(e?.response?.data?.detail || '驳回失败，请重试');
    } finally {
      setRejecting(null);
    }
  };

  const trustColor = (score: number) =>
    score >= 70 ? 'var(--green)' : score >= 40 ? 'var(--accent)' : 'var(--red, #e74c3c)';

  const outcomeLabel = (outcome: string | null) => {
    if (!outcome) return null;
    const map: Record<string, { text: string; type: 'success' | 'warning' | 'error' }> = {
      success: { text: '已验证成功', type: 'success' },
      partial: { text: '部分成功', type: 'warning' },
      failure: { text: '效果不佳', type: 'error' },
    };
    return map[outcome] ?? null;
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.title}>待审批决策</div>
        <ZButton variant="ghost" size="sm" onClick={load}>刷新</ZButton>
      </div>

      {loading ? (
        <div className={styles.body}><ZSkeleton rows={5} avatar /></div>
      ) : error ? (
        <div className={styles.body}>
          <ZEmpty icon="⚠️" title="加载失败" description={error} action={<ZButton size="sm" onClick={load}>重试</ZButton>} />
        </div>
      ) : items.length === 0 ? (
        <div className={styles.body}>
          <ZEmpty icon="✅" title="暂无待审批决策" description="所有决策已处理完毕" />
        </div>
      ) : (
        <div className={styles.body}>
          <ZCard subtitle={`共 ${items.length} 项待处理`}>
            {items.map(item => (
              <div key={item.id} className={styles.row} onClick={() => setSelected(item)}>
                <div className={styles.rowLeft}>
                  <ZBadge
                    type={item.confidence_pct >= 80 ? 'success' : item.confidence_pct >= 60 ? 'info' : 'warning'}
                    text={`${item.confidence_pct.toFixed(0)}%`}
                  />
                  <div className={styles.rowMeta}>
                    <div className={styles.rowTitle}>{item.title}</div>
                    <div className={styles.rowSub}>
                      {item.store_name || item.store_id}
                      {item.trust_score > 0 && (
                        <span className={styles.trustBadge} style={{ color: trustColor(item.trust_score) }}>
                          {' '}信任{item.trust_score.toFixed(0)}
                        </span>
                      )}
                      {item.outcome && (() => {
                        const info = outcomeLabel(item.outcome);
                        return info ? <span className={styles.outcomeBadge} data-type={info.type}>{' '}{info.text}</span> : null;
                      })()}
                      {item.created_at && ` · ${new Date(item.created_at).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
                    </div>
                  </div>
                </div>
                <div className={styles.rowRight}>
                  {item.expected_saving_yuan > 0 && (
                    <span className={styles.saving}>¥{item.expected_saving_yuan.toFixed(0)}</span>
                  )}
                  <span className={styles.chevron}>›</span>
                </div>
              </div>
            ))}
          </ZCard>
        </div>
      )}

      <ZModal
        open={!!selected}
        title="决策详情"
        onClose={() => { setSelected(null); setFeedback(''); }}
        footer={
          <>
            <ZButton
              variant="ghost"
              loading={rejecting === selected?.id}
              onClick={() => selected && handleReject(selected.id)}
              style={{ color: 'var(--red, #e74c3c)' }}
            >
              驳回
            </ZButton>
            <ZButton
              loading={approving === selected?.id}
              onClick={() => selected && handleApprove(selected.id)}
            >
              批准执行
            </ZButton>
          </>
        }
      >
        {selected && (
          <div className={styles.detail}>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>决策内容</span>
              <span className={styles.detailValue}>{selected.title}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>所属门店</span>
              <span className={styles.detailValue}>{selected.store_name || selected.store_id}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>预期节省</span>
              <span className={styles.detailAccent}>¥{selected.expected_saving_yuan.toFixed(2)}</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>AI置信度</span>
              <span className={styles.detailValue}>{selected.confidence_pct.toFixed(1)}%</span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>AI信任分</span>
              <span className={styles.detailValue} style={{ color: trustColor(selected.trust_score) }}>
                {selected.trust_score.toFixed(1)}
              </span>
            </div>
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>决策类型</span>
              <span className={styles.detailValue}>{selected.decision_type || selected.type}</span>
            </div>
            {selected.outcome && (() => {
              const info = outcomeLabel(selected.outcome);
              return info ? (
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>效果评估</span>
                  <span className={styles.outcomeBadge} data-type={info.type}>{info.text}</span>
                </div>
              ) : null;
            })()}
            {selected.ai_reasoning && (
              <div className={styles.reasoningSection}>
                <span className={styles.detailLabel}>AI推理依据</span>
                <div className={styles.reasoningText}>{selected.ai_reasoning}</div>
              </div>
            )}
            <div className={styles.feedbackSection}>
              <span className={styles.detailLabel}>驳回反馈（可选）</span>
              <textarea
                className={styles.feedbackInput}
                placeholder="请输入驳回理由，帮助AI改进..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={2}
              />
            </div>
          </div>
        )}
      </ZModal>
    </div>
  );
}
