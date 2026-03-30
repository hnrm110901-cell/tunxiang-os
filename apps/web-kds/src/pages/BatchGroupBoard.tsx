/**
 * 批次合并视图 — 切配/打荷岗位专用屏
 *
 * 将同档口多桌同款菜合并为批次视图，方便厨师按批次操作。
 * 仅在 dept_type='prep'（切配）或'assemble'（打荷）时展示。
 *
 * 数据流：GET /api/v1/kds-analytics/batched-queue/{dept_id}?store_id=...
 */
import { useEffect, useState, useCallback } from 'react';

// ── 类型定义 ─────────────────────────────────────────────────

interface BatchGroup {
  dish_id: string;
  dish_name: string;
  total_qty: number;
  base_qty: number;
  batch_count: number;
  remainder: number;
  table_list: string[];
  task_ids: string[];
}

type DeptType = 'prep' | 'assemble' | 'hot' | 'cold' | 'main' | string;

interface BatchGroupBoardProps {
  deptId: string;
  storeId: string;
  deptType: DeptType;
  tenantId: string;
  onSwitchToDetail?: () => void;
  /** 一键完成该菜所有工单的回调（传入 task_ids） */
  onCompleteAll?: (taskIds: string[], dishName: string) => Promise<void>;
}

// ── 样式常量 ─────────────────────────────────────────────────

const S = {
  root: {
    background: '#0B1A20',
    minHeight: '100vh',
    color: '#E0E0E0',
    fontFamily: 'Noto Sans SC, sans-serif',
    padding: 16,
  } as React.CSSProperties,
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
  } as React.CSSProperties,
  title: {
    fontSize: 26,
    fontWeight: 'bold',
    color: '#fff',
    margin: 0,
  } as React.CSSProperties,
  switchBtn: {
    padding: '8px 18px',
    background: 'transparent',
    border: '1px solid #8899A6',
    borderRadius: 8,
    color: '#8899A6',
    fontSize: 14,
    cursor: 'pointer',
  } as React.CSSProperties,
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: 14,
  } as React.CSSProperties,
  card: {
    background: '#112B36',
    borderRadius: 10,
    padding: 18,
    borderTop: '4px solid #1890ff',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  } as React.CSSProperties,
  dishName: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#fff',
    margin: 0,
  } as React.CSSProperties,
  batchRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
  } as React.CSSProperties,
  batchLabel: {
    fontSize: 16,
    color: '#8899A6',
  } as React.CSSProperties,
  batchCount: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#52c41a',
    fontFamily: 'JetBrains Mono, monospace',
  } as React.CSSProperties,
  batchUnit: {
    fontSize: 16,
    color: '#E0C97F',
  } as React.CSSProperties,
  remainder: {
    fontSize: 15,
    color: '#faad14',
  } as React.CSSProperties,
  tableRow: {
    fontSize: 13,
    color: '#8899A6',
  } as React.CSSProperties,
  completeBtn: {
    marginTop: 4,
    padding: '10px 0',
    background: '#52c41a',
    border: 'none',
    borderRadius: 8,
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    cursor: 'pointer',
    width: '100%',
  } as React.CSSProperties,
  emptyTip: {
    textAlign: 'center',
    color: '#8899A6',
    fontSize: 18,
    marginTop: 80,
  } as React.CSSProperties,
  notSupported: {
    textAlign: 'center',
    color: '#ff4d4f',
    fontSize: 18,
    marginTop: 80,
  } as React.CSSProperties,
  loadingTip: {
    textAlign: 'center',
    color: '#8899A6',
    fontSize: 16,
    marginTop: 60,
  } as React.CSSProperties,
  errorTip: {
    textAlign: 'center',
    color: '#ff4d4f',
    fontSize: 15,
    marginTop: 60,
  } as React.CSSProperties,
};

// ── 主组件 ───────────────────────────────────────────────────

