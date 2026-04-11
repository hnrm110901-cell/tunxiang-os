/**
 * 整改指挥中心 — 预警转化整改任务、责任人跟踪、闭环管理
 * API: GET  /api/v1/ops/rectification/summary
 *      GET  /api/v1/ops/rectification/tasks?status=&severity=&region=&store_id=&q=
 *      PATCH /api/v1/ops/rectification/tasks/:id/status
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Tag,
  Drawer,
  Button,
  Select,
  Input,
  Statistic,
  Timeline,
  Progress,
  Space,
  Row,
  Col,
  Image,
  message,
  Empty,
  Spin,
  Tooltip,
  Steps,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchRectificationSummary,
  fetchRectificationTasks,
  updateRectificationStatus,
} from '../../../api/rectificationApi';
import type {
  RectificationTask,
  RectificationSummary,
  TaskStatus,
  Severity,
} from '../../../api/rectificationApi';

// ─── 格式化工具 ───

const fmtPct = (rate: number) => `${(rate * 100).toFixed(1)}%`;

// ─── 颜色常量 ───

const COLOR = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  error: '#A32D2D',
  info: '#185FA5',
  text: '#2C2C2A',
  muted: '#8c8c8c',
  bg: '#F8F7F5',
} as const;

// ─── 状态/严重度配置 ───

const STATUS_CONFIG: Record<TaskStatus, { label: string; color: string }> = {
  pending: { label: '待处理', color: COLOR.warning },
  in_progress: { label: '进行中', color: COLOR.info },
  completed: { label: '已完成', color: COLOR.success },
  overdue: { label: '已超期', color: COLOR.error },
  escalated: { label: '已升级', color: '#7B2D8E' },
};

const SEVERITY_CONFIG: Record<Severity, { label: string; color: string }> = {
  critical: { label: '严重', color: COLOR.error },
  warning: { label: '警告', color: COLOR.warning },
  info: { label: '提示', color: COLOR.info },
};

const ESCALATION_LABELS = ['门店', '区域', '总部'];
const ESCALATION_TIMEOUTS = ['2小时', '4小时', '8小时'];

// ─── 空数据 ───

const EMPTY_SUMMARY: RectificationSummary = {
  pending: 0,
  in_progress: 0,
  completed: 0,
  overdue: 0,
  avg_resolve_hours: 0,
  completion_rate: 0,
  by_region: [],
};

// ─── 主组件 ───

export function RectificationCenterPage() {
  // 数据状态
  const [summary, setSummary] = useState<RectificationSummary>(EMPTY_SUMMARY);
  const [tasks, setTasks] = useState<RectificationTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusUpdating, setStatusUpdating] = useState(false);

  // 筛选状态
  const [statusFilter, setStatusFilter] = useState<TaskStatus | undefined>(undefined);
  const [severityFilter, setSeverityFilter] = useState<Severity | undefined>(undefined);
  const [regionFilter, setRegionFilter] = useState<string | undefined>(undefined);
  const [searchText, setSearchText] = useState('');

  // 抽屉状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedTask, setSelectedTask] = useState<RectificationTask | null>(null);

  // ─── 数据加载 ───

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryData, tasksData] = await Promise.all([
        fetchRectificationSummary().catch(() => EMPTY_SUMMARY),
        fetchRectificationTasks({
          status: statusFilter,
          severity: severityFilter,
          region: regionFilter,
          q: searchText || undefined,
        }).catch(() => [] as RectificationTask[]),
      ]);
      setSummary(summaryData);
      setTasks(tasksData);
    } catch {
      setSummary(EMPTY_SUMMARY);
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, severityFilter, regionFilter, searchText]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ─── 状态变更 ───

  const handleStatusChange = useCallback(
    async (taskId: string, newStatus: TaskStatus, note?: string) => {
      setStatusUpdating(true);
      try {
        await updateRectificationStatus(taskId, { status: newStatus, note });
        message.success('状态更新成功');
        // 刷新数据
        await loadData();
        // 更新抽屉中的选中任务
        if (selectedTask?.id === taskId) {
          setSelectedTask((prev) =>
            prev ? { ...prev, status: newStatus } : null
          );
        }
      } catch {
        message.error('状态更新失败，请重试');
      } finally {
        setStatusUpdating(false);
      }
    },
    [loadData, selectedTask?.id]
  );

  // ─── 打开详情抽屉 ───

  const openDrawer = useCallback((task: RectificationTask) => {
    setSelectedTask(task);
    setDrawerOpen(true);
  }, []);

  // ─── 提取区域列表（用于筛选下拉） ───

  const regionOptions = Array.from(new Set(tasks.map((t) => t.region))).filter(Boolean);

  // ─── 表格列定义 ───

  const columns: ColumnsType<RectificationTask> = [
    {
      title: '任务ID',
      dataIndex: 'id',
      key: 'id',
      width: 120,
      render: (id: string) => (
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: COLOR.muted }}>
          {id.slice(0, 8)}
        </span>
      ),
    },
    {
      title: '来源预警',
      dataIndex: 'alert_title',
      key: 'alert_title',
      width: 180,
      ellipsis: true,
      render: (title: string, record) => (
        <Tooltip title={`预警ID: ${record.alert_id}`}>
          <span style={{ color: COLOR.text }}>{title}</span>
        </Tooltip>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      key: 'store_name',
      width: 120,
      ellipsis: true,
    },
    {
      title: '责任人',
      dataIndex: 'assignee',
      key: 'assignee',
      width: 80,
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      key: 'severity',
      width: 80,
      render: (sev: Severity) => (
        <Tag color={SEVERITY_CONFIG[sev].color} style={{ margin: 0 }}>
          {SEVERITY_CONFIG[sev].label}
        </Tag>
      ),
      filters: [
        { text: '严重', value: 'critical' },
        { text: '警告', value: 'warning' },
        { text: '提示', value: 'info' },
      ],
      onFilter: (value, record) => record.severity === value,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: TaskStatus) => (
        <Tag color={STATUS_CONFIG[status].color} style={{ margin: 0 }}>
          {STATUS_CONFIG[status].label}
        </Tag>
      ),
    },
    {
      title: '截止时间',
      dataIndex: 'deadline',
      key: 'deadline',
      width: 160,
      render: (deadline: string, record) => {
        const isOverdue =
          record.status !== 'completed' && new Date(deadline) < new Date();
        return (
          <span style={{ color: isOverdue ? COLOR.error : COLOR.text, fontWeight: isOverdue ? 600 : 400 }}>
            {deadline}
            {isOverdue && ' (已超期)'}
          </span>
        );
      },
      sorter: (a, b) => new Date(a.deadline).getTime() - new Date(b.deadline).getTime(),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      defaultSortOrder: 'descend',
    },
  ];

  // ─── 渲染：顶部统计卡片 ───

  const renderSummaryCards = () => {
    const cards = [
      { title: '待处理', value: summary.pending, color: COLOR.warning, icon: '⏳' },
      { title: '进行中', value: summary.in_progress, color: COLOR.info, icon: '🔄' },
      { title: '已完成', value: summary.completed, color: COLOR.success, icon: '✅' },
      { title: '已超期', value: summary.overdue, color: COLOR.error, icon: '⚠️' },
    ];

    return (
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {cards.map((c) => (
          <Col span={6} key={c.title}>
            <Card
              bordered={false}
              style={{
                background: '#fff',
                borderLeft: `4px solid ${c.color}`,
                borderRadius: 8,
              }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <Statistic
                title={
                  <span style={{ color: COLOR.muted, fontSize: 13 }}>
                    {c.icon} {c.title}
                  </span>
                }
                value={c.value}
                valueStyle={{ color: c.color, fontSize: 28, fontWeight: 700 }}
              />
            </Card>
          </Col>
        ))}
      </Row>
    );
  };

  // ─── 渲染：筛选栏 ───

  const renderFilters = () => (
    <Card
      bordered={false}
      style={{ marginBottom: 16, borderRadius: 8 }}
      bodyStyle={{ padding: '12px 16px' }}
    >
      <Space wrap size={12}>
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: 140 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          options={[
            { label: '待处理', value: 'pending' },
            { label: '进行中', value: 'in_progress' },
            { label: '已完成', value: 'completed' },
            { label: '已超期', value: 'overdue' },
            { label: '已升级', value: 'escalated' },
          ]}
        />
        <Select
          placeholder="严重度"
          allowClear
          style={{ width: 120 }}
          value={severityFilter}
          onChange={(v) => setSeverityFilter(v)}
          options={[
            { label: '严重', value: 'critical' },
            { label: '警告', value: 'warning' },
            { label: '提示', value: 'info' },
          ]}
        />
        <Select
          placeholder="区域"
          allowClear
          style={{ width: 140 }}
          value={regionFilter}
          onChange={(v) => setRegionFilter(v)}
          options={regionOptions.map((r) => ({ label: r, value: r }))}
        />
        <Input.Search
          placeholder="搜索任务/门店/责任人"
          allowClear
          style={{ width: 240 }}
          onSearch={(v) => setSearchText(v)}
          onChange={(e) => {
            if (!e.target.value) setSearchText('');
          }}
        />
        <Button onClick={loadData} style={{ color: COLOR.primary, borderColor: COLOR.primary }}>
          刷新
        </Button>
      </Space>
    </Card>
  );

  // ─── 渲染：详情抽屉 ───

  const renderDrawer = () => {
    if (!selectedTask) return null;
    const task = selectedTask;

    // 可执行的状态变更动作
    const statusActions: { label: string; target: TaskStatus; type: 'primary' | 'default' | 'dashed' }[] = [];
    if (task.status === 'pending') {
      statusActions.push({ label: '开始处理', target: 'in_progress', type: 'primary' });
    }
    if (task.status === 'in_progress') {
      statusActions.push({ label: '标记完成', target: 'completed', type: 'primary' });
      statusActions.push({ label: '升级处理', target: 'escalated', type: 'dashed' });
    }
    if (task.status === 'overdue') {
      statusActions.push({ label: '开始处理', target: 'in_progress', type: 'primary' });
      statusActions.push({ label: '升级处理', target: 'escalated', type: 'dashed' });
    }
    if (task.status === 'escalated') {
      statusActions.push({ label: '开始处理', target: 'in_progress', type: 'primary' });
    }

    return (
      <Drawer
        title={
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Tag color={SEVERITY_CONFIG[task.severity].color}>
                {SEVERITY_CONFIG[task.severity].label}
              </Tag>
              <Tag color={STATUS_CONFIG[task.status].color}>
                {STATUS_CONFIG[task.status].label}
              </Tag>
              <span style={{ fontSize: 16, fontWeight: 600, color: COLOR.text }}>
                整改任务详情
              </span>
            </div>
          </div>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={560}
        footer={
          statusActions.length > 0 && (
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              {statusActions.map((action) => (
                <Button
                  key={action.target}
                  type={action.type}
                  loading={statusUpdating}
                  onClick={() => handleStatusChange(task.id, action.target)}
                  style={
                    action.type === 'primary'
                      ? { background: COLOR.primary, borderColor: COLOR.primary }
                      : action.type === 'dashed'
                        ? { color: COLOR.error, borderColor: COLOR.error }
                        : {}
                  }
                >
                  {action.label}
                </Button>
              ))}
            </div>
          )
        }
      >
        {/* 预警来源 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
            预警来源
          </div>
          <Card
            size="small"
            bordered
            style={{ background: COLOR.bg, borderRadius: 8 }}
            bodyStyle={{ padding: 12 }}
          >
            <div style={{ fontSize: 12, color: COLOR.muted, marginBottom: 4 }}>
              预警ID: {task.alert_id}
            </div>
            <div style={{ fontSize: 14, color: COLOR.text, fontWeight: 500 }}>
              {task.alert_title}
            </div>
            <div style={{ fontSize: 12, color: COLOR.muted, marginTop: 4 }}>
              分类: {task.alert_category} | 门店: {task.store_name} | 区域: {task.region}
            </div>
          </Card>
        </div>

        {/* 整改要求 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
            整改要求
          </div>
          <div
            style={{
              padding: 12,
              borderRadius: 8,
              background: COLOR.bg,
              fontSize: 13,
              color: COLOR.text,
              lineHeight: 1.8,
              border: '1px solid #e8e8e8',
            }}
          >
            {task.requirement || task.description}
          </div>
        </div>

        {/* 基本信息 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
            基本信息
          </div>
          <Row gutter={[16, 8]}>
            <Col span={12}>
              <span style={{ color: COLOR.muted, fontSize: 12 }}>责任人：</span>
              <span style={{ color: COLOR.text, fontSize: 13 }}>{task.assignee}</span>
            </Col>
            <Col span={12}>
              <span style={{ color: COLOR.muted, fontSize: 12 }}>截止时间：</span>
              <span
                style={{
                  color:
                    task.status !== 'completed' && new Date(task.deadline) < new Date()
                      ? COLOR.error
                      : COLOR.text,
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {task.deadline}
              </span>
            </Col>
            <Col span={12}>
              <span style={{ color: COLOR.muted, fontSize: 12 }}>创建时间：</span>
              <span style={{ color: COLOR.text, fontSize: 13 }}>{task.created_at}</span>
            </Col>
            <Col span={12}>
              <span style={{ color: COLOR.muted, fontSize: 12 }}>更新时间：</span>
              <span style={{ color: COLOR.text, fontSize: 13 }}>{task.updated_at}</span>
            </Col>
          </Row>
        </div>

        {/* 升级链路 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
            升级链路
          </div>
          <Steps
            current={task.escalation_level}
            size="small"
            items={ESCALATION_LABELS.map((label, idx) => ({
              title: label,
              description: (
                <span style={{ fontSize: 11, color: COLOR.muted }}>
                  超时 {ESCALATION_TIMEOUTS[idx]}
                </span>
              ),
              status:
                idx < task.escalation_level
                  ? 'finish'
                  : idx === task.escalation_level
                    ? task.status === 'escalated'
                      ? 'error'
                      : 'process'
                    : 'wait',
            }))}
          />
        </div>

        {/* 完成进度 */}
        {task.completion_rate !== undefined && task.completion_rate > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
              完成进度
            </div>
            <Progress
              percent={Math.round(task.completion_rate * 100)}
              strokeColor={COLOR.primary}
              trailColor="#e8e8e8"
            />
          </div>
        )}

        {/* 执行时间线 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
            执行时间线
          </div>
          {task.timeline && task.timeline.length > 0 ? (
            <Timeline
              items={task.timeline.map((entry) => ({
                color: COLOR.primary,
                children: (
                  <div>
                    <div style={{ fontSize: 12, color: COLOR.muted }}>{entry.time}</div>
                    <div style={{ fontSize: 13, color: COLOR.text, fontWeight: 500 }}>
                      {entry.operator}：{entry.action}
                    </div>
                    {entry.note && (
                      <div style={{ fontSize: 12, color: COLOR.muted, marginTop: 2 }}>
                        备注：{entry.note}
                      </div>
                    )}
                  </div>
                ),
              }))}
            />
          ) : (
            <div style={{ color: COLOR.muted, fontSize: 12, textAlign: 'center', padding: 16 }}>
              暂无操作记录
            </div>
          )}
        </div>

        {/* 照片证据 */}
        {((task.photos_before && task.photos_before.length > 0) ||
          (task.photos_after && task.photos_after.length > 0)) && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.text, marginBottom: 8 }}>
              照片证据
            </div>
            <Row gutter={16}>
              {task.photos_before && task.photos_before.length > 0 && (
                <Col span={12}>
                  <div
                    style={{
                      fontSize: 12,
                      color: COLOR.error,
                      fontWeight: 600,
                      marginBottom: 6,
                    }}
                  >
                    整改前 (Before)
                  </div>
                  <Image.PreviewGroup>
                    <Space wrap size={8}>
                      {task.photos_before.map((url, idx) => (
                        <Image
                          key={`before-${idx}`}
                          src={url}
                          width={100}
                          height={100}
                          style={{ borderRadius: 6, objectFit: 'cover' }}
                          fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1zaXplPSIxMiIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9IjAuMzVlbSI+5peg5Zu+54mHPC90ZXh0Pjwvc3ZnPg=="
                        />
                      ))}
                    </Space>
                  </Image.PreviewGroup>
                </Col>
              )}
              {task.photos_after && task.photos_after.length > 0 && (
                <Col span={12}>
                  <div
                    style={{
                      fontSize: 12,
                      color: COLOR.success,
                      fontWeight: 600,
                      marginBottom: 6,
                    }}
                  >
                    整改后 (After)
                  </div>
                  <Image.PreviewGroup>
                    <Space wrap size={8}>
                      {task.photos_after.map((url, idx) => (
                        <Image
                          key={`after-${idx}`}
                          src={url}
                          width={100}
                          height={100}
                          style={{ borderRadius: 6, objectFit: 'cover' }}
                          fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1zaXplPSIxMiIgZmlsbD0iIzk5OSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9IjAuMzVlbSI+5peg5Zu+54mHPC90ZXh0Pjwvc3ZnPg=="
                        />
                      ))}
                    </Space>
                  </Image.PreviewGroup>
                </Col>
              )}
            </Row>
          </div>
        )}
      </Drawer>
    );
  };

  // ─── 渲染：底部统计 ───

  const renderBottomStats = () => {
    const totalTasks = summary.pending + summary.in_progress + summary.completed + summary.overdue;
    const overdueRate = totalTasks > 0 ? summary.overdue / totalTasks : 0;

    return (
      <Row gutter={16} style={{ marginTop: 16 }}>
        {/* 完成率 */}
        <Col span={6}>
          <Card bordered={false} style={{ borderRadius: 8 }} bodyStyle={{ padding: '16px 20px', textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: COLOR.muted, marginBottom: 8 }}>完成率</div>
            <Progress
              type="circle"
              percent={Math.round(summary.completion_rate * 100)}
              size={80}
              strokeColor={COLOR.success}
              format={(pct) => (
                <span style={{ color: COLOR.success, fontWeight: 700, fontSize: 18 }}>{pct}%</span>
              )}
            />
          </Card>
        </Col>

        {/* 超时率 */}
        <Col span={6}>
          <Card bordered={false} style={{ borderRadius: 8 }} bodyStyle={{ padding: '16px 20px', textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: COLOR.muted, marginBottom: 8 }}>超时率</div>
            <Progress
              type="circle"
              percent={Math.round(overdueRate * 100)}
              size={80}
              strokeColor={COLOR.error}
              format={(pct) => (
                <span style={{ color: COLOR.error, fontWeight: 700, fontSize: 18 }}>{pct}%</span>
              )}
            />
          </Card>
        </Col>

        {/* 平均处理时长 */}
        <Col span={6}>
          <Card bordered={false} style={{ borderRadius: 8 }} bodyStyle={{ padding: '16px 20px', textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: COLOR.muted, marginBottom: 8 }}>平均处理时长</div>
            <Statistic
              value={summary.avg_resolve_hours}
              suffix="小时"
              valueStyle={{ color: COLOR.primary, fontSize: 28, fontWeight: 700 }}
            />
          </Card>
        </Col>

        {/* 按区域分布 */}
        <Col span={6}>
          <Card bordered={false} style={{ borderRadius: 8 }} bodyStyle={{ padding: '16px 20px' }}>
            <div style={{ fontSize: 12, color: COLOR.muted, marginBottom: 8, textAlign: 'center' }}>
              区域分布
            </div>
            {summary.by_region.length > 0 ? (
              <div style={{ maxHeight: 120, overflowY: 'auto' }}>
                {summary.by_region.map((r) => {
                  const rate = r.count > 0 ? r.completed / r.count : 0;
                  return (
                    <div
                      key={r.region}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 6,
                        fontSize: 12,
                      }}
                    >
                      <span style={{ color: COLOR.text }}>{r.region}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: COLOR.muted }}>{r.count}项</span>
                        <Tag
                          color={rate >= 0.8 ? COLOR.success : rate >= 0.5 ? COLOR.warning : COLOR.error}
                          style={{ margin: 0, fontSize: 11 }}
                        >
                          {fmtPct(rate)}
                        </Tag>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ color: COLOR.muted, fontSize: 12, textAlign: 'center', padding: 16 }}>
                暂无数据
              </div>
            )}
          </Card>
        </Col>
      </Row>
    );
  };

  // ─── 页面渲染 ───

  return (
    <div style={{ padding: 24, background: COLOR.bg, minHeight: '100vh' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: COLOR.text }}>
          整改指挥中心
        </h2>
        <div style={{ fontSize: 13, color: COLOR.muted, marginTop: 4 }}>
          总部视角管理预警整改任务，跟踪责任闭环，超时自动升级
        </div>
      </div>

      {/* 顶部统计卡片 */}
      {renderSummaryCards()}

      {/* 筛选栏 */}
      {renderFilters()}

      {/* 任务列表 */}
      <Card
        bordered={false}
        style={{ borderRadius: 8, marginBottom: 0 }}
        bodyStyle={{ padding: 0 }}
      >
        <Spin spinning={loading}>
          <Table<RectificationTask>
            columns={columns}
            dataSource={tasks}
            rowKey="id"
            pagination={{
              pageSize: 15,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条整改任务`,
              size: 'small',
            }}
            size="middle"
            locale={{
              emptyText: <Empty description="暂无整改任务" />,
            }}
            onRow={(record) => ({
              onClick: () => openDrawer(record),
              style: { cursor: 'pointer' },
            })}
            rowClassName={(record) =>
              record.status === 'overdue'
                ? 'rectification-row-overdue'
                : record.status === 'escalated'
                  ? 'rectification-row-escalated'
                  : ''
            }
          />
        </Spin>
      </Card>

      {/* 底部统计 */}
      {renderBottomStats()}

      {/* 详情抽屉 */}
      {renderDrawer()}

      {/* 行样式 */}
      <style>{`
        .rectification-row-overdue {
          background: rgba(163, 45, 45, 0.04) !important;
        }
        .rectification-row-overdue:hover > td {
          background: rgba(163, 45, 45, 0.08) !important;
        }
        .rectification-row-escalated {
          background: rgba(123, 45, 142, 0.04) !important;
        }
        .rectification-row-escalated:hover > td {
          background: rgba(123, 45, 142, 0.08) !important;
        }
      `}</style>
    </div>
  );
}
