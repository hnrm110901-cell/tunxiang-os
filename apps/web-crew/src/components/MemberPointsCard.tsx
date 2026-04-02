/**
 * MemberPointsCard — 会员积分卡片
 * 显示当前积分、等级徽章、升级进度条及快捷操作
 * 深色主题内联CSS，无外部依赖
 */
import { MemberLevelBadge, type MemberLevelBadgeProps } from './MemberLevelBadge';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  accent: '#FF6B35',
  text: '#e2e8f0',
  muted: '#64748b',
  border: '#1E3A45',
  green: '#22c55e',
  white: '#ffffff',
};

export interface MemberPointsCardProps {
  memberId: string
  memberName: string
  currentLevel: string
  points: number
  nextLevelPoints: number   // 升级所需积分（下一级阈值）
  nextLevel: string         // 下一等级名称
  onViewDetail?: () => void
  onRecharge?: () => void
}

/** 规范化等级code为MemberLevelBadge接受的类型 */
function normalizeLevelCode(code: string): MemberLevelBadgeProps['level'] {
  if (code === 'gold') return 'gold';
  if (code === 'silver') return 'silver';
  if (code === 'diamond') return 'diamond';
  return 'bronze';
}

export function MemberPointsCard({
  memberName,
  currentLevel,
  points,
  nextLevelPoints,
  nextLevel,
  onViewDetail,
  onRecharge,
}: MemberPointsCardProps) {
  const progressPct = nextLevelPoints > 0
    ? Math.min(100, Math.round((points / nextLevelPoints) * 100))
    : 100;
  const pointsLeft = Math.max(0, nextLevelPoints - points);
  const levelCode = normalizeLevelCode(currentLevel);
  const isMaxLevel = !nextLevel || nextLevelPoints <= 0;

  return (
    <div style={{
      background: C.card,
      borderRadius: 12,
      padding: 16,
      border: `1px solid ${C.border}`,
    }}>
      {/* 顶部：姓名 + 等级徽章 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 16,
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text }}>
          {memberName}
        </div>
        <MemberLevelBadge level={levelCode} size="md" />
      </div>

      {/* 中部：积分大字 */}
      <div style={{
        textAlign: 'center',
        marginBottom: 16,
        background: C.bg,
        borderRadius: 10,
        padding: '16px 12px 12px',
      }}>
        <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>当前积分</div>
        <div style={{
          fontSize: 48,
          fontWeight: 800,
          color: C.accent,
          lineHeight: 1.1,
          fontVariantNumeric: 'tabular-nums',
        }}>
          {points.toLocaleString()}
        </div>
        <div style={{ fontSize: 16, color: C.muted, marginTop: 2 }}>积分</div>
      </div>

      {/* 进度条区域 */}
      {!isMaxLevel && (
        <div style={{ marginBottom: 16 }}>
          {/* 轨道 */}
          <div style={{
            height: 10,
            borderRadius: 5,
            background: C.border,
            overflow: 'hidden',
            marginBottom: 8,
          }}>
            <div style={{
              height: '100%',
              borderRadius: 5,
              width: `${progressPct}%`,
              background: C.accent,
              transition: 'width 0.6s ease',
            }} />
          </div>
          {/* 进度文字 */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 14,
            color: C.muted,
          }}>
            <span>{progressPct}% → 升{nextLevel}</span>
            <span style={{ color: C.accent, fontWeight: 600 }}>
              还差 {pointsLeft.toLocaleString()} 积分升级
            </span>
          </div>
        </div>
      )}

      {isMaxLevel && (
        <div style={{
          textAlign: 'center',
          fontSize: 15,
          color: '#FFD700',
          padding: '8px 0 16px',
          fontWeight: 600,
        }}>
          已达最高等级 ✦
        </div>
      )}

      {/* 操作按钮行 */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          onClick={onViewDetail}
          style={{
            flex: 1,
            minHeight: 48,
            borderRadius: 10,
            background: C.bg,
            border: `1px solid ${C.border}`,
            color: C.text,
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
          }}
        >
          <span>📋</span>积分明细
        </button>
        <button
          onClick={onRecharge}
          style={{
            flex: 1,
            minHeight: 48,
            borderRadius: 10,
            background: `${C.green}22`,
            border: `1px solid ${C.green}55`,
            color: C.green,
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
          }}
        >
          <span>💳</span>充值储值
        </button>
      </div>
    </div>
  );
}
