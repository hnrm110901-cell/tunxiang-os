import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Tag,
  Input,
  Select,
  Space,
  Button,
  Modal,
  Alert,
  Typography,
} from 'antd'
import { Plus, RefreshCw } from 'lucide-react'
import dayjs from 'dayjs'
import { useApplications } from '@/hooks/useApplications'
import {
  RESOURCE_TYPE_LABELS,
  RESOURCE_TYPE_COLORS,
  type Application,
  type ResourceType,
} from '@/types/application'

const { Title } = Typography

export default function AppsPage() {
  const navigate = useNavigate()
  const [resourceType, setResourceType] = useState<ResourceType | undefined>(undefined)
  const [q, setQ] = useState('')
  const [createOpen, setCreateOpen] = useState(false)

  const { data, isLoading, refetch, isFetching } = useApplications({
    resource_type: resourceType,
    q: q || undefined,
  })

  const columns = [
    {
      title: 'CODE',
      dataIndex: 'code',
      key: 'code',
      width: 180,
      render: (code: string, row: Application) => (
        <a onClick={() => navigate(`/apps/${row.id}`)} className="mono">
          {code}
        </a>
      ),
    },
    { title: '名称', dataIndex: 'name', key: 'name', width: 220 },
    {
      title: '资源类型',
      dataIndex: 'resource_type',
      key: 'resource_type',
      width: 130,
      render: (t: ResourceType) => (
        <Tag color={RESOURCE_TYPE_COLORS[t]}>{RESOURCE_TYPE_LABELS[t]}</Tag>
      ),
    },
    { title: '负责人', dataIndex: 'owner', key: 'owner', width: 110 },
    {
      title: '技术栈',
      dataIndex: 'tech_stack',
      key: 'tech_stack',
      width: 110,
      render: (s: string | null) => s ?? '—',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (s: string | null) => s ?? '—',
    },
    {
      title: '更新于',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (t: string) => (
        <span className="mono" style={{ color: '#94a3b8' }}>
          {dayjs(t).format('YYYY-MM-DD HH:mm')}
        </span>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          应用中心
        </Title>
        <Space>
          <Button
            icon={<RefreshCw size={14} />}
            onClick={() => refetch()}
            loading={isFetching}
          >
            刷新
          </Button>
          <Button type="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
            新建应用
          </Button>
        </Space>
      </div>

      {data?.usingMock && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="后端 tx-devforge:8017 未连通，当前展示为 Mock 数据"
        />
      )}

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="资源类型"
          allowClear
          style={{ width: 180 }}
          value={resourceType}
          onChange={setResourceType}
          options={(Object.keys(RESOURCE_TYPE_LABELS) as ResourceType[]).map((t) => ({
            value: t,
            label: RESOURCE_TYPE_LABELS[t],
          }))}
        />
        <Input.Search
          placeholder="搜索 code / 名称 / 描述"
          allowClear
          style={{ width: 320 }}
          onSearch={setQ}
        />
      </Space>

      <Table<Application>
        rowKey="id"
        columns={columns}
        dataSource={data?.items ?? []}
        loading={isLoading}
        pagination={{ total: data?.total ?? 0, pageSize: 20, showSizeChanger: false }}
      />

      <Modal
        open={createOpen}
        title="新建应用"
        onCancel={() => setCreateOpen(false)}
        onOk={() => setCreateOpen(false)}
        okText="提交"
        cancelText="取消"
      >
        <Alert
          type="info"
          showIcon
          message="表单 TODO：接入 createApplication() 后开放（code / name / resource_type / owner / repo_path / tech_stack / description）"
        />
      </Modal>
    </div>
  )
}
