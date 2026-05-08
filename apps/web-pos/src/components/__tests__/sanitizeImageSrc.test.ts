/**
 * sanitizeImageSrc 单元测试 — A2UI image src 白名单（P1 review smell #6）
 *
 * 覆盖 SSRF / DNS rebinding 攻击向量：
 *   - 内部网段（10.0.0.0/8 / 192.168.x / 127.0.0.1）必须被拒
 *   - 任意外部 host 默认拒，仅 allowlist 放行
 *   - javascript:/file:/chrome-extension: 等危险 protocol 拒
 *   - 同源资产 / data:image / 相对 URL 放行
 */
import { describe, expect, it } from 'vitest';
import { sanitizeImageSrc } from '../a2ui/sanitizeImageSrc';

const SAME_ORIGIN = 'https://admin.tunxiang.cloud';

describe('sanitizeImageSrc — A2UI image 白名单', () => {
  describe('放行', () => {
    it('data:image/png base64 内联图片', () => {
      const data = 'data:image/png;base64,iVBORw0KGgo=';
      expect(sanitizeImageSrc(data)).toBe(data);
    });

    it('相对 URL（绝对路径）— 同源资产', () => {
      expect(sanitizeImageSrc('/static/dish.jpg')).toBe('/static/dish.jpg');
    });

    it('相对 URL（无前缀）', () => {
      expect(sanitizeImageSrc('static/dish.jpg')).toBe('static/dish.jpg');
    });

    it('同 origin 完整 URL', () => {
      const url = `${SAME_ORIGIN}/static/dish.jpg`;
      expect(sanitizeImageSrc(url, { sameOrigin: SAME_ORIGIN })).toBe(url);
    });

    it('allowlist 内的外部 CDN host', () => {
      const cdn = 'https://cdn.tunxiang.cloud/dishes/luyu.jpg';
      const opts = {
        sameOrigin: SAME_ORIGIN,
        allowedHosts: ['cdn.tunxiang.cloud'],
      };
      expect(sanitizeImageSrc(cdn, opts)).toBe(cdn);
    });
  });

  describe('拦截', () => {
    it.each(['', '   ', null, undefined])('空值 %s → 空串', (raw) => {
      expect(sanitizeImageSrc(raw)).toBe('');
    });

    it('javascript: scheme — XSS 入口', () => {
      expect(sanitizeImageSrc('javascript:alert(1)')).toBe('');
    });

    it('file: scheme — 本地文件读取', () => {
      expect(sanitizeImageSrc('file:///etc/passwd')).toBe('');
    });

    it('chrome-extension: scheme', () => {
      expect(
        sanitizeImageSrc('chrome-extension://abcd/foo.png'),
      ).toBe('');
    });

    it('外部 host 不在 allowlist — DNS rebinding 入口', () => {
      const opts = { sameOrigin: SAME_ORIGIN, allowedHosts: [] };
      expect(
        sanitizeImageSrc('https://attacker.example.com/x.png', opts),
      ).toBe('');
    });

    it('内部网段 IP（127.0.0.1）— SSRF 入口', () => {
      const opts = { sameOrigin: SAME_ORIGIN, allowedHosts: [] };
      expect(sanitizeImageSrc('http://127.0.0.1:8000/admin', opts)).toBe('');
    });

    it('非法 URL（malformed）→ 空串', () => {
      expect(sanitizeImageSrc('https://')).toBe('');
    });

    it('data: 但不是 image/* — 防 data:text/html xss', () => {
      expect(sanitizeImageSrc('data:text/html,<script>alert(1)</script>')).toBe(
        '',
      );
    });
  });
});
