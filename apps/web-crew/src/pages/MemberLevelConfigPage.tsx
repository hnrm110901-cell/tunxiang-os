/**
 * 会员等级配置页 — 管理员配置等级权益与积分规则
 * URL: /member-level-config
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchLevelConfigs,
  updateLevelConfig,
  fetchPointsRules,
  createPointsRule,
  getLevelColor,
  type LevelConfig,
  type LevelConfigUpdate,
  type PointsRule,
} from '../api/memberLevelApi';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  gold: '#facc15',
};

const TENANT_ID = (import.meta.env.VITE_TENANT_ID as string) || 'demo-tenant';

/* ---------- 等级卡片颜色 ---------- */
function levelBorderColor(code: string): string {
  if (code === 'gold') return C.gold;
  if (code === 'silver') return '#c0c0c0';
  if (code === 'diamond') return '#ffffff';
  return C.muted;
}

function levelBgGradient(code: string): string {
  if (code === 'gold') return 'linear-gradient(135deg, #facc1514 0%, #112228 100%)';
  if (code === 'silver') return 'linear-gradient(135deg, #c0c0c014 0%, #112228 100%)';
  if (code === 'diamond') return 'linear-gradient(135deg, #0B1A20 0%, #1a2a33 100%)';
  return 'none';
}

function discountLabel(rate: number): string {
  if (rate >= 1.0) return '无折扣';
  return `${(rate * 10).toFixed(1).replace(/\.0$/, '')}折`;
}

function earnTypeName(t: string): string {
  const map: Record<string, string> = {
    consumption: '消费积分',
    birthday: '生日赠送',
    signup: '注册赠送',
    referral: '推荐好友',
    checkin: '每日签到',
  };
  return map[t] ?? t;
}

/* ---------- 编辑弹层 ---------- */
interface EditSheetProps {
  config: LevelConfig;
  onClose: () => void;
  onSave: (id: string, update: LevelConfigUpdate) => Promise<void>;
}

