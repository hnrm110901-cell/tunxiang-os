/**
 * DailyPlanPage -- 每日经营计划审批页面
 * 商家端：5个区块折叠面板，逐条审批 AI 建议
 */
import { useState, useMemo } from 'react';

// ---- 类型定义 ----

type PlanStatus = 'pending' | 'approved' | 'executing' | 'completed';
type ItemStatus = 'pending' | 'approved' | 'adjusted' | 'skipped';
type SectionKey = 'dishes' | 'purchase' | 'staffing' | 'marketing' | 'risks';

interface PlanItem {
  id: string;
  status: ItemStatus;
  confidence: number;    // 0~1
  impactYuan: number;    // 预期影响 (正=节省/增收, 负=花费)
  [key: string]: unknown;
}

interface DishItem extends PlanItem {
  name: string;
  action: '主推' | '减推' | '试点';
  reason: string;
}

interface PurchaseItem extends PlanItem {
  ingredient: string;
  quantity: string;
  urgency: 'urgent' | 'normal';
  supplier: string;
}

interface StaffItem extends PlanItem {
  position: string;
  action: '增加' | '减少' | '调换';
  shift: string;
  reason: string;
}

interface MarketingItem extends PlanItem {
  audience: string;
  action: '发券' | '短信' | '推送';
  content: string;
  count: number;
}

interface RiskItem extends PlanItem {
  type: string;
  severity: 'high' | 'medium' | 'low';
  detail: string;
  suggestedAction: string;
}

// ---- 颜色常量 ----
const BG_0 = '#0B1A20';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- Mock 数据 ----

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const MOCK_DISHES: DishItem[] = [
  { id: 'dish-1', name: '剁椒鱼头', action: '主推', reason: '近7天销量上升23%, 毛利率62%, 库存充足', confidence: 0.92, impactYuan: 1200, status: 'pending' },
  { id: 'dish-2', name: '外婆鸡', action: '减推', reason: '鸡肉库存偏低, 明日到货前需控制出品量', confidence: 0.85, impactYuan: 350, status: 'pending' },
  { id: 'dish-3', name: '酸菜鱼', action: '试点', reason: '新菜试点第3天, 好评率87%, 建议继续观察', confidence: 0.78, impactYuan: 500, status: 'pending' },
];

const MOCK_PURCHASE: PurchaseItem[] = [
  { id: 'pur-1', ingredient: '基围虾', quantity: '15kg', urgency: 'urgent', supplier: '湘江水产', confidence: 0.95, impactYuan: -480, status: 'pending' },
  { id: 'pur-2', ingredient: '香菜', quantity: '5kg', urgency: 'normal', supplier: '红星农批', confidence: 0.82, impactYuan: -35, status: 'pending' },
];

const MOCK_STAFFING: StaffItem[] = [
  { id: 'staff-1', position: '服务员', action: '增加', shift: '11:00-14:00 午高峰', reason: '预测今日午间客流+18%, 当前排班不足', confidence: 0.88, impactYuan: 600, status: 'pending' },
];

const MOCK_MARKETING: MarketingItem[] = [
  { id: 'mkt-1', audience: '30天未到店老客', action: '发券', content: '满100减20回归券', count: 156, confidence: 0.76, impactYuan: 2400, status: 'pending' },
  { id: 'mkt-2', audience: '周边3km新注册用户', action: '推送', content: '新人首单立减15元', count: 89, confidence: 0.71, impactYuan: 800, status: 'pending' },
];

const MOCK_RISKS: RiskItem[] = [
  { id: 'risk-1', type: '食材效期', severity: 'high', detail: '冷库三文鱼(批次B2403)明日到期, 剩余2.3kg', suggestedAction: '今日午市前用完或转员工餐', confidence: 0.97, impactYuan: 180, status: 'pending' },
  { id: 'risk-2', type: '设备异常', severity: 'medium', detail: '2号出餐口打印机响应延迟>3秒', suggestedAction: '安排维修或切换至1号备用打印机', confidence: 0.89, impactYuan: 0, status: 'pending' },
];

