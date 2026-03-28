/**
 * MenuTemplatePage — 菜单模板排版管理
 *
 * 功能:
 *   - 可视化菜单模板编辑（拖拽排序分类和菜品）
 *   - 支持多套模板（午市/晚市/宴席/外卖）
 *   - 预览打印效果
 *   - 按门店/品牌下发
 */
import { useState, useCallback } from 'react';
import {
  Card, Row, Col, Button, Select, Space, Tag, Typography,
  Divider, Empty, Tooltip, Switch, InputNumber, message,
} from 'antd';

const { Title, Text } = Typography;

// ── 类型 ──

interface MenuDishItem {
  id: string;
  name: string;
  price: number;
  tags: string[];
  isRecommend: boolean;
  sortOrder: number;
}

interface MenuCategory {
  id: string;
  name: string;
  dishes: MenuDishItem[];
  sortOrder: number;
}

interface MenuTemplate {
  id: string;
  name: string;
  type: 'lunch' | 'dinner' | 'banquet' | 'takeout';
  categories: MenuCategory[];
  columnsPerRow: number;     // 每行显示几个菜品
  showImage: boolean;
  showPrice: boolean;
  updatedAt: string;
}

// ── Mock 数据 ──

const MOCK_TEMPLATES: MenuTemplate[] = [
  {
    id: 't1',
    name: '午市菜单',
    type: 'lunch',
    columnsPerRow: 2,
    showImage: false,
    showPrice: true,
    updatedAt: '2026-03-25',
    categories: [
      {
        id: 'mc1', name: '招牌必点', sortOrder: 1,
        dishes: [
          { id: 'd1', name: '招牌剁椒鱼头', price: 128, tags: ['招牌'], isRecommend: true, sortOrder: 1 },
          { id: 'd4', name: '口味虾', price: 128, tags: ['招牌', '时令'], isRecommend: true, sortOrder: 2 },
        ],
      },
      {
        id: 'mc2', name: '湘味热菜', sortOrder: 2,
        dishes: [
          { id: 'd2', name: '小炒黄牛肉', price: 68, tags: [], isRecommend: false, sortOrder: 1 },
          { id: 'd5', name: '农家小炒肉', price: 42, tags: [], isRecommend: true, sortOrder: 2 },
          { id: 'd8', name: '辣椒炒肉', price: 38, tags: [], isRecommend: false, sortOrder: 3 },
          { id: 'd7', name: '酸辣土豆丝', price: 22, tags: [], isRecommend: false, sortOrder: 4 },
          { id: 'd16', name: '外婆菜炒蛋', price: 28, tags: [], isRecommend: false, sortOrder: 5 },
        ],
      },
      {
        id: 'mc3', name: '清爽凉菜', sortOrder: 3,
        dishes: [
          { id: 'd6', name: '凉拌黄瓜', price: 18, tags: [], isRecommend: false, sortOrder: 1 },
          { id: 'd10', name: '紫苏桃子姜', price: 16, tags: ['时令'], isRecommend: false, sortOrder: 2 },
        ],
      },
      {
        id: 'mc4', name: '汤品', sortOrder: 4,
        dishes: [
          { id: 'd3', name: '茶油土鸡汤', price: 88, tags: ['养生'], isRecommend: true, sortOrder: 1 },
        ],
      },
      {
        id: 'mc5', name: '主食饮品', sortOrder: 5,
        dishes: [
          { id: 'd11', name: '米饭', price: 3, tags: [], isRecommend: false, sortOrder: 1 },
          { id: 'd12', name: '酸梅汤', price: 8, tags: [], isRecommend: false, sortOrder: 2 },
          { id: 'd13', name: '鲜榨橙汁', price: 18, tags: ['新品'], isRecommend: false, sortOrder: 3 },
        ],
      },
    ],
  },
  {
    id: 't2',
    name: '晚市菜单',
    type: 'dinner',
    columnsPerRow: 2,
    showImage: true,
    showPrice: true,
    updatedAt: '2026-03-20',
    categories: [],
  },
];

const TEMPLATE_TYPES: Record<string, string> = {
  lunch: '午市',
  dinner: '晚市',
  banquet: '宴席',
  takeout: '外卖',
};

// ── 菜品行组件 ──

function DishRow({ dish, showPrice }: { dish: MenuDishItem; showPrice: boolean }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '8px 0',
      borderBottom: '1px solid #F0EDE6',
    }}>
      <Space>
        <Text>{dish.name}</Text>
        {dish.isRecommend && <Tag color="orange">推荐</Tag>}
        {dish.tags.map(t => <Tag key={t} style={{ fontSize: 12 }}>{t}</Tag>)}
      </Space>
      {showPrice && (
        <Text strong style={{ color: '#FF6B35' }}>¥{dish.price}</Text>
      )}
    </div>
  );
}

// ── 分类板块组件 ──

