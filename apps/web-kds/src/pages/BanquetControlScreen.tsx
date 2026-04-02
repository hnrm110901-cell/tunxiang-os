/**
 * BanquetControlScreen — 宴席控菜大屏
 *
 * 职责：厨师长在此页面统一指挥宴席出品节奏
 * - 显示今日所有宴席场次及倒计时
 * - 出品进度条（各节完成率）
 * - 一键推进到下一节（所有档口同步触发）
 * - 开席操作（正式开始出品）
 *
 * 终端：后厨控菜大屏（1920×1080 或更大），横屏专用
 * 触控：支持触屏操作，按钮尺寸≥56px
 */

import { useEffect, useState, useCallback, useRef } from "react";

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface BanquetSession {
  id: string;
  session_name: string;
  scheduled_at: string;
  actual_open_at: string | null;
  status: "scheduled" | "preparing" | "serving" | "completed" | "cancelled";
  guest_count: number;
  table_count: number;
  menu_name: string;
  per_person_fen: number;
  current_section_id: string | null;
  current_section_name: string | null;
  countdown_seconds: number | null;
  is_urgent: boolean;
}

interface SectionProgress {
  section_name: string;
  serve_sequence: number;
  total_tasks: number;
  done_tasks: number;
  cooking_tasks: number;
  pending_tasks: number;
  completion_pct: number;
  status: "not_started" | "pending" | "in_progress" | "completed";
}

interface BanquetProgress {
  session_id: string;
  sections: SectionProgress[];
  overall_completion_pct: number;
  overall_total: number;
  overall_done: number;
}

// ─── API 客户端 ──────────────────────────────────────────────────────────────

const API_HOST =
  localStorage.getItem("kds_mac_host") || "http://localhost:8000";
const TENANT_ID = localStorage.getItem("kds_tenant_id") || "";
const STORE_ID = localStorage.getItem("kds_store_id") || "";

const headers = {
  "Content-Type": "application/json",
  "X-Tenant-ID": TENANT_ID,
  "X-Store-ID": STORE_ID,
};

async function fetchSessions(): Promise<BanquetSession[]> {
  const r = await fetch(
    `${API_HOST}/api/v1/kds/banquet-sessions/${STORE_ID}`,
    { headers }
  );
  const json = await r.json();
  return json.data?.sessions ?? [];
}

async function fetchProgress(sessionId: string): Promise<BanquetProgress | null> {
  const r = await fetch(
    `${API_HOST}/api/v1/kds/banquet-sessions/${sessionId}/progress`,
    { headers }
  );
  const json = await r.json();
  return json.data ?? null;
}

async function openBanquet(sessionId: string): Promise<void> {
  await fetch(`${API_HOST}/api/v1/kds/banquet-sessions/open`, {
    method: "POST",
    headers,
    body: JSON.stringify({ session_id: sessionId }),
  });
}

