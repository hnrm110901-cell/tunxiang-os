/**
 * useButtonTf — 触控按钮快捷 Hook
 *
 * 一行替代手写 tf.handlers + tf.style，减少样板代码。
 *
 * 用法:
 *   const btn = useButtonTf();
 *   <button {...btn.props} style={{ padding: 10, ...btn.style }}>按钮</button>
 *
 * 等价于:
 *   const tf = useTouchFeedback();
 *   <button {...tf.handlers} style={{ padding: 10, ...tf.style }}>按钮</button>
 */
import { useTouchFeedback } from './useTouchFeedback';

export function useButtonTf() {
  const tf = useTouchFeedback();
  return { props: tf.handlers, style: tf.style };
}
