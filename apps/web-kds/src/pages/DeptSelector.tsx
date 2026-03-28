/**
 * DeptSelector — 档口选择页面
 *
 * 档口列表（楼面/吧台/凉菜/蒸菜/炒炉等）
 * 选择后只显示本档口任务
 * 档口负载指示器（绿/黄/红）
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 */
import { useState, useEffect } from 'react';

// ─── Types ───

interface Department {
  id: string;
  name: string;
  icon: string;
  pendingCount: number;
  cookingCount: number;
  avgWaitMin: number;
  status: 'online' | 'offline';
}

// ─── Mock Data ───

const MOCK_DEPTS: Department[] = [
  { id: 'hot', name: '炒炉', icon: '🔥', pendingCount: 8, cookingCount: 4, avgWaitMin: 14, status: 'online' },
  { id: 'cold', name: '凉菜', icon: '🥗', pendingCount: 3, cookingCount: 1, avgWaitMin: 5, status: 'online' },
  { id: 'steam', name: '蒸菜', icon: '♨️', pendingCount: 5, cookingCount: 3, avgWaitMin: 22, status: 'online' },
  { id: 'bar', name: '吧台', icon: '🍹', pendingCount: 2, cookingCount: 1, avgWaitMin: 3, status: 'online' },
  { id: 'floor', name: '楼面', icon: '🍽️', pendingCount: 0, cookingCount: 0, avgWaitMin: 0, status: 'online' },
  { id: 'staple', name: '主食', icon: '🍚', pendingCount: 6, cookingCount: 2, avgWaitMin: 4, status: 'online' },
  { id: 'bbq', name: '烧烤', icon: '🍖', pendingCount: 0, cookingCount: 0, avgWaitMin: 0, status: 'offline' },
  { id: 'dessert', name: '甜品', icon: '🍰', pendingCount: 1, cookingCount: 0, avgWaitMin: 2, status: 'online' },
];

// ─── 负载等级 ───

type LoadLevel = 'low' | 'medium' | 'high';

function getLoadLevel(dept: Department): LoadLevel {
  const total = dept.pendingCount + dept.cookingCount;
  if (dept.status === 'offline') return 'low';
  if (total >= 10 || dept.avgWaitMin >= 20) return 'high';
  if (total >= 5 || dept.avgWaitMin >= 12) return 'medium';
  return 'low';
}

const LOAD_COLORS: Record<LoadLevel, string> = {
  low: '#0F6E56',
  medium: '#BA7517',
  high: '#A32D2D',
};

const LOAD_LABELS: Record<LoadLevel, string> = {
  low: '空闲',
  medium: '繁忙',
  high: '高负荷',
};

// ─── Component ───

