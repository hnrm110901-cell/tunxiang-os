# 屯象OS A2UI 协议规范（中文 v0.8）

> Sprint 3 S3-02 落盘文档。Sprint 3 完成后正式作为 屯象OS Agent ↔ 前端 通信协议的单一可信源。
>
> 参考：Google A2UI Spec v0.8 (Dec 2025) — Agent-to-User-Interface 协议
> 实现：`apps/web-pos/src/components/a2ui/` + `services/tx-agent/src/agents/a2ui_surfaces.py`

---

## 一、协议总览

### 1.1 设计动机

传统 Agent 输出业务 JSON，前端必须为每个 Agent 类型写适配代码（解析 → React 组件）。
A2UI 协议反转这个关系：**Agent 输出 UI 声明**，前端只维护一个白名单渲染器（`A2UIRenderer`），新 Agent 上线零前端代码。

### 1.2 数据流

```
Skill Agent (Python)
  └─ build_*_surface() 输出 A2UIDeclaration JSON
     └─ HTTP/WebSocket 推送到前端
        └─ A2UIRenderer (React) 按白名单渲染
           └─ 用户交互 → onAction(actionId, payload)
              └─ 回调 Agent 触发下一步（决策留痕 in AgentDecisionLog）
```

### 1.3 与 Google A2UI v0.8 spec 关系

- **复用**：`A2UIDeclaration` 顶层结构（version / surface / metadata）；`type` 字段做白名单
- **本地化**：组件清单根据屯象OS Store/Admin 终端裁剪
- **强化**：触控基线（≥ 48px / 关键 ≥ 72px）、品牌色锁定、决策留痕

---

## 二、组件白名单（20 type）

### 2.1 基础组件（14 type，M1 阶段已上线）

| Type | 用途 | 关键 props |
|------|------|-----------|
| `card` | 卡片容器 | title / subtitle / severity (info\|warning\|critical) / children |
| `text` | 文本块 | content / variant (heading\|subheading\|body\|caption) / color / align |
| `button` | 按钮 | label / variant (primary\|secondary\|danger\|ghost) / disabled / icon / action / actionPayload |
| `list` | 列表（不分页） | items[] (id/title/subtitle/leadingIcon/trailingText/actionId) / ordered |
| `input` | 单行输入 | type / placeholder / defaultValue / disabled |
| `image` | 图片 | src / alt / style |
| `chart` | 图表 | chartType (bar\|line\|pie\|number) / title / data[] / height |
| `badge` | 徽标 | text / variant (success\|warning\|danger\|info) |
| `progress` | 进度条 | value / max / label / color |
| `table` | 数据表 | columns[] / rows[] / pageSize |
| `actions` | 按钮组 | buttons[] (与 button 同 props) |
| `section` | 区块 | title / children |
| `divider` | 分割线 | (无 props) |
| `spinner` | 加载中 | (无 props) |

### 2.2 Sprint 3 S3-01 新增（6 type）

| Type | 用途 | 安全约束 |
|------|------|---------|
| `form` | Agent 引导填表（创建宴席合同等） | fields 类型严格枚举：text\|number\|date\|select\|textarea；submit 走 actionId 白名单 |
| `map` | 桌台地图 / 配送范围可视化 | 坐标 0-100 百分比（自动 clamp）；不接受 raw URL |
| `heatmap` | KDS 实时档口热力 / 销售热力 | 数据值 0-1 范围（自动 clamp）；color gradient 由前端控制 |
| `timeline` | 订单时间线 / 食材生命周期 | ISO 8601 时间戳；severity 枚举；limit 截断防过长 |
| `cascader` | 多级菜单（菜系→菜→规格） | 深度上限 5（防递归攻击）；value 全字符串白名单 |
| `tabs` | 多视图切换 | 数量上限 12；children 节点必须有对应 contentId |

---

## 三、Surface 生成器规范

Agent 端通过 `services/tx-agent/src/agents/a2ui_surfaces.py` 提供的函数式构造器输出 A2UI 声明。

### 3.1 已实现 Surface 生成器（Sprint 3 S3-03）

