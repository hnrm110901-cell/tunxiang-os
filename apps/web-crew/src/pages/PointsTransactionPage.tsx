/**
 * PointsTransactionPage — 会员积分明细页（按月分组）
 * URL: /member/:memberId/points
 * 从 MemberPage 跳转，支持 URL params 或 location.state 传入会员信息
 * 竖屏PWA，最小点击区域48×48px，最小字体16px，深色主题内联CSS
 */
import { useState, useEffect } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { getMemberPoints, type PointsTransaction } from '../api/memberPointsApi';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1E3A45',
  accent: '#FF6B35',
  green: '#22c55e',
  red: '#ef4444',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

/* ---------- 工具函数 ---------- */
function formatDate(iso: string): string {
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${min}`;
}

function getMonthKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}年${d.getMonth() + 1}月`;
}

/** 按月分组积分记录 */
function groupByMonth(txns: PointsTransaction[]): Array<{ month: string; items: PointsTransaction[] }> {
  const map = new Map<string, PointsTransaction[]>();
  for (const t of txns) {
    const key = getMonthKey(t.created_at);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(t);
  }
  return Array.from(map.entries()).map(([month, items]) => ({ month, items }));
}

/* ---------- 加载骨架 ---------- */
function SkeletonRow() {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '12px 0', borderBottom: `1px solid ${C.border}`,
    }}>
      <div>
        <div style={{ height: 16, width: 100, borderRadius: 4, background: C.border, marginBottom: 6 }} />
        <div style={{ height: 14, width: 70, borderRadius: 4, background: C.border }} />
      </div>
      <div style={{ height: 20, width: 50, borderRadius: 4, background: C.border }} />
    </div>
  );
}

/* ---------- 单条记录 ---------- */
function TxnRow({ txn }: { txn: PointsTransaction }) {
  const isPlus = txn.change >= 0;
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '12px 0', borderBottom: `1px solid ${C.border}`,
    }}>
      <div>
        <div style={{ fontSize: 16, color: C.text, fontWeight: 500 }}>{txn.reason}</div>
        <div style={{ fontSize: 14, color: C.muted, marginTop: 3 }}>{formatDate(txn.created_at)}</div>
      </div>
      <span style={{
        fontSize: 20, fontWeight: 700,
        color: isPlus ? C.green : C.red,
        minWidth: 60, textAlign: 'right',
      }}>
        {isPlus ? `+${txn.change}` : `${txn.change}`}
      </span>
    </div>
  );
}

/* ---------- 主页面 ---------- */
export function PointsTransactionPage() {
  const navigate = useNavigate();
  const { memberId } = useParams<{ memberId: string }>();
  const location = useLocation();

  // 优先从 location.state 获取 memberName / currentPoints，否则从 query
  const state = (location.state as { memberName?: string; currentPoints?: number } | null) ?? {};
  const params = new URLSearchParams(location.search);
  const memberName = state.memberName ?? params.get('name') ?? '会员';
  const statePoints = state.currentPoints;

  const [loading, setLoading] = useState(true);
  const [groups, setGroups] = useState<Array<{ month: string; items: PointsTransaction[] }>>([]);
  const [currentPoints, setCurrentPoints] = useState<number>(statePoints ?? 0);
  const [totalEarned, setTotalEarned] = useState(0);
  const [totalConsumed, setTotalConsumed] = useState(0);

  useEffect(() => {
    if (!memberId) return;
    setLoading(true);
    getMemberPoints(memberId)
      .then(res => {
        if (!res.ok) return;
        const d = res.data;
        setCurrentPoints(d.current_points);
        setGroups(groupByMonth(d.transactions));
        const earned = d.transactions.filter(t => t.change > 0).reduce((s, t) => s + t.change, 0);
        const consumed = d.transactions.filter(t => t.change < 0).reduce((s, t) => s + Math.abs(t.change), 0);
        setTotalEarned(earned);
        setTotalConsumed(consumed);
      })
      .catch(() => setGroups([]))
      .finally(() => setLoading(false));
  }, [memberId]);

  return (
    <div style={{
      background: C.bg, minHeight: '100vh',
      color: C.text,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    }}>
      {/* 顶部导航 */}
      <div style={{
        background: C.card, padding: '0 16px',
        borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 12,
        position: 'sticky', top: 0, zIndex: 10,
        height: 60,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            width: 48, height: 48, borderRadius: 10,
            background: C.border, border: 'none',
            color: C.text, fontSize: 22, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
          aria-label="返回"
        >
          ←
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{memberName}</div>
          <div style={{ fontSize: 14, color: C.muted }}>积分明细</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 13, color: C.muted }}>当前积分</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: C.accent }}>
            {currentPoints.toLocaleString()}
          </div>
        </div>
      </div>

      {/* 内容区 */}
      <div style={{ padding: '16px 16px 100px' }}>
        {loading && (
          <div style={{
            background: C.card, borderRadius: 12, padding: '0 16px',
            border: `1px solid ${C.border}`,
          }}>
            {Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)}
          </div>
        )}

        {!loading && groups.length === 0 && (
          <div style={{
            textAlign: 'center', padding: '60px 20px',
            color: C.muted, fontSize: 16,
          }}>
            暂无积分记录
          </div>
        )}

        {!loading && groups.map(({ month, items }) => (
          <div key={month} style={{ marginBottom: 20 }}>
            {/* 月份标题 */}
            <div style={{
              fontSize: 15, fontWeight: 700, color: C.muted,
              padding: '8px 0 4px',
              borderBottom: `2px solid ${C.border}`,
              marginBottom: 4,
            }}>
              {month}
            </div>
            <div style={{
              background: C.card, borderRadius: 12,
              padding: '0 16px', border: `1px solid ${C.border}`,
            }}>
              {items.map(t => <TxnRow key={t.id} txn={t} />)}
            </div>
          </div>
        ))}

        {/* 底部统计条 */}
        {!loading && groups.length > 0 && (
          <div style={{
            position: 'fixed', bottom: 0, left: 0, right: 0,
            background: C.card,
            borderTop: `1px solid ${C.border}`,
            padding: '12px 16px',
            display: 'flex', gap: 0,
            zIndex: 20,
          }}>
            <div style={{
              flex: 1, textAlign: 'center',
              borderRight: `1px solid ${C.border}`,
            }}>
              <div style={{ fontSize: 13, color: C.muted, marginBottom: 2 }}>累计获得</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.green }}>
                +{totalEarned.toLocaleString()}
              </div>
            </div>
            <div style={{ flex: 1, textAlign: 'center' }}>
              <div style={{ fontSize: 13, color: C.muted, marginBottom: 2 }}>累计消耗</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.red }}>
                -{totalConsumed.toLocaleString()}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
