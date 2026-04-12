/**
 * 移动端异常汇总
 * 路由: /m/anomaly
 * 聚合: 折扣异常 + 退单异常 + 库存预警 + Agent预警
 */
import { useState } from 'react';
import { MobileLayout } from '../../components/MobileLayout';
import { txFetchData } from '../../api/client';

// ─── 类型 ───

type Severity = 'high' | 'medium' | 'low';
type AnomalyCategory = 'discount' | 'refund' | 'inventory' | 'agent';

interface AnomalyItem {
  id: string;
  store_name: string;
  time: string;
  description: string;
  severity: Severity;
  handled: boolean;
}

interface AnomalyGroup {
  category: AnomalyCategory;
  label: string;
  icon: string;
  count: number;
  items: AnomalyItem[];
}

// ─── Mock 数据 ───

const MOCK_ANOMALIES: AnomalyGroup[] = [
  {
    category: 'discount',
    label: '折扣异常',
    icon: '🏷️',
    count: 2,
    items: [
      {
        id: 'a1',
        store_name: '五一广场店',
        time: '13:42',
        description: '服务员陈某对订单#20240603-0089使用9折折扣，超出授权范围（最高9.5折）',
        severity: 'high',
        handled: false,
      },
      {
        id: 'a2',
        store_name: '解放西路店',
        time: '11:15',
        description: '整单免单操作，操作员：刘某，金额¥328，未见审批记录',
        severity: 'high',
        handled: false,
      },
    ],
  },
  {
    category: 'refund',
    label: '退单异常',
    icon: '↩️',
    count: 0,
    items: [],
  },
  {
    category: 'inventory',
    label: '库存预警',
    icon: '📦',
    count: 1,
    items: [
      {
        id: 'a3',
        store_name: '湘江新区店',
        time: '09:30',
        description: '活鲜鲈鱼库存剩余2条，低于安全库存线（10条），建议立即补货',
        severity: 'medium',
        handled: false,
      },
    ],
  },
  {
    category: 'agent',
    label: 'Agent预警',
    icon: '🤖',
    count: 0,
    items: [],
  },
];

// ─── 工具函数 ───

const SEVERITY_CONFIG: Record<Severity, { label: string; color: string; bg: string }> = {
  high:   { label: '高',  color: '#A32D2D', bg: '#FEF2F2' },
  medium: { label: '中',  color: '#BA7517', bg: '#FFFBEB' },
  low:    { label: '低',  color: '#185FA5', bg: '#EFF6FF' },
};

// ─── 异常条目 ───

function AnomalyItemCard({
  item,
  onHandle,
}: {
  item: AnomalyItem;
  onHandle: (id: string) => void;
}) {
  const sev = SEVERITY_CONFIG[item.severity];

  return (
    <div style={{
      background: item.handled ? '#F8F7F5' : '#fff',
      borderRadius: 10,
      padding: 14,
      marginBottom: 8,
      border: '1px solid #E8E6E1',
      opacity: item.handled ? 0.6 : 1,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#5F5E5A' }}>{item.store_name}</span>
          <span style={{ fontSize: 11, color: '#B4B2A9' }}>{item.time}</span>
        </div>
        <span style={{
          fontSize: 11,
          fontWeight: 600,
          color: sev.color,
          background: sev.bg,
          padding: '2px 8px',
          borderRadius: 10,
        }}>
          {sev.label}
        </span>
      </div>
      <div style={{ fontSize: 13, color: '#2C2C2A', lineHeight: 1.5, marginBottom: 10 }}>
        {item.description}
      </div>
      {!item.handled ? (
        <button
          onClick={() => onHandle(item.id)}
          style={{
            padding: '7px 16px',
            background: '#FF6B35',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            minHeight: 34,
          }}
        >
          标记已处理
        </button>
      ) : (
        <span style={{ fontSize: 12, color: '#0F6E56', fontWeight: 500 }}>✓ 已处理</span>
      )}
    </div>
  );
}

// ─── 主组件 ───

export function MobileAnomalyPage() {
  const [groups, setGroups] = useState<AnomalyGroup[]>(MOCK_ANOMALIES);
  const [expandedKeys, setExpandedKeys] = useState<Set<AnomalyCategory>>(new Set(['discount', 'inventory']));

  const toggleExpand = (cat: AnomalyCategory) => {
    setExpandedKeys(prev => {
      const next = new Set(prev);
      if (next.has(cat)) { next.delete(cat); } else { next.add(cat); }
      return next;
    });
  };

  const handleItem = (id: string) => {
    // 乐观更新
    setGroups(prev => prev.map(g => ({
      ...g,
      items: g.items.map(item =>
        item.id === id ? { ...item, handled: true } : item
      ),
    })));

    // 后端提交（静默失败）
    txFetchData(`/api/v1/anomalies/${id}/handle`, { method: 'POST' }).catch(() => {});
  };

  const totalUnhandled = groups.reduce((sum, g) => sum + g.items.filter(i => !i.handled).length, 0);

  return (
    <MobileLayout title="异常汇总">
      <div style={{ padding: 16 }}>

        {/* 汇总头部 */}
        <div style={{
          background: totalUnhandled > 0 ? '#FEF2F2' : '#F0FDF4',
          borderRadius: 12,
          padding: '14px 16px',
          marginBottom: 16,
          border: `1.5px solid ${totalUnhandled > 0 ? '#A32D2D' : '#0F6E56'}`,
        }}>
          <div style={{ fontSize: 13, color: '#5F5E5A' }}>今日待处理异常</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: totalUnhandled > 0 ? '#A32D2D' : '#0F6E56' }}>
            {totalUnhandled} 条
          </div>
        </div>

        {/* 分类卡片 */}
        {groups.map(group => {
          const isExpanded = expandedKeys.has(group.category);
          const unhandled = group.items.filter(i => !i.handled).length;

          return (
            <div key={group.category} style={{ marginBottom: 10 }}>
              {/* 分类头 */}
              <button
                onClick={() => toggleExpand(group.category)}
                style={{
                  width: '100%',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: '#fff',
                  borderRadius: isExpanded ? '12px 12px 0 0' : 12,
                  padding: '14px 16px',
                  border: 'none',
                  cursor: 'pointer',
                  boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 20 }}>{group.icon}</span>
                  <span style={{ fontSize: 15, fontWeight: 600, color: '#2C2C2A' }}>{group.label}</span>
                  {unhandled > 0 && (
                    <span style={{
                      background: '#A32D2D',
                      color: '#fff',
                      fontSize: 11,
                      fontWeight: 700,
                      borderRadius: 10,
                      padding: '2px 7px',
                    }}>{unhandled}</span>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 13, color: '#B4B2A9' }}>
                    今日 {group.count} 条
                  </span>
                  <span style={{ fontSize: 16, color: '#B4B2A9' }}>
                    {isExpanded ? '▲' : '▼'}
                  </span>
                </div>
              </button>

              {/* 展开内容 */}
              {isExpanded && (
                <div style={{
                  background: '#F8F7F5',
                  borderRadius: '0 0 12px 12px',
                  padding: 12,
                  border: '1px solid #E8E6E1',
                  borderTop: 'none',
                }}>
                  {group.items.length > 0 ? (
                    group.items.map(item => (
                      <AnomalyItemCard key={item.id} item={item} onHandle={handleItem} />
                    ))
                  ) : (
                    <div style={{ textAlign: 'center', padding: '20px 0', color: '#B4B2A9', fontSize: 13 }}>
                      暂无异常
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        <div style={{ height: 8 }} />
      </div>
    </MobileLayout>
  );
}
