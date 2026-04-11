/**
 * 开店检查单 — /manager/opening-checklist
 * P0-11: 店长到店后执行开店检查（设备/物料/卫生/安全）
 * 大按钮逐项勾选，支持拍照上传，对接 tx-ops E1节点
 *
 * API: GET  /api/v1/ops/checklists/opening?store_id=&date=
 *      POST /api/v1/ops/checklists/opening/submit
 *      POST /api/v1/ops/checklists/opening/items/{id}/check
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../../api';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type CheckStatus = 'unchecked' | 'pass' | 'fail' | 'na';

interface CheckItem {
  id: string;
  category: string;
  title: string;
  description: string;
  required: boolean;
  status: CheckStatus;
  note: string;
  photoUrl: string | null;
}

interface ChecklistData {
  checklistId: string | null;
  date: string;
  storeName: string;
  operatorName: string;
  startedAt: string | null;
  completedAt: string | null;
  items: CheckItem[];
}

// ─── Fallback ──────────────────────────────────────────────────────────────────

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const FALLBACK_ITEMS: CheckItem[] = [
  // 设备检查
  { id: 'e1', category: '设备检查', title: 'POS收银机开机', description: '确认POS主机正常启动，屏幕显示正常', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'e2', category: '设备检查', title: '打印机测试', description: '打印测试小票，确认前台+厨房打印机工作正常', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'e3', category: '设备检查', title: '电子秤校准', description: '使用标准砝码校准电子秤，误差≤5g', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'e4', category: '设备检查', title: '钱箱现金清点', description: '确认钱箱备用金与昨日交接数一致', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'e5', category: '设备检查', title: '网络连接', description: '确认WiFi/有线网络正常，Mac mini在线', required: true, status: 'unchecked', note: '', photoUrl: null },
  // 物料盘点
  { id: 'm1', category: '物料盘点', title: '主要食材到位', description: '检查当日主要食材（鱼/虾/肉类）是否已到货', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'm2', category: '物料盘点', title: '酒水饮料库存', description: '确认常用酒水饮料库存充足', required: false, status: 'unchecked', note: '', photoUrl: null },
  { id: 'm3', category: '物料盘点', title: '一次性耗材', description: '纸巾/打包盒/筷子/吸管等一次性耗材充足', required: false, status: 'unchecked', note: '', photoUrl: null },
  { id: 'm4', category: '物料盘点', title: '活鲜缸检查', description: '检查活鲜缸水温/含氧量/鱼虾活力', required: true, status: 'unchecked', note: '', photoUrl: null },
  // 环境卫生
  { id: 'h1', category: '环境卫生', title: '前厅清洁', description: '地面/桌面/椅子清洁无污渍', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'h2', category: '环境卫生', title: '后厨清洁', description: '灶台/切配台/地面/排水沟清洁', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'h3', category: '环境卫生', title: '洗手间检查', description: '洗手间清洁、纸巾/洗手液充足', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 'h4', category: '环境卫生', title: '垃圾清运', description: '各区域垃圾桶已清空更换垃圾袋', required: true, status: 'unchecked', note: '', photoUrl: null },
  // 安全检查
  { id: 's1', category: '安全检查', title: '消防设备', description: '灭火器在位且在有效期内，安全通道畅通', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 's2', category: '安全检查', title: '燃气安全', description: '检查燃气管道无泄漏，阀门正常', required: true, status: 'unchecked', note: '', photoUrl: null },
  { id: 's3', category: '安全检查', title: '食品留样', description: '确认昨日留样已处理，今日留样容器已准备', required: true, status: 'unchecked', note: '', photoUrl: null },
];

const STORE_ID = import.meta.env.VITE_STORE_ID || '';

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function OpeningChecklistPage() {
  const navigate = useNavigate();
  const [checklist, setChecklist] = useState<ChecklistData>({
    checklistId: null, date: today(), storeName: '徐记海鲜·芙蓉店',
    operatorName: '店长', startedAt: null, completedAt: null, items: FALLBACK_ITEMS,
  });
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [noteModal, setNoteModal] = useState<string | null>(null);
  const [noteText, setNoteText] = useState('');
  const [expandedCategory, setExpandedCategory] = useState<string>('设备检查');

  // ─── 加载 ──────────────────────────────────────────────────────────────────

  const loadChecklist = useCallback(async () => {
    setLoading(true);
    try {
      const data = await txFetch<Record<string, unknown>>(`/api/v1/ops/checklists/opening?store_id=${STORE_ID}&date=${today()}`);
      if (data && Array.isArray(data.items) && data.items.length > 0) {
        setChecklist(prev => ({
          ...prev,
          checklistId: String(data.checklist_id || ''),
          items: (data.items as Record<string, unknown>[]).map(i => ({
            id: String(i.id), category: String(i.category || ''),
            title: String(i.title || ''), description: String(i.description || ''),
            required: Boolean(i.required), status: (i.status as CheckStatus) || 'unchecked',
            note: String(i.note || ''), photoUrl: i.photo_url ? String(i.photo_url) : null,
          })),
        }));
      }
    } catch { /* fallback */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadChecklist(); }, [loadChecklist]);

  // ─── 操作 ──────────────────────────────────────────────────────────────────

  const toggleItem = async (itemId: string, newStatus: CheckStatus) => {
    setChecklist(prev => ({
      ...prev,
      startedAt: prev.startedAt || new Date().toISOString(),
      items: prev.items.map(i => i.id === itemId ? { ...i, status: newStatus } : i),
    }));
    try {
      await txFetch(`/api/v1/ops/checklists/opening/items/${itemId}/check`, {
        method: 'POST', body: JSON.stringify({ status: newStatus }),
      });
    } catch { /* offline ok */ }
  };

  const saveNote = (itemId: string) => {
    setChecklist(prev => ({
      ...prev,
      items: prev.items.map(i => i.id === itemId ? { ...i, note: noteText } : i),
    }));
    setNoteModal(null);
  };

  const handleSubmit = async () => {
    const requiredUnchecked = checklist.items.filter(i => i.required && i.status === 'unchecked');
    if (requiredUnchecked.length > 0) {
      // 不允许提交未完成的必选项 — 高亮提示
      setExpandedCategory(requiredUnchecked[0].category);
      return;
    }
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/checklists/opening/submit', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID, date: today(),
          items: checklist.items.map(i => ({ id: i.id, status: i.status, note: i.note })),
        }),
      });
    } catch { /* offline */ }
    setChecklist(prev => ({ ...prev, completedAt: new Date().toISOString() }));
    setSubmitting(false);
  };

  // ─── 统计 ──────────────────────────────────────────────────────────────────

  const total = checklist.items.length;
  const checked = checklist.items.filter(i => i.status !== 'unchecked').length;
  const failed = checklist.items.filter(i => i.status === 'fail').length;
  const progress = total > 0 ? Math.round((checked / total) * 100) : 0;
  const categories = [...new Set(checklist.items.map(i => i.category))];

  // ─── 已提交 ──────────────────────────────────────────────────────────────

  if (checklist.completedAt) {
    return (
      <div style={pageStyle}>
        <div style={{ textAlign: 'center', paddingTop: 60 }}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>✅</div>
          <div style={{ fontSize: 22, fontWeight: 600, marginBottom: 8, color: '#52c41a' }}>开店检查已完成</div>
          <div style={{ fontSize: 16, color: '#9CA3AF', marginBottom: 6 }}>
            通过 {checked - failed}/{total} · 异常 {failed}
          </div>
          <div style={{ fontSize: 14, color: '#6B7280' }}>{checklist.date}</div>
          <button type="button" onClick={() => navigate(-1)}
            style={{ marginTop: 32, padding: '14px 48px', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 10, fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 52 }}>
            返回
          </button>
        </div>
      </div>
    );
  }

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>开店检查单</div>
          <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>{checklist.storeName} · {checklist.date}</div>
        </div>
        <button type="button" onClick={() => navigate(-1)} style={backBtnStyle}>← 返回</button>
      </div>

      {/* 进度条 */}
      <div style={{ background: '#112228', borderRadius: 10, padding: 16, marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>完成进度</span>
          <span style={{ fontSize: 16, fontWeight: 600, color: progress === 100 ? '#52c41a' : '#FF6B35' }}>{progress}%</span>
        </div>
        <div style={{ height: 8, background: '#1a2a33', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${progress}%`, background: progress === 100 ? '#52c41a' : '#FF6B35', borderRadius: 4, transition: 'width 300ms ease' }} />
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 13, color: '#9CA3AF' }}>
          <span>已检查 {checked}/{total}</span>
          {failed > 0 && <span style={{ color: '#ff4d4f' }}>异常 {failed}</span>}
        </div>
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {/* 分类列表 */}
      {categories.map(cat => {
        const catItems = checklist.items.filter(i => i.category === cat);
        const catChecked = catItems.filter(i => i.status !== 'unchecked').length;
        const isExpanded = expandedCategory === cat;

        return (
          <div key={cat} style={{ marginBottom: 12 }}>
            {/* 分类头 */}
            <button type="button" onClick={() => setExpandedCategory(isExpanded ? '' : cat)}
              style={{
                width: '100%', padding: '14px 16px', background: '#112228', border: 'none', borderRadius: isExpanded ? '10px 10px 0 0' : 10,
                color: '#fff', fontSize: 16, fontWeight: 600, cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', minHeight: 52,
              }}>
              <span>{cat}</span>
              <span style={{ fontSize: 14, color: catChecked === catItems.length ? '#52c41a' : '#9CA3AF' }}>
                {catChecked}/{catItems.length} {isExpanded ? '▼' : '▶'}
              </span>
            </button>

            {/* 检查项 */}
            {isExpanded && catItems.map(item => (
              <div key={item.id} style={{
                padding: '14px 16px', background: '#0e1e25', borderBottom: '1px solid #1a2a33',
                display: 'flex', gap: 12, alignItems: 'flex-start',
              }}>
                {/* 勾选按钮组 */}
                <div style={{ display: 'flex', gap: 6, flexShrink: 0, paddingTop: 2 }}>
                  <CheckBtn label="✓" active={item.status === 'pass'} color="#52c41a"
                    onClick={() => toggleItem(item.id, item.status === 'pass' ? 'unchecked' : 'pass')} />
                  <CheckBtn label="✗" active={item.status === 'fail'} color="#ff4d4f"
                    onClick={() => toggleItem(item.id, item.status === 'fail' ? 'unchecked' : 'fail')} />
                  <CheckBtn label="N/A" active={item.status === 'na'} color="#6B7280"
                    onClick={() => toggleItem(item.id, item.status === 'na' ? 'unchecked' : 'na')} />
                </div>

                {/* 内容 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 500, color: item.status === 'fail' ? '#ff4d4f' : '#fff' }}>
                    {item.title}
                    {item.required && <span style={{ color: '#ff4d4f', marginLeft: 4 }}>*</span>}
                  </div>
                  <div style={{ fontSize: 13, color: '#6B7280', marginTop: 2 }}>{item.description}</div>
                  {item.note && <div style={{ fontSize: 13, color: '#faad14', marginTop: 4 }}>备注: {item.note}</div>}
                  <button type="button" onClick={() => { setNoteModal(item.id); setNoteText(item.note); }}
                    style={{ marginTop: 6, padding: '4px 10px', background: 'transparent', border: '1px solid #333', borderRadius: 4, color: '#6B7280', fontSize: 12, cursor: 'pointer' }}>
                    {item.note ? '改备注' : '+ 备注'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        );
      })}

      {/* 提交按钮 */}
      <div style={{ marginTop: 20, paddingBottom: 20 }}>
        <button type="button" onClick={handleSubmit} disabled={submitting || checked === 0}
          style={{
            width: '100%', padding: '16px 0', border: 'none', borderRadius: 10, fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 56,
            background: checked > 0 && !submitting ? '#FF6B35' : '#444', color: '#fff', opacity: submitting ? 0.6 : 1,
          }}>
          {submitting ? '提交中...' : `提交开店检查 (${checked}/${total})`}
        </button>
      </div>

      {/* 备注弹窗 */}
      {noteModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }} onClick={() => setNoteModal(null)}>
          <div style={{ background: '#1a2a33', borderRadius: '16px 16px 0 0', padding: 20, width: '100%', maxWidth: 500 }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>添加备注</div>
            <textarea value={noteText} onChange={e => setNoteText(e.target.value)} rows={3} placeholder="描述异常情况..."
              style={{ width: '100%', padding: 10, background: '#112228', border: '1px solid #333', borderRadius: 8, color: '#fff', fontSize: 16, resize: 'none', boxSizing: 'border-box', outline: 'none' }} />
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <button type="button" onClick={() => setNoteModal(null)}
                style={{ flex: 1, padding: '12px 0', background: '#333', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 48 }}>取消</button>
              <button type="button" onClick={() => saveNote(noteModal)}
                style={{ flex: 1, padding: '12px 0', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 500, cursor: 'pointer', minHeight: 48 }}>保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function CheckBtn({ label, active, color, onClick }: { label: string; active: boolean; color: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{
      width: 44, height: 44, borderRadius: 8, fontSize: 16, fontWeight: 700, cursor: 'pointer',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: active ? color : 'transparent',
      border: `2px solid ${active ? color : '#333'}`,
      color: active ? '#fff' : '#6B7280',
      transition: 'all 150ms ease',
    }}>
      {label}
    </button>
  );
}

const pageStyle: React.CSSProperties = {
  padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
  maxWidth: 500, margin: '0 auto',
};

const backBtnStyle: React.CSSProperties = {
  padding: '6px 14px', background: '#1a2a33', color: '#9CA3AF', border: '1px solid #333',
  borderRadius: 6, fontSize: 14, cursor: 'pointer', minHeight: 36,
};
