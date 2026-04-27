import { useParams, useNavigate } from 'react-router-dom'
import { Card, Tabs, Tag, Descriptions, Button, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { getApplication } from '@/api/applications'
import { RESOURCE_TYPE_LABELS, RESOURCE_TYPE_COLORS } from '@/types/application'

export default function AppDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['devforge', 'application', id],
    queryFn: () => getApplication(id),
    enabled: !!id,
  })

  if (isLoading) return <Spin />
  if (!data) return <Card>应用不存在</Card>

  return (
    <div>
      <Button
        type="text"
        icon={<ArrowLeft size={14} />}
        onClick={() => navigate('/apps')}
        style={{ marginBottom: 12 }}
      >
        返回列表
      </Button>

      <Card
        title={
          <span>
            <span className="mono" style={{ color: '#94a3b8', marginRight: 12 }}>
              {data.code}
            </span>
            {data.name}{' '}
            <Tag color={RESOURCE_TYPE_COLORS[data.resource_type]}>
              {RESOURCE_TYPE_LABELS[data.resource_type]}
            </Tag>
          </span>
        }
      >
        <Descriptions column={2} size="small">
          <Descriptions.Item label="负责人">{data.owner ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="技术栈">{data.tech_stack ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="代码路径" span={2}>
            <code>{data.repo_path ?? '—'}</code>
          </Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>
            {data.description ?? '—'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Tabs
        style={{ marginTop: 16 }}
        defaultActiveKey="overview"
        items={[
          { key: 'overview', label: '概览', children: <PlaceholderPanel name="概览" /> },
          { key: 'pipeline', label: '流水线', children: <PlaceholderPanel name="流水线" /> },
          { key: 'artifact', label: '制品', children: <PlaceholderPanel name="制品" /> },
          { key: 'deploy', label: '部署', children: <PlaceholderPanel name="部署" /> },
          { key: 'config', label: '配置', children: <PlaceholderPanel name="配置" /> },
          { key: 'observe', label: '可观测', children: <PlaceholderPanel name="可观测" /> },
          { key: 'security', label: '安全', children: <PlaceholderPanel name="安全" /> },
          { key: 'settings', label: '设置', children: <PlaceholderPanel name="设置" /> },
        ]}
      />
    </div>
  )
}

function PlaceholderPanel({ name }: { name: string }) {
  return <Card>{name} Tab — TODO：Day-2 实装</Card>
}
