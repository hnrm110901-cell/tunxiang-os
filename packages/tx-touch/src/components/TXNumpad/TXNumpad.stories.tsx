import type { Meta, StoryObj } from '@storybook/react';
import { useState } from 'react';
import { TXNumpad } from './TXNumpad';

const meta: Meta<typeof TXNumpad> = {
  title: 'TXTouch/TXNumpad',
  component: TXNumpad,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          '收银金额输入数字键盘。宪法 §3.2：12 个键全部 ≥ 72×72px (关键操作)。' +
          '禁用浏览器原生 input — 避免误触 + 适配商米 T2 触控延迟。',
      },
    },
  },
};
export default meta;
type Story = StoryObj<typeof TXNumpad>;

const InteractiveTemplate = (args: { allowDecimal?: boolean; maxValue?: number; label?: string }) => {
  const [value, setValue] = useState('');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: 16 }}>
      <div style={{ fontSize: 24, color: 'var(--tx-text-1)' }}>当前: {value || '0'}</div>
      <TXNumpad
        value={value}
        onChange={setValue}
        onConfirm={(v) => alert(`确认: ${v}`)}
        {...args}
      />
    </div>
  );
};

export const CashAmount: Story = {
  render: () => <InteractiveTemplate label="实收金额" allowDecimal />,
  parameters: {
    docs: {
      description: { story: '现金收银场景 — 允许小数（元/角/分）。' },
    },
  },
};

export const IntegerOnly: Story = {
  render: () => <InteractiveTemplate label="桌号" allowDecimal={false} />,
  parameters: {
    docs: {
      description: { story: '桌号输入 — 整数。' },
    },
  },
};

export const WithMaxValue: Story = {
  render: () => <InteractiveTemplate label="折扣率%" allowDecimal={false} maxValue={100} />,
  parameters: {
    docs: {
      description: { story: '折扣率 — 0-100 限制；超出会被守护。' },
    },
  },
};
