/**
 * SwimLaneBoard — 泳道模式看板
 *
 * 适用场景：多工序厨房（切配→烹饪→装盘→传菜）
 *
 * 布局：
 *   每列 = 一道工序
 *   每格 = 处于该工序的任务卡片
 *   点击"推进"完成当前工序，任务自动流入下一列
 *
 * 颜色约定（按工序状态）：
 *   pending     → 灰色（等待进入）
 *   in_progress → 蓝色（正在执行）
 *   done        → 绿色（已完成）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface ProductionStep {
  step_id: string;
  step_name: string;
  step_order: number;
  color: string;
}

interface TaskStepCard {
  task_step_id: string;
  task_id: string;
  status: 'pending' | 'in_progress' | 'done' | 'skipped';
  operator_id: string | null;
  started_at: string | null;
  table_no?: string;
  dish_name?: string;
}

interface SwimLaneData {
  steps: ProductionStep[];
  lanes: Record<string, TaskStepCard[]>;
}

// ─── Constants ───

const API_BASE = (window as any).__STORE_API_BASE__ || '';
const TENANT_ID = (window as any).__TENANT_ID__ || '';
const DEPT_ID = (window as any).__KDS_DEPT_ID__ || '';
const OPERATOR_ID = (window as any).__OPERATOR_ID__ || '';
const REFRESH_MS = 15_000;

const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  pending:     { bg: '#1C1C1E', border: '#3A3A3C', text: '#8E8E93' },
  in_progress: { bg: '#0A2540', border: '#1A6CF0', text: '#FFFFFF' },
  done:        { bg: '#0A2218', border: '#30D158', text: '#30D158' },
  skipped:     { bg: '#1C1C1E', border: '#3A3A3C', text: '#636366' },
};

// ─── Sub-components ───

function StepHeader({ step, count }: { step: ProductionStep; count: number }) {
  return (
    <div
      style={{
        padding: '12px 16px',
        borderBottom: `3px solid ${step.color}`,
        background: '#111',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}
    >
      <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
        {step.step_name}
      </span>
      {count > 0 && (
        <span
          style={{
            background: step.color,
            color: '#000',
            borderRadius: 10,
            padding: '2px 8px',
            fontSize: 14,
            fontWeight: 700,
          }}
        >
          {count}
        </span>
      )}
    </div>
  );
}

function TaskCard({
  card,
  stepId,
  stepColor,
  onAdvance,
}: {
  card: TaskStepCard;
  stepId: string;
  stepColor: string;
  onAdvance: (taskId: string, stepId: string) => void;
}) {
  const style = STATUS_COLORS[card.status] ?? STATUS_COLORS.pending;
  const isActive = card.status === 'in_progress';

  return (
    <div
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        borderRadius: 12,
        padding: 14,
        marginBottom: 10,
        minHeight: 80,
      }}
    >
      {/* 菜名 + 桌号 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
          {card.dish_name || '—'}
        </span>
        <span
          style={{
            fontSize: 16,
            color: '#FF6B35',
            fontWeight: 700,
            background: '#2A1A0E',
            borderRadius: 6,
            padding: '2px 8px',
          }}
        >
          {card.table_no || '—'}
        </span>
      </div>

      {/* 开始时间 */}
      {card.started_at && (
        <div style={{ fontSize: 13, color: '#8E8E93', marginBottom: 10 }}>
          {new Date(card.started_at).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })} 开始
        </div>
      )}

      {/* 推进按钮（仅 in_progress 可操作） */}
      {isActive && (
        <button
          onClick={() => onAdvance(card.task_id, stepId)}
          style={{
            width: '100%',
            minHeight: 48,
            background: stepColor,
            color: '#000',
            border: 'none',
            borderRadius: 8,
            fontSize: 16,
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'transform 0.15s',
            active: { transform: 'scale(0.97)' },
          } as React.CSSProperties}
        >
          完成此工序 →
        </button>
      )}

      {card.status === 'done' && (
        <div
          style={{
            textAlign: 'center',
            color: '#30D158',
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          ✓ 已完成
        </div>
      )}
    </div>
  );
}

// ─── Main ───

