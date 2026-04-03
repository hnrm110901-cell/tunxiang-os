/**
 * 转台/并台 页面
 * 转台: 选源桌 → 选目标桌 → 确认
 * 并台: 多选桌台 → 选主桌 → 确认
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect } from 'react';
import { fetchTables, transferTable, mergeTables, TableInfo } from '../api/tablesApi';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
  info: '#185FA5',
};

type Mode = 'transfer' | 'merge';
type Step = 'select-source' | 'select-target' | 'confirm';

/* ---------- 组件 ---------- */
const storeId = (window as any).__STORE_ID__ || 'store_001';

export function TableOpsPage() {
  const [mode, setMode] = useState<Mode>('transfer');
  const [step, setStep] = useState<Step>('select-source');
  const [sourceTable, setSourceTable] = useState<string | null>(null);
  const [targetTable, setTargetTable] = useState<string | null>(null);
  // 并台模式
  const [mergeSelection, setMergeSelection] = useState<string[]>([]);
  const [mainTable, setMainTable] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [done, setDone] = useState(false);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTables(storeId).then(res => {
      setTables(res.items);
    }).catch((err: unknown) => {
      console.error(err);
      setError('桌台数据加载失败');
    }).finally(() => setLoading(false));
  }, []);

  const occupied = tables.filter(t => t.status === 'occupied');
  const idle = tables.filter(t => t.status === 'idle');

  const reset = () => {
    setStep('select-source');
    setSourceTable(null);
    setTargetTable(null);
    setMergeSelection([]);
    setMainTable(null);
    setDone(false);
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    reset();
  };

  /* ---- 转台逻辑 ---- */
  const handleSelectSource = (no: string) => {
    setSourceTable(no);
    setStep('select-target');
  };

  const handleSelectTarget = (no: string) => {
    setTargetTable(no);
    setStep('confirm');
  };

  const handleConfirmTransfer = async () => {
    if (!sourceTable || !targetTable) return;
    setProcessing(true);
    setError(null);
    try {
      await transferTable(storeId, sourceTable, targetTable);
      setDone(true);
    } catch (err: unknown) {
      console.error(err);
      setError('转台失败，请重试');
    } finally {
      setProcessing(false);
    }
  };

  /* ---- 并台逻辑 ---- */
  const toggleMergeSelect = (no: string) => {
    setMergeSelection(prev =>
      prev.includes(no) ? prev.filter(n => n !== no) : [...prev, no]
    );
  };

  const handleConfirmMerge = async () => {
    if (!mainTable) return;
    setProcessing(true);
    setError(null);
    try {
      await mergeTables(storeId, mainTable, mergeSelection);
      setDone(true);
    } catch (err: unknown) {
      console.error(err);
      setError('并台失败，请重试');
    } finally {
      setProcessing(false);
    }
  };

  /* ---- 渲染桌台按钮 ---- */
  const renderTableBtn = (
    t: TableInfo,
    opts: {
      selected?: boolean;
      disabled?: boolean;
      onPress: () => void;
    },
  ) => (
    <button
      key={t.table_no}
      onClick={opts.onPress}
      disabled={opts.disabled}
      style={{
        minHeight: 72, padding: 12, borderRadius: 12,
        background: opts.selected ? `${C.accent}22` : C.card,
        border: opts.selected ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
        color: C.white, cursor: opts.disabled ? 'not-allowed' : 'pointer',
        opacity: opts.disabled ? 0.4 : 1,
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 20, fontWeight: 700 }}>{t.table_no}</div>
      <div style={{ fontSize: 16, color: t.status === 'occupied' ? C.accent : C.green, marginTop: 4 }}>
        {t.status === 'occupied' ? `${t.guest_count}人` : '空闲'}
      </div>
    </button>
  );

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
        桌台操作
      </h1>

      {loading && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          加载中...
        </div>
      )}

      {error && (
        <div style={{
          background: `${C.danger}22`, border: `1px solid ${C.danger}`,
          borderRadius: 12, padding: 12, marginBottom: 16,
          color: '#ff9999', fontSize: 16, textAlign: 'center',
        }}>
          {error}
        </div>
      )}

      {!loading && (
      <>

      {/* 模式切换 */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 20, borderRadius: 12, overflow: 'hidden' }}>
        {(['transfer', 'merge'] as Mode[]).map(m => (
          <button
            key={m}
            onClick={() => switchMode(m)}
            style={{
              flex: 1, minHeight: 48, border: 'none',
              background: mode === m ? C.accent : C.card,
              color: mode === m ? C.white : C.muted,
              fontSize: 18, fontWeight: mode === m ? 700 : 400,
              cursor: 'pointer',
            }}
          >
            {m === 'transfer' ? '转台' : '并台'}
          </button>
        ))}
      </div>

      {/* 完成状态 */}
      {done && (
        <div style={{
          background: `${C.green}22`, border: `1px solid ${C.green}`,
          borderRadius: 12, padding: 20, textAlign: 'center', marginBottom: 20,
        }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>OK</div>
          <div style={{ fontSize: 18, color: C.green, fontWeight: 700, marginBottom: 16 }}>
            {mode === 'transfer' ? '转台成功' : '并台成功'}
          </div>
          <div style={{ fontSize: 16, color: C.text, marginBottom: 16 }}>
            {mode === 'transfer'
              ? `${sourceTable} \u2192 ${targetTable}`
              : `主桌 ${mainTable}，合并 ${mergeSelection.filter(n => n !== mainTable).join(', ')}`
            }
          </div>
          <button
            onClick={reset}
            style={{
              minHeight: 48, padding: '10px 24px', borderRadius: 12,
              background: C.accent, color: C.white, border: 'none',
              fontSize: 16, fontWeight: 700, cursor: 'pointer',
            }}
          >
            继续操作
          </button>
        </div>
      )}

      {/* ========== 转台模式 ========== */}
      {mode === 'transfer' && !done && (
        <>
          {step === 'select-source' && (
            <>
              <h2 style={{ fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 10px' }}>
                第1步: 选择要转出的桌台
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                {occupied.map(t => renderTableBtn(t, {
                  selected: false,
                  onPress: () => handleSelectSource(t.table_no),
                }))}
              </div>
              {occupied.length === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
                  暂无就餐中的桌台
                </div>
              )}
            </>
          )}

          {step === 'select-target' && (
            <>
              <div style={{
                background: C.card, borderRadius: 12, padding: 14, marginBottom: 16,
                border: `1px solid ${C.border}`,
              }}>
                <span style={{ fontSize: 16, color: C.muted }}>转出桌: </span>
                <span style={{ fontSize: 18, fontWeight: 700, color: C.accent }}>{sourceTable}</span>
                <button
                  onClick={() => { setStep('select-source'); setSourceTable(null); }}
                  style={{
                    float: 'right', minHeight: 48, padding: '8px 12px',
                    borderRadius: 8, background: 'transparent',
                    border: `1px solid ${C.muted}`, color: C.muted,
                    fontSize: 16, cursor: 'pointer',
                  }}
                >
                  重选
                </button>
              </div>
              <h2 style={{ fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 10px' }}>
                第2步: 选择目标空桌
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                {idle.map(t => renderTableBtn(t, {
                  selected: false,
                  onPress: () => handleSelectTarget(t.table_no),
                }))}
              </div>
              {idle.length === 0 && (
                <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
                  暂无空闲桌台
                </div>
              )}
            </>
          )}

          {step === 'confirm' && (
            <div style={{ textAlign: 'center', padding: 20 }}>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>确认转台</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: C.white, marginBottom: 20 }}>
                <span style={{ color: C.accent }}>{sourceTable}</span>
                {' \u2192 '}
                <span style={{ color: C.green }}>{targetTable}</span>
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <button
                  onClick={() => { setStep('select-source'); setSourceTable(null); setTargetTable(null); }}
                  style={{
                    flex: 1, minHeight: 56, borderRadius: 12,
                    background: C.card, border: `1px solid ${C.border}`,
                    color: C.text, fontSize: 18, cursor: 'pointer',
                  }}
                >
                  取消
                </button>
                <button
                  onClick={handleConfirmTransfer}
                  disabled={processing}
                  style={{
                    flex: 1, minHeight: 56, borderRadius: 12,
                    background: processing ? C.muted : C.accent,
                    color: C.white, border: 'none', fontSize: 18, fontWeight: 700,
                    cursor: processing ? 'not-allowed' : 'pointer',
                  }}
                >
                  {processing ? '处理中...' : '确认转台'}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ========== 并台模式 ========== */}
      {mode === 'merge' && !done && (
        <>
          {!mainTable ? (
            <>
              <h2 style={{ fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 10px' }}>
                第1步: 选择要合并的桌台（至少2桌）
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 16 }}>
                {occupied.map(t => renderTableBtn(t, {
                  selected: mergeSelection.includes(t.table_no),
                  onPress: () => toggleMergeSelect(t.table_no),
                }))}
              </div>
              {mergeSelection.length >= 2 && (
                <>
                  <h2 style={{ fontSize: 17, fontWeight: 600, color: C.text, margin: '0 0 10px' }}>
                    第2步: 选择主桌（订单合并到此桌）
                  </h2>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 16 }}>
                    {mergeSelection.map(no => {
                      const t = tables.find(tb => tb.table_no === no)!;
                      return renderTableBtn(t, {
                        selected: false,
                        onPress: () => setMainTable(no),
                      });
                    })}
                  </div>
                </>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 20 }}>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>确认并台</div>
              <div style={{ fontSize: 18, color: C.white, marginBottom: 8 }}>
                主桌: <span style={{ fontWeight: 700, color: C.accent }}>{mainTable}</span>
              </div>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 20 }}>
                合并: {mergeSelection.filter(n => n !== mainTable).join(', ')}
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <button
                  onClick={() => setMainTable(null)}
                  style={{
                    flex: 1, minHeight: 56, borderRadius: 12,
                    background: C.card, border: `1px solid ${C.border}`,
                    color: C.text, fontSize: 18, cursor: 'pointer',
                  }}
                >
                  取消
                </button>
                <button
                  onClick={handleConfirmMerge}
                  disabled={processing}
                  style={{
                    flex: 1, minHeight: 56, borderRadius: 12,
                    background: processing ? C.muted : C.accent,
                    color: C.white, border: 'none', fontSize: 18, fontWeight: 700,
                    cursor: processing ? 'not-allowed' : 'pointer',
                  }}
                >
                  {processing ? '处理中...' : '确认并台'}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      </> /* end !loading */
      )}
    </div>
  );
}
