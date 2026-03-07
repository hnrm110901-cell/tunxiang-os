import React, { useState, useCallback } from 'react';
import { Form, Input, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZEmpty, ZSelect, ZTable } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components';
import { apiClient, handleApiError } from '../services/api';
import styles from './RecommendationsPage.module.css';

// ── Types ──────────────────────────────────────────────────────────────────────

interface DishRecommendation {
  dish_id: string;
  dish_name: string;
  score: number;
  reason: string;
  price: number;
  estimated_profit: number;
  confidence: number;
  recommendation_type?: string;
}

interface RecommendResult {
  customer_id: string;
  store_id: string;
  recommendations: DishRecommendation[];
  generated_at?: string;
}

// ── Table columns ──────────────────────────────────────────────────────────────

const dishColumns: ZTableColumn<DishRecommendation>[] = [
  {
    key: 'dish_name',
    title: '菜品',
    render: (name) => <strong>{name}</strong>,
  },
  {
    key: 'score',
    title: '匹配度',
    width: 130,
    render: (score) => {
      const pct = Math.round((score || 0) * 100);
      const color = pct >= 80 ? 'var(--green)' : pct >= 60 ? '#fa8c16' : 'var(--text-secondary)';
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ flex: 1, height: 5, background: '#f0f0f0', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
          </div>
          <span style={{ fontSize: 12, color, minWidth: 30 }}>{pct}%</span>
        </div>
      );
    },
  },
  {
    key: 'price',
    title: '定价',
    align: 'right',
    render: (v) => v != null ? `¥${Number(v).toFixed(2)}` : '-',
  },
  {
    key: 'estimated_profit',
    title: '预估毛利',
    align: 'right',
    render: (v) => v != null
      ? <span style={{ color: 'var(--green)', fontWeight: 600 }}>¥{Number(v).toFixed(2)}</span>
      : '-',
  },
  {
    key: 'confidence',
    title: '置信度',
    align: 'center',
    render: (v) => {
      const pct = Math.round((v || 0) * 100);
      return <ZBadge type={pct >= 80 ? 'success' : pct >= 60 ? 'warning' : 'neutral'} text={`${pct}%`} />;
    },
  },
  {
    key: 'reason',
    title: '推荐理由',
    render: (r) => <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{r}</span>,
  },
];

// ── Store options ──────────────────────────────────────────────────────────────

const STORE_OPTIONS = [
  { value: 'STORE001', label: '门店 001' },
  { value: 'STORE002', label: '门店 002' },
  { value: 'STORE003', label: '门店 003' },
];

const TOPK_OPTIONS = [
  { value: '3', label: '推荐 3 道' },
  { value: '5', label: '推荐 5 道' },
  { value: '8', label: '推荐 8 道' },
  { value: '10', label: '推荐 10 道' },
];

const CONTEXT_OPTIONS = [
  { value: '', label: '无特定场景' },
  { value: 'lunch', label: '午餐时段' },
  { value: 'dinner', label: '晚餐时段' },
  { value: 'weekend', label: '周末聚餐' },
  { value: 'birthday', label: '生日场合' },
];

// ── Component ──────────────────────────────────────────────────────────────────

