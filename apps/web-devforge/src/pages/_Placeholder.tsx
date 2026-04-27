import { Card, Typography, Space, Tag } from 'antd'
import { Construction } from 'lucide-react'

const { Title, Paragraph } = Typography

interface Props {
  no: string
  title: string
  description?: string
  todos?: string[]
}

/** 占位页 — Day-1 骨架，所有非 02 应用中心页面共用 */
export function Placeholder({ no, title, description, todos }: Props) {
  return (
    <div>
      <Title level={3} style={{ margin: 0, marginBottom: 16 }}>
        <span className="mono" style={{ color: '#64748b', marginRight: 12 }}>
          {no}
        </span>
        {title}
      </Title>

      <Card>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space>
            <Construction size={18} color="#D97706" />
            <Tag color="orange">Day-1 骨架</Tag>
            <span style={{ color: '#94a3b8' }}>该模块尚在规划中</span>
          </Space>

          {description && <Paragraph style={{ margin: 0 }}>{description}</Paragraph>}

          {todos && todos.length > 0 && (
            <div>
              <strong style={{ color: '#e2e8f0' }}>TODO（待实装）</strong>
              <ul style={{ marginTop: 8, color: '#94a3b8' }}>
                {todos.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </div>
          )}
        </Space>
      </Card>
    </div>
  )
}