export function BatchGroupBoard({
  deptId,
  storeId,
  deptType,
  tenantId,
  onSwitchToDetail,
  onCompleteAll,
}: BatchGroupBoardProps) {
  const [groups, setGroups] = useState<BatchGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completingId, setCompletingId] = useState<string | null>(null);

  // 仅切配/打荷档口支持此视图
  const isSupported = deptType === 'prep' || deptType === 'assemble';

  const fetchGroups = useCallback(async () => {
    if (!isSupported) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/kds-analytics/batched-queue/${deptId}?store_id=${storeId}`,
        { headers: { 'X-Tenant-ID': tenantId } }
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: BatchGroup[] = await res.json();
      setGroups(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [deptId, storeId, tenantId, isSupported]);

  // 首次加载 + 30秒自动刷新
  useEffect(() => {
    fetchGroups();
    const timer = setInterval(fetchGroups, 30_000);
    return () => clearInterval(timer);
  }, [fetchGroups]);

  const handleCompleteAll = async (group: BatchGroup) => {
    if (!onCompleteAll || completingId === group.dish_id) return;
    setCompletingId(group.dish_id);
    try {
      await onCompleteAll(group.task_ids, group.dish_name);
      // 完成后刷新
      await fetchGroups();
    } finally {
      setCompletingId(null);
    }
  };

  if (!isSupported) {
    return (
      <div style={S.root}>
        <p style={S.notSupported}>此视图仅适用于切配（prep）或打荷（assemble）档口</p>
      </div>
    );
  }

  return (
    <div style={S.root}>
      {/* 标题栏 */}
      <div style={S.header}>
        <h1 style={S.title}>批次合并视图</h1>
        <button style={S.switchBtn} onClick={onSwitchToDetail}>
          切换至明细视图
        </button>
      </div>

      {/* 状态提示 */}
      {loading && <p style={S.loadingTip}>加载中...</p>}
      {error && <p style={S.errorTip}>加载失败：{error}</p>}

      {/* 批次卡片网格 */}
      {!loading && !error && groups.length === 0 && (
        <p style={S.emptyTip}>当前档口无待制作工单</p>
      )}

      {!loading && groups.length > 0 && (
        <div style={S.grid}>
          {groups.map((g) => (
            <DishCard
              key={g.dish_id}
              group={g}
              completing={completingId === g.dish_id}
              onCompleteAll={onCompleteAll ? () => handleCompleteAll(g) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 菜品批次卡片 ─────────────────────────────────────────────

interface DishCardProps {
  group: BatchGroup;
  completing: boolean;
  onCompleteAll?: () => void;
}

function DishCard({ group, completing, onCompleteAll }: DishCardProps) {
  const { dish_name, batch_count, base_qty, remainder, table_list, total_qty } = group;

  return (
    <div style={S.card}>
      {/* 菜名 */}
      <p style={S.dishName}>{dish_name}</p>

      {/* 批次数量 */}
      <div style={S.batchRow}>
        <span style={S.batchLabel}>本批：</span>
        <span style={S.batchCount}>{batch_count}</span>
        <span style={S.batchUnit}>批 × {base_qty} 份</span>
      </div>

      {/* 余量 */}
      {remainder > 0 && (
        <div>
          <span style={S.remainder}>余：{remainder} 份</span>
        </div>
      )}

      {/* 合计 */}
      <div style={{ fontSize: 13, color: '#8899A6' }}>
        合计 {total_qty} 份
      </div>

      {/* 涉及桌台 */}
      {table_list.length > 0 && (
        <div style={S.tableRow}>
          桌台：{table_list.join(' / ')}
        </div>
      )}

      {/* 全部完成按钮 */}
      {onCompleteAll && (
        <button
          style={{
            ...S.completeBtn,
            opacity: completing ? 0.6 : 1,
            cursor: completing ? 'not-allowed' : 'pointer',
          }}
          onClick={completing ? undefined : onCompleteAll}
          disabled={completing}
        >
          {completing ? '处理中...' : '全部完成'}
        </button>
      )}
    </div>
  );
}
