import { useCallback, useEffect, useRef, useState } from 'react';
import { txFetch } from '../api/index';

interface CourseStatus {
  course_name: string;
  course_label: string;
  sort_order: number;
  status: 'waiting' | 'fired' | 'completed';
  dish_count: number;
  fired_count: number;
  done_count: number;
  fired_at: string | null;
  fired_by: string | null;
}

interface Props {
  orderId: string;
  onFire?: (courseName: string) => void;
}


function statusIcon(status: CourseStatus['status']): string {
  if (status === 'completed') return '✅';
  if (status === 'fired') return '🔥';
  return '⏸';
}

function statusColor(status: CourseStatus['status']): string {
  if (status === 'completed') return '#22c55e';
  if (status === 'fired') return '#FF6B35';
  return '#64748b';
}

export function CourseFiringPanel({ orderId, onFire }: Props) {
  const [courses, setCourses] = useState<CourseStatus[]>([]);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [confirmCourse, setConfirmCourse] = useState<CourseStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchCourses = useCallback(async () => {
    try {
      const data = await txFetch<{ items: CourseStatus[] }>('/api/v1/trade/kds/course-queue');
      setCourses(data.items ?? []);
    } catch {
      setCourses([]);
    }
  }, []);

  const fetchSuggestion = useCallback(async () => {
    // suggestion 是可选功能，失败时不展示
    setSuggestion(null);
  }, []);

  useEffect(() => {
    fetchCourses();
    fetchSuggestion();
    intervalRef.current = setInterval(() => {
      fetchCourses();
      fetchSuggestion();
    }, 15000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchCourses, fetchSuggestion]);

  const handleFireConfirm = async () => {
    if (!confirmCourse) return;
    setLoading(true);
    try {
      await txFetch(`/api/v1/trade/kds/course/${encodeURIComponent(confirmCourse.course_name)}/fire`, {
        method: 'POST',
      });
      onFire?.(confirmCourse.course_name);
      await fetchCourses();
    } catch {
      // fire 失败 — 保持 UI 响应，不崩溃
    } finally {
      setLoading(false);
      setConfirmCourse(null);
    }
  };

  const handleSuggestionFire = () => {
    const nextWaiting = courses
      .filter(c => c.status === 'waiting')
      .sort((a, b) => a.sort_order - b.sort_order)[0];
    if (nextWaiting) setConfirmCourse(nextWaiting);
    setSuggestion(null);
  };

  return (
    <div style={{ background: '#112228', borderRadius: 12, overflow: 'hidden', margin: '8px 0' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #1a2a33' }}>
        <span style={{ color: '#e2e8f0', fontSize: 16, fontWeight: 600 }}>上菜节奏控制</span>
      </div>

      {suggestion && (
        <div style={{
          background: '#1a2a33',
          borderLeft: '3px solid #FF6B35',
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}>
          <span style={{ color: '#e2e8f0', fontSize: 15, flex: 1 }}>💡 {suggestion}</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleSuggestionFire}
              style={{
                background: '#FF6B35',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                padding: '8px 14px',
                fontSize: 15,
                fontWeight: 600,
                minWidth: 80,
                minHeight: 48,
                cursor: 'pointer',
              }}
            >
              立即开火
            </button>
            <button
              onClick={() => setSuggestion(null)}
              style={{
                background: '#1a2a33',
                color: '#64748b',
                border: '1px solid #1a2a33',
                borderRadius: 8,
                padding: '8px 14px',
                fontSize: 15,
                minWidth: 60,
                minHeight: 48,
                cursor: 'pointer',
              }}
            >
              稍后
            </button>
          </div>
        </div>
      )}

      {courses.map(course => (
        <div
          key={course.course_name}
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid #1a2a33',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
              <span style={{ fontSize: 18 }}>{statusIcon(course.status)}</span>
              <span style={{ color: statusColor(course.status), fontSize: 16, fontWeight: 600 }}>
                {course.course_label}
              </span>
              <span style={{ color: '#64748b', fontSize: 14 }}>
                {course.dish_count}道
              </span>
            </div>
            <div style={{ color: '#64748b', fontSize: 14, paddingLeft: 26 }}>
              {course.status === 'completed' && '已全部上桌'}
              {course.status === 'fired' && `制作中${course.fired_count - course.done_count}道 · 已出餐${course.done_count}道`}
              {course.status === 'waiting' && '等待开火'}
            </div>
          </div>

          {course.status === 'waiting' && (
            <button
              onClick={() => setConfirmCourse(course)}
              style={{
                background: '#FF6B35',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                padding: '10px 16px',
                fontSize: 15,
                fontWeight: 600,
                minWidth: 120,
                minHeight: 48,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              开火{course.course_label}({course.dish_count}道)
            </button>
          )}

          {course.status === 'fired' && (
            <div style={{ color: '#FF6B35', fontSize: 14, textAlign: 'right', whiteSpace: 'nowrap' }}>
              已开火，等待出餐
            </div>
          )}
        </div>
      ))}

      {confirmCourse && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setConfirmCourse(null)}
        >
          <div
            style={{
              background: '#112228',
              borderRadius: 16,
              padding: '24px 20px',
              width: 300,
              maxWidth: '90vw',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ color: '#e2e8f0', fontSize: 18, fontWeight: 700, marginBottom: 12 }}>
              确认开火"{confirmCourse.course_label}"？
            </div>
            <div style={{ color: '#64748b', fontSize: 15, marginBottom: 24 }}>
              共{confirmCourse.dish_count}道菜将发送到厨房制作
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={handleFireConfirm}
                disabled={loading}
                style={{
                  flex: 1,
                  background: '#FF6B35',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 10,
                  padding: '14px 0',
                  fontSize: 16,
                  fontWeight: 700,
                  minHeight: 52,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  opacity: loading ? 0.7 : 1,
                }}
              >
                {loading ? '开火中...' : '确认开火'}
              </button>
              <button
                onClick={() => setConfirmCourse(null)}
                style={{
                  flex: 1,
                  background: '#1a2a33',
                  color: '#e2e8f0',
                  border: '1px solid #1a2a33',
                  borderRadius: 10,
                  padding: '14px 0',
                  fontSize: 16,
                  minHeight: 52,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
