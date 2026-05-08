/**
 * TXAgentAlert — Sprint 3 S3-04 单测
 *
 * 验证：
 *   - severity 视觉映射（class 注入）
 *   - TTS 行为映射（ttsMode × severity 真值表）
 *   - aria-live 由 severity 派生
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { TXAgentAlert } from '@tx/touch';

// jsdom 不实现 ResizeObserver；TXAgentAlert 用它跟踪高度，stub 即可
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = class {
  observe(): void {}
  disconnect(): void {}
  unobserve(): void {}
};

interface SpeechSynthesisStub {
  speak: ReturnType<typeof vi.fn>;
}

function installSpeechStub(): SpeechSynthesisStub {
  const stub: SpeechSynthesisStub = { speak: vi.fn() };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).speechSynthesis = stub;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).SpeechSynthesisUtterance = class {
    constructor(public text: string) {}
    lang = 'zh-CN';
    rate = 1;
    pitch = 1;
    volume = 1;
  };
  return stub;
}

describe('TXAgentAlert — severity 视觉映射', () => {
  afterEach(() => cleanup());

  it.each([
    ['critical', 'assertive'],
    ['warning', 'polite'],
    ['info', 'polite'],
  ] as const)('severity=%s aria-live=%s', (severity, expectedAriaLive) => {
    const { container } = render(
      <TXAgentAlert
        agentName="测试 Agent"
        message="测试消息"
        severity={severity}
        ttsMode="never"
      />,
    );
    const alert = container.querySelector('[role="alert"]');
    expect(alert).toBeTruthy();
    expect(alert?.getAttribute('aria-live')).toBe(expectedAriaLive);
  });
});

describe('TXAgentAlert — TTS 行为真值表 (S3-04 spec)', () => {
  let stub: SpeechSynthesisStub;
  beforeEach(() => {
    stub = installSpeechStub();
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('mode=auto + severity=critical → 触发 TTS（厨房关键事件铁律）', () => {
    render(
      <TXAgentAlert
        agentName="折扣守护"
        message="毛利破底线"
        severity="critical"
        ttsMode="auto"
      />,
    );
    expect(stub.speak).toHaveBeenCalledTimes(1);
  });

  it('mode=auto + severity=warning → 静默（避免噪音淹没）', () => {
    render(
      <TXAgentAlert
        agentName="库存"
        message="霸王蟹剩 8 只"
        severity="warning"
        ttsMode="auto"
      />,
    );
    expect(stub.speak).not.toHaveBeenCalled();
  });

  it('mode=auto + severity=info → 静默', () => {
    render(
      <TXAgentAlert
        agentName="会员"
        message="钻石会员 in"
        severity="info"
        ttsMode="auto"
      />,
    );
    expect(stub.speak).not.toHaveBeenCalled();
  });

  it('mode=always + severity=info → 触发 TTS（厨房关键工位无视觉关注）', () => {
    render(
      <TXAgentAlert
        agentName="会员"
        message="钻石会员 in"
        severity="info"
        ttsMode="always"
      />,
    );
    expect(stub.speak).toHaveBeenCalledTimes(1);
  });

  it('mode=never + severity=critical → 强制静默（噪音容忍度低的窗口）', () => {
    render(
      <TXAgentAlert
        agentName="折扣守护"
        message="毛利破底线"
        severity="critical"
        ttsMode="never"
      />,
    );
    expect(stub.speak).not.toHaveBeenCalled();
  });

  it('ttsText 覆盖默认 "{agentName}：{message}" 拼接', () => {
    render(
      <TXAgentAlert
        agentName="A"
        message="B"
        severity="critical"
        ttsMode="always"
        ttsText="自定义播报内容"
      />,
    );
    expect(stub.speak).toHaveBeenCalledTimes(1);
    const utterance = stub.speak.mock.calls[0][0] as { text: string };
    expect(utterance.text).toBe('自定义播报内容');
  });

  it('未设 ttsText 时拼接默认格式', () => {
    render(
      <TXAgentAlert
        agentName="折扣守护"
        message="毛利异常"
        severity="critical"
        ttsMode="auto"
      />,
    );
    expect(stub.speak).toHaveBeenCalledTimes(1);
    const utterance = stub.speak.mock.calls[0][0] as { text: string };
    expect(utterance.text).toBe('折扣守护：毛利异常');
  });
});