async function pushNextSection(
  sessionId: string,
  sectionId: string
): Promise<{ section_name: string; tasks_created: number } | null> {
  const r = await fetch(
    `${API_HOST}/api/v1/kds/banquet-sessions/push-section`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ session_id: sessionId, section_id: sectionId }),
    }
  );
  const json = await r.json();
  return json.data ?? null;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "已到开席时间";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatTime(isoStr: string): string {
  if (!isoStr) return "--:--";
  return new Date(isoStr).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusColor(status: BanquetSession["status"]): string {
  const map: Record<string, string> = {
    scheduled: "#6B7280",
    preparing: "#D97706",
    serving: "#059669",
    completed: "#374151",
    cancelled: "#DC2626",
  };
  return map[status] || "#6B7280";
}

function statusLabel(status: BanquetSession["status"]): string {
  const map: Record<string, string> = {
    scheduled: "待开席",
    preparing: "备餐中",
    serving: "进行中",
    completed: "已结束",
    cancelled: "已取消",
  };
  return map[status] || status;
}

function sectionStatusColor(s: SectionProgress["status"]): string {
  const map: Record<string, string> = {
    not_started: "#9CA3AF",
    pending: "#F59E0B",
    in_progress: "#3B82F6",
    completed: "#10B981",
  };
  return map[s] || "#9CA3AF";
}

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export default function BanquetControlScreen() {
  const [sessions, setSessions] = useState<BanquetSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [progress, setProgress] = useState<BanquetProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [countdowns, setCountdowns] = useState<Record<string, number>>({});
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const data = await fetchSessions();
      setSessions(data);
      // 初始化倒计时
      const cd: Record<string, number> = {};
      for (const s of data) {
        if (s.countdown_seconds !== null) cd[s.id] = s.countdown_seconds;
      }
      setCountdowns(cd);
    } catch (e) {
      console.error("fetch sessions error", e);
    }
  }, []);

  const loadProgress = useCallback(async (sessionId: string) => {
    try {
      const data = await fetchProgress(sessionId);
      setProgress(data);
    } catch (e) {
      console.error("fetch progress error", e);
    }
  }, []);

  // 初始加载 + 30秒刷新
  useEffect(() => {
    loadSessions();
    const interval = setInterval(loadSessions, 30_000);
    return () => clearInterval(interval);
  }, [loadSessions]);

  // 倒计时每秒递减
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setCountdowns((prev) => {
        const next = { ...prev };
        for (const id of Object.keys(next)) {
          if (next[id] > 0) next[id] -= 1;
        }
        return next;
      });
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // 选中场次时加载进度
  useEffect(() => {
    if (selectedId) {
      loadProgress(selectedId);
      const interval = setInterval(() => loadProgress(selectedId), 10_000);
      return () => clearInterval(interval);
    }
  }, [selectedId, loadProgress]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const handleOpen = async (sessionId: string) => {
    setLoading(true);
    try {
      await openBanquet(sessionId);
      showToast("✅ 开席成功！出品任务已下发到各档口KDS");
      await loadSessions();
      await loadProgress(sessionId);
    } catch {
      showToast("❌ 开席失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const handlePushSection = async (sessionId: string, sectionId: string) => {
    setLoading(true);
    try {
      const result = await pushNextSection(sessionId, sectionId);
      if (result) {
        showToast(
          `✅ 「${result.section_name}」已推送！${result.tasks_created}个任务下发到各档口`
        );
        await loadProgress(sessionId);
      }
    } catch {
      showToast("❌ 推送失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const selected = sessions.find((s) => s.id === selectedId);

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        background: "#111827",
        color: "#F9FAFB",
        fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
        overflow: "hidden",
      }}
    >
      {/* ── 左侧：场次列表 ── */}
      <div
        style={{
          width: 340,
          background: "#1F2937",
          borderRight: "1px solid #374151",
          display: "flex",
          flexDirection: "column",
          overflowY: "auto",
        }}
      >
        {/* 头部 */}
        <div
          style={{
            padding: "20px 16px 12px",
            borderBottom: "1px solid #374151",
          }}
        >
          <div style={{ fontSize: 11, color: "#6B7280", letterSpacing: 2 }}>
            后厨控菜大屏
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
            今日宴席场次
          </div>
          <div style={{ fontSize: 13, color: "#9CA3AF", marginTop: 2 }}>
            {new Date().toLocaleDateString("zh-CN", {
              month: "long",
              day: "numeric",
              weekday: "long",
            })}
          </div>
        </div>

        {/* 场次卡片列表 */}
        <div style={{ flex: 1, padding: "8px 0" }}>
          {sessions.length === 0 ? (
            <div
              style={{
                padding: 24,
                textAlign: "center",
                color: "#6B7280",
                fontSize: 14,
              }}
            >
              今日暂无宴席场次
            </div>
          ) : (
            sessions.map((session) => {
              const cd = countdowns[session.id];
              const isSelected = selectedId === session.id;
              return (
                <div
                  key={session.id}
                  onClick={() => setSelectedId(session.id)}
                  style={{
                    margin: "4px 8px",
                    padding: "14px 16px",
                    borderRadius: 8,
                    cursor: "pointer",
                    background: isSelected ? "#374151" : "transparent",
                    border: isSelected
                      ? "1px solid #4B5563"
                      : "1px solid transparent",
                    transition: "all 0.15s",
                  }}
                >
                  {/* 场次名 + 状态 */}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: 6,
                    }}
                  >
                    <div
                      style={{ fontSize: 15, fontWeight: 600, flex: 1 }}
                    >
                      {session.session_name || "宴席场次"}
                    </div>
                    <div
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        padding: "2px 8px",
                        borderRadius: 4,
                        background: statusColor(session.status) + "33",
                        color: statusColor(session.status),
                        whiteSpace: "nowrap",
                      }}
                    >
                      {statusLabel(session.status)}
                    </div>
                  </div>

                  {/* 菜单名 */}
                  <div
                    style={{ fontSize: 12, color: "#9CA3AF", marginBottom: 6 }}
                  >
                    {session.menu_name}
                  </div>

                  {/* 信息行 */}
                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      fontSize: 12,
                      color: "#6B7280",
                    }}
                  >
                    <span>🕐 {formatTime(session.scheduled_at)}</span>
                    <span>🍽 {session.table_count}桌</span>
                    <span>👥 {session.guest_count}人</span>
                  </div>

                  {/* 倒计时（仅 scheduled 状态显示）*/}
                  {session.status === "scheduled" && cd !== undefined && (
                    <div
                      style={{
                        marginTop: 8,
                        fontSize: 20,
                        fontWeight: 700,
                        fontVariantNumeric: "tabular-nums",
                        color: session.is_urgent ? "#F59E0B" : "#60A5FA",
                        letterSpacing: 1,
                      }}
                    >
                      {formatCountdown(cd)}
                    </div>
                  )}

                  {/* 当前节（serving 状态显示）*/}
                  {session.status === "serving" &&
                    session.current_section_name && (
                      <div
                        style={{
                          marginTop: 8,
                          fontSize: 12,
                          color: "#34D399",
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <span
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            background: "#34D399",
                            display: "inline-block",
                            animation: "pulse 1.5s infinite",
                          }}
                        />
                        正在出品：{session.current_section_name}
                      </div>
                    )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── 右侧：选中场次详情 ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!selectedId || !selected ? (
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexDirection: "column",
              color: "#4B5563",
              gap: 12,
            }}
          >
            <div style={{ fontSize: 48 }}>🍽</div>
            <div style={{ fontSize: 18 }}>选择左侧宴席场次查看详情</div>
          </div>
        ) : (
          <>
            {/* 详情头部 */}
            <div
              style={{
                padding: "20px 28px 16px",
                borderBottom: "1px solid #374151",
                background: "#1F2937",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div>
                <div style={{ fontSize: 11, color: "#6B7280", letterSpacing: 2 }}>
                  宴席场次
                </div>
                <div style={{ fontSize: 24, fontWeight: 700, marginTop: 2 }}>
                  {selected.session_name || "宴席场次"}
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 16,
                    marginTop: 6,
                    fontSize: 13,
                    color: "#9CA3AF",
                  }}
                >
                  <span>📋 {selected.menu_name}</span>
                  <span>🕐 {formatTime(selected.scheduled_at)}</span>
                  <span>🍽 {selected.table_count}桌</span>
                  <span>👥 {selected.guest_count}人</span>
                  {selected.per_person_fen > 0 && (
                    <span>💰 ¥{selected.per_person_fen / 100}/位</span>
                  )}
                </div>
              </div>

              {/* 操作按钮 */}
              <div style={{ display: "flex", gap: 12 }}>
                {selected.status === "scheduled" && (
                  <button
                    onClick={() => handleOpen(selected.id)}
                    disabled={loading}
                    style={{
                      padding: "14px 28px",
                      fontSize: 16,
                      fontWeight: 700,
                      background: loading ? "#4B5563" : "#059669",
                      color: "#fff",
                      border: "none",
                      borderRadius: 8,
                      cursor: loading ? "not-allowed" : "pointer",
                      minWidth: 120,
                    }}
                  >
                    {loading ? "处理中..." : "🚀 开席"}
                  </button>
                )}

                {selected.status === "serving" && progress && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {progress.sections
                      .filter(
                        (s) =>
                          s.status === "pending" || s.status === "not_started"
                      )
                      .slice(0, 3)
                      .map((section) => (
                        <button
                          key={section.section_name}
                          onClick={() =>
                            /* 实际需要 sectionId，此处用 section_name 作为临时 mock */
                            handlePushSection(selected.id, section.section_name)
                          }
                          disabled={loading}
                          style={{
                            padding: "12px 20px",
                            fontSize: 14,
                            fontWeight: 600,
                            background: loading ? "#4B5563" : "#1D4ED8",
                            color: "#fff",
                            border: "none",
                            borderRadius: 8,
                            cursor: loading ? "not-allowed" : "pointer",
                          }}
                        >
                          📢 推送{section.section_name}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            </div>

            {/* 出品进度区域 */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "24px 28px",
              }}
            >
              {/* 总体进度 */}
              {progress && (
                <>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 16,
                      marginBottom: 24,
                    }}
                  >
                    <div style={{ fontSize: 14, color: "#9CA3AF" }}>
                      整体出品进度
                    </div>
                    <div
                      style={{
                        flex: 1,
                        height: 8,
                        background: "#374151",
                        borderRadius: 4,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          width: `${progress.overall_completion_pct}%`,
                          height: "100%",
                          background: "#10B981",
                          borderRadius: 4,
                          transition: "width 0.5s ease",
                        }}
                      />
                    </div>
                    <div
                      style={{
                        fontSize: 20,
                        fontWeight: 700,
                        color: "#10B981",
                        minWidth: 60,
                        textAlign: "right",
                      }}
                    >
                      {progress.overall_completion_pct}%
                    </div>
                    <div style={{ fontSize: 13, color: "#6B7280" }}>
                      {progress.overall_done}/{progress.overall_total}
                    </div>
                  </div>

                  {/* 各节进度卡片 */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                      gap: 16,
                    }}
                  >
                    {progress.sections.map((section, idx) => (
                      <div
                        key={section.section_name}
                        style={{
                          background: "#1F2937",
                          borderRadius: 12,
                          padding: 20,
                          border: `1px solid ${
                            section.status === "in_progress"
                              ? "#3B82F6"
                              : "#374151"
                          }`,
                          position: "relative",
                          overflow: "hidden",
                        }}
                      >
                        {/* 进行中闪烁边框 */}
                        {section.status === "in_progress" && (
                          <div
                            style={{
                              position: "absolute",
                              top: 0,
                              left: 0,
                              right: 0,
                              height: 3,
                              background: "#3B82F6",
                            }}
                          />
                        )}

                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "flex-start",
                            marginBottom: 12,
                          }}
                        >
                          <div>
                            <div
                              style={{
                                fontSize: 11,
                                color: "#6B7280",
                                marginBottom: 4,
                              }}
                            >
                              第{idx + 1}节 · 第{section.serve_sequence}道
                            </div>
                            <div
                              style={{ fontSize: 18, fontWeight: 700 }}
                            >
                              {section.section_name}
                            </div>
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: "3px 10px",
                              borderRadius: 4,
                              background:
                                sectionStatusColor(section.status) + "22",
                              color: sectionStatusColor(section.status),
                            }}
                          >
                            {section.status === "not_started"
                              ? "未开始"
                              : section.status === "pending"
                              ? "待出品"
                              : section.status === "in_progress"
                              ? "出品中"
                              : "✓ 已完成"}
                          </div>
                        </div>

                        {/* 进度条 */}
                        <div
                          style={{
                            height: 6,
                            background: "#374151",
                            borderRadius: 3,
                            overflow: "hidden",
                            marginBottom: 10,
                          }}
                        >
                          <div
                            style={{
                              width: `${section.completion_pct}%`,
                              height: "100%",
                              background: sectionStatusColor(section.status),
                              borderRadius: 3,
                              transition: "width 0.5s",
                            }}
                          />
                        </div>

                        {/* 统计数字 */}
                        <div
                          style={{
                            display: "flex",
                            gap: 16,
                            fontSize: 12,
                            color: "#9CA3AF",
                          }}
                        >
                          <span style={{ color: "#10B981" }}>
                            ✓ {section.done_tasks} 完成
                          </span>
                          {section.cooking_tasks > 0 && (
                            <span style={{ color: "#3B82F6" }}>
                              ⏳ {section.cooking_tasks} 制作中
                            </span>
                          )}
                          {section.pending_tasks > 0 && (
                            <span>◯ {section.pending_tasks} 待制作</span>
                          )}
                          <span style={{ marginLeft: "auto", fontWeight: 600 }}>
                            {section.completion_pct}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* 未开席时的提示 */}
              {selected.status === "scheduled" && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    height: 300,
                    color: "#6B7280",
                    gap: 16,
                  }}
                >
                  <div style={{ fontSize: 64 }}>⏰</div>
                  <div style={{ fontSize: 20, color: "#9CA3AF" }}>
                    宴席将于 {formatTime(selected.scheduled_at)} 开席
                  </div>
                  {countdowns[selected.id] !== undefined && (
                    <div
                      style={{
                        fontSize: 48,
                        fontWeight: 700,
                        fontVariantNumeric: "tabular-nums",
                        color: selected.is_urgent ? "#F59E0B" : "#60A5FA",
                        letterSpacing: 2,
                      }}
                    >
                      {formatCountdown(countdowns[selected.id])}
                    </div>
                  )}
                  <div style={{ fontSize: 14 }}>
                    点击「开席」按钮后，出品任务将同步下发到所有档口KDS
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* 全局 Toast */}
      {toast && (
        <div
          style={{
            position: "fixed",
            top: 24,
            left: "50%",
            transform: "translateX(-50%)",
            background: toast.startsWith("✅") ? "#065F46" : "#7F1D1D",
            color: "#fff",
            padding: "12px 24px",
            borderRadius: 8,
            fontSize: 15,
            fontWeight: 600,
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
            zIndex: 9999,
            whiteSpace: "nowrap",
          }}
        >
          {toast}
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
