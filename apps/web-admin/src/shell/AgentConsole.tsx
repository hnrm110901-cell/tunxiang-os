/**
 * Agent Console — 决策2：Context Panel 升级为 Agent Console
 *
 * 三个子面板：
 * 1. Agent Feed — 实时决策推送
 * 2. Agent Chat — 自然语言问数
 * 3. Agent Audit — 决策留痕查看
 *
 * 告警映射（AI工程师建议）：
 *   .crit → 硬约束被违反
 *   .warn → 硬约束接近阈值
 *   .info → Agent 建议性推送
 *
 * 决策3（商务建议）：底部显示"本月 AI 为你节省了 ¥XX"
 */
import { useState } from 'react';

type Tab = 'feed' | 'chat' | 'audit';

const MOCK_FEED = [
  { id: '1', type: 'crit', agent: '折扣守护', title: '毛利底线告警', detail: 'A03桌订单折扣率62%，已超毛利底线', time: '2分钟前' },
  { id: '2', type: 'warn', agent: '库存预警', title: '鲈鱼库存不足', detail: '当前库存2kg，预计明天缺货', time: '15分钟前' },
  { id: '3', type: 'info', agent: '智能排菜', title: '新菜上市建议', detail: '「酸菜鱼」试点评分92分，建议全品牌推广', time: '1小时前' },
  { id: '4', type: 'info', agent: '财务稽核', title: '成本率优化', detail: '本周成本率降至31.2%，环比-1.5pp', time: '3小时前' },
];

const MOCK_AUDIT = [
  { id: '1', agent: '折扣守护', action: '拦截异常折扣', constraint: '毛利底线 ✓', confidence: '95%', time: '14:25' },
  { id: '2', agent: '出餐调度', action: '调整排班', constraint: '客户体验 ✓', confidence: '78%', time: '14:10' },
  { id: '3', agent: '库存预警', action: '生成补货单', constraint: '食安合规 ✓', confidence: '88%', time: '13:45' },
];

const typeStyle: Record<string, { bg: string; border: string; label: string }> = {
  crit: { bg: 'rgba(255,77,79,0.08)', border: '#ff4d4f', label: '严重' },
  warn: { bg: 'rgba(250,173,20,0.08)', border: '#faad14', label: '警告' },
  info: { bg: 'rgba(24,144,255,0.08)', border: '#1890ff', label: '信息' },
};

export function AgentConsole() {
  const [tab, setTab] = useState<Tab>('feed');

  return (
    <aside style={{
      width: 340, background: 'var(--bg-1, #112228)',
      borderLeft: '1px solid var(--bg-2, #1a2a33)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      {/* Tab 切换 */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--bg-2)' }}>
        {([
          { key: 'feed', label: '决策推送' },
          { key: 'chat', label: 'AI 问数' },
          { key: 'audit', label: '决策审计' },
        ] as { key: Tab; label: string }[]).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              flex: 1, padding: '10px 0', border: 'none', cursor: 'pointer', fontSize: 12,
              background: 'transparent',
              color: tab === t.key ? 'var(--brand)' : 'var(--text-3)',
              borderBottom: tab === t.key ? '2px solid var(--brand)' : '2px solid transparent',
              transition: 'all var(--duration-fast)',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Feed */}
      {tab === 'feed' && (
        <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
          {MOCK_FEED.map((f) => {
            const s = typeStyle[f.type];
            return (
              <div key={f.id} style={{
                padding: 10, marginBottom: 8, borderRadius: 8,
                background: s.bg, borderLeft: `3px solid ${s.border}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{ fontSize: 11, color: s.border, fontWeight: 600 }}>
                    {s.label} · {f.agent}
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--text-4)' }}>{f.time}</span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{f.title}</div>
                <div style={{ fontSize: 12, color: 'var(--text-3)' }}>{f.detail}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* Chat */}
      {tab === 'chat' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 12 }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-4)' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>💬</div>
              <div style={{ fontSize: 13 }}>用自然语言查询经营数据</div>
              <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 4 }}>
                试试："今天营收多少？" "鲈鱼损耗排名？"
              </div>
            </div>
          </div>
          <input
            placeholder="输入问题..."
            style={{
              padding: '10px 12px', borderRadius: 8, border: '1px solid var(--bg-2)',
              background: 'var(--bg-0)', color: 'var(--text-2)', fontSize: 13, outline: 'none',
            }}
          />
        </div>
      )}

      {/* Audit */}
      {tab === 'audit' && (
        <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
          {MOCK_AUDIT.map((a) => (
            <div key={a.id} style={{
              padding: 10, marginBottom: 8, borderRadius: 8,
              background: 'var(--bg-0)', border: '1px solid var(--bg-2)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>{a.agent}</span>
                <span style={{ fontSize: 10, color: 'var(--text-4)' }}>{a.time}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-2)' }}>{a.action}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: 'var(--text-3)' }}>
                <span>{a.constraint}</span>
                <span>置信度 {a.confidence}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 决策3（商务）：AI 价值可视化 */}
      <div style={{
        padding: '10px 12px', borderTop: '1px solid var(--bg-2)',
        textAlign: 'center', fontSize: 12,
      }}>
        <span style={{ color: 'var(--text-4)' }}>本月 AI 为你节省</span>
        <span style={{ color: 'var(--green)', fontWeight: 'bold', fontSize: 18, marginLeft: 6 }}>¥12,680</span>
      </div>
    </aside>
  );
}
