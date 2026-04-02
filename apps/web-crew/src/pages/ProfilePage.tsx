/**
 * 个人中心 — 员工信息、本月绩效、排班日历占位
 */
import { useNavigate } from 'react-router-dom';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

/* ---------- Mock 数据 ---------- */
const employee = {
  name: '张小明',
  role: '值班店长',
  store: '尝在一起 · 万达店',
  employeeId: 'TX-20240318',
  phone: '138****6789',
  joinDate: '2024-03-18',
};

const kpis = [
  { label: '本月出勤', value: '22 / 26 天', pct: 85 },
  { label: '巡航完成率', value: '96%', pct: 96 },
  { label: '整改关闭率', value: '88%', pct: 88 },
  { label: '客诉处理时效', value: '平均 4.2 分钟', pct: 78 },
];

/* 简化排班日历 — 当月数据 */
const scheduleWeeks = [
  ['一', '二', '三', '四', '五', '六', '日'],
];
const scheduleDays = [
  { day: 1, shift: 'A' }, { day: 2, shift: 'A' }, { day: 3, shift: 'B' },
  { day: 4, shift: 'A' }, { day: 5, shift: 'off' }, { day: 6, shift: 'A' },
  { day: 7, shift: 'B' }, { day: 8, shift: 'A' }, { day: 9, shift: 'A' },
  { day: 10, shift: 'A' }, { day: 11, shift: 'B' }, { day: 12, shift: 'off' },
  { day: 13, shift: 'A' }, { day: 14, shift: 'A' }, { day: 15, shift: 'B' },
  { day: 16, shift: 'A' }, { day: 17, shift: 'A' }, { day: 18, shift: 'A' },
  { day: 19, shift: 'off' }, { day: 20, shift: 'B' }, { day: 21, shift: 'A' },
  { day: 22, shift: 'A' }, { day: 23, shift: 'A' }, { day: 24, shift: 'B' },
  { day: 25, shift: 'A' }, { day: 26, shift: 'off' }, { day: 27, shift: 'A' },
  { day: 28, shift: 'A' }, { day: 29, shift: 'B' }, { day: 30, shift: 'A' },
  { day: 31, shift: 'A' },
];

function shiftColor(shift: string) {
  if (shift === 'A') return C.accent;
  if (shift === 'B') return C.green;
  return C.muted;
}

function shiftLabel(shift: string) {
  if (shift === 'A') return 'A';
  if (shift === 'B') return 'B';
  return '休';
}

