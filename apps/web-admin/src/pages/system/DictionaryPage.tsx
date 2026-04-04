/**
 * DictionaryPage -- 数据字典管理
 * 域F . 系统设置 . 数据字典管理
 *
 * 左侧：字典列表（搜索+卡片列表+新建）
 * 右侧：字典项管理（ProTable + 拖拽排序 + 新增/编辑 ModalForm）
 *
 * API: gateway :8000, try/catch 降级 Mock
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  ColorPicker,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  BookOutlined,
  DeleteOutlined,
  EditOutlined,
  HolderOutlined,
  LockOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProFormDigit,
  ProTable,
} from '@ant-design/pro-components';

const { Title, Text } = Typography;

const BASE = 'http://localhost:8000';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Types
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface Dictionary {
  id: string;
  code: string;
  name: string;
  description: string;
  is_system: boolean;
  is_enabled: boolean;
  item_count: number;
  created_at: string;
}

interface DictionaryItem {
  id: string;
  dictionary_id: string;
  code: string;
  label: string;
  value: string;
  color: string | null;
  icon: string | null;
  sort_order: number;
  is_enabled: boolean;
  created_at: string;
}

// Mock 数据已移除，由 API 提供数据

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DICT_HEADERS = () => ({
  'Content-Type': 'application/json',
  'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
});

async function fetchDictionaries(): Promise<Dictionary[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/dictionaries`, { headers: DICT_HEADERS() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) return json.data.items ?? json.data ?? [];
  } catch { /* API 不可用时返回空数组 */ }
  return [];
}

