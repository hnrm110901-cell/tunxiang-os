/**
 * 今日特供推荐 — Smart Specials
 * 将临期食材自动转化为有利润的特供菜，推送到 POS 屏幕和小程序
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetch } from '../../../api';

// ─── 类型定义 ───

interface SpecialDish {
  dish_id: string;
  dish_name: string;
  original_price_fen: number;
  special_price_fen: number;
  discount_rate: number;
  reason: string;
  ingredient_name: string;
  expiry_days: number | null;
  sales_script: string;
  banner_text: string;
  pushed: boolean;
}

interface AlternativeItem {
  dish_id: string;
  dish_name: string;
  category: string;
  price_fen: number;
}

interface SpecialsData {
  store_id: string;
  date: string;
  total_specials: number;
  pushed_count?: number;
  generated_at: string;
  pushed_at?: string | null;
  specials: SpecialDish[];
  alternatives: AlternativeItem[];
}

// ─── 常量 ───

const STORES = [
  { id: 'store-001', name: '尝在一起·芙蓉路店' },
  { id: 'store-002', name: '尝在一起·五一广场店' },
  { id: 'store-003', name: '最黔线·解放西路店' },
];

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function getDiscountLabel(rate: number): string {
  const pct = Math.round((1 - rate) * 10);
  return `${10 - pct}折`;
}

function getReasonColor(reason: string): { color: string; bg: string } {
  if (reason === '临期食材') return { color: '#FF4D4D', bg: '#FF4D4D22' };
  if (reason === '高库存清货') return { color: '#BA7517', bg: '#BA751722' };
  return { color: '#185FA5', bg: '#185FA522' };
}

// ─── 子组件：特供菜卡片 ───

interface SpecialCardProps {
  dish: SpecialDish;
  selected: boolean;
  onToggle: (id: string) => void;
  expanded: boolean;
  onExpandToggle: (id: string) => void;
}

function SpecialCard({ dish, selected, onToggle, expanded, onExpandToggle }: SpecialCardProps) {
  const reasonStyle = getReasonColor(dish.reason);
  const discountPct = Math.round((1 - dish.discount_rate) * 100);

  return (
    <div style={{
      background: selected ? '#1f3040' : '#1a2a33',
      borderRadius: 10,
      border: `1px solid ${selected ? '#FF6B35' : '#2a3a44'}`,
      padding: 16,
      transition: 'border-color 0.2s, background 0.2s',
    }}>
      {/* 顶行：复选框 + 菜品名 + 食材标签 */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggle(dish.dish_id)}
          style={{ width: 16, height: 16, marginTop: 3, accentColor: '#FF6B35', cursor: 'pointer', flexShrink: 0 }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ color: '#fff', fontWeight: 700, fontSize: 16 }}>{dish.dish_name}</span>
            {dish.expiry_days != null && (
              <span style={{
                padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                background: reasonStyle.bg, color: reasonStyle.color,
              }}>
                ⏰ 剩余{dish.expiry_days}天
              </span>
            )}
            <span style={{
              padding: '2px 8px', borderRadius: 10, fontSize: 11,
              background: reasonStyle.bg, color: reasonStyle.color,
            }}>
              {dish.reason}
            </span>
            {dish.pushed && (
              <span style={{
                padding: '2px 8px', borderRadius: 10, fontSize: 11,
                background: '#0F6E5622', color: '#0F6E56',
              }}>
                ✓ 已推送
              </span>
            )}
          </div>
          <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>
            食材：{dish.ingredient_name}
          </div>
        </div>

        {/* 折扣徽章 */}
        <div style={{
          background: '#FF6B35', color: '#fff', borderRadius: 8,
          padding: '4px 10px', fontSize: 13, fontWeight: 700, flexShrink: 0,
        }}>
          {getDiscountLabel(dish.discount_rate)}
        </div>
      </div>

      {/* 价格行 */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, margin: '12px 0 0 28px' }}>
        <span style={{ color: '#888', fontSize: 13, textDecoration: 'line-through' }}>
          ¥{fenToYuan(dish.original_price_fen)}
        </span>
        <span style={{ color: '#FF6B35', fontSize: 24, fontWeight: 800 }}>
          ¥{fenToYuan(dish.special_price_fen)}
        </span>
        <span style={{ color: '#888', fontSize: 12 }}>省¥{fenToYuan(dish.original_price_fen - dish.special_price_fen)}</span>
      </div>

      {/* 推销话术（可展开） */}
      {dish.sales_script && (
        <div style={{ marginTop: 10, marginLeft: 28 }}>
          <button
            onClick={() => onExpandToggle(dish.dish_id)}
            style={{
              background: 'none', border: 'none', color: '#888', fontSize: 12,
              cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            <span style={{ transition: 'transform 0.2s', display: 'inline-block', transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
            服务员话术
          </button>
          {expanded && (
            <div style={{
              marginTop: 6, padding: '8px 12px', background: '#0d1e28',
              borderRadius: 6, color: '#aaa', fontSize: 12, lineHeight: 1.6,
              borderLeft: '3px solid #FF6B3544',
            }}>
              {dish.sales_script}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───

export function SmartSpecialsPage() {
  const [storeId, setStoreId] = useState(STORES[0].id);
  const [specials, setSpecials] = useState<SpecialsData | null>(null);
  const [generating, setGenerating] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expandedScripts, setExpandedScripts] = useState<Set<string>>(new Set());
  const [pushSuccess, setPushSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载今日已有方案
  const loadToday = useCallback(async () => {
    try {
      const data = await txFetch<SpecialsData | null>(`/api/v1/specials/today?store_id=${encodeURIComponent(storeId)}`);
      if (data) {
        setSpecials(data);
        // 恢复已推送状态
        setSelected(new Set(data.specials.filter(s => s.pushed).map(s => s.dish_id)));
      } else {
        setSpecials(null);
        setSelected(new Set());
      }
    } catch {
      /* 无今日方案，静默处理 */
    }
  }, [storeId]);

  useEffect(() => {
    loadToday();
    setPushSuccess(false);
    setError(null);
  }, [loadToday]);

  // 生成特供方案
  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    setPushSuccess(false);
    try {
      const data = await txFetch<SpecialsData>(`/api/v1/specials/generate?store_id=${encodeURIComponent(storeId)}`, {
        method: 'POST',
      });
      setSpecials(data);
      setSelected(new Set());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '生成失败，请重试');
    } finally {
      setGenerating(false);
    }
  };

  // 推送选中菜品
  const handlePush = async () => {
    if (selected.size === 0) return;
    setPushing(true);
    setError(null);
    try {
      await txFetch('/api/v1/specials/push', {
        method: 'POST',
        body: JSON.stringify({ store_id: storeId, dish_ids: Array.from(selected) }),
      });
      setPushSuccess(true);
      await loadToday();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '推送失败，请重试');
    } finally {
      setPushing(false);
    }
  };

  const toggleSelect = (dishId: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(dishId)) next.delete(dishId);
      else next.add(dishId);
      return next;
    });
    setPushSuccess(false);
  };

  const toggleScript = (dishId: string) => {
    setExpandedScripts(prev => {
      const next = new Set(prev);
      if (next.has(dishId)) next.delete(dishId);
      else next.add(dishId);
      return next;
    });
  };

  const pushedDishes = specials?.specials.filter(s => s.pushed) ?? [];
  const unpushedDishes = specials?.specials.filter(s => !s.pushed) ?? [];

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>🍽️ 今日特供推荐</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            AI 分析临期食材，自动生成有利润的特供方案
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <select
            value={storeId}
            onChange={e => setStoreId(e.target.value)}
            style={{
              padding: '7px 12px', borderRadius: 6, border: '1px solid #2a3a44',
              background: '#1a2a33', color: '#fff', fontSize: 13, cursor: 'pointer', outline: 'none',
            }}
          >
            {STORES.map(s => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              padding: '7px 18px', borderRadius: 6, border: 'none',
              background: generating ? '#2a3a44' : '#FF6B35',
              color: generating ? '#888' : '#fff',
              fontSize: 14, fontWeight: 600, cursor: generating ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', gap: 6,
              transition: 'background 0.2s',
            }}
          >
            {generating ? (
              <>
                <span style={{
                  display: 'inline-block', width: 14, height: 14,
                  border: '2px solid #888', borderTopColor: '#fff',
                  borderRadius: '50%', animation: 'tx-spin 0.7s linear infinite',
                }} />
                生成中...
              </>
            ) : '✨ AI生成特供方案'}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          background: '#A32D2D22', border: '1px solid #A32D2D44', borderRadius: 8,
          padding: '10px 16px', marginBottom: 16, color: '#FF4D4D', fontSize: 13,
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* 主体：左侧卡片 + 右侧操作面板 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 20, alignItems: 'start' }}>

        {/* 左侧：特供方案卡片 */}
        <div>
          {!specials && !generating && (
            <div style={{
              background: '#1a2a33', borderRadius: 12, border: '1px dashed #2a3a44',
              padding: '60px 24px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>🍽️</div>
              <div style={{ color: '#888', fontSize: 15 }}>点击右上角「✨ AI生成特供方案」开始分析</div>
              <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>
                系统将扫描临期食材、高库存食材，约3-5秒出方案
              </div>
            </div>
          )}

          {generating && (
            <div style={{
              background: '#1a2a33', borderRadius: 12, padding: '60px 24px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 36, marginBottom: 16, animation: 'tx-spin 1.5s linear infinite', display: 'inline-block' }}>✨</div>
              <div style={{ color: '#ccc', fontSize: 15 }}>AI 正在分析食材库存与临期数据...</div>
              <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>通常需要3-5秒</div>
            </div>
          )}

          {specials && !generating && (
            <>
              {/* 未推送的特供菜 */}
              {unpushedDishes.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ color: '#888', fontSize: 12, marginBottom: 10, letterSpacing: '0.05em' }}>
                    待推送特供 · {unpushedDishes.length} 道菜
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {unpushedDishes.map(dish => (
                      <SpecialCard
                        key={dish.dish_id}
                        dish={dish}
                        selected={selected.has(dish.dish_id)}
                        onToggle={toggleSelect}
                        expanded={expandedScripts.has(dish.dish_id)}
                        onExpandToggle={toggleScript}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* 无特供菜时提示 */}
              {specials.specials.length === 0 && (
                <div style={{
                  background: '#1a2a33', borderRadius: 12, border: '1px solid #2a3a44',
                  padding: 24, textAlign: 'center', color: '#888',
                }}>
                  当前无临期食材或高库存食材，暂无特供推荐
                </div>
              )}

              {/* 替代菜品建议 */}
              {specials.alternatives.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ color: '#888', fontSize: 12, marginBottom: 10, letterSpacing: '0.05em' }}>
                    缺货菜品替代建议 · {specials.alternatives.length} 条
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {specials.alternatives.map((alt, idx) => (
                      <div key={alt.dish_id || idx} style={{
                        background: '#152028', borderRadius: 8, border: '1px solid #2a3a44',
                        padding: '10px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      }}>
                        <div>
                          <span style={{ color: '#ccc', fontSize: 14, fontWeight: 600 }}>{alt.dish_name}</span>
                          {alt.category && (
                            <span style={{ color: '#666', fontSize: 12, marginLeft: 8 }}>{alt.category}</span>
                          )}
                        </div>
                        {alt.price_fen > 0 && (
                          <span style={{ color: '#888', fontSize: 13 }}>¥{fenToYuan(alt.price_fen)}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 今日已推送记录 */}
              {pushedDishes.length > 0 && (
                <div style={{ marginTop: 24 }}>
                  <div style={{ color: '#888', fontSize: 12, marginBottom: 10, letterSpacing: '0.05em' }}>
                    今日已推送 · {pushedDishes.length} 道菜
                    {specials.pushed_at && (
                      <span style={{ marginLeft: 8 }}>
                        · {new Date(specials.pushed_at).toLocaleTimeString('zh-CN')}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {pushedDishes.map(dish => (
                      <div key={dish.dish_id} style={{
                        background: '#0F6E5611', borderRadius: 8,
                        border: '1px solid #0F6E5633', padding: '10px 14px',
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ color: '#0F6E56', fontSize: 16 }}>✓</span>
                          <div>
                            <span style={{ color: '#ccc', fontSize: 14, fontWeight: 600 }}>{dish.dish_name}</span>
                            <span style={{ color: '#666', fontSize: 12, marginLeft: 8 }}>{dish.ingredient_name}</span>
                          </div>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <span style={{ color: '#FF6B35', fontWeight: 700 }}>¥{fenToYuan(dish.special_price_fen)}</span>
                          <span style={{ color: '#666', fontSize: 12, marginLeft: 6, textDecoration: 'line-through' }}>
                            ¥{fenToYuan(dish.original_price_fen)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* 右侧操作面板 */}
        <div style={{ position: 'sticky', top: 24 }}>
          <div style={{ background: '#1a2a33', borderRadius: 12, padding: 20, border: '1px solid #2a3a44' }}>
            <div style={{ color: '#888', fontSize: 12, marginBottom: 16, letterSpacing: '0.05em' }}>
              操作面板
            </div>

            {/* 已选计数 */}
            <div style={{
              background: '#0d1e28', borderRadius: 8, padding: '12px 16px', marginBottom: 16,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span style={{ color: '#888', fontSize: 14 }}>已选菜品</span>
              <span style={{ color: selected.size > 0 ? '#FF6B35' : '#888', fontSize: 20, fontWeight: 700 }}>
                {selected.size} 道
              </span>
            </div>

            {/* 推送按钮 */}
            <button
              onClick={handlePush}
              disabled={selected.size === 0 || pushing || pushSuccess}
              style={{
                width: '100%', padding: '12px 0', borderRadius: 8, border: 'none',
                background: pushSuccess
                  ? '#0F6E56'
                  : selected.size > 0 && !pushing
                  ? '#FF6B35'
                  : '#2a3a44',
                color: selected.size > 0 || pushSuccess ? '#fff' : '#666',
                fontSize: 15, fontWeight: 700, cursor: selected.size > 0 && !pushing && !pushSuccess ? 'pointer' : 'not-allowed',
                transition: 'background 0.3s',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              }}
            >
              {pushing ? (
                <>
                  <span style={{
                    display: 'inline-block', width: 14, height: 14,
                    border: '2px solid rgba(255,255,255,0.4)', borderTopColor: '#fff',
                    borderRadius: '50%', animation: 'tx-spin 0.7s linear infinite',
                  }} />
                  推送中...
                </>
              ) : pushSuccess ? (
                '✅ 推送成功！'
              ) : (
                '📢 一键推送到POS+小程序'
              )}
            </button>

            {/* 推送成功提示 */}
            {pushSuccess && (
              <div style={{
                marginTop: 12, padding: '10px 14px', borderRadius: 8,
                background: '#0F6E5622', border: '1px solid #0F6E5644',
                color: '#0F6E56', fontSize: 13, textAlign: 'center',
              }}>
                特供方案已推送至 POS 屏幕和小程序推荐位
              </div>
            )}

            {/* 方案摘要 */}
            {specials && (
              <div style={{ marginTop: 20, borderTop: '1px solid #2a3a44', paddingTop: 16 }}>
                <div style={{ color: '#888', fontSize: 12, marginBottom: 10 }}>今日方案摘要</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                    <span style={{ color: '#888' }}>特供总数</span>
                    <span style={{ color: '#fff', fontWeight: 600 }}>{specials.total_specials} 道</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                    <span style={{ color: '#888' }}>已推送</span>
                    <span style={{ color: '#0F6E56', fontWeight: 600 }}>{specials.pushed_count ?? pushedDishes.length} 道</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                    <span style={{ color: '#888' }}>生成时间</span>
                    <span style={{ color: '#888', fontSize: 12 }}>
                      {new Date(specials.generated_at).toLocaleTimeString('zh-CN')}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* 替代建议计数 */}
            {specials && specials.alternatives.length > 0 && (
              <div style={{
                marginTop: 16, padding: '10px 14px', borderRadius: 8,
                background: '#185FA522', border: '1px solid #185FA544',
                color: '#185FA5', fontSize: 13,
              }}>
                💡 {specials.alternatives.length} 条缺货菜品替代建议，见下方列表
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 旋转动画样式 */}
      <style>{`
        @keyframes tx-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