/* ---------- 组件 ---------- */
export function ProfilePage() {
  const navigate = useNavigate();
  const role = (window as any).__STAFF_ROLE__;
  const isManager = role === 'manager' || role === 'owner';
  const todayRank = 2;
  const totalStaff = 5;

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      {/* 员工信息卡 */}
      <div style={{
        background: C.card, borderRadius: 12, padding: 16, marginBottom: 16,
        border: `1px solid ${C.border}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {/* 头像占位 */}
          <div style={{
            width: 56, height: 56, borderRadius: '50%',
            background: `linear-gradient(135deg, ${C.accent}, ${C.green})`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22, fontWeight: 700, color: C.white, flexShrink: 0,
          }}>
            {employee.name.slice(-2)}
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.white }}>
              {employee.name}
            </div>
            <div style={{ fontSize: 14, color: C.accent, marginTop: 2 }}>
              {employee.role}
            </div>
            <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
              {employee.store}
            </div>
          </div>
        </div>

        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr',
          gap: '8px 16px', marginTop: 14, paddingTop: 14,
          borderTop: `1px solid ${C.border}`,
        }}>
          <div>
            <div style={{ fontSize: 12, color: C.muted }}>工号</div>
            <div style={{ fontSize: 14, color: C.text }}>{employee.employeeId}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: C.muted }}>手机</div>
            <div style={{ fontSize: 14, color: C.text }}>{employee.phone}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: C.muted }}>入职日期</div>
            <div style={{ fontSize: 14, color: C.text }}>{employee.joinDate}</div>
          </div>
        </div>
      </div>

      {/* 管理驾驶舱入口（店长/老板专属） */}
      {isManager && (
        <button
          onClick={() => navigate('/manager-app')}
          style={{
            width: '100%', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center',
            gap: 10, background: C.accent, borderRadius: 12, marginBottom: 16,
            border: 'none', cursor: 'pointer',
          }}
        >
          <span style={{ fontSize: 22 }}>🏪</span>
          <span style={{ fontSize: 17, fontWeight: 700, color: C.white }}>管理驾驶舱</span>
          <span style={{ fontSize: 18, color: `${C.white}80` }}>›</span>
        </button>
      )}

      {/* 集团驾驶舱入口（店长/老板专属） */}
      {isManager && (
        <button
          onClick={() => navigate('/group-dashboard')}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: C.card, borderRadius: 12, padding: '14px 16px', marginBottom: 16,
            border: `1px solid ${C.border}`, cursor: 'pointer', textAlign: 'left',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: `${C.accent}22`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, flexShrink: 0,
            }}>
              📡
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.white }}>集团驾驶舱</div>
              <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
                跨店实时营收与异常告警
              </div>
            </div>
          </div>
          <span style={{ fontSize: 18, color: C.muted }}>›</span>
        </button>
      )}

      {/* 会员等级配置入口（店长/老板专属） */}
      {isManager && (
        <button
          onClick={() => navigate('/member-level-config')}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: C.card, borderRadius: 12, padding: '14px 16px', marginBottom: 16,
            border: `1px solid ${C.border}`, cursor: 'pointer', textAlign: 'left',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: '#facc1522',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, flexShrink: 0,
            }}>
              🥇
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.white }}>会员等级配置</div>
              <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
                配置等级权益与积分规则
              </div>
            </div>
          </div>
          <span style={{ fontSize: 18, color: C.muted }}>›</span>
        </button>
      )}

      {/* 打印机配置入口（店长/老板专属） */}
      {isManager && (
        <button
          onClick={() => navigate('/printer-settings')}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: C.card, borderRadius: 12, padding: '14px 16px', marginBottom: 16,
            border: `1px solid ${C.border}`, cursor: 'pointer', textAlign: 'left',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: `${C.accent}22`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, flexShrink: 0,
            }}>
              🖨
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.white }}>打印机配置</div>
              <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
                配置打印机与菜品路由规则
              </div>
            </div>
          </div>
          <span style={{ fontSize: 18, color: C.muted }}>›</span>
        </button>
      )}

      {/* 预订收件箱入口（所有人可见） */}
      <button
        onClick={() => navigate('/reservations')}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: C.card, borderRadius: 12, padding: '14px 16px', marginBottom: 16,
          border: `1px solid ${C.border}`, cursor: 'pointer', textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: 'rgba(255,107,44,0.15)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 20, flexShrink: 0,
          }}>
            📅
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: C.white }}>预订收件箱</div>
            <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
              美团/大众点评/微信多渠道预订聚合
            </div>
          </div>
        </div>
        <span style={{ fontSize: 18, color: C.muted }}>›</span>
      </button>

      {/* 供应链移动端入口 */}
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: C.muted, margin: '0 0 10px' }}>供应链</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <button
            onClick={() => navigate('/receiving')}
            style={{
              height: 64, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 4,
              background: C.card, borderRadius: 12,
              border: `1px solid ${C.border}`, cursor: 'pointer',
            }}
          >
            <span style={{ fontSize: 22 }}>📦</span>
            <span style={{ fontSize: 15, fontWeight: 600, color: C.white }}>移动收货</span>
          </button>
          <button
            onClick={() => navigate('/stocktake')}
            style={{
              height: 64, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 4,
              background: C.card, borderRadius: 12,
              border: `1px solid ${C.border}`, cursor: 'pointer',
            }}
          >
            <span style={{ fontSize: 22 }}>📋</span>
            <span style={{ fontSize: 15, fontWeight: 600, color: C.white }}>库存盘点</span>
          </button>
        </div>
        {isManager && (
          <button
            onClick={() => navigate('/purchase-approval')}
            style={{
              width: '100%', height: 56, display: 'flex',
              alignItems: 'center', justifyContent: 'center', gap: 10,
              background: C.card, borderRadius: 12, marginTop: 10,
              border: `1px solid ${C.border}`, cursor: 'pointer',
            }}
          >
            <span style={{ fontSize: 20 }}>✅</span>
            <span style={{ fontSize: 16, fontWeight: 600, color: C.white }}>采购审批</span>
            <span style={{ fontSize: 13, color: C.muted }}>（店长专属）</span>
          </button>
        )}
      </div>

      {/* 我的绩效入口卡 */}
      <button
        onClick={() => navigate('/crew-stats')}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: C.card, borderRadius: 12, padding: '14px 16px', marginBottom: 16,
          border: `1px solid ${C.border}`, borderLeft: `4px solid ${C.accent}`,
          cursor: 'pointer', textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: `${C.accent}22`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 20, flexShrink: 0,
          }}>
            📊
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: C.white }}>我的绩效</div>
            <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
              今日第 {todayRank} 名 / 共 {totalStaff} 人
            </div>
          </div>
        </div>
        <span style={{ fontSize: 18, color: C.muted }}>›</span>
      </button>

      {/* 本月绩效 */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '0 0 10px' }}>
        本月绩效
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20 }}>
        {kpis.map(k => (
          <div key={k.label} style={{
            background: C.card, borderRadius: 10, padding: '12px 14px',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontSize: 13, color: C.muted }}>{k.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.white, margin: '6px 0' }}>
              {k.value}
            </div>
            {/* 进度条 */}
            <div style={{ height: 4, borderRadius: 2, background: C.border, overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: 2,
                width: `${k.pct}%`,
                background: k.pct >= 90 ? C.green : k.pct >= 70 ? C.accent : '#ef4444',
              }} />
            </div>
          </div>
        ))}
      </div>

      {/* 排班日历 */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '0 0 10px' }}>
        本月排班
      </h2>
      <div style={{
        background: C.card, borderRadius: 12, padding: 14,
        border: `1px solid ${C.border}`,
      }}>
        {/* 星期头 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4, marginBottom: 6 }}>
          {scheduleWeeks[0].map(d => (
            <div key={d} style={{ textAlign: 'center', fontSize: 12, color: C.muted, padding: '4px 0' }}>
              {d}
            </div>
          ))}
        </div>

        {/* 日期格子 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
          {/* 补齐前面的空白（假设 1 号是周六，偏移 5 格） */}
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={`pad-${i}`} />
          ))}
          {scheduleDays.map(sd => (
            <div key={sd.day} style={{
              textAlign: 'center', padding: '6px 0', borderRadius: 6,
              background: sd.day === 22 ? `${C.accent}22` : 'transparent',
              border: sd.day === 22 ? `1px solid ${C.accent}` : '1px solid transparent',
            }}>
              <div style={{ fontSize: 13, color: C.text }}>{sd.day}</div>
              <div style={{
                fontSize: 11, fontWeight: 600,
                color: shiftColor(sd.shift),
                marginTop: 1,
              }}>
                {shiftLabel(sd.shift)}
              </div>
            </div>
          ))}
        </div>

        {/* 图例 */}
        <div style={{
          display: 'flex', gap: 16, marginTop: 12, paddingTop: 10,
          borderTop: `1px solid ${C.border}`,
        }}>
          {[
            { label: 'A 班（早班）', color: C.accent },
            { label: 'B 班（晚班）', color: C.green },
            { label: '休息', color: C.muted },
          ].map(l => (
            <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: C.muted }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: l.color, display: 'inline-block' }} />
              {l.label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
