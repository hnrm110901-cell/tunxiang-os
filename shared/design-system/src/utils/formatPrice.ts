/**
 * 统一金额格式化 — 分(fen) → 元(yuan)
 * 所有终端共用，消除各 app 各写一遍的问题
 */
export function formatPrice(fen: number, options?: { symbol?: boolean; decimals?: number }): string {
  const { symbol = true, decimals = 2 } = options ?? {};
  const yuan = (fen / 100).toFixed(decimals);
  return symbol ? `¥${yuan}` : yuan;
}

export function fenToYuan(fen: number): number {
  return fen / 100;
}

export function yuanToFen(yuan: number): number {
  return Math.round(Number((yuan * 100).toFixed(4)));
}
