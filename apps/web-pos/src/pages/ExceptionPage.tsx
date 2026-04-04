/**
 * 异常中心 — 投诉/退菜/设备故障/缺料 集中处理
 */
import { useEffect, useState, useCallback } from 'react';
import { fetchExceptions, resolveException, type ExceptionItem } from '../api';

const STORE_ID = import.meta.env.VITE_STORE_ID || '';

const typeIcon: Record<string, string> = { complaint: '😤', return_dish: '↩️', equipment: '🔧', shortage: '📦', discount: '💰' };
const severityColor: Record<string, string> = { critical: '#ff4d4f', high: '#faad14', medium: '#1890ff', low: '#52c41a' };
const statusLabel: Record<string, string> = { pending: '待处理', processing: '处理中', resolved: '已解决' };

export function ExceptionPage() {
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchExceptions(STORE_ID);
      setExceptions(data.items);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '加载异常列表失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleResolve = async (id: string) => {
    setResolving(id);
    try {
      await resolveException(id);
      setExceptions(prev =>
        prev.map(e => (e.id === id ? { ...e, status: 'processing' as const } : e)),
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '处理失败';
      setError(message);
    } finally {
      setResolving(null);
    }
  };

  const pending = exceptions.filter(e => e.status === 'pending');
  const processing = exceptions.filter(e => e.status === 'processing');
  const resolved = exceptions.filter(e => e.status === 'resolved');

  return (
    <div style={{ padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>异常中心</h3>
        <div style={{ display: 'flex', gap: 12, fontSize: 13 }}>
          <span style={{ color: '#ff4d4f' }}>待处理 {pending.length}</span>
          <span style={{ color: '#faad14' }}>处理中 {processing.length}</span>
          <span style={{ color: '#52c41a' }}>已解决 {resolved.length}</span>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 48, color: '#888', fontSize: 14 }}>
          加载中...
        </div>
      )}

      {error && !loading && (
        <div style={{ textAlign: 'center', padding: 48, color: '#ff4d4f', fontSize: 14 }}>
          <div>{error}</div>
          <button
            onClick={loadData}
            style={{ marginTop: 12, padding: '6px 16px', background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}
          >
            重试
          </button>
        </div>
      )}

      {!loading && !error && exceptions.length === 0 && (
        <div style={{ textAlign: 'center', padding: 48, color: '#888', fontSize: 14 }}>
          暂无异常记录
        </div>
      )}

      {!loading && !error && exceptions.map(e => (
        <div key={e.id} style={{
          padding: 14, marginBottom: 8, borderRadius: 8, background: '#112228',
          borderLeft: `4px solid ${severityColor[e.severity]}`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 24 }}>{typeIcon[e.type]}</span>
            <div>
              <div style={{ fontWeight: 'bold' }}>{e.title}</div>
              <div style={{ fontSize: 12, color: '#666' }}>{e.time} {e.table ? `· ${e.table}` : ''}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              padding: '3px 10px', borderRadius: 10, fontSize: 11,
              background: e.status === 'pending' ? '#ff4d4f22' : e.status === 'processing' ? '#faad1422' : '#52c41a22',
              color: e.status === 'pending' ? '#ff4d4f' : e.status === 'processing' ? '#faad14' : '#52c41a',
            }}>
              {statusLabel[e.status]}
            </span>
            {e.status === 'pending' && (
              <button
                disabled={resolving === e.id}
                onClick={() => handleResolve(e.id)}
                style={{
                  padding: '4px 12px', background: '#FF6B2C', color: '#fff', border: 'none',
                  borderRadius: 6, cursor: resolving === e.id ? 'not-allowed' : 'pointer', fontSize: 12,
                  opacity: resolving === e.id ? 0.6 : 1,
                }}
              >
                {resolving === e.id ? '处理中...' : '处理'}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
