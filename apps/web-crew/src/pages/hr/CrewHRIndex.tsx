/**
 * HR入口页 — 员工端 PWA（人力Tab下的索引）
 * 路由: /me/hr
 */
import { useNavigate } from 'react-router-dom';

const T = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  text:     '#E0E0E0',
  muted:    '#64748b',
  primary:  '#FF6B35',
};

interface HREntry {
  icon: string;
  name: string;
  desc: string;
  path: string;
}

const entries: HREntry[] = [
  { icon: '📅', name: '我的班表',  desc: '本周排班与调班',    path: '/me/schedule' },
  { icon: '⏰', name: '打卡',      desc: '上班/下班打卡',     path: '/schedule-clock' },
  { icon: '📝', name: '请假',      desc: '请假申请与余额',    path: '/me/leave' },
  { icon: '📊', name: '考勤',      desc: '出勤记录与申诉',    path: '/me/attendance' },
  { icon: '🏆', name: '绩效',      desc: '评分与排名',        path: '/me/performance' },
  { icon: '💎', name: '积分',      desc: '积分余额与流水',    path: '/me/points' },
  { icon: '💰', name: '工资',      desc: '月度工资单',        path: '/me/payroll' },
  { icon: '📚', name: '成长',      desc: '技能与培训',        path: '/me/growth' },
  { icon: '📋', name: '证照',      desc: '健康证与合同',      path: '/me/compliance' },
];

export function CrewHRIndex() {
  const navigate = useNavigate();

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 16 }}>人力服务</h1>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {entries.map(e => (
          <div
            key={e.path}
            style={{
              background: T.card, borderRadius: 12, padding: 16,
              border: `1px solid ${T.border}`, cursor: 'pointer',
              minHeight: 48, display: 'flex', flexDirection: 'column',
              justifyContent: 'center',
            }}
            onClick={() => navigate(e.path)}
          >
            <div style={{ fontSize: 28, marginBottom: 8 }}>{e.icon}</div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{e.name}</div>
            <div style={{ fontSize: 13, color: T.muted, marginTop: 4 }}>{e.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default CrewHRIndex;
