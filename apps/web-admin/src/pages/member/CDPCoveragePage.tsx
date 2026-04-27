/**
 * CDP覆盖率看板 — S2W5
 *
 * 展示多源数据的身份匹配覆盖率：
 * - 各数据源卡片（微信/WiFi/美团/饿了么/大众点评）及匹配率
 * - 总独立客户 vs 已识别客户
 * - 门店级别明细表
 * - 手动触发批量解析按钮
 */

import { useCallback, useEffect, useState } from "react";

const API_WIFI = "/api/v1/member/wifi";
const API_EXT = "/api/v1/member/external";

interface SourceCoverage {
  total: number;
  matched: number;
  match_rate: number;
}

interface StoreCoverage {
  store_id: string;
  store_name: string;
  wifi_total: number;
  wifi_matched: number;
  external_total: number;
  external_matched: number;
  overall_rate: number;
}

const SOURCE_CONFIG: Record<string, { label: string; icon: string; color: string; bgColor: string }> = {
  wechat: { label: "微信", icon: "💬", color: "text-green-700", bgColor: "bg-green-50" },
  wifi: { label: "WiFi探针", icon: "📡", color: "text-blue-700", bgColor: "bg-blue-50" },
  meituan: { label: "美团", icon: "🟡", color: "text-yellow-700", bgColor: "bg-yellow-50" },
  eleme: { label: "饿了么", icon: "🔵", color: "text-sky-700", bgColor: "bg-sky-50" },
  dianping: { label: "大众点评", icon: "⭐", color: "text-orange-700", bgColor: "bg-orange-50" },
  douyin: { label: "抖音", icon: "🎵", color: "text-pink-700", bgColor: "bg-pink-50" },
  xiaohongshu: { label: "小红书", icon: "📕", color: "text-red-700", bgColor: "bg-red-50" },
};

