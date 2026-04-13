/**
 * 知识文档列表页 — 查看、筛选、发布文档
 */
import { useState } from 'react';
import { Card, Table, Tag, Space, Button, Input, Select, Typography } from 'antd';
import {
  FileTextOutlined,
  SearchOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EditOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Text } = Typography;

const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  info: '#185FA5',
  textSub: '#5F5E5A',
};

interface KnowledgeDocument {
  id: string;
  title: string;
  collection: string;
  status: 'draft' | 'published' | 'archived';
  chunks_count: number;
  updated_at: string;
}

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  published: { color: 'green', label: '已发布' },
  draft: { color: 'orange', label: '草稿' },
  archived: { color: 'default', label: '已归档' },
};

// Mock 数据
const MOCK_DOCS: KnowledgeDocument[] = [
  { id: '1', title: '剁椒鱼头标准制作流程', collection: '菜品知识', status: 'published', chunks_count: 12, updated_at: '2026-04-10T10:30:00Z' },
  { id: '2', title: '门店日清日结操作规范', collection: '运营SOP', status: 'published', chunks_count: 8, updated_at: '2026-04-09T14:20:00Z' },
  { id: '3', title: '食品安全自检手册 v3.0', collection: '食安标准', status: 'published', chunks_count: 24, updated_at: '2026-03-15T09:00:00Z' },
  { id: '4', title: '新员工入职培训指南', collection: '培训手册', status: 'draft', chunks_count: 0, updated_at: '2026-04-11T16:45:00Z' },
  { id: '5', title: '商米T2打印机故障排查', collection: '设备维护', status: 'published', chunks_count: 6, updated_at: '2026-02-20T11:00:00Z' },
  { id: '6', title: '会员储值活动话术模板', collection: '运营SOP', status: 'archived', chunks_count: 4, updated_at: '2026-01-05T08:30:00Z' },
];

const columns = [
  {
    title: '文档标题',
    dataIndex: 'title',
    key: 'title',
    render: (text: string) => (
      <Space>
        <FileTextOutlined style={{ color: C.info }} />
        <span style={{ fontWeight: 500 }}>{text}</span>
      </Space>
    ),
  },
  {
    title: '集合',
    dataIndex: 'collection',
    key: 'collection',
    render: (text: string) => <Tag color="blue">{text}</Tag>,
  },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    render: (status: string) => {
      const cfg = STATUS_MAP[status] || STATUS_MAP.draft;
      return <Tag color={cfg.color}>{cfg.label}</Tag>;
    },
  },
  {
    title: '知识块数',
    dataIndex: 'chunks_count',
    key: 'chunks_count',
    render: (count: number) => (
      <Text style={{ color: count > 0 ? C.success : C.warning }}>
        {count} 条
      </Text>
    ),
  },
  {
    title: '更新时间',
    dataIndex: 'updated_at',
    key: 'updated_at',
    render: (ts: string) => new Date(ts).toLocaleDateString('zh-CN'),
  },
  {
    title: '操作',
    key: 'actions',
    render: (_: unknown, record: KnowledgeDocument) => (
      <Space>
        {record.status === 'draft' && (
          <Button type="link" size="small" icon={<CheckCircleOutlined />}>
            发布
          </Button>
        )}
        <Button type="link" size="small" icon={<EditOutlined />}>
          编辑
        </Button>
      </Space>
    ),
  },
];

export default function DocumentListPage() {
  const navigate = useNavigate();
  const [searchText, setSearchText] = useState('');
  const [filterCollection, setFilterCollection] = useState<string | undefined>();

  const filteredDocs = MOCK_DOCS.filter((doc) => {
    const matchText = !searchText || doc.title.includes(searchText);
    const matchCollection = !filterCollection || doc.collection === filterCollection;
    return matchText && matchCollection;
  });

  const collections = [...new Set(MOCK_DOCS.map((d) => d.collection))];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>文档管理</h2>
          <Text style={{ fontSize: 13, color: C.textSub }}>管理知识库中的所有文档</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} size="small">刷新</Button>
          <Button type="primary" icon={<FileTextOutlined />} onClick={() => navigate('/knowledge/upload')}>
            上传文档
          </Button>
        </Space>
      </div>

      <Card>
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <Input
            placeholder="搜索文档标题..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 280 }}
            allowClear
          />
          <Select
            placeholder="筛选集合"
            allowClear
            value={filterCollection}
            onChange={setFilterCollection}
            style={{ width: 160 }}
            options={collections.map((c) => ({ label: c, value: c }))}
          />
        </div>
        <Table
          columns={columns}
          dataSource={filteredDocs}
          rowKey="id"
          pagination={{ pageSize: 10 }}
          size="middle"
        />
      </Card>
    </div>
  );
}
