/**
 * RFM分层与标签中心 — 管理会员分层和自定义标签
 * 功能: RFM矩阵网格 + 分层会员列表 + 标签管理 + 人群包创建
 * API: /api/v1/member/rfm/distribution, /rfm/:level/members, /tags, /segments
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Row,
  Col,
  Table,
  Tag,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Space,
  Spin,
  Empty,
  message,
  Checkbox,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  ExportOutlined,
  TagsOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import {
  fetchRFMDistribution,
  fetchRFMLevelMembers,
  fetchMemberTags,
  createMemberTag,
  createSegment,
  type RFMCell,
  type RFMDistribution,
  type MemberListItem,
  type MemberTag,
  type CreateTagPayload,
} from '../../../api/memberGrowthApi';

const COLOR = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  error: '#A32D2D',
  info: '#185FA5',
};

const fmtYuan = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;

// ────────── 预设标签颜色 ──────────
const TAG_COLORS = [
  { label: '红色', value: '#A32D2D' },
  { label: '橙色', value: '#FF6B35' },
  { label: '绿色', value: '#0F6E56' },
  { label: '蓝色', value: '#185FA5' },
  { label: '紫色', value: '#7B2D8E' },
  { label: '金色', value: '#BA7517' },
  { label: '灰色', value: '#666666' },
];

// ────────── RFM 矩阵网格组件 ──────────
function RFMMatrix({
  cells,
  totalMembers,
  selectedLevel,
  onSelect,
}: {
  cells: RFMCell[];
  totalMembers: number;
  selectedLevel: string | null;
  onSelect: (cell: RFMCell) => void;
}) {
  // 构造 4x2 矩阵: 行=消费金额(高/低) x 最近消费(近/远), 列=消费频次(高/低)
  // 排列: 左列=频次高, 右列=频次低; 上行=金额高+近期, 下行=金额低+远期
  const matrixOrder: Array<{ r: string; f: string; m: string }> = [
    { r: 'high', f: 'high', m: 'high' }, // 重要价值
    { r: 'high', f: 'low', m: 'high' },  // 重要发展
    { r: 'low', f: 'high', m: 'high' },  // 重要保持
    { r: 'low', f: 'low', m: 'high' },   // 重要挽留
    { r: 'high', f: 'high', m: 'low' },  // 一般价值
    { r: 'high', f: 'low', m: 'low' },   // 一般发展
    { r: 'low', f: 'high', m: 'low' },   // 一般保持
    { r: 'low', f: 'low', m: 'low' },    // 一般挽留
  ];

  const findCell = (r: string, f: string, m: string) =>
    cells.find((c) => c.r === r && c.f === f && c.m === m);

  // 分成两行，每行4个格子
  const row1 = matrixOrder.slice(0, 4);
  const row2 = matrixOrder.slice(4, 8);

  const renderCell = (pos: { r: string; f: string; m: string }) => {
    const cell = findCell(pos.r, pos.f, pos.m);
    if (!cell) {
      return (
        <div
          style={{
            flex: 1,
            padding: 12,
            background: '#f5f5f5',
            borderRadius: 6,
            minHeight: 100,
          }}
        >
          <div style={{ color: '#ccc', fontSize: 12 }}>--</div>
        </div>
      );
    }
    const isSelected = selectedLevel === cell.level;
    return (
      <Tooltip title={cell.description} key={cell.level}>
        <div
          onClick={() => onSelect(cell)}
          style={{
            flex: 1,
            padding: 14,
            borderRadius: 8,
            background: cell.color,
            opacity: isSelected ? 1 : 0.78,
            cursor: 'pointer',
            transition: 'all 0.2s',
            border: isSelected ? '2px solid #2C2C2A' : '2px solid transparent',
            minHeight: 100,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginBottom: 6 }}>
            {cell.label}
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#fff' }}>
            {cell.count.toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.8)', marginTop: 2 }}>
            占比 {(cell.ratio * 100).toFixed(1)}%
          </div>
          <div
            style={{
              fontSize: 11,
              color: 'rgba(255,255,255,0.7)',
              marginTop: 4,
              lineHeight: 1.3,
            }}
          >
            {cell.description}
          </div>
        </div>
      </Tooltip>
    );
  };

  return (
    <div>
      {/* 轴标签 */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: '#999' }}>
          消费金额(高) / 频次(高→低) →
        </span>
      </div>
      {/* 第一行: 高消费 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
        <div
          style={{
            writingMode: 'vertical-rl',
            textOrientation: 'mixed',
            fontSize: 12,
            color: '#999',
            display: 'flex',
            alignItems: 'center',
            paddingRight: 4,
          }}
        >
          高消费
        </div>
        <div style={{ display: 'flex', gap: 10, flex: 1 }}>
          {row1.map((pos) => renderCell(pos))}
        </div>
      </div>
      {/* 第二行: 低消费 */}
      <div style={{ display: 'flex', gap: 10 }}>
        <div
          style={{
            writingMode: 'vertical-rl',
            textOrientation: 'mixed',
            fontSize: 12,
            color: '#999',
            display: 'flex',
            alignItems: 'center',
            paddingRight: 4,
          }}
        >
          低消费
        </div>
        <div style={{ display: 'flex', gap: 10, flex: 1 }}>
          {row2.map((pos) => renderCell(pos))}
        </div>
      </div>
      {/* 总人数 */}
      <div style={{ textAlign: 'center', marginTop: 12, fontSize: 13, color: '#999' }}>
        会员总数：{totalMembers.toLocaleString()} 人
      </div>
    </div>
  );
}

