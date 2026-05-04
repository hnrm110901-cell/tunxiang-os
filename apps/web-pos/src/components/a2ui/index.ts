/**
 * A2UI 模块 barrel export
 *
 * A2UIRenderer: JSON→React 渲染引擎（Google A2UI v0.8 协议）
 * parseA2UIFromAgent: 从 Agent 返回数据中提取/构造 A2UI 声明
 */
export { A2UIRenderer, parseA2UIFromAgent } from './A2UIRenderer';
export type {
  A2UINode, A2UIDeclaration, A2UIComponentType,
  A2UIActionCallback, A2UIRenderContext,
} from './types';
