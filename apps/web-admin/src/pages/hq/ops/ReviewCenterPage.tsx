/**
 * 复盘中心 — 日/周/月复盘、门店问题看板、经营案例库
 * 调用 GET /api/v1/review/*
 */
import { useState } from 'react';

type ReviewPeriod = 'day' | 'week' | 'month';
type HealthLevel = 'green' | 'yellow' | 'red';

interface StoreIssue {
  store: string;
  level: HealthLevel;
  score: number;
  issues: string[];
  actions: string[];
}

const LEVEL_CONFIG: Record<HealthLevel, { label: string; color: string; bg: string }> = {
  green: { label: '健康', color: '#52c41a', bg: 'rgba(82,196,26,0.1)' },
  yellow: { label: '关注', color: '#faad14', bg: 'rgba(250,173,20,0.1)' },
  red: { label: '预警', color: '#ff4d4f', bg: 'rgba(255,77,79,0.1)' },
};

const MOCK_STORE_ISSUES: StoreIssue[] = [
  { store: '芙蓉路店', level: 'green', score: 92, issues: [], actions: ['继续保持当前运营水平'] },
  { store: '岳麓店', level: 'yellow', score: 72, issues: ['成本率偏高(34.2%)', '下午时段翻台率低'], actions: ['调整采购计划减少浪费', '下午推出茶歇套餐引流'] },
  { store: '星沙店', level: 'yellow', score: 65, issues: ['午市出餐超时频繁', '客诉率上升'], actions: ['增加午市备餐人员', '优化出餐动线'] },
  { store: '河西店', level: 'red', score: 45, issues: ['翻台率连续一周低于2.0', '营收目标完成率仅62%', '员工流失2人'], actions: ['制定促销方案提升客流', '紧急招聘补充人手', '店长本周提交整改方案'] },
  { store: '开福店', level: 'yellow', score: 58, issues: ['食材损耗偏高', '周末人手不足'], actions: ['实施精准备料', '调整排班增加周末人手'] },
];

const MOCK_CASES = [
  { id: 1, title: '芙蓉路店：翻台率提升30%的方法', store: '芙蓉路店', period: '2026年1月', tags: ['翻台率', '排队管理'], summary: '通过优化排队叫号系统和加快清台速度，翻台率从2.5提升至3.2。关键措施：1)引入预点餐 2)清台时间从8分钟压缩至4分钟 3)优化菜品出餐顺序。' },
  { id: 2, title: '岳麓店：成本率从36%降至31%', store: '岳麓店', period: '2025年12月', tags: ['成本控制', '采购优化'], summary: '通过精准备料和供应商谈判，三个月内将食材成本率降低5个百分点。核心：每日销量预测准确率提升至85%，浪费减少40%。' },
  { id: 3, title: '河西店：客诉率下降60%', store: '河西店', period: '2026年2月', tags: ['客户体验', '出餐效率'], summary: '针对出餐超时问题，重新设计后厨动线，增加预制菜比例。出餐时间从平均22分钟降至15分钟，客诉率下降60%。' },
];

const MOCK_REVIEW_SUMMARY = {
  day: { period: '2026-03-27', highlight: '今日整体营收¥28,560，完成目标112%。河西店翻台率持续偏低需重点关注。', score: 78 },
  week: { period: '第13周 (3/21-3/27)', highlight: '本周总营收¥185,200，环比+6.8%。星沙店出餐效率有明显改善。', score: 75 },
  month: { period: '2026年3月', highlight: '本月预计总营收¥740,000，同比+15.2%。新品"酸汤肥牛"表现超预期。', score: 80 },
};

