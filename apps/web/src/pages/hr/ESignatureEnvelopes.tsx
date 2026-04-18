/**
 * 电子签约 — 信封列表
 * - 状态筛选
 * - 新建信封（选模板、填签署人、发送）
 */
import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../../services/api';
import styles from './HRPages.module.css';

interface EnvelopeItem {
  id: string;
  envelope_no: string;
  subject?: string;
  envelope_status: string;
  sent_at?: string;
  completed_at?: string;
  expires_at?: string;
  signed_document_url?: string;
}

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  sent: '已发送',
  partially_signed: '部分签署',
  completed: '已完成',
  rejected: '已拒签',
  expired: '已过期',
};

const STATUS_COLORS: Record<string, string> = {
  draft: '#888',
  sent: '#2D9CDB',
  partially_signed: '#F2994A',
  completed: '#27AE60',
  rejected: '#EB5757',
  expired: '#EB5757',
};

const ESignatureEnvelopes: React.FC = () => {
  const [userId] = useState<string>(localStorage.getItem('user_id') || 'HR');
  const [role, setRole] = useState<'initiator' | 'signer'>('initiator');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [items, setItems] = useState<EnvelopeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    subject: '',
    signers_text: '',  // 简化：signer_id|name|role 每行一条
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ role, user_id: userId });
      if (statusFilter) qs.append('status', statusFilter);
      const res = await apiClient.get(`/api/v1/hr/e-signature/envelopes/my?${qs.toString()}`);
      setItems(res.data?.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [role, userId, statusFilter]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = async () => {
    const signers = form.signers_text.split('\n').filter(Boolean).map((line, idx) => {
      const [signer_id, name, srole] = line.split('|').map(s => s.trim());
      return { signer_id, name: name || signer_id, role: srole || 'employee', order: idx + 1 };
    });
    if (signers.length === 0) {
      alert('至少需要 1 个签署人');
      return;
    }
    await apiClient.post('/api/v1/hr/e-signature/envelopes', {
      subject: form.subject,
      initiator_id: userId,
      signer_list: signers,
      expires_in_days: 14,
    });
    setShowNew(false);
    setForm({ subject: '', signers_text: '' });
    void load();
  };

  const handleSend = async (id: string) => {
    await apiClient.post(`/api/v1/hr/e-signature/envelopes/${id}/send`, { actor_id: userId });
    void load();
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>电子签约 · 信封管理</h1>
        <div>
          <select value={role} onChange={e => setRole(e.target.value as 'initiator' | 'signer')}>
            <option value="initiator">我发起的</option>
            <option value="signer">我要签署</option>
          </select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ marginLeft: 8 }}>
            <option value="">全部状态</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <button className={styles.primaryBtn} style={{ marginLeft: 8 }} onClick={() => setShowNew(true)}>新建信封</button>
        </div>
      </div>

      {loading ? (
        <div className={styles.empty}>加载中...</div>
      ) : items.length === 0 ? (
        <div className={styles.empty}>暂无信封</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>信封编号</th><th>主题</th><th>状态</th>
              <th>发送时间</th><th>完成时间</th><th>过期时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map(e => (
              <tr key={e.id}>
                <td>{e.envelope_no}</td>
                <td>{e.subject || '-'}</td>
                <td>
                  <span style={{ color: STATUS_COLORS[e.envelope_status], fontWeight: 600 }}>
                    {STATUS_LABELS[e.envelope_status] || e.envelope_status}
                  </span>
                </td>
                <td>{e.sent_at || '-'}</td>
                <td>{e.completed_at || '-'}</td>
                <td>{e.expires_at || '-'}</td>
                <td>
                  {e.envelope_status === 'draft' && (
                    <button className={styles.linkBtn} onClick={() => handleSend(e.id)}>发送</button>
                  )}
                  <a className={styles.linkBtn} href={`/api/v1/hr/e-signature/envelopes/${e.id}/audit-trail`} target="_blank" rel="noreferrer">审计链</a>
                  {e.envelope_status === 'completed' && (
                    <a className={styles.linkBtn} href={`/api/v1/hr/e-signature/envelopes/${e.id}/pdf`} target="_blank" rel="noreferrer">下载PDF</a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showNew && (
        <div className={styles.modal}>
          <div className={styles.modalBody}>
            <h3>新建信封</h3>
            <input placeholder="信封主题（如：劳动合同 - 张三）"
              value={form.subject}
              onChange={e => setForm({ ...form, subject: e.target.value })} />
            <textarea
              placeholder="签署人（每行一条，格式：signer_id|姓名|角色，角色可选 employee/hr/legal_rep）&#10;例：E001|张三|employee&#10;HR|人事|hr"
              rows={6}
              value={form.signers_text}
              onChange={e => setForm({ ...form, signers_text: e.target.value })}
            />
            <div>
              <button onClick={() => setShowNew(false)}>取消</button>
              <button className={styles.primaryBtn} onClick={handleCreate}>保存草稿</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ESignatureEnvelopes;