// ---- 组件 ----

const STATUS_MAP: Record<PlanStatus, { label: string; emoji: string; color: string }> = {
  pending:   { label: '待审批', emoji: '\u23F3', color: YELLOW },
  approved:  { label: '已批准', emoji: '\u2705', color: GREEN },
  executing: { label: '执行中', emoji: '\uD83D\uDD04', color: '#1890ff' },
  completed: { label: '已完成', emoji: '\u2713', color: GREEN },
};

function StatusBadge({ status }: { status: PlanStatus }) {
  const s = STATUS_MAP[status];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '4px 12px', borderRadius: 12,
      background: s.color + '22', color: s.color,
      fontSize: 12, fontWeight: 600,
    }}>
      {s.emoji} {s.label}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 85 ? GREEN : pct >= 70 ? YELLOW : RED;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 120 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: BG_2 }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 3, background: color, transition: 'width .3s' }} />
      </div>
      <span style={{ fontSize: 11, color: TEXT_3, minWidth: 32 }}>{pct}%</span>
    </div>
  );
}

function ActionButtons({ status, onApprove, onAdjust, onSkip }: {
  status: ItemStatus;
  onApprove: () => void;
  onAdjust: () => void;
  onSkip: () => void;
}) {
  if (status !== 'pending') {
    const labelMap: Record<ItemStatus, { text: string; color: string }> = {
      approved: { text: '已批准', color: GREEN },
      adjusted: { text: '已调整', color: YELLOW },
      skipped:  { text: '已跳过', color: TEXT_4 },
      pending:  { text: '', color: '' },
    };
    const info = labelMap[status];
    return <span style={{ fontSize: 12, color: info.color, fontWeight: 600 }}>{info.text}</span>;
  }
  const btnBase: React.CSSProperties = {
    padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
    fontSize: 12, fontWeight: 600, transition: 'opacity .15s',
  };
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      <button style={{ ...btnBase, background: GREEN, color: '#fff' }} onClick={onApprove}>批准</button>
      <button style={{ ...btnBase, background: YELLOW + '33', color: YELLOW, border: `1px solid ${YELLOW}55` }} onClick={onAdjust}>调整</button>
      <button style={{ ...btnBase, background: 'transparent', color: TEXT_4, border: `1px solid ${BG_2}` }} onClick={onSkip}>跳过</button>
    </div>
  );
}

function ImpactBadge({ yuan }: { yuan: number }) {
  const isPositive = yuan >= 0;
  return (
    <span style={{
      fontSize: 13, fontWeight: 700,
      color: isPositive ? GREEN : RED,
    }}>
      {isPositive ? '+' : ''}\u00A5{Math.abs(yuan).toLocaleString()}
    </span>
  );
}

// ---- 区块配置 ----

interface SectionConfig {
  key: SectionKey;
  icon: string;
  title: string;
  renderItem: (item: PlanItem, onAction: (id: string, action: ItemStatus) => void) => React.ReactNode;
}

