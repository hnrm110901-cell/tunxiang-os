/**
 * 快速开店 — 门店配置克隆
 * 选择源门店和目标门店，勾选克隆项，一键复制配置
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { txFetch } from '../../../api';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface StoreOption {
  id: string;
  name: string;
}

interface CloneProgressData {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'partial';
  progress_pct: number;
  completed_items: number;
  total_items: number;
  current_step: string;
  errors: string[];
  started_at: string | null;
  completed_at: string | null;
}

interface CloneHistoryItem {
  id: string;
  source_store_id: string;
  target_store_id: string;
  selected_items: string[] | string;
  status: string;
  progress: number;
  created_by: string | null;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

// ─── 常量 ───────────────────────────────────────────────────────────────────

const CLONE_ITEMS: { value: string; label: string; desc: string }[] = [
  { value: 'menu_config',     label: '菜品分类与菜品', desc: '分类树、菜品档案、BOM配方' },
  { value: 'pricing',         label: '定价与折扣规则', desc: '价格体系、优惠方案' },
  { value: 'roles',           label: '角色权限配置',   desc: '店长/收银/服务员等角色权限' },
  { value: 'print_templates', label: '打印模板',       desc: '小票模板、厨房单模板' },
  { value: 'kds_routes',      label: 'KDS路由规则',    desc: '档口→打印机/KDS映射' },
  { value: 'business_hours',  label: '营业时间',       desc: '每日营业时段、休息日设置' },
  { value: 'thresholds',      label: '经营阈值',       desc: '毛利底线、折扣上限、临期预警' },
];

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  pending:   { label: '等待中', color: '#888',    bg: '#88888822' },
  running:   { label: '进行中', color: '#FF6B35', bg: '#FF6B3522' },
  completed: { label: '完成',   color: '#0F6E56', bg: '#0F6E5622' },
  failed:    { label: '失败',   color: '#FF4D4D', bg: '#FF4D4D22' },
  partial:   { label: '部分成功', color: '#BA7517', bg: '#BA751722' },
};

const POLL_INTERVAL = 1500; // ms

// ─── 工具函数 ───────────────────────────────────────────────────────────────

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('zh-CN', { hour12: false });
}

function parseItems(raw: string[] | string): string[] {
  if (Array.isArray(raw)) return raw;
  try { return JSON.parse(raw); } catch { return []; }
}

// ─── 子组件：门店下拉 ───────────────────────────────────────────────────────

function StoreSelect({
  label,
  value,
  options,
  onChange,
  excludeId,
}: {
  label: string;
  value: string;
  options: StoreOption[];
  onChange: (v: string) => void;
  excludeId?: string;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 6 }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%', padding: '8px 12px', borderRadius: 6,
          border: '1px solid #2a3a44', background: '#0d1e28',
          color: value ? '#fff' : '#888', fontSize: 14, outline: 'none', cursor: 'pointer',
        }}
      >
        <option value="">— 请选择门店 —</option>
        {options
          .filter((s) => s.id !== excludeId)
          .map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
      </select>
    </div>
  );
}

// ─── 子组件：进度面板 ───────────────────────────────────────────────────────

function ProgressPanel({ progress }: { progress: CloneProgressData }) {
  const isTerminal = progress.status === 'completed' || progress.status === 'failed' || progress.status === 'partial';
  const cfg = STATUS_CONFIG[progress.status] || STATUS_CONFIG.pending;

  return (
    <div style={{
      background: '#1a2a33', borderRadius: 10, padding: 20,
      border: `1px solid ${cfg.color}44`, marginTop: 20,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{
          padding: '3px 10px', borderRadius: 12, fontSize: 12,
          background: cfg.bg, color: cfg.color, fontWeight: 600,
        }}>
          {cfg.label}
        </span>
        <span style={{ color: '#aaa', fontSize: 13 }}>{progress.current_step}</span>
      </div>

      {/* 进度条 */}
      <div style={{ height: 8, background: '#0d1e28', borderRadius: 4, overflow: 'hidden', marginBottom: 8 }}>
        <div style={{
          width: `${progress.progress_pct}%`, height: '100%', borderRadius: 4,
          background: progress.status === 'failed' ? '#FF4D4D'
            : progress.status === 'partial' ? '#BA7517' : '#FF6B35',
          transition: 'width 0.4s ease',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#888', fontSize: 12 }}>
        <span>{progress.completed_items} / {progress.total_items} 项</span>
        <span>{progress.progress_pct.toFixed(0)}%</span>
      </div>

      {/* 完成提示 */}
      {progress.status === 'completed' && (
        <div style={{
          marginTop: 16, padding: '10px 14px', borderRadius: 6,
          background: '#0F6E5622', border: '1px solid #0F6E5644',
          color: '#0F6E56', fontSize: 14, fontWeight: 600,
        }}>
          克隆完成！所有配置已成功复制到目标门店。
        </div>
      )}

      {/* 错误列表 */}
      {progress.errors.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ color: '#FF4D4D', fontSize: 12, marginBottom: 6 }}>
            以下项目克隆失败：
          </div>
          {progress.errors.map((e, i) => (
            <div key={i} style={{
              padding: '6px 10px', background: '#FF4D4D11', borderRadius: 4,
              color: '#FF4D4D', fontSize: 12, marginBottom: 4,
            }}>
              {e}
            </div>
          ))}
        </div>
      )}

      {isTerminal && (
        <div style={{ color: '#888', fontSize: 11, marginTop: 12 }}>
          开始：{formatTime(progress.started_at)} &nbsp;·&nbsp; 完成：{formatTime(progress.completed_at)}
        </div>
      )}
    </div>
  );
}

