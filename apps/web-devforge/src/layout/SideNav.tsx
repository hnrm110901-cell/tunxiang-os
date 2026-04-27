import { Layout, Menu } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import { MENU } from '@/data/menuConfig'
import { COLORS } from '@/styles/theme'

const { Sider } = Layout

/** 左侧固定 240px 导航 */
export function SideNav() {
  const navigate = useNavigate()
  const location = useLocation()

  const selectedKey =
    MENU.find((m) => location.pathname.startsWith(m.path))?.key ?? 'dashboard'

  return (
    <Sider
      width={240}
      style={{
        height: '100vh',
        position: 'sticky',
        top: 0,
        left: 0,
        background: COLORS.slate900,
        borderRight: `1px solid ${COLORS.slate700}`,
      }}
    >
      <div
        style={{
          padding: '16px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          borderBottom: `1px solid ${COLORS.slate700}`,
          height: 56,
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: COLORS.amber600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            color: '#fff',
            fontSize: 14,
          }}
        >
          屯
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          <strong style={{ color: '#fff', fontSize: 14 }}>DevForge</strong>
          <span style={{ color: '#94a3b8', fontSize: 11 }}>屯象研运平台</span>
        </div>
      </div>

      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[selectedKey]}
        style={{ background: COLORS.slate900, borderRight: 'none', paddingTop: 8 }}
        items={MENU.map((m) => ({
          key: m.key,
          icon: m.icon,
          label: (
            <span style={{ display: 'inline-flex', gap: 8, alignItems: 'baseline' }}>
              <span
                className="mono"
                style={{ color: '#64748b', fontSize: 11, width: 18 }}
              >
                {m.no}
              </span>
              <span>{m.label}</span>
            </span>
          ),
          onClick: () => navigate(m.path),
        }))}
      />
    </Sider>
  )
}
