/**
 * MenuBoardControlPage — 数字菜单屏远程控制页
 *
 * POS 端管理人员远程推送公告到数字菜单展示屏。
 *
 * 功能：
 *   - 展示当前生效的公告文本
 *   - 编辑框输入新公告内容
 *   - "立即推送"调用 POST /api/v1/menu/board-announcement
 *   - 调用结果实时反馈（成功 / 失败）
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── Constants ───

const API_BASE: string =
  (window as Record<string, unknown>).__STORE_API_BASE__ as string || '';
const TENANT_ID: string =
  (window as Record<string, unknown>).__TENANT_ID__ as string || '';
const STORE_ID: string =
  (window as Record<string, unknown>).__STORE_ID__ as string || '';

const HEADERS: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
};

const DEFAULT_ANNOUNCEMENT =
  '今日特供：佛跳墙限量10份 · 营业时间 10:00–22:00 · 服务电话 400-888-8888';

// ─── Types ───

type PushStatus = 'idle' | 'pushing' | 'success' | 'error';

// ─── Main ───

export function MenuBoardControlPage() {
  const [currentAnnouncement, setCurrentAnnouncement] = useState('');
  const [draft, setDraft] = useState('');
  const [status, setPushStatus] = useState<PushStatus>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 加载当前公告
  const fetchCurrent = useCallback(async () => {
    if (!API_BASE) {
      setCurrentAnnouncement(DEFAULT_ANNOUNCEMENT);
      setDraft(DEFAULT_ANNOUNCEMENT);
      return;
    }
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/menu/board-config?store_id=${STORE_ID}`,
        { headers: HEADERS }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (body.ok) {
        const ann: string = body.data.announcement ?? '';
        setCurrentAnnouncement(ann);
        setDraft(ann);
      }
    } catch {
      setCurrentAnnouncement(DEFAULT_ANNOUNCEMENT);
      setDraft(DEFAULT_ANNOUNCEMENT);
    }
  }, []);

  useEffect(() => {
    fetchCurrent();
    return () => {
      if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
    };
  }, [fetchCurrent]);

  const handlePush = useCallback(async () => {
    const trimmed = draft.trim();
    if (!trimmed) return;

    setPushStatus('pushing');
    setErrorMsg('');

    try {
      const res = await fetch(`${API_BASE}/api/v1/menu/board-announcement`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({ store_id: STORE_ID, announcement: trimmed }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) {
        throw new Error(body.error?.message ?? `HTTP ${res.status}`);
      }
      setCurrentAnnouncement(trimmed);
      setPushStatus('success');
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '推送失败，请重试');
      setPushStatus('error');
    } finally {
      if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
      feedbackTimerRef.current = setTimeout(() => setPushStatus('idle'), 3000);
    }
  }, [draft]);

  const isDirty = draft.trim() !== currentAnnouncement.trim();
  const isPushing = status === 'pushing';

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#111827',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'flex-start',
        padding: '40px 24px',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        color: '#F0F0F0',
      }}
    >
      {/* 页面标题 */}
      <div
        style={{
          width: '100%',
          maxWidth: 680,
          marginBottom: 32,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginBottom: 8,
          }}
        >
          <div
            style={{
              width: 4,
              height: 28,
              background: '#FF6B35',
              borderRadius: 2,
            }}
          />
          <h1
            style={{
              margin: 0,
              fontSize: 24,
              fontWeight: 800,
              color: '#F0F0F0',
            }}
          >
            数字菜单屏控制
          </h1>
        </div>
        <p style={{ margin: 0, fontSize: 15, color: '#6B7280' }}>
          在此推送的公告将实时更新到门店数字菜单展示屏的滚动栏。
        </p>
      </div>

      {/* 主卡片 */}
      <div
        style={{
          width: '100%',
          maxWidth: 680,
          background: '#1F2937',
          borderRadius: 16,
          padding: '28px 28px 24px',
          border: '1px solid #2D3748',
        }}
      >
        {/* 当前生效公告 */}
        <div style={{ marginBottom: 28 }}>
          <label
            style={{
              display: 'block',
              fontSize: 13,
              fontWeight: 700,
              color: '#9CA3AF',
              letterSpacing: 1,
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            当前生效公告
          </label>
          <div
            style={{
              background: '#111827',
              border: '1px solid #374151',
              borderRadius: 10,
              padding: '14px 16px',
              fontSize: 16,
              color: currentAnnouncement ? '#D1D5DB' : '#4B5563',
              lineHeight: 1.6,
              minHeight: 52,
            }}
          >
            {currentAnnouncement || '暂无公告'}
          </div>
        </div>

        {/* 编辑框 */}
        <div style={{ marginBottom: 24 }}>
          <label
            style={{
              display: 'block',
              fontSize: 13,
              fontWeight: 700,
              color: '#9CA3AF',
              letterSpacing: 1,
              textTransform: 'uppercase',
              marginBottom: 10,
            }}
          >
            新公告内容
          </label>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="输入要推送到菜单屏的公告…"
            rows={4}
            style={{
              width: '100%',
              background: '#111827',
              border: `1px solid ${isDirty ? '#FF6B35' : '#374151'}`,
              borderRadius: 10,
              padding: '14px 16px',
              fontSize: 16,
              color: '#F0F0F0',
              lineHeight: 1.6,
              resize: 'vertical',
              outline: 'none',
              boxSizing: 'border-box',
              transition: 'border-color 0.2s',
              fontFamily: 'inherit',
            }}
          />
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              marginTop: 6,
            }}
          >
            <span style={{ fontSize: 13, color: '#4B5563' }}>
              {draft.length} 字符
            </span>
          </div>
        </div>

        {/* 错误提示 */}
        {status === 'error' && errorMsg && (
          <div
            style={{
              background: 'rgba(163, 45, 45, 0.2)',
              border: '1px solid #A32D2D',
              borderRadius: 8,
              padding: '10px 14px',
              fontSize: 15,
              color: '#FCA5A5',
              marginBottom: 20,
            }}
          >
            {errorMsg}
          </div>
        )}

        {/* 成功提示 */}
        {status === 'success' && (
          <div
            style={{
              background: 'rgba(15, 110, 86, 0.2)',
              border: '1px solid #0F6E56',
              borderRadius: 8,
              padding: '10px 14px',
              fontSize: 15,
              color: '#6EE7B7',
              marginBottom: 20,
            }}
          >
            公告已成功推送到菜单屏。
          </div>
        )}

        {/* 推送按钮 */}
        <button
          onClick={handlePush}
          disabled={isPushing || !draft.trim()}
          style={{
            width: '100%',
            height: 56,
            background:
              isPushing || !draft.trim()
                ? '#374151'
                : '#FF6B35',
            color: isPushing || !draft.trim() ? '#6B7280' : '#fff',
            border: 'none',
            borderRadius: 12,
            fontSize: 18,
            fontWeight: 700,
            cursor: isPushing || !draft.trim() ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s, transform 0.15s',
            letterSpacing: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
          }}
          onPointerDown={(e) => {
            if (!isPushing && draft.trim()) {
              (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
            }
          }}
          onPointerUp={(e) => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
          }}
          onPointerLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
          }}
        >
          {isPushing ? (
            <>
              <span
                style={{
                  display: 'inline-block',
                  width: 18,
                  height: 18,
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderTopColor: '#fff',
                  borderRadius: '50%',
                  animation: 'spin 0.7s linear infinite',
                }}
              />
              推送中…
            </>
          ) : (
            '立即推送'
          )}
        </button>

        {/* 提示文字 */}
        <p
          style={{
            margin: '14px 0 0',
            fontSize: 13,
            color: '#4B5563',
            textAlign: 'center',
          }}
        >
          推送后公告将在 1 秒内同步到菜单展示屏的滚动栏
        </p>
      </div>

      {/* CSS 动画 */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
