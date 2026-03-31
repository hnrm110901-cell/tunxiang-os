---
name: skill-creator
description: "Claude Code技能构建器。当用户要求创建新技能、自动化工作流、自定义命令、或提到'创建技能'、'新建skill'、'添加工作流'、'自动化'时触发。帮助用户设计、编写、测试和注册Claude Code自定义技能，包括SKILL.md定义、references参考文件、触发条件、设计审查清单等完整技能架构。"
---

# Claude Code 技能构建器

## 概述

本技能是一个**元技能**（meta-skill），用于创建其他技能。
它理解 Claude Code 技能系统的完整架构，能够帮用户从需求到交付完整地构建自定义技能。

## 技能架构知识

### 目录结构
```
.claude/skills/<skill-name>/
  SKILL.md              # 技能定义文件（必需）
  references/           # 参考文档目录（可选）
    *.md                # 技能所需的领域知识、模板、规范
```

### SKILL.md 格式规范

```markdown
---
name: <skill-name>          # 英文kebab-case，全局唯一
description: "<触发描述>"     # 中文，描述何时触发此技能
---

# 技能标题

## 概述
<技能的核心价值和使用场景>

## 第一步：<识别/分析>
<理解用户意图的决策树>

## 第二步：<读取参考>
<需要加载的领域知识>

## 第三步：<决策/规划>
<在执行前的思考框架>

## 第四步：<执行>
<具体执行步骤和规则>

## 核心铁律
<不可违反的硬约束>

## 设计审查清单
<输出质量检查项>
```

### 关键设计原则

1. **触发描述要精确** — description 字段决定技能何时被激活，要覆盖所有触发场景的关键词
2. **参考文件要实用** — references/ 下放模板、规范、示例，不放空洞的说明
3. **决策树要明确** — 用户意图模糊时，技能应指导 Claude 主动询问
4. **铁律要可执行** — 不是建议，是硬约束，违反即失败
5. **审查清单要可检查** — 每项都是 yes/no 判断，不是主观评价

## 创建流程

### Step 1: 需求分析

向用户确认以下信息（如果用户没有明确说明）：

| 问题 | 为什么重要 |
|------|-----------|
| 这个技能解决什么问题？ | 定义核心价值 |
| 谁在什么场景下使用？ | 确定触发条件 |
| 输入是什么？输出是什么？ | 定义接口 |
| 有哪些不可违反的规则？ | 定义铁律 |
| 需要什么领域知识？ | 规划 references |

### Step 2: 设计技能架构

基于需求，设计：
- 技能名称（kebab-case）
- 触发关键词列表
- 执行步骤流程
- 需要的参考文件
- 质量审查清单

### Step 3: 编写 SKILL.md

按照格式规范编写，确保：
- description 包含所有触发关键词
- 步骤清晰可执行
- 铁律不含模糊用语（"尽量"、"建议"→ 改为"必须"、"禁止"）

### Step 4: 编写 references/

如果技能需要领域知识，创建参考文件：
- 模板文件（如文档模板、代码模板）
- 规范文件（如品牌规范、API规范）
- 示例文件（如最佳实践、常见模式）

### Step 5: 验证技能

检查清单：
- [ ] `name` 字段是 kebab-case 且全局唯一？
- [ ] `description` 包含中文和英文关键触发词？
- [ ] 步骤之间有逻辑依赖关系时按顺序排列？
- [ ] 铁律是硬约束，不是建议？
- [ ] references/ 中的文件在 SKILL.md 中被引用？
- [ ] 审查清单每项都是 yes/no 判断？

## 核心铁律

1. **技能名称必须 kebab-case** — 不用中文、不用驼峰、不用下划线
2. **description 必须包含触发关键词** — 这是技能被激活的唯一入口
3. **不创建空壳技能** — 每个技能必须有实际可执行的步骤
4. **references 文件必须被引用** — 创建了就必须在 SKILL.md 中说明何时读取
5. **一个技能一个职责** — 不做瑞士军刀，职责模糊时拆分为多个技能

## 屯象OS 已有技能清单

维护当前项目的技能列表，避免重复创建：

| 技能 | 职责 | 位置 |
|------|------|------|
| tx-ui | 全终端UI智能设计与开发 | `.claude/skills/tx-ui/` |
| skill-creator | 技能构建（本技能） | `.claude/skills/skill-creator/` |
| docx | Word文档生成 | `.claude/skills/docx/` |
| frontend-design | 前端设计方案 | `.claude/skills/frontend-design/` |
| pptx | PPT演示文稿生成 | `.claude/skills/pptx/` |
| xlsx | Excel电子表格生成 | `.claude/skills/xlsx/` |
| product-self-knowledge | 产品自知识库 | `.claude/skills/product-self-knowledge/` |
| pdf | PDF文档生成 | `.claude/skills/pdf/` |
| pdf-reading | PDF文件解析 | `.claude/skills/pdf-reading/` |
| file-reading | 多格式文件解析 | `.claude/skills/file-reading/` |

> 创建新技能时，先检查此表避免职责冲突。