export function SwimLaneBoard() {
  const [data, setData] = useState<SwimLaneData | null>(null);
  const [loading, setLoading] = useState(true);
  const [advancing, setAdvancing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchBoard = useCallback(async () => {
    if (!DEPT_ID) {
      // mock 数据
      setData({
        steps: [
          { step_id: 's1', step_name: '切配', step_order: 1, color: '#FF9F0A' },
          { step_id: 's2', step_name: '烹饪', step_order: 2, color: '#FF6B35' },
          { step_id: 's3', step_name: '装盘', step_order: 3, color: '#30D158' },
          { step_id: 's4', step_name: '传菜', step_order: 4, color: '#64D2FF' },
        ],
        lanes: {
          s1: [
            { task_step_id: 'ts1', task_id: 't1', status: 'in_progress', operator_id: null, started_at: new Date().toISOString(), table_no: 'A03', dish_name: '剁椒鱼头' },
            { task_step_id: 'ts2', task_id: 't2', status: 'in_progress', operator_id: null, started_at: new Date().toISOString(), table_no: 'B05', dish_name: '烤羊腿' },
          ],
          s2: [
            { task_step_id: 'ts3', task_id: 't3', status: 'in_progress', operator_id: null, started_at: new Date(Date.now() - 180000).toISOString(), table_no: 'C01', dish_name: '清蒸鲈鱼' },
          ],
          s3: [],
          s4: [],
        },
      });
      setLoading(false);
      return;
    }

    try {
      const res = await txFetch(
        `${API_BASE}/api/v1/kds/swimlane/board?dept_id=${encodeURIComponent(DEPT_ID)}`,
        undefined,
        TENANT_ID,
      );
      if (res.ok) {
        setData(res.data as SwimLaneData);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBoard();
    timerRef.current = setInterval(fetchBoard, REFRESH_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchBoard]);

  const handleAdvance = useCallback(async (taskId: string, stepId: string) => {
    setAdvancing(`${taskId}-${stepId}`);
    try {
      await txFetch(
        `${API_BASE}/api/v1/kds/swimlane/tasks/${encodeURIComponent(taskId)}/advance`,
        {
          method: 'POST',
          body: JSON.stringify({ step_id: stepId, operator_id: OPERATOR_ID || null }),
        },
        TENANT_ID,
      );
      await fetchBoard();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '推进失败');
    } finally {
      setAdvancing(null);
    }
  }, [fetchBoard]);

  if (loading) {
    return (
      <div style={{ background: '#000', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: '#888', fontSize: 20 }}>加载泳道数据…</span>
      </div>
    );
  }

  const steps = data?.steps ?? [];
  const lanes = data?.lanes ?? {};

  return (
    <div
      style={{
        background: '#0B0B0B',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'Noto Sans SC, sans-serif',
        color: '#E0E0E0',
      }}
    >
      {/* 标题栏 */}
      <header
        style={{
          background: '#111',
          padding: '12px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          borderBottom: '1px solid #222',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>
          生产动线 · 泳道模式
        </span>
        <span style={{ fontSize: 14, color: '#666' }}>
          {steps.length} 道工序
        </span>
        {error && (
          <span style={{ color: '#FF3B30', fontSize: 14 }}>{error}</span>
        )}
      </header>

      {/* 泳道主体 */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          overflow: 'hidden',
          gap: 2,
        }}
      >
        {steps.length === 0 ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#444',
            }}
          >
            <div style={{ fontSize: 48, marginBottom: 16 }}>⚙</div>
            <div style={{ fontSize: 18 }}>尚未配置工序步骤</div>
            <div style={{ fontSize: 14, marginTop: 8, color: '#333' }}>
              请在管理后台 → 档口设置 → 工序配置中添加工序
            </div>
          </div>
        ) : (
          steps.map((step) => {
            const cards = lanes[step.step_id] ?? [];
            return (
              <div
                key={step.step_id}
                style={{
                  flex: 1,
                  minWidth: 240,
                  display: 'flex',
                  flexDirection: 'column',
                  background: '#0D0D0D',
                  overflow: 'hidden',
                }}
              >
                <StepHeader step={step} count={cards.length} />
                <div
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: 12,
                    WebkitOverflowScrolling: 'touch',
                  }}
                >
                  {cards.length === 0 ? (
                    <div
                      style={{
                        textAlign: 'center',
                        padding: '40px 16px',
                        color: '#333',
                        fontSize: 14,
                      }}
                    >
                      暂无任务
                    </div>
                  ) : (
                    cards.map((card) => (
                      <TaskCard
                        key={card.task_step_id}
                        card={card}
                        stepId={step.step_id}
                        stepColor={step.color}
                        onAdvance={
                          advancing ? () => {} : handleAdvance
                        }
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
