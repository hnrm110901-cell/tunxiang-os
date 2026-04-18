/** 分转元，保留两位小数。如 8800 → "88.00" */
export function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}
