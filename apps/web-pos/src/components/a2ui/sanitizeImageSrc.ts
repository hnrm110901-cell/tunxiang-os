/**
 * sanitizeImageSrc — A2UI image src 白名单（防 SSRF / DNS rebinding）。
 *
 * LLM 生成的 A2UI 卡片可能携带任意 src，浏览器加载会暴露内网拓扑、cookie 或
 * 触发 DNS rebinding。本函数仅放行以下三类：
 *   1. data:image/*     — 内联 base64，无网络请求
 *   2. 相对 URL          — 同源资产
 *   3. allowlist 内 host — 由 VITE_A2UI_IMG_HOSTS env 注入（逗号分隔）
 *
 * 其他一律返回空串，调用方按"无图片"处理。
 *
 * P1 review smell #6（来源：#293 code review）。
 */
export function sanitizeImageSrc(
  raw: unknown,
  opts?: { allowedHosts?: string[]; sameOrigin?: string },
): string {
  const src = String(raw ?? '').trim();
  if (!src) return '';

  if (src.startsWith('data:image/')) return src;

  // 含 protocol scheme（http:、javascript:、file: 等）
  const hasScheme = /^[a-z][a-z0-9+\-.]*:/i.test(src);
  if (!hasScheme) return src; // 相对 URL / 同源

  let parsed: URL;
  try {
    parsed = new URL(src);
  } catch {
    return '';
  }

  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return '';

  const sameOrigin =
    opts?.sameOrigin ??
    (typeof window !== 'undefined' ? window.location.origin : '');
  if (sameOrigin && parsed.origin === sameOrigin) return src;

  const envHosts = readEnvAllowlist();
  const allowed = opts?.allowedHosts ?? envHosts;
  if (allowed.includes(parsed.hostname)) return src;

  return '';
}

function readEnvAllowlist(): string[] {
  const raw =
    typeof import.meta !== 'undefined' &&
    typeof (import.meta as { env?: Record<string, unknown> }).env === 'object'
      ? String(
          (import.meta as { env: Record<string, unknown> }).env
            .VITE_A2UI_IMG_HOSTS ?? '',
        )
      : '';
  return raw
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean);
}