export function DeptSelector() {
  const [depts, setDepts] = useState<Department[]>(MOCK_DEPTS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // 自动刷新（模拟轮询）
  useEffect(() => {
    const timer = setInterval(() => {
      // 实际接入时调用 fetchDeptLoad API
      setDepts(prev => prev.map(d => ({
        ...d,
        pendingCount: d.status === 'online'
          ? Math.max(0, d.pendingCount + Math.floor(Math.random() * 3) - 1)
          : 0,
      })));
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    // 实际使用时，通过 Zustand 或 URL 参数传到 KitchenBoard
    // 这里跳转到看板页并带上档口参数
    window.location.href = `/board?dept=${id}`;
  };

  const totalPending = depts.filter(d => d.status === 'online').reduce((s, d) => s + d.pendingCount, 0);
  const totalCooking = depts.filter(d => d.status === 'online').reduce((s, d) => s + d.cookingCount, 0);

  return (
    <div style={{
      background: '#0A0A0A', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      padding: 20,
    }}>
      {/* 顶栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 24,
      }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#FF6B35' }}>选择档口</h1>
        <div style={{ display: 'flex', gap: 24, fontSize: 18 }}>
          <span>
            全部待制作 <b style={{ color: '#BA7517', fontSize: 24 }}>{totalPending}</b>
          </span>
          <span>
            全部制作中 <b style={{ color: '#1890ff', fontSize: 24 }}>{totalCooking}</b>
          </span>
        </div>
      </div>

      {/* 查看全部入口 */}
      <button
        onClick={() => { window.location.href = '/board?dept=all'; }}
        style={{
          width: '100%', padding: '18px 0', marginBottom: 20,
          background: '#1a1a1a', border: '2px solid #FF6B35', borderRadius: 12,
          color: '#FF6B35', fontSize: 22, fontWeight: 'bold',
          cursor: 'pointer', minHeight: 64,
          transition: 'transform 200ms ease',
        }}
        onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
        onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
      >
        全部档口看板
      </button>

      {/* 档口网格 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
        gap: 16,
      }}>
        {depts.map(dept => {
          const load = getLoadLevel(dept);
          const isOffline = dept.status === 'offline';
          const total = dept.pendingCount + dept.cookingCount;

          return (
            <button
              key={dept.id}
              onClick={() => !isOffline && handleSelect(dept.id)}
              disabled={isOffline}
              style={{
                background: isOffline ? '#1a1a1a' : selectedId === dept.id ? '#1a2a1a' : '#111',
                borderRadius: 16,
                padding: 20,
                border: selectedId === dept.id ? '3px solid #FF6B35' : '2px solid #222',
                borderLeft: `6px solid ${isOffline ? '#444' : LOAD_COLORS[load]}`,
                cursor: isOffline ? 'not-allowed' : 'pointer',
                opacity: isOffline ? 0.4 : 1,
                textAlign: 'left',
                color: '#E0E0E0',
                minHeight: 140,
                transition: 'transform 200ms ease',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
              onTouchStart={e => {
                if (!isOffline) e.currentTarget.style.transform = 'scale(0.97)';
              }}
              onTouchEnd={e => {
                if (!isOffline) e.currentTarget.style.transform = 'scale(1)';
              }}
            >
              {/* 档口名称 + icon */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 32 }}>{dept.icon}</span>
                  <span style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{dept.name}</span>
                </div>
                {isOffline && (
                  <span style={{
                    fontSize: 16, padding: '4px 12px', borderRadius: 6,
                    background: '#333', color: '#666',
                  }}>
                    离线
                  </span>
                )}
              </div>

              {/* 数量统计 */}
              {!isOffline && (
                <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
                  <div>
                    <div style={{ fontSize: 16, color: '#888' }}>待制作</div>
                    <div style={{ fontSize: 28, fontWeight: 'bold', color: '#BA7517', fontFamily: 'JetBrains Mono, monospace' }}>
                      {dept.pendingCount}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 16, color: '#888' }}>制作中</div>
                    <div style={{ fontSize: 28, fontWeight: 'bold', color: '#1890ff', fontFamily: 'JetBrains Mono, monospace' }}>
                      {dept.cookingCount}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 16, color: '#888' }}>均耗时</div>
                    <div style={{ fontSize: 28, fontWeight: 'bold', color: '#E0E0E0', fontFamily: 'JetBrains Mono, monospace' }}>
                      {dept.avgWaitMin}'
                    </div>
                  </div>
                </div>
              )}

              {/* 负载指示器 */}
              {!isOffline && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {/* 负载进度条 */}
                  <div style={{
                    flex: 1, height: 10, background: '#222', borderRadius: 5, overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${Math.min((total / 15) * 100, 100)}%`,
                      height: '100%', borderRadius: 5,
                      background: LOAD_COLORS[load],
                      transition: 'width 300ms ease',
                    }} />
                  </div>
                  <span style={{
                    fontSize: 16, fontWeight: 'bold',
                    color: LOAD_COLORS[load], minWidth: 60,
                  }}>
                    {LOAD_LABELS[load]}
                  </span>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
