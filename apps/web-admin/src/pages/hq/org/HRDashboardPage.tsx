/**
 * 人力资源管理仪表板 — HR Dashboard
 * 考勤 + 请假 + 薪资 三合一管理视图
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetch } from '../../../api';

// ─── 类型定义 ───

interface AttendanceRecord {
  employee_id: string;
  employee_name: string;
  position: string;
  clock_in_time?: string;
  clock_out_time?: string;
  status: 'normal' | 'late' | 'absent' | 'pending';
  late_minutes?: number;
}

interface AttendanceSummary {
  total_expected: number;
  total_present: number;
  total_late: number;
  total_absent: number;
  records: AttendanceRecord[];
}

interface AttendanceAnomaly {
  id: string;
  employee_name: string;
  type: 'late' | 'early_leave' | 'absent';
  date: string;
  description: string;
}

interface LeaveRequest {
  id: string;
  employee_name: string;
  employee_id: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  days: number;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  reason: string;
  applied_at: string;
}

interface LeaveBalance {
  employee_id: string;
  employee_name: string;
  annual_leave: number;
  sick_leave: number;
}

interface PayrollRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  position: string;
  base_salary_fen: number;
  performance_fen: number;
  deductions_fen: number;
  gross_fen: number;
  net_fen: number;
  status: 'draft' | 'confirmed' | 'paid';
}

interface PayrollSummary {
  total_gross_fen: number;
  confirmed_count: number;
  pending_count: number;
  paid_count: number;
  unpaid_count: number;
  records: PayrollRecord[];
}

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function getTodayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function getMonthStr(): string {
  return new Date().toISOString().slice(0, 7);
}

// ─── 子组件：统计卡片 ───

function StatCard({
  icon, label, value, color,
}: {
  icon: string; label: string; value: number | string; color?: string;
}) {
  return (
    <div style={{
      background: '#1a2a33', borderRadius: 10, padding: '16px 20px',
      border: '1px solid #2a3a44', flex: 1, minWidth: 120,
    }}>
      <div style={{ fontSize: 22, marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || '#fff' }}>{value}</div>
      <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{label}</div>
    </div>
  );
}

// ─── 子组件：状态徽章 ───

function StatusBadge({ status }: { status: AttendanceRecord['status'] }) {
  const map: Record<AttendanceRecord['status'], { label: string; color: string; bg: string }> = {
    normal:  { label: '正常',   color: '#0F6E56', bg: '#0F6E5622' },
    late:    { label: '迟到',   color: '#BA7517', bg: '#BA751722' },
    absent:  { label: '缺勤',   color: '#FF4D4D', bg: '#FF4D4D22' },
    pending: { label: '待打卡', color: '#888',    bg: '#88888822' },
  };
  const s = map[status];
  return (
    <span style={{
      padding: '3px 10px', borderRadius: 12, fontSize: 12,
      background: s.bg, color: s.color,
    }}>
      {s.label}
    </span>
  );
}

// ─── 子组件：假期类型标签 ───

function LeaveTypeBadge({ type }: { type: string }) {
  const colorMap: Record<string, { color: string; bg: string }> = {
    年假: { color: '#3B82F6', bg: '#3B82F622' },
    病假: { color: '#BA7517', bg: '#BA751722' },
    事假: { color: '#888',    bg: '#88888822' },
    婚假: { color: '#EC4899', bg: '#EC489922' },
    产假: { color: '#8B5CF6', bg: '#8B5CF622' },
  };
  const s = colorMap[type] || { color: '#888', bg: '#88888822' };
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 10, fontSize: 12,
      background: s.bg, color: s.color,
    }}>
      {type}
    </span>
  );
}

// ─── 子组件：请假状态徽章 ───

function LeaveStatusBadge({ status }: { status: LeaveRequest['status'] }) {
  const map: Record<LeaveRequest['status'], { label: string; color: string; bg: string }> = {
    pending:   { label: '待审批', color: '#BA7517', bg: '#BA751722' },
    approved:  { label: '已批准', color: '#0F6E56', bg: '#0F6E5622' },
    rejected:  { label: '已拒绝', color: '#FF4D4D', bg: '#FF4D4D22' },
    cancelled: { label: '已取消', color: '#888',    bg: '#88888822' },
  };
  const s = map[status];
  return (
    <span style={{
      padding: '3px 10px', borderRadius: 12, fontSize: 12,
      background: s.bg, color: s.color,
    }}>
      {s.label}
    </span>
  );
}

// ─── 子组件：薪资状态徽章 ───

function PayrollStatusBadge({ status }: { status: PayrollRecord['status'] }) {
  const map: Record<PayrollRecord['status'], { label: string; color: string; bg: string }> = {
    draft:     { label: '待确认', color: '#BA7517', bg: '#BA751722' },
    confirmed: { label: '已确认', color: '#3B82F6', bg: '#3B82F622' },
    paid:      { label: '已发放', color: '#0F6E56', bg: '#0F6E5622' },
  };
  const s = map[status];
  return (
    <span style={{
      padding: '3px 10px', borderRadius: 12, fontSize: 12,
      background: s.bg, color: s.color,
    }}>
      {s.label}
    </span>
  );
}

// ─── Tab 1：今日考勤 ───

function AttendanceTab({
  storeId, date,
}: {
  storeId: string; date: string;
}) {
  const [summary, setSummary] = useState<AttendanceSummary | null>(null);
  const [anomalies, setAnomalies] = useState<AttendanceAnomaly[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const [sum, ano] = await Promise.all([
        txFetch<AttendanceSummary>(
          `/api/v1/attendance/daily?store_id=${encodeURIComponent(storeId)}&date=${date}`,
        ),
        txFetch<{ items: AttendanceAnomaly[] }>(
          `/api/v1/attendance/anomalies?store_id=${encodeURIComponent(storeId)}&start_date=${date.slice(0, 7)}-01&end_date=${date}`,
        ),
      ]);
      setSummary(sum);
      setAnomalies((ano.items || []).slice(0, 10));
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, [storeId, date]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载考勤数据...</div>;

  const records = summary?.records || [];

  return (
    <div>
      {/* 统计卡片行 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <StatCard icon="👤" label="应出勤人数" value={summary?.total_expected ?? '-'} />
        <StatCard icon="✅" label="已到岗" value={summary?.total_present ?? '-'} color="#0F6E56" />
        <StatCard icon="⏰" label="迟到" value={summary?.total_late ?? '-'} color="#BA7517" />
        <StatCard icon="❌" label="缺勤" value={summary?.total_absent ?? '-'} color="#FF4D4D" />
      </div>

      {/* 出勤状态表格 */}
      <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid #2a3a44', fontSize: 14, color: '#ccc', fontWeight: 600 }}>
          今日出勤状态
        </div>
        {records.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#888' }}>暂无数据</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#0d1e28' }}>
                {['员工姓名', '职位', '打卡时间', '状态', '迟到分钟'].map(h => (
                  <th key={h} style={{
                    padding: '10px 16px', textAlign: 'left',
                    color: '#888', fontSize: 12, fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.map(r => (
                <tr key={r.employee_id} style={{ borderBottom: '1px solid #2a3a4440' }}>
                  <td style={{ padding: '12px 16px', color: '#fff', fontWeight: 600 }}>{r.employee_name}</td>
                  <td style={{ padding: '12px 16px', color: '#aaa', fontSize: 13 }}>{r.position}</td>
                  <td style={{ padding: '12px 16px', color: '#ccc', fontSize: 13 }}>
                    {r.clock_in_time
                      ? <span>{r.clock_in_time}{r.clock_out_time ? ` → ${r.clock_out_time}` : ' (未退)'}</span>
                      : <span style={{ color: '#666' }}>—</span>
                    }
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <StatusBadge status={r.status} />
                  </td>
                  <td style={{ padding: '12px 16px', color: r.late_minutes ? '#BA7517' : '#888', fontSize: 13 }}>
                    {r.late_minutes ? `${r.late_minutes} 分钟` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 异常记录区 */}
      <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid #2a3a44', fontSize: 14, color: '#ccc', fontWeight: 600 }}>
          本月异常记录（近10条）
        </div>
        {anomalies.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#888' }}>本月暂无异常记录</div>
        ) : (
          <div style={{ padding: '8px 16px' }}>
            {anomalies.map((a, idx) => {
              const typeMap: Record<string, { label: string; color: string }> = {
                late:        { label: '迟到',   color: '#BA7517' },
                early_leave: { label: '早退',   color: '#8B5CF6' },
                absent:      { label: '缺勤',   color: '#FF4D4D' },
              };
              const t = typeMap[a.type] || { label: a.type, color: '#888' };
              return (
                <div key={a.id || idx} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 4px', borderBottom: '1px solid #2a3a4430',
                }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 8, fontSize: 11,
                    background: `${t.color}22`, color: t.color, whiteSpace: 'nowrap',
                  }}>{t.label}</span>
                  <span style={{ color: '#fff', fontWeight: 600, fontSize: 13 }}>{a.employee_name}</span>
                  <span style={{ color: '#888', fontSize: 12 }}>{a.date}</span>
                  <span style={{ color: '#aaa', fontSize: 12, flex: 1 }}>{a.description}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Tab 2：请假管理 ───

function LeaveTab({
  storeId,
}: {
  storeId: string;
}) {
  const [requests, setRequests] = useState<LeaveRequest[]>([]);
  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const [allReqs, balData] = await Promise.all([
        txFetch<{ items: LeaveRequest[] }>(
          `/api/v1/leave-requests?store_id=${encodeURIComponent(storeId)}&status=`,
        ),
        txFetch<{ items: LeaveBalance[] }>(
          `/api/v1/leave-requests/balance?employee_id=`,
        ),
      ]);
      setRequests(allReqs.items || []);
      setBalances(balData.items || []);
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) return <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载请假数据...</div>;

  const pending = requests.filter(r => r.status === 'pending');
  const others = requests.filter(r => r.status !== 'pending');

  // 本月请假汇总（按类型统计）
  const typeSummary: Record<string, number> = {};
  requests.forEach(r => {
    if (r.status === 'approved') {
      typeSummary[r.leave_type] = (typeSummary[r.leave_type] || 0) + r.days;
    }
  });

  return (
    <div>
      {/* 待审批区域 */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 14, color: '#ccc', fontWeight: 600, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          待审批请假
          {pending.length > 0 && (
            <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 12, background: '#BA751722', color: '#BA7517' }}>
              {pending.length} 条
            </span>
          )}
        </div>
        {pending.length === 0 ? (
          <div style={{ background: '#1a2a33', borderRadius: 10, padding: 24, textAlign: 'center', color: '#888' }}>
            暂无待审批请假
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {pending.map(req => (
              <div key={req.id} style={{
                background: '#1a2a33', borderRadius: 10, padding: '16px 20px',
                border: '1px solid #BA751744',
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                      <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>{req.employee_name}</span>
                      <LeaveTypeBadge type={req.leave_type} />
                      <span style={{ color: '#ccc', fontSize: 13 }}>
                        {req.start_date} 至 {req.end_date.slice(5)}
                      </span>
                      <span style={{ color: '#BA7517', fontWeight: 600, fontSize: 13 }}>({req.days}天)</span>
                    </div>
                    <div style={{ color: '#888', fontSize: 12 }}>
                      申请时间：{new Date(req.applied_at).toLocaleString('zh-CN')}
                      &nbsp;&nbsp;原因：{req.reason}
                    </div>
                  </div>
                  <button style={{
                    padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
                    background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12,
                    marginLeft: 16,
                  }}>
                    查看
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 本月请假汇总 */}
      <div style={{ background: '#1a2a33', borderRadius: 12, padding: '16px 20px', marginBottom: 20 }}>
        <div style={{ fontSize: 14, color: '#ccc', fontWeight: 600, marginBottom: 14 }}>本月请假汇总</div>
        {Object.keys(typeSummary).length === 0 ? (
          <div style={{ color: '#888', fontSize: 13 }}>本月暂无已批准请假记录</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
            {Object.entries(typeSummary).map(([type, days]) => (
              <div key={type} style={{
                background: '#0d1e28', borderRadius: 8, padding: '10px 16px',
                border: '1px solid #2a3a44',
              }}>
                <LeaveTypeBadge type={type} />
                <div style={{ color: '#fff', fontSize: 20, fontWeight: 700, marginTop: 6 }}>{days}</div>
                <div style={{ color: '#888', fontSize: 12 }}>天</div>
              </div>
            ))}
            <div style={{
              background: '#0d1e28', borderRadius: 8, padding: '10px 16px',
              border: '1px solid #2a3a44',
            }}>
              <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 12, background: '#ffffff11', color: '#ccc' }}>总计</span>
              <div style={{ color: '#fff', fontSize: 20, fontWeight: 700, marginTop: 6 }}>
                {requests.filter(r => r.status === 'approved').length}
              </div>
              <div style={{ color: '#888', fontSize: 12 }}>人次</div>
            </div>
          </div>
        )}
      </div>

      {/* 已审批 / 其他记录 */}
      {others.length > 0 && (
        <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid #2a3a44', fontSize: 14, color: '#ccc', fontWeight: 600 }}>
            其他请假记录
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#0d1e28' }}>
                {['员工', '类型', '起止日期', '天数', '原因', '状态'].map(h => (
                  <th key={h} style={{ padding: '10px 16px', textAlign: 'left', color: '#888', fontSize: 12, fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {others.map(req => (
                <tr key={req.id} style={{ borderBottom: '1px solid #2a3a4440' }}>
                  <td style={{ padding: '12px 16px', color: '#fff', fontWeight: 600 }}>{req.employee_name}</td>
                  <td style={{ padding: '12px 16px' }}><LeaveTypeBadge type={req.leave_type} /></td>
                  <td style={{ padding: '12px 16px', color: '#aaa', fontSize: 13 }}>{req.start_date} ~ {req.end_date}</td>
                  <td style={{ padding: '12px 16px', color: '#ccc', fontSize: 13 }}>{req.days}天</td>
                  <td style={{ padding: '12px 16px', color: '#888', fontSize: 12 }}>{req.reason}</td>
                  <td style={{ padding: '12px 16px' }}><LeaveStatusBadge status={req.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 假期余额表 */}
      <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid #2a3a44', fontSize: 14, color: '#ccc', fontWeight: 600 }}>
          假期余额（按员工）
        </div>
        {balances.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#888' }}>暂无余额数据</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#0d1e28' }}>
                {['员工姓名', '年假余额 (天)', '病假余额 (天)'].map(h => (
                  <th key={h} style={{ padding: '10px 16px', textAlign: 'left', color: '#888', fontSize: 12, fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {balances.map(b => (
                <tr key={b.employee_id} style={{ borderBottom: '1px solid #2a3a4440' }}>
                  <td style={{ padding: '12px 16px', color: '#fff', fontWeight: 600 }}>{b.employee_name}</td>
                  <td style={{ padding: '12px 16px', color: '#3B82F6', fontWeight: 600 }}>{b.annual_leave}</td>
                  <td style={{ padding: '12px 16px', color: '#BA7517', fontWeight: 600 }}>{b.sick_leave}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ─── Tab 3：薪资管理 ───

function PayrollTab({
  storeId, month,
}: {
  storeId: string; month: string;
}) {
  const [payroll, setPayroll] = useState<PayrollSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [batchLoading, setBatchLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<Record<string, string>>({});

  const fetchData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const data = await txFetch<PayrollSummary>(
        `/api/v1/payroll/store/${encodeURIComponent(storeId)}/${encodeURIComponent(month)}`,
      );
      setPayroll(data);
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, [storeId, month]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBatchCompute = async () => {
    if (!storeId) return;
    setBatchLoading(true);
    try {
      await txFetch(`/api/v1/payroll/batch/${encodeURIComponent(storeId)}`, {
        method: 'POST',
        body: JSON.stringify({ month }),
      });
      await fetchData();
    } catch {
      /* 忽略错误 */
    } finally {
      setBatchLoading(false);
    }
  };

  const handleConfirm = async (recordId: string) => {
    setActionLoading(prev => ({ ...prev, [recordId]: 'confirm' }));
    try {
      await txFetch(`/api/v1/payroll/${encodeURIComponent(recordId)}/confirm`, { method: 'POST' });
      await fetchData();
    } finally {
      setActionLoading(prev => { const n = { ...prev }; delete n[recordId]; return n; });
    }
  };

  const handlePay = async (recordId: string) => {
    setActionLoading(prev => ({ ...prev, [recordId]: 'pay' }));
    try {
      await txFetch(`/api/v1/payroll/${encodeURIComponent(recordId)}/pay`, { method: 'POST' });
      await fetchData();
    } finally {
      setActionLoading(prev => { const n = { ...prev }; delete n[recordId]; return n; });
    }
  };

  if (loading) return <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载薪资数据...</div>;

  const records = payroll?.records || [];

  return (
    <div>
      {/* 月度薪资汇总卡片 */}
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: '20px 24px',
        border: '1px solid #2a3a44', marginBottom: 20,
      }}>
        <div style={{ fontSize: 14, color: '#888', marginBottom: 4 }}>{month} 月度薪资汇总</div>
        <div style={{ fontSize: 32, fontWeight: 700, color: '#fff', marginBottom: 16 }}>
          ¥{fenToYuan(payroll?.total_gross_fen ?? 0)}
          <span style={{ fontSize: 13, color: '#888', fontWeight: 400, marginLeft: 8 }}>本月应发总额</span>
        </div>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#3B82F6', display: 'inline-block' }} />
            <span style={{ color: '#888', fontSize: 13 }}>已确认 <strong style={{ color: '#3B82F6' }}>{payroll?.confirmed_count ?? 0}</strong> 人</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#BA7517', display: 'inline-block' }} />
            <span style={{ color: '#888', fontSize: 13 }}>待确认 <strong style={{ color: '#BA7517' }}>{payroll?.pending_count ?? 0}</strong> 人</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#0F6E56', display: 'inline-block' }} />
            <span style={{ color: '#888', fontSize: 13 }}>已发放 <strong style={{ color: '#0F6E56' }}>{payroll?.paid_count ?? 0}</strong> 人</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#888', display: 'inline-block' }} />
            <span style={{ color: '#888', fontSize: 13 }}>待发放 <strong style={{ color: '#ccc' }}>{payroll?.unpaid_count ?? 0}</strong> 人</span>
          </div>
        </div>
      </div>

      {/* 薪资单列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
        {records.length === 0 ? (
          <div style={{ background: '#1a2a33', borderRadius: 10, padding: 32, textAlign: 'center', color: '#888' }}>
            暂无薪资记录，可点击下方按钮批量计算
          </div>
        ) : records.map(rec => (
          <div key={rec.id} style={{
            background: '#1a2a33', borderRadius: 10, padding: '16px 20px',
            border: '1px solid #2a3a44',
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                  <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>{rec.employee_name}</span>
                  <span style={{ color: '#888', fontSize: 13 }}>{rec.position}</span>
                  <span style={{ color: '#888', fontSize: 12 }}>应发：</span>
                  <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>¥{fenToYuan(rec.gross_fen)}</span>
                  <span style={{ color: '#888', fontSize: 12 }}>实发：</span>
                  <span style={{ color: '#0F6E56', fontWeight: 700, fontSize: 15 }}>¥{fenToYuan(rec.net_fen)}</span>
                </div>
                <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>
                  基本工资：¥{fenToYuan(rec.base_salary_fen)}
                  &nbsp;+&nbsp;绩效：¥{fenToYuan(rec.performance_fen)}
                  &nbsp;-&nbsp;扣款：¥{fenToYuan(rec.deductions_fen)}
                </div>
                <PayrollStatusBadge status={rec.status} />
              </div>
              <div style={{ display: 'flex', gap: 8, marginLeft: 16, alignItems: 'center' }}>
                {rec.status === 'draft' && (
                  <button
                    onClick={() => handleConfirm(rec.id)}
                    disabled={!!actionLoading[rec.id]}
                    style={{
                      padding: '6px 14px', borderRadius: 6,
                      border: '1px solid #3B82F644', background: '#3B82F622',
                      color: '#3B82F6', cursor: 'pointer', fontSize: 12,
                      opacity: actionLoading[rec.id] ? 0.5 : 1,
                    }}
                  >
                    {actionLoading[rec.id] === 'confirm' ? '处理中...' : '确认薪资'}
                  </button>
                )}
                {(rec.status === 'draft' || rec.status === 'confirmed') && (
                  <button
                    onClick={() => handlePay(rec.id)}
                    disabled={!!actionLoading[rec.id]}
                    style={{
                      padding: '6px 14px', borderRadius: 6,
                      border: '1px solid #0F6E5644', background: '#0F6E5622',
                      color: '#0F6E56', cursor: 'pointer', fontSize: 12,
                      opacity: actionLoading[rec.id] ? 0.5 : 1,
                    }}
                  >
                    {actionLoading[rec.id] === 'pay' ? '处理中...' : '标记已发'}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* AI 批量计算按钮 */}
      <div style={{ textAlign: 'center', paddingTop: 8 }}>
        <button
          onClick={handleBatchCompute}
          disabled={batchLoading}
          style={{
            padding: '12px 32px', borderRadius: 8,
            border: '1px solid #3B82F644',
            background: batchLoading ? '#1a2a33' : '#3B82F622',
            color: batchLoading ? '#888' : '#3B82F6',
            cursor: batchLoading ? 'not-allowed' : 'pointer',
            fontSize: 15, fontWeight: 600,
            transition: 'all 0.2s',
          }}
        >
          {batchLoading ? '🤖 AI 计算中...' : `🤖 AI批量计算本月薪资`}
        </button>
      </div>
    </div>
  );
}

// ─── 主页面 ───

export function HRDashboardPage() {
  const [activeTab, setActiveTab] = useState<'attendance' | 'leave' | 'payroll'>('attendance');
  const [storeId, setStoreId] = useState('store_001');
  const [date, setDate] = useState(getTodayStr());
  const [month, setMonth] = useState(getMonthStr());
  const [refreshKey, setRefreshKey] = useState(0);

  const tabs: { id: typeof activeTab; label: string; icon: string }[] = [
    { id: 'attendance', label: '今日考勤', icon: '📅' },
    { id: 'leave',      label: '请假管理', icon: '🏖️' },
    { id: 'payroll',    label: '薪资管理', icon: '💰' },
  ];

  const STORE_OPTIONS = [
    { value: 'store_001', label: '尝在一起·芙蓉路店' },
    { value: 'store_002', label: '尝在一起·五一广场店' },
    { value: 'store_003', label: '最黔线·解放西店' },
  ];

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>👥 人力资源管理</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            考勤 · 请假 · 薪资 一体化管理
          </p>
        </div>

        {/* 控制区 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* 门店选择 */}
          <select
            value={storeId}
            onChange={e => setStoreId(e.target.value)}
            style={{
              padding: '6px 12px', borderRadius: 6, border: '1px solid #2a3a44',
              background: '#1a2a33', color: '#ccc', fontSize: 13, outline: 'none', cursor: 'pointer',
            }}
          >
            {STORE_OPTIONS.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>

          {/* 月份选择 */}
          <input
            type="month"
            value={month}
            onChange={e => setMonth(e.target.value)}
            style={{
              padding: '6px 10px', borderRadius: 6, border: '1px solid #2a3a44',
              background: '#1a2a33', color: '#ccc', fontSize: 13, outline: 'none',
              colorScheme: 'dark',
            }}
          />

          {/* 日期选择（仅考勤 Tab 有意义） */}
          {activeTab === 'attendance' && (
            <input
              type="date"
              value={date}
              onChange={e => setDate(e.target.value)}
              style={{
                padding: '6px 10px', borderRadius: 6, border: '1px solid #2a3a44',
                background: '#1a2a33', color: '#ccc', fontSize: 13, outline: 'none',
                colorScheme: 'dark',
              }}
            />
          )}

          {/* 刷新按钮 */}
          <button
            onClick={() => setRefreshKey(k => k + 1)}
            style={{
              padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
              background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13,
            }}
          >
            ↻ 刷新
          </button>
        </div>
      </div>

      {/* Tab 切换栏 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: '#1a2a33', borderRadius: 10, padding: 4, width: 'fit-content' }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '8px 20px', borderRadius: 8, border: 'none', cursor: 'pointer',
              fontSize: 14, fontWeight: activeTab === tab.id ? 600 : 400,
              background: activeTab === tab.id ? '#0d1e28' : 'transparent',
              color: activeTab === tab.id ? '#fff' : '#888',
              transition: 'all 0.15s',
            }}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 内容区 */}
      <div key={`${activeTab}-${storeId}-${month}-${refreshKey}`}>
        {activeTab === 'attendance' && (
          <AttendanceTab storeId={storeId} date={date} />
        )}
        {activeTab === 'leave' && (
          <LeaveTab storeId={storeId} />
        )}
        {activeTab === 'payroll' && (
          <PayrollTab storeId={storeId} month={month} />
        )}
      </div>
    </div>
  );
}
