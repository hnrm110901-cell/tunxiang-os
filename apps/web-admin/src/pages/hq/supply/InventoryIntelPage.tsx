/**
 * 库存智能补货页 — Inventory Intel
 * 域D 供应链 · 采购员视角
 * 深色主题，与 EventBusHealthPage 风格一致
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetch } from '../../../api';

// ─── 类型定义 ───

interface IngredientStock {
  id: string;
  name: string;
  current_qty: number;
  unit: string;
  safety_stock_qty: number;
  status: 'out_of_stock' | 'critical' | 'low' | 'normal';
  expiry_date?: string;
  preferred_supplier: string;
  last_price_fen: number;
}

interface InventorySummary {
  out_of_stock: number;
  critical: number;
  low_stock: number;
  normal: number;
  expiring_soon: number;
  expired: number;
}

interface DashboardData {
  summary: InventorySummary;
  low_items: IngredientStock[];
}

interface RestockAlertItem {
  ingredient_id?: string;
  name: string;
  suggested_qty: number;
  unit?: string;
  estimated_cost_fen?: number;
  urgency?: 'urgent' | 'high' | 'medium' | 'low';
  reason?: string;
}

interface AIPlanData {
  restock_alerts: RestockAlertItem[];
  severity: Record<string, unknown>;
  ai_reasoning: string;
  confidence: number;
  constraints_ok: boolean;
  execution_ms: number;
}

interface OrchestrateResult {
  synthesis?: string;
  recommended_actions?: Array<{
    action: string;
    reason: string;
    priority: string;
  }>;
}

// ─── 常量 ───

const STORES = [
  { id: 'store_001', name: '尝在一起·芙蓉路店' },
  { id: 'store_002', name: '尝在一起·解放西路店' },
  { id: 'store_003', name: '最黔线·五一广场店' },
];

// ─── 工具函数 ───

function statusConfig(status: IngredientStock['status']): { label: string; color: string; bg: string } {
  switch (status) {
    case 'out_of_stock': return { label: '缺货',   color: '#FF4D4D', bg: '#FF4D4D22' };
    case 'critical':     return { label: '临界',   color: '#E55A28', bg: '#E55A2822' };
    case 'low':          return { label: '低库存', color: '#BA7517', bg: '#BA751722' };
    case 'normal':       return { label: '正常',   color: '#0F6E56', bg: '#0F6E5622' };
    default:             return { label: status,   color: '#888',    bg: '#88888822' };
  }
}

function urgencyConfig(urgency?: string): { label: string; color: string } {
  switch (urgency) {
    case 'urgent': return { label: '紧急', color: '#FF4D4D' };
    case 'high':   return { label: '高',   color: '#E55A28' };
    case 'medium': return { label: '中',   color: '#BA7517' };
    default:       return { label: '低',   color: '#0F6E56' };
  }
}

function fenToYuan(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

/** 根据缺货量和安全库存计算建议补货量 */
function calcSuggestedQty(item: IngredientStock): number {
  const gap = item.safety_stock_qty - item.current_qty;
  // 补到安全库存的 1.5 倍，最少补 1 个单位
  return Math.max(1, Math.ceil(gap * 1.5));
}

// ─── 子组件：统计卡片 ───

interface StatCardProps {
  emoji: string;
  label: string;
  value: number;
  color: string;
  bg: string;
}

function StatCard({ emoji, label, value, color, bg }: StatCardProps) {
  return (
    <div style={{
      background: '#1a2a33',
      border: `1px solid ${color}44`,
      borderRadius: 10,
      padding: '14px 18px',
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      flex: 1,
      minWidth: 120,
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: bg, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: 20, flexShrink: 0,
      }}>
        {emoji}
      </div>
      <div>
        <div style={{ fontSize: 24, fontWeight: 700, color, lineHeight: 1.1 }}>
          {value}
        </div>
        <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{label}</div>
      </div>
    </div>
  );
}

// ─── 主页面 ───