function DishRow({ item, onAction }: { item: DishItem; onAction: (id: string, a: ItemStatus) => void }) {
  const actionColors: Record<string, string> = { '\u4E3B\u63A8': GREEN, '\u51CF\u63A8': YELLOW, '\u8BD5\u70B9': '#1890ff' };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px solid ${BG_2}` }}>
      <span style={{
        padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
        background: (actionColors[item.action] || TEXT_4) + '22',
        color: actionColors[item.action] || TEXT_4,
      }}>{item.action}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{item.name}</div>
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>{item.reason}</div>
      </div>
      <ConfidenceBar value={item.confidence} />
      <ImpactBadge yuan={item.impactYuan} />
      <ActionButtons status={item.status} onApprove={() => onAction(item.id, 'approved')} onAdjust={() => onAction(item.id, 'adjusted')} onSkip={() => onAction(item.id, 'skipped')} />
    </div>
  );
}

function PurchaseRow({ item, onAction }: { item: PurchaseItem; onAction: (id: string, a: ItemStatus) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px solid ${BG_2}` }}>
      <span style={{ fontSize: 16 }}>{item.urgency === 'urgent' ? '\uD83D\uDD34' : '\uD83D\uDFE1'}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{item.ingredient} <span style={{ color: TEXT_3, fontWeight: 400 }}>x {item.quantity}</span></div>
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>供应商: {item.supplier} {item.urgency === 'urgent' ? '| 紧急采购' : ''}</div>
      </div>
      <ConfidenceBar value={item.confidence} />
      <ImpactBadge yuan={item.impactYuan} />
      <ActionButtons status={item.status} onApprove={() => onAction(item.id, 'approved')} onAdjust={() => onAction(item.id, 'adjusted')} onSkip={() => onAction(item.id, 'skipped')} />
    </div>
  );
}

function StaffRow({ item, onAction }: { item: StaffItem; onAction: (id: string, a: ItemStatus) => void }) {
  const actionColors: Record<string, string> = { '\u589E\u52A0': GREEN, '\u51CF\u5C11': RED, '\u8C03\u6362': '#1890ff' };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px solid ${BG_2}` }}>
      <span style={{
        padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
        background: (actionColors[item.action] || TEXT_4) + '22',
        color: actionColors[item.action] || TEXT_4,
      }}>{item.action}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{item.position} <span style={{ color: TEXT_3, fontWeight: 400 }}>| {item.shift}</span></div>
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>{item.reason}</div>
      </div>
      <ConfidenceBar value={item.confidence} />
      <ImpactBadge yuan={item.impactYuan} />
      <ActionButtons status={item.status} onApprove={() => onAction(item.id, 'approved')} onAdjust={() => onAction(item.id, 'adjusted')} onSkip={() => onAction(item.id, 'skipped')} />
    </div>
  );
}

function MarketingRow({ item, onAction }: { item: MarketingItem; onAction: (id: string, a: ItemStatus) => void }) {
  const actionIcons: Record<string, string> = { '\u53D1\u5238': '\uD83C\uDF9F\uFE0F', '\u77ED\u4FE1': '\uD83D\uDCE7', '\u63A8\u9001': '\uD83D\uDCE3' };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px solid ${BG_2}` }}>
      <span style={{ fontSize: 16 }}>{actionIcons[item.action] || '\uD83D\uDCE3'}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{item.action}: {item.content}</div>
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>目标: {item.audience} | {item.count}人</div>
      </div>
      <ConfidenceBar value={item.confidence} />
      <ImpactBadge yuan={item.impactYuan} />
      <ActionButtons status={item.status} onApprove={() => onAction(item.id, 'approved')} onAdjust={() => onAction(item.id, 'adjusted')} onSkip={() => onAction(item.id, 'skipped')} />
    </div>
  );
}