// ────────── 主组件 ──────────
export function MemberSegmentPage() {
  // RFM 数据
  const [rfmLoading, setRfmLoading] = useState(false);
  const [rfmData, setRfmData] = useState<RFMDistribution | null>(null);
  const [selectedCell, setSelectedCell] = useState<RFMCell | null>(null);

  // 会员列表
  const [memberLoading, setMemberLoading] = useState(false);
  const [members, setMembers] = useState<MemberListItem[]>([]);
  const [memberTotal, setMemberTotal] = useState(0);
  const [memberPage, setMemberPage] = useState(1);
  const [selectedRows, setSelectedRows] = useState<string[]>([]);

  // 标签
  const [tags, setTags] = useState<MemberTag[]>([]);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [tagForm] = Form.useForm();
  const [tagSubmitting, setTagSubmitting] = useState(false);

  // 人群包
  const [segmentModalOpen, setSegmentModalOpen] = useState(false);
  const [segmentForm] = Form.useForm();
  const [segmentSubmitting, setSegmentSubmitting] = useState(false);

  // ── 加载 RFM 分布 ──
  const loadRFM = useCallback(async () => {
    setRfmLoading(true);
    try {
      const res = await fetchRFMDistribution();
      setRfmData(res);
    } catch {
      // 保持空
    } finally {
      setRfmLoading(false);
    }
  }, []);

  // ── 加载标签 ──
  const loadTags = useCallback(async () => {
    try {
      const res = await fetchMemberTags();
      setTags(res);
    } catch {
      // 保持空
    }
  }, []);

  useEffect(() => {
    loadRFM();
    loadTags();
  }, [loadRFM, loadTags]);

  // ── 加载某层会员列表 ──
  const loadMembers = useCallback(
    async (level: string, page: number) => {
      setMemberLoading(true);
      try {
        const res = await fetchRFMLevelMembers(level, page, 20);
        setMembers(res.items);
        setMemberTotal(res.total);
      } catch {
        setMembers([]);
        setMemberTotal(0);
      } finally {
        setMemberLoading(false);
      }
    },
    [],
  );

  // 选中某个 RFM 格子
  const handleCellSelect = (cell: RFMCell) => {
    setSelectedCell(cell);
    setMemberPage(1);
    setSelectedRows([]);
    loadMembers(cell.level, 1);
  };

  // 分页
  const handlePageChange = (page: number) => {
    setMemberPage(page);
    if (selectedCell) {
      loadMembers(selectedCell.level, page);
    }
  };

  // ── 创建标签 ──
  const handleCreateTag = async () => {
    try {
      const values = await tagForm.validateFields();
      setTagSubmitting(true);
      const payload: CreateTagPayload = {
        name: values.name,
        color: values.color,
        description: values.description,
        is_auto: values.is_auto ?? false,
        rule: values.rule,
      };
      await createMemberTag(payload);
      message.success('标签创建成功');
      setTagModalOpen(false);
      tagForm.resetFields();
      loadTags();
    } catch {
      // 表单校验失败或接口报错
    } finally {
      setTagSubmitting(false);
    }
  };

  // ── 创建人群包 ──
  const handleCreateSegment = async () => {
    try {
      const values = await segmentForm.validateFields();
      setSegmentSubmitting(true);
      await createSegment({
        name: values.name,
        rfm_levels: values.rfm_levels ?? [],
        tag_ids: values.tag_ids ?? [],
        description: values.description,
      });
      message.success('人群包创建成功');
      setSegmentModalOpen(false);
      segmentForm.resetFields();
    } catch {
      // 校验或接口报错
    } finally {
      setSegmentSubmitting(false);
    }
  };

  // ── 会员列表列定义 ──
  const memberColumns = [
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 100,
    },
    {
      title: '手机号',
      dataIndex: 'phone_masked',
      key: 'phone_masked',
      width: 130,
    },
    {
      title: '累计消费',
      dataIndex: 'total_spent_fen',
      key: 'total_spent_fen',
      width: 120,
      render: (v: number) => fmtYuan(v),
      sorter: (a: MemberListItem, b: MemberListItem) =>
        a.total_spent_fen - b.total_spent_fen,
    },
    {
      title: '最近消费',
      dataIndex: 'last_order_at',
      key: 'last_order_at',
      width: 110,
      render: (v: string) => v?.slice(0, 10) ?? '--',
    },
    {
      title: '消费次数',
      dataIndex: 'order_count',
      key: 'order_count',
      width: 90,
      sorter: (a: MemberListItem, b: MemberListItem) =>
        a.order_count - b.order_count,
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      width: 200,
      render: (tagNames: string[]) =>
        tagNames?.length > 0 ? (
          <Space size={4} wrap>
            {tagNames.map((t) => {
              const tagDef = tags.find((td) => td.name === t);
              return (
                <Tag key={t} color={tagDef?.color ?? '#999'} style={{ fontSize: 11 }}>
                  {t}
                </Tag>
              );
            })}
          </Space>
        ) : (
          <span style={{ color: '#ccc', fontSize: 12 }}>--</span>
        ),
    },
    {
      title: '注册时间',
      dataIndex: 'registered_at',
      key: 'registered_at',
      width: 110,
      render: (v: string) => v?.slice(0, 10) ?? '--',
    },
  ];

  // RFM层级选项（用于人群包创建）
  const rfmLevelOptions =
    rfmData?.cells.map((c) => ({
      label: `${c.label} (${c.count}人)`,
      value: c.level,
    })) ?? [];

  const tagOptions = tags.map((t) => ({
    label: t.name,
    value: t.id,
  }));

  return (
    <div style={{ padding: 24 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
        }}
      >
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>RFM分层与标签中心</h2>
        <Space>
          <Button
            icon={<TeamOutlined />}
            onClick={() => setSegmentModalOpen(true)}
            style={{ borderColor: COLOR.primary, color: COLOR.primary }}
          >
            创建人群包
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setTagModalOpen(true)}
            style={{ background: COLOR.primary, borderColor: COLOR.primary }}
          >
            新建标签
          </Button>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        {/* 左侧: RFM矩阵 + 标签管理 */}
        <Col span={24}>
          <Card title="RFM 分层矩阵" size="small" loading={rfmLoading}>
            {rfmData && rfmData.cells.length > 0 ? (
              <RFMMatrix
                cells={rfmData.cells}
                totalMembers={rfmData.total_members}
                selectedLevel={selectedCell?.level ?? null}
                onSelect={handleCellSelect}
              />
            ) : (
              <Empty description="暂无 RFM 数据" />
            )}
          </Card>
        </Col>

        {/* 分层详情表 */}
        <Col span={16}>
          <Card
            title={
              selectedCell
                ? `${selectedCell.label} — 会员列表 (${memberTotal}人)`
                : '会员列表 — 请选择RFM层级'
            }
            size="small"
            extra={
              selectedCell && selectedRows.length > 0 ? (
                <Space size={8}>
                  <Button size="small" icon={<TagsOutlined />} disabled>
                    批量加标签
                  </Button>
                  <Button size="small" icon={<ExportOutlined />} disabled>
                    导出
                  </Button>
                  <span style={{ fontSize: 12, color: '#999' }}>
                    已选 {selectedRows.length} 人
                  </span>
                </Space>
              ) : null
            }
          >
            {selectedCell ? (
              <Table<MemberListItem>
                columns={memberColumns}
                dataSource={members}
                rowKey="id"
                loading={memberLoading}
                size="small"
                rowSelection={{
                  selectedRowKeys: selectedRows,
                  onChange: (keys) => setSelectedRows(keys as string[]),
                }}
                pagination={{
                  current: memberPage,
                  pageSize: 20,
                  total: memberTotal,
                  onChange: handlePageChange,
                  showTotal: (t) => `共 ${t} 条`,
                  size: 'small',
                }}
                scroll={{ x: 860 }}
              />
            ) : (
              <Empty
                description="点击上方矩阵格子查看该层会员"
                style={{ padding: '40px 0' }}
              />
            )}
          </Card>
        </Col>

        {/* 右侧: 标签管理 */}
        <Col span={8}>
          <Card title="自定义标签" size="small">
            {tags.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {tags.map((tag) => (
                  <div
                    key={tag.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#F8F7F5',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Tag color={tag.color} style={{ margin: 0 }}>
                        {tag.name}
                      </Tag>
                      {tag.is_auto && (
                        <span
                          style={{
                            fontSize: 10,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: `${COLOR.info}15`,
                            color: COLOR.info,
                            fontWeight: 600,
                          }}
                        >
                          自动
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 12, color: '#999' }}>
                      {tag.member_count.toLocaleString()}人
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <Empty description="暂无标签" />
            )}
          </Card>
        </Col>
      </Row>

      {/* ── 新建标签弹窗 ── */}
      <Modal
        title="新建标签"
        open={tagModalOpen}
        onCancel={() => {
          setTagModalOpen(false);
          tagForm.resetFields();
        }}
        onOk={handleCreateTag}
        confirmLoading={tagSubmitting}
        okButtonProps={{
          style: { background: COLOR.primary, borderColor: COLOR.primary },
        }}
      >
        <Form form={tagForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="标签名称"
            rules={[{ required: true, message: '请输入标签名称' }]}
          >
            <Input placeholder="例：高频外卖用户" maxLength={20} />
          </Form.Item>
          <Form.Item
            name="color"
            label="标签颜色"
            rules={[{ required: true, message: '请选择颜色' }]}
          >
            <Select
              placeholder="选择颜色"
              options={TAG_COLORS}
              optionRender={(option) => (
                <Space>
                  <span
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 3,
                      background: option.value as string,
                      display: 'inline-block',
                    }}
                  />
                  {option.label}
                </Space>
              )}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="标签说明（可选）" maxLength={100} />
          </Form.Item>
          <Form.Item name="is_auto" valuePropName="checked">
            <Checkbox>自动标签（基于规则自动打标）</Checkbox>
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) => prev.is_auto !== cur.is_auto}
          >
            {({ getFieldValue }) =>
              getFieldValue('is_auto') ? (
                <Form.Item
                  name="rule"
                  label="自动规则"
                  rules={[{ required: true, message: '请输入自动标签规则' }]}
                >
                  <Input.TextArea
                    rows={3}
                    placeholder="例：近30天消费>=3次 且 客单价>=80元"
                    maxLength={200}
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>

      {/* ── 创建人群包弹窗 ── */}
      <Modal
        title="创建人群包"
        open={segmentModalOpen}
        onCancel={() => {
          setSegmentModalOpen(false);
          segmentForm.resetFields();
        }}
        onOk={handleCreateSegment}
        confirmLoading={segmentSubmitting}
        okButtonProps={{
          style: { background: COLOR.primary, borderColor: COLOR.primary },
        }}
      >
        <Form form={segmentForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="人群包名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例：高价值复购人群" maxLength={30} />
          </Form.Item>
          <Form.Item name="rfm_levels" label="RFM层级">
            <Select
              mode="multiple"
              placeholder="选择RFM层级（可多选）"
              options={rfmLevelOptions}
            />
          </Form.Item>
          <Form.Item name="tag_ids" label="标签筛选">
            <Select
              mode="multiple"
              placeholder="选择标签（可多选）"
              options={tagOptions}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="人群包用途说明（可选）" maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
