import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import { SideNav } from './SideNav'
import { TopBar } from './TopBar'
import { COLORS } from '@/styles/theme'

const { Content } = Layout

export function AppLayout() {
  return (
    <Layout style={{ minHeight: '100vh', background: COLORS.slate900 }}>
      <SideNav />
      <Layout style={{ background: COLORS.slate900 }}>
        <TopBar />
        <Content
          style={{
            padding: 24,
            background: COLORS.slate900,
            minHeight: 'calc(100vh - 56px)',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