export function InventoryIntelPage() {
  const [storeId, setStoreId] = useState(STORES[0].id);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loadingDash, setLoadingDash] = useState(true);

  // 多选状态
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // AI 补货计划
  const [aiLoading, setAiLoading] = useState(false);
  const [aiPlan, setAiPlan] = useState<AIPlanData | null>(null);
  const [aiOrchestrate, setAiOrchestrate] = useState<OrchestrateResult | null>(null);
  const [planExpanded, setPlanExpanded] = useState(false);

  // 手动调整的补货量（item.id → qty）
  const [suggestedQty, setSuggestedQty] = useState<Record<string, number>>({});

  // ── 拉取库存总览 ──
  const fetchDashboard = useCallback(async () => {
    setLoadingDash(true);
    setSelectedIds(new Set());
    try {
      const data = await txFetch<DashboardData>(
        `/api/v1/inventory/dashboard?store_id=${encodeURIComponent(storeId)}`,
      );
      setDashboard(data);
      // 初始化建议补货量
      const qtyMap: Record<string, number> = {};
      (data.low_items || []).forEach((item) => {
        qtyMap[item.id] = calcSuggestedQty(item);
      });
      setSuggestedQty(qtyMap);
    } catch {
      setDashboard({ summary: {} as InventorySummary, low_items: [] });
    } finally {
      setLoadingDash(false);
    }
  }, [storeId]);

  useEffect(() => { fetchDashboard(); }, [fetchDashboard]);

  // ── 生成 AI 补货计划 ──
  const generatePlan = async () => {
    setAiLoading(true);
    setPlanExpanded(true);
    setAiPlan(null);
    setAiOrchestrate(null);

    const lowItems = dashboard?.low_items || [];

    try {
      // 同时调用聚合接口和 Orchestrate
      const [planResult, orchestrateResult] = await Promise.allSettled([
        txFetch<AIPlanData>(`/api/v1/inventory/restock-plan?store_id=${encodeURIComponent(storeId)}`, {
          method: 'POST',
        }),
        txFetch<OrchestrateResult>('/api/v1/orchestrate', {
          method: 'POST',
          body: JSON.stringify({
            intent: `为门店 ${storeId} 生成今日补货计划，分析所有低库存食材，给出优先级和建议采购量`,
            context: {
              store_id: storeId,
              low_items: lowItems.map((i) => i.name),
            },
          }),
        }),
      ]);

      if (planResult.status === 'fulfilled') setAiPlan(planResult.value);
      if (orchestrateResult.status === 'fulfilled') setAiOrchestrate(orchestrateResult.value);
    } catch {
      // 保持已有数据，不清空
    } finally {
      setAiLoading(false);
    }
  };

  // ── 多选处理 ──
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const items = dashboard?.low_items || [];
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((i) => i.id)));
    }
  };

  const addToCart = (id: string) => {
    setSelectedIds((prev) => new Set([...prev, id]));
  };

  // ── 导出 CSV ──
  const exportCSV = () => {
    const items = dashboard?.low_items || [];
    const selected = items.filter((i) => selectedIds.has(i.id));
    const target = selected.length > 0 ? selected : items;

    const rows = target.map((item) =>
      [
        item.name,
        item.current_qty,
        item.unit,
        suggestedQty[item.id] ?? calcSuggestedQty(item),
        item.preferred_supplier,
        fenToYuan(item.last_price_fen),
        item.status,
      ].join(','),
    );

    const csv = ['食材名,当前库存,单位,建议采购量,供应商,最后进价,状态', ...rows].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `补货单_${new Date().toLocaleDateString('zh-CN')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const summary = dashboard?.summary ?? ({} as InventorySummary);
  const lowItems = dashboard?.low_items ?? [];
  const allSelected = lowItems.length > 0 && selectedIds.size === lowItems.length;
  const someSelected = selectedIds.size > 0 && !allSelected;
  const storeName = STORES.find((s) => s.id === storeId)?.name ?? storeId;

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>

      {/* ── 页头 ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>📦 库存智能补货</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            AI 驱动的采购建议 · 实时库存预警
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* 门店选择 */}
          <select
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
            style={{
              padding: '7px 12px', borderRadius: 8,
              border: '1px solid #2a3a44', background: '#1a2a33',
              color: '#fff', fontSize: 13, cursor: 'pointer', outline: 'none',
            }}
          >
            {STORES.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>

          {/* 刷新 */}
          <button
            onClick={fetchDashboard}
            style={{
              padding: '7px 14px', borderRadius: 8,
              border: '1px solid #2a3a44', background: 'transparent',
              color: '#888', cursor: 'pointer', fontSize: 13,
            }}
          >
            ↻ 刷新
          </button>

          {/* AI 生成补货计划 */}
          <button
            onClick={generatePlan}
            disabled={aiLoading}
            style={{
              padding: '7px 18px', borderRadius: 8,
              border: 'none', background: aiLoading ? '#2a3a44' : '#FF6B35',
              color: '#fff', cursor: aiLoading ? 'not-allowed' : 'pointer',
              fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            {aiLoading ? (
              <><span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⏳</span> AI 分析中...</>
            ) : (
              <>🤖 AI 生成补货计划</>
            )}
          </button>
        </div>
      </div>

      {loadingDash ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
      ) : (
        <>
          {/* ── 统计行 ── */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
            <StatCard emoji="🚨" label="缺货"     value={summary.out_of_stock  ?? 0} color="#FF4D4D" bg="#FF4D4D22" />
            <StatCard emoji="⚠️"  label="临界"     value={summary.critical      ?? 0} color="#E55A28" bg="#E55A2822" />
            <StatCard emoji="📉" label="低库存"   value={summary.low_stock     ?? 0} color="#BA7517" bg="#BA751722" />
            <StatCard emoji="✅" label="正常"     value={summary.normal        ?? 0} color="#0F6E56" bg="#0F6E5622" />
            <StatCard emoji="⏰" label="即将临期" value={summary.expiring_soon ?? 0} color="#BA7517" bg="#BA751722" />
            <StatCard emoji="❌" label="已过期"   value={summary.expired       ?? 0} color="#FF4D4D" bg="#FF4D4D22" />
          </div>

          {/* ── 库存状态表格 ── */}
          <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', marginBottom: 24 }}>
            {/* 表格工具栏 */}
            <div style={{
              padding: '14px 20px', borderBottom: '1px solid #2a3a44',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div style={{ fontSize: 14, color: '#ccc', fontWeight: 600 }}>
                低库存 / 缺货食材清单
                <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>
                  共 {lowItems.length} 项
                  {selectedIds.size > 0 && `，已选 ${selectedIds.size} 项`}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {selectedIds.size > 0 && (
                  <button
                    onClick={exportCSV}
                    style={{
                      padding: '5px 14px', borderRadius: 6,
                      border: '1px solid #0F6E56', background: '#0F6E5622',
                      color: '#0F6E56', cursor: 'pointer', fontSize: 12,
                    }}
                  >
                    📤 导出选中 ({selectedIds.size})
                  </button>
                )}
                <button
                  onClick={exportCSV}
                  style={{
                    padding: '5px 14px', borderRadius: 6,
                    border: '1px solid #2a3a44', background: 'transparent',
                    color: '#888', cursor: 'pointer', fontSize: 12,
                  }}
                >
                  📤 导出全部
                </button>
              </div>
            </div>

            {lowItems.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: '#888' }}>
                ✅ 暂无低库存或缺货食材
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#0d1e28' }}>
                    <th style={{ padding: '10px 16px', width: 40 }}>
                      <input
                        type="checkbox"
                        checked={allSelected}
                        ref={(el) => { if (el) el.indeterminate = someSelected; }}
                        onChange={toggleSelectAll}
                        style={{ cursor: 'pointer', accentColor: '#FF6B35' }}
                      />
                    </th>
                    {['食材名', '当前库存', '安全库存', '状态', '建议补货量', '首选供应商', '最后进价', '操作'].map((h) => (
                      <th key={h} style={{
                        padding: '10px 16px', textAlign: 'left',
                        color: '#888', fontSize: 12, fontWeight: 500,
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {lowItems.map((item) => {
                    const sc = statusConfig(item.status);
                    const isSelected = selectedIds.has(item.id);
                    return (
                      <tr
                        key={item.id}
                        style={{
                          borderBottom: '1px solid #2a3a4440',
                          background: isSelected ? '#FF6B3510' : 'transparent',
                          transition: 'background 0.15s',
                        }}
                        onMouseEnter={(e) => {
                          if (!isSelected) (e.currentTarget as HTMLTableRowElement).style.background = '#ffffff08';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLTableRowElement).style.background = isSelected ? '#FF6B3510' : 'transparent';
                        }}
                      >
                        {/* Checkbox */}
                        <td style={{ padding: '12px 16px' }}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(item.id)}
                            style={{ cursor: 'pointer', accentColor: '#FF6B35' }}
                          />
                        </td>

                        {/* 食材名 */}
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>
                            {item.name}
                          </div>
                          {item.expiry_date && (
                            <div style={{ fontSize: 11, color: '#BA7517', marginTop: 2 }}>
                              ⏰ 到期 {item.expiry_date}
                            </div>
                          )}
                        </td>

                        {/* 当前库存 */}
                        <td style={{ padding: '12px 16px' }}>
                          <span style={{ color: sc.color, fontWeight: 700, fontSize: 15 }}>
                            {item.current_qty}
                          </span>
                          <span style={{ color: '#888', fontSize: 12, marginLeft: 4 }}>{item.unit}</span>
                        </td>

                        {/* 安全库存 */}
                        <td style={{ padding: '12px 16px', color: '#888', fontSize: 13 }}>
                          {item.safety_stock_qty} {item.unit}
                        </td>

                        {/* 状态徽章 */}
                        <td style={{ padding: '12px 16px' }}>
                          <span style={{
                            padding: '3px 10px', borderRadius: 12, fontSize: 12,
                            background: sc.bg, color: sc.color, fontWeight: 600,
                          }}>
                            {sc.label}
                          </span>
                        </td>

                        {/* 建议补货量（可编辑） */}
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input
                              type="number"
                              min={0}
                              value={suggestedQty[item.id] ?? calcSuggestedQty(item)}
                              onChange={(e) => {
                                const v = parseFloat(e.target.value) || 0;
                                setSuggestedQty((prev) => ({ ...prev, [item.id]: v }));
                              }}
                              style={{
                                width: 70, padding: '4px 8px', borderRadius: 6,
                                border: '1px solid #2a3a44', background: '#0d1e28',
                                color: '#fff', fontSize: 13, outline: 'none',
                                textAlign: 'center',
                              }}
                            />
                            <span style={{ color: '#888', fontSize: 12 }}>{item.unit}</span>
                          </div>
                        </td>

                        {/* 供应商 */}
                        <td style={{ padding: '12px 16px', color: '#ccc', fontSize: 13 }}>
                          {item.preferred_supplier}
                        </td>

                        {/* 进价 */}
                        <td style={{ padding: '12px 16px', color: '#ccc', fontSize: 13 }}>
                          {item.last_price_fen > 0 ? fenToYuan(item.last_price_fen) : '—'}
                        </td>

                        {/* 操作 */}
                        <td style={{ padding: '12px 16px' }}>
                          <button
                            onClick={() => addToCart(item.id)}
                            disabled={isSelected}
                            style={{
                              padding: '4px 12px', borderRadius: 6,
                              border: `1px solid ${isSelected ? '#0F6E56' : '#2a3a44'}`,
                              background: isSelected ? '#0F6E5622' : 'transparent',
                              color: isSelected ? '#0F6E56' : '#888',
                              cursor: isSelected ? 'default' : 'pointer',
                              fontSize: 12, whiteSpace: 'nowrap',
                            }}
                          >
                            {isSelected ? '✓ 已选' : '📋 加入补货单'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* ── AI 补货计划面板 ── */}
          {planExpanded && (
            <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden' }}>
              {/* 面板标题栏 */}
              <div style={{
                padding: '14px 20px', borderBottom: '1px solid #2a3a44',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 18 }}>🤖</span>
                  <div>
                    <div style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>
                      AI 补货计划
                    </div>
                    {aiPlan && !aiLoading && (
                      <div style={{ color: '#888', fontSize: 11, marginTop: 1 }}>
                        置信度 {Math.round(aiPlan.confidence * 100)}%
                        · 耗时 {aiPlan.execution_ms}ms
                        {aiPlan.constraints_ok
                          ? <span style={{ color: '#0F6E56' }}> · ✓ 硬约束通过</span>
                          : <span style={{ color: '#FF4D4D' }}> · ✗ 约束警告</span>}
                      </div>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {!aiLoading && (aiPlan || aiOrchestrate) && (
                    <button
                      onClick={exportCSV}
                      style={{
                        padding: '5px 14px', borderRadius: 6,
                        border: '1px solid #FF6B35', background: '#FF6B3522',
                        color: '#FF6B35', cursor: 'pointer', fontSize: 12, fontWeight: 600,
                      }}
                    >
                      📤 导出为采购单
                    </button>
                  )}
                  <button
                    onClick={() => setPlanExpanded(false)}
                    style={{
                      padding: '5px 10px', borderRadius: 6,
                      border: '1px solid #2a3a44', background: 'transparent',
                      color: '#888', cursor: 'pointer', fontSize: 12,
                    }}
                  >
                    ✕ 关闭
                  </button>
                </div>
              </div>

              {/* 面板内容 */}
              <div style={{ padding: 20 }}>
                {aiLoading ? (
                  <div style={{ textAlign: 'center', padding: '40px 0', color: '#888' }}>
                    <div style={{ fontSize: 36, marginBottom: 12, animation: 'pulse 1.5s ease-in-out infinite' }}>🤖</div>
                    <div style={{ fontSize: 15, fontWeight: 600, color: '#ccc' }}>AI 分析中...</div>
                    <div style={{ fontSize: 13, marginTop: 6 }}>
                      正在分析 {storeName} 的库存状态，生成最优补货方案
                    </div>
                  </div>
                ) : (
                  <div>
                    {/* AI 综合分析说明 */}
                    {(aiOrchestrate?.synthesis || aiPlan?.ai_reasoning) && (
                      <div style={{
                        background: '#185FA522', border: '1px solid #185FA544',
                        borderRadius: 10, padding: '14px 18px', marginBottom: 20,
                      }}>
                        <div style={{ color: '#185FA5', fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
                          🧠 AI 分析说明
                        </div>
                        <div style={{ color: '#ccc', fontSize: 13, lineHeight: 1.7 }}>
                          {aiOrchestrate?.synthesis || aiPlan?.ai_reasoning || '暂无分析说明'}
                        </div>
                      </div>
                    )}

                    {/* Orchestrate 推荐行动 */}
                    {aiOrchestrate?.recommended_actions && aiOrchestrate.recommended_actions.length > 0 && (
                      <div style={{ marginBottom: 20 }}>
                        <div style={{ color: '#888', fontSize: 12, marginBottom: 10, fontWeight: 600 }}>
                          推荐行动
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {aiOrchestrate.recommended_actions.map((action, idx) => (
                            <div key={idx} style={{
                              background: '#0d1e28', borderRadius: 8, padding: '10px 14px',
                              border: '1px solid #2a3a44', display: 'flex', alignItems: 'flex-start', gap: 10,
                            }}>
                              <span style={{
                                fontSize: 11, padding: '2px 8px', borderRadius: 8, flexShrink: 0,
                                background: action.priority === 'high' ? '#A32D2D22' : '#185FA522',
                                color: action.priority === 'high' ? '#A32D2D' : '#185FA5',
                                fontWeight: 600,
                              }}>
                                {action.priority === 'high' ? '高优先' : action.priority}
                              </span>
                              <div>
                                <div style={{ color: '#fff', fontSize: 13, fontWeight: 600 }}>{action.action}</div>
                                <div style={{ color: '#888', fontSize: 12, marginTop: 2 }}>{action.reason}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 具体补货建议列表 */}
                    {aiPlan && aiPlan.restock_alerts && aiPlan.restock_alerts.length > 0 ? (
                      <div>
                        <div style={{ color: '#888', fontSize: 12, marginBottom: 10, fontWeight: 600 }}>
                          补货建议清单（{aiPlan.restock_alerts.length} 项）
                        </div>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ background: '#0d1e28' }}>
                              {['食材名', '建议采购量', '预估金额', '紧急程度', '说明'].map((h) => (
                                <th key={h} style={{
                                  padding: '8px 14px', textAlign: 'left',
                                  color: '#888', fontSize: 12, fontWeight: 500,
                                }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {aiPlan.restock_alerts.map((alert, idx) => {
                              const uc = urgencyConfig(alert.urgency);
                              return (
                                <tr key={idx} style={{ borderBottom: '1px solid #2a3a4440' }}>
                                  <td style={{ padding: '10px 14px', color: '#fff', fontWeight: 600, fontSize: 13 }}>
                                    {alert.name}
                                  </td>
                                  <td style={{ padding: '10px 14px', color: '#ccc', fontSize: 13 }}>
                                    {alert.suggested_qty} {alert.unit || ''}
                                  </td>
                                  <td style={{ padding: '10px 14px', color: '#ccc', fontSize: 13 }}>
                                    {alert.estimated_cost_fen ? fenToYuan(alert.estimated_cost_fen) : '—'}
                                  </td>
                                  <td style={{ padding: '10px 14px' }}>
                                    <span style={{
                                      fontSize: 12, padding: '2px 10px', borderRadius: 10,
                                      background: `${uc.color}22`, color: uc.color, fontWeight: 600,
                                    }}>
                                      {uc.label}
                                    </span>
                                  </td>
                                  <td style={{ padding: '10px 14px', color: '#888', fontSize: 12 }}>
                                    {alert.reason || '—'}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      !aiLoading && (
                        <div style={{ textAlign: 'center', padding: '24px 0', color: '#888', fontSize: 13 }}>
                          {aiPlan ? '当前库存状态良好，暂无需紧急补货的食材。' : 'AI 分析数据加载中...'}
                        </div>
                      )
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* ── CSS 动画 ── */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 0.8; transform: scale(1); }
          50%       { opacity: 1;   transform: scale(1.05); }
        }
      `}</style>
    </div>
  );
}
