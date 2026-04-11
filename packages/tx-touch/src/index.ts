/**
 * @tx/touch — TXTouch 共享触控组件库
 *
 * 专为屯象OS门店触控终端设计：POS收银 / KDS后厨 / Crew服务员
 * 所有组件遵循：触控优先 · 最小48px点击区 · 无hover依赖 · CSS变量主题
 *
 * 使用方式：
 *   import { TXButton, TXDishCard, useLongPress } from '@tx/touch';
 *   import '@tx/touch/styles/tokens.css';
 *   import '@tx/touch/styles/reset.css';
 */

// ─── 组件 ───────────────────────────────────────────────────────
export { TXButton } from './components/TXButton/TXButton';
export type { TXButtonProps, TXButtonVariant, TXButtonSize } from './components/TXButton/TXButton';

export { TXCard } from './components/TXCard/TXCard';
export type { TXCardProps } from './components/TXCard/TXCard';

export { TXDishCard } from './components/TXDishCard/TXDishCard';
export type { TXDishCardProps } from './components/TXDishCard/TXDishCard';

export { TXKDSTicket } from './components/TXKDSTicket/TXKDSTicket';
export type { TXKDSTicketProps, TXKDSTicketItem } from './components/TXKDSTicket/TXKDSTicket';

export { TXPaymentPanel } from './components/TXPaymentPanel/TXPaymentPanel';
export type { TXPaymentPanelProps, TXPaymentPanelItem } from './components/TXPaymentPanel/TXPaymentPanel';

export { TXAgentAlert } from './components/TXAgentAlert/TXAgentAlert';
export type { TXAgentAlertProps } from './components/TXAgentAlert/TXAgentAlert';

export { TXNumpad } from './components/TXNumpad/TXNumpad';
export type { TXNumpadProps } from './components/TXNumpad/TXNumpad';

export { TXSelector } from './components/TXSelector/TXSelector';
export type { TXSelectorProps, TXSelectorOption } from './components/TXSelector/TXSelector';

export { TXScrollList } from './components/TXScrollList/TXScrollList';
export type { TXScrollListProps } from './components/TXScrollList/TXScrollList';

// ─── Hooks ──────────────────────────────────────────────────────
export { useLongPress } from './hooks/useLongPress';
export { useSwipe } from './hooks/useSwipe';
export { useHaptic } from './hooks/useHaptic';

// ─── Styles 路径（消费方自行 import）────────────────────────────
// import '@tx/tokens/src/tokens.css';     ← Token（必须，在 tx-touch 之前引入）
// import '@tx/touch/src/styles/reset.css';
// import '@tx/touch/src/styles/animations.css';
