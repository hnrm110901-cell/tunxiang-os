/**
 * AI预订洞察面板 — 嵌入 ReservationBoard 顶部
 *
 * 对标: SevenRooms (guest insights), Anolla (AI maitre d'), OpenTable (yield management)
 *
 * Store终端组件: 不使用Ant Design, 触控48px+, 字体16px+
 */
import { useState, useEffect } from 'react';

// ── AI洞察数据 ──
interface AIInsight {
  predictedArrivalRate: number;    // 预测到店率 %
  suggestedOverbooking: number;    // 建议超订桌数
  highRiskReservations: { id: string; name: string; noShowProb: number; reason: string }[];
  peakSlot: string;
  valleySlot: string;
  valleyPromotion: string;
  confirmationPending: number;     // 待确认数
  guestProfileMatched: number;     // 已匹配画像数
  revenueForecas: number;         // 预测营收(元)
}

const MOCK_INSIGHT: AIInsight = {
  predictedArrivalRate: 82,
  suggestedOverbooking: 2,
  highRiskReservations: [
    { id: 'R007', name: '孙先生', noShowProb: 68, reason: '未付押金+历史爽约2次' },
    { id: 'R008', name: '周女士', noShowProb: 35, reason: '提前7天预订+非会员' },
  ],
  peakSlot: '18:00-19:00',
  valleySlot: '13:00-17:00',
  valleyPromotion: '低谷时段建议推送"下午茶套餐¥68"引流',
  confirmationPending: 3,
  guestProfileMatched: 5,
  revenueForecas: 28600,
};

export function AIInsightsPanel() {
  const [insight] = useState<AIInsight>(MOCK_INSIGHT);
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        style={{
          width: '100%', minHeight: 48, background: 'var(--tx-bg-2)',
          border: '1px solid var(--tx-border)', borderRadius: 'var(--tx-radius-md)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          fontSize: 18, fontWeight: 600, color: 'var(--tx-primary)', cursor: 'pointer',
          marginBottom: 16,
        }}
      >
        <span>AI 预订洞察</span>
        <span style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>点击展开</span>
      </button>
    );
  }

  return (
    <div style={{
      background: 'linear-gradient(135deg, #FFF8F4 0%, #FFF3ED 100%)',
      borderRadius: 'var(--tx-radius-lg)',
      border: '2px solid var(--tx-primary)',
      padding: 20, marginBottom: 20,
    }}>
      {/* 标题栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--tx-primary)' }}>
            AI 预订洞察
          </span>
          <span style={{
            fontSize: 16, background: 'var(--tx-primary)', color: '#FFF',
            padding: '2px 10px', borderRadius: 12, fontWeight: 600,
          }}>
            Agent OS
          </span>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          style={{
            minWidth: 48, minHeight: 48, border: '1px solid var(--tx-border)',
            borderRadius: 'var(--tx-radius-sm)', background: '#FFF',
            fontSize: 18, cursor: 'pointer', color: 'var(--tx-text-3)',
          }}
        >
          收起
        </button>
      </div>

      {/* KPI卡片行 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <KPICard
          label="预测到店率"
          value={`${insight.predictedArrivalRate}%`}
          color={insight.predictedArrivalRate >= 80 ? 'var(--tx-success)' : 'var(--tx-warning)'}
        />
        <KPICard
          label="建议超订"
          value={`+${insight.suggestedOverbooking}桌`}
          color="var(--tx-info)"
        />
        <KPICard
          label="已匹配画像"
          value={`${insight.guestProfileMatched}位`}
          color="var(--tx-success)"
        />
        <KPICard
          label="待确认"
          value={`${insight.confirmationPending}单`}
          color={insight.confirmationPending > 2 ? 'var(--tx-warning)' : 'var(--tx-text-2)'}
        />
        <KPICard
          label="预测营收"
          value={`¥${(insight.revenueForecas / 10000).toFixed(2)}万`}
          color="var(--tx-primary)"
        />
      </div>

      {/* 高风险预订 */}
      {insight.highRiskReservations.length > 0 && (
        <div style={{
          background: '#FFF', borderRadius: 'var(--tx-radius-md)',
          padding: 16, marginBottom: 12,
          border: '1px solid var(--tx-border)',
        }}>
          <div style={{
            fontSize: 18, fontWeight: 700, color: 'var(--tx-danger)',
            marginBottom: 10,
          }}>
            No-Show 高风险预警
          </div>
          {insight.highRiskReservations.map(r => (
            <div key={r.id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0', borderBottom: '1px solid var(--tx-border)',
              fontSize: 18,
            }}>
              <div>
                <span style={{ fontWeight: 600 }}>{r.name}</span>
                <span style={{ color: 'var(--tx-text-3)', marginLeft: 8, fontSize: 16 }}>
                  {r.reason}
                </span>
              </div>
              <div style={{
                fontWeight: 700, fontSize: 20,
                color: r.noShowProb > 50 ? 'var(--tx-danger)' : 'var(--tx-warning)',
              }}>
                {r.noShowProb}%
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 时段优化建议 */}
      <div style={{
        background: '#FFF', borderRadius: 'var(--tx-radius-md)',
        padding: 16, border: '1px solid var(--tx-border)',
        display: 'flex', gap: 20, flexWrap: 'wrap',
      }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <span style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>高峰时段</span>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--tx-danger)' }}>
            {insight.peakSlot}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <span style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>低谷时段</span>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--tx-info)' }}>
            {insight.valleySlot}
          </div>
        </div>
        <div style={{ flex: 2, minWidth: 300 }}>
          <span style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>引流建议</span>
          <div style={{ fontSize: 18, color: 'var(--tx-text-1)' }}>
            {insight.valleyPromotion}
          </div>
        </div>
      </div>
    </div>
  );
}

function KPICard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      background: '#FFF', borderRadius: 'var(--tx-radius-md)',
      padding: '12px 20px', minWidth: 130, flex: '1 1 130px',
      border: '1px solid var(--tx-border)',
      textAlign: 'center',
    }}>
      <div style={{ fontSize: 26, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 16, color: 'var(--tx-text-3)', marginTop: 2 }}>{label}</div>
    </div>
  );
}
