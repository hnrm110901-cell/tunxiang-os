/**
 * 屯象OS Admin — 通用格式化工具
 */

/** 将分转换为带¥前缀的元格式，两位小数，千位分隔 */
export const fenToYuan = (fen: number): string =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** 将0-1的小数转换为百分比字符串，一位小数 */
export const pctDisplay = (pct: number): string => `${(pct * 100).toFixed(1)}%`;
