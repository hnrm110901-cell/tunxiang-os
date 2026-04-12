/**
 * 吧台盘点入口页 — Bar Inventory Entry Page
 * 终端：Store-POS（安卓 POS / iPad）
 * 功能: 6 个功能卡片入口（盘点品项设置/领用单/调拨单/盘点单/库存状况/盘点报表）
 * 权限: 仅仓管/店长可操作
 * 规范: TXTouch 触控风格，大按钮大字体
 */
import { useNavigate } from 'react-router-dom';

// ─── 卡片数据定义 ─────────────────────────────────────────────────────────────

interface EntryCard {
  key: string;
  title: string;
  desc: string;
  icon: string;
  route: string;
  color: string;
}

const ENTRY_CARDS: EntryCard[] = [
  {
    key: 'item-setting',
    title: '盘点品项设置',
    desc: '配置参与盘点的原料品项清单',
    icon: '📋',
    route: '/bar-inventory/item-setting',
    color: '#FF6B35',
  },
  {
    key: 'requisition',
    title: '领用单',
    desc: '吧台日常原料领用记录',
    icon: '📦',
    route: '/bar-inventory/requisition',
    color: '#3498DB',
  },
  {
    key: 'transfer',
    title: '调拨单',
    desc: '门店间原料调拨申请与确认',
    icon: '🔄',
    route: '/bar-inventory/transfer',
    color: '#2ECC71',
  },
  {
    key: 'stocktake',
    title: '盘点单',
    desc: '创建盘点单、录入实际库存',
    icon: '✅',
    route: '/bar-inventory/stocktake',
    color: '#E74C3C',
  },
  {
    key: 'stock-status',
    title: '库存状况',
    desc: '实时查看吧台各品项库存',
    icon: '📊',
    route: '/bar-inventory/stock-status',
    color: '#9B59B6',
  },
  {
    key: 'report',
    title: '盘点报表',
    desc: '盈亏汇总、差异分析报表',
    icon: '📈',
    route: '/bar-inventory/report',
    color: '#F39C12',
  },
];

// ─── 权限角色 ─────────────────────────────────────────────────────────────────

// ─── 占位子页面 ─────────────────────────────────────────────────────────────

export function BarInventoryPlaceholder({ title }: { title: string }) {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-[#F8F7F5] font-sans text-[#2C2C2A]">
      <header className="flex items-center justify-between bg-[#1E2A3A] px-5 py-4">
        <button
          className="text-base font-medium text-white"
          onClick={() => navigate('/bar-inventory')}
        >
          ← 返回
        </button>
        <h1 className="m-0 text-xl font-bold text-white">{title}</h1>
        <div className="w-12" />
      </header>
      <div className="flex flex-col items-center justify-center px-4 pt-32">
        <div className="text-5xl">🚧</div>
        <p className="mt-4 text-lg text-[#8C8B87]">"{title}" 功能开发中…</p>
      </div>
    </div>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function BarInventoryPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-[#F8F7F5] font-sans text-[#2C2C2A]">
      {/* ── 顶栏 ── */}
      <header className="flex items-center justify-between bg-[#1E2A3A] px-5 py-4">
        <button
          className="text-base font-medium text-white"
          onClick={() => navigate(-1)}
        >
          ← 返回
        </button>
        <h1 className="m-0 text-xl font-bold text-white">吧台盘点</h1>
        <div className="w-12" />
      </header>

      {/* ── 权限提示 ── */}
      <div className="mx-4 mt-3 flex items-center gap-2 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-700">
        <span>⚠️</span>
        <span>仅仓管或店长角色可执行盘点操作</span>
      </div>

      {/* ── 功能卡片网格 ── */}
      <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-3">
        {ENTRY_CARDS.map((card) => (
          <button
            key={card.key}
            className="flex flex-col items-center rounded-xl bg-white p-5 shadow-sm
                       transition-transform active:scale-95"
            style={{ WebkitTapHighlightColor: 'transparent' }}
            onClick={() => navigate(card.route)}
          >
            {/* 图标圆圈 */}
            <div
              className="mb-3 flex h-14 w-14 items-center justify-center rounded-full text-2xl"
              style={{ background: `${card.color}18` }}
            >
              {card.icon}
            </div>
            {/* 名称 */}
            <span className="text-lg font-bold leading-tight">{card.title}</span>
            {/* 说明 */}
            <span className="mt-1 text-center text-xs leading-snug text-[#8C8B87]">
              {card.desc}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
