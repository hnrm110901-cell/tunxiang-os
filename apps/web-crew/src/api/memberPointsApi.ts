/**
 * 会员积分 API — Mock实现，待后端接入
 */

export interface PointsTransaction {
  id: string
  change: number       // 正数=获得，负数=消耗
  reason: string
  created_at: string
}

export interface MemberPoints {
  member_id: string
  current_points: number
  lifetime_points: number
  level: 'bronze' | 'silver' | 'gold' | 'diamond'
  next_level_threshold: number
  transactions: PointsTransaction[]
}

/** 获取会员积分数据（含明细） */
export async function getMemberPoints(
  member_id: string,
): Promise<{ ok: boolean; data: MemberPoints }> {
  // Mock数据，实际接口待后端实现
  return {
    ok: true,
    data: {
      member_id,
      current_points: 1280,
      lifetime_points: 3560,
      level: 'silver',
      next_level_threshold: 2000,
      transactions: [
        { id: '1', change: +150, reason: '消费积分', created_at: '2026-04-01T12:30:00Z' },
        { id: '2', change: -100, reason: '积分兑换', created_at: '2026-03-28T18:00:00Z' },
        { id: '3', change: +200, reason: '充值赠积分', created_at: '2026-03-20T09:15:00Z' },
        { id: '4', change: +80,  reason: '消费积分', created_at: '2026-03-15T13:20:00Z' },
        { id: '5', change: -50,  reason: '积分兑换', created_at: '2026-03-10T20:00:00Z' },
        { id: '6', change: +120, reason: '消费积分', created_at: '2026-03-05T12:00:00Z' },
        { id: '7', change: +300, reason: '注册赠送', created_at: '2026-02-20T10:00:00Z' },
        { id: '8', change: +100, reason: '生日赠积分', created_at: '2026-02-14T00:00:00Z' },
        { id: '9', change: -80,  reason: '积分兑换', created_at: '2026-02-10T16:30:00Z' },
        { id: '10', change: +180, reason: '消费积分', created_at: '2026-02-05T19:00:00Z' },
      ],
    },
  };
}
