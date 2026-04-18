/**
 * 法人主体管理页
 * - 列表 + 新建
 * - 门店绑定管理（支持历史变更）
 */
import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../../services/api';
import styles from './HRPages.module.css';

interface LegalEntityItem {
  id: string;
  code: string;
  name: string;
  entity_type: string;
  legal_representative?: string;
  unified_social_credit?: string;
  status: string;
  registered_capital_yuan?: number;
}

const TYPE_LABELS: Record<string, string> = {
  direct_operated: '直营',
  franchise: '加盟',
  joint_venture: '合资',
  subsidiary: '子公司',
};

const LegalEntities: React.FC = () => {
  const [brandId] = useState<string>(localStorage.getItem('brand_id') || '');
  const [items, setItems] = useState<LegalEntityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showBind, setShowBind] = useState<string | null>(null);

  const [form, setForm] = useState({
    code: '',
    name: '',
    entity_type: 'direct_operated',
    legal_representative: '',
    unified_social_credit: '',
    registered_capital_fen: 0,
    tax_number: '',
    bank_name: '',
    bank_account: '',
  });

  const [bindForm, setBindForm] = useState({
    store_id: '',
    start_date: new Date().toISOString().slice(0, 10),
    is_primary: true,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const url = brandId ? `/api/v1/hr/legal-entities?brand_id=${brandId}` : '/api/v1/hr/legal-entities';
      const res = await apiClient.get(url);
      setItems(res.data?.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = async () => {
    await apiClient.post('/api/v1/hr/legal-entities', { ...form, brand_id: brandId || undefined });
    setShowForm(false);
    void load();
  };

  const handleBind = async (entityId: string) => {
    await apiClient.post(`/api/v1/hr/legal-entities/${entityId}/stores`, bindForm);
    setShowBind(null);
    alert('绑定成功');
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>法人主体管理</h1>
        <button className={styles.primaryBtn} onClick={() => setShowForm(true)}>新建主体</button>
      </div>

      {loading ? (
        <div className={styles.empty}>加载中...</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>主体编码</th><th>名称</th><th>类型</th><th>法定代表人</th>
              <th>统一社会信用代码</th><th>注册资本（元）</th><th>状态</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map(e => (
              <tr key={e.id}>
                <td>{e.code}</td>
                <td>{e.name}</td>
                <td>{TYPE_LABELS[e.entity_type] || e.entity_type}</td>
                <td>{e.legal_representative || '-'}</td>
                <td>{e.unified_social_credit || '-'}</td>
                <td>{e.registered_capital_yuan ?? '-'}</td>
                <td>{e.status}</td>
                <td>
                  <button className={styles.linkBtn} onClick={() => setShowBind(e.id)}>绑定门店</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalBody}>
            <h3>新建法人主体</h3>
            <input placeholder="主体编码" value={form.code} onChange={e => setForm({ ...form, code: e.target.value })} />
            <input placeholder="公司全称" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
            <select value={form.entity_type} onChange={e => setForm({ ...form, entity_type: e.target.value })}>
              {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input placeholder="法定代表人" value={form.legal_representative} onChange={e => setForm({ ...form, legal_representative: e.target.value })} />
            <input placeholder="统一社会信用代码" value={form.unified_social_credit} onChange={e => setForm({ ...form, unified_social_credit: e.target.value })} />
            <input type="number" placeholder="注册资本（分）" value={form.registered_capital_fen} onChange={e => setForm({ ...form, registered_capital_fen: Number(e.target.value) })} />
            <input placeholder="税号" value={form.tax_number} onChange={e => setForm({ ...form, tax_number: e.target.value })} />
            <input placeholder="开户行" value={form.bank_name} onChange={e => setForm({ ...form, bank_name: e.target.value })} />
            <input placeholder="银行账号" value={form.bank_account} onChange={e => setForm({ ...form, bank_account: e.target.value })} />
            <div>
              <button onClick={() => setShowForm(false)}>取消</button>
              <button className={styles.primaryBtn} onClick={handleCreate}>保存</button>
            </div>
          </div>
        </div>
      )}

      {showBind && (
        <div className={styles.modal}>
          <div className={styles.modalBody}>
            <h3>绑定门店到该主体</h3>
            <input placeholder="门店ID" value={bindForm.store_id} onChange={e => setBindForm({ ...bindForm, store_id: e.target.value })} />
            <input type="date" value={bindForm.start_date} onChange={e => setBindForm({ ...bindForm, start_date: e.target.value })} />
            <label>
              <input type="checkbox" checked={bindForm.is_primary}
                onChange={e => setBindForm({ ...bindForm, is_primary: e.target.checked })} />
              主签约主体
            </label>
            <div>
              <button onClick={() => setShowBind(null)}>取消</button>
              <button className={styles.primaryBtn} onClick={() => handleBind(showBind)}>确定</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LegalEntities;