export function ReviewCenterPage() {
  const [period, setPeriod] = useState<ReviewPeriod>('day');
  const [searchCase, setSearchCase] = useState('');

  const summary = MOCK_REVIEW_SUMMARY[period];
  const filteredCases = MOCK_CASES.filter((c) =>
    !searchCase || c.title.includes(searchCase) || c.tags.some((t) => t.includes(searchCase))
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>复盘中心</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['day', 'week', 'month'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === p ? '#FF6B2C' : '#1a2a33',
              color: period === p ? '#fff' : '#999',
            }}>{p === 'day' ? '日复盘' : p === 'week' ? '周复盘' : '月复盘'}</button>
          ))}
        </div>
      </div>

      {/* 复盘摘要 */}
      <div style={{
        background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16,
        borderLeft: '4px solid #FF6B2C',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{summary.period}</div>
          <div style={{
            width: 48, height: 48, borderRadius: '50%',
            border: `3px solid ${summary.score >= 80 ? '#52c41a' : summary.score >= 60 ? '#faad14' : '#ff4d4f'}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18, fontWeight: 'bold',
            color: summary.score >= 80 ? '#52c41a' : summary.score >= 60 ? '#faad14' : '#ff4d4f',
          }}>{summary.score}</div>
        </div>
        <div style={{ fontSize: 13, color: '#ccc', lineHeight: 1.8 }}>{summary.highlight}</div>
      </div>

      {/* 门店问题看板（红黄绿） */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>门店问题看板</h3>

        {/* 红黄绿统计 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          {(['red', 'yellow', 'green'] as HealthLevel[]).map((level) => {
            const count = MOCK_STORE_ISSUES.filter((s) => s.level === level).length;
            return (
              <div key={level} style={{
                flex: 1, padding: 12, borderRadius: 8, textAlign: 'center',
                background: LEVEL_CONFIG[level].bg,
              }}>
                <div style={{ fontSize: 24, fontWeight: 'bold', color: LEVEL_CONFIG[level].color }}>{count}</div>
                <div style={{ fontSize: 11, color: LEVEL_CONFIG[level].color }}>{LEVEL_CONFIG[level].label}</div>
              </div>
            );
          })}
        </div>

        {/* 门店详情列表 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {MOCK_STORE_ISSUES.map((s) => (
            <div key={s.store} style={{
              padding: 14, borderRadius: 8, background: '#0B1A20',
              borderLeft: `3px solid ${LEVEL_CONFIG[s.level].color}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>{s.store}</span>
                  <span style={{
                    padding: '1px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                    background: LEVEL_CONFIG[s.level].bg, color: LEVEL_CONFIG[s.level].color,
                  }}>{LEVEL_CONFIG[s.level].label}</span>
                </div>
                <span style={{ fontSize: 14, fontWeight: 'bold', color: LEVEL_CONFIG[s.level].color }}>{s.score}</span>
              </div>
              {s.issues.length > 0 && (
                <div style={{ marginBottom: 6 }}>
                  {s.issues.map((issue, i) => (
                    <div key={i} style={{ fontSize: 12, color: '#ff9999', marginBottom: 2 }}>- {issue}</div>
                  ))}
                </div>
              )}
              <div>
                {s.actions.map((action, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#999', marginBottom: 2 }}>-> {action}</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 经营案例库 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>经营案例库</h3>
          <input
            placeholder="搜索案例..."
            value={searchCase}
            onChange={(e) => setSearchCase(e.target.value)}
            style={{
              padding: '6px 12px', borderRadius: 6, border: '1px solid #1a2a33',
              background: '#0B1A20', color: '#ccc', fontSize: 12, width: 200, outline: 'none',
            }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filteredCases.map((c) => (
            <div key={c.id} style={{
              padding: 16, borderRadius: 8, background: '#0B1A20',
              border: '1px solid #1a2a33', cursor: 'pointer',
              transition: 'border-color .15s',
            }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>{c.title}</div>
              <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                <span style={{ fontSize: 10, color: '#999' }}>{c.store}</span>
                <span style={{ fontSize: 10, color: '#666' }}>|</span>
                <span style={{ fontSize: 10, color: '#999' }}>{c.period}</span>
                {c.tags.map((t) => (
                  <span key={t} style={{
                    fontSize: 10, padding: '0px 6px', borderRadius: 3,
                    background: 'rgba(255,107,44,0.1)', color: '#FF6B2C',
                  }}>{t}</span>
                ))}
              </div>
              <div style={{ fontSize: 12, color: '#999', lineHeight: 1.6 }}>{c.summary}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
