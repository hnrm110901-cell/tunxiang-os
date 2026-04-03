/**
 * OrgPage — 组织管理（真实 API 版）
 * Section 1：员工总览统计
 * Section 2：员工列表（筛选 + 分页 + 展开详情）
 * Section 3：本周排班概览（7天横向日历）
 * Section 4：本月绩效排行 TOP10
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetch } from '../api';

// ─── 类型定义 ───────────────────────────────────────────────

interface Employee {
  id: string;
  name: string;
  phone?: string;
  position: string;
  department?: string;
  store_id: string;
  store_name?: string;
  status: 'active' | 'probation' | 'resigned';
  hire_date: string;
  today_attendance?: 'checked_in' | 'late' | 'absent' | 'not_yet';
  salary_grade?: string;
  attendance_rate_30d?: number; // 0-1
}

interface EmployeeListResp {
  items: Employee[];
  total: number;
}

interface AttendanceRecord {
  emp_id: string;
  emp_name: string;
  status: 'checked_in' | 'late' | 'absent' | 'not_yet';
  check_in_time?: string;
}

interface AttendanceResp {
  records: AttendanceRecord[];
}

interface ScheduleShift {
  date: string;       // YYYY-MM-DD
  shift: 'morning' | 'midday' | 'evening';
  count: number;
  emp_names?: string[];
}

interface ScheduleResp {
  schedule: ScheduleShift[];
}

interface PerformanceRank {
  emp_id: string;
  emp_name: string;
  store_name?: string;
  score: number;           // 综合得分 0-100
  sales_fen?: number;      // 销售额（分）
  attendance_rate?: number; // 出勤率 0-1
  customer_score?: number; // 客评分 0-5
}

// ─── 工具函数 ───────────────────────────────────────────────

function calcTenureMonths(hireDate: string): number {
  const hire = new Date(hireDate);
  const now = new Date();
  return (now.getFullYear() - hire.getFullYear()) * 12 + (now.getMonth() - hire.getMonth());
}

function formatTenure(months: number): string {
  if (months < 1) return '不足1个月';
  if (months < 12) return `${months} 个月`;
  const y = Math.floor(months / 12);
  const m = months % 12;
  return m > 0 ? `${y} 年 ${m} 个月` : `${y} 年`;
}

function isThisMonth(dateStr: string): boolean {
  const d = new Date(dateStr);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
}

function getWeekDays(): string[] {
  const today = new Date();
  const day = today.getDay(); // 0=日
  const monday = new Date(today);
  monday.setDate(today.getDate() - (day === 0 ? 6 : day - 1));
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return d.toISOString().split('T')[0];
  });
}

function fen2yuan(fen: number): string {
  return `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;
}

const CN_WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

// ─── 样式常量 ───────────────────────────────────────────────

const S = {
  container: {
    backgroundColor: '#0B1A20',
    color: '#E0E0E0',
    minHeight: '100vh',
    padding: '24px 32px',
    fontFamily: 'system-ui, -apple-system, "PingFang SC", sans-serif',
  } as React.CSSProperties,

  header: {
    fontSize: '24px',
    fontWeight: 700,
    color: '#FFFFFF',
    marginBottom: '4px',
  } as React.CSSProperties,

  subtitle: {
    fontSize: '13px',
    color: '#6B8A99',
    marginBottom: '28px',
  } as React.CSSProperties,

  sectionTitle: {
    fontSize: '15px',
    fontWeight: 600,
    color: '#4FC3F7',
    marginBottom: '14px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  } as React.CSSProperties,

  card: {
    backgroundColor: '#112B36',
    borderRadius: '12px',
    padding: '20px',
    border: '1px solid #1E3A47',
    marginBottom: '20px',
  } as React.CSSProperties,

  statCard: {
    backgroundColor: '#112B36',
    borderRadius: '10px',
    padding: '16px 20px',
    border: '1px solid #1E3A47',
    flex: 1,
  } as React.CSSProperties,

  statValue: {
    fontSize: '28px',
    fontWeight: 700,
    color: '#FFFFFF',
    lineHeight: 1.2,
  } as React.CSSProperties,

  statLabel: {
    fontSize: '12px',
    color: '#6B8A99',
    marginTop: '4px',
  } as React.CSSProperties,

  filterBar: {
    display: 'flex',
    gap: '10px',
    marginBottom: '14px',
    flexWrap: 'wrap' as const,
    alignItems: 'center',
  } as React.CSSProperties,

  select: {
    backgroundColor: '#0B1A20',
    border: '1px solid #2A4A5A',
    borderRadius: '6px',
    color: '#E0E0E0',
    padding: '6px 10px',
    fontSize: '13px',
    cursor: 'pointer',
    outline: 'none',
  } as React.CSSProperties,

  empRow: {
    borderBottom: '1px solid #1A3040',
    padding: '10px 0',
    cursor: 'pointer',
    transition: 'background 0.15s',
  } as React.CSSProperties,

  empRowExpanded: {
    borderBottom: '1px solid #1A3040',
    padding: '10px 0',
    backgroundColor: '#0D2230',
    cursor: 'pointer',
  } as React.CSSProperties,

  badge: (color: string, bg: string) => ({
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: '10px',
    fontSize: '11px',
    fontWeight: 500,
    color,
    backgroundColor: bg,
    whiteSpace: 'nowrap' as const,
  }),

  pagination: {
    display: 'flex',
    gap: '6px',
    justifyContent: 'flex-end',
    marginTop: '14px',
    alignItems: 'center',
  } as React.CSSProperties,

  pageBtn: (active: boolean) => ({
    padding: '4px 10px',
    borderRadius: '5px',
    border: active ? '1px solid #4FC3F7' : '1px solid #2A4A5A',
    backgroundColor: active ? '#4FC3F7' : '#0B1A20',
    color: active ? '#0B1A20' : '#9BB5C4',
    cursor: 'pointer',
    fontSize: '13px',
  }),

  weekTable: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: '13px',
  } as React.CSSProperties,

  weekTh: {
    textAlign: 'center' as const,
    padding: '8px 4px',
    color: '#6B8A99',
    fontWeight: 500,
    borderBottom: '1px solid #1E3A47',
    width: '14.28%',
  } as React.CSSProperties,

  weekTd: {
    textAlign: 'center' as const,
    padding: '8px 4px',
    borderBottom: '1px solid #1A3040',
    verticalAlign: 'top' as const,
  } as React.CSSProperties,

  shiftBubble: (color: string) => ({
    display: 'inline-block',
    backgroundColor: color,
    color: '#fff',
    borderRadius: '12px',
    padding: '2px 8px',
    fontSize: '11px',
    margin: '2px',
    fontWeight: 500,
  }),

  rankRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '10px 0',
    borderBottom: '1px solid #1A3040',
  } as React.CSSProperties,

  rankNum: (rank: number) => ({
    width: '26px',
    height: '26px',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '12px',
    fontWeight: 700,
    flexShrink: 0,
    backgroundColor: rank === 1 ? '#D4A010' : rank === 2 ? '#8899A6' : rank === 3 ? '#A0522D' : '#1E3A47',
    color: rank <= 3 ? '#fff' : '#6B8A99',
  }),

  scoreBar: (score: number) => ({
    height: '6px',
    borderRadius: '3px',
    backgroundColor: '#1E3A47',
    flex: 1,
    overflow: 'hidden' as const,
    position: 'relative' as const,
  }),

  errorBanner: {
    backgroundColor: '#2A1010',
    border: '1px solid #6B2020',
    borderRadius: '8px',
    padding: '10px 14px',
    marginBottom: '14px',
    color: '#FF8080',
    fontSize: '13px',
  } as React.CSSProperties,

  skeletonLine: (w: string, h = '12px') => ({
    height: h,
    width: w,
    backgroundColor: '#1A3040',
    borderRadius: '4px',
  }),
};

// ─── 子组件 ─────────────────────────────────────────────────

function StatusBadge({ status }: { status: Employee['status'] }) {
  const map = {
    active:    { label: '在职', color: '#52C97A', bg: '#0D2A1A' },
    probation: { label: '试用期', color: '#4FC3F7', bg: '#0D2030' },
    resigned:  { label: '离职', color: '#6B8A99', bg: '#1A2A33' },
  };
  const { label, color, bg } = map[status] ?? map.resigned;
  return <span style={S.badge(color, bg)}>{label}</span>;
}

function AttendanceBadge({ status }: { status?: Employee['today_attendance'] }) {
  if (!status) return null;
  const map = {
    checked_in: { label: '已打卡', color: '#52C97A', bg: '#0D2A1A' },
    late:       { label: '迟到',   color: '#FFB347', bg: '#2A1A00' },
    absent:     { label: '缺勤',   color: '#FF6B6B', bg: '#2A1010' },
    not_yet:    { label: '未打卡', color: '#6B8A99', bg: '#1A2A33' },
  };
  const conf = map[status] ?? map.not_yet;
  return <span style={S.badge(conf.color, conf.bg)}>{conf.label}</span>;
}

function ExpandedDetail({ emp }: { emp: Employee }) {
  return (
    <div style={{
      backgroundColor: '#0D2230',
      borderRadius: '8px',
      padding: '14px 16px',
      margin: '8px 0 4px',
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
      gap: '10px',
      fontSize: '13px',
    }}>
      <div>
        <div style={{ color: '#6B8A99', marginBottom: '4px' }}>联系电话</div>
        <div style={{ color: '#E0E0E0' }}>{emp.phone || '未登记'}</div>
      </div>
      <div>
        <div style={{ color: '#6B8A99', marginBottom: '4px' }}>薪资等级</div>
        <div style={{ color: '#E0E0E0' }}>{emp.salary_grade || '未设置'}</div>
      </div>
      <div>
        <div style={{ color: '#6B8A99', marginBottom: '4px' }}>近30天出勤率</div>
        <div style={{
          color: emp.attendance_rate_30d != null
            ? emp.attendance_rate_30d >= 0.9 ? '#52C97A'
            : emp.attendance_rate_30d >= 0.7 ? '#FFB347' : '#FF6B6B'
            : '#6B8A99',
          fontWeight: 600,
        }}>
          {emp.attendance_rate_30d != null
            ? `${(emp.attendance_rate_30d * 100).toFixed(0)}%`
            : '--'}
        </div>
      </div>
      <div>
        <div style={{ color: '#6B8A99', marginBottom: '4px' }}>所在门店</div>
        <div style={{ color: '#E0E0E0' }}>{emp.store_name || emp.store_id}</div>
      </div>
    </div>
  );
}

function SkeletonRows({ count = 5 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} style={{ padding: '12px 0', borderBottom: '1px solid #1A3040', display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={S.skeletonLine('30%')} />
          <div style={S.skeletonLine('20%')} />
          <div style={S.skeletonLine('15%')} />
          <div style={{ flex: 1 }} />
          <div style={S.skeletonLine('60px')} />
        </div>
      ))}
    </>
  );
}

// ─── 主组件 ─────────────────────────────────────────────────

export function OrgPage() {
  // ── 员工列表状态 ──
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [empTotal, setEmpTotal] = useState(0);
  const [empLoading, setEmpLoading] = useState(true);
  const [empError, setEmpError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // ── 筛选状态 ──
  const [filterStore, setFilterStore] = useState('');
  const [filterStatus, setFilterStatus] = useState<Employee['status'] | ''>('');
  const [filterPosition, setFilterPosition] = useState('');

  // ── 展开行 ──
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // ── 考勤状态（当天） ──
  const [attendanceMap, setAttendanceMap] = useState<Record<string, AttendanceRecord>>({});

  // ── 排班状态 ──
  const [scheduleData, setScheduleData] = useState<ScheduleShift[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(true);

  // ── 绩效排行 ──
  const [perfRanking, setPerfRanking] = useState<PerformanceRank[]>([]);
  const [perfLoading, setPerfLoading] = useState(true);

  // ── 门店列表（从员工数据中提取） ──
  const [storeOptions, setStoreOptions] = useState<Array<{ id: string; name: string }>>([]);

  // ── 统计数据（从员工列表计算） ──
  const stats = {
    total: empTotal,
    newThisMonth: employees.filter((e) => isThisMonth(e.hire_date)).length,
    resigned: employees.filter((e) => e.status === 'resigned').length,
    avgTenureMonths: employees.length > 0
      ? Math.round(employees.reduce((s, e) => s + calcTenureMonths(e.hire_date), 0) / employees.length)
      : 0,
  };

  // ── 拉员工列表 ──
  const fetchEmployees = useCallback(() => {
    setEmpLoading(true);
    setEmpError(null);

    const params = new URLSearchParams({
      page: String(page),
      size: String(PAGE_SIZE),
    });
    if (filterStore) params.set('store_id', filterStore);
    if (filterStatus) params.set('status', filterStatus);
    if (filterPosition) params.set('role', filterPosition);

    // 使用 store_id 兜底：当未选门店时传第一个门店或空
    const storeId = filterStore || (storeOptions[0]?.id ?? 'all');
    if (!filterStore) params.set('store_id', storeId);

    txFetch<EmployeeListResp>(`/api/v1/org/employees?${params}`)
      .then((data) => {
        setEmployees(data.items ?? []);
        setEmpTotal(data.total ?? 0);
        // 提取门店选项
        const stores: Record<string, string> = {};
        (data.items ?? []).forEach((e) => {
          if (e.store_id && e.store_name) stores[e.store_id] = e.store_name;
        });
        setStoreOptions(Object.entries(stores).map(([id, name]) => ({ id, name })));
      })
      .catch((err: unknown) => {
        setEmpError(err instanceof Error ? err.message : 'API Error');
      })
      .finally(() => setEmpLoading(false));
  }, [page, filterStore, filterStatus, filterPosition, storeOptions]);

  // ── 拉当天考勤 ──
  const fetchAttendance = useCallback(() => {
    const today = new Date().toISOString().split('T')[0];
    const storeId = filterStore || (storeOptions[0]?.id ?? '');
    if (!storeId) return;

    txFetch<AttendanceResp>(`/api/v1/org/attendance?store_id=${storeId}&date=${today}`)
      .then((data) => {
        const map: Record<string, AttendanceRecord> = {};
        (data.records ?? []).forEach((r) => { map[r.emp_id] = r; });
        setAttendanceMap(map);
      })
      .catch(() => {/* 考勤失败不阻断主流程 */});
  }, [filterStore, storeOptions]);

  // ── 拉本周排班 ──
  const fetchSchedule = useCallback(() => {
    setScheduleLoading(true);
    const weekDays = getWeekDays();
    const week = weekDays[0]; // 本周一
    const storeId = filterStore || (storeOptions[0]?.id ?? '');
    if (!storeId) {
      setScheduleLoading(false);
      return;
    }

    txFetch<ScheduleResp>(`/api/v1/org/schedule/?store_id=${storeId}&week=${week}`)
      .then((data) => setScheduleData(data.schedule ?? []))
      .catch(() => setScheduleData([]))
      .finally(() => setScheduleLoading(false));
  }, [filterStore, storeOptions]);

  // ── 拉绩效排行（取本月，遍历员工前10） ──
  const fetchPerformance = useCallback(() => {
    setPerfLoading(true);
    const period = new Date().toISOString().slice(0, 7); // YYYY-MM
    const storeId = filterStore || (storeOptions[0]?.id ?? '');

    // 用 compute 接口触发计算，再用 labor-cost/ranking 取排行
    txFetch<{ rankings: PerformanceRank[] }>(`/api/v1/org/labor-cost/ranking${storeId ? `?brand_id=${storeId}` : ''}`)
      .then((data) => setPerfRanking((data.rankings ?? []).slice(0, 10)))
      .catch(() => setPerfRanking([]))
      .finally(() => setPerfLoading(false));
    void period; // 待后端绩效接口支持 period 参数后使用
  }, [filterStore, storeOptions]);

  // ── 初始化 + 筛选变化时重新拉取 ──
  useEffect(() => { fetchEmployees(); }, [page, filterStore, filterStatus, filterPosition]);

  useEffect(() => {
    fetchAttendance();
    fetchSchedule();
    fetchPerformance();
  }, [filterStore, storeOptions.length]);

  // 重置分页
  useEffect(() => { setPage(1); }, [filterStore, filterStatus, filterPosition]);

  const totalPages = Math.ceil(empTotal / PAGE_SIZE);

  // ── 职位选项（从当前员工数据提取） ──
  const positionOptions = Array.from(new Set(employees.map((e) => e.position).filter(Boolean)));

  // ── 本周日期 ──
  const weekDays = getWeekDays();

  // ── 排班数据按日期+班次索引 ──
  const scheduleIndex: Record<string, Record<string, ScheduleShift>> = {};
  scheduleData.forEach((s) => {
    if (!scheduleIndex[s.date]) scheduleIndex[s.date] = {};
    scheduleIndex[s.date][s.shift] = s;
  });

  const SHIFT_CONFIG = [
    { key: 'morning', label: '早班', color: '#2563EB' },
    { key: 'midday',  label: '中班', color: '#0F6E56' },
    { key: 'evening', label: '晚班', color: '#7C3AED' },
  ];

  // ── 绩效排行最高分（用于进度条） ──
  const maxScore = perfRanking.length > 0 ? Math.max(...perfRanking.map((r) => r.score)) : 100;

  return (
    <div style={S.container}>
      {/* 页面标题 */}
      <h1 style={S.header}>组织管理</h1>
      <p style={S.subtitle}>员工花名册 · 排班概览 · 绩效排行</p>

      {/* ═══════════════════════════════════════════════
          Section 1：员工总览统计
      ═══════════════════════════════════════════════ */}
      <div style={{ display: 'flex', gap: '16px', marginBottom: '20px', flexWrap: 'wrap' }}>
        <div style={S.statCard}>
          <div style={S.statValue}>{empLoading ? '--' : empTotal}</div>
          <div style={S.statLabel}>在职员工总数</div>
        </div>
        <div style={S.statCard}>
          <div style={{ ...S.statValue, color: '#52C97A' }}>
            {empLoading ? '--' : `+${stats.newThisMonth}`}
          </div>
          <div style={S.statLabel}>本月新入职</div>
        </div>
        <div style={S.statCard}>
          <div style={{ ...S.statValue, color: stats.resigned > 0 ? '#FF6B6B' : '#6B8A99' }}>
            {empLoading ? '--' : stats.resigned}
          </div>
          <div style={S.statLabel}>本月离职</div>
        </div>
        <div style={S.statCard}>
          <div style={{ ...S.statValue, color: '#4FC3F7' }}>
            {empLoading ? '--' : formatTenure(stats.avgTenureMonths)}
          </div>
          <div style={S.statLabel}>平均工龄</div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════
          Section 2：员工列表
      ═══════════════════════════════════════════════ */}
      <div style={S.card}>
        <div style={S.sectionTitle}>
          <span style={{ fontSize: '18px' }}>👥</span>
          员工花名册
          {!empLoading && (
            <span style={{ fontSize: '12px', color: '#6B8A99', fontWeight: 400, marginLeft: 'auto' }}>
              共 {empTotal} 人
            </span>
          )}
        </div>

        {/* 筛选栏 */}
        <div style={S.filterBar}>
          <select
            style={S.select}
            value={filterStore}
            onChange={(e) => setFilterStore(e.target.value)}
          >
            <option value="">全部门店</option>
            {storeOptions.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>

          <select
            style={S.select}
            value={filterPosition}
            onChange={(e) => setFilterPosition(e.target.value)}
          >
            <option value="">全部职位</option>
            {positionOptions.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          <select
            style={S.select}
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as Employee['status'] | '')}
          >
            <option value="">全部状态</option>
            <option value="active">在职</option>
            <option value="probation">试用期</option>
            <option value="resigned">离职</option>
          </select>
        </div>

        {/* 错误提示 */}
        {empError && (
          <div style={S.errorBanner}>
            数据加载失败：{empError}
          </div>
        )}

        {/* 表头 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1.5fr 1fr 1fr 80px 80px',
          gap: '8px',
          padding: '6px 0 8px',
          borderBottom: '1px solid #1E3A47',
          fontSize: '12px',
          color: '#6B8A99',
        }}>
          <span>姓名 / 职位</span>
          <span>入职日期 / 工龄</span>
          <span>门店</span>
          <span style={{ textAlign: 'center' }}>状态</span>
          <span style={{ textAlign: 'center' }}>今日出勤</span>
        </div>

        {/* 员工行 */}
        {empLoading ? (
          <SkeletonRows count={8} />
        ) : employees.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#6B8A99', padding: '40px 0', fontSize: '14px' }}>
            {empError ? '加载失败' : '暂无员工数据'}
          </div>
        ) : (
          employees.map((emp) => {
            const isExpanded = expandedId === emp.id;
            const attRecord = attendanceMap[emp.id];
            const attendanceStatus = attRecord?.status ?? emp.today_attendance;
            const tenureMonths = calcTenureMonths(emp.hire_date);

            return (
              <div key={emp.id}>
                <div
                  style={isExpanded ? S.empRowExpanded : S.empRow}
                  onClick={() => setExpandedId(isExpanded ? null : emp.id)}
                >
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1.5fr 1fr 1fr 80px 80px',
                    gap: '8px',
                    alignItems: 'center',
                    fontSize: '13px',
                  }}>
                    {/* 姓名 + 职位 */}
                    <div>
                      <div style={{ color: '#FFFFFF', fontWeight: 500 }}>{emp.name}</div>
                      <div style={{ color: '#6B8A99', fontSize: '12px', marginTop: '2px' }}>
                        {emp.position}{emp.department ? ` · ${emp.department}` : ''}
                      </div>
                    </div>

                    {/* 入职日期 + 工龄 */}
                    <div>
                      <div style={{ color: '#B0C4CE' }}>{emp.hire_date}</div>
                      <div style={{ color: '#6B8A99', fontSize: '12px', marginTop: '2px' }}>
                        {formatTenure(tenureMonths)}
                      </div>
                    </div>

                    {/* 门店 */}
                    <div style={{ color: '#B0C4CE' }}>
                      {emp.store_name || emp.store_id}
                    </div>

                    {/* 状态徽章 */}
                    <div style={{ textAlign: 'center' }}>
                      <StatusBadge status={emp.status} />
                    </div>

                    {/* 今日出勤 */}
                    <div style={{ textAlign: 'center' }}>
                      <AttendanceBadge status={attendanceStatus} />
                    </div>
                  </div>
                </div>

                {/* 展开详情 */}
                {isExpanded && <ExpandedDetail emp={emp} />}
              </div>
            );
          })
        )}

        {/* 分页 */}
        {!empLoading && totalPages > 1 && (
          <div style={S.pagination}>
            <span style={{ color: '#6B8A99', fontSize: '12px', marginRight: '8px' }}>
              第 {page} / {totalPages} 页
            </span>
            <button
              style={S.pageBtn(false)}
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const p = Math.max(1, Math.min(page - 2, totalPages - 4)) + i;
              return (
                <button
                  key={p}
                  style={S.pageBtn(p === page)}
                  onClick={() => setPage(p)}
                >
                  {p}
                </button>
              );
            })}
            <button
              style={S.pageBtn(false)}
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              ›
            </button>
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════════
          Section 3：本周排班概览
      ═══════════════════════════════════════════════ */}
      <div style={S.card}>
        <div style={S.sectionTitle}>
          <span style={{ fontSize: '18px' }}>📅</span>
          本周排班概览
        </div>

        {scheduleLoading ? (
          <div style={{ color: '#6B8A99', textAlign: 'center', padding: '30px 0' }}>加载中...</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={S.weekTable}>
              <thead>
                <tr>
                  <th style={{ ...S.weekTh, textAlign: 'left', width: '60px', color: '#4FC3F7' }}>班次</th>
                  {weekDays.map((date, i) => {
                    const isToday = date === new Date().toISOString().split('T')[0];
                    return (
                      <th key={date} style={{
                        ...S.weekTh,
                        color: isToday ? '#4FC3F7' : '#6B8A99',
                        fontWeight: isToday ? 700 : 500,
                      }}>
                        <div>{CN_WEEKDAYS[i]}</div>
                        <div style={{ fontSize: '11px', marginTop: '2px' }}>
                          {date.slice(5)} {/* MM-DD */}
                        </div>
                        {isToday && (
                          <div style={{
                            width: '4px', height: '4px', borderRadius: '50%',
                            backgroundColor: '#4FC3F7', margin: '3px auto 0',
                          }} />
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {SHIFT_CONFIG.map(({ key, label, color }) => (
                  <tr key={key}>
                    <td style={{ ...S.weekTd, textAlign: 'left', color: '#B0C4CE', fontWeight: 500 }}>
                      {label}
                    </td>
                    {weekDays.map((date) => {
                      const shift = scheduleIndex[date]?.[key];
                      return (
                        <td key={date} style={S.weekTd}>
                          {shift ? (
                            <span style={S.shiftBubble(color)}>
                              {shift.count} 人
                            </span>
                          ) : (
                            <span style={{ color: '#2A4A5A', fontSize: '11px' }}>—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!scheduleLoading && scheduleData.length === 0 && (
          <div style={{ textAlign: 'center', color: '#6B8A99', fontSize: '13px', marginTop: '12px' }}>
            本周暂无排班数据。请先在排班管理中生成排班计划。
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════════
          Section 4：本月绩效排行
      ═══════════════════════════════════════════════ */}
      <div style={S.card}>
        <div style={S.sectionTitle}>
          <span style={{ fontSize: '18px' }}>🏆</span>
          本月绩效排行 TOP 10
        </div>

        {perfLoading ? (
          <SkeletonRows count={5} />
        ) : perfRanking.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#6B8A99', padding: '30px 0', fontSize: '13px' }}>
            暂无绩效数据。请先执行绩效计算（POST /api/v1/org/performance/compute）。
          </div>
        ) : (
          perfRanking.map((r, i) => {
            const rank = i + 1;
            const barWidth = maxScore > 0 ? `${(r.score / maxScore) * 100}%` : '0%';
            return (
              <div key={r.emp_id} style={S.rankRow}>
                {/* 排名序号 */}
                <div style={S.rankNum(rank)}>{rank}</div>

                {/* 姓名 + 门店 */}
                <div style={{ flex: '0 0 100px' }}>
                  <div style={{ color: '#FFFFFF', fontWeight: 500, fontSize: '13px' }}>{r.emp_name}</div>
                  {r.store_name && (
                    <div style={{ color: '#6B8A99', fontSize: '11px', marginTop: '2px' }}>{r.store_name}</div>
                  )}
                </div>

                {/* 进度条 */}
                <div style={{ ...S.scoreBar(r.score), flex: 1 }}>
                  <div style={{
                    position: 'absolute' as const,
                    top: 0, left: 0,
                    height: '100%',
                    width: barWidth,
                    backgroundColor: rank === 1 ? '#D4A010' : rank <= 3 ? '#4FC3F7' : '#2563EB',
                    borderRadius: '3px',
                    transition: 'width 0.4s ease',
                  }} />
                </div>

                {/* 分数 */}
                <div style={{
                  flex: '0 0 50px',
                  textAlign: 'right',
                  fontWeight: 700,
                  fontSize: '15px',
                  color: rank === 1 ? '#D4A010' : rank <= 3 ? '#4FC3F7' : '#B0C4CE',
                }}>
                  {r.score}
                </div>

                {/* 附加指标 */}
                <div style={{
                  flex: '0 0 160px',
                  display: 'flex',
                  gap: '6px',
                  justifyContent: 'flex-end',
                }}>
                  {r.sales_fen != null && (
                    <span style={S.badge('#52C97A', '#0D2A1A')}>
                      {fen2yuan(r.sales_fen)}
                    </span>
                  )}
                  {r.attendance_rate != null && (
                    <span style={S.badge('#4FC3F7', '#0D2030')}>
                      出勤 {(r.attendance_rate * 100).toFixed(0)}%
                    </span>
                  )}
                  {r.customer_score != null && (
                    <span style={S.badge('#FFB347', '#2A1A00')}>
                      客评 {r.customer_score.toFixed(1)}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