// ─── 子组件：历史记录卡片 ───────────────────────────────────────────────────

function HistoryCard({
  item,
  storeMap,
}: {
  item: CloneHistoryItem;
  storeMap: Record<string, string>;
}) {
  const cfg = STATUS_CONFIG[item.status] || STATUS_CONFIG.pending;
  const items = parseItems(item.selected_items);

  return (
    <div style={{
      background: '#1a2a33', borderRadius: 8, padding: '14px 16px',
      border: '1px solid #2a3a44', marginBottom: 10,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: '#fff', fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
            {storeMap[item.source_store_id] || item.source_store_id.slice(0, 8)}
            <span style={{ color: '#FF6B35', margin: '0 6px' }}>→</span>
            {storeMap[item.target_store_id] || item.target_store_id.slice(0, 8)}
          </div>
          <div style={{ color: '#888', fontSize: 11, marginBottom: 6 }}>
            {formatTime(item.created_at)}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {items.map((v) => (
              <span key={v} style={{
                padding: '1px 7px', borderRadius: 10, fontSize: 10,
                background: '#FF6B3522', color: '#FF6B35',
              }}>
                {CLONE_ITEMS.find((c) => c.value === v)?.label || v}
              </span>
            ))}
          </div>
          {item.error_message && (
            <div style={{ color: '#FF4D4D', fontSize: 11, marginTop: 6 }}>
              {item.error_message}
            </div>
          )}
        </div>
        <span style={{
          padding: '3px 10px', borderRadius: 10, fontSize: 11, whiteSpace: 'nowrap',
          background: cfg.bg, color: cfg.color, marginLeft: 10, flexShrink: 0,
        }}>
          {cfg.label}
        </span>
      </div>
    </div>
  );
}

// ─── 主页面 ─────────────────────────────────────────────────────────────────

export function StoreClonePage() {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [selectedItems, setSelectedItems] = useState<Set<string>>(
    new Set(CLONE_ITEMS.map((c) => c.value))
  );
  const [launching, setLaunching] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState<CloneProgressData | null>(null);
  const [history, setHistory] = useState<CloneHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 加载门店列表 ──
  useEffect(() => {
    txFetch<{ items: StoreOption[] }>('/api/v1/stores').then((res) => {
      setStores(res.items ?? []);
    }).catch(() => {
      // 降级：如果接口不存在则保持空列表，不崩溃
    });
  }, []);

  // ── 加载历史 ──
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await txFetch<{ items: CloneHistoryItem[] }>('/api/v1/store-clone/history');
      setHistory((res.items ?? []).slice(0, 20));
    } catch {
      // 静默失败
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  // ── 轮询进度 ──
  const startPolling = useCallback((taskId: string) => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
      try {
        const data = await txFetch<CloneProgressData>(`/api/v1/store-clone/${taskId}/progress`);
        setProgress(data);
        const isTerminal = ['completed', 'failed', 'partial'].includes(data.status);
        if (isTerminal) {
          clearInterval(pollTimerRef.current!);
          pollTimerRef.current = null;
          loadHistory();
        }
      } catch {
        clearInterval(pollTimerRef.current!);
        pollTimerRef.current = null;
      }
    }, POLL_INTERVAL);
  }, [loadHistory]);

  useEffect(() => () => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  }, []);

  // ── 全选/反选 ──
  const handleToggleAll = () => {
    if (selectedItems.size === CLONE_ITEMS.length) {
      setSelectedItems(new Set());
    } else {
      setSelectedItems(new Set(CLONE_ITEMS.map((c) => c.value)));
    }
  };

  const handleToggleItem = (value: string) => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value); else next.add(value);
      return next;
    });
  };

  // ── 启动克隆 ──
  const handleStartClone = async () => {
    setError('');
    if (!sourceId) { setError('请选择源门店'); return; }
    if (!targetId) { setError('请选择目标门店'); return; }
    if (sourceId === targetId) { setError('源门店和目标门店不能相同'); return; }
    if (selectedItems.size === 0) { setError('请至少选择一个克隆项'); return; }

    setLaunching(true);
    setProgress(null);

    try {
      const res = await txFetch<{ task_id: string; message: string }>('/api/v1/store-clone', {
        method: 'POST',
        body: JSON.stringify({
          source_store_id: sourceId,
          target_store_id: targetId,
          items: Array.from(selectedItems),
          operator_id: '00000000-0000-0000-0000-000000000000', // TODO: 从登录态获取
        }),
      });
      setActiveTaskId(res.task_id);
      startPolling(res.task_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '启动失败，请重试';
      setError(msg);
    } finally {
      setLaunching(false);
    }
  };

  // ── 构建门店 ID→名称 映射（供历史记录展示） ──
  const storeMap = Object.fromEntries(stores.map((s) => [s.id, s.name]));

  const isRunning = progress?.status === 'running' || progress?.status === 'pending';
  const allSelected = selectedItems.size === CLONE_ITEMS.length;

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>快速开店</h2>
        <p style={{ color: '#888', margin: '6px 0 0', fontSize: 13 }}>
          选择源门店和目标门店，勾选克隆项，一键复制配置
        </p>
      </div>

      {/* 主体两栏 */}
      <div style={{ display: 'grid', gridTemplateColumns: '480px 1fr', gap: 24, alignItems: 'start' }}>

        {/* ── 左侧配置区 ── */}
        <div>
          {/* 门店选择卡片 */}
          <div style={{
            background: '#1a2a33', borderRadius: 10, padding: 20,
            border: '1px solid #2a3a44', marginBottom: 16,
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 16, color: '#fff' }}>
              门店选择
            </div>
            <StoreSelect
              label="源门店（复制配置来源）"
              value={sourceId}
              options={stores}
              onChange={setSourceId}
              excludeId={targetId}
            />
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#FF6B35', fontSize: 20, margin: '4px 0 8px',
            }}>
              ↓
            </div>
            <StoreSelect
              label="目标门店（新门店，将被写入配置）"
              value={targetId}
              options={stores}
              onChange={setTargetId}
              excludeId={sourceId}
            />
          </div>

          {/* 克隆项勾选卡片 */}
          <div style={{
            background: '#1a2a33', borderRadius: 10, padding: 20,
            border: '1px solid #2a3a44', marginBottom: 16,
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14,
            }}>
              <span style={{ fontSize: 14, fontWeight: 600 }}>克隆配置项</span>
              <button
                onClick={handleToggleAll}
                style={{
                  padding: '3px 12px', borderRadius: 6, border: '1px solid #2a3a44',
                  background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12,
                }}
              >
                {allSelected ? '全部取消' : '全部选择'}
              </button>
            </div>

            {CLONE_ITEMS.map((item) => {
              const checked = selectedItems.has(item.value);
              return (
                <div
                  key={item.value}
                  onClick={() => handleToggleItem(item.value)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 12px', borderRadius: 6, marginBottom: 6,
                    cursor: 'pointer',
                    background: checked ? '#FF6B3511' : 'transparent',
                    border: `1px solid ${checked ? '#FF6B3533' : '#2a3a44'}`,
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{
                    width: 18, height: 18, borderRadius: 4, flexShrink: 0,
                    border: `2px solid ${checked ? '#FF6B35' : '#2a3a44'}`,
                    background: checked ? '#FF6B35' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {checked && <span style={{ color: '#fff', fontSize: 11, fontWeight: 700 }}>✓</span>}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ color: '#fff', fontSize: 13, fontWeight: 500 }}>{item.label}</div>
                    <div style={{ color: '#888', fontSize: 11, marginTop: 2 }}>{item.desc}</div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 错误提示 */}
          {error && (
            <div style={{
              padding: '10px 14px', borderRadius: 6, marginBottom: 12,
              background: '#FF4D4D22', border: '1px solid #FF4D4D44', color: '#FF4D4D', fontSize: 13,
            }}>
              {error}
            </div>
          )}

          {/* 启动按钮 */}
          <button
            onClick={handleStartClone}
            disabled={launching || isRunning}
            style={{
              width: '100%', padding: '14px 0', borderRadius: 8, border: 'none',
              background: (launching || isRunning) ? '#333' : '#FF6B35',
              color: (launching || isRunning) ? '#888' : '#fff',
              fontSize: 16, fontWeight: 700, cursor: (launching || isRunning) ? 'not-allowed' : 'pointer',
              transition: 'background 0.15s',
            }}
          >
            {launching ? '启动中...' : isRunning ? '克隆进行中...' : '开始克隆'}
          </button>

          {/* 进度面板 */}
          {progress && activeTaskId && (
            <ProgressPanel progress={progress} />
          )}
        </div>

        {/* ── 右侧历史记录 ── */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>克隆历史</span>
            <button
              onClick={loadHistory}
              disabled={historyLoading}
              style={{
                padding: '4px 12px', borderRadius: 6, border: '1px solid #2a3a44',
                background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12,
              }}
            >
              {historyLoading ? '加载中...' : '刷新'}
            </button>
          </div>

          {history.length === 0 && !historyLoading && (
            <div style={{
              background: '#1a2a33', borderRadius: 10, padding: 40,
              border: '1px solid #2a3a44', textAlign: 'center', color: '#888', fontSize: 13,
            }}>
              暂无克隆记录
            </div>
          )}

          {history.map((item) => (
            <HistoryCard key={item.id} item={item} storeMap={storeMap} />
          ))}
        </div>
      </div>
    </div>
  );
}