```python
from agents.a2ui_surfaces import (
    build_discount_alert_surface,        # 折扣守护 critical
    build_member_recommendation_surface, # 会员洞察 info
    build_inventory_warning_surface,     # 库存预警 warning/critical
)
```

### 3.2 输出 JSON Schema

```json
{
  "surfaceId": "disc-alert-a3b2c1d4",
  "version": "0.8",
  "surface": {
    "id": "disc-alert-a3b2c1d4-root",
    "type": "card",
    "props": { "title": "🚨 毛利底线告警", "severity": "critical" },
    "children": [
      { "id": "...", "type": "text", "props": { "content": "..." } },
      { "id": "...", "type": "actions", "props": { "buttons": [...] } }
    ]
  },
  "metadata": {
    "agentId": "discount_guard",
    "confidence": 0.95,
    "timestamp": "2026-05-08T13:50:00.000Z"
  }
}
```

### 3.3 编写新 Surface 生成器的要求

1. **函数式**：无状态，纯函数，可独立测试
2. **类型严格**：所有参数命名 keyword-only（`*,`），避免位置参数错配
3. **白名单 type**：所有 `surface.type` 必须在 §2 白名单内
4. **金额分位**：所有金额字段单位 **分（整数）**，渲染层 `fenToYuan` 转换
5. **决策留痕**：actionPayload 必须含足够上下文（order_id / member_id / operator_id 等）
6. **测试覆盖**：每个生成器至少 3 用例（正常 / 边界 / actionPayload 注入）

---

## 四、前端渲染流程

### 4.1 接入

```tsx
import { A2UIRenderer, parseA2UIFromAgent } from '@/components/a2ui/A2UIRenderer';

const declaration = parseA2UIFromAgent(agentResponse);
return <A2UIRenderer
  declaration={declaration}
  onAction={(actionId, action, payload) => {
    // 转发 Agent 触发下一步动作
    txFetch('/api/v1/agent/dispatch', {
      method: 'POST',
      body: JSON.stringify({ actionId, action, payload }),
    });
  }}
/>;
```

### 4.2 渲染保护

- **未知 type**：`console.warn` + 静默跳过（不抛错，不阻塞其他节点）
- **递归深度**：cascader 5、tabs 12 数量上限（renderer 中 enforce + warn）
- **错误边界**：调用方应在 `<A2UIRenderer />` 外加 ErrorBoundary

---

## 五、安全 Review 6 条铁律

> **凡通过 PR 修改 A2UI 渲染逻辑或 Surface 生成器，必须逐条验证。**

### 5.1 ❌ 禁止 raw HTML 注入

```tsx
// ❌ 反例：dangerouslySetInnerHTML 渲染 Agent 内容
<div dangerouslySetInnerHTML={{ __html: props.content }} />

// ✅ 正例：始终走 React 文本节点
<div>{String(props.content ?? '')}</div>
```

### 5.2 ❌ 禁止 eval / Function 构造器

```python
# ❌ 反例：从 Agent 输出动态生成代码
exec(node["props"]["onClick"])

# ✅ 正例：actionId 走白名单 dispatch
onAction(actionId, action_name, payload)
```

### 5.3 ❌ 禁止 raw URL（图片/链接）

```tsx
// ❌ 反例：Agent 任意指定外站 URL
<img src={props.src as string} />  // src 可能是 "javascript:..." 或外站追踪

// ✅ 正例：走 storeId/dishId 白名单派生
<img src={`/api/v1/menu/dish/${props.dishId}/image`} />
```

### 5.4 ❌ 禁止颜色字段任意值

```tsx
// ❌ 反例：任意 hex 注入
style={{ background: props.bg as string }}  // 可能 url("javascript:...")

// ✅ 正例：枚举映射
const colorMap = { success: T.success, danger: T.danger, ... };
style={{ background: colorMap[props.severity] }}
```

### 5.5 ✅ Props 类型严格

每个组件的 props 接口必须详尽枚举所有字段类型；前端 renderer 中通过 `as unknown as A2UI*Props` 显式断言。

