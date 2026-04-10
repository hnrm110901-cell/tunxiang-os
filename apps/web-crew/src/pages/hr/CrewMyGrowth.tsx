/**
 * 我的成长 — 员工端 PWA
 * 路由: /me/growth
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const T = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  text:     '#E0E0E0',
  muted:    '#64748b',
  dim:      '#334155',
  primary:  '#FF6B35',
  success:  '#30D158',
  warning:  '#FF9F0A',
};

interface SkillTag {
  name: string;
  level: 'beginner' | 'intermediate' | 'advanced';
}

interface TrainingCourse {
  id: string;
  title: string;
  description: string;
  duration_min: number;
  recommended: boolean;
}

interface TrainingRecord {
  id: string;
  course_title: string;
  completed_at: string;
  score: number | null;
}

function buildHeaders(): HeadersInit {
  const tenantId = localStorage.getItem('tenantId') ?? '';
  return {
    'Content-Type': 'application/json',
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };
}

async function apiGet<R>(url: string): Promise<R> {
  const res = await fetch(url, { headers: buildHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json() as { ok: boolean; data: R };
  if (!json.ok) throw new Error('API error');
  return json.data;
}

const levelConfig: Record<SkillTag['level'], { label: string; color: string }> = {
  beginner:     { label: '初级', color: T.warning },
  intermediate: { label: '中级', color: T.primary },
  advanced:     { label: '高级', color: T.success },
};

export function CrewMyGrowth() {
  const navigate = useNavigate();

  const [skills, setSkills] = useState<SkillTag[]>([]);
  const [courses, setCourses] = useState<TrainingCourse[]>([]);
  const [records, setRecords] = useState<TrainingRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, c, r] = await Promise.allSettled([
        apiGet<SkillTag[]>('/api/v1/growth/skills'),
        apiGet<TrainingCourse[]>('/api/v1/growth/courses'),
        apiGet<TrainingRecord[]>('/api/v1/growth/records'),
      ]);
      if (s.status === 'fulfilled') setSkills(s.value);
      if (c.status === 'fulfilled') setCourses(c.value);
      if (r.status === 'fulfilled') setRecords(r.value);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的成长</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {/* 技能标签 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16, marginBottom: 16,
        border: `1px solid ${T.border}`,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>我的技能</div>
        {skills.length === 0 && <div style={{ fontSize: 14, color: T.muted }}>暂无技能标签</div>}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {skills.map(sk => {
            const lc = levelConfig[sk.level];
            return (
              <span key={sk.name} style={{
                fontSize: 14, padding: '6px 14px', borderRadius: 20,
                background: lc.color + '22', color: lc.color,
                border: `1px solid ${lc.color}40`,
              }}>
                {sk.name} · {lc.label}
              </span>
            );
          })}
        </div>
      </div>

      {/* 推荐培训 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16, marginBottom: 16,
        border: `1px solid ${T.border}`,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>推荐培训</div>
        {courses.length === 0 && <div style={{ fontSize: 14, color: T.muted }}>暂无推荐课程</div>}
        {courses.map(c => (
          <div key={c.id} style={{
            padding: '12px 0', borderBottom: `1px solid ${T.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{c.title}</div>
              {c.recommended && (
                <span style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 4,
                  background: T.primary + '22', color: T.primary,
                }}>推荐</span>
              )}
            </div>
            <div style={{ fontSize: 14, color: T.muted, marginTop: 4 }}>
              {c.description} · {c.duration_min}分钟
            </div>
          </div>
        ))}
      </div>

      {/* 完成记录 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16,
        border: `1px solid ${T.border}`,
      }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>培训完成记录</div>
        {records.length === 0 && <div style={{ fontSize: 14, color: T.muted }}>暂无完成记录</div>}
        {records.map(r => (
          <div key={r.id} style={{
            padding: '10px 0', borderBottom: `1px solid ${T.border}`,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <div>
              <div style={{ fontSize: 16 }}>{r.course_title}</div>
              <div style={{ fontSize: 13, color: T.muted }}>{r.completed_at}</div>
            </div>
            {r.score != null && (
              <span style={{ fontSize: 16, fontWeight: 700, color: T.success }}>{r.score}分</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default CrewMyGrowth;
