/**
 * 流失预测看板 — S1W2
 *
 * 展示会员流失风险分布、干预效果、评分趋势
 */

import { useCallback, useEffect, useState } from "react";

const API_BASE = "/api/v1/predict/churn";

interface ChurnScore {
  id: string;
  customer_id: string;
  score: number;
  risk_tier: string;
  root_cause: string;
  signals: Record<string, number>;
  score_delta: number;
  scored_at: string;
  journey_triggered_at: string | null;
}

interface DashboardData {
  total_scored: number;
  tiers: Record<string, { count: number; avg_score: number; intervened: number }>;
  intervention_rate: number;
}

const TIER_CONFIG: Record<string, { label: string; color: string; bgColor: string }> = {
  warm: { label: "温和风险", color: "text-yellow-700", bgColor: "bg-yellow-50" },
  urgent: { label: "紧急风险", color: "text-orange-700", bgColor: "bg-orange-50" },
  critical: { label: "严重风险", color: "text-red-700", bgColor: "bg-red-50" },
};

const CAUSE_LABELS: Record<string, string> = {
  price: "价格敏感",
  taste: "口味变化",
  competition: "竞品吸引",
  moved: "搬迁",
  seasonal: "季节性",
  service: "服务问题",
  unknown: "待分析",
};

export default function ChurnDashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [scores, setScores] = useState<ChurnScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTier, setSelectedTier] = useState<string | null>(null);

  const tenantId = localStorage.getItem("tenant_id") || "";

  const fetchData = useCallback(async () => {
    setLoading(true);
    const headers = { "X-Tenant-ID": tenantId };
    try {
      const tierParam = selectedTier ? `&risk_tier=${selectedTier}` : "";
      const [dashRes, scoresRes] = await Promise.all([
        fetch(`${API_BASE}/dashboard`, { headers }),
        fetch(`${API_BASE}/scores?min_score=40&size=50${tierParam}`, { headers }),
      ]);
      if (dashRes.ok) {
        const d = await dashRes.json();
        if (d.ok) setDashboard(d.data);
      }
      if (scoresRes.ok) {
        const d = await scoresRes.json();
        if (d.ok) setScores(d.data?.items || []);
      }
    } catch { /* network error */ } finally {
      setLoading(false);
    }
  }, [tenantId, selectedTier]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBatchScore = async () => {
    await fetch(`${API_BASE}/score/batch`, {
      method: "POST",
      headers: { "X-Tenant-ID": tenantId },
    });
    await fetchData();
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">流失预测看板</h1>
        <button onClick={handleBatchScore} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          立即评分
        </button>
      </div>

      {/* Risk Tier Cards */}
      {dashboard && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white rounded-lg shadow p-4">
            <div className="text-xs text-gray-500">总评分人数</div>
            <div className="text-2xl font-bold">{dashboard.total_scored}</div>
            <div className="text-xs text-gray-400 mt-1">干预率 {dashboard.intervention_rate}%</div>
          </div>
          {(["warm", "urgent", "critical"] as const).map((tier) => {
            const data = dashboard.tiers[tier];
            const cfg = TIER_CONFIG[tier];
            return (
              <button key={tier} onClick={() => setSelectedTier(selectedTier === tier ? null : tier)}
                className={`rounded-lg shadow p-4 text-left transition ${selectedTier === tier ? "ring-2 ring-blue-500" : ""} ${cfg.bgColor}`}>
                <div className={`text-xs ${cfg.color}`}>{cfg.label}</div>
                <div className="text-2xl font-bold">{data?.count || 0}</div>
                <div className="text-xs text-gray-500 mt-1">均分 {data?.avg_score?.toFixed(0) || "-"} | 已干预 {data?.intervened || 0}</div>
              </button>
            );
          })}
        </div>
      )}

      {/* Scores Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {selectedTier ? `${TIER_CONFIG[selectedTier]?.label}客户` : "高风险客户列表"}
          </h2>
          <button onClick={fetchData} disabled={loading} className="text-sm text-blue-600 hover:underline">
            {loading ? "加载中..." : "刷新"}
          </button>
        </div>
        {scores.length === 0 ? (
          <div className="p-12 text-center text-gray-400">暂无评分数据。点击"立即评分"开始。</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-4 py-3 text-left">客户ID</th>
                  <th className="px-4 py-3 text-left">评分</th>
                  <th className="px-4 py-3 text-left">风险</th>
                  <th className="px-4 py-3 text-left">根因</th>
                  <th className="px-4 py-3 text-left">变化</th>
                  <th className="px-4 py-3 text-left">最后到店</th>
                  <th className="px-4 py-3 text-left">干预状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {scores.map((s) => {
                  const cfg = TIER_CONFIG[s.risk_tier] || TIER_CONFIG.warm;
                  return (
                    <tr key={s.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono text-xs">{s.customer_id.slice(0, 8)}...</td>
                      <td className="px-4 py-3">
                        <span className={`text-lg font-bold ${s.score >= 80 ? "text-red-600" : s.score >= 60 ? "text-orange-600" : "text-yellow-600"}`}>
                          {s.score}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bgColor} ${cfg.color}`}>
                          {cfg.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs">{CAUSE_LABELS[s.root_cause] || s.root_cause}</td>
                      <td className="px-4 py-3 text-xs">
                        {s.score_delta > 0 ? (
                          <span className="text-red-500">+{s.score_delta}</span>
                        ) : s.score_delta < 0 ? (
                          <span className="text-green-500">{s.score_delta}</span>
                        ) : <span className="text-gray-400">-</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">
                        {s.signals?.days_since_last ? `${s.signals.days_since_last}天前` : "-"}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {s.journey_triggered_at ? (
                          <span className="text-green-600">已触发旅程</span>
                        ) : (
                          <span className="text-gray-400">待干预</span>
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
