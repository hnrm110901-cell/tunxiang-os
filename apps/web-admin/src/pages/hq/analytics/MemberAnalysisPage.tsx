/**
 * 会员分析页 -- F6 总部端
 * 功能: 会员增长趋势 + 活跃度漏斗 + 复购率趋势 + 流失预警列表
 * 调用 GET /api/v1/member/analytics/*
 */
import { useState } from 'react';
import { TxLineChart, TxScatterChart } from '../../../components/charts';

// ---------- 类型 ----------
interface FunnelStep {
  name: string;
  value: number;
  color: string;
}

interface RepurchaseData {
  month: string;
  rate: number;
  orders: number;
}

interface ChurnRisk {
  id: string;
  name: string;
  phone: string;
  level: string;
  lastVisit: string;
  daysSince: number;
  totalSpend: number;
  visitCount: number;
  riskScore: number;
  suggestedAction: string;
}

// ---------- Mock 数据 ----------
const MOCK_OVERVIEW = [
  { label: '总会员数', value: '12,860', trend: '+326', up: true, color: '#FF6B2C' },
  { label: '本月新增', value: '326', trend: '+18.2%', up: true, color: '#0F6E56' },
  { label: '月活会员', value: '4,280', trend: '+5.6%', up: true, color: '#185FA5' },
  { label: '流失预警', value: '186', trend: '+23', up: false, color: '#A32D2D' },
];

const MOCK_FUNNEL: FunnelStep[] = [
  { name: '注册会员', value: 12860, color: '#FF6B2C' },
  { name: '首次消费', value: 9640, color: '#FF8555' },
  { name: '二次复购', value: 5800, color: '#185FA5' },
  { name: '活跃会员(月3次+)', value: 2150, color: '#0F6E56' },
  { name: '忠诚会员(月5次+)', value: 860, color: '#0F6E56' },
];

const MOCK_REPURCHASE: RepurchaseData[] = [
  { month: '10月', rate: 38.2, orders: 3680 },
  { month: '11月', rate: 40.1, orders: 3920 },
  { month: '12月', rate: 42.5, orders: 4210 },
  { month: '1月', rate: 39.8, orders: 3850 },
  { month: '2月', rate: 41.3, orders: 4050 },
  { month: '3月', rate: 43.6, orders: 4380 },
];

const MOCK_CHURN_RISK: ChurnRisk[] = [
  { id: 'c1', name: '张*华', phone: '138****6789', level: '金卡', lastVisit: '2026-01-15', daysSince: 71, totalSpend: 18600, visitCount: 42, riskScore: 95, suggestedAction: '发送专属优惠券' },
  { id: 'c2', name: '李*芳', phone: '139****2345', level: '银卡', lastVisit: '2026-01-28', daysSince: 58, totalSpend: 8900, visitCount: 23, riskScore: 88, suggestedAction: '生日关怀+满减券' },
  { id: 'c3', name: '王*明', phone: '137****8901', level: '金卡', lastVisit: '2026-02-05', daysSince: 50, totalSpend: 15200, visitCount: 36, riskScore: 82, suggestedAction: '新品试吃邀请' },
  { id: 'c4', name: '赵*红', phone: '135****4567', level: '普通', lastVisit: '2026-02-10', daysSince: 45, totalSpend: 3200, visitCount: 8, riskScore: 76, suggestedAction: '回归礼包' },
  { id: 'c5', name: '陈*伟', phone: '136****7890', level: '银卡', lastVisit: '2026-02-18', daysSince: 37, totalSpend: 6800, visitCount: 18, riskScore: 68, suggestedAction: '积分兑换提醒' },
  { id: 'c6', name: '刘*静', phone: '158****3456', level: '金卡', lastVisit: '2026-02-20', daysSince: 35, totalSpend: 22400, visitCount: 56, riskScore: 65, suggestedAction: 'VIP专属邀请' },
  { id: 'c7', name: '杨*军', phone: '180****1234', level: '普通', lastVisit: '2026-02-25', daysSince: 30, totalSpend: 2100, visitCount: 5, riskScore: 58, suggestedAction: '满减优惠推送' },
];

// ---------- 工具 ----------
const riskColor = (score: number) => score >= 80 ? '#A32D2D' : score >= 60 ? '#BA7517' : '#185FA5';
const levelColor = (level: string) =>
  level === '金卡' ? '#BA7517' : level === '银卡' ? '#888' : '#555';