async function fetchDictionaryItems(code: string): Promise<DictionaryItem[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/dictionaries/${code}/items`, { headers: DICT_HEADERS() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) return json.data.items ?? json.data ?? [];
  } catch { /* API 不可用时返回空数组 */ }
  return [];
}

async function updateDictionaryItem(
  dictCode: string,
  itemId: string,
  payload: { label?: string; value?: string; sort_order?: number; is_enabled?: boolean; color?: string },
): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/dictionaries/${dictCode}/items/${itemId}`, {
      method: 'PATCH',
      headers: DICT_HEADERS(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return json.ok === true;
  } catch { /* API 不可用 */ }
  return false;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Component
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function DictionaryPage() {
  const [dictionaries, setDictionaries] = useState<Dictionary[]>([]);
  const [selectedDict, setSelectedDict] = useState<Dictionary | null>(null);
  const [items, setItems] = useState<DictionaryItem[]>([]);
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(false);
  const [dictModalOpen, setDictModalOpen] = useState(false);
  const [editingDict, setEditingDict] = useState<Dictionary | null>(null);
  const tableRef = useRef<ActionType>();

  // load dictionaries
  useEffect(() => {
    fetchDictionaries().then(setDictionaries);
  }, []);

  // load items when dict selected
  useEffect(() => {
    if (!selectedDict) {
      setItems([]);
      return;
    }
    setLoading(true);
    fetchDictionaryItems(selectedDict.code).then((data) => {
      setItems(data);
      setLoading(false);
    });
  }, [selectedDict]);

  const filteredDicts = dictionaries.filter(
    (d) =>
      d.name.includes(searchText) ||
      d.code.includes(searchText) ||
      d.description.includes(searchText),
  );

  const handleToggleEnabled = useCallback(
    async (dict: Dictionary, checked: boolean) => {
      // 乐观更新
      setDictionaries((prev) =>
        prev.map((d) => (d.id === dict.id ? { ...d, is_enabled: checked } : d)),
      );
      try {
        const res = await fetch(`${BASE}/api/v1/system/dictionaries/${dict.code}`, {
          method: 'PATCH',
          headers: DICT_HEADERS(),
          body: JSON.stringify({ is_enabled: checked }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch { /* 乐观更新已完成，API 失败时保持本地状态 */ }
      message.success(`${dict.name} 已${checked ? '启用' : '停用'}`);
    },
    [],
  );

  const handleDeleteDict = useCallback(
    (dict: Dictionary) => {
      if (dict.is_system) {
        message.error('系统字典不可删除');
        return;
      }
      setDictionaries((prev) => prev.filter((d) => d.id !== dict.id));
      if (selectedDict?.id === dict.id) {
        setSelectedDict(null);
      }
      message.success(`已删除字典: ${dict.name}`);
    },
    [selectedDict],
  );

  const handleSaveDict = useCallback(
    (values: Record<string, string | boolean>) => {
      if (editingDict) {
        setDictionaries((prev) =>
          prev.map((d) =>
            d.id === editingDict.id ? { ...d, ...values } as Dictionary : d,
          ),
        );
        message.success('字典已更新');
      } else {
        const newDict: Dictionary = {
          id: String(Date.now()),
          code: values.code as string,
          name: values.name as string,
          description: (values.description as string) || '',
          is_system: false,
          is_enabled: true,
          item_count: 0,
          created_at: new Date().toISOString().slice(0, 10),
        };
        setDictionaries((prev) => [...prev, newDict]);
        message.success('字典已创建');
      }
      setDictModalOpen(false);
      setEditingDict(null);
    },
    [editingDict],
  );

  // item drag sort (swap positions)
  const handleDragSort = useCallback(
    (dragIndex: number, dropIndex: number) => {
      setItems((prev) => {
        const next = [...prev];
        const [removed] = next.splice(dragIndex, 1);
        next.splice(dropIndex, 0, removed);
        return next.map((item, idx) => ({ ...item, sort_order: idx + 1 }));
      });
      message.success('排序已更新');
    },
    [],
  );

  // ── Item columns ──
  const itemColumns: ProColumns<DictionaryItem>[] = [
    {
      title: '',
      dataIndex: 'sort',
      width: 40,
      render: () => <HolderOutlined style={{ cursor: 'grab', color: '#999' }} />,
      search: false,
    },
    {
      title: '项名称',
      dataIndex: 'label',
      width: 120,
    },
    {
      title: '编码',
      dataIndex: 'code',
      width: 120,
      render: (_, record) => <Tag>{record.code}</Tag>,
    },
    {
      title: '值',
      dataIndex: 'value',
      width: 100,
    },
    {
      title: '颜色',
      dataIndex: 'color',
      width: 80,
      search: false,
      render: (_, record) =>
        record.color ? (
          <Space>
            <span
              style={{
                display: 'inline-block',
                width: 14,
                height: 14,
                borderRadius: '50%',
                backgroundColor: record.color,
                verticalAlign: 'middle',
              }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.color}
            </Text>
          </Space>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '图标',
      dataIndex: 'icon',
      width: 80,
      search: false,
      render: (_, record) =>
        record.icon ? <Tag>{record.icon}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      width: 60,
      search: false,
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      width: 70,
      search: false,
      render: (_, record) => (
        <Switch
          size="small"
          checked={record.is_enabled}
          onChange={async (checked) => {
            setItems((prev) =>
              prev.map((it) =>
                it.id === record.id ? { ...it, is_enabled: checked } : it,
              ),
            );
            if (selectedDict) {
              await updateDictionaryItem(selectedDict.code, record.id, { is_enabled: checked });
            }
          }}
        />
      ),
    },
    {
      title: '操作',
      width: 100,
      search: false,
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除此字典项?"
            onConfirm={() => {
              setItems((prev) => prev.filter((it) => it.id !== record.id));
              message.success('字典项已删除');
            }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 120px)' }}>
      {/* ── 左侧：字典列表 (30%) ── */}
      <Card
        title={
          <Space>
            <BookOutlined />
            <span>数据字典</span>
          </Space>
        }
        extra={
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditingDict(null);
              setDictModalOpen(true);
            }}
          >
            新建
          </Button>
        }
        style={{ width: '30%', overflow: 'auto' }}
        bodyStyle={{ padding: '12px' }}
      >
        <Input
          placeholder="搜索字典名称/编码..."
          prefix={<SearchOutlined />}
          allowClear
          style={{ marginBottom: 12 }}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />

        <List
          dataSource={filteredDicts}
          locale={{ emptyText: <Empty description="暂无字典" /> }}
          renderItem={(dict) => (
            <Card
              size="small"
              hoverable
              style={{
                marginBottom: 8,
                borderColor:
                  selectedDict?.id === dict.id ? '#FF6B35' : undefined,
                borderWidth: selectedDict?.id === dict.id ? 2 : 1,
              }}
              bodyStyle={{ padding: '10px 12px' }}
              onClick={() => setSelectedDict(dict)}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 4,
                }}
              >
                <Space size={4}>
                  <Text strong>{dict.name}</Text>
                  {dict.is_system && (
                    <Tooltip title="系统字典，不可删除">
                      <LockOutlined style={{ color: '#999', fontSize: 12 }} />
                    </Tooltip>
                  )}
                </Space>
                <Switch
                  size="small"
                  checked={dict.is_enabled}
                  onChange={(checked, e) => {
                    e.stopPropagation();
                    handleToggleEnabled(dict, checked);
                  }}
                />
              </div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <Tag style={{ fontSize: 11 }}>{dict.code}</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {dict.item_count} 项
                </Text>
              </div>
              {dict.description && (
                <Text
                  type="secondary"
                  style={{ fontSize: 12, display: 'block', marginTop: 4 }}
                >
                  {dict.description}
                </Text>
              )}
            </Card>
          )}
        />
      </Card>

      {/* ── 右侧：字典项管理 (70%) ── */}
      <Card
        title={
          selectedDict ? (
            <Space>
              <span>{selectedDict.name}</span>
              <Tag color="default">{selectedDict.code}</Tag>
              <Badge
                count={items.length}
                style={{ backgroundColor: '#FF6B35' }}
              />
            </Space>
          ) : (
            '请选择左侧字典'
          )
        }
        style={{ flex: 1, overflow: 'auto' }}
        bodyStyle={{ padding: selectedDict ? 0 : 24 }}
      >
        {!selectedDict ? (
          <Empty description="请从左侧选择一个字典查看其配置项" />
        ) : (
          <ProTable<DictionaryItem>
            actionRef={tableRef}
            rowKey="id"
            columns={itemColumns}
            dataSource={items}
            loading={loading}
            search={false}
            pagination={false}
            options={{ density: true, reload: false }}
            headerTitle={`${selectedDict.name} - 字典项`}
            toolBarRender={() => [
              <ModalForm<{
                label: string;
                code: string;
                value: string;
                color: string;
                icon: string;
                sort_order: number;
              }>
                key="add-item"
                title="新增字典项"
                trigger={
                  <Button type="primary" icon={<PlusOutlined />}>
                    新增字典项
                  </Button>
                }
                modalProps={{ destroyOnClose: true }}
                onFinish={async (values) => {
                  const newItem: DictionaryItem = {
                    id: String(Date.now()),
                    dictionary_id: selectedDict.id,
                    code: values.code,
                    label: values.label,
                    value: values.value,
                    color: values.color || null,
                    icon: values.icon || null,
                    sort_order: values.sort_order ?? items.length + 1,
                    is_enabled: true,
                    created_at: new Date().toISOString().slice(0, 10),
                  };
                  setItems((prev) => [...prev, newItem]);
                  message.success('字典项已添加');
                  return true;
                }}
              >
                <ProFormText
                  name="label"
                  label="项名称"
                  rules={[{ required: true, message: '请输入项名称' }]}
                />
                <ProFormText
                  name="code"
                  label="编码"
                  rules={[{ required: true, message: '请输入编码' }]}
                />
                <ProFormText
                  name="value"
                  label="值"
                  rules={[{ required: true, message: '请输入值' }]}
                />
                <ProFormText name="color" label="颜色 (如 #FF6B35)" />
                <ProFormText name="icon" label="图标 (Ant Design 图标名)" />
                <ProFormDigit
                  name="sort_order"
                  label="排序"
                  initialValue={items.length + 1}
                  min={1}
                />
              </ModalForm>,
            ]}
          />
        )}
      </Card>

      {/* ── 新建/编辑字典 Modal ── */}
      <Modal
        title={editingDict ? '编辑字典' : '新建字典'}
        open={dictModalOpen}
        onCancel={() => {
          setDictModalOpen(false);
          setEditingDict(null);
        }}
        footer={null}
        destroyOnClose
      >
        <ModalForm<{ name: string; code: string; description: string }>
          initialValues={
            editingDict
              ? {
                  name: editingDict.name,
                  code: editingDict.code,
                  description: editingDict.description,
                }
              : undefined
          }
          submitter={{
            searchConfig: { submitText: editingDict ? '保存' : '创建' },
          }}
          onFinish={async (values) => {
            handleSaveDict(values);
            return true;
          }}
        >
          <ProFormText
            name="name"
            label="字典名称"
            rules={[{ required: true, message: '请输入字典名称' }]}
          />
          <ProFormText
            name="code"
            label="字典编码"
            rules={[
              { required: true, message: '请输入字典编码' },
              { pattern: /^[a-z_]+$/, message: '仅允许小写字母和下划线' },
            ]}
            disabled={!!editingDict}
          />
          <ProFormTextArea name="description" label="描述" />
        </ModalForm>
      </Modal>
    </div>
  );
}
