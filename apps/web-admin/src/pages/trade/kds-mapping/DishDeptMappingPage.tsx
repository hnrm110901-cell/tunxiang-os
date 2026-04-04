/**
 * 菜品→档口映射管理页
 * 域A KDS 出餐调度 · 档口绑定管理
 *
 * 功能：
 * 1. 左侧：门店选择器 + 档口选择器（Segmented）
 * 2. 右侧 Table：展示当前档口的菜品映射，列：菜品名/分类/是否主档口/优先级/操作（删除）
 * 3. 顶部"批量导入"按钮 → Modal + 菜品多选 → 批量绑定
 * 4. 支持拖拽排序调整 priority（使用 @hello-pangea/dnd 若可用，否则手动上移下移）
 * 5. 未分配档口菜品提示
 *
 * 技术栈：antd 5.x + React 18 TypeScript strict
 * 注意：由于 @hello-pangea/dnd 未在 package.json，使用 antd Table 行拖拽（通过上移/下移按钮实现）
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── Design Token ─────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface KdsDepartment {
  dept_id: string;
  dept_name: string;
  dept_code: string;
  store_id: string;
}

interface DishDeptMapping {
  id: string;
  dish_id: string;
  dish_name: string;
  dish_category: string;
  dept_id: string;
  dept_name: string;
  is_primary: boolean;
  priority: number;
}

interface UnassignedDishInfo {
  unassigned_count: number;
  dish_names: string[];
}

interface CatalogDishOption {
  dish_id: string;
  dish_name: string;
  category: string;
}

// ─── API 函数 ─────────────────────────────────────────────────────────────────

async function fetchDepartments(storeId: string): Promise<{ items: KdsDepartment[]; total: number }> {
  return txFetch(`/api/v1/kds/departments?store_id=${storeId}`);
}

async function fetchMappings(storeId: string, deptId: string): Promise<{ items: DishDeptMapping[]; total: number }> {
  const params = new URLSearchParams({ store_id: storeId, dept_id: deptId });
  return txFetch(`/api/v1/kds/dish-dept-mappings?${params.toString()}`);
}

async function deleteMapping(id: string): Promise<void> {
  return txFetch(`/api/v1/kds/dish-dept-mappings/${id}`, { method: 'DELETE' });
}

async function batchCreateMappings(payload: {
  dept_id: string;
  store_id: string;
  dish_ids: string[];
  is_primary: boolean;
}): Promise<{ created: number }> {
  return txFetch('/api/v1/kds/dish-dept-mappings/batch', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function patchMapping(id: string, payload: Partial<DishDeptMapping>): Promise<DishDeptMapping> {
  return txFetch(`/api/v1/kds/dish-dept-mappings/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

async function fetchUnassignedDishes(storeId: string): Promise<UnassignedDishInfo> {
  return txFetch(`/api/v1/kds/dish-dept-mappings/unassigned?store_id=${storeId}`);
}

async function fetchCatalogDishes(storeId: string, keyword?: string): Promise<{ items: CatalogDishOption[] }> {
  const params = new URLSearchParams({ store_id: storeId });
  if (keyword) params.set('keyword', keyword);
  return txFetch(`/api/v1/menu/dishes?${params.toString()}`);
}

// ─── 门店选项类型 ────────────────────────────────────────────────────────────

interface StoreOption {
  id: string;
  name: string;
}

// ─── 批量导入 Modal ───────────────────────────────────────────────────────────

interface BatchImportModalProps {
  open: boolean;
  onClose: () => void;
  storeId: string;
  deptId: string;
  deptName: string;
  onSuccess: () => void;
}

const BatchImportModal: React.FC<BatchImportModalProps> = ({
  open,
  onClose,
  storeId,
  deptId,
  deptName,
  onSuccess,
}) => {
  const [dishes, setDishes] = useState<CatalogDishOption[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isPrimary, setIsPrimary] = useState(true);
  const [keyword, setKeyword] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);

  const searchDishes = useCallback(async (kw?: string) => {
    if (!storeId) return;
    setSearchLoading(true);
    try {
      const res = await fetchCatalogDishes(storeId, kw);
      setDishes(res.items);
    } catch {
      message.error('搜索菜品失败');
    } finally {
      setSearchLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    if (open) {
      setSelectedIds([]);
      setKeyword('');
      searchDishes();
    }
  }, [open, searchDishes]);

  const handleSearch = (value: string) => {
    setKeyword(value);
    searchDishes(value);
  };

  const handleToggle = (dishId: string) => {
    setSelectedIds((prev) =>
      prev.includes(dishId) ? prev.filter((id) => id !== dishId) : [...prev, dishId],
    );
  };

  const handleSelectAll = () => {
    if (selectedIds.length === dishes.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(dishes.map((d) => d.dish_id));
    }
  };

  const handleSubmit = async () => {
    if (selectedIds.length === 0) {
      message.warning('请至少选择一个菜品');
      return;
    }
    setSubmitLoading(true);
    try {
      const result = await batchCreateMappings({
        dept_id: deptId,
        store_id: storeId,
        dish_ids: selectedIds,
        is_primary: isPrimary,
      });
      message.success(`成功绑定 ${result.created} 个菜品到「${deptName}」`);
      onSuccess();
      onClose();
    } catch {
      message.error('批量绑定失败，请重试');
    } finally {
      setSubmitLoading(false);
    }
  };

  const allSelected = dishes.length > 0 && selectedIds.length === dishes.length;
  const indeterminate = selectedIds.length > 0 && selectedIds.length < dishes.length;

  return (
    <Modal
      title={`批量绑定菜品到「${deptName}」`}
      open={open}
      onCancel={onClose}
      width={600}
      destroyOnClose
      footer={
        <Space>
          <Space style={{ marginRight: 'auto' }}>
            <Text type="secondary">设为主档口：</Text>
            <Switch
              checked={isPrimary}
              onChange={setIsPrimary}
              size="small"
              checkedChildren="是"
              unCheckedChildren="否"
            />
          </Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            loading={submitLoading}
            onClick={handleSubmit}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            disabled={selectedIds.length === 0}
          >
            绑定 {selectedIds.length > 0 ? `(${selectedIds.length})` : ''}
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <Input.Search
          placeholder="搜索菜品名称"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={handleSearch}
          loading={searchLoading}
          allowClear
        />

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Checkbox
            indeterminate={indeterminate}
            checked={allSelected}
            onChange={handleSelectAll}
          >
            全选（{dishes.length} 个菜品）
          </Checkbox>
          <Text type="secondary" style={{ fontSize: 12 }}>已选 {selectedIds.length} 个</Text>
        </div>

        <div
          style={{
            maxHeight: 360,
            overflowY: 'auto',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            padding: '4px 0',
          }}
        >
          {searchLoading ? (
            <div style={{ textAlign: 'center', padding: 32 }}>
              <Spin />
            </div>
          ) : dishes.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: '#999' }}>
              暂无菜品数据
            </div>
          ) : (
            dishes.map((dish) => (
              <div
                key={dish.dish_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '8px 16px',
                  cursor: 'pointer',
                  background: selectedIds.includes(dish.dish_id) ? '#fff8f4' : undefined,
                  borderLeft: selectedIds.includes(dish.dish_id) ? `3px solid ${TX_PRIMARY}` : '3px solid transparent',
                }}
                onClick={() => handleToggle(dish.dish_id)}
              >
                <Checkbox
                  checked={selectedIds.includes(dish.dish_id)}
                  onChange={() => handleToggle(dish.dish_id)}
                  style={{ marginRight: 12 }}
                />
                <div style={{ flex: 1 }}>
                  <Text style={{ fontSize: 14 }}>{dish.dish_name}</Text>
                  <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    {dish.category}
                  </Text>
                </div>
              </div>
            ))
          )}
        </div>
      </Space>
    </Modal>
  );
};

async function fetchStores(): Promise<StoreOption[]> {
  try {
    const res = await txFetch<{ items: StoreOption[] }>('/api/v1/menu/dish-dept-mappings/stores');
    return res?.items ?? [];
  } catch {
    return [];
  }
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function DishDeptMappingPage() {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [storeId, setStoreId] = useState('');
  const [departments, setDepartments] = useState<KdsDepartment[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState<string>('');
  const [mappings, setMappings] = useState<DishDeptMapping[]>([]);
  const [unassigned, setUnassigned] = useState<UnassignedDishInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [deptLoading, setDeptLoading] = useState(false);
  const [batchModalOpen, setBatchModalOpen] = useState(false);

  // 加载档口列表
  const loadDepartments = useCallback(async () => {
    if (!storeId) return;
    setDeptLoading(true);
    try {
      const res = await fetchDepartments(storeId);
      setDepartments(res.items);
      if (res.items.length > 0 && !selectedDeptId) {
        setSelectedDeptId(res.items[0].dept_id);
      }
    } catch {
      message.error('加载档口列表失败');
    } finally {
      setDeptLoading(false);
    }
  }, [storeId, selectedDeptId]);

  // 加载映射列表
  const loadMappings = useCallback(async () => {
    if (!storeId || !selectedDeptId) return;
    setLoading(true);
    try {
      const res = await fetchMappings(storeId, selectedDeptId);
      // 按priority排序
      const sorted = [...res.items].sort((a, b) => a.priority - b.priority);
      setMappings(sorted);
    } catch {
      message.error('加载映射列表失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, selectedDeptId]);

  // 加载未分配菜品信息
  const loadUnassigned = useCallback(async () => {
    if (!storeId) return;
    try {
      const info = await fetchUnassignedDishes(storeId);
      setUnassigned(info);
    } catch {
      // 静默失败
    }
  }, [storeId]);

  // 加载门店列表
  useEffect(() => {
    fetchStores().then((list) => {
      setStores(list);
      if (list.length > 0 && !storeId) {
        setStoreId(list[0].id);
      }
    });
  }, []);

  useEffect(() => {
    if (!storeId) return;
    loadDepartments();
    loadUnassigned();
  }, [storeId]);

  useEffect(() => {
    if (selectedDeptId) loadMappings();
  }, [selectedDeptId, loadMappings]);

  // 切换门店时重置档口选择
  const handleStoreChange = (sid: string) => {
    setStoreId(sid);
    setSelectedDeptId('');
    setMappings([]);
    setDepartments([]);
  };

  // 删除映射
  const handleDelete = async (mapping: DishDeptMapping) => {
    try {
      await deleteMapping(mapping.id);
      message.success(`「${mapping.dish_name}」已从此档口移除`);
      loadMappings();
      loadUnassigned();
    } catch {
      message.error('删除失败');
    }
  };

  // 切换主档口
  const handleTogglePrimary = async (mapping: DishDeptMapping, checked: boolean) => {
    try {
      await patchMapping(mapping.id, { is_primary: checked });
      message.success(`「${mapping.dish_name}」主档口状态已更新`);
      loadMappings();
    } catch {
      message.error('更新失败');
    }
  };

  // 上移 / 下移（调整priority）
  const handleMoveUp = async (index: number) => {
    if (index === 0) return;
    const curr = mappings[index];
    const prev = mappings[index - 1];
    try {
      await Promise.all([
        patchMapping(curr.id, { priority: prev.priority }),
        patchMapping(prev.id, { priority: curr.priority }),
      ]);
      loadMappings();
    } catch {
      message.error('排序调整失败');
    }
  };

  const handleMoveDown = async (index: number) => {
    if (index === mappings.length - 1) return;
    const curr = mappings[index];
    const next = mappings[index + 1];
    try {
      await Promise.all([
        patchMapping(curr.id, { priority: next.priority }),
        patchMapping(next.id, { priority: curr.priority }),
      ]);
      loadMappings();
    } catch {
      message.error('排序调整失败');
    }
  };

  const selectedDept = departments.find((d) => d.dept_id === selectedDeptId);

  const columns: ColumnsType<DishDeptMapping> = [
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 90,
      render: (priority: number, _, index) => (
        <Space size={2}>
          <Button
            type="text"
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={index === 0}
            onClick={() => handleMoveUp(index)}
            style={{ padding: '0 4px' }}
          />
          <Text style={{ fontSize: 12, color: '#999', minWidth: 20, textAlign: 'center' }}>
            {priority}
          </Text>
          <Button
            type="text"
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={index === mappings.length - 1}
            onClick={() => handleMoveDown(index)}
            style={{ padding: '0 4px' }}
          />
        </Space>
      ),
    },
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '分类',
      dataIndex: 'dish_category',
      width: 120,
      render: (cat: string) => cat ? <Tag>{cat}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '是否主档口',
      dataIndex: 'is_primary',
      width: 110,
      render: (isPrimary: boolean, record) => (
        <Switch
          checked={isPrimary}
          size="small"
          onChange={(checked) => handleTogglePrimary(record, checked)}
          checkedChildren="主"
          unCheckedChildren="副"
          style={{ background: isPrimary ? TX_SUCCESS : undefined }}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Popconfirm
          title={`移除「${record.dish_name}」`}
          description="确认从此档口移除该菜品映射？"
          onConfirm={() => handleDelete(record)}
          okText="移除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
          >
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div style={{ minWidth: 1280 }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>菜品→档口映射管理</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>配置菜品绑定到哪个档口出品，支持多档口映射与优先级排序</Text>
        </div>
        <Space>
          <Select
            value={storeId}
            onChange={handleStoreChange}
            style={{ width: 200 }}
            options={stores.map((s) => ({ label: s.name, value: s.id }))}
            placeholder="选择门店"
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => { loadDepartments(); loadMappings(); loadUnassigned(); }}
          >
            刷新
          </Button>
        </Space>
      </div>

      {/* 未分配菜品提示 */}
      {unassigned && unassigned.unassigned_count > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message={
            <Space>
              <Text>
                当前门店有 <Text strong style={{ color: TX_WARNING }}>{unassigned.unassigned_count}</Text> 个菜品未分配档口
              </Text>
              {unassigned.dish_names.length > 0 && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  包括：{unassigned.dish_names.slice(0, 3).join('、')}
                  {unassigned.dish_names.length > 3 ? `等${unassigned.dish_names.length}项` : ''}
                </Text>
              )}
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      <Row gutter={16}>
        {/* 左侧：档口选择器 */}
        <Col span={6}>
          <Card
            title="选择档口"
            size="small"
            loading={deptLoading}
            style={{ minHeight: 400 }}
          >
            {departments.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 24 }}>
                暂无档口数据
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {departments.map((dept) => {
                  const isSelected = dept.dept_id === selectedDeptId;
                  return (
                    <div
                      key={dept.dept_id}
                      onClick={() => setSelectedDeptId(dept.dept_id)}
                      style={{
                        padding: '10px 14px',
                        borderRadius: 6,
                        cursor: 'pointer',
                        background: isSelected ? '#fff4ef' : '#fafafa',
                        border: isSelected ? `1px solid ${TX_PRIMARY}` : '1px solid #f0f0f0',
                        borderLeft: isSelected ? `3px solid ${TX_PRIMARY}` : '3px solid transparent',
                        transition: 'all .15s',
                      }}
                    >
                      <Text strong style={{ color: isSelected ? TX_PRIMARY : undefined }}>
                        {dept.dept_name}
                      </Text>
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>{dept.dept_code}</Text>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </Col>

        {/* 右侧：映射列表 */}
        <Col span={18}>
          <Card
            title={
              <Space>
                <Text strong>
                  {selectedDept ? `「${selectedDept.dept_name}」菜品列表` : '请选择档口'}
                </Text>
                {mappings.length > 0 && (
                  <Badge count={mappings.length} color="#1677ff" />
                )}
              </Space>
            }
            extra={
              selectedDeptId && (
                <Space>
                  <Button
                    type="primary"
                    icon={<ImportOutlined />}
                    onClick={() => setBatchModalOpen(true)}
                    style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
                  >
                    批量导入
                  </Button>
                </Space>
              )
            }
            styles={{ body: { padding: 0 } }}
          >
            {!selectedDeptId ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: '#999' }}>
                请在左侧选择一个档口
              </div>
            ) : (
              <>
                {mappings.length === 0 && !loading && (
                  <div style={{ textAlign: 'center', padding: '40px 0' }}>
                    <Text type="secondary">此档口暂无菜品映射</Text>
                    <div style={{ marginTop: 12 }}>
                      <Button
                        type="primary"
                        icon={<PlusOutlined />}
                        onClick={() => setBatchModalOpen(true)}
                        style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
                      >
                        添加菜品
                      </Button>
                    </div>
                  </div>
                )}
                <Table<DishDeptMapping>
                  rowKey="id"
                  dataSource={mappings}
                  columns={columns}
                  loading={loading}
                  pagination={false}
                  size="middle"
                  style={{ display: mappings.length === 0 && !loading ? 'none' : undefined }}
                  footer={() => (
                    <div style={{ textAlign: 'right' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        共 {mappings.length} 个菜品映射 · 拖拽优先级数字左侧上下箭头可调整出品顺序
                      </Text>
                    </div>
                  )}
                />
              </>
            )}
          </Card>
        </Col>
      </Row>

      {/* 批量导入 Modal */}
      {selectedDeptId && selectedDept && (
        <BatchImportModal
          open={batchModalOpen}
          onClose={() => setBatchModalOpen(false)}
          storeId={storeId}
          deptId={selectedDeptId}
          deptName={selectedDept.dept_name}
          onSuccess={() => { loadMappings(); loadUnassigned(); }}
        />
      )}
    </div>
  );
}
