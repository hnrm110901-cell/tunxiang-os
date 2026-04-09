/**
 * 模板选择器 — 根据门店业态自动路由到对应点餐模板
 *
 * 业态-模板映射：
 *   hotpot   → HotpotTemplate（先选锅底，再选菜品）
 *   quick    → QuickServiceTemplate（图片网格，一键下单）
 *   tea      → TeaTemplate（规格+加料+甜度+温度）
 *   default  → 原有 MenuBrowse（通用模板）
 *
 * 门店业态从 storeConfig.templateType 读取（扫码时由后端返回）
 */
import { lazy, Suspense } from 'react';
import { useOrderStore } from '@/store/useOrderStore';

const HotpotTemplate = lazy(() => import('./HotpotTemplate'));
const QuickServiceTemplate = lazy(() => import('./QuickServiceTemplate'));
const TeaTemplate = lazy(() => import('./TeaTemplate'));
const MenuBrowse = lazy(() => import('@/pages/MenuBrowse'));

export type TemplateType = 'hotpot' | 'quick' | 'tea' | 'default';

const TEMPLATE_MAP: Record<TemplateType, React.LazyExoticComponent<() => JSX.Element>> = {
  hotpot: HotpotTemplate,
  quick: QuickServiceTemplate,
  tea: TeaTemplate,
  default: MenuBrowse,
};

/** 加载占位 */
function TemplateFallback() {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100vh', background: 'var(--tx-bg-primary, #fff)',
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            width: 32, height: 32, border: '3px solid var(--tx-brand, #FF6B35)',
            borderTopColor: 'transparent', borderRadius: '50%',
            animation: 'spin 0.8s linear infinite', margin: '0 auto 12px',
          }}
        />
        <div style={{ color: 'var(--tx-text-tertiary, #B4B2A9)', fontSize: 14 }}>
          加载中...
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    </div>
  );
}

/**
 * TemplateRouter — 在 /menu 路由下使用，自动选择模板
 *
 * 使用方式：
 *   <Route path="/menu" element={<TemplateRouter />} />
 *
 * 门店业态通过 useOrderStore 的 templateType 字段获取
 * 若未设置则 fallback 到默认通用模板
 */
export default function TemplateRouter() {
  const templateType = useOrderStore((s) => (s as any).templateType as TemplateType | undefined) ?? 'default';
  const Component = TEMPLATE_MAP[templateType] ?? TEMPLATE_MAP.default;

  return (
    <Suspense fallback={<TemplateFallback />}>
      <Component />
    </Suspense>
  );
}