// ---------- 组件 ----------
export function MemberAnalysisPage() {
  const [period, setPeriod] = useState('本月');

  const funnelMax = MOCK_FUNNEL[0].value;

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>会员分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {['本周', '本月', '本季', '本年'].map((d) => (
            <button key={d} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === d ? '#FF6B2C' : '#1a2a33',
              color: period === d ? '#fff' : '#999',
            }} onClick={() => setPeriod(d)}>
              {d}
            </button>
          ))}
        </div>
      </div>

      {/* 概览卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {MOCK_OVERVIEW.map((kpi) => (
          <div key={kpi.label} style={{
            background: '#112228', borderRadius: 8, padding: 16,
            borderLeft: `3px solid ${kpi.color}`,
          }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
            <div style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</div>
            <div style={{ fontSize: 11, marginTop: 4, color: kpi.up ? '#0F6E56' : '#A32D2D' }}>
              {kpi.up ? '\u2191' : '\u2193'} {kpi.trend}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 会员增长趋势 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>会员增长趋势</h3>
          <TxLineChart
            data={{
              labels: ['10月', '11月', '12月', '1月', '2月', '3月'],
              datasets: [
                { name: '累计会员', values: [10200, 10800, 11400, 11900, 12480, 12860], color: '#FF6B2C' },
                { name: '新增会员', values: [280, 310, 290, 320, 300, 326], color: '#0F6E56' },
              ],
            }}
            height={240}
            showArea
          />
        </div>

        {/* 活跃度漏斗 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>活跃度漏斗</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {MOCK_FUNNEL.map((step, i) => {
              const widthPct = Math.max((step.value / funnelMax) * 100, 20);
              const convRate = i > 0
                ? ((step.value / MOCK_FUNNEL[i - 1].value) * 100).toFixed(1)
                : null;
              return (
                <div key={step.name}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 13, color: '#ccc' }}>{step.name}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 14, fontWeight: 'bold', color: '#fff' }}>
                        {step.value.toLocaleString()}
                      </span>
                      {convRate && (
                        <span style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 4,
                          background: '#185FA520', color: '#185FA5', fontWeight: 600,
                        }}>
                          {convRate}%
                        </span>
                      )}
                    </div>
                  </div>
                  <div style={{
                    height: 24, borderRadius: 6, background: '#0B1A20',
                    overflow: 'hidden', display: 'flex', justifyContent: 'center',
                  }}>
                    <div style={{
                      width: `${widthPct}%`, height: '100%', borderRadius: 6,
                      background: step.color, transition: 'width 0.6s ease',
                      opacity: 0.7 + (i === 0 ? 0.3 : 0),
                    }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 复购率趋势 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>复购率趋势</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_REPURCHASE.map((item) => {
              const barColor = item.rate >= 42 ? '#0F6E56' : item.rate >= 40 ? '#185FA5' : '#BA7517';
              return (
                <div key={item.month} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ width: 36, fontSize: 12, color: '#999', textAlign: 'right' }}>{item.month}</span>
                  <div style={{ flex: 1, height: 20, borderRadius: 4, background: '#0B1A20', overflow: 'hidden', position: 'relative' }}>
                    <div style={{
                      width: `${item.rate * 2}%`, height: '100%', borderRadius: 4,
                      background: barColor, transition: 'width 0.6s ease',
                    }} />
                    <span style={{
                      position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                      fontSize: 11, fontWeight: 600, color: '#fff',
                    }}>
                      {item.rate}%
                    </span>
                  </div>
                  <span style={{ width: 60, fontSize: 11, color: '#999', textAlign: 'right' }}>
                    {item.orders.toLocaleString()}单
                  </span>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 12 }}>
            <TxScatterChart
              data={[
                { name: '金卡', x: 68.5, y: 72.3, size: 56 },
                { name: '银卡', x: 58.2, y: 48.6, size: 42 },
                { name: '普通', x: 45.0, y: 28.4, size: 28 },
                { name: '新客', x: 52.0, y: 15.2, size: 18 },
              ]}
              height={140}
              xLabel="客单价(元)"
              yLabel="复购率(%)"
              xUnit="元"
              yUnit="%"
            />
          </div>
        </div>

        {/* 流失预警列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            流失预警
            <span style={{
              fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
              background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
            }}>
              {MOCK_CHURN_RISK.length} 人
            </span>
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_CHURN_RISK.map((member) => (
              <div key={member.id} style={{
                padding: 12, borderRadius: 8, background: '#0B1A20',
                borderLeft: `3px solid ${riskColor(member.riskScore)}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>{member.name}</span>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                      background: levelColor(member.level) + '30',
                      color: levelColor(member.level),
                    }}>
                      {member.level}
                    </span>
                  </div>
                  <span style={{
                    fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 700,
                    background: riskColor(member.riskScore) + '20',
                    color: riskColor(member.riskScore),
                  }}>
                    风险 {member.riskScore}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#999', marginBottom: 4 }}>
                  <span>{member.daysSince}天未到店</span>
                  <span>累计 \u00A5{(member.totalSpend / 100).toLocaleString()} | {member.visitCount}次</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: '#185FA5' }}>{member.suggestedAction}</span>
                  <button style={{
                    padding: '3px 10px', borderRadius: 4, border: 'none',
                    background: '#FF6B2C20', color: '#FF6B2C',
                    cursor: 'pointer', fontWeight: 600, fontSize: 10,
                  }}>
                    执行
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
