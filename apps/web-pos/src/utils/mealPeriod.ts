/**
 * 营业市别配置 — 根据当前时间判断所处营业时段
 *
 * 早市 06:00-10:00 | 午市 10:00-14:00 | 下午茶 14:00-17:00
 * 晚市 17:00-21:00 | 夜宵 21:00-06:00
 */

export function getCurrentMealPeriod(): string {
  const hour = new Date().getHours();
  if (hour >= 6 && hour < 10) return 'breakfast';   // 早市
  if (hour >= 10 && hour < 14) return 'lunch';      // 午市
  if (hour >= 14 && hour < 17) return 'tea';         // 下午茶
  if (hour >= 17 && hour < 21) return 'dinner';      // 晚市
  return 'late_night';                                // 夜宵
}

export const MEAL_PERIOD_LABELS: Record<string, string> = {
  breakfast: '早市',
  lunch: '午市',
  tea: '下午茶',
  dinner: '晚市',
  late_night: '夜宵',
};

export const MEAL_PERIOD_COLORS: Record<string, string> = {
  breakfast: '#faad14',
  lunch: '#FF6B35',
  tea: '#13c2c2',
  dinner: '#1890ff',
  late_night: '#722ed1',
};
