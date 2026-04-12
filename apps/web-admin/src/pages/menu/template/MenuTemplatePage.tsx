/**
 * 菜单模板管理页
 * 域B 菜单模板 · 总部管理后台
 *
 * 功能：
 * 1. 左侧面板（240px）：模板列表 + 新建模板按钮
 * 2. 右侧 Tab1：菜品分类管理（按钮上移/下移排序，展开菜品）
 * 3. 右侧 Tab2：发布管理（门店多选 + 差异配置 + 发布记录）
 * 4. 右侧 Tab3：版本历史（版本列表 + 回滚）
 * 5. 新建/编辑模板 Modal
 *
 * API：
 * GET/POST/PUT /api/v1/menu/templates
 * GET /api/v1/menu/templates/{id}/sections
 * POST /api/v1/menu/brand/publish
 * GET /api/v1/menu/publish-status
 *
 * 技术栈：antd 5.x + React 18 TypeScript strict
 * 设计：txAdminTheme，主色 #FF6B35，最小支持1280px
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  ConfigProvider,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tabs,
  Timeline,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  ClockCircleOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  ExclamationCircleOutlined,
  HistoryOutlined,
  MenuOutlined,
  PlusOutlined,
  ReloadOutlined,
  RollbackOutlined,
  ShopOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const { Panel } = Collapse;
const { Option } = Select;

// ─── Design Tokens ───────────────────────────────────────────────────────────

const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_INFO = '#185FA5';
const TX_BG_SECONDARY = '#F8F7F5';
const TX_BORDER = '#E8E6E1';
const TX_NAVY = '#1E2A3A';

const txAdminTheme = {
  token: {
    colorPrimary: TX_PRIMARY,
    colorSuccess: TX_SUCCESS,
    colorWarning: TX_WARNING,
    colorError: '#A32D2D',
    colorInfo: TX_INFO,
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Layout: { headerBg: TX_NAVY, siderBg: TX_NAVY },
    Menu: { darkItemBg: TX_NAVY, darkItemSelectedBg: TX_PRIMARY },
    Table: { headerBg: TX_BG_SECONDARY },
  },
};

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type BusinessType = 'large' | 'small' | 'banquet' | 'delivery';

const BUSINESS_TYPE_LABELS: Record<BusinessType, string> = {
  large: '大店',
  small: '小店',
  banquet: '宴席',
  delivery: '外卖专',
};

const BUSINESS_TYPE_COLORS: Record<BusinessType, string> = {
  large: 'blue',
  small: 'green',
  banquet: 'purple',
  delivery: 'orange',
};

interface MenuTemplate {
  id: string;
  name: string;
  business_type: BusinessType;
  description: string;
  store_count: number;
  updated_at: string;
  version: number;
}

interface MenuSection {
  id: string;
  name: string;
  sort_order: number;
  is_enabled: boolean;
  dish_count: number;
  dishes: MenuDishItem[];
}

interface MenuDishItem {
  id: string;
  dish_id: string;
  dish_name: string;
  sort_order: number;
  is_enabled: boolean;
  template_price_fen: number | null;
  actual_price_fen: number;
  category: string;
}

interface StoreOption {
  id: string;
  name: string;
  business_type: BusinessType;
}

interface StoreDiffConfig {
  store_id: string;
  dish_id: string;
  override_price_fen: number | null;
  is_unavailable: boolean;
}

interface PublishRecord {
  id: string;
  published_at: string;
  operator: string;
  target_stores: string[];
  target_store_names: string[];
  status: 'success' | 'partial' | 'failed';
  template_version: number;
  summary: string;
}

interface VersionHistory {
  id: string;
  version: number;
  published_at: string;
  operator: string;
  change_summary: string;
  store_count: number;
}

// ─── 空数据 fallback（API 不可用时）──────────────────────────────────────────

const EMPTY_TEMPLATES: MenuTemplate[] = [];
const EMPTY_SECTIONS: MenuSection[] = [];
const EMPTY_STORES: StoreOption[] = [];
const EMPTY_PUBLISH_RECORDS: PublishRecord[] = [];
const EMPTY_VERSIONS: VersionHistory[] = [];

// ─── API 函数 ────────────────────────────────────────────────────────────────

async function fetchTemplates(): Promise<{ items: MenuTemplate[]; total: number }> {
  try {
    const res = await txFetchData<{ items: MenuTemplate[]; total: number }>('/api/v1/menu/templates');
    return res.data ?? { items: EMPTY_TEMPLATES, total: 0 };
  } catch (err) {
    console.error('[MenuTemplatePage] fetchTemplates 失败:', err);
    return { items: EMPTY_TEMPLATES, total: 0 };
  }
}

async function fetchTemplateSections(templateId: string): Promise<MenuSection[]> {
  try {
    const res = await txFetchData<MenuSection[]>(`/api/v1/menu/templates/${templateId}/sections`);
    return res.data ?? EMPTY_SECTIONS;
  } catch (err) {
    console.error('[MenuTemplatePage] fetchTemplateSections 失败:', err);
    return EMPTY_SECTIONS;
  }
}

async function applyTemplate(templateId: string, storeId: string): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/templates/${templateId}/apply`, {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId }),
  });
}

async function createTemplate(payload: {
  name: string;
  business_type: BusinessType;
  description: string;
  copy_from_id?: string;
}): Promise<MenuTemplate> {
  const res = await txFetchData<MenuTemplate>('/api/v1/menu/templates', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!res.data) throw new Error('创建模板失败');
  return res.data;
}

async function updateTemplate(
  id: string,
  payload: Partial<Pick<MenuTemplate, 'name' | 'business_type' | 'description'>>,
): Promise<MenuTemplate> {
  const res = await txFetchData<MenuTemplate>(`/api/v1/menu/templates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  if (!res.data) throw new Error('更新模板失败');
  return res.data;
}

async function updateSectionOrder(
  templateId: string,
  sections: Array<{ id: string; sort_order: number }>,
): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/templates/${templateId}/sections/reorder`, {
    method: 'PUT',
    body: JSON.stringify({ sections }),
  });
}

async function toggleSectionEnabled(
  templateId: string,
  sectionId: string,
  is_enabled: boolean,
): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/templates/${templateId}/sections/${sectionId}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_enabled }),
  });
}

async function updateDishInSection(
  templateId: string,
  sectionId: string,
  dishItemId: string,
  payload: { is_enabled?: boolean; template_price_fen?: number | null; sort_order?: number },
): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/templates/${templateId}/sections/${sectionId}/dishes/${dishItemId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

async function publishToStores(payload: {
  template_id: string;
  store_ids: string[];
  diff_configs: StoreDiffConfig[];
}): Promise<{ publish_id: string; status: string }> {
  const res = await txFetchData<{ publish_id: string; status: string }>('/api/v1/menu/brand/publish', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return res.data ?? { publish_id: '', status: 'unknown' };
}

async function fetchPublishStatus(templateId: string): Promise<PublishRecord[]> {
  try {
    const res = await txFetchData<PublishRecord[]>(`/api/v1/menu/publish-status?template_id=${templateId}`);
    return res.data ?? EMPTY_PUBLISH_RECORDS;
  } catch (err) {
    console.error('[MenuTemplatePage] fetchPublishStatus 失败:', err);
    return EMPTY_PUBLISH_RECORDS;
  }
}

async function fetchVersionHistory(templateId: string): Promise<VersionHistory[]> {
  try {
    const res = await txFetchData<VersionHistory[]>(`/api/v1/menu/templates/${templateId}/versions`);
    return res.data ?? EMPTY_VERSIONS;
  } catch (err) {
    console.error('[MenuTemplatePage] fetchVersionHistory 失败:', err);
    return EMPTY_VERSIONS;
  }
}

async function rollbackToVersion(templateId: string, versionId: string): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/templates/${templateId}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ version_id: versionId }),
  });
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function formatDateTime(isoString: string): string {
  try {
    const d = new Date(isoString);
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoString;
  }
}

function formatPrice(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

// ─── 子组件：新建/编辑模板 Modal ──────────────────────────────────────────────

interface TemplateModalProps {
  open: boolean;
  editingTemplate: MenuTemplate | null;
  allTemplates: MenuTemplate[];
  onClose: () => void;
  onSuccess: () => void;
}

const TemplateModal: React.FC<TemplateModalProps> = ({
  open,
  editingTemplate,
  allTemplates,
  onClose,
  onSuccess,
}) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const isEdit = !!editingTemplate;

  useEffect(() => {
    if (open && editingTemplate) {
      form.setFieldsValue({
        name: editingTemplate.name,
        business_type: editingTemplate.business_type,
        description: editingTemplate.description,
      });
    } else if (open) {
      form.resetFields();
    }
  }, [open, editingTemplate, form]);

  const handleFinish = async (values: Record<string, unknown>) => {
    setLoading(true);
    try {
      if (isEdit && editingTemplate) {
        await updateTemplate(editingTemplate.id, {
          name: values.name as string,
          business_type: values.business_type as BusinessType,
          description: values.description as string,
        });
        message.success('模板更新成功');
      } else {
        await createTemplate({
          name: values.name as string,
          business_type: values.business_type as BusinessType,
          description: values.description as string,
          copy_from_id: values.copy_from_id as string | undefined,
        });
        message.success('模板创建成功');
      }
      onSuccess();
      onClose();
    } catch {
      message.error(isEdit ? '更新失败，请重试' : '创建失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={isEdit ? `编辑模板 — ${editingTemplate?.name}` : '新建菜单模板'}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={loading}
      width={520}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={handleFinish} style={{ marginTop: 16 }}>
        <Form.Item
          name="name"
          label="模板名称"
          rules={[{ required: true, message: '请输入模板名称' }, { max: 50 }]}
        >
          <Input placeholder="如：标准大店菜单2026版" maxLength={50} showCount />
        </Form.Item>

        <Form.Item
          name="business_type"
          label="适用业态"
          rules={[{ required: true, message: '请选择适用业态' }]}
        >
          <Select placeholder="选择业态">
            <Option value="large">大店（200座以上）</Option>
            <Option value="small">小店（200座以下）</Option>
            <Option value="banquet">宴席</Option>
            <Option value="delivery">外卖专</Option>
          </Select>
        </Form.Item>

        <Form.Item name="description" label="模板描述">
          <Input.TextArea
            placeholder="简要描述此模板的适用场景与特点"
            rows={3}
            maxLength={200}
            showCount
          />
        </Form.Item>

        {!isEdit && (
          <Form.Item name="copy_from_id" label="从已有模板复制（可选）">
            <Select placeholder="选择源模板（留空则新建空白模板）" allowClear>
              {allTemplates.map((t) => (
                <Option key={t.id} value={t.id}>
                  {t.name}
                  <Tag color={BUSINESS_TYPE_COLORS[t.business_type]} style={{ marginLeft: 8 }}>
                    {BUSINESS_TYPE_LABELS[t.business_type]}
                  </Tag>
                </Option>
              ))}
            </Select>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
};

// ─── 子组件：Tab1 菜品分类管理 ────────────────────────────────────────────────

interface DishSectionTabProps {
  templateId: string;
}

const DishSectionTab: React.FC<DishSectionTabProps> = ({ templateId }) => {
  const [sections, setSections] = useState<MenuSection[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  const loadSections = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTemplateSections(templateId);
      const sorted = [...data].sort((a, b) => a.sort_order - b.sort_order);
      setSections(sorted);
    } catch {
      message.error('加载分类失败');
    } finally {
      setLoading(false);
    }
  }, [templateId]);

  useEffect(() => {
    loadSections();
  }, [loadSections]);

  const moveSectionUp = async (index: number) => {
    if (index === 0) return;
    const newSections = [...sections];
    [newSections[index - 1], newSections[index]] = [newSections[index], newSections[index - 1]];
    const reordered = newSections.map((s, i) => ({ ...s, sort_order: i + 1 }));
    setSections(reordered);
    try {
      await updateSectionOrder(templateId, reordered.map((s) => ({ id: s.id, sort_order: s.sort_order })));
    } catch {
      message.error('排序更新失败');
      loadSections();
    }
  };

  const moveSectionDown = async (index: number) => {
    if (index === sections.length - 1) return;
    const newSections = [...sections];
    [newSections[index], newSections[index + 1]] = [newSections[index + 1], newSections[index]];
    const reordered = newSections.map((s, i) => ({ ...s, sort_order: i + 1 }));
    setSections(reordered);
    try {
      await updateSectionOrder(templateId, reordered.map((s) => ({ id: s.id, sort_order: s.sort_order })));
    } catch {
      message.error('排序更新失败');
      loadSections();
    }
  };

  const toggleSection = async (sectionId: string, checked: boolean) => {
    setSections((prev) =>
      prev.map((s) => (s.id === sectionId ? { ...s, is_enabled: checked } : s)),
    );
    try {
      await toggleSectionEnabled(templateId, sectionId, checked);
    } catch {
      message.error('更新失败');
      loadSections();
    }
  };

  const toggleDish = async (section: MenuSection, dishItem: MenuDishItem, checked: boolean) => {
    setSections((prev) =>
      prev.map((s) =>
        s.id === section.id
          ? {
              ...s,
              dishes: s.dishes.map((d) =>
                d.id === dishItem.id ? { ...d, is_enabled: checked } : d,
              ),
            }
          : s,
      ),
    );
    try {
      await updateDishInSection(templateId, section.id, dishItem.id, { is_enabled: checked });
    } catch {
      message.error('更新失败');
      loadSections();
    }
  };

  const moveDishUp = async (section: MenuSection, dishIndex: number) => {
    if (dishIndex === 0) return;
    const newDishes = [...section.dishes];
    [newDishes[dishIndex - 1], newDishes[dishIndex]] = [newDishes[dishIndex], newDishes[dishIndex - 1]];
    const reordered = newDishes.map((d, i) => ({ ...d, sort_order: i + 1 }));
    setSections((prev) =>
      prev.map((s) => (s.id === section.id ? { ...s, dishes: reordered } : s)),
    );
    try {
      await updateDishInSection(templateId, section.id, reordered[dishIndex - 1].id, {
        sort_order: dishIndex,
      });
    } catch {
      message.error('排序更新失败');
      loadSections();
    }
  };

  const moveDishDown = async (section: MenuSection, dishIndex: number) => {
    if (dishIndex === section.dishes.length - 1) return;
    const newDishes = [...section.dishes];
    [newDishes[dishIndex], newDishes[dishIndex + 1]] = [newDishes[dishIndex + 1], newDishes[dishIndex]];
    const reordered = newDishes.map((d, i) => ({ ...d, sort_order: i + 1 }));
    setSections((prev) =>
      prev.map((s) => (s.id === section.id ? { ...s, dishes: reordered } : s)),
    );
    try {
      await updateDishInSection(templateId, section.id, reordered[dishIndex + 1].id, {
        sort_order: dishIndex + 2,
      });
    } catch {
      message.error('排序更新失败');
      loadSections();
    }
  };

  const [editPriceModal, setEditPriceModal] = useState<{
    open: boolean;
    section: MenuSection | null;
    dish: MenuDishItem | null;
  }>({ open: false, section: null, dish: null });
  const [priceForm] = Form.useForm();
  const [priceLoading, setPriceLoading] = useState(false);

  const openPriceEdit = (section: MenuSection, dish: MenuDishItem) => {
    setEditPriceModal({ open: true, section, dish });
    priceForm.setFieldsValue({
      template_price: dish.template_price_fen !== null ? dish.template_price_fen / 100 : null,
    });
  };

  const handlePriceSave = async (values: Record<string, unknown>) => {
    const { section, dish } = editPriceModal;
    if (!section || !dish) return;
    setPriceLoading(true);
    const templatePriceFen =
      values.template_price != null
        ? Math.round((values.template_price as number) * 100)
        : null;
    try {
      await updateDishInSection(templateId, section.id, dish.id, {
        template_price_fen: templatePriceFen,
      });
      setSections((prev) =>
        prev.map((s) =>
          s.id === section.id
            ? {
                ...s,
                dishes: s.dishes.map((d) =>
                  d.id === dish.id ? { ...d, template_price_fen: templatePriceFen } : d,
                ),
              }
            : s,
        ),
      );
      message.success('价格覆盖已保存');
      setEditPriceModal({ open: false, section: null, dish: null });
    } catch {
      message.error('保存失败');
    } finally {
      setPriceLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text type="secondary">共 {sections.length} 个分类，拖动排序或使用箭头按钮调整顺序</Text>
        <Button icon={<ReloadOutlined />} size="small" onClick={loadSections}>
          刷新
        </Button>
      </div>

      {sections.length === 0 ? (
        <Empty description="暂无菜品分类，请先在菜品档案中配置" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sections.map((section, sectionIndex) => (
            <Card
              key={section.id}
              size="small"
              style={{
                border: `1px solid ${section.is_enabled ? TX_BORDER : '#f0f0f0'}`,
                opacity: section.is_enabled ? 1 : 0.6,
                borderRadius: 6,
              }}
              styles={{ body: { padding: '8px 12px' } }}
            >
              {/* 分类行 */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  cursor: 'pointer',
                }}
              >
                <MenuOutlined style={{ color: '#ccc', fontSize: 14 }} />

                {/* 上下移动按钮 */}
                <Space.Compact size="small">
                  <Tooltip title="上移">
                    <Button
                      icon={<ArrowUpOutlined />}
                      size="small"
                      disabled={sectionIndex === 0}
                      onClick={(e) => { e.stopPropagation(); moveSectionUp(sectionIndex); }}
                    />
                  </Tooltip>
                  <Tooltip title="下移">
                    <Button
                      icon={<ArrowDownOutlined />}
                      size="small"
                      disabled={sectionIndex === sections.length - 1}
                      onClick={(e) => { e.stopPropagation(); moveSectionDown(sectionIndex); }}
                    />
                  </Tooltip>
                </Space.Compact>

                <Text strong style={{ flex: 1, fontSize: 15 }}>
                  {section.name}
                </Text>

                <Tag color="default">{section.dish_count} 道菜</Tag>

                <Switch
                  size="small"
                  checked={section.is_enabled}
                  checkedChildren="启用"
                  unCheckedChildren="禁用"
                  onChange={(checked) => toggleSection(section.id, checked)}
                />

                <Button
                  type="link"
                  size="small"
                  style={{ color: TX_PRIMARY, padding: 0 }}
                  onClick={() =>
                    setExpandedKeys((prev) =>
                      prev.includes(section.id)
                        ? prev.filter((k) => k !== section.id)
                        : [...prev, section.id],
                    )
                  }
                >
                  {expandedKeys.includes(section.id) ? '收起' : '展开菜品'}
                </Button>
              </div>

              {/* 展开菜品列表 */}
              {expandedKeys.includes(section.id) && (
                <div style={{ marginTop: 8, borderTop: `1px solid ${TX_BORDER}`, paddingTop: 8 }}>
                  {section.dishes.length === 0 ? (
                    <Text type="secondary" style={{ fontSize: 13, paddingLeft: 32 }}>
                      暂无菜品
                    </Text>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {section.dishes
                        .slice()
                        .sort((a, b) => a.sort_order - b.sort_order)
                        .map((dish, dishIndex) => (
                          <div
                            key={dish.id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              padding: '4px 8px 4px 32px',
                              background: dish.is_enabled ? 'transparent' : '#fafafa',
                              borderRadius: 4,
                              opacity: dish.is_enabled ? 1 : 0.55,
                              gap: 8,
                            }}
                          >
                            {/* 菜品排序按钮 */}
                            <Space.Compact size="small">
                              <Tooltip title="上移">
                                <Button
                                  icon={<ArrowUpOutlined />}
                                  size="small"
                                  disabled={dishIndex === 0}
                                  onClick={() => moveDishUp(section, dishIndex)}
                                />
                              </Tooltip>
                              <Tooltip title="下移">
                                <Button
                                  icon={<ArrowDownOutlined />}
                                  size="small"
                                  disabled={dishIndex === section.dishes.length - 1}
                                  onClick={() => moveDishDown(section, dishIndex)}
                                />
                              </Tooltip>
                            </Space.Compact>

                            <Text style={{ flex: 1, fontSize: 13 }}>{dish.dish_name}</Text>

                            {/* 价格展示 */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                实际价：{formatPrice(dish.actual_price_fen)}
                              </Text>
                              {dish.template_price_fen !== null ? (
                                <Tag color="orange" style={{ fontSize: 11 }}>
                                  模板价：{formatPrice(dish.template_price_fen)}
                                </Tag>
                              ) : (
                                <Tag style={{ fontSize: 11 }}>跟随实际价</Tag>
                              )}
                            </div>

                            {/* 价格覆盖编辑按钮 */}
                            <Button
                              type="link"
                              size="small"
                              style={{ color: TX_INFO, padding: 0, fontSize: 12 }}
                              onClick={() => openPriceEdit(section, dish)}
                            >
                              覆盖价格
                            </Button>

                            {/* 启用 Switch */}
                            <Switch
                              size="small"
                              checked={dish.is_enabled}
                              onChange={(checked) => toggleDish(section, dish, checked)}
                            />
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* 价格覆盖 Modal */}
      <Modal
        title={`覆盖模板价格 — ${editPriceModal.dish?.dish_name ?? ''}`}
        open={editPriceModal.open}
        onCancel={() => setEditPriceModal({ open: false, section: null, dish: null })}
        onOk={() => priceForm.submit()}
        confirmLoading={priceLoading}
        width={400}
        destroyOnClose
      >
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary">实际价格：</Text>
          <Text strong>
            {editPriceModal.dish ? formatPrice(editPriceModal.dish.actual_price_fen) : '—'}
          </Text>
        </div>
        <Form form={priceForm} layout="vertical" onFinish={handlePriceSave}>
          <Form.Item
            name="template_price"
            label="模板覆盖价（元）"
            help="留空则跟随实际价格，设置后该模板中此菜品使用覆盖价"
          >
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              precision={2}
              prefix="¥"
              placeholder="留空则跟随实际价格"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

// ─── 子组件：Tab2 发布管理 ────────────────────────────────────────────────────

interface PublishTabProps {
  template: MenuTemplate;
}

const PublishTab: React.FC<PublishTabProps> = ({ template }) => {
  const [selectedStoreIds, setSelectedStoreIds] = useState<string[]>([]);
  const [diffConfigs, setDiffConfigs] = useState<StoreDiffConfig[]>([]);
  const [publishRecords, setPublishRecords] = useState<PublishRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);
  const [stores, setStores] = useState<StoreOption[]>(EMPTY_STORES);

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: StoreOption[] }>('/api/v1/system/stores?size=200')
      .then((res) => setStores(res.data?.items ?? EMPTY_STORES))
      .catch((err) => console.error('[PublishTab] 加载门店失败:', err));
  }, []);
  const [diffModalOpen, setDiffModalOpen] = useState(false);
  const [diffStoreId, setDiffStoreId] = useState<string>('');
  const [diffForm] = Form.useForm();

  const loadRecords = useCallback(async () => {
    setRecordsLoading(true);
    try {
      const records = await fetchPublishStatus(template.id);
      setPublishRecords(records);
    } catch {
      message.error('加载发布记录失败');
    } finally {
      setRecordsLoading(false);
    }
  }, [template.id]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  const handlePublish = async () => {
    if (selectedStoreIds.length === 0) {
      message.warning('请至少选择一个目标门店');
      return;
    }
    Modal.confirm({
      title: '确认发布',
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          <p>将把模板 <strong>{template.name}</strong>（v{template.version}）发布到以下门店：</p>
          <ul>
            {selectedStoreIds.map((id) => {
              const s = stores.find((st) => st.id === id);
              return <li key={id}>{s?.name ?? id}</li>;
            })}
          </ul>
          <p style={{ color: TX_WARNING }}>此操作将覆盖所选门店当前生效的菜单配置。</p>
        </div>
      ),
      okText: '确认发布',
      okType: 'primary',
      cancelText: '取消',
      onOk: async () => {
        setPublishLoading(true);
        try {
          await publishToStores({
            template_id: template.id,
            store_ids: selectedStoreIds,
            diff_configs: diffConfigs,
          });
          message.success('发布成功！');
          setSelectedStoreIds([]);
          loadRecords();
        } catch {
          message.error('发布失败，请重试');
        } finally {
          setPublishLoading(false);
        }
      },
    });
  };

  const openDiffConfig = (storeId: string) => {
    setDiffStoreId(storeId);
    const existing = diffConfigs.find((d) => d.store_id === storeId);
    diffForm.setFieldsValue({
      override_price_fen: existing?.override_price_fen != null ? existing.override_price_fen / 100 : null,
      is_unavailable: existing?.is_unavailable ?? false,
    });
    setDiffModalOpen(true);
  };

  const saveDiffConfig = (values: Record<string, unknown>) => {
    const config: StoreDiffConfig = {
      store_id: diffStoreId,
      dish_id: '',
      override_price_fen:
        values.override_price_fen != null
          ? Math.round((values.override_price_fen as number) * 100)
          : null,
      is_unavailable: values.is_unavailable as boolean,
    };
    setDiffConfigs((prev) => {
      const exists = prev.findIndex((d) => d.store_id === diffStoreId);
      if (exists >= 0) {
        const updated = [...prev];
        updated[exists] = config;
        return updated;
      }
      return [...prev, config];
    });
    setDiffModalOpen(false);
    message.success('差异配置已暂存');
  };

  const publishRecordColumns: ColumnsType<PublishRecord> = [
    {
      title: '发布时间',
      dataIndex: 'published_at',
      width: 160,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: '操作人',
      dataIndex: 'operator',
      width: 90,
    },
    {
      title: '目标门店',
      dataIndex: 'target_store_names',
      render: (names: string[]) =>
        names.map((n) => <Tag key={n}>{n}</Tag>),
    },
    {
      title: '版本',
      dataIndex: 'template_version',
      width: 70,
      render: (v: number) => <Tag>v{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: 'success' | 'partial' | 'failed') => {
        const config = {
          success: { color: 'success', text: '成功' },
          partial: { color: 'warning', text: '部分成功' },
          failed: { color: 'error', text: '失败' },
        }[status];
        return <Badge status={config.color as 'success' | 'warning' | 'error'} text={config.text} />;
      },
    },
    {
      title: '变更摘要',
      dataIndex: 'summary',
      ellipsis: true,
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 门店选择器 */}
      <Card
        title={
          <Space>
            <ShopOutlined />
            <span>选择目标门店</span>
          </Space>
        }
        extra={
          <Text type="secondary">
            已选 <Text strong style={{ color: TX_PRIMARY }}>{selectedStoreIds.length}</Text> 家门店
          </Text>
        }
        size="small"
      >
        <Checkbox.Group
          value={selectedStoreIds}
          onChange={(v) => setSelectedStoreIds(v as string[])}
        >
          <Row gutter={[12, 12]}>
            {stores.map((store) => {
              const hasDiff = diffConfigs.some((d) => d.store_id === store.id);
              return (
                <Col span={8} key={store.id}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      padding: '8px 12px',
                      border: `1px solid ${selectedStoreIds.includes(store.id) ? TX_PRIMARY : TX_BORDER}`,
                      borderRadius: 6,
                      background: selectedStoreIds.includes(store.id) ? '#fff3ed' : '#fff',
                      gap: 8,
                    }}
                  >
                    <Checkbox value={store.id} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{store.name}</div>
                      <Tag
                        color={BUSINESS_TYPE_COLORS[store.business_type]}
                        style={{ fontSize: 11, marginTop: 2 }}
                      >
                        {BUSINESS_TYPE_LABELS[store.business_type]}
                      </Tag>
                      {hasDiff && (
                        <Tag color="orange" style={{ fontSize: 11 }}>已配置差异</Tag>
                      )}
                    </div>
                    {selectedStoreIds.includes(store.id) && (
                      <Button
                        type="link"
                        size="small"
                        style={{ color: TX_INFO, padding: 0, fontSize: 11 }}
                        onClick={() => openDiffConfig(store.id)}
                      >
                        差异配置
                      </Button>
                    )}
                  </div>
                </Col>
              );
            })}
          </Row>
        </Checkbox.Group>

        <Divider style={{ margin: '12px 0' }} />

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            type="primary"
            icon={<CloudUploadOutlined />}
            loading={publishLoading}
            disabled={selectedStoreIds.length === 0}
            onClick={handlePublish}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            发布到所选门店（{selectedStoreIds.length}家）
          </Button>
        </div>
      </Card>

      {/* 发布记录 */}
      <Card
        title={
          <Space>
            <ClockCircleOutlined />
            <span>发布记录</span>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} size="small" onClick={loadRecords}>
            刷新
          </Button>
        }
        size="small"
      >
        <Table<PublishRecord>
          rowKey="id"
          dataSource={publishRecords}
          columns={publishRecordColumns}
          loading={recordsLoading}
          pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
          size="small"
        />
      </Card>

      {/* 差异配置 Modal */}
      <Modal
        title={`门店差异配置 — ${stores.find((s) => s.id === diffStoreId)?.name ?? ''}`}
        open={diffModalOpen}
        onCancel={() => setDiffModalOpen(false)}
        onOk={() => diffForm.submit()}
        width={420}
        destroyOnClose
      >
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#fffbe6', borderRadius: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            差异配置仅对此门店生效，不影响其他门店。当前为门店级全局差异，如需菜品级差异请在发布后在门店端调整。
          </Text>
        </div>
        <Form form={diffForm} layout="vertical" onFinish={saveDiffConfig}>
          <Form.Item
            name="override_price_fen"
            label="全局价格系数覆盖（元）"
            help="留空则使用模板原价"
          >
            <InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" placeholder="留空则使用模板价" />
          </Form.Item>
          <Form.Item name="is_unavailable" label="整店屏蔽此模板" valuePropName="checked">
            <Switch checkedChildren="屏蔽" unCheckedChildren="启用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

// ─── 子组件：Tab3 版本历史 ────────────────────────────────────────────────────

interface VersionHistoryTabProps {
  template: MenuTemplate;
}

const VersionHistoryTab: React.FC<VersionHistoryTabProps> = ({ template }) => {
  const [versions, setVersions] = useState<VersionHistory[]>([]);
  const [loading, setLoading] = useState(false);
  const [rollbackLoading, setRollbackLoading] = useState<string | null>(null);

  const loadVersions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchVersionHistory(template.id);
      setVersions(data);
    } catch {
      message.error('加载版本历史失败');
    } finally {
      setLoading(false);
    }
  }, [template.id]);

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  const handleRollback = (ver: VersionHistory) => {
    Modal.confirm({
      title: `回滚到版本 v${ver.version}`,
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          <p>确认将模板回滚到 <strong>v{ver.version}</strong>（{formatDateTime(ver.published_at)}）？</p>
          <p style={{ color: TX_WARNING }}>
            <ExclamationCircleOutlined style={{ marginRight: 4 }} />
            回滚后当前版本的所有修改将被覆盖，此操作不可撤销。
          </p>
          <p>版本摘要：{ver.change_summary}</p>
        </div>
      ),
      okText: '确认回滚',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setRollbackLoading(ver.id);
        try {
          await rollbackToVersion(template.id, ver.id);
          message.success(`已成功回滚到 v${ver.version}`);
          loadVersions();
        } catch {
          message.error('回滚失败，请重试');
        } finally {
          setRollbackLoading(null);
        }
      },
    });
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text type="secondary">当前版本：v{template.version}</Text>
        <Button icon={<ReloadOutlined />} size="small" onClick={loadVersions}>
          刷新
        </Button>
      </div>

      {versions.length === 0 ? (
        <Empty description="暂无版本历史" />
      ) : (
        <Timeline
          items={versions.map((ver, index) => ({
            color: index === 0 ? TX_PRIMARY : '#d9d9d9',
            dot: index === 0 ? (
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: TX_PRIMARY,
                  border: `2px solid ${TX_PRIMARY}`,
                }}
              />
            ) : undefined,
            children: (
              <Card
                size="small"
                style={{
                  border: `1px solid ${index === 0 ? TX_PRIMARY : TX_BORDER}`,
                  background: index === 0 ? '#fff3ed' : '#fff',
                  borderRadius: 6,
                  marginBottom: 8,
                }}
                styles={{ body: { padding: '10px 14px' } }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <Space style={{ marginBottom: 4 }}>
                      <Tag
                        color={index === 0 ? 'orange' : 'default'}
                        style={{ fontWeight: 600 }}
                      >
                        v{ver.version}
                      </Tag>
                      {index === 0 && <Tag color="success">当前版本</Tag>}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        <ClockCircleOutlined style={{ marginRight: 4 }} />
                        {formatDateTime(ver.published_at)}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        操作人：{ver.operator}
                      </Text>
                    </Space>
                    <div>
                      <Text style={{ fontSize: 13 }}>{ver.change_summary}</Text>
                    </div>
                    <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
                      覆盖门店数：{ver.store_count} 家
                    </Text>
                  </div>
                  {index !== 0 && (
                    <Tooltip title="回滚到此版本">
                      <Button
                        size="small"
                        icon={<RollbackOutlined />}
                        loading={rollbackLoading === ver.id}
                        onClick={() => handleRollback(ver)}
                        style={{ marginLeft: 12 }}
                      >
                        回滚
                      </Button>
                    </Tooltip>
                  )}
                </div>
              </Card>
            ),
          }))}
        />
      )}
    </div>
  );
};

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function MenuTemplatePage() {
  const [templates, setTemplates] = useState<MenuTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<MenuTemplate | null>(null);
  const [activeTab, setActiveTab] = useState('sections');

  // 模板 Modal 状态
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<MenuTemplate | null>(null);

  const loadTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    try {
      const res = await fetchTemplates();
      setTemplates(res.items);
      // 如果当前选中模板不存在，自动选第一个
      if (res.items.length > 0 && !selectedTemplate) {
        setSelectedTemplate(res.items[0]);
      }
    } catch {
      message.error('加载模板列表失败');
    } finally {
      setTemplatesLoading(false);
    }
  }, [selectedTemplate]);

  useEffect(() => {
    loadTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelectTemplate = (tpl: MenuTemplate) => {
    setSelectedTemplate(tpl);
    setActiveTab('sections');
  };

  const handleCreateNew = () => {
    setEditingTemplate(null);
    setTemplateModalOpen(true);
  };

  const handleEditTemplate = (tpl: MenuTemplate, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingTemplate(tpl);
    setTemplateModalOpen(true);
  };

  const tabItems = selectedTemplate
    ? [
        {
          key: 'sections',
          label: (
            <span>
              <MenuOutlined />
              菜品分类管理
            </span>
          ),
          children: <DishSectionTab templateId={selectedTemplate.id} />,
        },
        {
          key: 'publish',
          label: (
            <span>
              <CloudUploadOutlined />
              发布管理
            </span>
          ),
          children: <PublishTab template={selectedTemplate} />,
        },
        {
          key: 'versions',
          label: (
            <span>
              <HistoryOutlined />
              版本历史
            </span>
          ),
          children: <VersionHistoryTab template={selectedTemplate} />,
        },
      ]
    : [];

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ minWidth: 1280, height: '100%' }}>
        {/* 页面标题栏 */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
            paddingBottom: 12,
            borderBottom: `1px solid ${TX_BORDER}`,
          }}
        >
          <div>
            <Title level={4} style={{ margin: 0 }}>
              菜单模板管理
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              总部建立标准模板，各门店差异化调整 · 支持品牌→门店三级发布
            </Text>
          </div>
          <Space>
            <Tag color="blue" icon={<ShopOutlined />}>
              {templates.reduce((sum, t) => sum + t.store_count, 0)} 家门店使用中
            </Tag>
          </Space>
        </div>

        {/* 主体：左右分栏 */}
        <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 180px)' }}>
          {/* 左侧：模板列表面板 */}
          <div
            style={{
              width: 240,
              flexShrink: 0,
              border: `1px solid ${TX_BORDER}`,
              borderRadius: 6,
              background: '#fff',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* 左侧标题 + 新建按钮 */}
            <div
              style={{
                padding: '12px 12px 8px',
                borderBottom: `1px solid ${TX_BORDER}`,
                background: TX_BG_SECONDARY,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>
                  菜单模板
                </Text>
                <Tag>{templates.length}</Tag>
              </div>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                size="small"
                block
                onClick={handleCreateNew}
                style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                新建模板
              </Button>
            </div>

            {/* 模板列表 */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {templatesLoading ? (
                <div style={{ textAlign: 'center', padding: 24 }}>
                  <Spin size="small" />
                </div>
              ) : templates.length === 0 ? (
                <Empty
                  description="暂无模板"
                  style={{ padding: 24 }}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : (
                <List
                  dataSource={templates}
                  renderItem={(tpl) => {
                    const isSelected = selectedTemplate?.id === tpl.id;
                    return (
                      <List.Item
                        key={tpl.id}
                        onClick={() => handleSelectTemplate(tpl)}
                        style={{
                          padding: '10px 12px',
                          cursor: 'pointer',
                          background: isSelected ? '#fff3ed' : 'transparent',
                          borderLeft: `3px solid ${isSelected ? TX_PRIMARY : 'transparent'}`,
                          borderBottom: `1px solid ${TX_BORDER}`,
                          transition: 'all 0.15s',
                        }}
                      >
                        <div style={{ width: '100%' }}>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              marginBottom: 3,
                            }}
                          >
                            <Text
                              strong
                              style={{
                                fontSize: 13,
                                color: isSelected ? TX_PRIMARY : '#2C2C2A',
                                flex: 1,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                              title={tpl.name}
                            >
                              {tpl.name}
                            </Text>
                            <Button
                              type="link"
                              size="small"
                              style={{ padding: 0, fontSize: 11, color: '#999', flexShrink: 0 }}
                              onClick={(e) => handleEditTemplate(tpl, e)}
                            >
                              编辑
                            </Button>
                          </div>

                          <Space size={4} wrap>
                            <Tag
                              color={BUSINESS_TYPE_COLORS[tpl.business_type]}
                              style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px' }}
                            >
                              {BUSINESS_TYPE_LABELS[tpl.business_type]}
                            </Tag>
                            <Tag style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px' }}>
                              v{tpl.version}
                            </Tag>
                          </Space>

                          <div style={{ marginTop: 4 }}>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              <ShopOutlined style={{ marginRight: 3 }} />
                              {tpl.store_count} 家门店
                            </Text>
                            <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                              {formatDateTime(tpl.updated_at).split(' ')[0]}
                            </Text>
                          </div>
                        </div>
                      </List.Item>
                    );
                  }}
                />
              )}
            </div>
          </div>

          {/* 右侧：Tab 区域 */}
          <div
            style={{
              flex: 1,
              border: `1px solid ${TX_BORDER}`,
              borderRadius: 6,
              background: '#fff',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {!selectedTemplate ? (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '100%',
                  color: '#ccc',
                }}
              >
                <MenuOutlined style={{ fontSize: 48, marginBottom: 16 }} />
                <Text type="secondary">从左侧选择一个模板开始编辑</Text>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                {/* 右侧标题 */}
                <div
                  style={{
                    padding: '12px 16px 0',
                    borderBottom: `1px solid ${TX_BORDER}`,
                    background: TX_BG_SECONDARY,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <Text strong style={{ fontSize: 15 }}>
                      {selectedTemplate.name}
                    </Text>
                    <Tag color={BUSINESS_TYPE_COLORS[selectedTemplate.business_type]}>
                      {BUSINESS_TYPE_LABELS[selectedTemplate.business_type]}
                    </Tag>
                    <Tag>v{selectedTemplate.version}</Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      最后更新：{formatDateTime(selectedTemplate.updated_at)}
                    </Text>
                  </div>
                  {selectedTemplate.description && (
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                      {selectedTemplate.description}
                    </Text>
                  )}
                </div>

                {/* Tabs */}
                <div style={{ flex: 1, overflow: 'auto', padding: '0 16px 16px' }}>
                  <Tabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    items={tabItems}
                    style={{ height: '100%' }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 新建/编辑模板 Modal */}
      <TemplateModal
        open={templateModalOpen}
        editingTemplate={editingTemplate}
        allTemplates={templates}
        onClose={() => setTemplateModalOpen(false)}
        onSuccess={() => {
          loadTemplates();
          setTemplateModalOpen(false);
        }}
      />
    </ConfigProvider>
  );
}
