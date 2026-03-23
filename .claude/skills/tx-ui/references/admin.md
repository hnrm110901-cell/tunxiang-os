# Admin 终端 · 总部管理后台

## 技术栈

```
React 18 + TypeScript (strict)
Ant Design 5.x + ProComponents (ProTable / ProForm / ProLayout)
Zustand（状态管理）
@ant-design/charts（图表）
UnoCSS（原子样式补充）
Vite（构建）
```

## 适用场景

八大产品域中"总部视角"的所有功能：
- 域A：预订总览、桌台穿透
- 域B：菜品档案、菜单模板、BOM配方、定价
- 域C：CDP会员、RFM分析、营销活动
- 域D：采购、库存、供应商、成本
- 域E：对账、支付流水、凭证、损益
- 域F：组织架构、权限、门店入驻、提成、巡店
- 域G：经营驾驶舱、140+报表、自然语言问数
- 域H：Agent管理、规则策略、Agent监控

## 主题配置

```typescript
// 必须通过ConfigProvider注入，不要硬编码颜色
import { ThemeConfig } from 'antd';

export const txAdminTheme: ThemeConfig = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Layout: { headerBg: '#1E2A3A', siderBg: '#1E2A3A' },
    Menu: { darkItemBg: '#1E2A3A', darkItemSelectedBg: '#FF6B35' },
    Table: { headerBg: '#F8F7F5' },
  },
};
```

## 页面开发模式

### 标准CRUD页面（64个模块中约80%适用）

```tsx
// 使用ProTable——不要手写Table+分页+筛选
import { ProTable, ProColumns, ActionType } from '@ant-design/pro-components';

const columns: ProColumns<DishItem>[] = [
  { title: '菜品名称', dataIndex: 'name', valueType: 'text',
    fieldProps: { placeholder: '搜索菜品' } },
  { title: '分类', dataIndex: 'category', valueType: 'select',
    valueEnum: dishCategoryEnum },
  { title: '售价', dataIndex: 'price', valueType: 'money' },
  { title: '毛利率', dataIndex: 'margin', valueType: 'percent',
    render: (_, r) => <Tag color={r.margin < 0.4 ? 'red' : 'green'}>
      {(r.margin * 100).toFixed(1)}%</Tag> },
  { title: '操作', valueType: 'option',
    render: (_, r) => [
      <a key="edit" onClick={() => handleEdit(r)}>编辑</a>,
      <a key="detail" onClick={() => handleDetail(r)}>详情</a>,
    ] },
];

<ProTable<DishItem>
  columns={columns}
  request={async (params) => {
    const res = await api.dish.list({ ...params, tenantId });
    return { data: res.items, total: res.total, success: true };
  }}
  rowKey="id"
  search={{ labelWidth: 'auto' }}
  toolBarRender={() => [
    <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
      新增菜品
    </Button>,
  ]}
  pagination={{ defaultPageSize: 20 }}
/>
```

### 表单页

```tsx
// 使用ModalForm / DrawerForm——不要手写Modal+Form
import { ModalForm, ProFormText, ProFormMoney, ProFormSelect } from '@ant-design/pro-components';

<ModalForm
  title="新增菜品"
  trigger={<Button type="primary">新增</Button>}
  onFinish={async (values) => {
    await api.dish.create(values);
    message.success('创建成功');
    return true; // 关闭弹窗
  }}
>
  <ProFormText name="name" label="菜品名称" rules={[{ required: true }]} />
  <ProFormMoney name="price" label="售价" min={0} />
  <ProFormSelect name="categoryId" label="分类"
    request={async () => api.dish.categories()} />
</ModalForm>
```

### 经营驾驶舱

```tsx
// 顶部指标卡片 + 中间图表 + 底部明细表
import { StatisticCard } from '@ant-design/pro-components';
import { Line, Pie } from '@ant-design/charts';

// 指标卡片组
<Row gutter={16}>
  <Col span={6}>
    <StatisticCard statistic={{
      title: '今日营收',
      value: todayRevenue,
      prefix: '¥',
      description: <Statistic title="环比" value={ratio} suffix="%" trend={trend} />,
    }} />
  </Col>
  {/* 更多指标卡片... */}
</Row>

// 图表
<Line data={revenueData} xField="date" yField="revenue" seriesField="store" />
```

## 编码规则

1. **列表页必须用 ProTable** —— 自带搜索栏、分页、列设置、密度切换
2. **表单必须用 ProForm 系列** —— 自带校验、布局、联动
3. **布局用 ProLayout** —— 侧边栏从路由配置自动生成
4. **图表用 @ant-design/charts** —— 不引入ECharts
5. **Admin终端禁止使用TXTouch组件** —— TXTouch仅给Store终端
6. **布局用Ant Grid/Flex** —— UnoCSS仅用于微调
7. **最小支持1280px宽度** —— 所有页面必须响应式
8. **毛利率低于阈值必须红色Tag** —— `<Tag color="red">`
9. **Agent相关数据用info色标注** —— 区分AI建议和人工数据
10. **操作留痕展示** —— Agent决策日志用Timeline组件展示

## 文件组织

```
apps/web-admin/src/
  layouts/                # ProLayout配置
  pages/                  # 按域A-H分目录
    trade/                # 域A
      reservation/        # 预订管理
      table-overview/     # 桌台穿透
    menu/                 # 域B
      dish-list/          # 菜品列表（ProTable标准页）
      dish-form/          # 菜品表单（ModalForm/DrawerForm）
      template/           # 菜单模板
      bom/                # BOM配方
    member/               # 域C
    supply/               # 域D
    finance/              # 域E
    org/                  # 域F
    analytics/            # 域G
      dashboard/          # 经营驾驶舱
      reports/            # 分析报表
      nlq/                # 自然语言问数
    agent/                # 域H
  components/             # Admin共享组件
    AgentDecisionLog/     # Agent决策日志展示
    MarginTag/            # 毛利率Tag（自动变色）
    TenantSelector/       # 租户/品牌/门店选择器
  hooks/                  # Admin共享Hooks
    useProTableRequest/   # ProTable标准请求Hook
    useTenantContext/     # 租户上下文
  theme/                  # 主题配置
    antd-theme.ts
  store/                  # Zustand stores
  api/                    # API调用层
```
