/**
 * 触觉反馈 Hook
 * 封装 navigator.vibrate API（仅安卓支持；iOS 静默忽略）
 *
 * 使用示例：
 *   const { tap, success, error } = useHaptic();
 *   tap();     // 轻触确认
 *   success(); // 支付成功
 *   error();   // 操作失败
 */
export function useHaptic() {
  const vibrate = (pattern: number | number[]) => {
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      try {
        navigator.vibrate(pattern);
      } catch {
        // 部分浏览器禁止脚本调用振动，静默忽略
      }
    }
  };

  return {
    /** 轻触确认反馈（10ms），普通按键按压 */
    tap: () => vibrate(10),

    /** 成功操作反馈（短-停-短），支付成功/出餐完成 */
    success: () => vibrate([10, 50, 10]),

    /** 错误/警告反馈（长-停-长），折扣超限/食安违规 */
    error: () => vibrate([50, 30, 50]),
  };
}