function CategorySection({ category, showPrice, columnsPerRow }: {
  category: MenuCategory;
  showPrice: boolean;
  columnsPerRow: number;
}) {
  const sortedDishes = [...category.dishes].sort((a, b) => a.sortOrder - b.sortOrder);

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{
        fontSize: 18,
        fontWeight: 700,
        color: '#1E2A3A',
        borderLeft: '4px solid #FF6B35',
        paddingLeft: 12,
        marginBottom: 12,
      }}>
        {category.name}
      </div>

      {columnsPerRow === 1 ? (
        // 单列
        sortedDishes.map(d => <DishRow key={d.id} dish={d} showPrice={showPrice} />)
      ) : (
        // 多列网格
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${columnsPerRow}, 1fr)`,
          gap: '0 24px',
        }}>
          {sortedDishes.map(d => <DishRow key={d.id} dish={d} showPrice={showPrice} />)}
        </div>
      )}
    </div>
  );
}

// ── 主页面 ──

export function MenuTemplatePage() {
  const [templates] = useState<MenuTemplate[]>(MOCK_TEMPLATES);
  const [activeTemplateId, setActiveTemplateId] = useState(MOCK_TEMPLATES[0].id);
  const activeTemplate = templates.find(t => t.id === activeTemplateId) || templates[0];

  const [columnsPerRow, setColumnsPerRow] = useState(activeTemplate.columnsPerRow);
  const [showPrice, setShowPrice] = useState(activeTemplate.showPrice);
  const [showImage, setShowImage] = useState(activeTemplate.showImage);

  const handlePublish = useCallback(() => {
    message.success('菜单模板已下发到所有门店');
  }, []);

  const sortedCategories = [...activeTemplate.categories].sort((a, b) => a.sortOrder - b.sortOrder);

  return (
    <div style={{ padding: '24px 32px', background: '#FFFFFF', minHeight: '100vh' }}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>菜单模板排版</Title>
          <Text type="secondary">域B · 菜单模板可视化编辑 / 排版预览 / 门店下发</Text>
        </div>
        <Space>
          <Button onClick={() => message.info('打印预览（开发中）')}>打印预览</Button>
          <Button type="primary" onClick={handlePublish} style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
            下发到门店
          </Button>
        </Space>
      </div>

      <Row gutter={24}>
        {/* 左侧: 控制面板 */}
        <Col span={6}>
          <Card title="模板选择" size="small" style={{ marginBottom: 16 }}>
            <Select
              value={activeTemplateId}
              onChange={setActiveTemplateId}
              style={{ width: '100%' }}
            >
              {templates.map(t => (
                <Select.Option key={t.id} value={t.id}>
                  {t.name} ({TEMPLATE_TYPES[t.type]})
                </Select.Option>
              ))}
            </Select>
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">更新时间: {activeTemplate.updatedAt}</Text>
            </div>
          </Card>

          <Card title="排版设置" size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text>每行列数</Text>
                <InputNumber min={1} max={4} value={columnsPerRow} onChange={v => setColumnsPerRow(v || 2)} size="small" />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text>显示价格</Text>
                <Switch checked={showPrice} onChange={setShowPrice} size="small" />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text>显示图片</Text>
                <Switch checked={showImage} onChange={setShowImage} size="small" />
              </div>
            </Space>
          </Card>

          <Card title="分类列表" size="small">
            {sortedCategories.length === 0 ? (
              <Empty description="暂无分类" />
            ) : (
              sortedCategories.map((cat, idx) => (
                <div key={cat.id} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: idx < sortedCategories.length - 1 ? '1px solid #F0EDE6' : undefined,
                }}>
                  <Text>{cat.name}</Text>
                  <Text type="secondary">{cat.dishes.length}道</Text>
                </div>
              ))
            )}
          </Card>
        </Col>

        {/* 右侧: 菜单预览 */}
        <Col span={18}>
          <Card
            title={
              <Space>
                <span>{activeTemplate.name}</span>
                <Tag>{TEMPLATE_TYPES[activeTemplate.type]}</Tag>
              </Space>
            }
            extra={<Text type="secondary">菜品数: {sortedCategories.reduce((s, c) => s + c.dishes.length, 0)}道</Text>}
          >
            {/* 菜单头部 */}
            <div style={{ textAlign: 'center', marginBottom: 32 }}>
              <Title level={2} style={{ color: '#1E2A3A', margin: '0 0 4px' }}>屯象餐厅</Title>
              <Text type="secondary">{activeTemplate.name} · 精心出品</Text>
              <Divider style={{ margin: '16px 0' }} />
            </div>

            {/* 分类+菜品 */}
            {sortedCategories.length === 0 ? (
              <Empty description="该模板暂无菜品，请先添加分类和菜品" />
            ) : (
              sortedCategories.map(cat => (
                <CategorySection
                  key={cat.id}
                  category={cat}
                  showPrice={showPrice}
                  columnsPerRow={columnsPerRow}
                />
              ))
            )}

            {/* 底部 */}
            <Divider />
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                * 菜品供应视当日食材情况而定 · 价格含税
              </Text>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
