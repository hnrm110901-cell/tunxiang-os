/**
 * mockSSE — Admin AI 对话 mock 流式生成器
 *
 * S4-01 阶段：tx-brain NLQ 后端尚未上线（S4-02 #289 才落），本文件提供
 * mock 流式生成器，让前端 chat 链路（输入 → 流式 token → A2UI Surface）跑通。
 *
 * 后续 S4-02 接通后，替换本文件实现为真实 SSE 客户端（fetch + ReadableStream）。
 * 协议契约保留不变 —— StreamEvent 联合类型。
 *
 * 协议契约：
 *   - { type: 'token', text }       // 流式文本片段
 *   - { type: 'surface', declaration }  // A2UI Surface 声明
 *   - { type: 'done' }              // 流正常结束
 *   - { type: 'error', message }    // 错误（流终止）
 *
 * Sprint 4 / S4-01 / Tier 2
 */
import type { A2UIDeclaration } from '../a2ui/types';

export type StreamEvent =
  | { type: 'token'; text: string }
  | { type: 'surface'; declaration: A2UIDeclaration }
  | { type: 'done' }
  | { type: 'error'; message: string };

interface MockOptions {
  /** 单个字符之间的延迟（毫秒） */
  tokenDelayMs?: number;
}

/**
 * mockNlqStream — 模拟 NLQ 流式回复
 *
 * 真接口签名应保持兼容：
 *   async function* nlqStream(question: string): AsyncGenerator<StreamEvent>
 */
export async function* mockNlqStream(
  question: string,
  options: MockOptions = {},
): AsyncGenerator<StreamEvent> {
  const delay = options.tokenDelayMs ?? 25;
  const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

  // 阶段 1：思考提示（typewriter）
  const intro = `正在分析您的问题"${question}"…\n\n`;
  for (const ch of intro) {
    await sleep(delay);
    yield { type: 'token', text: ch };
  }

  // 阶段 2：模拟自然语言回复
  const reply = '本周营收同比上升 12.3%，主推菜品「酸菜鱼」贡献 38%。\n';
  for (const ch of reply) {
    await sleep(delay);
    yield { type: 'token', text: ch };
  }

  // 阶段 3：返回一个示例 A2UI Surface（展示通路）
  await sleep(150);
  yield {
    type: 'surface',
    declaration: {
      version: '0.8',
      surface: {
        id: 'mock-surface-1',
        type: 'card',
        props: { title: '本周营收洞察', severity: 'info' },
        children: [
          {
            id: 'mock-text-1',
            type: 'text',
            props: { content: '同比 +12.3%', variant: 'heading' },
          },
          {
            id: 'mock-text-2',
            type: 'text',
            props: { content: '主推菜：酸菜鱼（贡献 38%）' },
          },
        ],
      },
      metadata: { agentId: 'mock-nlq', confidence: 0.85 },
    },
  };

  yield { type: 'done' };
}
