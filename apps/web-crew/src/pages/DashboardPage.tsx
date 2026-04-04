/**
 * DashboardPage - 服务员工作台首页
 * 快捷入口 + 今日业绩 + 待办提醒（15s刷新）
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 类型 ---------- */
interface TodoItem {
  id: string;
  type: 'rush' | 'add' | 'call' | 'clear';
  table: string;
  content: string;
  time: string;           // 相对时间如 "2分钟前"
  createdAt: number;      // 时间戳
}

interface DailyStats {
  tables: number;
  recommended: number;
  tips: number;
  rating: number;
}

/* ---------- 常量 ---------- */
const REFRESH_MS = 15_000;

const TODO_COLORS: Record<TodoItem['type'], string> = {
  rush:  '#EF4444',
  add:   '#F97316',
  call:  '#3B82F6',
  clear: '#6B7280',
};

const TODO_LABELS: Record<TodoItem['type'], string> = {
  rush:  '催菜',
  add:   '加菜请求',
  call:  '呼叫服务',
  clear: '清台提醒',
};

const SHORTCUTS = [
  { label: '扫码点餐', icon: 'S', path: '/order',       badgeKey: null },
  { label: '催菜处理', icon: 'R', path: '/rush-order',   badgeKey: 'rush' as const },
  { label: '巡台检查', icon: 'X', path: '/patrol',       badgeKey: null },
  { label: '加菜记录', icon: 'J', path: '/add-history',  badgeKey: null },
  { label: '桌台状态', icon: 'Z', path: '/tables',       badgeKey: null },
  { label: '交班报告', icon: 'B', path: '/shift-handover', badgeKey: null },
] as const;

/* ---------- mock 数据（后续接 API） ---------- */
function mockTodos(): TodoItem[] {
  const types: TodoItem['type'][] = ['rush', 'add', 'call', 'clear'];
  const tables = ['A3', 'B5', 'C1', 'A7', 'B2', 'D4'];
  const contents = ['红烧肉催第2次', '加一份蒜蓉西兰花', '客人呼叫加水', '客人已离店待清台', '鱼头汤催菜', '需要纸巾'];
  const now = Date.now();
  return Array.from({ length: 4 + Math.floor(Math.random() * 3) }, (_, i) => ({
    id: `todo-${i}-${now}`,
    type: types[i % types.length],
    table: tables[i % tables.length],
    content: contents[i % contents.length],
    time: `${1 + Math.floor(Math.random() * 10)}分钟前`,
    createdAt: now - i * 60_000,
  }));
}

function mockStats(): DailyStats {
  return { tables: 12, recommended: 8, tips: 35, rating: 4.8 };
}

/* ---------- 组件 ---------- */
export function DashboardPage() {
  const nav = useNavigate();
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [stats, setStats] = useState<DailyStats>(mockStats);
  const [rushCount, setRushCount] = useState(0);

  const refresh = useCallback(() => {
    const items = mockTodos();
    setTodos(items);
    setRushCount(items.filter(t => t.type === 'rush').length);
    setStats(mockStats());
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleTap = (path: string) => {
    try { navigator.vibrate(50); } catch (_e) { /* 不支持振动 */ }
    nav(path);
  };

  const handleDone = (id: string) => {
    try { navigator.vibrate(50); } catch (_e) { /* 不支持振动 */ }
    setTodos(prev => prev.filter(t => t.id !== id));
  };

  return (
    <div style={{ padding: '16px 12px 80px', maxWidth: 480, margin: '0 auto' }}>
      {/* 顶部信息栏 */}
      <div style={{
        background: '#112228', borderRadius: 12, padding: '16px 18px',
        marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>李小明</div>
          <div style={{ fontSize: 16, color: '#94a3b8', marginTop: 4 }}>早班 08:00-16:00</div>
        </div>
        <div style={{
          background: 'rgba(255,107,53,0.15)', borderRadius: 8, padding: '8px 14px',
          fontSize: 16, color: '#FF6B35', fontWeight: 600,
        }}>
          已工作 3h 42m
        </div>
      </div>

      {/* 快捷入口 2x3 */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 16,
      }}>
        {SHORTCUTS.map(s => (
          <button
            key={s.label}
            onClick={() => handleTap(s.path)}
            style={{
              position: 'relative', background: '#112228', border: 'none', borderRadius: 12,
              padding: '18px 8px', display: 'flex', flexDirection: 'column',
              alignItems: 'center', gap: 8, cursor: 'pointer', minHeight: 88,
              justifyContent: 'center',
            }}
          >
            <span style={{
              width: 40, height: 40, borderRadius: 10,
              background: 'rgba(255,107,53,0.15)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              fontSize: 18, fontWeight: 700, color: '#FF6B35',
            }}>
              {s.icon}
            </span>
            <span style={{ fontSize: 16, color: '#e2e8f0', fontWeight: 500 }}>{s.label}</span>
            {s.badgeKey === 'rush' && rushCount > 0 && (
              <span style={{
                position: 'absolute', top: 6, right: 6, background: '#EF4444',
                color: '#fff', fontSize: 12, fontWeight: 700, borderRadius: 10,
                minWidth: 20, height: 20, display: 'flex', alignItems: 'center',
                justifyContent: 'center', padding: '0 5px',
              }}>
                {rushCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* 今日业绩卡 */}
      <div style={{
        background: '#112228', borderRadius: 12, padding: 16, marginBottom: 16,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: '#94a3b8' }}>今日业绩</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8 }}>
          {([
            { label: '服务桌数', value: String(stats.tables) },
            { label: '推荐菜品', value: String(stats.recommended) },
            { label: '获得小费', value: `${stats.tips}` },
            { label: '顾客评分', value: String(stats.rating) },
          ] as const).map(item => (
            <div key={item.label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#FF6B35' }}>{item.value}</div>
              <div style={{ fontSize: 14, color: '#64748b', marginTop: 2 }}>{item.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 待办提醒列表 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{
          fontSize: 16, fontWeight: 600, color: '#94a3b8', marginBottom: 10,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>待办提醒</span>
          <span style={{ fontSize: 14, color: '#475569' }}>15s 刷新</span>
        </div>
        {todos.length === 0 && (
          <div style={{
            background: '#112228', borderRadius: 12, padding: 24, textAlign: 'center',
            color: '#475569', fontSize: 16,
          }}>
            暂无待办事项
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {todos.map(item => (
            <div key={item.id} style={{
              background: '#112228', borderRadius: 12, padding: '12px 14px',
              borderLeft: `4px solid ${TODO_COLORS[item.type]}`,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{
                    fontSize: 12, fontWeight: 600, color: TODO_COLORS[item.type],
                    background: `${TODO_COLORS[item.type]}22`, borderRadius: 4,
                    padding: '2px 6px',
                  }}>
                    {TODO_LABELS[item.type]}
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 700 }}>{item.table}桌</span>
                </div>
                <div style={{ fontSize: 16, color: '#94a3b8' }}>{item.content}</div>
                <div style={{ fontSize: 14, color: '#475569', marginTop: 2 }}>{item.time}</div>
              </div>
              <button
                onClick={() => handleDone(item.id)}
                style={{
                  background: '#FF6B35', border: 'none', borderRadius: 8,
                  color: '#fff', fontSize: 16, fontWeight: 600,
                  padding: '10px 16px', cursor: 'pointer',
                  minWidth: 48, minHeight: 48,
                }}
              >
                处理
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
