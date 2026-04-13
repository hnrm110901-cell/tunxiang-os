/**
 * DishSortPage — 菜品排序管理
 * 域B：按分类展示菜品，支持上移/下移/置顶/置底，批量保存排序
 * 特殊分类"推荐菜品"控制首页推荐展示顺序
 * 技术栈：Ant Design 5.x + ProComponents
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../api';
import {
  Card,
  Tabs,
  Button,
  Space,
  Tag,
  message,
  Typography,
  Tooltip,
  Badge,
  Divider,
  Alert,
} from 'antd';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  VerticalAlignTopOutlined,
  VerticalAlignBottomOutlined,
  SaveOutlined,
  StarFilled,
} from '@ant-design/icons';
import { formatPrice } from '@tx-ds/utils';

const { Text } = Typography;

// ─── 类型定义 ───────────────────────────────────────────────

interface DishSortItem {
  id: string;
  name: string;
  price_fen: number;
  category_id: string;
  sort_order: number;
  is_available: boolean;
  tags: ('recommended' | 'new' | 'limited')[];
}

// ─── 类型扩展 ────────────────────────────────────────────────

interface DishCategory {
  id: string;
  name: string;
  icon?: string;
}

// ─── API 函数 ───────────────────────────────────���─────────────

async function fetchCategories(): Promise<DishCategory[]> {
  try {
    const res = await txFetchData<{ items: DishCategory[] }>('/api/v1/menu/categories');
    return res?.items ?? [];
  } catch (err) {
    console.error('[DishSortPage] fetchCategories 失败:', err);
    return [];
  }
}

async function fetchDishesByCategory(categoryId: string): Promise<DishSortItem[]> {
  try {
    const res = await txFetchData<{ items: DishSortItem[] }>(
      `/api/v1/menu/dishes?category_id=${encodeURIComponent(categoryId)}&include_sort=true&size=200`,
    );
    return res?.items ?? [];
  } catch (err) {
    console.error('[DishSortPage] fetchDishesByCategory 失败:', err);
    return [];
  }
}

async function saveDishSort(items: { id: string; sort_order: number }[]): Promise<void> {
  await txFetchData<void>('/api/v1/menu/dishes/sort', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

// ─── 工具函数 ────────────────────────────────────────────────

/** @deprecated — use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number) {
  return `¥${(fen / 100).toFixed(2)}`;
}

const TAG_CONFIG = {
  recommended: { label: '推荐', color: '#FF6B35' },
  new: { label: '新品', color: '#0F6E56' },
  limited: { label: '限时', color: '#BA7517' },
};

// ─── 单个分类排序列表 ─────────────────────────────────────────

interface CategorySortListProps {
  dishes: DishSortItem[];
  onChange: (dishes: DishSortItem[]) => void;
  isDirty: boolean;
}

function CategorySortList({ dishes, onChange }: CategorySortListProps) {
  const sortedDishes = [...dishes].sort((a, b) => a.sort_order - b.sort_order);

  const move = (idx: number, direction: 'up' | 'down') => {
    if (direction === 'up' && idx === 0) return;
    if (direction === 'down' && idx === sortedDishes.length - 1) return;

    const next = [...sortedDishes];
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
    const temp = next[idx].sort_order;
    next[idx] = { ...next[idx], sort_order: next[swapIdx].sort_order };
    next[swapIdx] = { ...next[swapIdx], sort_order: temp };
    onChange(next);
  };

  const moveToTop = (idx: number) => {
    if (idx === 0) return;
    const next = [...sortedDishes];
    const minOrder = Math.min(...next.map((d) => d.sort_order));
    next[idx] = { ...next[idx], sort_order: minOrder - 1 };
    // Renormalize orders
    const sorted = [...next].sort((a, b) => a.sort_order - b.sort_order);
    onChange(sorted.map((d, i) => ({ ...d, sort_order: i + 1 })));
  };

  const moveToBottom = (idx: number) => {
    if (idx === sortedDishes.length - 1) return;
    const next = [...sortedDishes];
    const maxOrder = Math.max(...next.map((d) => d.sort_order));
    next[idx] = { ...next[idx], sort_order: maxOrder + 1 };
    const sorted = [...next].sort((a, b) => a.sort_order - b.sort_order);
    onChange(sorted.map((d, i) => ({ ...d, sort_order: i + 1 })));
  };

  if (sortedDishes.length === 0) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center', color: '#999' }}>
        该分类暂无菜品
      </div>
    );
  }

  return (
    <div>
      {sortedDishes.map((dish, idx) => (
        <div
          key={dish.id}
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '10px 16px',
            borderRadius: 8,
            marginBottom: 4,
            background: idx % 2 === 0 ? '#fafafa' : '#fff',
            border: '1px solid #f0ede6',
            transition: 'background 0.15s',
            opacity: dish.is_available ? 1 : 0.55,
          }}
        >
          {/* 序号 */}
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: idx === 0 ? '#FF6B35' : '#f0ede6',
              color: idx === 0 ? '#fff' : '#5f5e5a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: 14,
              marginRight: 12,
              flexShrink: 0,
            }}
          >
            {dish.sort_order}
          </div>

          {/* 菜品信息 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <Text strong style={{ fontSize: 14 }}>
                {dish.name}
              </Text>
              {dish.tags.map((tag) => (
                <Tag
                  key={tag}
                  style={{
                    background: `${TAG_CONFIG[tag].color}22`,
                    color: TAG_CONFIG[tag].color,
                    border: `1px solid ${TAG_CONFIG[tag].color}44`,
                    fontSize: 11,
                    padding: '0 6px',
                    lineHeight: '18px',
                  }}
                >
                  {TAG_CONFIG[tag].label}
                </Tag>
              ))}
              {!dish.is_available && <Tag color="default">已下架</Tag>}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {fenToYuan(dish.price_fen)}
            </Text>
          </div>

          {/* 操作按钮 */}
          <Space size={4}>
            <Tooltip title="置顶">
              <Button
                size="small"
                icon={<VerticalAlignTopOutlined />}
                disabled={idx === 0}
                onClick={() => moveToTop(idx)}
              />
            </Tooltip>
            <Tooltip title="上移">
              <Button
                size="small"
                icon={<ArrowUpOutlined />}
                disabled={idx === 0}
                onClick={() => move(idx, 'up')}
              />
            </Tooltip>
            <Tooltip title="下移">
              <Button
                size="small"
                icon={<ArrowDownOutlined />}
                disabled={idx === sortedDishes.length - 1}
                onClick={() => move(idx, 'down')}
              />
            </Tooltip>
            <Tooltip title="置底">
              <Button
                size="small"
                icon={<VerticalAlignBottomOutlined />}
                disabled={idx === sortedDishes.length - 1}
                onClick={() => moveToBottom(idx)}
              />
            </Tooltip>
          </Space>
        </div>
      ))}
    </div>
  );
}