function RiskRow({ item, onAction }: { item: RiskItem; onAction: (id: string, a: ItemStatus) => void }) {
  const sevColors: Record<string, string> = { high: RED, medium: YELLOW, low: '#1890ff' };
  const sevLabels: Record<string, string> = { high: '\u9AD8', medium: '\u4E2D', low: '\u4F4E' };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px solid ${BG_2}` }}>
      <span style={{
        padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
        background: sevColors[item.severity] + '22',
        color: sevColors[item.severity],
      }}>{sevLabels[item.severity]}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>[{item.type}] {item.detail}</div>
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>建议: {item.suggestedAction}</div>
      </div>
      <ConfidenceBar value={item.confidence} />
      <ImpactBadge yuan={item.impactYuan} />
      <ActionButtons status={item.status} onApprove={() => onAction(item.id, 'approved')} onAdjust={() => onAction(item.id, 'adjusted')} onSkip={() => onAction(item.id, 'skipped')} />
    </div>
  );
}

// ---- 折叠面板区块 ----

function PlanSection({ icon, title, items, children, onApproveAll }: {
  icon: string;
  title: string;
  items: PlanItem[];
  children: React.ReactNode;
  onApproveAll: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const pendingCount = items.filter(i => i.status === 'pending').length;
  return (
    <div style={{ background: BG_1, borderRadius: 10, marginBottom: 12, overflow: 'hidden', border: `1px solid ${BG_2}` }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', cursor: 'pointer', userSelect: 'none',
        }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18 }}>{icon}</span>
          <span style={{ fontSize: 15, fontWeight: 700 }}>{title}</span>
          <span style={{
            fontSize: 11, padding: '1px 8px', borderRadius: 10,
            background: BRAND + '22', color: BRAND,
          }}>{items.length} 条</span>
          <span style={{ fontSize: 12, color: collapsed ? TEXT_4 : 'transparent', transition: 'color .2s' }}>
            {collapsed ? '\u25B6' : '\u25BC'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {pendingCount > 0 && (
            <button
              style={{
                padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: GREEN + '22', color: GREEN, fontSize: 12, fontWeight: 600,
              }}
              onClick={(e) => { e.stopPropagation(); onApproveAll(); }}
            >
              全部批准
            </button>
          )}
        </div>
      </div>
      {!collapsed && (
        <div style={{ padding: '0 16px 12px' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function DailyPlanPage() {
  const [date, setDate] = useState(today());
  const [planStatus, setPlanStatus] = useState<PlanStatus>('pending');
  const [dishes, setDishes] = useState<DishItem[]>(MOCK_DISHES);
  const [purchase, setPurchase] = useState<PurchaseItem[]>(MOCK_PURCHASE);
  const [staffing, setStaffing] = useState<StaffItem[]>(MOCK_STAFFING);
  const [marketing, setMarketing] = useState<MarketingItem[]>(MOCK_MARKETING);
  const [risks, setRisks] = useState<RiskItem[]>(MOCK_RISKS);

  // 所有条目聚合
  const allItems = useMemo(
    () => [...dishes, ...purchase, ...staffing, ...marketing, ...risks],
    [dishes, purchase, staffing, marketing, risks],
  );

  const totalCount = allItems.length;
  const pendingCount = allItems.filter(i => i.status === 'pending').length;
  const totalSavingYuan = allItems
    .filter(i => i.status === 'approved' || i.status === 'pending')
    .reduce((s, i) => s + i.impactYuan, 0);

  // 通用 action handler
  function makeAction<T extends PlanItem>(
    setter: React.Dispatch<React.SetStateAction<T[]>>,
  ) {
    return (id: string, action: ItemStatus) => {
      setter(prev => prev.map(item => item.id === id ? { ...item, status: action } : item));
    };
  }

  function makeApproveAll<T extends PlanItem>(
    setter: React.Dispatch<React.SetStateAction<T[]>>,
  ) {
    return () => {
      setter(prev => prev.map(item => item.status === 'pending' ? { ...item, status: 'approved' } : item));
    };
  }

  const approveAllItems = () => {
    makeApproveAll(setDishes)();
    makeApproveAll(setPurchase)();
    makeApproveAll(setStaffing)();
    makeApproveAll(setMarketing)();
    makeApproveAll(setRisks)();
  };

  const handleGenerate = () => {
    // 模拟生成 - 重置所有状态
    setDishes(MOCK_DISHES.map(d => ({ ...d, status: 'pending' as ItemStatus })));
    setPurchase(MOCK_PURCHASE.map(d => ({ ...d, status: 'pending' as ItemStatus })));
    setStaffing(MOCK_STAFFING.map(d => ({ ...d, status: 'pending' as ItemStatus })));
    setMarketing(MOCK_MARKETING.map(d => ({ ...d, status: 'pending' as ItemStatus })));
    setRisks(MOCK_RISKS.map(d => ({ ...d, status: 'pending' as ItemStatus })));
    setPlanStatus('pending');
  };

  const handleComplete = () => {
    setPlanStatus('approved');
  };

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* 顶部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20, flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>每日经营计划</h2>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            style={{
              background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 6,
              color: TEXT_2, padding: '4px 10px', fontSize: 13, outline: 'none',
            }}
          />
          <span style={{ fontSize: 13, color: TEXT_3 }}>尝在一起 \u00B7 芙蓉路店</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <StatusBadge status={planStatus} />
          <button
            onClick={handleGenerate}
            style={{
              padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700,
              transition: 'opacity .15s',
            }}
          >
            生成今日计划
          </button>
        </div>
      </div>

      {/* 5个区块 */}
      <PlanSection
        icon={'\uD83D\uDCCB'}
        title="排菜建议"
        items={dishes}
        onApproveAll={makeApproveAll(setDishes)}
      >
        {dishes.map(item => (
          <DishRow key={item.id} item={item} onAction={makeAction(setDishes)} />
        ))}
      </PlanSection>

      <PlanSection
        icon={'\uD83D\uDCE6'}
        title="紧急采购"
        items={purchase}
        onApproveAll={makeApproveAll(setPurchase)}
      >
        {purchase.map(item => (
          <PurchaseRow key={item.id} item={item} onAction={makeAction(setPurchase)} />
        ))}
      </PlanSection>

      <PlanSection
        icon={'\uD83D\uDC65'}
        title="排班微调"
        items={staffing}
        onApproveAll={makeApproveAll(setStaffing)}
      >
        {staffing.map(item => (
          <StaffRow key={item.id} item={item} onAction={makeAction(setStaffing)} />
        ))}
      </PlanSection>

      <PlanSection
        icon={'\uD83D\uDCE3'}
        title="营销触发"
        items={marketing}
        onApproveAll={makeApproveAll(setMarketing)}
      >
        {marketing.map(item => (
          <MarketingRow key={item.id} item={item} onAction={makeAction(setMarketing)} />
        ))}
      </PlanSection>

      <PlanSection
        icon={'\u26A0\uFE0F'}
        title="风险预警"
        items={risks}
        onApproveAll={makeApproveAll(setRisks)}
      >
        {risks.map(item => (
          <RiskRow key={item.id} item={item} onAction={makeAction(setRisks)} />
        ))}
      </PlanSection>

      {/* 底部汇总 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: '16px 20px', marginTop: 8,
        border: `1px solid ${BG_2}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, fontSize: 14 }}>
          <span>总建议 <strong style={{ color: BRAND }}>{totalCount}</strong> 条</span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span>待处理 <strong style={{ color: YELLOW }}>{pendingCount}</strong> 条</span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span>预期影响 <strong style={{ color: GREEN }}>+\u00A5{totalSavingYuan.toLocaleString()}</strong></span>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={approveAllItems}
            style={{
              padding: '10px 28px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: GREEN, color: '#fff', fontSize: 15, fontWeight: 700,
              boxShadow: `0 4px 16px ${GREEN}44`,
              transition: 'transform .15s, box-shadow .15s',
            }}
          >
            一键全部批准
          </button>
          <button
            onClick={handleComplete}
            disabled={pendingCount > 0}
            style={{
              padding: '10px 28px', borderRadius: 8, border: `1px solid ${BG_2}`, cursor: pendingCount > 0 ? 'not-allowed' : 'pointer',
              background: pendingCount > 0 ? BG_2 : BG_1, color: pendingCount > 0 ? TEXT_4 : TEXT_1,
              fontSize: 15, fontWeight: 700,
              opacity: pendingCount > 0 ? 0.5 : 1,
              transition: 'opacity .15s',
            }}
          >
            逐条审批完成
          </button>
        </div>
      </div>
    </div>
  );
}
