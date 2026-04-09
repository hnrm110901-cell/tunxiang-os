/**
 * 菜品需求预测详情 -- 按类别折叠
 * 菜品名 / 预测量 / 当前库存 / 需采购量
 * 类别折叠：凉菜 / 热菜 / 海鲜 / 主食 / 饮品
 * 一键生成采购单按钮
 *
 * 数据源：txFetch（后端 API）
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Select, Button, Spin, Tag, Modal, message, Input, Collapse } from 'antd';
import { ReloadOutlined, ShoppingCartOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetch } from '../../../api';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface StoreOption {
  store_id: string;
  store_name: string;
}

type DishCategory = '凉菜' | '热菜' | '海鲜' | '主食' | '饮品';

interface DemandItem {
  dish_id: string;
  dish_name: string;
  category: DishCategory;
  predicted_qty: number;    // 预测需求量
  current_stock: number;    // 当前库存
  purchase_needed: number;  // 需采购量
  unit: string;             // 份/斤/瓶 等
  confidence: number;       // 预测置信度 0-1
  trend: 'up' | 'down' | 'flat';
}

const CATEGORIES: DishCategory[] = ['凉菜', '热菜', '海鲜', '主食', '饮品'];

const CATEGORY_COLORS: Record<DishCategory, string> = {
  '凉菜': '#185FA5',
  '热菜': '#A32D2D',
  '海鲜': '#0F6E56',
  '主食': '#BA7517',
  '饮品': '#8B5CF6',
};

const TREND_ICONS: Record<string, { icon: string; color: string }> = {
  up: { icon: '↑', color: '#A32D2D' },
  down: { icon: '↓', color: '#0F6E56' },
  flat: { icon: '→', color: '#5F5E5A' },
};

// ─── Mock 数据 ──────────────────────────────────────────────────────────────

function mockStores(): StoreOption[] {
  return [
    { store_id: 's1', store_name: '长沙万达店' },
    { store_id: 's2', store_name: '长沙德思勤店' },
    { store_id: 's3', store_name: '株洲旗舰店' },
  ];
}

function mockDemandItems(): DemandItem[] {
  const dishes: Array<{ name: string; cat: DishCategory; unit: string }> = [
    { name: '凉拌黄瓜', cat: '凉菜', unit: '份' },
    { name: '口水鸡', cat: '凉菜', unit: '份' },
    { name: '皮蛋豆腐', cat: '凉菜', unit: '份' },
    { name: '凉拌木耳', cat: '凉菜', unit: '份' },
    { name: '剁椒鱼头', cat: '热菜', unit: '份' },
    { name: '小炒黄牛肉', cat: '热菜', unit: '份' },
    { name: '辣椒炒肉', cat: '热菜', unit: '份' },
    { name: '红烧肉', cat: '热菜', unit: '份' },
    { name: '回锅肉', cat: '热菜', unit: '份' },
    { name: '宫保鸡丁', cat: '热菜', unit: '份' },
    { name: '麻婆豆腐', cat: '热菜', unit: '份' },
    { name: '口味虾', cat: '海鲜', unit: '份' },
    { name: '蒜蓉蒸虾', cat: '海鲜', unit: '份' },
    { name: '清蒸鲈鱼', cat: '海鲜', unit: '份' },
    { name: '水煮鱼片', cat: '海鲜', unit: '份' },
    { name: '蛋炒饭', cat: '主食', unit: '份' },
    { name: '阳春面', cat: '主食', unit: '份' },
    { name: '糖油粑粑', cat: '主食', unit: '份' },
    { name: '酸梅汤', cat: '饮品', unit: '杯' },
    { name: '鲜榨橙汁', cat: '饮品', unit: '杯' },
    { name: '啤酒', cat: '饮品', unit: '瓶' },
  ];

  const trends: Array<'up' | 'down' | 'flat'> = ['up', 'down', 'flat'];

  return dishes.map((d, i) => {
    const predicted = 20 + Math.floor(Math.random() * 80);
    const stock = Math.floor(Math.random() * 60);
    return {
      dish_id: `d${i}`,
      dish_name: d.name,
      category: d.cat,
      predicted_qty: predicted,
      current_stock: stock,
      purchase_needed: Math.max(0, predicted - stock),
      unit: d.unit,
      confidence: 0.7 + Math.random() * 0.25,
      trend: trends[Math.floor(Math.random() * 3)],
    };
  });
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function DemandForecastPage() {
  const [stores] = useState<StoreOption[]>(mockStores);
  const [selectedStore, setSelectedStore] = useState<string>('s1');
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<DemandItem[]>([]);
  const [searchText, setSearchText] = useState('');
  const [generating, setGenerating] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // TODO: 后端就绪后替换
      // const res = await txFetch<{ items: DemandItem[] }>(
      //   `/api/v1/predict/demand/list?store_id=${selectedStore}`,
      // );
      await new Promise(r => setTimeout(r, 400));
      setItems(mockDemandItems());
    } finally {
      setLoading(false);
    }
  }, [selectedStore]);

  useEffect(() => { loadData(); }, [loadData]);

  // ─── 过滤和分组 ───

  const filteredItems = useMemo(() => {
    if (!searchText) return items;
    const lower = searchText.toLowerCase();
    return items.filter(i => i.dish_name.toLowerCase().includes(lower));
  }, [items, searchText]);

  const groupedByCategory = useMemo(() => {
    const groups: Record<DishCategory, DemandItem[]> = {
      '凉菜': [], '热菜': [], '海鲜': [], '主食': [], '饮品': [],
    };
    filteredItems.forEach(item => {
      if (groups[item.category]) groups[item.category].push(item);
    });
    return groups;
  }, [filteredItems]);

  const totalPurchaseItems = items.filter(i => i.purchase_needed > 0).length;
  const totalPurchaseQty = items.reduce((s, i) => s + i.purchase_needed, 0);

  // ─── 生成采购单 ───

  const handleGeneratePO = () => {
    const needPurchase = items.filter(i => i.purchase_needed > 0);
    if (needPurchase.length === 0) {
      message.info('当前库存充足，无需采购');
      return;
    }
    Modal.confirm({
      title: '确认生成采购单',
      content: (
        <div>
          <p>将为以下 <b>{needPurchase.length}</b> 个品项生成采购单：</p>
          <div style={{ maxHeight: 200, overflow: 'auto', fontSize: 13 }}>
            {needPurchase.map(i => (
              <div key={i.dish_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span>{i.dish_name}</span>
                <span style={{ color: '#FF6B35', fontWeight: 600 }}>{i.purchase_needed} {i.unit}</span>
              </div>
            ))}
          </div>
        </div>
      ),
      okText: '确认生成',
      cancelText: '取消',
      onOk: async () => {
        setGenerating(true);
        try {
          // TODO: 后端就绪后替换
          // await txFetch('/api/v1/supply/purchase-order/generate', {
          //   method: 'POST',
          //   body: JSON.stringify({ store_id: selectedStore, items: needPurchase }),
          // });
          await new Promise(r => setTimeout(r, 800));
          message.success(`已生成采购单，包含 ${needPurchase.length} 个品项`);
        } finally {
          setGenerating(false);
        }
      },
    });
  };

  // ─── 库存状态 ───

  const stockStatus = (item: DemandItem) => {
    const ratio = item.current_stock / Math.max(1, item.predicted_qty);
    if (ratio >= 1) return { color: '#0F6E56', label: '充足' };
    if (ratio >= 0.5) return { color: '#BA7517', label: '偏低' };
    return { color: '#A32D2D', label: '不足' };
  };

  // ─── Collapse items ───

  const collapseItems = CATEGORIES
    .filter(cat => groupedByCategory[cat].length > 0)
    .map(cat => {
      const catItems = groupedByCategory[cat];
      const catPurchaseCount = catItems.filter(i => i.purchase_needed > 0).length;
      return {
        key: cat,
        label: (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{
              display: 'inline-block', width: 4, height: 16, borderRadius: 2,
              background: CATEGORY_COLORS[cat],
            }} />
            <span style={{ fontWeight: 600, color: '#2C2C2A' }}>{cat}</span>
            <Tag style={{ margin: 0 }}>{catItems.length} 道</Tag>
            {catPurchaseCount > 0 && (
              <Tag color="orange" style={{ margin: 0 }}>{catPurchaseCount} 需采购</Tag>
            )}
          </div>
        ),
        children: (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #E8E6E1' }}>
                <th style={{ padding: '8px 12px', textAlign: 'left', color: '#5F5E5A', fontWeight: 500 }}>
                  菜品名称
                </th>
                <th style={{ padding: '8px 12px', textAlign: 'right', color: '#5F5E5A', fontWeight: 500 }}>
                  预测需求量
                </th>
                <th style={{ padding: '8px 12px', textAlign: 'right', color: '#5F5E5A', fontWeight: 500 }}>
                  当前库存
                </th>
                <th style={{ padding: '8px 12px', textAlign: 'right', color: '#5F5E5A', fontWeight: 500 }}>
                  需采购量
                </th>
                <th style={{ padding: '8px 12px', textAlign: 'center', color: '#5F5E5A', fontWeight: 500 }}>
                  趋势
                </th>
                <th style={{ padding: '8px 12px', textAlign: 'center', color: '#5F5E5A', fontWeight: 500 }}>
                  置信度
                </th>
              </tr>
            </thead>
            <tbody>
              {catItems.map(item => {
                const status = stockStatus(item);
                const trend = TREND_ICONS[item.trend];
                return (
                  <tr key={item.dish_id} style={{ borderBottom: '1px solid #F0EDE6' }}>
                    <td style={{ padding: '10px 12px', color: '#2C2C2A', fontWeight: 500 }}>
                      {item.dish_name}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', color: '#2C2C2A' }}>
                      {item.predicted_qty} {item.unit}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                      <span style={{ color: status.color, fontWeight: 500 }}>
                        {item.current_stock} {item.unit}
                      </span>
                      <Tag
                        style={{ marginLeft: 8, fontSize: 11 }}
                        color={status.color === '#0F6E56' ? 'green' : status.color === '#BA7517' ? 'orange' : 'red'}
                      >
                        {status.label}
                      </Tag>
                    </td>
                    <td style={{
                      padding: '10px 12px', textAlign: 'right',
                      fontWeight: item.purchase_needed > 0 ? 700 : 400,
                      color: item.purchase_needed > 0 ? '#FF6B35' : '#B4B2A9',
                    }}>
                      {item.purchase_needed > 0 ? `${item.purchase_needed} ${item.unit}` : '-'}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                      <span style={{ color: trend.color, fontWeight: 600 }}>
                        {trend.icon}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                      <div style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                      }}>
                        <div style={{
                          width: 40, height: 4, borderRadius: 2, background: '#E8E6E1',
                          position: 'relative', overflow: 'hidden',
                        }}>
                          <div style={{
                            position: 'absolute', left: 0, top: 0, height: '100%',
                            borderRadius: 2,
                            width: `${item.confidence * 100}%`,
                            background: item.confidence >= 0.85 ? '#0F6E56' : item.confidence >= 0.7 ? '#BA7517' : '#A32D2D',
                          }} />
                        </div>
                        <span style={{ fontSize: 11, color: '#B4B2A9' }}>
                          {(item.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ),
      };
    });

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      {/* ─── 顶部筛选栏 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 24, flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>菜品需求预测</h2>
          <Select
            value={selectedStore}
            onChange={setSelectedStore}
            style={{ width: 180 }}
            options={stores.map(s => ({ label: s.store_name, value: s.store_id }))}
          />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Input
            prefix={<SearchOutlined />}
            placeholder="搜索菜品..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            allowClear
            style={{ width: 200 }}
          />
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<ShoppingCartOutlined />}
            onClick={handleGeneratePO}
            loading={generating}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            一键生成采购单
          </Button>
        </div>
      </div>

      {/* ─── 汇总卡片 ─── */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: 16, marginBottom: 24,
      }}>
        <div style={{
          background: '#fff', borderRadius: 8, padding: 16,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 13, color: '#5F5E5A' }}>总品项数</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#2C2C2A' }}>{items.length}</div>
        </div>
        <div style={{
          background: '#fff', borderRadius: 8, padding: 16,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 13, color: '#5F5E5A' }}>需采购品项</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#FF6B35' }}>{totalPurchaseItems}</div>
        </div>
        <div style={{
          background: '#fff', borderRadius: 8, padding: 16,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 13, color: '#5F5E5A' }}>总采购量</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#BA7517' }}>{totalPurchaseQty}</div>
        </div>
        <div style={{
          background: '#fff', borderRadius: 8, padding: 16,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 13, color: '#5F5E5A' }}>库存充足率</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#0F6E56' }}>
            {items.length > 0 ? ((items.filter(i => i.purchase_needed === 0).length / items.length) * 100).toFixed(0) : 0}%
          </div>
        </div>
      </div>

      <Spin spinning={loading}>
        {/* ─── 按类别折叠列表 ─── */}
        <div style={{
          background: '#fff', borderRadius: 8,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          overflow: 'hidden',
        }}>
          <Collapse
            defaultActiveKey={CATEGORIES}
            items={collapseItems}
            style={{ border: 'none', background: '#fff' }}
          />
        </div>
      </Spin>
    </div>
  );
}

export default DemandForecastPage;