function EditSheet({ config, onClose, onSave }: EditSheetProps) {
  const [levelName, setLevelName] = useState(config.level_name);
  const [minPoints, setMinPoints] = useState(config.min_points);
  const [minAnnualSpendYuan, setMinAnnualSpendYuan] = useState(
    Math.round(config.min_annual_spend_fen / 100),
  );
  const [discountRate, setDiscountRate] = useState(config.discount_rate);
  const [birthdayMultiplier, setBirthdayMultiplier] = useState(config.birthday_bonus_multiplier);
  const [priorityQueue, setPriorityQueue] = useState(config.priority_queue);
  const [freeDelivery, setFreeDelivery] = useState(config.free_delivery);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await onSave(config.id, {
        level_name: levelName,
        min_points: minPoints,
        min_annual_spend_fen: minAnnualSpendYuan * 100,
        discount_rate: discountRate,
        birthday_bonus_multiplier: birthdayMultiplier,
        priority_queue: priorityQueue,
        free_delivery: freeDelivery,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        zIndex: 100, display: 'flex', alignItems: 'flex-end',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', background: C.card, borderRadius: '16px 16px 0 0',
          padding: '20px 16px 32px', maxHeight: '92vh', overflowY: 'auto',
        }}
      >
        {/* 拖拽把手 */}
        <div style={{
          width: 40, height: 4, borderRadius: 2, background: C.muted,
          margin: '0 auto 16px',
        }} />

        <h2 style={{ fontSize: 20, fontWeight: 700, color: getLevelColor(config.level_code), margin: '0 0 20px' }}>
          编辑 {config.level_name}
        </h2>

        {/* 等级名称 */}
        <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 4 }}>等级名称</label>
        <input
          value={levelName}
          onChange={e => setLevelName(e.target.value)}
          style={{
            width: '100%', padding: 14, fontSize: 18, boxSizing: 'border-box',
            background: C.bg, border: `1px solid ${C.border}`,
            borderRadius: 10, color: C.white, marginBottom: 16,
          }}
        />

        {/* 积分门槛 */}
        <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 4 }}>积分门槛</label>
        <input
          type="number"
          value={minPoints}
          onChange={e => setMinPoints(Number(e.target.value))}
          style={{
            width: '100%', padding: 14, fontSize: 18, boxSizing: 'border-box',
            background: C.bg, border: `1px solid ${C.border}`,
            borderRadius: 10, color: C.white, marginBottom: 16,
          }}
        />

        {/* 年消费门槛 */}
        <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 4 }}>
          年消费门槛（元）
        </label>
        <input
          type="number"
          value={minAnnualSpendYuan}
          onChange={e => setMinAnnualSpendYuan(Number(e.target.value))}
          style={{
            width: '100%', padding: 14, fontSize: 18, boxSizing: 'border-box',
            background: C.bg, border: `1px solid ${C.border}`,
            borderRadius: 10, color: C.white, marginBottom: 16,
          }}
        />

        {/* 折扣率滑块 */}
        <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 4 }}>
          折扣率 — <span style={{ color: C.accent, fontWeight: 700 }}>{discountLabel(discountRate)}</span>
        </label>
        <input
          type="range"
          min={0.5}
          max={1.0}
          step={0.05}
          value={discountRate}
          onChange={e => setDiscountRate(Number(e.target.value))}
          style={{ width: '100%', marginBottom: 4, accentColor: C.accent }}
        />
        <div style={{
          display: 'flex', justifyContent: 'space-between',
          fontSize: 14, color: C.muted, marginBottom: 16,
        }}>
          <span>5折</span>
          <span>不打折</span>
        </div>

        {/* 生日积分倍率 */}
        <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 8 }}>生日积分倍率</label>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          {[1, 1.5, 2, 3].map(v => (
            <button
              key={v}
              onClick={() => setBirthdayMultiplier(v)}
              style={{
                flex: 1, minHeight: 48, borderRadius: 10, border: 'none',
                background: birthdayMultiplier === v ? C.accent : C.bg,
                color: birthdayMultiplier === v ? C.white : C.muted,
                fontSize: 16, fontWeight: 700, cursor: 'pointer',
              }}
            >
              {v}x
            </button>
          ))}
        </div>

        {/* 开关 */}
        {[
          { label: '优先等位', val: priorityQueue, set: setPriorityQueue },
          { label: '免外卖费', val: freeDelivery, set: setFreeDelivery },
        ].map(({ label, val, set }) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '14px 0', borderTop: `1px solid ${C.border}`,
          }}>
            <span style={{ fontSize: 17, color: C.text }}>{label}</span>
            <button
              onClick={() => set(!val)}
              style={{
                width: 52, height: 28, borderRadius: 14, border: 'none',
                background: val ? C.accent : C.muted,
                position: 'relative', cursor: 'pointer', transition: 'background 0.2s',
              }}
            >
              <span style={{
                position: 'absolute', top: 3,
                left: val ? 26 : 3,
                width: 22, height: 22, borderRadius: '50%',
                background: C.white, transition: 'left 0.2s',
              }} />
            </button>
          </div>
        ))}

        {error && (
          <div style={{ fontSize: 16, color: '#ef4444', margin: '10px 0' }}>{error}</div>
        )}

        {/* 保存按钮 */}
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            width: '100%', minHeight: 56, borderRadius: 12, border: 'none',
            background: saving ? C.muted : C.accent,
            color: C.white, fontSize: 18, fontWeight: 700,
            cursor: saving ? 'default' : 'pointer', marginTop: 8,
          }}
        >
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
    </div>
  );
}

