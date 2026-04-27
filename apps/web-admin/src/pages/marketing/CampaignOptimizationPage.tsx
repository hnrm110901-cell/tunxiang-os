/**
 * Campaign自优化看板 — S1W1
 *
 * 展示Campaign AB测试优化记录：
 * - 优化大盘统计（轮次/自动应用/待审批/进行中）
 * - 优化记录列表（Campaign维度，含AB指标对比）
 * - 审批操作（通过/拒绝/应用）
 */

import { useCallback, useEffect, useState } from "react";

const API_BASE = "/api/v1/growth/ai-marketing";

interface OptimizationLog {
  id: string;
  campaign_id: string;
  marketing_task_id: string | null;
  optimization_round: number;
  variant_a_metrics: Record<string, number>;
  variant_b_metrics: Record<string, number>;
  winner: string | null;
  p_value: number | null;
  status: string;
  budget_shift_pct: number;
  adjustment_action: Record<string, unknown>;
  created_at: string;
  approved_by: string | null;
  applied_at: string | null;
}

interface DashboardStats {
  total_rounds: number;
  applied_count: number;
  rejected_count: number;
  evaluating_count: number;
  pending_count: number;
  avg_budget_shift: number;
  avg_p_value: number;
  campaigns_optimized: number;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  evaluating: { label: "评估中", color: "bg-blue-100 text-blue-800" },
  pending_approval: { label: "待审批", color: "bg-yellow-100 text-yellow-800" },
  approved: { label: "已审批", color: "bg-green-100 text-green-800" },
  applied: { label: "已应用", color: "bg-green-200 text-green-900" },
  auto_applied: { label: "自动应用", color: "bg-emerald-100 text-emerald-800" },
  rejected: { label: "已拒绝", color: "bg-red-100 text-red-800" },
};

const WINNER_LABELS: Record<string, string> = {
  a: "变体A胜出",
  b: "变体B胜出",
  none: "无差异",
  inconclusive: "尚无结论",
};

export default function CampaignOptimizationPage() {
  const [logs, setLogs] = useState<OptimizationLog[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const tenantId = localStorage.getItem("tenant_id") || "";

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const headers = { "X-Tenant-ID": tenantId };

      // Fetch dashboard stats and recent logs in parallel
      const [statsRes, logsRes] = await Promise.all([
        fetch(`${API_BASE}/optimization/dashboard`, { headers }),
        fetch(`${API_BASE}/optimization/recent?size=50`, { headers }),
      ]);

      if (statsRes.ok) {
        const d = await statsRes.json();
        if (d.ok) setStats(d.data);
      }
      if (logsRes.ok) {
        const d = await logsRes.json();
        if (d.ok) setLogs(d.data?.items || []);
      }
    } catch {
      // Network error — silently fail, show empty state
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleApprove = async (optimizationId: string) => {
    setActionLoading(optimizationId);
    try {
      const resp = await fetch(`${API_BASE}/optimization/${optimizationId}/apply`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({ approved_by: "admin" }),
      });
      if (resp.ok) {
        await fetchData();
      }
    } finally {
      setActionLoading(null);
    }
  };

  const formatRate = (rate: number | undefined) =>
    rate != null ? `${(rate * 100).toFixed(1)}%` : "-";

  const formatFen = (fen: number | undefined) =>
    fen != null ? `¥${(fen / 100).toFixed(0)}` : "-";

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Campaign 自优化看板</h1>

      {/* Dashboard Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard label="优化Campaign数" value={stats.campaigns_optimized} />
          <StatCard label="总轮次" value={stats.total_rounds} />
          <StatCard
            label="已应用"
            value={stats.applied_count}
            accent="text-green-600"
          />
          <StatCard
            label="待审批"
            value={stats.pending_count}
            accent="text-yellow-600"
          />
          <StatCard label="评估中" value={stats.evaluating_count} />
          <StatCard label="已拒绝" value={stats.rejected_count} />
          <StatCard
            label="平均预算偏移"
            value={`${stats.avg_budget_shift.toFixed(1)}%`}
          />
          <StatCard
            label="平均p-value"
            value={stats.avg_p_value.toFixed(4)}
          />
        </div>
      )}

      {/* Optimization Logs Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold">优化记录</h2>
          <button
            onClick={fetchData}
            disabled={loading}
            className="px-4 py-2 text-sm bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 disabled:opacity-50"
          >
            {loading ? "加载中..." : "刷新"}
          </button>
        </div>

        {loading && logs.length === 0 ? (
          <div className="p-12 text-center text-gray-400">加载中...</div>
        ) : logs.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            暂无优化记录。启动营销任务后，系统将自动创建AB测试并评估效果。
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-4 py-3 text-left">轮次</th>
                  <th className="px-4 py-3 text-left">状态</th>
                  <th className="px-4 py-3 text-left">变体A</th>
                  <th className="px-4 py-3 text-left">变体B</th>
                  <th className="px-4 py-3 text-left">胜出</th>
                  <th className="px-4 py-3 text-left">p-value</th>
                  <th className="px-4 py-3 text-left">预算偏移</th>
                  <th className="px-4 py-3 text-left">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {logs.map((log) => {
                  const statusInfo = STATUS_LABELS[log.status] || {
                    label: log.status,
                    color: "bg-gray-100 text-gray-800",
                  };

                  return (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs">
                          R{log.optimization_round}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusInfo.color}`}
                        >
                          {statusInfo.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <div>发送: {log.variant_a_metrics?.send_count || 0}</div>
                        <div>
                          转化: {formatRate(log.variant_a_metrics?.conversion_rate)}
                        </div>
                        <div>
                          收入: {formatFen(log.variant_a_metrics?.revenue_fen)}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <div>发送: {log.variant_b_metrics?.send_count || 0}</div>
                        <div>
                          转化: {formatRate(log.variant_b_metrics?.conversion_rate)}
                        </div>
                        <div>
                          收入: {formatFen(log.variant_b_metrics?.revenue_fen)}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs">
                          {log.winner
                            ? WINNER_LABELS[log.winner] || log.winner
                            : "-"}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {log.p_value != null ? log.p_value.toFixed(4) : "-"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {log.budget_shift_pct > 0
                          ? `${log.budget_shift_pct}%`
                          : "-"}
                      </td>
                      <td className="px-4 py-3">
                        {log.status === "pending_approval" && (
                          <button
                            onClick={() => handleApprove(log.id)}
                            disabled={actionLoading === log.id}
                            className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                          >
                            {actionLoading === log.id ? "处理中..." : "审批通过"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: string;
}) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${accent || "text-gray-900"}`}>
        {value}
      </div>
    </div>
  );
}
