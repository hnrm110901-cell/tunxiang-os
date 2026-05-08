import type { Meta, StoryObj } from '@storybook/react';
import { TXAgentAlert } from './TXAgentAlert';

const meta: Meta<typeof TXAgentAlert> = {
  title: 'TXTouch/TXAgentAlert',
  component: TXAgentAlert,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          'Agent 顶部预警条。S3-04 升级支持 critical/warning/info 三级 + TTS 触发。' +
          'critical 默认 TTS 播报（厨房噪音环境关键事件），auto 模式下 warning/info 静默。' +
          'fixed 顶部，z-index 9999，role="alert"，aria-live 由 severity 决定。',
      },
    },
    // 故事覆盖整个屏幕顶部 fixed，给个 layout 让预览可见
    layout: 'fullscreen',
  },
  argTypes: {
    severity: { control: 'select', options: ['info', 'warning', 'critical'] },
    ttsMode: {
      control: 'select',
      options: ['auto', 'never', 'always'],
      description: 'auto = 仅 critical 播报；always = 任意 severity 播报；never = 静默',
    },
  },
  decorators: [
    (Story) => (
      <div style={{ minHeight: 200, position: 'relative', background: '#0D1117' }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof TXAgentAlert>;

export const Critical: Story = {
  args: {
    agentName: '折扣守护',
    message: '本单累计折扣率 35.2%，已突破毛利底线 — 是否复核？',
    severity: 'critical',
    actionLabel: '查看详情',
    onAction: () => alert('打开详情'),
    ttsMode: 'auto',
  },
  parameters: {
    docs: {
      description: { story: 'Critical 级 — 红色背景 + 脉冲动画 + auto 触发 TTS。' },
    },
  },
};

export const Warning: Story = {
  args: {
    agentName: '库存预警',
    message: '霸王蟹剩余 8 只，按当前消耗速度 30 分钟后沽清',
    severity: 'warning',
    actionLabel: '安排补货',
    onAction: () => {},
    ttsMode: 'auto',
  },
  parameters: {
    docs: {
      description: { story: 'Warning 级 — 橙色背景，auto 模式下静默不触发 TTS。' },
    },
  },
};

export const Info: Story = {
  args: {
    agentName: '会员洞察',
    message: '当前桌客户为「钻石」会员王总，距上次到店 16 天',
    severity: 'info',
    ttsMode: 'auto',
  },
  parameters: {
    docs: {
      description: { story: 'Info 级 — 蓝色背景，纯通知性。' },
    },
  },
};

export const CriticalSilenced: Story = {
  args: {
    ...Critical.args,
    ttsMode: 'never',
  },
  parameters: {
    docs: {
      description: { story: 'Critical 但强制静默（噪音容忍度低的工位，如包间外台）。' },
    },
  },
};

export const InfoForceSpeak: Story = {
  args: {
    ...Info.args,
    ttsMode: 'always',
  },
  parameters: {
    docs: {
      description: { story: 'Info 但强制播报（厨房关键工位无视觉关注）。' },
    },
  },
};
