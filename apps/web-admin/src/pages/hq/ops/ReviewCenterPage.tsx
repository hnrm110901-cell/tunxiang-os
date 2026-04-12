/**
 * 复盘中心 — 日/周/月复盘、门店问题看板、经营案例库
 * API: GET /api/v1/ops/reviews?status={status}&store_id={storeId}
 *      POST /api/v1/ops/reviews/{id}/submit  { score, notes }
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../../api';

type ReviewPeriod = 'day' | 'week' | 'month';
type HealthLevel = 'green' | 'yellow' | 'red';

interface StoreIssue {
  store: string;
  level: HealthLevel;
  score: number;
  issues: string[];
  actions: string[];
}

interface ReviewSummary {
  period: string;
  highlight: string;
  score: number;
}

interface ReviewCase {
  id: number;
  title: string;
  store: string;
  period: string;
  tags: string[];
  summary: string;
}

interface ReviewData {
  summary: ReviewSummary;
  store_issues: StoreIssue[];
  cases: ReviewCase[];
}

const LEVEL_CONFIG: Record<HealthLevel, { label: string; color: string; bg: string }> = {
  green: { label: '健康', color: '#52c41a', bg: 'rgba(82,196,26,0.1)' },
  yellow: { label: '关注', color: '#faad14', bg: 'rgba(250,173,20,0.1)' },
  red: { label: '预警', color: '#ff4d4f', bg: 'rgba(255,77,79,0.1)' },
};

// 空数据 fallback
const EMPTY_DATA: ReviewData = {
  summary: { period: '-', highlight: '暂无数据', score: 0 },
  store_issues: [],
  cases: [],
};

export function ReviewCenterPage() {
  const [period, setPeriod] = useState<ReviewPeriod>('day');
  const [searchCase, setSearchCase] = useState('');
  const [data, setData] = useState<ReviewData>(EMPTY_DATA);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await txFetchData<ReviewData>(
        `/api/v1/ops/reviews?status=${period}`
      );
      setData(res ?? EMPTY_DATA);
    } catch {
      setData(EMPTY_DATA);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { load(); }, [load]);

  const { summary, store_issues, cases } = data;

  const filteredCases = cases.filter((c) =>
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

      {loading && (
        <div style={{ textAlign: 'center', color: '#999', padding: 16, fontSize: 13 }}>加载中...</div>
      )}

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
            const count = store_issues.filter((s) => s.level === level).length;
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
        {store_issues.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#666', padding: 24, fontSize: 13 }}>暂无问题门店数据</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {store_issues.map((s) => (
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
                    <div key={i} style={{ fontSize: 12, color: '#999', marginBottom: 2 }}>{'-> '}{action}</div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
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
        {filteredCases.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#666', padding: 24, fontSize: 13 }}>暂无案例数据</div>
        ) : (
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
        )}
      </div>
    </div>
  );
}