// ─── 主组件 ─────────────────────────────────────────────────

export function DishSortPage() {
  const [categories, setCategories] = useState<DishCategory[]>([]);
  const [dishes, setDishes] = useState<DishSortItem[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [categoryDishLoading, setCategoryDishLoading] = useState(false);
  const [dirtyCategories, setDirtyCategories] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [activeCategory, setActiveCategory] = useState('');

  // 加载分类列表
  const loadCategories = useCallback(async () => {
    setCategoriesLoading(true);
    try {
      const cats = await fetchCategories();
      setCategories(cats);
      if (cats.length > 0 && !activeCategory) {
        setActiveCategory(cats[0].id);
      }
    } catch {
      message.error('加载分类失败');
    } finally {
      setCategoriesLoading(false);
    }
  }, [activeCategory]);

  // 加载当前分类下的菜品
  const loadCategoryDishes = useCallback(async (categoryId: string) => {
    if (!categoryId) return;
    setCategoryDishLoading(true);
    try {
      const items = await fetchDishesByCategory(categoryId);
      setDishes((prev) => {
        const others = prev.filter((d) => d.category_id !== categoryId);
        return [...others, ...items];
      });
    } catch {
      message.error('加载菜品失败');
    } finally {
      setCategoryDishLoading(false);
    }
  }, []);

  useEffect(() => { loadCategories(); }, []);
  useEffect(() => { if (activeCategory) loadCategoryDishes(activeCategory); }, [activeCategory, loadCategoryDishes]);

  const handleCategoryChange = (categoryId: string, updatedDishes: DishSortItem[]) => {
    setDishes((prev) => {
      const others = prev.filter((d) => d.category_id !== categoryId);
      return [...others, ...updatedDishes];
    });
    setDirtyCategories((prev) => new Set(prev).add(categoryId));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      // 收集所有脏分类的排序变更并一次性保存
      const dirtyDishes = dishes.filter((d) => dirtyCategories.has(d.category_id));
      const sortItems = dirtyDishes.map((d) => ({ id: d.id, sort_order: d.sort_order }));
      await saveDishSort(sortItems);
      message.success('排序已保存，前台展示顺序已更新');
      setDirtyCategories(new Set());
    } catch {
      message.error('保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const tabItems = (categories.length > 0 ? categories : []).map((cat) => {
    const catDishes = dishes.filter((d) => d.category_id === cat.id);
    const isDirty = dirtyCategories.has(cat.id);
    return {
      key: cat.id,
      label: (
        <span>
          {cat.icon}{' '}
          {cat.id === 'recommended' ? (
            <span style={{ color: '#FF6B35', fontWeight: 600 }}>
              <StarFilled style={{ marginRight: 4, fontSize: 12 }} />
              {cat.name}
            </span>
          ) : (
            cat.name
          )}
          <Badge
            count={catDishes.length}
            style={{ marginLeft: 6, backgroundColor: '#f0f0f0', color: '#666', boxShadow: 'none' }}
          />
          {isDirty && (
            <span
              style={{
                display: 'inline-block',
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: '#FF6B35',
                marginLeft: 6,
                verticalAlign: 'middle',
              }}
            />
          )}
        </span>
      ),
    };
  });

  const currentDirtyCount = dirtyCategories.size;

  return (
    <div>
      {/* 页头操作栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div>
          <Text style={{ fontSize: 20, fontWeight: 700 }}>菜品排序管理</Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 13 }}>
            调整菜品在菜单中的展示顺序
          </Text>
        </div>
        <Space>
          {currentDirtyCount > 0 && (
            <Tag color="orange">
              {currentDirtyCount} 个分类有未保存的排序变更
            </Tag>
          )}
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            disabled={currentDirtyCount === 0}
            onClick={handleSave}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            保存排序
          </Button>
        </Space>
      </div>

      {/* 推荐菜品提示 */}
      {activeCategory === 'recommended' && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message='「推荐菜品」分类控制首页推荐展示顺序，排在最前的菜品将优先展示给顾客。'
        />
      )}

      <Card bodyStyle={{ padding: 0 }} loading={categoriesLoading}>
        <Tabs
          activeKey={activeCategory}
          onChange={setActiveCategory}
          items={tabItems}
          tabBarStyle={{ paddingLeft: 16, paddingRight: 16, marginBottom: 0 }}
          tabBarExtraContent={
            <Text type="secondary" style={{ fontSize: 12, paddingRight: 16 }}>
              使用按钮调整排序
            </Text>
          }
        />
        <Divider style={{ margin: 0 }} />
        <div style={{ padding: 16 }}>
          {categoryDishLoading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
              加载菜品中...
            </div>
          ) : (
            <CategorySortList
              dishes={dishes.filter((d) => d.category_id === activeCategory)}
              onChange={(updated) => handleCategoryChange(activeCategory, updated)}
              isDirty={dirtyCategories.has(activeCategory)}
            />
          )}
        </div>
      </Card>
    </div>
  );
}