const RecommendationsPage: React.FC = () => {
  const [storeId, setStoreId] = useState(localStorage.getItem('store_id') || 'STORE001');
  const [customerId, setCustomerId] = useState('');
  const [topK, setTopK] = useState('5');
  const [context, setContext] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [lastQueried, setLastQueried] = useState<string | null>(null);

  const handleSearch = useCallback(async () => {
    if (!customerId.trim()) {
      message.warning('请输入顾客手机号或会员ID');
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const payload: Record<string, unknown> = {
        customer_id: customerId.trim(),
        store_id: storeId,
        top_k: parseInt(topK),
      };
      if (context) {
        payload.context = { occasion: context };
      }
      const res = await apiClient.post('/api/v1/recommendations/dishes', payload);
      const data = res.data;
      setResult({
        customer_id: customerId.trim(),
        store_id: storeId,
        recommendations: Array.isArray(data.recommendations) ? data.recommendations : (Array.isArray(data) ? data : []),
        generated_at: new Date().toLocaleTimeString('zh-CN'),
      });
      setLastQueried(customerId.trim());
    } catch (e) {
      handleApiError(e);
    } finally {
      setLoading(false);
    }
  }, [customerId, storeId, topK, context]);

  const recs = result?.recommendations || [];
  const avgScore = recs.length > 0
    ? Math.round(recs.reduce((s, r) => s + (r.score || 0), 0) / recs.length * 100)
    : 0;
  const totalProfit = recs.reduce((s, r) => s + (r.estimated_profit || 0), 0);

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>个性化推荐引擎</h1>
          <p className={styles.pageSub}>基于协同过滤 + 菜品内容 + 场景感知的混合推荐</p>
        </div>
      </div>

      {/* Query bar */}
      <ZCard>
        <div className={styles.queryBar}>
          <div className={styles.queryField}>
            <label className={styles.queryLabel}>门店</label>
            <ZSelect
              value={storeId}
              options={STORE_OPTIONS}
              onChange={(v) => { setStoreId(v); localStorage.setItem('store_id', v); }}
            />
          </div>
          <div className={styles.queryFieldGrow}>
            <label className={styles.queryLabel}>顾客手机号 / 会员ID</label>
            <Input
              placeholder="输入顾客手机号或会员ID后按 Enter 查询"
              prefix={<SearchOutlined style={{ color: 'var(--text-secondary)' }} />}
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              onPressEnter={handleSearch}
              style={{ borderRadius: 8 }}
            />
          </div>
          <div className={styles.queryField}>
            <label className={styles.queryLabel}>推荐数量</label>
            <ZSelect value={topK} options={TOPK_OPTIONS} onChange={setTopK} />
          </div>
          <div className={styles.queryField}>
            <label className={styles.queryLabel}>就餐场景</label>
            <ZSelect value={context} options={CONTEXT_OPTIONS} onChange={setContext} />
          </div>
          <ZButton
            variant="primary"
            disabled={loading}
            onClick={handleSearch}
          >
            {loading ? '推荐中…' : '获取推荐'}
          </ZButton>
        </div>
      </ZCard>

      {/* KPI cards — only when results exist */}
      {result && (
        <div className={styles.kpiGrid}>
          <ZCard>
            <ZKpi label="推荐菜品数" value={recs.length} unit="道" />
          </ZCard>
          <ZCard>
            <ZKpi label="平均匹配度" value={avgScore} unit="%" />
          </ZCard>
          <ZCard>
            <ZKpi label="预估总毛利" value={`¥${totalProfit.toFixed(2)}`} />
          </ZCard>
          <ZCard>
            <ZKpi label="查询顾客" value={lastQueried || '-'} />
          </ZCard>
        </div>
      )}

      {/* Results */}
      <ZCard
        title={result ? `推荐结果 — ${result.customer_id}` : '推荐结果'}
        extra={result?.generated_at && (
          <span className={styles.genTime}>生成于 {result.generated_at}</span>
        )}
      >
        {loading ? (
          <ZSkeleton height={240} />
        ) : recs.length > 0 ? (
          <ZTable
            columns={dishColumns}
            data={recs}
            rowKey="dish_id"
          />
        ) : (
          <ZEmpty text={result ? '该顾客暂无推荐菜品（订单历史不足）' : '请输入顾客信息并点击「获取推荐」'} />
        )}
      </ZCard>

      {/* Algorithm explainer */}
      <ZCard title="推荐算法说明">
        <div className={styles.algoGrid}>
          <div className={styles.algoItem}>
            <div className={styles.algoTitle}>协同过滤</div>
            <div className={styles.algoDesc}>找到消费行为相似的顾客群体，推荐他们喜爱但该顾客未点过的菜品</div>
          </div>
          <div className={styles.algoItem}>
            <div className={styles.algoTitle}>内容匹配</div>
            <div className={styles.algoDesc}>基于顾客口味偏好向量（辣度/素食/海鲜/肉类/甜品）与菜品特征进行余弦相似度匹配</div>
          </div>
          <div className={styles.algoItem}>
            <div className={styles.algoTitle}>场景感知</div>
            <div className={styles.algoDesc}>结合就餐时段（午/晚/周末）、节假日、天气等上下文动态调整推荐权重</div>
          </div>
          <div className={styles.algoItem}>
            <div className={styles.algoTitle}>商业规则</div>
            <div className={styles.algoDesc}>兼顾高毛利菜品、库存充足食材、门店主推商品，在个性化与商业目标间平衡</div>
          </div>
        </div>
      </ZCard>
    </div>
  );
};

export default RecommendationsPage;
