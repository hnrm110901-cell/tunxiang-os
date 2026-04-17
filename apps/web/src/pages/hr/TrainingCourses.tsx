/**
 * 培训课程管理页 — D11 Must-Fix P0
 *
 * 功能：
 *   · 课程列表（antd Table）
 *   · 新增 / 编辑课程（Drawer + Form）
 *   · 停用课程（软删除）
 *   · 跳转课件维护（暂以 Drawer 内列表方式简易呈现）
 *
 * 后端：/api/v1/hr/training/courses
 * 路由：/hr/training/courses
 */
import React, { useEffect, useState } from 'react';
import {
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
  Popconfirm,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import apiClient from '../../services/api';

interface TrainingCourse {
  id: string;
  title: string;
  description?: string;
  category: string;
  course_type: string;
  duration_minutes: number;
  content_url?: string;
  credits: number;
  is_mandatory: boolean;
  is_active: boolean;
  store_id?: string | null;
}

const CATEGORY_OPTIONS = [
  { label: '食品安全', value: 'safety' },
  { label: '服务礼仪', value: 'service' },
  { label: '厨艺出品', value: 'cooking' },
  { label: '管理运营', value: 'management' },
  { label: '企业文化', value: 'culture' },
];

const COURSE_TYPE_OPTIONS = [
  { label: '线上', value: 'online' },
  { label: '线下', value: 'offline' },
  { label: '实操', value: 'practice' },
];

const DEFAULT_BRAND_ID = 'B001'; // TODO: 接入全局 brand context 后替换

const TrainingCoursesPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<TrainingCourse[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  const loadCourses = async () => {
    setLoading(true);
    try {
      const resp = await apiClient.get('/api/v1/hr/training/courses', {
        params: { brand_id: DEFAULT_BRAND_ID, is_active: true },
      });
      setData(resp.data?.data || []);
    } catch (err: any) {
      message.error('加载课程失败：' + (err?.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCourses();
  }, []);

  const openCreate = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({
      category: 'safety',
      course_type: 'online',
      duration_minutes: 60,
      credits: 1,
      is_mandatory: false,
      pass_score: 60,
    });
    setDrawerOpen(true);
  };

  const openEdit = (record: TrainingCourse) => {
    setEditingId(record.id);
    form.setFieldsValue(record);
    setDrawerOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingId) {
        await apiClient.put(`/api/v1/hr/training/courses/${editingId}`, values);
        message.success('已更新');
      } else {
        await apiClient.post('/api/v1/hr/training/courses', {
          ...values,
          brand_id: DEFAULT_BRAND_ID,
        });
        message.success('已创建');
      }
      setDrawerOpen(false);
      loadCourses();
    } catch (err: any) {
      if (err?.errorFields) return; // 表单校验错误
      message.error('保存失败：' + (err?.message || '未知错误'));
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiClient.delete(`/api/v1/hr/training/courses/${id}`);
      message.success('已停用');
      loadCourses();
    } catch (err: any) {
      message.error('停用失败：' + (err?.message || '未知错误'));
    }
  };

  const columns: ColumnsType<TrainingCourse> = [
    { title: '课程名称', dataIndex: 'title', key: 'title', width: 220 },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      render: (v: string) => CATEGORY_OPTIONS.find(o => o.value === v)?.label || v,
    },
    {
      title: '类型',
      dataIndex: 'course_type',
      key: 'course_type',
      width: 80,
      render: (v: string) => COURSE_TYPE_OPTIONS.find(o => o.value === v)?.label || v,
    },
    { title: '时长(分钟)', dataIndex: 'duration_minutes', key: 'duration_minutes', width: 100 },
    { title: '学分', dataIndex: 'credits', key: 'credits', width: 80 },
    {
      title: '必修',
      dataIndex: 'is_mandatory',
      key: 'is_mandatory',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="red">必修</Tag> : <Tag>选修</Tag>),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: unknown, record: TrainingCourse) => (
        <Space>
          <Button type="link" onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确认停用该课程？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" danger>停用</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>培训课程管理</h2>
        <Space>
          <Button onClick={loadCourses}>刷新</Button>
          <Button type="primary" onClick={openCreate}>新建课程</Button>
        </Space>
      </div>

      <Table<TrainingCourse>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 20 }}
      />

      <Drawer
        title={editingId ? '编辑课程' : '新建课程'}
        width={520}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" onClick={handleSubmit}>保存</Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="课程名称" rules={[{ required: true, message: '请输入课程名称' }]}>
            <Input placeholder="如：食品安全基础培训" />
          </Form.Item>
          <Form.Item name="description" label="课程描述">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="category" label="分类" rules={[{ required: true }]}>
            <Select options={CATEGORY_OPTIONS} />
          </Form.Item>
          <Form.Item name="course_type" label="授课类型" rules={[{ required: true }]}>
            <Select options={COURSE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="duration_minutes" label="时长（分钟）" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="content_url" label="课件链接（视频/PDF URL）">
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item name="pass_score" label="及格分">
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="credits" label="学分">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_mandatory" label="是否必修" valuePropName="checked">
            <Switch />
          </Form.Item>
          {editingId && (
            <Form.Item name="is_active" label="是否启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Drawer>
    </div>
  );
};

export default TrainingCoursesPage;
