import { useEffect, useState } from 'react'
import { Layout, Breadcrumb, Avatar, Badge, Space, Tooltip } from 'antd'
import { Search, Bell } from 'lucide-react'
import { useLocation, Link } from 'react-router-dom'
import { MENU } from '@/data/menuConfig'
import { EnvSwitcher } from './EnvSwitcher'
import { GlobalSearch } from './GlobalSearch'
import { useUserStore } from '@/stores/user'
import { useEnvStore } from '@/stores/env'
import { COLORS } from '@/styles/theme'

const { Header } = Layout

export function TopBar() {
  const location = useLocation()
  const { user } = useUserStore()
  const { currentEnv } = useEnvStore()
  const [searchOpen, setSearchOpen] = useState(false)

  // ⌘K / Ctrl+K 唤起全局搜索
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey
      if (isMod && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setSearchOpen(true)
      } else if (e.key === 'Escape') {
        setSearchOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const matched = MENU.find((m) => location.pathname.startsWith(m.path))
  const breadcrumbItems = [
    { title: <Link to="/dashboard">DevForge</Link> },
    matched ? { title: matched.label } : { title: '工作台' },
  ]

  const isProd = currentEnv === 'prod'

  return (
    <>
      <Header
        className={isProd ? 'devforge-topbar-prod' : ''}
        style={{
          height: 56,
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: COLORS.slate900,
          borderBottom: `1px solid ${COLORS.slate700}`,
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <Breadcrumb items={breadcrumbItems} />

        <Space size="middle">
          <Tooltip title="⌘K / Ctrl+K">
            <div
              onClick={() => setSearchOpen(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 12px',
                background: COLORS.slate800,
                border: `1px solid ${COLORS.slate700}`,
                borderRadius: 6,
                cursor: 'pointer',
                color: '#94a3b8',
                fontSize: 13,
                minWidth: 220,
              }}
            >
              <Search size={14} />
              <span style={{ flex: 1 }}>全局搜索</span>
              <span
                className="mono"
                style={{
                  fontSize: 11,
                  padding: '1px 6px',
                  background: COLORS.slate900,
                  borderRadius: 4,
                  border: `1px solid ${COLORS.slate700}`,
                }}
              >
                ⌘K
              </span>
            </div>
          </Tooltip>

          <EnvSwitcher />

          <Badge count={3} size="small">
            <Bell size={18} style={{ color: '#94a3b8', cursor: 'pointer' }} />
          </Badge>

          <Space size={8}>
            <Avatar
              size={32}
              style={{ background: COLORS.amber600, fontSize: 13 }}
            >
              {user.name.slice(0, 1)}
            </Avatar>
            <span style={{ color: '#e2e8f0', fontSize: 13 }}>{user.name}</span>
          </Space>
        </Space>
      </Header>

      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  )
}