export default function CDPCoveragePage() {
  const [sources, setSources] = useState<Record<string, SourceCoverage>>({});
  const [stores, setStores] = useState<StoreCoverage[]>([]);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);
  const [totalCustomers, setTotalCustomers] = useState(0);
  const [identifiedCustomers, setIdentifiedCustomers] = useState(0);

  const tenantId = localStorage.getItem("tenant_id") || "";

  const fetchData = useCallback(async () => {
    setLoading(true);
    const headers = { "X-Tenant-ID": tenantId };
    try {
      const [wifiRes, extRes] = await Promise.all([
        fetch(`${API_WIFI}/coverage`, { headers }),
        fetch(`${API_EXT}/coverage`, { headers }),
      ]);

      const merged: Record<string, SourceCoverage> = {};

      if (wifiRes.ok) {
        const w = await wifiRes.json();
        if (w.ok) {
          merged.wifi = {
            total: w.data.total_visits || 0,
            matched: w.data.matched || 0,
            match_rate: w.data.match_rate || 0,
          };
        }
      }

      if (extRes.ok) {
        const e = await extRes.json();
        if (e.ok) {
          for (const [src, stats] of Object.entries(e.data as Record<string, SourceCoverage>)) {
            merged[src] = stats;
          }
        }
      }

      setSources(merged);

      // 计算汇总
      let total = 0;
      let identified = 0;
      for (const s of Object.values(merged)) {
        total += s.total;
        identified += s.matched;
      }
      setTotalCustomers(total);
      setIdentifiedCustomers(identified);
    } catch {
      /* network error */
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleResolve = async () => {
    setResolving(true);
    const headers = { "X-Tenant-ID": tenantId, "Content-Type": "application/json" };
    try {
      await Promise.all([
        fetch(`${API_WIFI}/match`, { method: "POST", headers, body: JSON.stringify({}) }),
        fetch(`${API_EXT}/resolve`, { method: "POST", headers, body: JSON.stringify({}) }),
      ]);
      await fetchData();
    } catch {
      /* network error */
    } finally {
      setResolving(false);
    }
  };

  const overallRate = totalCustomers > 0
    ? Math.round((identifiedCustomers / totalCustomers) * 1000) / 10
    : 0;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">CDP 覆盖率看板</h1>
          <p className="text-sm text-gray-500 mt-1">多源数据身份匹配统计</p>
        </div>
        <button
          onClick={handleResolve}
          disabled={resolving}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {resolving ? "解析中..." : "触发身份解析"}
        </button>
      </div>

      {/* Overall Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-white rounded-lg shadow p-5">
          <div className="text-xs text-gray-500">总触点记录</div>
          <div className="text-3xl font-bold mt-1">{totalCustomers.toLocaleString()}</div>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <div className="text-xs text-gray-500">已识别客户</div>
          <div className="text-3xl font-bold mt-1 text-green-600">{identifiedCustomers.toLocaleString()}</div>
        </div>
        <div className="bg-white rounded-lg shadow p-5">
          <div className="text-xs text-gray-500">总体识别率</div>
          <div className="text-3xl font-bold mt-1">
            <span className={overallRate >= 60 ? "text-green-600" : overallRate >= 30 ? "text-yellow-600" : "text-red-600"}>
              {overallRate}%
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
            <div
              className={`h-2 rounded-full ${overallRate >= 60 ? "bg-green-500" : overallRate >= 30 ? "bg-yellow-500" : "bg-red-500"}`}
              style={{ width: `${Math.min(overallRate, 100)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Per-Source Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-8">
        {Object.entries(SOURCE_CONFIG).map(([key, cfg]) => {
          const s = sources[key];
          const rate = s?.match_rate ?? 0;
          const total = s?.total ?? 0;
          return (
            <div key={key} className={`rounded-lg shadow p-4 ${cfg.bgColor}`}>
              <div className="flex items-center gap-1 mb-2">
                <span className="text-lg">{cfg.icon}</span>
                <span className={`text-xs font-medium ${cfg.color}`}>{cfg.label}</span>
              </div>
              <div className="text-xl font-bold">{rate}%</div>
              <div className="text-xs text-gray-500 mt-1">{total.toLocaleString()} 条</div>
              <div className="w-full bg-white/50 rounded-full h-1.5 mt-2">
                <div
                  className={`h-1.5 rounded-full ${rate >= 60 ? "bg-green-500" : rate >= 30 ? "bg-yellow-500" : "bg-red-400"}`}
                  style={{ width: `${Math.min(rate, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Store Breakdown Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold">门店级别明细</h2>
          <button
            onClick={fetchData}
            disabled={loading}
            className="text-sm text-blue-600 hover:underline"
          >
            {loading ? "加载中..." : "刷新"}
          </button>
        </div>
        {stores.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            暂无门店数据。请先通过WiFi探针或外部订单导入数据。
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-4 py-3 text-left">门店</th>
                  <th className="px-4 py-3 text-right">WiFi总量</th>
                  <th className="px-4 py-3 text-right">WiFi已匹配</th>
                  <th className="px-4 py-3 text-right">外部订单</th>
                  <th className="px-4 py-3 text-right">外部已匹配</th>
                  <th className="px-4 py-3 text-right">综合识别率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {stores.map((st) => (
                  <tr key={st.store_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{st.store_name}</td>
                    <td className="px-4 py-3 text-right">{st.wifi_total}</td>
                    <td className="px-4 py-3 text-right">{st.wifi_matched}</td>
                    <td className="px-4 py-3 text-right">{st.external_total}</td>
                    <td className="px-4 py-3 text-right">{st.external_matched}</td>
                    <td className="px-4 py-3 text-right">
                      <span className={`font-semibold ${
                        st.overall_rate >= 60 ? "text-green-600" : st.overall_rate >= 30 ? "text-yellow-600" : "text-red-600"
                      }`}>
                        {st.overall_rate}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