### 5.6 ✅ actionId 白名单 + 决策留痕

```python
# Agent 派发 action 时记录到 AgentDecisionLog
AgentDecisionLog(
    agent_id="discount_guard",
    decision_type="approve",
    input_context=action_payload,
    output_action={"surfaceId": ..., "actionId": ...},
    constraints_check={...},
    confidence=0.95,
)
```

---

## 六、决策留痕（强制）

每次 Agent 输出 Surface + 用户触发 actionId，都必须在 `services/tx-agent` 的 `AgentDecisionLog` 表中留痕：

| 字段 | 来源 |
|------|------|
| `agent_id` | metadata.agentId |
| `decision_type` | "surface_emit" / "action_invoke" |
| `input_context` | Agent 输入 + 用户操作上下文 |
| `output_action` | { surfaceId, actionId, payload } |
| `constraints_check` | 三条硬约束（毛利/食安/客户体验）校验结果 |
| `confidence` | metadata.confidence |
| `created_at` | UTC ISO 8601 |

---

## 七、测试与验证

### 7.1 单测覆盖

- 前端：`apps/web-pos/src/components/__tests__/A2UI.newTypes.test.tsx`（8 用例覆盖 6 新组件 + 安全约束）
- 后端：`services/tx-agent/src/tests/test_a2ui_surfaces.py`（10 用例覆盖 3 Surface 生成器）

### 7.2 类型同步检查

前后端 type 白名单必须严格同步：
- 前端：`apps/web-pos/src/components/a2ui/types.ts` 的 `A2UIComponentType` union
- 后端：`services/tx-agent/src/tests/test_a2ui_surfaces.py` 的 `A2UI_WHITELIST_TYPES` set
- 后端测试递归校验所有 surface 节点的 type 在白名单中

### 7.3 PR 模板新增 checkbox

`.github/pull_request_template.md`（待补）应增加：

```markdown
## A2UI 安全 Review（仅 a2ui/* 或 a2ui_surfaces.py 改动需要）

- [ ] 无 dangerouslySetInnerHTML / eval / Function
- [ ] 所有 type 在 §2 白名单内
- [ ] 所有 URL/颜色字段走枚举映射
- [ ] Props 接口类型严格（无 any，无 unknown 直传）
- [ ] actionId 走 Agent 白名单
- [ ] 决策留痕到 AgentDecisionLog
```

---

## 八、调试 / 测试用例

### 8.1 浏览器 DevTools

打开 web-pos / web-admin，Console 中：

```javascript
// 模拟 Agent 输出
const surface = {
  version: '0.8',
  surface: {
    id: 'test-1',
    type: 'card',
    props: { title: '测试卡片', severity: 'info' },
    children: [
      { id: 't1', type: 'text', props: { content: 'Hello A2UI' } },
    ],
  },
};
// 通过 Redux/Zustand store 触发渲染
window.txDebug.renderA2UI(surface);
```

### 8.2 Agent 端单测示例

```python
def test_my_new_surface():
    surface = build_my_surface(arg1="x")
    assert surface["version"] == "0.8"
    assert surface["surface"]["type"] == "card"
    # 类型白名单校验
    types = _walk_node_types(surface["surface"])
    assert types <= A2UI_WHITELIST_TYPES
```

---

## 九、版本演进

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.8 (M1) | 2026-04 | 初版 14 type 白名单 + voice_order Surface 生成器 |
| v0.8 (M2 W0+) | 2026-05-08 | Sprint 3：+6 type（form/map/heatmap/timeline/cascader/tabs）+ 3 业务 Surface 生成器 + 中文协议文档 |

---

## 十、未来扩展（M3+）

- A2UI v0.9 升级（如 Google 发布）：评估新组件价值，按需引入
- 视觉回归 CI：tx-touch Storybook + chromatic / Playwright snapshot
- A2UI Surface 缓存：高频 Surface 客户端缓存避免重复渲染
- 多语言：基于 i18n key 的 props.content 自动翻译

---

> 本文档随 Sprint 3 S3-02 完成于 2026-05-08。后续变更请提 PR 并增加版本演进表项。