/* ---------- 主组件 ---------- */
export function MemberLevelConfigPage() {
  const navigate = useNavigate();

  const [configs, setConfigs] = useState<LevelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [editTarget, setEditTarget] = useState<LevelConfig | null>(null);

  const [rules, setRules] = useState<PointsRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);

  // 加载等级配置
  const loadConfigs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchLevelConfigs(TENANT_ID);
      setConfigs(res.items.sort((a, b) => a.sort_order - b.sort_order));
    } catch {
      // 网络失败时使用占位数据
      setConfigs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // 加载积分规则
  const loadRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const res = await fetchPointsRules();
      setRules(res.items);
    } catch {
      setRules([]);
    } finally {
      setRulesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfigs();
    loadRules();
  }, [loadConfigs, loadRules]);

  const handleSave = async (id: string, update: LevelConfigUpdate) => {
    await updateLevelConfig(id, update);
    await loadConfigs();
  };

  // 快捷初始化积分规则（消费/注册/生日）
  const handleInitDefaultRules = async () => {
    try {
      await createPointsRule({
        rule_name: '消费积分（基础）',
        earn_type: 'consumption',
        points_per_100fen: 1,
        fixed_points: 0,
        multiplier: 1.0,
        is_active: true,
      });
      await createPointsRule({
        rule_name: '注册赠送',
        earn_type: 'signup',
        points_per_100fen: 0,
        fixed_points: 100,
        multiplier: 1.0,
        is_active: true,
      });
      await createPointsRule({
        rule_name: '生日赠送',
        earn_type: 'birthday',
        points_per_100fen: 0,
        fixed_points: 200,
        multiplier: 1.0,
        is_active: true,
      });
      await loadRules();
    } catch {
      // 规则已存在时静默忽略
    }
  };

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      {/* 标题栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 40, minHeight: 40, borderRadius: 10,
            background: C.card, border: `1px solid ${C.border}`,
            color: C.text, fontSize: 18, cursor: 'pointer',
          }}
        >
          ‹
        </button>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: 0 }}>
            会员等级配置
          </h1>
          <p style={{ fontSize: 14, color: C.muted, margin: '2px 0 0' }}>
            配置等级权益与升级门槛
          </p>
        </div>
      </div>

      {/* 等级卡片 */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '0 0 12px' }}>
        等级设置
      </h2>

      {loading && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>加载中...</div>
      )}

      {!loading && configs.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          暂无等级配置，请联系系统管理员初始化
        </div>
      )}

      {configs.map(cfg => {
        const color = getLevelColor(cfg.level_code);
        const borderColor = levelBorderColor(cfg.level_code);
        const bg = levelBgGradient(cfg.level_code);
        const isDiamond = cfg.level_code === 'diamond';
        return (
          <div
            key={cfg.id}
            style={{
              background: isDiamond ? '#0e1820' : C.card,
              backgroundImage: isDiamond ? bg : bg,
              borderRadius: 14,
              border: `2px solid ${borderColor}55`,
              padding: 16,
              marginBottom: 14,
            }}
          >
            {/* 等级标题 */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 22 }}>
                  {cfg.level_code === 'normal' ? '🎫'
                    : cfg.level_code === 'silver' ? '🥈'
                    : cfg.level_code === 'gold' ? '🥇'
                    : '💎'}
                </span>
                <span style={{ fontSize: 18, fontWeight: 700, color }}>
                  {cfg.level_name}
                </span>
                {!cfg.is_active && (
                  <span style={{ fontSize: 13, color: C.muted, marginLeft: 4 }}>(已停用)</span>
                )}
              </div>
              <button
                onClick={() => setEditTarget(cfg)}
                style={{
                  minHeight: 36, padding: '0 16px', borderRadius: 8,
                  background: `${color}22`, border: `1px solid ${color}55`,
                  color, fontSize: 15, fontWeight: 600, cursor: 'pointer',
                }}
              >
                编辑
              </button>
            </div>

            {/* 配置项网格 */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 12px',
            }}>
              <div style={{ background: '#00000025', borderRadius: 8, padding: '8px 12px' }}>
                <div style={{ fontSize: 13, color: C.muted }}>积分门槛</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginTop: 2 }}>
                  {cfg.min_points.toLocaleString()} 分
                </div>
              </div>
              <div style={{ background: '#00000025', borderRadius: 8, padding: '8px 12px' }}>
                <div style={{ fontSize: 13, color: C.muted }}>年消费门槛</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginTop: 2 }}>
                  {cfg.min_annual_spend_fen === 0
                    ? '无'
                    : `¥${(cfg.min_annual_spend_fen / 100).toLocaleString()}`}
                </div>
              </div>
              <div style={{ background: '#00000025', borderRadius: 8, padding: '8px 12px' }}>
                <div style={{ fontSize: 13, color: C.muted }}>折扣率</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.accent, marginTop: 2 }}>
                  {discountLabel(cfg.discount_rate)}
                </div>
              </div>
              <div style={{ background: '#00000025', borderRadius: 8, padding: '8px 12px' }}>
                <div style={{ fontSize: 13, color: C.muted }}>生日积分</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.gold, marginTop: 2 }}>
                  {cfg.birthday_bonus_multiplier}x
                </div>
              </div>
            </div>

            {/* 权益标签 */}
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <span style={{
                fontSize: 14, padding: '4px 10px', borderRadius: 6,
                background: cfg.priority_queue ? `${C.accent}22` : '#00000025',
                color: cfg.priority_queue ? C.accent : C.muted,
                fontWeight: cfg.priority_queue ? 700 : 400,
              }}>
                {cfg.priority_queue ? '✓' : '✗'} 优先等位
              </span>
              <span style={{
                fontSize: 14, padding: '4px 10px', borderRadius: 6,
                background: cfg.free_delivery ? `${C.green}22` : '#00000025',
                color: cfg.free_delivery ? C.green : C.muted,
                fontWeight: cfg.free_delivery ? 700 : 400,
              }}>
                {cfg.free_delivery ? '✓' : '✗'} 免外卖费
              </span>
            </div>
          </div>
        );
      })}

      {/* 积分规则 */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '24px 0 12px' }}>
        积分规则
      </h2>

      {rulesLoading && (
        <div style={{ fontSize: 16, color: C.muted, textAlign: 'center', padding: 20 }}>加载中...</div>
      )}

      {!rulesLoading && rules.length === 0 && (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>暂无积分规则</div>
          <button
            onClick={handleInitDefaultRules}
            style={{
              minHeight: 48, padding: '0 24px', borderRadius: 10,
              background: C.accent, border: 'none',
              color: C.white, fontSize: 16, fontWeight: 700, cursor: 'pointer',
            }}
          >
            初始化默认规则
          </button>
        </div>
      )}

      {rules.map(rule => (
        <div
          key={rule.id}
          style={{
            background: C.card, borderRadius: 12, padding: 14,
            border: `1px solid ${C.border}`, marginBottom: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: 17, fontWeight: 600, color: C.white }}>{rule.rule_name}</div>
              <div style={{ fontSize: 14, color: C.muted, marginTop: 4 }}>
                类型: {earnTypeName(rule.earn_type)}
                {rule.earn_type === 'consumption' && (
                  <span style={{ marginLeft: 8, color: C.text }}>
                    每消费¥1 得 {rule.points_per_100fen} 积分
                  </span>
                )}
                {rule.earn_type !== 'consumption' && rule.fixed_points > 0 && (
                  <span style={{ marginLeft: 8, color: C.text }}>
                    固定 {rule.fixed_points} 积分
                  </span>
                )}
              </div>
              {(rule.valid_from || rule.valid_to) && (
                <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
                  有效期: {rule.valid_from ?? '不限'} 至 {rule.valid_to ?? '不限'}
                </div>
              )}
            </div>
            <span style={{
              fontSize: 14, padding: '4px 10px', borderRadius: 6,
              background: rule.is_active ? `${C.green}22` : `${C.muted}22`,
              color: rule.is_active ? C.green : C.muted,
              fontWeight: 700,
            }}>
              {rule.is_active ? '生效中' : '已停用'}
            </span>
          </div>
          {rule.multiplier !== 1 && (
            <div style={{ fontSize: 13, color: C.gold, marginTop: 6 }}>
              倍率活动: ×{rule.multiplier}
            </div>
          )}
        </div>
      ))}

      {/* 编辑弹层 */}
      {editTarget && (
        <EditSheet
          config={editTarget}
          onClose={() => setEditTarget(null)}
          onSave={handleSave}
        />
      )}
    </div>
  );
}

